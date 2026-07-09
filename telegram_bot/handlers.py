"""Thin Telegram handler stubs."""

from typing import Any

from agents.orchestrator import NetworkOrchestrator


def handle_command(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a command-shaped payload and route it through the orchestrator."""
    orchestrator = NetworkOrchestrator()
    return orchestrator.handle(command, payload)
