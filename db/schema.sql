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
    updated_at TEXT NOT NULL,
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
    created_at TEXT NOT NULL,
    CHECK (
        interaction_type IN (
            'outreach_draft',
            'follow_up_draft',
            'reply_logged',
            'meeting_confirmed',
            'note'
        )
    ),
    CHECK (direction IN ('outbound_draft', 'inbound_logged'))
);

CREATE TABLE IF NOT EXISTS core_intent (
    id INTEGER PRIMARY KEY,
    rule_key TEXT NOT NULL UNIQUE,
    rule_value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS content_posts (
    id INTEGER PRIMARY KEY,
    draft_text TEXT NOT NULL,
    image_source TEXT NOT NULL DEFAULT 'none',
    image_path TEXT,
    inspiration_source_notes TEXT,
    status TEXT NOT NULL DEFAULT 'drafted',
    engagement_metric REAL,
    created_at TEXT NOT NULL,
    CHECK (image_source IN ('user_upload', 'generated', 'none')),
    CHECK (status IN ('drafted', 'approved', 'posted', 'rejected'))
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
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prospects_status ON prospects(status);
CREATE INDEX IF NOT EXISTS idx_prospects_last_touch_date ON prospects(last_touch_date);
CREATE INDEX IF NOT EXISTS idx_interactions_prospect_id ON interactions(prospect_id);
CREATE INDEX IF NOT EXISTS idx_interactions_interaction_type ON interactions(interaction_type);
CREATE INDEX IF NOT EXISTS idx_refinable_parameters_agent_key
    ON refinable_parameters(agent_name, parameter_key);
CREATE INDEX IF NOT EXISTS idx_refinement_history_agent_name ON refinement_history(agent_name);
CREATE INDEX IF NOT EXISTS idx_refinement_history_version ON refinement_history(version);
CREATE INDEX IF NOT EXISTS idx_content_posts_status ON content_posts(status);
CREATE INDEX IF NOT EXISTS idx_calendar_blocks_prospect_id ON calendar_blocks(prospect_id);
