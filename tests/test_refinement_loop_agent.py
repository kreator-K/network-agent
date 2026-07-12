"""Tests for RefinementLoopAgent."""

import json
from pathlib import Path
from typing import Any

import pytest

from agents.refinement_loop_agent import (
    InvalidRefinementAgentError,
    RefinementLoopAgent,
)
from db.database import connect, fetch_all_rows, initialize_database


class FakeModelOrchestrationAgent:
    """Captures refinement calls and returns deterministic proposals."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run_task(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "task_type": task_type,
                "prompt": prompt,
                "expected_schema": expected_schema,
            }
        )
        return {
            "task_type": task_type,
            "mode": "mock",
            "fallback_used": False,
            "result": {
                "proposed_parameters": {"opening_style": "specific_and_concise"},
                "rationale": "Recent outcomes favor specificity.",
            },
        }


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "network_agent.db"
    initialize_database(path)
    return path


def _insert_parameter(
    database_path: Path,
    agent_name: str,
    version: int,
    parameter_key: str = "opening_style",
) -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO refinable_parameters (
                agent_name,
                parameter_key,
                parameter_value,
                version,
                is_active,
                created_at
            )
            VALUES (?, ?, 'concise', ?, 1, '2026-01-01')
            """,
            (agent_name, parameter_key, version),
        )


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
            VALUES ('Ada Lovelace', 'connection_sent', '2026-01-01', '2026-01-01')
            """
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _insert_content_post(database_path: Path) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO content_posts (
                topic,
                draft_text,
                image_source,
                status,
                created_at
            )
            VALUES ('AI launches', 'Post draft', 'none', 'saved', '2026-01-01')
            """
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def _run_rows(database_path: Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            "SELECT * FROM refinement_loop_runs ORDER BY id ASC",
        )
    return [dict(row) for row in rows]


def _parameter_rows(database_path: Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT agent_name, parameter_key, parameter_value, version, is_active
            FROM refinable_parameters
            ORDER BY id ASC
            """,
        )
    return [dict(row) for row in rows]


def _set_constraint(database_path: Path, key: str, value: str) -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinement_loop_constraints
            SET constraint_value = ?
            WHERE constraint_key = ?
            """,
            (value, key),
        )


def _proposal_rows(database_path: Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            "SELECT * FROM refinement_proposals ORDER BY id ASC",
        )
    return [dict(row) for row in rows]


def _history_rows(database_path: Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            "SELECT * FROM refinement_history ORDER BY id ASC",
        )
    return [dict(row) for row in rows]


def _history_events(database_path: Path) -> list[dict[str, Any]]:
    events = []
    for row in _history_rows(database_path):
        event = json.loads(row["what_changed"])
        events.append({**event, "id": row["id"], "accepted": row["accepted"]})
    return events


def _applied_refinement_id(database_path: Path) -> int:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    _set_constraint(database_path, "mode", "assisted")
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)
    proposal_id = report["suggestions"][0]["proposal_id"]
    RefinementLoopAgent().apply_persisted_proposal(proposal_id, database_path)
    events = _history_events(database_path)
    applied = [event for event in events if event.get("event") == "proposal_applied"]
    assert applied
    return int(applied[-1]["id"])


def test_record_outcome_inserts_metric(database_path: Path) -> None:
    RefinementLoopAgent().record_outcome(
        "outreach_draft_agent",
        1,
        1.0,
        database_path,
    )

    with connect(database_path) as connection:
        rows = fetch_all_rows(connection, "SELECT * FROM refinement_outcomes")

    assert rows[0]["agent_name"] == "outreach_draft_agent"
    assert rows[0]["parameter_version"] == 1
    assert rows[0]["metric_value"] == 1.0


