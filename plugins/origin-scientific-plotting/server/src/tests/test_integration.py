"""Integration tests for cross-version compatibility, pool limits and the
singleton spawn race. Kept behind ORIGIN_PRO_MCP_INTEGRATION=1 because they spawn
isolated daemon processes and (optionally) an old build from a backup.

Run explicitly:
    python -m unittest discover -s tests -p "test_integration.py" -v
with env ORIGIN_PRO_MCP_INTEGRATION=1.

They never touch the user's default lockfile, real daemon or Origin GUI: every
daemon uses a temporary lockfile and ORIGIN_PRO_MCP_FAKE_ORIGIN=1.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest

from origin_pro_mcp import daemon as daemon_module
from origin_pro_mcp import shim as shim_module
from origin_pro_mcp.shim import ShimClient

INTEGRATION = os.environ.get("ORIGIN_PRO_MCP_INTEGRATION") == "1"
OLD_BACKUP_SRC = os.environ.get("ORIGIN_PRO_MCP_OLD_BACKUP_SRC")


def _wait_for(path: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


def _spawn_daemon(src_root: str, lockfile: str,
                  extra_env: dict | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": src_root,
        "ORIGIN_PRO_MCP_LOCKFILE": lockfile,
        "ORIGIN_PRO_MCP_FAKE_ORIGIN": "1",
        "ORIGIN_PRO_MCP_STATUS_LOG": "off",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    env.update(extra_env or {})
    return subprocess.Popen(
        [sys.executable, "-m", "origin_pro_mcp.daemon"],
        env=env, cwd=src_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _stop_daemon(process: subprocess.Popen, lockfile: str) -> None:
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    for suffix in ("", ".lock"):
        try:
            os.remove(lockfile + suffix)
        except OSError:
            pass


@unittest.skipUnless(INTEGRATION, "set ORIGIN_PRO_MCP_INTEGRATION=1")
class OldDaemonCompatibilityTests(unittest.TestCase):
    def test_unknown_old_daemon_allows_reads_refuses_writes(self):
        if not OLD_BACKUP_SRC or not os.path.isdir(os.path.join(OLD_BACKUP_SRC, "origin_pro_mcp")):
            self.skipTest("set ORIGIN_PRO_MCP_OLD_BACKUP_SRC to the legacy server/src directory")
        directory = tempfile.mkdtemp(prefix="origin-mcp-oldint-")
        lockfile = os.path.join(directory, "daemon.json")
        process = _spawn_daemon(OLD_BACKUP_SRC, lockfile)
        client = ShimClient(lockfile_path=lockfile, allow_spawn=False,
                            session_id="integration-old", heartbeat_interval=0)
        try:
            self.assertTrue(_wait_for(lockfile), "old daemon did not start")
            # Old build has no identity protocol -> "unknown", read-only allowed.
            result = client.call("prepare_spectrum_peaks",
                                 {"mz": [1.0], "intensity": [2.0]})
            self.assertIsInstance(result, str)
            self.assertIn("[origin-mcp] Note:", result)
            # Side-effecting tools must be refused BEFORE any request is sent.
            with self.assertRaises(RuntimeError) as ctx:
                client.call("create_worksheet",
                            {"book_name": "X", "sheet_name": "Y"})
            self.assertIn("Refusing", str(ctx.exception))
        finally:
            client.close()
            _stop_daemon(process, lockfile)


@unittest.skipUnless(INTEGRATION, "set ORIGIN_PRO_MCP_INTEGRATION=1")
class PoolLimitTests(unittest.TestCase):
    def test_fourth_client_is_rejected(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-poolint-")
        lockfile = os.path.join(directory, "daemon.json")
        daemon = daemon_module.Daemon()
        self.assertTrue(daemon.start(
            origin_factory=lambda: None, registry={"noop": lambda: "ok"},
            max_size=3, lockfile_path=lockfile, monitor_tick=0.05,
            idle_exit_after=3600.0))
        clients = [ShimClient(lockfile_path=lockfile, allow_spawn=False,
                              session_id=f"pool-{index}", heartbeat_interval=0)
                   for index in range(4)]
        try:
            for client in clients[:3]:
                self.assertEqual(client.call("noop", {}), "ok")
            with self.assertRaises(RuntimeError) as ctx:
                clients[3].call("noop", {})
            message = str(ctx.exception).lower()
            self.assertTrue("pool" in message or "capacity" in message
                            or "session" in message, message)
        finally:
            for client in clients:
                client.close()
            daemon.stop()


@unittest.skipUnless(INTEGRATION, "set ORIGIN_PRO_MCP_INTEGRATION=1")
class SingletonSpawnRaceTests(unittest.TestCase):
    def test_racing_daemons_yield_one_survivor(self):
        directory = tempfile.mkdtemp(prefix="origin-mcp-race-")
        lockfile = os.path.join(directory, "daemon.json")
        processes = [_spawn_daemon(os.path.join(
            os.path.dirname(daemon_module.__file__), ".."), lockfile)
            for _ in range(2)]
        try:
            deadline = time.time() + 40
            while time.time() < deadline and not os.path.exists(lockfile):
                time.sleep(0.05)
            self.assertTrue(os.path.exists(lockfile), "no daemon wrote the lockfile")
            time.sleep(1.0)
            alive = [proc for proc in processes if proc.poll() is None]
            self.assertTrue(alive, "both daemons exited")
            self.assertEqual(len(alive), 1, "two daemons survived the singleton guard")
            data = daemon_module.read_lockfile(lockfile)
            # The surviving daemon is the real interpreter process, which may be
            # the venv-redirector child of the Popen pid: assert it is alive.
            self.assertTrue(daemon_module.default_is_alive(data["pid"]))
        finally:
            try:
                if os.path.exists(lockfile):
                    daemon_module.default_terminate_process(
                        daemon_module.read_lockfile(lockfile).get("pid"))
            except Exception:
                pass
            for process in processes:
                try:
                    process.terminate()
                except Exception:
                    pass
            for process in processes:
                try:
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
            for suffix in ("", ".lock"):
                try:
                    os.remove(lockfile + suffix)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
