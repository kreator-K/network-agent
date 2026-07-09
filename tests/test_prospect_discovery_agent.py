"""Tests for ProspectDiscoveryAgent manual intake behavior."""

import pytest

from agents.prospect_discovery_agent import (
    InvalidProfileUrlError,
    InvalidProspectNameError,
    ProspectDiscoveryAgent,
    ProspectDiscoveryError,
)
from db.models import Prospect


class FakeTracker:
    """In-memory fake for RelationshipTrackerAgent behavior."""

    def __init__(self) -> None:
        self.added: list[dict] = []
        self.prospects: dict[int, Prospect] = {}
        self.next_id = 1

    def add_prospect(
        self,
        name: str,
        profile_url: str | None = None,
        location: str | None = None,
        role_title: str | None = None,
        company: str | None = None,
        notes: str | None = None,
    ) -> Prospect:
        payload = {
            "name": name,
            "profile_url": profile_url,
            "location": location,
            "role_title": role_title,
            "company": company,
            "notes": notes,
        }
        self.added.append(payload)
        prospect = Prospect(
            id=self.next_id,
            name=name,
            profile_url=profile_url,
            location=location,
            role_title=role_title,
            company=company,
            notes=notes,
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        self.prospects[self.next_id] = prospect
        self.next_id += 1
        return prospect

    def get_prospect(self, prospect_id: int) -> Prospect:
        try:
            return self.prospects[prospect_id]
        except KeyError as exc:
            raise ProspectDiscoveryError(
                f"Prospect id {prospect_id} does not exist."
            ) from exc

    def update_prospect_notes(self, prospect_id: int, notes: str) -> Prospect:
        prospect = self.get_prospect(prospect_id)
        updated = prospect.model_copy(update={"notes": notes})
        self.prospects[prospect_id] = updated
        return updated


def test_intake_prospect_creates_via_tracker() -> None:
    tracker = FakeTracker()

    prospect = ProspectDiscoveryAgent().intake_prospect(
        name=" Ada Lovelace ",
        profile_url="https://www.linkedin.com/in/ada",
        location="  new york, ny ",
        role_title=" Research Lead ",
        company=" Analytical Engines ",
        notes=" Met at event. ",
        tracker=tracker,
    )

    assert prospect.name == "Ada Lovelace"
    assert prospect.location == "New York, Ny"
    assert tracker.added == [
        {
            "name": "Ada Lovelace",
            "profile_url": "https://www.linkedin.com/in/ada",
            "location": "New York, Ny",
            "role_title": "Research Lead",
            "company": "Analytical Engines",
            "notes": "Met at event.",
        }
    ]


def test_intake_prospect_rejects_empty_name() -> None:
    with pytest.raises(InvalidProspectNameError, match="must not be empty"):
        ProspectDiscoveryAgent().intake_prospect("", tracker=FakeTracker())


def test_intake_prospect_rejects_whitespace_only_name() -> None:
    with pytest.raises(InvalidProspectNameError, match="must not be empty"):
        ProspectDiscoveryAgent().intake_prospect("   ", tracker=FakeTracker())


def test_intake_prospect_validates_linkedin_url_format() -> None:
    with pytest.raises(InvalidProfileUrlError, match="linkedin.com"):
        ProspectDiscoveryAgent().intake_prospect(
            "Ada Lovelace",
            profile_url="https://example.com/ada",
            tracker=FakeTracker(),
        )


def test_intake_prospect_allows_missing_optional_fields() -> None:
    prospect = ProspectDiscoveryAgent().intake_prospect(
        "Ada Lovelace",
        tracker=FakeTracker(),
    )

    assert prospect.name == "Ada Lovelace"
    assert prospect.profile_url is None
    assert prospect.location is None


def test_intake_bulk_adds_all_valid_rows() -> None:
    tracker = FakeTracker()
    result = ProspectDiscoveryAgent().intake_bulk(
        [
            {"name": "Ada Lovelace"},
            {"name": "Grace Hopper", "profile_url": "linkedin.com/in/grace"},
        ],
        tracker,
    )

    assert [prospect.name for prospect in result["added"]] == [
        "Ada Lovelace",
        "Grace Hopper",
    ]
    assert result["skipped"] == []


def test_intake_bulk_skips_invalid_rows_without_failing_entire_batch() -> None:
    tracker = FakeTracker()
    result = ProspectDiscoveryAgent().intake_bulk(
        [{"name": "Ada Lovelace"}, {"name": ""}, {"name": "Grace Hopper"}],
        tracker,
    )

    assert [prospect.name for prospect in result["added"]] == [
        "Ada Lovelace",
        "Grace Hopper",
    ]
    assert len(result["skipped"]) == 1


def test_intake_bulk_returns_skip_reasons() -> None:
    result = ProspectDiscoveryAgent().intake_bulk(
        [{"name": "  "}],
        FakeTracker(),
    )

    assert result["skipped"][0]["index"] == 0
    assert "must not be empty" in result["skipped"][0]["reason"]


def test_enrich_notes_appends_rather_than_overwrites() -> None:
    tracker = FakeTracker()
    prospect = tracker.add_prospect("Ada Lovelace", notes="Original note")

    updated = ProspectDiscoveryAgent().enrich_notes(
        prospect_id=prospect.id or 0,
        additional_notes="New note",
        tracker=tracker,
    )

    assert updated.notes is not None
    assert "Original note" in updated.notes
    assert "New note" in updated.notes
    assert updated.notes != "New note"


def test_enrich_notes_raises_for_invalid_prospect_id() -> None:
    with pytest.raises(ProspectDiscoveryError, match="does not exist"):
        ProspectDiscoveryAgent().enrich_notes(
            prospect_id=999,
            additional_notes="New note",
            tracker=FakeTracker(),
        )
