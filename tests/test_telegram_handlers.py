"""Tests for thin Telegram bot handlers."""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.orchestrator import NetworkOrchestrator, NetworkOrchestratorError
from db.database import connect, initialize_database
from db.models import Prospect
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
    image_source: str = "none"
    image_path: str | None = None


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
    def __init__(
        self,
        message: FakeMessage | None = None,
        callback_query: Any | None = None,
    ) -> None:
        message = message or FakeMessage()
        self.effective_message = message
        self.callback_query = callback_query


class FakeApplication:
    def __init__(self, orchestrator: Any, database_path: str = "test.db") -> None:
        self.bot_data = {
            "orchestrator": orchestrator,
            "database_path": database_path,
        }


class FakeContext:
    def __init__(
        self,
        orchestrator: Any,
        error: Exception | None = None,
        database_path: str = "test.db",
    ) -> None:
        self.application = FakeApplication(orchestrator, database_path=database_path)
        self.error = error


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.followups_due: list[dict[str, Any]] = []
        self.system_result: dict[str, Any] | None = None

    def get_guided_next_steps(self, **kwargs: Any) -> dict[str, list[dict[str, str]]]:
        self.calls.append({"method": "get_guided_next_steps", "kwargs": kwargs})
        return {
            "steps": [
                {
                    "title": "Review your newest content package",
                    "command": "/content_package 3",
                    "detail": "Read it, revise it, or approve it for later posting.",
                }
            ]
        }

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
            "draft_interaction_id": 11,
        }

    def draft_followup(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "draft_followup", "kwargs": kwargs})
        return {
            "draft": {
                "draft_text": "Following up.",
                "character_count": 13,
            },
            "draft_interaction_id": 12,
        }

    def get_followups_due(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "get_followups_due", "kwargs": kwargs})
        return self.followups_due

    def confirm_meeting(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "confirm_meeting", "kwargs": kwargs})
        return {"calendar_synced": False}

    def draft_content_post(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "draft_content_post", "kwargs": kwargs})
        if kwargs.get("user_image_path"):
            image_source = "uploaded"
            image_path = kwargs["user_image_path"]
        elif kwargs.get("generate_image"):
            image_source = "generated"
            image_path = "mock://generated-linkedin-image.png"
        else:
            image_source = "none"
            image_path = None
        return {
            "post": FakePost(
                id=3,
                draft_text="Post draft",
                image_source=image_source,
                image_path=image_path,
            )
        }

    def get_pending_content_drafts(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "get_pending_content_drafts", "kwargs": kwargs})
        return []

    def get_content_publish_readiness(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(
            {"method": "get_content_publish_readiness", "kwargs": kwargs}
        )
        return {
            "exists": True,
            "package_backed": True,
            "ready": True,
            "status": "approved_for_later_posting",
            "blockers": [],
        }

    def get_linkedin_publish_diagnostics(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "get_linkedin_publish_diagnostics", "kwargs": kwargs})
        return {
            "mode": "disabled",
            "real_publish_enabled": False,
            "connection_status": "connected",
            "member_identity_resolved": True,
            "pending": 2,
            "in_progress": 0,
            "uncertain": 1,
            "stale": 0,
            "startup_reconciled_count": 1,
            "recent_safe_failures": [
                {"request_id": 7, "status": "publish_uncertain", "code": "timeout"}
            ],
        }

    def get_pending_drafts(self, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        self.calls.append({"method": "get_pending_drafts", "kwargs": kwargs})
        return {"outreach": [], "content": []}

    def get_brand_profile_summary(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append({"method": "get_brand_profile_summary", "kwargs": kwargs})
        return {
            "id": 1,
            "version": 1,
            "is_active": True,
            "professional_identity": "Tech MBA product professional",
            "current_program": "Tech MBA",
            "institutions": ["Cornell", "Cornell Tech"],
            "career_focus": ["Product management"],
            "content_pillars": ["AI products"],
            "target_audiences": ["Product managers"],
            "preferred_tone": ["Thoughtful"],
            "preferred_depth": "Practical",
            "humor_preferences": ["Light humor only"],
            "claims_requiring_confirmation": ["Achievements"],
            "topics_to_avoid": ["Rumors"],
            "networking_goals": ["Learn from leaders"],
        }

    def list_brand_profile_versions(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "list_brand_profile_versions", "kwargs": kwargs})
        summary = self.get_brand_profile_summary()
        assert summary is not None
        return [summary]

    def activate_brand_profile(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "activate_brand_profile", "kwargs": kwargs})
        return {"version": kwargs["version"], "is_active": True}

    def update_brand_profile_field(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "update_brand_profile_field", "kwargs": kwargs})
        return {"version": 2, "is_active": True}

    def add_signal_source(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "add_signal_source", "kwargs": kwargs})
        return {"id": 3, "approval_status": "pending"}

    def list_signal_sources(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "list_signal_sources", "kwargs": kwargs})
        return [
            {
                "id": 3,
                "name": "Example",
                "source_type": "rss",
                "approval_status": "approved",
                "enabled": True,
                "last_fetch_status": "success",
            }
        ]

    def approve_signal_source(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "approve_signal_source", "kwargs": kwargs})
        return {"id": kwargs["source_id"], "approval_status": "approved"}

    def reject_signal_source(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "reject_signal_source", "kwargs": kwargs})
        return {"id": kwargs["source_id"], "approval_status": "rejected"}

    def set_signal_source_enabled(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "set_signal_source_enabled", "kwargs": kwargs})
        return {"id": kwargs["source_id"], "enabled": kwargs["enabled"]}

    def scan_signal_source(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "scan_signal_source", "kwargs": kwargs})
        return {
            "status": "success",
            "items_fetched": 2,
            "new_signals": 1,
            "duplicates": 1,
            "failures": 0,
            "not_modified": False,
            "warnings": [],
            "errors": [],
        }

    def scan_enabled_signal_sources(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "scan_enabled_signal_sources", "kwargs": kwargs})
        return {"sources_scanned": 1, "new_signals": 1, "duplicates": 0, "failures": 0}

    def get_recent_signals(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "get_recent_signals", "kwargs": kwargs})
        return [{"id": 8, "title": "Signal", "source_name": "Example", "status": "normalized"}]

    def get_signal(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "get_signal", "kwargs": kwargs})
        return {"id": kwargs["signal_id"], "title": "Signal", "source_name": "Example", "status": "normalized"}

    def get_briefing_status(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "get_briefing_status", "kwargs": kwargs})
        return {"enabled": False, "briefing_time": "08:30", "timezone": "America/New_York", "dry_run": False, "last_run": None}

    def list_briefing_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "list_briefing_runs", "kwargs": kwargs})
        return []

    def build_daily_briefing(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "build_daily_briefing", "kwargs": kwargs})
        return {"run_id": 4, "status": "no_content", "scan": {"sources_scanned": 0, "new_signals": 0}, "scoring": {"scored": 0}, "packages": [], "followups": [], "dry_run": kwargs.get("dry_run", False)}

    def update_briefing_settings(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "update_briefing_settings", "kwargs": kwargs})
        return {"enabled": kwargs.get("enabled", False), "briefing_time": kwargs.get("briefing_time", "08:30"), "timezone": "America/New_York"}

    def mark_outreach_sent(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "mark_outreach_sent", "kwargs": kwargs})
        return {"status": "connection_sent", "prospect": FakeProspect(id=7, name="Ada")}

    def discard_outreach_draft(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "discard_outreach_draft", "kwargs": kwargs})
        return {"status": "discarded"}
    def save_content_draft(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "save_content_draft", "kwargs": kwargs})
        return {"status": "saved"}

    def approve_content_draft_for_later_posting(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "approve_content_draft_for_later_posting",
                "kwargs": kwargs,
            }
        )
        return {"status": "approved_for_later_posting"}

    def discard_content_draft(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "discard_content_draft", "kwargs": kwargs})
        return {"status": "discarded"}

    def record_outcome(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "record_outcome", "kwargs": kwargs})
        return {"id": 9}

    def suggest_refinements(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "suggest_refinements", "kwargs": kwargs})
        return {
            "run_id": "run-1",
            "status": "completed",
            "mode": "report_only",
            "message": "Report-only. No changes have been applied.",
            "suggestions": [
                {
                    "proposal_id": "proposal-1",
                    "target_area": "outreach_draft_agent",
                    "parameter_name": "opening_style",
                    "current_value": "concise",
                    "proposed_value": "concise | emphasize specific evidence",
                    "reason": "Positive replies favored specificity.",
                    "evidence": [{"outcome": "replied_positive"}],
                    "checker": {
                        "passed": True,
                        "status": "approved_for_report",
                        "risk_level": "low",
                        "reason": "Safe report-only proposal.",
                    },
                    "status": "pending_approval",
                }
            ],
        }

    def apply_refinement(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "apply_refinement", "kwargs": kwargs})
        return {"status": "accepted", "accepted": True}

    def apply_refinement_proposal(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "apply_refinement_proposal", "kwargs": kwargs})
        return {"status": "applied"}

    def reject_refinement(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "reject_refinement", "kwargs": kwargs})
        return {"status": "rejected"}

    def reject_refinement_proposal(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "reject_refinement_proposal", "kwargs": kwargs})
        return {"status": "rejected"}

    def get_refinement_reasoning(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "get_refinement_reasoning", "kwargs": kwargs})
        return {
            "proposal_id": kwargs["proposal_id"],
            "target_area": "outreach_draft_agent",
            "parameter_name": "opening_style",
            "current_value": "concise",
            "proposed_value": "concise | emphasize specific evidence",
            "reason": "Positive replies favored specificity.",
            "evidence": [{"outcome": "replied_positive"}],
            "risk_level": "low",
            "checker_status": "passed",
        }

    def rollback_refinement(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "rollback_refinement", "kwargs": kwargs})
        return {
            "status": "rolled_back",
            "refinement_id": kwargs["refinement_id"],
            "parameter_name": "opening_style",
            "restored_value": "concise",
        }

    def get_refinement_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"method": "get_refinement_history", "kwargs": kwargs})
        return [
            {
                "refinement_id": 12,
                "event_type": "proposal_applied",
                "parameter_name": "opening_style",
                "old_value": "concise",
                "new_value": "specific",
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "applied",
                "rollback_from_refinement_id": None,
            }
        ]

    def get_refinement_status(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "get_refinement_status", "kwargs": kwargs})
        return {
            "mode": "report_only",
            "loop_paused": False,
            "max_proposals_per_run": 3,
            "max_apply_per_run": 1,
            "recent_run": {"status": "completed"},
            "pending_proposals_count": 1,
            "applied_refinements_count": 2,
            "rejected_refinements_count": 1,
            "failed_validation_count": 0,
        }

    def get_refinement_report(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "get_refinement_report", "kwargs": kwargs})
        return {
            "message": "This is a report only. No changes were applied.",
            "recent_outcomes": [{"outcome": "replied_positive"}],
            "recent_proposals": [{"proposal_id": "proposal-1"}],
            "pending_proposals": [
                {
                    "proposal_id": "proposal-1",
                    "target_area": "outreach_draft_agent",
                    "parameter_name": "opening_style",
                    "proposed_value": "specific",
                    "risk_level": "low",
                    "checker_status": "passed",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "proposal_counts": {"pending_approval": 1},
            "event_counts": {"proposal_applied": 2, "proposal_rejected": 1},
            "rollbacks_applied_count": 1,
            "common_failed_validation_reasons": [],
            "current_parameters": {
                "outreach_draft_agent": {"opening_style": "concise"}
            },
            "recommended_next_action": "Review pending proposals with /suggest_refinements before applying anything.",
        }


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


class InvalidProspectOrchestrator(FakeOrchestrator):
    def draft_outreach(self, **kwargs: Any) -> dict[str, Any]:
        raise NetworkOrchestratorError("draft_outreach failed: missing prospect")

    def draft_followup(self, **kwargs: Any) -> dict[str, Any]:
        raise NetworkOrchestratorError("draft_followup failed: missing prospect")

    def mark_outreach_sent(self, **kwargs: Any) -> dict[str, Any]:
        raise NetworkOrchestratorError("mark_outreach_sent failed: missing prospect")

    def discard_outreach_draft(self, **kwargs: Any) -> dict[str, Any]:
        raise NetworkOrchestratorError("discard_outreach_draft failed: stale draft")


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


class FakeCallbackQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answered = False
        self.edited_text: str | None = None

    async def answer(self) -> None:
        self.answered = True

    async def edit_message_text(self, text: str) -> None:
        self.edited_text = text


def test_start_shows_a_small_state_aware_next_step_guide() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/start")

    run_async(handlers.start(FakeUpdate(message), FakeContext(orchestrator)))

    assert orchestrator.calls == [
        {
            "method": "get_guided_next_steps",
            "kwargs": {"database": "test.db"},
        }
    ]
    reply = message.replies[0]["text"]
    assert "Welcome back. Here are your next best steps:" in reply
    assert "/content_package 3" in reply
    assert "Available commands:" not in reply
    assert "Use Telegram's command menu" in reply


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


def test_draft_outreach_button_wording_is_manual_only() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/draft_outreach 7 career_guidance")

    run_async(handlers.draft_outreach(FakeUpdate(message), FakeContext(orchestrator)))

    markup = message.replies[0]["reply_markup"]
    button = markup.inline_keyboard[0][0]
    assert button.text == "Mark as Manually Sent"
    assert "Approve & Mark Sent" not in button.text
    assert markup.inline_keyboard[0][1].text == "Discard Draft"


def test_real_model_mode_routes_only_through_model_orchestration_agent() -> None:
    outreach_source = Path("agents/outreach_draft_agent.py").read_text(
        encoding="utf-8"
    )
    orchestrator_source = Path("agents/orchestrator.py").read_text(encoding="utf-8")
    handler_source = Path("telegram_bot/handlers.py").read_text(encoding="utf-8")

    assert "ModelOrchestrationAgent" in outreach_source
    assert "nvidia_model_gateway" not in outreach_source
    assert "call_nvidia_llm" not in outreach_source
    assert "ModelOrchestrationAgent" not in orchestrator_source
    assert "ModelOrchestrationAgent" not in handler_source


def test_draft_outreach_rejects_invalid_ask_type_with_clear_message() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/draft_outreach 7 spam_mode")

    run_async(handlers.draft_outreach(FakeUpdate(message), FakeContext(orchestrator)))

    assert orchestrator.calls == []
    assert "Invalid ask_type" in message.replies[0]["text"]


def test_draft_outreach_invalid_prospect_id_gives_clean_message() -> None:
    orchestrator = InvalidProspectOrchestrator()
    message = FakeMessage("/draft_outreach 999 career_guidance")

    run_async(handlers.draft_outreach(FakeUpdate(message), FakeContext(orchestrator)))

    assert "Could not draft outreach for prospect_id=999" in message.replies[0]["text"]
    assert "Traceback" not in message.replies[0]["text"]


def test_draft_outreach_includes_context_warning_when_present() -> None:
    orchestrator = WarningOrchestrator()
    message = FakeMessage("/draft_outreach 7 general_chat")

    run_async(handlers.draft_outreach(FakeUpdate(message), FakeContext(orchestrator)))

    assert "Context warning" in message.replies[0]["text"]
    assert "Add notes" in message.replies[0]["text"]


def test_mock_mode_still_returns_deterministic_draft() -> None:
    orchestrator = FakeOrchestrator()
    first_message = FakeMessage("/draft_outreach 7 general_chat")
    second_message = FakeMessage("/draft_outreach 7 general_chat")

    run_async(handlers.draft_outreach(FakeUpdate(first_message), FakeContext(orchestrator)))
    run_async(handlers.draft_outreach(FakeUpdate(second_message), FakeContext(orchestrator)))

    assert first_message.replies[0]["text"] == second_message.replies[0]["text"]


def test_followups_due_formats_empty_list_gracefully() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/followups_due")

    run_async(handlers.followups_due(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == "No follow-ups due."


def test_pending_drafts_handles_empty_state() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/pending_drafts")

    run_async(handlers.pending_drafts(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == "No pending drafts right now."


def test_brand_profile_displays_concise_active_profile() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/brand_profile")

    run_async(handlers.brand_profile(FakeUpdate(message), FakeContext(orchestrator)))

    reply = message.replies[0]["text"]
    assert "Personal-brand profile v1" in reply
    assert "Tech MBA product professional" in reply
    assert "Content pillars: AI products" in reply
    assert orchestrator.calls[0]["method"] == "get_brand_profile_summary"


def test_brand_profile_versions_marks_active_version() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/brand_profile_versions")

    run_async(
        handlers.brand_profile_versions(FakeUpdate(message), FakeContext(orchestrator))
    )

    assert "v1 (id=1) active" in message.replies[0]["text"]


def test_activate_brand_profile_validates_argument_and_calls_orchestrator() -> None:
    orchestrator = FakeOrchestrator()
    invalid_message = FakeMessage("/activate_brand_profile nope")
    run_async(
        handlers.activate_brand_profile(
            FakeUpdate(invalid_message),
            FakeContext(orchestrator),
        )
    )
    assert invalid_message.replies[0]["text"] == "Usage: /activate_brand_profile <version>"

    message = FakeMessage("/activate_brand_profile 2")
    run_async(
        handlers.activate_brand_profile(FakeUpdate(message), FakeContext(orchestrator))
    )
    assert message.replies[0]["text"] == "Personal-brand profile version 2 is now active."
    assert orchestrator.calls[-1]["method"] == "activate_brand_profile"


def test_set_brand_field_parses_value_and_creates_new_version() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage(
        "/set_brand_field content_pillars | product management, AI products"
    )

    run_async(handlers.set_brand_field(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == "Created and activated personal-brand profile version 2."
    call = orchestrator.calls[-1]
    assert call["method"] == "update_brand_profile_field"
    assert call["kwargs"]["field_name"] == "content_pillars"
    assert call["kwargs"]["value"] == "product management, AI products"


def test_signal_source_commands_parse_and_format_results() -> None:
    orchestrator = FakeOrchestrator()
    add_message = FakeMessage("/add_signal_source Example | https://example.com/feed")
    run_async(handlers.add_signal_source(FakeUpdate(add_message), FakeContext(orchestrator)))
    assert "Source ID: 3" in add_message.replies[0]["text"]
    assert orchestrator.calls[-1]["method"] == "add_signal_source"

    scan_message = FakeMessage("/scan_signal_source 3")
    run_async(handlers.scan_signal_source(FakeUpdate(scan_message), FakeContext(orchestrator)))
    assert "New signals: 1" in scan_message.replies[0]["text"]


def test_signal_commands_validate_ids_and_display_recent_items() -> None:
    orchestrator = FakeOrchestrator()
    invalid = FakeMessage("/approve_signal_source nope")
    run_async(
        handlers.approve_signal_source(FakeUpdate(invalid), FakeContext(orchestrator))
    )
    assert invalid.replies[0]["text"] == "Usage: /approve_signal_source <source_id>"

    recent = FakeMessage("/signals")
    run_async(handlers.signals(FakeUpdate(recent), FakeContext(orchestrator)))
    assert "8: Signal | Example" in recent.replies[0]["text"]

    detail = FakeMessage("/signal 8")
    run_async(handlers.signal(FakeUpdate(detail), FakeContext(orchestrator)))
    assert "Signal 8: Signal" in detail.replies[0]["text"]


def test_pending_drafts_lists_outreach_and_content_drafts() -> None:
    class PendingOrchestrator(FakeOrchestrator):
        def get_pending_drafts(self, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
            self.calls.append({"method": "get_pending_drafts", "kwargs": kwargs})
            return {
                "outreach": [
                    {
                        "id": 11,
                        "prospect_id": 7,
                        "prospect_name": "Ada Lovelace",
                        "ask_type": "career_guidance",
                        "status": "drafted",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "content": [
                    {
                        "id": 3,
                        "topic": "AI product launches",
                        "image_source": "uploaded",
                        "status": "saved",
                        "created_at": "2026-01-02T00:00:00+00:00",
                    }
                ],
            }

    orchestrator = PendingOrchestrator()
    message = FakeMessage("/pending_drafts")

    run_async(handlers.pending_drafts(FakeUpdate(message), FakeContext(orchestrator)))

    reply = message.replies[0]["text"]
    assert "Outreach drafts:" in reply
    assert "Ada Lovelace" in reply
    assert "career_guidance" in reply
    assert "Content drafts:" in reply
    assert "AI product launches" in reply
    assert "image=uploaded" in reply


def test_record_outcome_outreach_parses_notes_and_delegates() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage(
        '/record_outcome outreach 7 replied_positive "Asked to chat next week"'
    )

    run_async(handlers.record_outcome(FakeUpdate(message), FakeContext(orchestrator)))

    call = orchestrator.calls[0]
    assert call["method"] == "record_outcome"
    assert call["kwargs"]["target_type"] == "outreach"
    assert call["kwargs"]["target_id"] == 7
    assert call["kwargs"]["outcome"] == "replied_positive"
    assert call["kwargs"]["notes"] == "Asked to chat next week"
    assert "Outcome recorded" in message.replies[0]["text"]


def test_record_outcome_content_parses_and_delegates() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/record_outcome content 3 good_engagement strong comments")

    run_async(handlers.record_outcome(FakeUpdate(message), FakeContext(orchestrator)))

    call = orchestrator.calls[0]
    assert call["kwargs"]["target_type"] == "content"
    assert call["kwargs"]["target_id"] == 3
    assert call["kwargs"]["outcome"] == "good_engagement"
    assert call["kwargs"]["notes"] == "strong comments"


def test_record_outcome_rejects_invalid_outcome() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/record_outcome outreach 7 viral")

    run_async(handlers.record_outcome(FakeUpdate(message), FakeContext(orchestrator)))

    assert orchestrator.calls == []
    assert "Invalid outreach outcome" in message.replies[0]["text"]


def test_suggest_refinements_renders_apply_reject_reasoning_buttons() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/suggest_refinements")
    context = FakeContext(orchestrator)

    run_async(handlers.suggest_refinements(FakeUpdate(message), context))

    assert "Refinement loop report" in message.replies[0]["text"]
    assert "Refinements are not applied unless you tap Apply." in message.replies[0]["text"]
    assert "Target area: outreach_draft_agent" in message.replies[0]["text"]
    markup = message.replies[0]["reply_markup"]
    assert markup is not None
    labels = [button.text for button in markup.inline_keyboard[0]]
    assert labels == ["Apply Refinement 1", "Reject Refinement", "View Reasoning"]


def test_apply_refinement_callback_delegates_to_persisted_proposal() -> None:
    orchestrator = FakeOrchestrator()
    context = FakeContext(orchestrator)
    callback = FakeCallbackQuery("refinement_apply:proposal-1")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), context))

    assert callback.edited_text == "Refinement applied. Core intent was not changed."
    assert orchestrator.calls[0]["method"] == "apply_refinement_proposal"
    assert orchestrator.calls[0]["kwargs"]["proposal_id"] == "proposal-1"


def test_reject_refinement_callback_delegates_to_persisted_proposal() -> None:
    orchestrator = FakeOrchestrator()
    context = FakeContext(orchestrator)
    callback = FakeCallbackQuery("refinement_reject:proposal-1")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), context))

    assert callback.edited_text == "Refinement rejected. No changes were made."
    assert orchestrator.calls[0]["method"] == "reject_refinement_proposal"
    assert orchestrator.calls[0]["kwargs"]["proposal_id"] == "proposal-1"


def test_view_refinement_reasoning_callback_is_read_only() -> None:
    orchestrator = FakeOrchestrator()
    context = FakeContext(orchestrator)
    callback = FakeCallbackQuery("refinement_reason:proposal-1")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), context))

    assert callback.edited_text is not None
    assert "Refinement reasoning" in callback.edited_text
    assert orchestrator.calls[0]["method"] == "get_refinement_reasoning"


def test_missing_refinement_apply_callback_gives_clean_error() -> None:
    orchestrator = FakeOrchestrator()
    def raise_missing(**kwargs: Any) -> dict[str, Any]:
        raise NetworkOrchestratorError("apply_refinement_proposal failed: not found")
    orchestrator.apply_refinement_proposal = raise_missing  # type: ignore[method-assign]
    callback = FakeCallbackQuery("refinement_apply:missing")

    run_async(
        handlers.button_callback(
            FakeUpdate(callback_query=callback),
            FakeContext(orchestrator),
        )
    )

    assert callback.edited_text == "Could not apply refinement. No changes were made."


def test_refinement_status_shows_loop_counts() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/refinement_status")

    run_async(handlers.refinement_status(FakeUpdate(message), FakeContext(orchestrator)))

    reply = message.replies[0]["text"]
    assert "Refinement status" in reply
    assert "Mode: report_only" in reply
    assert "Paused: False" in reply
    assert "Pending proposals: 1" in reply
    assert "Applied refinements: 2" in reply
    assert "Rejected refinements: 1" in reply
    assert orchestrator.calls[0]["method"] == "get_refinement_status"


def test_refinement_report_summarizes_without_applying_changes() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/refinement_report")

    run_async(handlers.refinement_report(FakeUpdate(message), FakeContext(orchestrator)))

    reply = message.replies[0]["text"]
    assert "Refinement report" in reply
    assert "This is a report only. No changes were applied." in reply
    assert "Recent outcomes: 1" in reply
    assert "Pending proposals:" in reply
    assert "proposal-1 outreach_draft_agent opening_style -> specific" in reply
    assert "Current parameters:" in reply
    assert orchestrator.calls == [
        {"method": "get_refinement_report", "kwargs": {"database": "test.db"}}
    ]


def test_rollback_refinement_parses_and_delegates() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/rollback_refinement 12")

    run_async(handlers.rollback_refinement(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == (
        "Rollback applied for opening_style. Restored previous value. Core intent was not changed."
    )
    assert orchestrator.calls[0]["method"] == "rollback_refinement"
    assert orchestrator.calls[0]["kwargs"]["refinement_id"] == 12


def test_rollback_refinement_malformed_command_gives_clean_error() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/rollback_refinement outreach_draft_agent 1")

    run_async(handlers.rollback_refinement(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == "Usage: /rollback_refinement <refinement_id>"
    assert orchestrator.calls == []


def test_rollback_refinement_stale_failure_is_clean() -> None:
    class StaleRollbackOrchestrator(FakeOrchestrator):
        def rollback_refinement(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append({"method": "rollback_refinement", "kwargs": kwargs})
            raise NetworkOrchestratorError(
                "rollback_refinement failed (refinement_id=12): "
                "This refinement cannot be rolled back automatically because the parameter "
                "has changed since it was applied. Please review manually."
            )

    orchestrator = StaleRollbackOrchestrator()
    message = FakeMessage("/rollback_refinement 12")

    run_async(handlers.rollback_refinement(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == (
        "This refinement cannot be rolled back automatically because the parameter has changed since it was applied. Please review manually."
    )
    assert "Traceback" not in message.replies[0]["text"]


def test_refinement_history_formats_recent_events() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/refinement_history")

    run_async(handlers.refinement_history(FakeUpdate(message), FakeContext(orchestrator)))

    reply = message.replies[0]["text"]
    assert "Recent refinement history:" in reply
    assert "#12 proposal_applied opening_style" in reply
    assert "concise -> specific" in reply
    assert orchestrator.calls[0]["method"] == "get_refinement_history"


def test_manual_sent_callback_persists_to_sqlite_and_followups_due_uses_cadence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)
    orchestrator = NetworkOrchestrator()
    prospect_record = orchestrator.add_prospect(
        "Ada Lovelace",
        database=database_path,
    )["prospect"]
    assert isinstance(prospect_record, Prospect)
    prospect = prospect_record
    prospect_id = prospect.id
    assert prospect_id is not None
    context = FakeContext(orchestrator, database_path=str(database_path))
    context.application.bot_data["outreach_drafts"] = {
        str(prospect_id): {
            "ask_type": "career_guidance",
            "draft_text": "Could we connect?",
        }
    }
    callback = FakeCallbackQuery(f"manual_sent:{prospect_id}")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), context))

    assert callback.edited_text == (
        "Marked as manually sent on LinkedIn. I'll track this for follow-up."
    )
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM interactions
            WHERE prospect_id = ? AND interaction_type = 'linkedin_connection_request'
            """,
            (prospect_id,),
        ).fetchone()
        prospect_row = connection.execute(
            "SELECT status, last_touch_date FROM prospects WHERE id = ?",
            (prospect_id,),
        ).fetchone()
    assert row is not None
    assert prospect_row["status"] == "connection_sent"
    assert prospect_row["last_touch_date"] is not None
    content = json.loads(row["content"])
    assert content == {
        "ask_type": "career_guidance",
        "draft_text": "Could we connect?",
        "source": "telegram_button",
        "status": "sent_manually",
    }
    assert orchestrator.get_followups_due(database=database_path) == []


def test_outreach_discard_callback_updates_sqlite_without_touching_followup(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)
    orchestrator = NetworkOrchestrator()
    prospect = orchestrator.add_prospect("Ada Lovelace", database=database_path)[
        "prospect"
    ]
    assert isinstance(prospect, Prospect)
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO interactions (
                prospect_id,
                interaction_type,
                content,
                direction,
                status,
                source,
                created_at,
                updated_at
            )
            VALUES (
                ?,
                'outreach_draft',
                '{"ask_type": "career_guidance"}',
                'outbound_draft',
                'drafted',
                'telegram',
                '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00'
            )
            """,
            (prospect.id,),
        )
        draft_interaction_id = cursor.lastrowid
    callback = FakeCallbackQuery(f"outreach_discard:{draft_interaction_id}")

    run_async(
        handlers.button_callback(
            FakeUpdate(callback_query=callback),
            FakeContext(orchestrator, database_path=str(database_path)),
        )
    )

    assert callback.edited_text == "Discarded draft."
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM interactions WHERE id = ?",
            (draft_interaction_id,),
        ).fetchone()
        prospect_row = connection.execute(
            "SELECT last_touch_date FROM prospects WHERE id = ?",
            (prospect.id,),
        ).fetchone()
    assert row["status"] == "discarded"
    assert prospect_row["last_touch_date"] is None


def test_meeting_confirmed_validates_date_and_time_format() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/meeting_confirmed 7 2026-99-99 9am")

    run_async(handlers.meeting_confirmed(FakeUpdate(message), FakeContext(orchestrator)))

    assert orchestrator.calls == []
    assert "Date/time must be YYYY-MM-DD and HH:MM." == message.replies[0]["text"]


def test_draft_post_handles_photo_reply_as_user_image() -> None:
    orchestrator = FakeOrchestrator()
    photo = FakePhoto()
    photo_message = FakeMessage(photo=[photo])
    context = FakeContext(orchestrator)

    run_async(handlers.photo_reply(FakeUpdate(photo_message), context))
    message = FakeMessage("/draft_post AI product management")
    run_async(handlers.draft_post(FakeUpdate(message), context))

    kwargs = orchestrator.calls[0]["kwargs"]
    assert kwargs["topic"] == "AI product management"
    assert kwargs["user_image_path"].endswith("photo-123.jpg")
    assert kwargs["generate_image"] is False
    assert photo_message.replies[0]["text"] == "Image saved for your next /draft_post."
    assert "based on your uploaded image" in message.replies[0]["text"]
    assert message.replies[0]["reply_markup"].inline_keyboard[0][0].text == "Save Draft"
    assert message.replies[0]["reply_markup"].inline_keyboard[0][1].text == "Discard Draft"


def test_draft_post_without_photo_reply_has_no_user_image() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/draft_post AI product management")

    run_async(handlers.draft_post(FakeUpdate(message), FakeContext(orchestrator)))

    kwargs = orchestrator.calls[0]["kwargs"]
    assert kwargs["topic"] == "AI product management"
    assert kwargs["user_image_path"] is None
    assert kwargs["generate_image"] is False
    assert "Here's a LinkedIn post draft." in message.replies[0]["text"]


def test_draft_post_generated_image_mode_uses_gateway_path() -> None:
    orchestrator = FakeOrchestrator()
    context = FakeContext(orchestrator)
    context.application.bot_data["generate_image_for_draft_posts"] = True
    message = FakeMessage("/draft_post AI product management")

    run_async(handlers.draft_post(FakeUpdate(message), context))

    kwargs = orchestrator.calls[0]["kwargs"]
    assert kwargs["user_image_path"] is None
    assert kwargs["generate_image"] is True
    assert "suggested/generated image concept" in message.replies[0]["text"]


def test_photo_reply_rejects_unsupported_image_type_cleanly() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage()

    run_async(handlers.photo_reply(FakeUpdate(message), FakeContext(orchestrator)))

    assert message.replies[0]["text"] == (
        "Unsupported image type. Please upload a standard Telegram photo."
    )
    assert orchestrator.calls == []


def test_no_linkedin_sending_or_scraping_behavior() -> None:
    handler_source = Path("telegram_bot/handlers.py").read_text(encoding="utf-8")
    orchestrator_source = Path("agents/orchestrator.py").read_text(encoding="utf-8")
    combined_source = f"{handler_source}\n{orchestrator_source}".lower()

    assert "linkedinpublishagent" not in combined_source
    assert "send_linkedin" not in combined_source
    assert "scrape" not in combined_source


def test_telegram_handler_has_no_direct_image_or_model_provider_calls() -> None:
    handler_source = Path("telegram_bot/handlers.py").read_text(encoding="utf-8")

    assert "image_gateway" not in handler_source
    assert "ModelOrchestrationAgent" not in handler_source
    assert "call_nvidia_llm" not in handler_source


def test_content_save_callback_updates_status() -> None:
    orchestrator = FakeOrchestrator()
    callback = FakeCallbackQuery("post_save:3")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), FakeContext(orchestrator)))

    assert callback.edited_text == "Saved as draft."
    assert orchestrator.calls[0]["method"] == "save_content_draft"
    assert orchestrator.calls[0]["kwargs"]["post_id"] == 3


