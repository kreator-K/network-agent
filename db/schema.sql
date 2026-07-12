PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS prospects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    profile_url TEXT,
    location TEXT,
    role_title TEXT,
    company TEXT,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'not_contacted',
    last_touch_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        status IN (
            'not_contacted',
            'outreach_drafted',
            'connection_sent',
            'connected',
            'meeting_confirmed',
            'closed'
        )
    )
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY,
    prospect_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL,
    content TEXT,
    direction TEXT NOT NULL,
    status TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        interaction_type IN (
            'outreach_draft',
            'follow_up_draft',
            'linkedin_connection_request',
            'reply_logged',
            'meeting_confirmed',
            'note'
        )
    ),
    CHECK (direction IN ('outbound_draft', 'inbound_logged')),
    CHECK (status IS NULL OR status IN ('drafted', 'sent_manually', 'discarded'))
);

CREATE TABLE IF NOT EXISTS core_intent (
    id INTEGER PRIMARY KEY,
    rule_key TEXT NOT NULL UNIQUE,
    rule_value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personal_brand_profile (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    CHECK (version >= 1),
    CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS signal_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    enabled INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    last_fetched_at TEXT,
    etag TEXT,
    last_modified TEXT,
    last_fetch_status TEXT,
    last_error TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_type IN ('rss', 'atom', 'auto_feed')),
    CHECK (approval_status IN ('pending', 'approved', 'rejected')),
    CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES signal_sources(id) ON DELETE CASCADE,
    external_id TEXT,
    canonical_url TEXT,
    title TEXT,
    summary TEXT,
    author TEXT,
    published_at TEXT,
    updated_at_source TEXT,
    fetched_at TEXT NOT NULL,
    content_hash TEXT,
    dedupe_key TEXT,
    duplicate_of_id INTEGER REFERENCES signals(id) ON DELETE SET NULL,
    raw_payload_json TEXT NOT NULL,
    normalized_json TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    profile_version INTEGER REFERENCES personal_brand_profile(version),
    scoring_config_version INTEGER REFERENCES signal_scoring_config(version),
    score_json TEXT,
    total_score REAL,
    scoring_confidence REAL,
    scoring_mode TEXT,
    scored_at TEXT,
    eligibility_status TEXT NOT NULL DEFAULT 'pending',
    eligibility_reasons_json TEXT,
    CHECK (status IN ('fetched', 'normalized', 'scored', 'ineligible', 'duplicate', 'failed')),
    CHECK (eligibility_status IN ('pending', 'eligible', 'ineligible', 'scoring_failed')),
    CHECK (total_score IS NULL OR (total_score >= 0 AND total_score <= 100)),
    CHECK (scoring_confidence IS NULL OR (scoring_confidence >= 0 AND scoring_confidence <= 1))
);

