"""Persistent stdio runtime for the Google Calendar MCP server."""

from __future__ import annotations

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
        self._stack: AsyncExitStack | None = None
        self._session: Any | None = None
        self._client: GoogleCalendarMCPClient | None = None

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
            tool_names = {
                tool.name for tool in getattr(tool_result, "tools", [])
            }
            if REQUIRED_TOOL not in tool_names:
                raise GoogleCalendarMCPUnavailableError(
                    "Google Calendar MCP server does not expose create-event."
                )
            self._stack = stack
            self._session = session
            self._client = GoogleCalendarMCPClient(session)
        except GoogleCalendarMCPUnavailableError:
            await stack.aclose()
            raise
        except Exception as exc:
            await stack.aclose()
            raise GoogleCalendarMCPUnavailableError(
                "Google Calendar MCP runtime could not be started."
            ) from exc

    async def close(self) -> None:
        """Close the MCP session and stdio subprocess, if started."""
        stack, self._stack = self._stack, None
        self._session = None
        self._client = None
        if stack is not None:
            await stack.aclose()

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
        return self._client is not None

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
