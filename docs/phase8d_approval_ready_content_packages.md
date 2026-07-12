# Phase 8D: Approval-ready Content Packages

Phase 8D turns a stored content opportunity into a reviewable `content_posts` package. It preserves the opportunity, profile version, scoring configuration, source references, factual claims, personal angle, risk assessment, hooks, and image brief. It does not publish, schedule, fetch sources, or score signals.

## Package Flow

`selected/candidate opportunity -> ContentInspirationAgent -> draft package -> Telegram review -> saved, approved_for_later_posting, or discarded`.

The agent uses `content_package_generation` through `ModelOrchestrationAgent` as the only model boundary, but deterministic source and claim validation remains authoritative. Invalid or unavailable model output never removes the valid deterministic package.

## Safety

Every factual claim references stored signal IDs. The default personal angle is a professional identity or analytical perspective, never an invented experience. Unresolved confirmation requirements, unsupported source references, high factual risk, or an image without alt text block approval.

`image_gateway` is the only image-provider boundary. Disabled mode makes a text-only package; mock mode returns its deterministic marker; real mode remains behind the gateway and an image failure preserves the text package.

## Telegram

Use `/prepare_content <opportunity_id>`, `/content_packages`, `/content_package <post_id>`, `/content_sources <post_id>`, `/content_claims <post_id>`, and `/revise_content <post_id> <revision_type>`. Buttons support save, approve for later, reject, source/claim review, and bounded revisions. Approval says clearly: “Nothing has been published.”

## Limits and Next Phase

Packages are review artifacts. They are not posting jobs and hold no LinkedIn identifier. Phase 8E may add scheduled briefings only after explicit approval of its separate scope.
