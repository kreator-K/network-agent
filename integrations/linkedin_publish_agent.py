"""Fresh LinkedIn post publishing integration stub."""

from typing import Any


class LinkedInPublishAgent:
    """Publish approved LinkedIn posts only after explicit approval.

    Purpose:
        Provide a thin wrapper around future LinkedIn Share/Posts API calls.
        This integration never sends connection requests, messages, notes, or
        InMail.
    Inputs:
        Approved post content, approval metadata, optional media reference,
        and LinkedIn auth configuration.
    Outputs:
        Mock publish result or future structured API result.
    """

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a mock publish result without calling LinkedIn."""
        return {"mock": True, "published": False, "payload": payload}
