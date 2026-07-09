"""Relationship tracking and CRM agent."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast, get_args

from db.database import connect
from db.models import (
    CalendarBlock,
    Interaction,
    InteractionDirection,
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
    ) -> Interaction:
        """Log an interaction and update last-touch date when appropriate."""
        _validate_interaction_type(interaction_type)
        _validate_direction(direction)
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
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (prospect_id, interaction_type, content, direction, now),
            )
            if direction == "outbound_draft" or interaction_type == "reply_logged":
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
                    created_at
                )
                VALUES (?, 'meeting_confirmed', ?, 'inbound_logged', ?)
                """,
                (prospect_id, notes, now),
            )
            calendar_block_id = _required_lastrowid(cursor)
            row = connection.execute(
                "SELECT * FROM calendar_blocks WHERE id = ?",
                (calendar_block_id,),
            ).fetchone()
        return _calendar_block_from_row(row)

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
        created_at=row["created_at"],
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
        created_at=row["created_at"],
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _required_lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RelationshipTrackerError("SQLite did not return an inserted row id.")
    return cursor.lastrowid
