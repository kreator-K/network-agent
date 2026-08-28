"""Unit tests for the four content-creation specialist stages."""

from typing import Any, cast

from agents.caption_writer_agent import CaptionWriterAgent
from agents.carousel_maker_agent import CarouselMakerAgent, carousel_fingerprint
from agents.content_research_agent import ContentResearchAgent
from agents.hook_writer_agent import HookWriterAgent
from db.models import ContentPlan, FactualClaim, ResearchBrief


class FakeModel:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = result or {}
        self.calls: list[str] = []

    def run_task(self, task_type: str, prompt: str, expected_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = (prompt, expected_schema)
        self.calls.append(task_type)
        return {"mode": "mock", "fallback_used": not bool(self.result), "result": self.result}


def _research() -> ResearchBrief:
    return ResearchBrief(
        sources=[{"id": "src-1", "url": "https://example.com", "title": "A source", "summary": "A supported observation."}],
        evidence_points=["A source: A supported observation."],
        claim_ids=["claim-1"],
    )


def _plan() -> ContentPlan:
    return ContentPlan(
        editorial_pillar="Authority",
        topical_pillar="AI products",
        funnel_position="MOF",
        hook_archetype="Evidence gap",
        hook_idea="Name the missing evidence.",
    )


def test_research_agent_only_packages_stored_rows() -> None:
    # A lightweight row-like object keeps this test independent of SQLite setup.
    class Source:
        def __getitem__(self, key: str) -> Any:
            return {"id": 1, "canonical_url": "https://example.com", "title": "A source", "summary": "A supported observation."}[key]

    brief = ContentResearchAgent().build_brief(
        [{"signal_id": 1}],
        cast(Any, [Source()]),
        [FactualClaim(id="claim-1", claim_text="A source", source_signal_ids=[1], confidence=1.0, directly_supported=True)],
    )
    assert brief.status == "completed"
    assert brief.sources[0]["signal_id"] == 1
    assert brief.claim_ids == ["claim-1"]


def test_hook_carousel_caption_stages_have_traceable_contracts() -> None:
    research = _research()
    model = FakeModel()
    hook = HookWriterAgent().write(research, _plan(), model)
    carousel = CarouselMakerAgent().make(research, hook, _plan(), model)
    caption = CaptionWriterAgent().write(research, hook, carousel, model)

    assert hook.claim_ids == research.claim_ids
    assert len(hook.alternatives) == 3
    assert carousel.status == "planned"
    assert all(set(slide.claim_ids) == {"claim-1"} for slide in carousel.slides)
    assert caption.carousel_sha256 == carousel_fingerprint(carousel)
    assert caption.source_references == research.sources
    assert model.calls == ["content_hook_generation", "carousel_generation", "caption_generation"]


def test_hook_and_caption_model_output_is_used_when_valid() -> None:
    research = _research()
    model = FakeModel(
        {
            "primary": "A precise opening.",
            "alternatives": [
                {"text": "A precise opening.", "rationale": "Primary."},
                {"text": "A second opening.", "rationale": "Alternative."},
            ],
            "selection_rationale": "Specific and grounded.",
        }
    )
    hook = HookWriterAgent().write(research, _plan(), model)
    assert hook.primary == "A precise opening."
    assert hook.selection_rationale == "Specific and grounded."
