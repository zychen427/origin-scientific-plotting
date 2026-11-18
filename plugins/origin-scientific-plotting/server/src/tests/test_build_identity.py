"""Tests for the cross-process code identity, lockfile schema and run budget.

Run from ``server/src``:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from origin_pro_mcp import transport
from origin_pro_mcp.build_version import (
    CODE_VERSION,
    PACKAGE_VERSION,
    IDENTITY_PROTOCOL,
    compare_versions,
    short_version,
    source_digest,
)
from origin_pro_mcp.daemon import Daemon, read_lockfile, write_lockfile
from origin_pro_mcp.shim import ShimClient


class CodeVersionTests(unittest.TestCase):
    def test_identity_shape(self):
        self.assertRegex(source_digest(), r"^[0-9a-f]{12}$")
        self.assertEqual(CODE_VERSION, PACKAGE_VERSION + "+" + source_digest())

    def test_identity_is_stable_within_a_process(self):
        self.assertEqual(CODE_VERSION, CODE_VERSION)
        self.assertEqual(source_digest(), source_digest())

    def test_compare_versions(self):
        match = compare_versions("a+bcd123", "a+bcd123")
        self.assertEqual(match["status"], "match")
        self.assertEqual(match["message"], "")

        mismatch = compare_versions("a+bcd123", "a+ffffff")
        self.assertEqual(mismatch["status"], "mismatch")
        self.assertIn("Version mismatch", mismatch["message"])
        self.assertIn("restart", mismatch["message"].lower())

        unknown = compare_versions("a+bcd123", None)
        self.assertEqual(unknown["status"], "unknown")
        self.assertIn("could not be confirmed", unknown["message"])
        # Unknown is never silently promoted to a match.
        self.assertNotEqual(unknown["status"], "match")

    def test_short_version(self):
        self.assertEqual(short_version("0.3.0-dev4+abcdef123456"),
                         "0.3.0-dev4+abcdef")
        self.assertEqual(short_version(None), "unknown")
        self.assertEqual(short_version("weird"), "weird")


class LockfileTests(unittest.TestCase):
    def test_roundtrip_with_identity(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-lock-")
        path = os.path.join(directory, "daemon.json")
        started = time.time()
        write_lockfile(path, 1234, "token-value", os.getpid(), [42],
                       code_version=CODE_VERSION,
                       started_at=started,
                       protocol=IDENTITY_PROTOCOL)
        data = read_lockfile(path)
        self.assertEqual(data["port"], 1234)
        self.assertEqual(data["code_version"], CODE_VERSION)
        self.assertEqual(data["identity_protocol"], IDENTITY_PROTOCOL)
        self.assertAlmostEqual(data["started_at"], started, places=3)
        self.assertEqual(data["child_pids"], [42])
        # The token is part of the discovery contract (never in diagnostics).
        self.assertEqual(data["token"], "token-value")

    def test_legacy_lockfile_still_readable(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-lock-")
        path = os.path.join(directory, "daemon.json")
        write_lockfile(path, 1, "tok", os.getpid(), [])
        data = read_lockfile(path)
        self.assertNotIn("code_version", data)
        self.assertEqual(data["port"], 1)


class TransportHelloTests(unittest.TestCase):
    def test_hello_carries_client_identity(self):
        server = transport.TcpServer("secret-token")
        accepted = {}

        def accept_once():
            conn = server.accept()
            accepted["conn"] = conn

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        conn = transport.connect(server.host, server.port, "secret-token",
                                 session_id="s-1",
                                 metadata={"code_version": "v1+abc123",
                                           "identity_protocol": 7})
        thread.join(timeout=5)
        self.assertIsNotNone(accepted.get("conn"))
        accepted_conn = accepted["conn"]
        self.assertEqual(accepted_conn.session_id, "s-1")
        self.assertEqual(accepted_conn.client_code_version, "v1+abc123")
        self.assertEqual(accepted_conn.client_identity_protocol, 7)
        conn.close()
        accepted_conn.close()
        server.close()

    def test_hello_without_metadata_is_accepted(self):
        server = transport.TcpServer("tok2")
        accepted = {}

        def accept_once():
            accepted["conn"] = server.accept()

        threading.Thread(target=accept_once, daemon=True).start()
        conn = transport.connect(server.host, server.port, "tok2")
        deadline = time.time() + 5
        while "conn" not in accepted and time.time() < deadline:
            time.sleep(0.02)
        self.assertIsNotNone(accepted.get("conn"))
        self.assertIsNone(accepted["conn"].client_code_version)
        conn.close()
        accepted["conn"].close()
        server.close()


class DaemonIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="origin-mcp-daemon-")
        self.lockfile = os.path.join(self.directory, "daemon.json")
        self.daemon = Daemon()
        started = self.daemon.start(
            origin_factory=lambda: None, registry={},
            lockfile_path=self.lockfile, monitor_tick=0.05,
            idle_exit_after=3600.0,
        )
        self.assertTrue(started, "daemon failed to acquire its singleton")

    def tearDown(self):
        try:
            self.daemon.stop()
        except Exception:
            pass

    def test_lockfile_records_running_identity(self):
        data = read_lockfile(self.lockfile)
        self.assertEqual(data["code_version"], CODE_VERSION)
        self.assertEqual(data["identity_protocol"], IDENTITY_PROTOCOL)
        self.assertIn("started_at", data)

    def test_status_snapshot(self):
        snapshot = self.daemon.status_snapshot()
        self.assertTrue(snapshot["active"])
        self.assertEqual(snapshot["code_version"], CODE_VERSION)
        self.assertEqual(snapshot["daemon_pid"], os.getpid())
        self.assertEqual(snapshot["pool"]["session_ids"], [])
        self.assertIsNotNone(snapshot["uptime_sec"])

    def test_identify_frame_returns_identity(self):
        conn = transport.connect(self.daemon.host, self.daemon.port,
                                 self.daemon.token, session_id="identify-test",
                                 metadata={"code_version": CODE_VERSION,
                                           "identity_protocol": IDENTITY_PROTOCOL})
        conn.settimeout(5)
        conn.send_frame({"type": "identify"})
        identity = None
        deadline = time.time() + 5
        while time.time() < deadline:
            frame = conn.recv_frame()
            if frame is not None and frame.get("type") == "identity":
                identity = frame
                break
        conn.close()
        self.assertIsNotNone(identity)
        self.assertEqual(identity["code_version"], CODE_VERSION)
        self.assertEqual(identity["identity_protocol"], IDENTITY_PROTOCOL)
        self.assertEqual(identity["daemon_pid"], os.getpid())
        self.assertNotIn("token", identity)


class ToolSurfaceTests(unittest.TestCase):
    """Guard the model-facing surface: 68 tools, descriptions within budget."""

    MAX_TOOL_BYTES = 78_000
    MAX_DESCRIPTION_BYTES = 1_200

    @classmethod
    def setUpClass(cls):
        from origin_pro_mcp import server  # noqa: F401 - registers tools
        from origin_pro_mcp.app import mcp

        cls.tools = dict(mcp._tool_manager._tools)

    def test_tool_count_and_unique_names(self):
        self.assertEqual(len(self.tools), 68)

    def test_descriptions_non_empty_and_bounded(self):
        for name, tool in self.tools.items():
            description = tool.description or ""
            self.assertTrue(description.strip(), f"{name} has no description")
            self.assertLessEqual(
                len(description), self.MAX_DESCRIPTION_BYTES,
                f"{name} description is {len(description)} bytes")

    @staticmethod
    def _wire_json(tool) -> str:
        """Serialize exactly like FastMCP's tools/list MCPTool."""
        from mcp.types import Tool as MCPTool

        mcp_tool = MCPTool(
            name=tool.name,
            title=tool.title,
            description=tool.description,
            inputSchema=tool.parameters,
            outputSchema=tool.output_schema,
            annotations=tool.annotations,
            icons=tool.icons,
            _meta=tool.meta,
        )
        return mcp_tool.model_dump_json(by_alias=True, exclude_none=True)

    def test_total_tool_bytes_budget(self):
        total = sum(len(self._wire_json(tool)) for tool in self.tools.values())
        self.assertLessEqual(
            total, self.MAX_TOOL_BYTES,
            f"tools/list payload is {total} bytes (budget {self.MAX_TOOL_BYTES})")


