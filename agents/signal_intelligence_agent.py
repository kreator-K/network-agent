"""Deterministic public-feed signal normalization and persistence agent."""

import hashlib
import json
import logging
import math
import sqlite3
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agents.model_orchestration_agent import ModelOrchestrationAgent
from agents.profile_context_agent import ProfileContextAgent
from db.database import connect, get_active_signal_scoring_config_row
from db.models import (
    ContentOpportunity,
    DeterministicSignalScores,
    PersonalBrandProfileData,
    SemanticSignalScores,
    Signal,
    SignalScoreBreakdown,
    SignalSource,
)
from integrations.public_signal_gateway import (
    FeedFetchResult,
    PublicSignalGatewayError,
    PublicSignalSourceRequest,
    RawFeedItem,
    fetch_feed,
    validate_public_signal_url,
)


logger = logging.getLogger(__name__)
DatabaseRef = sqlite3.Connection | str | Path
SOURCE_TYPES = {"rss", "atom", "auto_feed"}
SOURCE_APPROVAL_STATES = {"pending", "approved", "rejected"}
SIGNAL_STATUSES = {"fetched", "normalized", "scored", "ineligible", "duplicate", "failed"}
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


class SignalIntelligenceError(ValueError):
    """Base error for deterministic signal-intelligence failures."""


class SignalSourceStateError(SignalIntelligenceError):
    """Raised when a source is not approved and enabled for scanning."""


class FeedGateway(Protocol):
    """Network boundary used by deterministic signal ingestion."""

    def __call__(self, source: PublicSignalSourceRequest) -> FeedFetchResult:
        """Fetch one approved public feed without persistence side effects."""


