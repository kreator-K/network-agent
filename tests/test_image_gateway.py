"""Tests for the image generation gateway."""

import pytest

from integrations.image_gateway import generate_image


def test_generate_image_mock_mode_returns_path_without_real_call() -> None:
    result = generate_image("AI PM transitions", mock_mode=True)

    assert result == "mock://generated-linkedin-image.png"


def test_generate_image_real_mode_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase 3"):
        generate_image("AI PM transitions", mock_mode=False)
