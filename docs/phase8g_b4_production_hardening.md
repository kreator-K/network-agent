# Phase 8G-B4 Production Hardening

## Controls

- Real writes require `LINKEDIN_PUBLISH_MODE=real` and
  `LINKEDIN_REAL_PUBLISH_ENABLED=true`; defaults fail closed.
- Preview creation is idempotent and confirmation uses an atomic SQLite claim.
- Confirmation attempts are bounded by `LINKEDIN_MAX_CONFIRMATION_ATTEMPTS`.
- No SQLite transaction remains open during provider HTTP operations.
- Provider 429, 5xx, timeout, connection reset, and malformed write success are
  uncertain and are never retried automatically.
- Startup reconciliation converts interrupted write/upload states to
  `publish_uncertain` without creating a provider client.
- Manual uncertainty resolution is append-only; the original uncertain request
  remains immutable and auditable.
- Provider upload URLs require HTTPS and an allowlisted LinkedIn host, are never
  stored durably, and do not receive the OAuth bearer token.
- Terminal requests and append-only event/resolution ledgers are protected by
  SQLite triggers.
- Upgrades from the Phase 8G-A request ledger archive the old table as
  `linkedin_publish_requests_legacy_8ga`. Compatible rows are imported only as
  terminal audit records, so an old preview can never become confirmable.

## Operator Visibility

`/linkedin_publish_diagnostics` is read-only and reports mode, kill switch,
connection state, pending/in-progress/uncertain/stale counts, recent safe
failures, and reconciliation count. It never contacts LinkedIn.

## Startup

Bot startup runs local reconciliation before normal operation. It does not
reissue an upload or post. Environment changes require process restart because
settings are loaded from `.env.local` at process initialization.
