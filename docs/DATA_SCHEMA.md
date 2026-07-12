# Data Schema

SQLite is the source of truth for operational data. `config/core_intent.json` is human-editable input loaded into SQLite at startup or explicit reload; agents do not read it live. Refinable parameters, outcomes, proposals, and history live only in SQLite.

## Core Tables

### `prospects`

Stores manually entered prospects. Columns: `id INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, optional `profile_url`, `location`, `role_title`, `company`, and `notes`, `source TEXT`, `status TEXT`, `last_touch_date TEXT`, `created_at TEXT`, and `updated_at TEXT`. Status values are `not_contacted`, `outreach_drafted`, `connection_sent`, `connected`, `meeting_confirmed`, and `closed`.

### `interactions`

Stores outreach drafts, manually sent outreach, replies, notes, and meeting confirmations. It has `id`, `prospect_id INTEGER NOT NULL` referencing `prospects(id)`, `interaction_type`, `content`, `direction`, optional lifecycle `status`, optional `source`, `created_at`, and `updated_at`. Manual LinkedIn outreach is represented by `interaction_type='linkedin_connection_request'` and `status='sent_manually'`; it is never an API send event.

### `core_intent`

Immutable runtime reference data loaded from JSON. It has `id`, unique `rule_key`, `rule_value`, `description`, and `updated_at`. `cadence_floor_days=21` is the default follow-up floor and is read from this table.

### `personal_brand_profile`

Stores user-authored personal-brand versions separately from safety policy and refinement parameters. It has `id`, unique `version`, `schema_version`, canonical `profile_json`, `profile_hash`, `is_active`, `created_at`, and `activated_at`. Historical rows are immutable; a partial unique index and transactional activation enforce at most one active version. The initial template is in `config/personal_brand_profile.json` and is not read live by agents after a profile is stored in SQLite.

### `refinable_parameters`

SQLite-only versioned parameters for `outreach_draft_agent` and `content_inspiration_agent`. The unique key is `(agent_name, parameter_key, version)`. Only one active version per parameter key is valid. An empty table is valid before the first refinement cycle.

### `refinement_history`

Append-only history containing agent, version, change, rationale, optional metrics, diff against version one, semantic-check result, acceptance, and timestamp. Active versions after the initial version must have accepted history; the empty initial state is valid before refinement begins.

### `refinement_outcomes`, `refinement_loop_runs`, and `refinement_proposals`

These tables record outcome evidence, run metadata, and human-reviewable proposals. Proposal states are `pending_approval`, `applied`, `rejected`, `failed_validation`, or `expired`.

### `content_posts`

Stores content drafts and review state. Image sources are `uploaded`, `generated`, or `none`. Internal lifecycle states are `draft`, `saved`, `approved_for_later_posting`, and `discarded`. No row represents an automatic LinkedIn publication in the MVP.

### `calendar_blocks`

Stores meetings confirmed explicitly by the user. It references `prospects(id)` and includes `scheduled_date`, `start_time`, optional `end_time`, `timezone`, `notes`, optional `external_event_id`, lifecycle `status`, and `created_at`. Calendar status values are `confirmed`, `calendar_created`, and `calendar_failed`.

## Integrity Rules

- Foreign keys are enabled whenever the application opens SQLite.
- Follow-up eligibility uses `core_intent.rule_key='cadence_floor_days'`, default `21`; cadence is not hardcoded in agent logic.
- A meeting-confirmed prospect must have both a `meeting_confirmed` interaction and a calendar block.
- Only explicitly approved refinement proposals may change refinable parameters.
- The system integrity check is read-only and validates foreign keys, cadence, refinement safety, meeting consistency, and content lifecycle state.

## Phase 8C Signal Scoring

### `signal_scoring_config`

Stores immutable scoring versions: `id`, unique `version`, canonical `config_json`, `config_hash`, `is_active`, `created_at`, and `activated_at`. A partial unique index permits exactly one active configuration. The seed in `config/signal_scoring_config.json` is used only when the table is empty.

### `signals` scoring fields

Normalized signal records retain nullable `profile_version`, `scoring_config_version`, `score_json`, `total_score`, `scoring_confidence`, `scoring_mode`, `scored_at`, `eligibility_status`, and `eligibility_reasons_json`. This keeps Phase 8B ingestion backward-compatible while preserving every Phase 8C decision.

### `content_opportunities`

Stores review-only, pre-draft angles. It references a primary signal, profile version, and scoring configuration version; preserves source references and a complete score breakdown; and moves through `candidate`, `saved`, `selected`, `dismissed`, or `expired`. A partial unique index prevents duplicate active opportunities for the same signal/profile/configuration combination. It never stores a final post or image prompt.

### `content_preference_feedback`

Append-only explicit feedback records include `target_type`, `target_id`, `feedback_type`, optional note, source, and timestamp. They do not alter a personal-brand profile, core intent, or scoring configuration.
