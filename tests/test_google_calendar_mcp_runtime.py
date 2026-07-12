"""Unit tests for the persistent Google Calendar MCP stdio runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from integrations.google_calendar_mcp_client import (
    GoogleCalendarMCPClient,
    GoogleCalendarMCPUnavailableError,
)
from integrations.google_calendar_mcp_runtime import GoogleCalendarMCPRuntime


def run_async(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


class FakeAsyncContext:
    def __init__(self, value: Any, *, close_error: Exception | None = None) -> None:
        self.value = value
        self.entered = False
        self.closed = False
        self.close_error = close_error

    async def __aenter__(self) -> Any:
        self.entered = True
        return self.value

    async def __aexit__(self, *_: Any) -> None:
        self.closed = True
        if self.close_error:
            raise self.close_error


class FakeSession:
    def __init__(self, tools: list[str] | None = None) -> None:
        self.tools = tools or ["create-event", "get-current-time"]
        self.initialize_calls = 0
        self.list_tools_calls = 0

    async def initialize(self) -> None:
        self.initialize_calls += 1

    async def list_tools(self) -> Any:
        self.list_tools_calls += 1
        return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in self.tools])


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    credentials.write_text("placeholder", encoding="utf-8")
    token.write_text("placeholder", encoding="utf-8")
    return credentials, token


def make_runtime(
    files: tuple[Path, Path],
    *,
    tools: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[GoogleCalendarMCPRuntime, FakeAsyncContext, FakeAsyncContext, FakeSession, Any]:
    credentials, token = files
    entrypoint = files[0].parent / "vendor/google-calendar-mcp/node_modules/@cocal/google-calendar-mcp/build/index.js"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("// test placeholder", encoding="utf-8")
    session = FakeSession(tools)
    transport = FakeAsyncContext(("read", "write"))
    session_context = FakeAsyncContext(session)
    captured: dict[str, Any] = {}

    def stdio_factory(parameters: Any) -> FakeAsyncContext:
        captured["parameters"] = parameters
        return transport

    def session_factory(read_stream: Any, write_stream: Any) -> FakeAsyncContext:
        captured["streams"] = (read_stream, write_stream)
        return session_context

    runtime = GoogleCalendarMCPRuntime(
        credentials_path=credentials,
        token_path=token,
        repository_root=files[0].parent,
        stdio_client_factory=stdio_factory,
        session_factory=session_factory,
    )
    captured["runtime"] = runtime
    return runtime, transport, session_context, session, captured


def test_successful_start_initializes_session_and_preserves_environment(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _, _, session, captured = make_runtime(files)
    monkeypatch.setattr(
        "integrations.google_calendar_mcp_runtime.shutil.which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    monkeypatch.setenv("RUNTIME_TEST_SENTINEL", "preserved")

    async def scenario() -> tuple[Any, bool, bool]:
        await runtime.start()
        started = runtime.is_started
        typed_client = isinstance(runtime.client, GoogleCalendarMCPClient)
        await runtime.close()
        return captured["parameters"], started, typed_client

    parameters, started, typed_client = run_async(scenario())
    assert started is True
    assert typed_client is True
    assert parameters.command == str(Path("/usr/bin/node").resolve())
    assert parameters.args == [
        str(
            (files[0].parent / "vendor/google-calendar-mcp/node_modules/@cocal/google-calendar-mcp/build/index.js").resolve()
        )
    ]
    assert parameters.env["GOOGLE_OAUTH_CREDENTIALS"] == str(files[0])
    assert parameters.env["GOOGLE_CALENDAR_MCP_TOKEN_PATH"] == str(files[1])
    assert parameters.env["ENABLED_TOOLS"] == "create-event,get-current-time"
    assert parameters.env["RUNTIME_TEST_SENTINEL"] == "preserved"
    assert session.initialize_calls == 1
    assert session.list_tools_calls == 1


def test_missing_create_event_fails_and_cleans_up(files: tuple[Path, Path]) -> None:
    runtime, transport, session_context, _, _ = make_runtime(files, tools=["get-current-time"])

    with pytest.raises(GoogleCalendarMCPUnavailableError):
        run_async(runtime.start())

    assert transport.closed is True
    assert session_context.closed is True
    assert runtime.is_started is False


def test_missing_files_fail_before_stdio(files: tuple[Path, Path]) -> None:
    credentials, token = files
    calls = 0

    def stdio_factory(_: Any) -> FakeAsyncContext:
        nonlocal calls
        calls += 1
        return FakeAsyncContext(("read", "write"))

    runtime = GoogleCalendarMCPRuntime(
        credentials_path=credentials.with_name("missing.json"),
        token_path=token,
        stdio_client_factory=stdio_factory,
    )
    with pytest.raises(GoogleCalendarMCPUnavailableError):
        run_async(runtime.start())
    assert calls == 0


def test_missing_token_file_fails_before_stdio(files: tuple[Path, Path]) -> None:
    credentials, token = files
    calls = 0

    def stdio_factory(_: Any) -> FakeAsyncContext:
        nonlocal calls
        calls += 1
        return FakeAsyncContext(("read", "write"))

    runtime = GoogleCalendarMCPRuntime(
        credentials_path=credentials,
        token_path=token.with_name("missing-token.json"),
        stdio_client_factory=stdio_factory,
    )
    with pytest.raises(GoogleCalendarMCPUnavailableError):
        run_async(runtime.start())
    assert calls == 0


def test_missing_node_fails_before_stdio(files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, _, _, captured = make_runtime(files)
    monkeypatch.setattr("integrations.google_calendar_mcp_runtime.shutil.which", lambda _: None)

    with pytest.raises(GoogleCalendarMCPUnavailableError):
        run_async(runtime.start())
    assert "parameters" not in captured


def test_runtime_source_never_invokes_npx_or_npm() -> None:
    source = Path("integrations/google_calendar_mcp_runtime.py").read_text(encoding="utf-8").lower()
    assert "npx" not in source
    assert "npm" not in source


def test_missing_local_entrypoint_fails_before_stdio(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _, _, _, captured = make_runtime(files)
    monkeypatch.setattr(
        "integrations.google_calendar_mcp_runtime.shutil.which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    monkeypatch.setattr(
        "integrations.google_calendar_mcp_runtime.SERVER_ENTRYPOINT",
        Path("missing/build/index.js"),
    )
    with pytest.raises(GoogleCalendarMCPUnavailableError):
        run_async(runtime.start())
    assert "parameters" not in captured


def test_client_requires_started_runtime(files: tuple[Path, Path]) -> None:
    runtime, _, _, _, _ = make_runtime(files)
    with pytest.raises(GoogleCalendarMCPUnavailableError):
        _ = runtime.client


def test_repeated_start_does_not_create_another_subprocess(files: tuple[Path, Path]) -> None:
    runtime, _, _, _, captured = make_runtime(files)
    async def scenario() -> bool:
        await runtime.start()
        first_parameters = captured["parameters"]
        await runtime.start()
        return captured["parameters"] is first_parameters

    assert run_async(scenario()) is True


def test_close_releases_resources_and_is_idempotent(files: tuple[Path, Path]) -> None:
    runtime, transport, session_context, _, _ = make_runtime(files)
    async def scenario() -> tuple[bool, bool, bool]:
        await runtime.start()
        await runtime.close()
        await runtime.close()
        with pytest.raises(GoogleCalendarMCPUnavailableError):
            _ = runtime.client
        return transport.closed, session_context.closed, runtime.is_started

    transport_closed, session_closed, started = run_async(scenario())
    assert transport_closed is True
    assert session_closed is True
    assert started is False


def test_cross_task_close_exits_contexts_without_lifecycle_error(
    files: tuple[Path, Path],
) -> None:
    runtime, transport, session_context, _, _ = make_runtime(files)

    async def scenario() -> tuple[bool, bool]:
        await asyncio.create_task(runtime.start())
        await asyncio.create_task(runtime.close())
        return transport.closed, session_context.closed

    assert run_async(scenario()) == (True, True)


def test_partial_startup_failure_cleans_up_and_does_not_leak_secrets(
    files: tuple[Path, Path],
) -> None:
    runtime, transport, session_context, session, _ = make_runtime(files)

    async def fail_initialize() -> None:
        session.initialize_calls += 1
        raise RuntimeError("secret-content token-content")

    session.initialize = fail_initialize  # type: ignore[method-assign]
    with pytest.raises(GoogleCalendarMCPUnavailableError) as exc_info:
        run_async(runtime.start())

    message = str(exc_info.value)
    assert "secret-content" not in message
    assert "token-content" not in message
    assert transport.closed is True
    assert session_context.closed is True
    assert runtime.is_started is False
