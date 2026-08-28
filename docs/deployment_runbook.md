# Deployment Runbook

## Owner-only demo

Deploy `web/` to Vercel and the Python API to one Render Free Docker web
service using `render.yaml`. Configure these server-only Vercel variables for
Preview and Production:

- `NETWORK_API_BASE_URL`
- `WEB_API_TOKEN`
- `WEB_SESSION_SECRET`
- `WEB_OWNER_PASSWORD_HASH`

Keep Render in mock mode with LinkedIn publishing disabled. Verify the public
API `/healthz` and `/readyz`, then verify an owner can sign in to the Vercel
application and load the Profile page.

## Private beta promotion

Render Free is not a private-beta topology: it loses its local SQLite database
when sleeping, restarting, or redeploying. Before private beta, move to one
durable single-writer Python 3.11 host (or a reviewed database migration),
configure backup export and restore verification, and rerun the release gate.
Do not configure LinkedIn OAuth or enable publishing until that promotion is
complete.

Rollback preserves provider uncertainty: restore the prior application release
and database only under the migration plan. Never replay an uncertain provider
write.
