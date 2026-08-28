"""Append-only persistence for graph workflow and node receipts."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from db.database import connect
from workflows.contracts import WorkflowRunResult


WorkflowDatabaseRef = sqlite3.Connection | str | Path


class WorkflowPersistenceError(ValueError):
    """Raised when a workflow receipt conflicts with append-only history."""


def save_workflow_run(
    database: WorkflowDatabaseRef,
    run: WorkflowRunResult,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one complete workflow receipt atomically."""
    connection, should_close = _coerce_connection(database)
    try:
        if connection.execute(
            "SELECT 1 FROM workflow_runs WHERE run_id = ?",
            (run.run_id,),
        ).fetchone() is not None:
            raise WorkflowPersistenceError(
                f"Workflow run '{run.run_id}' is already persisted."
            )
        created_at = datetime.now(UTC).isoformat()
        try:
            connection.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_name, workflow_version, status, started_at,
                    finished_at, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.workflow_name,
                    run.workflow_version,
                    run.status.value,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat(),
                    _json(metadata or {}),
                    created_at,
                ),
            )
            for node in run.nodes.values():
                connection.execute(
                    """
                    INSERT INTO workflow_node_runs (
                        run_id, node_id, status, attempts, output_json,
                        error_code, error_detail, started_at, finished_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        node.node_id,
                        node.status.value,
                        node.attempts,
                        None if node.output is None else _json(node.output),
                        node.error_code,
                        node.error_detail,
                        None if node.started_at is None else node.started_at.isoformat(),
                        None if node.finished_at is None else node.finished_at.isoformat(),
                        created_at,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        if should_close:
            connection.close()


def get_workflow_run(database: WorkflowDatabaseRef, run_id: str) -> dict[str, Any]:
    """Return one persisted receipt with ordered node records."""
    connection, should_close = _coerce_connection(database)
    try:
        row = connection.execute(
            "SELECT * FROM workflow_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise WorkflowPersistenceError(f"Workflow run '{run_id}' does not exist.")
        nodes = connection.execute(
            "SELECT * FROM workflow_node_runs WHERE run_id = ? ORDER BY created_at, node_id",
            (run_id,),
        ).fetchall()
        return {
            "run_id": row["run_id"],
            "workflow_name": row["workflow_name"],
            "workflow_version": row["workflow_version"],
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "metadata": json.loads(row["metadata_json"]),
            "nodes": [
                {
                    "node_id": node["node_id"],
                    "status": node["status"],
                    "attempts": node["attempts"],
                    "output": None if node["output_json"] is None else json.loads(node["output_json"]),
                    "error_code": node["error_code"],
                    "error_detail": node["error_detail"],
                    "started_at": node["started_at"],
                    "finished_at": node["finished_at"],
                }
                for node in nodes
            ],
        }
    finally:
        if should_close:
            connection.close()


def _coerce_connection(database: WorkflowDatabaseRef) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
