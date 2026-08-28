"""Thin Starlette API that delegates product work to NetworkOrchestrator."""

from __future__ import annotations

import hmac
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import to_jsonable_python
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


class ProspectCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    profile_url: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=200)
    role_title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)


class OutreachDraftRequest(ApiModel):
    ask_type: Literal["resume_review", "career_guidance", "general_chat"]


class PublishPrepareRequest(ApiModel):
    post_id: int = Field(gt=0)


class PublishConfirmationRequest(ApiModel):
    confirmation: Literal["CONFIRM_PUBLISH"]


class PublishCancellationRequest(ApiModel):
    confirmation: Literal["CANCEL_PUBLISH"]


class LinkedInDisconnectRequest(ApiModel):
    confirmation: Literal["DISCONNECT_LINKEDIN"]


class MeetingPreviewRequest(ApiModel):
    meeting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class MeetingConfirmationRequest(MeetingPreviewRequest):
    confirmation: Literal["MEETING_CONFIRMED"]


class ContentRevisionRequest(ApiModel):
    revision_type: Literal[
        "make_more_personal",
        "make_more_analytical",
        "make_more_concise",
        "make_more_practical",
        "make_lighter",
        "make_funnier",
        "reduce_hype",
        "change_target_audience",
        "regenerate_hook",
        "custom_revision",
    ]
    revision_notes: str | None = Field(default=None, max_length=2000)


class ContentVariantRequest(ApiModel):
    variant_number: int = Field(ge=1, le=3)


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
            Route("/api/v1/content", _content_packages, methods=["GET"]),
            Route("/api/v1/content/{post_id:int}", _content_package, methods=["GET"]),
            Route("/api/v1/content/{post_id:int}/approve", _approve_content_package, methods=["POST"]),
            Route("/api/v1/content/{post_id:int}/publish-readiness", _content_publish_readiness, methods=["GET"]),
            Route("/api/v1/content/{post_id:int}/revise", _revise_content_package, methods=["POST"]),
            Route("/api/v1/content/{post_id:int}/select-variant", _select_content_variant, methods=["POST"]),
            Route("/api/v1/prospects", _prospects, methods=["GET", "POST"]),
            Route("/api/v1/prospects/followups-due", _followups_due, methods=["GET"]),
            Route("/api/v1/prospects/{prospect_id:int}/outreach-draft", _outreach_draft, methods=["POST"]),
            Route("/api/v1/prospects/{prospect_id:int}/followup-draft", _followup_draft, methods=["POST"]),
            Route("/api/v1/prospects/{prospect_id:int}/meeting-preview", _meeting_preview, methods=["POST"]),
            Route("/api/v1/prospects/{prospect_id:int}/meeting-confirmation", _meeting_confirmation, methods=["POST"]),
            Route("/api/v1/linkedin/status", _linkedin_status, methods=["GET"]),
            Route("/api/v1/linkedin/authorization", _linkedin_authorization, methods=["POST"]),
            Route("/api/v1/linkedin/callback", _linkedin_callback, methods=["GET"]),
            Route("/api/v1/linkedin/disconnect", _linkedin_disconnect, methods=["POST"]),
            Route("/api/v1/linkedin/publish-requests", _linkedin_publish_requests, methods=["GET", "POST"]),
            Route("/api/v1/linkedin/publish-requests/{request_id:int}", _linkedin_publish_request, methods=["GET"]),
            Route("/api/v1/linkedin/publish-requests/{request_id:int}/confirm", _confirm_linkedin_publish, methods=["POST"]),
            Route("/api/v1/linkedin/publish-requests/{request_id:int}/cancel", _cancel_linkedin_publish, methods=["POST"]),
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


async def _content_packages(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).list_pending_content_packages(
            database=_database(request),
        ),
    )


async def _approve_content_package(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).approve_content_package_for_later(
            int(request.path_params["post_id"]),
            database=_database(request),
        ),
    )


async def _content_publish_readiness(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).get_content_publish_readiness(
            int(request.path_params["post_id"]),
            database=_database(request),
        ),
    )


