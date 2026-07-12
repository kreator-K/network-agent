"""Draft-only LinkedIn outreach agent."""

import re
from typing import Any, Literal, Protocol, get_args

from agents.model_orchestration_agent import ModelOrchestrationAgent
from db.models import Interaction, Prospect


AskType = Literal["resume_review", "career_guidance", "general_chat"]
ALLOWED_ASK_TYPES = set(get_args(AskType))
CONNECTION_NOTE_LIMIT = 300
FOLLOWUP_MESSAGE_LIMIT = 1000
DEFAULT_CORE_INTENT_RULES = [
    {
        "rule_key": "no_fabrication",
        "rule_value": "true",
        "description": "Do not invent shared connections, shared experiences, skills, credentials, or unstated claims.",
    }
]
FABRICATION_PATTERNS = [
    r"\bwe (?:both|share|worked|studied|met|know)\b",
    r"\bour mutual\b",
    r"\bmutual connection\b",
    r"\bshared connection\b",
    r"\bshared experience\b",
    r"\bas a fellow\b",
    r"\bas someone with experience\b",
    r"\bmy experience at\b",
    r"\bi also worked at\b",
    r"\bi also studied at\b",
]


class OutreachDraftError(ValueError):
    """Base error for outreach draft failures."""


class InvalidAskTypeError(OutreachDraftError):
    """Raised when a connection request ask type is unsupported."""


class DraftTooLongError(OutreachDraftError):
    """Raised when a generated draft exceeds the allowed character limit."""


