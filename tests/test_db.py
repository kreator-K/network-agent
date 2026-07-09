"""Tests for SQLite data-layer initialization and constraints."""

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from db.database import connect, fetch_all_rows, initialize_database
from db.models import Prospect, RefinementHistoryEntry


EXPECTED_TABLES = [
    "calendar_blocks",
    "content_posts",
    "core_intent",
    "interactions",
    "prospects",
    "refinable_parameters",
    "refinement_history",
]


def _column_names(database_path: Path, table_name: str) -> list[str]:
    with connect(database_path) as connection:
        rows = fetch_all_rows(connection, f"PRAGMA table_info({table_name})")
    return [row["name"] for row in rows]


def _insert_prospect(database_path: Path) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO prospects (
                name,
                status,
                created_at,
                updated_at
            )
            VALUES ('Ada Lovelace', 'not_contacted', '2026-01-01', '2026-01-01')
            """
        )
        return int(cursor.lastrowid)


def test_initialize_database_creates_requested_tables(tmp_path: Path) -> None:
    """The schema creates every table required by the data-layer contract."""
    database_path = tmp_path / "network_agent.db"

    initialize_database(database_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
        )

    assert [row["name"] for row in rows] == EXPECTED_TABLES


def test_initialize_database_seeds_core_intent_from_json(tmp_path: Path) -> None:
    """Human-edited core intent JSON is loaded into SQLite on init."""
    database_path = tmp_path / "network_agent.db"
    core_intent_path = tmp_path / "core_intent.json"
    core_intent_path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "rule_key": "cadence_floor_days",
                        "rule_value": "21",
                        "description": "Follow-up cadence floor.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    initialize_database(database_path, core_intent_path=core_intent_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            "SELECT rule_key, rule_value, description FROM core_intent",
        )

    assert [dict(row) for row in rows] == [
        {
            "rule_key": "cadence_floor_days",
            "rule_value": "21",
            "description": "Follow-up cadence floor.",
        }
    ]


def test_prospect_status_check_constraint(tmp_path: Path) -> None:
    """Prospect status is constrained to the requested enum-like values."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    _insert_prospect(database_path)

    with connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO prospects (
                    name,
                    status,
                    created_at,
                    updated_at
                )
                VALUES ('Grace Hopper', 'invalid', '2026-01-01', '2026-01-01')
                """
            )


def test_foreign_key_constraint_rejects_invalid_prospect_id(tmp_path: Path) -> None:
    """Interactions cannot reference a missing prospect."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    with connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO interactions (
                    prospect_id,
                    interaction_type,
                    content,
                    direction,
                    created_at
                )
                VALUES (
                    999,
                    'outreach_draft',
                    'Hello',
                    'outbound_draft',
                    '2026-01-01'
                )
                """
            )


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    """Running initialization twice does not duplicate core intent rows."""
    database_path = tmp_path / "network_agent.db"
    core_intent_path = tmp_path / "core_intent.json"
    core_intent_path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "rule_key": "cadence_floor_days",
                        "rule_value": "21",
                        "description": "Follow-up cadence floor.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    initialize_database(database_path, core_intent_path=core_intent_path)
    initialize_database(database_path, core_intent_path=core_intent_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(connection, "SELECT rule_key FROM core_intent")

    assert [row["rule_key"] for row in rows] == ["cadence_floor_days"]


def test_prospect_model_rejects_invalid_status() -> None:
    """Pydantic validation rejects statuses outside the schema contract."""
    with pytest.raises(ValidationError):
        Prospect(
            name="Ada Lovelace",
            status="invalid",
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )


def test_refinement_history_entry_allows_null_metrics() -> None:
    """Refinement history metrics are optional before measurements exist."""
    entry = RefinementHistoryEntry(
        agent_name="outreach_draft_agent",
        version=1,
        what_changed="No-op scaffold entry",
        why="Testing optional metrics",
        metric_before=None,
        metric_after=None,
        diff_against_v1="{}",
        core_intent_check_passed=True,
        accepted=False,
        created_at="2026-01-01",
    )

    assert entry.metric_before is None
    assert entry.metric_after is None


def test_content_posts_table_created_with_correct_columns(tmp_path: Path) -> None:
    """The content_posts table includes the requested columns."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    assert _column_names(database_path, "content_posts") == [
        "id",
        "draft_text",
        "image_source",
        "image_path",
        "inspiration_source_notes",
        "status",
        "engagement_metric",
        "created_at",
    ]


def test_content_posts_status_check_constraint(tmp_path: Path) -> None:
    """Content post status accepts only drafted/approved/posted/rejected."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO content_posts (
                draft_text,
                image_source,
                status,
                created_at
            )
            VALUES ('Draft', 'none', 'drafted', '2026-01-01')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO content_posts (
                    draft_text,
                    image_source,
                    status,
                    created_at
                )
                VALUES ('Draft', 'none', 'invalid', '2026-01-01')
                """
            )


def test_calendar_blocks_table_created_with_correct_columns(tmp_path: Path) -> None:
    """The calendar_blocks table includes the expected inferred columns."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    assert _column_names(database_path, "calendar_blocks") == [
        "id",
        "prospect_id",
        "scheduled_date",
        "start_time",
        "end_time",
        "timezone",
        "notes",
        "external_event_id",
        "created_at",
    ]


def test_refinable_parameters_unique_constraint(tmp_path: Path) -> None:
    """Duplicate agent/key/version refinable parameters are rejected."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    insert_sql = """
        INSERT INTO refinable_parameters (
            agent_name,
            parameter_key,
            parameter_value,
            version,
            created_at
        )
        VALUES (
            'outreach_draft_agent',
            'opening_style',
            'concise',
            1,
            '2026-01-01'
        )
    """
    with connect(database_path) as connection:
        connection.execute(insert_sql)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert_sql)
