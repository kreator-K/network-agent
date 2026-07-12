# Phase 5 Draft Lifecycle

## Purpose

This phase hardens the internal approval queue for outreach drafts and content
drafts. It does not send, publish, scrape, schedule, or automate any LinkedIn
action.

## Safety Rules

- LinkedIn connection requests are never sent by the bot.
- LinkedIn DMs and InMail are never sent by the bot.
- LinkedIn posts are never published by the bot in this phase.
- LinkedIn scraping is not allowed.
- Approval means internal approval only.
- Outreach `sent_manually` means the user manually sent the message in
  LinkedIn.

## Outreach Draft Statuses

Outreach and follow-up drafts are stored in `interactions`.

- `drafted`: the bot generated a draft for human review.
- `sent_manually`: the user tapped `Mark as Manually Sent` after manually
  sending the message in LinkedIn.
- `discarded`: the user discarded the internal draft.

Stored fields include:

- `prospect_id`
- `interaction_type`
- `content`
- `direction`
- `status`
- `source`
- `created_at`
- `updated_at`

The `content` field may contain JSON with `ask_type`, `draft_text`, `source`,
and lifecycle status.

## Content Draft Statuses

Content drafts are stored in `content_posts`.

- `draft`: generated and waiting for user action.
- `saved`: retained in the queue as an internal draft.
- `approved_for_later_posting`: internally approved, but not posted.
- `discarded`: removed from the active review queue.

Stored fields include:

- `topic`
- `draft_text`
- `image_source`
- `image_path`
- `inspiration_source_notes`
- `status`
- `created_at`
- `updated_at`

## Telegram Commands

`/draft_outreach <prospect_id> <ask_type>`

Shows a draft with:

- `Mark as Manually Sent`
- `Discard Draft`

`/draft_followup <prospect_id>`

Shows a follow-up draft with the same safe internal actions.

`/draft_post <topic>`

Shows a content draft with:

- `Save Draft`
- `Mark Approved for Later Posting`
- `Discard Draft`

`/pending_drafts`

Lists active outreach and content drafts with type, prospect/topic, created
time, status, and safe available actions.

## Inline Button Behavior

- `Mark as Manually Sent` records `sent_manually`, updates the prospect to
  `connection_sent`, and starts follow-up tracking.
- `Discard Draft` records `discarded` and does not affect the follow-up
  schedule.
- `Save Draft` updates a content post to `saved`.
- `Mark Approved for Later Posting` updates a content post to
  `approved_for_later_posting` only.
- Content `Discard Draft` updates a content post to `discarded`.

Malformed or stale callback data returns a clean Telegram error and does not
expose stack traces.

## Known Limitations

- Outreach draft metadata is stored in the interaction `content` JSON rather
  than a dedicated outreach draft table.
- There is no LinkedIn posting, OAuth, scheduling, or message automation.
- Uploaded image context is stored as a local path; no vision analysis is
  performed yet.
- Pending Telegram upload context is in-memory and can be lost on bot restart.

## Future Scope

LinkedIn publishing can be added later only after explicit approval
architecture is in place. Future publishing must remain separate from outreach
messaging, which stays permanently manual.
