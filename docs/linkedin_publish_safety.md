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

## Phase 8G-B2

B2 is reserved for real text-only posting through an approved
`LinkedInPublishingGateway`. It has not started and must retain explicit human
approval and both confirmation controls.
