"""Tests for SQLite data-layer initialization and constraints."""

import json
import sqlite3
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from db.database import connect, fetch_all_rows, initialize_database
from db.models import Prospect, ProspectStatus, RefinementHistoryEntry


EXPECTED_TABLES = [
    "beta_feedback",
    "briefing_runs",
    "briefing_settings",
    "calendar_blocks",
    "content_opportunities",
    "content_post_versions",
    "content_posts",
    "content_preference_feedback",
    "core_intent",
    "interactions",
    "linkedin_credentials",
    "linkedin_oauth_states",
    "linkedin_publish_events",
    "linkedin_publish_requests",
    "linkedin_publish_resolutions",
    "personal_brand_profile",
    "prospect_candidates",
    "prospects",
    "refinable_parameters",
    "refinement_history",
    "refinement_loop_constraints",
    "refinement_loop_runs",
    "refinement_outcomes",
    "refinement_proposals",
    "signal_scoring_config",
    "signal_sources",
    "signals",
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
        assert cursor.lastrowid is not None
        return cursor.lastrowid


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


def test_personal_brand_profile_table_has_versioning_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    assert _column_names(database_path, "personal_brand_profile") == [
        "id",
        "version",
        "schema_version",
        "profile_json",
        "profile_hash",
        "is_active",
        "created_at",
        "activated_at",
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


def test_init_db_repairs_legacy_content_opportunity_signal_foreign_key(
    tmp_path: Path,
) -> None:
    """A temporary Phase 8C table name must not survive in durable FKs."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='content_opportunities'"
        ).fetchone()[0]
        broken_sql = table_sql.replace(
            "CREATE TABLE content_opportunities",
            "CREATE TABLE content_opportunities_broken",
            1,
        ).replace(
            "REFERENCES signals(id)",
            'REFERENCES "signals_phase8c_legacy"(id)',
            1,
        )
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(broken_sql)
        connection.execute("DROP TABLE content_opportunities")
        connection.execute("PRAGMA legacy_alter_table = ON")
        connection.execute(
            "ALTER TABLE content_opportunities_broken "
            "RENAME TO content_opportunities"
        )
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.commit()
    finally:
        connection.close()

    initialize_database(database_path)

    with connect(database_path) as repaired:
        opportunity_targets = {
            row["table"]
            for row in repaired.execute(
                "PRAGMA foreign_key_list(content_opportunities)"
            ).fetchall()
            if row["from"] == "primary_signal_id"
        }
        content_post_targets = {
            row["table"]
            for row in repaired.execute(
                "PRAGMA foreign_key_list(content_posts)"
            ).fetchall()
            if row["from"] == "opportunity_id"
        }
        user_version = repaired.execute("PRAGMA user_version").fetchone()[0]

    assert opportunity_targets == {"signals"}
    assert content_post_targets == {"content_opportunities"}
    assert user_version == 12


def test_prospect_model_rejects_invalid_status() -> None:
    """Pydantic validation rejects statuses outside the schema contract."""
    with pytest.raises(ValidationError):
        Prospect(
            name="Ada Lovelace",
            status=cast(ProspectStatus, "invalid"),
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
        "topic",
        "draft_text",
        "image_source",
        "image_path",
        "inspiration_source_notes",
        "status",
        "engagement_metric",
        "opportunity_id",
        "profile_version",
        "scoring_config_version",
        "package_version",
        "package_json",
        "source_references_json",
        "factual_claims_json",
        "alternative_hooks_json",
        "personal_angle_json",
        "risk_assessment_json",
        "suggested_first_comment",
        "suggested_hashtags_json",
        "image_brief_json",
        "image_alt_text",
        "approved_at",
        "created_at",
        "updated_at",
    ]


def test_content_post_versions_preserve_revision_text_and_metadata(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    assert _column_names(database_path, "content_post_versions") == [
        "id",
        "content_post_id",
        "package_version",
        "draft_text",
        "package_json",
        "revision_type",
        "revision_notes",
        "model_mode",
        "fallback_used",
        "created_at",
    ]


def test_content_posts_status_check_constraint(tmp_path: Path) -> None:
    """Content post status accepts only safe internal lifecycle states."""
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
            VALUES ('Draft', 'none', 'draft', '2026-01-01')
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


def test_content_posts_image_source_check_constraint(tmp_path: Path) -> None:
    """Content post images accept uploaded/generated/none only."""
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
            VALUES ('Draft', 'uploaded', 'draft', '2026-01-01')
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
                VALUES ('Draft', 'user_upload', 'draft', '2026-01-01')
                """
            )


def test_init_db_migrates_legacy_user_upload_image_source(tmp_path: Path) -> None:
    """Existing DBs using user_upload are migrated to uploaded."""
    database_path = tmp_path / "network_agent.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE content_posts (
                id INTEGER PRIMARY KEY,
                draft_text TEXT NOT NULL,
                image_source TEXT NOT NULL DEFAULT 'none',
                image_path TEXT,
                inspiration_source_notes TEXT,
                status TEXT NOT NULL DEFAULT 'drafted',
                engagement_metric REAL,
                created_at TEXT NOT NULL,
                CHECK (image_source IN ('user_upload', 'generated', 'none')),
                CHECK (status IN ('drafted', 'approved', 'posted', 'rejected'))
            );
            INSERT INTO content_posts (
                draft_text,
                image_source,
                image_path,
                status,
                created_at
            )
            VALUES ('Draft', 'user_upload', '/tmp/image.png', 'drafted', '2026-01-01');
            """
        )

    initialize_database(database_path)

    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT image_source, status FROM content_posts WHERE id = 1"
        ).fetchone()

    assert row["image_source"] == "uploaded"
    assert row["status"] == "draft"


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
            "status",
            "idempotency_key",
            "provider",
            "provider_event_id",
            "provider_event_url",
            "sync_status",
            "last_error",
            "created_at",
            "updated_at",
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


def test_refinement_outcomes_table_supports_explicit_user_outcomes(
    tmp_path: Path,
) -> None:
    """Outcome rows can store explicit target metadata and notes."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    assert _column_names(database_path, "refinement_outcomes") == [
        "id",
        "agent_name",
        "parameter_version",
        "metric_value",
        "target_type",
        "target_id",
        "related_interaction_id",
        "outcome",
        "notes",
        "source",
        "created_at",
    ]

    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO refinement_outcomes (
                agent_name,
                parameter_version,
                metric_value,
                target_type,
                target_id,
                outcome,
                notes,
                source,
                created_at
            )
            VALUES (
                'outreach_draft_agent',
                1,
                1.0,
                'outreach',
                7,
                'replied_positive',
                'Asked to chat next week',
                'telegram_command',
                '2026-01-01'
            )
            """
        )


def test_refinement_loop_tables_are_initialized(tmp_path: Path) -> None:
    """Phase 6A loop constraints and run logs are durable SQLite tables."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)

    assert _column_names(database_path, "refinement_loop_constraints") == [
        "constraint_key",
        "constraint_value",
        "description",
        "updated_at",
    ]
    assert _column_names(database_path, "refinement_loop_runs") == [
        "id",
        "run_id",
        "loop_type",
        "mode",
        "started_at",
        "completed_at",
        "status",
        "outcomes_considered_count",
        "proposals_created_count",
        "proposals_applied_count",
        "error_message",
        "metadata_json",
    ]
    assert _column_names(database_path, "refinement_proposals") == [
        "id",
        "proposal_id",
        "run_id",
        "target_area",
        "parameter_name",
        "current_value",
        "proposed_value",
        "reason",
        "evidence_json",
        "risk_level",
        "checker_status",
        "core_intent_check_status",
        "status",
        "created_at",
        "decided_at",
        "metadata_json",
    ]


