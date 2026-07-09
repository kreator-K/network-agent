"""Tests for read-only cross-table integrity checks."""

from pathlib import Path

from agents.system_integrity_agent import SystemIntegrityAgent
from db.database import connect, initialize_database


FUTURE_DATE = "2099-01-01"


def _database_path(tmp_path: Path) -> Path:
    database_path = tmp_path / "network_agent.db"
    initialize_database(database_path)
    return database_path


def _insert_prospect(
    database_path: Path,
    *,
    status: str = "not_contacted",
    name: str = "Ada Lovelace",
) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO prospects (name, status, created_at, updated_at)
            VALUES (?, ?, '2026-07-09T00:00:00+00:00', '2026-07-09T00:00:00+00:00')
            """,
            (name, status),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _insert_calendar_block(
    database_path: Path,
    prospect_id: int,
    *,
    scheduled_date: str = FUTURE_DATE,
) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO calendar_blocks (
                prospect_id,
                scheduled_date,
                start_time,
                created_at
            )
            VALUES (?, ?, '09:00', '2026-07-09T00:00:00+00:00')
            """,
            (prospect_id, scheduled_date),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _insert_meeting_interaction(database_path: Path, prospect_id: int) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO interactions (
                prospect_id,
                interaction_type,
                content,
                direction,
                created_at
            )
            VALUES (
                ?,
                'meeting_confirmed',
                'Confirmed meeting',
                'inbound_logged',
                '2026-07-09T00:00:00+00:00'
            )
            """,
            (prospect_id,),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _insert_refinable_parameter(
    database_path: Path,
    *,
    agent_name: str = "outreach_draft_agent",
    parameter_key: str = "opening_style",
    version: int = 1,
    is_active: int = 1,
) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO refinable_parameters (
                agent_name,
                parameter_key,
                parameter_value,
                version,
                is_active,
                created_at
            )
            VALUES (?, ?, 'direct', ?, ?, '2026-07-09T00:00:00+00:00')
            """,
            (agent_name, parameter_key, version, is_active),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _insert_refinement_history(
    database_path: Path,
    *,
    agent_name: str = "outreach_draft_agent",
    version: int = 1,
    accepted: int = 1,
) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO refinement_history (
                agent_name,
                version,
                what_changed,
                why,
                diff_against_v1,
                core_intent_check_passed,
                accepted,
                created_at
            )
            VALUES (
                ?,
                ?,
                'Initial accepted parameter',
                'Seed clean state',
                '{}',
                1,
                ?,
                '2026-07-09T00:00:00+00:00'
            )
            """,
            (agent_name, version, accepted),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _insert_content_post(
    database_path: Path,
    *,
    status: str = "drafted",
    engagement_metric: float | None = None,
) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO content_posts (
                draft_text,
                image_source,
                status,
                engagement_metric,
                created_at
            )
            VALUES (
                'A post draft',
                'none',
                ?,
                ?,
                '2026-07-09T00:00:00+00:00'
            )
            """,
            (status, engagement_metric),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _seed_clean_parameter_state(database_path: Path) -> None:
    _insert_refinable_parameter(database_path, version=1, is_active=1)
    _insert_refinement_history(database_path, version=1, accepted=1)


def test_check_no_duplicate_active_meeting_passes_clean_data(tmp_path: Path) -> None:
    database_path = _database_path(tmp_path)
    prospect_id = _insert_prospect(database_path)
    _insert_calendar_block(database_path, prospect_id)

    result = SystemIntegrityAgent().check_no_duplicate_active_meeting(database_path)

    assert result == {
        "check": "no_duplicate_active_meeting",
        "passed": True,
        "violations": [],
    }


