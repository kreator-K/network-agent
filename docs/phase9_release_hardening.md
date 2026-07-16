# Phase 9 Release Hardening

Phase 9 turns the Phase 8 feature set into one release candidate. The release
path preserves the existing approval boundaries:

```text
approved source -> signal -> opportunity -> content package -> Telegram review
                                             -> frozen LinkedIn request
stored signal -> evidence-backed candidate -> approval -> CRM -> outreach draft
explicit meeting confirmation -> CalendarAgent -> Google Calendar MCP
```

The release gate is `python -m scripts.release_check`. It validates local
configuration, safe publish switches, generated command documentation, required
runbooks, tracked-file secret patterns, a temporary-copy migration, and the
read-only integrity suite. Without `--skip-tests`, it also runs pytest, mypy,
and Ruff. It never performs a provider write.

Phase 9 certification requires:

- `LINKEDIN_PUBLISH_MODE=disabled`;
- `LINKEDIN_REAL_PUBLISH_ENABLED=false`;
- image generation and daily briefings disabled unless explicitly tested;
- public HTTP signal fetching disabled;
- `.env.local` as the only runtime environment source;
- temporary database copies for migration and restore tests.

The Google Calendar MCP remains a separate integration. Calendar writes still
require the explicit deterministic meeting-confirmation flow and retain their
idempotency record.

Certification result: PASS. The release gate completed with 409 passing tests,
clean mypy and Ruff checks, a successful temporary-copy migration/integrity
check, and no provider writes. Phase 10 is not started.
