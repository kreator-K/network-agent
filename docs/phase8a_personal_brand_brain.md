# Phase 8A: Personal Brand Brain

## Purpose

The Personal Brand Brain stores human-controlled professional positioning for later signal ranking, content opportunities, post and image packages, prospect recommendations, and Telegram briefings. Phase 8A does not fetch sources, score signals, generate content, or publish anything.

## Separation Of Concerns

- `core_intent` contains system safety rules and is loaded from `core_intent.json`.
- `personal_brand_profile` contains evolving user identity, positioning, preferences, and goals.
- `refinable_parameters` contains controlled agent behavior changes only.

Profile facts are never silently changed by the refinement loop.

## Profile Schema

`PersonalBrandProfileData` requires `schema_version="1.0"`, `professional_identity`, non-empty `content_pillars`, and non-empty `target_audiences`.

Optional fields cover program, institutions, career focus, tone, depth, formats, humor preferences, experience boundaries, verified experiences, allowed claims, claims requiring confirmation, topics to avoid, posting preferences, networking goals, desired networks, industries, companies, geography, and notes. All list fields are bounded, normalized, and reject empty entries.

## Versioning

Every save appends immutable JSON as a new version. A partial unique SQLite index permits at most one active version. Activating a historical version changes only active state and activation time; it never rewrites its JSON. Canonical normalized JSON is SHA-256 hashed for change detection and integrity checks.

## Seed Initialization

`config/personal_brand_profile.json` is loaded only during database initialization when no SQLite profile exists. It is not read during normal profile workflows, and later seed-file edits never overwrite stored versions. Invalid seed data raises a clear initialization error; a missing seed leaves profile setup empty for explicit creation.

## Telegram Commands

```text
/brand_profile
/brand_profile_versions
/activate_brand_profile 2
/set_brand_field content_pillars | product management, AI products, product strategy
```

Activation uses version numbers only. List fields accept comma-separated values. Sensitive factual entries such as `verified_experiences` must be supplied explicitly; the system does not infer them.

## Personal-Claim Safeguards

Verified experiences, allowed personal claims, claims requiring confirmation, and experience boundaries are distinct fields. General interest in Cornell, Cornell Tech, a Tech MBA, product management, or AI products is not treated as proof of attendance, employment, completed work, or achievement.

## Known Limitations

There is no onboarding wizard, source scanning, signal scoring, automatic content generation, or automatic profile refinement in this phase.

## Phase 8B Dependency

Phase 8B will consume the active SQLite profile as relevance context for public signals. It must not read the live seed file or alter profile facts.
