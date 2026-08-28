"""CI workflow safety and runtime contract checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_pins_python_and_frontend_node_runtimes() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'python-version: "3.11"' in workflow
    assert 'node-version: "22"' in workflow
    assert "python -m pytest" in workflow
    assert "npm run build" in workflow


def test_ci_keeps_provider_writes_disabled_and_uses_read_only_permissions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "LINKEDIN_PUBLISH_MODE: disabled" in workflow
    assert 'LINKEDIN_REAL_PUBLISH_ENABLED: "false"' in workflow
    assert "OPENAI_API_KEY" not in workflow
