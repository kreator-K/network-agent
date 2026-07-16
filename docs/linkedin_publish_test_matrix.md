# LinkedIn Publish Test Matrix

| Area | Automated evidence |
|---|---|
| Configuration | `.env.local` only; disabled/false defaults; invalid host/version rejected |
| OAuth | state expiry/replay, exchange, introspection, scope normalization, OIDC identity |
| Credentials | Fernet encryption, active/revoked/expired handling, local restart persistence |
| Text | exact commentary/author, headers, 201 plus post ID, uncertain malformed success |
| Single image | MIME/hash/alt text, initialize/upload/post, no text fallback |
| Multi-image | 2 to configured maximum, distinct hashes, stable order, all-or-nothing post |
| Video | MP4/size/duration, exact multipart ranges, finalize, one processing read |
| Document | allowlisted file/MIME/size/hash, upload, one processing read |
| Article | HTTPS, credential-free URL, public-network resolution, frozen metadata, no scrape |
| Poll | 2-4 distinct options, length limits, allowlisted duration, exact frozen payload |
| Concurrency | one atomic claim wins; replay and duplicate preview are blocked |
| Recovery | uncertain states block retry; manual resolution is immutable and provider-free |
| Reconciliation | interrupted states become uncertain without a provider call |
| Backup/restore | encrypted credential structure and history preserved; writes do not resume |
| Telegram | all commands reply; diagnostics are local/read-only; malformed IDs fail cleanly |
| Boundaries | only `LinkedInApiClient` contains LinkedIn write endpoints |
| Regressions | content, prospect/CRM, outreach, refinement, and Calendar MCP full-suite coverage |

All provider-write tests use fake HTTP/provider clients. A real write was not
executed and requires separate approval for one frozen package.
