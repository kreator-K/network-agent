# Agent Architecture

## Coordinating Layer: NetworkOrchestrator

`NetworkOrchestrator` is the only application layer that coordinates specialist agents. Telegram bot handlers validate user input, normalize command payloads, and call the orchestrator. They must not call agents directly.

Text flow diagram:

```text
Telegram command or inline reply
  -> Telegram bot handler
  -> NetworkOrchestrator
  -> specialist agent or LinkedInPublishAgent
  -> persistence layer and ModelOrchestrationAgent as needed
  -> NetworkOrchestrator
  -> Telegram response, approval prompt, or confirmation
```

Approval-gated post publishing flow:

```text
LinkedIn post draft request
  -> NetworkOrchestrator
  -> ContentInspirationAgent
  -> ModelOrchestrationAgent
  -> draft saved as pending
  -> Telegram approval prompt
  -> explicit approval
  -> NetworkOrchestrator
  -> LinkedInPublishAgent
```

Manual outreach draft flow:

```text
Outreach draft request
  -> NetworkOrchestrator
  -> OutreachDraftAgent
  -> ModelOrchestrationAgent
  -> draft returned to user
  -> user manually copies and sends in LinkedIn
```

This manual outreach flow is permanent in MVP scope. LinkedIn's public developer API does not support sending connection requests, connection-request notes, regular direct messages, or InMail for individual developer accounts. Those capabilities are restricted to partner-only Sales Navigator/Talent Solutions APIs.

Meeting-confirmation flow:

```text
User sends /meeting_confirmed
  -> Telegram bot handler
  -> NetworkOrchestrator
  -> RelationshipTrackerAgent updates meeting status
  -> CalendarAgent blocks calendar time
```

## ProspectDiscoveryAgent

Purpose:
Intake and normalize manually provided prospect information. It may enrich structure and identify missing fields, but it must not search or scrape LinkedIn.

Inputs:
- Prospect name.
- User-provided LinkedIn profile URL.
- User-provided profile text, notes, context, or tags.
- Optional company, title, location, or relationship notes.

Outputs:
- Structured prospect record.
- Missing-data prompts for the user.
- Enrichment notes derived only from supplied data.

Dependencies:
- SQLite prospects table.
- NetworkOrchestrator.
- ModelOrchestrationAgent if model-assisted normalization is needed.

Edge cases:
- Missing name.
- Missing or malformed profile URL.
- Sparse notes with no useful personalization signal.
- Duplicate prospect record.
- User asks the agent to search LinkedIn.

## ProfileContextAgent

Purpose:
Extract useful personalization signals from user-provided profile text and notes for outreach drafting.

Inputs:
- Prospect record.
- User-supplied profile text.
- User notes about the prospect or relationship.
- Optional prior interactions.

Outputs:
- Personalization signals.
- Safe facts that may be referenced in outreach.
- Unusable or risky claims that should be excluded.

Dependencies:
- ProspectDiscoveryAgent output.
- SQLite prospects and interactions tables.
- ModelOrchestrationAgent for extraction.

Edge cases:
- Profile text is copied poorly or incomplete.
- Notes contain uncertain claims.
- User-provided notes imply a shared connection but do not state one.
- The extracted signal would require fabricating familiarity.

## OutreachDraftAgent

Purpose:
Draft LinkedIn connection requests and follow-up messages. It is permanently draft-only in MVP scope and never sends messages. The user manually copies draft text into LinkedIn and sends it themselves.

Inputs:
- Prospect record.
- Personalization signals from ProfileContextAgent.
- Relationship status and last-touch date.
- User instructions for tone, objective, or context.
- Core intent and refinable parameters.

Outputs:
- Draft connection request.
- Draft follow-up message.
- Safety notes when a claim is excluded or more user context is needed.
- Manual-send metadata indicating the draft cannot be API-sent.

Dependencies:
- ProfileContextAgent.
- RelationshipTrackerAgent for cadence and status.
- ModelOrchestrationAgent.
- SQLite interactions, core_intent, and refinable_parameters tables.

Edge cases:
- Follow-up requested before `FOLLOWUP_CADENCE_DAYS`, default 21 days, as configured in `core_intent`.
- Prospect has already replied.
- Draft would require invented shared credentials or experiences.
- Missing personalization context.
- User asks the system to send the outreach message through LinkedIn; the agent must refuse and keep the output draft-only.