def test_record_explicit_outreach_outcome_saves_target_and_notes(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    prospect_id = _insert_prospect(database_path)

    result = RefinementLoopAgent().record_explicit_outcome(
        "outreach",
        prospect_id,
        "replied_positive",
        "Asked to chat next week",
        database_path,
    )

    with connect(database_path) as connection:
        rows = fetch_all_rows(connection, "SELECT * FROM refinement_outcomes")

    assert result["target_type"] == "outreach"
    assert rows[0]["target_type"] == "outreach"
    assert rows[0]["target_id"] == prospect_id
    assert rows[0]["outcome"] == "replied_positive"
    assert rows[0]["notes"] == "Asked to chat next week"
    assert rows[0]["source"] == "telegram_command"


def test_record_explicit_content_outcome_saves_post_target(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "content_inspiration_agent", 1)
    post_id = _insert_content_post(database_path)

    result = RefinementLoopAgent().record_explicit_outcome(
        "content",
        post_id,
        "good_engagement",
        "Strong comments",
        database_path,
    )

    assert result["agent_name"] == "content_inspiration_agent"
    assert result["metric_value"] == 1.0
    with connect(database_path) as connection:
        row = fetch_all_rows(connection, "SELECT * FROM refinement_outcomes")[0]
    assert row["target_type"] == "content"
    assert row["target_id"] == post_id


def test_record_explicit_outcome_rejects_invalid_target(database_path: Path) -> None:
    with pytest.raises(Exception, match="Prospect id 999 does not exist"):
        RefinementLoopAgent().record_explicit_outcome(
            "outreach",
            999,
            "replied_positive",
            None,
            database_path,
        )


def test_record_outcome_rejects_invalid_agent_name(database_path: Path) -> None:
    with pytest.raises(InvalidRefinementAgentError, match="Invalid agent_name"):
        RefinementLoopAgent().record_outcome("bad_agent", 1, 1.0, database_path)


def test_report_only_loop_creates_run_record(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome(
        "outreach_draft_agent",
        1,
        1.0,
        database_path,
    )
    before_parameters = _parameter_rows(database_path)

    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)

    rows = _run_rows(database_path)
    assert report["mode"] == "report_only"
    assert report["message"] == "Report-only. No changes have been applied."
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["outcomes_considered_count"] == 1
    assert rows[0]["proposals_created_count"] == 1
    assert rows[0]["proposals_applied_count"] == 0
    assert _parameter_rows(database_path) == before_parameters


def test_safe_proposals_are_saved_as_pending_approval(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)

    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)

    proposals = _proposal_rows(database_path)
    assert len(proposals) == 1
    assert report["suggestions"][0]["proposal_id"] == proposals[0]["proposal_id"]
    assert proposals[0]["status"] == "pending_approval"
    assert proposals[0]["checker_status"] == "passed"
    assert proposals[0]["core_intent_check_status"] == "passed"


def test_report_only_loop_logs_no_op_when_no_outcomes(database_path: Path) -> None:
    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)

    rows = _run_rows(database_path)
    assert report["status"] == "no_op"
    assert report["suggestions"] == []
    assert rows[0]["status"] == "no_op"
    assert rows[0]["outcomes_considered_count"] == 0
    assert "no_outcomes" in rows[0]["metadata_json"]


def test_report_only_loop_logs_failed_status_cleanly(database_path: Path) -> None:
    agent = RefinementLoopAgent()
    with connect(database_path) as connection:
        connection.execute("DROP TABLE refinement_loop_constraints")

    with pytest.raises(Exception):
        agent.run_report_only_refinement_loop(database_path)

    rows = _run_rows(database_path)
    assert rows[0]["status"] == "failed"
    assert rows[0]["error_message"] is not None


def test_loop_paused_prevents_proposal_generation(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinement_loop_constraints
            SET constraint_value = 'true'
            WHERE constraint_key = 'loop_paused'
            """
        )

    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)

    assert report["status"] == "paused"
    assert report["suggestions"] == []
    assert _run_rows(database_path)[0]["status"] == "paused"


def test_max_proposals_per_run_is_respected(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    _insert_parameter(database_path, "content_inspiration_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    RefinementLoopAgent().record_outcome(
        "content_inspiration_agent",
        1,
        1.0,
        database_path,
    )
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinement_loop_constraints
            SET constraint_value = '1'
            WHERE constraint_key = 'max_proposals_per_run'
            """
        )

    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)

    assert len(report["suggestions"]) == 1
    assert _run_rows(database_path)[0]["proposals_created_count"] == 1


