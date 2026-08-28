"""Focused Phase 8D package lifecycle tests."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agents.content_inspiration_agent import ContentInspirationAgent, ContentInspirationError
from agents.signal_intelligence_agent import SignalIntelligenceAgent
from db.database import connect, initialize_database
from integrations.public_signal_gateway import RawFeedItem


class FakeModel:
    def run_task(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = (prompt, expected_schema)
        return {"task_type": task_type, "mode": "mock", "fallback_used": False, "result": {"primary_post": "mock"}}


class NarrativeModel(FakeModel):
    def __init__(self) -> None:
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
        if task_type == "content_package_generation":
            primary = "Most roadmap reviews skip the one question that matters: what would make us stop."
            result = {
                "primary_post": primary,
                "alternative_hooks": [
                    {"text": "The demo worked. That is not the same as ready.", "rationale": "Leads with the gap between capability and trust."},
                    {"text": "Nobody asked what evidence would change the call.", "rationale": "Names the missing step directly."},
                ],
                "variants": [
                    {"label": "Variant 1", "hook_archetype": "Evidence gap", "funnel_position": "MOF", "post_text": primary},
                    {"label": "Variant 2", "hook_archetype": "Practical distinction", "funnel_position": "MOF", "post_text": "A roadmap is a decision record, not a feature queue.\n\nThe source makes the evidence gap visible."},
                    {"label": "Variant 3", "hook_archetype": "Decision consequence", "funnel_position": "MOF", "post_text": "The expensive mistake is scaling before the evidence supports it.\n\nThe source gives teams a useful checkpoint."},
                ],
                "hook_ab": {
                    "hook_a": "The demo worked. That is not the same as ready.",
                    "hook_b": "Nobody asked what evidence would change the call.",
                },
                "flop_adjustment": "Shorten the setup and lead with the source-backed decision consequence.",
            }
        else:
            result = {
                "primary_post": (
                    "A system can look certain long before people can trust it.\n\n"
                    "That gap is where product judgment becomes human: someone must "
                    "decide what evidence is enough, whose risk matters, and when to pause.\n\n"
                    "The most useful question is not whether the technology works. "
                    "It is whether the people affected can understand when it might not."
                )
            }
        return {
            "task_type": task_type,
            "mode": "model",
            "fallback_used": False,
            "result": result,
        }


def _opportunity(tmp_path: Path) -> tuple[Path, int]:
    database = tmp_path / "network.db"
    initialize_database(database)
    agent = SignalIntelligenceAgent()
    source = agent.add_source("Example", "https://example.com/feed", database=database)
    agent.set_source_approval(source.id or 0, "approved", database)
    agent.set_source_enabled(source.id or 0, True, database)
    signal = agent.persist_signal(source.id or 0, RawFeedItem("one", "AI product strategy for product managers at Cornell Tech", "Practical AI product strategy and product leadership analysis for product managers.", "Editor", datetime.now(UTC).isoformat(), None, "https://example.com/item", {}), database)["signal"]
    agent.score_signal(signal.id or 0, database)
    opportunity = agent.generate_content_opportunity(signal.id or 0, database)
    assert opportunity is not None
    return database, opportunity.id or 0


def test_selected_opportunity_creates_source_traced_package(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    post = ContentInspirationAgent(FakeModel()).generate_package_from_opportunity(opportunity_id, database)
    assert post.opportunity_id == opportunity_id
    assert post.draft_text
    assert post.source_references_json
    assert post.profile_version == 1
    assert post.scoring_config_version == 1
    assert "A practical review starts with three checks" in post.draft_text
    assert "My takeaway: Analyze" not in post.draft_text
    package = json.loads(post.package_json or "{}")
    assert len(package["variants"]) == 3
    assert package["selected_variant"] == 1
    assert package["variants"][0]["post_text"] == post.draft_text
    assert package["content_plan"]["funnel_position"] in {"TOF", "MOF", "BOF"}
    assert package["hook_ab"]["hook_a"]
    assert package["flop_adjustment"]


def test_valid_model_output_replaces_deterministic_template_and_hooks(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    model = NarrativeModel()
    post = ContentInspirationAgent(model).generate_package_from_opportunity(opportunity_id, database)
    assert post.draft_text == "Most roadmap reviews skip the one question that matters: what would make us stop."
    assert "A practical review starts with three checks" not in post.draft_text
    package = json.loads(post.package_json or "{}")
    hook_texts = [hook["text"] for hook in package["alternative_hooks"]]
    assert "The demo worked. That is not the same as ready." in hook_texts
    assert package["variants"][1]["post_text"].startswith("A roadmap is a decision record")
    assert package["hook_ab"]["hook_b"] == "Nobody asked what evidence would change the call."
    assert package["flop_adjustment"].startswith("Shorten the setup")
    package_call = next(call for call in model.calls if call["task_type"] == "content_package_generation")
    assert "Do not default to a fixed listicle formula" in package_call["prompt"]
    assert "AI product strategy for product managers at Cornell Tech" in package_call["prompt"]
    assert "Voice DNA" in package_call["prompt"]
    assert "variants: exactly 3 objects" in package_call["prompt"]
    assert "Primary blue #2D5BFF" in package_call["prompt"]
    assert "Simple and direct" in package_call["prompt"]


def test_selecting_variant_versions_package_and_resets_approval(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    agent = ContentInspirationAgent(NarrativeModel())
    original = agent.generate_package_from_opportunity(opportunity_id, database)
    with connect(database) as connection:
        connection.execute(
            "UPDATE content_posts SET status = 'approved_for_later_posting', approved_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), original.id),
        )
        connection.commit()

    selected = agent.select_variant(original.id or 0, 2, database)

    package = json.loads(selected.package_json or "{}")
    assert selected.package_version == 2
    assert selected.status == "draft"
    assert selected.approved_at is None
    assert package["selected_variant"] == 2
    assert selected.draft_text == package["variants"][1]["post_text"]
    with connect(database) as connection:
        versions = connection.execute(
            "SELECT package_version, revision_type FROM content_post_versions WHERE content_post_id = ? ORDER BY package_version",
            (original.id,),
        ).fetchall()
    assert [(row["package_version"], row["revision_type"]) for row in versions] == [
        (1, "initial_package"),
        (2, "select_variant"),
    ]


def test_mock_image_package_has_alt_text(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    post = ContentInspirationAgent(FakeModel()).generate_package_from_opportunity(opportunity_id, database, "mock")
    assert post.image_source == "generated"
    assert post.image_alt_text


def test_unresolved_claim_blocks_approval_validation(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    agent = ContentInspirationAgent(FakeModel())
    post = agent.generate_package_from_opportunity(opportunity_id, database)
    from db.database import connect
    with connect(database) as connection:
        connection.execute("UPDATE content_posts SET factual_claims_json = '[{\"source_signal_ids\":[1],\"confirmation_required\":true}]' WHERE id = ?", (post.id,))
        changed = agent.get_package(post.id or 0, connection)
    assert "requires confirmation" in agent.validate_package_for_approval(changed)[0]


def test_dismissed_opportunity_cannot_create_package(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    from db.database import connect
    with connect(database) as connection:
        connection.execute("UPDATE content_opportunities SET status = 'dismissed' WHERE id = ?", (opportunity_id,))
    with pytest.raises(ContentInspirationError, match="Dismissed"):
        ContentInspirationAgent(FakeModel()).generate_package_from_opportunity(opportunity_id, database)


def test_revision_rewrites_whole_post_and_preserves_distinct_versions(
    tmp_path: Path,
) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    agent = ContentInspirationAgent(FakeModel())
    original = agent.generate_package_from_opportunity(opportunity_id, database)

    revised = agent.revise_package(
        original.id or 0,
        "make_more_personal",
        database,
    )

    assert revised.package_version == 2
    assert revised.draft_text != original.draft_text
    assert original.draft_text not in revised.draft_text
    assert "I keep returning" in revised.draft_text
    with connect(database) as connection:
        versions = connection.execute(
            """
            SELECT package_version, draft_text, revision_type
            FROM content_post_versions
            WHERE content_post_id = ?
            ORDER BY package_version
            """,
            (original.id,),
        ).fetchall()
    assert [row["package_version"] for row in versions] == [1, 2]
    assert versions[0]["draft_text"] != versions[1]["draft_text"]
    assert versions[1]["revision_type"] == "make_more_personal"


def test_custom_revision_notes_reach_storytelling_prompt(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    model = NarrativeModel()
    agent = ContentInspirationAgent(model)
    post = agent.generate_package_from_opportunity(opportunity_id, database)

    revised = agent.revise_package(
        post.id or 0,
        "custom_revision",
        database,
        revision_notes="Open with uncertainty and make the ending warmer",
    )

    revision_call = model.calls[-1]
    assert revision_call["task_type"] == "content_analytical_revision"
    assert "Open with uncertainty and make the ending warmer" in revision_call["prompt"]
    assert revised.draft_text.startswith("A system can look certain")


def test_revision_resets_approval_and_rejected_package_cannot_revise(
    tmp_path: Path,
) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    agent = ContentInspirationAgent(FakeModel())
    post = agent.generate_package_from_opportunity(opportunity_id, database)
    with connect(database) as connection:
        connection.execute(
            "UPDATE content_posts SET status='approved_for_later_posting', "
            "approved_at='2026-01-01' WHERE id=?",
            (post.id,),
        )
    revised = agent.revise_package(post.id or 0, "make_more_analytical", database)
    assert revised.status == "draft"
    assert revised.approved_at is None

    with connect(database) as connection:
        connection.execute(
            "UPDATE content_posts SET status='discarded' WHERE id=?",
            (post.id,),
        )
    with pytest.raises(ContentInspirationError, match="cannot be revised"):
        agent.revise_package(post.id or 0, "make_more_personal", database)


def test_custom_revision_requires_human_notes(tmp_path: Path) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    agent = ContentInspirationAgent(FakeModel())
    post = agent.generate_package_from_opportunity(opportunity_id, database)

    with pytest.raises(ContentInspirationError, match="require revision notes"):
        agent.revise_package(post.id or 0, "custom_revision", database)


def test_four_revision_styles_create_four_distinct_post_bodies(
    tmp_path: Path,
) -> None:
    database, opportunity_id = _opportunity(tmp_path)
    agent = ContentInspirationAgent(FakeModel())
    post = agent.generate_package_from_opportunity(opportunity_id, database)
    texts = {post.draft_text}

    for revision_type in (
        "make_more_personal",
        "make_more_analytical",
        "make_funnier",
        "make_more_concise",
    ):
        post = agent.revise_package(post.id or 0, revision_type, database)
        assert post.draft_text not in texts
        texts.add(post.draft_text)

    assert post.package_version == 5
    with connect(database) as connection:
        versions = connection.execute(
            """
            SELECT package_version, draft_text
            FROM content_post_versions
            WHERE content_post_id = ?
            ORDER BY package_version
            """,
            (post.id,),
        ).fetchall()
    assert [row["package_version"] for row in versions] == [1, 2, 3, 4, 5]
    assert len({row["draft_text"] for row in versions}) == 5