## RelationshipTrackerAgent

Purpose:
Act as the CRM layer for prospects, interactions, statuses, follow-up due flags, and meeting state.

Inputs:
- Prospect records.
- Interaction events.
- User updates from Telegram.
- Approval and reply outcomes.
- Meeting confirmation commands.

Outputs:
- Updated prospect status.
- Follow-up eligibility decisions.
- Last-touch timestamps.
- Meeting status updates.

Dependencies:
- SQLite prospects and interactions tables.
- NetworkOrchestrator.
- CalendarAgent for confirmed meetings.

Edge cases:
- Follow-up is due but prospect already replied.
- Last-touch date is missing.
- Prospect is archived or inactive.
- Meeting confirmed with incomplete prospect data.
- Duplicate interaction events.

## ContentInspirationAgent

Purpose:
Draft LinkedIn post concepts and copy inspired by high-engagement creator patterns in similar niches, without copying source material.

Inputs:
- User topic, notes, thesis, or draft.
- Optional uploaded image.
- Optional request for generated image.
- Core intent and refinable parameters.
- Engagement outcome data.

Outputs:
- Draft LinkedIn post.
- Optional image-generation prompt or image selection decision.
- Explanation of which user-provided inputs were used.

Dependencies:
- ModelOrchestrationAgent for drafting and image gateway calls.
- SQLite refinable_parameters and refinement_history tables.
- NetworkOrchestrator for approval flow.
- LinkedInPublishAgent only after explicit approval.

Edge cases:
- User uploads an image and requests generated imagery in the same request; uploaded image wins by default.
- Draft leans too close to copied creator content.
- Post claims credentials or outcomes the user has not stated.
- User tries to publish without approval.
- Image generation is unavailable in mock mode.

## CalendarAgent

Purpose:
Block calendar time after explicit user confirmation of a meeting.

Inputs:
- `/meeting_confirmed` command.
- Prospect record.
- Meeting date, time, duration, and context supplied by the user.

Outputs:
- Calendar block request.
- Confirmation or validation error.
- Relationship status update request.

Dependencies:
- NetworkOrchestrator.
- RelationshipTrackerAgent.
- Calendar provider integration in later phases.
- SQLite prospects and interactions tables.

Edge cases:
- Meeting confirmed with no email on file; do not attempt an invite.
- Natural language implies a meeting but no `/meeting_confirmed` command was sent.
- Missing date or time.
- Ambiguous timezone.
- Duplicate meeting confirmation.

## RefinementLoopAgent

Purpose:
Use outreach and content outcome data to propose controlled refinements while preserving immutable core rules.

Inputs:
- Reply, acceptance, engagement, or publication outcome metrics.
- Current refinable parameters.
- Immutable core intent.
- Fixed evaluation set.

Outputs:
- Proposed refinable parameter changes.
- Semantic drift check result.
- Versioned refinement history entry.
- Rollback decision or rollback result.

Dependencies:
- SQLite refinement_history, core_intent, and refinable_parameters tables.
- ModelOrchestrationAgent for evaluation and drift checks.
- OutreachDraftAgent and ContentInspirationAgent outputs.

Edge cases:
- Metric improves but core intent is violated.
- More than 5 automatic refinement iterations are requested.
- Rollback target version does not exist.
- History write fails or would overwrite prior history.
- Proposed change tries to modify core intent.

## LinkedInPublishAgent

Purpose:
Provide a thin wrapper around LinkedIn posting APIs built fresh for this project once developer app approval is obtained. This module handles posting only; it does not send LinkedIn connection requests, direct messages, connection-request notes, or InMail.

Inputs:
- Approved post content.
- Approval flag set to true.
- LinkedIn auth configuration.
- Optional user-uploaded image selected by the approval flow.

Outputs:
- LinkedIn post result.
- API error details.
- Publication event for interaction history.

Dependencies:
- Fresh LinkedIn Share/Posts API implementation.
- NetworkOrchestrator.
- SQLite interactions table.

Edge cases:
- Approval flag is false or missing.
- Auth token is missing, expired, or invalid.
- LinkedIn API rejects content or media.
- Content was changed after approval.
- Module is asked to generate or judge content quality.
- Module is asked to send LinkedIn outreach messages or connection requests.
