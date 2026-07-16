# Operator Runbook

## Install and start

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env.local
python -m scripts.init_db
python -m scripts.release_check
python -m scripts.run_bot
```

Runtime reads `.env.local` only. Never copy credentials into source control.

## Health and daily operations

Use `/system_check`, `/linkedin_publish_diagnostics`,
`/linkedin_connection_status`, `/scoring_diagnostics`, and `/briefing_status`.
Run `/briefing_now dry_run` for a safe manual briefing. Scheduled briefings are
disabled unless explicitly enabled in `.env.local`.

## Approval boundaries

Outreach is copied and sent manually by the user. Calendar blocking requires
`/meeting_confirmed`. LinkedIn publication requires an approved package,
`/prepare_publish`, review of the frozen preview, and
`/confirm_publish <request_id>`. Never interpret freeform text as approval.

## OAuth and recovery

Use `/linkedin_reauthorize` when credentials expire, are revoked, or lose a
required scope. For an uncertain publish, inspect LinkedIn manually and use
`/resolve_publish_uncertain <request_id> posted|not_posted`; it never calls the
provider. For Calendar MCP failures, inspect the safe bot log and the matching
`calendar_blocks` row; do not duplicate a command without checking idempotency.

## Backup and shutdown

```bash
python -m scripts.backup_database --output backups/network-agent-$(date +%Y%m%d-%H%M%S).db
python -m scripts.verify_backup --backup backups/FILE.db
```

Back up only SQLite through the project helper. Do not copy `.env.local` or
`secrets/`. Stop the bot with Ctrl+C and confirm the MCP session and vendored
Node process close cleanly.

## Safe logs

Collect timestamps, workflow names, internal IDs, stages, durations, typed
errors, and provider status codes. Remove tokens, OAuth codes/state, client
secrets, encryption keys, full upload URLs, and private prospect or event text.
