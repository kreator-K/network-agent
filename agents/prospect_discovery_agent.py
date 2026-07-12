"""Prospect intake and normalization agent."""

from datetime import UTC, datetime
import json
import sqlite3
from pathlib import Path
from typing import Protocol

from agents.relationship_tracker_agent import (
    ProspectNotFoundError,
)
from db.database import connect, get_active_signal_scoring_config_row
from db.models import Prospect, ProspectCandidate


class ProspectDiscoveryError(ValueError):
    """Base error for prospect discovery intake failures."""


class InvalidProspectNameError(ProspectDiscoveryError):
    """Raised when a prospect name is missing or empty."""


class InvalidProfileUrlError(ProspectDiscoveryError):
    """Raised when a provided profile URL is not a LinkedIn URL."""


class TrackerProtocol(Protocol):
    """Minimal tracker interface required by ProspectDiscoveryAgent."""

    def add_prospect(
        self,
        name: str,
        profile_url: str | None = None,
        location: str | None = None,
        role_title: str | None = None,
        company: str | None = None,
        notes: str | None = None,
    ) -> Prospect:
        """Add a prospect to storage."""


class NotesTrackerProtocol(TrackerProtocol, Protocol):
    """Tracker interface required for note enrichment."""

    def get_prospect(self, prospect_id: int) -> Prospect:
        """Return one prospect by ID."""

    def update_prospect_notes(self, prospect_id: int, notes: str) -> Prospect:
        """Update prospect notes and return the changed prospect."""