def test_check_no_duplicate_active_meeting_flags_duplicate_future_meetings(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    prospect_id = _insert_prospect(database_path)
    first_id = _insert_calendar_block(database_path, prospect_id)
    second_id = _insert_calendar_block(database_path, prospect_id)

    result = SystemIntegrityAgent().check_no_duplicate_active_meeting(database_path)

    assert result["passed"] is False
    assert result["violations"] == [
        {
            "prospect_id": prospect_id,
            "conflicting_meeting_ids": [first_id, second_id],
        }
    ]


def test_check_single_active_parameter_version_passes_clean_data(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    _seed_clean_parameter_state(database_path)

    result = SystemIntegrityAgent().check_single_active_parameter_version(
        database_path
    )

    assert result == {
        "check": "single_active_parameter_version",
        "passed": True,
        "violations": [],
    }


def test_check_single_active_parameter_version_flags_two_active_versions(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    _insert_refinable_parameter(database_path, version=1, is_active=1)
    _insert_refinable_parameter(database_path, version=2, is_active=1)

    result = SystemIntegrityAgent().check_single_active_parameter_version(
        database_path
    )

    assert result["passed"] is False
    assert result["violations"] == [
        {
            "agent_name": "outreach_draft_agent",
            "parameter_key": "opening_style",
            "conflicting_versions": [1, 2],
        }
    ]


def test_check_refinement_history_matches_parameter_state_passes_clean_data(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    _seed_clean_parameter_state(database_path)

    result = (
        SystemIntegrityAgent().check_refinement_history_matches_parameter_state(
            database_path
        )
    )

    assert result == {
        "check": "refinement_history_matches_parameter_state",
        "passed": True,
        "violations": [],
    }


def test_check_refinement_history_matches_parameter_state_flags_orphaned_activation(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    _insert_refinable_parameter(database_path, version=2, is_active=1)

    result = (
        SystemIntegrityAgent().check_refinement_history_matches_parameter_state(
            database_path
        )
    )

    assert result["passed"] is False
    assert result["violations"] == [
        {
            "agent_name": "outreach_draft_agent",
            "parameter_key": "opening_style",
            "version": 2,
        }
    ]


def test_check_prospect_status_matches_interaction_history_passes_clean_data(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    prospect_id = _insert_prospect(database_path, status="meeting_confirmed")
    _insert_meeting_interaction(database_path, prospect_id)
    _insert_calendar_block(database_path, prospect_id)

    result = SystemIntegrityAgent().check_prospect_status_matches_interaction_history(
        database_path
    )

    assert result == {
        "check": "prospect_status_matches_interaction_history",
        "passed": True,
        "violations": [],
    }


def test_check_prospect_status_matches_interaction_history_flags_missing_interaction(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    prospect_id = _insert_prospect(database_path, status="meeting_confirmed")
    _insert_calendar_block(database_path, prospect_id)

    result = SystemIntegrityAgent().check_prospect_status_matches_interaction_history(
        database_path
    )

    assert result["passed"] is False
    assert result["violations"] == [
        {
            "prospect_id": prospect_id,
            "missing_interaction": True,
            "missing_calendar_block": False,
        }
    ]


def test_check_content_posts_status_consistency_passes_clean_data(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    _insert_content_post(database_path, status="posted", engagement_metric=42.0)

    result = SystemIntegrityAgent().check_content_posts_status_consistency(
        database_path
    )

    assert result == {
        "check": "content_posts_status_consistency",
        "passed": True,
        "violations": [],
        "notes": [],
    }


def test_check_content_posts_status_consistency_flags_missing_metric_as_pending_not_failure(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    content_post_id = _insert_content_post(
        database_path,
        status="posted",
        engagement_metric=None,
    )

    result = SystemIntegrityAgent().check_content_posts_status_consistency(
        database_path
    )

    assert result["passed"] is True
    assert result["violations"] == []
    assert result["notes"] == [
        f"content_post_id={content_post_id} pending_metric: posted content has no engagement metric yet."
    ]


def test_run_full_integrity_check_aggregates_all_five_checks(tmp_path: Path) -> None:
    database_path = _database_path(tmp_path)
    prospect_id = _insert_prospect(database_path, status="meeting_confirmed")
    _insert_meeting_interaction(database_path, prospect_id)
    _insert_calendar_block(database_path, prospect_id)
    _seed_clean_parameter_state(database_path)
    _insert_content_post(database_path, status="posted", engagement_metric=None)

    result = SystemIntegrityAgent().run_full_integrity_check(database_path)

    assert result["overall_passed"] is True
    assert len(result["checks"]) == 5
    assert [check["check"] for check in result["checks"]] == [
        "no_duplicate_active_meeting",
        "single_active_parameter_version",
        "refinement_history_matches_parameter_state",
        "prospect_status_matches_interaction_history",
        "content_posts_status_consistency",
    ]
    assert result["summary"] == "All integrity checks passed."
    assert isinstance(result["checked_at"], str)


def test_run_full_integrity_check_overall_passed_false_if_any_check_fails(
    tmp_path: Path,
) -> None:
    database_path = _database_path(tmp_path)
    prospect_id = _insert_prospect(database_path)
    _insert_calendar_block(database_path, prospect_id)
    _insert_calendar_block(database_path, prospect_id)

    result = SystemIntegrityAgent().run_full_integrity_check(database_path)

    assert result["overall_passed"] is False
    assert result["summary"] == "1 integrity check(s) failed."
    assert result["checks"][0]["check"] == "no_duplicate_active_meeting"
    assert result["checks"][0]["passed"] is False


def test_agent_is_read_only_never_calls_insert_update_or_delete() -> None:
    source = Path("agents/system_integrity_agent.py").read_text(encoding="utf-8")
    uppercase_source = source.upper()

    assert "INSERT" not in uppercase_source
    assert "UPDATE" not in uppercase_source
    assert "DELETE" not in uppercase_source
