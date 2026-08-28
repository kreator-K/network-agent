"""Phase 9 configuration safety diagnostics."""

from dataclasses import replace

from config.diagnostics import configuration_diagnostics
from config.settings import settings


def test_configuration_diagnostics_is_safe_and_reports_valid_local_config() -> None:
    result = configuration_diagnostics()
    assert result["valid"] is True
    rendered = repr(result)
    for secret in (
        settings.linkedin_client_secret,
        settings.linkedin_token_encryption_key,
        settings.nvidia_api_key,
    ):
        if secret:
            assert secret not in rendered


def test_configuration_diagnostics_rejects_real_publish_without_kill_switch() -> None:
    invalid = replace(settings, linkedin_publish_mode="real", linkedin_real_publish_enabled=False)
    result = configuration_diagnostics(invalid)
    assert result["valid"] is False
    assert any(item["name"] == "LINKEDIN_REAL_PUBLISH_ENABLED" and not item["valid"] for item in result["checks"])


def test_configuration_diagnostics_rejects_invalid_mode() -> None:
    result = configuration_diagnostics(replace(settings, linkedin_publish_mode="unsafe"))
    assert result["valid"] is False
    assert any(item["name"] == "LINKEDIN_PUBLISH_MODE" and not item["valid"] for item in result["checks"])


def test_configuration_diagnostics_reports_web_interface_readiness() -> None:
    result = configuration_diagnostics(replace(settings, web_api_token="x" * 32))

    assert result["active_modes"]["interface"] == "web_ui"
    assert result["beta_access_ready"] is True
