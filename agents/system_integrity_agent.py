"""Read-only cross-table integrity checks for Network Growth Agent."""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from db.database import connect


DatabaseRef = sqlite3.Connection | str | Path


class SystemIntegrityAgent:
    """Report cross-agent data anomalies without changing stored data.

    These checks look for invariants that isolated agent unit tests can miss
    because those tests commonly mock neighboring agents. The agent is strictly
    observational: it opens read queries and returns structured reports only.
    """

    def check_no_duplicate_active_meeting(self, database: DatabaseRef) -> dict[str, Any]:
        """Flag prospects with multiple future calendar blocks."""
        today = date.today().isoformat()
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    prospect_id,
                    GROUP_CONCAT(id) AS conflicting_meeting_ids,
                    COUNT(*) AS meeting_count
                FROM calendar_blocks
                WHERE scheduled_date >= ?
                GROUP BY prospect_id
                HAVING COUNT(*) > 1
                """,
                (today,),
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "prospect_id": row["prospect_id"],
                "conflicting_meeting_ids": _parse_id_list(
                    row["conflicting_meeting_ids"]
                ),
            }
            for row in rows
        ]
        return _result("no_duplicate_active_meeting", violations)

    def check_single_active_parameter_version(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Flag parameter keys with more than one active version."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    agent_name,
                    parameter_key,
                    GROUP_CONCAT(version) AS conflicting_versions,
                    COUNT(*) AS active_count
                FROM refinable_parameters
                WHERE is_active = 1
                GROUP BY agent_name, parameter_key
                HAVING COUNT(*) > 1
                """,
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "agent_name": row["agent_name"],
                "parameter_key": row["parameter_key"],
                "conflicting_versions": _parse_id_list(row["conflicting_versions"]),
            }
            for row in rows
        ]
        return _result("single_active_parameter_version", violations)

    def check_refinement_history_matches_parameter_state(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Flag active parameter versions without accepted history."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    parameters.agent_name,
                    parameters.parameter_key,
                    parameters.version
                FROM refinable_parameters AS parameters
                LEFT JOIN refinement_history AS history
                    ON history.agent_name = parameters.agent_name
                    AND history.version = parameters.version
                    AND history.accepted = 1
                WHERE parameters.is_active = 1
                    AND history.id IS NULL
                ORDER BY parameters.agent_name, parameters.parameter_key
                """,
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "agent_name": row["agent_name"],
                "parameter_key": row["parameter_key"],
                "version": row["version"],
            }
            for row in rows
        ]
        return _result("refinement_history_matches_parameter_state", violations)

    def check_prospect_status_matches_interaction_history(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Flag meeting-confirmed prospects missing required records."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    prospects.id AS prospect_id,
                    COUNT(DISTINCT interactions.id) AS meeting_interaction_count,
                    COUNT(DISTINCT calendar_blocks.id) AS calendar_block_count
                FROM prospects
                LEFT JOIN interactions
                    ON interactions.prospect_id = prospects.id
                    AND interactions.interaction_type = 'meeting_confirmed'
                LEFT JOIN calendar_blocks
                    ON calendar_blocks.prospect_id = prospects.id
                WHERE prospects.status = 'meeting_confirmed'
                GROUP BY prospects.id
                HAVING meeting_interaction_count = 0
                    OR calendar_block_count = 0
                """,
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "prospect_id": row["prospect_id"],
                "missing_interaction": row["meeting_interaction_count"] == 0,
                "missing_calendar_block": row["calendar_block_count"] == 0,
            }
            for row in rows
        ]
        return _result("prospect_status_matches_interaction_history", violations)

    def check_content_posts_status_consistency(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Report posted content waiting on engagement metrics.

        Engagement data often arrives after posting, so a posted row with no
        metric is informational in MVP. It is returned as a pending metric note
        rather than a failing violation.
        """
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT id, status
                FROM content_posts
                WHERE status = 'posted'
                    AND engagement_metric IS NULL
                ORDER BY id
                """,
            )
        finally:
            if should_close:
                connection.close()

        notes = [
            f"content_post_id={row['id']} pending_metric: posted content has no engagement metric yet."
            for row in rows
        ]
        return {
            "check": "content_posts_status_consistency",
            "passed": True,
            "violations": [],
            "notes": notes,
        }

    def run_full_integrity_check(self, database: DatabaseRef) -> dict[str, Any]:
        """Run all integrity checks and summarize the result."""
        checks = [
            self.check_no_duplicate_active_meeting(database),
            self.check_single_active_parameter_version(database),
            self.check_refinement_history_matches_parameter_state(database),
            self.check_prospect_status_matches_interaction_history(database),
            self.check_content_posts_status_consistency(database),
        ]
        overall_passed = all(bool(check["passed"]) for check in checks)
        failed_count = sum(1 for check in checks if not check["passed"])
        summary = (
            "All integrity checks passed."
            if overall_passed
            else f"{failed_count} integrity check(s) failed."
        )
        return {
            "overall_passed": overall_passed,
            "checks": checks,
            "summary": summary,
            "checked_at": datetime.now(UTC).isoformat(),
        }


def _coerce_connection(database: DatabaseRef) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _fetch_dicts(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, parameters)
    column_names = [description[0] for description in cursor.description]
    return [dict(zip(column_names, row, strict=True)) for row in cursor.fetchall()]


def _parse_id_list(value: Any) -> list[int]:
    if value is None:
        return []
    return [int(item) for item in str(value).split(",") if item]


def _result(check_name: str, violations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "check": check_name,
        "passed": len(violations) == 0,
        "violations": violations,
    }
