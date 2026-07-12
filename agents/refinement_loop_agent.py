"""Controlled refinement loop agent.

MVP simplification: semantic drift checks are rule-based keyword/pattern
checks. Future phases may add model-assisted evaluation through
ModelOrchestrationAgent while still treating core_intent as immutable.
"""

import json
import re
import sqlite3
import uuid
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
AUTO_ACTION_PATTERNS = [
    r"\bauto[- ]?send",
    r"\bautomatically send",
    r"\bsend.*linkedin",
    r"\bconnection request.*automatic",
    r"\bscrap",
    r"\bcrawl",
    r"\bpublish.*linkedin",
    r"\bpost.*automatically",
    r"\bbypass.*approval",
    r"\bwithout.*approval",
    r"\bdraft-only.*off",
]
OUTREACH_OUTCOME_METRICS = {
    "replied_positive": 1.0,
    "replied_neutral": 0.6,
    "replied_negative": 0.0,
    "no_reply": 0.0,
    "meeting_booked": 1.0,
    "not_relevant": 0.0,
    "manually_sent": 0.2,
    "custom_note": 0.5,
}
CONTENT_OUTCOME_METRICS = {
    "good_engagement": 1.0,
    "low_engagement": 0.0,
    "comments_positive": 1.0,
    "comments_negative": 0.0,
    "saved_for_later": 0.5,
    "discarded": 0.0,
    "custom_note": 0.5,
}


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

    def record_explicit_outcome(
        self,
        target_type: str,
        target_id: int,
        outcome: str,
        notes: str | None,
        database: sqlite3.Connection | str | Path,
        source: str = "telegram_command",
    ) -> dict[str, Any]:
        """Persist an explicit user-reported outcome for refinement analysis."""
        agent_name = _agent_for_target_type(target_type)
        metric_value = _metric_for_outcome(target_type, outcome)
        connection, should_close = _coerce_connection(database)
        try:
            _ensure_target_exists(connection, target_type, target_id)
            related_interaction_id = (
                _latest_relevant_interaction_id(connection, target_id)
                if target_type == "outreach"
                else None
            )
            parameter_version = _active_version_or_one(connection, agent_name)
            cursor = connection.execute(
                """
                INSERT INTO refinement_outcomes (
                    agent_name,
                    parameter_version,
                    metric_value,
                    target_type,
                    target_id,
                    related_interaction_id,
                    outcome,
                    notes,
                    source,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_name,
                    parameter_version,
                    metric_value,
                    target_type,
                    target_id,
                    related_interaction_id,
                    outcome,
                    notes,
                    source,
                    _utc_now(),
                ),
            )
            connection.commit()
            return {
                "id": cursor.lastrowid,
                "target_type": target_type,
                "target_id": target_id,
                "related_interaction_id": related_interaction_id,
                "outcome": outcome,
                "notes": notes,
                "agent_name": agent_name,
                "parameter_version": parameter_version,
                "metric_value": metric_value,
                "source": source,
            }
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
            core_intent_rules = _core_intent_rules(connection)
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
        proposed_parameters = _filter_to_allowed_parameters(
            proposed_parameters,
            current_parameters,
        )
        core_intent_check = self.validate_against_core_intent(
            proposed_parameters,
            core_intent_rules,
        )
        risk_level = "low" if core_intent_check["passed"] else "high"

        return {
            "agent_name": agent_name,
            "current_version": current_version,
            "proposed_version": current_version + 1,
            "proposed_parameters": proposed_parameters,
            "rationale": rationale,
            "evidence": outcomes,
            "risk_level": risk_level,
            "core_intent_check": core_intent_check,
            "status": "proposed",
        }

    def run_report_only_refinement_loop(
        self,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Run the Phase 6A report-only loop and append one run record."""
        run_id = str(uuid.uuid4())
        started_at = _utc_now()
        connection, should_close = _coerce_connection(database)
        try:
            constraints = _loop_constraints(connection)
            mode = str(constraints.get("mode", "report_only"))
            metadata: dict[str, Any] = {
                "constraints": constraints,
                "checker_rejections": [],
            }
            if _constraint_bool(constraints, "loop_paused"):
                _append_loop_run(
                    connection=connection,
                    run_id=run_id,
                    loop_type="refinement_suggestions",
                    mode=str(constraints.get("mode", "report_only")),
                    started_at=started_at,
                    completed_at=_utc_now(),
                    status="paused",
                    outcomes_considered_count=0,
                    proposals_created_count=0,
                    proposals_applied_count=0,
                    error_message=None,
                    metadata=metadata,
                )
                connection.commit()
                return {
                    "run_id": run_id,
                    "status": "paused",
                    "mode": "report_only",
                    "message": "Refinement loop is paused. Report-only. No changes have been applied.",
                    "constraints": constraints,
                    "suggestions": [],
                }
            if mode not in {"report_only", "assisted"}:
                constraints["mode"] = "report_only"
            outcomes = _recent_all_outcomes(connection)
            core_intent_rules = _core_intent_rules(connection)
            active_parameters_by_agent = {
                agent_name: _active_parameters(connection, agent_name)
                for agent_name in get_args(RefinableAgentName)
            }
            if not outcomes:
                _append_loop_run(
                    connection=connection,
                    run_id=run_id,
                    loop_type="refinement_suggestions",
                    mode=str(constraints.get("mode", "report_only")),
                    started_at=started_at,
                    completed_at=_utc_now(),
                    status="no_op",
                    outcomes_considered_count=0,
                    proposals_created_count=0,
                    proposals_applied_count=0,
                    error_message=None,
                    metadata={
                        **metadata,
                        "reason": "no_outcomes",
                    },
                )
                connection.commit()
                return {
                    "run_id": run_id,
                    "status": "no_op",
                    "mode": "report_only",
                    "message": "No refinement outcomes found. Report-only. No changes have been applied.",
                    "constraints": constraints,
                    "suggestions": [],
                }

            raw_proposals = self._make_report_only_proposals(
                outcomes=outcomes,
                active_parameters_by_agent=active_parameters_by_agent,
                constraints=constraints,
            )
            suggestions: list[dict[str, Any]] = []
            max_proposals = _constraint_int(constraints, "max_proposals_per_run", 3)
            for proposal in raw_proposals:
                checker_result = self._check_report_only_proposal(
                    proposal=proposal,
                    active_parameters_by_agent=active_parameters_by_agent,
                    core_intent_rules=core_intent_rules,
                    constraints=constraints,
                )
                if checker_result["passed"]:
                    saved_proposal = _save_refinement_proposal(
                        connection=connection,
                        run_id=run_id,
                        proposal=proposal,
                        checker_result=checker_result,
                    )
                    suggestions.append(saved_proposal)
                    if len(suggestions) >= max_proposals:
                        break
                else:
                    metadata["checker_rejections"].append(
                        {**proposal, "checker": checker_result}
                    )

            status = "completed" if suggestions else "no_op"
            _append_loop_run(
                connection=connection,
                run_id=run_id,
                loop_type="refinement_suggestions",
                mode=str(constraints.get("mode", "report_only")),
                started_at=started_at,
                completed_at=_utc_now(),
                status=status,
                outcomes_considered_count=len(outcomes),
                proposals_created_count=len(suggestions),
                proposals_applied_count=0,
                error_message=None,
                metadata=metadata,
            )
            connection.commit()
            return {
                "run_id": run_id,
                "status": status,
                "mode": constraints.get("mode", "report_only"),
                "message": "Report-only. No changes have been applied.",
                "constraints": constraints,
                "suggestions": suggestions,
                "rejected_proposals": metadata["checker_rejections"],
            }
        except Exception as exc:
            _append_loop_run(
                connection=connection,
                run_id=run_id,
                loop_type="refinement_suggestions",
                mode="report_only",
                started_at=started_at,
                completed_at=_utc_now(),
                status="failed",
                outcomes_considered_count=0,
                proposals_created_count=0,
                proposals_applied_count=0,
                error_message=str(exc),
                metadata={},
            )
            connection.commit()
            raise
        finally:
            if should_close:
                connection.close()

    def _make_report_only_proposals(
        self,
        *,
        outcomes: list[dict[str, Any]],
        active_parameters_by_agent: dict[str, dict[str, str]],
        constraints: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Maker step: generate candidate refinements without validation."""
        _ = constraints
        proposals: list[dict[str, Any]] = []
        outcomes_by_agent: dict[str, list[dict[str, Any]]] = {}
        for outcome in outcomes:
            outcomes_by_agent.setdefault(str(outcome["agent_name"]), []).append(outcome)
        for agent_name, agent_outcomes in outcomes_by_agent.items():
            parameters = active_parameters_by_agent.get(agent_name, {})
            if not parameters:
                continue
            parameter_key, current_value = next(iter(parameters.items()))
            positive_count = sum(
                1 for outcome in agent_outcomes if float(outcome["metric_value"]) >= 0.6
            )
            proposed_value = (
                f"{current_value} | emphasize specific evidence"
                if positive_count
                else f"{current_value} | make opener more concrete"
            )
            proposals.append(
                {
                    "target_area": agent_name,
                    "parameter_name": parameter_key,
                    "current_value": current_value,
                    "proposed_value": proposed_value,
                    "reason": "Recent explicit outcomes suggest a small, reversible wording adjustment.",
                    "evidence": agent_outcomes[:5],
                }
            )
        return proposals

    def _check_report_only_proposal(
        self,
        *,
        proposal: dict[str, Any],
        active_parameters_by_agent: dict[str, dict[str, str]],
        core_intent_rules: list[dict[str, Any]],
        constraints: dict[str, str],
    ) -> dict[str, Any]:
        """Checker step: validate report-only proposals before display."""
        agent_name = str(proposal.get("target_area", ""))
        parameter_name = str(proposal.get("parameter_name", ""))
        proposed_value = str(proposal.get("proposed_value", ""))
        active_parameters = active_parameters_by_agent.get(agent_name, {})
        if parameter_name not in active_parameters:
            return _checker_failed("Parameter is not currently refinable.")
        if not _constraint_bool(constraints, "human_approval_required"):
            return _checker_failed("Human approval requirement is disabled.")
        if constraints.get("mode") not in {"report_only", "assisted"}:
            return _checker_failed("Loop mode must be report_only or assisted.")
        core_check = self.validate_against_core_intent(
            {parameter_name: proposed_value},
            core_intent_rules,
        )
        if not core_check["passed"]:
            return _checker_failed(str(core_check["warning"]), risk_level="high")
        if not _is_specific_and_reversible(proposal):
            return _checker_failed("Proposal is not specific and reversible.")
        return {
            "passed": True,
            "status": "approved_for_report",
            "risk_level": "low",
            "reason": "Proposal targets one refinable parameter, preserves constraints, and is reversible.",
        }

    def apply_persisted_proposal(
        self,
        proposal_id: str,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Apply a pending proposal after human approval and re-validation."""
        connection, should_close = _coerce_connection(database)
        try:
            proposal = _get_refinement_proposal_row(connection, proposal_id)
            if proposal is None:
                raise RefinementLoopError("Refinement proposal was not found.")
            if proposal["status"] != "pending_approval":
                raise RefinementLoopError(
                    f"Refinement proposal is already {proposal['status']}."
                )
            constraints = _loop_constraints(connection)
            if _constraint_bool(constraints, "loop_paused"):
                raise RefinementLoopError("Refinement loop is paused. No changes were applied.")
            if constraints.get("mode") != "assisted":
                raise RefinementLoopError(
                    "The refinement loop is currently report-only. No changes were applied."
                )
            if not _constraint_bool(constraints, "human_approval_required"):
                raise RefinementLoopError("Human approval requirement is disabled.")
            if _applies_for_run(connection, proposal["run_id"]) >= _constraint_int(
                constraints,
                "max_apply_per_run",
                1,
            ):
                raise RefinementLoopError("Maximum applies for this run has been reached.")

            active_parameters_by_agent = {
                str(proposal["target_area"]): _active_parameters(
                    connection,
                    str(proposal["target_area"]),
                )
            }
            core_intent_rules = _core_intent_rules(connection)
            checker_result = self._check_report_only_proposal(
                proposal={
                    "target_area": proposal["target_area"],
                    "parameter_name": proposal["parameter_name"],
                    "current_value": proposal["current_value"],
                    "proposed_value": proposal["proposed_value"],
                    "reason": proposal["reason"],
                    "evidence": json.loads(proposal["evidence_json"] or "[]"),
                },
                active_parameters_by_agent=active_parameters_by_agent,
                core_intent_rules=core_intent_rules,
                constraints=constraints,
            )
            if not checker_result["passed"]:
                _append_history_event(
                    connection=connection,
                    agent_name=str(proposal["target_area"]),
                    version=_current_version(connection, str(proposal["target_area"])),
                    event={
                        "event": "proposal_failed_validation",
                        "proposal_id": proposal_id,
                        "parameter_name": proposal["parameter_name"],
                        "failure_reason": checker_result["reason"],
                        "status": "failed_validation",
                    },
                    why="Proposal failed re-validation before apply.",
                    core_intent_check_passed=False,
                    accepted=False,
                )
                _mark_proposal_decided(
                    connection,
                    proposal_id,
                    "failed_validation",
                    {"checker": checker_result},
                )
                connection.commit()
                raise RefinementLoopError("Proposal failed validation. No changes were applied.")

            current_value = active_parameters_by_agent[str(proposal["target_area"])].get(
                str(proposal["parameter_name"])
            )
            if current_value != proposal["current_value"]:
                _append_history_event(
                    connection=connection,
                    agent_name=str(proposal["target_area"]),
                    version=_current_version(connection, str(proposal["target_area"])),
                    event={
                        "event": "proposal_failed_validation",
                        "proposal_id": proposal_id,
                        "parameter_name": proposal["parameter_name"],
                        "failure_reason": "stale_current_value",
                        "expected_current_value": proposal["current_value"],
                        "actual_current_value": current_value,
                        "status": "failed_validation",
                    },
                    why="Proposal was stale at apply time.",
                    core_intent_check_passed=True,
                    accepted=False,
                )
                _mark_proposal_decided(
                    connection,
                    proposal_id,
                    "failed_validation",
                    {"reason": "stale_current_value", "actual_value": current_value},
                )
                connection.commit()
                raise RefinementLoopError(
                    "This proposal is stale because the parameter changed. Please run /suggest_refinements again."
                )

            new_version = _current_version(connection, str(proposal["target_area"])) + 1
            now = _utc_now()
            connection.execute(
                """
                UPDATE refinable_parameters
                SET is_active = 0
                WHERE agent_name = ? AND parameter_key = ?
                """,
                (proposal["target_area"], proposal["parameter_name"]),
            )
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
                (
                    proposal["target_area"],
                    proposal["parameter_name"],
                    proposal["proposed_value"],
                    new_version,
                    now,
                ),
            )
            _append_history(
                connection=connection,
                agent_name=str(proposal["target_area"]),
                version=new_version,
                what_changed=json.dumps(
                    {
                        "event": "proposal_applied",
                        "proposal_id": proposal_id,
                        "parameter_name": proposal["parameter_name"],
                        "old_value": proposal["current_value"],
                        "new_value": proposal["proposed_value"],
                        "status": "applied",
                        "source": "telegram_callback",
                    },
                    sort_keys=True,
                ),
                why=str(proposal["reason"]),
                diff_against_v1=json.dumps(
                    {proposal["parameter_name"]: proposal["proposed_value"]},
                    sort_keys=True,
                ),
                core_intent_check_passed=True,
                accepted=True,
            )
            _mark_proposal_decided(connection, proposal_id, "applied", {"checker": checker_result})
            connection.execute(
                """
                UPDATE refinement_loop_runs
                SET proposals_applied_count = proposals_applied_count + 1
                WHERE run_id = ?
                """,
                (proposal["run_id"],),
            )
            connection.commit()
            return {
                "status": "applied",
                "proposal_id": proposal_id,
                "agent_name": proposal["target_area"],
                "parameter_name": proposal["parameter_name"],
                "version": new_version,
            }
        finally:
            if should_close:
                connection.close()

    def reject_persisted_proposal(
        self,
        proposal_id: str,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Reject a pending proposal without changing parameters."""
        connection, should_close = _coerce_connection(database)
        try:
            proposal = _get_refinement_proposal_row(connection, proposal_id)
            if proposal is None:
                raise RefinementLoopError("Refinement proposal was not found.")
            if proposal["status"] == "rejected":
                raise RefinementLoopError("Refinement proposal is already rejected.")
            if proposal["status"] == "applied":
                raise RefinementLoopError("Refinement proposal is already applied.")
            _append_history_event(
                connection=connection,
                agent_name=str(proposal["target_area"]),
                version=_current_version(connection, str(proposal["target_area"])),
                event={
                    "event": "proposal_rejected",
                    "proposal_id": proposal_id,
                    "parameter_name": proposal["parameter_name"],
                    "status": "rejected",
                    "reason": "Human rejected proposal.",
                },
                why="Human rejected proposal.",
                core_intent_check_passed=True,
                accepted=False,
            )
            _mark_proposal_decided(connection, proposal_id, "rejected", {})
            connection.commit()
            return {"status": "rejected", "proposal_id": proposal_id}
        finally:
            if should_close:
                connection.close()

    def rollback_applied_refinement(
        self,
        refinement_id: int,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Rollback one applied refinement history event by appending history."""
        connection, should_close = _coerce_connection(database)
        try:
            history = connection.execute(
                """
                SELECT *
                FROM refinement_history
                WHERE id = ?
                """,
                (refinement_id,),
            ).fetchone()
            if history is None:
                raise RefinementLoopError(f"Refinement id {refinement_id} does not exist.")
            event = _history_event(history)
            if history["accepted"] != 1 or event.get("event") != "proposal_applied":
                raise RefinementLoopError("Only applied refinements can be rolled back.")
            parameter_name = str(event.get("parameter_name") or "")
            old_value = event.get("old_value")
            new_value = event.get("new_value")
            if not parameter_name or old_value is None or new_value is None:
                _append_history_event(
                    connection=connection,
                    agent_name=str(history["agent_name"]),
                    version=int(history["version"]),
                    event={
                        "event": "rollback_failed",
                        "rollback_from_refinement_id": refinement_id,
                        "failure_reason": "missing_old_or_new_value",
                        "status": "failed",
                    },
                    why="Rollback failed because the applied event lacks old/new values.",
                    core_intent_check_passed=False,
                    accepted=False,
                )
                connection.commit()
                raise RefinementLoopError("Applied refinement is missing rollback values.")
            constraints = _loop_constraints(connection)
            if _constraint_bool(constraints, "loop_paused"):
                raise RefinementLoopError("Refinement loop is paused. No changes were applied.")
            if not _constraint_bool(constraints, "human_approval_required"):
                raise RefinementLoopError("Human approval requirement is disabled.")
            active_parameters = _active_parameters(connection, str(history["agent_name"]))
            if parameter_name not in active_parameters:
                _append_rollback_failed(
                    connection,
                    history,
                    refinement_id,
                    "non_refinable_parameter",
                )
                connection.commit()
                raise RefinementLoopError("Rollback target parameter is not refinable.")
            current_value = active_parameters[parameter_name]
            if current_value != new_value:
                _append_rollback_failed(
                    connection,
                    history,
                    refinement_id,
                    "stale_current_value",
                    {"actual_current_value": current_value, "expected_value": new_value},
                )
                connection.commit()
                raise RefinementLoopError(
                    "This refinement cannot be rolled back automatically because the parameter has changed since it was applied. Please review manually."
                )
            checker_result = self._check_report_only_proposal(
                proposal={
                    "target_area": history["agent_name"],
                    "parameter_name": parameter_name,
                    "current_value": str(new_value),
                    "proposed_value": str(old_value),
                    "reason": "Rollback to prior approved value.",
                    "evidence": [],
                },
                active_parameters_by_agent={
                    str(history["agent_name"]): active_parameters
                },
                core_intent_rules=_core_intent_rules(connection),
                constraints={
                    **constraints,
                    "mode": constraints.get("mode", "assisted"),
                },
            )
            if not checker_result["passed"]:
                _append_rollback_failed(
                    connection,
                    history,
                    refinement_id,
                    "core_intent_or_checker_violation",
                    {"checker": checker_result},
                )
                connection.commit()
                raise RefinementLoopError("Rollback failed validation. No changes were applied.")
            new_version = _current_version(connection, str(history["agent_name"])) + 1
            now = _utc_now()
            connection.execute(
                """
                UPDATE refinable_parameters
                SET is_active = 0
                WHERE agent_name = ? AND parameter_key = ?
                """,
                (history["agent_name"], parameter_name),
            )
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
                (
                    history["agent_name"],
                    parameter_name,
                    str(old_value),
                    new_version,
                    now,
                ),
            )
            rollback_history_id = _append_history_event(
                connection=connection,
                agent_name=str(history["agent_name"]),
                version=new_version,
                event={
                    "event": "rollback_applied",
                    "rollback_from_refinement_id": refinement_id,
                    "parameter_name": parameter_name,
                    "old_value": new_value,
                    "new_value": old_value,
                    "status": "applied",
                },
                why="Human requested rollback.",
                core_intent_check_passed=True,
                accepted=True,
            )
            connection.commit()
            return {
                "status": "rolled_back",
                "refinement_id": refinement_id,
                "rollback_history_id": rollback_history_id,
                "agent_name": history["agent_name"],
                "parameter_name": parameter_name,
                "restored_value": old_value,
                "version": new_version,
            }
        finally:
            if should_close:
                connection.close()

    def recent_refinement_history(
        self,
        database: sqlite3.Connection | str | Path,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return recent refinement history events for operator review."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM refinement_history
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_history_row_to_summary(row) for row in rows]
        finally:
            if should_close:
                connection.close()

    def get_refinement_status(
        self,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Return read-only operator status for the refinement loop."""
        connection, should_close = _coerce_connection(database)
        try:
            constraints = _loop_constraints(connection)
            recent_run = connection.execute(
                """
                SELECT run_id, status, mode, completed_at, error_message
                FROM refinement_loop_runs
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            proposal_counts = _proposal_status_counts(connection)
            history_counts = _history_event_counts(connection)
            return {
                "mode": constraints.get("mode", "report_only"),
                "loop_paused": _constraint_bool(constraints, "loop_paused"),
                "max_proposals_per_run": _constraint_int(
                    constraints,
                    "max_proposals_per_run",
                    3,
                ),
                "max_apply_per_run": _constraint_int(
                    constraints,
                    "max_apply_per_run",
                    1,
                ),
                "recent_run": dict(recent_run) if recent_run is not None else None,
                "pending_proposals_count": proposal_counts.get("pending_approval", 0),
                "applied_refinements_count": history_counts.get("proposal_applied", 0),
                "rejected_refinements_count": history_counts.get("proposal_rejected", 0),
                "failed_validation_count": history_counts.get(
                    "proposal_failed_validation",
                    0,
                ),
            }
        finally:
            if should_close:
                connection.close()

    def get_refinement_report(
        self,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Return a read-only refinement report. No parameters are changed."""
        connection, should_close = _coerce_connection(database)
        try:
            history = [
                _history_row_to_summary(row)
                for row in connection.execute(
                    """
                    SELECT *
                    FROM refinement_history
                    ORDER BY created_at DESC, id DESC
                    LIMIT 25
                    """
                ).fetchall()
            ]
            failed_reasons = _failed_validation_reasons(history)
            pending_proposals = [
                _proposal_row_to_dict(row)
                for row in connection.execute(
                    """
                    SELECT *
                    FROM refinement_proposals
                    WHERE status = 'pending_approval'
                    ORDER BY created_at ASC, id ASC
                    LIMIT 10
                    """
                ).fetchall()
            ]
            all_recent_proposals = [
                _proposal_row_to_dict(row)
                for row in connection.execute(
                    """
                    SELECT *
                    FROM refinement_proposals
                    ORDER BY created_at DESC, id DESC
                    LIMIT 15
                    """
                ).fetchall()
            ]
            current_parameters = {
                agent_name: _active_parameters(connection, agent_name)
                for agent_name in get_args(RefinableAgentName)
            }
            recent_outcomes = _recent_all_outcomes(connection)[:10]
            event_counts = _history_event_counts(connection)
            proposal_counts = _proposal_status_counts(connection)
            return {
                "message": "This is a report only. No changes were applied.",
                "recent_outcomes": recent_outcomes,
                "recent_proposals": all_recent_proposals,
                "pending_proposals": pending_proposals,
                "proposal_counts": proposal_counts,
                "event_counts": event_counts,
                "rollbacks_applied_count": event_counts.get("rollback_applied", 0),
                "common_failed_validation_reasons": failed_reasons,
                "current_parameters": current_parameters,
                "recommended_next_action": _recommended_next_action(
                    pending_count=proposal_counts.get("pending_approval", 0),
                    failed_reasons=failed_reasons,
                    recent_outcomes_count=len(recent_outcomes),
                ),
            }
        finally:
            if should_close:
                connection.close()

    def get_persisted_proposal_reasoning(
        self,
        proposal_id: str,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Return user-facing rationale for a persisted proposal."""
        connection, should_close = _coerce_connection(database)
        try:
            proposal = _get_refinement_proposal_row(connection, proposal_id)
            if proposal is None:
                raise RefinementLoopError("Refinement proposal was not found.")
            return _proposal_row_to_dict(proposal)
        finally:
            if should_close:
                connection.close()

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
        for pattern in AUTO_ACTION_PATTERNS:
            if re.search(pattern, text):
                return {
                    "passed": False,
                    "warning": "Proposed parameters may violate core intent by enabling automation, scraping, or bypassing human approval.",
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
            current_parameters = _active_parameters(connection, agent_name)
            out_of_scope = [
                key for key in proposed_parameters if key not in current_parameters
            ]
            if out_of_scope:
                raise RefinementLoopError(
                    "Proposed parameters include non-refinable keys: "
                    + ", ".join(sorted(out_of_scope))
                )
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
                what_changed=json.dumps(
                    {
                        "event": "apply_refinement",
                        "old_parameters": current_parameters,
                        "new_parameters": proposed_parameters,
                        "source": proposal.get("source", "telegram_callback"),
                    },
                    sort_keys=True,
                ),
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
                what_changed=json.dumps(
                    {
                        "event": "rollback",
                        "target_version": target_version,
                        "restored_parameters": {
                            row["parameter_key"]: row["parameter_value"]
                            for row in rows
                        },
                    },
                    sort_keys=True,
                ),
                why="Human requested rollback.",
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


def _agent_for_target_type(target_type: str) -> str:
    if target_type == "outreach":
        return "outreach_draft_agent"
    if target_type == "content":
        return "content_inspiration_agent"
    raise RefinementLoopError(
        "target_type must be one of: outreach, content."
    )


def _metric_for_outcome(target_type: str, outcome: str) -> float:
    metrics = (
        OUTREACH_OUTCOME_METRICS
        if target_type == "outreach"
        else CONTENT_OUTCOME_METRICS
        if target_type == "content"
        else None
    )
    if metrics is None:
        raise RefinementLoopError("target_type must be one of: outreach, content.")
    if outcome not in metrics:
        allowed = ", ".join(sorted(metrics))
        raise RefinementLoopError(
            f"Invalid {target_type} outcome '{outcome}'. Allowed values: {allowed}."
        )
    return metrics[outcome]


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


def _active_version_or_one(connection: sqlite3.Connection, agent_name: str) -> int:
    row = connection.execute(
        """
        SELECT version
        FROM refinable_parameters
        WHERE agent_name = ? AND is_active = 1
        ORDER BY version DESC
        LIMIT 1
        """,
        (agent_name,),
    ).fetchone()
    if row is None:
        return 1
    return int(row["version"])


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
        SELECT
            parameter_version,
            metric_value,
            target_type,
            target_id,
            related_interaction_id,
            outcome,
            notes,
            source,
            created_at
        FROM refinement_outcomes
        WHERE agent_name = ? AND parameter_version = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 20
        """,
        (agent_name, parameter_version),
    ).fetchall()
    return [dict(row) for row in rows]


def _recent_all_outcomes(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            agent_name,
            parameter_version,
            metric_value,
            target_type,
            target_id,
            related_interaction_id,
            outcome,
            notes,
            source,
            created_at
        FROM refinement_outcomes
        ORDER BY created_at DESC, id DESC
        LIMIT 100
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _loop_constraints(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT constraint_key, constraint_value
        FROM refinement_loop_constraints
        ORDER BY constraint_key ASC
        """
    ).fetchall()
    return {str(row["constraint_key"]): str(row["constraint_value"]) for row in rows}


def _ensure_target_exists(
    connection: sqlite3.Connection,
    target_type: str,
    target_id: int,
) -> None:
    if target_type == "outreach":
        row = connection.execute(
            "SELECT id FROM prospects WHERE id = ?",
            (target_id,),
        ).fetchone()
        if row is None:
            raise RefinementLoopError(f"Prospect id {target_id} does not exist.")
        return
    if target_type == "content":
        row = connection.execute(
            "SELECT id FROM content_posts WHERE id = ?",
            (target_id,),
        ).fetchone()
        if row is None:
            raise RefinementLoopError(f"Content post id {target_id} does not exist.")
        return
    raise RefinementLoopError("target_type must be one of: outreach, content.")


def _latest_relevant_interaction_id(
    connection: sqlite3.Connection,
    prospect_id: int,
) -> int | None:
    row = connection.execute(
        """
        SELECT id
        FROM interactions
        WHERE prospect_id = ?
            AND interaction_type IN (
                'linkedin_connection_request',
                'outreach_draft',
                'follow_up_draft',
                'reply_logged',
                'meeting_confirmed'
            )
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (prospect_id,),
    ).fetchone()
    return None if row is None else int(row["id"])


def _filter_to_allowed_parameters(
    proposed_parameters: dict[str, Any],
    current_parameters: dict[str, str],
) -> dict[str, Any]:
    if not current_parameters:
        return proposed_parameters
    return {
        key: value
        for key, value in proposed_parameters.items()
        if key in current_parameters
    }


def _constraint_bool(
    constraints: dict[str, str],
    key: str,
    default: bool = False,
) -> bool:
    raw_value = constraints.get(key)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _constraint_int(
    constraints: dict[str, str],
    key: str,
    default: int,
) -> int:
    raw_value = constraints.get(key)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _checker_failed(reason: str, risk_level: str = "medium") -> dict[str, Any]:
    return {
        "passed": False,
        "status": "rejected_by_checker",
        "risk_level": risk_level,
        "reason": reason,
    }


def _is_specific_and_reversible(proposal: dict[str, Any]) -> bool:
    parameter_name = str(proposal.get("parameter_name", "")).strip()
    current_value = str(proposal.get("current_value", "")).strip()
    proposed_value = str(proposal.get("proposed_value", "")).strip()
    vague_terms = {"better", "improve", "optimize", "more engaging", "best"}
    if not parameter_name or not current_value or not proposed_value:
        return False
    if proposed_value == current_value:
        return False
    if proposed_value.lower() in vague_terms:
        return False
    return True


def _append_loop_run(
    *,
    connection: sqlite3.Connection,
    run_id: str,
    loop_type: str,
    mode: str,
    started_at: str,
    completed_at: str | None,
    status: str,
    outcomes_considered_count: int,
    proposals_created_count: int,
    proposals_applied_count: int,
    error_message: str | None,
    metadata: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO refinement_loop_runs (
            run_id,
            loop_type,
            mode,
            started_at,
            completed_at,
            status,
            outcomes_considered_count,
            proposals_created_count,
            proposals_applied_count,
            error_message,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            loop_type,
            mode,
            started_at,
            completed_at,
            status,
            outcomes_considered_count,
            proposals_created_count,
            proposals_applied_count,
            error_message,
            json.dumps(metadata, sort_keys=True),
        ),
    )


def _save_refinement_proposal(
    *,
    connection: sqlite3.Connection,
    run_id: str,
    proposal: dict[str, Any],
    checker_result: dict[str, Any],
) -> dict[str, Any]:
    proposal_id = str(uuid.uuid4())
    now = _utc_now()
    evidence = proposal.get("evidence", [])
    metadata = {"checker": checker_result}
    connection.execute(
        """
        INSERT INTO refinement_proposals (
            proposal_id,
            run_id,
            target_area,
            parameter_name,
            current_value,
            proposed_value,
            reason,
            evidence_json,
            risk_level,
            checker_status,
            core_intent_check_status,
            status,
            created_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?)
        """,
        (
            proposal_id,
            run_id,
            proposal["target_area"],
            proposal["parameter_name"],
            proposal["current_value"],
            proposal["proposed_value"],
            proposal["reason"],
            json.dumps(evidence, sort_keys=True),
            checker_result["risk_level"],
            "passed",
            "passed",
            now,
            json.dumps(metadata, sort_keys=True),
        ),
    )
    _append_history_event(
        connection=connection,
        agent_name=str(proposal["target_area"]),
        version=_current_version(connection, str(proposal["target_area"])),
        event={
            "event": "proposal_created",
            "proposal_id": proposal_id,
            "parameter_name": proposal["parameter_name"],
            "old_value": proposal["current_value"],
            "new_value": proposal["proposed_value"],
            "status": "pending_approval",
        },
        why=str(proposal["reason"]),
        core_intent_check_passed=True,
        accepted=False,
    )
    return {
        **proposal,
        "proposal_id": proposal_id,
        "run_id": run_id,
        "status": "pending_approval",
        "checker": checker_result,
    }


def _get_refinement_proposal_row(
    connection: sqlite3.Connection,
    proposal_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT *
        FROM refinement_proposals
        WHERE proposal_id = ?
        """,
        (proposal_id,),
    ).fetchone()


def _proposal_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "proposal_id": row["proposal_id"],
        "run_id": row["run_id"],
        "target_area": row["target_area"],
        "parameter_name": row["parameter_name"],
        "current_value": row["current_value"],
        "proposed_value": row["proposed_value"],
        "reason": row["reason"],
        "evidence": json.loads(row["evidence_json"] or "[]"),
        "risk_level": row["risk_level"],
        "checker_status": row["checker_status"],
        "core_intent_check_status": row["core_intent_check_status"],
        "status": row["status"],
        "created_at": row["created_at"],
        "decided_at": row["decided_at"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def _proposal_status_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM refinement_proposals
        GROUP BY status
        """
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _history_event_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT what_changed
        FROM refinement_history
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        event_type = str(_history_event(row).get("event", "legacy_event"))
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts


def _failed_validation_reasons(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for event in history:
        if event.get("event_type") not in {
            "proposal_failed_validation",
            "rollback_failed",
        }:
            continue
        reason = str(event.get("failure_reason") or "unspecified")
        counts[reason] = counts.get(reason, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: item[0])
    ]


def _recommended_next_action(
    *,
    pending_count: int,
    failed_reasons: list[dict[str, Any]],
    recent_outcomes_count: int,
) -> str:
    if pending_count:
        return "Review pending proposals with /suggest_refinements before applying anything."
    if failed_reasons:
        return "Review failed validation reasons before creating more proposals."
    if recent_outcomes_count == 0:
        return "Record outreach or content outcomes before running the refinement loop again."
    return "Run /suggest_refinements when you want fresh report-only proposals."


def _mark_proposal_decided(
    connection: sqlite3.Connection,
    proposal_id: str,
    status: str,
    metadata: dict[str, Any],
) -> None:
    row = _get_refinement_proposal_row(connection, proposal_id)
    existing_metadata = {}
    if row is not None:
        existing_metadata = json.loads(row["metadata_json"] or "{}")
    connection.execute(
        """
        UPDATE refinement_proposals
        SET status = ?, decided_at = ?, metadata_json = ?
        WHERE proposal_id = ?
        """,
        (
            status,
            _utc_now(),
            json.dumps({**existing_metadata, **metadata}, sort_keys=True),
            proposal_id,
        ),
    )


def _applies_for_run(connection: sqlite3.Connection, run_id: str) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS applied_count
        FROM refinement_proposals
        WHERE run_id = ? AND status = 'applied'
        """,
        (run_id,),
    ).fetchone()
    return int(row["applied_count"])


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
) -> int:
    before_metric = _average_metric(connection, agent_name, version - 1)
    after_metric = _average_metric(connection, agent_name, version)
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
    if cursor.lastrowid is None:
        raise RefinementLoopError("Could not append refinement history.")
    return int(cursor.lastrowid)


def _append_history_event(
    *,
    connection: sqlite3.Connection,
    agent_name: str,
    version: int,
    event: dict[str, Any],
    why: str,
    core_intent_check_passed: bool,
    accepted: bool,
) -> int:
    """Append one structured refinement_history event."""
    return _append_history(
        connection=connection,
        agent_name=agent_name,
        version=version,
        what_changed=json.dumps(event, sort_keys=True),
        why=why,
        diff_against_v1=json.dumps(event, sort_keys=True),
        core_intent_check_passed=core_intent_check_passed,
        accepted=accepted,
    )


def _history_event(row: sqlite3.Row) -> dict[str, Any]:
    raw_value = row["what_changed"]
    if not isinstance(raw_value, str):
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _append_rollback_failed(
    connection: sqlite3.Connection,
    history: sqlite3.Row,
    refinement_id: int,
    failure_reason: str,
    extra: dict[str, Any] | None = None,
) -> int:
    event = {
        "event": "rollback_failed",
        "rollback_from_refinement_id": refinement_id,
        "failure_reason": failure_reason,
        "status": "failed",
    }
    if extra:
        event.update(extra)
    history_event = _history_event(history)
    parameter_name = history_event.get("parameter_name")
    if parameter_name:
        event["parameter_name"] = parameter_name
    return _append_history_event(
        connection=connection,
        agent_name=str(history["agent_name"]),
        version=int(history["version"]),
        event=event,
        why=f"Rollback failed: {failure_reason}.",
        core_intent_check_passed=failure_reason != "core_intent_or_checker_violation",
        accepted=False,
    )


def _history_row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
    event = _history_event(row)
    return {
        "refinement_id": row["id"],
        "agent_name": row["agent_name"],
        "version": row["version"],
        "event_type": event.get("event", "legacy_event"),
        "parameter_name": event.get("parameter_name"),
        "old_value": event.get("old_value"),
        "new_value": event.get("new_value"),
        "failure_reason": event.get("failure_reason"),
        "rollback_from_refinement_id": event.get("rollback_from_refinement_id"),
        "status": event.get("status", "accepted" if row["accepted"] else "recorded"),
        "created_at": row["created_at"],
        "accepted": bool(row["accepted"]),
    }


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
