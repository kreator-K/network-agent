# Phase 8G-B3 — Richer LinkedIn Content Formats

Status: completed through automated and mocked acceptance. Live provider writes
were not executed and still require package-specific confirmation.

B3 extends the existing request lifecycle with multi-image, video, document,
article, and poll package types. Every type freezes commentary, metadata,
assets, hashes, owner, API version, and visibility before confirmation.

- Multi-image: 2–20 ordered, distinct approved JPG/PNG/GIF assets.
- Video: one approved MP4 with frozen duration and hash, optional approved
  thumbnail/captions, member-owned initialization, exact provider byte ranges,
  finalize step, and one processing-status read.
- Document: one approved PDF, DOC/DOCX, or PPT/PPTX with a frozen title and one
  processing-status read.
- Article: approved HTTPS URL and frozen title/description; no confirmation-time scraping.
- Poll: 2–4 distinct options and an allowlisted fixed duration.

Provider-issued asset URNs are accepted only from the current upload session.
No rich format may downgrade after an asset failure. Live provider verification
remains pending explicit package-specific user confirmation.
