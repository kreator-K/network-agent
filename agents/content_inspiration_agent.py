"""LinkedIn content inspiration and drafting agent."""

import sqlite3
import json
from difflib import SequenceMatcher
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from agents.model_orchestration_agent import ModelOrchestrationAgent
from agents.caption_writer_agent import CaptionWriterAgent
from agents.carousel_maker_agent import CarouselMakerAgent, carousel_fingerprint
from agents.content_research_agent import ContentResearchAgent
from agents.hook_writer_agent import HookWriterAgent
from config.content_strategy import hooks_for_pillar, pillar_for_weekday
from config.settings import settings
from db.database import connect
from db.models import (
    AlternativeHook,
    ContentPlan,
    ContentPackage,
    ContentPost,
    ContentPostImageSource,
    ContentRiskAssessment,
    FactualClaim,
    HookAB,
    HookArtifact,
    ImageBrief,
    PersonalAngle,
    PostVariant,
    ResearchBrief,
    CarouselArtifact,
    CarouselSlide,
    CaptionArtifact,
)
from integrations import image_gateway
from workflows.content_creation import (
    ContentGraphError,
    content_graph_preview,
    run_content_artifact_graph,
)
from workflows.contracts import WorkflowRunResult
from workflows.persistence import save_workflow_run


WRITING_STYLE_INSTRUCTIONS = """Writing style:
- Be spartan, specific, and informative.
- Use mild uncertainty when evidence is incomplete.
- Use first-person actions only when grounded in supplied facts. Do not invent lived experience.
- Address the reader with you or your when useful.
- Give practical, actionable insight. Use verified data or examples when available.
- Vary sentence length, paragraph length, and pacing.
- Remove buzzwords, cliches, generic praise, filler, and repeated wording.
- Use plain punctuation. Never use em dashes, semicolons, hashtags, markdown, or rhetorical questions.
- Do not use balanced filler or broad generalizations.
- Avoid these terms: can, may, just, very, really, literally, actually, certainly, probably, basically, could, maybe, however, furthermore, moreover, utilize, utilizing, leverage, unlock, revolutionize, disruptive, game-changer, cutting-edge, groundbreaking, powerful, remarkable, exciting, boost, skyrocket.
"""


