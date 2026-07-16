"""Run the no-provider-write release-candidate certification gate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.system_integrity_agent import SystemIntegrityAgent  # noqa: E402
from config.diagnostics import configuration_diagnostics  # noqa: E402
from config.settings import settings  # noqa: E402
from db.backup import backup_database  # noqa: E402
from db.database import initialize_database  # noqa: E402
from scripts.generate_command_reference import OUTPUT, registered_commands, render  # noqa: E402


REQUIRED_DOCS = (
    "docs/phase9_release_hardening.md", "docs/release_candidate_checklist.md",
    "docs/operator_runbook.md", "docs/backup_restore.md", "docs/incident_response.md",
    "docs/security_model.md", "docs/telegram_command_reference.md", "docs/system_architecture.md",
)


def _secret_scan() -> tuple[bool, str]:
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.py", "*.md", "*.toml", "*.json", "*.yml", "*.yaml"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    patterns = (
        r"-----BEGIN .*PRIVATE" + r" KEY-----",
        r"Bearer\s+[A-Za-z0-9._~-]{20,}",
        r"(?:access|refresh)_token\s*=\s*['\"][A-Za-z0-9._~-]{20,}['\"]",
    )
    for relative in tracked:
        text = (ROOT / relative).read_text(encoding="utf-8", errors="ignore")
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            return False, "credential-like material found in tracked safe files"
    return True, "no credential-like patterns found"


def _migration_and_integrity() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="network-agent-release-") as directory:
        copy = Path(directory) / "database.db"
        source = Path(settings.database_path).expanduser()
        if source.is_file():
            backup_database(source, copy)
        initialize_database(copy)
        result = SystemIntegrityAgent().run_full_integrity_check(copy)
        return bool(result["overall_passed"]), f"{len(result['checks'])} integrity checks; failed={sum(not check['passed'] for check in result['checks'])}"


def _run(command: list[str]) -> tuple[bool, str]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip().splitlines()
    return result.returncode == 0, output[-1] if output else "completed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest/mypy/Ruff; useful for quick local diagnostics.")
    args = parser.parse_args()
    results: list[tuple[str, bool, str]] = []
    config = configuration_diagnostics()
    results.append(("configuration", bool(config["valid"]), "valid" if config["valid"] else "invalid"))
    results.append(("publish switches", settings.linkedin_publish_mode == "disabled" and not settings.linkedin_real_publish_enabled, "disabled/false required"))
    results.append(("command reference", OUTPUT.is_file() and OUTPUT.read_text(encoding="utf-8") == render(), f"{len(registered_commands())} registered commands"))
    results.append(("documentation", all((ROOT / path).is_file() for path in REQUIRED_DOCS), "required runbooks present"))
    results.append(("secret scan", *_secret_scan()))
    results.append(("migration/integrity", *_migration_and_integrity()))
    if not args.skip_tests:
        for label, command in (
            ("pytest", [sys.executable, "-m", "pytest"]),
            ("mypy", [sys.executable, "-m", "mypy", "."]),
            ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ):
            results.append((label, *_run(command)))
    print(json.dumps({"passed": all(item[1] for item in results), "checks": [{"name": name, "passed": passed, "detail": detail} for name, passed, detail in results]}, indent=2))
    return 0 if all(item[1] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
