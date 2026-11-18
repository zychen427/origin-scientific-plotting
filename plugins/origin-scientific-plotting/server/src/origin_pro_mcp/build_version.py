"""Code identity for the shared shim/daemon runtime.

The same source tree and venv are used by more than one MCP client (for example
Codex and DeepSeek Harness). A long-lived daemon keeps the Python modules it
imported when it started, so an on-disk source update is invisible to it while a
freshly started shim runs the new code. That mismatch is silent: the shim's tool
schemas come from the new files while execution happens in the old daemon.

:data:`CODE_VERSION` gives every process a stable identity — the declared plugin
version plus a short SHA-256 digest of this package's own Python sources — which
the shim, the daemon, and diagnostics can compare. The digest is computed once
per process (``lru_cache``), so a process can never "become" a different version
at runtime.

Nothing here performs I/O beyond reading already-imported source files at first
use, and nothing imports the daemon (the daemon imports this module).
"""
from __future__ import annotations

import functools
import hashlib
import os

# Declared release of the plugin; keep in sync with plugin.json. The digest
# suffix distinguishes two checkouts of the same declared release.
PACKAGE_VERSION = "0.5.1"

# Bumped only when the shim<->daemon identity exchange changes shape. Old peers
# that do not understand the exchange are reported as "unknown", never as a
# match and never as a reason to replace anything.
#   v1: identify handshake (code identity + daemon pid/generation)
#   v2: + pre-send ping/pong liveness probe on the cached connection
PING_PROTOCOL = 2
IDENTITY_PROTOCOL = PING_PROTOCOL

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _source_files():
    for root, dirs, files in os.walk(_PACKAGE_DIR):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


@functools.lru_cache(maxsize=1)
def source_digest() -> str:
    """Short digest of every ``.py`` file in this package (paths + contents)."""
    digest = hashlib.sha256()
    for path in sorted(_source_files()):
        relative = os.path.relpath(path, _PACKAGE_DIR).replace(os.sep, "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        try:
            with open(path, "rb") as handle:
                digest.update(handle.read())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\x00")
    return digest.hexdigest()[:12]


@functools.lru_cache(maxsize=1)
def code_version() -> str:
    """``<declared version>+<12-hex digest>`` for this process's loaded code."""
    return f"{PACKAGE_VERSION}+{source_digest()}"


CODE_VERSION = code_version()


def short_version(version: str | None) -> str:
    """Compact label for a version string (full value when malformed)."""
    if not version:
        return "unknown"
    if "+" in version:
        base, _, digest = version.partition("+")
        return f"{base}+{digest[:6]}"
    return version


def compare_versions(local: str, remote: str | None, *,
                     remote_source: str = "handshake") -> dict:
    """Compare this process's identity with the peer's.

    Returns ``{"status": "match"|"mismatch"|"unknown", "local", "remote",
    "remote_source", "message"}``. An absent/unsupported remote identity is
    reported as ``unknown`` — callers must not treat it as a match nor as proof
    that an automatic replacement is safe.
    """
    if not remote:
        return {
            "status": "unknown",
            "local": local,
            "remote": None,
            "remote_source": remote_source,
            "message": (
                "Daemon code version could not be confirmed (older build or "
                "unsupported identity handshake). It may be running stale code; "
                "restart this MCP client (and any other connected client) to get "
                "a version-checked daemon. Do not rely on results until then."
            ),
        }
    if remote == local:
        return {
            "status": "match",
            "local": local,
            "remote": remote,
            "remote_source": remote_source,
            "message": "",
        }
    return {
        "status": "mismatch",
        "local": local,
        "remote": remote,
        "remote_source": remote_source,
        "message": (
            f"Version mismatch: this client runs {short_version(local)} but the "
            f"daemon runs {short_version(remote)}. Tool results may come from "
            "stale code. Finish/stop the work in progress, restart this MCP "
            "client, and confirm the other connected client is restarted too so "
            "only one code version serves the daemon."
        ),
    }
