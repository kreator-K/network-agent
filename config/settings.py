"""Environment-backed settings for network-agent."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()
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
    followup_cadence_days: int = int(os.getenv("FOLLOWUP_CADENCE_DAYS", "21"))
    database_path: str = os.getenv("DATABASE_PATH", "network_agent.db")
    generate_image_for_draft_posts: bool = _env_bool(
        "GENERATE_IMAGE_FOR_DRAFT_POSTS",
        False,
    )
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


settings = Settings()
