# Render API deployment

The current demo topology is a Vercel Next.js frontend and one free Render
Docker web service. SQLite remains the source of truth, but the free service's
filesystem is ephemeral: the demo database and local assets are reset whenever
Render spins down, restarts, or redeploys the service. Do not use this topology
for retained user data or real external actions.

## Create the API service

1. Connect the repository to Render and create a Blueprint from `render.yaml`.
2. Keep the `free` service and one instance. The Blueprint deliberately does
   not attach a disk because Render does not support disks on free services.
3. Keep model mode mocked and LinkedIn publishing disabled. Do not configure
   LinkedIn OAuth credentials on this ephemeral demo service.
4. After creation, copy the generated `WEB_API_TOKEN` from Render into the
   Vercel project as the server-only variable with the same name.
5. Set Vercel `NETWORK_API_BASE_URL` to the Render service's HTTPS origin.
6. Generate and configure Vercel's `WEB_SESSION_SECRET` and
   `WEB_OWNER_PASSWORD_HASH` as described in `docs/vercel_deployment.md`.
7. Leave LinkedIn OAuth and real publishing unconfigured. Enable them only
   after moving the API to durable storage and completing the separate live
   publishing review.

The Blueprint places all mutable files under `/tmp/network-agent` to make their
ephemeral status explicit. `/readyz` is the Render health check. The container
reads Render's `PORT` variable and defaults to 8000 for local Compose runs.

## First-deploy verification

- Confirm `/healthz` and `/readyz` return HTTP 200.
- Confirm a redeploy resets demo data; do not treat local backup files as
  durable because they are on the same ephemeral filesystem.
- Confirm the Vercel deployment can load authenticated data without exposing
  `WEB_API_TOKEN` to browser JavaScript.
- Keep exactly one Render instance and leave all real LinkedIn publishing
  disabled. Frozen publication requests, tokens, audit records, and idempotency
  state require durable storage and are outside this demo deployment.

Free Render services spin down after inactivity and discard local changes. For
private beta or production, return to the paid single-instance disk topology or
migrate the database to a durable remote store before enabling external writes.
