"""Tests for explicit calendar confirmation behavior."""

import asyncio
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_mock

from agents import calendar_agent as calendar_module
from agents.calendar_agent import (
    CalendarAgent,
    CalendarAgentError,
    CalendarProviderError,
    InvalidMeetingDateError,
    InvalidMeetingTimeError,
)
from db.models import CalendarBlock
from db.database import initialize_database
from integrations.google_calendar_mcp_client import CalendarEventResult


class _CalendarClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def create_event(self, **kwargs: object) -> CalendarEventResult:
        self.calls += 1
        if self.error:
            raise self.error
        return CalendarEventResult("event-1", "https://calendar/event-1", "created")


def _event_database(tmp_path: Path) -> Path:
    path = tmp_path / "calendar-events.db"
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO prospects (name, source, status, created_at, updated_at) "
            "VALUES ('Alex', 'manual', 'not_contacted', 'now', 'now')"
        )
    return path


def test_confirmed_event_is_idempotent_and_persisted(tmp_path: Path) -> None:
    client = _CalendarClient()
    agent = CalendarAgent(_event_database(tmp_path), client)
    start = datetime(2026, 2, 1, 14, tzinfo=UTC)
    first = asyncio.run(agent.create_confirmed_meeting_event(
        prospect_id="1", prospect_name="Alex", start=start,
        end=start + timedelta(hours=1), timezone="America/New_York",
    ))
    second = asyncio.run(agent.create_confirmed_meeting_event(
        prospect_id="1", prospect_name="Alex", start=start,
        end=start + timedelta(hours=1), timezone="America/New_York",
    ))
    assert first.status == "created"
    assert second.was_existing is True
    assert client.calls == 1
    assert agent.database_path is not None
    with sqlite3.connect(agent.database_path) as connection:
        assert connection.execute(
            "SELECT provider_event_id, provider_event_url FROM calendar_blocks"
        ).fetchone() == ("event-1", "https://calendar/event-1")


def test_failed_event_can_be_retried(tmp_path: Path) -> None:
    client = _CalendarClient(RuntimeError("provider down"))
    agent = CalendarAgent(_event_database(tmp_path), client)
    start = datetime(2026, 2, 1, 14, tzinfo=UTC)
    with pytest.raises(CalendarProviderError):
        asyncio.run(agent.create_confirmed_meeting_event(
            prospect_id="1", prospect_name="Alex", start=start,
            end=start + timedelta(hours=1), timezone="America/New_York",
        ))
    client.error = None
    result = asyncio.run(agent.create_confirmed_meeting_event(
        prospect_id="1", prospect_name="Alex", start=start,
        end=start + timedelta(hours=1), timezone="America/New_York",
    ))
    assert result.status == "created"
    assert client.calls == 2


@pytest.mark.parametrize("start,end", [
    (datetime(2026, 2, 1, 15, tzinfo=UTC), datetime(2026, 2, 1, 14, tzinfo=UTC)),
    (datetime(2026, 2, 1, 14, tzinfo=UTC), datetime(2026, 2, 1, 14, tzinfo=UTC)),
])
def test_confirmed_event_rejects_invalid_range(tmp_path: Path, start: datetime, end: datetime) -> None:
    client = _CalendarClient()
    with pytest.raises(CalendarAgentError):
        asyncio.run(CalendarAgent(_event_database(tmp_path), client).create_confirmed_meeting_event(
            prospect_id="1", prospect_name="Alex", start=start, end=end,
            timezone="America/New_York",
        ))
    assert client.calls == 0