class _FakeWatchdog:
    def __init__(self):
        self.arms = []
        self.disarms = []

    def arm(self, session_id, pid, deadline, reason="reap", callback=None):
        self.arms.append((session_id, pid, deadline, reason))

    def disarm(self, session_id, reason="reap"):
        self.disarms.append((session_id, reason))


class _FakeSession:
    pid = None

    def __init__(self):
        self.submitted = []

    def submit(self, request_id, name, kwargs, reply_fn):
        self.submitted.append((request_id, name, kwargs))


class _FakeConn:
    def __init__(self):
        self.frames = []

    def send_frame(self, frame):
        self.frames.append(frame)


class DispatchTimeoutTests(unittest.TestCase):
    """Regression: the hard 'dispatch' deadline must actually be armed."""

    def _daemon(self, timeout=30.0, grace=90.0):
        daemon = Daemon()
        daemon._watchdog = _FakeWatchdog()
        daemon._dispatch_timeout = timeout
        daemon._dispatch_kill_grace = grace
        daemon._clock = lambda: 1000.0
        return daemon

    def test_two_phase_arms_both_deadlines(self):
        daemon = self._daemon(timeout=30.0, grace=90.0)
        session = _FakeSession()
        daemon._submit_with_dispatch_timeout(
            session, "sid", "rid", "some_tool", {}, _FakeConn())
        reasons = {arm[3]: arm for arm in daemon._watchdog.arms}
        self.assertIn("dispatch-warn", reasons)
        self.assertIn("dispatch", reasons)
        self.assertEqual(reasons["dispatch-warn"][2], 1030.0)
        self.assertEqual(reasons["dispatch"][2], 1120.0)
        self.assertEqual(len(session.submitted), 1)

    def test_grace_zero_arms_single_phase(self):
        daemon = self._daemon(timeout=30.0, grace=0.0)
        daemon._submit_with_dispatch_timeout(
            _FakeSession(), "sid", "rid", "some_tool", {}, _FakeConn())
        reasons = [arm[3] for arm in daemon._watchdog.arms]
        self.assertEqual(reasons, ["dispatch"])
        self.assertEqual(daemon._watchdog.arms[0][2], 1030.0)

    def test_disabled_timeout_submits_without_arming(self):
        daemon = self._daemon(timeout=0.0, grace=90.0)
        session = _FakeSession()
        daemon._submit_with_dispatch_timeout(
            session, "sid", "rid", "some_tool", {}, _FakeConn())
        self.assertEqual(daemon._watchdog.arms, [])
        self.assertEqual(len(session.submitted), 1)

    def test_run_labtalk_override_extends_dispatch_budget(self):
        daemon = self._daemon(timeout=30.0, grace=90.0)
        daemon._submit_with_dispatch_timeout(
            _FakeSession(), "sid", "rid", "run_labtalk",
            {"timeout": 600}, _FakeConn())
        reasons = {arm[3]: arm for arm in daemon._watchdog.arms}
        self.assertEqual(reasons["dispatch-warn"][2], 1600.0)
        self.assertEqual(reasons["dispatch"][2], 1690.0)


