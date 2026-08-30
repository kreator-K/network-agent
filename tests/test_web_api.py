"""Authentication and delegation tests for the Vercel-facing web API."""

from __future__ import annotations

from typing import Any

import pytest

from starlette.testclient import TestClient

from api.app import create_app


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_recent_signals(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("signals", kwargs))
        return [{"id": 1, "title": "Stored signal"}]

    def scan_enabled_signal_sources(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("scan", kwargs))
        return {"sources_scanned": 2}

    def clear_signal_workspace(self, **kwargs: Any) -> dict[str, int]:
        self.calls.append(("clear_signal_workspace", kwargs))
        return {"signals": 2, "signal_sources": 1, "content_opportunities": 1, "preference_feedback": 3}

    def list_content_opportunities(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("opportunities", kwargs))
        return [{"id": 3, "status": "candidate"}]

    def generate_content_package(self, opportunity_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("generate", {"opportunity_id": opportunity_id, **kwargs}))
        return {"id": 4, "status": "draft"}

    def get_content_package(self, post_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("content", {"post_id": post_id, **kwargs}))
        return {"id": post_id, "status": "draft"}

    def get_workflow_run(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("workflow", {"run_id": run_id, **kwargs}))
        return {"run_id": run_id, "status": "completed"}

    def list_workflow_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("workflows", kwargs))
        return [{"run_id": "run-123", "status": "completed"}]

    def list_prospects(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("prospects", kwargs))
        return [{"id": 11, "name": "Ada Lovelace", "status": "not_contacted"}]

    def add_prospect(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("add_prospect", kwargs))
        return {"status": "added", "prospect": {"id": 12, "name": kwargs["name"]}}

    def get_followups_due(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("followups", kwargs))
        return [{"prospect_id": 13, "name": "Grace Hopper", "days_since_last_touch": 25}]

    def draft_outreach(self, prospect_id: int, ask_type: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("draft_outreach", {"prospect_id": prospect_id, "ask_type": ask_type, **kwargs}))
        return {"draft": {"draft_text": "Manual-send connection draft"}, "draft_interaction_id": 8}

    def draft_followup(self, prospect_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("draft_followup", {"prospect_id": prospect_id, **kwargs}))
        return {"draft": {"draft_text": "Manual-send follow-up draft"}, "draft_interaction_id": 9}

    def list_pending_content_packages(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("content_packages", kwargs))
        return [{"id": 21, "draft_text": "Frozen candidate", "status": "saved", "package_version": 2}]

    def create_research_content_package(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_content", kwargs))
        return {"post": {"id": 22, "status": "draft", "image_source": "uploaded"}}

    def get_content_image(self, post_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("content_image", {"post_id": post_id, **kwargs}))
        return {"bytes": b"private-png", "content_type": "image/png"}

    def approve_content_package_for_later(self, post_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("approve_content", {"post_id": post_id, **kwargs}))
        return {"post_id": post_id, "status": "approved_for_later_posting"}

    def get_content_publish_readiness(self, post_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("readiness", {"post_id": post_id, **kwargs}))
        return {"exists": True, "ready": True, "blockers": []}

    def get_linkedin_publish_status(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("linkedin_status", kwargs))
        return {"publishing_mode": "disabled", "pending_confirmations": 1}

    def list_linkedin_publish_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("publish_history", kwargs))
        return [{"request_id": 31, "post_id": 21, "status": "awaiting_confirmation"}]

    def prepare_linkedin_publish(self, post_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("prepare_publish", {"post_id": post_id, **kwargs}))
        return {"request_id": 31, "post_id": post_id, "status": "awaiting_confirmation", "commentary": "Exact frozen text"}

    def get_linkedin_publish_request(self, request_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("publish_request", {"request_id": request_id, **kwargs}))
        return {"request_id": request_id, "status": "awaiting_confirmation"}

    def confirm_linkedin_publish(self, request_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("confirm_publish", {"request_id": request_id, **kwargs}))
        return {"request_id": request_id, "status": "disabled", "published": False}

    def cancel_linkedin_publish(self, request_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("cancel_publish", {"request_id": request_id, **kwargs}))
        return {"request_id": request_id, "status": "cancelled"}

    def prepare_linkedin_authorization(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("linkedin_authorization", kwargs))
        return {"authorization_url": "https://www.linkedin.com/oauth/v2/authorization?state=safe", "scopes": ["openid", "profile", "w_member_social"]}

    def complete_linkedin_authorization(self, params: dict[str, str], **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("linkedin_callback", {"params": params, **kwargs}))
        return {"status": "connected", "member_display_name": "Owner"}

    def disconnect_linkedin(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("linkedin_disconnect", kwargs))
        return {"status": "revoked", "message": "Nothing was published."}

    def preview_meeting_confirmation(self, prospect_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("meeting_preview", {"prospect_id": prospect_id, **kwargs}))
        return {"prospect_id": prospect_id, **kwargs, "calendar_action": False, "confirmation_required": True}

    def confirm_meeting(self, prospect_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("meeting_confirmation", {"prospect_id": prospect_id, **kwargs}))
        return {"calendar_synced": True, "calendar_block": {"prospect_id": prospect_id}}

    def revise_content_package(self, post_id: int, revision_type: str, revision_notes: str | None, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("revise_content", {"post_id": post_id, "revision_type": revision_type, "revision_notes": revision_notes, **kwargs}))
        return {"id": post_id, "package_version": 3, "status": "draft"}

    def select_content_variant(self, post_id: int, variant_number: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("select_variant", {"post_id": post_id, "variant_number": variant_number, **kwargs}))
        return {"id": post_id, "package_version": 3, "status": "draft"}

    def get_brand_profile_summary(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("profile", kwargs))
        return {"version": 4, "is_active": True, "professional_identity": "Product leader", "content_pillars": ["AI products"]}

    def list_brand_profile_versions(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("profile_versions", kwargs))
        return [{"version": 4, "is_active": True}, {"version": 3, "is_active": False}]

    def update_brand_profile_field(self, field_name: str, value: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("profile_field", {"field_name": field_name, "value": value, **kwargs}))
        return {"version": 5, "is_active": True, field_name: value}

    def activate_brand_profile(self, version: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("activate_profile", {"version": version, **kwargs}))
        return {"version": version, "is_active": True}

    def record_signal_preference(self, signal_id: int, feedback_type: str, **kwargs: Any) -> None:
        self.calls.append(("signal_feedback", {"signal_id": signal_id, "feedback_type": feedback_type, **kwargs}))

    def record_opportunity_preference(self, opportunity_id: int, feedback_type: str, **kwargs: Any) -> None:
        self.calls.append(("opportunity_feedback", {"opportunity_id": opportunity_id, "feedback_type": feedback_type, **kwargs}))

    def get_briefing_status(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("briefing_status", kwargs))
        return {"enabled": False, "dry_run": True, "last_run": None}

    def list_briefing_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("briefing_runs", kwargs))
        return [{"id": 7, "status": "completed", "run_type": "manual_web"}]

    def build_daily_briefing(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("run_briefing", kwargs))
        return {"run_id": 8, "status": "completed", "dry_run": True}

    def list_signal_sources(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("signal_sources", kwargs))
        return [{"id": 41, "name": "Operator feed", "approval_status": "pending", "enabled": False}]

    def get_signal_source_catalog(self) -> list[dict[str, Any]]:
        self.calls.append(("source_catalog", {}))
        return [{"name": "Catalog feed", "url": "https://example.com/feed", "approval_status": "pending", "enabled": False}]

    def add_signal_source(self, name: str, url: str, source_type: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("add_source", {"name": name, "url": url, "source_type": source_type, **kwargs}))
        return {"id": 42, "name": name, "url": url, "approval_status": "pending", "enabled": False}

    def approve_signal_source(self, source_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("approve_source", {"source_id": source_id, **kwargs}))
        return {"id": source_id, "approval_status": "approved", "enabled": False}

    def reject_signal_source(self, source_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("reject_source", {"source_id": source_id, **kwargs}))
        return {"id": source_id, "approval_status": "rejected", "enabled": False}

    def set_signal_source_enabled(self, source_id: int, enabled: bool, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("enable_source", {"source_id": source_id, "enabled": enabled, **kwargs}))
        return {"id": source_id, "approval_status": "approved", "enabled": enabled}


