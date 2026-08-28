"""Bounded in-process executor for typed workflow graphs."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from workflows.contracts import (
    CancellationToken,
    MAX_GRAPH_WORKERS,
    NodeContract,
    NodeExecutionError,
    NodeRunResult,
    NodeStatus,
    WorkflowDefinition,
    WorkflowRunResult,
    WorkflowStatus,
)


class GraphWorkflowEngine:
    """Execute a validated graph with bounded fan-out and isolated failures."""

    def __init__(self, *, max_workers: int = 4, fail_fast: bool = False) -> None:
        if not 1 <= max_workers <= MAX_GRAPH_WORKERS:
            raise ValueError(
                f"max_workers must be between 1 and {MAX_GRAPH_WORKERS}."
            )
        self.max_workers = max_workers
        self.fail_fast = fail_fast

    def run(
        self,
        definition: WorkflowDefinition,
        workflow_input: BaseModel | Mapping[str, Any],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> WorkflowRunResult:
        """Run all reachable nodes and return a persistence-neutral record."""
        started_at = _utc_now()
        validated_input = definition.input_schema.model_validate(workflow_input)
        token = cancellation_token or CancellationToken()
        node_results = {
            node.node_id: NodeRunResult(
                node_id=node.node_id,
                status=NodeStatus.PENDING,
                attempts=0,
            )
            for node in definition.nodes
        }
        artifacts: dict[str, BaseModel] = {}

        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=f"workflow-{definition.name}",
        ) as executor:
            while _pending_node_ids(node_results):
                if token.is_cancelled:
                    _mark_pending(node_results, NodeStatus.CANCELLED, "workflow_cancelled")
                    break

                _skip_blocked_nodes(definition, node_results)
                ready = _ready_nodes(definition, node_results)
                if not ready:
                    break

                futures: dict[Future[tuple[NodeRunResult, BaseModel | None]], str] = {}
                for node in ready:
                    dependency_artifacts = {
                        dependency: artifacts[dependency]
                        for dependency in node.dependencies
                    }
                    node_results[node.node_id] = NodeRunResult(
                        node_id=node.node_id,
                        status=NodeStatus.RUNNING,
                        attempts=0,
                        started_at=_utc_now(),
                    )
                    future = executor.submit(
                        _execute_node,
                        node,
                        validated_input,
                        dependency_artifacts,
                        token,
                    )
                    futures[future] = node.node_id

                for future, node_id in futures.items():
                    result, artifact = future.result()
                    node_results[node_id] = result
                    if artifact is not None:
                        artifacts[node_id] = artifact
                    if result.status is NodeStatus.FAILED and self.fail_fast:
                        _mark_pending(
                            node_results,
                            NodeStatus.CANCELLED,
                            "fail_fast_cancelled",
                        )
                        raise NodeExecutionError(
                            f"Workflow node '{node_id}' failed with {result.error_code}."
                        )

        finished_at = _utc_now()
        ordered_results = {
            node.node_id: node_results[node.node_id] for node in definition.nodes
        }
        return WorkflowRunResult(
            run_id=str(uuid4()),
            workflow_name=definition.name,
            workflow_version=definition.version,
            status=_workflow_status(ordered_results),
            nodes=ordered_results,
            started_at=started_at,
            finished_at=finished_at,
        )


def _execute_node(
    node: NodeContract,
    workflow_input: BaseModel,
    dependency_artifacts: Mapping[str, BaseModel],
    cancellation_token: CancellationToken,
) -> tuple[NodeRunResult, BaseModel | None]:
    started_at = _utc_now()
    if cancellation_token.is_cancelled:
        return (
            NodeRunResult(
                node_id=node.node_id,
                status=NodeStatus.CANCELLED,
                attempts=0,
                error_code="workflow_cancelled",
                error_detail="Node did not start because cancellation was requested.",
                started_at=started_at,
                finished_at=_utc_now(),
            ),
            None,
        )

    for attempt in range(1, node.retry.max_attempts + 1):
        try:
            raw_input = node.build_input(workflow_input, dependency_artifacts)
            validated_input = node.input_schema.model_validate(raw_input)
            raw_output = node.handler(validated_input)
            validated_output = node.output_schema.model_validate(raw_output)
            return (
                NodeRunResult(
                    node_id=node.node_id,
                    status=NodeStatus.COMPLETED,
                    attempts=attempt,
                    output=validated_output.model_dump(mode="json"),
                    started_at=started_at,
                    finished_at=_utc_now(),
                ),
                validated_output,
            )
        except Exception as exc:
            if attempt == node.retry.max_attempts:
                return (
                    NodeRunResult(
                        node_id=node.node_id,
                        status=NodeStatus.FAILED,
                        attempts=attempt,
                        error_code=type(exc).__name__,
                        error_detail=(
                            "Node input construction, contract validation, or "
                            "execution failed. Provider details were not retained."
                        ),
                        started_at=started_at,
                        finished_at=_utc_now(),
                    ),
                    None,
                )
    raise AssertionError("The bounded attempt loop must always return.")


def _pending_node_ids(results: Mapping[str, NodeRunResult]) -> set[str]:
    return {
        node_id
        for node_id, result in results.items()
        if result.status is NodeStatus.PENDING
    }


def _ready_nodes(
    definition: WorkflowDefinition,
    results: Mapping[str, NodeRunResult],
) -> list[NodeContract]:
    return [
        node
        for node in definition.nodes
        if results[node.node_id].status is NodeStatus.PENDING
        and all(
            results[dependency].status is NodeStatus.COMPLETED
            for dependency in node.dependencies
        )
    ]


def _skip_blocked_nodes(
    definition: WorkflowDefinition,
    results: dict[str, NodeRunResult],
) -> None:
    changed = True
    while changed:
        changed = False
        for node in definition.nodes:
            if results[node.node_id].status is not NodeStatus.PENDING:
                continue
            if any(
                results[dependency].status
                in {NodeStatus.FAILED, NodeStatus.SKIPPED, NodeStatus.CANCELLED}
                for dependency in node.dependencies
            ):
                results[node.node_id] = NodeRunResult(
                    node_id=node.node_id,
                    status=NodeStatus.SKIPPED,
                    attempts=0,
                    error_code="dependency_unavailable",
                    error_detail="A required upstream node did not complete.",
                    finished_at=_utc_now(),
                )
                changed = True


def _mark_pending(
    results: dict[str, NodeRunResult],
    status: NodeStatus,
    error_code: str,
) -> None:
    for node_id, result in tuple(results.items()):
        if result.status is NodeStatus.PENDING:
            results[node_id] = NodeRunResult(
                node_id=node_id,
                status=status,
                attempts=0,
                error_code=error_code,
                error_detail="The node did not start.",
                finished_at=_utc_now(),
            )


def _workflow_status(results: Mapping[str, NodeRunResult]) -> WorkflowStatus:
    statuses = {result.status for result in results.values()}
    if NodeStatus.CANCELLED in statuses:
        return WorkflowStatus.CANCELLED
    completed = sum(
        result.status is NodeStatus.COMPLETED for result in results.values()
    )
    if statuses == {NodeStatus.COMPLETED}:
        return WorkflowStatus.COMPLETED
    if completed:
        return WorkflowStatus.PARTIAL
    return WorkflowStatus.FAILED


def _utc_now() -> datetime:
    return datetime.now(UTC)
