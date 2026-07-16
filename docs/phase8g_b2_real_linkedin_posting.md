# Phase 8G-B2 — Text and Single-Image Publishing

B2 uses one durable `linkedin_publish_requests` record per approved package
version, authenticated member, format, payload hash, and image hash. Preview
creation performs no provider request. Confirmation is accepted only through a
request ID and is atomically claimed before any HTTP write.

Text posts preserve exact commentary and use the authenticated Person URN.
Single-image posts validate the local JPG, PNG, or GIF, MIME signature,
dimensions, size, hash, and alt text before initializing and uploading the
image. An image failure never falls back to text-only.

Disabled mode and mock mode make no LinkedIn request. Real mode requires
`LINKEDIN_PUBLISH_MODE=real` and `LINKEDIN_REAL_PUBLISH_ENABLED=true`. Automated
and mocked acceptance passed; no live post was created during implementation.
