"""Relationship tracking and CRM agent."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast, get_args

from db.database import connect
from db.models import (
    CalendarBlock,
    Interaction,
    InteractionDirection,
    InteractionStatus,
    InteractionType,
    Prospect,
    ProspectStatus,
)


class RelationshipTrackerError(ValueError):
    """Base error for relationship tracker domain failures."""


class ProspectNotFoundError(RelationshipTrackerError):
    """Raised when a requested prospect does not exist."""


class InvalidProspectStatusError(RelationshipTrackerError):
    """Raised when an invalid prospect status is requested."""


class InvalidInteractionError(RelationshipTrackerError):
    """Raised when an invalid interaction payload is requested."""


class InvalidCalendarBlockError(RelationshipTrackerError):
    """Raised when a calendar block cannot be updated."""


class RelationshipTrackerAgent:
    """Track prospect status, interactions, and follow-up eligibility.

    Purpose:
        Maintain relationship state, last-touch timestamps, follow-up due
        flags, replies, and meeting status.
    Inputs:
        Prospect records, interaction events, Telegram updates, reply outcomes,
        approvals, and meeting-confirmation commands.
    Outputs:
        Updated status decisions and follow-up eligibility metadata.
    """

    def __init__(self, database_path: str | Path) -> None:
        """Create a relationship tracker bound to one SQLite database."""
        self.database_path = database_path

    def add_prospect(
        self,
        name: str,
        profile_url: str | None = None,
        location: str | None = None,
        role_title: str | None = None,
        company: str | None = None,
        notes: str | None = None,
    ) -> Prospect:
        """Insert a manually added prospect with default not-contacted status."""
        now = _utc_now()
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO prospects (
                    name,
                    profile_url,
                    location,
                    role_title,
                    company,
                    notes,
                    source,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'manual', 'not_contacted', ?, ?)
                """,
                (name, profile_url, location, role_title, company, notes, now, now),
            )
            prospect_id = _required_lastrowid(cursor)
            return self._get_prospect(connection, prospect_id)

    def log_interaction(
        self,
        prospect_id: int,
        interaction_type: InteractionType,
        content: str | None = None,
        direction: InteractionDirection = "outbound_draft",
        status: InteractionStatus | None = None,
        source: str | None = None,
    ) -> Interaction:
        """Log an interaction and update last-touch date when appropriate."""
        _validate_interaction_type(interaction_type)
        _validate_direction(direction)
        if status is not None:
            _validate_interaction_status(status)
        now = _utc_now()
        with connect(self.database_path) as connection:
            self._ensure_prospect_exists(connection, prospect_id)
            cursor = connection.execute(
                """
                INSERT INTO interactions (
                    prospect_id,
                    interaction_type,
                    content,
                    direction,
                    status,
                    source,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prospect_id,
                    interaction_type,
                    content,
                    direction,
                    status,
                    source,
                    now,
                    now,
                ),
            )
            if _should_update_last_touch(
                direction=direction,
                interaction_type=interaction_type,
                status=status,
            ):
                connection.execute(
                    """
                    UPDATE prospects
                    SET last_touch_date = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, prospect_id),
                )
            interaction_id = _required_lastrowid(cursor)
            return self._get_interaction(connection, interaction_id)

    def update_status(
        self,
        prospect_id: int,
        new_status: ProspectStatus,
    ) -> Prospect:
        """Update a prospect status after validating the enum-like value."""
        _validate_status(new_status)
        now = _utc_now()
        with connect(self.database_path) as connection:
            self._ensure_prospect_exists(connection, prospect_id)
            connection.execute(
                "UPDATE prospects SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, prospect_id),
            )
            return self._get_prospect(connection, prospect_id)

    def get_prospects_due_for_followup(self) -> list[Prospect]:
        """Return prospects due by the cadence stored in `core_intent`."""
        with connect(self.database_path) as connection:
            cadence_days = self._get_followup_cadence_days(connection)
            threshold = datetime.now(UTC) - timedelta(days=cadence_days)
            rows = connection.execute(
                """
                SELECT *
                FROM prospects
                WHERE status NOT IN ('meeting_confirmed', 'closed')
                    AND (
                        last_touch_date IS NULL
                        OR last_touch_date < ?
                    )
                ORDER BY created_at ASC, id ASC
                """,
                (threshold.isoformat(),),
            ).fetchall()
        return [_prospect_from_row(row) for row in rows]

    def get_prospect_history(self, prospect_id: int) -> list[Interaction]:
        """Return all interactions for a prospect ordered oldest to newest."""
        with connect(self.database_path) as connection:
            self._ensure_prospect_exists(connection, prospect_id)
            rows = connection.execute(
                """
                SELECT *
                FROM interactions
                WHERE prospect_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (prospect_id,),
            ).fetchall()
        return [_interaction_from_row(row) for row in rows]

    def update_interaction_status(
        self,
        interaction_id: int,
        status: InteractionStatus,
    ) -> Interaction:
        """Update draft lifecycle status for an existing interaction."""
        _validate_interaction_status(status)
        now = _utc_now()
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM interactions WHERE id = ?",
                (interaction_id,),
            ).fetchone()
            if row is None:
                raise InvalidInteractionError(
                    f"Interaction id {interaction_id} does not exist."
                )
            connection.execute(
                """
                UPDATE interactions
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, interaction_id),
            )
            return self._get_interaction(connection, interaction_id)

    def mark_outreach_manually_sent(
        self,
        prospect_id: int,
        draft_interaction_id: int | None = None,
        ask_type: str | None = None,
        draft_text: str | None = None,
        source: str = "telegram_button",
    ) -> Prospect:
        """Atomically record an explicit user-sent outreach action."""
        now = _utc_now()
        content = json.dumps(
            {
                "status": "sent_manually",
                "ask_type": ask_type,
                "draft_text": draft_text,
                "source": source,
            },
            sort_keys=True,
        )
        with connect(self.database_path) as connection:
            self._ensure_prospect_exists(connection, prospect_id)
            if draft_interaction_id is not None:
                draft = connection.execute(
                    "SELECT prospect_id, status FROM interactions WHERE id = ?",
                    (draft_interaction_id,),
                ).fetchone()
                if draft is None or draft["prospect_id"] != prospect_id:
                    raise InvalidInteractionError(
                        "The outreach draft does not belong to this prospect."
                    )
                if draft["status"] not in {"drafted", "sent_manually"}:
                    raise InvalidInteractionError(
                        "This outreach draft is no longer available for sending."
                    )
                connection.execute(
                    """
                    UPDATE interactions
                    SET status = 'sent_manually', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, draft_interaction_id),
                )

            existing = connection.execute(
                """
                SELECT id FROM interactions
                WHERE prospect_id = ?
                    AND interaction_type = 'linkedin_connection_request'
                    AND status = 'sent_manually'
                    AND source = ?
                    AND content = ?
                ORDER BY id DESC LIMIT 1
                """,
                (prospect_id, source, content),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO interactions (
                        prospect_id, interaction_type, content, direction,
                        status, source, created_at, updated_at
                    )
                    VALUES (?, 'linkedin_connection_request', ?, 'outbound_draft',
                        'sent_manually', ?, ?, ?)
                    """,
                    (prospect_id, content, source, now, now),
                )
            connection.execute(
                """
                UPDATE prospects
                SET status = 'connection_sent', last_touch_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, prospect_id),
            )
            return self._get_prospect(connection, prospect_id)

    def update_calendar_block_sync(
        self,
        calendar_block_id: int,
        event_id: str | None,
        status: str,
    ) -> CalendarBlock:
        """Persist the calendar provider result for an existing block."""
        if status not in {"confirmed", "calendar_created", "calendar_failed"}:
            raise ValueError("Invalid calendar block status.")
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE calendar_blocks
                SET external_event_id = ?, status = ?
                WHERE id = ?
                """,
                (event_id, status, calendar_block_id),
            )
            if cursor.rowcount != 1:
                raise InvalidCalendarBlockError(
                    f"Calendar block id {calendar_block_id} does not exist."
                )
            row = connection.execute(
                "SELECT * FROM calendar_blocks WHERE id = ?",
                (calendar_block_id,),
            ).fetchone()
        return _calendar_block_from_row(row)

    def get_prospect(self, prospect_id: int) -> Prospect:
        """Return a single prospect by ID."""
        with connect(self.database_path) as connection:
            return self._get_prospect(connection, prospect_id)

    def update_prospect_notes(self, prospect_id: int, notes: str) -> Prospect:
        """Update prospect notes and return the changed prospect."""
        now = _utc_now()
        with connect(self.database_path) as connection:
            self._ensure_prospect_exists(connection, prospect_id)
            connection.execute(
                "UPDATE prospects SET notes = ?, updated_at = ? WHERE id = ?",
                (notes, now, prospect_id),
            )
            return self._get_prospect(connection, prospect_id)

    def mark_meeting_confirmed(
        self,
        prospect_id: int,
        meeting_date: str,
        start_time: str,
        end_time: str | None = None,
        timezone: str | None = None,
        notes: str | None = None,
    ) -> CalendarBlock:
        """Record a confirmed meeting without calling Google Calendar."""
        now = _utc_now()
        with connect(self.database_path) as connection:
            self._ensure_prospect_exists(connection, prospect_id)
            cursor = connection.execute(
                """
                INSERT INTO calendar_blocks (
                    prospect_id,
                    scheduled_date,
                    start_time,
                    end_time,
                    timezone,
                    notes,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (prospect_id, meeting_date, start_time, end_time, timezone, notes, now),
            )
            connection.execute(
                """
                UPDATE prospects
                SET status = 'meeting_confirmed', updated_at = ?
                WHERE id = ?
                """,
                (now, prospect_id),
            )
            connection.execute(
                """
                INSERT INTO interactions (
                    prospect_id,
                    interaction_type,
                    content,
                    direction,
                    status,
                    source,
                    created_at,
                    updated_at
                )
                VALUES (?, 'meeting_confirmed', ?, 'inbound_logged', NULL, NULL, ?, ?)
                """,
                (prospect_id, notes, now, now),
            )
            calendar_block_id = _required_lastrowid(cursor)
            row = connection.execute(
                "SELECT * FROM calendar_blocks WHERE id = ?",
                (calendar_block_id,),
            ).fetchone()
        return _calendar_block_from_row(row)

    def get_upcoming_meetings(self, today: str) -> list[dict[str, str | None]]:
        """Return upcoming confirmed meetings with prospect display details."""
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    prospects.name AS prospect_name,
                    calendar_blocks.id AS calendar_block_id,
                    calendar_blocks.prospect_id,
                    calendar_blocks.scheduled_date,
                    calendar_blocks.start_time,
                    calendar_blocks.end_time,
                    calendar_blocks.timezone,
                    calendar_blocks.notes,
                    calendar_blocks.external_event_id
                FROM calendar_blocks
                JOIN prospects ON prospects.id = calendar_blocks.prospect_id
                WHERE calendar_blocks.scheduled_date >= ?
                    AND prospects.status = 'meeting_confirmed'
                ORDER BY calendar_blocks.scheduled_date ASC,
                    calendar_blocks.start_time ASC,
                    calendar_blocks.id ASC
                """,
                (today,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _ensure_prospect_exists(
        self,
        connection: sqlite3.Connection,
        prospect_id: int,
    ) -> None:
        row = connection.execute(
            "SELECT id FROM prospects WHERE id = ?",
            (prospect_id,),
        ).fetchone()
        if row is None:
            raise ProspectNotFoundError(f"Prospect id {prospect_id} does not exist.")

    def _get_prospect(
        self,
        connection: sqlite3.Connection,
        prospect_id: int,
    ) -> Prospect:
        row = connection.execute(
            "SELECT * FROM prospects WHERE id = ?",
            (prospect_id,),
        ).fetchone()
        if row is None:
            raise ProspectNotFoundError(f"Prospect id {prospect_id} does not exist.")
        return _prospect_from_row(row)

    def _get_interaction(
        self,
        connection: sqlite3.Connection,
        interaction_id: int,
    ) -> Interaction:
        row = connection.execute(
            "SELECT * FROM interactions WHERE id = ?",
            (interaction_id,),
        ).fetchone()
        if row is None:
            raise InvalidInteractionError(
                f"Interaction id {interaction_id} does not exist."
            )
        return _interaction_from_row(row)

    def _get_followup_cadence_days(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT rule_value FROM core_intent WHERE rule_key = ?",
            ("cadence_floor_days",),
        ).fetchone()
        if row is None:
            return 21
        try:
            return int(row["rule_value"])
        except ValueError:
            return 21


def _validate_status(status: str) -> None:
    if status not in get_args(ProspectStatus):
        allowed = ", ".join(get_args(ProspectStatus))
        raise InvalidProspectStatusError(
            f"Invalid prospect status '{status}'. Allowed values: {allowed}."
        )


def _validate_interaction_type(interaction_type: str) -> None:
    if interaction_type not in get_args(InteractionType):
        allowed = ", ".join(get_args(InteractionType))
        raise InvalidInteractionError(
            f"Invalid interaction type '{interaction_type}'. Allowed values: {allowed}."
        )


def _validate_direction(direction: str) -> None:
    if direction not in get_args(InteractionDirection):
        allowed = ", ".join(get_args(InteractionDirection))
        raise InvalidInteractionError(
            f"Invalid interaction direction '{direction}'. Allowed values: {allowed}."
        )


def _validate_interaction_status(status: str) -> None:
    if status not in get_args(InteractionStatus):
        allowed = ", ".join(get_args(InteractionStatus))
        raise InvalidInteractionError(
            f"Invalid interaction status '{status}'. Allowed values: {allowed}."
        )


def _should_update_last_touch(
    *,
    direction: str,
    interaction_type: str,
    status: str | None,
) -> bool:
    if status in {"drafted", "discarded"}:
        return False
    return direction == "outbound_draft" or interaction_type == "reply_logged"


def _prospect_from_row(row: sqlite3.Row) -> Prospect:
    return Prospect(
        id=row["id"],
        name=row["name"],
        profile_url=row["profile_url"],
        location=row["location"],
        role_title=row["role_title"],
        company=row["company"],
        notes=row["notes"],
        source=row["source"],
        status=cast(ProspectStatus, row["status"]),
        last_touch_date=row["last_touch_date"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _interaction_from_row(row: sqlite3.Row) -> Interaction:
    return Interaction(
        id=row["id"],
        prospect_id=row["prospect_id"],
        interaction_type=cast(InteractionType, row["interaction_type"]),
        content=row["content"],
        direction=cast(InteractionDirection, row["direction"]),
        status=cast(InteractionStatus | None, row["status"]),
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _calendar_block_from_row(row: sqlite3.Row) -> CalendarBlock:
    return CalendarBlock(
        id=row["id"],
        prospect_id=row["prospect_id"],
        scheduled_date=row["scheduled_date"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        timezone=row["timezone"],
        notes=row["notes"],
        external_event_id=row["external_event_id"],
        status=row["status"] if "status" in row.keys() else "confirmed",
        idempotency_key=row["idempotency_key"] if "idempotency_key" in row.keys() else None,
        provider=row["provider"] if "provider" in row.keys() else None,
        provider_event_id=row["provider_event_id"] if "provider_event_id" in row.keys() else None,
        provider_event_url=row["provider_event_url"] if "provider_event_url" in row.keys() else None,
        sync_status=row["sync_status"] if "sync_status" in row.keys() else "pending",
        last_error=row["last_error"] if "last_error" in row.keys() else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"] if "updated_at" in row.keys() else None,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _required_lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RelationshipTrackerError("SQLite did not return an inserted row id.")
    return cursor.lastrowid
