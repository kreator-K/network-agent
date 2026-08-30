"""SQLite database helpers for the network-agent data layer."""

import json
import hashlib
import re
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from db.models import PersonalBrandProfileData


DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_CORE_INTENT_PATH = Path(__file__).resolve().parent.parent / "config" / "core_intent.json"
DEFAULT_PERSONAL_BRAND_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "personal_brand_profile.json"
)
DEFAULT_SIGNAL_SCORING_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "signal_scoring_config.json"
)


def connect(database_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection and enable foreign key enforcement."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _migrate_research_resource_columns(connection: sqlite3.Connection) -> None:
    columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(research_resources)")}
    for name in ("source_text", "research_brief_json"):
        if name not in columns:
            connection.execute(f"ALTER TABLE research_resources ADD COLUMN {name} TEXT")


def initialize_database(
    database_path: str | Path,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    core_intent_path: str | Path = DEFAULT_CORE_INTENT_PATH,
    personal_brand_profile_path: str | Path = DEFAULT_PERSONAL_BRAND_PROFILE_PATH,
    signal_scoring_config_path: str | Path = DEFAULT_SIGNAL_SCORING_CONFIG_PATH,
) -> None:
    """Initialize tables and seed durable human-controlled configuration."""
    schema = Path(schema_path).read_text(encoding="utf-8")
    with connect(database_path) as connection:
        _prepare_linkedin_publish_legacy_migration(connection)
        connection.executescript(schema)
        _migrate_research_resource_columns(connection)
        _migrate_interactions_connection_request_type(connection)
        _migrate_interactions_lifecycle_columns(connection)
        _migrate_content_posts_uploaded_image_source(connection)
        _migrate_content_posts_lifecycle_columns(connection)
        _migrate_content_package_columns(connection)
        _repair_content_post_versions_foreign_key(connection)
        _seed_content_post_versions(connection)
        _migrate_refinement_outcomes_explicit_columns(connection)
        _migrate_calendar_block_lifecycle_columns(connection)
        _migrate_signal_scoring_columns(connection)
        _repair_content_opportunities_signal_foreign_key(connection)
        _migrate_linkedin_oauth_columns(connection)
        _migrate_linkedin_publish_columns(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_score ON signals(total_score DESC)"
        )
        seed_refinement_loop_constraints(connection)
        seed_core_intent(connection, core_intent_path)
        seed_personal_brand_profile(connection, personal_brand_profile_path)
        seed_signal_scoring_config(connection, signal_scoring_config_path)
        connection.execute(
            "INSERT OR IGNORE INTO briefing_settings (id, updated_at) VALUES (1, ?)",
            (_utc_now(),),
        )
        connection.execute("PRAGMA user_version = 12")


def canonical_signal_scoring_config_json(config: dict[str, Any]) -> str:
    """Serialize a validated scoring configuration deterministically."""
    _validate_signal_scoring_config(config)
    return json.dumps(config, sort_keys=True, separators=(",", ":"))


def signal_scoring_config_hash(config_json: str) -> str:
    """Return a stable hash for an immutable scoring configuration."""
    return hashlib.sha256(config_json.encode("utf-8")).hexdigest()


def seed_signal_scoring_config(
    connection: sqlite3.Connection,
    config_path: str | Path = DEFAULT_SIGNAL_SCORING_CONFIG_PATH,
) -> bool:
    """Seed conservative immutable scoring version one only on an empty table."""
    exists = connection.execute("SELECT 1 FROM signal_scoring_config LIMIT 1").fetchone()
    if exists is not None:
        return False
    raw_config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    config_json = canonical_signal_scoring_config_json(raw_config)
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO signal_scoring_config (
            version, config_json, config_hash, is_active, created_at, activated_at
        ) VALUES (1, ?, ?, 1, ?, ?)
        """,
        (config_json, signal_scoring_config_hash(config_json), now, now),
    )
    return True


def get_active_signal_scoring_config_row(connection: sqlite3.Connection) -> sqlite3.Row:
    """Return the one active scoring configuration or raise a useful error."""
    row = connection.execute(
        "SELECT * FROM signal_scoring_config WHERE is_active = 1"
    ).fetchone()
    if row is None:
        raise ValueError("No active signal scoring configuration exists.")
    return row


def _validate_signal_scoring_config(config: dict[str, Any]) -> None:
    required = {
        "formula_version", "weights", "minimum_final_score", "minimum_credibility_score",
        "maximum_factual_risk", "maximum_generic_commentary_risk",
        "freshness_half_life_days", "maximum_age_days", "topic_saturation_limit",
        "maximum_signals_per_run", "maximum_model_assisted_signals_per_run",
        "maximum_opportunities_per_run", "model_assisted_scoring_enabled",
        "maximum_retry_attempts",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"Signal scoring configuration is missing: {', '.join(sorted(missing))}.")
    weights = config["weights"]
    if not isinstance(weights, dict) or not weights:
        raise ValueError("Signal scoring configuration weights must be a non-empty object.")
    if any(not isinstance(value, (int, float)) or value < 0 or value > 1 for value in weights.values()):
        raise ValueError("Signal scoring weights must be between 0 and 1.")
    if sum(weights.values()) > 1.00001:
        raise ValueError("Signal scoring weights cannot total more than 1.")
    for key in (
        "minimum_final_score", "minimum_credibility_score", "maximum_factual_risk",
        "maximum_generic_commentary_risk",
    ):
        value = config[key]
        if not isinstance(value, (int, float)) or value < 0 or value > 100:
            raise ValueError(f"Signal scoring configuration {key} must be between 0 and 100.")
    for key in (
        "freshness_half_life_days", "maximum_age_days", "topic_saturation_limit",
        "maximum_signals_per_run", "maximum_model_assisted_signals_per_run",
        "maximum_opportunities_per_run", "maximum_retry_attempts",
    ):
        if not isinstance(config[key], int) or config[key] < 0:
            raise ValueError(f"Signal scoring configuration {key} must be a non-negative integer.")


def seed_core_intent(
    connection: sqlite3.Connection,
    core_intent_path: str | Path = DEFAULT_CORE_INTENT_PATH,
) -> None:
    """Upsert core intent rules from `config/core_intent.json` into SQLite."""
    rules = _load_core_intent_rules(core_intent_path)
    updated_at = _utc_now()
    connection.executemany(
        """
        INSERT INTO core_intent (rule_key, rule_value, description, updated_at)
        VALUES (:rule_key, :rule_value, :description, :updated_at)
        ON CONFLICT(rule_key) DO UPDATE SET
            rule_value = excluded.rule_value,
            description = excluded.description,
            updated_at = excluded.updated_at
        """,
        (
            {
                "rule_key": rule["rule_key"],
                "rule_value": rule["rule_value"],
                "description": rule.get("description"),
                "updated_at": updated_at,
            }
            for rule in rules
        ),
    )


def seed_personal_brand_profile(
    connection: sqlite3.Connection,
    profile_path: str | Path = DEFAULT_PERSONAL_BRAND_PROFILE_PATH,
) -> bool:
    """Create version one from seed JSON only when no profile exists.

    The seed is an initialization input, not live agent configuration. Existing
    SQLite profile versions are never overwritten by later seed-file edits.
    """
    if personal_brand_profile_exists(connection):
        return False
    path = Path(profile_path)
    if not path.exists():
        return False
    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
        profile = PersonalBrandProfileData.model_validate(raw_data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Personal-brand profile seed is invalid: {path}") from exc
    create_personal_brand_profile_version(connection, profile, activate=True)
    return True


def canonical_personal_brand_profile_json(profile: PersonalBrandProfileData) -> str:
    """Serialize typed profile content deterministically before hashing."""
    return json.dumps(
        profile.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


def personal_brand_profile_hash(profile_json: str) -> str:
    """Return the stable hash for canonical personal-brand profile JSON."""
    return hashlib.sha256(profile_json.encode("utf-8")).hexdigest()


def personal_brand_profile_exists(connection: sqlite3.Connection) -> bool:
    """Return whether any stored profile version exists."""
    row = connection.execute(
        "SELECT 1 FROM personal_brand_profile LIMIT 1"
    ).fetchone()
    return row is not None


def next_personal_brand_profile_version(connection: sqlite3.Connection) -> int:
    """Return the next immutable personal-brand profile version number."""
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM personal_brand_profile"
    ).fetchone()
    return int(row["next_version"])


def create_personal_brand_profile_version(
    connection: sqlite3.Connection,
    profile: PersonalBrandProfileData,
    activate: bool = True,
) -> sqlite3.Row:
    """Append a typed profile version and optionally activate it atomically."""
    profile_json = canonical_personal_brand_profile_json(profile)
    profile_hash = personal_brand_profile_hash(profile_json)
    now = _utc_now()
    connection.execute("SAVEPOINT personal_brand_version")
    try:
        version = next_personal_brand_profile_version(connection)
        if activate:
            connection.execute(
                "UPDATE personal_brand_profile SET is_active = 0 WHERE is_active = 1"
            )
        cursor = connection.execute(
            """
            INSERT INTO personal_brand_profile (
                version, schema_version, profile_json, profile_hash,
                is_active, created_at, activated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version,
                profile.schema_version,
                profile_json,
                profile_hash,
                int(activate),
                now,
                now if activate else None,
            ),
        )
        row = connection.execute(
            "SELECT * FROM personal_brand_profile WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        if row is None:
            raise ValueError("SQLite did not return the created personal-brand profile.")
        connection.execute("RELEASE SAVEPOINT personal_brand_version")
        return row
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT personal_brand_version")
        connection.execute("RELEASE SAVEPOINT personal_brand_version")
        raise


def get_active_personal_brand_profile_row(
    connection: sqlite3.Connection,
) -> sqlite3.Row | None:
    """Return the active profile row, if profile setup has occurred."""
    return connection.execute(
        "SELECT * FROM personal_brand_profile WHERE is_active = 1 LIMIT 1"
    ).fetchone()


def get_personal_brand_profile_by_id(
    connection: sqlite3.Connection,
    profile_id: int,
) -> sqlite3.Row | None:
    """Return a profile row by stable database identifier."""
    return connection.execute(
        "SELECT * FROM personal_brand_profile WHERE id = ?",
        (profile_id,),
    ).fetchone()


def get_personal_brand_profile_by_version(
    connection: sqlite3.Connection,
    version: int,
) -> sqlite3.Row | None:
    """Return a profile row by immutable version number."""
    return connection.execute(
        "SELECT * FROM personal_brand_profile WHERE version = ?",
        (version,),
    ).fetchone()


def list_personal_brand_profile_rows(
    connection: sqlite3.Connection,
    limit: int = 10,
) -> list[sqlite3.Row]:
    """Return newest profile versions first for concise operator review."""
    return list(
        connection.execute(
            "SELECT * FROM personal_brand_profile ORDER BY version DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def activate_personal_brand_profile_version(
    connection: sqlite3.Connection,
    version: int,
) -> sqlite3.Row | None:
    """Activate an existing profile version without changing its JSON content."""
    row = get_personal_brand_profile_by_version(connection, version)
    if row is None:
        return None
    now = _utc_now()
    connection.execute("SAVEPOINT personal_brand_activation")
    try:
        connection.execute(
            "UPDATE personal_brand_profile SET is_active = 0 WHERE is_active = 1"
        )
        connection.execute(
            """
            UPDATE personal_brand_profile
            SET is_active = 1, activated_at = ?
            WHERE version = ?
            """,
            (now, version),
        )
        active = get_personal_brand_profile_by_version(connection, version)
        connection.execute("RELEASE SAVEPOINT personal_brand_activation")
        return active
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT personal_brand_activation")
        connection.execute("RELEASE SAVEPOINT personal_brand_activation")
        raise


def verify_personal_brand_profile_hash(row: sqlite3.Row) -> bool:
    """Validate stored profile JSON and compare its canonical content hash."""
    try:
        profile = PersonalBrandProfileData.model_validate(json.loads(row["profile_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if profile.schema_version != row["schema_version"]:
        return False
    # Stored versions are immutable. Hash their exact canonical payload so a
    # later schema addition with optional defaults does not invalidate history.
    return personal_brand_profile_hash(row["profile_json"]) == row["profile_hash"]


def seed_refinement_loop_constraints(connection: sqlite3.Connection) -> None:
    """Seed durable Phase 6A loop constraints without overwriting edits."""
    now = _utc_now()
    constraints = [
        (
            "no_linkedin_auto_send",
            "true",
            "The loop must never send LinkedIn connection requests, DMs, or InMail.",
        ),
        (
            "no_linkedin_scraping",
            "true",
            "The loop must never scrape or crawl LinkedIn.",
        ),
        (
            "no_linkedin_auto_publish",
            "true",
            "The loop must never publish LinkedIn posts automatically.",
        ),
        (
            "human_approval_required",
            "true",
            "Any future parameter change requires explicit human approval.",
        ),
        (
            "loop_paused",
            "false",
            "Pause/kill switch for refinement proposal generation.",
        ),
        (
            "mode",
            "report_only",
            "Use report_only for Phase 6A reports or assisted for human-approved Phase 6B applies.",
        ),
        (
            "max_apply_per_run",
            "1",
            "Maximum human-approved refinements that may be applied from one run.",
        ),
        (
            "max_proposals_per_run",
            "3",
            "Maximum checker-approved proposals to show in one run.",
        ),
    ]
    connection.executemany(
        """
        INSERT INTO refinement_loop_constraints (
            constraint_key,
            constraint_value,
            description,
            updated_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(constraint_key) DO NOTHING
        """,
        (
            (key, value, description, now)
            for key, value, description in constraints
        ),
    )


def _migrate_calendar_block_lifecycle_columns(
    connection: sqlite3.Connection,
) -> None:
    """Add calendar sync lifecycle metadata to existing databases."""
    columns = _column_names(connection, "calendar_blocks")
    if columns and "status" not in columns:
        connection.execute(
            "ALTER TABLE calendar_blocks ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'"
        )
    additions = {
        "idempotency_key": "TEXT",
        "provider": "TEXT",
        "provider_event_id": "TEXT",
        "provider_event_url": "TEXT",
        "sync_status": "TEXT NOT NULL DEFAULT 'pending'",
        "last_error": "TEXT",
        "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    columns = _column_names(connection, "calendar_blocks")
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE calendar_blocks ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_blocks_idempotency "
        "ON calendar_blocks(idempotency_key) WHERE idempotency_key IS NOT NULL"
    )


def _migrate_interactions_connection_request_type(
    connection: sqlite3.Connection,
) -> None:
    """Allow manual LinkedIn connection-request tracking in existing DBs."""
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'interactions'
        """
    ).fetchone()
    if row is None or "linkedin_connection_request" in str(row["sql"]):
        return

    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_interactions_prospect_id;
        DROP INDEX IF EXISTS idx_interactions_interaction_type;

        ALTER TABLE interactions RENAME TO interactions_legacy;

        CREATE TABLE interactions (
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
                    'linkedin_connection_request',
                    'reply_logged',
                    'meeting_confirmed',
                    'note'
                )
            ),
            CHECK (direction IN ('outbound_draft', 'inbound_logged'))
        );

        INSERT INTO interactions (
            id,
            prospect_id,
            interaction_type,
            content,
            direction,
            created_at
        )
        SELECT
            id,
            prospect_id,
            interaction_type,
            content,
            direction,
            created_at
        FROM interactions_legacy;

        DROP TABLE interactions_legacy;

        CREATE INDEX IF NOT EXISTS idx_interactions_prospect_id
            ON interactions(prospect_id);
        CREATE INDEX IF NOT EXISTS idx_interactions_interaction_type
            ON interactions(interaction_type);
        """
    )


def _migrate_interactions_lifecycle_columns(connection: sqlite3.Connection) -> None:
    """Add draft lifecycle metadata to existing interaction tables."""
    columns = _column_names(connection, "interactions")
    if not columns:
        return
    if "status" not in columns:
        connection.execute("ALTER TABLE interactions ADD COLUMN status TEXT")
    if "source" not in columns:
        connection.execute("ALTER TABLE interactions ADD COLUMN source TEXT")
    if "updated_at" not in columns:
        connection.execute("ALTER TABLE interactions ADD COLUMN updated_at TEXT")
        connection.execute(
            """
            UPDATE interactions
            SET updated_at = created_at
            WHERE updated_at IS NULL
            """
        )


def _migrate_content_posts_uploaded_image_source(
    connection: sqlite3.Connection,
) -> None:
    """Rename legacy `user_upload` image source to `uploaded` in existing DBs."""
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'content_posts'
        """
    ).fetchone()
    if row is None or "'user_upload'" not in str(row["sql"]):
        return

    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_content_posts_status;

        PRAGMA legacy_alter_table = ON;
        ALTER TABLE content_posts RENAME TO content_posts_legacy;

        CREATE TABLE content_posts (
            id INTEGER PRIMARY KEY,
            draft_text TEXT NOT NULL,
            image_source TEXT NOT NULL DEFAULT 'none',
            image_path TEXT,
            inspiration_source_notes TEXT,
            status TEXT NOT NULL DEFAULT 'drafted',
            engagement_metric REAL,
            created_at TEXT NOT NULL,
            CHECK (image_source IN ('uploaded', 'generated', 'none')),
            CHECK (status IN ('drafted', 'approved', 'posted', 'rejected'))
        );

        INSERT INTO content_posts (
            id,
            draft_text,
            image_source,
            image_path,
            inspiration_source_notes,
            status,
            engagement_metric,
            created_at
        )
        SELECT
            id,
            draft_text,
            CASE
                WHEN image_source = 'user_upload' THEN 'uploaded'
                ELSE image_source
            END,
            image_path,
            inspiration_source_notes,
            status,
            engagement_metric,
            created_at
        FROM content_posts_legacy;

        DROP TABLE content_posts_legacy;
        PRAGMA legacy_alter_table = OFF;

        CREATE INDEX IF NOT EXISTS idx_content_posts_status
            ON content_posts(status);
        """
    )


def _migrate_content_posts_lifecycle_columns(connection: sqlite3.Connection) -> None:
    """Move content posts to the safe internal draft lifecycle statuses."""
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'content_posts'
        """
    ).fetchone()
    if row is None:
        return
    sql = str(row["sql"])
    columns = _column_names(connection, "content_posts")
    needs_rebuild = (
        "topic" not in columns
        or "updated_at" not in columns
        or "'drafted'" in sql
        or "'posted'" in sql
        or ("'rejected'" in sql and "package_version" not in columns)
    )
    if not needs_rebuild:
        return

    select_topic = "topic" if "topic" in columns else "NULL"
    select_updated_at = "updated_at" if "updated_at" in columns else "created_at"
    connection.executescript(
        f"""
        DROP INDEX IF EXISTS idx_content_posts_status;

        PRAGMA legacy_alter_table = ON;
        ALTER TABLE content_posts RENAME TO content_posts_legacy;

        CREATE TABLE content_posts (
            id INTEGER PRIMARY KEY,
            topic TEXT,
            draft_text TEXT NOT NULL,
            image_source TEXT NOT NULL DEFAULT 'none',
            image_path TEXT,
            inspiration_source_notes TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            engagement_metric REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (image_source IN ('uploaded', 'generated', 'none')),
            CHECK (
                status IN (
                    'draft',
                    'saved',
                    'approved_for_later_posting',
                    'discarded'
                )
            )
        );

        INSERT INTO content_posts (
            id,
            topic,
            draft_text,
            image_source,
            image_path,
            inspiration_source_notes,
            status,
            engagement_metric,
            created_at,
            updated_at
        )
        SELECT
            id,
            {select_topic},
            draft_text,
            image_source,
            image_path,
            inspiration_source_notes,
            CASE
                WHEN status = 'drafted' THEN 'draft'
                WHEN status = 'approved' THEN 'approved_for_later_posting'
                WHEN status = 'rejected' THEN 'discarded'
                ELSE status
            END,
            engagement_metric,
            created_at,
            {select_updated_at}
        FROM content_posts_legacy
        WHERE status != 'posted';

        DROP TABLE content_posts_legacy;
        PRAGMA legacy_alter_table = OFF;

        CREATE INDEX IF NOT EXISTS idx_content_posts_status
            ON content_posts(status);
        """
    )


def _migrate_content_package_columns(connection: sqlite3.Connection) -> None:
    """Add nullable Phase 8D package fields without altering prior drafts."""
    columns = _column_names(connection, "content_posts")
    additions = {
        "opportunity_id": "INTEGER",
        "profile_version": "INTEGER",
        "scoring_config_version": "INTEGER",
        "package_version": "INTEGER NOT NULL DEFAULT 1",
        "package_json": "TEXT",
        "source_references_json": "TEXT",
        "factual_claims_json": "TEXT",
        "alternative_hooks_json": "TEXT",
        "personal_angle_json": "TEXT",
        "risk_assessment_json": "TEXT",
        "suggested_first_comment": "TEXT",
        "suggested_hashtags_json": "TEXT",
        "image_brief_json": "TEXT",
        "image_alt_text": "TEXT",
        "approved_at": "TEXT",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE content_posts ADD COLUMN {column_name} {column_type}"
            )


def _seed_content_post_versions(connection: sqlite3.Connection) -> None:
    """Backfill one immutable baseline for package rows created before v12."""
    if not _column_names(connection, "content_post_versions"):
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO content_post_versions (
            content_post_id,
            package_version,
            draft_text,
            package_json,
            revision_type,
            revision_notes,
            model_mode,
            fallback_used,
            created_at
        )
        SELECT
            id,
            package_version,
            draft_text,
            package_json,
            'baseline',
            NULL,
            'legacy',
            0,
            COALESCE(updated_at, created_at, ?)
        FROM content_posts
        WHERE package_json IS NOT NULL
        """,
        (_utc_now(),),
    )


def _repair_content_post_versions_foreign_key(
    connection: sqlite3.Connection,
) -> None:
    """Repair version-history FKs rewritten during legacy content migrations."""
    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(content_post_versions)"
    ).fetchall()
    targets = {
        str(row["table"])
        for row in foreign_keys
        if str(row["from"]) == "content_post_id"
    }
    if not targets or targets == {"content_posts"}:
        return
    if targets != {"content_posts_legacy"}:
        raise RuntimeError("content_post_versions has an unsupported post foreign key")
    if connection.in_transaction:
        connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE content_post_versions_repaired (
                id INTEGER PRIMARY KEY,
                content_post_id INTEGER NOT NULL REFERENCES content_posts(id) ON DELETE CASCADE,
                package_version INTEGER NOT NULL,
                draft_text TEXT NOT NULL,
                package_json TEXT NOT NULL,
                revision_type TEXT NOT NULL,
                revision_notes TEXT,
                model_mode TEXT NOT NULL,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE (content_post_id, package_version),
                CHECK (package_version >= 1),
                CHECK (fallback_used IN (0, 1))
            );
            INSERT INTO content_post_versions_repaired
                SELECT * FROM content_post_versions;
            DROP TABLE content_post_versions;
            PRAGMA legacy_alter_table = ON;
            ALTER TABLE content_post_versions_repaired
                RENAME TO content_post_versions;
            PRAGMA legacy_alter_table = OFF;
            CREATE INDEX IF NOT EXISTS idx_content_post_versions_post_version
                ON content_post_versions(content_post_id, package_version DESC);
            COMMIT;
            """
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                "Foreign-key validation failed after repairing content versions"
            )
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _migrate_refinement_outcomes_explicit_columns(
    connection: sqlite3.Connection,
) -> None:
    """Add explicit user-reported outcome metadata to existing DBs."""
    columns = _column_names(connection, "refinement_outcomes")
    if not columns:
        return
    additions = {
        "target_type": "TEXT",
        "target_id": "INTEGER",
        "related_interaction_id": "INTEGER",
        "outcome": "TEXT",
        "notes": "TEXT",
        "source": "TEXT",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE refinement_outcomes ADD COLUMN {column_name} {column_type}"
            )


def _migrate_signal_scoring_columns(connection: sqlite3.Connection) -> None:
    """Add nullable Phase 8C score fields without rewriting historical signals."""
    columns = _column_names(connection, "signals")
    if not columns:
        return
    additions = {
        "profile_version": "INTEGER",
        "scoring_config_version": "INTEGER",
        "score_json": "TEXT",
        "total_score": "REAL",
        "scoring_confidence": "REAL",
        "scoring_mode": "TEXT",
        "scored_at": "TEXT",
        "eligibility_status": "TEXT NOT NULL DEFAULT 'pending'",
        "eligibility_reasons_json": "TEXT",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(f"ALTER TABLE signals ADD COLUMN {column_name} {column_type}")
    table_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'signals'"
    ).fetchone()
    table_sql = str(table_sql_row["sql"]) if table_sql_row is not None else ""
    if "'scored'" not in table_sql:
        _rebuild_signals_for_phase8c(connection)


def _rebuild_signals_for_phase8c(connection: sqlite3.Connection) -> None:
    """Widen the legacy signal status constraint while preserving all rows."""
    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_signals_source_id;
        DROP INDEX IF EXISTS idx_signals_source_external_id;
        DROP INDEX IF EXISTS idx_signals_canonical_url;
        DROP INDEX IF EXISTS idx_signals_content_hash;
        DROP INDEX IF EXISTS idx_signals_dedupe_key;
        DROP INDEX IF EXISTS idx_signals_published_at;
        DROP INDEX IF EXISTS idx_signals_status;
        DROP INDEX IF EXISTS idx_signals_score;
        PRAGMA legacy_alter_table = ON;
        ALTER TABLE signals RENAME TO signals_phase8c_legacy;
        CREATE TABLE signals (
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
        INSERT INTO signals SELECT * FROM signals_phase8c_legacy;
        DROP TABLE signals_phase8c_legacy;
        CREATE INDEX IF NOT EXISTS idx_signals_source_id ON signals(source_id);
        CREATE INDEX IF NOT EXISTS idx_signals_source_external_id ON signals(source_id, external_id);
        CREATE INDEX IF NOT EXISTS idx_signals_canonical_url ON signals(canonical_url);
        CREATE INDEX IF NOT EXISTS idx_signals_content_hash ON signals(content_hash);
        CREATE INDEX IF NOT EXISTS idx_signals_dedupe_key ON signals(dedupe_key);
        CREATE INDEX IF NOT EXISTS idx_signals_published_at ON signals(published_at);
        CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
        CREATE INDEX IF NOT EXISTS idx_signals_score ON signals(total_score DESC);
        PRAGMA legacy_alter_table = OFF;
        """
    )


