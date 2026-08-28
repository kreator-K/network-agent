"""Tests for the image generation gateway."""

import types
from pathlib import Path

import pytest
from PIL import Image

from integrations import image_gateway
from integrations.image_gateway import generate_image, render_branded_card


@pytest.fixture(autouse=True)
def _isolated_media_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect generated media into a temp directory for every test."""
    fake_settings = types.SimpleNamespace(media_storage_path=str(tmp_path))
    monkeypatch.setattr(image_gateway, "settings", fake_settings)


def test_generate_image_mock_mode_returns_path_without_real_call() -> None:
    result = generate_image("AI PM transitions", mock_mode=True)

    assert result == "mock://generated-linkedin-image.png"


def test_generate_image_real_mode_renders_a_real_png() -> None:
    result = generate_image("The demo worked. That is not the same as ready.", mock_mode=False)

    path = Path(result)
    assert path.exists()
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == (1200, 1200)


def test_render_branded_card_respects_aspect_ratio() -> None:
    result = render_branded_card("A short headline for a tall card", aspect_ratio="4:5")

    with Image.open(result) as image:
        assert image.size == (1080, 1350)


def test_render_branded_card_is_deterministic_for_same_input() -> None:
    first = render_branded_card("Same text every time", aspect_ratio="1:1")
    second = render_branded_card("Same text every time", aspect_ratio="1:1")

    assert first == second


def test_render_branded_card_differs_for_different_text() -> None:
    first = render_branded_card("First distinct headline", aspect_ratio="1:1")
    second = render_branded_card("Second distinct headline", aspect_ratio="1:1")

    assert first != second


def test_render_branded_card_handles_long_text_without_overflow_crash() -> None:
    long_text = " ".join(["word"] * 120)

    result = render_branded_card(long_text, aspect_ratio="1:1")

    with Image.open(result) as image:
        assert image.size == (1200, 1200)


def test_render_branded_card_handles_empty_text() -> None:
    result = render_branded_card("   ", aspect_ratio="1:1")

    with Image.open(result) as image:
        assert image.size == (1200, 1200)
