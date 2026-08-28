"""Tests for typed, bounded graph workflow orchestration."""

from __future__ import annotations

from threading import Barrier
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from workflows import (
    CancellationToken,
    GraphDefinitionError,
    GraphWorkflowEngine,
    NodeContract,
    NodeExecutionError,
    NodeStatus,
    RetryPolicy,
    WorkflowDefinition,
    WorkflowStatus,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowInput(StrictModel):
    value: int


class ValueArtifact(StrictModel):
    value: int


class SumArtifact(StrictModel):
    total: int


def _root_input(
    workflow_input: BaseModel,
    _dependencies: dict[str, BaseModel] | Any,
) -> dict[str, Any]:
    return workflow_input.model_dump()


def _workflow(*nodes: NodeContract) -> WorkflowDefinition:
    return WorkflowDefinition(
        name="test_graph",
        version=1,
        input_schema=WorkflowInput,
        nodes=nodes,
    )


def test_diamond_graph_fans_out_and_fans_in_with_typed_artifacts() -> None:
    barrier = Barrier(2, timeout=1)

    def parallel_handler(node_input: BaseModel) -> dict[str, int]:
        validated = ValueArtifact.model_validate(node_input)
        barrier.wait()
        return {"value": validated.value * 2}

    left = NodeContract(
        node_id="left",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=parallel_handler,
    )
    right = NodeContract(
        node_id="right",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=parallel_handler,
    )
    merge = NodeContract(
        node_id="merge",
        input_schema=SumArtifact,
        output_schema=SumArtifact,
        dependencies=("left", "right"),
        build_input=lambda _root, dependencies: {
            "total": sum(
                ValueArtifact.model_validate(artifact).value
                for artifact in dependencies.values()
            )
        },
        handler=lambda node_input: node_input,
    )

    result = GraphWorkflowEngine(max_workers=2).run(
        _workflow(left, right, merge),
        {"value": 3},
    )

    assert result.status is WorkflowStatus.COMPLETED
    assert result.nodes["left"].output == {"value": 6}
    assert result.nodes["right"].output == {"value": 6}
    assert result.nodes["merge"].output == {"total": 12}


def test_failed_branch_is_isolated_and_descendant_is_skipped() -> None:
    def fail(_node_input: BaseModel) -> dict[str, int]:
        raise RuntimeError("provider response containing a secret")

    failed = NodeContract(
        node_id="failed",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=fail,
    )
    child = NodeContract(
        node_id="child",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        dependencies=("failed",),
        build_input=lambda _root, dependencies: dependencies["failed"],
        handler=lambda node_input: node_input,
    )
    healthy = NodeContract(
        node_id="healthy",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=lambda node_input: node_input,
    )

    result = GraphWorkflowEngine(max_workers=2).run(
        _workflow(failed, child, healthy),
        {"value": 4},
    )

    assert result.status is WorkflowStatus.PARTIAL
    assert result.nodes["failed"].status is NodeStatus.FAILED
    assert result.nodes["failed"].error_code == "RuntimeError"
    assert "secret" not in (result.nodes["failed"].error_detail or "")
    assert result.nodes["child"].status is NodeStatus.SKIPPED
    assert result.nodes["healthy"].status is NodeStatus.COMPLETED


def test_node_retries_only_up_to_its_bounded_policy() -> None:
    attempts: list[int] = []

    def succeed_on_second(node_input: BaseModel) -> BaseModel:
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("temporary")
        return node_input

    node = NodeContract(
        node_id="retryable",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=succeed_on_second,
        retry=RetryPolicy(max_attempts=2),
    )

    result = GraphWorkflowEngine().run(_workflow(node), {"value": 5})

    assert result.status is WorkflowStatus.COMPLETED
    assert result.nodes["retryable"].attempts == 2
    assert len(attempts) == 2


def test_invalid_node_output_fails_contract_validation() -> None:
    node = NodeContract(
        node_id="invalid_output",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=lambda _node_input: {"unexpected": 3},
    )

    result = GraphWorkflowEngine().run(_workflow(node), {"value": 1})

    assert result.status is WorkflowStatus.FAILED
    assert result.nodes["invalid_output"].status is NodeStatus.FAILED
    assert result.nodes["invalid_output"].error_code == "ValidationError"


def test_workflow_input_is_validated_before_any_node_runs() -> None:
    node = NodeContract(
        node_id="unused",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=lambda node_input: node_input,
    )

    with pytest.raises(ValidationError):
        GraphWorkflowEngine().run(_workflow(node), {"wrong": 1})


def test_cancelled_workflow_does_not_start_nodes() -> None:
    token = CancellationToken()
    token.cancel()
    node = NodeContract(
        node_id="never_started",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=lambda node_input: node_input,
    )

    result = GraphWorkflowEngine().run(
        _workflow(node),
        {"value": 1},
        cancellation_token=token,
    )

    assert result.status is WorkflowStatus.CANCELLED
    assert result.nodes["never_started"].status is NodeStatus.CANCELLED
    assert result.nodes["never_started"].attempts == 0


def test_node_receives_only_declared_dependency_outputs() -> None:
    first = NodeContract(
        node_id="first",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=lambda node_input: node_input,
    )
    isolated = NodeContract(
        node_id="isolated",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=lambda _root, dependencies: dependencies["first"],
        handler=lambda node_input: node_input,
    )

    result = GraphWorkflowEngine().run(_workflow(first, isolated), {"value": 1})

    assert result.nodes["first"].status is NodeStatus.COMPLETED
    assert result.nodes["isolated"].status is NodeStatus.FAILED
    assert result.nodes["isolated"].error_code == "KeyError"


def test_unknown_dependency_is_rejected() -> None:
    node = NodeContract(
        node_id="consumer",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        dependencies=("missing",),
        build_input=lambda _root, dependencies: dependencies["missing"],
        handler=lambda node_input: node_input,
    )

    with pytest.raises(GraphDefinitionError, match="unknown dependencies"):
        _workflow(node)


def test_dependency_cycle_is_rejected() -> None:
    first = NodeContract(
        node_id="first",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        dependencies=("second",),
        build_input=lambda _root, dependencies: dependencies["second"],
        handler=lambda node_input: node_input,
    )
    second = NodeContract(
        node_id="second",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        dependencies=("first",),
        build_input=lambda _root, dependencies: dependencies["first"],
        handler=lambda node_input: node_input,
    )

    with pytest.raises(GraphDefinitionError, match="dependency cycle"):
        _workflow(first, second)


def test_fail_fast_mode_raises_without_exposing_provider_error() -> None:
    def fail(_node_input: BaseModel) -> dict[str, int]:
        raise RuntimeError("sensitive provider payload")

    node = NodeContract(
        node_id="failed",
        input_schema=ValueArtifact,
        output_schema=ValueArtifact,
        build_input=_root_input,
        handler=fail,
    )

    with pytest.raises(NodeExecutionError) as error:
        GraphWorkflowEngine(fail_fast=True).run(_workflow(node), {"value": 1})

    assert "sensitive provider payload" not in str(error.value)


@pytest.mark.parametrize("attempts", [0, 4])
def test_retry_policy_rejects_unsafe_attempt_counts(attempts: int) -> None:
    with pytest.raises(GraphDefinitionError, match="max_attempts"):
        RetryPolicy(max_attempts=attempts)


@pytest.mark.parametrize("workers", [0, 17])
def test_engine_rejects_unsafe_worker_counts(workers: int) -> None:
    with pytest.raises(ValueError, match="max_workers"):
        GraphWorkflowEngine(max_workers=workers)