class _ScriptedConn:
    """Minimal connection double for ShimClient._exchange."""

    def __init__(self):
        self.timeouts = []
        self.frames = []
        self._response = None

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def send_frame(self, frame):
        self.frames.append(frame)
        self._response = {"type": "response",
                          "request_id": frame.get("request_id"),
                          "ok": True, "result": "done"}

    def recv_frame(self):
        return dict(self._response)


class ShimCallBudgetTests(unittest.TestCase):
    def test_run_labtalk_widens_socket_budget(self):
        from origin_pro_mcp.shim import ShimClient

        client = ShimClient(call_timeout=195.0)
        conn = _ScriptedConn()
        result = client._exchange(conn, "run_labtalk", {"timeout": 600})
        self.assertEqual(result, "done")
        # widened for the call, then restored to the normal budget
        self.assertGreaterEqual(max(conn.timeouts), 630.0)
        self.assertEqual(conn.timeouts[-1], 195.0)

    def test_regular_tool_keeps_default_budget(self):
        from origin_pro_mcp.shim import ShimClient

        client = ShimClient(call_timeout=195.0)
        conn = _ScriptedConn()
        client._exchange(conn, "create_graph", {})
        self.assertEqual(set(conn.timeouts), {195.0})


class ShimVersionNoticeTests(unittest.TestCase):
    def test_mismatch_notice_is_appended_once(self):
        from origin_pro_mcp.shim import ShimClient

        client = ShimClient(call_timeout=195.0)
        client._version_issue = "Version mismatch: test-notice"
        conn = _ScriptedConn()
        first = client._exchange(conn, "get_worksheet_data", {})
        self.assertIn("[origin-mcp] Note: Version mismatch: test-notice", first)
        second = client._exchange(conn, "get_worksheet_data", {})
        self.assertNotIn("test-notice", second)

    def test_clean_version_has_no_notice(self):
        from origin_pro_mcp.shim import ShimClient

        client = ShimClient(call_timeout=195.0)
        client._version_issue = None
        conn = _ScriptedConn()
        self.assertEqual(client._exchange(conn, "create_graph", {}), "done")


