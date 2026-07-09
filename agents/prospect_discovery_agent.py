"""Prospect intake and normalization agent."""

from datetime import UTC, datetime
from typing import Protocol

from agents.relationship_tracker_agent import (
    ProspectNotFoundError,
    RelationshipTrackerAgent,
)
from db.models import Prospect


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
        tracker: RelationshipTrackerAgent,
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
