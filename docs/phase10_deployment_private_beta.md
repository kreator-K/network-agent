# Phase 10 Deployment and Private Beta

Status: implementation-ready, deployment blocked until a real owner Telegram
ID and stable production domain are configured. No cloud infrastructure is
provisioned by this repository.

The supported target is one Linux VM with systemd, one writable SQLite
database, one Telegram bot process, one callback process behind a TLS reverse
proxy, one Google Calendar MCP subprocess owned by the bot, and one backup
timer. This topology deliberately does not horizontally scale SQLite writes.

Phase 10 keeps LinkedIn publishing disabled, outreach manual-send only,
calendar writes explicit, CRM conversion approved, and public HTTP sources
off until reviewed. See the deployment and private-beta runbooks for the
operator sequence.

Phase 9 prerequisite: passed automated release gate. Phase 10 has not made a
live LinkedIn, Calendar, outreach, or infrastructure write.