def _client(
    orchestrator: FakeOrchestrator | None = None,
    *,
    token: str = "owner-secret",
    database: str = "test.db",
) -> TestClient:
    return TestClient(
        create_app(
            orchestrator=orchestrator,  # type: ignore[arg-type]
            database=database,
            api_token=token,
        )
    )


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_health_endpoint_is_public_and_minimal() -> None:
    response = _client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "network-growth-agent",
    }


def test_readiness_endpoint_fails_closed_without_healthy_production_config() -> None:
    response = _client(token="owner-secret").get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["api_auth_configured"] is False


def test_readiness_endpoint_returns_503_for_unreadable_database(tmp_path: Any) -> None:
    database = tmp_path / "missing" / "network-agent.db"
    response = _client(token="a" * 32, database=str(database)).get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["database_integrity"] is False
    assert database.parent.exists() is False


@pytest.mark.skip(reason="Signal ingestion API was removed.")
def test_api_denies_access_when_authentication_is_not_configured() -> None:
    response = _client(token="").get("/api/v1/signals")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_not_configured"


@pytest.mark.skip(reason="Signal ingestion API was removed.")
def test_api_rejects_invalid_bearer_token_without_echoing_it() -> None:
    response = _client().get(
        "/api/v1/signals",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert "wrong-secret" not in response.text


@pytest.mark.skip(reason="Signal ingestion API was removed.")
def test_signal_list_delegates_to_orchestrator_with_bounded_limit() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).get(
        "/api/v1/signals?limit=7",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["title"] == "Stored signal"
    assert orchestrator.calls == [
        ("signals", {"database": "test.db", "limit": 7})
    ]


@pytest.mark.skip(reason="Signal ingestion API was removed.")
def test_signal_scan_accepts_only_typed_graph_mode_request() -> None:
    orchestrator = FakeOrchestrator()
    invalid = _client(orchestrator).post(
        "/api/v1/signals/scan",
        headers=_headers(),
        json={"graph_mode": "enabled", "unexpected": True},
    )
    valid = _client(orchestrator).post(
        "/api/v1/signals/scan",
        headers=_headers(),
        json={"graph_mode": "shadow"},
    )

    assert invalid.status_code == 422
    assert valid.status_code == 202
    assert valid.json()["data"]["sources_scanned"] == 2
    assert orchestrator.calls == [
        ("scan", {"database": "test.db", "graph_mode": "shadow"})
    ]


@pytest.mark.skip(reason="Signal ingestion API was removed.")
def test_signal_workspace_reset_requires_exact_confirmation_and_delegates() -> None:
    orchestrator = FakeOrchestrator()
    invalid = _client(orchestrator).post(
        "/api/v1/signals/reset",
        headers=_headers(),
        json={"confirmation": "clear"},
    )
    valid = _client(orchestrator).post(
        "/api/v1/signals/reset",
        headers=_headers(),
        json={"confirmation": "CLEAR_SIGNAL_WORKSPACE"},
    )

    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert valid.json()["data"]["signals"] == 2
    assert orchestrator.calls == [("clear_signal_workspace", {"database": "test.db"})]


@pytest.mark.skip(reason="Signal-derived opportunities were removed.")
def test_content_generation_remains_a_draft_orchestrator_operation() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).post(
        "/api/v1/opportunities/3/content-package",
        headers=_headers(),
        json={"image_mode": "disabled", "graph_mode": "enabled"},
    )

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "draft"
    assert orchestrator.calls == [
        (
            "generate",
            {
                "opportunity_id": 3,
                "database": "test.db",
                "image_mode": "disabled",
                "graph_mode": "enabled",
            },
        )
    ]


