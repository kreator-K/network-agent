"""Profile context extraction agent."""

from typing import Any


class ProfileContextAgent:
    """Extract safe personalization signals from user-provided context.

    Purpose:
        Identify usable facts and risky claims from supplied profile text,
        notes, and interaction history.
    Inputs:
        Prospect records, copied profile text, user notes, and prior
        interactions.
    Outputs:
        Safe personalization signals and excluded risky claims.
    """

    def extract(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return a mock set of personalization signals."""
        return {"mock": True, "safe_signals": [], "excluded_claims": [], "context": context}
