"""Retired Telegram entrypoint kept as a migration guard."""

def main() -> None:
    """Fail closed so Telegram cannot start as an active service."""
    raise SystemExit(
        "Telegram runtime retired. Use the authenticated web UI/API. "
        "Migration-only testing uses scripts/run_legacy_telegram_bot.py."
    )


if __name__ == "__main__":
    main()
