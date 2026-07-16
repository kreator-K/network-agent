"""LinkedIn startup reconciliation never invokes a provider write."""

import asyncio
from typing import Any, cast

import telegram_bot.bot as bot_module


class FakeRuntime:
    def __init__(self) -> None:
        self.client = object()

    async def start(self) -> None:
        return None


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reconcile_linkedin_publish_requests(self, **kwargs: Any) -> dict[str, int]:
        self.calls.append(kwargs)
        return {"reconciled": 2, "provider_calls": 0}


class FakeApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, Any] = {
            "orchestrator": FakeOrchestrator(),
            "database_path": "test.db",
        }


def test_post_init_reconciles_without_provider_call(monkeypatch: Any) -> None:
    application = FakeApplication()
    monkeypatch.setattr(bot_module, "GoogleCalendarMCPRuntime", FakeRuntime)
    monkeypatch.setattr(bot_module, "NetworkOrchestrator", lambda **_kwargs: application.bot_data["orchestrator"])
    asyncio.run(bot_module._post_init(cast(Any, application)))
    assert application.bot_data["linkedin_publish_reconciliation"] == {
        "reconciled": 2,
        "provider_calls": 0,
    }
    assert application.bot_data["orchestrator"].calls == [{"database": "test.db"}]
