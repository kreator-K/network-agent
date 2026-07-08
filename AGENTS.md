# AGENTS.md

## Repo
- Repo name: `network-agent`
- Product name: `Network Growth Agent`
- Language: Python 3.11

## Project Purpose

`network-agent` is a multi-agent system that reduces the time spent on professional networking and personal-brand building for a job search. It manages prospect outreach, relationship tracking, LinkedIn content creation, and calendar coordination - with a human-in-the-loop approval step before any external action (sending a message, posting content, blocking calendar time).

This is not an automation/spam tool. No agent may autonomously send a LinkedIn connection request, message, or post without explicit human approval via the Telegram interface.

## Non-Negotiable Rules

- No agent may submit a LinkedIn connection request, message, or post automatically. Every outbound action requires explicit human approval through Telegram.
- No agent may scrape or programmatically search LinkedIn. Prospect data is manually provided by the user (name, profile URL, notes) and enriched by agents - never discovered via scraping.
- No agent may fabricate shared connections, experiences, skills, or credentials the user has not actually stated.
- Follow-up cadence must never be more frequent than once every 2-3 weeks per prospect, to avoid pester behavior.
- Calendar blocking only triggers on explicit user confirmation (e.g., `/meeting_confirmed`), never on inferred/parsed natural language intent from a reply.
- All model calls must go through `ModelOrchestrationAgent`. No agent calls an LLM/VLM/image provider directly.
- `NetworkOrchestrator` coordinates all specialist agents. Telegram bot handlers call the orchestrator, never agents directly.
- The LinkedIn publishing integration (ported from the prior `linkedin_agent` project) is the only module allowed to call the LinkedIn API. It has no opinion on content quality - it only authenticates and posts what it is given, after human approval.

## Agent Architecture

`NetworkOrchestrator` coordinates:

1. `ProspectDiscoveryAgent` - structured intake and enrichment of manually-provided prospect info. Does not search or scrape.
2. `ProfileContextAgent` - extracts personalization signal from user-provided profile text/notes for use in outreach drafting.
3. `OutreachDraftAgent` - drafts connection requests and follow-up messages. Never sends.
4. `RelationshipTrackerAgent` - CRM. Tracks contact status, last-touch date, follow-up-due flags, meeting status.
5. `ContentInspirationAgent` - drafts LinkedIn posts inspired by (not copied from) high-engagement creator patterns in similar niches. Supports both user-uploaded images and agent-generated images (via image gateway). User-uploaded image takes precedence if both are provided in the same request.
6. `CalendarAgent` - blocks calendar time on explicit meeting confirmation via `/meeting_confirmed`. Email invites are future scope, not MVP.
7. `RefinementLoopAgent` - tracks reply/engagement outcomes for `OutreachDraftAgent` and `ContentInspirationAgent`, proposes refinements, and tests them against a fixed evaluation set. See Refinement Loop Rules below.

Supporting integration module (not a decision-making agent):

8. `LinkedInPublishAgent` - thin wrapper around the LinkedIn API, ported from the prior working `linkedin_agent` repo's auth/posting logic. Only called after explicit human approval in Telegram. Has no content-generation logic.

## Refinement Loop Rules

- `RefinementLoopAgent` may only modify `refinable_parameters.json` (tone variations, phrasing patterns, structural choices).
- `RefinementLoopAgent` must never modify `core_intent.json` (immutable rules: no fabrication, cadence limits, tone floor). Changes to `core_intent.json` require explicit human edit, never agent-written.
- Every refinement is versioned and logged to `refinement_history.json` with: version, timestamp, what changed, why, metric before/after, and a diff against v1 (the original).
- Before a refinement is accepted, run a semantic drift check: does the refined prompt still satisfy every rule in `core_intent.json`? Reject if any rule is violated, regardless of metric improvement.
- Cap automatic refinement iterations at 5. After 5 cycles, pause and require human review before continuing.
- Any refinement must be able to be rolled back to any prior version.

## Interface

Telegram bot is the primary interface. All approval, editing, and confirmation flows happen via Telegram commands and inline replies. Data is persisted in SQLite for MVP, not just in-memory or chat history.

## Development Rules

- Keep the MVP scoped to the 7 agents + 1 integration module above. Do not add new agents without updating this file first.
- Prefer structured data (typed dataclasses/pydantic models) over loose dicts, consistent with prior projects (`video-data-agent`, `ads-agent`).
- Keep Telegram bot handlers thin - they validate input and call `NetworkOrchestrator`, never agents directly.
- Keep model orchestration separate from bot handlers and from business logic.
- Use mock mode by default for all model/image calls during development (`MOCK_MODE=true`), same pattern as `ads-agent`.
- Use Nvidia NIM as the default model provider (same pattern as `video-data-agent`), configurable via `.env`.

## Testing Rules

- Every agent needs unit tests for normal cases and edge cases.
- `RefinementLoopAgent` needs tests proving: core_intent violations are rejected even when metrics improve; iteration cap is enforced; rollback works; history log is append-only and accurate.
- `CalendarAgent` needs tests proving it never triggers without explicit `/meeting_confirmed` command.
- `OutreachDraftAgent` and `ContentInspirationAgent` need tests proving no fabricated claims appear in output (no invented shared connections, skills, or credentials).
- Follow-up cadence logic needs tests proving it never suggests contact more frequently than the 2-3 week floor.
- `LinkedInPublishAgent` needs tests proving it never fires without an explicit approval flag set to true.

## QA Edge Cases

- Prospect with missing/incomplete profile data.
- Prospect marked meeting-confirmed with no email on file (should not attempt invite).
- Refinement that improves reply-rate metric but violates core_intent (must be rejected).
- User uploads image AND requests generated image in the same post (user upload wins by default).
- Follow-up due for a prospect who already replied (should not re-trigger).
- Telegram command sent with malformed/missing arguments.
- LinkedIn publish attempted without prior approval flag (must be rejected).

## Required Commands

After any code change:

```bash
python -m pytest
python -m mypy .
python -m ruff check .
```

If these are missing, create the closest equivalent scripts.

## Final Response Rule for Codex

Whenever completing a task, summarize:
1. What files changed
2. What was implemented
3. What tests were added
4. What commands were run
5. Any known limitations or ambiguities needing my clarification
