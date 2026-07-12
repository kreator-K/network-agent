"""Tests for deterministic public-signal persistence and deduplication."""

from pathlib import Path

import pytest

from agents.signal_intelligence_agent import (
    SignalIntelligenceAgent,
    SignalSourceStateError,
)
from db.database import initialize_database
from integrations.public_signal_gateway import FeedFetchResult, RawFeedItem


def _item(
    external_id: str | None = "guid-1",
    link: str | None = "https://example.com/post?utm_source=test",
) -> RawFeedItem:
    return RawFeedItem(
        external_id=external_id,
        title="  AI Product News  ",
        summary="  Useful summary.  ",
        author="  Ada  ",
        published_at="Tue, 10 Jun 2025 10:00:00 GMT",
        updated_at=None,
        link=link,
        raw_metadata={"guid": external_id},
    )


def _database_path(tmp_path: Path) -> Path:
    path = tmp_path / "network_agent.db"
    initialize_database(path)
    return path


def test_source_requires_approval_and_enablement_before_scan(tmp_path: Path) -> None:
    database_path = _database_path(tmp_path)
    agent = SignalIntelligenceAgent()
    source = agent.add_source("Example", "https://example.com/feed", database=database_path)

    with pytest.raises(SignalSourceStateError, match="approved"):
        agent.ingest_source(source.id or 0, database_path)

    approved = agent.set_source_approval(source.id or 0, "approved", database_path)
    assert approved.approved_at is not None
    with pytest.raises(SignalSourceStateError, match="enabled"):
        agent.ingest_source(source.id or 0, database_path)


def test_ingestion_normalizes_and_deduplicates_repeated_feed_items(tmp_path: Path) -> None:
    database_path = _database_path(tmp_path)
    feed = FeedFetchResult(
        source_url="https://example.com/feed",
        http_status=200,
        fetched_at="2026-01-01T00:00:00+00:00",
        etag='"tag"',
        last_modified=None,
        feed_title="Example",
        items=[_item()],
    )
    agent = SignalIntelligenceAgent(gateway=lambda request: feed)
    source = agent.add_source("Example", "https://example.com/feed", database=database_path)
    agent.set_source_approval(source.id or 0, "approved", database_path)
    agent.set_source_enabled(source.id or 0, True, database_path)

    first = agent.ingest_source(source.id or 0, database_path)
    second = agent.ingest_source(source.id or 0, database_path)
    signals = agent.get_recent_signals(database_path)

    assert first["new_signals"] == 1
    assert second["duplicates"] == 1
    assert len(signals) == 1
    assert signals[0]["title"] == "AI Product News"
    assert signals[0]["canonical_url"] == "https://example.com/post"
    assert signals[0]["content_hash"]
    assert signals[0]["dedupe_key"] == "external:1:guid-1"


def test_cross_source_duplicate_retains_source_provenance(tmp_path: Path) -> None:
    database_path = _database_path(tmp_path)
    agent = SignalIntelligenceAgent()
    first = agent.add_source("One", "https://example.com/one", database=database_path)
    second = agent.add_source("Two", "https://example.org/two", database=database_path)
    primary = agent.persist_signal(first.id or 0, _item("one", "https://news.example/item"), database_path)
    duplicate = agent.persist_signal(second.id or 0, _item("two", "https://news.example/item"), database_path)

    assert primary["result"] == "new"
    assert duplicate["result"] == "duplicate"
    assert duplicate["signal"].duplicate_of_id == primary["signal"].id


def test_normalization_and_hashing_are_deterministic() -> None:
    agent = SignalIntelligenceAgent()
    normalized = agent.normalize_feed_item(_item())

    assert normalized["title"] == "AI Product News"
    assert agent.generate_content_hash(normalized) == agent.generate_content_hash(normalized)
    assert agent.generate_dedupe_key(7, normalized) == "external:7:guid-1"
