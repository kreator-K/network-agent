"""Idempotent operational runner for a proactive briefing; no scheduler daemon."""

import argparse
import json
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.orchestrator import NetworkOrchestrator
from config.settings import settings
from db.database import initialize_database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not settings.daily_briefing_enabled and not args.force:
        print("Briefing is disabled. Use --force for an explicit manual run.")
        return 0
    initialize_database(settings.database_path)
    result = NetworkOrchestrator().build_daily_briefing(
        database=settings.database_path, run_type="manual" if args.force else "scheduled",
        dry_run=args.dry_run or settings.briefing_dry_run,
    )
    print(json.dumps({key: result.get(key) for key in ("run_id", "status", "run_key", "dry_run")}, default=str))
    return 0 if result.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