@pytest.mark.skip(reason="Signal ingestion API was removed.")
def test_internal_orchestrator_errors_return_generic_envelope() -> None:
    class FailingOrchestrator(FakeOrchestrator):
        def get_recent_signals(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("database password must not escape")

    response = _client(FailingOrchestrator()).get(
        "/api/v1/signals",
        headers=_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "operation_failed"
    assert "database password" not in response.text
    assert response.json()["error"]["request_id"]


def test_workflow_receipt_route_is_authenticated_and_delegated() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).get(
        "/api/v1/workflows/run-123",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["run_id"] == "run-123"
    assert orchestrator.calls == [
        ("workflow", {"run_id": "run-123", "database": "test.db"})
    ]


def test_workflow_history_route_returns_compact_receipts() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).get(
        "/api/v1/workflows?limit=9",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["run_id"] == "run-123"
    assert orchestrator.calls == [
        ("workflows", {"database": "test.db", "limit": 9})
    ]


def test_prospect_intake_and_listing_delegate_through_orchestrator() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    listed = client.get("/api/v1/prospects?limit=25", headers=_headers())
    created = client.post(
        "/api/v1/prospects",
        headers=_headers(),
        json={"name": "Katherine Johnson", "company": "NASA"},
    )

    assert listed.status_code == 200
    assert listed.json()["data"][0]["name"] == "Ada Lovelace"
    assert created.status_code == 201
    assert created.json()["data"]["status"] == "added"
    assert orchestrator.calls == [
        ("prospects", {"database": "test.db", "limit": 25}),
        (
            "add_prospect",
            {
                "name": "Katherine Johnson",
                "profile_url": None,
                "location": None,
                "role_title": None,
                "company": "NASA",
                "notes": None,
                "database": "test.db",
            },
        ),
    ]


def test_outreach_endpoints_only_create_manual_send_drafts() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    connection = client.post(
        "/api/v1/prospects/11/outreach-draft",
        headers=_headers(),
        json={"ask_type": "career_guidance"},
    )
    followup = client.post(
        "/api/v1/prospects/11/followup-draft",
        headers=_headers(),
    )

    assert connection.status_code == 201
    assert connection.json()["data"]["draft"]["draft_text"] == "Manual-send connection draft"
    assert followup.status_code == 201
    assert followup.json()["data"]["draft"]["draft_text"] == "Manual-send follow-up draft"
    assert orchestrator.calls == [
        (
            "draft_outreach",
            {
                "prospect_id": 11,
                "ask_type": "career_guidance",
                "database": "test.db",
                "source": "web_api",
            },
        ),
        (
            "draft_followup",
            {"prospect_id": 11, "database": "test.db", "source": "web_api"},
        ),
    ]


def test_outreach_rejects_unknown_ask_type_before_delegating() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).post(
        "/api/v1/prospects/11/outreach-draft",
        headers=_headers(),
        json={"ask_type": "send_it_for_me"},
    )

    assert response.status_code == 422
    assert orchestrator.calls == []


def test_followups_due_is_read_only_and_authenticated() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).get(
        "/api/v1/prospects/followups-due",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["prospect_id"] == 13
    assert orchestrator.calls == [("followups", {"database": "test.db"})]


def test_content_approval_and_readiness_remain_separate_from_publish() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    packages = client.get("/api/v1/content", headers=_headers())
    approved = client.post("/api/v1/content/21/approve", headers=_headers())
    readiness = client.get("/api/v1/content/21/publish-readiness", headers=_headers())

    assert packages.status_code == 200
    assert approved.json()["data"]["status"] == "approved_for_later_posting"
    assert readiness.json()["data"]["ready"] is True
    assert orchestrator.calls == [
        ("content_packages", {"database": "test.db"}),
        ("approve_content", {"post_id": 21, "database": "test.db"}),
        ("readiness", {"post_id": 21, "database": "test.db"}),
    ]


def test_content_creation_accepts_a_typed_private_image_payload() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).post(
        "/api/v1/content",
        headers=_headers(),
        json={
            "topic": "Evidence thresholds",
            "research_resource_id": 7,
            "image_base64": "cG5nLWRhdGE=",
            "image_content_type": "image/png",
            "overlay_text": "Evidence before confidence",
            "image_alt_text": "A product decision workshop.",
            "generate_image": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["post"]["status"] == "draft"
    name, call = orchestrator.calls[0]
    assert name == "create_content"
    assert call["image_bytes"] == b"png-data"
    assert call["database"] == "test.db"


def test_content_creation_rejects_unpaired_image_fields() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).post(
        "/api/v1/content",
        headers=_headers(),
        json={"topic": "A topic", "image_base64": "cG5nLWRhdGE="},
    )

    assert response.status_code == 422
    assert orchestrator.calls == []


def test_content_image_is_authenticated_and_streamed_without_storage_details() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).get(
        "/api/v1/content/22/image", headers=_headers()
    )

    assert response.status_code == 200
    assert response.content == b"private-png"
    assert response.headers["content-type"] == "image/png"
    assert orchestrator.calls == [
        ("content_image", {"post_id": 22, "database": "test.db"})
    ]


