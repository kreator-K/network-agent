"""Run provider-write-free deployment prechecks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.diagnostics import configuration_diagnostics
from config.settings import settings
from db.database import connect, initialize_database


def main() -> int:
    diagnostics = configuration_diagnostics()
    initialize_database(settings.database_path)
    with connect(settings.database_path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    report = {
        "configuration_valid": diagnostics["valid"],
        "publish_disabled": settings.linkedin_publish_mode == "disabled" and not settings.linkedin_real_publish_enabled,
        "database_integrity": integrity == "ok",
        "allowlist_configured": bool(settings.telegram_allowed_user_ids.strip()),
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if all(report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
