# Data Schema

This document proposes the initial SQLite schema for the MVP. SQLite is the source of truth for all operational data. The schema favors explicit timestamps, JSON text fields for structured agent artifacts, and relationships that preserve the human approval trail.

`core_intent.json` is the only human-editable configuration file in this model. It is loaded into the SQLite `core_intent` table on startup or explicit reload. Agents read `core_intent` from SQLite, not from the JSON file directly. `refinable_parameters` and `refinement_history` live natively in SQLite only; no JSON mirror is required.

## prospects

Stores manually provided prospect records. Prospect discovery must not scrape or search LinkedIn.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY | Internal prospect ID. |
| full_name | TEXT NOT NULL | User-provided prospect name. |
| linkedin_url | TEXT | User-provided profile URL. |
| company | TEXT | Optional user-provided company. |
| title | TEXT | Optional user-provided title. |
| location | TEXT | Optional user-provided location. |
| notes | TEXT | User-provided notes. |
| profile_text | TEXT | User-provided copied profile text. |
| status | TEXT NOT NULL DEFAULT 'new' | Suggested values: `new`, `drafted`, `contacted`, `replied`, `meeting_confirmed`, `archived`. |
| last_touch_at | TEXT | ISO-8601 timestamp for most recent outbound or meaningful interaction. |
| follow_up_due_at | TEXT | ISO-8601 timestamp. Must respect `FOLLOWUP_CADENCE_DAYS`, default `21`, from `core_intent`. |
| meeting_status | TEXT NOT NULL DEFAULT 'none' | Suggested values: `none`, `confirmed`, `blocked`. |
| meeting_at | TEXT | ISO-8601 timestamp if known. |
| email | TEXT | Optional. Missing email must not block calendar time, but should prevent email invites. |
| created_at | TEXT NOT NULL | ISO-8601 timestamp. |
| updated_at | TEXT NOT NULL | ISO-8601 timestamp. |

Relationships:
- `interactions.prospect_id` references `prospects.id`.

## interactions

Stores drafts, approvals, replies, publishing events, meeting confirmations, and calendar events.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY | Internal interaction ID. |
| prospect_id | INTEGER | Nullable for content posts not tied to one prospect. References `prospects.id`. |
| interaction_type | TEXT NOT NULL | Suggested values: `connection_draft`, `follow_up_draft`, `reply`, `post_draft`, `approval`, `publish`, `meeting_confirmed`, `calendar_block`. |
| channel | TEXT NOT NULL | Suggested values: `telegram`, `linkedin`, `calendar`, `internal`. |
| direction | TEXT NOT NULL | Suggested values: `inbound`, `outbound`, `internal`. |
| content | TEXT | Draft, message body, reply text, or event description. |
| metadata_json | TEXT | JSON object for agent-specific structured metadata. |
| approval_required | INTEGER NOT NULL DEFAULT 0 | Boolean. |
| approved | INTEGER NOT NULL DEFAULT 0 | Boolean. Must be true before publishing. Outreach messages are draft-only and manually sent by the user outside the app. |
| approved_at | TEXT | ISO-8601 timestamp. |
| sent_or_published_at | TEXT | ISO-8601 timestamp. |
| created_by | TEXT NOT NULL | Agent/module/user that created the interaction. |
| created_at | TEXT NOT NULL | ISO-8601 timestamp. |

Relationships:
- Optional many-to-one relationship with `prospects`.
- Approval and publish interactions should reference prior draft IDs in `metadata_json`.

## core_intent

Immutable reference table for non-negotiable rules and configurable safety values. Agents must not update these rows automatically. Rows are loaded from human-edited `core_intent.json` on startup or explicit reload; SQLite remains the runtime source of truth.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY | Internal rule ID. |
| rule_key | TEXT NOT NULL UNIQUE | Stable rule identifier. |
| rule_text | TEXT NOT NULL | Human-readable immutable rule. |
| value_json | TEXT | Optional JSON value for configurable rules, such as `{"days": 21}` for `FOLLOWUP_CADENCE_DAYS`. |
| category | TEXT NOT NULL | Suggested values: `approval`, `linkedin`, `fabrication`, `cadence`, `calendar`, `model_access`. |
| active | INTEGER NOT NULL DEFAULT 1 | Boolean. |
| version | INTEGER NOT NULL DEFAULT 1 | Starts at 1; changes require human edit. |
| created_at | TEXT NOT NULL | ISO-8601 timestamp. |
| updated_at | TEXT NOT NULL | ISO-8601 timestamp. |

Relationships:
- Referenced during `RefinementLoopAgent` semantic drift checks.

Required initial value:
- `rule_key='FOLLOWUP_CADENCE_DAYS'`
- `value_json='{"days": 21}'`
- `category='cadence'`
- `rule_text='Follow-up cadence must never suggest contact more frequently than the configured day interval.'`

## refinable_parameters

Stores controlled prompt and strategy parameters that `RefinementLoopAgent` may update. This table lives natively in SQLite only; there is no `refinable_parameters.json` mirror.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY | Internal parameter ID. |
| parameter_key | TEXT NOT NULL UNIQUE | Stable key. |
| parameter_value_json | TEXT NOT NULL | JSON value for tone, phrasing, structure, or drafting choices. |
| applies_to | TEXT NOT NULL | Suggested values: `outreach`, `content`, `both`. |
| version | INTEGER NOT NULL | Current parameter version. |
| active | INTEGER NOT NULL DEFAULT 1 | Boolean. |
| created_at | TEXT NOT NULL | ISO-8601 timestamp. |
| updated_at | TEXT NOT NULL | ISO-8601 timestamp. |

Relationships:
- `refinement_history.parameter_key` references `refinable_parameters.parameter_key`.

## refinement_history

Append-only SQLite log of refinement proposals, acceptances, rejections, and rollbacks. This table has no JSON mirror.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY | Internal history ID. |
| version | INTEGER NOT NULL | Refinement version. |
| parameter_key | TEXT NOT NULL | Parameter changed or proposed. |
| action | TEXT NOT NULL | Suggested values: `proposed`, `accepted`, `rejected`, `rollback`. |
| changed_by | TEXT NOT NULL | Usually `RefinementLoopAgent` or `human`. |
| what_changed | TEXT NOT NULL | Human-readable change summary. |
| why | TEXT NOT NULL | Rationale. |
| metric_before_json | TEXT | JSON metric snapshot. |
| metric_after_json | TEXT | JSON metric snapshot. |
| diff_against_v1_json | TEXT NOT NULL | JSON diff against original version. |
| semantic_drift_passed | INTEGER NOT NULL DEFAULT 0 | Boolean. |
| rejection_reason | TEXT | Required when rejected. |
| rollback_to_version | INTEGER | Target version for rollback actions. |
| created_at | TEXT NOT NULL | ISO-8601 timestamp. |

Relationships:
- References `refinable_parameters.parameter_key`.
- Must be append-only.

## Suggested Constraints And Indexes

```sql
CREATE INDEX idx_prospects_status ON prospects(status);
CREATE INDEX idx_prospects_follow_up_due_at ON prospects(follow_up_due_at);
CREATE INDEX idx_interactions_prospect_id ON interactions(prospect_id);
CREATE INDEX idx_interactions_type_created_at ON interactions(interaction_type, created_at);
CREATE INDEX idx_refinement_history_parameter_key ON refinement_history(parameter_key);
CREATE INDEX idx_refinement_history_version ON refinement_history(version);
```

Future implementation should add database-level foreign keys where SQLite foreign key enforcement is enabled.
