# Phase 6 Refinement Loop

## Purpose

The refinement loop lets the user explicitly report outcomes and request small
parameter improvements. It never changes core intent, sends LinkedIn messages,
publishes posts, scrapes LinkedIn, or applies strategy changes automatically.

## Outcome Commands

Outreach:

```text
/record_outcome outreach <prospect_id> <outcome> [notes]
```

Supported outreach outcomes:

- `replied_positive`
- `replied_neutral`
- `replied_negative`
- `no_reply`
- `meeting_booked`
- `not_relevant`
- `manually_sent`
- `custom_note`

Content:

```text
/record_outcome content <post_id> <outcome> [notes]
```

Supported content outcomes:

- `good_engagement`
- `low_engagement`
- `comments_positive`
- `comments_negative`
- `saved_for_later`
- `discarded`
- `custom_note`

Outcomes are saved to `refinement_outcomes` with target metadata, notes,
source, created time, and a metric value used only for controlled analysis.

## Suggestion Flow

```text
/suggest_refinements
```

The system reads:

- recent `refinement_outcomes`
- active `refinable_parameters`
- immutable `core_intent` from SQLite

It proposes changes only to existing refinable parameter keys. Suggestions are
shown with:

- parameter name
- current/proposed version
- proposed value
- reason
- evidence count
- risk level
- core-intent validation result

Suggestions are not applied automatically.

## Inline Actions

- `Apply Refinement`: validates again against core intent, updates only
  `refinable_parameters`, and appends to `refinement_history`.
- `Reject`: records an internal rejection response without changing
  parameters.
- `View Reasoning`: displays rationale and validation details only.

Telegram confirms successful application with:

```text
Refinement applied. Core intent was not changed.
```

## Rollback

```text
/rollback_refinement <agent_name> <target_version>
```

Rollback reactivates a prior parameter version if it exists and appends a new
history event. It does not delete or rewrite prior history.

## Core-Intent Protection

Refinements are rejected if they try to:

- enable automatic LinkedIn sending
- enable LinkedIn scraping
- publish or post automatically
- bypass human approval
- weaken draft-only outreach requirements
- encourage fabricated familiarity or invented context

`core_intent` remains immutable unless the user edits the source file and
reloads it through the existing data-layer flow.

## SQLite Tables

- `core_intent`
- `refinable_parameters`
- `refinement_history`
- `refinement_outcomes`
- `interactions`
- `content_posts`
- `prospects`

## Limitations

- Suggestions are based on explicit user-reported outcomes, not scraped
  LinkedIn data.
- Rejected proposals are not yet written as full rejection events unless they
  fail core-intent validation during apply.
- Proposal cache for Telegram inline buttons is in memory and can be lost on
  bot restart.
- No dashboard analytics or automated A/B testing exists in this phase.