def test_legacy_content_approve_callback_uses_strict_package_approval() -> None:
    orchestrator = FakeOrchestrator()
    callback = FakeCallbackQuery("post_approve_later:3")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), FakeContext(orchestrator)))

    assert callback.edited_text == (
        "Content package approved for later posting. Nothing has been published."
    )
    assert orchestrator.calls[0]["method"] == "approve_content_draft_for_later_posting"
    assert "publish" not in str(orchestrator.calls).lower()


def test_content_discard_callback_updates_status() -> None:
    orchestrator = FakeOrchestrator()
    callback = FakeCallbackQuery("post_discard:3")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), FakeContext(orchestrator)))

    assert callback.edited_text == "Discarded draft."
    assert orchestrator.calls[0]["method"] == "discard_content_draft"


def test_malformed_content_callback_gives_clean_error() -> None:
    orchestrator = FakeOrchestrator()
    callback = FakeCallbackQuery("post_save:not-a-number")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), FakeContext(orchestrator)))

    assert callback.edited_text == "Invalid content draft action. Please draft again."
    assert orchestrator.calls == []


def test_manual_sent_callback_rejects_invalid_callback_data_cleanly() -> None:
    orchestrator = FakeOrchestrator()
    callback = FakeCallbackQuery("manual_sent:not-a-number")

    run_async(handlers.button_callback(FakeUpdate(callback_query=callback), FakeContext(orchestrator)))

    assert callback.answered is True
    assert callback.edited_text == "Invalid outreach action. Please draft again."
    assert orchestrator.calls == []