class ProspectDiscoveryAgent:
    """Normalize manually provided prospect information.

    Purpose:
        Intake prospect name, LinkedIn URL, copied profile text, and notes
        without scraping or programmatic LinkedIn search.
    Inputs:
        User-provided prospect fields such as name, profile URL, company,
        title, location, notes, and profile text.
    Outputs:
        A structured prospect record via RelationshipTrackerAgent.
    """

    def intake_prospect(
        self,
        name: str,
        profile_url: str | None = None,
        location: str | None = None,
        role_title: str | None = None,
        company: str | None = None,
        notes: str | None = None,
        tracker: TrackerProtocol | None = None,
    ) -> Prospect:
        """Validate and add a manually supplied prospect."""
        if tracker is None:
            raise ProspectDiscoveryError("A RelationshipTrackerAgent is required.")
        cleaned_name = _clean_name(name)
        cleaned_profile_url = _clean_profile_url(profile_url)
        cleaned_location = _normalize_location(location)
        return tracker.add_prospect(
            name=cleaned_name,
            profile_url=cleaned_profile_url,
            location=cleaned_location,
            role_title=_clean_optional(role_title),
            company=_clean_optional(company),
            notes=_clean_optional(notes),
        )

    def intake_bulk(
        self,
        prospects: list[dict],
        tracker: TrackerProtocol,
    ) -> dict:
        """Add valid prospect rows and skip invalid rows with reasons."""
        added: list[Prospect] = []
        skipped: list[dict] = []
        for index, row in enumerate(prospects):
            try:
                added.append(
                    self.intake_prospect(
                        name=row.get("name", ""),
                        profile_url=row.get("profile_url"),
                        location=row.get("location"),
                        role_title=row.get("role_title"),
                        company=row.get("company"),
                        notes=row.get("notes"),
                        tracker=tracker,
                    )
                )
            except ProspectDiscoveryError as exc:
                skipped.append({"index": index, "row": row, "reason": str(exc)})
        return {"added": added, "skipped": skipped}

    def enrich_notes(
        self,
        prospect_id: int,
        additional_notes: str,
        tracker: NotesTrackerProtocol,
    ) -> Prospect:
        """Append notes to an existing prospect instead of overwriting them."""
        cleaned_notes = _clean_optional(additional_notes)
        if not cleaned_notes:
            raise ProspectDiscoveryError("additional_notes must not be empty.")
        try:
            prospect = tracker.get_prospect(prospect_id)
        except ProspectNotFoundError:
            raise
        except Exception as exc:
            raise ProspectDiscoveryError(
                f"Prospect id {prospect_id} does not exist."
            ) from exc

        timestamp = datetime.now(UTC).isoformat()
        separator = f"\n\n[{timestamp}] "
        updated_notes = f"{prospect.notes or ''}{separator}{cleaned_notes}".strip()
        return tracker.update_prospect_notes(prospect_id, updated_notes)

    def extract_candidates_from_signals(self, database: sqlite3.Connection | str | Path, limit: int = 20) -> list[ProspectCandidate]:
        """Create source-backed candidates from stored public author metadata only."""
        connection, close = _connection(database)
        try:
            profile = connection.execute("SELECT * FROM personal_brand_profile WHERE is_active = 1").fetchone()
            config = get_active_signal_scoring_config_row(connection)
            if profile is None:
                raise ProspectDiscoveryError("An active personal-brand profile is required.")
            rows = connection.execute("SELECT signals.*, signal_sources.name AS source_name FROM signals JOIN signal_sources ON signal_sources.id = signals.source_id WHERE signals.status IN ('normalized','scored') AND signals.author IS NOT NULL ORDER BY signals.total_score DESC, signals.id DESC LIMIT ?", (limit,)).fetchall()
            candidates: list[ProspectCandidate] = []
            for row in rows:
                name = _clean_optional(row["author"])
                if not name or len(name.split()) < 2:
                    continue
                normalized = " ".join(name.lower().split())
                crm = connection.execute("SELECT id FROM prospects WHERE lower(name) = ? LIMIT 1", (normalized,)).fetchone()
                existing = connection.execute("SELECT * FROM prospect_candidates WHERE normalized_name = ? AND source_signal_ids_json LIKE ? LIMIT 1", (normalized, f"%{row['id']}%" )).fetchone()
                if existing is not None:
                    continue
                total = float(row["total_score"] or 45.0)
                now = datetime.now(UTC).isoformat()
                references = [{"signal_id": row["id"], "source": row["source_name"], "url": row["canonical_url"]}]
                cursor = connection.execute("INSERT INTO prospect_candidates (full_name, normalized_name, professional_summary, source_signal_ids_json, source_references_json, relevant_topics_json, recommended_ask_type, recommended_rationale, profile_version, scoring_config_version, score_json, total_score, confidence, source_credibility_score, matching_prospect_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'general_chat', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (name, normalized, row["summary"], json.dumps([row["id"]]), json.dumps(references), json.dumps(_topics(row["title"] or "")), "Public author metadata from an approved stored signal aligns with the active networking goals.", profile["version"], config["version"], json.dumps({"signal_score": total}), total, 0.7, 70.0, None if crm is None else crm["id"], "duplicate" if crm else "discovered", now, now))
                created = connection.execute("SELECT * FROM prospect_candidates WHERE id = ?", (cursor.lastrowid,)).fetchone()
                candidates.append(ProspectCandidate(**dict(created)))
            connection.commit()
            return candidates
        finally:
            if close:
                connection.close()

    def list_candidates(self, database: sqlite3.Connection | str | Path, limit: int = 20) -> list[ProspectCandidate]:
        connection, close = _connection(database)
        try:
            return [ProspectCandidate(**dict(row)) for row in connection.execute("SELECT * FROM prospect_candidates ORDER BY total_score DESC, id DESC LIMIT ?", (limit,)).fetchall()]
        finally:
            if close:
                connection.close()

    def approve_candidate(self, candidate_id: int, tracker: TrackerProtocol, database: sqlite3.Connection | str | Path) -> Prospect:
        """Convert an explicitly approved candidate into CRM prospect data."""
        connection, close = _connection(database)
        try:
            row = connection.execute("SELECT * FROM prospect_candidates WHERE id = ?", (candidate_id,)).fetchone()
            if row is None:
                raise ProspectDiscoveryError(f"Candidate id {candidate_id} does not exist.")
            if row["status"] in {"rejected", "duplicate", "added_to_crm"}:
                raise ProspectDiscoveryError("Candidate cannot be added to CRM from its current state.")
            prospect = tracker.add_prospect(name=row["full_name"], profile_url=row["public_profile_url"], location=row["location"], role_title=row["role_title"], company=row["company"], notes=f"Approved public-source candidate. {row['recommended_rationale']}")
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "UPDATE prospect_candidates SET status = 'added_to_crm', matching_prospect_id = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                (prospect.id, now, now, candidate_id),
            )
            connection.commit()
            return prospect
        finally:
            if close:
                connection.close()


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise InvalidProspectNameError("Prospect name must not be empty.")
    return " ".join(cleaned.split())


def _clean_profile_url(profile_url: str | None) -> str | None:
    cleaned = _clean_optional(profile_url)
    if cleaned is None:
        return None
    lowered = cleaned.lower()
    if "linkedin.com" not in lowered:
        raise InvalidProfileUrlError("profile_url must be a linkedin.com URL.")
    return cleaned


def _normalize_location(location: str | None) -> str | None:
    cleaned = _clean_optional(location)
    if cleaned is None:
        return None
    return " ".join(cleaned.split()).title()


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _connection(database: sqlite3.Connection | str | Path) -> tuple[sqlite3.Connection, bool]:
    return (database, False) if isinstance(database, sqlite3.Connection) else (connect(database), True)


def _topics(value: str) -> list[str]:
    return [term for term in ("product management", "AI products", "strategy") if term.split()[0].lower() in value.lower()]