def _repair_content_opportunities_signal_foreign_key(
    connection: sqlite3.Connection,
) -> None:
    """Repair Phase 8C databases whose opportunity FK retained a temp name."""
    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(content_opportunities)"
    ).fetchall()
    primary_signal_targets = {
        str(row["table"])
        for row in foreign_keys
        if str(row["from"]) == "primary_signal_id"
    }
    if not primary_signal_targets or primary_signal_targets == {"signals"}:
        return
    if primary_signal_targets != {"signals_phase8c_legacy"}:
        raise RuntimeError(
            "content_opportunities has an unsupported primary-signal foreign key"
        )

    if connection.in_transaction:
        connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE content_opportunities_phase8c_repaired (
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
            INSERT INTO content_opportunities_phase8c_repaired
            SELECT * FROM content_opportunities;
            DROP TABLE content_opportunities;
            PRAGMA legacy_alter_table = ON;
            ALTER TABLE content_opportunities_phase8c_repaired
                RENAME TO content_opportunities;
            PRAGMA legacy_alter_table = OFF;
            CREATE INDEX IF NOT EXISTS idx_content_opportunities_status_score
                ON content_opportunities(status, total_score DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_active_opportunity_per_signal_config
                ON content_opportunities(
                    primary_signal_id,
                    profile_version,
                    scoring_config_version
                )
                WHERE status IN ('candidate', 'saved', 'selected');
            COMMIT;
            """
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                "Foreign-key validation failed after repairing content opportunities"
            )
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _load_core_intent_rules(core_intent_path: str | Path) -> list[dict[str, str]]:
    raw_data = json.loads(Path(core_intent_path).read_text(encoding="utf-8"))
    raw_rules = raw_data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError("core_intent.json must contain a list at key 'rules'.")
    return [_normalize_core_intent_rule(rule) for rule in raw_rules]


def _normalize_core_intent_rule(rule: dict[str, Any]) -> dict[str, str]:
    rule_key = rule.get("rule_key")
    if not isinstance(rule_key, str) or not rule_key:
        raise ValueError("Each core intent rule must include a non-empty rule_key.")

    rule_value = rule.get("rule_value", rule.get("value"))
    if not isinstance(rule_value, str):
        rule_value = json.dumps(rule_value)

    description = rule.get("description", rule.get("rule_text", ""))
    if not isinstance(description, str):
        description = str(description)

    return {
        "rule_key": rule_key,
        "rule_value": rule_value,
        "description": description,
    }


def _migrate_linkedin_oauth_columns(connection: sqlite3.Connection) -> None:
    """Add B1 metadata columns to databases created before the OAuth flow."""
    state_columns = {row[1] for row in connection.execute("PRAGMA table_info(linkedin_oauth_states)")}
    if "requested_scopes" not in state_columns:
        connection.execute("ALTER TABLE linkedin_oauth_states ADD COLUMN requested_scopes TEXT NOT NULL DEFAULT 'openid profile w_member_social'")
    if "redirect_uri" not in state_columns:
        connection.execute("ALTER TABLE linkedin_oauth_states ADD COLUMN redirect_uri TEXT NOT NULL DEFAULT ''")
    for column, definition in (
        ("correlation_id", "TEXT"), ("failure_stage", "TEXT"), ("error_summary", "TEXT"),
        ("granted_scopes", "TEXT"), ("missing_scopes", "TEXT"),
        ("unexpected_scopes", "TEXT"), ("raw_scope_type", "TEXT"),
        ("scope_field_present", "INTEGER"),
        ("introspection_attempted", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in state_columns:
            connection.execute(f"ALTER TABLE linkedin_oauth_states ADD COLUMN {column} {definition}")
    credential_columns = {row[1] for row in connection.execute("PRAGMA table_info(linkedin_credentials)")}
    if "member_display_name" not in credential_columns:
        connection.execute("ALTER TABLE linkedin_credentials ADD COLUMN member_display_name TEXT")
    _canonicalize_linkedin_granted_scopes(connection)


def _canonicalize_linkedin_granted_scopes(connection: sqlite3.Connection) -> None:
    """Normalize legacy scope text to the durable JSON-list representation."""
    required = ("openid", "profile", "w_member_social")
    rows = connection.execute(
        "SELECT id, granted_scopes FROM linkedin_credentials"
    ).fetchall()
    for row in rows:
        raw = row[1]
        try:
            parsed = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            parsed = raw or ""
        if isinstance(parsed, list):
            scopes = {str(item).strip() for item in parsed if str(item).strip()}
        elif isinstance(parsed, str):
            scopes = {part for part in re.split(r"[\s,]+", parsed) if part}
        else:
            scopes = set()
        ordered = [scope for scope in required if scope in scopes]
        ordered.extend(sorted(scopes.difference(required)))
        canonical = json.dumps(ordered, separators=(",", ":"))
        if raw != canonical:
            connection.execute(
                "UPDATE linkedin_credentials SET granted_scopes=? WHERE id=?",
                (canonical, row[0]),
            )


def _migrate_linkedin_publish_columns(connection: sqlite3.Connection) -> None:
    """Add production-hardening fields to pre-certification publish ledgers."""
    columns = _column_names(connection, "linkedin_publish_requests")
    if not columns:
        return
    if "confirmation_attempts" not in columns:
        connection.execute(
            "ALTER TABLE linkedin_publish_requests ADD COLUMN confirmation_attempts INTEGER NOT NULL DEFAULT 0"
        )
    if "last_confirmation_attempt_at" not in columns:
        connection.execute(
            "ALTER TABLE linkedin_publish_requests ADD COLUMN last_confirmation_attempt_at TEXT"
        )
    _import_legacy_linkedin_publish_requests(connection)


def _prepare_linkedin_publish_legacy_migration(connection: sqlite3.Connection) -> None:
    """Archive the Phase 8G-A ledger before the certified schema is applied."""
    columns = _column_names(connection, "linkedin_publish_requests")
    if not columns or "publish_format" in columns:
        return
    legacy_table = "linkedin_publish_requests_legacy_8ga"
    if _column_names(connection, legacy_table):
        raise sqlite3.OperationalError("A legacy LinkedIn publish archive already exists.")
    connection.execute(
        f"ALTER TABLE linkedin_publish_requests RENAME TO {legacy_table}"
    )
    connection.execute("DROP INDEX IF EXISTS idx_linkedin_publish_requests_status")
    connection.execute("DROP INDEX IF EXISTS idx_linkedin_publish_requests_post")


def _import_legacy_linkedin_publish_requests(connection: sqlite3.Connection) -> None:
    """Import legacy requests as terminal audit records, never reusable previews."""
    legacy_table = "linkedin_publish_requests_legacy_8ga"
    if not _column_names(connection, legacy_table):
        return
    credential = connection.execute(
        """SELECT id, oidc_subject FROM linkedin_credentials
           WHERE oidc_subject IS NOT NULL
           ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC LIMIT 1"""
    ).fetchone()
    if credential is None:
        return
    status_map = {
        "mock_published": "published_mock",
        "cancelled": "cancelled",
        "expired": "expired",
        "preview_ready": "expired",
        "awaiting_confirmation": "expired",
        "blocked_disabled": "publish_failed",
        "failed": "publish_failed",
        "real_publish_not_implemented": "publish_failed",
    }
    rows = connection.execute(
        f"SELECT * FROM {legacy_table} ORDER BY id"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        publish_format = str(
            payload.get("format") or payload.get("publish_format") or "text"
        )
        if publish_format not in {
            "text", "single_image", "multi_image", "video", "document", "article", "poll"
        }:
            publish_format = "text"
        status = status_map.get(str(row["status"]), "publish_failed")
        author = f"urn:li:person:{credential['oidc_subject']}"
        provider_post_id = row["external_post_id"]
        now = _utc_now()
        connection.execute(
            """INSERT OR IGNORE INTO linkedin_publish_requests (
                id, content_post_id, package_version, publish_format, status,
                payload_json, payload_hash, asset_manifest_json, idempotency_key,
                credential_id, author_urn, visibility, api_version,
                provider_post_id, safe_error_code, safe_error_summary,
                expires_at, confirmed_at, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id"], row["content_post_id"], row["package_version"], publish_format,
                status, payload_json, hashlib.sha256(payload_json.encode()).hexdigest(),
                row["idempotency_key"], credential["id"], author,
                str(payload.get("visibility") or "PUBLIC"),
                str(payload.get("api_version") or "202606"), provider_post_id,
                row["error_code"] or "legacy_migration",
                row["error_summary"] or "Migrated from the Phase 8G-A request ledger.",
                row["expires_at"], row["confirmed_at"], row["completed_at"],
                row["created_at"], now,
            ),
        )
        migrated = connection.execute(
            "SELECT id FROM linkedin_publish_requests WHERE idempotency_key=?",
            (row["idempotency_key"],),
        ).fetchone()
        if migrated is not None:
            connection.execute(
                """INSERT INTO linkedin_publish_events
                   (request_id, event_type, stage, safe_metadata_json, created_at)
                   SELECT ?, 'legacy_migrated', 'migration', ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM linkedin_publish_events
                       WHERE request_id=? AND event_type='legacy_migrated'
                   )""",
                (
                    migrated["id"],
                    json.dumps(
                        {
                            "legacy_status": row["status"],
                            "external_url_present": bool(row["external_post_url"]),
                        },
                        sort_keys=True,
                    ),
                    now,
                    migrated["id"],
                ),
            )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def fetch_all_rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: Iterable[Any] = (),
) -> list[sqlite3.Row]:
    """Fetch rows for data-layer tests and scripts."""
    return list(connection.execute(query, tuple(parameters)).fetchall())
