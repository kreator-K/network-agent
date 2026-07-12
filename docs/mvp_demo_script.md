# MVP Demo Script

## Setup

1. Create or activate the Python 3.11 environment: `.venv/bin/activate`.
2. Copy `.env.example` to `.env.local` and provide `TELEGRAM_BOT_TOKEN`.
3. Set `MOCK_MODE=true` for a deterministic demo, or set `MOCK_MODE=false` with `NVIDIA_API_KEY` for real drafting.
4. Initialize SQLite: `.venv/bin/python scripts/init_db.py`.
5. Start the bot: `.venv/bin/python scripts/run_bot.py`.

## Telegram Walkthrough

```text
/start
/add_prospect Ada Lovelace | https://www.linkedin.com/in/ada-lovelace | London | CTO | Analytical Engines | Discussed systems thinking
/draft_outreach 1 career_guidance
```

Review the draft, then tap `Mark as Manually Sent`. The bot must say that the user manually sent the message; the application does not contact LinkedIn.

```text
/followups_due
/draft_followup 1
/meeting_confirmed 1 2026-08-01 09:30 10:00
/draft_post AI product transitions
/pending_drafts
/record_outcome outreach 1 replied_positive
/suggest_refinements
/refinement_status
/refinement_report
/refinement_history
/system_check
```

## Expected Checks

- A manual-send interaction exists in SQLite with `status='sent_manually'` and `source='telegram_button'`.
- A newly touched prospect is not due until the configured cadence has elapsed.
- Follow-up drafts refer only to recorded context and remain drafts.
- Meeting confirmation records a block; real Google Calendar sync is not implemented.
- Content is saved for review and is not automatically published.
- `/system_check` reports all checks passed on an initialized database.

## Limitations

LinkedIn messaging, connection requests, scraping, and posting automation are not implemented. Google Calendar OAuth and real image generation are future work. Refinement remains report-only unless the human-approved assisted mode is explicitly enabled.
