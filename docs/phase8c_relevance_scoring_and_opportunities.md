# Phase 8C: Relevance Scoring and Content Opportunities

Phase 8C converts already stored public-feed signals into reviewable content opportunities. It does not fetch sources, draft a post, generate an image, schedule work, discover prospects, or publish to LinkedIn.

## Architecture

`SignalIntelligenceAgent` loads a normalized signal, the active personal-brand profile, and the active immutable scoring configuration. It applies deterministic eligibility gates before optional semantic analysis. The only model route is `ModelOrchestrationAgent` using `signal_semantic_scoring`; malformed model output becomes a deterministic-only fallback.

Hard gates cover approved and enabled provenance, blocked LinkedIn URLs, duplicate or failed records, required normalized fields, source credibility, freshness, factual-risk terms, content-pillar overlap, and plainly promotional material. A weighted score cannot override a failed gate.

## Score Formula

The `8c-v1` configuration combines topic and audience relevance, credibility, freshness, originality, personal-angle evidence, semantic relevance, audience-interest potential, and humor suitability. It subtracts factual, generic-commentary, promotional, and topic-saturation penalties. All score components are 0-100; confidence is 0-1.

Profile context distinguishes verified experiences and allowed claims from broad interests. With no verified experience, the opportunity is framed as an analytical observation and explicitly avoids personal-experience claims.

## Lifecycle and Review

Signals move from `normalized` to `scored` or `ineligible`. A qualifying scored signal may create one active `content_opportunities` record for the same signal/profile/configuration combination. Opportunities are `candidate`, `saved`, `selected`, `dismissed`, or `expired`; a dismissed record cannot be selected without a future explicit restore workflow.

Telegram commands: `/score_signal`, `/score_signals`, `/ranked_signals`, `/content_opportunities`, and `/content_opportunity`. The review buttons save, select, dismiss, capture preference feedback, or show source attribution. They never create a `content_posts` record.

## Cost and Safety Controls

The scoring configuration sets maximum batch size, model-assisted evaluations, opportunity count, retry count, freshness window, and risk thresholds. Logs contain identifiers, mode, and versions only, never prompts, profile JSON, feed bodies, or secrets. Feedback is stored as an audit record and never edits the profile, core intent, or scoring weights.

## Phase 8D Dependency

Phase 8D may consume an explicitly selected opportunity to create an approval-ready content package. It must retain this record's source references, scoring rationale, profile/configuration versions, and personal-claim safeguards.
