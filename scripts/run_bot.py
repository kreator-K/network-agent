"""Run the Telegram bot."""

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from telegram_bot.bot import build_bot  # noqa: E402


def main() -> None:
    """Start the Telegram bot polling loop."""
    application = build_bot()
    application.run_polling()


if __name__ == "__main__":
    main()
