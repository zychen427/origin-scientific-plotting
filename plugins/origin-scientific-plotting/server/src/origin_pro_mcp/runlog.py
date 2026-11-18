"""Bounded, privacy-minimal runtime logging for the shared Origin MCP daemon.

Two independent channels:

* **Event log** — opt-in via ``ORIGIN_PRO_MCP_LOG_DIR``. JSONL lines built from a
  fixed allow-list of fields: no tool arguments, response bodies, tokens, raw
  exception text, absolute paths or raw session ids; only short random
  correlation ids. Rotated by size (2 MiB, 3 backups).
* **Status record** — ON by default, opt-out via ``ORIGIN_PRO_MCP_STATUS_LOG=off``.
  A tiny bounded log next to the daemon lockfile recording process phases and
  exit/error *types* only, so a failed or losing daemon start leaves a trace even
  when the event log is disabled. Rotated once at 64 KiB.

All writes are best-effort: a logging failure must never block or crash the MCP.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

EVENT_FILE = "origin-mcp-events.jsonl"
STATUS_FILE = "daemon-status.jsonl"
CRASH_FILE = "daemon-crash.log"

MAX_EVENT_BYTES = 2 * 1024 * 1024
EVENT_BACKUPS = 3
MAX_STATUS_BYTES = 64 * 1024
STATUS_BACKUPS = 1

# Any field not listed here is dropped, so a caller cannot accidentally leak a
# path, an argument value, a response body or a credential into the log.
_ALLOWED_EVENT_FIELDS = frozenset({
    "phase", "pid", "generation", "tool", "duration_ms", "ok", "error_type",
    "conn_cid", "session_cid", "pool_max", "pool_used", "auth_failures",
    "code_version", "reason",
})
_ALLOWED_STATUS_FIELDS = frozenset({
    "pid", "phase", "error_type", "reason", "code_version", "exit_code",
})

_write_lock = threading.Lock()


def correlation_id(prefix: str) -> str:
    """Short random id usable in logs instead of a session/connection id."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def error_type(exc: BaseException) -> str:
    """Exception class name only — never the message (may contain paths)."""
    try:
        return type(exc).__name__[:64]
    except Exception:  # pragma: no cover - defensive
        return "Exception"


def _rotate(path: str, backups: int) -> None:
    for index in range(backups, 1, -1):
        source = f"{path}.{index - 1}"
        if os.path.exists(source):
            try:
                os.replace(source, f"{path}.{index}")
            except OSError:
                pass
    try:
        os.replace(path, f"{path}.1")
    except OSError:
        pass


def _append(path: str, line: str, max_bytes: int, backups: int) -> bool:
    data = line.rstrip("\n") + "\n"
    try:
        with _write_lock:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size + len(data.encode("utf-8")) > max_bytes:
                _rotate(path, backups)
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
    except OSError:
        return False
    return True


class EventLog:
    """Opt-in structured event log (JSONL, size-rotated, allow-listed fields)."""

    def __init__(self, directory: str):
        self.directory = directory
        self.path = os.path.join(directory, EVENT_FILE)
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass

    def event(self, name: str, level: str = "info", **fields) -> bool:
        record = {"ts": _timestamp(), "level": level, "event": name}
        for key, value in fields.items():
            if key in _ALLOWED_EVENT_FIELDS and value is not None:
                record[key] = value
        return _append(self.path, json.dumps(record, ensure_ascii=False),
                       MAX_EVENT_BYTES, EVENT_BACKUPS)


class NullEventLog:
    """No-op logger used when ORIGIN_PRO_MCP_LOG_DIR is unset."""

    def event(self, *_args, **_kwargs) -> bool:
        return False


def make_event_log(directory: str | None):
    if not directory:
        return NullEventLog()
    try:
        return EventLog(directory)
    except Exception:  # pragma: no cover - never break the daemon for logging
        return NullEventLog()


def status_enabled() -> bool:
    raw = os.environ.get("ORIGIN_PRO_MCP_STATUS_LOG")
    if raw is None:
        return True
    return raw.strip().lower() not in ("off", "0", "false", "no")


def status_path(lockfile_path: str) -> str:
    directory = os.path.dirname(os.path.abspath(lockfile_path))
    return os.path.join(directory, STATUS_FILE)


def status(lockfile_path: str, event: str, **fields) -> bool:
    """Record one bounded phase/exit line next to the daemon lockfile."""
    if not status_enabled():
        return False
    try:
        os.makedirs(os.path.dirname(os.path.abspath(lockfile_path)),
                    exist_ok=True)
    except OSError:
        pass
    record = {"ts": _timestamp(), "event": event, "pid": os.getpid()}
    for key, value in fields.items():
        if key in _ALLOWED_STATUS_FIELDS and value is not None:
            record[key] = value
    return _append(status_path(lockfile_path),
                   json.dumps(record, ensure_ascii=False),
                   MAX_STATUS_BYTES, STATUS_BACKUPS)


def enable_fault_handler(lockfile_path: str) -> bool:
    """Opt-in faulthandler dump written next to the lockfile.

    NOTE: a fatal traceback contains absolute source paths. Only enable this when
    that is acceptable (``ORIGIN_PRO_MCP_FAULTHANDLER=1``); the file is bounded
    only by the OS.
    """
    import faulthandler

    try:
        directory = os.path.dirname(os.path.abspath(lockfile_path))
        os.makedirs(directory, exist_ok=True)
        handle = open(os.path.join(directory, CRASH_FILE), "a",
                      encoding="utf-8")
        faulthandler.enable(file=handle)
        return True
    except Exception:  # pragma: no cover - best effort
        return False
