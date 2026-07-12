"""Tests for RelationshipTrackerAgent database behavior."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.relationship_tracker_agent import (
    InvalidProspectStatusError,
    ProspectNotFoundError,
    RelationshipTrackerAgent,
)
from db.database import connect, fetch_all_rows, initialize_database


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """Create a clean temporary SQLite database for each test."""
    path = tmp_path / "network_agent.db"
    initialize_database(path)
    return path


@pytest.fixture
def tracker(database_path: Path) -> RelationshipTrackerAgent:
    """Create a relationship tracker bound to the temp database."""
    return RelationshipTrackerAgent(database_path)


def test_add_prospect_creates_with_correct_defaults(
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect(
        name="Ada Lovelace",
        profile_url="https://linkedin.com/in/ada",
        location="London",
        role_title="Mathematician",
        company="Analytical Engines",
        notes="Interested in computing.",
    )

    assert prospect.id is not None
    assert prospect.name == "Ada Lovelace"
    assert prospect.profile_url == "https://linkedin.com/in/ada"
    assert prospect.source == "manual"
    assert prospect.status == "not_contacted"
    assert prospect.last_touch_date is None


def test_log_interaction_updates_last_touch_date(
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")

    interaction = tracker.log_interaction(
        prospect_id=_id(prospect.id),
        interaction_type="outreach_draft",
        content="Hello Ada",
        direction="outbound_draft",
    )
    updated = tracker.update_status(_id(prospect.id), "outreach_drafted")

    assert interaction.id is not None
    assert interaction.prospect_id == prospect.id
    assert updated.last_touch_date is not None


def test_log_interaction_raises_for_invalid_prospect_id(
    tracker: RelationshipTrackerAgent,
) -> None:
    with pytest.raises(ProspectNotFoundError, match="Prospect id 999 does not exist"):
        tracker.log_interaction(
            prospect_id=999,
            interaction_type="outreach_draft",
            content="Hello",
        )


def test_update_status_rejects_invalid_status(
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")

    with pytest.raises(InvalidProspectStatusError, match="Invalid prospect status"):
        tracker.update_status(_id(prospect.id), "invalid")  # type: ignore[arg-type]


def test_update_status_raises_for_invalid_prospect_id(
    tracker: RelationshipTrackerAgent,
) -> None:
    with pytest.raises(ProspectNotFoundError, match="Prospect id 999 does not exist"):
        tracker.update_status(999, "connected")


def test_get_prospects_due_for_followup_excludes_meeting_confirmed_and_closed(
    tracker: RelationshipTrackerAgent,
) -> None:
    due = tracker.add_prospect("Due Prospect")
    meeting = tracker.add_prospect("Meeting Prospect")
    closed = tracker.add_prospect("Closed Prospect")
    tracker.update_status(_id(meeting.id), "meeting_confirmed")
    tracker.update_status(_id(closed.id), "closed")

    results = tracker.get_prospects_due_for_followup()

    assert [prospect.id for prospect in results] == [due.id]


def test_get_prospects_due_for_followup_includes_null_last_touch_date(
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")

    results = tracker.get_prospects_due_for_followup()

    assert [result.id for result in results] == [prospect.id]


def test_get_prospects_due_for_followup_respects_cadence_from_core_intent(
    database_path: Path,
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")
    ten_days_ago = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE core_intent
            SET rule_value = '7'
            WHERE rule_key = 'cadence_floor_days'
            """
        )
        connection.execute(
            """
            UPDATE prospects
            SET last_touch_date = ?
            WHERE id = ?
            """,
            (ten_days_ago, prospect.id),
        )

    results = tracker.get_prospects_due_for_followup()

    assert [result.id for result in results] == [prospect.id]


