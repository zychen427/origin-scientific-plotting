"""Read-only listing of recorded Origin processes that MIGHT be leftovers.

This command never closes, kills or saves anything: there is intentionally no
``--close`` switch. A record is evidence only — another daemon, another
lockfile, or the user may own the process, and Windows recycles PIDs. Verify the
image name and creation time in the output before doing anything manually.

Usage:
    python -m origin_pro_mcp.orphans
    python -m origin_pro_mcp.orphans --json
    python -m origin_pro_mcp.orphans --lockfile C:\\path\\daemon.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import daemon as daemon_module


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_pro_mcp.orphans",
        description="List recorded Origin PIDs that MIGHT be leftovers "
                    "(read-only; never closes anything).",
    )
    parser.add_argument("--lockfile", default="",
                        help="daemon lockfile path (default: resolved unified path)")
    parser.add_argument("--json", action="store_true",
                        help="print the full evidence report as JSON")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.lockfile:
        os.environ["ORIGIN_PRO_MCP_LOCKFILE"] = args.lockfile
    report = daemon_module.candidate_orphan_origins()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0
    print(f"spawn log: {report['spawn_log']}")
    print(f"records: {report['records_total']}  "
          f"alive candidates: {len(report['orphan_origin_pids'])}")
    for item in report["candidates"]:
        print(f"- pid {item['pid']}: alive={item['alive']} "
              f"image={item['image']} owner={item['owner_evidence']} "
              f"verdict={item['verdict']} safe_to_close={item['safe_to_close']}")
        for reason in item["reasons"]:
            print(f"    reason: {reason}")
    for note in report["notes"]:
        print(f"note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
