"""Render deployment contract tests."""

from pathlib import Path

import pytest

from scripts.run_api import api_port


ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_uses_one_instance_and_one_persistent_disk() -> None:
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "runtime: docker" in blueprint
    assert "numInstances: 1" in blueprint
    assert "mountPath: /data" in blueprint
    assert "maxShutdownDelaySeconds" not in blueprint
    assert "DATABASE_PATH" in blueprint
    assert "value: /data/network_agent.db" in blueprint
    assert "healthCheckPath: /readyz" in blueprint


def test_render_blueprint_starts_with_external_writes_disabled() -> None:
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "LINKEDIN_PUBLISH_MODE" in blueprint
    assert "LINKEDIN_REAL_PUBLISH_ENABLED" in blueprint
    assert "PUBLIC_SIGNAL_ALLOW_HTTP" in blueprint
    assert "generateValue: true" in blueprint
    assert "LINKEDIN_CLIENT_SECRET\n        sync: false" in blueprint


@pytest.mark.parametrize(("raw", "expected"), [(None, 8000), ("10000", 10000), ("65535", 65535)])
def test_api_port_accepts_local_and_provider_ports(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int) -> None:
    monkeypatch.delenv("PORT", raising=False)
    assert api_port(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "0", "65536"])
def test_api_port_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match="PORT must be"):
        api_port(raw)
