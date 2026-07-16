"""Read-only cross-table integrity checks for Network Growth Agent."""

import json
import hashlib
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from db.database import connect
from db.models import PersonalBrandProfileData
from db.database import personal_brand_profile_hash, signal_scoring_config_hash
from config.settings import settings


DatabaseRef = sqlite3.Connection | str | Path


class SystemIntegrityAgent:
    """Report cross-agent data anomalies without changing stored data.

    These checks look for invariants that isolated agent unit tests can miss
    because those tests commonly mock neighboring agents. The agent is strictly
    observational: it opens read queries and returns structured reports only.
    """

    def check_no_duplicate_active_meeting(self, database: DatabaseRef) -> dict[str, Any]:
        """Flag prospects with multiple future calendar blocks."""
        today = date.today().isoformat()
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    prospect_id,
                    GROUP_CONCAT(id) AS conflicting_meeting_ids,
                    COUNT(*) AS meeting_count
                FROM calendar_blocks
                WHERE scheduled_date >= ?
                GROUP BY prospect_id
                HAVING COUNT(*) > 1
                """,
                (today,),
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "prospect_id": row["prospect_id"],
                "conflicting_meeting_ids": _parse_id_list(
                    row["conflicting_meeting_ids"]
                ),
            }
            for row in rows
        ]
        return _result("no_duplicate_active_meeting", violations)

    def check_single_active_parameter_version(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Flag parameter keys with more than one active version."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    agent_name,
                    parameter_key,
                    GROUP_CONCAT(version) AS conflicting_versions,
                    COUNT(*) AS active_count
                FROM refinable_parameters
                WHERE is_active = 1
                GROUP BY agent_name, parameter_key
                HAVING COUNT(*) > 1
                """,
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "agent_name": row["agent_name"],
                "parameter_key": row["parameter_key"],
                "conflicting_versions": _parse_id_list(row["conflicting_versions"]),
            }
            for row in rows
        ]
        return _result("single_active_parameter_version", violations)

    def check_refinement_history_matches_parameter_state(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Flag active parameter versions without accepted history."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    parameters.agent_name,
                    parameters.parameter_key,
                    parameters.version
                FROM refinable_parameters AS parameters
                LEFT JOIN refinement_history AS history
                    ON history.agent_name = parameters.agent_name
                    AND history.version = parameters.version
                    AND history.accepted = 1
                WHERE parameters.is_active = 1
                    AND parameters.version > 1
                    AND history.id IS NULL
                ORDER BY parameters.agent_name, parameters.parameter_key
                """,
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "agent_name": row["agent_name"],
                "parameter_key": row["parameter_key"],
                "version": row["version"],
            }
            for row in rows
        ]
        return _result("refinement_history_matches_parameter_state", violations)

    def check_prospect_status_matches_interaction_history(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Flag meeting-confirmed prospects missing required records."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT
                    prospects.id AS prospect_id,
                    COUNT(DISTINCT interactions.id) AS meeting_interaction_count,
                    COUNT(DISTINCT calendar_blocks.id) AS calendar_block_count
                FROM prospects
                LEFT JOIN interactions
                    ON interactions.prospect_id = prospects.id
                    AND interactions.interaction_type = 'meeting_confirmed'
                LEFT JOIN calendar_blocks
                    ON calendar_blocks.prospect_id = prospects.id
                WHERE prospects.status = 'meeting_confirmed'
                GROUP BY prospects.id
                HAVING meeting_interaction_count = 0
                    OR calendar_block_count = 0
                """,
            )
        finally:
            if should_close:
                connection.close()

        violations = [
            {
                "prospect_id": row["prospect_id"],
                "missing_interaction": row["meeting_interaction_count"] == 0,
                "missing_calendar_block": row["calendar_block_count"] == 0,
            }
            for row in rows
        ]
        return _result("prospect_status_matches_interaction_history", violations)

    def check_content_posts_status_consistency(
        self,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Report internal content approval state without publishing assumptions.

        Phase 1 has no LinkedIn publishing path. A row marked
        `approved_for_later_posting` is an internal queue state only, so missing
        engagement metrics are expected and informational rather than a failure.
        """
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """
                SELECT id, status
                FROM content_posts
                WHERE status = 'approved_for_later_posting'
                    AND engagement_metric IS NULL
                ORDER BY id
                """,
            )
        finally:
            if should_close:
                connection.close()

        notes = [
            f"content_post_id={row['id']} approved_for_later_posting: no engagement metric expected before publishing exists."
            for row in rows
        ]
        return {
            "check": "content_posts_status_consistency",
            "passed": True,
            "violations": [],
            "notes": notes,
        }

    def check_refinement_loop_safety(self, database: DatabaseRef) -> dict[str, Any]:
        """Flag unsafe refinement loop configuration or proposal/history state."""
        connection, should_close = _coerce_connection(database)
        try:
            constraints = {
                row["constraint_key"]: row["constraint_value"]
                for row in _fetch_dicts(
                    connection,
                    """
                    SELECT constraint_key, constraint_value
                    FROM refinement_loop_constraints
                    """,
                )
            }
            core_count = _fetch_dicts(
                connection,
                "SELECT COUNT(*) AS count FROM core_intent",
            )[0]["count"]
            cadence_rows = _fetch_dicts(
                connection,
                "SELECT rule_value FROM core_intent WHERE rule_key = 'cadence_floor_days'",
            )
            unsafe_pending = _fetch_dicts(
                connection,
                """
                SELECT proposal_id, checker_status, core_intent_check_status, status
                FROM refinement_proposals
                WHERE status = 'pending_approval'
                    AND (
                        checker_status != 'passed'
                        OR core_intent_check_status != 'passed'
                    )
                ORDER BY id
                """,
            )
            applied_rows = _fetch_dicts(
                connection,
                """
                SELECT id, agent_name, what_changed
                FROM refinement_history
                WHERE accepted = 1
                ORDER BY id
                """,
            )
            active_keys = {
                (row["agent_name"], row["parameter_key"])
                for row in _fetch_dicts(
                    connection,
                    """
                    SELECT agent_name, parameter_key
                    FROM refinable_parameters
                    WHERE is_active = 1
                    """,
                )
            }
            foreign_key_errors = _fetch_dicts(
                connection,
                "PRAGMA foreign_key_check",
            )
        finally:
            if should_close:
                connection.close()

        violations: list[dict[str, Any]] = []
        if int(core_count) == 0:
            violations.append({"type": "missing_core_intent"})
        if len(cadence_rows) != 1:
            violations.append({"type": "missing_followup_cadence"})
        else:
            try:
                if int(cadence_rows[0]["rule_value"]) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                violations.append(
                    {
                        "type": "invalid_followup_cadence",
                        "value": cadence_rows[0]["rule_value"],
                    }
                )
        # An empty parameter table is a valid pre-refinement MVP state. Any
        # rows that do exist are checked for active-version and history safety.
        required_true_constraints = [
            "human_approval_required",
            "no_linkedin_auto_send",
            "no_linkedin_scraping",
            "no_linkedin_auto_publish",
        ]
        for key in required_true_constraints:
            if constraints.get(key, "").strip().lower() != "true":
                violations.append(
                    {
                        "type": "unsafe_constraint",
                        "constraint_key": key,
                        "constraint_value": constraints.get(key),
                    }
                )
        if not constraints:
            violations.append({"type": "missing_loop_constraints"})
        for row in foreign_key_errors:
            violations.append(
                {
                    "type": "foreign_key_violation",
                    "table": row.get("table"),
                    "rowid": row.get("rowid"),
                    "parent": row.get("parent"),
                }
            )
        for row in unsafe_pending:
            violations.append(
                {
                    "type": "unsafe_pending_proposal",
                    "proposal_id": row["proposal_id"],
                    "checker_status": row["checker_status"],
                    "core_intent_check_status": row["core_intent_check_status"],
                }
            )
        for row in applied_rows:
            event = _json_object(row["what_changed"])
            if event.get("event") != "proposal_applied":
                continue
            parameter_name = event.get("parameter_name")
            if (row["agent_name"], parameter_name) not in active_keys:
                violations.append(
                    {
                        "type": "applied_refinement_targets_non_refinable_parameter",
                        "refinement_id": row["id"],
                        "agent_name": row["agent_name"],
                        "parameter_name": parameter_name,
                    }
                )
            if event.get("old_value") is None or event.get("new_value") is None:
                violations.append(
                    {
                        "type": "applied_refinement_missing_old_new_values",
                        "refinement_id": row["id"],
                    }
                )
        return _result("refinement_loop_safety", violations)

    def check_personal_brand_profile(self, database: DatabaseRef) -> dict[str, Any]:
        """Check profile version structure and the single-active invariant."""
        connection, should_close = _coerce_connection(database)
        try:
            table = _fetch_dicts(
                connection,
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'personal_brand_profile'
                """,
            )
            if not table:
                return _result(
                    "personal_brand_profile",
                    [{"type": "missing_personal_brand_profile_table"}],
                )
            rows = _fetch_dicts(
                connection,
                """
                SELECT id, version, schema_version, profile_json,
                    profile_hash, is_active
                FROM personal_brand_profile
                ORDER BY version
                """,
            )
            core_rules = {
                row["rule_key"]
                for row in _fetch_dicts(
                    connection,
                    "SELECT rule_key FROM core_intent",
                )
            }
            version_conflicts = _fetch_dicts(
                connection,
                """
                SELECT version, COUNT(*) AS count
                FROM personal_brand_profile
                GROUP BY version
                HAVING COUNT(*) > 1
                """,
            )
            foreign_keys = _fetch_dicts(
                connection,
                "PRAGMA foreign_key_list(personal_brand_profile)",
            )
        finally:
            if should_close:
                connection.close()

        violations: list[dict[str, Any]] = []
        if not rows:
            violations.append({"type": "missing_personal_brand_profile"})
        active_rows = [row for row in rows if row["is_active"] == 1]
        if len(active_rows) == 0:
            violations.append({"type": "missing_active_personal_brand_profile"})
        elif len(active_rows) > 1:
            violations.append(
                {
                    "type": "multiple_active_profiles",
                    "versions": [row["version"] for row in active_rows],
                }
            )
        for row in rows:
            try:
                parsed = json.loads(row["profile_json"])
                if not isinstance(parsed, dict):
                    raise ValueError
                if parsed.get("schema_version") != "1.0":
                    violations.append(
                        {
                            "type": "unsupported_profile_schema_version",
                            "profile_id": row["id"],
                            "version": row["version"],
                            "schema_version": parsed.get("schema_version"),
                        }
                    )
                    continue
                validated = PersonalBrandProfileData.model_validate(parsed)
                if validated.schema_version != row["schema_version"]:
                    raise ValueError
                expected_hash = personal_brand_profile_hash(
                    json.dumps(
                        validated.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                if expected_hash != row["profile_hash"]:
                    violations.append(
                        {
                            "type": "profile_hash_mismatch",
                            "profile_id": row["id"],
                            "version": row["version"],
                        }
                    )
            except (TypeError, ValueError, json.JSONDecodeError):
                violations.append(
                    {
                        "type": "invalid_profile_record",
                        "profile_id": row["id"],
                        "version": row["version"],
                    }
                )
            else:
                if row["is_active"] == 1 and not (
                    validated.personal_experience_boundaries
                    or validated.allowed_personal_claims
                    or validated.claims_requiring_confirmation
                ):
                    violations.append(
                        {
                            "type": "missing_personal_claim_safeguards",
                            "profile_id": row["id"],
                            "version": row["version"],
                        }
                    )
        if version_conflicts:
            violations.append(
                {
                    "type": "duplicate_profile_versions",
                    "versions": [row["version"] for row in version_conflicts],
                }
            )
        if foreign_keys:
            violations.append({"type": "profile_has_unexpected_relationships"})
        required_core_rules = {
            "cadence_floor_days",
            "no_fabrication",
            "linkedin_outreach_draft_only",
            "tone_floor",
        }
        missing_core_rules = sorted(required_core_rules - core_rules)
        if missing_core_rules:
            violations.append(
                {
                    "type": "missing_core_safety_rules",
                    "rule_keys": missing_core_rules,
                }
            )
        return _result("personal_brand_profile", violations)

    def check_signal_integrity(self, database: DatabaseRef) -> dict[str, Any]:
        """Check approved public-source and stored-signal invariants."""
        connection, should_close = _coerce_connection(database)
        try:
            table_rows = _fetch_dicts(
                connection,
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name IN ('signal_sources', 'signals')
                """,
            )
            table_names = {row["name"] for row in table_rows}
            if table_names != {"signal_sources", "signals"}:
                missing = sorted({"signal_sources", "signals"} - table_names)
                return _result("signal_integrity", [{"type": "missing_signal_tables", "tables": missing}])
            sources = _fetch_dicts(connection, "SELECT * FROM signal_sources")
            signals = _fetch_dicts(
                connection,
                """
                SELECT signals.*, source.id AS valid_source_id,
                    original.id AS valid_duplicate_id
                FROM signals
                LEFT JOIN signal_sources AS source ON source.id = signals.source_id
                LEFT JOIN signals AS original ON original.id = signals.duplicate_of_id
                """,
            )
            duplicates = _fetch_dicts(
                connection,
                """
                SELECT url, COUNT(*) AS count
                FROM signal_sources GROUP BY url HAVING COUNT(*) > 1
                """,
            )
        finally:
            if should_close:
                connection.close()

        violations: list[dict[str, Any]] = []
        for row in duplicates:
            violations.append({"type": "duplicate_signal_source_url", "url": row["url"]})
        for source in sources:
            host = str(source["url"]).lower()
            if source["approval_status"] == "approved" and not source["approved_at"]:
                violations.append({"type": "approved_source_missing_timestamp", "source_id": source["id"]})
            if source["approval_status"] == "rejected" and source["enabled"]:
                violations.append({"type": "rejected_source_enabled", "source_id": source["id"]})
            if source["enabled"] and source["approval_status"] != "approved":
                violations.append({"type": "enabled_source_not_approved", "source_id": source["id"]})
            if source["approval_status"] == "approved" and "linkedin.com" in host:
                violations.append({"type": "approved_linkedin_source", "source_id": source["id"]})
        for signal in signals:
            if signal["valid_source_id"] is None:
                violations.append({"type": "orphan_signal", "signal_id": signal["id"]})
            if signal["duplicate_of_id"] is not None and signal["valid_duplicate_id"] is None:
                violations.append({"type": "invalid_duplicate_reference", "signal_id": signal["id"]})
            if signal["status"] not in {"fetched", "normalized", "scored", "ineligible", "duplicate", "failed"}:
                violations.append({"type": "unsupported_signal_status", "signal_id": signal["id"]})
            if signal["status"] in {"normalized", "duplicate"} and (
                not signal["content_hash"] or not signal["dedupe_key"]
            ):
                violations.append({"type": "signal_missing_dedupe_fields", "signal_id": signal["id"]})
        return _result("signal_integrity", violations)

    def check_signal_scoring_and_opportunities(self, database: DatabaseRef) -> dict[str, Any]:
        """Check Phase 8C score provenance and review-only opportunity invariants."""
        connection, should_close = _coerce_connection(database)
        try:
            table_names = {row["name"] for row in _fetch_dicts(connection, "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('signal_scoring_config', 'content_opportunities')")}
            if table_names != {"signal_scoring_config", "content_opportunities"}:
                return _result("signal_scoring_and_opportunities", [{"type": "missing_phase8c_tables"}])
            configs = _fetch_dicts(connection, "SELECT * FROM signal_scoring_config ORDER BY version")
            signals = _fetch_dicts(connection, "SELECT * FROM signals WHERE total_score IS NOT NULL OR eligibility_status != 'pending'")
            opportunities = _fetch_dicts(connection, "SELECT * FROM content_opportunities")
            active_duplicate_rows = _fetch_dicts(connection, "SELECT primary_signal_id, profile_version, scoring_config_version, COUNT(*) AS count FROM content_opportunities WHERE status IN ('candidate', 'saved', 'selected') GROUP BY primary_signal_id, profile_version, scoring_config_version HAVING COUNT(*) > 1")
        finally:
            if should_close:
                connection.close()
        violations: list[dict[str, Any]] = []
        active = [config for config in configs if config["is_active"] == 1]
        if len(active) != 1:
            violations.append({"type": "invalid_active_scoring_config_count", "count": len(active)})
        valid_config_versions = {config["version"] for config in configs}
        for config in configs:
            try:
                if signal_scoring_config_hash(config["config_json"]) != config["config_hash"]:
                    violations.append({"type": "scoring_config_hash_mismatch", "version": config["version"]})
                parsed = json.loads(config["config_json"])
                if not isinstance(parsed, dict):
                    raise ValueError
            except (TypeError, ValueError, json.JSONDecodeError):
                violations.append({"type": "invalid_scoring_config", "version": config["version"]})
        for signal in signals:
            if signal["profile_version"] is None:
                violations.append({"type": "scored_signal_missing_profile_version", "signal_id": signal["id"]})
            if signal["scoring_config_version"] not in valid_config_versions:
                violations.append({"type": "scored_signal_invalid_config_version", "signal_id": signal["id"]})
            if signal["eligibility_status"] == "eligible" and (signal["total_score"] is None or signal["score_json"] is None):
                violations.append({"type": "eligible_signal_missing_breakdown", "signal_id": signal["id"]})
            if signal["eligibility_status"] == "ineligible" and not signal["eligibility_reasons_json"]:
                violations.append({"type": "ineligible_signal_missing_reasons", "signal_id": signal["id"]})
            for field, upper in (("total_score", 100), ("scoring_confidence", 1)):
                value = signal[field]
                if value is not None and not 0 <= float(value) <= upper:
                    violations.append({"type": "score_out_of_range", "signal_id": signal["id"], "field": field})
        for opportunity in opportunities:
            if opportunity["primary_signal_id"] is None or opportunity["profile_version"] is None or opportunity["scoring_config_version"] not in valid_config_versions:
                violations.append({"type": "opportunity_missing_provenance", "opportunity_id": opportunity["id"]})
            if not opportunity["source_references_json"]:
                violations.append({"type": "opportunity_missing_source_references", "opportunity_id": opportunity["id"]})
            if opportunity["status"] == "dismissed" and opportunity["status"] == "selected":
                violations.append({"type": "dismissed_opportunity_selected", "opportunity_id": opportunity["id"]})
            metadata = _json_object(opportunity["metadata_json"])
            if any(key in metadata for key in ("post_text", "draft_text", "image_prompt", "image_path")):
                violations.append({"type": "opportunity_contains_out_of_phase_content", "opportunity_id": opportunity["id"]})
        for row in active_duplicate_rows:
            violations.append({"type": "duplicate_active_opportunity", "primary_signal_id": row["primary_signal_id"]})
        return _result("signal_scoring_and_opportunities", violations)

    def check_content_package_integrity(self, database: DatabaseRef) -> dict[str, Any]:
        """Check content packages remain source-traced, review-only artifacts."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(connection, "SELECT * FROM content_posts WHERE package_json IS NOT NULL")
        finally:
            if should_close:
                connection.close()
        violations: list[dict[str, Any]] = []
        for row in rows:
            post_id = row["id"]
            if row["opportunity_id"] is None or row["profile_version"] is None or row["scoring_config_version"] is None:
                violations.append({"type": "package_missing_provenance", "post_id": post_id})
            references = _json_object(row["package_json"]).get("source_references", [])
            if not isinstance(references, list) or not references:
                violations.append({"type": "package_missing_sources", "post_id": post_id})
            for claim in _json_object(row["package_json"]).get("factual_claims", []):
                if not isinstance(claim, dict) or not claim.get("source_signal_ids"):
                    violations.append({"type": "package_claim_missing_sources", "post_id": post_id})
                if row["status"] == "approved_for_later_posting" and claim.get("confirmation_required"):
                    violations.append({"type": "approved_package_has_unresolved_claim", "post_id": post_id})
            if row["image_source"] != "none" and not row["image_alt_text"]:
                violations.append({"type": "package_image_missing_alt_text", "post_id": post_id})
            if row["status"] not in {"draft", "saved", "needs_confirmation", "approved_for_later_posting", "rejected", "discarded"}:
                violations.append({"type": "package_invalid_phase_status", "post_id": post_id})
        return _result("content_package_integrity", violations)

    def check_linkedin_publish_integrity(self, database: DatabaseRef) -> dict[str, Any]:
        """Check durable approval, hashing, identity, and replay invariants."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = _fetch_dicts(
                connection,
                """SELECT requests.*, posts.status AS post_status,
                          posts.package_version AS current_package_version,
                          credentials.oidc_subject, credentials.granted_scopes
                   FROM linkedin_publish_requests AS requests
                   LEFT JOIN content_posts AS posts ON posts.id=requests.content_post_id
                   LEFT JOIN linkedin_credentials AS credentials ON credentials.id=requests.credential_id""",
            )
        finally:
            if should_close:
                connection.close()
        violations: list[dict[str, Any]] = []
        notes: list[str] = []
        if settings.linkedin_publish_mode not in {"disabled", "mock", "real"}:
            violations.append({"type": "publish_mode_invalid"})
        elif settings.linkedin_real_publish_enabled and settings.linkedin_publish_mode != "real":
            violations.append({"type": "publish_kill_switch_mode_mismatch"})
        elif settings.linkedin_publish_mode == "real" and not settings.linkedin_real_publish_enabled:
            notes = ["Real mode is selected but the independent publish kill switch is off."]
        else:
            notes = []
        terminal = {"published_linkedin", "published_mock", "publish_uncertain", "upload_uncertain", "image_upload_uncertain", "processing_unknown", "cancelled", "expired"}
        for row in rows:
            request_id = row["id"]
            if not _is_json_type(row["payload_json"], dict):
                violations.append({"type": "publish_payload_json_invalid", "request_id": request_id})
            if not _is_json_type(row["asset_manifest_json"], list):
                violations.append({"type": "publish_asset_manifest_json_invalid", "request_id": request_id})
            if row["post_status"] != "approved_for_later_posting":
                violations.append({"type": "publish_request_unapproved_package", "request_id": request_id})
            if row["package_version"] != row["current_package_version"] and row["status"] not in terminal:
                violations.append({"type": "publish_request_obsolete_package", "request_id": request_id})
            actual_hash = hashlib.sha256(str(row["payload_json"]).encode()).hexdigest()
            if actual_hash != row["payload_hash"]:
                violations.append({"type": "publish_payload_hash_mismatch", "request_id": request_id})
            expected_author = f"urn:li:person:{row['oidc_subject']}" if row["oidc_subject"] else None
            if row["author_urn"] != expected_author:
                violations.append({"type": "publish_author_mismatch", "request_id": request_id})
            scopes = set(_json_list(row["granted_scopes"]))
            if "w_member_social" not in scopes:
                violations.append({"type": "publish_credential_missing_scope", "request_id": request_id})
            stored = " ".join(str(row.get(field) or "") for field in ("payload_json", "asset_manifest_json", "provider_asset_urns_json", "safe_error_summary"))
            if any(marker in stored.lower() for marker in ("bearer ", "access_token", "refresh_token", "uploadurl", "upload_url")):
                violations.append({"type": "publish_request_contains_sensitive_material", "request_id": request_id})
            assets = _json_list(row["asset_manifest_json"])
            if row["publish_format"] == "single_image" and len(assets) != 1:
                violations.append({"type": "single_image_asset_count", "request_id": request_id})
            if row["publish_format"] == "multi_image" and not 2 <= len(assets) <= settings.linkedin_max_multi_images:
                violations.append({"type": "multi_image_asset_count", "request_id": request_id})
            provider_urns = _json_list(row["provider_asset_urns_json"])
            expected_prefix = {
                "single_image": "urn:li:image:",
                "multi_image": "urn:li:image:",
                "video": "urn:li:video:",
                "document": "urn:li:document:",
            }.get(row["publish_format"])
            if expected_prefix and any(
                not isinstance(urn, str) or not urn.startswith(expected_prefix)
                for urn in provider_urns
            ):
                violations.append({"type": "publish_provider_asset_urn_invalid", "request_id": request_id})
            if row["status"] == "published_linkedin" and not row["provider_post_id"]:
                violations.append({"type": "published_request_missing_provider_id", "request_id": request_id})
        return {"check": "linkedin_publish_integrity", "passed": not violations, "violations": violations, "notes": notes}

    def run_full_integrity_check(self, database: DatabaseRef) -> dict[str, Any]:
        """Run all integrity checks and summarize the result."""
        checks = [
            self.check_no_duplicate_active_meeting(database),
            self.check_single_active_parameter_version(database),
            self.check_refinement_history_matches_parameter_state(database),
            self.check_prospect_status_matches_interaction_history(database),
            self.check_content_posts_status_consistency(database),
            self.check_refinement_loop_safety(database),
            self.check_personal_brand_profile(database),
            self.check_signal_integrity(database),
            self.check_signal_scoring_and_opportunities(database),
            self.check_content_package_integrity(database),
            self.check_linkedin_publish_integrity(database),
        ]
        overall_passed = all(bool(check["passed"]) for check in checks)
        failed_count = sum(1 for check in checks if not check["passed"])
        summary = (
            "All integrity checks passed."
            if overall_passed
            else f"{failed_count} integrity check(s) failed."
        )
        return {
            "overall_passed": overall_passed,
            "checks": checks,
            "summary": summary,
            "checked_at": datetime.now(UTC).isoformat(),
        }


def _coerce_connection(database: DatabaseRef) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _fetch_dicts(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, parameters)
    column_names = [description[0] for description in cursor.description]
    return [dict(zip(column_names, row, strict=True)) for row in cursor.fetchall()]


def _parse_id_list(value: Any) -> list[int]:
    if value is None:
        return []
    return [int(item) for item in str(value).split(",") if item]


def _is_json_type(value: Any, expected_type: type[Any]) -> bool:
    try:
        return isinstance(json.loads(str(value)), expected_type)
    except (json.JSONDecodeError, TypeError):
        return False


def _json_object(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, str):
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(raw_value: Any) -> list[Any]:
    if not isinstance(raw_value, str):
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _result(check_name: str, violations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "check": check_name,
        "passed": len(violations) == 0,
        "violations": violations,
    }