class FakeTracker:
    """In-memory fake for relationship tracker calendar behavior."""

    def __init__(self) -> None:
        self.mark_calls: list[dict[str, object]] = []
        self.upcoming: list[dict[str, str | None]] = []
        self.sync_calls: list[tuple[int, str | None, str]] = []

    def mark_meeting_confirmed(
        self,
        prospect_id: int,
        meeting_date: str,
        start_time: str,
        end_time: str | None = None,
        timezone: str | None = None,
        notes: str | None = None,
    ) -> CalendarBlock:
        self.mark_calls.append(
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
            created_at="2026-01-01",
        )

    def get_upcoming_meetings(self, today: str) -> list[dict[str, str | None]]:
        return [
            meeting
            for meeting in self.upcoming
            if str(meeting["scheduled_date"]) >= today
        ]

    def update_calendar_block_sync(
        self,
        calendar_block_id: int,
        event_id: str | None,
        status: str,
    ) -> CalendarBlock:
        self.sync_calls.append((calendar_block_id, event_id, status))
        return CalendarBlock(
            id=calendar_block_id,
            prospect_id=7,
            scheduled_date="2026-01-20",
            start_time="09:30",
            external_event_id=event_id,
            status=cast("Any", status),
            created_at="2026-01-01",
        )


def test_confirm_meeting_validates_date_format(
    mocker: pytest_mock.MockerFixture,
) -> None:
    tracker = FakeTracker()
    mocker.patch.object(
        calendar_module.google_calendar_client,
        "block_time",
        return_value="mock-event",
    )

    result = CalendarAgent().confirm_meeting(
        prospect_id=7,
        meeting_date="2026-01-20",
        start_time="09:30",
        tracker=tracker,
    )

    assert result["calendar_synced"] is True
    assert tracker.mark_calls[0]["meeting_date"] == "2026-01-20"


def test_confirm_meeting_rejects_invalid_date_format() -> None:
    with pytest.raises(InvalidMeetingDateError, match="YYYY-MM-DD"):
        CalendarAgent().confirm_meeting(
            prospect_id=7,
            meeting_date="01/20/2026",
            start_time="09:30",
            tracker=FakeTracker(),
        )


def test_confirm_meeting_validates_time_format(
    mocker: pytest_mock.MockerFixture,
) -> None:
    tracker = FakeTracker()
    mocker.patch.object(
        calendar_module.google_calendar_client,
        "block_time",
        return_value="mock-event",
    )

    result = CalendarAgent().confirm_meeting(
        prospect_id=7,
        meeting_date="2026-01-20",
        start_time="23:59",
        tracker=tracker,
    )

    assert result["calendar_synced"] is True
    assert tracker.mark_calls[0]["start_time"] == "23:59"


def test_confirm_meeting_rejects_invalid_time_format() -> None:
    with pytest.raises(InvalidMeetingTimeError, match="HH:MM"):
        CalendarAgent().confirm_meeting(
            prospect_id=7,
            meeting_date="2026-01-20",
            start_time="9:30",
            tracker=FakeTracker(),
        )


def test_preview_meeting_confirmation_has_no_tracker_or_provider_side_effect() -> None:
    result = CalendarAgent().preview_meeting_confirmation(
        prospect_id=7,
        meeting_date="2026-09-10",
        start_time="14:30",
        end_time="15:00",
        timezone="America/New_York",
        notes="Confirmed separately.",
    )

    assert result == {
        "prospect_id": 7,
        "meeting_date": "2026-09-10",
        "start_time": "14:30",
        "end_time": "15:00",
        "timezone": "America/New_York",
        "notes": "Confirmed separately.",
        "calendar_action": False,
        "confirmation_required": True,
    }


def test_preview_meeting_confirmation_rejects_invalid_details() -> None:
    with pytest.raises(InvalidMeetingDateError):
        CalendarAgent().preview_meeting_confirmation(
            prospect_id=7,
            meeting_date="September 10",
            start_time="14:30",
        )


def test_confirm_meeting_records_via_tracker(
    mocker: pytest_mock.MockerFixture,
) -> None:
    tracker = FakeTracker()
    mocker.patch.object(
        calendar_module.google_calendar_client,
        "block_time",
        return_value="mock-event",
    )

    result = CalendarAgent().confirm_meeting(
        prospect_id=7,
        meeting_date="2026-01-20",
        start_time="09:30",
        end_time="10:00",
        timezone="America/New_York",
        notes="Intro chat",
        tracker=tracker,
    )

    calendar_block = cast(CalendarBlock, result["calendar_block"])
    assert calendar_block.prospect_id == 7
    assert tracker.mark_calls == [
        {
            "prospect_id": 7,
            "meeting_date": "2026-01-20",
            "start_time": "09:30",
            "end_time": "10:00",
            "timezone": "America/New_York",
            "notes": "Intro chat",
        }
    ]


