"""Calendar coordination agent."""

from datetime import date, datetime
from typing import Protocol

from config.settings import settings
from db.models import CalendarBlock
from integrations import google_calendar_client


class CalendarAgentError(ValueError):
    """Base error for calendar-agent failures."""


class InvalidMeetingDateError(CalendarAgentError):
    """Raised when meeting_date is not YYYY-MM-DD."""


class InvalidMeetingTimeError(CalendarAgentError):
    """Raised when start_time is not HH:MM."""


class TrackerProtocol(Protocol):
    """Minimal tracker interface used by CalendarAgent."""

    def mark_meeting_confirmed(
        self,
        prospect_id: int,
        meeting_date: str,
        start_time: str,
        end_time: str | None = None,
        timezone: str | None = None,
        notes: str | None = None,
    ) -> CalendarBlock:
        """Record a confirmed meeting."""

    def get_upcoming_meetings(self, today: str) -> list[dict[str, str | None]]:
        """Return upcoming meeting display rows."""


class CalendarAgent:
    """Prepare calendar blocks after explicit meeting confirmation.

    Purpose:
        Block calendar time only after the user sends an explicit
        `/meeting_confirmed` command. This class intentionally exposes no
        natural-language parser or inference path for meeting intent.
    Inputs:
        Confirmed meeting command payload, prospect record, date, time,
        duration, timezone, and meeting context.
    Outputs:
        Calendar block records plus sync status metadata.
    """

    def confirm_meeting(
        self,
        prospect_id: int,
        meeting_date: str,
        start_time: str,
        end_time: str | None = None,
        timezone: str | None = None,
        notes: str | None = None,
        tracker: TrackerProtocol | None = None,
    ) -> dict[str, object]:
        """Record a confirmed meeting and attempt provider calendar sync."""
        if tracker is None:
            raise CalendarAgentError("A RelationshipTrackerAgent is required.")
        _validate_date(meeting_date)
        _validate_time(start_time)
        if end_time is not None:
            _validate_time(end_time)

        calendar_block = tracker.mark_meeting_confirmed(
            prospect_id=prospect_id,
            meeting_date=meeting_date,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            notes=notes,
        )

        try:
            google_calendar_client.block_time(
                meeting_date=meeting_date,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                title=f"Networking meeting for prospect {prospect_id}",
                mock_mode=settings.mock_mode,
            )
        except NotImplementedError:
            return {
                "calendar_block": calendar_block,
                "calendar_synced": False,
                "sync_note": (
                    "Google Calendar sync will happen once Phase 4 is implemented."
                ),
            }

        return {
            "calendar_block": calendar_block,
            "calendar_synced": True,
            "sync_note": None,
        }

    def get_upcoming_meetings(
        self,
        tracker: TrackerProtocol | None,
    ) -> list[dict[str, str | None]]:
        """Return upcoming confirmed meetings for Telegram display."""
        if tracker is None:
            raise CalendarAgentError("A RelationshipTrackerAgent is required.")
        today = date.today().isoformat()
        meetings = tracker.get_upcoming_meetings(today)
        return sorted(
            meetings,
            key=lambda item: (item.get("scheduled_date") or "", item.get("start_time") or ""),
        )


def _validate_date(value: str) -> None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidMeetingDateError(
            "meeting_date must be a valid ISO date in YYYY-MM-DD format."
        ) from exc
    if parsed.isoformat() != value:
        raise InvalidMeetingDateError(
            "meeting_date must be a valid ISO date in YYYY-MM-DD format."
        )


def _validate_time(value: str) -> None:
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise InvalidMeetingTimeError(
            "time values must be valid 24-hour HH:MM strings."
        ) from exc
    if parsed.strftime("%H:%M") != value:
        raise InvalidMeetingTimeError(
            "time values must be valid 24-hour HH:MM strings."
        )
