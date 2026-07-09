"""Nvidia NIM model gateway stub."""

from typing import Any


class NvidiaModelGateway:
    """Mock-first boundary for future Nvidia NIM calls.

    Purpose:
        Keep provider-specific model access outside specialist agents.
    Inputs:
        Model request payloads from ModelOrchestrationAgent.
    Outputs:
        Mock provider responses until real integration is enabled.
    """

    def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a mock completion response."""
        return {"mock": True, "payload": payload}
