"""Tests for draft-only outreach generation."""

from typing import Any

import pytest

from agents.outreach_draft_agent import (
    DraftTooLongError,
    InvalidAskTypeError,
    OutreachDraftAgent,
)
from db.models import Interaction, Prospect


class FakeModelOrchestrationAgent:
    """Captures model requests and returns a configurable draft."""

    def __init__(self, draft_text: str = "Hi Ada, your computing work stood out. Open to a quick chat?") -> None:
        self.draft_text = draft_text
        self.calls: list[dict[str, Any]] = []

    def run_task(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "task_type": task_type,
                "prompt": prompt,
                "expected_schema": expected_schema,
            }
        )
        return {
            "task_type": task_type,
            "mode": "mock",
            "fallback_used": False,
            "result": {"draft_text": self.draft_text},
        }


def _prospect() -> Prospect:
    return Prospect(
        id=7,
        name="Ada Lovelace",
        role_title="Research Lead",
        company="Analytical Engines",
        location="London",
        notes="User met her after a public talk about computing.",
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )


def test_draft_connection_request_returns_expected_metadata() -> None:
    model = FakeModelOrchestrationAgent()

    result = OutreachDraftAgent(model).draft_connection_request(
        _prospect(),
        "career_guidance",
    )

    assert result == {
        "prospect_id": 7,
        "draft_text": model.draft_text,
        "ask_type": "career_guidance",
        "character_count": len(model.draft_text),
        "mode": "mock",
        "fallback_used": False,
        "core_intent_warning": None,
    }


def test_draft_connection_request_uses_model_boundary_and_safe_prompt() -> None:
    model = FakeModelOrchestrationAgent()

    OutreachDraftAgent(model).draft_connection_request(_prospect(), "resume_review")

    call = model.calls[0]
    assert call["task_type"] == "outreach_draft"
    assert call["expected_schema"] == {"draft_text": str}
    assert "Do not invent shared connections" in call["prompt"]
    assert "300 characters or fewer" in call["prompt"]
    assert "Ada Lovelace" in call["prompt"]
    assert "Research Lead" in call["prompt"]
    assert "Analytical Engines" in call["prompt"]


def test_draft_connection_request_omits_missing_fields_from_prompt() -> None:
    model = FakeModelOrchestrationAgent()
    prospect = Prospect(
        id=8,
        name="Grace Hopper",
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )

    OutreachDraftAgent(model).draft_connection_request(prospect, "general_chat")

    prompt = model.calls[0]["prompt"]
    assert "Grace Hopper" in prompt
    assert "Role title:" not in prompt
    assert "Company:" not in prompt
    assert "Location:" not in prompt
    assert "Notes:" not in prompt


def test_draft_connection_request_rejects_invalid_ask_type() -> None:
    with pytest.raises(InvalidAskTypeError, match="Invalid ask_type"):
        OutreachDraftAgent(FakeModelOrchestrationAgent()).draft_connection_request(
            _prospect(),
            "job_referral",  # type: ignore[arg-type]
        )


def test_draft_connection_request_rejects_over_300_characters() -> None:
    model = FakeModelOrchestrationAgent("x" * 301)

    with pytest.raises(DraftTooLongError, match="limit is 300"):
        OutreachDraftAgent(model).draft_connection_request(_prospect(), "general_chat")


def test_draft_followup_message_uses_history_and_followup_task() -> None:
    model = FakeModelOrchestrationAgent("Just following up on my earlier note.")
    history = [
        Interaction(
            id=1,
            prospect_id=7,
            interaction_type="outreach_draft",
            content="First message",
            direction="outbound_draft",
            created_at="2026-01-01",
        ),
        Interaction(
            id=2,
            prospect_id=7,
            interaction_type="reply_logged",
            content="Thanks for reaching out.",
            direction="inbound_logged",
            created_at="2026-01-02",
        ),
    ]

    result = OutreachDraftAgent(model).draft_followup_message(_prospect(), history)

    assert result["draft_text"] == "Just following up on my earlier note."
    assert result["prospect_id"] == 7
    call = model.calls[0]
    assert call["task_type"] == "followup_draft"
    assert "First message" in call["prompt"]
    assert "Thanks for reaching out." in call["prompt"]
    assert "Do not repeat the prior message" in call["prompt"]


def test_draft_followup_message_rejects_over_limit() -> None:
    model = FakeModelOrchestrationAgent("x" * 1001)

    with pytest.raises(DraftTooLongError, match="limit is 1000"):
        OutreachDraftAgent(model).draft_followup_message(_prospect(), [])


def test_validate_against_core_intent_flags_fabrication_language() -> None:
    result = OutreachDraftAgent(
        FakeModelOrchestrationAgent()
    ).validate_against_core_intent(
        "I noticed our mutual connection and shared experience in AI.",
        [
            {
                "rule_key": "no_fabrication",
                "description": "No invented shared connections or shared experiences.",
            }
        ],
    )

    assert result["passed"] is False
    assert "unstated shared connection" in result["warning"]
    assert result["matched_pattern"] is not None


def test_validate_against_core_intent_passes_clean_draft() -> None:
    result = OutreachDraftAgent(
        FakeModelOrchestrationAgent()
    ).validate_against_core_intent(
        "Hi Ada, your public talk on computing stood out. Open to a quick chat?",
        [
            {
                "rule_key": "no_fabrication",
                "description": "No invented shared connections or shared experiences.",
            }
        ],
    )

    assert result == {"passed": True, "warning": None, "matched_pattern": None}


def test_every_draft_includes_core_intent_validation_result() -> None:
    model = FakeModelOrchestrationAgent("Our mutual connection suggested I reach out.")
    agent = OutreachDraftAgent(model)

    connection = agent.draft_connection_request(_prospect(), "general_chat")
    followup = agent.draft_followup_message(_prospect(), [])

    assert "core_intent_warning" in connection
    assert connection["core_intent_warning"] is not None
    assert "core_intent_warning" in followup
    assert followup["core_intent_warning"] is not None
