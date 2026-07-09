"""Tests for explicit calendar confirmation behavior."""

from datetime import date, timedelta

import pytest
import pytest_mock

from agents import calendar_agent as calendar_module
from agents.calendar_agent import (
    CalendarAgent,
    InvalidMeetingDateError,
    InvalidMeetingTimeError,
)
from db.models import CalendarBlock


class FakeTracker:
    """In-memory fake for relationship tracker calendar behavior."""

    def __init__(self) -> None:
        self.mark_calls: list[dict[str, object]] = []
        self.upcoming: list[dict[str, str | None]] = []

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

    assert result["calendar_block"].prospect_id == 7
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
