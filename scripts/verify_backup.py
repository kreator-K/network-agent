"""Verify a SQLite backup on a temporary copy without resuming writes."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.system_integrity_agent import SystemIntegrityAgent
from db.backup import restore_database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="network-agent-restore-") as directory:
        restored = restore_database(args.backup, Path(directory) / "restored.db")
        report = SystemIntegrityAgent().run_full_integrity_check(restored)
    print(json.dumps({"verified": report["overall_passed"], "summary": report["summary"]}))
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