class LockfileResolutionTests(unittest.TestCase):
    def test_explicit_argument_wins(self):
        from origin_pro_mcp.shim import resolve_lockfile_path

        with mock.patch.dict(os.environ,
                             {"ORIGIN_PRO_MCP_LOCKFILE": r"C:\env\lock.json"}):
            resolved = resolve_lockfile_path("relative/lock.json")
        self.assertTrue(os.path.isabs(resolved))
        self.assertTrue(resolved.endswith("lock.json"))
        self.assertNotIn("env", resolved.replace("\\", "/").split("/")[-2])

    def test_env_used_when_no_explicit(self):
        from origin_pro_mcp.shim import resolve_lockfile_path

        directory = tempfile.mkdtemp(prefix="origin-mcp-lockres-")
        env_path = os.path.join(directory, "env-lock.json")
        with mock.patch.dict(os.environ,
                             {"ORIGIN_PRO_MCP_LOCKFILE": env_path}):
            self.assertEqual(resolve_lockfile_path(None), os.path.abspath(env_path))

    def test_empty_env_falls_back_to_default(self):
        from origin_pro_mcp import daemon as daemon_module
        from origin_pro_mcp.shim import resolve_lockfile_path

        with mock.patch.dict(os.environ,
                             {"ORIGIN_PRO_MCP_LOCKFILE": "   "}):
            self.assertEqual(resolve_lockfile_path(None),
                             daemon_module.default_lockfile_path())


class TimeoutBudgetTests(unittest.TestCase):
    def test_daemon_defaults_fit_inside_client_budget(self):
        from origin_pro_mcp import daemon as daemon_module
        from origin_pro_mcp.shim import _reconcile_call_timeout

        self.assertEqual(daemon_module.DISPATCH_TIMEOUT_DEFAULT, 75.0)
        self.assertEqual(daemon_module.DISPATCH_KILL_GRACE_DEFAULT, 75.0)
        keys = ("ORIGIN_PRO_MCP_DISPATCH_TIMEOUT",
                "ORIGIN_PRO_MCP_DISPATCH_KILL_GRACE")
        saved = {key: os.environ.pop(key, None) for key in keys}
        try:
            # Client budgets are 180 s (Codex tool_timeout_sec / DSH
            # toolCallTimeoutMs); the shim socket budget must stay below that.
            self.assertLessEqual(_reconcile_call_timeout(60.0), 180.0)
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value


class PingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="origin-mcp-ping-")
        self.lockfile = os.path.join(self.directory, "daemon.json")
        self.daemon = Daemon()
        self.assertTrue(self.daemon.start(
            origin_factory=lambda: None, registry={},
            lockfile_path=self.lockfile, monitor_tick=0.05,
            idle_exit_after=3600.0))

    def tearDown(self):
        try:
            self.daemon.stop()
        except Exception:
            pass

    def test_ping_returns_pong_without_dispatch(self):
        conn = transport.connect(self.daemon.host, self.daemon.port,
                                 self.daemon.token, session_id="ping-test")
        conn.settimeout(5)
        conn.send_frame({"type": "ping", "ts": time.time()})
        pong = None
        deadline = time.time() + 5
        while time.time() < deadline:
            frame = conn.recv_frame()
            if frame is not None and frame.get("type") == "pong":
                pong = frame
                break
        conn.close()
        self.assertIsNotNone(pong)
        # A ping must not create a session/Origin.
        self.assertEqual(self.daemon.status_snapshot()["pool"]["session_ids"], [])
        self.assertEqual(self.daemon.status_snapshot()["calls_total"], 0)


