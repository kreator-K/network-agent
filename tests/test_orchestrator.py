"""Tests for NetworkOrchestrator workflow coordination."""

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from agents.orchestrator import NetworkOrchestrator, NetworkOrchestratorError
from db.database import initialize_database
from db.models import (
    CalendarBlock,
    ContentPost,
    ContentPostStatus,
    Interaction,
    Prospect,
)


def _prospect(
    prospect_id: int = 1,
    name: str = "Ada Lovelace",
    role_title: str | None = "Engineer",
    company: str | None = "Analytical Engines",
    notes: str | None = "Interested in AI infrastructure.",
) -> Prospect:
    return Prospect(
        id=prospect_id,
        name=name,
        profile_url="https://www.linkedin.com/in/ada",
        location="New York",
        role_title=role_title,
        company=company,
        notes=notes,
        source="manual",
        status="not_contacted",
        last_touch_date=None,
        created_at="2026-07-08T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
    )


def _interaction(
    interaction_id: int = 1,
    prospect_id: int = 1,
    content: str = "Previous draft",
) -> Interaction:
    return Interaction(
        id=interaction_id,
        prospect_id=prospect_id,
        interaction_type="outreach_draft",
        content=content,
        direction="outbound_draft",
        created_at="2026-07-08T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
    )


def _content_post(post_id: int = 1, status: str = "draft") -> ContentPost:
    return ContentPost(
        id=post_id,
        topic="AI product launches",
        draft_text="A draft post",
        image_source="none",
        image_path=None,
        inspiration_source_notes=None,
        status=cast(ContentPostStatus, status),
        engagement_metric=None,
        created_at="2026-07-08T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
    )


class FakeTracker:
    """Fake RelationshipTrackerAgent used for orchestration tests."""

    def __init__(self, prospect: Prospect | None = None) -> None:
        self.prospect = prospect or _prospect()
        self.history = [_interaction()]
        self.due_prospects = [self.prospect]
        self.logged_interactions: list[dict[str, Any]] = []
        self.meeting_calls: list[dict[str, Any]] = []

    def add_prospect(
        self,
        name: str,
        profile_url: str | None = None,
        location: str | None = None,
        role_title: str | None = None,
        company: str | None = None,
        notes: str | None = None,
    ) -> Prospect:
        self.prospect = _prospect(name=name)
        self.prospect.profile_url = profile_url
        self.prospect.location = location
        self.prospect.role_title = role_title
        self.prospect.company = company
        self.prospect.notes = notes
        return self.prospect

    def get_prospect(self, prospect_id: int) -> Prospect:
        assert prospect_id == self.prospect.id
        return self.prospect

    def get_prospect_history(self, prospect_id: int) -> list[Interaction]:
        assert prospect_id == self.prospect.id
        return self.history

    def log_interaction(
        self,
        prospect_id: int,
        interaction_type: str,
        content: str | None = None,
        direction: str = "outbound_draft",
        status: str | None = None,
        source: str | None = None,
    ) -> Interaction:
        self.logged_interactions.append(
            {
                "prospect_id": prospect_id,
                "interaction_type": interaction_type,
                "content": content,
                "direction": direction,
                "status": status,
                "source": source,
            }
        )
        return _interaction(
            interaction_id=len(self.logged_interactions),
            prospect_id=prospect_id,
            content=content or "",
        )

    def get_prospects_due_for_followup(self) -> list[Prospect]:
        return self.due_prospects

    def mark_meeting_confirmed(
        self,
        prospect_id: int,
        meeting_date: str,
        start_time: str,
        end_time: str | None = None,
        timezone: str | None = None,
        notes: str | None = None,
    ) -> CalendarBlock:
        self.meeting_calls.append(
            {
                "prospect_id": prospect_id,
                "meeting_date": meeting_date,
                "start_time": start_time,
                "end_time": end_time,
                "timezone": timezone,
                "notes": notes,
            }
        )
        return CalendarBlock(
            id=1,
            prospect_id=prospect_id,
            scheduled_date=meeting_date,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            notes=notes,
            external_event_id=None,
            created_at="2026-07-08T00:00:00+00:00",
        )


class FakeProspectDiscoveryAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def intake_prospect(self, **kwargs: Any) -> Prospect:
        self.calls.append(kwargs)
        tracker = kwargs["tracker"]
        return tracker.add_prospect(
            name=kwargs["name"],
            profile_url=kwargs.get("profile_url"),
            location=kwargs.get("location"),
            role_title=kwargs.get("role_title"),
            company=kwargs.get("company"),
            notes=kwargs.get("notes"),
        )


class FakeProfileContextAgent:
    def __init__(self, sufficient: bool) -> None:
        self.sufficient = sufficient

    def flag_insufficient_context(self, prospect: Prospect) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "missing_fields": [] if self.sufficient else ["notes"],
            "recommendation": "Add notes.",
        }


class FakeOutreachDraftAgent:
    def __init__(self) -> None:
        self.connection_calls: list[dict[str, Any]] = []
        self.followup_calls: list[dict[str, Any]] = []

    def draft_connection_request(self, prospect: Prospect, ask_type: str) -> dict[str, Any]:
        self.connection_calls.append({"prospect": prospect, "ask_type": ask_type})
        return {
            "prospect_id": prospect.id,
            "draft_text": "Could we connect?",
            "ask_type": ask_type,
            "character_count": 17,
            "mode": "mock",
            "fallback_used": False,
            "core_intent_warning": None,
        }

    def draft_followup_message(
        self,
        prospect: Prospect,
        history: list[Interaction],
    ) -> dict[str, Any]:
        self.followup_calls.append({"prospect": prospect, "history": history})
        return {
            "prospect_id": prospect.id,
            "draft_text": "Following up.",
            "character_count": 13,
            "mode": "mock",
            "fallback_used": False,
            "core_intent_warning": None,
        }


class FakeCalendarAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def confirm_meeting(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"calendar_block": "block", "calendar_synced": False, "sync_note": None}


class FakeContentInspirationAgent:
    def __init__(self) -> None:
        self.draft_calls: list[dict[str, Any]] = []
        self.save_calls: list[dict[str, Any]] = []
        self.pending = [_content_post()]

    def draft_post(self, **kwargs: Any) -> dict[str, Any]:
        self.draft_calls.append(kwargs)
        return {
            "draft_text": "A draft post",
            "image_source": "none",
            "image_path": None,
            "inspiration_source_notes": kwargs.get("inspiration_notes"),
            "mode": "mock",
            "fallback_used": False,
        }

    def save_draft_to_db(
        self,
        draft: dict[str, Any],
        database: sqlite3.Connection | str | Path,
    ) -> ContentPost:
        self.save_calls.append({"draft": draft, "database": database})
        return _content_post()

    def get_pending_drafts(
        self,
        database: sqlite3.Connection | str | Path,
    ) -> list[ContentPost]:
        return self.pending


