# QA Test Plan

## ProspectDiscoveryAgent

Normal intake:
Given a name, LinkedIn URL, and notes, the agent creates a structured prospect record without external lookup.

Missing profile data:
Given only a name, the agent creates a partial record and returns prompts for missing details instead of failing.

Malformed URL:
Given an invalid LinkedIn URL, the agent flags the URL and does not attempt to fix it through web search.

No scraping:
Given a request to "find this person on LinkedIn," the agent refuses or redirects the user to manually provide the data.

Duplicate prospect:
Given a prospect with the same name and LinkedIn URL as an existing record, the agent returns a duplicate warning.

## ProfileContextAgent

Extract safe personalization:
Given profile text and notes, the agent returns only facts present in the supplied material.

Incomplete profile text:
Given sparse copied profile text, the agent returns low-confidence or missing-context notes instead of fabricating details.

Uncertain shared connection:
Given notes that imply but do not state a shared connection, the agent excludes the claim from safe personalization.

Risky claim filtering:
Given ambiguous credentials or experience claims, the agent marks them as unusable unless the user explicitly confirms them.

## OutreachDraftAgent

Connection request draft:
Given safe prospect context, the agent drafts a concise connection request and stores it as pending approval.

No fabricated claims:
Given no shared connection, skill, or credential in the input, the draft does not invent any of those claims.

Follow-up cadence floor:
Given a last-touch date less than 2 weeks ago, the agent refuses to suggest a follow-up.

Replied prospect:
Given a prospect who has replied, the agent does not generate a routine follow-up-due prompt.

Permanent draft-only outreach:
Given a user request to draft and send immediately, the agent drafts only and explains that the user must manually copy and send the message in LinkedIn.

## RelationshipTrackerAgent

Status update:
Given a saved outbound interaction, the agent updates `last_touch_at` and prospect status.

Follow-up due:
Given a last-touch date older than the configured floor and no reply, the agent marks a prospect follow-up eligible.

Follow-up suppression after reply:
Given a follow-up-due prospect who has since replied, the agent clears or suppresses the follow-up prompt.

Missing last-touch date:
Given no last-touch date, the agent does not mark follow-up due without enough history.

Duplicate interaction:
Given the same event twice, the agent avoids double-counting or corrupting status.

## ContentInspirationAgent

Draft post:
Given a user topic and notes, the agent creates a draft LinkedIn post for approval.

No copied creator content:
Given inspiration patterns, the agent produces original phrasing rather than copying source material.

No invented credentials:
Given no stated job title, employer, achievement, or credential, the post does not invent one.

Uploaded image precedence:
Given both a user-uploaded image and a generated-image request, the agent uses the uploaded image by default.

Mock image mode:
Given mock mode is enabled, image generation returns a mock artifact or placeholder decision rather than calling a real image provider.

## CalendarAgent

Explicit confirmation required:
Given a natural-language reply like "great, meeting booked," the agent does not block calendar time.

Meeting confirmed command:
Given `/meeting_confirmed` with required meeting details, the agent creates a calendar block request.

No email on file:
Given a confirmed meeting with no prospect email, the agent does not attempt an email invite.

Missing date or time:
Given `/meeting_confirmed` without enough scheduling detail, the agent asks for missing fields and does not block time.

Duplicate confirmation:
Given the same meeting confirmation twice, the agent avoids duplicate calendar blocks.

## RefinementLoopAgent

Metric improvement with violation:
Given a refinement that improves reply rate but violates core intent, the agent rejects the refinement.

Iteration cap:
Given 5 automatic refinement cycles have already occurred, the agent pauses and requires human review.

Rollback:
Given a valid prior version, the agent restores refinable parameters to that version and logs the rollback.

Append-only history:
Given a refinement action, the agent appends a new history row and never mutates prior rows.

Core intent immutability:
Given a proposed change to `core_intent`, the agent rejects it and records the reason.

## LinkedInPublishAgent

Approval required:
Given post content without `approved=true`, the module refuses to publish.

Approved post:
Given approved post content and valid auth, the module calls the LinkedIn posting integration.

Changed-after-approval:
Given content differs from the approved draft, the module refuses to publish until reapproved.

Auth failure:
Given missing or expired LinkedIn credentials, the module returns an auth error and does not retry blindly.

No content judgment:
Given approved content, the module does not rewrite, score, or judge quality before posting.

## Telegram Interface And Orchestrator

Malformed command:
Given a Telegram command with missing or malformed arguments, the handler returns validation guidance and does not call agents with invalid data.

Thin handler rule:
Given any command, the handler validates and calls `NetworkOrchestrator`; it does not call specialist agents directly.

Approval flow:
Given a pending draft, the Telegram approval action records explicit approval before any outbound integration is called.

Model boundary:
Given an agent needs model output, the call is routed through `ModelOrchestrationAgent`.
