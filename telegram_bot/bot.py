"""Telegram bot application bootstrap."""

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.settings import settings
from telegram_bot import handlers


def build_bot() -> Application:
    """Build and configure the python-telegram-bot application."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required to start the Telegram bot.")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["database_path"] = settings.database_path

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("add_prospect", handlers.add_prospect))
    application.add_handler(CommandHandler("draft_outreach", handlers.draft_outreach))
    application.add_handler(CommandHandler("draft_followup", handlers.draft_followup))
    application.add_handler(CommandHandler("followups_due", handlers.followups_due))
    application.add_handler(
        CommandHandler("meeting_confirmed", handlers.meeting_confirmed)
    )
    application.add_handler(CommandHandler("draft_post", handlers.draft_post))
    application.add_handler(CommandHandler("pending_drafts", handlers.pending_drafts))
    application.add_handler(CommandHandler("system_check", handlers.system_check))
    application.add_handler(CallbackQueryHandler(handlers.button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.photo_reply))
    application.add_error_handler(error_handler)
    return application


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delegate uncaught Telegram errors to the user-safe handler."""
    await handlers.handle_error(update, context)
