"""Thin Starlette API that delegates product work to NetworkOrchestrator."""

from __future__ import annotations

import hmac
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agents.orchestrator import NetworkOrchestrator
from config.diagnostics import configuration_diagnostics
from config.settings import settings


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalScanRequest(ApiModel):
    graph_mode: str | None = None


class ContentPackageRequest(ApiModel):
    image_mode: str = "disabled"
    graph_mode: str | None = None


def create_app(
    *,
    orchestrator: NetworkOrchestrator | None = None,
    database: str | None = None,
    api_token: str | None = None,
) -> Starlette:
    """Create an injectable ASGI application for Vercel and tests."""
    application = Starlette(
        debug=False,
        routes=[
            Route("/healthz", _health, methods=["GET"]),
            Route("/api/v1/diagnostics", _diagnostics, methods=["GET"]),
            Route("/api/v1/workflows/{run_id:str}", _workflow_run, methods=["GET"]),
            Route("/api/v1/workflows", _workflow_runs, methods=["GET"]),
            Route("/api/v1/signals", _signals, methods=["GET"]),
            Route("/api/v1/signals/scan", _scan_signals, methods=["POST"]),
            Route("/api/v1/opportunities", _opportunities, methods=["GET"]),
            Route(
                "/api/v1/opportunities/{opportunity_id:int}/content-package",
                _generate_content_package,
                methods=["POST"],
            ),
            Route("/api/v1/content/{post_id:int}", _content_package, methods=["GET"]),
        ],
    )
    application.state.orchestrator = orchestrator or NetworkOrchestrator()
    application.state.database = database or settings.database_path
    application.state.api_token = settings.web_api_token if api_token is None else api_token
    return application


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "network-growth-agent"})


async def _diagnostics(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _ok(configuration_diagnostics())


async def _signals(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    limit = _bounded_limit(request, default=20)
    if isinstance(limit, JSONResponse):
        return limit
    return _delegate(
        request,
        lambda: _orchestrator(request).get_recent_signals(
            database=_database(request),
            limit=limit,
        ),
    )


async def _workflow_run(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    run_id = str(request.path_params["run_id"])
    return _delegate(
        request,
        lambda: _orchestrator(request).get_workflow_run(
            run_id,
            database=_database(request),
        ),
    )


async def _workflow_runs(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    limit = _bounded_limit(request, default=20)
    if isinstance(limit, JSONResponse):
        return limit
    return _delegate(
        request,
        lambda: _orchestrator(request).list_workflow_runs(
            database=_database(request),
            limit=limit,
        ),
    )


async def _scan_signals(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, SignalScanRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    signal_request = cast(SignalScanRequest, parsed)
    return _delegate(
        request,
        lambda: _orchestrator(request).scan_enabled_signal_sources(
            database=_database(request),
            graph_mode=signal_request.graph_mode,
        ),
        status_code=202,
    )


async def _opportunities(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    limit = _bounded_limit(request, default=20)
    if isinstance(limit, JSONResponse):
        return limit
    status = request.query_params.get("status") or None
    return _delegate(
        request,
        lambda: _orchestrator(request).list_content_opportunities(
            database=_database(request),
            status=status,
            limit=limit,
        ),
    )


async def _generate_content_package(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, ContentPackageRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    content_request = cast(ContentPackageRequest, parsed)
    opportunity_id = int(request.path_params["opportunity_id"])
    return _delegate(
        request,
        lambda: _orchestrator(request).generate_content_package(
            opportunity_id,
            database=_database(request),
            image_mode=content_request.image_mode,
            graph_mode=content_request.graph_mode,
        ),
        status_code=201,
    )


async def _content_package(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    post_id = int(request.path_params["post_id"])
    return _delegate(
        request,
        lambda: _orchestrator(request).get_content_package(
            post_id,
            database=_database(request),
        ),
    )


def _authorize(request: Request) -> JSONResponse | None:
    expected = str(request.app.state.api_token or "")
    request_id = _request_id(request)
    if not expected:
        return _error(
            "authentication_not_configured",
            "Web API authentication is not configured.",
            request_id,
            503,
        )
    authorization = request.headers.get("authorization", "")
    supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        return _error("unauthorized", "Authentication is required.", request_id, 401)
    return None


async def _parse_body(
    request: Request,
    schema: type[ApiModel],
) -> ApiModel | JSONResponse:
    try:
        body = await request.json()
        return schema.model_validate(body)
    except (ValueError, ValidationError):
        return _error(
            "invalid_request",
            "Request body did not satisfy the API contract.",
            _request_id(request),
            422,
        )


def _bounded_limit(request: Request, *, default: int) -> int | JSONResponse:
    try:
        limit = int(request.query_params.get("limit", str(default)))
    except ValueError:
        limit = 0
    if not 1 <= limit <= 100:
        return _error(
            "invalid_limit",
            "Limit must be between 1 and 100.",
            _request_id(request),
            422,
        )
    return limit


def _delegate(
    request: Request,
    operation: Any,
    *,
    status_code: int = 200,
) -> JSONResponse:
    try:
        return _ok(operation(), status_code=status_code)
    except Exception:
        return _error(
            "operation_failed",
            "The requested operation could not be completed.",
            _request_id(request),
            400,
        )


def _ok(data: Any, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"data": data}, status_code=status_code)


def _error(
    code: str,
    message: str,
    request_id: str,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": request_id}},
        status_code=status_code,
    )


def _request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if existing:
        return str(existing)
    request.state.request_id = str(uuid4())
    return str(request.state.request_id)


def _orchestrator(request: Request) -> NetworkOrchestrator:
    return request.app.state.orchestrator


def _database(request: Request) -> str:
    return str(request.app.state.database)


app = create_app()
