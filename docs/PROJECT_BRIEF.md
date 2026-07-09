# Project Brief

## Product Goal

`network-agent` powers the Network Growth Agent, a multi-agent assistant for professional networking and personal-brand building during a job search. The product reduces manual work around prospect intake, outreach drafting, relationship tracking, LinkedIn content preparation, and meeting coordination.

The system is explicitly human-in-the-loop. It may draft, organize, suggest, and prepare actions, but it must not send LinkedIn connection requests or LinkedIn messages at all. Outreach stays permanently draft-only: the user manually copies drafted outreach into LinkedIn and sends it themselves. LinkedIn posts and calendar blocks require explicit user approval through Telegram before any external action.

## Core Safety Boundaries

- No automated LinkedIn connection requests or messages.
- LinkedIn posting may be automated only after explicit approval.
- No LinkedIn scraping or programmatic LinkedIn search.
- No fabricated shared connections, experiences, skills, credentials, or claims.
- Follow-ups may not be suggested more often than `FOLLOWUP_CADENCE_DAYS`, default 21 days, from `core_intent`.
- Calendar blocking requires an explicit `/meeting_confirmed` command.
- All model calls go through `ModelOrchestrationAgent`.
- Telegram handlers call `NetworkOrchestrator`, not specialist agents directly.

## Agents And Integration Module

The MVP contains seven decision-making agents coordinated by `NetworkOrchestrator`:

- `ProspectDiscoveryAgent`: Intake and enrich manually supplied prospect information.
- `ProfileContextAgent`: Extract personalization signals from user-provided profile text and notes.
- `OutreachDraftAgent`: Draft connection requests and follow-up messages for manual copy/paste sending only.
- `RelationshipTrackerAgent`: Track prospect status, touch history, meeting status, and follow-up eligibility.
- `ContentInspirationAgent`: Draft LinkedIn post ideas and copy based on patterns, user notes, and optional imagery.
- `CalendarAgent`: Block calendar time only after explicit meeting confirmation.
- `RefinementLoopAgent`: Track outcomes, propose refinements, enforce drift checks, and preserve rollback history.

The MVP also includes one supporting integration module:

- `LinkedInPublishAgent`: A thin LinkedIn API wrapper built fresh for approved post publishing. It authenticates and posts only already-approved content. It does not decide what to publish and has no content-generation logic.

## MVP Scope

The MVP should provide:

- Telegram as the primary user interface for intake, approvals, edits, and confirmations.
- SQLite persistence for prospects, interactions, refinement history, core intent, and refinable parameters.
- Mock mode by default for model and image calls.
- A `ModelOrchestrationAgent` boundary for all LLM, VLM, and image-provider access.
- Manual prospect intake only.
- Permanently draft-only outreach workflows.
- Draft-only content workflows until the user approves publishing.
- LinkedIn publishing only after explicit approval.
- Calendar blocking only after `/meeting_confirmed`.

Out of scope for MVP:

- LinkedIn scraping.
- Automated LinkedIn outreach sending.
- Autonomous posting.
- Email invites.
- New agents beyond the seven listed in `AGENTS.md`.
- Any direct model-provider call from a specialist agent or Telegram handler.
