"""Draft-only LinkedIn outreach agent."""

from typing import Any


class OutreachDraftAgent:
    """Draft outreach messages for manual copy/paste sending.

    Purpose:
        Create LinkedIn connection-request and follow-up drafts while never
        sending outreach through any API.
    Inputs:
        Prospect records, safe personalization signals, relationship status,
        last-touch data, core intent, refinable parameters, and user tone
        instructions.
    Outputs:
        Draft outreach text, safety notes, and metadata indicating the user
        must manually send the draft in LinkedIn.
    """

    def draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a mock manual-send outreach draft."""
        return {
            "mock": True,
            "draft": "",
            "manual_send_required": True,
            "payload": payload,
        }
