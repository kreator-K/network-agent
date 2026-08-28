"""Graph-mode tests for source-grounded content artifact generation."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agents.carousel_maker_agent import CarouselMakerAgent
from agents.content_inspiration_agent import ContentInspirationAgent, ContentInspirationError
from tests.test_content_packages import FakeModel, _opportunity


def test_enabled_content_graph_persists_verified_node_receipts(tmp_path) -> None:
    database, opportunity_id = _opportunity(tmp_path)

    post = ContentInspirationAgent(FakeModel()).generate_package_from_opportunity(
        opportunity_id,
        database,
        graph_mode="enabled",
    )

    package = json.loads(post.package_json or "{}")
    workflow = package["generation_workflow"]
    assert workflow["workflow_name"] == "content_artifacts"
    assert workflow["status"] == "completed"
    assert workflow["nodes"]["research"]["status"] == "completed"
    assert workflow["nodes"]["verify_evidence"]["output"]["passed"] is True
    assert workflow["nodes"]["bundle"]["status"] == "completed"
    assert package["caption"]["carousel_sha256"]
    assert post.status == "draft"


def test_shadow_content_graph_does_not_duplicate_model_calls(tmp_path) -> None:
    database, opportunity_id = _opportunity(tmp_path)

    class CountingModel(FakeModel):
        def __init__(self) -> None:
            self.calls: list[str] = []

        def run_task(
            self,
            task_type: str,
            prompt: str,
            expected_schema: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            self.calls.append(task_type)
            return super().run_task(task_type, prompt, expected_schema)

    model = CountingModel()
    post = ContentInspirationAgent(model).generate_package_from_opportunity(
        opportunity_id,
        database,
        graph_mode="shadow",
    )

    package = json.loads(post.package_json or "{}")
    assert package["generation_workflow"]["executed"] is False
    assert model.calls.count("content_hook_generation") == 1
    assert model.calls.count("carousel_generation") == 1
    assert model.calls.count("caption_generation") == 1
    assert model.calls.count("content_package_generation") == 1


def test_graph_falls_back_to_plan_when_carousel_rendering_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, opportunity_id = _opportunity(tmp_path)

    class FailingRenderer(CarouselMakerAgent):
        def make(self, *args: Any, render: bool = False, **kwargs: Any):  # type: ignore[no-untyped-def]
            if render:
                raise RuntimeError("render provider unavailable")
            return super().make(*args, render=False, **kwargs)

    agent = ContentInspirationAgent(FakeModel())
    agent.carousel_maker_agent = FailingRenderer()
    monkeypatch.setattr(
        "agents.content_inspiration_agent.image_gateway.generate_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disabled")),
    )

    post = agent.generate_package_from_opportunity(
        opportunity_id,
        database,
        image_mode="real",
        graph_mode="enabled",
    )

    package = json.loads(post.package_json or "{}")
    bundle = package["generation_workflow"]["nodes"]["bundle"]["output"]
    assert bundle["render_fallback_used"] is True
    assert package["carousel"]["status"] == "planned"
    assert package["caption"]["status"] == "completed"
    assert post.image_source == "none"


def test_invalid_content_graph_mode_fails_closed(tmp_path) -> None:
    database, opportunity_id = _opportunity(tmp_path)

    with pytest.raises(ContentInspirationError, match="disabled, shadow, or enabled"):
        ContentInspirationAgent(FakeModel()).generate_package_from_opportunity(
            opportunity_id,
            database,
            graph_mode="dynamic",
        )
