"""Persistent stdio runtime for the Google Calendar MCP server."""

from __future__ import annotations

import asyncio
import os
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config.settings import settings
from integrations.google_calendar_mcp_client import (
    GoogleCalendarMCPClient,
    GoogleCalendarMCPUnavailableError,
)


SERVER_ENTRYPOINT = Path("vendor/google-calendar-mcp/node_modules/@cocal/google-calendar-mcp/build/index.js")
ENABLED_TOOLS = "create-event,get-current-time"
REQUIRED_TOOL = "create-event"


class GoogleCalendarMCPRuntime:
    """Own one initialized Google Calendar MCP stdio session."""

    def __init__(
        self,
        *,
        credentials_path: str | Path | None = None,
        token_path: str | Path | None = None,
        repository_root: Path | None = None,
        stdio_client_factory: Callable[..., Any] = stdio_client,
        session_factory: Callable[..., Any] = ClientSession,
    ) -> None:
        self._repository_root = repository_root or Path(__file__).resolve().parent.parent
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._stdio_client_factory = stdio_client_factory
        self._session_factory = session_factory
        self._session: Any | None = None
        self._client: GoogleCalendarMCPClient | None = None
        self._owner_task: asyncio.Task[None] | None = None
        self._ready: asyncio.Event | None = None
        self._shutdown: asyncio.Event | None = None
        self._startup_error: BaseException | None = None

    async def start(self) -> None:
        """Validate configuration and initialize the reusable MCP session."""
        if self.is_started:
            return

        credentials = self._resolve_path(
            self._credentials_path
            if self._credentials_path is not None
            else settings.google_calendar_credentials_path,
            "GOOGLE_CALENDAR_CREDENTIALS_PATH",
        )
        token = self._resolve_path(
            self._token_path
            if self._token_path is not None
            else settings.google_calendar_mcp_token_path,
            "GOOGLE_CALENDAR_MCP_TOKEN_PATH",
        )
        self._validate_file(credentials, "Google Calendar credentials file")
        self._validate_file(token, "Google Calendar token file")
        node_command = shutil.which("node")
        if node_command is None:
            raise GoogleCalendarMCPUnavailableError(
                "Google Calendar MCP runtime requires Node.js, but node is unavailable."
            )
        entrypoint = (self._repository_root / SERVER_ENTRYPOINT).resolve()
        if not entrypoint.is_file():
            raise GoogleCalendarMCPUnavailableError(
                "Project-local Google Calendar MCP entry point is missing."
            )

        child_environment = os.environ.copy()
        child_environment.update(
            {
                "GOOGLE_OAUTH_CREDENTIALS": str(credentials),
                "GOOGLE_CALENDAR_MCP_TOKEN_PATH": str(token),
                "ENABLED_TOOLS": ENABLED_TOOLS,
            }
        )
        parameters = StdioServerParameters(
            command=str(Path(node_command).resolve()),
            args=[str(entrypoint)],
            env=child_environment,
            cwd=self._repository_root,
        )
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._startup_error = None
        self._owner_task = asyncio.create_task(
            self._own_lifecycle(parameters),
            name="google-calendar-mcp-lifecycle-owner",
        )
        await self._ready.wait()
        if self._startup_error is not None:
            error = self._startup_error
            self._owner_task = None
            self._ready = None
            self._shutdown = None
            raise error

    async def close(self) -> None:
        """Close the MCP session and stdio subprocess, if started."""
        owner = self._owner_task
        if owner is None:
            self._client = None
            self._session = None
            return
        if self._shutdown is not None:
            self._shutdown.set()
        try:
            await asyncio.wait_for(asyncio.shield(owner), timeout=10)
        except asyncio.TimeoutError:
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        finally:
            self._owner_task = None
            self._ready = None
            self._shutdown = None
            self._session = None
            self._client = None

    async def _own_lifecycle(self, parameters: StdioServerParameters) -> None:
        """Enter, use, and exit all MCP contexts in one owning task."""
        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                self._stdio_client_factory(parameters)
            )
            session = await stack.enter_async_context(
                self._session_factory(read_stream, write_stream)
            )
            await session.initialize()
            tool_result = await session.list_tools()
            tool_names = {tool.name for tool in getattr(tool_result, "tools", [])}
            if REQUIRED_TOOL not in tool_names:
                raise GoogleCalendarMCPUnavailableError(
                    "Google Calendar MCP server does not expose create-event."
                )
            self._session = session
            self._client = GoogleCalendarMCPClient(session)
            if self._ready is not None:
                self._ready.set()
            if self._shutdown is not None:
                await self._shutdown.wait()
        except GoogleCalendarMCPUnavailableError as exc:
            self._startup_error = exc
            if self._ready is not None:
                self._ready.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._startup_error = GoogleCalendarMCPUnavailableError(
                "Google Calendar MCP runtime could not be started."
            )
            self._startup_error.__cause__ = exc
            if self._ready is not None:
                self._ready.set()
        finally:
            self._session = None
            self._client = None
            try:
                await stack.aclose()
            except Exception as cleanup_error:
                if self._startup_error is None:
                    self._startup_error = GoogleCalendarMCPUnavailableError(
                        "Google Calendar MCP runtime cleanup failed."
                    )
                    self._startup_error.__cause__ = cleanup_error
                if self._ready is not None and not self._ready.is_set():
                    self._ready.set()

    @property
    def client(self) -> GoogleCalendarMCPClient:
        """Return the initialized typed client, never the raw session."""
        if self._client is None:
            raise GoogleCalendarMCPUnavailableError(
                "Google Calendar MCP runtime is not started."
            )
        return self._client

    @property
    def is_started(self) -> bool:
        return self._client is not None and self._owner_task is not None

    def _resolve_path(self, raw_path: str | Path, setting_name: str) -> Path:
        value = str(raw_path).strip()
        if not value:
            raise GoogleCalendarMCPUnavailableError(
                f"{setting_name} must be configured for Google Calendar MCP."
            )
        path = Path(value)
        return path if path.is_absolute() else self._repository_root / path

    @staticmethod
    def _validate_file(path: Path, label: str) -> None:
        if not path.is_file():
            raise GoogleCalendarMCPUnavailableError(
                f"{label} is missing or is not a regular file."
            )
