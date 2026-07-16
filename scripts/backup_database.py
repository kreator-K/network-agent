"""Create a timestamped SQLite backup without copying environment files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings
from db.backup import backup_database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = backup_database(settings.database_path, args.output)
    print(f"SQLite backup created: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
