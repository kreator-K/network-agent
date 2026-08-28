"""Append-only workflow receipt persistence tests."""

from datetime import UTC, datetime

import pytest

from db.database import initialize_database
from workflows.contracts import (
    NodeRunResult,
    NodeStatus,
    WorkflowRunResult,
    WorkflowStatus,
)
from workflows.persistence import (
    WorkflowPersistenceError,
    get_workflow_run,
    save_workflow_run,
)


def _run() -> WorkflowRunResult:
    now = datetime.now(UTC)
    return WorkflowRunResult(
        run_id="run-123",
        workflow_name="test_graph",
        workflow_version=1,
        status=WorkflowStatus.COMPLETED,
        nodes={
            "research": NodeRunResult(
                node_id="research",
                status=NodeStatus.COMPLETED,
                attempts=1,
                output={"evidence": "stored"},
                started_at=now,
                finished_at=now,
            )
        },
        started_at=now,
        finished_at=now,
    )


def test_workflow_receipt_and_nodes_are_persisted_atomically(tmp_path) -> None:
    database = tmp_path / "workflow.db"
    initialize_database(database)

    save_workflow_run(database, _run(), metadata={"owner": "web"})
    stored = get_workflow_run(database, "run-123")

    assert stored["workflow_name"] == "test_graph"
    assert stored["metadata"] == {"owner": "web"}
    assert stored["nodes"][0]["output"] == {"evidence": "stored"}


def test_workflow_history_is_append_only(tmp_path) -> None:
    database = tmp_path / "workflow.db"
    initialize_database(database)
    save_workflow_run(database, _run())

    with pytest.raises(WorkflowPersistenceError, match="already persisted"):
        save_workflow_run(database, _run())


def test_missing_workflow_receipt_returns_clean_error(tmp_path) -> None:
    database = tmp_path / "workflow.db"
    initialize_database(database)

    with pytest.raises(WorkflowPersistenceError, match="does not exist"):
        get_workflow_run(database, "missing")
