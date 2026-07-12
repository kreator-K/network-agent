# Phase 6B Refinement Apply/Reject

## Purpose

Phase 6B upgrades the refinement loop from L1 report-only to L2 assisted
refinement. The system may suggest safe refinements, but it still never applies
anything unless the user explicitly taps `Apply Refinement`.

## Proposal Lifecycle

Safe checker-approved suggestions are persisted in `refinement_proposals`.

Statuses:

- `pending_approval`
- `applied`
- `rejected`
- `failed_validation`
- `expired`

Only proposals with all of the following can be applied:

- `checker_status = passed`
- `core_intent_check_status = passed`
- `status = pending_approval`

## Suggest Flow

```text
/suggest_refinements
```

The loop:

- creates a `refinement_loop_runs` row
- loads constraints
- reads explicit `refinement_outcomes`
- reads immutable `core_intent`
- reads active `refinable_parameters`
- creates maker proposals
- checker-validates them
- persists safe proposals as `pending_approval`
- shows Telegram buttons

Telegram wording says:

```text
Refinements are not applied unless you tap Apply.
```

## Apply Behavior

When the user taps `Apply Refinement`, the system:

- loads the proposal from SQLite
- reloads current constraints
- reloads current core intent
- reloads active refinable parameters
- re-runs the checker
- confirms the proposal is still pending
- confirms the current parameter value still matches
- confirms mode is `assisted`
- enforces `max_apply_per_run`

If valid, it:

- updates only the approved `refinable_parameters` key
- appends `refinement_history`
- marks the proposal `applied`
- increments `refinement_loop_runs.proposals_applied_count`

Telegram confirms:

```text
Refinement applied. Core intent was not changed.
```

## Reject Behavior

When the user taps `Reject Refinement`, the system:

- marks the proposal `rejected`
- sets `decided_at`
- does not change parameters
- does not change core intent

Telegram confirms:

```text
Refinement rejected. No changes were made.
```

## View Reasoning

`View Reasoning` shows user-facing rationale only:

- target area
- parameter
- current value
- proposed value
- evidence count
- checker/risk status

It does not expose internal chain-of-thought or secrets.

## Constraints

`mode` can be:

- `report_only`: proposals can be shown, but Apply returns a clean no-change message.
- `assisted`: Apply may proceed after validation.

Other enforced constraints:

- `human_approval_required=true`
- `loop_paused=false`
- `max_apply_per_run=1` by default
- no LinkedIn auto-send
- no LinkedIn scraping
- no LinkedIn auto-publish

## Drift Protection

If the active parameter value changed after proposal creation, Apply fails with:

```text
This proposal is stale because the parameter changed. Please run /suggest_refinements again.
```

The system does not blindly overwrite drifted parameters.

## Safety Rules

Phase 6B does not implement:

- rollback
- unattended scheduled refinement
- automatic apply
- LinkedIn posting
- LinkedIn sending
- LinkedIn scraping
- freeform LinkedIn outcome detection
- analytics dashboard

## Future Phase 6C

Phase 6C may add rollback and richer lifecycle controls, while preserving
append-only history and human approval.
