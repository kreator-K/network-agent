# Current Phase

## Phase Completion Report

Phase: 8F — Assisted Prospect Discovery

Status: completed

Files changed: candidate model and SQLite ledger, ProspectDiscoveryAgent source-backed extraction and CRM conversion, orchestrator coordination, Telegram review commands, tests, and Phase 8F documentation.

Safety: candidates are created only from already stored approved public-signal metadata. No LinkedIn fetching, scraping, private contact data, automated CRM insertion, outreach, email, meeting, or publishing exists.

Telegram commands: `/discover_candidates`, `/prospect_candidates`, and `/approve_candidate <candidate_id>`.

Tests executed: full pytest suite, mypy, and ruff.

Acceptance: source attribution, explicit approval before CRM insertion, clean duplicate/invalid status rejection, and existing manual prospect workflows remain intact.

Phase 8G-B1 — LinkedIn OAuth Foundation: completed

LinkedIn integration decision: use LinkedIn's official OAuth and REST APIs
directly. LinkedIn MCP is explicitly out of scope and no LinkedIn MCP server
is maintained. B1 authenticates only with `openid`, `profile`, and
`w_member_social`; tokens are encrypted before storage. Publishing remains
`LINKEDIN_PUBLISH_MODE=disabled` and successful authentication cannot publish.

Phase 8G-B2 — Real Text and Single-Image LinkedIn Member Posting: completed through automated and mocked acceptance. Live publication was not executed because it requires explicit package-specific user confirmation.

Phase 8G-B3 — Richer LinkedIn Content Formats: completed through automated and mocked acceptance. Multi-image, video, document, article, and poll formats reuse the same frozen preview, request ID, confirmation, idempotency, uncertainty, and audit boundary.

Phase 8G-B4 — Production Publishing Hardening: completed through automated, disabled-mode, mock-mode, and local read-only certification. Atomic claims, bounded confirmation attempts, startup reconciliation, append-only recovery, diagnostics, database integrity, and backup/restore controls are implemented.

Phase 8G: completed. No live provider write was performed; each real write still requires explicit confirmation for a specific frozen package.

Phase 9 — Whole-System Integration and Release Hardening: completed.

The release-hardening pass adds safe configuration diagnostics, generated
Telegram command inventory, bounded background operation handling, SQLite
backup/restore verification, release checks, and operator runbooks. The full
release gate passed with 409 tests, mypy across 78 files, Ruff, migration, and
integrity checks. Real LinkedIn publishing remains disabled and no provider
write is part of the release certification.

Former Phase 10 systemd/Telegram deployment: retired. Telegram is retained only
as a migration adapter while the product moves to an authenticated Vercel web
UI/API.

Graph Orchestration Foundation — Phase 0 complete; Phase 1 foundation complete.

The typed in-process graph engine validates workflow topology and Pydantic node
contracts, executes independent nodes with bounded parallelism, isolates failed
branches, caps retries, supports cooperative cancellation, and returns
persistence-neutral run records. Signal ingestion now has disabled, shadow, and
enabled graph modes. It fetches approved sources concurrently and persists all
results through one controlled SQLite write node. Content packages now also
support disabled, shadow, and enabled graph modes with typed research, hook,
carousel, caption, evidence-verification, and bundle nodes. Both graph modes
remain disabled by default. The authenticated ASGI web API foundation now
provides owner-token-protected signal, opportunity, and draft-content routes
through `NetworkOrchestrator`, plus a public minimal health route. The Vercel
frontend shell is implemented with Next.js 16.3.3, a responsive dashboard,
Signals, Opportunities, and Content Studio routes, and a server-only typed API
client. Web routes now require a signed, HTTP-only, eight-hour owner session
created from a scrypt-verified password; missing production configuration fails
closed. Authenticated Server Actions now support approved-source scanning and
opportunity-to-draft generation without exposing the backend token. These are
internal preparation actions only. Graph runs and node receipts are now stored
atomically and append-only, with authenticated retrieval by run ID. Recent run
summaries are available through the protected Workflow Runs page with status
and node-failure counts.

Web parity is complete through CRM intake and draft-only outreach, explicit
meeting confirmation, versioned personal-brand profiles, reviewed public-feed
catalogs, content revision/variant controls, OAuth, frozen LinkedIn publishing
previews, dry briefings, feedback, and legacy Telegram retirement. SQLite is the
selected MVP database and is covered by the backup/restore and readiness gates.
Phase 10 web deployment foundation is now complete for an owner-only demo:
the Next.js web application is deployed on Vercel and the Python 3.11 API is
deployed as one Render Free web service. Health, readiness, owner-session
authentication, and server-to-server API calls have been verified.

The Render Free filesystem is ephemeral, so SQLite data is intentionally demo
only. The next private-beta step is moving the single-writer API and SQLite
database to durable storage, validating backups, then separately configuring
LinkedIn OAuth. Publishing remains disabled throughout the demo deployment.