class ModelOrchestrator(Protocol):
    """Minimal model orchestration interface used by this agent."""

    def run_task(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a model task through the approved orchestration boundary."""


class OutreachDraftAgent:
    """Draft outreach messages for manual copy/paste sending.

    Purpose:
        Create LinkedIn connection-request and follow-up drafts while never
        sending outreach through any API.
    Inputs:
        Prospect records, safe personalization signals, relationship status,
        last-touch data, core intent, refinable parameters, and user tone
        instructions.
    Outputs:
        Draft outreach text, safety notes, and metadata indicating the user
        must manually send the draft in LinkedIn.
    """

    def __init__(
        self,
        model_orchestration_agent: ModelOrchestrator | None = None,
    ) -> None:
        """Create an outreach drafter using the approved model boundary."""
        self.model_orchestration_agent = (
            model_orchestration_agent or ModelOrchestrationAgent()
        )

    def draft_connection_request(self, prospect: Prospect, ask_type: AskType) -> dict:
        """Draft a LinkedIn connection request note for human review."""
        self._validate_ask_type(ask_type)
        prompt = self._build_connection_prompt(prospect, ask_type)
        response = self.model_orchestration_agent.run_task(
            task_type="outreach_draft",
            prompt=prompt,
            expected_schema={"draft_text": str},
        )
        draft_text = self._extract_draft_text(response)
        self._validate_length(draft_text, CONNECTION_NOTE_LIMIT)
        validation = self.validate_against_core_intent(
            draft_text,
            DEFAULT_CORE_INTENT_RULES,
        )
        return {
            "prospect_id": prospect.id,
            "draft_text": draft_text,
            "ask_type": ask_type,
            "character_count": len(draft_text),
            "mode": response["mode"],
            "fallback_used": response["fallback_used"],
            "core_intent_warning": validation["warning"],
        }

    def draft_followup_message(
        self,
        prospect: Prospect,
        history: list[Interaction],
    ) -> dict:
        """Draft a follow-up message using prior interaction history."""
        prompt = self._build_followup_prompt(prospect, history)
        response = self.model_orchestration_agent.run_task(
            task_type="followup_draft",
            prompt=prompt,
            expected_schema={"draft_text": str},
        )
        draft_text = self._extract_draft_text(response)
        self._validate_length(draft_text, FOLLOWUP_MESSAGE_LIMIT)
        validation = self.validate_against_core_intent(
            draft_text,
            DEFAULT_CORE_INTENT_RULES,
        )
        return {
            "prospect_id": prospect.id,
            "draft_text": draft_text,
            "character_count": len(draft_text),
            "mode": response["mode"],
            "fallback_used": response["fallback_used"],
            "core_intent_warning": validation["warning"],
        }

    def validate_against_core_intent(
        self,
        draft_text: str,
        core_intent_rules: list,
    ) -> dict:
        """Validate draft text against immutable safety intent rules.

        This local check is deliberately conservative and does not call a model.
        It returns a warning instead of mutating the draft so the caller can
        decide whether to reject, revise, or show the warning to the user.
        """
        active_rule_text = " ".join(
            str(rule.get("rule_key", "")) + " " + str(rule.get("description", ""))
            for rule in core_intent_rules
            if isinstance(rule, dict)
        ).lower()
        should_check_fabrication = (
            not core_intent_rules
            or "fabrication" in active_rule_text
            or "shared connection" in active_rule_text
            or "shared experience" in active_rule_text
        )

        if should_check_fabrication:
            matched_pattern = _find_fabrication_pattern(draft_text)
            if matched_pattern is not None:
                return {
                    "passed": False,
                    "warning": (
                        "Draft may imply an unstated shared connection, shared "
                        "experience, skill, credential, or relationship."
                    ),
                    "matched_pattern": matched_pattern,
                }

        return {"passed": True, "warning": None, "matched_pattern": None}

    def _validate_ask_type(self, ask_type: str) -> None:
        if ask_type not in ALLOWED_ASK_TYPES:
            allowed = ", ".join(sorted(ALLOWED_ASK_TYPES))
            raise InvalidAskTypeError(
                f"Invalid ask_type '{ask_type}'. Allowed values: {allowed}."
            )

    def _build_connection_prompt(self, prospect: Prospect, ask_type: AskType) -> str:
        prospect_context = _format_prospect_context(prospect)
        ask_instruction = {
            "resume_review": "Ask politely if they would be open to a brief resume review.",
            "career_guidance": "Ask politely if they would be open to sharing career guidance.",
            "general_chat": "Ask politely if they would be open to a brief general chat.",
        }[ask_type]

        return "\n".join(
            [
                "Draft a LinkedIn connection request note.",
                "The output must be JSON with key draft_text.",
                f"The draft_text must be {CONNECTION_NOTE_LIMIT} characters or fewer.",
                "Use only the prospect details provided below.",
                "Do not invent shared connections, shared experiences, skills, credentials, or facts the user has not stated.",
                "Write from the user's perspective as a job seeker; do not imply the user works or worked at the prospect's company.",
                "Do not claim the user has product management, AI, or industry experience unless the notes explicitly say so.",
                "Keep the tone professional and specific, not generic flattery.",
                "The message must be concise and suitable for manual copy/paste by the user.",
                ask_instruction,
                "",
                "Prospect details:",
                prospect_context,
            ]
        )

    def _build_followup_prompt(
        self,
        prospect: Prospect,
        history: list[Interaction],
    ) -> str:
        history_context = _format_history(history)
        return "\n".join(
            [
                "Draft a LinkedIn follow-up message for human review.",
                "The output must be JSON with key draft_text.",
                f"The draft_text must be {FOLLOWUP_MESSAGE_LIMIT} characters or fewer.",
                "Use only the prospect details and interaction history provided below.",
                "Do not invent shared connections, shared experiences, skills, credentials, or facts the user has not stated.",
                "Write from the user's perspective as a job seeker; do not imply the user works or worked at the prospect's company.",
                "Do not claim the user has product management, AI, or industry experience unless the notes explicitly say so.",
                "Do not repeat the prior message; acknowledge the existing thread when useful.",
                "Keep the tone professional, specific, concise, and non-pushy.",
                "The user will manually copy and send this draft in LinkedIn.",
                "",
                "Prospect details:",
                _format_prospect_context(prospect),
                "",
                "Interaction history:",
                history_context,
            ]
        )

    def _extract_draft_text(self, response: dict[str, Any]) -> str:
        result = response.get("result")
        if not isinstance(result, dict):
            raise OutreachDraftError("Model response result was not an object.")
        draft_text = result.get("draft_text")
        if not isinstance(draft_text, str) or not draft_text.strip():
            raise OutreachDraftError("Model response did not include draft_text.")
        return draft_text.strip()

    def _validate_length(self, draft_text: str, limit: int) -> None:
        if len(draft_text) > limit:
            raise DraftTooLongError(
                f"Generated draft is {len(draft_text)} characters; limit is {limit}."
            )


def _format_prospect_context(prospect: Prospect) -> str:
    fields = [
        ("Name", prospect.name),
        ("Role title", prospect.role_title),
        ("Company", prospect.company),
        ("Location", prospect.location),
        ("Notes", prospect.notes),
    ]
    present_fields = [f"- {label}: {value}" for label, value in fields if value]
    if present_fields:
        return "\n".join(present_fields)
    return "- No prospect details provided."


def _format_history(history: list[Interaction]) -> str:
    if not history:
        return "- No prior interactions."
    return "\n".join(
        f"- {item.created_at} | {item.interaction_type} | {item.direction}: {item.content or ''}"
        for item in history
    )


def _find_fabrication_pattern(draft_text: str) -> str | None:
    for pattern in FABRICATION_PATTERNS:
        if re.search(pattern, draft_text, flags=re.IGNORECASE):
            return pattern
    return None
