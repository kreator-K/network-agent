# Network Growth Agent

Network Growth Agent is an approval-first Telegram assistant for professional
networking and personal-brand workflows. It supports manual prospect intake,
draft-only outreach, follow-up tracking, public-signal intelligence, content
packages, explicit calendar confirmation, controlled refinement, and approved
LinkedIn member publishing.

## Quick Start

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env.local
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/prepare_runtime.py
.venv/bin/python scripts/run_bot.py
```

`config/.env.example` is a template only. Runtime code loads the project-root
`.env.local` file exclusively. Preserve local secrets and machine-specific paths
there; `.env.local` is ignored by Git.

Use `MOCK_MODE=true` for deterministic model development. LinkedIn publishing
fails closed by default:

```env
LINKEDIN_PUBLISH_MODE=disabled
LINKEDIN_REAL_PUBLISH_ENABLED=false
```

Both settings must explicitly permit a real write. Changing environment values
requires restarting the bot and callback service.

## LinkedIn Publishing

The certified Phase 8G architecture is:

```text
approved content package
-> frozen preview and hashes
-> explicit one-time confirmation
-> LinkedInPublishingGateway
-> LinkedInApiClient
-> official LinkedIn REST APIs
-> durable result and audit history
```

Supported member formats are text, single image, multi-image, video, document,
article, and poll. Every format uses the same approval, expiry, cancellation,
idempotency, replay-prevention, and uncertainty boundary.

Useful Telegram commands:

```text
/linkedin_connection_status
/linkedin_access_check
/linkedin_publish_status
/linkedin_publish_diagnostics
/prepare_publish <post_id>
/confirm_publish <request_id>
/cancel_publish <request_id>
/publish_request <request_id>
/publish_history
/resolve_publish_uncertain <request_id> posted|not_posted
/system_check
```

Preparing or approving a package does not publish it. A real write requires an
unexpired frozen request and the exact `/confirm_publish <request_id>` command.
Freeform consent is never accepted, and provider write failures are never
retried automatically.

## Safety Boundaries

- Outreach messages remain permanently draft-only and are manually sent by the
  user.
- The application does not scrape LinkedIn, read feeds, send connection
  requests, DMs, or InMail, or publish as an organization.
- Models, briefings, schedulers, prospect workflows, outreach workflows, and
  calendar workflows cannot publish.
- Google Calendar uses its separate MCP integration and remains independent of
  LinkedIn's direct OAuth and REST integration.
- Interrupted or uncertain LinkedIn writes block replay and require manual
  inspection and resolution.

## Validation

```bash
.venv/bin/python -m pytest
.venv/bin/python -m mypy .
.venv/bin/python -m ruff check .
.venv/bin/python scripts/release_check.py
```

Phase 8G certification uses mocked provider writes plus local read-only OAuth
status checks. No real LinkedIn post or media upload is part of automated tests.

See [Phase 8G certification](docs/phase8g_complete_certification.md),
[LinkedIn publish safety](docs/linkedin_publish_safety.md), and the
[MVP release checklist](docs/mvp_release_checklist.md) for operational details.

Phase 9 release operations are documented in
[the operator runbook](docs/operator_runbook.md), with a no-provider-write
gate available through `scripts/release_check.py`. The gate verifies the
active local configuration, generated Telegram command reference, tracked-file
secret patterns, SQLite migration/integrity, pytest, mypy, and Ruff. Use
`scripts/backup_database.py` and `scripts/verify_backup.py` for the documented
temporary backup/restore check.

Phase 10 deployment uses the documented systemd target in `deploy/`. Review
`docs/deployment_runbook.md`, set numeric Telegram allowlist values, configure
a stable HTTPS callback domain, and run `scripts/pre_deploy.py` before
installing services. No infrastructure is provisioned automatically.
