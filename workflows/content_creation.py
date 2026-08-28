"""Typed graph for source-grounded content-creation artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents.caption_writer_agent import CaptionWriterAgent
from agents.carousel_maker_agent import CarouselMakerAgent
from agents.content_research_agent import ContentResearchAgent
from agents.hook_writer_agent import HookWriterAgent
from db.models import (
    CaptionArtifact,
    CarouselArtifact,
    ContentPackage,
    ContentPlan,
    FactualClaim,
    HookArtifact,
    ResearchBrief,
)
from workflows.contracts import NodeContract, WorkflowDefinition
from workflows.engine import GraphWorkflowEngine


class ContentGraphError(ValueError):
    """Raised when content artifacts fail deterministic graph verification."""


class ContentGraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentArtifactInput(ContentGraphModel):
    references: list[dict[str, Any]] = Field(min_length=1)
    sources: list[dict[str, Any]] = Field(min_length=1)
    claims: list[FactualClaim] = Field(min_length=1)
    plan: ContentPlan
    render_carousel: bool = False


class ResearchNodeInput(ContentGraphModel):
    references: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    claims: list[FactualClaim]


class HookNodeInput(ContentGraphModel):
    research: ResearchBrief
    plan: ContentPlan


class CarouselNodeInput(ContentGraphModel):
    research: ResearchBrief
    hook: HookArtifact
    plan: ContentPlan
    render: bool


class CarouselNodeArtifact(ContentGraphModel):
    carousel: CarouselArtifact
    render_fallback_used: bool = False


class CaptionNodeInput(ContentGraphModel):
    research: ResearchBrief
    hook: HookArtifact
    carousel: CarouselArtifact


class EvidenceVerificationInput(ContentGraphModel):
    research: ResearchBrief
    claims: list[FactualClaim]


class EvidenceVerificationArtifact(ContentGraphModel):
    passed: bool
    blockers: list[str] = Field(default_factory=list)


class BundleNodeInput(ContentGraphModel):
    research: ResearchBrief
    hook: HookArtifact
    carousel_result: CarouselNodeArtifact
    caption: CaptionArtifact
    verification: EvidenceVerificationArtifact


class ContentArtifactBundle(ContentGraphModel):
    research: ResearchBrief
    hook: HookArtifact
    carousel: CarouselArtifact
    caption: CaptionArtifact
    verification: EvidenceVerificationArtifact
    render_fallback_used: bool = False


def content_graph_preview(*, render_carousel: bool) -> dict[str, Any]:
    """Return the static graph topology without calling agents or providers."""
    return {
        "workflow": "content_artifacts",
        "workflow_version": 1,
        "nodes": [
            "research",
            "hook",
            "carousel",
            "caption",
            "verify_evidence",
            "bundle",
        ],
        "render_carousel": render_carousel,
        "executed": False,
    }


def run_content_artifact_graph(
    *,
    package: ContentPackage,
    references: list[dict[str, Any]],
    source_rows: list[Mapping[str, Any]],
    model: Any,
    render_carousel: bool,
    research_agent: ContentResearchAgent,
    hook_agent: HookWriterAgent,
    carousel_agent: CarouselMakerAgent,
    caption_agent: CaptionWriterAgent,
) -> tuple[ContentArtifactBundle, dict[str, Any]]:
    """Execute content artifacts and enforce the evidence verification gate."""
    root = ContentArtifactInput(
        references=references,
        sources=[dict(row) for row in source_rows],
        claims=package.factual_claims,
        plan=package.content_plan,
        render_carousel=render_carousel,
    )

    research = NodeContract(
        node_id="research",
        input_schema=ResearchNodeInput,
        output_schema=ResearchBrief,
        build_input=lambda workflow_input, _artifacts: {
            "references": ContentArtifactInput.model_validate(workflow_input).references,
            "sources": ContentArtifactInput.model_validate(workflow_input).sources,
            "claims": ContentArtifactInput.model_validate(workflow_input).claims,
        },
        handler=lambda node_input: research_agent.build_brief(
            ResearchNodeInput.model_validate(node_input).references,
            ResearchNodeInput.model_validate(node_input).sources,
            ResearchNodeInput.model_validate(node_input).claims,
        ),
    )
    hook = NodeContract(
        node_id="hook",
        input_schema=HookNodeInput,
        output_schema=HookArtifact,
        dependencies=("research",),
        build_input=lambda workflow_input, artifacts: {
            "research": artifacts["research"],
            "plan": ContentArtifactInput.model_validate(workflow_input).plan,
        },
        handler=lambda node_input: hook_agent.write(
            HookNodeInput.model_validate(node_input).research,
            HookNodeInput.model_validate(node_input).plan,
            model,
        ),
    )

    def make_carousel(node_input: BaseModel) -> CarouselNodeArtifact:
        validated = CarouselNodeInput.model_validate(node_input)
        try:
            carousel = carousel_agent.make(
                validated.research,
                validated.hook,
                validated.plan,
                model,
                render=validated.render,
            )
            return CarouselNodeArtifact(carousel=carousel)
        except Exception:
            if not validated.render:
                raise
            carousel = carousel_agent.make(
                validated.research,
                validated.hook,
                validated.plan,
                model,
                render=False,
            )
            return CarouselNodeArtifact(
                carousel=carousel,
                render_fallback_used=True,
            )

    carousel = NodeContract(
        node_id="carousel",
        input_schema=CarouselNodeInput,
        output_schema=CarouselNodeArtifact,
        dependencies=("research", "hook"),
        build_input=lambda workflow_input, artifacts: {
            "research": artifacts["research"],
            "hook": artifacts["hook"],
            "plan": ContentArtifactInput.model_validate(workflow_input).plan,
            "render": ContentArtifactInput.model_validate(
                workflow_input
            ).render_carousel,
        },
        handler=make_carousel,
    )
    caption = NodeContract(
        node_id="caption",
        input_schema=CaptionNodeInput,
        output_schema=CaptionArtifact,
        dependencies=("research", "hook", "carousel"),
        build_input=lambda _root, artifacts: {
            "research": artifacts["research"],
            "hook": artifacts["hook"],
            "carousel": CarouselNodeArtifact.model_validate(
                artifacts["carousel"]
            ).carousel,
        },
        handler=lambda node_input: caption_agent.write(
            CaptionNodeInput.model_validate(node_input).research,
            CaptionNodeInput.model_validate(node_input).hook,
            CaptionNodeInput.model_validate(node_input).carousel,
            model,
        ),
    )
    verifier = NodeContract(
        node_id="verify_evidence",
        input_schema=EvidenceVerificationInput,
        output_schema=EvidenceVerificationArtifact,
        dependencies=("research",),
        build_input=lambda workflow_input, artifacts: {
            "research": artifacts["research"],
            "claims": ContentArtifactInput.model_validate(workflow_input).claims,
        },
        handler=_verify_evidence,
    )
    bundle = NodeContract(
        node_id="bundle",
        input_schema=BundleNodeInput,
        output_schema=ContentArtifactBundle,
        dependencies=("research", "hook", "carousel", "caption", "verify_evidence"),
        build_input=lambda _root, artifacts: {
            "research": artifacts["research"],
            "hook": artifacts["hook"],
            "carousel_result": artifacts["carousel"],
            "caption": artifacts["caption"],
            "verification": artifacts["verify_evidence"],
        },
        handler=lambda node_input: _bundle(BundleNodeInput.model_validate(node_input)),
    )
    run = GraphWorkflowEngine(max_workers=2).run(
        WorkflowDefinition(
            name="content_artifacts",
            version=1,
            input_schema=ContentArtifactInput,
            nodes=(research, hook, carousel, caption, verifier, bundle),
        ),
        root,
    )
    output = run.nodes["bundle"].output
    if output is None:
        raise ContentGraphError("Content graph did not produce a complete artifact bundle.")
    artifact_bundle = ContentArtifactBundle.model_validate(output)
    if not artifact_bundle.verification.passed:
        raise ContentGraphError(
            "Content evidence verification failed: "
            + "; ".join(artifact_bundle.verification.blockers)
        )
    return artifact_bundle, run.model_dump(mode="json")


def _verify_evidence(node_input: BaseModel) -> EvidenceVerificationArtifact:
    validated = EvidenceVerificationInput.model_validate(node_input)
    source_ids = {
        int(source["signal_id"])
        for source in validated.research.sources
        if source.get("signal_id") is not None
    }
    blockers: list[str] = []
    if set(validated.research.claim_ids) != {claim.id for claim in validated.claims}:
        blockers.append("Research claim IDs do not match the frozen factual claims.")
    for claim in validated.claims:
        if not set(claim.source_signal_ids).issubset(source_ids):
            blockers.append(f"Claim '{claim.id}' references an unavailable source.")
    return EvidenceVerificationArtifact(passed=not blockers, blockers=blockers)


def _bundle(node_input: BundleNodeInput) -> ContentArtifactBundle:
    return ContentArtifactBundle(
        research=node_input.research,
        hook=node_input.hook,
        carousel=node_input.carousel_result.carousel,
        caption=node_input.caption,
        verification=node_input.verification,
        render_fallback_used=node_input.carousel_result.render_fallback_used,
    )
