# Phase 8G Certification

## Result

Phase 8G-B1 through 8G-B4 are complete through automated, disabled-mode,
mock-mode, and local read-only certification. No real LinkedIn write was made.
Any live post or media initialization still requires a separately approved,
specific content package and one-time confirmation.

## Certified Boundary

`NetworkOrchestrator -> LinkedInPublishingGateway -> LinkedInApiClient -> official LinkedIn REST APIs`

- B1: single-use OAuth state, allowlisted scopes, OIDC member identity,
  encrypted durable credentials, restart-safe local status.
- B2: text and single-image frozen previews, exact hashes, explicit claim,
  provider-result persistence, and no silent media downgrade.
- B3: multi-image, video, document, article, and poll formats reuse the same
  approval, confirmation, idempotency, expiry, cancellation, and audit path.
- B4: atomic claims, bounded confirmation attempts, interrupted-write
  reconciliation, immutable uncertainty resolutions, safe diagnostics,
  append-only events, terminal-state protection, backward-compatible 8G-A
  ledger migration, and SQLite backup/restore.

## Evidence

- Full pytest: 399 passed.
- Full mypy: clean.
- Ruff: clean.
- Provider writes: mocked only.
- Real LinkedIn checks: local encrypted-credential and connection-state reads
  only; no Posts, Images, Videos, Documents, or Poll write was performed.
- Google Calendar MCP regression remained in the full suite.

## Provider Limit

Video and document processing are checked once after upload. A non-available
state becomes `processing_unknown`; the system does not poll or retry a write.
The operator must inspect LinkedIn and record a manual resolution.

Phase 9 is not started.
