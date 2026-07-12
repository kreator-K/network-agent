# Phase 3 Content Image Support

## Scope

Content image support belongs inside `ContentInspirationAgent`; no new agent is added. The feature helps draft LinkedIn posts with optional image context while keeping all post output draft-only.

This phase does not publish to LinkedIn, schedule posts, edit images, create carousels, or bypass the existing gateway/orchestrator boundaries.

## Required Environment

- `TELEGRAM_BOT_TOKEN` for Telegram bot operation.
- `DATABASE_PATH` for SQLite persistence.
- `MOCK_MODE=true` for deterministic mock model/image behavior.
- `GENERATE_IMAGE_FOR_DRAFT_POSTS=false` by default.

Optional:

- `GENERATE_IMAGE_FOR_DRAFT_POSTS=true` enables the generated-image path for `/draft_post` when no uploaded image is pending.
- Real image generation still depends on `integrations/image_gateway.py`. If real generation is not implemented/configured, the draft falls back to text-only with image error metadata.

## Text-Only Draft Flow

Command:

```text
/draft_post <topic>
```

Expected behavior:

- Telegram handler parses the topic.
- `NetworkOrchestrator.draft_content_post` coordinates the workflow.
- `ContentInspirationAgent` drafts original LinkedIn copy through `ModelOrchestrationAgent`.
- The draft is saved to `content_posts` with `status='draft'`.
- `image_source='none'` unless generated-image mode is enabled.
- Telegram replies: `Here's a LinkedIn post draft.`

## Uploaded Image Flow

Flow:

```text
User uploads a Telegram photo
-> bot saves a local MVP file reference
-> bot stores it as pending image context for the next /draft_post
-> user runs /draft_post <topic>
```

Expected behavior:

- Telegram stores the image under `/tmp/network-agent-telegram-photos`.
- Pending image metadata is kept in Telegram app memory for the next draft request.
- `/draft_post` passes the local image reference to `NetworkOrchestrator`.
- `ContentInspirationAgent` includes the uploaded image reference in the drafting prompt as context.
- The draft is saved with `image_source='uploaded'` and `image_path=<local reference>`.
- Telegram replies: `Here's a LinkedIn post draft based on your uploaded image.`

MVP limitation:

- Uploaded image metadata is in-memory until the next `/draft_post`.
- If the bot restarts before `/draft_post`, the pending image context is lost.

## Generated Or Mock Image Flow

Flow:

```text
/draft_post <topic>
```

When `GENERATE_IMAGE_FOR_DRAFT_POSTS=true` and no uploaded image is pending:

- `ContentInspirationAgent` requests an image through `integrations/image_gateway.py`.
- In mock mode, the gateway returns deterministic mock metadata.
- In real mode, the gateway remains the only place where a real provider integration may live.
- Telegram handlers never call image APIs directly.

Expected SQLite fields:

- `image_source='generated'` when gateway generation succeeds.
- `image_path` stores the generated/mock image reference.
- If generation fails, the draft still saves as text-only with `image_source='none'`.

Telegram reply for successful generated/mock image:

```text
Here's a LinkedIn post draft with a suggested/generated image concept.
```

## SQLite Storage

`content_posts` is the source of truth for content drafts.

Stored fields used by this phase:

- `draft_text`
- `image_source`: `uploaded`, `generated`, or `none`
- `image_path`: local uploaded-image path or generated/mock reference
- `inspiration_source_notes`
- `status='draft'`
- `created_at`

Existing DBs that used legacy `image_source='user_upload'` are migrated to `uploaded` at database initialization.

## Safety Checks

- No LinkedIn post is published.
- No LinkedIn API is called.
- No button says `Post Now`, `Publish`, or `Send to LinkedIn`.
- Telegram handlers call `NetworkOrchestrator` for product workflows.
- Model calls go through `ModelOrchestrationAgent`.
- Image generation goes through `image_gateway.py`.
- Uploaded image context is used for drafting only; the system does not claim visual details that are not provided in text.

## Future Scope

Later phases may add:

- Persistent media library.
- Real image provider integration behind `image_gateway.py`.
- Image editing.
- Multi-image carousel drafts.
- LinkedIn posting only after explicit Telegram approval and a separate approved publishing phase.
