"""Authentication and delegation tests for the Vercel-facing web API."""

from __future__ import annotations

from typing import Any

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


def _client(
    orchestrator: FakeOrchestrator | None = None,
    *,
    token: str = "owner-secret",
) -> TestClient:
    return TestClient(
        create_app(
            orchestrator=orchestrator,  # type: ignore[arg-type]
            database="test.db",
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


def test_api_denies_access_when_authentication_is_not_configured() -> None:
    response = _client(token="").get("/api/v1/signals")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_not_configured"


def test_api_rejects_invalid_bearer_token_without_echoing_it() -> None:
    response = _client().get(
        "/api/v1/signals",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert "wrong-secret" not in response.text


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
