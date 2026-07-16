"""Create a timestamped SQLite backup without copying environment files."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings
from db.backup import backup_database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--retention", type=int, default=settings.backup_retention_count)
    args = parser.parse_args()
    if args.output:
        output = Path(args.output)
    else:
        output_dir = Path(settings.backup_path).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"network-agent-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
    destination = backup_database(settings.database_path, output)
    destination.chmod(0o600)
    candidates = sorted(destination.parent.glob("network-agent-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old_backup in candidates[max(1, args.retention):]:
        old_backup.unlink()
    print(f"SQLite backup created: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
