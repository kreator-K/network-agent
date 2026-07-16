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
    idempotency_key TEXT UNIQUE,
    provider TEXT,
    provider_event_id TEXT,
    provider_event_url TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('confirmed', 'calendar_created', 'calendar_failed')),
    CHECK (sync_status IN ('pending', 'created', 'failed'))
);

CREATE TABLE IF NOT EXISTS briefing_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    briefing_time TEXT NOT NULL DEFAULT '08:30',
    timezone TEXT NOT NULL DEFAULT 'America/New_York',
    dry_run INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    CHECK (enabled IN (0, 1)), CHECK (dry_run IN (0, 1))
);

CREATE TABLE IF NOT EXISTS briefing_runs (
    id INTEGER PRIMARY KEY,
    run_key TEXT NOT NULL UNIQUE,
    run_type TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    timezone TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    sources_considered_count INTEGER NOT NULL DEFAULT 0,
    sources_succeeded_count INTEGER NOT NULL DEFAULT 0,
    sources_failed_count INTEGER NOT NULL DEFAULT 0,
    signals_fetched_count INTEGER NOT NULL DEFAULT 0,
    new_signals_count INTEGER NOT NULL DEFAULT 0,
    duplicate_signals_count INTEGER NOT NULL DEFAULT 0,
    signals_scored_count INTEGER NOT NULL DEFAULT 0,
    eligible_signals_count INTEGER NOT NULL DEFAULT 0,
    opportunities_created_count INTEGER NOT NULL DEFAULT 0,
    packages_prepared_count INTEGER NOT NULL DEFAULT 0,
    followups_due_count INTEGER NOT NULL DEFAULT 0,
    meetings_count INTEGER NOT NULL DEFAULT 0,
    telegram_delivery_status TEXT NOT NULL DEFAULT 'not_requested',
    telegram_message_ids_json TEXT NOT NULL DEFAULT '[]',
    error_summary TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    CHECK (status IN ('started','completed','completed_with_warnings','no_content','failed','skipped','delivery_failed'))
);

CREATE TABLE IF NOT EXISTS prospect_candidates (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    role_title TEXT,
    company TEXT,
    location TEXT,
    public_profile_url TEXT,
    professional_summary TEXT,
    source_signal_ids_json TEXT NOT NULL,
    source_references_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    relevant_topics_json TEXT NOT NULL DEFAULT '[]',
    recommended_ask_type TEXT NOT NULL,
    recommended_rationale TEXT NOT NULL,
    profile_version INTEGER NOT NULL REFERENCES personal_brand_profile(version),
    scoring_config_version INTEGER NOT NULL REFERENCES signal_scoring_config(version),
    score_json TEXT NOT NULL,
    total_score REAL NOT NULL,
    confidence REAL NOT NULL,
    source_credibility_score REAL NOT NULL,
    duplicate_candidate_id INTEGER REFERENCES prospect_candidates(id) ON DELETE SET NULL,
    matching_prospect_id INTEGER REFERENCES prospects(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'discovered',
    decision_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (status IN ('discovered','shortlisted','saved','approved','added_to_crm','skipped','rejected','duplicate','expired','failed_validation')),
    CHECK (total_score >= 0 AND total_score <= 100), CHECK (confidence >= 0 AND confidence <= 1),
    CHECK (source_credibility_score >= 0 AND source_credibility_score <= 100)
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
CREATE INDEX IF NOT EXISTS idx_briefing_runs_scheduled_for ON briefing_runs(scheduled_for DESC);
CREATE INDEX IF NOT EXISTS idx_prospect_candidates_status_score ON prospect_candidates(status, total_score DESC);
CREATE INDEX IF NOT EXISTS idx_calendar_blocks_prospect_id ON calendar_blocks(prospect_id);

CREATE TABLE IF NOT EXISTS linkedin_oauth_states (
    id INTEGER PRIMARY KEY,
    state_hash TEXT NOT NULL UNIQUE,
    telegram_user_id TEXT NOT NULL,
    telegram_chat_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT,
    requested_scopes TEXT NOT NULL DEFAULT 'openid profile w_member_social',
    redirect_uri TEXT NOT NULL DEFAULT '',
    correlation_id TEXT,
    failure_stage TEXT,
    error_summary TEXT,
    granted_scopes TEXT,
    missing_scopes TEXT,
    unexpected_scopes TEXT,
    raw_scope_type TEXT,
    scope_field_present INTEGER,
    introspection_attempted INTEGER NOT NULL DEFAULT 0,
    CHECK (status IN ('pending', 'consumed', 'expired', 'cancelled', 'failed'))
);

CREATE TABLE IF NOT EXISTS linkedin_credentials (
    id INTEGER PRIMARY KEY,
    encrypted_access_token BLOB NOT NULL,
    encrypted_refresh_token BLOB,
    oidc_subject TEXT,
    granted_scopes TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    access_token_expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    revoked_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    member_display_name TEXT,
    CHECK (status IN ('active', 'expired', 'revoked', 'invalid', 'reauthorization_required'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_linkedin_credentials_active
ON linkedin_credentials(status) WHERE status = 'active';
