# Phase 10 Deployment and Private Beta

Status: implementation-ready, deployment blocked until a stable production
domain, durable API host, and owner web credentials are configured. No cloud
infrastructure is provisioned by this repository.

The supported target is one Python 3.11 API service, one writable SQLite
database, one LinkedIn callback path behind HTTPS, one Google Calendar MCP
subprocess, and one backup timer. This topology deliberately does not
horizontally scale SQLite writes. The Vercel frontend is deployed separately.

Phase 10 keeps LinkedIn publishing disabled, outreach manual-send only,
calendar writes explicit, CRM conversion approved, and public HTTP sources
off until reviewed. See the deployment and private-beta runbooks for the
operator sequence.

Phase 9 prerequisite: passed automated release gate. Phase 10 has not made a
live LinkedIn, Calendar, outreach, or infrastructure write.
