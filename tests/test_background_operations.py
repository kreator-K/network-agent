"""Bounded Telegram background-work safeguards."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from telegram_bot.handlers import BackgroundOperationBusy, _run_bounded_operation


class Context:
    def __init__(self) -> None:
        self.application = SimpleNamespace(bot_data={})


def test_background_operation_runs_off_request_path_and_clears_state() -> None:
    context = Context()
    assert asyncio.run(_run_bounded_operation(context, "scan", lambda: "done")) == "done"
    assert context.application.bot_data["background_operations"] == set()


def test_duplicate_background_operation_is_rejected() -> None:
    async def exercise() -> None:
        context = Context()
        first = asyncio.create_task(_run_bounded_operation(context, "scan", lambda: time.sleep(0.2)))
        while "scan" not in context.application.bot_data.get("background_operations", set()):
            await asyncio.sleep(0)
        with pytest.raises(BackgroundOperationBusy):
            await _run_bounded_operation(context, "scan", lambda: "again")
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

    asyncio.run(exercise())


def test_background_operation_timeout_clears_state(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Context()
    monkeypatch.setattr("telegram_bot.handlers.settings", SimpleNamespace(
        max_background_operations=2,
        background_operation_timeout_seconds=0.01,
    ))
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(_run_bounded_operation(context, "slow", lambda: time.sleep(1)))
    assert context.application.bot_data["background_operations"] == set()
