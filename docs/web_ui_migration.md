# Web UI migration boundary

Telegram is retired as the active Network Growth Agent interface. The
`telegram_bot/` package, its database columns, and its tests remain isolated as
a temporary legacy adapter so existing deployments and encrypted LinkedIn OAuth
state can be migrated safely. It is not an approved production entrypoint.

The Vercel application calls `NetworkOrchestrator` through a
framework-neutral HTTP/API boundary. The orchestrator remains responsible for
validation, approval state, provenance, and provider safety. UI code must not
call specialist agents or LinkedIn clients directly.

Implemented web parity includes signed owner sessions, prospect intake,
draft-only outreach, explicit meeting confirmation, signal scans, content
package preparation and approval, frozen LinkedIn previews, exact one-time
confirmation contracts, OAuth callback handling, and workflow audit receipts.

Remaining migration work is durable production persistence, profile editing,
variant/revision controls, briefing/feedback replacements, and deletion of the
isolated legacy adapter after data migration. See `docs/vercel_deployment.md`.

The retired `scripts/run_bot.py` entrypoint fails closed. Migration-only testing
requires the explicit `scripts/run_legacy_telegram_bot.py` entrypoint.
