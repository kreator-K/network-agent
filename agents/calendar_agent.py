"""Calendar coordination agent."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import sqlite3
from typing import Any, Protocol

from config.settings import settings
from db.models import CalendarBlock
from db.database import connect
from integrations.google_calendar_mcp_client import GoogleCalendarMCPError
from integrations import google_calendar_client


class CalendarAgentError(ValueError):
    """Base error for calendar-agent failures."""


class InvalidMeetingDateError(CalendarAgentError):
    """Raised when meeting_date is not YYYY-MM-DD."""


class InvalidMeetingTimeError(CalendarAgentError):
    """Raised when start_time is not HH:MM."""


class CalendarPersistenceError(CalendarAgentError):
    """Raised when calendar synchronization state cannot be persisted."""


class CalendarProviderError(CalendarAgentError):
    """Raised when the calendar provider cannot create the event."""


@dataclass(frozen=True)
class CalendarBlockResult:
    idempotency_key: str
    status: str
    event_id: str | None
    event_url: str | None
    was_existing: bool


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

    def __init__(self, database_path: str | Path | None = None, calendar_client: Any = None) -> None:
        self.database_path = Path(database_path) if database_path is not None else None
        self.calendar_client = calendar_client

    async def create_confirmed_meeting_event(self, *, prospect_id: str, prospect_name: str, start: datetime, end: datetime, timezone: str, description: str = "") -> CalendarBlockResult:
        """Create one confirmed event with durable, retry-safe idempotency."""
        if not str(prospect_id).strip():
            raise CalendarAgentError("prospect_id must be non-empty.")
        if not prospect_name.strip():
            raise CalendarAgentError("prospect_name must be non-empty.")
        if not timezone.strip():
            raise CalendarAgentError("timezone must be non-empty.")
        if start.tzinfo is None or start.utcoffset() is None:
            raise CalendarAgentError("start must be timezone-aware.")
        if end.tzinfo is None or end.utcoffset() is None:
            raise CalendarAgentError("end must be timezone-aware.")
        if end <= start:
            raise CalendarAgentError("end must be later than start.")
        if self.database_path is None:
            raise CalendarPersistenceError("A database_path is required for event persistence.")
        database_path = self.database_path
        if self.calendar_client is None:
            raise CalendarProviderError("An injected Google Calendar client is required.")
        key = f"google_calendar:{prospect_id}:{start.isoformat()}"
        with connect(database_path) as connection:
            row = connection.execute("SELECT * FROM calendar_blocks WHERE idempotency_key = ?", (key,)).fetchone()
            if row is not None and row["sync_status"] == "created":
                return _calendar_result(row, True)
            try:
                if row is None:
                    now = datetime.now(UTC).isoformat()
                    connection.execute("""INSERT INTO calendar_blocks
                        (prospect_id, scheduled_date, start_time, end_time, timezone, idempotency_key, provider, sync_status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'google_calendar', 'pending', ?, ?)""",
                        (int(prospect_id), start.date().isoformat(), start.strftime("%H:%M"), end.strftime("%H:%M"), timezone, key, now, now))
            except sqlite3.IntegrityError as exc:
                raise CalendarPersistenceError("Could not create the unique calendar synchronization record.") from exc
            try:
                event = await self.calendar_client.create_event(calendar_id="primary", summary=f"Meeting with {prospect_name}", description=description, start=start, end=end, timezone=timezone)
            except Exception as exc:
                safe = str(exc)[:500] if isinstance(exc, GoogleCalendarMCPError) else "Calendar provider request failed."
                connection.execute("UPDATE calendar_blocks SET sync_status = 'failed', last_error = ?, updated_at = ? WHERE idempotency_key = ?", (safe, datetime.now(UTC).isoformat(), key))
                raise CalendarProviderError(safe) from exc
            if not event.event_id:
                raise CalendarProviderError("Calendar provider returned no event ID.")
            now = datetime.now(UTC).isoformat()
            connection.execute("UPDATE calendar_blocks SET sync_status = 'created', provider_event_id = ?, provider_event_url = ?, external_event_id = ?, updated_at = ? WHERE idempotency_key = ?", (event.event_id, event.html_link, event.event_id, now, key))
            row = connection.execute("SELECT * FROM calendar_blocks WHERE idempotency_key = ?", (key,)).fetchone()
        if row is None:
            raise CalendarPersistenceError("Calendar synchronization record disappeared.")
        return _calendar_result(row, False)

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
            event_id = google_calendar_client.block_time(
                meeting_date=meeting_date,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                title=f"Networking meeting for prospect {prospect_id}",
                mock_mode=settings.mock_mode,
            )
            if hasattr(tracker, "update_calendar_block_sync"):
                calendar_block = tracker.update_calendar_block_sync(
                    calendar_block.id or 0,
                    event_id,
                    "calendar_created",
                )
        except NotImplementedError:
            if hasattr(tracker, "update_calendar_block_sync"):
                calendar_block = tracker.update_calendar_block_sync(
                    calendar_block.id or 0,
                    None,
                    "calendar_failed",
                )
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


def _calendar_result(row: sqlite3.Row, was_existing: bool) -> CalendarBlockResult:
    return CalendarBlockResult(row["idempotency_key"], row["sync_status"], row["provider_event_id"], row["provider_event_url"], was_existing)
