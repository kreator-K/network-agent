# LinkedIn Publishing Safety

## Decision

Network-agent uses LinkedIn's official authorization-code OAuth flow and REST
API directly. It does not use LinkedIn MCP and does not create or maintain a
LinkedIn MCP server. The working Google Calendar MCP integration is unrelated
and remains unchanged.

## Phase 8G-B1

B1 provides OAuth foundation only. It requests exactly these scopes:

- `openid`
- `profile`
- `w_member_social`

Access and refresh tokens are encrypted before local storage. Authentication
does not authorize publishing. `LINKEDIN_PUBLISH_MODE=disabled` remains the
required mode throughout B1.

The existing disabled/mock publishing boundary and Telegram double-confirmation
controls remain in place. No scraping, feed reading, messaging, connection
requests, InMail, or autonomous publishing is permitted.

## Publishing Boundary

`NetworkOrchestrator` coordinates `LinkedInPublishingGateway`, and only
`LinkedInApiClient` performs official LinkedIn HTTP requests. Every format uses
an approved content package, frozen preview, deterministic payload and asset
hashes, expiring request ID, and separate `/confirm_publish <request_id>`.

Disabled mode and a disabled real-publish kill switch make no provider request.
Mock mode records a deterministic local result and never contacts LinkedIn.
Real mode requires both controls and never retries a provider write
automatically. Interrupted or ambiguous writes become uncertain and block
replay until the operator resolves them.

Startup reconciliation never resumes a write. It marks interrupted work
uncertain and records an append-only audit event. Manual resolution records the
operator's decision separately and does not rewrite the original uncertainty.

Phase 8G-B2 supports text and one approved image. Phase 8G-B3 adds multi-image,
video, document, article, and poll packages through the same boundary. No
workflow may scrape LinkedIn, send outreach, schedule publishing, infer consent,
or publish from a briefing, model, scheduler, prospect, or outreach workflow.
