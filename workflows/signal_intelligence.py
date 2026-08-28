"""Feature-flagged graph workflow for approved public-signal ingestion."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.signal_intelligence_agent import SignalIntelligenceAgent
from integrations.public_signal_gateway import (
    FeedFetchResult,
    PublicSignalSourceRequest,
    RawFeedItem,
)
from workflows.contracts import MAX_GRAPH_NODES, NodeContract, WorkflowDefinition
from workflows.engine import GraphWorkflowEngine
from workflows.persistence import save_workflow_run


logger = logging.getLogger(__name__)
SignalDatabaseRef = sqlite3.Connection | str | Path
SignalDatabasePath = str | Path


class SignalGraphConfigurationError(ValueError):
    """Raised when the signal graph cannot execute safely."""


class SignalGraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalIngestionInput(SignalGraphModel):
    source_ids: list[int] = Field(default_factory=list, max_length=64)


class SignalFetchInput(SignalGraphModel):
    source_id: int = Field(gt=0)
    url: str
    source_type: str
    etag: str | None = None
    last_modified: str | None = None


class RawFeedItemArtifact(SignalGraphModel):
    external_id: str | None = None
    title: str | None = None
    summary: str | None = None
    author: str | None = None
    published_at: str | None = None
    updated_at: str | None = None
    link: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class SignalFetchArtifact(SignalGraphModel):
    source_id: int = Field(gt=0)
    status: Literal["success", "not_modified", "failed"]
    source_url: str
    http_status: int | None = None
    fetched_at: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    feed_title: str | None = None
    items: list[RawFeedItemArtifact] = Field(default_factory=list)
    not_modified: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class PersistFetchesInput(SignalGraphModel):
    fetches: list[SignalFetchArtifact]


class SourceScanResult(SignalGraphModel):
    source_id: int
    status: str
    items_fetched: int = 0
    new_signals: int = 0
    duplicates: int = 0
    failures: int = 0
    not_modified: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SignalIngestionSummary(SignalGraphModel):
    sources_scanned: int
    new_signals: int
    duplicates: int
    failures: int
    results: list[SourceScanResult]


def enabled_source_ids(
    agent: SignalIntelligenceAgent,
    database: SignalDatabaseRef,
) -> list[int]:
    """Return the deterministic source selection shared by control and graph paths."""
    return [
        source.id
        for source in agent.list_sources(database, limit=1000)
        if source.id is not None
        and source.approval_status == "approved"
        and source.enabled
    ]


def signal_graph_preview(
    agent: SignalIntelligenceAgent,
    database: SignalDatabaseRef,
) -> dict[str, Any]:
    """Describe the graph selection without fetching or writing anything."""
    source_ids = enabled_source_ids(agent, database)
    return {
        "workflow": "signal_ingestion",
        "workflow_version": 1,
        "source_ids": source_ids,
        "fetch_nodes": len(source_ids),
        "persistence_nodes": 1 if source_ids else 0,
        "executed": False,
    }


def run_signal_ingestion_graph(
    agent: SignalIntelligenceAgent,
    database: SignalDatabasePath,
    *,
    max_workers: int = 4,
) -> dict[str, Any]:
    """Fetch approved sources in parallel and persist them sequentially."""
    source_ids = enabled_source_ids(agent, database)
    if not source_ids:
        return {
            "sources_scanned": 0,
            "new_signals": 0,
            "duplicates": 0,
            "failures": 0,
            "results": [],
            "execution_mode": "graph",
            "workflow": None,
        }
    maximum_sources = MAX_GRAPH_NODES - 1
    if len(source_ids) > maximum_sources:
        raise SignalGraphConfigurationError(
            f"Signal graph supports at most {maximum_sources} sources per run."
        )

    sources = {source.id: source for source in agent.list_sources(database, limit=1000)}
    fetch_nodes = tuple(
        _fetch_node(agent, sources[source_id].model_dump())
        for source_id in source_ids
    )
    persist_node = _persist_node(agent, database, source_ids)
    definition = WorkflowDefinition(
        name="signal_ingestion",
        version=1,
        input_schema=SignalIngestionInput,
        nodes=(*fetch_nodes, persist_node),
    )
    run = GraphWorkflowEngine(max_workers=max_workers).run(
        definition,
        {"source_ids": source_ids},
    )
    save_workflow_run(
        database,
        run,
        metadata={"source_ids": source_ids, "execution_mode": "graph"},
    )
    persisted = run.nodes["persist_fetches"]
    if persisted.output is None:
        raise SignalGraphConfigurationError(
            "Signal graph did not reach its controlled persistence boundary."
        )
    summary = SignalIngestionSummary.model_validate(persisted.output).model_dump()
    summary.update(
        {
            "execution_mode": "graph",
            "workflow": run.model_dump(mode="json"),
        }
    )
    return summary


def _fetch_node(
    agent: SignalIntelligenceAgent,
    source: dict[str, Any],
) -> NodeContract:
    source_id = int(source["id"])
    node_id = f"fetch_source_{source_id}"

    def build_input(
        _root: BaseModel,
        _dependencies: dict[str, BaseModel] | Any,
    ) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "url": source["url"],
            "source_type": source["source_type"],
            "etag": source.get("etag"),
            "last_modified": source.get("last_modified"),
        }

    def fetch(node_input: BaseModel) -> dict[str, Any]:
        request_data = SignalFetchInput.model_validate(node_input)
        request = PublicSignalSourceRequest(**request_data.model_dump())
        try:
            fetched = agent.fetch_source_request(request)
        except Exception:
            logger.warning("Graph signal fetch failed: source_id=%s", source_id)
            return SignalFetchArtifact(
                source_id=source_id,
                status="failed",
                source_url=request.url,
                error="Public feed request failed.",
            ).model_dump()
        return _fetch_artifact(source_id, fetched).model_dump()

    return NodeContract(
        node_id=node_id,
        input_schema=SignalFetchInput,
        output_schema=SignalFetchArtifact,
        build_input=build_input,
        handler=fetch,
    )


def _persist_node(
    agent: SignalIntelligenceAgent,
    database: SignalDatabasePath,
    source_ids: list[int],
) -> NodeContract:
    dependencies = tuple(f"fetch_source_{source_id}" for source_id in source_ids)

    def build_input(
        _root: BaseModel,
        artifacts: dict[str, BaseModel] | Any,
    ) -> dict[str, Any]:
        return {
            "fetches": [
                artifacts[f"fetch_source_{source_id}"].model_dump()
                for source_id in source_ids
            ]
        }

    def persist(node_input: BaseModel) -> dict[str, Any]:
        persistence_input = PersistFetchesInput.model_validate(node_input)
        results: list[dict[str, Any]] = []
        for artifact in persistence_input.fetches:
            if artifact.status == "failed":
                results.append(
                    agent.persist_fetch_result(
                        artifact.source_id,
                        None,
                        database,
                        error=artifact.error,
                    )
                )
                continue
            results.append(
                agent.persist_fetch_result(
                    artifact.source_id,
                    _feed_fetch_result(artifact),
                    database,
                )
            )
        return SignalIngestionSummary(
            sources_scanned=len(results),
            new_signals=sum(result["new_signals"] for result in results),
            duplicates=sum(result["duplicates"] for result in results),
            failures=sum(result["failures"] for result in results),
            results=[SourceScanResult.model_validate(result) for result in results],
        ).model_dump()

    return NodeContract(
        node_id="persist_fetches",
        input_schema=PersistFetchesInput,
        output_schema=SignalIngestionSummary,
        dependencies=dependencies,
        build_input=build_input,
        handler=persist,
    )


def _fetch_artifact(source_id: int, fetched: FeedFetchResult) -> SignalFetchArtifact:
    return SignalFetchArtifact(
        source_id=source_id,
        status="not_modified" if fetched.not_modified else "success",
        source_url=fetched.source_url,
        http_status=fetched.http_status,
        fetched_at=fetched.fetched_at,
        etag=fetched.etag,
        last_modified=fetched.last_modified,
        feed_title=fetched.feed_title,
        items=[RawFeedItemArtifact(**asdict(item)) for item in fetched.items],
        not_modified=fetched.not_modified,
        warnings=fetched.warnings,
    )


def _feed_fetch_result(artifact: SignalFetchArtifact) -> FeedFetchResult:
    return FeedFetchResult(
        source_url=artifact.source_url,
        http_status=artifact.http_status or 200,
        fetched_at=artifact.fetched_at or "",
        etag=artifact.etag,
        last_modified=artifact.last_modified,
        feed_title=artifact.feed_title,
        items=[RawFeedItem(**item.model_dump()) for item in artifact.items],
        not_modified=artifact.not_modified,
        warnings=artifact.warnings,
    )
