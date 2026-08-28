"""Typed contracts for deterministic graph workflow orchestration."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from threading import Event
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_GRAPH_NODES = 64
MAX_NODE_ATTEMPTS = 3
MAX_GRAPH_WORKERS = 16


class GraphDefinitionError(ValueError):
    """Raised when a graph is unsafe or structurally invalid."""


class NodeExecutionError(RuntimeError):
    """Raised when the caller requests fail-fast execution and a node fails."""


class NodeStatus(StrEnum):
    """Persistable lifecycle states for one workflow node."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class WorkflowStatus(StrEnum):
    """Persistable terminal states for one workflow run."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeRunResult(BaseModel):
    """Serializable execution record for one node."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    status: NodeStatus
    attempts: int = Field(ge=0, le=MAX_NODE_ATTEMPTS)
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowRunResult(BaseModel):
    """Serializable result returned after one bounded graph execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    workflow_name: str
    workflow_version: int = Field(ge=1)
    status: WorkflowStatus
    nodes: dict[str, NodeRunResult]
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy for a node.

    Retries are immediate in the in-process engine. Durable queue consumers can
    translate the same attempt limit into delayed delivery later.
    """

    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= MAX_NODE_ATTEMPTS:
            raise GraphDefinitionError(
                f"max_attempts must be between 1 and {MAX_NODE_ATTEMPTS}."
            )


NodeInputBuilder = Callable[
    [BaseModel, Mapping[str, BaseModel]], BaseModel | Mapping[str, Any]
]
NodeHandler = Callable[[BaseModel], BaseModel | Mapping[str, Any]]


@dataclass(frozen=True)
class NodeContract:
    """One bounded graph job with explicit input and output schemas."""

    node_id: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    build_input: NodeInputBuilder
    handler: NodeHandler
    dependencies: tuple[str, ...] = ()
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if NODE_ID_PATTERN.fullmatch(self.node_id) is None:
            raise GraphDefinitionError(
                "node_id must start with a lowercase letter and contain only "
                "lowercase letters, numbers, and underscores."
            )
        if len(set(self.dependencies)) != len(self.dependencies):
            raise GraphDefinitionError(
                f"Node '{self.node_id}' declares a dependency more than once."
            )
        if self.node_id in self.dependencies:
            raise GraphDefinitionError(
                f"Node '{self.node_id}' cannot depend on itself."
            )


@dataclass(frozen=True)
class WorkflowDefinition:
    """A validated directed acyclic graph of typed nodes."""

    name: str
    version: int
    input_schema: type[BaseModel]
    nodes: tuple[NodeContract, ...]

    def __post_init__(self) -> None:
        if NODE_ID_PATTERN.fullmatch(self.name) is None:
            raise GraphDefinitionError(
                "workflow name must use lowercase letters, numbers, and underscores."
            )
        if self.version < 1:
            raise GraphDefinitionError("workflow version must be at least 1.")
        if not self.nodes:
            raise GraphDefinitionError("A workflow must contain at least one node.")
        if len(self.nodes) > MAX_GRAPH_NODES:
            raise GraphDefinitionError(
                f"A workflow cannot contain more than {MAX_GRAPH_NODES} nodes."
            )
        node_ids = [node.node_id for node in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise GraphDefinitionError("Workflow node IDs must be unique.")
        known = set(node_ids)
        for node in self.nodes:
            missing = set(node.dependencies) - known
            if missing:
                names = ", ".join(sorted(missing))
                raise GraphDefinitionError(
                    f"Node '{node.node_id}' has unknown dependencies: {names}."
                )
        _assert_acyclic(self.nodes)


class CancellationToken:
    """Thread-safe cooperative cancellation signal for a workflow run."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        """Request cancellation before the next node starts."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation was requested."""
        return self._event.is_set()


def _assert_acyclic(nodes: tuple[NodeContract, ...]) -> None:
    remaining = {node.node_id: set(node.dependencies) for node in nodes}
    while remaining:
        ready = {node_id for node_id, dependencies in remaining.items() if not dependencies}
        if not ready:
            involved = ", ".join(sorted(remaining))
            raise GraphDefinitionError(
                f"Workflow contains a dependency cycle involving: {involved}."
            )
        remaining = {
            node_id: dependencies - ready
            for node_id, dependencies in remaining.items()
            if node_id not in ready
        }
