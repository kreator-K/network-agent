"""Production interface retirement guards."""

from pathlib import Path

import pytest

from scripts.run_bot import main


ROOT = Path(__file__).resolve().parents[1]


def test_standard_bot_entrypoint_fails_closed() -> None:
    with pytest.raises(SystemExit, match="Telegram runtime retired"):
        main()


def test_active_telegram_systemd_unit_is_removed() -> None:
    assert not (ROOT / "deploy" / "network-agent-bot.service").exists()


def test_legacy_adapter_is_explicitly_named() -> None:
    legacy = ROOT / "scripts" / "run_legacy_telegram_bot.py"
    assert legacy.is_file()
    assert "migration testing" in legacy.read_text(encoding="utf-8")
