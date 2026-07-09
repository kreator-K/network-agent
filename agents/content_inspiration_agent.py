"""LinkedIn content inspiration and drafting agent."""

from typing import Any


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

    def draft_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a mock post draft."""
        return {"mock": True, "draft": "", "payload": payload}
