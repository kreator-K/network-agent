# System Architecture

```text
Telegram handlers
        |
NetworkOrchestrator
   |       |       |
specialist agents  integrations  SQLite source of truth
                     |             |
             model / feed / image / Calendar MCP / LinkedIn REST
```

Specialists own business decisions: signal intelligence scores public signals,
content inspiration builds packages, prospect discovery handles evidence-backed
candidate intake, relationship tracking owns CRM state, CalendarAgent owns
explicit meeting confirmation, and refinement owns controlled parameter change.
`ModelOrchestrationAgent` is the only model boundary.

LinkedIn uses `LinkedInPublishingGateway -> LinkedInApiClient`; the latter is
the only LinkedIn HTTP boundary. Google Calendar uses its existing persistent
MCP runtime and typed client. `SystemIntegrityAgent` is read-only. Briefing
execution is operational infrastructure and cannot approve, publish, send
outreach, insert prospects, or create calendar events.

Startup initializes SQLite, reconciles interrupted LinkedIn work without
retrying, starts the persistent Calendar MCP runtime, and then polls Telegram.
Shutdown closes the MCP owner task and subprocess within a bounded timeout.
