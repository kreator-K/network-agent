"""Environment-backed settings for network-agent."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


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
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    google_calendar_credentials_path: str = os.getenv(
        "GOOGLE_CALENDAR_CREDENTIALS_PATH", ""
    )
    followup_cadence_days: int = int(os.getenv("FOLLOWUP_CADENCE_DAYS", "21"))
    database_path: str = os.getenv("DATABASE_PATH", "network_agent.db")


settings = Settings()
