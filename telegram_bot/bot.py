"""Telegram bot application bootstrap."""

import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.settings import settings
from db.database import initialize_database
from telegram_bot import handlers


logger = logging.getLogger(__name__)


def build_bot() -> Application:
    """Build and configure the python-telegram-bot application."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required to start the Telegram bot.")

    initialize_database(settings.database_path)
    logger.info(
        "Network-agent modes: model=%s calendar=%s image=%s refinement=%s",
        "mock" if settings.mock_mode else "real",
        "mock" if settings.mock_mode else "real",
        "mock" if settings.mock_mode else "real",
        "report_only",
    )
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
    application.add_handler(CommandHandler("brand_profile", handlers.brand_profile))
    application.add_handler(
        CommandHandler("brand_profile_versions", handlers.brand_profile_versions)
    )
    application.add_handler(
        CommandHandler("activate_brand_profile", handlers.activate_brand_profile)
    )
    application.add_handler(CommandHandler("set_brand_field", handlers.set_brand_field))
    application.add_handler(CommandHandler("add_signal_source", handlers.add_signal_source))
    application.add_handler(CommandHandler("signal_sources", handlers.signal_sources))
    application.add_handler(
        CommandHandler("approve_signal_source", handlers.approve_signal_source)
    )
    application.add_handler(
        CommandHandler("reject_signal_source", handlers.reject_signal_source)
    )
    application.add_handler(
        CommandHandler("enable_signal_source", handlers.enable_signal_source)
    )
    application.add_handler(
        CommandHandler("disable_signal_source", handlers.disable_signal_source)
    )
    application.add_handler(CommandHandler("scan_signal_source", handlers.scan_signal_source))
    application.add_handler(CommandHandler("scan_signals", handlers.scan_signals))
    application.add_handler(CommandHandler("signals", handlers.signals))
    application.add_handler(CommandHandler("signal", handlers.signal))
    application.add_handler(CommandHandler("score_signal", handlers.score_signal))
    application.add_handler(CommandHandler("score_signals", handlers.score_signals))
    application.add_handler(CommandHandler("ranked_signals", handlers.ranked_signals))
    application.add_handler(
        CommandHandler("content_opportunities", handlers.content_opportunities)
    )
    application.add_handler(
        CommandHandler("content_opportunity", handlers.content_opportunity)
    )
    application.add_handler(CommandHandler("prepare_content", handlers.prepare_content))
    application.add_handler(CommandHandler("content_packages", handlers.content_packages))
    application.add_handler(CommandHandler("content_package", handlers.content_package))
    application.add_handler(CommandHandler("content_sources", handlers.content_sources))
    application.add_handler(CommandHandler("content_claims", handlers.content_claims))
    application.add_handler(CommandHandler("revise_content", handlers.revise_content))
    application.add_handler(CommandHandler("record_outcome", handlers.record_outcome))
    application.add_handler(
        CommandHandler("suggest_refinements", handlers.suggest_refinements)
    )
    application.add_handler(
        CommandHandler("refinement_status", handlers.refinement_status)
    )
    application.add_handler(
        CommandHandler("refinement_report", handlers.refinement_report)
    )
    application.add_handler(
        CommandHandler("rollback_refinement", handlers.rollback_refinement)
    )
    application.add_handler(
        CommandHandler("refinement_history", handlers.refinement_history)
    )
    application.add_handler(CommandHandler("system_check", handlers.system_check))
    application.add_handler(CallbackQueryHandler(handlers.button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.photo_reply))
    application.add_error_handler(error_handler)
    return application


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delegate uncaught Telegram errors to the user-safe handler."""
    await handlers.handle_error(update, context)
