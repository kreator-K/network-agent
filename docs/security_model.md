# Security Model

## Boundaries

- `.env.local` is the only runtime environment source.
- Model calls go through `ModelOrchestrationAgent`.
- Public feeds go through `public_signal_gateway`.
- LinkedIn HTTP writes go only through `LinkedInApiClient`.
- Google Calendar MCP is injected behind the Calendar integration.
- Telegram handlers call the orchestrator and never own business logic.

## Approval and privacy

Outreach remains draft-only. CRM insertion from a candidate requires explicit
approval. Calendar writes require explicit meeting confirmation. LinkedIn
publishing requires a frozen request and one-time confirmation. Public content
is treated as untrusted data, not instructions; no private contact enrichment
or sensitive personal-attribute inference is performed.

## Network and files

Signal URLs, article URLs, LinkedIn API URLs, and temporary upload URLs are
validated against their allowlists and require HTTPS where applicable. Media
files are type, size, hash, and role validated. Redirects and private/reserved
network targets are blocked. SQLite stores encrypted LinkedIn credentials and
does not retain temporary upload URLs.

## Failure behavior

External uncertainty is durable and blocks automatic retry. Safe logs contain
stages, IDs, fingerprints, durations, typed errors, and provider status only;
tokens, OAuth material, client secrets, encryption keys, private content, and
full temporary URLs are excluded.
