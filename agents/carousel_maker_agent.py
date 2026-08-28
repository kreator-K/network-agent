"""Carousel planning and local slide-rendering stage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from db.models import CarouselArtifact, CarouselSlide, ContentPlan, HookArtifact, RenderedSlide, ResearchBrief
from integrations import image_gateway


class ModelRunner(Protocol):
    def run_task(self, task_type: str, prompt: str, expected_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a bounded task through ModelOrchestrationAgent."""


class CarouselMakerAgent:
    """Create an evidence-linked 1-10 slide plan and optional PNG receipts."""

    def make(
        self,
        research: ResearchBrief,
        hook: HookArtifact,
        plan: ContentPlan,
        model: Any,
        *,
        render: bool = False,
    ) -> CarouselArtifact:
        evidence = research.evidence_points[0]
        slides = [
            CarouselSlide(id="slide-1", role="cover", headline=hook.primary, visual_job="High-contrast statement", claim_ids=research.claim_ids),
            CarouselSlide(id="slide-2", role="evidence", headline="What the source actually supports", body=evidence, visual_job="Show the source-backed evidence", claim_ids=research.claim_ids),
            CarouselSlide(id="slide-3", role="interpretation", headline="The product implication", body="Separate the reported signal from the decision it may change.", visual_job="Simple decision framework", claim_ids=research.claim_ids),
            CarouselSlide(id="slide-4", role="closing", headline="Set the evidence threshold", body="Name the boundary case and define what would change the next commitment.", visual_job="Direct takeaway", claim_ids=research.claim_ids),
        ]
        response = model.run_task(
            task_type="carousel_generation",
            prompt=(
                "Plan an original evidence-linked LinkedIn carousel. Return JSON with slides, each containing id, role, "
                "headline, body, visual_job, claim_ids, and asset_ids. Use only supplied evidence.\n"
                f"Hook: {hook.primary}\nEditorial pillar: {plan.editorial_pillar}\nEvidence: {evidence}"
            ),
            expected_schema={"slides": list},
        )
        result = response.get("result") if not response.get("fallback_used") else None
        if isinstance(result, dict) and isinstance(result.get("slides"), list):
            parsed: list[CarouselSlide] = []
            for item in result["slides"][:10]:
                try:
                    parsed.append(CarouselSlide.model_validate(item))
                except Exception:
                    parsed = []
                    break
            if parsed:
                slides = parsed
        artifact = CarouselArtifact(status="completed" if render else "planned", slides=slides)
        if render:
            rendered: list[RenderedSlide] = []
            for slide in slides:
                path = Path(image_gateway.render_branded_card(f"{slide.headline}\n{slide.body}", aspect_ratio="4:5"))
                rendered.append(
                    RenderedSlide(
                        slide_id=slide.id,
                        file=str(path),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
            artifact = artifact.model_copy(update={"rendered_slides": rendered})
        return artifact


def carousel_fingerprint(carousel: CarouselArtifact) -> str:
    """Return a stable fingerprint for caption binding."""
    payload = json.dumps(carousel.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