class StaleConnectionRetryTests(unittest.TestCase):
    """The pre-send ping makes one retry provably safe (nothing was sent)."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="origin-mcp-stale-")
        self.lockfile = os.path.join(self.directory, "daemon.json")
        self.count = 0
        outer = self

        def fake_write():
            outer.count += 1
            return f"ok-{outer.count}"

        self.daemon = Daemon()
        self.assertTrue(self.daemon.start(
            origin_factory=lambda: None, registry={"fake_write": fake_write},
            lockfile_path=self.lockfile, monitor_tick=0.05,
            idle_exit_after=3600.0))
        self.client = ShimClient(
            lockfile_path=self.lockfile, allow_spawn=False,
            session_id="stale-test", heartbeat_interval=0,
        )

    def tearDown(self):
        try:
            self.client.close()
        finally:
            self.daemon.stop()

    def test_stale_cached_link_retries_once_without_duplicate(self):
        self.assertEqual(self.client.call("fake_write", {}), "ok-1")
        self.client._conn.close()  # stale socket, but the cache is not reset
        self.assertEqual(self.client.call("fake_write", {}), "ok-2")
        self.assertEqual(self.count, 2)  # no duplicate dispatch

    def test_no_retry_when_ping_is_unsupported(self):
        self.assertEqual(self.client.call("fake_write", {}), "ok-1")
        self.client._daemon_identity_protocol = None  # simulate an old daemon
        self.client._conn.close()
        with self.assertRaises(RuntimeError) as ctx:
            self.client.call("fake_write", {})
        self.assertIn("outcome is unknown", str(ctx.exception))
        self.assertEqual(self.count, 1)  # never replayed


class _FakeDialogWatchdog:
    def __init__(self, pid, callback):
        self.pid = pid
        self.callback = callback
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class SessionPidRefreshTests(unittest.TestCase):
    """A COM relaunch must refresh Session.pid and rebuild the dialog watchdog."""

    def _session(self, factory, get_pid, dogs):
        from origin_pro_mcp.daemon import Session

        def watchdog_factory(pid, callback):
            watchdog = _FakeDialogWatchdog(pid, callback)
            dogs.append(watchdog)
            return watchdog

        return Session("session-test", factory, registry={},
                       get_pid=get_pid,
                       dialog_watchdog_factory=watchdog_factory)

    def test_relaunch_refreshes_pid_and_restarts_watchdog(self):
        pids = iter([111, 222])
        dogs = []
        session = self._session(lambda: object(), lambda _i: next(pids, None),
                                dogs)
        session.start(ready_timeout=5)
        try:
            self.assertEqual(session.pid, 111)
            self.assertEqual(dogs[-1].pid, 111)
            self.assertEqual(dogs[-1].started, 1)
            managed = session._managed_factory()
            managed()  # simulate the dead-proxy relaunch path
            self.assertEqual(session.pid, 222)
            self.assertEqual(dogs[0].stopped, 1)
            self.assertEqual(dogs[-1].pid, 222)
            self.assertIsNot(dogs[0], dogs[-1])
        finally:
            session.stop()

    def test_failed_relaunch_clears_pid_and_stops_watchdog(self):
        calls = {"n": 0}

        def factory():
            calls["n"] += 1
            if calls["n"] == 1:
                return object()
            raise RuntimeError("relaunch failed")

        dogs = []
        session = self._session(factory, lambda _i: 333, dogs)
        session.start(ready_timeout=5)
        try:
            self.assertEqual(session.pid, 333)
            managed = session._managed_factory()
            with self.assertRaises(RuntimeError):
                managed()
            self.assertIsNone(session.pid)  # never keeps the stale pid
            self.assertEqual(dogs[0].stopped, 1)
        finally:
            session.stop()

    def test_unknown_pid_starts_no_watchdog(self):
        dogs = []
        session = self._session(lambda: object(), lambda _i: None, dogs)
        session.start(ready_timeout=5)
        try:
            self.assertIsNone(session.pid)
            self.assertEqual(dogs, [])  # attached/user Origin: never dialog-swept
        finally:
            session.stop()


class VersionGateTests(unittest.TestCase):
    """An unverified daemon must not run side-effecting tools."""

    def _client(self, issue="Version mismatch: test", status="mismatch"):
        client = ShimClient(call_timeout=195.0)
        client._daemon_identity = {"status": status}
        client._version_issue = issue
        return client

    def test_side_effecting_tool_refused_before_send(self):
        conn = _ScriptedConn()
        client = self._client()
        with self.assertRaises(RuntimeError) as ctx:
            client._exchange(conn, "create_worksheet", {})
        self.assertIn("Refusing", str(ctx.exception))
        self.assertEqual(conn.frames, [])  # provably nothing was sent

    def test_read_only_tool_allowed_with_warning(self):
        conn = _ScriptedConn()
        client = self._client()
        result = client._exchange(conn, "get_worksheet_data", {})
        self.assertEqual(len(conn.frames), 1)
        self.assertIn("[origin-mcp] Note:", result)

    def test_matching_version_has_no_gate(self):
        conn = _ScriptedConn()
        client = ShimClient(call_timeout=195.0)
        client._version_issue = None
        client._daemon_identity = {"status": "match"}
        self.assertEqual(client._exchange(conn, "create_worksheet", {}), "done")


if __name__ == "__main__":
    unittest.main()
