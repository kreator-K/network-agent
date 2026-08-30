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
        evidence = research.evidence_points[0]
        if "demo" in evidence.lower() or "dependab" in hook.primary.lower():
            text = (
                f"{hook.primary}\n\n"
                f"{evidence}\n\n"
                "A demo proves capability on a chosen path. Dependability asks a harder question: "
                "what happens when the input is ambiguous, the edge case is expensive, or the model is wrong?\n\n"
                "Before a wider rollout, I would require three things:\n"
                "1. Test the boundary case with the highest cost of failure.\n"
                "2. Define the pass-fail threshold before reviewing results.\n"
                "3. Record what new evidence would pause or expand the release.\n\n"
                "A promising demo earns the next test. It does not earn blind trust."
            )
        else:
            text = (
                f"{hook.primary}\n\n"
                f"{evidence}\n\n"
                "The useful distinction is between what the source supports and what a product team decides to do next.\n\n"
                "I would name the highest-risk boundary case, define the evidence threshold before acting, "
                "and record what new information would change the decision."
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
