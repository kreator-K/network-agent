"""Unit tests for the injected Google Calendar MCP create-event boundary."""

from datetime import datetime, timezone
import asyncio
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent

from integrations.google_calendar_mcp_client import (
    GoogleCalendarMCPClient,
    GoogleCalendarMCPResponseError,
    GoogleCalendarMCPUnavailableError,
)


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


class FakeSession:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, arguments or {}))
        return self.response


def _dates() -> tuple[datetime, datetime]:
    return (
        datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 12, 11, 0, tzinfo=timezone.utc),
    )


def _result(**data: Any) -> CallToolResult:
    return CallToolResult(structuredContent=data, content=[])


async def _create(session: Any, **overrides: Any) -> Any:
    start, end = _dates()
    values: dict[str, Any] = {
        "calendar_id": "primary",
        "summary": "Review",
        "description": "Notes",
        "start": start,
        "end": end,
        "timezone": "America/New_York",
    }
    values.update(overrides)
    return await GoogleCalendarMCPClient(session).create_event(**values)


def test_success_and_exact_tool_payload() -> None:
    session = FakeSession(_result(id="evt-1", htmlLink="https://calendar.google/e/1", status="confirmed"))
    result = _run(_create(session))
    name, payload = session.calls[0]
    assert result.event_id == "evt-1"
    assert result.html_link == "https://calendar.google/e/1"
    assert result.status == "confirmed"
    assert name == "create-event"
    assert set(payload) == {"calendarId", "summary", "description", "start", "end", "timeZone", "sendUpdates"}
    assert "attendees" not in payload
    assert payload["sendUpdates"] == "none"
    assert payload["start"].endswith("+00:00") and payload["end"].endswith("+00:00")


@pytest.mark.parametrize("override", [{"end": _dates()[0]}, {"start": _dates()[1]}])
def test_invalid_order_rejected_before_call(override: dict[str, Any]) -> None:
    session = FakeSession(_result(id="evt"))
    with pytest.raises(ValueError):
        _run(_create(session, **override))
    assert session.calls == []


@pytest.mark.parametrize("field", ["calendar_id", "summary", "timezone"])
def test_required_strings_rejected(field: str) -> None:
    session = FakeSession(_result(id="evt"))
    with pytest.raises(ValueError):
        _run(_create(session, **{field: "  "}))
    assert session.calls == []


def test_naive_datetimes_rejected() -> None:
    session = FakeSession(_result(id="evt"))
    with pytest.raises(ValueError):
        _run(_create(session, start=datetime(2026, 7, 12, 10), end=_dates()[1]))
    with pytest.raises(ValueError):
        _run(_create(session, start=_dates()[0], end=datetime(2026, 7, 12, 11)))
    assert session.calls == []


def test_mcp_error_is_controlled() -> None:
    session = FakeSession(CallToolResult(content=[], isError=True))
    with pytest.raises(GoogleCalendarMCPResponseError):
        _run(_create(session))


def test_missing_event_id_is_controlled() -> None:
    with pytest.raises(GoogleCalendarMCPResponseError):
        _run(_create(FakeSession(_result(status="created"))))


def test_unavailable_session_is_controlled() -> None:
    with pytest.raises(GoogleCalendarMCPUnavailableError):
        _run(_create(None))


def test_json_text_fallback_and_html_alias() -> None:
    response = CallToolResult(
        content=[TextContent(type="text", text='{"eventId":"evt-2","html_link":"mock://event"}')]
    )
    result = _run(_create(FakeSession(response)))
    assert result.event_id == "evt-2"
    assert result.html_link == "mock://event"


def test_invalid_text_is_rejected_cleanly() -> None:
    response = CallToolResult(content=[TextContent(type="text", text="not json")])
    with pytest.raises(GoogleCalendarMCPResponseError):
        _run(_create(FakeSession(response)))