CREATE TABLE IF NOT EXISTS signal_scoring_config (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    CHECK (version >= 1),
    CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS content_opportunities (
    id INTEGER PRIMARY KEY,
    primary_signal_id INTEGER NOT NULL REFERENCES signals(id) ON DELETE RESTRICT,
    supporting_signal_ids_json TEXT NOT NULL DEFAULT '[]',
    profile_version INTEGER NOT NULL REFERENCES personal_brand_profile(version),
    scoring_config_version INTEGER NOT NULL REFERENCES signal_scoring_config(version),
    headline TEXT NOT NULL,
    suggested_angle TEXT NOT NULL,
    rationale TEXT NOT NULL,
    target_audience TEXT NOT NULL,
    recommended_format TEXT NOT NULL,
    suggested_treatment TEXT NOT NULL,
    humor_suitability REAL NOT NULL,
    factual_risk REAL NOT NULL,
    generic_commentary_risk REAL NOT NULL,
    score_json TEXT NOT NULL,
    total_score REAL NOT NULL,
    confidence REAL NOT NULL,
    source_references_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    decision_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (status IN ('candidate', 'saved', 'selected', 'dismissed', 'expired')),
    CHECK (humor_suitability >= 0 AND humor_suitability <= 100),
    CHECK (factual_risk >= 0 AND factual_risk <= 100),
    CHECK (generic_commentary_risk >= 0 AND generic_commentary_risk <= 100),
    CHECK (total_score >= 0 AND total_score <= 100),
    CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE TABLE IF NOT EXISTS content_preference_feedback (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    feedback_type TEXT NOT NULL,
    note TEXT,
    source TEXT NOT NULL DEFAULT 'telegram',
    created_at TEXT NOT NULL,
    CHECK (target_type IN ('signal', 'opportunity')),
    CHECK (feedback_type IN ('more_like_this', 'less_like_this', 'save', 'dismiss', 'not_relevant', 'too_generic', 'too_risky', 'good_angle', 'wrong_audience'))
);

CREATE TABLE IF NOT EXISTS refinable_parameters (
    id INTEGER PRIMARY KEY,
    agent_name TEXT NOT NULL,
    parameter_key TEXT NOT NULL,
    parameter_value TEXT NOT NULL,
    version INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (agent_name, parameter_key, version),
    CHECK (agent_name IN ('outreach_draft_agent', 'content_inspiration_agent')),
    CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS refinement_history (
    id INTEGER PRIMARY KEY,
    agent_name TEXT NOT NULL,
    version INTEGER NOT NULL,
    what_changed TEXT NOT NULL,
    why TEXT NOT NULL,
    metric_before REAL,
    metric_after REAL,
    diff_against_v1 TEXT NOT NULL,
    core_intent_check_passed INTEGER NOT NULL,
    accepted INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (agent_name IN ('outreach_draft_agent', 'content_inspiration_agent')),
    CHECK (core_intent_check_passed IN (0, 1)),
    CHECK (accepted IN (0, 1))
);

CREATE TABLE IF NOT EXISTS refinement_outcomes (
    id INTEGER PRIMARY KEY,
    agent_name TEXT NOT NULL,
    parameter_version INTEGER NOT NULL,
    metric_value REAL NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    related_interaction_id INTEGER,
    outcome TEXT,
    notes TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    CHECK (agent_name IN ('outreach_draft_agent', 'content_inspiration_agent')),
    CHECK (target_type IS NULL OR target_type IN ('outreach', 'content'))
);

CREATE TABLE IF NOT EXISTS refinement_loop_constraints (
    constraint_key TEXT PRIMARY KEY,
    constraint_value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refinement_loop_runs (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    loop_type TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    outcomes_considered_count INTEGER NOT NULL DEFAULT 0,
    proposals_created_count INTEGER NOT NULL DEFAULT 0,
    proposals_applied_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata_json TEXT,
    CHECK (status IN ('completed', 'failed', 'paused', 'no_op')),
    CHECK (mode IN ('report_only', 'assisted'))
);

CREATE TABLE IF NOT EXISTS refinement_proposals (
    id INTEGER PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    target_area TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    current_value TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT,
    risk_level TEXT NOT NULL,
    checker_status TEXT NOT NULL,
    core_intent_check_status TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    metadata_json TEXT,
    CHECK (
        status IN (
            'pending_approval',
            'applied',
            'rejected',
            'failed_validation',
            'expired'
        )
    )
);

CREATE TABLE IF NOT EXISTS content_posts (
    id INTEGER PRIMARY KEY,
    topic TEXT,
    draft_text TEXT NOT NULL,
    image_source TEXT NOT NULL DEFAULT 'none',
    image_path TEXT,
    inspiration_source_notes TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    engagement_metric REAL,
    opportunity_id INTEGER REFERENCES content_opportunities(id) ON DELETE SET NULL,
    profile_version INTEGER REFERENCES personal_brand_profile(version),
    scoring_config_version INTEGER REFERENCES signal_scoring_config(version),
    package_version INTEGER NOT NULL DEFAULT 1,
    package_json TEXT,
    source_references_json TEXT,
    factual_claims_json TEXT,
    alternative_hooks_json TEXT,
    personal_angle_json TEXT,
    risk_assessment_json TEXT,
    suggested_first_comment TEXT,
    suggested_hashtags_json TEXT,
    image_brief_json TEXT,
    image_alt_text TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (image_source IN ('uploaded', 'generated', 'none')),
    CHECK (status IN ('draft', 'saved', 'needs_confirmation', 'approved_for_later_posting', 'rejected', 'discarded')),
    CHECK (package_version >= 1)
);

CREATE TABLE IF NOT EXISTS calendar_blocks (
    id INTEGER PRIMARY KEY,
    prospect_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    scheduled_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    timezone TEXT,
    notes TEXT,
    external_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_at TEXT NOT NULL,
    CHECK (status IN ('confirmed', 'calendar_created', 'calendar_failed'))
);

CREATE INDEX IF NOT EXISTS idx_prospects_status ON prospects(status);
CREATE INDEX IF NOT EXISTS idx_prospects_last_touch_date ON prospects(last_touch_date);
CREATE INDEX IF NOT EXISTS idx_interactions_prospect_id ON interactions(prospect_id);
CREATE INDEX IF NOT EXISTS idx_interactions_interaction_type ON interactions(interaction_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_brand_profile_one_active
    ON personal_brand_profile(is_active)
    WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_personal_brand_profile_version
    ON personal_brand_profile(version);
CREATE INDEX IF NOT EXISTS idx_signal_sources_approval_enabled
    ON signal_sources(approval_status, enabled);
CREATE INDEX IF NOT EXISTS idx_signals_source_id ON signals(source_id);
CREATE INDEX IF NOT EXISTS idx_signals_source_external_id ON signals(source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_signals_canonical_url ON signals(canonical_url);
CREATE INDEX IF NOT EXISTS idx_signals_content_hash ON signals(content_hash);
CREATE INDEX IF NOT EXISTS idx_signals_dedupe_key ON signals(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_signals_published_at ON signals(published_at);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_signal_scoring_config
ON signal_scoring_config(is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_content_opportunities_status_score
ON content_opportunities(status, total_score DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_opportunity_per_signal_config
ON content_opportunities(primary_signal_id, profile_version, scoring_config_version)
WHERE status IN ('candidate', 'saved', 'selected');
CREATE INDEX IF NOT EXISTS idx_content_preference_feedback_target
ON content_preference_feedback(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_refinable_parameters_agent_key
    ON refinable_parameters(agent_name, parameter_key);
CREATE INDEX IF NOT EXISTS idx_refinement_history_agent_name ON refinement_history(agent_name);
CREATE INDEX IF NOT EXISTS idx_refinement_history_version ON refinement_history(version);
CREATE INDEX IF NOT EXISTS idx_refinement_outcomes_agent_version
    ON refinement_outcomes(agent_name, parameter_version);
CREATE INDEX IF NOT EXISTS idx_refinement_loop_runs_run_id
    ON refinement_loop_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_refinement_loop_runs_status
    ON refinement_loop_runs(status);
CREATE INDEX IF NOT EXISTS idx_refinement_proposals_proposal_id
    ON refinement_proposals(proposal_id);
CREATE INDEX IF NOT EXISTS idx_refinement_proposals_run_id
    ON refinement_proposals(run_id);
CREATE INDEX IF NOT EXISTS idx_refinement_proposals_status
    ON refinement_proposals(status);
CREATE INDEX IF NOT EXISTS idx_content_posts_status ON content_posts(status);
CREATE INDEX IF NOT EXISTS idx_calendar_blocks_prospect_id ON calendar_blocks(prospect_id);
