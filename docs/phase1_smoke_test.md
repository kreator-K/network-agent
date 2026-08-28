# Web/API smoke test

## Required environment

- Python 3.11 virtual environment active.
- `.env.local` present and ignored by Git.
- `WEB_API_TOKEN` is at least 32 characters.
- Frontend session secret and owner password hash pass
  `npm run deployment-check`.
- `MOCK_MODE=true`, `LINKEDIN_PUBLISH_MODE=disabled`, and
  `LINKEDIN_REAL_PUBLISH_ENABLED=false`.
- `FOLLOWUP_CADENCE_DAYS=21` unless deliberately changed in core intent.

## Checks

```bash
.venv/bin/python -m pytest
.venv/bin/python -m mypy .
.venv/bin/python -m ruff check .
cd web
npm run typecheck
npm run build
npm run deployment-check
```

Start the Python API and request `/healthz`; it must return a minimal public
health response. Protected routes must reject missing or incorrect bearer
tokens. Sign in to the web UI and exercise prospect intake, draft-only outreach,
meeting preview, signals, opportunities, profile versions, Content Studio,
frozen publish review, briefings, and workflow receipts.

## Safety assertions

- No route sends a LinkedIn connection request or message.
- No route scrapes or searches LinkedIn.
- Follow-up eligibility reads cadence from SQLite core intent.
- A meeting preview cannot create a calendar block.
- Freeform meeting or publish consent is rejected.
- Content approval and frozen preview creation do not publish.
- Provider uncertainty never triggers polling or automatic retry.
- `scripts/run_bot.py` exits without starting Telegram.

The isolated `scripts/run_legacy_telegram_bot.py` exists only for migration
testing and is not a deployment entrypoint.
