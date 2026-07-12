"""Focused Phase 8D package lifecycle tests."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agents.content_inspiration_agent import ContentInspirationAgent, ContentInspirationError
from agents.signal_intelligence_agent import SignalIntelligenceAgent
from db.database import initialize_database
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