def test_publish_preview_is_frozen_before_any_confirmation() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    prepared = client.post(
        "/api/v1/linkedin/publish-requests",
        headers=_headers(),
        json={"post_id": 21},
    )

    assert prepared.status_code == 201
    assert prepared.json()["data"]["status"] == "awaiting_confirmation"
    assert prepared.json()["data"]["commentary"] == "Exact frozen text"
    assert orchestrator.calls == [
        ("prepare_publish", {"post_id": 21, "database": "test.db"})
    ]


def test_publish_confirmation_requires_exact_typed_contract() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    missing = client.post(
        "/api/v1/linkedin/publish-requests/31/confirm",
        headers=_headers(),
        json={},
    )
    freeform = client.post(
        "/api/v1/linkedin/publish-requests/31/confirm",
        headers=_headers(),
        json={"confirmation": "yes please"},
    )
    confirmed = client.post(
        "/api/v1/linkedin/publish-requests/31/confirm",
        headers=_headers(),
        json={"confirmation": "CONFIRM_PUBLISH"},
    )

    assert missing.status_code == 422
    assert freeform.status_code == 422
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["published"] is False
    assert orchestrator.calls == [
        ("confirm_publish", {"request_id": 31, "database": "test.db"})
    ]


def test_publish_history_and_cancellation_are_auditable() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    history = client.get("/api/v1/linkedin/publish-requests?limit=12", headers=_headers())
    cancelled = client.post(
        "/api/v1/linkedin/publish-requests/31/cancel",
        headers=_headers(),
        json={"confirmation": "CANCEL_PUBLISH"},
    )

    assert history.json()["data"][0]["request_id"] == 31
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert orchestrator.calls == [
        ("publish_history", {"database": "test.db", "limit": 12}),
        ("cancel_publish", {"request_id": 31, "database": "test.db"}),
    ]


