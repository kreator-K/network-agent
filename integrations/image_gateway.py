"""Image generation gateway.

Phase 1 supports deterministic mock image paths only. Real image-provider
integration belongs to Phase 3 and is intentionally not implemented here.
"""


MOCK_IMAGE_PATH = "mock://generated-linkedin-image.png"


def generate_image(prompt: str, mock_mode: bool) -> str:
    """Return a generated image path.

    In mock mode this returns a deterministic marker path without calling any
    real API. In real mode this raises because actual image-provider
    integration is Phase 3 scope.
    """
    if mock_mode:
        return MOCK_IMAGE_PATH
    raise NotImplementedError(
        "Real image generation is Phase 3 scope and is not implemented yet."
    )
