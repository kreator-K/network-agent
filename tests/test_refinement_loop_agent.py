"""Tests for RefinementLoopAgent."""

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


def _insert_parameter(database_path: Path, agent_name: str, version: int) -> None:
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
            VALUES (?, 'opening_style', 'concise', ?, 1, '2026-01-01')
            """,
            (agent_name, version),
        )


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


def test_record_outcome_rejects_invalid_agent_name(database_path: Path) -> None:
    with pytest.raises(InvalidRefinementAgentError, match="Invalid agent_name"):
        RefinementLoopAgent().record_outcome("bad_agent", 1, 1.0, database_path)


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
    _insert_parameter(database_path, "outreach_draft_agent", 1)
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


def test_rejected_refinement_does_not_write_new_parameters(database_path: Path) -> None:
    _insert_parameter(database_path, "outreach_draft_agent", 1)
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
    _insert_parameter(database_path, "content_inspiration_agent", 1)
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
        "proposed_parameters": {"tone": "fake credibility"},
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
    assert rows[0]["what_changed"] == "Rolled back to version 1"
    assert rows[0]["accepted"] == 1


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