def test_web_owner_can_start_and_complete_state_bound_oauth() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    started = client.post("/api/v1/linkedin/authorization", headers=_headers())
    callback = client.get(
        "/api/v1/linkedin/callback?code=provider-code&state=one-time-state",
        headers=_headers(),
    )

    assert started.status_code == 201
    assert started.json()["data"]["scopes"] == ["openid", "profile", "w_member_social"]
    assert callback.json()["data"]["status"] == "connected"
    assert orchestrator.calls == [
        (
            "linkedin_authorization",
            {
                "telegram_user_id": "web_owner",
                "telegram_chat_id": "web_owner",
                "database": "test.db",
            },
        ),
        (
            "linkedin_callback",
            {
                "params": {"code": "provider-code", "state": "one-time-state"},
                "database": "test.db",
            },
        ),
    ]


def test_linkedin_callback_still_requires_internal_api_authentication() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).get(
        "/api/v1/linkedin/callback?code=provider-code&state=one-time-state"
    )

    assert response.status_code == 401
    assert orchestrator.calls == []


def test_linkedin_disconnect_requires_exact_confirmation_contract() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    invalid = client.post(
        "/api/v1/linkedin/disconnect",
        headers=_headers(),
        json={"confirmation": "sure"},
    )
    valid = client.post(
        "/api/v1/linkedin/disconnect",
        headers=_headers(),
        json={"confirmation": "DISCONNECT_LINKEDIN"},
    )

    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert valid.json()["data"]["status"] == "revoked"
    assert orchestrator.calls == [("linkedin_disconnect", {"database": "test.db"})]


