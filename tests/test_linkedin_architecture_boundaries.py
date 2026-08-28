"""Architectural and secret-boundary regression tests for LinkedIn publishing."""

import ast
from pathlib import Path

from config.settings import settings


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_only_linkedin_api_client_contains_linkedin_write_endpoints() -> None:
    allowed = ROOT / "integrations" / "linkedin_api_client.py"
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        if path == allowed or "tests" in path.parts or ".venv" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if any(endpoint in source for endpoint in ("/rest/posts", "/rest/images", "/rest/videos", "/rest/documents")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_handlers_and_automated_workflows_cannot_import_provider_client() -> None:
    prohibited = [
        "telegram_bot/handlers.py",
        "agents/model_orchestration_agent.py",
        "agents/content_inspiration_agent.py",
        "agents/prospect_discovery_agent.py",
        "agents/outreach_draft_agent.py",
        "agents/calendar_agent.py",
        "agents/refinement_loop_agent.py",
    ]
    for relative in prohibited:
        tree = ast.parse(_source(relative))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "LinkedInApiClient" not in imports
        assert "integrations.linkedin_api_client" not in imports


def test_runtime_settings_load_only_env_local() -> None:
    source = _source("config/settings.py")
    assert 'load_dotenv(".env.local", override=_DOTENV_OVERRIDE)' in source
    assert ".env.example" not in source
    assert "load_dotenv()" not in source


def test_safe_tracked_surfaces_do_not_contain_runtime_secret_values() -> None:
    sensitive_values = [
        settings.linkedin_client_secret,
        settings.linkedin_token_encryption_key,
    ]
    surfaces = [
        path
        for folder in ("agents", "config", "db", "integrations", "telegram_bot", "docs")
        for path in (ROOT / folder).rglob("*")
        if path.is_file() and path.suffix in {".py", ".md", ".json", ".example"}
    ]
    contents = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in surfaces)
    for value in sensitive_values:
        if len(value) >= 16 and value in contents:
            raise AssertionError("A runtime LinkedIn secret appeared in a tracked safe surface.")


def test_no_linkedin_scraping_messaging_or_organization_write_endpoints_exist() -> None:
    client = _source("integrations/linkedin_api_client.py")
    forbidden = ("ugcPosts", "/rest/messages", "/rest/inmail", "/rest/connections", "/rest/socialActions")
    assert all(value not in client for value in forbidden)
