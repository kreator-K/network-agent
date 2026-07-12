"""LinkedIn content inspiration and drafting agent."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from agents.model_orchestration_agent import ModelOrchestrationAgent
from config.settings import settings
from db.database import connect
from db.models import ContentPost, ContentPostImageSource
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
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _required_lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise ContentInspirationError("SQLite did not return an inserted row id.")
    return cursor.lastrowid


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
