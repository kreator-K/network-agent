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


def deployment_report(
    *,
    configuration_valid: bool,
    database_integrity: bool,
    python_version: tuple[int, int],
) -> dict[str, bool | str]:
    """Build a secret-free, deterministic deployment readiness report."""
    return {
        "configuration_valid": configuration_valid,
        "publish_disabled": settings.linkedin_publish_mode == "disabled" and not settings.linkedin_real_publish_enabled,
        "database_integrity": database_integrity,
        "python_311": python_version == (3, 11),
        "web_api_auth_configured": len(settings.web_api_token) >= 32,
        "persistence_acknowledged": settings.deployment_persistence_acknowledged,
        "active_interface": "web_ui",
    }


def main() -> int:
    diagnostics = configuration_diagnostics()
    initialize_database(settings.database_path)
    with connect(settings.database_path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    report = deployment_report(
        configuration_valid=bool(diagnostics["valid"]),
        database_integrity=integrity == "ok",
        python_version=sys.version_info[:2],
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if all(value is True for key, value in report.items() if key != "active_interface") else 1


if __name__ == "__main__":
    raise SystemExit(main())
