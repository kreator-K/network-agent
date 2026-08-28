# MVP web demo script

## Setup

1. Activate the Python 3.11 environment and initialize SQLite.
2. Keep `MOCK_MODE=true`, `LINKEDIN_PUBLISH_MODE=disabled`, and
   `LINKEDIN_REAL_PUBLISH_ENABLED=false`.
3. Configure the protected Python API and Next.js variables described in
   `docs/vercel_deployment.md`.
4. Start the API locally with Uvicorn and the UI with `npm run dev` from
   `web/`, or use linked preview deployments.

## Walkthrough

1. Sign in through `/login` with the owner password.
2. Open **Profile**, review the active version, edit one allowed field, and
   confirm that a new immutable version appears.
3. Open **Prospects**, manually add a prospect, create a connection note, and
   verify the UI labels it draft-only for manual copying.
4. Preview a meeting. Verify no calendar action occurs, then use the separate
   explicit confirmation button.
5. Open **Signals**, scan only approved sources, and record preference feedback.
6. Open **Opportunities** and create a source-backed content package.
7. Open **Content Studio**, select a variant, create a revision, approve it for
   later posting, and create a frozen preview.
8. Open **Publish review** and inspect the exact commentary, package version,
   asset manifest, expiry, and payload fingerprint. With publishing disabled,
   confirmation must report that nothing was posted.
9. Open **Workflow runs** and verify the append-only graph receipts.
10. Open **Briefings** and run a manual dry briefing.

## Expected safety checks

- There is no LinkedIn outreach-send action or endpoint.
- Profile edits never mutate old versions or core intent.
- Meeting previews make no provider call.
- Content approval does not publish.
- Frozen publication requests require a separate exact confirmation.
- Disabled/mock automated checks never perform a real LinkedIn write.
- Telegram is not available through the standard runtime entrypoint.
