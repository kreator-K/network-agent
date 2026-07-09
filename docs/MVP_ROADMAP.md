# MVP Roadmap

## Phase 1: Documentation, Skeleton, And Mock Mode

Goals:
- Implement the 7 specialist agents and 1 LinkedIn integration module as scoped in `AGENTS.md`.
- Add `NetworkOrchestrator` as the only coordination layer for agents.
- Add a Telegram bot skeleton with thin handlers.
- Add SQLite persistence for prospects, interactions, refinement history, core intent, and refinable parameters.
- Use `MOCK_MODE=true` by default for model and image calls.
- Create `ModelOrchestrationAgent` as the gateway for all model-provider access.
- Build fresh LinkedIn authentication and posting logic in `LinkedInPublishAgent` once developer app approval is obtained.

Completion criteria:
- Telegram handlers do not call specialist agents directly.
- No LinkedIn post can occur without explicit approval.
- LinkedIn outreach remains draft-only and manually sent by the user.
- Calendar logic does not block time without `/meeting_confirmed`.
- Unit tests exist for each agent's normal and edge cases.

## Phase 2: Real Model Calls Through Nvidia NIM

Goals:
- Configure Nvidia NIM as the default provider through `.env`.
- Replace mock responses with real calls routed only through `ModelOrchestrationAgent`.
- Keep mock mode available for local development and tests.
- Add provider-level error handling, timeouts, and safe fallbacks.

Completion criteria:
- Specialist agents have no direct model-provider imports or clients.
- Tests can run without network access in mock mode.
- Real-provider integration tests are separately gated.

## Phase 3: Image Generation

Goals:
- Add image-generation support through the model/image gateway.
- Support ContentInspirationAgent workflows where the user requests generated imagery.
- Preserve the rule that user-uploaded images take precedence over generated imagery when both are provided.
- Keep image generation disabled or mocked by default in development.

Completion criteria:
- Image requests route through `ModelOrchestrationAgent` or its image gateway.
- User-uploaded image precedence is covered by tests.
- Publishing requires explicit approval for both copy and selected image.

## Phase 4: Google Calendar Integration

Goals:
- Integrate Google Calendar API for confirmed meeting blocks.
- Trigger calendar blocking only from explicit `/meeting_confirmed` flow.
- Avoid email invites in MVP unless explicitly added to scope later.
- Handle missing email, missing time, duplicate confirmations, and timezone ambiguity.

Completion criteria:
- Natural-language meeting inference does not trigger calendar blocking.
- `/meeting_confirmed` command validates required fields before calendar calls.
- Calendar API failures are reported back through Telegram.
- Relationship status and interaction history reflect successful calendar blocks.
