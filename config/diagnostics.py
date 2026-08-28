"""Release-safe configuration validation and diagnostics."""

from __future__ import annotations

import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config.settings import Settings, settings


ROOT = Path(__file__).resolve().parent.parent


_BOOL_VALUES = {"0", "1", "false", "true", "no", "yes", "off", "on"}
_REQUIRED_LINKEDIN_SCOPES = {"openid", "profile", "w_member_social"}


def _configured(value: object) -> bool:
    return bool(str(value or "").strip())


def _check(name: str, valid: bool, detail: str) -> dict[str, str | bool]:
    return {"name": name, "valid": valid, "detail": detail}


def configuration_diagnostics(current: Settings = settings) -> dict[str, Any]:
    """Return safe configuration state; values and secrets are never returned."""
    checks: list[dict[str, str | bool]] = []
    for name, value in (
        ("NVIDIA_API_KEY", current.nvidia_api_key),
        ("LINKEDIN_CLIENT_ID", current.linkedin_client_id),
        ("LINKEDIN_CLIENT_SECRET", current.linkedin_client_secret),
        ("LINKEDIN_TOKEN_ENCRYPTION_KEY", current.linkedin_token_encryption_key),
    ):
        checks.append(_check(name, _configured(value), "configured" if _configured(value) else "missing"))
    for name, value in (
        ("GOOGLE_CALENDAR_CREDENTIALS_PATH", current.google_calendar_credentials_path),
        ("GOOGLE_CALENDAR_MCP_TOKEN_PATH", current.google_calendar_mcp_token_path),
    ):
        if _configured(value):
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            checks.append(_check(name + ".file", path.is_file(), "regular file" if path.is_file() else "missing regular file"))
    for name, value in (
        ("GOOGLE_CALENDAR_CREDENTIALS_PATH", current.google_calendar_credentials_path),
        ("GOOGLE_CALENDAR_MCP_TOKEN_PATH", current.google_calendar_mcp_token_path),
        ("DATABASE_PATH", current.database_path),
    ):
        checks.append(_check(name, _configured(value), "configured" if _configured(value) else "missing"))

    checks.extend(
        [
            _check(
                "TELEGRAM_BOT_TOKEN",
                True,
                "legacy adapter optional; web UI/API is the active interface",
            ),
            _check(
                "TELEGRAM_ALLOWED_USER_IDS",
                bool(current.telegram_allowed_user_ids.strip()) and all(
                    re.fullmatch(r"[0-9]+", item.strip())
                    for item in current.telegram_allowed_user_ids.split(",")
                    if item.strip()
                ),
                "numeric private-beta allowlist" if current.telegram_allowed_user_ids.strip() else "missing; access is denied by default",
            ),
            _check(
                "TELEGRAM_ADMIN_USER_IDS",
                all(
                    re.fullmatch(r"[0-9]+", item.strip())
                    for item in current.telegram_admin_user_ids.split(",")
                    if item.strip()
                ),
                "numeric admin IDs" if current.telegram_admin_user_ids.strip() else "not configured",
            ),
            _check(
                "LINKEDIN_PUBLISH_MODE",
                current.linkedin_publish_mode in {"disabled", "mock", "real"},
                current.linkedin_publish_mode if current.linkedin_publish_mode in {"disabled", "mock", "real"} else "invalid",
            ),
            _check(
                "LINKEDIN_REAL_PUBLISH_ENABLED",
                current.linkedin_real_publish_enabled == (current.linkedin_publish_mode == "real"),
                "real mode and kill switch agree" if current.linkedin_real_publish_enabled == (current.linkedin_publish_mode == "real") else "real mode requires the kill switch",
            ),
            _check(
                "LINKEDIN_OAUTH_SCOPES",
                set(current.linkedin_oauth_scopes.split()) == _REQUIRED_LINKEDIN_SCOPES,
                "allowlisted scopes" if set(current.linkedin_oauth_scopes.split()) == _REQUIRED_LINKEDIN_SCOPES else "must be openid profile w_member_social",
            ),
            _check(
                "LINKEDIN_API_BASE_URL",
                current.linkedin_api_base_url == "https://api.linkedin.com",
                "official HTTPS API host" if current.linkedin_api_base_url == "https://api.linkedin.com" else "must be https://api.linkedin.com",
            ),
            _check(
                "LINKEDIN_REDIRECT_URI",
                not current.linkedin_redirect_uri or urlparse(current.linkedin_redirect_uri).scheme == "https",
                "HTTPS or not configured" if not current.linkedin_redirect_uri or urlparse(current.linkedin_redirect_uri).scheme == "https" else "must use HTTPS",
            ),
            _check("MOCK_MODE", True, "enabled" if current.mock_mode else "disabled"),
            _check("IMAGE_MODE", current.image_mode in {"disabled", "mock", "real"}, current.image_mode),
            _check("DAILY_BRIEFING_ENABLED", True, "enabled" if current.daily_briefing_enabled else "disabled"),
            _check("PUBLIC_SIGNAL_ALLOW_HTTP", not current.public_signal_allow_http, "disabled" if not current.public_signal_allow_http else "unsafe HTTP enabled"),
        ]
    )
    for numeric_name, numeric_value in (
        ("NVIDIA_TIMEOUT_SECONDS", current.nvidia_timeout_seconds),
        ("LINKEDIN_REQUEST_TIMEOUT_SECONDS", current.linkedin_request_timeout_seconds),
        ("LINKEDIN_PUBLISH_REQUEST_TTL_SECONDS", current.linkedin_publish_request_ttl_seconds),
        ("LINKEDIN_MAX_CONFIRMATION_ATTEMPTS", current.linkedin_max_confirmation_attempts),
        ("PUBLIC_SIGNAL_MAX_RESPONSE_BYTES", current.public_signal_max_response_bytes),
        ("BACKGROUND_OPERATION_TIMEOUT_SECONDS", current.background_operation_timeout_seconds),
        ("MAX_BACKGROUND_OPERATIONS", current.max_background_operations),
    ):
        checks.append(_check(numeric_name, 0 < numeric_value <= 86_400_000, "within safe range" if 0 < numeric_value <= 86_400_000 else "outside safe range"))

    invalid_booleans = [
        name for name in (
            "MOCK_MODE", "LINKEDIN_REAL_PUBLISH_ENABLED", "GENERATE_IMAGE_FOR_DRAFT_POSTS",
            "AUTO_GENERATE_CONTENT_IMAGES", "DAILY_BRIEFING_ENABLED", "BRIEFING_DRY_RUN",
            "PUBLIC_SIGNAL_ALLOW_HTTP",
        ) if os.getenv(name) is not None and os.getenv(name, "").strip().lower() not in _BOOL_VALUES
    ]
    if invalid_booleans:
        checks.append(_check("boolean_variables", False, "invalid: " + ",".join(invalid_booleans)))
    valid = all(
        bool(item["valid"])
        for item in checks
        if item["name"] not in {"TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_ADMIN_USER_IDS"}
    )
    beta_access_ready = any(
        item["name"] == "TELEGRAM_ALLOWED_USER_IDS" and bool(item["valid"])
        for item in checks
    )
    return {
        "valid": valid,
        "beta_access_ready": beta_access_ready,
        "checks": checks,
        "active_modes": {
            "interface": "web_ui_pending",
            "model": "mock" if current.mock_mode else "real",
            "image": current.image_mode,
            "briefing": "enabled" if current.daily_briefing_enabled else "disabled",
            "linkedin": current.linkedin_publish_mode,
            "linkedin_real_write": current.linkedin_real_publish_enabled,
            "public_signal_http": current.public_signal_allow_http,
            "signal_graph": current.signal_graph_mode,
            "content_graph": current.content_graph_mode,
        },
        "safe_defaults": {
            "linkedin_disabled": current.linkedin_publish_mode == "disabled" and not current.linkedin_real_publish_enabled,
            "image_generation_disabled": current.image_mode == "disabled" and not current.auto_generate_content_images,
            "briefing_disabled": not current.daily_briefing_enabled,
            "public_http_disabled": not current.public_signal_allow_http,
        },
    }


def settings_snapshot_for_tests(current: Settings = settings) -> dict[str, Any]:
    """Expose only non-secret settings for deterministic tests and diagnostics."""
    data = asdict(current)
    for secret in (
        "nvidia_api_key",
        "telegram_bot_token",
        "linkedin_client_secret",
        "linkedin_token_encryption_key",
        "web_api_token",
    ):
        data.pop(secret, None)
    return data