def test_confirm_meeting_handles_calendar_sync_not_implemented_gracefully(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(
        calendar_module.google_calendar_client,
        "block_time",
        side_effect=NotImplementedError("Phase 4"),
    )

    result = CalendarAgent().confirm_meeting(
        prospect_id=7,
        meeting_date="2026-01-20",
        start_time="09:30",
        tracker=FakeTracker(),
    )

    assert result["calendar_synced"] is False
    assert "Phase 4" in str(result["sync_note"])


def test_confirm_meeting_persists_provider_event_id_and_status(
    mocker: pytest_mock.MockerFixture,
) -> None:
    tracker = FakeTracker()
    mocker.patch.object(
        calendar_module.google_calendar_client,
        "block_time",
        return_value="event-12",
    )

    CalendarAgent().confirm_meeting(
        prospect_id=7,
        meeting_date="2026-01-20",
        start_time="09:30",
        tracker=tracker,
    )

    assert tracker.sync_calls == [(1, "event-12", "calendar_created")]


def test_confirm_meeting_never_triggers_without_explicit_call() -> None:
    assert CalendarAgent.confirm_meeting.__doc__ is not None
    assert "Record a confirmed meeting" in CalendarAgent.confirm_meeting.__doc__
    assert not hasattr(CalendarAgent, "infer_meeting_from_text")


def test_get_upcoming_meetings_filters_past_dates() -> None:
    tracker = FakeTracker()
    today = date.today()
    tracker.upcoming = [
        {
            "prospect_name": "Past",
            "scheduled_date": (today - timedelta(days=1)).isoformat(),
            "start_time": "09:00",
            "end_time": None,
            "timezone": None,
            "notes": None,
            "external_event_id": None,
        },
        {
            "prospect_name": "Future",
            "scheduled_date": (today + timedelta(days=1)).isoformat(),
            "start_time": "09:00",
            "end_time": None,
            "timezone": None,
            "notes": None,
            "external_event_id": None,
        },
    ]

    meetings = CalendarAgent().get_upcoming_meetings(tracker)

    assert [meeting["prospect_name"] for meeting in meetings] == ["Future"]


def test_get_upcoming_meetings_sorts_chronologically() -> None:
    tracker = FakeTracker()
    today = date.today()
    tracker.upcoming = [
        {
            "prospect_name": "Later",
            "scheduled_date": (today + timedelta(days=2)).isoformat(),
            "start_time": "10:00",
            "end_time": None,
            "timezone": None,
            "notes": None,
            "external_event_id": None,
        },
        {
            "prospect_name": "Sooner",
            "scheduled_date": (today + timedelta(days=1)).isoformat(),
            "start_time": "09:00",
            "end_time": None,
            "timezone": None,
            "notes": None,
            "external_event_id": None,
        },
    ]

    meetings = CalendarAgent().get_upcoming_meetings(tracker)

    assert [meeting["prospect_name"] for meeting in meetings] == ["Sooner", "Later"]


def test_get_upcoming_meetings_includes_prospect_name() -> None:
    tracker = FakeTracker()
    tracker.upcoming = [
        {
            "prospect_name": "Ada Lovelace",
            "scheduled_date": date.today().isoformat(),
            "start_time": "09:00",
            "end_time": "09:30",
            "timezone": "UTC",
            "notes": "Intro",
            "external_event_id": "mock",
        }
    ]

    meetings = CalendarAgent().get_upcoming_meetings(tracker)

    assert meetings[0]["prospect_name"] == "Ada Lovelace"
    assert meetings[0]["start_time"] == "09:00"