def test_refinement_loop_constraints_are_seeded_without_overwriting(
    tmp_path: Path,
) -> None:
    """Default constraints are inserted once and human edits persist."""
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinement_loop_constraints
            SET constraint_value = 'true'
            WHERE constraint_key = 'loop_paused'
            """
        )

    initialize_database(database_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT constraint_key, constraint_value
            FROM refinement_loop_constraints
            ORDER BY constraint_key
            """,
        )

    constraints = {row["constraint_key"]: row["constraint_value"] for row in rows}
    assert constraints["no_linkedin_auto_send"] == "true"
    assert constraints["no_linkedin_scraping"] == "true"
    assert constraints["no_linkedin_auto_publish"] == "true"
    assert constraints["human_approval_required"] == "true"
    assert constraints["loop_paused"] == "true"
    assert constraints["mode"] == "report_only"
    assert constraints["max_apply_per_run"] == "1"
    assert constraints["max_proposals_per_run"] == "3"


def test_legacy_linkedin_publish_ledger_migrates_to_terminal_audit_record(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-linkedin.db"
    initialize_database(database_path)
    now = "2026-01-01T00:00:00+00:00"
    with connect(database_path) as connection:
        post_id = connection.execute(
            """INSERT INTO content_posts
               (draft_text, image_source, status, created_at, updated_at)
               VALUES ('Legacy preview', 'none', 'draft', ?, ?)""",
            (now, now),
        ).lastrowid
        connection.execute(
            """INSERT INTO linkedin_credentials
               (encrypted_access_token, oidc_subject, granted_scopes,
                authorized_at, status)
               VALUES ('encrypted', 'legacy-member',
                       '[\"openid\",\"profile\",\"w_member_social\"]', ?, 'active')""",
            (now,),
        )
        connection.executescript(
            """
            DROP TABLE linkedin_publish_resolutions;
            DROP TABLE linkedin_publish_events;
            DROP TRIGGER trg_linkedin_publish_terminal_immutable;
            DROP TRIGGER trg_linkedin_publish_no_delete;
            DROP TABLE linkedin_publish_requests;
            CREATE TABLE linkedin_publish_requests (
                id INTEGER PRIMARY KEY,
                request_key TEXT NOT NULL UNIQUE,
                content_post_id INTEGER NOT NULL REFERENCES content_posts(id),
                package_version INTEGER NOT NULL,
                publish_mode TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                confirmed_at TEXT,
                completed_at TEXT,
                cancelled_at TEXT,
                external_post_id TEXT,
                external_post_url TEXT,
                error_code TEXT,
                error_summary TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX idx_linkedin_publish_requests_status
                ON linkedin_publish_requests(status, created_at);
            CREATE INDEX idx_linkedin_publish_requests_post
                ON linkedin_publish_requests(content_post_id, package_version);
            """
        )
        connection.execute(
            """INSERT INTO linkedin_publish_requests
               (request_key, content_post_id, package_version, publish_mode,
                payload_json, payload_hash, idempotency_key, status,
                created_at, expires_at, metadata_json)
               VALUES ('legacy-key', ?, 1, 'disabled',
                       '{"commentary":"Legacy","format":"text"}',
                       'legacy-hash', 'legacy-idempotency', 'preview_ready',
                       ?, ?, '{}')""",
            (post_id, now, "2026-01-01T00:15:00+00:00"),
        )
        connection.commit()

    initialize_database(database_path)
    initialize_database(database_path)

    with connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(linkedin_publish_requests)"
            ).fetchall()
        }
        assert {"publish_format", "credential_id", "author_urn"} <= columns
        migrated = connection.execute(
            "SELECT status, author_urn FROM linkedin_publish_requests"
        ).fetchone()
        assert migrated["status"] == "expired"
        assert migrated["author_urn"] == "urn:li:person:legacy-member"
        assert connection.execute(
            "SELECT COUNT(*) FROM linkedin_publish_requests_legacy_8ga"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM linkedin_publish_events WHERE event_type='legacy_migrated'"
        ).fetchone()[0] == 1