def test_get_prospects_due_for_followup_excludes_recently_touched(
    database_path: Path,
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")
    recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE prospects
            SET last_touch_date = ?
            WHERE id = ?
            """,
            (recent, prospect.id),
        )

    results = tracker.get_prospects_due_for_followup()

    assert results == []


def test_get_prospect_history_returns_ordered_interactions(
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")
    tracker.log_interaction(_id(prospect.id), "outreach_draft", "First")
    tracker.log_interaction(_id(prospect.id), "follow_up_draft", "Second")

    history = tracker.get_prospect_history(_id(prospect.id))

    assert [interaction.content for interaction in history] == ["First", "Second"]


def test_get_prospect_history_returns_empty_list_for_prospect_with_no_interactions(
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")

    history = tracker.get_prospect_history(_id(prospect.id))

    assert history == []


def test_get_prospect_history_raises_for_invalid_prospect_id(
    tracker: RelationshipTrackerAgent,
) -> None:
    with pytest.raises(ProspectNotFoundError, match="Prospect id 999 does not exist"):
        tracker.get_prospect_history(999)


def test_mark_meeting_confirmed_creates_calendar_block_and_updates_status(
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")

    block = tracker.mark_meeting_confirmed(
        prospect_id=_id(prospect.id),
        meeting_date="2026-02-01",
        start_time="09:00",
        end_time="09:30",
        timezone="America/New_York",
        notes="Intro chat",
    )
    updated = tracker.update_status(_id(prospect.id), "meeting_confirmed")

    assert block.id is not None
    assert block.prospect_id == prospect.id
    assert block.scheduled_date == "2026-02-01"
    assert block.start_time == "09:00"
    assert block.end_time == "09:30"
    assert block.timezone == "America/New_York"
    assert block.notes == "Intro chat"
    assert updated.status == "meeting_confirmed"


def test_mark_meeting_confirmed_logs_interaction(
    database_path: Path,
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")

    tracker.mark_meeting_confirmed(
        prospect_id=_id(prospect.id),
        meeting_date="2026-02-01",
        start_time="09:00",
        notes="Intro chat",
    )

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT interaction_type, content, direction
            FROM interactions
            WHERE prospect_id = ?
            """,
            (_id(prospect.id),),
        )

    assert [dict(row) for row in rows] == [
        {
            "interaction_type": "meeting_confirmed",
            "content": "Intro chat",
            "direction": "inbound_logged",
        }
    ]


def test_mark_outreach_manually_sent_is_atomic_and_idempotent(
    database_path: Path,
    tracker: RelationshipTrackerAgent,
) -> None:
    prospect = tracker.add_prospect("Ada Lovelace")
    draft = tracker.log_interaction(
        _id(prospect.id),
        "outreach_draft",
        '{"draft_text":"Hello","ask_type":"general_chat"}',
        status="drafted",
        source="telegram",
    )

    for _ in range(2):
        tracker.mark_outreach_manually_sent(
            _id(prospect.id),
            draft_interaction_id=_id(draft.id),
            ask_type="general_chat",
            draft_text="Hello",
        )

    history = tracker.get_prospect_history(_id(prospect.id))
    manual = [
        item
        for item in history
        if item.interaction_type == "linkedin_connection_request"
    ]
    assert len(manual) == 1
    assert manual[0].status == "sent_manually"
    assert tracker.get_prospect(_id(prospect.id)).status == "connection_sent"


def test_mark_outreach_manually_sent_rejects_cross_prospect_draft(
    tracker: RelationshipTrackerAgent,
) -> None:
    first = tracker.add_prospect("Ada Lovelace")
    second = tracker.add_prospect("Grace Hopper")
    draft = tracker.log_interaction(
        _id(first.id),
        "outreach_draft",
        "Hello",
        status="drafted",
    )

    with pytest.raises(Exception, match="does not belong"):
        tracker.mark_outreach_manually_sent(
            _id(second.id),
            draft_interaction_id=_id(draft.id),
            draft_text="Hello",
        )


def _id(value: int | None) -> int:
    assert value is not None
    return value
