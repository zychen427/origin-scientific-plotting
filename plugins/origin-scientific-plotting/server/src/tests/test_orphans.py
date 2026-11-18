"""Tests for the spawned-Origin record, candidate listing and read-only CLI."""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest import mock

from origin_pro_mcp import daemon as daemon_module
from origin_pro_mcp import orphans


class SpawnRecordTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="origin-mcp-spawnlog-")
        self.path = os.path.join(self.directory, "spawned-pids.log")

    def test_jsonl_roundtrip_and_legacy_lines(self):
        daemon_module.record_spawned_pid(111, self.path, generation="g1",
                                         image="Origin64.exe")
        daemon_module.record_spawned_pid(222, self.path, generation="g2")
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("333\n")  # legacy plain-PID line
        records = daemon_module.read_spawn_records(self.path)
        self.assertEqual([r["pid"] for r in records], [111, 222, 333])
        self.assertEqual(records[0]["generation"], "g1")
        self.assertEqual(records[0]["image"], "Origin64.exe")
        self.assertFalse(records[0]["legacy"])
        self.assertTrue(records[2]["legacy"])
        self.assertEqual(daemon_module.read_spawned_pids(self.path),
                         [111, 222, 333])

    def test_record_is_bounded(self):
        with mock.patch.object(daemon_module, "_SPAWN_LOG_MAX_BYTES", 300), \
                mock.patch.object(daemon_module, "_SPAWN_LOG_MAX_ENTRIES", 5):
            for pid in range(100, 140):
                daemon_module.record_spawned_pid(pid, self.path)
            records = daemon_module.read_spawn_records(self.path)
        self.assertLessEqual(len(records), 6)  # bounded to the kept tail

    def test_concurrent_records_are_valid_json_lines(self):
        errors = []

        def worker(base):
            try:
                for offset in range(20):
                    daemon_module.record_spawned_pid(base + offset, self.path)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(1000 + 100 * i,))
                   for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        records = daemon_module.read_spawn_records(self.path)
        self.assertEqual(len(records), 120)

    def test_corrupt_lines_are_tolerated(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write('{"pid": 7, "generation": "g"}\nnot-a-record\n')
        records = daemon_module.read_spawn_records(self.path)
        self.assertEqual([r["pid"] for r in records], [7])


class CandidateListingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="origin-mcp-candidates-")
        self.path = os.path.join(self.directory, "spawned-pids.log")
        daemon_module.record_spawned_pid(111, self.path, generation="g1")
        daemon_module.record_spawned_pid(222, self.path, generation="g1")
        daemon_module.record_spawned_pid(333, self.path, generation="g0")
        daemon_module.record_spawned_pid(555, self.path, generation="g1")
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("444\n")  # legacy record

    def test_classification_never_claims_safety(self):
        report = daemon_module.candidate_orphan_origins(
            spawn_log_path=self.path,
            live_pids={111, 222, 444, 555},
            current_pids=[111],
            generation="g1",
            image_resolver=lambda pid: "notepad.exe" if pid == 555 else "Origin64.exe",
            create_time_resolver=lambda _pid: 1234.5,
        )
        by_pid = {item["pid"]: item for item in report["candidates"]}
        self.assertEqual(by_pid[111]["owner_evidence"], "current_daemon_session")
        self.assertEqual(by_pid[222]["owner_evidence"], "unverified_owner")
        self.assertEqual(by_pid[333]["owner_evidence"], "not_running")
        self.assertEqual(by_pid[555]["owner_evidence"], "not_origin_image")
        self.assertTrue(by_pid[444]["legacy_pid_only"])
        self.assertTrue(by_pid[444]["reasons"])
        for item in report["candidates"]:
            self.assertEqual(item["verdict"], "unverified")
            self.assertFalse(item["safe_to_close"])
        # Alive, not clearly owned by us and not clearly another image.
        self.assertEqual(report["orphan_origin_pids"], [222, 444])

    def test_dead_processes_are_reported_but_not_candidates(self):
        report = daemon_module.candidate_orphan_origins(
            spawn_log_path=self.path, live_pids=set(), current_pids=[],
            generation="g1", image_resolver=lambda _p: None,
            create_time_resolver=lambda _p: None,
        )
        self.assertEqual(report["orphan_origin_pids"], [])
        self.assertTrue(all(item["alive"] is False
                            for item in report["candidates"]))


class ReadOnlyCliTests(unittest.TestCase):
    def test_cli_json_is_read_only_listing(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-cli-")
        lockfile = os.path.join(directory, "daemon.json")
        with mock.patch.dict(os.environ,
                             {"ORIGIN_PRO_MCP_LOCKFILE": lockfile}):
            daemon_module.record_spawned_pid(777, generation="g1")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = orphans.main(["--json"])
            report = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIn("candidates", report)
        self.assertIn("notes", report)

    def test_cli_has_no_close_switch(self):
        with self.assertRaises(SystemExit):
            orphans.main(["--close"])


class StartupSweepPreservesRecordsTests(unittest.TestCase):
    def test_sweep_disabled_keeps_spawn_records(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-sweep-")
        lockfile = os.path.join(directory, "daemon.json")
        spawn_log = os.path.join(directory, "spawned-pids.log")
        daemon_module.record_spawned_pid(4242, spawn_log, generation="old")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORIGIN_PRO_MCP_SWEEP_ORPHANS", None)
            daemon = daemon_module.Daemon()
            self.assertTrue(daemon.start(
                origin_factory=lambda: None, registry={},
                lockfile_path=lockfile, monitor_tick=0.05,
                idle_exit_after=3600.0))
            try:
                self.assertTrue(os.path.exists(spawn_log))
                self.assertEqual(
                    daemon_module.read_spawned_pids(spawn_log), [4242])
            finally:
                daemon.stop()


if __name__ == "__main__":
    unittest.main()
