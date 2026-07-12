"""Unit tests for the injected Google Calendar MCP create-event boundary."""

from datetime import datetime, timezone
import asyncio
from typing import Any
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

from integrations import google_calendar_mcp_client as client_module
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


def test_explicit_account_is_trimmed_and_included(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", SimpleNamespace(google_calendar_account=" work "))
    session = FakeSession(_result(id="evt-account"))
    _run(_create(session))
    assert session.calls[0][1]["account"] == "work"


def test_blank_account_is_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", SimpleNamespace(google_calendar_account="   "))
    session = FakeSession(_result(id="evt-blank"))
    _run(_create(session))
    assert "account" not in session.calls[0][1]


def test_nested_event_response_is_parsed() -> None:
    result = _run(_create(FakeSession(_result(
        event={"id": "evt-nested", "htmlLink": "mock://nested", "status": "confirmed"}
    ))))
    assert result.event_id == "evt-nested"
    assert result.html_link == "mock://nested"
    assert result.status == "confirmed"


def test_nested_error_detail_is_preserved_and_redacted() -> None:
    response = CallToolResult(
        content=[TextContent(
            type="text",
            text="permission denied access_token=secret-value refresh_token=refresh-value",
        )],
        isError=True,
    )
    with pytest.raises(GoogleCalendarMCPResponseError) as exc_info:
        _run(_create(FakeSession(response)))
    message = str(exc_info.value)
    assert "permission denied" in message
    assert "secret-value" not in message
    assert "refresh-value" not in message


def test_invalid_text_is_rejected_cleanly() -> None:
    response = CallToolResult(content=[TextContent(type="text", text="not json")])
    with pytest.raises(GoogleCalendarMCPResponseError):
        _run(_create(FakeSession(response)))
