"""Private-beta Telegram authorization tests."""

from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

from telegram_bot import access
from telegram_bot import handlers
from db.database import connect, initialize_database


def test_parse_user_ids_requires_numeric_values() -> None:
    assert access.parse_user_ids("12, 34") == frozenset({12, 34})
    with pytest.raises(ValueError):
        access.parse_user_ids("12,owner")


def test_authorization_is_deny_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access, "settings", SimpleNamespace(telegram_allowed_user_ids=""))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=12))
    assert access.is_authorized(update) is False


def test_authorization_guard_rejects_unauthorized_user() -> None:
    class Message:
        replies: list[str] = []

        async def reply_text(self, text: str) -> None:
            self.replies.append(text)

    async def exercise() -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(id=None), effective_message=Message(), callback_query=None)
        with pytest.raises(ApplicationHandlerStop):
            await access.authorization_guard(update, SimpleNamespace())
        assert update.effective_message.replies == ["Access denied."]

    import asyncio

    asyncio.run(exercise())


def test_feedback_is_stored_locally_for_authorized_user(tmp_path, monkeypatch) -> None:
    database = tmp_path / "beta.db"
    initialize_database(database)
    monkeypatch.setattr(
        handlers,
        "settings",
        SimpleNamespace(
            telegram_allowed_user_ids="12",
            telegram_admin_user_ids="12",
            application_environment="test",
            linkedin_publish_mode="disabled",
            linkedin_real_publish_enabled=False,
        ),
    )

    class Message:
        text = "/feedback bug callback is unclear"
        replies: list[str] = []

        async def reply_text(self, text: str, reply_markup=None) -> None:
            _ = reply_markup
            self.replies.append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=12), effective_message=Message())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database_path": str(database)}))

    import asyncio

    asyncio.run(handlers.feedback(update, context))
    with connect(database) as connection:
        row = connection.execute("SELECT telegram_user_id, category, message FROM beta_feedback").fetchone()
    assert row is not None
    assert tuple(row) == ("12", "bug", "callback is unclear")