def test_manual_sent_callback_rejects_stale_unknown_prospect_cleanly() -> None:
    orchestrator = InvalidProspectOrchestrator()
    callback = FakeCallbackQuery("manual_sent:999")

    run_async(
        handlers.button_callback(
            FakeUpdate(callback_query=callback),
            FakeContext(orchestrator),
        )
    )

    assert callback.answered is True
    assert (
        callback.edited_text
        == "Could not mark prospect_id=999 as manually sent. Please check the prospect ID."
    )
    assert "Traceback" not in callback.edited_text


def test_outreach_discard_callback_rejects_stale_draft_cleanly() -> None:
    orchestrator = InvalidProspectOrchestrator()
    callback = FakeCallbackQuery("outreach_discard:999")

    run_async(
        handlers.button_callback(
            FakeUpdate(callback_query=callback),
            FakeContext(orchestrator),
        )
    )

    assert callback.answered is True
    assert callback.edited_text == (
        "Could not discard that outreach draft. Please draft again."
    )
    assert "Traceback" not in callback.edited_text


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


def test_briefing_status_replies_when_disabled() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/briefing_status")
    run_async(handlers.briefing_status(FakeUpdate(message), FakeContext(orchestrator)))
    assert "disabled" in message.replies[0]["text"]
    assert orchestrator.calls[0]["method"] == "get_briefing_status"


