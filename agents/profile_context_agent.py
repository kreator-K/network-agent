"""Profile context extraction agent.

MVP simplification: this agent does not call an LLM. It structures only the
manual prospect fields the user has already provided. Future phases may route
richer profile text extraction through ModelOrchestrationAgent.
"""

from typing import Any

from db.models import Prospect


CORE_CONTEXT_FIELDS = ("role_title", "company", "notes")


class ProfileContextAgent:
    """Extract safe personalization signals from user-provided context.

    Purpose:
        Identify usable facts from supplied prospect fields and notes without
        inventing missing context.
    Inputs:
        Prospect role title, company, location, and user-provided notes.
    Outputs:
        Prompt-ready personalization context and missing-field guidance.
    """

    def build_context(self, prospect: Prospect) -> dict[str, Any]:
        """Build structured context from manually supplied prospect fields."""
        talking_points = _extract_talking_points(prospect.notes)
        return {
            "role_title": _clean_optional(prospect.role_title),
            "company": _clean_optional(prospect.company),
            "location": _clean_optional(prospect.location),
            "talking_points": talking_points,
            "has_sufficient_context": _has_sufficient_context(prospect),
        }

    def summarize_for_prompt(self, context: dict[str, Any]) -> str:
        """Convert context into a clean prompt-ready text block."""
        lines: list[str] = []
        role_title = _clean_optional(context.get("role_title"))
        company = _clean_optional(context.get("company"))
        location = _clean_optional(context.get("location"))
        talking_points = context.get("talking_points")

        if role_title:
            lines.append(f"Role title: {role_title}")
        if company:
            lines.append(f"Company: {company}")
        if location:
            lines.append(f"Location: {location}")
        if isinstance(talking_points, list):
            clean_points = [
                point.strip()
                for point in talking_points
                if isinstance(point, str) and point.strip()
            ]
            if clean_points:
                lines.append("Talking points:")
                lines.extend(f"- {point}" for point in clean_points)

        return "\n".join(lines)

    def flag_insufficient_context(self, prospect: Prospect) -> dict[str, Any]:
        """Return missing-field guidance for stronger personalization."""
        context = self.build_context(prospect)
        missing_fields = [
            field
            for field in CORE_CONTEXT_FIELDS
            if not _clean_optional(getattr(prospect, field))
        ]
        sufficient = bool(context["has_sufficient_context"])
        return {
            "sufficient": sufficient,
            "missing_fields": missing_fields,
            "recommendation": _recommendation_for_missing_fields(missing_fields),
        }


def _extract_talking_points(notes: str | None) -> list[str]:
    cleaned = _clean_optional(notes)
    if cleaned is None:
        return []
    return [cleaned]


def _has_sufficient_context(prospect: Prospect) -> bool:
    available_count = sum(
        1 for field in CORE_CONTEXT_FIELDS if _clean_optional(getattr(prospect, field))
    )
    return available_count >= 2


def _recommendation_for_missing_fields(missing_fields: list[str]) -> str:
    if "notes" in missing_fields:
        return (
            "Add notes about how you found this person or a shared interest for "
            "a stronger connection request."
        )
    if "role_title" in missing_fields:
        return "Add the prospect's role title to make the outreach more specific."
    if "company" in missing_fields:
        return "Add the prospect's company to ground the outreach in context."
    return "Enough context is available for a personalized draft."


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = " ".join(value.strip().split())
    return cleaned or None
