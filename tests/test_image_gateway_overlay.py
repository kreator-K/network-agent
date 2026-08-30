"""Tests for user-image text overlays."""

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from integrations import image_gateway


def test_render_text_overlay_creates_linkedin_portrait_png(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (640, 480), color=(120, 30, 60)).save(source)
    monkeypatch.setattr(
        image_gateway,
        "settings",
        SimpleNamespace(media_storage_path=str(tmp_path)),
    )

    result = Path(image_gateway.render_text_overlay(str(source), "A source-backed point"))

    assert result.exists()
    with Image.open(result) as rendered:
        assert rendered.size == (1080, 1350)
        assert rendered.format == "PNG"
