"""Mockable boundary for the Google Calendar MCP ``create-event`` tool.

This module deliberately does not create an MCP session, start ``npx``, or
make a network request. A ready session/tool caller is injected by the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class GoogleCalendarMCPError(RuntimeError):
    """Base error for controlled Google Calendar MCP failures."""


class GoogleCalendarMCPUnavailableError(GoogleCalendarMCPError):
    """Raised when no initialized MCP tool caller is available."""


class GoogleCalendarMCPResponseError(GoogleCalendarMCPError):
    """Raised when the MCP result is an error or lacks a usable event ID."""


@dataclass(frozen=True)
class CalendarEventResult:
    event_id: str
    html_link: str | None
    status: str


class MCPToolCaller(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        """Call one initialized MCP tool."""


class GoogleCalendarMCPClient:
    """Call only the injected Google Calendar MCP tool boundary."""

    def __init__(self, session: MCPToolCaller | None) -> None:
        self.session = session

    async def create_event(
        self,
        *,
        calendar_id: str,
        summary: str,
        description: str,
        start: datetime,
        end: datetime,
        timezone: str,
    ) -> CalendarEventResult:
        """Create one no-invite calendar event through MCP."""
        self._validate_inputs(calendar_id, summary, timezone, start, end)
        if self.session is None:
            raise GoogleCalendarMCPUnavailableError(
                "Google Calendar MCP session is unavailable."
            )
        payload = {
            "calendarId": calendar_id,
            "summary": summary,
            "description": description,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeZone": timezone,
            "sendUpdates": "none",
        }
        try:
            response = await self.session.call_tool("create-event", arguments=payload)
        except GoogleCalendarMCPError:
            raise
        except Exception as exc:
            raise GoogleCalendarMCPUnavailableError(
                "Google Calendar MCP tool call was unavailable."
            ) from exc
        return _parse_result(response)

    @staticmethod
    def _validate_inputs(
        calendar_id: str,
        summary: str,
        timezone: str,
        start: datetime,
        end: datetime,
    ) -> None:
        if not calendar_id.strip():
            raise ValueError("calendar_id must be non-empty.")
        if not summary.strip():
            raise ValueError("summary must be non-empty.")
        if not timezone.strip():
            raise ValueError("timezone must be non-empty.")
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be timezone-aware.")
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("end must be timezone-aware.")
        if end <= start:
            raise ValueError("end must be later than start.")


def _parse_result(response: Any) -> CalendarEventResult:
    if response is None:
        raise GoogleCalendarMCPUnavailableError("Google Calendar MCP returned no response.")
    if bool(getattr(response, "isError", False)):
        raise GoogleCalendarMCPResponseError("Google Calendar MCP returned an error result.")

    candidates: list[dict[str, Any]] = []
    structured = getattr(response, "structuredContent", None)
    if isinstance(structured, dict):
        candidates.append(structured)
    for item in getattr(response, "content", []) or []:
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)

    for candidate in candidates:
        event_id = candidate.get("id") or candidate.get("eventId")
        if isinstance(event_id, str) and event_id.strip():
            html_link = candidate.get("htmlLink", candidate.get("html_link"))
            return CalendarEventResult(
                event_id=event_id,
                html_link=html_link if isinstance(html_link, str) else None,
                status=str(candidate.get("status") or "created"),
            )
    raise GoogleCalendarMCPResponseError(
        "Google Calendar MCP response did not include a valid event ID."
    )
