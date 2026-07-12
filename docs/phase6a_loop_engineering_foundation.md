# Phase 6A Loop Engineering Foundation

## Purpose

Phase 6A adds a minimal loop-engineering foundation to
`RefinementLoopAgent`. The loop is stateful, auditable, constrained, and
report-only.

No refinement is applied automatically in this phase.

## Ideas Adapted

The design adapts general loop-engineering concepts:

- durable loop run state
- explicit constraints
- report-only mode
- maker/checker separation
- human approval as a hard constraint
- append-only run logging
- pause/kill switch behavior

No code, files, prompts, or implementation details were imported, vendored, or
copied from `cobusgreyling/loop-engineering`.

## Report-Only Mode

`/suggest_refinements` now runs a report-only refinement loop. It can inspect
outcomes and produce checker-approved suggestions, but it cannot update:

- `core_intent`
- `refinable_parameters`
- `refinement_history`
- LinkedIn state

Telegram reports always include:

```text
Report-only. No changes have been applied.
```

## Loop Constraints

Durable constraints live in SQLite table `refinement_loop_constraints`.

Defaults:

- `no_linkedin_auto_send = true`
- `no_linkedin_scraping = true`
- `no_linkedin_auto_publish = true`
- `human_approval_required = true`
- `loop_paused = false`
- `mode = report_only`
- `max_proposals_per_run = 3`

The agent loads constraints at the start of every run. If `loop_paused=true`,
the loop logs a paused run and does not generate proposals.

## Run Logging

Every `/suggest_refinements` call appends one row to
`refinement_loop_runs`.

Tracked fields include:

- `run_id`
- `loop_type`
- `mode`
- `started_at`
- `completed_at`
- `status`
- `outcomes_considered_count`
- `proposals_created_count`
- `proposals_applied_count`
- `error_message`
- `metadata_json`

No rows are overwritten or deleted.

## Maker/Checker Separation

The maker step proposes candidate changes from explicit
`refinement_outcomes`.

The checker step verifies:

- the parameter is currently refinable
- `core_intent` is not changed
- LinkedIn auto-send is not enabled
- LinkedIn scraping is not enabled
- LinkedIn auto-publishing is not enabled
- human approval remains required
- the proposal is specific and reversible

Unsafe proposals are rejected before they are shown.

## Safety Rules

Phase 6A never:

- sends LinkedIn connection requests
- sends LinkedIn DMs or InMail
- scrapes LinkedIn
- publishes LinkedIn posts
- applies refinements
- mutates `core_intent`
- mutates `refinable_parameters`
- runs unattended scheduled loops

## Future Scope

Phase 6B:

- explicit Apply/Reject lifecycle
- human-approved parameter updates
- rejection audit records

Phase 6C:

- rollback workflow
- advanced refinement lifecycle controls
- richer run dashboards or analytics
