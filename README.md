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

## Latest update

The latest Telegram workflow improvement prioritizes pending public-source approval in guided next steps. When a source is awaiting review, the assistant now surfaces `/approve_signal_source <id>` before suggesting source intake or scanning. This keeps public-signal intelligence approval-first: no source is enabled or scanned until it has been explicitly approved.
