"""Tests for ContentInspirationAgent."""

from pathlib import Path
from typing import Any

import pytest
import pytest_mock

from agents import content_inspiration_agent as content_module
from agents.content_inspiration_agent import ContentInspirationAgent
from db.database import connect, initialize_database


class FakeModelOrchestrationAgent:
    """Captures model calls and returns a deterministic post draft."""

    def __init__(self, draft_text: str = "Mock LinkedIn post draft.") -> None:
        self.draft_text = draft_text
        self.calls: list[dict[str, Any]] = []

    def run_task(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "task_type": task_type,
                "prompt": prompt,
                "expected_schema": expected_schema,
            }
        )
        return {
            "task_type": task_type,
            "mode": "mock",
            "fallback_used": False,
            "result": {"draft_text": self.draft_text},
        }


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """Create a clean temporary database for content post tests."""
    path = tmp_path / "network_agent.db"
    initialize_database(path)
    return path


def test_draft_post_calls_model_orchestrator_with_correct_task_type() -> None:
    model = FakeModelOrchestrationAgent()

    ContentInspirationAgent(model).draft_post("AI PM transitions")

    assert model.calls[0]["task_type"] == "content_post_draft"
    assert model.calls[0]["expected_schema"] == {"draft_text": str}


def test_draft_post_prompt_instructs_against_copying_specific_wording() -> None:
    model = FakeModelOrchestrationAgent()

    ContentInspirationAgent(model).draft_post(
        topic="AI PM transitions",
        inspiration_notes="Similar structure to posts about AI PM transitions.",
    )

    prompt = model.calls[0]["prompt"]
    assert "inspiration, not duplication" in prompt
    assert "do not reproduce another creator's specific wording" in prompt
    assert "hook style, post length, and formatting" in prompt
    assert "Similar structure to posts about AI PM transitions." in prompt


def test_user_image_takes_precedence_over_generate_image_flag(
    mocker: pytest_mock.MockerFixture,
) -> None:
    model = FakeModelOrchestrationAgent()
    image_generate = mocker.patch.object(content_module.image_gateway, "generate_image")

    result = ContentInspirationAgent(model).draft_post(
        "AI PM transitions",
        user_image_path="/tmp/user.png",
        generate_image=True,
    )

    assert result["image_source"] == "uploaded"
    assert result["image_path"] == "/tmp/user.png"
    image_generate.assert_not_called()
    assert "Uploaded image context" in model.calls[0]["prompt"]


def test_manual_research_package_runs_all_four_specialists(database_path: Path) -> None:
    model = FakeModelOrchestrationAgent()
    agent = ContentInspirationAgent(model)

    post = agent.create_package_from_research(
        topic="AI product evidence",
        source_title="Evaluation report",
        source_url="https://example.com/report",
        evidence_text="The supplied report describes a bounded evaluation.",
        research_resource_id=9,
        image_source="none",
        image_path=None,
        image_alt_text=None,
        database=database_path,
    )

    assert post.package_json is not None
    assert post.opportunity_id is None
    assert [call["task_type"] for call in model.calls] == [
        "content_hook_generation",
        "carousel_generation",
        "caption_generation",
    ]


def test_generate_image_used_when_no_user_image_provided(
    mocker: pytest_mock.MockerFixture,
) -> None:
    model = FakeModelOrchestrationAgent()
    image_generate = mocker.patch.object(
        content_module.image_gateway,
        "generate_image",
        return_value="mock://image.png",
    )

    result = ContentInspirationAgent(model).draft_post(
        "AI PM transitions",
        generate_image=True,
    )

    assert result["image_source"] == "generated"
    assert result["image_path"] == "mock://image.png"
    image_generate.assert_called_once_with(
        prompt="AI PM transitions",
        mock_mode=content_module.settings.mock_mode,
        aspect_ratio=content_module.settings.default_content_image_aspect_ratio,
    )


