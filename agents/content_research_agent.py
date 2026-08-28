"""Evidence brief stage for source-traced content packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from db.models import FactualClaim, ResearchBrief


class ContentResearchAgent:
    """Turn already-approved signal rows into a downstream research artifact.

    Public fetching and signal scoring remain owned by ``SignalIntelligenceAgent``.
    This stage only packages the stored evidence and never invents research.
    """

    def build_brief(
        self,
        references: list[Any],
        source_rows: Sequence[Mapping[str, Any]],
        claims: list[FactualClaim],
    ) -> ResearchBrief:
        sources = [
            {
                "id": f"src-{row['id']}",
                "signal_id": int(row["id"]),
                "url": str(row["canonical_url"]),
                "title": str(row["title"] or "Untitled source"),
                "summary": str(row["summary"] or ""),
                "source_type": "approved_public_signal",
            }
            for row in source_rows
        ]
        evidence = [
            f"{source['title']}: {source['summary']}".strip(": ")
            for source in sources
        ]
        claim_ids = [claim.id for claim in claims]
        gaps = [
            "The brief contains source summaries only; verify any detail beyond these summaries."
        ] if any(not source["summary"] for source in sources) else []
        return ResearchBrief(
            sources=sources,
            evidence_points=evidence,
            claim_ids=claim_ids,
            gaps=gaps,
        )