def test_briefing_history_has_clean_empty_state() -> None:
    message = FakeMessage("/briefing_history")
    run_async(handlers.briefing_history(FakeUpdate(message), FakeContext(FakeOrchestrator())))
    assert message.replies[0]["text"] == "No briefing runs have been recorded yet."


def test_briefing_now_always_replies_for_manual_dry_run() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/briefing_now dry_run")
    run_async(handlers.briefing_now(FakeUpdate(message), FakeContext(orchestrator)))
    assert "Manual briefing" in message.replies[0]["text"]
    assert orchestrator.calls[0]["kwargs"]["dry_run"] is True


def test_prepare_publish_displays_complete_confirmation_boundary() -> None:
    class PublishOrchestrator(FakeOrchestrator):
        def prepare_linkedin_publish(self, post_id: int, *, database: str) -> dict[str, Any]:
            self.calls.append({"method": "prepare_linkedin_publish", "post_id": post_id, "database": database})
            return {"request_id": 8, "post_id": post_id, "package_version": 2, "format": "text", "visibility": "PUBLIC", "commentary": "Exact commentary", "assets": [], "payload_fingerprint": "abc123", "expires_at": "later"}

    orchestrator = PublishOrchestrator()
    message = FakeMessage("/prepare_publish 3")
    run_async(handlers.prepare_publish(FakeUpdate(message), FakeContext(orchestrator)))
    assert "REAL LINKEDIN PUBLISH PREVIEW" in message.replies[0]["text"]
    assert "Exact commentary" in message.replies[0]["text"]
    assert "/confirm_publish 8" in message.replies[0]["text"]


