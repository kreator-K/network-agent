# Vercel deployment contract

## Supported topology

Deploy the `web/` directory as the Vercel Next.js project. Keep the Python API
as a separate Python 3.11 service and set `NETWORK_API_BASE_URL` in Vercel to
its stable HTTPS origin. The frontend calls the API server-to-server; the API
bearer token and owner-session secrets are never exposed with `NEXT_PUBLIC_`
names.

This split is required for the current release. Vercel's Python runtime
currently supports Python 3.12 through 3.14, while this repository requires
Python 3.11. Do not deploy the root Python project to Vercel or silently change
its runtime. A Python 3.12 migration requires a separate reviewed phase.

Vercel documents one project per application directory for monorepos:
https://vercel.com/docs/monorepos. Its current Python runtime matrix is at
https://vercel.com/docs/functions/runtimes/python.

## Frontend project

1. Import this repository into Vercel.
2. Set Root Directory to `web` and Framework Preset to Next.js.
3. Configure the four variables from `web/.env.example` for Preview and
   Production using distinct secrets.
4. Generate the owner password hash locally with
   `npm run hash-password -- '<password>'` from `web/`.
5. Set `LINKEDIN_REDIRECT_URI` on the Python API to the production frontend URL
   plus `/linkedin/callback`, and register that exact URL in LinkedIn.
6. Run `npm run typecheck`, `npm run build`, and
   `npm run deployment-check` before promotion.

## Python API service

The API host must provide Python 3.11, durable storage, HTTPS, backups, and one
writable database owner. The provider-neutral `Dockerfile` and `compose.yaml`
run the API on port 8000 with a named SQLite data volume. `scripts/pre_deploy.py`
intentionally fails until:

- `WEB_API_TOKEN` is at least 32 characters and matches the Vercel project;
- LinkedIn real publishing remains disabled for initial deployment;
- `DEPLOYMENT_PERSISTENCE_ACKNOWLEDGED=true` records an operator decision about
  durable storage and backups;
- the configured SQLite database passes `PRAGMA integrity_check`.

Expose `/healthz` for liveness and `/readyz` for readiness. Readiness returns
503 unless the database is healthy, the API token is configured, and publishing
is disabled. Keep the API behind HTTPS and a single-writer runtime.

SQLite on an ephemeral or horizontally scaled serverless filesystem is not a
supported production topology. Do not set the persistence acknowledgement
until a durable single-writer host or a reviewed database migration is ready.

## Promotion checks

```bash
cd web
npm run typecheck
npm run build
npm run deployment-check
cd ..
.venv/bin/python scripts/pre_deploy.py
NETWORK_AGENT_DOTENV_OVERRIDE=false LINKEDIN_PUBLISH_MODE=disabled LINKEDIN_REAL_PUBLISH_ENABLED=false .venv/bin/python scripts/release_check.py
```

Automated tests and deployment checks never perform a LinkedIn provider write.

## Continuous integration

`.github/workflows/ci.yml` runs the Python 3.11 test/type/lint/release gates and
the Next.js typecheck/build/audit gates on every push and pull request. CI uses
placeholder credentials, disabled LinkedIn publishing, and no provider-write
permissions.
