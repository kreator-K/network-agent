# network-agent

Network Growth Agent is a human-in-the-loop Telegram workflow for manually provided professional networking prospects, outreach drafts, follow-up tracking, content drafts, explicit meeting confirmations, and controlled refinement proposals.

## Quick Start

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env.local
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/run_bot.py
```

Use `MOCK_MODE=true` for deterministic local development. See [docs/mvp_demo_script.md](docs/mvp_demo_script.md) and [docs/mvp_release_checklist.md](docs/mvp_release_checklist.md) for the complete workflow.

The application never sends LinkedIn messages or connection requests, never scrapes LinkedIn, and never publishes content without an explicit future approval path. Outreach is permanently draft-only in MVP scope.
