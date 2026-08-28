# Graph Orchestration Foundation

## Status

Phase 0 contracts, the Phase 1 in-process engine, and the feature-flagged signal
ingestion graph are implemented. The default remains the existing control path.

## Boundary

`GraphWorkflowEngine` is operational infrastructure, not a specialist agent.
UI/API handlers continue to call `NetworkOrchestrator`, and all model calls
continue to pass through `ModelOrchestrationAgent`. The graph engine cannot
publish to LinkedIn, send outreach, or infer approval.

## Contracts

Each `NodeContract` declares:

- a stable node ID;
- explicit dependencies;
- a Pydantic input schema;
- a Pydantic output schema;
- an input builder that receives only the root workflow input and declared
  dependency artifacts;
- one bounded handler;
- a retry limit capped at three attempts.

`WorkflowDefinition` validates unique node IDs, known dependencies, graph size,
and acyclicity before execution. Open-ended cycles and runtime-created nodes are
not supported by the first engine.

## Execution

The engine executes ready nodes in bounded parallel waves. A downstream node
starts only after every declared dependency completes. Failed branches are
contained: descendants are skipped, while independent branches continue.

Provider exception messages are not retained in workflow results. Results store
only a safe error type and generic detail. This makes the returned structure
suitable for a future persistence adapter without accidentally storing provider
payloads or secrets.

Cancellation is cooperative. It prevents pending or queued nodes from starting,
but it cannot forcibly stop Python code already running in a worker thread.
Durable cancellation and per-node execution timeouts belong to the later queue
integration phase.

## Signal Ingestion Graph

The first product integration is the signal-intelligence workflow:

1. Load approved sources.
2. Fetch independent sources with bounded fan-out.
3. Normalize and persist through one controlled write boundary.
4. Score eligible stored signals with bounded fan-out.
5. Deterministically deduplicate and rank at a fan-in barrier.
6. Create review-only opportunities.

`SIGNAL_GRAPH_MODE` controls rollout:

- `disabled` keeps the sequential control path;
- `shadow` runs the control path once and reports graph-selection parity without
  issuing duplicate network requests or writes;
- `enabled` executes the graph.

Fetch nodes run concurrently, but `persist_fetches` owns one deterministic,
sequential SQLite write boundary. Graph execution requires a database path and
refuses a shared SQLite connection. The graph caps each run at 63 sources and
the engine caps concurrency at 16 workers.

## Deferred Work

- PostgreSQL-backed workflow and node records.
- Durable queue delivery and deployment recovery.
- Per-node timeouts and delayed retries.
- Feature-flagged signal scoring and content graph definitions.
- UI progress events and individual node retry controls.
- Conditional model tiering.
- Verifier panels and bounded convergent loops.
- Dynamic graph proposals.

Dynamic graphs will remain proposal-only until authorization, node-count, cost,
depth, and approval-boundary validation exists.

## Content Artifact Graph

`CONTENT_GRAPH_MODE` uses the same `disabled`, `shadow`, and `enabled` rollout
states. Shadow mode records topology metadata without duplicating model calls.
Enabled mode executes six typed nodes:

1. `research`
2. `hook`
3. `carousel`
4. `caption`
5. `verify_evidence`
6. `bundle`

The evidence verifier runs independently after research while the writing path
continues. It rejects claim/source mismatches before persistence. If optional
carousel rendering fails, the graph falls back to the validated slide plan and
continues caption generation. The package remains a draft and stores the graph
run receipt for the future web UI.