def test_prepare_publish_explains_plain_draft_is_not_a_package() -> None:
    class PlainDraftOrchestrator(FakeOrchestrator):
        def get_content_publish_readiness(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "exists": True,
                "package_backed": False,
                "ready": False,
                "status": "draft",
                "blockers": ["This is a plain topic draft."],
            }

    message = FakeMessage("/prepare_publish 3")
    run_async(
        handlers.prepare_publish(
            FakeUpdate(message), FakeContext(PlainDraftOrchestrator())
        )
    )

    assert message.replies[0]["text"] == (
        "Post #3 is a plain topic draft, not a publishable content package. "
        "Use /content_opportunities, then /prepare_content <opportunity_id>."
    )


def test_content_package_explains_existing_plain_draft() -> None:
    class PlainDraftOrchestrator(FakeOrchestrator):
        def get_content_publish_readiness(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "exists": True,
                "package_backed": False,
                "ready": False,
                "status": "draft",
                "blockers": ["This is a plain topic draft."],
            }

    message = FakeMessage("/content_package 3")
    run_async(
        handlers.content_package(
            FakeUpdate(message), FakeContext(PlainDraftOrchestrator())
        )
    )

    assert "exists, but it is a plain topic draft" in message.replies[0]["text"]


def test_revise_content_passes_human_storytelling_notes() -> None:
    class RevisionOrchestrator(FakeOrchestrator):
        def revise_content_package(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append({"method": "revise_content_package", "kwargs": kwargs})
            return {
                "id": kwargs["post_id"],
                "status": "draft",
                "package_version": 2,
                "draft_text": "A warmer, cohesive narrative.",
                "alternative_hooks_json": "[]",
                "factual_claims_json": "[]",
                "image_source": "none",
                "image_alt_text": None,
            }

    orchestrator = RevisionOrchestrator()
    message = FakeMessage(
        "/revise_content 5 custom_revision Open with uncertainty and end warmly"
    )

    run_async(handlers.revise_content(FakeUpdate(message), FakeContext(orchestrator)))

    call = orchestrator.calls[0]
    assert call["method"] == "revise_content_package"
    assert call["kwargs"]["revision_notes"] == (
        "Open with uncertainty and end warmly"
    )
    assert "A warmer, cohesive narrative." in message.replies[0]["text"]


def test_confirm_publish_disabled_reports_nothing_published() -> None:
    class PublishOrchestrator(FakeOrchestrator):
        def confirm_linkedin_publish(self, request_id: int, *, database: str) -> dict[str, Any]:
            self.calls.append({"method": "confirm_linkedin_publish", "request_id": request_id, "database": database})
            return {"status": "disabled", "published": False, "message": "LinkedIn publishing is disabled. Nothing was published."}

    message = FakeMessage("/confirm_publish 8")
    run_async(handlers.confirm_publish(FakeUpdate(message), FakeContext(PublishOrchestrator())))
    assert message.replies[0]["text"] == "LinkedIn publishing is disabled. Nothing was published."


def test_confirm_publish_rejects_malformed_request_id_without_calling_orchestrator() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/confirm_publish stale")
    run_async(handlers.confirm_publish(FakeUpdate(message), FakeContext(orchestrator)))
    assert message.replies[0]["text"] == "Usage: /confirm_publish <request_id>"
    assert orchestrator.calls == []


def test_linkedin_publish_diagnostics_is_read_only_and_always_replies() -> None:
    orchestrator = FakeOrchestrator()
    message = FakeMessage("/linkedin_publish_diagnostics")
    run_async(
        handlers.linkedin_publish_diagnostics(
            FakeUpdate(message), FakeContext(orchestrator)
        )
    )
    text = message.replies[0]["text"]
    assert "Mode: disabled" in text
    assert "Pending: 2" in text
    assert "Uncertain: 1" in text
    assert "request 7: publish_uncertain (timeout)" in text
    assert orchestrator.calls == [
        {"method": "get_linkedin_publish_diagnostics", "kwargs": {"database": "test.db"}}
    ]
