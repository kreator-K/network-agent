"""Deterministic cross-feature Phase 9 journeys with no provider writes."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.content_inspiration_agent import ContentInspirationAgent
from agents.orchestrator import NetworkOrchestrator
from agents.signal_intelligence_agent import SignalIntelligenceAgent
from db.database import initialize_database
from db.models import Prospect
from integrations.public_signal_gateway import RawFeedItem


class FakeSemanticModel:
    def run_task(self, task_type: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        _ = (task_type, prompt, kwargs)
        return {
            "task_type": "content_post_draft",
            "mode": "mock",
            "fallback_used": False,
            "result": {
                "semantic_profile_relevance": 80,
                "personal_angle_availability": 20,
                "audience_interest_potential": 70,
                "humor_suitability": 10,
                "generic_commentary_risk": 20,
                "factual_risk": 10,
                "suggested_treatment": "practical analysis",
                "explanation": "Stored public signal has a useful product angle.",
                "confidence": 0.8,
            },
        }


class FakeContentModel:
    def run_task(self, task_type: str, prompt: str, expected_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = (task_type, prompt, expected_schema)
        return {"task_type": task_type, "mode": "mock", "fallback_used": False, "result": {"primary_post": "A practical product lesson."}}


class FakeOutreach:
    def draft_connection_request(self, prospect: Any, ask_type: str) -> dict[str, Any]:
        return {"prospect_id": prospect.id, "draft_text": f"Hi {prospect.name}, could we connect?", "ask_type": ask_type, "character_count": 32, "mode": "mock", "fallback_used": False}

    def draft_followup_message(self, prospect: Any, history: list[Any]) -> dict[str, Any]:
        return {"prospect_id": prospect.id, "draft_text": "Following up on my earlier note.", "character_count": 34, "mode": "mock", "fallback_used": False}


def test_signal_to_content_package_is_stored_without_publishing(tmp_path: Path) -> None:
    database = tmp_path / "phase9.db"
    initialize_database(database)
    signal_agent = SignalIntelligenceAgent(model_agent=FakeSemanticModel())
    source = signal_agent.add_source("Approved source", "https://example.com/feed", database=database)
    signal_agent.set_source_approval(source.id or 0, "approved", database)
    signal_agent.set_source_enabled(source.id or 0, True, database)
    signal = signal_agent.persist_signal(
        source.id or 0,
        RawFeedItem(
            "phase9-signal",
            "AI product strategy for product managers at Cornell Tech",
            "A practical product strategy analysis.",
            "Editorial team",
            datetime.now(UTC).isoformat(),
            None,
            "https://example.com/phase9-signal",
            {},
        ),
        database,
    )["signal"]
    signal_agent.score_signal(signal.id or 0, database)
    opportunity = signal_agent.generate_content_opportunity(signal.id or 0, database)
    assert opportunity is not None
    post = ContentInspirationAgent(FakeContentModel()).generate_package_from_opportunity(opportunity.id or 0, database)
    assert post.draft_text
    assert post.status == "draft"


def test_prospect_outreach_manual_send_and_followup_share_persistent_state(tmp_path: Path) -> None:
    database = tmp_path / "phase9-crm.db"
    initialize_database(database)
    orchestrator = NetworkOrchestrator(outreach_draft_agent=FakeOutreach())
    added = orchestrator.add_prospect(
        "Ada Lovelace",
        profile_url="https://www.linkedin.com/in/ada-lovelace",
        role_title="Product strategist",
        company="Analytical Engines",
        notes="Interested in practical AI product strategy.",
        database=database,
    )
    assert isinstance(added["prospect"], Prospect)
    prospect_id = added["prospect"].id
    assert prospect_id is not None
    draft = orchestrator.draft_outreach(prospect_id, "career_guidance", database=database)
    assert draft["draft"]["mode"] == "mock"
    sent = orchestrator.mark_outreach_sent(
        prospect_id,
        ask_type="career_guidance",
        draft_text=draft["draft"]["draft_text"],
        draft_interaction_id=int(draft["draft_interaction_id"]),
        database=database,
    )
    assert sent["status"] == "sent_manually"
    history = orchestrator._tracker(database).get_prospect_history(prospect_id)
    assert any(item.interaction_type == "linkedin_connection_request" for item in history)
    assert orchestrator.get_followups_due(database=database) == []
    followup = orchestrator.draft_followup(prospect_id, database=database)
    assert followup["draft"]["draft_text"] == "Following up on my earlier note."
