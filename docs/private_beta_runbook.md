# Private Beta Runbook

Start owner-only with the Vercel web login. Before admitting another user,
establish application-level identity and authorization; the current
owner-password session is not a multi-user access-control system.

Owner checklist: verify the API `/healthz` and `/readyz`, an authenticated web
session, the Profile page, backup creation and restore verification, and safe
logs. Keep `LINKEDIN_PUBLISH_MODE=disabled` and
`LINKEDIN_REAL_PUBLISH_ENABLED=false` during normal beta operation.

Render Free must not be used for private beta because it resets local SQLite
state. Promote to a durable single-writer host first. Never send outreach
automatically; the user manually sends every outreach draft. A LinkedIn post
requires a separately approved frozen request and explicit one-time web
confirmation.