def test_image_gateway_failure_falls_back_to_text_only(
    mocker: pytest_mock.MockerFixture,
) -> None:
    model = FakeModelOrchestrationAgent()
    mocker.patch.object(
        content_module.image_gateway,
        "generate_image",
        side_effect=RuntimeError("gateway unavailable"),
    )

    result = ContentInspirationAgent(model).draft_post(
        "AI PM transitions",
        generate_image=True,
    )

    assert result["image_source"] == "none"
    assert result["image_path"] is None
    assert "gateway unavailable" in result["image_error"]


def test_no_image_when_neither_provided() -> None:
    result = ContentInspirationAgent(FakeModelOrchestrationAgent()).draft_post(
        "AI PM transitions"
    )

    assert result["image_source"] == "none"
    assert result["image_path"] is None


def test_save_draft_to_db_persists_with_draft_status(database_path: Path) -> None:
    agent = ContentInspirationAgent(FakeModelOrchestrationAgent())
    draft = {
        "draft_text": "Draft",
        "image_source": "none",
        "image_path": None,
        "inspiration_source_notes": "Use a crisp hook.",
    }

    with connect(database_path) as connection:
        post = agent.save_draft_to_db(draft, connection)

    assert post.id is not None
    assert post.draft_text == "Draft"
    assert post.status == "draft"
    assert post.inspiration_source_notes == "Use a crisp hook."


def test_plain_draft_publish_readiness_explains_package_requirement(
    database_path: Path,
) -> None:
    agent = ContentInspirationAgent(FakeModelOrchestrationAgent())
    with connect(database_path) as connection:
        post = agent.save_draft_to_db(
            {
                "draft_text": "Draft",
                "image_source": "none",
                "image_path": None,
                "inspiration_source_notes": None,
            },
            connection,
        )
        readiness = agent.get_publish_readiness(post.id or 0, connection)

    assert readiness["exists"] is True
    assert readiness["package_backed"] is False
    assert readiness["ready"] is False
    assert "plain topic draft" in readiness["blockers"][0]


def test_missing_post_publish_readiness_is_explicit(database_path: Path) -> None:
    agent = ContentInspirationAgent(FakeModelOrchestrationAgent())

    readiness = agent.get_publish_readiness(999, database_path)

    assert readiness == {
        "exists": False,
        "package_backed": False,
        "ready": False,
        "status": None,
        "blockers": ["Content post id 999 does not exist."],
    }


def test_get_pending_drafts_returns_draft_status(database_path: Path) -> None:
    agent = ContentInspirationAgent(FakeModelOrchestrationAgent())
    with connect(database_path) as connection:
        agent.save_draft_to_db(
            {
                "draft_text": "Draft",
                "image_source": "none",
                "image_path": None,
                "inspiration_source_notes": None,
            },
            connection,
        )

        pending = agent.get_pending_drafts(connection)

    assert [post.draft_text for post in pending] == ["Draft"]


def test_get_pending_drafts_excludes_discarded_status(database_path: Path) -> None:
    agent = ContentInspirationAgent(FakeModelOrchestrationAgent())
    with connect(database_path) as connection:
        agent.save_draft_to_db(
            {
                "draft_text": "Draft",
                "image_source": "none",
                "image_path": None,
                "inspiration_source_notes": None,
            },
            connection,
        )
        connection.execute(
            """
            INSERT INTO content_posts (draft_text, image_source, status, created_at)
            VALUES
                ('Saved', 'none', 'saved', '2026-01-01'),
                ('Approved', 'none', 'approved_for_later_posting', '2026-01-01'),
                ('Discarded', 'none', 'discarded', '2026-01-01')
            """
        )

        pending = agent.get_pending_drafts(connection)

    assert {post.status for post in pending} == {
        "draft",
        "saved",
        "approved_for_later_posting",
    }
    assert {post.draft_text for post in pending} == {"Draft", "Saved", "Approved"}


def test_mock_mode_produces_deterministic_draft() -> None:
    model = FakeModelOrchestrationAgent("Deterministic draft")

    first = ContentInspirationAgent(model).draft_post("AI PM transitions")
    second = ContentInspirationAgent(model).draft_post("AI PM transitions")

    assert first["draft_text"] == "Deterministic draft"
    assert second["draft_text"] == "Deterministic draft"
    assert first["mode"] == "mock"
    assert first["fallback_used"] is False