async def _revise_content_package(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, ContentRevisionRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    revision = cast(ContentRevisionRequest, parsed)
    return _delegate(
        request,
        lambda: _orchestrator(request).revise_content_package(
            int(request.path_params["post_id"]),
            revision.revision_type,
            revision.revision_notes,
            database=_database(request),
        ),
    )


async def _select_content_variant(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, ContentVariantRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    variant = cast(ContentVariantRequest, parsed)
    return _delegate(
        request,
        lambda: _orchestrator(request).select_content_variant(
            int(request.path_params["post_id"]),
            variant.variant_number,
            database=_database(request),
        ),
    )


async def _prospects(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    if request.method == "GET":
        limit = _bounded_limit(request, default=50)
        if isinstance(limit, JSONResponse):
            return limit
        return _delegate(
            request,
            lambda: _orchestrator(request).list_prospects(
                database=_database(request),
                limit=limit,
            ),
        )
    parsed = await _parse_body(request, ProspectCreateRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    prospect = cast(ProspectCreateRequest, parsed)
    return _delegate(
        request,
        lambda: _orchestrator(request).add_prospect(
            **prospect.model_dump(),
            database=_database(request),
        ),
        status_code=201,
    )


async def _followups_due(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).get_followups_due(database=_database(request)),
    )


async def _outreach_draft(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, OutreachDraftRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    draft = cast(OutreachDraftRequest, parsed)
    return _delegate(
        request,
        lambda: _orchestrator(request).draft_outreach(
            int(request.path_params["prospect_id"]),
            draft.ask_type,
            database=_database(request),
            source="web_api",
        ),
        status_code=201,
    )


async def _followup_draft(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).draft_followup(
            int(request.path_params["prospect_id"]),
            database=_database(request),
            source="web_api",
        ),
        status_code=201,
    )


async def _meeting_preview(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, MeetingPreviewRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    preview = cast(MeetingPreviewRequest, parsed)
    return _delegate(
        request,
        lambda: _orchestrator(request).preview_meeting_confirmation(
            int(request.path_params["prospect_id"]),
            **preview.model_dump(),
        ),
    )


async def _meeting_confirmation(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, MeetingConfirmationRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    confirmation = cast(MeetingConfirmationRequest, parsed)
    payload = confirmation.model_dump(exclude={"confirmation"})
    return _delegate(
        request,
        lambda: _orchestrator(request).confirm_meeting(
            int(request.path_params["prospect_id"]),
            **payload,
            database=_database(request),
        ),
    )


async def _linkedin_status(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).get_linkedin_publish_status(
            database=_database(request),
        ),
    )


async def _linkedin_authorization(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).prepare_linkedin_authorization(
            telegram_user_id="web_owner",
            telegram_chat_id="web_owner",
            database=_database(request),
        ),
        status_code=201,
    )


async def _linkedin_callback(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).complete_linkedin_authorization(
            dict(request.query_params),
            database=_database(request),
        ),
    )


async def _linkedin_disconnect(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, LinkedInDisconnectRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    return _delegate(
        request,
        lambda: _orchestrator(request).disconnect_linkedin(
            database=_database(request),
        ),
    )


async def _linkedin_publish_requests(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    if request.method == "GET":
        limit = _bounded_limit(request, default=30)
        if isinstance(limit, JSONResponse):
            return limit
        return _delegate(
            request,
            lambda: _orchestrator(request).list_linkedin_publish_history(
                database=_database(request),
                limit=limit,
            ),
        )
    parsed = await _parse_body(request, PublishPrepareRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    publish_request = cast(PublishPrepareRequest, parsed)
    return _delegate(
        request,
        lambda: _orchestrator(request).prepare_linkedin_publish(
            publish_request.post_id,
            database=_database(request),
        ),
        status_code=201,
    )


async def _linkedin_publish_request(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    return _delegate(
        request,
        lambda: _orchestrator(request).get_linkedin_publish_request(
            int(request.path_params["request_id"]),
            database=_database(request),
        ),
    )


async def _confirm_linkedin_publish(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, PublishConfirmationRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    return _delegate(
        request,
        lambda: _orchestrator(request).confirm_linkedin_publish(
            int(request.path_params["request_id"]),
            database=_database(request),
        ),
    )


async def _cancel_linkedin_publish(request: Request) -> JSONResponse:
    denied = _authorize(request)
    if denied:
        return denied
    parsed = await _parse_body(request, PublishCancellationRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    return _delegate(
        request,
        lambda: _orchestrator(request).cancel_linkedin_publish(
            int(request.path_params["request_id"]),
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
    return JSONResponse({"data": to_jsonable_python(data)}, status_code=status_code)


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
