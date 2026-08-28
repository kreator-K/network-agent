"""Provider-neutral API deployment artifact checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_pins_required_python_runtime_and_asgi_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "python:3.11-slim" in dockerfile
    assert '"api.index:app"' in dockerfile
    assert "--host" in dockerfile


def test_compose_uses_named_durable_volumes_and_readiness_probe() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "network_agent_data:/data" in compose
    assert "DATABASE_PATH: /data/network_agent.db" in compose
    assert "http://127.0.0.1:8000/readyz" in compose
    assert "LINKEDIN_PUBLISH_MODE: disabled" in compose


def test_dockerignore_excludes_runtime_secrets_and_database_copies() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env*" in dockerignore
    assert "secrets/" in dockerignore
    assert "*.db" in dockerignore
