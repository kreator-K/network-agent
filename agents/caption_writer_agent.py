"""Caption-writing stage bound to the completed carousel artifact."""

from __future__ import annotations

from typing import Any, Protocol

from agents.carousel_maker_agent import carousel_fingerprint
from db.models import CaptionArtifact, CarouselArtifact, HookArtifact, ResearchBrief


class ModelRunner(Protocol):
    def run_task(self, task_type: str, prompt: str, expected_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a bounded task through ModelOrchestrationAgent."""


class CaptionWriterAgent:
    """Write a caption that reflects the actual carousel plan."""

    def write(
        self,
        research: ResearchBrief,
        hook: HookArtifact,
        carousel: CarouselArtifact,
        model: Any,
    ) -> CaptionArtifact:
        text = (
            f"{hook.primary}\n\n"
            "The useful distinction is between what the source supports and what a product team decides to do next. "
            "I would name the highest-risk boundary case, set the evidence threshold, and revisit the decision when the facts change.\n\n"
            "Follow for the AI PM trends that actually matter."
        )
        response = model.run_task(
            task_type="caption_generation",
            prompt=(
                "Write an original caption for the completed carousel. Return JSON with text, attribution, disclosure, "
                "and unresolved_gaps. Match the rendered slides and do not add unsupported claims.\n"
                f"Hook: {hook.primary}\nSlides: {len(carousel.slides)}\nEvidence: {'; '.join(research.evidence_points)}"
            ),
            expected_schema={"text": str, "attribution": str, "disclosure": str, "unresolved_gaps": list},
        )
        result = response.get("result") if not response.get("fallback_used") else None
        if (
            isinstance(result, dict)
            and isinstance(result.get("text"), str)
            and result["text"].strip()
            and result["text"].strip().lower() != "mock"
        ):
            text = result["text"].strip()[:3000]
        return CaptionArtifact(
            status="completed",
            text=text,
            claim_ids=research.claim_ids,
            source_references=research.sources,
            attribution=(str(result.get("attribution"))[:500] if isinstance(result, dict) and result.get("attribution") else None),
            disclosure=(str(result.get("disclosure"))[:500] if isinstance(result, dict) and result.get("disclosure") else None),
            unresolved_gaps=(result.get("unresolved_gaps", []) if isinstance(result, dict) and isinstance(result.get("unresolved_gaps"), list) else research.gaps),
            carousel_sha256=carousel_fingerprint(carousel),
        )