class ModelOrchestrator(Protocol):
    """Minimal model orchestration interface used by this agent."""

    def run_task(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a model task through the approved orchestration boundary."""


class ContentInspirationError(ValueError):
    """Base error for content inspiration failures."""


class ContentInspirationAgent:
    """Draft LinkedIn posts for approval before publishing.

    Purpose:
        Produce original LinkedIn post concepts and copy from user notes,
        topics, drafts, and optional imagery.
    Inputs:
        User topic, thesis, notes, optional uploaded image, optional generated
        image request, core intent, refinable parameters, and engagement data.
    Outputs:
        Draft post content, image-selection metadata, and approval-ready
        payloads.
    """

    def __init__(
        self,
        model_orchestration_agent: ModelOrchestrator | None = None,
    ) -> None:
        """Create a content drafter using the approved model boundary."""
        self.model_orchestration_agent = (
            model_orchestration_agent or ModelOrchestrationAgent()
        )
        self.content_research_agent = ContentResearchAgent()
        self.hook_writer_agent = HookWriterAgent()
        self.carousel_maker_agent = CarouselMakerAgent()
        self.caption_writer_agent = CaptionWriterAgent()

    def draft_post(
        self,
        topic: str,
        inspiration_notes: str | None = None,
        user_image_path: str | None = None,
        generate_image: bool = False,
    ) -> dict[str, Any]:
        """Draft a LinkedIn post and resolve image attachment metadata."""
        prompt = self._build_prompt(topic, inspiration_notes, user_image_path)
        response = self.model_orchestration_agent.run_task(
            task_type="content_post_draft",
            prompt=prompt,
            expected_schema={"draft_text": str},
        )
        draft_text = self._extract_draft_text(response)
        image_source, image_path, image_error = self._resolve_image(
            topic=topic,
            user_image_path=user_image_path,
            generate_image=generate_image,
        )
        result = {
            "topic": topic,
            "draft_text": draft_text,
            "image_source": image_source,
            "image_path": image_path,
            "inspiration_source_notes": inspiration_notes,
            "mode": response["mode"],
            "fallback_used": response["fallback_used"],
        }
        if image_error is not None:
            result["image_error"] = image_error
        return result

    def save_draft_to_db(
        self,
        draft: dict[str, Any],
        database: sqlite3.Connection | str | Path,
    ) -> ContentPost:
        """Persist a drafted content post with internal status `draft`."""
        created_at = _utc_now()
        connection, should_close = _coerce_connection(database)
        try:
            cursor = connection.execute(
                """
                INSERT INTO content_posts (
                    topic,
                    draft_text,
                    image_source,
                    image_path,
                    inspiration_source_notes,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    draft.get("topic"),
                    draft["draft_text"],
                    draft["image_source"],
                    draft.get("image_path"),
                    draft.get("inspiration_source_notes"),
                    created_at,
                    created_at,
                ),
            )
            connection.commit()
            post_id = _required_lastrowid(cursor)
            row = connection.execute(
                "SELECT * FROM content_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            return _content_post_from_row(row)
        finally:
            if should_close:
                connection.close()

    def get_pending_drafts(
        self,
        database: sqlite3.Connection | str | Path,
    ) -> list[ContentPost]:
        """Return content posts still waiting for authenticated review."""
        connection, should_close = _coerce_connection(database)
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM content_posts
                WHERE status IN ('draft', 'saved', 'approved_for_later_posting')
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
            return [_content_post_from_row(row) for row in rows]
        finally:
            if should_close:
                connection.close()

    def create_package_from_research(
        self,
        *,
        topic: str,
        source_title: str,
        source_url: str,
        evidence_text: str,
        research_resource_id: int | None,
        image_source: ContentPostImageSource,
        image_path: str | None,
        image_alt_text: str | None,
        database: sqlite3.Connection | str | Path,
    ) -> ContentPost:
        """Run the four specialist content stages for manually supplied research."""
        connection, should_close = _coerce_connection(database)
        try:
            profile = connection.execute(
                "SELECT version, profile_json FROM personal_brand_profile WHERE is_active=1"
            ).fetchone()
            scoring = connection.execute(
                "SELECT version FROM signal_scoring_config WHERE is_active=1"
            ).fetchone()
            if profile is None or scoring is None:
                raise ContentInspirationError(
                    "Active brand profile and scoring configuration are required."
                )
            source_id = research_resource_id or 0
            claim = FactualClaim(
                id=f"research-{source_id}-claim-1",
                claim_text=source_title,
                source_signal_ids=[source_id],
                confidence=0.8,
                directly_supported=True,
                softened=True,
                risk_note="Use only the user-supplied research evidence.",
            )
            source_row = {
                "id": source_id,
                "canonical_url": source_url,
                "title": source_title,
                "summary": evidence_text,
                "source_type": "manual_research_resource",
            }
            references = [
                {
                    "research_resource_id": research_resource_id,
                    "url": source_url,
                    "title": source_title,
                    "source_type": "manual_research_resource",
                }
            ]
            research = self.content_research_agent.build_brief(
                references, [source_row], [claim]
            )
            plan = ContentPlan(
                editorial_pillar="Source-backed insight",
                topical_pillar=topic,
                funnel_position="MOF",
                hook_archetype="Evidence gap",
                hook_idea="Open with the decision the evidence should change.",
            )
            hook = self.hook_writer_agent.write(
                research, plan, self.model_orchestration_agent
            )
            carousel = self.carousel_maker_agent.make(
                research, hook, plan, self.model_orchestration_agent, render=False
            )
            caption = self.caption_writer_agent.write(
                research, hook, carousel, self.model_orchestration_agent
            )
            hook_options = [hook.primary, *[item.text for item in hook.alternatives]]
            unique_hooks = list(dict.fromkeys(item.strip() for item in hook_options if item.strip()))
            while len(unique_hooks) < 3:
                unique_hooks.append(f"{topic}: the evidence should change a specific decision.")
            body = caption.text.split("\n\n", 1)[-1]
            variants = [
                PostVariant(
                    label=f"Variant {index}",
                    hook_archetype="Evidence gap",
                    funnel_position="MOF",
                    post_text=caption.text if index == 1 else f"{opening}\n\n{body}",
                )
                for index, opening in enumerate(unique_hooks[:3], start=1)
            ]
            profile_data = _json_object(profile["profile_json"])
            identity = str(
                profile_data.get("professional_identity")
                or "Professional learning from supplied research"
            )
            package = ContentPackage(
                research_resource_id=research_resource_id,
                primary_post=caption.text,
                alternative_hooks=hook.alternatives,
                content_plan=plan,
                variants=variants,
                hook_ab=HookAB(hook_a=unique_hooks[0], hook_b=unique_hooks[1]),
                flop_adjustment="Tighten the opening while preserving the same evidence.",
                research=research,
                hook=hook,
                carousel=carousel,
                caption=caption,
                target_audience="Professional network",
                recommended_format="single_image" if image_path else "text",
                content_treatment="Source-backed practical analysis",
                source_references=references,
                factual_claims=[claim],
                personal_angle=PersonalAngle(
                    angle_type="professional_identity", text=identity, verified=False
                ),
                image_brief=ImageBrief(
                    objective="Support the post without adding factual claims.",
                    visual_idea="Use the user-selected image and optional text overlay.",
                    aspect_ratio="4:5",
                    safety_notes=["Uploaded imagery takes precedence."],
                ),
                image_alt_text=image_alt_text,
                risk_assessment=ContentRiskAssessment(
                    factual_risk=15,
                    generic_content_risk=20,
                    notes=["Evidence is limited to manually supplied research."],
                    validation_passed=True,
                ),
                why_it_fits_profile="The user selected this topic and evidence for their content workflow.",
                profile_version=int(profile["version"]),
                scoring_config_version=int(scoring["version"]),
                package_version=1,
            )
            now = _utc_now()
            cursor = connection.execute(
                """INSERT INTO content_posts (
                    topic, draft_text, image_source, image_path,
                    inspiration_source_notes, status, opportunity_id,
                    profile_version, scoring_config_version, package_version,
                    package_json, source_references_json, factual_claims_json,
                    alternative_hooks_json, personal_angle_json,
                    risk_assessment_json, suggested_hashtags_json,
                    image_brief_json, image_alt_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', NULL, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    topic,
                    package.primary_post,
                    image_source,
                    image_path,
                    evidence_text,
                    package.profile_version,
                    package.scoring_config_version,
                    _json_dump(package.model_dump()),
                    _json_dump(package.source_references),
                    _json_dump([item.model_dump() for item in package.factual_claims]),
                    _json_dump([item.model_dump() for item in package.alternative_hooks]),
                    _json_dump(package.personal_angle.model_dump()),
                    _json_dump(package.risk_assessment.model_dump()),
                    "[]",
                    _json_dump(
                        package.image_brief.model_dump()
                        if package.image_brief is not None
                        else None
                    ),
                    image_alt_text,
                    now,
                    now,
                ),
            )
            post_id = _required_lastrowid(cursor)
            _insert_content_version(
                connection,
                content_post_id=post_id,
                package_version=1,
                draft_text=package.primary_post,
                package_json=_json_dump(package.model_dump()),
                revision_type="manual_research_package",
                revision_notes=None,
                model_mode="specialist_pipeline",
                fallback_used=settings.mock_mode,
                created_at=now,
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM content_posts WHERE id=?", (post_id,)
            ).fetchone()
            return _content_post_from_row(row)
        finally:
            if should_close:
                connection.close()

    def generate_package_from_opportunity(
        self, opportunity_id: int, database: sqlite3.Connection | str | Path,
        image_mode: str = "disabled",
        graph_mode: str | None = None,
    ) -> ContentPost:
        """Create a review-only package from one selected or candidate opportunity.

        This method never fetches signals, scores them, or invokes LinkedIn.
        """
        connection, should_close = _coerce_connection(database)
        try:
            opportunity = connection.execute(
                "SELECT * FROM content_opportunities WHERE id = ?", (opportunity_id,)
            ).fetchone()
            if opportunity is None:
                raise ContentInspirationError(f"Content opportunity id {opportunity_id} does not exist.")
            if opportunity["status"] in {"dismissed", "expired"}:
                raise ContentInspirationError("Dismissed or expired opportunities cannot create a package.")
            profile = connection.execute(
                "SELECT * FROM personal_brand_profile WHERE version = ?", (opportunity["profile_version"],)
            ).fetchone()
            if profile is None:
                raise ContentInspirationError("Opportunity references an unavailable personal-brand profile.")
            profile_data = json.loads(profile["profile_json"])
            references = _json_list(opportunity["source_references_json"])
            if not references:
                raise ContentInspirationError("Opportunity is missing source references.")
            source_ids = [int(item["signal_id"]) for item in references if isinstance(item, dict) and item.get("signal_id")]
            if not source_ids:
                raise ContentInspirationError("Opportunity source references are invalid.")
            source_rows = connection.execute(
                f"SELECT id, title, summary, canonical_url FROM signals WHERE id IN ({','.join('?' for _ in source_ids)})",
                source_ids,
            ).fetchall()
            if len(source_rows) != len(source_ids):
                raise ContentInspirationError("Opportunity references an unavailable signal.")
            # The deterministic package is the guaranteed-safe scaffold (claims, risk
            # assessment, image brief, personal angle) and the fallback narrative when
            # model output is absent or malformed. Real writing replaces the templated
            # primary_post/hooks whenever the model returns valid, source-grounded text.
            package = self._build_deterministic_package(opportunity, profile_data, references, source_rows)
            selected_graph_mode = (graph_mode or settings.content_graph_mode).strip().lower()
            if selected_graph_mode not in {"disabled", "shadow", "enabled"}:
                raise ContentInspirationError(
                    "Content graph mode must be disabled, shadow, or enabled."
                )
            generation_workflow: dict[str, Any] | None = None
            if selected_graph_mode == "enabled":
                try:
                    bundle, generation_workflow = run_content_artifact_graph(
                        package=package,
                        references=[dict(item) for item in references if isinstance(item, dict)],
                        source_rows=source_rows,
                        model=self.model_orchestration_agent,
                        render_carousel=image_mode == "real",
                        research_agent=self.content_research_agent,
                        hook_agent=self.hook_writer_agent,
                        carousel_agent=self.carousel_maker_agent,
                        caption_agent=self.caption_writer_agent,
                    )
                except ContentGraphError as exc:
                    raise ContentInspirationError(str(exc)) from exc
                research = bundle.research
                hook = bundle.hook
                carousel = bundle.carousel
                caption = bundle.caption
                save_workflow_run(
                    connection,
                    WorkflowRunResult.model_validate(generation_workflow),
                    metadata={
                        "opportunity_id": opportunity_id,
                        "artifact_type": "content_package",
                    },
                )
            else:
                research = self.content_research_agent.build_brief(
                    references, source_rows, package.factual_claims
                )
                hook = self.hook_writer_agent.write(
                    research, package.content_plan, self.model_orchestration_agent
                )
                carousel = self.carousel_maker_agent.make(
                    research,
                    hook,
                    package.content_plan,
                    self.model_orchestration_agent,
                    render=image_mode == "real",
                )
                caption = self.caption_writer_agent.write(
                    research, hook, carousel, self.model_orchestration_agent
                )
                if selected_graph_mode == "shadow":
                    generation_workflow = content_graph_preview(
                        render_carousel=image_mode == "real"
                    )
            package = package.model_copy(
                update={
                    "alternative_hooks": hook.alternatives,
                    "hook_ab": HookAB(
                        hook_a=hook.primary,
                        hook_b=hook.alternatives[1].text,
                    ),
                    "research": research,
                    "hook": hook,
                    "carousel": carousel,
                    "caption": caption,
                    "generation_workflow": generation_workflow,
                }
            )
            response = self.model_orchestration_agent.run_task(
                task_type="content_package_generation",
                prompt=_package_generation_prompt(opportunity, source_rows[0], package, profile_data),
                expected_schema={
                    "primary_post": str,
                    "alternative_hooks": list,
                    "variants": list,
                    "hook_ab": dict,
                    "flop_adjustment": str,
                },
            )
            model_text = _extract_generated_post_text(response)
            model_hooks = _extract_package_hooks(response)
            model_variants = _extract_package_variants(response, model_text)
            model_hook_ab = _extract_hook_ab(response)
            model_flop_adjustment = _extract_flop_adjustment(response)
            used_model = model_text is not None
            if used_model:
                variants = model_variants or [
                    package.variants[0].model_copy(update={"post_text": model_text}),
                    *package.variants[1:],
                ]
                package = package.model_copy(
                    update={
                        "primary_post": model_text,
                        "alternative_hooks": model_hooks or package.alternative_hooks,
                        "hook": package.hook.model_copy(
                            update={
                                "primary": (model_hooks[0].text if model_hooks else package.hook.primary),
                                "alternatives": (model_hooks or package.hook.alternatives),
                            }
                        ),
                        "variants": variants,
                        "hook_ab": model_hook_ab or package.hook_ab,
                        "flop_adjustment": model_flop_adjustment or package.flop_adjustment,
                    }
                )
            model_mode = str(response.get("mode") or "unknown") if used_model else "deterministic"
            fallback_used = bool(response.get("fallback_used")) or not used_model
            image_source, image_path = "none", None
            card_text = _card_display_text(package)
            card_aspect_ratio = package.image_brief.aspect_ratio if package.image_brief else "1:1"
            if image_mode == "mock":
                image_source, image_path = "generated", image_gateway.generate_image(
                    card_text,
                    mock_mode=True,
                    aspect_ratio=card_aspect_ratio,
                )
            elif image_mode == "real":
                try:
                    image_source, image_path = "generated", image_gateway.generate_image(
                        card_text,
                        mock_mode=False,
                        aspect_ratio=card_aspect_ratio,
                    )
                except Exception:
                    image_source, image_path = "none", None
            now = _utc_now()
            cursor = connection.execute(
                """INSERT INTO content_posts (
                    topic, draft_text, image_source, image_path, status, opportunity_id,
                    profile_version, scoring_config_version, package_version, package_json,
                    source_references_json, factual_claims_json, alternative_hooks_json,
                    personal_angle_json, risk_assessment_json, suggested_first_comment,
                    suggested_hashtags_json, image_brief_json, image_alt_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opportunity["headline"], package.primary_post, image_source, image_path,
                    opportunity_id, package.profile_version, package.scoring_config_version,
                    package.package_version, _json_dump(package.model_dump()), _json_dump(package.source_references),
                    _json_dump([claim.model_dump() for claim in package.factual_claims]),
                    _json_dump([hook.model_dump() for hook in package.alternative_hooks]),
                    _json_dump(package.personal_angle.model_dump()), _json_dump(package.risk_assessment.model_dump()),
                    package.suggested_first_comment, _json_dump(package.suggested_hashtags),
                    _json_dump(package.image_brief.model_dump() if package.image_brief else None),
                    package.image_alt_text, now, now,
                ),
            )
            post_id = _required_lastrowid(cursor)
            _insert_content_version(
                connection,
                content_post_id=post_id,
                package_version=package.package_version,
                draft_text=package.primary_post,
                package_json=_json_dump(package.model_dump()),
                revision_type="initial_package",
                revision_notes=None,
                model_mode=model_mode,
                fallback_used=fallback_used,
                created_at=now,
            )
            connection.execute("UPDATE content_opportunities SET status = 'selected', updated_at = ? WHERE id = ?", (now, opportunity_id))
            connection.commit()
            row = connection.execute("SELECT * FROM content_posts WHERE id = ?", (post_id,)).fetchone()
            return _content_post_from_row(row)
        finally:
            if should_close:
                connection.close()

    def get_package(self, post_id: int, database: sqlite3.Connection | str | Path) -> ContentPost:
        """Load a package-backed content post for review."""
        connection, should_close = _coerce_connection(database)
        try:
            row = connection.execute("SELECT * FROM content_posts WHERE id = ?", (post_id,)).fetchone()
            if row is None or row["package_json"] is None:
                raise ContentInspirationError(f"Content package id {post_id} does not exist.")
            return _content_post_from_row(row)
        finally:
            if should_close:
                connection.close()

    def get_publish_readiness(
        self,
        post_id: int,
        database: sqlite3.Connection | str | Path,
    ) -> dict[str, Any]:
        """Explain whether one content record can enter the publish-preview flow."""
        connection, should_close = _coerce_connection(database)
        try:
            row = connection.execute(
                "SELECT * FROM content_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if row is None:
                return {
                    "exists": False,
                    "package_backed": False,
                    "ready": False,
                    "status": None,
                    "blockers": [f"Content post id {post_id} does not exist."],
                }
            post = _content_post_from_row(row)
            package_backed = post.package_json is not None
            blockers: list[str] = []
            if not package_backed:
                blockers.append(
                    "This is a plain topic draft, not a source-grounded content package."
                )
            else:
                blockers.extend(self.validate_package_for_approval(post))
            if post.status != "approved_for_later_posting":
                blockers.append("The content package has not been approved for later posting.")
            return {
                "exists": True,
                "package_backed": package_backed,
                "ready": not blockers,
                "status": post.status,
                "blockers": blockers,
            }
        finally:
            if should_close:
                connection.close()

    def validate_package_for_approval(self, post: ContentPost) -> list[str]:
        """Return deterministic approval blockers without trusting model output."""
        blockers: list[str] = []
        claims = _json_list(post.factual_claims_json)
        if not post.source_references_json or not _json_list(post.source_references_json):
            blockers.append("Package is missing source references.")
        for claim in claims:
            if not isinstance(claim, dict) or not claim.get("source_signal_ids"):
                blockers.append("A factual claim is missing source support.")
            if isinstance(claim, dict) and claim.get("confirmation_required"):
                blockers.append("A factual claim requires confirmation.")
        risk = _json_object(post.risk_assessment_json)
        if float(risk.get("factual_risk", 0)) > 35 or not risk.get("validation_passed", False):
            blockers.append("Package failed factual-risk validation.")
        if post.image_source != "none" and not post.image_alt_text:
            blockers.append("Image assets require alt text.")
        return blockers

    def revise_package(
        self,
        post_id: int,
        revision_type: str,
        database: sqlite3.Connection | str | Path,
        revision_notes: str | None = None,
    ) -> ContentPost:
        """Rewrite a complete package narrative and preserve every text version."""
        allowed = {"make_more_personal", "make_more_analytical", "make_more_concise", "make_more_practical", "make_lighter", "make_funnier", "reduce_hype", "change_target_audience", "regenerate_hook", "custom_revision"}
        if revision_type not in allowed:
            raise ContentInspirationError("Unsupported content revision type.")
        post = self.get_package(post_id, database)
        if post.status in {"discarded", "rejected"}:
            raise ContentInspirationError("Rejected content packages cannot be revised.")
        if revision_type == "make_funnier" and "sensitive" in (post.risk_assessment_json or "").lower():
            raise ContentInspirationError("Humor revision is not allowed for sensitive content.")
        cleaned_notes = " ".join((revision_notes or "").split()) or None
        if revision_type == "custom_revision" and cleaned_notes is None:
            raise ContentInspirationError("Custom revisions require revision notes.")
        package_data = json.loads(post.package_json or "{}")
        response = self.model_orchestration_agent.run_task(
            task_type=_revision_task_type(revision_type),
            prompt=_revision_prompt(post, revision_type, cleaned_notes),
            expected_schema={"primary_post": str},
        )
        candidate = _extract_generated_post_text(response)
        fallback_used = bool(response.get("fallback_used"))
        model_mode = str(response.get("mode") or "unknown")
        if candidate is None or not _materially_changed(post.draft_text, candidate):
            candidate = _deterministic_storytelling_revision(
                post.draft_text,
                revision_type,
                package_data,
                cleaned_notes,
            )
            fallback_used = True
            model_mode = "deterministic_fallback"
        candidate = _deduplicate_paragraphs(candidate)
        if not _materially_changed(post.draft_text, candidate):
            raise ContentInspirationError(
                "Revision did not materially change the post narrative."
            )
        new_version = int(post.package_version) + 1
        package_data["primary_post"] = candidate
        variants = package_data.get("variants")
        if isinstance(variants, list) and variants and isinstance(variants[0], dict):
            variants[0]["post_text"] = candidate
        package_data["package_version"] = new_version
        package_json = _json_dump(package_data)
        connection, should_close = _coerce_connection(database)
        try:
            now = _utc_now()
            _insert_content_version(
                connection,
                content_post_id=post_id,
                package_version=post.package_version,
                draft_text=post.draft_text,
                package_json=post.package_json or "{}",
                revision_type="baseline",
                revision_notes=None,
                model_mode="legacy",
                fallback_used=False,
                created_at=post.updated_at,
            )
            connection.execute(
                """
                UPDATE content_posts
                SET draft_text = ?, package_version = ?, package_json = ?,
                    status = 'draft', approved_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (candidate, new_version, package_json, now, post_id),
            )
            _insert_content_version(
                connection,
                content_post_id=post_id,
                package_version=new_version,
                draft_text=candidate,
                package_json=package_json,
                revision_type=revision_type,
                revision_notes=cleaned_notes,
                model_mode=model_mode,
                fallback_used=fallback_used,
                created_at=now,
            )
            connection.commit()
            return self.get_package(post_id, connection)
        finally:
            if should_close:
                connection.close()

    def select_variant(
        self,
        post_id: int,
        variant_number: int,
        database: sqlite3.Connection | str | Path,
    ) -> ContentPost:
        """Promote one frozen package variant to primary review text."""
        if variant_number not in {1, 2, 3}:
            raise ContentInspirationError("Variant number must be 1, 2, or 3.")
        post = self.get_package(post_id, database)
        if post.status in {"discarded", "rejected"}:
            raise ContentInspirationError("Rejected content packages cannot change variants.")
        package_data = _json_object(post.package_json)
        variants = package_data.get("variants")
        if not isinstance(variants, list) or len(variants) != 3:
            raise ContentInspirationError("This legacy package does not contain three selectable variants.")
        selected = variants[variant_number - 1]
        candidate = selected.get("post_text") if isinstance(selected, dict) else None
        if not isinstance(candidate, str) or not candidate.strip():
            raise ContentInspirationError("The selected variant has no valid post text.")
        if package_data.get("selected_variant") == variant_number and candidate == post.draft_text:
            return post
        new_version = int(post.package_version) + 1
        package_data.update(
            {
                "primary_post": candidate,
                "selected_variant": variant_number,
                "package_version": new_version,
            }
        )
        package_json = _json_dump(package_data)
        connection, should_close = _coerce_connection(database)
        try:
            now = _utc_now()
            _insert_content_version(
                connection,
                content_post_id=post_id,
                package_version=post.package_version,
                draft_text=post.draft_text,
                package_json=post.package_json or "{}",
                revision_type="baseline",
                revision_notes=None,
                model_mode="legacy",
                fallback_used=False,
                created_at=post.updated_at,
            )
            connection.execute(
                """
                UPDATE content_posts
                SET draft_text = ?, package_version = ?, package_json = ?,
                    status = 'draft', approved_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (candidate, new_version, package_json, now, post_id),
            )
            _insert_content_version(
                connection,
                content_post_id=post_id,
                package_version=new_version,
                draft_text=candidate,
                package_json=package_json,
                revision_type="select_variant",
                revision_notes=f"Selected variant {variant_number}",
                model_mode="deterministic_selection",
                fallback_used=False,
                created_at=now,
            )
            connection.commit()
            return self.get_package(post_id, connection)
        finally:
            if should_close:
                connection.close()

    def _build_deterministic_package(self, opportunity: sqlite3.Row, profile: dict[str, Any], references: list[Any], source_rows: list[sqlite3.Row]) -> ContentPackage:
        source = source_rows[0]
        identity = str(profile.get("professional_identity") or "a thoughtful technology professional")
        personal_angle = PersonalAngle(angle_type="professional_identity", text=identity, verified=False)
        try:
            planning_timezone: tzinfo = ZoneInfo(settings.briefing_timezone)
        except ZoneInfoNotFoundError:
            planning_timezone = UTC
        pillar = pillar_for_weekday(datetime.now(planning_timezone).weekday())
        hook_archetypes = hooks_for_pillar(pillar)
        topical_pillars = profile.get("content_pillars")
        topical_pillar = (
            str(topical_pillars[(int(opportunity["id"]) - 1) % len(topical_pillars)])
            if isinstance(topical_pillars, list) and topical_pillars
            else str(opportunity["suggested_angle"])
        )
        plan = ContentPlan(
            editorial_pillar=pillar.name,
            topical_pillar=topical_pillar,
            funnel_position=pillar.funnel_position,
            hook_archetype=hook_archetypes[0].name,
            hook_idea=hook_archetypes[0].instruction,
        )
        summary = str(source["summary"] or source["title"])
        title = str(source["title"])
        if "ai" in title.lower() or "artificial intelligence" in summary.lower():
            practical_lens = (
                "For AI product teams, capability is only the starting point. "
                "The harder work is defining edge cases, evaluation criteria, "
                "and the consequence of a wrong decision."
            )
            closing_point = (
                "Before a consequential decision, I would require evidence from "
                "the highest-risk edge case."
            )
        else:
            practical_lens = (
                f"For {opportunity['target_audience']}, the useful move is to "
                "separate what the source reports from the product or strategy "
                "decision it may change."
            )
            closing_point = (
                "Before turning this signal into a roadmap decision, I would test "
                "the assumption most likely to change the outcome."
            )
        primary = (
            f"{title}\n\n{summary}\n\n{practical_lens}\n\n"
            "A practical review starts with three checks. Separate source evidence "
            "from interpretation. Identify the boundary case with the highest cost. "
            "Set the evidence required for the next decision.\n\n"
            f"{closing_point}"
        )
        hook_texts = [
            f"{title} points to a gap between capability and dependable product judgment.",
            "The headline matters less than the evidence required for the next decision.",
            "A product signal becomes useful when it changes a specific decision.",
        ]
        variant_texts = [
            primary,
            (
                f"{hook_texts[1]}\n\n{summary}\n\n{practical_lens}\n\n"
                "I would separate the reported evidence from interpretation, name the highest-cost boundary case, "
                f"and set a decision threshold before expanding the claim.\n\n{closing_point}"
            ),
            (
                f"{hook_texts[2]}\n\n{summary}\n\nFor {opportunity['target_audience']}, the practical issue is not whether "
                "the signal sounds important. It is which assumption, risk, or roadmap choice should change.\n\n"
                "That creates a useful sequence: identify the supported claim, test the fragile assumption, and record "
                "the evidence needed for the next commitment."
            ),
        ]
        claim = FactualClaim(id="claim-1", claim_text=str(source["title"]), source_signal_ids=[int(source["id"])], confidence=0.8, directly_supported=True, softened=True, risk_note="Use source-linked wording and avoid unsupported prediction.")
        hooks = [
            AlternativeHook(text=text, rationale=archetype.instruction)
            for text, archetype in zip(hook_texts, hook_archetypes, strict=True)
        ]
        variants = [
            PostVariant(
                label=f"Variant {index}",
                hook_archetype=archetype.name,
                funnel_position=pillar.funnel_position,
                post_text=text,
            )
            for index, (archetype, text) in enumerate(
                zip(hook_archetypes, variant_texts, strict=True),
                start=1,
            )
        ]
        research = ResearchBrief(
            sources=[
                {
                    "id": f"src-{source['id']}",
                    "signal_id": int(source["id"]),
                    "url": str(source["canonical_url"]),
                    "title": title,
                    "summary": summary,
                    "source_type": "approved_public_signal",
                }
            ],
            evidence_points=[f"{title}: {summary}"],
            claim_ids=["claim-1"],
        )
        hook_artifact = HookArtifact(
            primary=hook_texts[0],
            alternatives=hooks,
            claim_ids=["claim-1"],
            selection_rationale="Deterministic hook selected from source evidence and the frozen editorial plan.",
        )
        carousel = CarouselArtifact(
            slides=[
                CarouselSlide(id="slide-1", role="cover", headline=hook_texts[0], visual_job="High-contrast statement", claim_ids=["claim-1"]),
                CarouselSlide(id="slide-2", role="evidence", headline="What the source supports", body=summary, visual_job="Source-backed evidence", claim_ids=["claim-1"]),
                CarouselSlide(id="slide-3", role="closing", headline="Set the evidence threshold", body=closing_point, visual_job="Direct takeaway", claim_ids=["claim-1"]),
            ]
        )
        caption = CaptionArtifact(
            text=primary,
            claim_ids=["claim-1"],
            source_references=research.sources,
            unresolved_gaps=research.gaps,
            carousel_sha256=carousel_fingerprint(carousel),
        )
        risk = ContentRiskAssessment(factual_risk=float(opportunity["factual_risk"]), generic_content_risk=float(opportunity["generic_commentary_risk"]), notes=["Source-linked claim only."], validation_passed=True)
        brief = ImageBrief(objective="Support the analytical post without implying an event or claim.", visual_idea="Minimal professional conceptual illustration of a product decision framework; no logos, screenshots, charts, quotations, or real people.", safety_notes=["No official branding", "No deceptive visual claims"])
        return ContentPackage(
            opportunity_id=int(opportunity["id"]),
            primary_post=primary,
            alternative_hooks=hooks,
            content_plan=plan,
            variants=variants,
            hook_ab=HookAB(hook_a=hook_texts[0], hook_b=hook_texts[1]),
            flop_adjustment=(
                "If this underperforms, replace the abstract setup with one source-specific consequence and shorten "
                "the opening before changing the evidence-backed thesis."
            ),
            target_audience=str(opportunity["target_audience"]),
            recommended_format=str(opportunity["recommended_format"]),
            content_treatment=str(opportunity["suggested_treatment"]),
            source_references=references,
            factual_claims=[claim],
            personal_angle=personal_angle,
            claims_requiring_confirmation=[],
            image_brief=brief,
            image_alt_text="Conceptual illustration supporting a product strategy discussion.",
            suggested_first_comment=None,
            suggested_hashtags=[],
            risk_assessment=risk,
            why_it_fits_profile=str(opportunity["rationale"]),
            profile_version=int(opportunity["profile_version"]),
            scoring_config_version=int(opportunity["scoring_config_version"]),
            package_version=1,
            research=research,
            hook=hook_artifact,
            carousel=carousel,
            caption=caption,
        )

    def _build_prompt(
        self,
        topic: str,
        inspiration_notes: str | None,
        user_image_path: str | None = None,
    ) -> str:
        prompt_parts = [
            "Draft an original LinkedIn post.",
            "The output must be JSON with key draft_text.",
            WRITING_STYLE_INSTRUCTIONS,
            f"Topic: {topic}",
            "Use inspiration as structural guidance only.",
            "This is inspiration, not duplication: do not reproduce another creator's specific wording.",
            "Only borrow high-level structural or stylistic patterns such as hook style, post length, and formatting.",
            "Do not invent credentials, outcomes, employers, or personal experiences the user has not stated.",
        ]
        if inspiration_notes:
            prompt_parts.extend(["Inspiration notes:", inspiration_notes])
        if user_image_path:
            prompt_parts.extend(
                [
                    "Uploaded image context:",
                    f"Image reference: {user_image_path}",
                    "Use the uploaded image as context for the post, but do not claim visual details that are not provided in text.",
                ]
            )
        return "\n".join(prompt_parts)

    def _resolve_image(
        self,
        topic: str,
        user_image_path: str | None,
        generate_image: bool,
    ) -> tuple[ContentPostImageSource, str | None, str | None]:
        if user_image_path:
            return "uploaded", user_image_path, None
        if generate_image:
            try:
                return (
                    "generated",
                    image_gateway.generate_image(
                        prompt=topic,
                        mock_mode=settings.mock_mode,
                        aspect_ratio=settings.default_content_image_aspect_ratio,
                    ),
                    None,
                )
            except Exception as exc:
                return "none", None, str(exc)
        return "none", None, None

    def _extract_draft_text(self, response: dict[str, Any]) -> str:
        result = response.get("result")
        if not isinstance(result, dict):
            raise ContentInspirationError("Model response result was not an object.")
        draft_text = result.get("draft_text")
        if not isinstance(draft_text, str) or not draft_text.strip():
            raise ContentInspirationError("Model response did not include draft_text.")
        return draft_text.strip()


def _coerce_connection(
    database: sqlite3.Connection | str | Path,
) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _content_post_from_row(row: sqlite3.Row) -> ContentPost:
    return ContentPost(
        id=row["id"],
        topic=row["topic"],
        draft_text=row["draft_text"],
        image_source=row["image_source"],
        image_path=row["image_path"],
        inspiration_source_notes=row["inspiration_source_notes"],
        status=row["status"],
        engagement_metric=row["engagement_metric"],
        opportunity_id=row["opportunity_id"], profile_version=row["profile_version"],
        scoring_config_version=row["scoring_config_version"], package_version=row["package_version"],
        package_json=row["package_json"], source_references_json=row["source_references_json"],
        factual_claims_json=row["factual_claims_json"], alternative_hooks_json=row["alternative_hooks_json"],
        personal_angle_json=row["personal_angle_json"], risk_assessment_json=row["risk_assessment_json"],
        suggested_first_comment=row["suggested_first_comment"], suggested_hashtags_json=row["suggested_hashtags_json"],
        image_brief_json=row["image_brief_json"], image_alt_text=row["image_alt_text"], approved_at=row["approved_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _required_lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise ContentInspirationError("SQLite did not return an inserted row id.")
    return cursor.lastrowid


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _revision_task_type(
    revision_type: str,
) -> Literal[
    "content_humor_revision",
    "content_hook_regeneration",
    "content_personalization_revision",
    "content_analytical_revision",
]:
    if revision_type in {"make_lighter", "make_funnier"}:
        return "content_humor_revision"
    if revision_type == "regenerate_hook":
        return "content_hook_regeneration"
    if revision_type == "make_more_personal":
        return "content_personalization_revision"
    return "content_analytical_revision"


def _revision_prompt(
    post: ContentPost,
    revision_type: str,
    revision_notes: str | None,
) -> str:
    return "\n".join(
        [
            "Act as a human storytelling editor for a professional LinkedIn post.",
            "Rewrite the entire post; do not append a generic paragraph to the existing copy.",
            "Create a cohesive narrative with a concrete opening, one useful insight, and a direct closing point.",
            WRITING_STYLE_INSTRUCTIONS,
            "Preserve source-backed facts exactly and do not invent personal experiences, credentials, outcomes, or relationships.",
            "Do not add unsupported facts. Return JSON with key primary_post only.",
            f"Revision goal: {revision_type}",
            f"Human notes: {revision_notes or 'none'}",
            f"Verified personal angle: {post.personal_angle_json or '{}'}",
            f"Source references: {post.source_references_json or '[]'}",
            f"Factual claims: {post.factual_claims_json or '[]'}",
            "Current post:",
            post.draft_text,
        ]
    )


def _card_display_text(package: ContentPackage) -> str:
    """Pick the strongest short line to render on a designed image card.

    Prefers a real hook over the internal image_brief.visual_idea, which is
    an art-direction instruction for a hypothetical external image provider,
    not text meant to be displayed to a reader.
    """
    if package.alternative_hooks:
        return package.alternative_hooks[0].text
    first_line = package.primary_post.split("\n\n", 1)[0].strip()
    return first_line or package.primary_post


def _package_generation_prompt(
    opportunity: sqlite3.Row,
    source: sqlite3.Row,
    package: ContentPackage,
    profile: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "Act as a thoughtful professional writing an original LinkedIn post yourself, not filling in a template.",
            "Write one cohesive, specific post: a concrete opening line, one real point of view grounded in the "
            "source below, and a direct closing thought.",
            "Do not default to a fixed listicle formula, such as always writing three generic numbered checks, "
            "unless the source genuinely calls for numbered steps. Vary structure, opening style, and pacing so "
            "the post does not read like a template.",
            WRITING_STYLE_INSTRUCTIONS,
            f"Professional identity and personal angle to write from: {package.personal_angle.text}",
            _voice_dna_prompt(profile),
            f"Editorial pillar: {package.content_plan.editorial_pillar}",
            f"Topical pillar: {package.content_plan.topical_pillar}",
            f"Funnel position: {package.content_plan.funnel_position}",
            f"Primary hook archetype: {package.content_plan.hook_archetype}",
            f"Hook direction: {package.content_plan.hook_idea}",
            f"Target audience: {opportunity['target_audience']}",
            f"Why this source fits the author's profile: {opportunity['rationale']}",
            "Source to ground the post in. Do not add any detail beyond what is stated here:",
            f"Title: {source['title']}",
            f"Summary: {source['summary']}",
            f"Source URL: {source['canonical_url']}",
            "Do not invent personal experience, credentials, employers, outcomes, or relationships beyond the "
            "professional identity given above.",
            "Return JSON only with exactly these keys in this contract:",
            "primary_post: the selected full post, exactly matching variants[0].post_text.",
            "alternative_hooks: 2 to 3 objects with text and rationale.",
            "variants: exactly 3 objects, ordered Variant 1 through Variant 3. Each object must contain label, "
            "hook_archetype, funnel_position, and the complete post_text. Each variant must use the same evidence "
            "but have a meaningfully different opening and structure.",
            "hook_ab: an object with hook_a and hook_b, each a standalone alternate opening for the primary post.",
            "flop_adjustment: one line describing the first evidence-preserving change to test if the post underperforms.",
        ]
    )


def _voice_dna_prompt(profile: dict[str, Any]) -> str:
    fields = (
        ("Tone", "preferred_tone"),
        ("Sentence rhythm", "voice_sentence_rhythm"),
        ("Vocabulary to use", "voice_vocabulary_to_use"),
        ("Vocabulary to avoid", "voice_vocabulary_to_avoid"),
        ("Formatting", "voice_formatting_rules"),
        ("Point of view", "voice_point_of_view"),
        ("Reference notes", "voice_reference_notes"),
        ("Content rules to follow", "content_rules_do"),
        ("Content rules to avoid", "content_rules_avoid"),
        ("CTA style", "cta_style"),
        ("Visual direction", "visual_direction"),
        ("Visual colors", "visual_colors"),
        ("Typography", "typography"),
        ("Imagery guidelines", "imagery_guidelines"),
    )
    lines = ["Voice DNA. Follow this profile without inventing biography:"]
    for label, key in fields:
        value = profile.get(key)
        if isinstance(value, list) and value:
            lines.append(f"{label}: {'; '.join(str(item) for item in value)}")
        elif isinstance(value, str) and value.strip():
            lines.append(f"{label}: {' '.join(value.split())}")
    return "\n".join(lines)


def _extract_generated_post_text(response: dict[str, Any]) -> str | None:
    if response.get("fallback_used"):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    value = result.get("primary_post")
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "mock" or len(cleaned) > 6000:
        return None
    return cleaned


def _extract_package_hooks(response: dict[str, Any]) -> list[AlternativeHook] | None:
    if response.get("fallback_used"):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    raw_hooks = result.get("alternative_hooks")
    if not isinstance(raw_hooks, list):
        return None
    hooks: list[AlternativeHook] = []
    for item in raw_hooks:
        if not isinstance(item, dict):
            continue
        try:
            hooks.append(AlternativeHook(text=str(item.get("text", "")), rationale=str(item.get("rationale", ""))))
        except ValidationError:
            continue
        if len(hooks) == 3:
            break
    if len(hooks) < 2:
        return None
    return hooks


def _extract_package_variants(
    response: dict[str, Any],
    primary_post: str | None,
) -> list[PostVariant] | None:
    if primary_post is None or response.get("fallback_used"):
        return None
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("variants"), list):
        return None
    variants: list[PostVariant] = []
    for item in result["variants"]:
        try:
            variants.append(PostVariant.model_validate(item))
        except ValidationError:
            return None
    if len(variants) != 3 or variants[0].post_text.strip() != primary_post:
        return None
    return variants


def _extract_hook_ab(response: dict[str, Any]) -> HookAB | None:
    if response.get("fallback_used"):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    try:
        return HookAB.model_validate(result.get("hook_ab"))
    except ValidationError:
        return None


def _extract_flop_adjustment(response: dict[str, Any]) -> str | None:
    if response.get("fallback_used"):
        return None
    result = response.get("result")
    value = result.get("flop_adjustment") if isinstance(result, dict) else None
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned if 0 < len(cleaned) <= 500 else None


def _materially_changed(before: str, after: str) -> bool:
    before_normalized = " ".join(before.split()).lower()
    after_normalized = " ".join(after.split()).lower()
    if before_normalized == after_normalized or not after_normalized:
        return False
    return SequenceMatcher(None, before_normalized, after_normalized).ratio() < 0.94


def _deduplicate_paragraphs(text: str) -> str:
    seen: set[str] = set()
    paragraphs: list[str] = []
    for paragraph in (item.strip() for item in text.split("\n\n")):
        normalized = " ".join(paragraph.lower().split())
        if paragraph and normalized not in seen:
            paragraphs.append(paragraph)
            seen.add(normalized)
    return "\n\n".join(paragraphs)


def _deterministic_storytelling_revision(
    current_text: str,
    revision_type: str,
    package_data: dict[str, Any],
    revision_notes: str | None,
) -> str:
    paragraphs = [item.strip() for item in current_text.split("\n\n") if item.strip()]
    title = paragraphs[0] if paragraphs else "A product signal worth examining"
    source_summary = paragraphs[1] if len(paragraphs) > 1 else title
    audience = str(package_data.get("target_audience") or "product leaders")

    if revision_type == "make_more_concise":
        return (
            f"{title}\n\n{source_summary}\n\n"
            "I would separate the headline from the decision it should change. "
            "Before acting, I would name the evidence still missing."
        )
    if revision_type == "make_more_analytical":
        return (
            f"{title}\n\n{source_summary}\n\n"
            "I see a gap between technical capability and operational trust. "
            "A demo gives limited evidence about boundary cases.\n\n"
            f"For {audience}, I would use three tests: define the cost of a wrong call, show uncertainty, "
            "and set the evidence required before wider use.\n\n"
            "A slower decision is often cheaper than rework when the failure cost is high."
        )
    if revision_type in {"make_more_practical", "reduce_hype"}:
        return (
            f"{title}\n\n{source_summary}\n\n"
            "Before turning that signal into a roadmap decision, I would slow the conversation down:\n"
            "1. Separate the reported evidence from assumptions.\n"
            "2. Name the boundary case most likely to change the outcome.\n"
            "3. Agree on what would make the team pause.\n\n"
            "This approach is less dramatic than a launch announcement. It gives the team a checkable path."
        )
    if revision_type in {"make_lighter", "make_funnier"}:
        return (
            f"{title}\n\n{source_summary}\n\n"
            "I pay attention to the part product demos leave out: edge cases and unclear ownership.\n\n"
            "I would respond with targeted tests, clear limits, and an explicit rule for when more evidence is needed.\n\n"
            "That keeps a fast launch from turning into avoidable rework."
        )
    if revision_type == "regenerate_hook":
        return (
            "A capable demo is not evidence of a dependable product.\n\n"
            f"{source_summary}\n\n"
            "I would test the distance between 'it works' and 'people can rely on it' through ambiguous inputs, visible uncertainty, and costly failure cases."
        )

    _ = revision_notes
    return (
        "I keep returning to a practical test: what evidence would make this system safe to rely on?\n\n"
        f"{source_summary}\n\n"
        "I would look at the decision, the evidence behind it, and the cost of being wrong.\n\n"
        "For product teams, the next step is specific: test the highest-risk boundary case before expanding the claim."
    )


def _insert_content_version(
    connection: sqlite3.Connection,
    *,
    content_post_id: int,
    package_version: int,
    draft_text: str,
    package_json: str,
    revision_type: str,
    revision_notes: str | None,
    model_mode: str,
    fallback_used: bool,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO content_post_versions (
            content_post_id, package_version, draft_text, package_json,
            revision_type, revision_notes, model_mode, fallback_used, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_post_id,
            package_version,
            draft_text,
            package_json,
            revision_type,
            revision_notes,
            model_mode,
            int(fallback_used),
            created_at,
        ),
    )
