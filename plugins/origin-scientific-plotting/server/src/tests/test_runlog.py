"""Tests for the bounded, privacy-minimal runtime logging (runlog)."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from origin_pro_mcp import runlog
from origin_pro_mcp.daemon import Daemon
from origin_pro_mcp.shim import ShimClient


def _read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class EventLogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="origin-mcp-runlog-")

    def test_unknown_fields_are_dropped(self):
        log = runlog.EventLog(self.directory)
        log.event("tool_end", tool="create_graph", duration_ms=12.5,
                  secret="C:\\Users\\me\\token.txt", kwargs={"x": 1})
        records = _read_lines(log.path)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event"], "tool_end")
        self.assertEqual(record["tool"], "create_graph")
        self.assertEqual(record["duration_ms"], 12.5)
        self.assertNotIn("secret", record)
        self.assertNotIn("kwargs", record)
        self.assertNotIn("C:\\", json.dumps(record))

    def test_error_type_has_no_message(self):
        self.assertEqual(runlog.error_type(ValueError("C:\\secret\\path")),
                         "ValueError")

    def test_size_rotation(self):
        with mock.patch.object(runlog, "MAX_EVENT_BYTES", 300):
            log = runlog.EventLog(self.directory)
            for index in range(30):
                log.event("heartbeat", pool_used=index)
            self.assertTrue(os.path.exists(log.path))
            self.assertTrue(os.path.exists(log.path + ".1"))
            self.assertLessEqual(os.path.getsize(log.path), 300 + 200)

    def test_concurrent_writes_are_complete_lines(self):
        log = runlog.EventLog(self.directory)
        errors = []

        def worker(worker_id):
            try:
                for index in range(25):
                    log.event("tool_end", tool=f"t{worker_id}", ok=index % 2 == 0)
            except Exception as exc:  # pragma: no cover - thread safety failure
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        records = _read_lines(log.path)
        self.assertEqual(len(records), 8 * 25)  # every line parses, none lost

    def test_unwritable_directory_never_raises(self):
        blocker = os.path.join(self.directory, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        bad = os.path.join(blocker, "nested")
        log = runlog.EventLog(bad)  # constructor swallows the mkdir failure
        self.assertFalse(log.event("daemon_start"))


class StatusRecordTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="origin-mcp-status-")
        self.lockfile = os.path.join(self.directory, "daemon.json")

    def test_status_written_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORIGIN_PRO_MCP_STATUS_LOG", None)
            self.assertTrue(runlog.status(self.lockfile, "entry"))
            records = _read_lines(runlog.status_path(self.lockfile))
        self.assertEqual(records[-1]["event"], "entry")
        self.assertEqual(records[-1]["pid"], os.getpid())

    def test_status_opt_out(self):
        with mock.patch.dict(os.environ,
                             {"ORIGIN_PRO_MCP_STATUS_LOG": "off"}):
            self.assertFalse(runlog.status(self.lockfile, "entry"))
        self.assertFalse(os.path.exists(runlog.status_path(self.lockfile)))

    def test_status_drops_unknown_fields(self):
        runlog.status(self.lockfile, "init_error", error_type="OSError",
                      secret="token", path="C:\\x")
        record = _read_lines(runlog.status_path(self.lockfile))[-1]
        self.assertNotIn("secret", record)
        self.assertNotIn("path", record)

    def test_status_never_raises_on_unwritable_target(self):
        blocker = os.path.join(self.directory, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertFalse(runlog.status(os.path.join(blocker, "daemon.json"),
                                       "entry"))


class DaemonLoggingIntegrationTests(unittest.TestCase):
    def test_daemon_records_lifecycle_session_and_tool_events(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-logint-")
        lockfile = os.path.join(directory, "daemon.json")
        log_dir = os.path.join(directory, "logs")
        count = {"n": 0}

        def fake_read():
            count["n"] += 1
            return "ok"

        daemon = Daemon()
        daemon.configure_logging(log_dir)
        self.assertTrue(daemon.start(
            origin_factory=lambda: None, registry={"fake_read": fake_read},
            lockfile_path=lockfile, monitor_tick=0.05, idle_exit_after=3600.0))
        client = ShimClient(lockfile_path=lockfile, allow_spawn=False,
                            session_id="log-test", heartbeat_interval=0)
        try:
            self.assertEqual(client.call("fake_read", {}), "ok")
        finally:
            client.close()
            daemon.stop()

        events = _read_lines(os.path.join(log_dir, runlog.EVENT_FILE))
        names = [record["event"] for record in events]
        for expected in ("daemon_start", "connection_open", "session_mint",
                         "tool_start", "tool_end", "daemon_stop"):
            self.assertIn(expected, names, names)
        tool_end = [r for r in events if r["event"] == "tool_end"][-1]
        self.assertEqual(tool_end["tool"], "fake_read")
        self.assertTrue(tool_end["ok"])
        self.assertIn("session_cid", tool_end)
        self.assertNotIn("log-test", json.dumps(events))  # raw session id hidden

        status = _read_lines(runlog.status_path(lockfile))
        status_names = [record["event"] for record in status]
        self.assertIn("starting", status_names)
        self.assertIn("ready", status_names)
        self.assertIn("stopping", status_names)

    def test_status_file_exists_even_without_event_log(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-statusint-")
        lockfile = os.path.join(directory, "daemon.json")
        daemon = Daemon()
        self.assertTrue(daemon.start(
            origin_factory=lambda: None, registry={}, lockfile_path=lockfile,
            monitor_tick=0.05, idle_exit_after=3600.0))
        try:
            status = _read_lines(runlog.status_path(lockfile))
            self.assertIn("ready", [record["event"] for record in status])
        finally:
            daemon.stop()


if __name__ == "__main__":
    unittest.main()
