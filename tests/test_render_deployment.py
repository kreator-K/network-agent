"""Render deployment contract tests."""

from pathlib import Path

import pytest

from scripts import run_api
from scripts.run_api import api_port


ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_uses_one_free_instance_and_ephemeral_demo_paths() -> None:
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "runtime: docker" in blueprint
    assert "plan: free" in blueprint
    assert "numInstances: 1" in blueprint
    assert "disk:" not in blueprint
    assert "mountPath:" not in blueprint
    assert "maxShutdownDelaySeconds" not in blueprint
    assert "DATABASE_PATH" in blueprint
    assert "value: /tmp/network-agent/network_agent.db" in blueprint
    assert "value: demo" in blueprint
    assert 'value: "false"' in blueprint
    assert "healthCheckPath: /readyz" in blueprint


def test_render_blueprint_starts_with_external_writes_disabled() -> None:
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "LINKEDIN_PUBLISH_MODE" in blueprint
    assert "LINKEDIN_REAL_PUBLISH_ENABLED" in blueprint
    assert "PUBLIC_SIGNAL_ALLOW_HTTP" in blueprint
    assert "generateValue: true" in blueprint
    assert "LINKEDIN_CLIENT_SECRET" not in blueprint
    assert "LINKEDIN_REDIRECT_URI" not in blueprint


def test_render_container_runner_supports_direct_script_execution() -> None:
    runner = (ROOT / "scripts" / "run_api.py").read_text(encoding="utf-8")

    path_setup = runner.index("sys.path.insert")
    project_import = runner.index("from config.settings import settings")
    assert path_setup < project_import


@pytest.mark.parametrize(("raw", "expected"), [(None, 8000), ("10000", 10000), ("65535", 65535)])
def test_api_port_accepts_local_and_provider_ports(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int) -> None:
    monkeypatch.delenv("PORT", raising=False)
    assert api_port(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "0", "65536"])
def test_api_port_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match="PORT must be"):
        api_port(raw)


def test_api_startup_prepares_runtime_and_initializes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def prepare_runtime() -> int:
        calls.append("runtime")
        return 0

    monkeypatch.setattr(run_api, "prepare_runtime", prepare_runtime)
    monkeypatch.setattr(
        run_api,
        "initialize_database",
        lambda path: calls.append(f"database:{path}"),
    )

    run_api.prepare_api_runtime("/tmp/network-agent/test.db")

    assert calls == ["runtime", "database:/tmp/network-agent/test.db"]


def test_api_startup_stops_when_runtime_preparation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_api, "prepare_runtime", lambda: 1)
    monkeypatch.setattr(
        run_api,
        "initialize_database",
        lambda _path: pytest.fail("database initialization must not run"),
    )

    with pytest.raises(RuntimeError, match="Runtime directory preparation failed"):
        run_api.prepare_api_runtime("/tmp/network-agent/test.db")
