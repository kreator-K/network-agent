# Phase 6D Refinement Reporting

Phase 6D adds read-only reporting for the refinement loop. Reports help the operator understand outcomes, pending proposals, applied changes, rejected changes, rollbacks, and safety status.

No Phase 6D command applies, rejects, rolls back, publishes, scrapes, or sends anything.

## Commands

```text
/refinement_status
```

Shows the current loop mode, pause state, proposal/apply limits, recent run status, and proposal/history counts.

```text
/refinement_report
```

Shows recent outcomes, recent proposals, pending proposals, applied/rejected counts, rollback count, failed-validation reasons, current refinable parameter values, and a recommended next action.

```text
/refinement_history
```

Shows the recent append-only audit trail with event id, event type, parameter name, value change, status, timestamp, and rollback reference when present.

```text
/system_check
```

Includes refinement-loop safety diagnostics in addition to existing cross-table checks.

## Interpreting Loop Status

`mode=report_only` means suggestions can be generated, but no refinement can be applied from a button.

`mode=assisted` means a human can explicitly apply a pending proposal. This still does not allow unattended changes.

`loop_paused=true` blocks proposal generation and apply operations.

`human_approval_required=true` must remain true. `/system_check` flags it if this safety constraint is not true.

## Pending Proposals

`/refinement_report` lists pending proposals with:

- proposal id
- target area
- parameter name
- proposed value
- risk level
- checker status
- creation timestamp

The report never applies these proposals. Use the existing Apply/Reject buttons from `/suggest_refinements` for human-approved action.

## Audit Model

Refinement history is append-only. Important event types include:

- `proposal_created`
- `proposal_applied`
- `proposal_rejected`
- `proposal_failed_validation`
- `rollback_applied`
- `rollback_failed`

Rollback references are shown as `rollback_from` in `/refinement_history`.

## System Safety Checks

`/system_check` now validates that:

- `core_intent` exists
- `refinable_parameters` exist
- loop constraints exist
- `human_approval_required=true`
- `no_linkedin_auto_send=true`
- `no_linkedin_scraping=true`
- `no_linkedin_auto_publish=true`
- no pending proposal failed checker/core-intent status
- no applied refinement targets a non-refinable parameter
- applied proposal history contains old/new values where possible

## Weekly Summary

`/weekly_refinement_summary on/off` is future scope. The project does not currently have a scheduler or task mechanism, and Phase 6D should not introduce one from scratch.

When implemented later, weekly summaries must remain report-only and must not Apply, Reject, Rollback, publish, scrape, or send anything.

## Limitations

- No pagination for `/refinement_history` yet.
- No dashboard UI.
- Reporting uses simple counts and recent records, not advanced analytics.
- Recommendations are operational hints only, not automated actions.
