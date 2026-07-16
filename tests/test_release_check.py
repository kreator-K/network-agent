"""Release gate and command-registry regression tests."""

import json
import subprocess
import sys
from pathlib import Path

from scripts.generate_command_reference import OUTPUT, registered_commands, render


ROOT = Path(__file__).resolve().parents[1]


def test_command_reference_matches_registered_handlers() -> None:
    commands = registered_commands()
    assert len(commands) == len(set(commands))
    assert len(commands) >= 60
    assert OUTPUT.read_text(encoding="utf-8") == render()


def test_release_check_passes_without_provider_writes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/release_check.py", "--skip-tests"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] is True
    assert all(item["passed"] for item in report["checks"])
