# Phase 6C Refinement Rollback

Phase 6C adds safe rollback for human-applied refinement changes. Rollback is operator initiated only and never runs unattended.

## Command

```text
/rollback_refinement <refinement_id>
```

`refinement_id` is the `refinement_history.id` for an applied `proposal_applied` event.

Optional audit view:

```text
/refinement_history
```

This shows recent refinement events with the event type, parameter name, value change, timestamp, and status.

## Eligibility Rules

A refinement can be rolled back only when all of these are true:

- The `refinement_history` row exists.
- The row is an accepted `proposal_applied` event.
- The event contains `parameter_name`, `old_value`, and `new_value`.
- The target parameter still exists in `refinable_parameters` and is active.
- The current active parameter value still matches the applied event's `new_value`.
- Human approval remains required by `refinement_loop_constraints`.
- The rollback value passes the same core-intent and safety checks used for proposals.

Rollback only writes to `refinable_parameters` and `refinement_history`. It never mutates `core_intent`.

## Append-Only History Model

Phase 6C treats `refinement_history` as an audit log. Historical rows are not deleted or overwritten.

Supported event types:

- `proposal_created`
- `proposal_applied`
- `proposal_rejected`
- `proposal_failed_validation`
- `rollback_applied`
- `rollback_failed`

Applied events include the previous and new parameter values. Rollback events include `rollback_from_refinement_id` so the audit chain remains traceable.

## Stale Refinements

If the active parameter value changed after the original refinement was applied, rollback fails safely:

```text
This refinement cannot be rolled back automatically because the parameter has changed since it was applied. Please review manually.
```

The failure is recorded as `rollback_failed` in `refinement_history`.

## Safety Checks

Rollback cannot be used to:

- Enable automatic LinkedIn sending.
- Enable LinkedIn scraping.
- Enable LinkedIn auto-publishing.
- Bypass or remove human approval.
- Modify immutable `core_intent`.
- Restore a value for a parameter that is no longer refinable.

## Examples

Successful rollback:

```text
/rollback_refinement 42
Rollback applied for opening_style. Restored previous value. Core intent was not changed.
```

Failed stale rollback:

```text
/rollback_refinement 42
This refinement cannot be rolled back automatically because the parameter has changed since it was applied. Please review manually.
```

## Limitations

- Rollback is one refinement event at a time.
- There is no scheduled or autonomous rollback.
- There is no analytics dashboard yet.
- Manual review is required for stale or ambiguous rollback cases.

## Future Scope

- Better history filtering by agent and event type.
- Operator notes on rollback decisions.
- Richer diff display for multi-parameter legacy events.
- Dashboard views for refinement performance and rollback frequency.
