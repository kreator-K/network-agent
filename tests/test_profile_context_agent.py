"""Tests for ProfileContextAgent."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agents.profile_context_agent import ProfileContextAgent
from db.database import connect, initialize_database
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


def _brand_profile(**overrides: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "professional_identity": "Tech MBA product professional",
        "content_pillars": ["AI products", "Product strategy"],
        "target_audiences": ["Product managers", "Founders"],
        "verified_experiences": ["Cornell Tech coursework"],
        "allowed_personal_claims": ["I studied at Cornell Tech"],
        "topics_to_avoid": ["Unsupported rumors"],
    }
    data.update(overrides)
    return data


def test_personal_brand_profile_validation_trims_strings_and_lists() -> None:
    profile = ProfileContextAgent().validate_personal_brand_profile(
        _brand_profile(
            professional_identity="  Tech MBA   product professional ",
            content_pillars=[" AI products ", "Product strategy"],
        )
    )

    assert profile.professional_identity == "Tech MBA product professional"
    assert profile.content_pillars == ["AI products", "Product strategy"]


def test_voice_dna_fields_are_validated_and_rendered_for_prompts() -> None:
    agent = ProfileContextAgent()
    profile = agent.validate_personal_brand_profile(
        _brand_profile(
            voice_sentence_rhythm=[" Short opening.  Compact explanation. "],
            voice_vocabulary_to_avoid=[" game-changer "],
            voice_formatting_rules=["No hashtags"],
            voice_point_of_view=["First person only for verified experience"],
            brand_name="kreator_K",
            visual_colors=["Primary blue #2D5BFF"],
            cta_style="Follow for useful trends.",
        )
    )

    assert profile.voice_sentence_rhythm == ["Short opening. Compact explanation."]
    context = agent.build_personal_brand_context(profile)
    assert "Voice sentence rhythm: Short opening. Compact explanation." in context
    assert "Voice vocabulary to avoid: game-changer" in context
    assert "Voice formatting rules: No hashtags" in context
    assert "Brand name: kreator_K" in context
    assert "Visual colors: Primary blue #2D5BFF" in context
    assert "CTA style: Follow for useful trends." in context


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": ""},
        {"content_pillars": []},
        {"target_audiences": []},
        {"content_pillars": [" "]},
        {"unknown_field": "not allowed"},
    ],
)
def test_personal_brand_profile_rejects_invalid_structure(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        ProfileContextAgent().validate_personal_brand_profile(
            _brand_profile(**overrides)
        )


def test_personal_brand_profile_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ValidationError):
        ProfileContextAgent().validate_personal_brand_profile(
            _brand_profile(schema_version="2.0")
        )


def test_personal_brand_profile_versions_are_immutable_and_context_is_deterministic(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "network_agent.db"
    initialize_database(
        database_path,
        personal_brand_profile_path=tmp_path / "missing_profile_seed.json",
    )
    agent = ProfileContextAgent()

    first = agent.save_profile(_brand_profile(), database_path)
    second = agent.save_profile(
        _brand_profile(content_pillars=["AI products", "Business strategy"]),
        database_path,
    )

    assert first.version == 1
    assert first.is_active is True
    assert second.version == 2
    assert second.is_active is True
    assert agent.get_profile(1, database_path).is_active is False
    active_profile = agent.get_active_profile(database_path)
    assert active_profile is not None
    assert active_profile.version == 2
    assert agent.build_personal_brand_context(second) == (
        "Professional identity: Tech MBA product professional\n"
        "Content pillars: AI products, Business strategy\n"
        "Target audiences: Product managers, Founders\n"
        "Verified experiences: Cornell Tech coursework\n"
        "Allowed personal claims: I studied at Cornell Tech\n"
        "Topics to avoid: Unsupported rumors"
    )

    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT version, is_active, profile_hash FROM personal_brand_profile ORDER BY version"
        ).fetchall()
    assert [(row["version"], row["is_active"]) for row in rows] == [(1, 0), (2, 1)]
    assert rows[0]["profile_hash"] != rows[1]["profile_hash"]


def test_personal_brand_profile_can_reactivate_prior_version(tmp_path: Path) -> None:
    database_path = tmp_path / "network_agent.db"
    initialize_database(
        database_path,
        personal_brand_profile_path=tmp_path / "missing_profile_seed.json",
    )
    agent = ProfileContextAgent()
    agent.save_profile(_brand_profile(), database_path)
    agent.save_profile(_brand_profile(content_pillars=["Strategy"]), database_path)

    active = agent.activate_profile(1, database_path)

    assert active.version == 1
    assert active.is_active is True
    assert agent.get_profile(2, database_path).is_active is False


def test_personal_brand_seed_loads_once_and_never_overwrites_sqlite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "network_agent.db"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(_brand_profile()), encoding="utf-8")

    initialize_database(database_path, personal_brand_profile_path=seed_path)
    agent = ProfileContextAgent()
    initial = agent.get_active_profile(database_path)
    assert initial is not None
    assert initial.version == 1

    seed_path.write_text(
        json.dumps(_brand_profile(professional_identity="Different identity")),
        encoding="utf-8",
    )
    initialize_database(database_path, personal_brand_profile_path=seed_path)
    unchanged = agent.get_active_profile(database_path)
    assert unchanged is not None
    assert unchanged.profile_json == initial.profile_json
    assert len(agent.list_profile_versions(database_path)) == 1


def test_invalid_or_missing_personal_brand_seed_is_safe(tmp_path: Path) -> None:
    database_path = tmp_path / "invalid_seed.db"
    invalid_seed = tmp_path / "invalid_seed.json"
    invalid_seed.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="seed is invalid"):
        initialize_database(database_path, personal_brand_profile_path=invalid_seed)

    missing_database_path = tmp_path / "missing_seed.db"
    initialize_database(
        missing_database_path,
        personal_brand_profile_path=tmp_path / "absent.json",
    )
    assert ProfileContextAgent().get_active_profile(missing_database_path) is None
