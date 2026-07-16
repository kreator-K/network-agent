"""Phase 8C scoring, opportunity, and feedback regression tests."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agents.signal_intelligence_agent import SignalIntelligenceAgent, SignalIntelligenceError
from db.database import connect, initialize_database, signal_scoring_config_hash
from integrations.public_signal_gateway import RawFeedItem


class FakeSemanticModel:
    """Captures semantic calls without any provider access."""

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        *,
        fallback_used: bool = False,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fallback_used = fallback_used
        self.result = result or {
            "semantic_profile_relevance": 80.0,
            "personal_angle_availability": 20.0,
            "audience_interest_potential": 70.0,
            "humor_suitability": 10.0,
            "generic_commentary_risk": 20.0,
            "factual_risk": 10.0,
            "suggested_treatment": "analytical observation",
            "explanation": "Clear product relevance.",
            "confidence": 0.8,
        }

    def run_task(self, task_type: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"task_type": task_type, "prompt": prompt, **kwargs})
        return {
            "task_type": task_type,
            "mode": "mock" if self.fallback_used else "model",
            "fallback_used": self.fallback_used,
            "fallback_reason": "provider unavailable" if self.fallback_used else None,
            "result": self.result,
        }


def _database_path(tmp_path: Path) -> Path:
    path = tmp_path / "network_agent.db"
    initialize_database(path)
    return path


def _scorable_signal(agent: SignalIntelligenceAgent, database: Path) -> int:
    source = agent.add_source("Official product source", "https://example.com/feed", database=database)
    agent.set_source_approval(source.id or 0, "approved", database)
    agent.set_source_enabled(source.id or 0, True, database)
    item = RawFeedItem(
        external_id="current-ai-product",
        title="AI product strategy for product managers at Cornell Tech",
        summary="A practical analysis of AI-enabled product strategy and product leadership.",
        author="Editorial team",
        published_at=datetime.now(UTC).isoformat(),
        updated_at=None,
        link="https://example.com/ai-product-strategy",
        raw_metadata={},
    )
    return agent.persist_signal(source.id or 0, item, database)["signal"].id or 0


def test_default_scoring_config_is_versioned_and_single_active(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    with connect(database) as connection:
        rows = connection.execute("SELECT * FROM signal_scoring_config").fetchall()
    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert rows[0]["is_active"] == 1
    assert rows[0]["config_hash"] == signal_scoring_config_hash(rows[0]["config_json"])


def test_invalid_scoring_config_weights_fail_validation(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    with connect(database) as connection:
        config = json.loads(connection.execute("SELECT config_json FROM signal_scoring_config").fetchone()[0])
    config["weights"]["topic_relevance"] = 2
    from db.database import canonical_signal_scoring_config_json

    with pytest.raises(ValueError, match="between 0 and 1"):
        canonical_signal_scoring_config_json(config)


def test_ineligible_duplicate_never_calls_model(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    model = FakeSemanticModel()
    agent = SignalIntelligenceAgent(model_agent=model)
    signal_id = _scorable_signal(agent, database)
    with connect(database) as connection:
        connection.execute("UPDATE signals SET status = 'duplicate' WHERE id = ?", (signal_id,))
    result = agent.score_signal(signal_id, database)
    assert result["eligible"] is False
    assert model.calls == []


def test_scoring_preserves_profile_and_configuration_versions(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    agent = SignalIntelligenceAgent(model_agent=FakeSemanticModel())
    result = agent.score_signal(_scorable_signal(agent, database), database)
    assert result["eligible"] is True
    assert result["score"]["profile_version"] == 1
    assert result["score"]["scoring_config_version"] == 1
    with connect(database) as connection:
        row = connection.execute("SELECT status, score_json, profile_version, scoring_config_version FROM signals").fetchone()
    assert row["status"] == "scored"
    assert row["score_json"]
    assert (row["profile_version"], row["scoring_config_version"]) == (1, 1)


def test_invalid_semantic_output_falls_back_to_deterministic_only(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    agent = SignalIntelligenceAgent(model_agent=FakeSemanticModel({"bad": "shape"}))
    result = agent.score_signal(_scorable_signal(agent, database), database)
    assert result["mode"] == "deterministic_fallback"
    assert result["score"]["semantic"] is None


def test_model_fallback_does_not_apply_zero_mock_semantic_scores(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    model = FakeSemanticModel(
        {
            "semantic_profile_relevance": 0.0,
            "personal_angle_availability": 0.0,
            "audience_interest_potential": 0.0,
            "humor_suitability": 0.0,
            "generic_commentary_risk": 0.0,
            "factual_risk": 0.0,
            "suggested_treatment": "mock",
            "explanation": "mock",
            "confidence": 0.0,
        },
        fallback_used=True,
    )
    agent = SignalIntelligenceAgent(model_agent=model)

    result = agent.score_signal(_scorable_signal(agent, database), database)

    assert result["mode"] == "deterministic_fallback"
    assert result["score"]["semantic"] is None
    assert result["score"]["confidence"] == 0.7
    assert result["fallback_reason"] == "provider unavailable"


def test_qualifying_signal_creates_pre_draft_opportunity(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    agent = SignalIntelligenceAgent(model_agent=FakeSemanticModel())
    signal_id = _scorable_signal(agent, database)
    agent.score_signal(signal_id, database)
    opportunity = agent.generate_content_opportunity(signal_id, database)
    assert opportunity is not None
    assert opportunity.primary_signal_id == signal_id
    assert opportunity.status == "candidate"
    assert "draft_text" not in opportunity.metadata_json
    assert json.loads(opportunity.source_references_json)[0]["signal_id"] == signal_id


def test_duplicate_active_opportunity_is_prevented(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    agent = SignalIntelligenceAgent(model_agent=FakeSemanticModel())
    signal_id = _scorable_signal(agent, database)
    agent.score_signal(signal_id, database)
    first = agent.generate_content_opportunity(signal_id, database)
    second = agent.generate_content_opportunity(signal_id, database)
    assert first is not None and second is not None
    assert first.id == second.id


def test_dismissed_opportunity_cannot_be_selected_without_restore(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    agent = SignalIntelligenceAgent(model_agent=FakeSemanticModel())
    signal_id = _scorable_signal(agent, database)
    agent.score_signal(signal_id, database)
    opportunity = agent.generate_content_opportunity(signal_id, database)
    assert opportunity is not None
    agent.transition_content_opportunity(opportunity.id or 0, "dismissed", database)
    with pytest.raises(SignalIntelligenceError, match="explicit restore"):
        agent.transition_content_opportunity(opportunity.id or 0, "selected", database)


def test_feedback_does_not_change_profile_or_scoring_weights(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    agent = SignalIntelligenceAgent(model_agent=FakeSemanticModel())
    signal_id = _scorable_signal(agent, database)
    with connect(database) as connection:
        profile_before = connection.execute("SELECT profile_json FROM personal_brand_profile WHERE is_active = 1").fetchone()[0]
        config_before = connection.execute("SELECT config_json FROM signal_scoring_config WHERE is_active = 1").fetchone()[0]
    agent.record_preference("signal", signal_id, "more_like_this", database)
    with connect(database) as connection:
        profile_after = connection.execute("SELECT profile_json FROM personal_brand_profile WHERE is_active = 1").fetchone()[0]
        config_after = connection.execute("SELECT config_json FROM signal_scoring_config WHERE is_active = 1").fetchone()[0]
        feedback = connection.execute("SELECT feedback_type FROM content_preference_feedback").fetchone()[0]
    assert (profile_before, config_before, feedback) == (profile_after, config_after, "more_like_this")
