# Render API deployment

The selected MVP topology is a Vercel Next.js frontend and one Render Docker
web service backed by a single persistent disk. SQLite remains the source of
truth. Do not increase the API instance count while SQLite is in use.

## Create the API service

1. Connect the repository to Render and create a Blueprint from `render.yaml`.
2. Keep the `starter` service and 1 GB disk for the private MVP, increasing disk
   size only when observed usage requires it.
3. Enter the `sync: false` values when Render prompts. Keep model mode mocked and
   LinkedIn publishing disabled for the first deployment.
4. After creation, copy the generated `WEB_API_TOKEN` from Render into the
   Vercel project as the server-only variable with the same name.
5. Set Vercel `NETWORK_API_BASE_URL` to the Render service's HTTPS origin.
6. Generate and configure Vercel's `WEB_SESSION_SECRET` and
   `WEB_OWNER_PASSWORD_HASH` as described in `docs/vercel_deployment.md`.
7. Set `LINKEDIN_REDIRECT_URI` on Render to the Vercel production origin plus
   `/linkedin/callback`, then register that exact HTTPS URI with LinkedIn.

The Blueprint mounts `/data` and places the database, token file, media,
runtime state, logs, and local backups underneath it. `/readyz` is the Render
health check. The container reads Render's `PORT` variable and defaults to 8000
for local Compose runs.

## First-deploy verification

- Confirm `/healthz` and `/readyz` return HTTP 200.
- Run `python scripts/backup_database.py`, then verify the created database with
  `python scripts/verify_backup.py --backup <path>` from the service shell.
- Copy verified backups off the Render disk on a defined schedule. Disk
  snapshots are useful, but they are not the application's only recovery copy.
- Confirm the Vercel deployment can load authenticated data without exposing
  `WEB_API_TOKEN` to browser JavaScript.
- Keep exactly one Render instance and leave real LinkedIn publishing disabled
  until the separate live-publishing review is approved.

Render disks are available only at runtime, so database initialization and
backup commands must not be configured as pre-deploy commands.
