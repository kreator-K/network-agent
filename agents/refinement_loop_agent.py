"""Controlled refinement loop agent.

MVP simplification: semantic drift checks are rule-based keyword/pattern
checks. Future phases may add model-assisted evaluation through
ModelOrchestrationAgent while still treating core_intent as immutable.
"""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, get_args

from agents.model_orchestration_agent import ModelOrchestrationAgent
from db.database import connect
from db.models import RefinableAgentName


MAX_AUTOMATIC_REFINEMENT_ITERATIONS = 5
FABRICATION_PATTERNS = [
    r"\bfabricat",
    r"\binvent",
    r"\bfake",
    r"\bpretend",
    r"\bshared connection",
    r"\bmutual connection",
    r"\bshared experience",
    r"\boverstate",
]


class ModelOrchestrator(Protocol):
    """Minimal model orchestration interface used by this agent."""

    def run_task(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a model task through the approved orchestration boundary."""


class RefinementLoopError(ValueError):
    """Base error for refinement loop failures."""


class InvalidRefinementAgentError(RefinementLoopError):
    """Raised when a refinement target agent is unsupported."""


class RefinementLoopAgent:
    """Propose refinements without modifying immutable core intent.

    Purpose:
        Track outreach and content outcomes, propose changes to SQLite-native
        refinable parameters, run semantic drift checks, enforce iteration
        caps, and append refinement history.
    Inputs:
        Metrics, current refinable parameters, core intent from SQLite, and a
        fixed evaluation set.
    Outputs:
        Proposed refinements, accept/reject decisions, drift-check results,
        and rollback metadata.
    """

    def __init__(
        self,
        model_orchestration_agent: ModelOrchestrator | None = None,
    ) -> None:
        """Create a refinement loop agent using the approved model boundary."""
        self.model_orchestration_agent = (
            model_orchestration_agent or ModelOrchestrationAgent()
        )

    def record_outcome(
        self,
        agent_name: str,
        parameter_version: int,
        metric_value: float,
        database: sqlite3.Connection | str | Path,
    ) -> None:
        """Record an outcome metric for one agent parameter version."""
        _validate_agent_name(agent_name)
        connection, should_close = _coerce_connection(database)
        try:
            connection.execute(
                """
                INSERT INTO refinement_outcomes (
                    agent_name,
                    parameter_version,
                    metric_value,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (agent_name, parameter_version, metric_value, _utc_now()),
            )
            connection.commit()
        finally:
            if should_close:
                connection.close()

    def propose_refinement(
        self,
        agent_name: str,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Propose a parameter change if the iteration cap allows it."""
        _validate_agent_name(agent_name)
        connection, should_close = _coerce_connection(database)
        try:
            current_version = _current_version(connection, agent_name)
            if current_version >= MAX_AUTOMATIC_REFINEMENT_ITERATIONS:
                return {"status": "cap_reached", "requires_human_review": True}

            current_parameters = _active_parameters(connection, agent_name)
            outcomes = _recent_outcomes(connection, agent_name, current_version)
            response = self.model_orchestration_agent.run_task(
                task_type="refinement_analysis",
                prompt=_build_refinement_prompt(
                    agent_name=agent_name,
                    current_version=current_version,
                    current_parameters=current_parameters,
                    outcomes=outcomes,
                ),
                expected_schema={"proposed_parameters": dict, "rationale": str},
            )
        finally:
            if should_close:
                connection.close()

        result = response.get("result", {})
        proposed_parameters = result.get("proposed_parameters", {})
        rationale = result.get("rationale", "")
        if not isinstance(proposed_parameters, dict):
            proposed_parameters = {}
        if not isinstance(rationale, str):
            rationale = str(rationale)

        return {
            "agent_name": agent_name,
            "current_version": current_version,
            "proposed_version": current_version + 1,
            "proposed_parameters": proposed_parameters,
            "rationale": rationale,
            "status": "proposed",
        }

    def validate_against_core_intent(
        self,
        proposed_parameters: dict[str, Any],
        core_intent_rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run a rule-based semantic drift check for MVP."""
        text = json.dumps(proposed_parameters).lower()
        active_rules = " ".join(
            f"{rule.get('rule_key', '')} {rule.get('description', '')} {rule.get('rule_value', '')}"
            for rule in core_intent_rules
        ).lower()
        should_check_fabrication = (
            not core_intent_rules
            or "fabrication" in active_rules
            or "shared connection" in active_rules
            or "shared experience" in active_rules
        )
        if should_check_fabrication:
            for pattern in FABRICATION_PATTERNS:
                if re.search(pattern, text):
                    return {
                        "passed": False,
                        "warning": "Proposed parameters may violate core intent by encouraging fabricated familiarity.",
                        "matched_pattern": pattern,
                    }
        return {"passed": True, "warning": None, "matched_pattern": None}

    def accept_refinement(
        self,
        proposal: dict[str, Any],
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Accept or reject a proposal after checking immutable core intent."""
        agent_name = str(proposal.get("agent_name", ""))
        _validate_agent_name(agent_name)
        proposed_parameters = proposal.get("proposed_parameters", {})
        if not isinstance(proposed_parameters, dict):
            proposed_parameters = {}
        proposed_version = int(proposal.get("proposed_version", 1))
        rationale = str(proposal.get("rationale", ""))

        connection, should_close = _coerce_connection(database)
        try:
            core_intent_rules = _core_intent_rules(connection)
            drift_check = self.validate_against_core_intent(
                proposed_parameters,
                core_intent_rules,
            )
            if not drift_check["passed"]:
                _append_history(
                    connection=connection,
                    agent_name=agent_name,
                    version=proposed_version,
                    what_changed=json.dumps(proposed_parameters, sort_keys=True),
                    why=rationale,
                    diff_against_v1=json.dumps(proposed_parameters, sort_keys=True),
                    core_intent_check_passed=False,
                    accepted=False,
                )
                connection.commit()
                return {
                    "status": "rejected",
                    "accepted": False,
                    "core_intent_check": drift_check,
                }

            connection.execute(
                "UPDATE refinable_parameters SET is_active = 0 WHERE agent_name = ?",
                (agent_name,),
            )
            for key, value in proposed_parameters.items():
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
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (agent_name, str(key), str(value), proposed_version, _utc_now()),
                )
            _append_history(
                connection=connection,
                agent_name=agent_name,
                version=proposed_version,
                what_changed=json.dumps(proposed_parameters, sort_keys=True),
                why=rationale,
                diff_against_v1=json.dumps(proposed_parameters, sort_keys=True),
                core_intent_check_passed=True,
                accepted=True,
            )
            connection.commit()
            return {
                "status": "accepted",
                "accepted": True,
                "version": proposed_version,
                "core_intent_check": drift_check,
            }
        finally:
            if should_close:
                connection.close()

    def rollback(
        self,
        agent_name: str,
        target_version: int,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Reactivate a prior parameter version and append rollback history."""
        _validate_agent_name(agent_name)
        connection, should_close = _coerce_connection(database)
        try:
            rows = connection.execute(
                """
                SELECT parameter_key, parameter_value
                FROM refinable_parameters
                WHERE agent_name = ? AND version = ?
                """,
                (agent_name, target_version),
            ).fetchall()
            if not rows:
                raise RefinementLoopError(
                    f"No refinable parameters found for {agent_name} version {target_version}."
                )
            connection.execute(
                "UPDATE refinable_parameters SET is_active = 0 WHERE agent_name = ?",
                (agent_name,),
            )
            connection.execute(
                """
                UPDATE refinable_parameters
                SET is_active = 1
                WHERE agent_name = ? AND version = ?
                """,
                (agent_name, target_version),
            )
            _append_history(
                connection=connection,
                agent_name=agent_name,
                version=target_version,
                what_changed=f"Rolled back to version {target_version}",
                why="Human or system requested rollback.",
                diff_against_v1=json.dumps(
                    {row["parameter_key"]: row["parameter_value"] for row in rows},
                    sort_keys=True,
                ),
                core_intent_check_passed=True,
                accepted=True,
            )
            connection.commit()
            return {
                "status": "rolled_back",
                "agent_name": agent_name,
                "active_version": target_version,
            }
        finally:
            if should_close:
                connection.close()


def _validate_agent_name(agent_name: str) -> None:
    if agent_name not in get_args(RefinableAgentName):
        allowed = ", ".join(get_args(RefinableAgentName))
        raise InvalidRefinementAgentError(
            f"Invalid agent_name '{agent_name}'. Allowed values: {allowed}."
        )


def _coerce_connection(
    database: sqlite3.Connection | str | Path,
) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _current_version(connection: sqlite3.Connection, agent_name: str) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(version), 1) AS current_version
        FROM refinable_parameters
        WHERE agent_name = ?
        """,
        (agent_name,),
    ).fetchone()
    return int(row["current_version"])


def _active_parameters(
    connection: sqlite3.Connection,
    agent_name: str,
) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT parameter_key, parameter_value
        FROM refinable_parameters
        WHERE agent_name = ? AND is_active = 1
        ORDER BY parameter_key ASC
        """,
        (agent_name,),
    ).fetchall()
    return {row["parameter_key"]: row["parameter_value"] for row in rows}


def _recent_outcomes(
    connection: sqlite3.Connection,
    agent_name: str,
    parameter_version: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT parameter_version, metric_value, created_at
        FROM refinement_outcomes
        WHERE agent_name = ? AND parameter_version = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 20
        """,
        (agent_name, parameter_version),
    ).fetchall()
    return [dict(row) for row in rows]


def _core_intent_rules(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT rule_key, rule_value, description
        FROM core_intent
        ORDER BY rule_key ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _append_history(
    connection: sqlite3.Connection,
    agent_name: str,
    version: int,
    what_changed: str,
    why: str,
    diff_against_v1: str,
    core_intent_check_passed: bool,
    accepted: bool,
) -> None:
    before_metric = _average_metric(connection, agent_name, version - 1)
    after_metric = _average_metric(connection, agent_name, version)
    connection.execute(
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_name,
            version,
            what_changed,
            why,
            before_metric,
            after_metric,
            diff_against_v1,
            int(core_intent_check_passed),
            int(accepted),
            _utc_now(),
        ),
    )


def _average_metric(
    connection: sqlite3.Connection,
    agent_name: str,
    parameter_version: int,
) -> float | None:
    row = connection.execute(
        """
        SELECT AVG(metric_value) AS metric_average
        FROM refinement_outcomes
        WHERE agent_name = ? AND parameter_version = ?
        """,
        (agent_name, parameter_version),
    ).fetchone()
    if row is None or row["metric_average"] is None:
        return None
    return float(row["metric_average"])


def _build_refinement_prompt(
    agent_name: str,
    current_version: int,
    current_parameters: dict[str, str],
    outcomes: list[dict[str, Any]],
) -> str:
    return "\n".join(
        [
            "Analyze recent outcomes and propose a safe refinable parameter update.",
            "Return JSON with keys proposed_parameters and rationale.",
            "Do not propose changes that violate core intent, fabricate familiarity, or loosen approval requirements.",
            f"Agent: {agent_name}",
            f"Current version: {current_version}",
            f"Current parameters: {json.dumps(current_parameters, sort_keys=True)}",
            f"Recent outcomes: {json.dumps(outcomes, sort_keys=True)}",
        ]
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
