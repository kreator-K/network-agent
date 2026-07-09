"""Image generation gateway stub."""

from typing import Any


class ImageGateway:
    """Mock-first boundary for future image generation.

    Purpose:
        Support ContentInspirationAgent image workflows without direct provider
        calls from agents.
    Inputs:
        Image prompt, selected user-uploaded image metadata, and generation
        preferences.
    Outputs:
        Mock image-selection or generation metadata.
    """

    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a mock image generation response."""
        return {"mock": True, "payload": payload}
