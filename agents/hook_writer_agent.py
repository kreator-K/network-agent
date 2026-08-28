"""Hook-writing stage for source-traced LinkedIn content packages."""

from __future__ import annotations

from typing import Any, Protocol

from db.models import AlternativeHook, ContentPlan, HookArtifact, ResearchBrief


class ModelRunner(Protocol):
    def run_task(self, task_type: str, prompt: str, expected_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a bounded task through ModelOrchestrationAgent."""


class HookWriterAgent:
    """Write a primary hook and alternatives without changing source meaning."""

    def write(
        self,
        research: ResearchBrief,
        plan: ContentPlan,
        model: Any,
    ) -> HookArtifact:
        primary = f"{research.evidence_points[0].split(':', 1)[0]} points to a decision gap worth examining."
        alternatives = [
            AlternativeHook(
                text=primary,
                rationale="Source-led opening tied to the selected editorial plan.",
            ),
            AlternativeHook(
                text="The useful question is what evidence would change the next decision.",
                rationale="Evidence-gap opening suited to practical analysis.",
            ),
            AlternativeHook(
                text="A strong signal is only useful when it changes a specific product choice.",
                rationale="Decision-consequence opening without hype.",
            ),
        ]
        response = model.run_task(
            task_type="content_hook_generation",
            prompt=(
                "Write an original, source-grounded LinkedIn hook. Return JSON with primary, alternatives, "
                "and selection_rationale. Do not invent biography or unsupported facts.\n"
                f"Editorial pillar: {plan.editorial_pillar}\nFunnel: {plan.funnel_position}\n"
                f"Evidence: {'; '.join(research.evidence_points)}"
            ),
            expected_schema={"primary": str, "alternatives": list, "selection_rationale": str},
        )
        result = response.get("result") if not response.get("fallback_used") else None
        if isinstance(result, dict) and isinstance(result.get("primary"), str) and result["primary"].strip():
            primary = result["primary"].strip()[:400]
            parsed: list[AlternativeHook] = []
            for item in result.get("alternatives", []):
                if not isinstance(item, dict):
                    continue
                try:
                    parsed.append(AlternativeHook.model_validate(item))
                except Exception:
                    continue
            if len(parsed) >= 2:
                alternatives = parsed[:3]
            rationale = str(result.get("selection_rationale") or "Model-selected hook grounded in the research brief")[:500]
        else:
            rationale = "Deterministic hook selected from source evidence and the frozen editorial plan."
        return HookArtifact(
            primary=primary,
            alternatives=alternatives,
            claim_ids=research.claim_ids,
            selection_rationale=rationale,
        )