def test_meeting_preview_never_confirms_or_calls_calendar_workflow() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).post(
        "/api/v1/prospects/11/meeting-preview",
        headers=_headers(),
        json={"meeting_date": "2026-09-10", "start_time": "14:30", "timezone": "America/New_York"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["calendar_action"] is False
    assert orchestrator.calls == [
        (
            "meeting_preview",
            {
                "prospect_id": 11,
                "meeting_date": "2026-09-10",
                "start_time": "14:30",
                "end_time": None,
                "timezone": "America/New_York",
                "notes": None,
            },
        )
    ]


def test_meeting_confirmation_rejects_freeform_consent() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)
    payload = {"meeting_date": "2026-09-10", "start_time": "14:30"}

    missing = client.post(
        "/api/v1/prospects/11/meeting-confirmation",
        headers=_headers(),
        json=payload,
    )
    freeform = client.post(
        "/api/v1/prospects/11/meeting-confirmation",
        headers=_headers(),
        json={**payload, "confirmation": "sounds good"},
    )

    assert missing.status_code == 422
    assert freeform.status_code == 422
    assert orchestrator.calls == []


def test_meeting_confirmation_runs_only_with_exact_confirmation() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).post(
        "/api/v1/prospects/11/meeting-confirmation",
        headers=_headers(),
        json={
            "meeting_date": "2026-09-10",
            "start_time": "14:30",
            "end_time": "15:00",
            "timezone": "America/New_York",
            "notes": "Confirmed by email",
            "confirmation": "MEETING_CONFIRMED",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["calendar_synced"] is True
    assert orchestrator.calls == [
        (
            "meeting_confirmation",
            {
                "prospect_id": 11,
                "meeting_date": "2026-09-10",
                "start_time": "14:30",
                "end_time": "15:00",
                "timezone": "America/New_York",
                "notes": "Confirmed by email",
                "database": "test.db",
            },
        )
    ]


def test_content_revision_and_variant_selection_are_typed_review_actions() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    revised = client.post(
        "/api/v1/content/21/revise",
        headers=_headers(),
        json={"revision_type": "make_more_concise", "revision_notes": "Keep the source caveat."},
    )
    selected = client.post(
        "/api/v1/content/21/select-variant",
        headers=_headers(),
        json={"variant_number": 2},
    )

    assert revised.status_code == 200
    assert selected.status_code == 200
    assert orchestrator.calls == [
        (
            "revise_content",
            {
                "post_id": 21,
                "revision_type": "make_more_concise",
                "revision_notes": "Keep the source caveat.",
                "database": "test.db",
            },
        ),
        ("select_variant", {"post_id": 21, "variant_number": 2, "database": "test.db"}),
    ]


def test_content_revision_rejects_unknown_operations_before_orchestration() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).post(
        "/api/v1/content/21/revise",
        headers=_headers(),
        json={"revision_type": "invent_sources"},
    )

    assert response.status_code == 422
    assert orchestrator.calls == []


def test_profile_reads_and_field_edits_use_versioned_orchestrator_boundary() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    profile = client.get("/api/v1/profile", headers=_headers())
    versions = client.get("/api/v1/profile/versions?limit=8", headers=_headers())
    edited = client.patch(
        "/api/v1/profile/field",
        headers=_headers(),
        json={"field_name": "content_pillars", "value": "AI products, product strategy"},
    )
    activated = client.post("/api/v1/profile/versions/3/activate", headers=_headers())

    assert profile.json()["data"]["version"] == 4
    assert len(versions.json()["data"]) == 2
    assert edited.json()["data"]["version"] == 5
    assert activated.json()["data"]["version"] == 3
    assert orchestrator.calls == [
        ("profile", {"database": "test.db"}),
        ("profile_versions", {"database": "test.db", "limit": 8}),
        (
            "profile_field",
            {
                "field_name": "content_pillars",
                "value": "AI products, product strategy",
                "database": "test.db",
            },
        ),
        ("activate_profile", {"version": 3, "database": "test.db"}),
    ]


def test_profile_field_contract_rejects_core_intent_or_unknown_fields() -> None:
    orchestrator = FakeOrchestrator()
    response = _client(orchestrator).patch(
        "/api/v1/profile/field",
        headers=_headers(),
        json={"field_name": "core_intent", "value": "rewrite it"},
    )

    assert response.status_code == 422
    assert orchestrator.calls == []


@pytest.mark.skip(reason="Signal-derived feedback API was removed.")
def test_feedback_is_stored_without_triggering_generation_or_profile_mutation() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)
    signal = client.post(
        "/api/v1/signals/4/feedback",
        headers=_headers(),
        json={"feedback_type": "more_like_this", "note": "Useful evidence"},
    )
    opportunity = client.post(
        "/api/v1/opportunities/5/feedback",
        headers=_headers(),
        json={"feedback_type": "too_generic"},
    )

    assert signal.status_code == 201
    assert opportunity.status_code == 201
    assert orchestrator.calls == [
        ("signal_feedback", {"signal_id": 4, "feedback_type": "more_like_this", "database": "test.db", "note": "Useful evidence", "source": "web_api"}),
        ("opportunity_feedback", {"opportunity_id": 5, "feedback_type": "too_generic", "database": "test.db", "note": None, "source": "web_api"}),
    ]


