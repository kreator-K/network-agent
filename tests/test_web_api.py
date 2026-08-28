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
