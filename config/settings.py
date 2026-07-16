"""Environment-backed settings for network-agent."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv(".env.local", override=True)


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Application settings loaded from `.env` with mock-safe defaults."""

    mock_mode: bool = _env_bool("MOCK_MODE", True)
    nvidia_api_key: str = os.getenv("NVIDIA_API_KEY", "")
    nvidia_model: str = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")
    nvidia_max_tokens: int = int(os.getenv("NVIDIA_MAX_TOKENS", "800"))
    nvidia_temperature: float = float(os.getenv("NVIDIA_TEMPERATURE", "0.2"))
    nvidia_timeout_seconds: int = int(os.getenv("NVIDIA_TIMEOUT_SECONDS", "30"))
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    google_calendar_credentials_path: str = os.getenv(
        "GOOGLE_CALENDAR_CREDENTIALS_PATH", ""
    )
    google_calendar_mcp_token_path: str = os.getenv(
        "GOOGLE_CALENDAR_MCP_TOKEN_PATH", ""
    )
    google_calendar_id: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    google_calendar_account: str = os.getenv("GOOGLE_CALENDAR_ACCOUNT", "")
    google_calendar_timezone: str = os.getenv(
        "GOOGLE_CALENDAR_TIMEZONE", "America/New_York"
    )
    linkedin_client_id: str = os.getenv("LINKEDIN_CLIENT_ID", "")
    linkedin_client_secret: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    linkedin_redirect_uri: str = os.getenv("LINKEDIN_REDIRECT_URI", "")
    linkedin_token_path: str = os.getenv("LINKEDIN_TOKEN_PATH", "secrets/linkedin-tokens.enc")
    linkedin_token_encryption_key: str = os.getenv("LINKEDIN_TOKEN_ENCRYPTION_KEY", "")
    linkedin_oauth_scopes: str = os.getenv("LINKEDIN_OAUTH_SCOPES", "openid profile w_member_social")
    linkedin_oauth_state_ttl_seconds: int = int(os.getenv("LINKEDIN_OAUTH_STATE_TTL_SECONDS", "600"))
    linkedin_request_timeout_seconds: int = int(os.getenv("LINKEDIN_REQUEST_TIMEOUT_SECONDS", "30"))
    linkedin_publish_mode: str = os.getenv("LINKEDIN_PUBLISH_MODE", "disabled")
    linkedin_real_publish_enabled: bool = _env_bool("LINKEDIN_REAL_PUBLISH_ENABLED", False)
    linkedin_api_base_url: str = os.getenv("LINKEDIN_API_BASE_URL", "https://api.linkedin.com")
    linkedin_api_version: str = os.getenv("LINKEDIN_API_VERSION", "202606")
    linkedin_restli_protocol_version: str = os.getenv("LINKEDIN_RESTLI_PROTOCOL_VERSION", "2.0.0")
    linkedin_default_visibility: str = os.getenv("LINKEDIN_DEFAULT_VISIBILITY", "PUBLIC")
    linkedin_publish_request_ttl_seconds: int = int(os.getenv("LINKEDIN_PUBLISH_REQUEST_TTL_SECONDS", "900"))
    linkedin_max_confirmation_attempts: int = int(os.getenv("LINKEDIN_MAX_CONFIRMATION_ATTEMPTS", "5"))
    linkedin_max_multi_images: int = int(os.getenv("LINKEDIN_MAX_MULTI_IMAGES", "20"))
    linkedin_max_image_bytes: int = int(os.getenv("LINKEDIN_MAX_IMAGE_BYTES", "20971520"))
    linkedin_max_document_bytes: int = int(os.getenv("LINKEDIN_MAX_DOCUMENT_BYTES", "104857600"))
    linkedin_max_video_bytes: int = int(os.getenv("LINKEDIN_MAX_VIDEO_BYTES", "524288000"))
    followup_cadence_days: int = int(os.getenv("FOLLOWUP_CADENCE_DAYS", "21"))
    database_path: str = os.getenv("DATABASE_PATH", "network_agent.db")
    generate_image_for_draft_posts: bool = _env_bool(
        "GENERATE_IMAGE_FOR_DRAFT_POSTS",
        False,
    )
    image_mode: str = os.getenv("IMAGE_MODE", "disabled")
    auto_generate_content_images: bool = _env_bool("AUTO_GENERATE_CONTENT_IMAGES", False)
    default_content_image_aspect_ratio: str = os.getenv("DEFAULT_CONTENT_IMAGE_ASPECT_RATIO", "1:1")
    max_image_generations_per_package: int = int(os.getenv("MAX_IMAGE_GENERATIONS_PER_PACKAGE", "1"))
    image_provider_timeout_seconds: int = int(os.getenv("IMAGE_PROVIDER_TIMEOUT_SECONDS", "30"))
    daily_briefing_enabled: bool = _env_bool("DAILY_BRIEFING_ENABLED", False)
    daily_briefing_time: str = os.getenv("DAILY_BRIEFING_TIME", "08:30")
    briefing_timezone: str = os.getenv("BRIEFING_TIMEZONE", "America/New_York")
    briefing_telegram_chat_id: str = os.getenv("BRIEFING_TELEGRAM_CHAT_ID", "")
    max_sources_per_briefing_run: int = int(os.getenv("MAX_SOURCES_PER_BRIEFING_RUN", "5"))
    max_signals_per_briefing_run: int = int(os.getenv("MAX_SIGNALS_PER_BRIEFING_RUN", "10"))
    max_content_opportunities_per_briefing: int = int(os.getenv("MAX_CONTENT_OPPORTUNITIES_PER_BRIEFING", "5"))
    auto_prepare_top_n: int = int(os.getenv("AUTO_PREPARE_TOP_N", "1"))
    briefing_dry_run: bool = _env_bool("BRIEFING_DRY_RUN", False)
    public_signal_allow_http: bool = _env_bool("PUBLIC_SIGNAL_ALLOW_HTTP", False)
    public_signal_connect_timeout_seconds: int = int(
        os.getenv("PUBLIC_SIGNAL_CONNECT_TIMEOUT_SECONDS", "5")
    )
    public_signal_read_timeout_seconds: int = int(
        os.getenv("PUBLIC_SIGNAL_READ_TIMEOUT_SECONDS", "15")
    )
    public_signal_max_response_bytes: int = int(
        os.getenv("PUBLIC_SIGNAL_MAX_RESPONSE_BYTES", "1000000")
    )
    public_signal_max_items_per_fetch: int = int(
        os.getenv("PUBLIC_SIGNAL_MAX_ITEMS_PER_FETCH", "50")
    )
    public_signal_max_redirects: int = int(
        os.getenv("PUBLIC_SIGNAL_MAX_REDIRECTS", "3")
    )
    background_operation_timeout_seconds: int = int(
        os.getenv("BACKGROUND_OPERATION_TIMEOUT_SECONDS", "120")
    )
    max_background_operations: int = int(
        os.getenv("MAX_BACKGROUND_OPERATIONS", "2")
    )
    application_environment: str = os.getenv("APPLICATION_ENVIRONMENT", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    callback_host: str = os.getenv("LINKEDIN_CALLBACK_HOST", "127.0.0.1")
    callback_port: int = int(os.getenv("LINKEDIN_CALLBACK_PORT", "8080"))
    telegram_allowed_user_ids: str = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    telegram_admin_user_ids: str = os.getenv("TELEGRAM_ADMIN_USER_IDS", "")
    media_storage_path: str = os.getenv("MEDIA_STORAGE_PATH", "runtime/media")
    backup_path: str = os.getenv("BACKUP_PATH", "backups")
    log_path: str = os.getenv("LOG_PATH", "logs")
    runtime_state_path: str = os.getenv("RUNTIME_STATE_PATH", "runtime/state")
    backup_retention_count: int = int(os.getenv("BACKUP_RETENTION_COUNT", "14"))
    backup_schedule: str = os.getenv("BACKUP_SCHEDULE", "03:00")


settings = Settings()
