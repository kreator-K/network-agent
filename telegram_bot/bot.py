"""Telegram bot application bootstrap."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from config.settings import settings
from config.diagnostics import configuration_diagnostics
from agents.calendar_agent import CalendarAgent
from agents.orchestrator import NetworkOrchestrator
from db.database import initialize_database
from integrations.google_calendar_mcp_runtime import GoogleCalendarMCPRuntime
from telegram_bot import handlers
from telegram_bot.access import authorization_guard


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
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["database_path"] = settings.database_path
    application.bot_data["started_at"] = datetime.now(UTC).isoformat()
    application.bot_data["configuration_diagnostics"] = configuration_diagnostics()
    application.bot_data["orchestrator"] = NetworkOrchestrator(
        calendar_agent=CalendarAgent(Path(settings.database_path))
    )

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(TypeHandler(Update, authorization_guard), group=-1)
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
    application.add_handler(CommandHandler("add_signal_sources", handlers.add_signal_sources))
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
    application.add_handler(CommandHandler("scoring_diagnostics", handlers.scoring_diagnostics))
    application.add_handler(CommandHandler("scoring_queue", handlers.scoring_queue))
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
    application.add_handler(CommandHandler("feedback", handlers.feedback))
    application.add_handler(CommandHandler("beta_status", handlers.beta_status))
    application.add_handler(CommandHandler("briefing_now", handlers.briefing_now))
    application.add_handler(CommandHandler("scan_now", handlers.scan_now))
    application.add_handler(CommandHandler("briefing_status", handlers.briefing_status))
    application.add_handler(CommandHandler("briefing_history", handlers.briefing_history))
    application.add_handler(CommandHandler("briefing_run", handlers.briefing_run))
    application.add_handler(CommandHandler("daily_briefing", handlers.daily_briefing))
    application.add_handler(CommandHandler("discover_candidates", handlers.discover_candidates))
    application.add_handler(CommandHandler("prospect_candidates", handlers.prospect_candidates))
    application.add_handler(CommandHandler("approve_candidate", handlers.approve_candidate))
    application.add_handler(CommandHandler("linkedin_connect", handlers.linkedin_connect))
    application.add_handler(CommandHandler("linkedin_connection_status", handlers.linkedin_connection_status))
    application.add_handler(CommandHandler("linkedin_access_check", handlers.linkedin_access_check))
    application.add_handler(CommandHandler("linkedin_publish_status", handlers.linkedin_publish_status))
    application.add_handler(CommandHandler("linkedin_publish_diagnostics", handlers.linkedin_publish_diagnostics))
    application.add_handler(CommandHandler("linkedin_reauthorize", handlers.linkedin_reauthorize))
    application.add_handler(CommandHandler("linkedin_disconnect", handlers.linkedin_disconnect))
    application.add_handler(CommandHandler("linkedin_oauth_history", handlers.linkedin_oauth_history))
    application.add_handler(CommandHandler("prepare_publish", handlers.prepare_publish))
    application.add_handler(CommandHandler("confirm_publish", handlers.confirm_publish))
    application.add_handler(CommandHandler("cancel_publish", handlers.cancel_publish))
    application.add_handler(CommandHandler("publish_request", handlers.publish_request))
    application.add_handler(CommandHandler("publish_history", handlers.publish_history))
    application.add_handler(CommandHandler("resolve_publish_uncertain", handlers.resolve_publish_uncertain))
    logger.info("Registered LinkedIn status handlers: linkedin_access_check, linkedin_connection_status, linkedin_publish_status")
    application.add_handler(CallbackQueryHandler(handlers.button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.photo_reply))
    application.add_error_handler(error_handler)
    return application


async def _post_init(application: Application) -> None:
    """Start one persistent optional calendar runtime for the bot lifecycle."""
    orchestrator = application.bot_data["orchestrator"]
    try:
        report = orchestrator.reconcile_linkedin_publish_requests(
            database=application.bot_data["database_path"]
        )
        application.bot_data["linkedin_publish_reconciliation"] = report
        logger.info(
            "LinkedIn publish startup reconciliation completed: count=%s provider_calls=0",
            report["reconciled"],
        )
    except Exception as exc:
        logger.warning(
            "LinkedIn publish startup reconciliation unavailable: %s",
            type(exc).__name__,
        )
    runtime = GoogleCalendarMCPRuntime()
    application.bot_data["calendar_runtime"] = runtime
    try:
        await runtime.start()
    except Exception as exc:
        logger.warning("Google Calendar MCP unavailable; bot will continue: %s", type(exc).__name__)
        application.bot_data["calendar_unavailable"] = True
        return
    application.bot_data["orchestrator"] = NetworkOrchestrator(
        calendar_agent=CalendarAgent(Path(settings.database_path), runtime.client)
    )


async def _post_shutdown(application: Application) -> None:
    """Close the persistent calendar runtime, including partial startup."""
    runtime = application.bot_data.get("calendar_runtime")
    if runtime is not None:
        await runtime.close()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delegate uncaught Telegram errors to the user-safe handler."""
    await handlers.handle_error(update, context)