class ModelRunner(Protocol):
    """Minimal model boundary needed for optional semantic scoring."""

    def run_task(self, task_type: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Return a metadata-wrapped model response."""


class SignalIntelligenceAgent:
    """Persist, score, and turn approved public signals into reviewable angles.

    Public fetching stays behind ``public_signal_gateway``. This agent never
    drafts posts, generates images, schedules work, or interacts with Telegram.
    """

    def __init__(
        self,
        gateway: FeedGateway | None = None,
        model_agent: ModelRunner | None = None,
        profile_agent: ProfileContextAgent | None = None,
    ) -> None:
        self.gateway = gateway or fetch_feed
        self.model_agent = model_agent or ModelOrchestrationAgent()
        self.profile_agent = profile_agent or ProfileContextAgent()

    def add_source(
        self,
        name: str,
        url: str,
        source_type: str = "auto_feed",
        database: DatabaseRef = ":memory:",
    ) -> SignalSource:
        """Store a validated source as pending approval without fetching it."""
        clean_name = _required_text(name, "Source name")
        if source_type not in SOURCE_TYPES:
            raise SignalIntelligenceError("Source type must be rss, atom, or auto_feed.")
        normalized_url = validate_public_signal_url(url, resolve_host=False)
        now = _utc_now()
        connection, should_close = _coerce_connection(database)
        try:
            existing = connection.execute(
                "SELECT id FROM signal_sources WHERE url = ?",
                (normalized_url,),
            ).fetchone()
            if existing is not None:
                raise SignalIntelligenceError("A signal source already uses that URL.")
            cursor = connection.execute(
                """
                INSERT INTO signal_sources (
                    name, source_type, url, approval_status, enabled,
                    config_json, created_at, updated_at
                )
                VALUES (?, ?, ?, 'pending', 0, '{}', ?, ?)
                """,
                (clean_name, source_type, normalized_url, now, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM signal_sources WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            logger.info("Signal source added with pending approval: source_id=%s", cursor.lastrowid)
            return _source_from_row(row)
        finally:
            if should_close:
                connection.close()

    def clear_signal_workspace(self, database: DatabaseRef) -> dict[str, int]:
        """Remove stored signal evidence and source configuration for a fresh start.

        The catalog, profile, scoring configuration, CRM records, content drafts,
        and audit receipts remain intact. Content drafts keep their text, while
        SQLite clears their optional link to any removed opportunity.
        """
        connection, should_close = _coerce_connection(database)
        try:
            counts = {
                "signal_sources": int(connection.execute("SELECT COUNT(*) FROM signal_sources").fetchone()[0]),
                "signals": int(connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]),
                "content_opportunities": int(connection.execute("SELECT COUNT(*) FROM content_opportunities").fetchone()[0]),
                "preference_feedback": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM content_preference_feedback "
                        "WHERE target_type IN ('signal', 'opportunity')"
                    ).fetchone()[0]
                ),
            }
            with connection:
                connection.execute(
                    "DELETE FROM content_preference_feedback "
                    "WHERE target_type IN ('signal', 'opportunity')"
                )
                connection.execute("DELETE FROM content_opportunities")
                connection.execute("DELETE FROM signals")
                connection.execute("DELETE FROM signal_sources")
            logger.info("Signal workspace cleared: %s", counts)
            return counts
        finally:
            if should_close:
                connection.close()

    def set_source_approval(
        self,
        source_id: int,
        approval_status: str,
        database: DatabaseRef,
    ) -> SignalSource:
        """Approve or reject a source without scanning it."""
        if approval_status not in {"approved", "rejected"}:
            raise SignalIntelligenceError("Approval status must be approved or rejected.")
        now = _utc_now()
        connection, should_close = _coerce_connection(database)
        try:
            source = _required_source(connection, source_id)
            enabled = 0 if approval_status == "rejected" else source["enabled"]
            connection.execute(
                """
                UPDATE signal_sources
                SET approval_status = ?, enabled = ?, approved_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    approval_status,
                    enabled,
                    now if approval_status == "approved" else None,
                    now,
                    source_id,
                ),
            )
            connection.commit()
            logger.info("Signal source approval changed: source_id=%s status=%s", source_id, approval_status)
            return _source_from_row(_required_source(connection, source_id))
        finally:
            if should_close:
                connection.close()

    def set_source_enabled(
        self,
        source_id: int,
        enabled: bool,
        database: DatabaseRef,
    ) -> SignalSource:
        """Enable or disable a source while enforcing approval state."""
        now = _utc_now()
        connection, should_close = _coerce_connection(database)
        try:
            source = _required_source(connection, source_id)
            if enabled and source["approval_status"] != "approved":
                raise SignalSourceStateError("Only approved signal sources can be enabled.")
            connection.execute(
                "UPDATE signal_sources SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), now, source_id),
            )
            connection.commit()
            logger.info("Signal source enabled state changed: source_id=%s enabled=%s", source_id, enabled)
            return _source_from_row(_required_source(connection, source_id))
        finally:
            if should_close:
                connection.close()

    def get_source(self, source_id: int, database: DatabaseRef) -> SignalSource:
        """Return one source record."""
        connection, should_close = _coerce_connection(database)
        try:
            return _source_from_row(_required_source(connection, source_id))
        finally:
            if should_close:
                connection.close()

    def list_sources(self, database: DatabaseRef, limit: int = 50) -> list[SignalSource]:
        """Return recent source records for operator review."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = connection.execute(
                "SELECT * FROM signal_sources ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_source_from_row(row) for row in rows]
        finally:
            if should_close:
                connection.close()

    def normalize_feed_item(self, item: RawFeedItem) -> dict[str, Any]:
        """Normalize item fields deterministically without semantic inference."""
        canonical_url = self.canonicalize_url(item.link)
        return {
            "external_id": _clean_optional(item.external_id),
            "title": _clean_optional(item.title),
            "summary": _clean_optional(item.summary),
            "author": _clean_optional(item.author),
            "published_at": _normalize_date(item.published_at),
            "updated_at_source": _normalize_date(item.updated_at),
            "canonical_url": canonical_url,
        }

    def canonicalize_url(self, url: str | None) -> str | None:
        """Remove fragments and common tracking parameters from public URLs."""
        if not url:
            return None
        parsed = urlsplit(url.strip())
        if not parsed.scheme or not parsed.hostname:
            return None
        filtered_query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY_KEYS
        ]
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                urlencode(filtered_query, doseq=True),
                "",
            )
        )

    def generate_content_hash(self, normalized: dict[str, Any]) -> str:
        """Hash stable normalized content fields for deterministic matching."""
        payload = {
            key: normalized.get(key)
            for key in ("title", "summary", "author", "published_at")
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def generate_dedupe_key(self, source_id: int, normalized: dict[str, Any]) -> str:
        """Prefer source GUID, then canonical URL, then normalized content hash."""
        external_id = normalized.get("external_id")
        if external_id:
            return f"external:{source_id}:{external_id}"
        canonical_url = normalized.get("canonical_url")
        if canonical_url:
            return f"url:{canonical_url}"
        return f"content:{self.generate_content_hash(normalized)}"

    def find_existing_signal(
        self,
        connection: sqlite3.Connection,
        source_id: int,
        normalized: dict[str, Any],
        content_hash: str,
    ) -> sqlite3.Row | None:
        """Find the deterministic primary signal matching a normalized item."""
        if normalized.get("external_id"):
            row = connection.execute(
                """
                SELECT * FROM signals
                WHERE source_id = ? AND external_id = ? AND duplicate_of_id IS NULL
                ORDER BY id ASC LIMIT 1
                """,
                (source_id, normalized["external_id"]),
            ).fetchone()
            if row is not None:
                return row
        if normalized.get("canonical_url"):
            row = connection.execute(
                """
                SELECT * FROM signals
                WHERE canonical_url = ? AND duplicate_of_id IS NULL
                ORDER BY id ASC LIMIT 1
                """,
                (normalized["canonical_url"],),
            ).fetchone()
            if row is not None:
                return row
        return connection.execute(
            """
            SELECT * FROM signals
            WHERE content_hash = ? AND duplicate_of_id IS NULL
            ORDER BY id ASC LIMIT 1
            """,
            (content_hash,),
        ).fetchone()

    def persist_signal(
        self,
        source_id: int,
        item: RawFeedItem,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Persist a primary signal or retain cross-source provenance as duplicate."""
        connection, should_close = _coerce_connection(database)
        try:
            _required_source(connection, source_id)
            normalized = self.normalize_feed_item(item)
            content_hash = self.generate_content_hash(normalized)
            dedupe_key = self.generate_dedupe_key(source_id, normalized)
            existing = self.find_existing_signal(connection, source_id, normalized, content_hash)
            now = _utc_now()
            if existing is not None and existing["source_id"] == source_id:
                return {"result": "existing", "signal": _signal_from_row(existing)}
            duplicate_of_id = None if existing is None else existing["id"]
            status = "normalized" if duplicate_of_id is None else "duplicate"
            cursor = connection.execute(
                """
                INSERT INTO signals (
                    source_id, external_id, canonical_url, title, summary, author,
                    published_at, updated_at_source, fetched_at, content_hash,
                    dedupe_key, duplicate_of_id, raw_payload_json, normalized_json,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    normalized["external_id"],
                    normalized["canonical_url"],
                    normalized["title"],
                    normalized["summary"],
                    normalized["author"],
                    normalized["published_at"],
                    normalized["updated_at_source"],
                    now,
                    content_hash,
                    dedupe_key,
                    duplicate_of_id,
                    _canonical_json(
                        {
                            "external_id": item.external_id,
                            "title": item.title,
                            "summary": item.summary,
                            "author": item.author,
                            "published_at": item.published_at,
                            "updated_at": item.updated_at,
                            "link": item.link,
                            "metadata": item.raw_metadata,
                        }
                    ),
                    _canonical_json(normalized),
                    status,
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM signals WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return {"result": "new" if duplicate_of_id is None else "duplicate", "signal": _signal_from_row(row)}
        finally:
            if should_close:
                connection.close()

    def ingest_source(self, source_id: int, database: DatabaseRef) -> dict[str, Any]:
        """Fetch one approved enabled source and persist deterministic signals."""
        source = self.get_source(source_id, database)
        if source.approval_status != "approved":
            raise SignalSourceStateError("Signal source must be approved before scanning.")
        if not source.enabled:
            raise SignalSourceStateError("Signal source must be enabled before scanning.")
        logger.info("Signal scan started: source_id=%s", source_id)
        request = PublicSignalSourceRequest(
            source_id=source_id,
            url=source.url,
            source_type=source.source_type,
            etag=source.etag,
            last_modified=source.last_modified,
        )
        try:
            fetched = self.fetch_source_request(request)
        except PublicSignalGatewayError as exc:
            logger.warning("Signal scan failed: source_id=%s", source_id)
            return self.persist_fetch_result(
                source_id,
                None,
                database,
                error=str(exc),
            )
        return self.persist_fetch_result(source_id, fetched, database)

    def fetch_source_request(
        self,
        request: PublicSignalSourceRequest,
    ) -> FeedFetchResult:
        """Fetch one pre-authorized source without writing application state."""
        return self.gateway(request)

    def persist_fetch_result(
        self,
        source_id: int,
        fetched: FeedFetchResult | None,
        database: DatabaseRef,
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Persist one completed fetch through a controlled write boundary."""
        if fetched is None:
            safe_error = error or "Public feed request failed."
            self._record_fetch(source_id, "failed", safe_error, None, None, database)
            return _scan_summary(source_id, "failed", errors=[safe_error])
        self._record_fetch(
            source_id,
            "not_modified" if fetched.not_modified else "success",
            None,
            fetched.etag,
            fetched.last_modified,
            database,
        )
        if fetched.not_modified:
            return _scan_summary(
                source_id,
                "not_modified",
                warnings=fetched.warnings,
                not_modified=True,
            )
        summary = _scan_summary(source_id, "success", warnings=fetched.warnings)
        for item in fetched.items:
            try:
                result = self.persist_signal(source_id, item, database)
            except Exception:
                summary["failures"] += 1
                summary["errors"].append("One feed item could not be persisted.")
                logger.warning("Signal item persistence failed: source_id=%s", source_id)
                continue
            summary["items_fetched"] += 1
            if result["result"] == "new":
                summary["new_signals"] += 1
            else:
                summary["duplicates"] += 1
        logger.info(
            "Signal scan completed: source_id=%s items=%s new=%s duplicates=%s failures=%s",
            source_id,
            summary["items_fetched"],
            summary["new_signals"],
            summary["duplicates"],
            summary["failures"],
        )
        return summary

    def ingest_enabled_sources(self, database: DatabaseRef) -> dict[str, Any]:
        """Scan all approved enabled sources while isolating per-source failures."""
        sources = [
            source
            for source in self.list_sources(database, limit=1000)
            if source.approval_status == "approved" and source.enabled
        ]
        results = [self.ingest_source(source.id or 0, database) for source in sources]
        return {
            "sources_scanned": len(results),
            "new_signals": sum(result["new_signals"] for result in results),
            "duplicates": sum(result["duplicates"] for result in results),
            "failures": sum(result["failures"] for result in results),
            "results": results,
        }

    def get_recent_signals(self, database: DatabaseRef, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent stored signals with source attribution."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = connection.execute(
                """
                SELECT signals.*, signal_sources.name AS source_name
                FROM signals JOIN signal_sources ON signal_sources.id = signals.source_id
                ORDER BY signals.created_at DESC, signals.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_signal_display(row) for row in rows]
        finally:
            if should_close:
                connection.close()

    def get_signal_by_id(self, signal_id: int, database: DatabaseRef) -> dict[str, Any]:
        """Return one stored signal with source attribution."""
        connection, should_close = _coerce_connection(database)
        try:
            row = connection.execute(
                """
                SELECT signals.*, signal_sources.name AS source_name
                FROM signals JOIN signal_sources ON signal_sources.id = signals.source_id
                WHERE signals.id = ?
                """,
                (signal_id,),
            ).fetchone()
            if row is None:
                raise SignalIntelligenceError(f"Signal id {signal_id} does not exist.")
            return _signal_display(row)
        finally:
            if should_close:
                connection.close()

    def score_signal(self, signal_id: int, database: DatabaseRef) -> dict[str, Any]:
        """Score one stored signal after deterministic hard-gate checks.

        Semantic analysis is optional and only requested through the model
        orchestration boundary after the deterministic gates pass.
        """
        connection, should_close = _coerce_connection(database)
        try:
            row = self._signal_with_source(connection, signal_id)
            profile = self.profile_agent.get_active_profile(connection)
            if profile is None:
                raise SignalIntelligenceError("An active personal-brand profile is required.")
            config_row = get_active_signal_scoring_config_row(connection)
            config = json.loads(config_row["config_json"])
            eligibility, reasons, deterministic = self._evaluate_eligibility(
                connection, row, _profile_data(profile), config
            )
            now = _utc_now()
            if not eligibility:
                self._persist_ineligible(
                    connection, signal_id, profile.version, config_row["version"], reasons, now
                )
                logger.info("Signal eligibility failed: signal_id=%s", signal_id)
                return {
                    "signal_id": signal_id, "title": row["title"], "eligible": False,
                    "reasons": reasons, "mode": "deterministic", "opportunity": None,
                    "published_at": row["published_at"], "age_days": _age_days(row["published_at"]),
                    "freshness_threshold_days": config["maximum_age_days"],
                    "credibility_score": deterministic.credibility,
                    "minimum_credibility_score": config["minimum_credibility_score"],
                    "profile_matches": _profile_matches(row, _profile_data(profile)),
                    "model_attempted": False,
                }

            semantic, mode, fallback_reason = self._semantic_scores(row, profile, deterministic, config)
            breakdown = self._build_breakdown(
                deterministic, semantic, profile.version, int(config_row["version"]), config,
                mode, fallback_reason,
            )
            score_json = _canonical_json(breakdown.model_dump(mode="json"))
            connection.execute(
                """
                UPDATE signals
                SET profile_version = ?, scoring_config_version = ?, score_json = ?,
                    total_score = ?, scoring_confidence = ?, scoring_mode = ?, scored_at = ?,
                    eligibility_status = 'eligible', eligibility_reasons_json = ?, status = 'scored',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    profile.version, config_row["version"], score_json, breakdown.final_score,
                    breakdown.confidence, mode, now, _canonical_json(reasons), now, signal_id,
                ),
            )
            connection.commit()
            logger.info(
                "Signal scoring completed: signal_id=%s profile_version=%s config_version=%s mode=%s",
                signal_id, profile.version, config_row["version"], mode,
            )
            return {
                "signal_id": signal_id, "title": row["title"], "eligible": True,
                "score": breakdown.model_dump(), "mode": mode,
                "fallback_reason": fallback_reason, "opportunity": None,
            }
        finally:
            if should_close:
                connection.close()

    def score_recent_signals(self, database: DatabaseRef, limit: int = 10, force: bool = False) -> dict[str, Any]:
        """Score a bounded set of normalized signals without fetching sources."""
        connection, should_close = _coerce_connection(database)
        try:
            config_row = get_active_signal_scoring_config_row(connection)
            config = json.loads(config_row["config_json"])
            profile = self.profile_agent.get_active_profile(connection)
            if profile is None:
                raise SignalIntelligenceError("An active personal-brand profile is required.")
            bounded = max(1, min(limit, int(config["maximum_signals_per_run"])))
            where = "status = 'normalized'"
            params: list[Any] = []
            if force:
                where = "status IN ('normalized', 'scored', 'ineligible')"
            else:
                where = """status = 'normalized'
                    OR (eligibility_status = 'ineligible' AND (
                        profile_version IS NULL OR profile_version != ?
                        OR scoring_config_version IS NULL OR scoring_config_version != ?
                    ))"""
                params = [profile.version, config_row["version"]]
            rows = connection.execute(
                f"""SELECT id, published_at, updated_at_source, fetched_at FROM signals
                WHERE ({where}) AND status NOT IN ('duplicate', 'failed')
                ORDER BY CASE WHEN datetime(published_at) IS NULL THEN 1 ELSE 0 END,
                    datetime(published_at) DESC,
                    CASE WHEN datetime(updated_at_source) IS NULL THEN 1 ELSE 0 END,
                    datetime(updated_at_source) DESC,
                    datetime(fetched_at) DESC, id ASC LIMIT ?""",
                (*params, bounded),
            ).fetchall()
        finally:
            if should_close:
                connection.close()
        results: list[dict[str, Any]] = []
        failures = 0
        for row in rows:
            try:
                results.append(self.score_signal(int(row["id"]), database))
            except Exception:
                failures += 1
                logger.warning("Signal scoring failed: signal_id=%s", row["id"])
        publication_dates = [str(row["published_at"]) for row in rows if row["published_at"]]
        return {
            "considered": len(rows), "eligible": sum(result["eligible"] for result in results),
            "ineligible": sum(not result["eligible"] for result in results),
            "evaluated": len(results), "ranked": sum(result["eligible"] for result in results), "scored": len(results), "model_assisted": sum(result["mode"] == "model_assisted" for result in results),
            "deterministic_fallbacks": sum(result["mode"] == "deterministic_fallback" for result in results),
            "failures": failures, "results": results, "ineligibility_summary": _summarize_ineligibility(results),
            "skipped_already_evaluated": 0, "force": force,
            "selected_publication_oldest": min(publication_dates) if publication_dates else None,
            "selected_publication_newest": max(publication_dates) if publication_dates else None,
        }

    def get_scoring_queue(self, database: DatabaseRef, limit: int = 10) -> list[dict[str, Any]]:
        """Preview the publication-first scoring queue without evaluating signals."""
        connection, should_close = _coerce_connection(database)
        try:
            config = json.loads(get_active_signal_scoring_config_row(connection)["config_json"])
            bounded = max(1, min(limit, int(config["maximum_signals_per_run"])))
            rows = connection.execute("""SELECT id, title, published_at, fetched_at, status FROM signals
                WHERE status = 'normalized' ORDER BY CASE WHEN datetime(published_at) IS NULL THEN 1 ELSE 0 END,
                datetime(published_at) DESC, datetime(updated_at_source) DESC, datetime(fetched_at) DESC, id ASC LIMIT ?""", (bounded,)).fetchall()
            return [{"signal_id": row["id"], "title": row["title"], "published_at": row["published_at"], "age_days": _age_days(row["published_at"]), "status": row["status"], "queue_reason": "newest publication date" if row["published_at"] else "no publication date; fetched-time fallback"} for row in rows]
        finally:
            if should_close:
                connection.close()

    def generate_content_opportunity(
        self, signal_id: int, database: DatabaseRef
    ) -> ContentOpportunity | None:
        """Persist one reviewable angle for a qualifying scored signal, never a post."""
        connection, should_close = _coerce_connection(database)
        try:
            row = self._signal_with_source(connection, signal_id)
            if row["status"] != "scored" or row["eligibility_status"] != "eligible":
                raise SignalIntelligenceError("Only eligible scored signals can create content opportunities.")
            if row["score_json"] is None:
                raise SignalIntelligenceError("Scored signal is missing its score breakdown.")
            score = json.loads(row["score_json"])
            config = json.loads(get_active_signal_scoring_config_row(connection)["config_json"])
            deterministic = score["deterministic"]
            if (
                float(row["total_score"] or 0) < config["minimum_final_score"]
                or deterministic["credibility"] < config["minimum_credibility_score"]
                or deterministic["factual_risk"] > config["maximum_factual_risk"]
                or deterministic["generic_commentary_risk"] > config["maximum_generic_commentary_risk"]
            ):
                return None
            existing = connection.execute(
                """
                SELECT * FROM content_opportunities
                WHERE primary_signal_id = ? AND profile_version = ? AND scoring_config_version = ?
                  AND status IN ('candidate', 'saved', 'selected')
                """,
                (signal_id, row["profile_version"], row["scoring_config_version"]),
            ).fetchone()
            if existing is not None:
                return _opportunity_from_row(existing)
            profile = self.profile_agent.get_active_profile(connection)
            if profile is None:
                raise SignalIntelligenceError("An active personal-brand profile is required.")
            profile_data = _profile_data(profile)
            treatment = _suggested_treatment(score, profile_data)
            title = str(row["title"] or "Public signal")
            audience = _first_profile_value(profile_data.target_audiences, "technology professionals")
            model_response = self.model_agent.run_task(
                task_type="content_opportunity_generation",
                prompt=_opportunity_generation_prompt(row, profile_data, score, audience),
                expected_schema={"headline": str, "rationale": str, "suggested_angle": str},
            )
            model_headline, model_rationale, model_angle = _extract_opportunity_fields(model_response)
            headline = model_headline or _opportunity_headline(title)
            rationale = model_rationale or _opportunity_rationale(score, profile_data)
            suggested_angle = model_angle or (
                f"Analyze the practical implication of {title} through a verified, non-generic product lens."
            )
            references = [{"signal_id": signal_id, "url": row["canonical_url"], "source": row["source_name"]}]
            now = _utc_now()
            cursor = connection.execute(
                """
                INSERT INTO content_opportunities (
                    primary_signal_id, supporting_signal_ids_json, profile_version,
                    scoring_config_version, headline, suggested_angle, rationale,
                    target_audience, recommended_format, suggested_treatment,
                    humor_suitability, factual_risk, generic_commentary_risk, score_json,
                    total_score, confidence, source_references_json, status, created_at,
                    updated_at, metadata_json
                ) VALUES (?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, '{}')
                """,
                (
                    signal_id, row["profile_version"], row["scoring_config_version"], headline,
                    suggested_angle,
                    rationale, audience, _first_profile_value(profile_data.preferred_post_formats, "short analysis"),
                    treatment, _score_value(score, "humor_suitability"), deterministic["factual_risk"],
                    deterministic["generic_commentary_risk"], row["score_json"], row["total_score"],
                    row["scoring_confidence"], _canonical_json(references), now, now,
                ),
            )
            connection.commit()
            created = connection.execute(
                "SELECT * FROM content_opportunities WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            logger.info("Content opportunity created: signal_id=%s opportunity_id=%s", signal_id, cursor.lastrowid)
            return _opportunity_from_row(created)
        finally:
            if should_close:
                connection.close()

    def generate_top_content_opportunities(self, database: DatabaseRef, limit: int = 5) -> list[ContentOpportunity]:
        """Create a bounded number of candidate opportunities from highest scored signals."""
        connection, should_close = _coerce_connection(database)
        try:
            config = json.loads(get_active_signal_scoring_config_row(connection)["config_json"])
            bounded = max(1, min(limit, int(config["maximum_opportunities_per_run"])))
            ids = [row["id"] for row in connection.execute(
                """SELECT id FROM signals WHERE status = 'scored' AND eligibility_status = 'eligible'
                ORDER BY total_score DESC, id DESC LIMIT ?""", (bounded,)
            ).fetchall()]
        finally:
            if should_close:
                connection.close()
        return [opportunity for signal_id in ids if (opportunity := self.generate_content_opportunity(signal_id, database)) is not None]

    def list_ranked_signals(self, database: DatabaseRef, limit: int = 20) -> list[dict[str, Any]]:
        """Return scored signals in review order with concise stored reasons."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = connection.execute(
                """SELECT signals.*, signal_sources.name AS source_name FROM signals
                JOIN signal_sources ON signal_sources.id = signals.source_id
                WHERE signals.total_score IS NOT NULL AND signals.eligibility_status = 'eligible' ORDER BY signals.total_score DESC, signals.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [_signal_display(row) for row in rows]
        finally:
            if should_close:
                connection.close()

    def get_scoring_diagnostics(self, database: DatabaseRef) -> dict[str, Any]:
        """Return read-only scoring configuration and recent eligibility evidence."""
        connection, should_close = _coerce_connection(database)
        try:
            config_row = get_active_signal_scoring_config_row(connection)
            config = json.loads(config_row["config_json"])
            rows = connection.execute("SELECT id, eligibility_reasons_json FROM signals WHERE eligibility_status = 'ineligible' ORDER BY scored_at DESC, id DESC LIMIT 100").fetchall()
            results = [{"signal_id": row["id"], "eligible": False, "reasons": _json_list(row["eligibility_reasons_json"])} for row in rows]
            latest = connection.execute("SELECT eligibility_status, COUNT(*) AS count FROM signals WHERE eligibility_status != 'pending' GROUP BY eligibility_status").fetchall()
            return {"config_version": config_row["version"], "maximum_age_days": config["maximum_age_days"], "minimum_final_score": config["minimum_final_score"], "minimum_credibility_score": config["minimum_credibility_score"], "maximum_factual_risk": config["maximum_factual_risk"], "maximum_generic_commentary_risk": config["maximum_generic_commentary_risk"], "model_assisted": config["model_assisted_scoring_enabled"], "latest_counts": {row["eligibility_status"]: row["count"] for row in latest}, "common_ineligibility_reasons": _summarize_ineligibility(results)}
        finally:
            if should_close:
                connection.close()

    def list_content_opportunities(self, database: DatabaseRef, status: str | None = None, limit: int = 20) -> list[ContentOpportunity]:
        """Return reviewable opportunity records, optionally filtered by lifecycle state."""
        query = "SELECT * FROM content_opportunities"
        params: tuple[Any, ...] = ()
        if status is not None:
            if status not in {"candidate", "saved", "selected", "dismissed", "expired"}:
                raise SignalIntelligenceError("Invalid content opportunity status.")
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY total_score DESC, id DESC LIMIT ?"
        connection, should_close = _coerce_connection(database)
        try:
            return [_opportunity_from_row(row) for row in connection.execute(query, (*params, limit)).fetchall()]
        finally:
            if should_close:
                connection.close()

    def get_content_opportunity(self, opportunity_id: int, database: DatabaseRef) -> ContentOpportunity:
        """Return one opportunity or report a clean stale identifier error."""
        connection, should_close = _coerce_connection(database)
        try:
            row = connection.execute("SELECT * FROM content_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
            if row is None:
                raise SignalIntelligenceError(f"Content opportunity id {opportunity_id} does not exist.")
            return _opportunity_from_row(row)
        finally:
            if should_close:
                connection.close()

    def transition_content_opportunity(self, opportunity_id: int, status: str, database: DatabaseRef, reason: str | None = None) -> ContentOpportunity:
        """Apply one guarded human decision; dismissed items cannot be silently selected."""
        allowed = {"saved", "selected", "dismissed"}
        if status not in allowed:
            raise SignalIntelligenceError("Content opportunity status must be saved, selected, or dismissed.")
        connection, should_close = _coerce_connection(database)
        try:
            current = self.get_content_opportunity(opportunity_id, connection)
            if current.status == "dismissed" and status == "selected":
                raise SignalIntelligenceError("Dismissed opportunities require an explicit restore workflow before selection.")
            now = _utc_now()
            connection.execute(
                "UPDATE content_opportunities SET status = ?, decided_at = ?, decision_reason = ?, updated_at = ? WHERE id = ?",
                (status, now, reason, now, opportunity_id),
            )
            connection.commit()
            return self.get_content_opportunity(opportunity_id, connection)
        finally:
            if should_close:
                connection.close()

    def record_preference(self, target_type: str, target_id: int, feedback_type: str, database: DatabaseRef, note: str | None = None, source: str = "telegram") -> None:
        """Persist explicit preference feedback without changing profiles or scoring weights."""
        if target_type not in {"signal", "opportunity"}:
            raise SignalIntelligenceError("Feedback target type must be signal or opportunity.")
        allowed = {"more_like_this", "less_like_this", "save", "dismiss", "not_relevant", "too_generic", "too_risky", "good_angle", "wrong_audience"}
        if feedback_type not in allowed:
            raise SignalIntelligenceError("Unsupported content preference feedback type.")
        connection, should_close = _coerce_connection(database)
        try:
            table = "signals" if target_type == "signal" else "content_opportunities"
            if connection.execute(f"SELECT 1 FROM {table} WHERE id = ?", (target_id,)).fetchone() is None:
                raise SignalIntelligenceError(f"{target_type.capitalize()} id {target_id} does not exist.")
            connection.execute(
                "INSERT INTO content_preference_feedback (target_type, target_id, feedback_type, note, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (target_type, target_id, feedback_type, note, source, _utc_now()),
            )
            connection.commit()
        finally:
            if should_close:
                connection.close()

    def _signal_with_source(self, connection: sqlite3.Connection, signal_id: int) -> sqlite3.Row:
        row = connection.execute(
            """SELECT signals.*, signal_sources.name AS source_name, signal_sources.url AS source_url,
            signal_sources.approval_status AS source_approval_status, signal_sources.enabled AS source_enabled,
            signal_sources.config_json AS source_config_json FROM signals
            JOIN signal_sources ON signal_sources.id = signals.source_id WHERE signals.id = ?""",
            (signal_id,),
        ).fetchone()
        if row is None:
            raise SignalIntelligenceError(f"Signal id {signal_id} does not exist.")
        return row

    def _evaluate_eligibility(self, connection: sqlite3.Connection, row: sqlite3.Row, profile: PersonalBrandProfileData, config: dict[str, Any]) -> tuple[bool, list[str], DeterministicSignalScores]:
        scores = self._deterministic_scores(connection, row, profile, config)
        reasons: list[str] = []
        if row["source_approval_status"] != "approved" or not row["source_enabled"]:
            reasons.append("Source is not approved and enabled.")
        if "linkedin.com" in str(row["source_url"] or "").lower():
            reasons.append("LinkedIn sources are blocked from automatic workflows.")
        if row["status"] in {"duplicate", "failed"}:
            reasons.append(f"Signal status {row['status']} is not eligible.")
        if not row["title"] or not row["summary"] or not row["canonical_url"]:
            reasons.append("Required normalized title, summary, or canonical URL is missing.")
        if scores.credibility < config["minimum_credibility_score"]:
            reasons.append("Source credibility is below the configured minimum.")
        if scores.freshness <= 0:
            reasons.append("Signal is older than the configured freshness window.")
        if scores.factual_risk > config["maximum_factual_risk"]:
            reasons.append("Signal has unacceptable deterministic factual risk.")
        if scores.topic_relevance <= 0:
            reasons.append("Signal has no meaningful overlap with active content pillars.")
        if scores.promotional_content_penalty >= 70:
            reasons.append("Signal is predominantly promotional without an analytical angle.")
        return not reasons, reasons, scores

    def _deterministic_scores(self, connection: sqlite3.Connection, row: sqlite3.Row, profile: PersonalBrandProfileData, config: dict[str, Any]) -> DeterministicSignalScores:
        text = " ".join(str(row[key] or "") for key in ("title", "summary", "author")).lower()
        topic_terms = ("product", "pm", "ai", "artificial intelligence", "cornell", "tech mba", "mba", "strategy", "leadership", "learning", "career")
        topic = min(100.0, 12.5 * sum(term in text for term in topic_terms))
        profile_terms = _keywords(profile.content_pillars + profile.career_focus + profile.institutions)
        audience_terms = _keywords(profile.target_audiences)
        topic = max(topic, min(100.0, 15.0 * sum(term in text for term in profile_terms)))
        audience = min(100.0, 20.0 * sum(term in text for term in audience_terms))
        source_config = _json_object(row["source_config_json"])
        tier = str(source_config.get("credibility_tier", "standard")).lower()
        credibility = {"low": 35.0, "standard": 70.0, "high": 85.0, "official": 95.0}.get(tier, 70.0)
        if row["author"]:
            credibility += 5
        if row["canonical_url"]:
            credibility += 5
        freshness = _freshness_score(row["published_at"], config["freshness_half_life_days"], config["maximum_age_days"])
        recent_topics = connection.execute("SELECT title, summary FROM signals WHERE id != ? ORDER BY created_at DESC LIMIT 30", (row["id"],)).fetchall()
        overlap_count = sum(_token_overlap(text, " ".join(str(item[key] or "") for key in ("title", "summary"))) >= 0.45 for item in recent_topics)
        saturation = connection.execute("SELECT COUNT(*) AS count FROM content_opportunities WHERE status IN ('candidate', 'saved', 'selected') AND headline LIKE ?", (f"%{str(row['title'] or '').split(' ')[0]}%",)).fetchone()["count"]
        originality = max(0.0, 100.0 - overlap_count * 20.0 - max(0, saturation - config["topic_saturation_limit"] + 1) * 25.0)
        personal_terms = _keywords(profile.verified_experiences + profile.allowed_personal_claims)
        identity_terms = _keywords([profile.professional_identity] + profile.career_focus + profile.industries_of_interest)
        personal_angle = min(100.0, 25.0 * sum(term in text for term in personal_terms) + 12.5 * sum(term in text for term in identity_terms))
        risk = 100.0 if any(term in text for term in ("rumor", "unverified", "leak", "speculation")) else 10.0
        if any(term in text for term in ("politics", "election", "confidential")):
            risk = max(risk, 70.0)
        promotional = 80.0 if any(term in text for term in ("sponsored", "buy now", "limited offer", "webinar")) else 0.0
        generic = 70.0 if len(text.split()) < 12 else 20.0
        return DeterministicSignalScores(topic_relevance=topic, audience_relevance=audience, credibility=min(100.0, credibility), freshness=freshness, originality=originality, personal_angle=personal_angle, factual_risk=risk, generic_commentary_risk=generic, promotional_content_penalty=promotional, topic_saturation_penalty=min(100.0, float(saturation) * 20.0))

    def _semantic_scores(self, row: sqlite3.Row, profile: Any, deterministic: DeterministicSignalScores, config: dict[str, Any]) -> tuple[SemanticSignalScores | None, Literal["deterministic", "model_assisted", "deterministic_fallback"], str | None]:
        if not config["model_assisted_scoring_enabled"]:
            return None, "deterministic", None
        schema = {"semantic_profile_relevance": 0.0, "personal_angle_availability": 0.0, "audience_interest_potential": 0.0, "humor_suitability": 0.0, "generic_commentary_risk": 0.0, "factual_risk": 0.0, "suggested_treatment": "", "explanation": "", "confidence": 0.0}
        prompt = "Score this stored public signal without inventing personal experiences. Return JSON only. " + _canonical_json({"title": row["title"], "summary": row["summary"], "deterministic": deterministic.model_dump(), "profile": self.profile_agent.build_personal_brand_context(profile)})
        response = self.model_agent.run_task("signal_semantic_scoring", prompt, expected_schema=schema)
        if response["fallback_used"]:
            return None, "deterministic_fallback", str(
                response.get("fallback_reason") or "model fallback"
            )
        try:
            semantic = SemanticSignalScores.model_validate(response["result"])
            return semantic, "model_assisted", None
        except Exception:
            return None, "deterministic_fallback", "Model output did not satisfy semantic score schema."

    def _build_breakdown(self, deterministic: DeterministicSignalScores, semantic: SemanticSignalScores | None, profile_version: int, config_version: int, config: dict[str, Any], mode: Literal["deterministic", "model_assisted", "deterministic_fallback"], fallback_reason: str | None) -> SignalScoreBreakdown:
        semantic_relevance = semantic.semantic_profile_relevance if semantic else deterministic.topic_relevance
        audience_interest = semantic.audience_interest_potential if semantic else deterministic.audience_relevance
        humor = semantic.humor_suitability if semantic else 0.0
        personal = semantic.personal_angle_availability if semantic else deterministic.personal_angle
        weights = config["weights"]
        positive = (weights["topic_relevance"] * deterministic.topic_relevance + weights["audience_relevance"] * deterministic.audience_relevance + weights["credibility"] * deterministic.credibility + weights["freshness"] * deterministic.freshness + weights["originality"] * deterministic.originality + weights["personal_angle"] * personal + weights["semantic_relevance"] * semantic_relevance + weights["audience_interest"] * audience_interest + weights["humor_suitability"] * humor)
        penalties = 0.12 * deterministic.factual_risk + 0.08 * max(deterministic.generic_commentary_risk, semantic.generic_commentary_risk if semantic else 0) + 0.08 * deterministic.promotional_content_penalty + 0.06 * deterministic.topic_saturation_penalty + (8 if personal < 15 else 0)
        confidence = semantic.confidence if semantic else 0.7
        reasons = [f"Topic relevance {deterministic.topic_relevance:.0f}/100", f"Credibility {deterministic.credibility:.0f}/100", f"Freshness {deterministic.freshness:.0f}/100"]
        return SignalScoreBreakdown(deterministic=deterministic, semantic=semantic, final_score=max(0.0, min(100.0, positive - penalties)), confidence=confidence, formula_version=str(config["formula_version"]), scoring_config_version=config_version, profile_version=profile_version, mode=mode, reasons=reasons, model_identifier="nvidia" if mode == "model_assisted" else None, fallback_reason=fallback_reason)

    def _persist_ineligible(self, connection: sqlite3.Connection, signal_id: int, profile_version: int, config_version: int, reasons: list[str], now: str) -> None:
        connection.execute("UPDATE signals SET profile_version = ?, scoring_config_version = ?, eligibility_status = 'ineligible', eligibility_reasons_json = ?, status = 'ineligible', scored_at = ?, updated_at = ? WHERE id = ?", (profile_version, config_version, _canonical_json(reasons), now, now, signal_id))
        connection.commit()

    def _record_fetch(
        self,
        source_id: int,
        status: str,
        error: str | None,
        etag: str | None,
        last_modified: str | None,
        database: DatabaseRef,
    ) -> None:
        now = _utc_now()
        connection, should_close = _coerce_connection(database)
        try:
            connection.execute(
                """
                UPDATE signal_sources
                SET last_fetched_at = ?, etag = COALESCE(?, etag),
                    last_modified = COALESCE(?, last_modified), last_fetch_status = ?,
                    last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, etag, last_modified, status, error, now, source_id),
            )
            connection.commit()
        finally:
            if should_close:
                connection.close()


def _required_source(connection: sqlite3.Connection, source_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM signal_sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise SignalIntelligenceError(f"Signal source id {source_id} does not exist.")
    return row


def _coerce_connection(database: DatabaseRef) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _source_from_row(row: sqlite3.Row) -> SignalSource:
    return SignalSource(
        id=row["id"], name=row["name"], source_type=row["source_type"], url=row["url"],
        approval_status=row["approval_status"], enabled=bool(row["enabled"]),
        approved_at=row["approved_at"], last_fetched_at=row["last_fetched_at"],
        etag=row["etag"], last_modified=row["last_modified"],
        last_fetch_status=row["last_fetch_status"], last_error=row["last_error"],
        config_json=row["config_json"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _signal_from_row(row: sqlite3.Row) -> Signal:
    return Signal(
        id=row["id"], source_id=row["source_id"], external_id=row["external_id"],
        canonical_url=row["canonical_url"], title=row["title"], summary=row["summary"],
        author=row["author"], published_at=row["published_at"],
        updated_at_source=row["updated_at_source"], fetched_at=row["fetched_at"],
        content_hash=row["content_hash"], dedupe_key=row["dedupe_key"],
        duplicate_of_id=row["duplicate_of_id"], raw_payload_json=row["raw_payload_json"],
        normalized_json=row["normalized_json"], status=row["status"],
        error_message=row["error_message"], profile_version=row["profile_version"],
        scoring_config_version=row["scoring_config_version"], score_json=row["score_json"],
        total_score=row["total_score"], scoring_confidence=row["scoring_confidence"],
        scoring_mode=row["scoring_mode"], scored_at=row["scored_at"],
        eligibility_status=row["eligibility_status"], eligibility_reasons_json=row["eligibility_reasons_json"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _opportunity_from_row(row: sqlite3.Row) -> ContentOpportunity:
    return ContentOpportunity(**dict(row))


def _profile_data(profile: Any) -> PersonalBrandProfileData:
    return PersonalBrandProfileData.model_validate_json(profile.profile_json)


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _keywords(values: list[str]) -> set[str]:
    return {word for value in values for word in value.lower().replace("-", " ").split() if len(word) > 2}


def _freshness_score(published_at: str | None, half_life_days: int, maximum_age_days: int) -> float:
    if not published_at:
        return 35.0
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return 25.0
    age_days = max(0.0, (datetime.now(UTC) - published).total_seconds() / 86400)
    if age_days > maximum_age_days:
        return 0.0
    return max(0.0, min(100.0, 100.0 * math.pow(0.5, age_days / max(1, half_life_days))))


def _age_days(published_at: str | None) -> int | None:
    if not published_at:
        return None
    try:
        value = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if value.tzinfo is None:
            return None
        return max(0, int((datetime.now(UTC) - value.astimezone(UTC)).total_seconds() // 86400))
    except ValueError:
        return None


def _profile_matches(row: sqlite3.Row, profile: PersonalBrandProfileData) -> list[str]:
    text = f"{row['title'] or ''} {row['summary'] or ''}".lower()
    return sorted({term for term in _keywords(profile.content_pillars + profile.career_focus + profile.institutions) if term in text})[:10]


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _summarize_ineligibility(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[int]] = {}
    for result in results:
        for reason in result.get("reasons", []):
            label = "stale" if "older than" in reason else "credibility below threshold" if "credibility" in reason else "no profile overlap" if "overlap" in reason else reason
            grouped.setdefault(label, []).append(int(result["signal_id"]))
    return [{"reason": reason, "count": len(ids), "example_ids": ids[:3]} for reason, ids in sorted(grouped.items(), key=lambda item: -len(item[1]))]


def _token_overlap(first: str, second: str) -> float:
    first_tokens = set(first.lower().split())
    second_tokens = set(second.lower().split())
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / min(len(first_tokens), len(second_tokens))


def _first_profile_value(values: list[str], default: str) -> str:
    return values[0] if values else default


def _score_value(score: dict[str, Any], field: str) -> float:
    semantic = score.get("semantic") or {}
    return float(semantic.get(field, 0.0))


def _opportunity_headline(title: str) -> str:
    return f"A product lens on {title}"[:200]


def _opportunity_generation_prompt(
    row: sqlite3.Row,
    profile: PersonalBrandProfileData,
    score: dict[str, Any],
    audience: str,
) -> str:
    """Build a bounded, source-grounded opportunity prompt."""
    deterministic = score.get("deterministic") or {}
    return "\n".join(
        [
            "Prepare a review-only LinkedIn content opportunity, not a post draft.",
            "Return JSON with headline, rationale, and suggested_angle.",
            "Use only the supplied source and personal-brand profile.",
            "Do not invent experience, credentials, outcomes, relationships, or source facts.",
            f"Source title: {row['title'] or 'Untitled'}",
            f"Source summary: {row['summary'] or 'No summary supplied.'}",
            f"Source URL: {row['canonical_url']}",
            f"Professional identity: {profile.professional_identity}",
            f"Content pillars: {', '.join(profile.content_pillars)}",
            f"Target audience: {audience}",
            f"Topic relevance score: {deterministic.get('topic_relevance', 0)}",
            "The headline must name a concrete angle. The rationale must explain profile fit. "
            "The suggested angle must remain analytical and source-grounded.",
        ]
    )


def _extract_opportunity_fields(
    response: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Return validated optional model fields; callers retain deterministic fallbacks."""
    if response.get("fallback_used"):
        return None, None, None
    result = response.get("result")
    if not isinstance(result, dict):
        return None, None, None

    def field(name: str, maximum: int) -> str | None:
        value = result.get(name)
        if not isinstance(value, str):
            return None
        cleaned = " ".join(value.split())
        return cleaned[:maximum] if cleaned else None

    return field("headline", 200), field("rationale", 1000), field("suggested_angle", 1000)


def _suggested_treatment(score: dict[str, Any], profile: PersonalBrandProfileData) -> str:
    semantic = score.get("semantic") or {}
    treatment = semantic.get("suggested_treatment")
    if isinstance(treatment, str) and treatment.strip():
        return treatment.strip()[:300]
    if profile.verified_experiences:
        return "experience-backed analytical observation"
    return "analytical observation grounded in verified profile context"


def _opportunity_rationale(score: dict[str, Any], profile: PersonalBrandProfileData) -> str:
    deterministic = score["deterministic"]
    identity = profile.professional_identity
    verified = " It does not claim an unverified personal experience." if not profile.verified_experiences else " It can be anchored in the profile's verified experience list."
    return f"Fits {identity} through its product and audience relevance (topic {deterministic['topic_relevance']:.0f}/100).{verified}"[:1000]


def _signal_display(row: sqlite3.Row) -> dict[str, Any]:
    return {**_signal_from_row(row).model_dump(), "source_name": row["source_name"]}


def _required_text(value: str, label: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise SignalIntelligenceError(f"{label} is required.")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()
        except ValueError:
            return _clean_optional(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _scan_summary(
    source_id: int,
    status: str,
    *,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    not_modified: bool = False,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "status": status,
        "items_fetched": 0,
        "new_signals": 0,
        "duplicates": 0,
        "failures": 0 if status != "failed" else 1,
        "not_modified": not_modified,
        "warnings": warnings or [],
        "errors": errors or [],
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
