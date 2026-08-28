"""Feature-flag and parity tests for graph-backed signal ingestion."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest

from agents.orchestrator import NetworkOrchestrator, NetworkOrchestratorError
from agents.signal_intelligence_agent import SignalIntelligenceAgent
from db.database import connect, initialize_database
from integrations.public_signal_gateway import (
    FeedFetchResult,
    PublicSignalGatewayError,
    RawFeedItem,
)
from workflows.signal_intelligence import run_signal_ingestion_graph


def _database_path(tmp_path: Path, name: str = "network_agent.db") -> Path:
    path = tmp_path / name
    initialize_database(path)
    return path


def _item(source_id: int) -> RawFeedItem:
    return RawFeedItem(
        external_id=f"guid-{source_id}",
        title=f"AI product signal {source_id}",
        summary="A sufficiently detailed product and AI strategy update.",
        author="Editorial team",
        published_at=datetime.now(UTC).isoformat(),
        updated_at=None,
        link=f"https://news.example.com/items/{source_id}",
        raw_metadata={},
    )


def _feed(source_id: int) -> FeedFetchResult:
    return FeedFetchResult(
        source_url=f"https://example{source_id}.com/feed",
        http_status=200,
        fetched_at=datetime.now(UTC).isoformat(),
        etag=f'"etag-{source_id}"',
        last_modified=None,
        feed_title=f"Feed {source_id}",
        items=[_item(source_id)],
    )


def _add_enabled_sources(
    agent: SignalIntelligenceAgent,
    database: Path,
    count: int,
) -> list[int]:
    source_ids: list[int] = []
    for number in range(1, count + 1):
        source = agent.add_source(
            f"Source {number}",
            f"https://example{number}.com/feed",
            database=database,
        )
        source_id = source.id or 0
        agent.set_source_approval(source_id, "approved", database)
        agent.set_source_enabled(source_id, True, database)
        source_ids.append(source_id)
    return source_ids


def test_signal_graph_fetches_independent_sources_in_parallel_then_persists(
    tmp_path: Path,
) -> None:
    database = _database_path(tmp_path)
    barrier = Barrier(2, timeout=1)

    def gateway(request):  # type: ignore[no-untyped-def]
        barrier.wait()
        return _feed(request.source_id)

    agent = SignalIntelligenceAgent(gateway=gateway)
    _add_enabled_sources(agent, database, 2)

    result = run_signal_ingestion_graph(agent, database, max_workers=2)

    assert result["execution_mode"] == "graph"
    assert result["sources_scanned"] == 2
    assert result["new_signals"] == 2
    assert result["failures"] == 0
    assert result["workflow"]["status"] == "completed"
    assert result["workflow"]["nodes"]["persist_fetches"]["attempts"] == 1
    assert len(agent.get_recent_signals(database)) == 2


def test_signal_graph_isolates_expected_fetch_failures(tmp_path: Path) -> None:
    database = _database_path(tmp_path)

    def gateway(request):  # type: ignore[no-untyped-def]
        if request.source_id == 1:
            raise PublicSignalGatewayError("upstream detail must not escape")
        return _feed(request.source_id)

    agent = SignalIntelligenceAgent(gateway=gateway)
    _add_enabled_sources(agent, database, 2)

    result = run_signal_ingestion_graph(agent, database, max_workers=2)

    assert result["sources_scanned"] == 2
    assert result["new_signals"] == 1
    assert result["failures"] == 1
    assert result["workflow"]["status"] == "completed"
    assert "upstream detail" not in str(result)
    with connect(database) as connection:
        failed = connection.execute(
            "SELECT last_fetch_status, last_error FROM signal_sources WHERE id = 1"
        ).fetchone()
    assert failed["last_fetch_status"] == "failed"
    assert failed["last_error"] == "Public feed request failed."


def test_graph_and_control_paths_produce_matching_ingestion_summaries(
    tmp_path: Path,
) -> None:
    control_database = _database_path(tmp_path, "control.db")
    graph_database = _database_path(tmp_path, "graph.db")
    control_agent = SignalIntelligenceAgent(
        gateway=lambda request: _feed(request.source_id)
    )
    graph_agent = SignalIntelligenceAgent(
        gateway=lambda request: _feed(request.source_id)
    )
    _add_enabled_sources(control_agent, control_database, 2)
    _add_enabled_sources(graph_agent, graph_database, 2)

    control = control_agent.ingest_enabled_sources(control_database)
    graph = run_signal_ingestion_graph(graph_agent, graph_database, max_workers=2)

    for field in ("sources_scanned", "new_signals", "duplicates", "failures"):
        assert graph[field] == control[field]
    assert [item["source_id"] for item in graph["results"]] == [
        item["source_id"] for item in control["results"]
    ]


def test_shadow_mode_runs_control_once_and_reports_selection_parity(
    tmp_path: Path,
) -> None:
    database = _database_path(tmp_path)
    calls: list[int] = []

    def gateway(request):  # type: ignore[no-untyped-def]
        calls.append(request.source_id)
        return _feed(request.source_id)

    agent = SignalIntelligenceAgent(gateway=gateway)
    _add_enabled_sources(agent, database, 2)
    orchestrator = NetworkOrchestrator(signal_intelligence_agent=agent)

    result = orchestrator.scan_enabled_signal_sources(
        database=database,
        graph_mode="shadow",
    )

    assert sorted(calls) == [1, 2]
    assert result["execution_mode"] == "control_with_graph_shadow"
    assert result["graph_shadow"]["executed"] is False
    assert result["graph_shadow"]["selection_parity"] is True
    assert result["graph_shadow"]["source_ids"] == [2, 1]


def test_enabled_graph_rejects_shared_sqlite_connection(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    agent = SignalIntelligenceAgent(gateway=lambda request: _feed(request.source_id))
    _add_enabled_sources(agent, database, 1)
    orchestrator = NetworkOrchestrator(signal_intelligence_agent=agent)

    connection = sqlite3.connect(database)
    try:
        with pytest.raises(NetworkOrchestratorError, match="database path"):
            orchestrator.scan_enabled_signal_sources(
                database=connection,
                graph_mode="enabled",
            )
    finally:
        connection.close()


def test_invalid_graph_mode_fails_closed(tmp_path: Path) -> None:
    database = _database_path(tmp_path)
    orchestrator = NetworkOrchestrator()

    with pytest.raises(NetworkOrchestratorError, match="disabled, shadow, or enabled"):
        orchestrator.scan_enabled_signal_sources(
            database=database,
            graph_mode="dynamic",
        )