def test_report_only_loop_does_not_mutate_core_intent_or_parameters(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    before_parameters = _parameter_rows(database_path)
    with connect(database_path) as connection:
        before_core = [dict(row) for row in fetch_all_rows(connection, "SELECT * FROM core_intent ORDER BY id")]

    RefinementLoopAgent().run_report_only_refinement_loop(database_path)

    with connect(database_path) as connection:
        after_core = [dict(row) for row in fetch_all_rows(connection, "SELECT * FROM core_intent ORDER BY id")]
    assert after_core == before_core
    assert _parameter_rows(database_path) == before_parameters


def test_apply_fails_in_report_only_mode(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)
    proposal_id = report["suggestions"][0]["proposal_id"]
    before_parameters = _parameter_rows(database_path)

    with pytest.raises(Exception, match="report-only"):
        RefinementLoopAgent().apply_persisted_proposal(proposal_id, database_path)

    assert _parameter_rows(database_path) == before_parameters
    assert _proposal_rows(database_path)[0]["status"] == "pending_approval"


def test_apply_in_assisted_mode_updates_parameter_and_history(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    _set_constraint(database_path, "mode", "assisted")
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)
    proposal_id = report["suggestions"][0]["proposal_id"]

    result = RefinementLoopAgent().apply_persisted_proposal(proposal_id, database_path)

    assert result["status"] == "applied"
    parameters = _parameter_rows(database_path)
    assert parameters[0]["is_active"] == 0
    assert parameters[1]["is_active"] == 1
    assert parameters[1]["parameter_value"] == "concise | emphasize specific evidence"
    assert _proposal_rows(database_path)[0]["status"] == "applied"
    with connect(database_path) as connection:
        history = fetch_all_rows(connection, "SELECT * FROM refinement_history")
        run = fetch_all_rows(connection, "SELECT proposals_applied_count FROM refinement_loop_runs")[0]
        core_count = fetch_all_rows(connection, "SELECT COUNT(*) AS count FROM core_intent")[0]
    events = [json.loads(row["what_changed"])["event"] for row in history]
    assert events == ["proposal_created", "proposal_applied"]
    assert history[0]["accepted"] == 0
    assert history[1]["accepted"] == 1
    assert run["proposals_applied_count"] == 1
    assert core_count["count"] > 0


def test_apply_fails_when_loop_paused(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    _set_constraint(database_path, "mode", "assisted")
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    proposal_id = RefinementLoopAgent().run_report_only_refinement_loop(database_path)["suggestions"][0]["proposal_id"]
    _set_constraint(database_path, "loop_paused", "true")

    with pytest.raises(Exception, match="paused"):
        RefinementLoopAgent().apply_persisted_proposal(proposal_id, database_path)


def test_apply_fails_if_proposal_is_stale(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    _set_constraint(database_path, "mode", "assisted")
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    proposal_id = RefinementLoopAgent().run_report_only_refinement_loop(database_path)["suggestions"][0]["proposal_id"]
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinable_parameters
            SET parameter_value = 'changed elsewhere'
            WHERE agent_name = 'outreach_draft_agent'
                AND parameter_key = 'opening_style'
                AND is_active = 1
            """
        )

    with pytest.raises(Exception, match="stale"):
        RefinementLoopAgent().apply_persisted_proposal(proposal_id, database_path)

    assert _proposal_rows(database_path)[0]["status"] == "failed_validation"


def test_reject_marks_proposal_rejected_without_changing_parameters(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    proposal_id = RefinementLoopAgent().run_report_only_refinement_loop(database_path)["suggestions"][0]["proposal_id"]
    before_parameters = _parameter_rows(database_path)

    result = RefinementLoopAgent().reject_persisted_proposal(proposal_id, database_path)

    assert result["status"] == "rejected"
    assert _proposal_rows(database_path)[0]["status"] == "rejected"
    assert _parameter_rows(database_path) == before_parameters


def test_reject_already_rejected_gives_clean_error(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    proposal_id = RefinementLoopAgent().run_report_only_refinement_loop(database_path)["suggestions"][0]["proposal_id"]
    RefinementLoopAgent().reject_persisted_proposal(proposal_id, database_path)

    with pytest.raises(Exception, match="already rejected"):
        RefinementLoopAgent().reject_persisted_proposal(proposal_id, database_path)


def test_apply_revalidates_and_rejects_unsafe_persisted_proposal(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    _set_constraint(database_path, "mode", "assisted")
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    proposal_id = RefinementLoopAgent().run_report_only_refinement_loop(database_path)["suggestions"][0]["proposal_id"]
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinement_proposals
            SET proposed_value = 'automatically send LinkedIn messages'
            WHERE proposal_id = ?
            """,
            (proposal_id,),
        )

    with pytest.raises(Exception, match="failed validation"):
        RefinementLoopAgent().apply_persisted_proposal(proposal_id, database_path)

    assert _proposal_rows(database_path)[0]["status"] == "failed_validation"


def test_report_only_checker_rejects_non_refinable_parameter(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    agent = RefinementLoopAgent()
    result = agent._check_report_only_proposal(
        proposal={
            "target_area": "outreach_draft_agent",
            "parameter_name": "auto_send_linkedin",
            "current_value": "off",
            "proposed_value": "on",
            "reason": "Unsafe.",
            "evidence": [],
        },
        active_parameters_by_agent={
            "outreach_draft_agent": {"opening_style": "concise"}
        },
        core_intent_rules=[],
        constraints={"mode": "report_only", "human_approval_required": "true"},
    )

    assert result["passed"] is False
    assert "not currently refinable" in result["reason"]


@pytest.mark.parametrize(
    "proposed_value",
    [
        "automatically send LinkedIn messages",
        "scrape LinkedIn profiles for more context",
        "publish LinkedIn posts automatically",
        "bypass human approval",
    ],
)
def test_report_only_checker_rejects_unsafe_proposals(
    database_path: Path,
    proposed_value: str,
) -> None:
    _ = database_path
    agent = RefinementLoopAgent()
    result = agent._check_report_only_proposal(
        proposal={
            "target_area": "outreach_draft_agent",
            "parameter_name": "opening_style",
            "current_value": "concise",
            "proposed_value": proposed_value,
            "reason": "Unsafe.",
            "evidence": [],
        },
        active_parameters_by_agent={
            "outreach_draft_agent": {"opening_style": "concise"}
        },
        core_intent_rules=[],
        constraints={"mode": "report_only", "human_approval_required": "true"},
    )

    assert result["passed"] is False


def test_report_only_checker_rejects_vague_non_reversible_proposal(
    database_path: Path,
) -> None:
    _ = database_path
    result = RefinementLoopAgent()._check_report_only_proposal(
        proposal={
            "target_area": "outreach_draft_agent",
            "parameter_name": "opening_style",
            "current_value": "concise",
            "proposed_value": "better",
            "reason": "Too vague.",
            "evidence": [],
        },
        active_parameters_by_agent={
            "outreach_draft_agent": {"opening_style": "concise"}
        },
        core_intent_rules=[],
        constraints={"mode": "report_only", "human_approval_required": "true"},
    )

    assert result["passed"] is False
    assert "specific and reversible" in result["reason"]


def test_propose_refinement_calls_model_with_outcomes_and_parameters(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    agent = RefinementLoopAgent(FakeModelOrchestrationAgent())
    agent.record_outcome("outreach_draft_agent", 1, 1.0, database_path)

    proposal = agent.propose_refinement("outreach_draft_agent", database_path)

    assert proposal == {
        "agent_name": "outreach_draft_agent",
        "current_version": 1,
        "proposed_version": 2,
        "proposed_parameters": {"opening_style": "specific_and_concise"},
        "rationale": "Recent outcomes favor specificity.",
        "evidence": [
            {
                "parameter_version": 1,
                "metric_value": 1.0,
                "target_type": None,
                "target_id": None,
                "related_interaction_id": None,
                "outcome": None,
                "notes": None,
                "source": None,
                "created_at": proposal["evidence"][0]["created_at"],
            }
        ],
        "risk_level": "low",
        "core_intent_check": {
            "passed": True,
            "warning": None,
            "matched_pattern": None,
        },
        "status": "proposed",
    }
    fake_model = agent.model_orchestration_agent
    assert isinstance(fake_model, FakeModelOrchestrationAgent)
    assert fake_model.calls[0]["task_type"] == "refinement_analysis"
    assert "Recent outcomes" in fake_model.calls[0]["prompt"]
    assert fake_model.calls[0]["expected_schema"] == {
        "proposed_parameters": dict,
        "rationale": str,
    }


def test_propose_refinement_enforces_iteration_cap(database_path: Path) -> None:
    _insert_parameter(database_path, "content_inspiration_agent", 5)

    proposal = RefinementLoopAgent(FakeModelOrchestrationAgent()).propose_refinement(
        "content_inspiration_agent",
        database_path,
    )

    assert proposal == {"status": "cap_reached", "requires_human_review": True}


def test_validate_against_core_intent_rejects_fabrication_drift() -> None:
    result = RefinementLoopAgent().validate_against_core_intent(
        {"tone": "pretend we have a mutual connection"},
        [{"rule_key": "no_fabrication", "description": "No fabrication."}],
    )

    assert result["passed"] is False
    assert "fabricated familiarity" in result["warning"]


def test_validate_against_core_intent_passes_safe_parameters() -> None:
    result = RefinementLoopAgent().validate_against_core_intent(
        {"tone": "professional and concise"},
        [{"rule_key": "no_fabrication", "description": "No fabrication."}],
    )

    assert result == {"passed": True, "warning": None, "matched_pattern": None}


def test_validate_against_core_intent_rejects_auto_send_and_scraping() -> None:
    agent = RefinementLoopAgent()

    auto_send = agent.validate_against_core_intent(
        {"automation": "automatically send LinkedIn messages"},
        [],
    )
    scraping = agent.validate_against_core_intent(
        {"research": "scrape LinkedIn profiles"},
        [],
    )

    assert auto_send["passed"] is False
    assert scraping["passed"] is False


def test_propose_refinement_rejects_invalid_agent_name(database_path: Path) -> None:
    with pytest.raises(InvalidRefinementAgentError, match="Invalid agent_name"):
        RefinementLoopAgent().propose_refinement("bad_agent", database_path)


def test_accept_refinement_writes_new_active_parameters(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    proposal = {
        "agent_name": "outreach_draft_agent",
        "proposed_version": 2,
        "proposed_parameters": {"opening_style": "specific"},
        "rationale": "Improve reply rate.",
    }

    result = RefinementLoopAgent().accept_refinement(proposal, database_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT parameter_key, parameter_value, version, is_active
            FROM refinable_parameters
            WHERE agent_name = 'outreach_draft_agent'
            ORDER BY version ASC
            """,
        )

    assert result["status"] == "accepted"
    assert [dict(row) for row in rows] == [
        {
            "parameter_key": "opening_style",
            "parameter_value": "concise",
            "version": 1,
            "is_active": 0,
        },
        {
            "parameter_key": "opening_style",
            "parameter_value": "specific",
            "version": 2,
            "is_active": 1,
        },
    ]


def test_accept_refinement_rejects_core_intent_violation_even_if_metrics_improve(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1, parameter_key="tone")
    agent = RefinementLoopAgent()
    agent.record_outcome("outreach_draft_agent", 1, 0.0, database_path)
    agent.record_outcome("outreach_draft_agent", 2, 1.0, database_path)
    proposal = {
        "agent_name": "outreach_draft_agent",
        "proposed_version": 2,
        "proposed_parameters": {"tone": "pretend we have a mutual connection"},
        "rationale": "This improves reply rate.",
    }

    result = agent.accept_refinement(proposal, database_path)

    assert result["status"] == "rejected"
    assert result["accepted"] is False
    assert result["core_intent_check"]["passed"] is False


def test_accept_refinement_rejects_non_refinable_parameter_key(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1, parameter_key="tone")
    proposal = {
        "agent_name": "outreach_draft_agent",
        "proposed_version": 2,
        "proposed_parameters": {"auto_send_linkedin": "enabled"},
        "rationale": "Unsafe.",
    }

    with pytest.raises(Exception, match="non-refinable keys"):
        RefinementLoopAgent().accept_refinement(proposal, database_path)


def test_rejected_refinement_does_not_write_new_parameters(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1, parameter_key="tone")
    proposal = {
        "agent_name": "outreach_draft_agent",
        "proposed_version": 2,
        "proposed_parameters": {"tone": "invent shared experience"},
        "rationale": "Unsafe.",
    }

    RefinementLoopAgent().accept_refinement(proposal, database_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            "SELECT version FROM refinable_parameters WHERE agent_name = 'outreach_draft_agent'",
        )

    assert [row["version"] for row in rows] == [1]


def test_refinement_history_is_append_only_and_accurate(database_path: Path) -> None:
    _insert_parameter(
        database_path,
        "content_inspiration_agent",
        1,
        parameter_key="post_structure",
    )
    _insert_parameter(
        database_path,
        "content_inspiration_agent",
        1,
        parameter_key="tone",
    )
    agent = RefinementLoopAgent()
    safe_proposal = {
        "agent_name": "content_inspiration_agent",
        "proposed_version": 2,
        "proposed_parameters": {"post_structure": "hook-body-close"},
        "rationale": "Improve engagement.",
    }
    unsafe_proposal = {
        "agent_name": "content_inspiration_agent",
        "proposed_version": 3,
        "proposed_parameters": {"post_structure": "fake credibility"},
        "rationale": "Unsafe.",
    }

    agent.accept_refinement(safe_proposal, database_path)
    agent.accept_refinement(unsafe_proposal, database_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT version, accepted, core_intent_check_passed
            FROM refinement_history
            WHERE agent_name = 'content_inspiration_agent'
            ORDER BY id ASC
            """,
        )

    assert [dict(row) for row in rows] == [
        {"version": 2, "accepted": 1, "core_intent_check_passed": 1},
        {"version": 3, "accepted": 0, "core_intent_check_passed": 0},
    ]


def test_rollback_reactivates_prior_version(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().accept_refinement(
        {
            "agent_name": "outreach_draft_agent",
            "proposed_version": 2,
            "proposed_parameters": {"opening_style": "specific"},
            "rationale": "Improve reply rate.",
        },
        database_path,
    )

    result = RefinementLoopAgent().rollback(
        "outreach_draft_agent",
        1,
        database_path,
    )

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT version, is_active
            FROM refinable_parameters
            WHERE agent_name = 'outreach_draft_agent'
            ORDER BY version ASC
            """,
        )

    assert result == {
        "status": "rolled_back",
        "agent_name": "outreach_draft_agent",
        "active_version": 1,
    }
    assert [dict(row) for row in rows] == [
        {"version": 1, "is_active": 1},
        {"version": 2, "is_active": 0},
    ]


def test_rollback_raises_for_missing_version(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)

    with pytest.raises(Exception, match="No refinable parameters found"):
        RefinementLoopAgent().rollback("outreach_draft_agent", 99, database_path)


def test_rollback_appends_history_entry(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)

    RefinementLoopAgent().rollback("outreach_draft_agent", 1, database_path)

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT version, what_changed, accepted
            FROM refinement_history
            WHERE agent_name = 'outreach_draft_agent'
            """
        )

    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert json.loads(rows[0]["what_changed"]) == {
        "event": "rollback",
        "restored_parameters": {"opening_style": "concise"},
        "target_version": 1,
    }
    assert rows[0]["accepted"] == 1


def test_rollback_applied_refinement_restores_old_value_and_appends_history(
    database_path: Path,
) -> None:
    refinement_id = _applied_refinement_id(database_path)

    result = RefinementLoopAgent().rollback_applied_refinement(
        refinement_id,
        database_path,
    )

    parameters = _parameter_rows(database_path)
    active_parameters = [row for row in parameters if row["is_active"] == 1]
    events = _history_events(database_path)
    rollback_events = [event for event in events if event.get("event") == "rollback_applied"]
    assert result["status"] == "rolled_back"
    assert result["parameter_name"] == "opening_style"
    assert result["restored_value"] == "concise"
    assert active_parameters[-1]["parameter_value"] == "concise"
    assert rollback_events[-1]["rollback_from_refinement_id"] == refinement_id
    assert rollback_events[-1]["old_value"] == "concise | emphasize specific evidence"
    assert rollback_events[-1]["new_value"] == "concise"


def test_rollback_does_not_delete_original_applied_history(database_path: Path) -> None:
    refinement_id = _applied_refinement_id(database_path)
    before_ids = [row["id"] for row in _history_rows(database_path)]

    RefinementLoopAgent().rollback_applied_refinement(refinement_id, database_path)

    after_rows = _history_rows(database_path)
    after_ids = [row["id"] for row in after_rows]
    events = _history_events(database_path)
    assert refinement_id in after_ids
    assert set(before_ids).issubset(set(after_ids))
    assert [event.get("event") for event in events].count("proposal_applied") == 1
    assert events[-1]["event"] == "rollback_applied"


def test_rollback_missing_refinement_id_fails_cleanly(database_path: Path) -> None:
    with pytest.raises(Exception, match="does not exist"):
        RefinementLoopAgent().rollback_applied_refinement(999, database_path)


def test_rollback_rejected_history_cannot_be_rolled_back(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    proposal_id = RefinementLoopAgent().run_report_only_refinement_loop(database_path)["suggestions"][0]["proposal_id"]
    RefinementLoopAgent().reject_persisted_proposal(proposal_id, database_path)
    rejected_id = [
        event["id"]
        for event in _history_events(database_path)
        if event.get("event") == "proposal_rejected"
    ][0]

    with pytest.raises(Exception, match="Only applied refinements"):
        RefinementLoopAgent().rollback_applied_refinement(rejected_id, database_path)


def test_rollback_failed_history_cannot_be_rolled_back(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    _set_constraint(database_path, "mode", "assisted")
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    proposal_id = RefinementLoopAgent().run_report_only_refinement_loop(database_path)["suggestions"][0]["proposal_id"]
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinement_proposals
            SET proposed_value = 'automatically send LinkedIn messages'
            WHERE proposal_id = ?
            """,
            (proposal_id,),
        )
    with pytest.raises(Exception, match="failed validation"):
        RefinementLoopAgent().apply_persisted_proposal(proposal_id, database_path)
    failed_id = [
        event["id"]
        for event in _history_events(database_path)
        if event.get("event") == "proposal_failed_validation"
    ][0]

    with pytest.raises(Exception, match="Only applied refinements"):
        RefinementLoopAgent().rollback_applied_refinement(failed_id, database_path)


def test_rollback_missing_old_value_fails_cleanly(database_path: Path) -> None:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO refinement_history (
                agent_name,
                version,
                what_changed,
                why,
                metric_before,
                metric_after,
                diff_against_v1,
                core_intent_check_passed,
                accepted,
                created_at
            )
            VALUES (
                'outreach_draft_agent',
                2,
                '{"event":"proposal_applied","parameter_name":"opening_style","new_value":"specific"}',
                'Missing old value.',
                NULL,
                NULL,
                '{}',
                1,
                1,
                '2026-01-01'
            )
            """
        )
        assert cursor.lastrowid is not None
        refinement_id = int(cursor.lastrowid)

    with pytest.raises(Exception, match="missing rollback values"):
        RefinementLoopAgent().rollback_applied_refinement(refinement_id, database_path)

    assert _history_events(database_path)[-1]["event"] == "rollback_failed"


def test_rollback_non_refinable_parameter_fails(database_path: Path) -> None:
    refinement_id = _applied_refinement_id(database_path)
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinable_parameters
            SET is_active = 0
            WHERE agent_name = 'outreach_draft_agent'
                AND parameter_key = 'opening_style'
            """
        )

    with pytest.raises(Exception, match="not refinable"):
        RefinementLoopAgent().rollback_applied_refinement(refinement_id, database_path)

    assert _history_events(database_path)[-1]["event"] == "rollback_failed"


def test_rollback_stale_parameter_value_fails_safely(database_path: Path) -> None:
    refinement_id = _applied_refinement_id(database_path)
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinable_parameters
            SET parameter_value = 'changed after apply'
            WHERE agent_name = 'outreach_draft_agent'
                AND parameter_key = 'opening_style'
                AND is_active = 1
            """
        )

    with pytest.raises(Exception, match="parameter has changed since it was applied"):
        RefinementLoopAgent().rollback_applied_refinement(refinement_id, database_path)

    assert _history_events(database_path)[-1]["failure_reason"] == "stale_current_value"


@pytest.mark.parametrize(
    "old_value",
    [
        "automatically send LinkedIn messages",
        "scrape LinkedIn profiles",
        "publish LinkedIn posts automatically",
        "bypass human approval",
    ],
)
def test_rollback_rejects_unsafe_old_value(
    database_path: Path,
    old_value: str,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE refinable_parameters
            SET parameter_value = 'safe current'
            WHERE agent_name = 'outreach_draft_agent'
                AND parameter_key = 'opening_style'
                AND is_active = 1
            """
        )
        cursor = connection.execute(
            """
            INSERT INTO refinement_history (
                agent_name,
                version,
                what_changed,
                why,
                metric_before,
                metric_after,
                diff_against_v1,
                core_intent_check_passed,
                accepted,
                created_at
            )
            VALUES (?, 2, ?, 'Applied old unsafe test.', NULL, NULL, '{}', 1, 1, '2026-01-01')
            """,
            (
                "outreach_draft_agent",
                json.dumps(
                    {
                        "event": "proposal_applied",
                        "parameter_name": "opening_style",
                        "old_value": old_value,
                        "new_value": "safe current",
                        "status": "applied",
                    }
                ),
            ),
        )
        assert cursor.lastrowid is not None
        refinement_id = int(cursor.lastrowid)

    with pytest.raises(Exception, match="failed validation"):
        RefinementLoopAgent().rollback_applied_refinement(refinement_id, database_path)

    assert _history_events(database_path)[-1]["event"] == "rollback_failed"


def test_rollback_does_not_mutate_core_intent(database_path: Path) -> None:
    refinement_id = _applied_refinement_id(database_path)
    with connect(database_path) as connection:
        before_core = [dict(row) for row in fetch_all_rows(connection, "SELECT * FROM core_intent ORDER BY id")]

    RefinementLoopAgent().rollback_applied_refinement(refinement_id, database_path)

    with connect(database_path) as connection:
        after_core = [dict(row) for row in fetch_all_rows(connection, "SELECT * FROM core_intent ORDER BY id")]
    assert after_core == before_core


def test_recent_refinement_history_returns_summary(database_path: Path) -> None:
    refinement_id = _applied_refinement_id(database_path)

    history = RefinementLoopAgent().recent_refinement_history(database_path, limit=5)

    applied = [event for event in history if event["refinement_id"] == refinement_id][0]
    assert applied["event_type"] == "proposal_applied"
    assert applied["parameter_name"] == "opening_style"
    assert applied["old_value"] == "concise"
    assert applied["new_value"] == "concise | emphasize specific evidence"


def test_get_refinement_status_summarizes_loop_state(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    report = RefinementLoopAgent().run_report_only_refinement_loop(database_path)

    status = RefinementLoopAgent().get_refinement_status(database_path)

    assert status["mode"] == "report_only"
    assert status["loop_paused"] is False
    assert status["max_proposals_per_run"] == 3
    assert status["max_apply_per_run"] == 1
    assert status["recent_run"]["run_id"] == report["run_id"]
    assert status["pending_proposals_count"] == 1
    assert status["applied_refinements_count"] == 0
    assert status["rejected_refinements_count"] == 0


def test_get_refinement_report_is_read_only_and_summarizes_state(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    RefinementLoopAgent().record_outcome("outreach_draft_agent", 1, 1.0, database_path)
    RefinementLoopAgent().run_report_only_refinement_loop(database_path)
    before_parameters = _parameter_rows(database_path)

    report = RefinementLoopAgent().get_refinement_report(database_path)

    assert report["message"] == "This is a report only. No changes were applied."
    assert len(report["recent_outcomes"]) == 1
    assert len(report["recent_proposals"]) == 1
    assert len(report["pending_proposals"]) == 1
    assert report["proposal_counts"]["pending_approval"] == 1
    assert report["current_parameters"]["outreach_draft_agent"] == {
        "opening_style": "concise"
    }
    assert "Review pending proposals" in report["recommended_next_action"]
    assert _parameter_rows(database_path) == before_parameters


def test_accept_refinement_records_metric_before_and_after(
    database_path: Path,
) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
    agent = RefinementLoopAgent()
    agent.record_outcome("outreach_draft_agent", 1, 0.25, database_path)
    agent.record_outcome("outreach_draft_agent", 2, 0.75, database_path)

    agent.accept_refinement(
        {
            "agent_name": "outreach_draft_agent",
            "proposed_version": 2,
            "proposed_parameters": {"opening_style": "specific"},
            "rationale": "Better outcome.",
        },
        database_path,
    )

    with connect(database_path) as connection:
        rows = fetch_all_rows(
            connection,
            """
            SELECT metric_before, metric_after
            FROM refinement_history
            WHERE agent_name = 'outreach_draft_agent'
            """
        )

    assert rows[0]["metric_before"] == 0.25
    assert rows[0]["metric_after"] == 0.75
