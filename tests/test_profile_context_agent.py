"""Tests for ProfileContextAgent."""

from typing import Any

from agents.profile_context_agent import ProfileContextAgent
from db.models import Prospect


def _prospect(**overrides: object) -> Prospect:
    data: dict[str, Any] = {
        "name": "Ada Lovelace",
        "created_at": "2026-01-01",
        "updated_at": "2026-01-01",
    }
    data.update(overrides)
    return Prospect(**data)


def test_build_context_extracts_available_fields() -> None:
    prospect = _prospect(
        role_title="Research Lead",
        company="Analytical Engines",
        location="London",
        notes="Met after a public talk about computing.",
    )

    context = ProfileContextAgent().build_context(prospect)

    assert context == {
        "role_title": "Research Lead",
        "company": "Analytical Engines",
        "location": "London",
        "talking_points": ["Met after a public talk about computing."],
        "has_sufficient_context": True,
    }


def test_build_context_has_sufficient_context_true_with_two_fields() -> None:
    prospect = _prospect(role_title="Research Lead", company="Analytical Engines")

    context = ProfileContextAgent().build_context(prospect)

    assert context["has_sufficient_context"] is True


def test_build_context_has_sufficient_context_false_with_only_one_field() -> None:
    prospect = _prospect(role_title="Research Lead")

    context = ProfileContextAgent().build_context(prospect)

    assert context["has_sufficient_context"] is False


def test_build_context_handles_all_fields_missing() -> None:
    prospect = _prospect()

    context = ProfileContextAgent().build_context(prospect)

    assert context == {
        "role_title": None,
        "company": None,
        "location": None,
        "talking_points": [],
        "has_sufficient_context": False,
    }


def test_summarize_for_prompt_produces_clean_text_block() -> None:
    context = {
        "role_title": "Research Lead",
        "company": "Analytical Engines",
        "location": "London",
        "talking_points": ["Met after a public talk about computing."],
        "has_sufficient_context": True,
    }

    summary = ProfileContextAgent().summarize_for_prompt(context)

    assert summary == (
        "Role title: Research Lead\n"
        "Company: Analytical Engines\n"
        "Location: London\n"
        "Talking points:\n"
        "- Met after a public talk about computing."
    )


def test_summarize_for_prompt_returns_empty_string_for_empty_context() -> None:
    summary = ProfileContextAgent().summarize_for_prompt({})

    assert summary == ""


def test_flag_insufficient_context_lists_missing_fields() -> None:
    prospect = _prospect(role_title="Research Lead")

    result = ProfileContextAgent().flag_insufficient_context(prospect)

    assert result["sufficient"] is False
    assert result["missing_fields"] == ["company", "notes"]


def test_flag_insufficient_context_provides_recommendation() -> None:
    prospect = _prospect(company="Analytical Engines")

    result = ProfileContextAgent().flag_insufficient_context(prospect)

    assert "Add notes about how you found this person" in result["recommendation"]
