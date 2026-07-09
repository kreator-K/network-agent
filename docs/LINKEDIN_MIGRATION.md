# LinkedIn Publish Implementation

`LinkedInPublishAgent` will be built fresh, not ported from any prior `linkedin_agent` repository.

Rationale: LinkedIn posting through the Share/Posts API is straightforward to implement directly once developer app approval is obtained. Building fresh avoids inheriting unknown authentication assumptions, stale dependencies, and edge-case debt from a prior project.

The module should remain a thin integration wrapper. It must not generate content, judge content quality, or decide whether a post should be published. It may only authenticate and publish content that has already received explicit human approval through Telegram.

## Implementation Requirements

- Implement LinkedIn auth and posting directly for this project.
- Add an explicit approval guard before any publish call.
- Record publish results in interaction history.
- Return structured errors for auth, validation, media, and API failures.
- Support posting only. Do not implement LinkedIn connection requests, direct messages, connection-request notes, or InMail.

## Target Interface

Expected inputs should include:

- Approved content payload.
- Approval flag.
- Approval timestamp or approval interaction ID.
- Optional media reference.
- LinkedIn auth configuration.

Expected outputs should include:

- Published post ID or URL when available.
- API response metadata.
- Structured error information.
- Interaction-history event payload.
