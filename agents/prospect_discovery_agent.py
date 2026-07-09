"""Prospect intake and normalization agent."""

from typing import Any


class ProspectDiscoveryAgent:
    """Normalize manually provided prospect information.

    Purpose:
        Intake prospect name, LinkedIn URL, copied profile text, and notes
        without scraping or programmatic LinkedIn search.
    Inputs:
        User-provided prospect fields such as name, profile URL, company,
        title, location, notes, and profile text.
    Outputs:
        A structured prospect draft plus missing-field prompts.
    """

    def intake(self, prospect_data: dict[str, Any]) -> dict[str, Any]:
        """Return a mock normalized prospect payload."""
        return {"mock": True, "prospect": prospect_data, "missing_fields": []}