class FakeRefinementLoopAgent:
    def __init__(self) -> None:
        self.outcome_calls: list[dict[str, Any]] = []
        self.propose_calls: list[dict[str, Any]] = []

    def record_outcome(
        self,
        agent_name: str,
        parameter_version: int,
        metric_value: float,
        database: sqlite3.Connection | str | Path,
    ) -> None:
        self.outcome_calls.append(
            {
                "agent_name": agent_name,
                "parameter_version": parameter_version,
                "metric_value": metric_value,
                "database": database,
            }
        )

    def propose_refinement(
        self,
        agent_name: str,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        self.propose_calls.append({"agent_name": agent_name, "database": database})
        return {"agent_name": agent_name, "status": "proposed"}


class CapReachedFakeRefinementLoopAgent(FakeRefinementLoopAgent):
    def __init__(self) -> None:
        super().__init__()
        self.accept_calls: list[dict[str, Any]] = []

    def propose_refinement(
        self,
        agent_name: str,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        self.propose_calls.append({"agent_name": agent_name, "database": database})
        return {"status": "cap_reached", "requires_human_review": True}

    def accept_refinement(
        self,
        proposal: dict[str, Any],
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        self.accept_calls.append({"proposal": proposal, "database": database})
        return {"status": "accepted"}


class FailingTracker(FakeTracker):
    def get_prospect(self, prospect_id: int) -> Prospect:
        raise RuntimeError("database unavailable")


def test_add_prospect_calls_prospect_discovery_agent() -> None:
    tracker = FakeTracker()
    discovery = FakeProspectDiscoveryAgent()
    orchestrator = NetworkOrchestrator(
        prospect_discovery_agent=discovery,
        tracker_factory=lambda database: tracker,
    )

    result = orchestrator.add_prospect(
        "Ada Lovelace",
        profile_url="https://www.linkedin.com/in/ada",
        location="new york",
        role_title="Engineer",
        company="Analytical Engines",
        notes="Met at event.",
        database="memory.db",
    )

    assert result["status"] == "added"
    assert result["prospect"] == tracker.prospect
    assert discovery.calls[0]["tracker"] == tracker


def test_draft_outreach_returns_context_warning_when_insufficient() -> None:
    tracker = FakeTracker(prospect=_prospect(role_title=None, company=None, notes=None))
    orchestrator = NetworkOrchestrator(
        profile_context_agent=FakeProfileContextAgent(sufficient=False),
        outreach_draft_agent=FakeOutreachDraftAgent(),
        tracker_factory=lambda database: tracker,
    )

    result = orchestrator.draft_outreach(
        prospect_id=1,
        ask_type="general_chat",
        database="memory.db",
    )

    assert result["context_warning"]["sufficient"] is False
    assert result["draft"]["draft_text"] == "Could we connect?"


def test_draft_outreach_logs_outreach_draft_interaction() -> None:
    tracker = FakeTracker()
    orchestrator = NetworkOrchestrator(
        profile_context_agent=FakeProfileContextAgent(sufficient=True),
        outreach_draft_agent=FakeOutreachDraftAgent(),
        tracker_factory=lambda database: tracker,
    )

    result = orchestrator.draft_outreach(
        prospect_id=1,
        ask_type="career_guidance",
        database="memory.db",
    )

    assert result["context_warning"] is None
    logged = tracker.logged_interactions[0]
    assert logged["prospect_id"] == 1
    assert logged["interaction_type"] == "outreach_draft"
    assert logged["direction"] == "outbound_draft"
    assert logged["status"] == "drafted"
    assert logged["source"] == "telegram"
    assert json.loads(logged["content"]) == {
        "ask_type": "career_guidance",
        "draft_text": "Could we connect?",
        "source": "telegram",
        "status": "drafted",
    }


def test_draft_followup_uses_history_and_logs_followup() -> None:
    tracker = FakeTracker()
    outreach = FakeOutreachDraftAgent()
    orchestrator = NetworkOrchestrator(
        outreach_draft_agent=outreach,
        tracker_factory=lambda database: tracker,
    )

    result = orchestrator.draft_followup(prospect_id=1, database="memory.db")

    assert result["draft"]["draft_text"] == "Following up."
    assert outreach.followup_calls[0]["history"] == tracker.history
    assert tracker.logged_interactions[0]["interaction_type"] == "follow_up_draft"
    assert json.loads(tracker.logged_interactions[0]["content"]) == {
        "draft_text": "Following up.",
        "source": "telegram",
        "status": "drafted",
    }
    assert tracker.logged_interactions[0]["status"] == "drafted"


def test_get_followups_due_formats_for_telegram_display() -> None:
    tracker = FakeTracker()
    orchestrator = NetworkOrchestrator(tracker_factory=lambda database: tracker)

    result = orchestrator.get_followups_due(database="memory.db")

    assert result == [
        {
            "prospect_id": 1,
            "name": "Ada Lovelace",
            "role_title": "Engineer",
            "company": "Analytical Engines",
            "last_touch_date": None,
            "status": "not_contacted",
        }
    ]


def test_confirm_meeting_delegates_to_calendar_agent() -> None:
    tracker = FakeTracker()
    calendar = FakeCalendarAgent()
    orchestrator = NetworkOrchestrator(
        calendar_agent=calendar,
        tracker_factory=lambda database: tracker,
    )

    result = orchestrator.confirm_meeting(
        prospect_id=1,
        meeting_date="2026-07-10",
        start_time="09:30",
        end_time="10:00",
        timezone="America/New_York",
        notes="Coffee chat.",
        database="memory.db",
    )

    assert result["calendar_synced"] is False
    assert calendar.calls[0]["tracker"] == tracker
    assert calendar.calls[0]["meeting_date"] == "2026-07-10"


def test_draft_content_post_saves_draft() -> None:
    content = FakeContentInspirationAgent()
    orchestrator = NetworkOrchestrator(content_inspiration_agent=content)

    result = orchestrator.draft_content_post(
        topic="AI product management",
        inspiration_notes="Use a short hook.",
        user_image_path="/tmp/image.png",
        generate_image=True,
        database="content.db",
    )

    assert result["post"].draft_text == "A draft post"
    assert content.draft_calls[0]["topic"] == "AI product management"
    assert content.save_calls[0]["draft"]["draft_text"] == "A draft post"


def test_get_pending_content_drafts_returns_serializable_dicts() -> None:
    content = FakeContentInspirationAgent()
    orchestrator = NetworkOrchestrator(content_inspiration_agent=content)

    result = orchestrator.get_pending_content_drafts(database="content.db")

    assert result == [_content_post().model_dump()]


def test_record_outreach_outcome_uses_current_active_version() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE refinable_parameters (
            id INTEGER PRIMARY KEY,
            agent_name TEXT NOT NULL,
            parameter_key TEXT NOT NULL,
            parameter_value TEXT NOT NULL,
            version INTEGER NOT NULL,
            is_active BOOLEAN NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO refinable_parameters (
            agent_name, parameter_key, parameter_value, version, is_active, created_at
        )
        VALUES ('outreach_draft_agent', 'opening_style', 'direct', 3, 1, 'now')
        """
    )
    refinement = FakeRefinementLoopAgent()
    orchestrator = NetworkOrchestrator(refinement_loop_agent=refinement)

    orchestrator.record_outreach_outcome(
        prospect_id=1,
        replied=True,
        database=connection,
    )

    assert refinement.outcome_calls == [
        {
            "agent_name": "outreach_draft_agent",
            "parameter_version": 3,
            "metric_value": 1.0,
            "database": connection,
        }
    ]


def test_run_refinement_cycle_calls_propose_refinement() -> None:
    refinement = FakeRefinementLoopAgent()
    orchestrator = NetworkOrchestrator(refinement_loop_agent=refinement)

    result = orchestrator.run_refinement_cycle(
        agent_name="content_inspiration_agent",
        database="refinement.db",
    )

    assert result == {"agent_name": "content_inspiration_agent", "status": "proposed"}
    assert refinement.propose_calls == [
        {"agent_name": "content_inspiration_agent", "database": "refinement.db"}
    ]


def test_run_refinement_cycle_returns_cap_reached_without_calling_accept() -> None:
    refinement = CapReachedFakeRefinementLoopAgent()
    orchestrator = NetworkOrchestrator(refinement_loop_agent=refinement)

    result = orchestrator.run_refinement_cycle(
        agent_name="outreach_draft_agent",
        database="refinement.db",
    )

    assert result == {"status": "cap_reached", "requires_human_review": True}
    assert refinement.propose_calls == [
        {"agent_name": "outreach_draft_agent", "database": "refinement.db"}
    ]
    assert refinement.accept_calls == []


def test_orchestrator_errors_include_context_not_just_raw_exception() -> None:
    orchestrator = NetworkOrchestrator(
        tracker_factory=lambda database: FailingTracker()
    )

    with pytest.raises(NetworkOrchestratorError) as exc_info:
        orchestrator.draft_outreach(
            prospect_id=42,
            ask_type="general_chat",
            database="memory.db",
        )

    message = str(exc_info.value)
    assert "draft_outreach" in message
    assert "prospect_id=42" in message
    assert "ask_type='general_chat'" in message
    assert "database unavailable" in message
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_orchestrator_never_imports_model_orchestration_agent_directly() -> None:
    source = Path("agents/orchestrator.py").read_text(encoding="utf-8")

    assert "ModelOrchestrationAgent" not in source


def test_personal_brand_profile_workflows_use_immutable_versions(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)
    orchestrator = NetworkOrchestrator()

    summary = orchestrator.get_brand_profile_summary(database=database_path)
    assert summary is not None
    assert summary["version"] == 1

    changed = orchestrator.update_brand_profile_field(
        field_name="content_pillars",
        value="product management, AI products",
        database=database_path,
    )
    assert changed["version"] == 2
    assert changed["is_active"] is True

    versions = orchestrator.list_brand_profile_versions(database=database_path)
    assert [version["version"] for version in versions] == [2, 1]

    restored = orchestrator.activate_brand_profile(1, database=database_path)
    assert restored["version"] == 1
    assert restored["is_active"] is True