def test_manual_web_briefing_is_forced_to_dry_run() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)
    status = client.get("/api/v1/briefings/status", headers=_headers())
    runs = client.get("/api/v1/briefings/runs?limit=6", headers=_headers())
    run = client.post("/api/v1/briefings/run-dry", headers=_headers())

    assert status.status_code == 200
    assert runs.status_code == 200
    assert run.status_code == 202
    assert run.json()["data"]["dry_run"] is True
    assert orchestrator.calls == [
        ("briefing_status", {"database": "test.db"}),
        ("briefing_runs", {"database": "test.db", "limit": 6}),
        ("run_briefing", {"database": "test.db", "run_type": "manual_web", "dry_run": True}),
    ]


@pytest.mark.skip(reason="RSS/Atom source catalog API was removed.")
def test_source_catalog_add_approval_and_enable_are_separate_actions() -> None:
    orchestrator = FakeOrchestrator()
    client = _client(orchestrator)

    catalog = client.get("/api/v1/signal-sources/catalog", headers=_headers())
    added = client.post(
        "/api/v1/signal-sources",
        headers=_headers(),
        json={"name": "Catalog feed", "url": "https://example.com/feed", "source_type": "rss"},
    )
    approved = client.post("/api/v1/signal-sources/42/approve", headers=_headers())
    enabled = client.post(
        "/api/v1/signal-sources/42/enabled",
        headers=_headers(),
        json={"enabled": True},
    )

    assert catalog.json()["data"][0]["enabled"] is False
    assert added.json()["data"]["approval_status"] == "pending"
    assert approved.json()["data"]["enabled"] is False
    assert enabled.json()["data"]["enabled"] is True
    assert orchestrator.calls == [
        ("source_catalog", {}),
        ("add_source", {"name": "Catalog feed", "url": "https://example.com/feed", "source_type": "rss", "database": "test.db"}),
        ("approve_source", {"source_id": 42, "database": "test.db"}),
        ("enable_source", {"source_id": 42, "enabled": True, "database": "test.db"}),
    ]
