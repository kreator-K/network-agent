# Workflow Receipt Persistence

Completed graph runs are stored append-only in `workflow_runs` and
`workflow_node_runs`. The parent records workflow identity, version, status,
timestamps, and non-secret metadata. Child rows record each node's bounded
attempt count, safe error fields, timestamps, and JSON output.

Persistence is atomic. Reusing a run ID is rejected instead of updating history.
Inputs, prompts, provider exception messages, and credentials are not stored.
The authenticated API exposes `GET /api/v1/workflows/{run_id}` for the future
workflow timeline UI.

The repository remains SQLite-backed locally. `workflows/persistence.py` is the
boundary to replace when managed PostgreSQL is selected for production.
