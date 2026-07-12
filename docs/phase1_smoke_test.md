# Phase 1 Smoke Test

## Required Environment

- Python 3.11 virtual environment active.
- `.env.local` present and ignored by git.
- `TELEGRAM_BOT_TOKEN` set.
- `NVIDIA_API_KEY` set when `MOCK_MODE=false`.
- `DATABASE_PATH` set, or default `network_agent.db` is acceptable.
- `FOLLOWUP_CADENCE_DAYS=21` unless intentionally overridden through `core_intent`.

Check config loading:

```bash
.venv/bin/python -c "from config.settings import settings; print(settings.mock_mode, bool(settings.telegram_bot_token), settings.database_path)"
```

## Run The Bot

```bash
.venv/bin/python scripts/run_bot.py
```

Expected:
- Bot starts polling without import errors.
- Startup initializes or migrates SQLite schema.
- No token or stack trace is printed to Telegram.

## Telegram Commands

1. Add a manually found prospect:

```text
/add_prospect Maya Chen | https://www.linkedin.com/in/maya-chen-example | New York | Senior Product Manager | Nvidia | Found through a public post about AI infrastructure product launches. Ask for career guidance, not a referral.
```

Expected:
- Bot replies with the new `prospect_id`.
- No LinkedIn search or scraping occurs.

2. Draft outreach:

```text
/draft_outreach <prospect_id> career_guidance
```

Expected:
- Bot replies with a draft, character count, and any context warning.
- Button text is exactly `Mark as Manually Sent`.
- Draft is for manual copy/paste only.

3. Manually send in LinkedIn yourself, then tap:

```text
Mark as Manually Sent
```

Expected:
- Bot replies: `Marked as manually sent on LinkedIn. I'll track this for follow-up.`
- SQLite records `interaction_type='linkedin_connection_request'`.
- Interaction content includes `status='sent_manually'`, `source='telegram_button'`, and any available `ask_type`/`draft_text`.
- Prospect status becomes `connection_sent`.
- `last_touch_date` is set.

4. Check follow-up queue:

```text
/followups_due
```

Expected immediately after manual send:
- Bot says `No follow-ups due.`
- Follow-up cadence comes from SQLite `core_intent`; default is 21 days.

5. Draft a follow-up:

```text
/draft_followup <prospect_id>
```

Expected:
- Draft uses prospect context and prior outreach history.
- Draft does not invent a reply, relationship, shared connection, or credential.
- Draft stays manual-send only.

## SQLite Verification

```sql
SELECT id, prospect_id, interaction_type, content, created_at
FROM interactions
WHERE prospect_id = <prospect_id>
ORDER BY id;

SELECT id, status, last_touch_date
FROM prospects
WHERE id = <prospect_id>;

SELECT rule_key, rule_value
FROM core_intent
WHERE rule_key = 'cadence_floor_days';
```

Expected:
- One `outreach_draft` interaction.
- One `linkedin_connection_request` interaction after button tap.
- `created_at` is present on both interactions.
- `prospects.last_touch_date` is present after manual-send tracking.
- Cadence rule is present, normally `21`.

## Safety Checks

- The bot never sends LinkedIn connection requests or messages.
- The bot never scrapes or searches LinkedIn.
- The bot never calls `LinkedInPublishAgent` in the outreach flow.
- Telegram handlers call `NetworkOrchestrator` for product workflows.
- Model calls route through `ModelOrchestrationAgent`.

## Known Limitations

- If the bot restarts after drafting but before button tap, in-memory draft metadata may be unavailable; manual-send tracking still works, but `ask_type` and `draft_text` may be null.
- Follow-up cadence is based on `last_touch_date`; there is no separate sent-message table in Phase 1.
- Outreach and follow-ups remain draft-only forever for LinkedIn API safety.
