"""Tests for thin Telegram bot handlers."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telegram_bot import handlers


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


@dataclass
class FakeProspect:
    id: int
    name: str


@dataclass
class FakePost:
    id: int
    draft_text: str


class FakeMessage:
    def __init__(
        self,
        text: str = "",
        *,
        caption: str | None = None,
        photo: list[Any] | None = None,
        reply_to_message: Any | None = None,
    ) -> None:
        self.text = text
        self.caption = caption
        self.photo = photo or []
        self.reply_to_message = reply_to_message
        self.replies: list[dict[str, Any]] = []

    async def reply_text(self, text: str, reply_markup: Any | None = None) -> None:
        self.replies.append({"text": text, "reply_markup": reply_markup})


class FakeUpdate:
    def __init__(self, message: FakeMessage) -> None:
        self.effective_message = message


class FakeApplication:
    def __init__(self, orchestrator: Any, database_path: str = "test.db") -> None:
        self.bot_data = {
            "orchestrator": orchestrator,
            "database_path": database_path,
        }


class FakeContext:
    def __init__(self, orchestrator: Any, error: Exception | None = None) -> None:
        self.application = FakeApplication(orchestrator)
        self.error = error


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.followups_due: list[dict[str, Any]] = []
        self.system_result: dict[str, Any] | None = None

    def add_prospect(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "add_prospect", "kwargs": kwargs})
        return {"prospect": FakeProspect(id=7, name=kwargs["name"]), "status": "added"}

    def draft_outreach(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "draft_outreach", "kwargs": kwargs})
        return {
            "draft": {
                "draft_text": "Could we connect?",
                "character_count": 17,
            },
            "context_warning": kwargs.get("context_warning"),
        }

    def draft_followup(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "draft_followup", "kwargs": kwargs})
        return {
            "draft": {
                "draft_text": "Following up.",
                "character_count": 13,
            }
        }

    def get_followups_due(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "get_followups_due", "kwargs": kwargs})
        return self.followups_due

    def confirm_meeting(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "confirm_meeting", "kwargs": kwargs})
        return {"calendar_synced": False}

    def draft_content_post(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "draft_content_post", "kwargs": kwargs})
        return {"post": FakePost(id=3, draft_text="Post draft")}

    def get_pending_content_drafts(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "get_pending_content_drafts", "kwargs": kwargs})
        return []


class WarningOrchestrator(FakeOrchestrator):
    def draft_outreach(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "draft_outreach", "kwargs": kwargs})
        return {
            "draft": {
                "draft_text": "Could we connect?",
                "character_count": 17,
            },
            "context_warning": {
                "recommendation": "Add notes about how you found this person."
            },
        }


class RaisingOrchestrator(FakeOrchestrator):
    def add_prospect(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("internal stack trace detail")


class FakeTelegramFile:
    def __init__(self) -> None:
        self.downloaded_to: str | None = None

    async def download_to_drive(self, destination: str) -> None:
        self.downloaded_to = destination
        Path(destination).write_text("fake image", encoding="utf-8")


class FakePhoto:
    def __init__(self) -> None:
        self.file_unique_id = "photo-123"
        self.file = FakeTelegramFile()

    async def get_file(self) -> FakeTelegramFile:
        return self.file


def test_add_prospect_parses_pipe_delimited_input_correctly() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage(
        "/add_prospect Ada Lovelace | linkedin.com/in/ada | london | Engineer | Engines | Met at event"
    )

    run_async(handlers.add_prospect(FakeUpdate(message), FakeContext(orchestrator)))

    call = orchestrator.calls[0]
    assert call["method"] == "add_prospect"
    assert call["kwargs"]["name"] == "Ada Lovelace"
    assert call["kwargs"]["profile_url"] == "linkedin.com/in/ada"
    assert call["kwargs"]["location"] == "london"
    assert call["kwargs"]["role_title"] == "Engineer"
    assert call["kwargs"]["company"] == "Engines"
    assert call["kwargs"]["notes"] == "Met at event"
    assert "id=7" in message.replies[0]["text"]


def test_add_prospect_handles_missing_optional_fields() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/add_prospect Ada Lovelace | | | Engineer | |")

    run_async(handlers.add_prospect(FakeUpdate(message), FakeContext(orchestrator)))

    kwargs = orchestrator.calls[0]["kwargs"]
    assert kwargs["name"] == "Ada Lovelace"
    assert kwargs["profile_url"] is None
    assert kwargs["location"] is None
    assert kwargs["role_title"] == "Engineer"
    assert kwargs["company"] is None
    assert kwargs["notes"] is None


def test_draft_outreach_validates_ask_type() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/draft_outreach 7 career_guidance")

    run_async(handlers.draft_outreach(FakeUpdate(message), FakeContext(orchestrator)))

    assert orchestrator.calls[0]["kwargs"]["prospect_id"] == 7
    assert orchestrator.calls[0]["kwargs"]["ask_type"] == "career_guidance"
    assert "Could we connect?" in message.replies[0]["text"]
    assert message.replies[0]["reply_markup"] is not None


def test_draft_outreach_rejects_invalid_ask_type_with_clear_message() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/draft_outreach 7 spam_mode")

    run_async(handlers.draft_outreach(FakeUpdate(message), FakeContext(orchestrator)))

    assert orchestrator.calls == []
    assert "Invalid ask_type" in message.replies[0]["text"]


def test_draft_outreach_includes_context_warning_when_present() -> None:
    orchestrator = WarningOrchestrator()
    message = FakeMessage("/draft_outreach 7 general_chat")

    run_async(handlers.draft_outreach(FakeUpdate(message), FakeContext(orchestrator)))

    assert "Context warning" in message.replies[0]["text"]
    assert "Add notes" in message.replies[0]["text"]


def test_followups_due_formats_empty_list_gracefully() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/followups_due")

    run_async(handlers.followups_due(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == "No follow-ups due."


def test_meeting_confirmed_validates_date_and_time_format() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/meeting_confirmed 7 2026-99-99 9am")

    run_async(handlers.meeting_confirmed(FakeUpdate(message), FakeContext(orchestrator)))

    assert orchestrator.calls == []
    assert "Date/time must be YYYY-MM-DD and HH:MM." == message.replies[0]["text"]


def test_draft_post_handles_photo_reply_as_user_image() -> None:
    orchestrator = FakeOrchestrator()
    reply_to = FakeMessage("/draft_post AI product management")
    photo = FakePhoto()
    message = FakeMessage(photo=[photo], reply_to_message=reply_to)

    run_async(handlers.photo_reply(FakeUpdate(message), FakeContext(orchestrator)))

    kwargs = orchestrator.calls[0]["kwargs"]
    assert kwargs["topic"] == "AI product management"
    assert kwargs["user_image_path"].endswith("photo-123.jpg")
    assert kwargs["generate_image"] is False
    assert "uploaded image" in message.replies[0]["text"]


def test_draft_post_without_photo_reply_has_no_user_image() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/draft_post AI product management")

    run_async(handlers.draft_post(FakeUpdate(message), FakeContext(orchestrator)))

    kwargs = orchestrator.calls[0]["kwargs"]
    assert kwargs["topic"] == "AI product management"
    assert kwargs["user_image_path"] is None
    assert kwargs["generate_image"] is False


def test_system_check_reports_violations_clearly(
    monkeypatch: Any,
) -> None:
    class FakeSystemIntegrityAgent:
        def run_full_integrity_check(self, database: str) -> dict[str, Any]:
            return {
                "overall_passed": False,
                "checks": [
                    {
                        "check": "single_active_parameter_version",
                        "passed": False,
                        "violations": [{"agent_name": "outreach_draft_agent"}],
                    }
                ],
                "summary": "1 integrity check(s) failed.",
                "checked_at": "now",
            }

    monkeypatch.setattr(handlers, "SystemIntegrityAgent", FakeSystemIntegrityAgent)
    message = FakeMessage("/system_check")

    run_async(handlers.system_check(FakeUpdate(message), FakeContext(FakeOrchestrator())))

    assert "overall_passed=False" in message.replies[0]["text"]
    assert "single_active_parameter_version" in message.replies[0]["text"]
    assert "outreach_draft_agent" in message.replies[0]["text"]


def test_handler_error_does_not_expose_stack_trace_to_user() -> None:
    message = FakeMessage("/add_prospect Ada")
    context = FakeContext(
        RaisingOrchestrator(),
        error=RuntimeError("internal stack trace detail"),
    )

    run_async(handlers.handle_error(FakeUpdate(message), context))

    assert message.replies[0]["text"] == "Something went wrong, please try again"
    assert "internal stack trace detail" not in message.replies[0]["text"]


def test_handler_error_is_logged(caplog: Any) -> None:
    message = FakeMessage("/add_prospect Ada")
    context = FakeContext(
        RaisingOrchestrator(),
        error=RuntimeError("internal stack trace detail"),
    )

    with caplog.at_level(logging.ERROR, logger="telegram_bot.handlers"):
        run_async(handlers.handle_error(FakeUpdate(message), context))

    assert "Telegram handler failed" in caplog.text
