"""LinkedIn content inspiration and drafting agent."""

import sqlite3
import json
from difflib import SequenceMatcher
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from agents.model_orchestration_agent import ModelOrchestrationAgent
from config.settings import settings
from db.database import connect
from db.models import (
    AlternativeHook,
    ContentPackage,
    ContentPost,
    ContentPostImageSource,
    ContentRiskAssessment,
    FactualClaim,
    ImageBrief,
    PersonalAngle,
)
from integrations import image_gateway


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
        """Return content posts still waiting for Telegram review."""
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

    def generate_package_from_opportunity(
        self, opportunity_id: int, database: sqlite3.Connection | str | Path,
        image_mode: str = "disabled",
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
            # The deterministic package remains authoritative when model output is absent
            # or malformed; this bounded call is the sole optional language-model path.
            self.model_orchestration_agent.run_task(
                task_type="content_package_generation",
                prompt=f"Prepare a source-grounded LinkedIn package for: {opportunity['headline']}",
                expected_schema={"primary_post": str},
            )
            package = self._build_deterministic_package(opportunity, profile_data, references, source_rows)
            image_source, image_path = "none", None
            if image_mode == "mock":
                image_source, image_path = "generated", image_gateway.generate_image(
                    package.image_brief.visual_idea if package.image_brief else package.primary_post,
                    mock_mode=True,
                )
            elif image_mode == "real":
                try:
                    image_source, image_path = "generated", image_gateway.generate_image(
                        package.image_brief.visual_idea if package.image_brief else package.primary_post,
                        mock_mode=False,
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
                model_mode="deterministic",
                fallback_used=False,
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
        candidate = _revision_text(response)
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

    def _build_deterministic_package(self, opportunity: sqlite3.Row, profile: dict[str, Any], references: list[Any], source_rows: list[sqlite3.Row]) -> ContentPackage:
        source = source_rows[0]
        identity = str(profile.get("professional_identity") or "a thoughtful technology professional")
        personal_angle = PersonalAngle(angle_type="professional_identity", text=identity, verified=False)
        summary = str(source["summary"] or source["title"])
        title = str(source["title"])
        if "ai" in title.lower() or "artificial intelligence" in summary.lower():
            practical_lens = (
                "For AI product teams, capability is only the starting point. "
                "The harder work is defining edge cases, evaluation criteria, "
                "and the consequence of a wrong decision."
            )
            closing_question = (
                "What evidence would you require before letting the system "
                "influence a consequential decision?"
            )
        else:
            practical_lens = (
                f"For {opportunity['target_audience']}, the useful move is to "
                "separate what the source reports from the product or strategy "
                "decision it may change."
            )
            closing_question = (
                "Which assumption would you test before turning this signal into "
                "a roadmap decision?"
            )
        primary = (
            f"{title}\n\n{summary}\n\n{practical_lens}\n\n"
            "A practical review starts with three questions:\n"
            "1. What is directly supported by the source?\n"
            "2. Which boundary cases matter most?\n"
            "3. What would change the current decision?\n\n"
            f"{closing_question}"
        )
        claim = FactualClaim(id="claim-1", claim_text=str(source["title"]), source_signal_ids=[int(source["id"])], confidence=0.8, directly_supported=True, softened=True, risk_note="Use source-linked wording and avoid unsupported prediction.")
        hooks = [AlternativeHook(text=f"What {source['title']} means for product judgment", rationale="Analytical product hook."), AlternativeHook(text="A useful distinction before turning this signal into strategy", rationale="Avoids generic source summary.")]
        risk = ContentRiskAssessment(factual_risk=float(opportunity["factual_risk"]), generic_content_risk=float(opportunity["generic_commentary_risk"]), notes=["Source-linked claim only."], validation_passed=True)
        brief = ImageBrief(objective="Support the analytical post without implying an event or claim.", visual_idea="Minimal professional conceptual illustration of a product decision framework; no logos, screenshots, charts, quotations, or real people.", safety_notes=["No official branding", "No deceptive visual claims"])
        return ContentPackage(opportunity_id=int(opportunity["id"]), primary_post=primary, alternative_hooks=hooks, target_audience=str(opportunity["target_audience"]), recommended_format=str(opportunity["recommended_format"]), content_treatment=str(opportunity["suggested_treatment"]), source_references=references, factual_claims=[claim], personal_angle=personal_angle, claims_requiring_confirmation=[], image_brief=brief, image_alt_text="Conceptual illustration supporting a product strategy discussion.", suggested_first_comment=None, suggested_hashtags=[], risk_assessment=risk, why_it_fits_profile=str(opportunity["rationale"]), profile_version=int(opportunity["profile_version"]), scoring_config_version=int(opportunity["scoring_config_version"]), package_version=1)

    def _build_prompt(
        self,
        topic: str,
        inspiration_notes: str | None,
        user_image_path: str | None = None,
    ) -> str:
        prompt_parts = [
            "Draft an original LinkedIn post.",
            "The output must be JSON with key draft_text.",
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
                        prompt=f"LinkedIn post image for: {topic}",
                        mock_mode=settings.mock_mode,
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
            "Create a cohesive narrative arc with a natural opening, tension or insight, and a clear closing thought.",
            "Use varied sentence lengths and emotionally legible language without becoming theatrical.",
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


def _revision_text(response: dict[str, Any]) -> str | None:
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
            "What matters is not the headline alone, but the decision it changes. "
            "Where would you demand stronger evidence before acting?"
        )
    if revision_type == "make_more_analytical":
        return (
            f"{title}\n\n{source_summary}\n\n"
            "The interesting tension sits between technical capability and operational trust. "
            "A system can look convincing in a demo and still struggle at the boundary cases that shape real decisions.\n\n"
            f"For {audience}, that creates three tests: define the cost of a wrong call, make uncertainty visible, "
            "and decide what evidence is sufficient before expanding use.\n\n"
            "The strongest strategy is rarely the fastest deployment. It is the one that knows what must be true before moving forward."
        )
    if revision_type in {"make_more_practical", "reduce_hype"}:
        return (
            f"{title}\n\n{source_summary}\n\n"
            "Before turning that signal into a roadmap decision, I would slow the conversation down:\n"
            "1. Separate the reported evidence from assumptions.\n"
            "2. Name the boundary case most likely to change the outcome.\n"
            "3. Agree on what would make the team pause.\n\n"
            "That may sound less exciting than a launch announcement. It is also where dependable products are built."
        )
    if revision_type in {"make_lighter", "make_funnier"}:
        return (
            f"{title}\n\n{source_summary}\n\n"
            "This is the part of product work that rarely makes the demo reel: the edge cases arrive, pull up a chair, "
            "and ask whether the system is actually ready.\n\n"
            "The useful response is not more confidence. It is better testing, clearer limits, and a team willing to say, "
            "'we need more evidence.'\n\n"
            "Good judgment is not the opposite of speed. Sometimes it is what keeps speed from becoming rework."
        )
    if revision_type == "regenerate_hook":
        return (
            "When does an impressive capability become a trustworthy product?\n\n"
            f"{source_summary}\n\n"
            "That question stays with me because the distance between 'it works' and 'people can rely on it' is where product judgment lives.\n\n"
            "The answer is usually found in the uncomfortable cases: ambiguous inputs, visible uncertainty, and decisions where being wrong has a real cost."
        )

    _ = revision_notes
    return (
        "I keep coming back to one question: when does a capable system become one people can actually trust?\n\n"
        f"{source_summary}\n\n"
        "That is what makes this story feel human. The technology matters, but so does the moment when someone has to rely on its judgment.\n\n"
        "Product work becomes more than a feature list at that moment. It becomes a promise about how carefully the team has listened, tested, and learned.\n\n"
        "What would you need to see before that promise felt credible?"
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
