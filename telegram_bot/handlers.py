"""Thin Telegram command handlers for Network Growth Agent."""

import asyncio
import logging
import json
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agents.orchestrator import NetworkOrchestrator, NetworkOrchestratorError
from agents.system_integrity_agent import SystemIntegrityAgent
from config.settings import settings
from db.database import connect
from telegram_bot.access import is_admin, update_user_id


logger = logging.getLogger(__name__)
ALLOWED_ASK_TYPES = {"resume_review", "career_guidance", "general_chat"}
PHOTO_UPLOAD_DIR = Path("/tmp/network-agent-telegram-photos")
OUTREACH_OUTCOMES = {
    "replied_positive",
    "replied_neutral",
    "replied_negative",
    "no_reply",
    "meeting_booked",
    "not_relevant",
    "manually_sent",
    "custom_note",
}
CONTENT_OUTCOMES = {
    "good_engagement",
    "low_engagement",
    "comments_positive",
    "comments_negative",
    "saved_for_later",
    "discarded",
    "custom_note",
}


async def start(update: Any, context: Any) -> None:
    """List available bot commands."""
    _ = context
    await _reply(
        update,
        "\n".join(
            [
                "Available commands:",
                "/add_prospect <name> | <profile_url> | <location> | <role_title> | <company> | <notes>",
                "/draft_outreach <prospect_id> <ask_type>",
                "/draft_followup <prospect_id>",
                "/followups_due",
                "/meeting_confirmed <prospect_id> <date:YYYY-MM-DD> <start_time:HH:MM> [end_time:HH:MM]",
                "/draft_post <topic>",
                "/pending_drafts",
                "/brand_profile",
                "/brand_profile_versions",
                "/activate_brand_profile <version>",
                "/set_brand_field <field> | <value>",
                "/add_signal_source <name> | <rss_or_atom_url>",
                "/signal_sources",
                "/approve_signal_source <source_id>",
                "/reject_signal_source <source_id>",
                "/enable_signal_source <source_id>",
                "/disable_signal_source <source_id>",
                "/scan_signal_source <source_id>",
                "/scan_signals",
                "/signals",
                "/signal <signal_id>",
                "/score_signal <signal_id>",
                "/score_signals [limit]",
                "/ranked_signals",
                "/scoring_diagnostics",
                "/scoring_queue [limit]",
                "/content_opportunities",
                "/content_opportunity <opportunity_id>",
                "/prepare_content <opportunity_id>",
                "/content_packages",
                "/content_package <post_id>",
                "/content_sources <post_id>",
                "/content_claims <post_id>",
                "/revise_content <post_id> <revision_type>",
                "/record_outcome <outreach|content> <id> <outcome> [notes]",
                "/suggest_refinements",
                "/refinement_status",
                "/refinement_report",
                "/rollback_refinement <refinement_id>",
                "/refinement_history",
                "/system_check",
                "/briefing_now [dry_run]",
                "/scan_now",
                "/briefing_status",
                "/briefing_history",
                "/briefing_run <run_id>",
                "/daily_briefing on|off|time <HH:MM>",
                "/discover_candidates",
                "/prospect_candidates",
                "/approve_candidate <candidate_id>",
                "/linkedin_connect",
                "/linkedin_connection_status",
                "/linkedin_access_check",
                "/linkedin_publish_status",
                "/linkedin_reauthorize",
                "/linkedin_disconnect",
                "/linkedin_oauth_history",
                "/prepare_publish <post_id>",
                "/confirm_publish <request_id>",
                "/cancel_publish <request_id>",
                "/publish_request <request_id>",
                "/publish_history",
                "/resolve_publish_uncertain <request_id> posted|not_posted",
                "/feedback [bug|safety] <message>",
                "/beta_status",
            ]
        ),
    )


async def feedback(update: Any, context: Any) -> None:
    """Store private-beta feedback locally without forwarding it externally."""
    payload = _command_payload(update).strip()
    if not payload:
        await _reply(update, "Usage: /feedback [bug|safety] <message>")
        return
    parts = payload.split(maxsplit=1)
    category = parts[0].lower() if parts[0].lower() in {"bug", "safety"} else "feedback"
    message = parts[1].strip() if category != "feedback" and len(parts) == 2 else payload
    if not message or len(message) > 4000:
        await _reply(update, "Feedback must contain between 1 and 4000 characters.")
        return
    user_id = update_user_id(update)
    if user_id is None:
        await _reply(update, "Could not identify the authorized Telegram user.")
        return
    with connect(_database(context)) as connection:
        connection.execute(
            "INSERT INTO beta_feedback (telegram_user_id, category, message, created_at) VALUES (?, ?, ?, ?)",
            (str(user_id), category, message, datetime.now(UTC).isoformat()),
        )
    await _reply(update, "Feedback received and stored for the private beta.")


async def beta_status(update: Any, context: Any) -> None:
    """Show safe owner-only private-beta operational status."""
    if not is_admin(update):
        await _reply(update, "This command is available to beta administrators only.")
        return
    with connect(_database(context)) as connection:
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        uncertain = int(connection.execute("SELECT COUNT(*) FROM linkedin_publish_requests WHERE status LIKE '%uncertain%' OR status = 'processing_unknown'").fetchone()[0])
    diagnostics = context.application.bot_data.get("configuration_diagnostics", {})
    modes = diagnostics.get("active_modes", {})
    authorized_count = len([item for item in settings.telegram_allowed_user_ids.split(",") if item.strip()])
    await _reply(
        update,
        "Beta status:\n"
        f"Application environment: {settings.application_environment}\n"
        f"Authorized users: {authorized_count}\n"
        f"LinkedIn mode: {modes.get('linkedin', settings.linkedin_publish_mode)}\n"
        f"Real publishing enabled: {settings.linkedin_real_publish_enabled}\n"
        f"Database schema version: {schema_version}\n"
        f"Uncertain operations: {uncertain}\n"
        "Health: local diagnostics available",
    )


async def linkedin_connect(update: Any, context: Any) -> None:
    """Start the direct LinkedIn OAuth flow; no provider call is made here."""
    try:
        result = _orchestrator(context).prepare_linkedin_authorization(
            telegram_user_id=str(update.effective_user.id),
            telegram_chat_id=str(update.effective_chat.id), database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "LinkedIn connection is not configured. Check the bot logs.")
        return
    await _reply(update, f"Open this authorization link to connect LinkedIn:\n{result['authorization_url']}\nRequested permissions: {', '.join(result['scopes'])}.\nConnecting does not publish anything.\nThe link expires in 10 minutes.")


async def linkedin_connection_status(update: Any, context: Any) -> None:
    try:
        result = _orchestrator(context).get_linkedin_connection_status(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "LinkedIn connection status is unavailable.")
        return
    missing = result.get("missing_scopes", [])
    missing_line = "\nMissing scopes: " + ", ".join(missing) if missing else ""
    await _reply(update, f"LinkedIn status: {result['status']}\nScopes: {', '.join(result.get('granted_scopes', [])) or 'none'}{missing_line}\nPublishing mode: {result['publishing_mode']}\nReal publishing available: no")


async def linkedin_access_check(update: Any, context: Any) -> None:
    try:
        result = _orchestrator(context).get_linkedin_access_check(database=_database(context))
    except NetworkOrchestratorError:
        logger.exception("LinkedIn access check failed at local_status")
        await _reply(update, "Unable to read LinkedIn access status due to a local configuration or database error. Nothing was published.")
        return
    await _reply(update, _format_linkedin_access_check(result))


async def linkedin_reauthorize(update: Any, context: Any) -> None:
    await linkedin_connect(update, context)


async def linkedin_disconnect(update: Any, context: Any) -> None:
    query = InlineKeyboardMarkup([[InlineKeyboardButton("Confirm disconnect", callback_data="linkedin_disconnect_confirm")]])
    await _reply(update, "This revokes local LinkedIn credentials. Nothing will be published.", query)


async def linkedin_oauth_history(update: Any, context: Any) -> None:
    try:
        rows = _orchestrator(context).list_linkedin_oauth_history(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "LinkedIn authorization history is unavailable.")
        return
    await _reply(update, "No LinkedIn authorization attempts yet." if not rows else "\n".join(f"{row['created_at']} | {row['status']} | stage={row.get('failure_stage') or 'completed'} | reason={row.get('error_summary') or 'none'} | ref={row.get('correlation_id') or 'none'}" for row in rows))


async def linkedin_publish_status(update: Any, context: Any) -> None:
    """Show local publishing readiness; this never calls LinkedIn."""
    try:
        result = _orchestrator(context).get_linkedin_publish_status(database=_database(context))
    except NetworkOrchestratorError:
        logger.exception("LinkedIn publish status failed at local_status")
        await _reply(update, "Unable to read LinkedIn publishing status due to a local configuration or database error. Nothing was published.")
        return
    await _reply(update, "LinkedIn publishing status\n\n"
        f"Mode: {result['publishing_mode']}\n"
        f"Real publishing enabled: {'yes' if result['real_publish_enabled'] else 'no'}\n"
        f"Connection: {result['connection_status']}\n"
        f"Permission w_member_social: {'available' if result['w_member_social'] else 'unavailable until authorization'}\n"
        f"Pending confirmations: {result['pending_confirmations']}\n"
        f"Real publishing available: {'yes' if result['real_publishing_available'] else 'no'}\n"
        "A separate /prepare_publish and /confirm_publish sequence is always required.")


async def linkedin_publish_diagnostics(update: Any, context: Any) -> None:
    """Show local publishing health; this command never contacts LinkedIn."""
    try:
        result = _orchestrator(context).get_linkedin_publish_diagnostics(
            database=_database(context)
        )
    except NetworkOrchestratorError:
        logger.exception("LinkedIn publishing diagnostics failed")
        await _reply(
            update,
            "LinkedIn publishing diagnostics are unavailable. Nothing was published.",
        )
        return
    failures = result.get("recent_safe_failures", [])
    failure_lines = [
        f"- request {item['request_id']}: {item['status']} ({item.get('code') or 'unknown'})"
        for item in failures
    ]
    await _reply(
        update,
        "LinkedIn publishing diagnostics\n\n"
        f"Mode: {result['mode']}\n"
        f"Real publishing enabled: {'yes' if result['real_publish_enabled'] else 'no'}\n"
        f"Connection: {result.get('connection_status') or 'unknown'}\n"
        f"Member identity resolved: {'yes' if result.get('member_identity_resolved') else 'no'}\n"
        f"Pending: {result['pending']}\n"
        f"In progress: {result['in_progress']}\n"
        f"Uncertain: {result['uncertain']}\n"
        f"Stale: {result['stale']}\n"
        f"Startup reconciliations: {result['startup_reconciled_count']}\n"
        + ("Recent safe failures:\n" + "\n".join(failure_lines) if failure_lines else "Recent safe failures: none"),
    )


async def prepare_publish(update: Any, context: Any) -> None:
    """Freeze one approved package; this command never contacts LinkedIn."""
    post_id = _parse_int(_command_payload(update).strip(), "post_id")
    if post_id is None:
        await _reply(update, "Usage: /prepare_publish <post_id>")
        return
    try:
        readiness = _orchestrator(context).get_content_publish_readiness(
            post_id=post_id,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not inspect that content post safely.")
        return
    if not readiness["exists"]:
        await _reply(update, f"Content post id={post_id} does not exist.")
        return
    if not readiness["package_backed"]:
        await _reply(
            update,
            f"Post #{post_id} is a plain topic draft, not a publishable content package. "
            "Use /content_opportunities, then /prepare_content <opportunity_id>.",
        )
        return
    if not readiness["ready"]:
        blockers = "\n".join(f"- {item}" for item in readiness["blockers"])
        await _reply(
            update,
            f"Content package #{post_id} is not ready for publication:\n{blockers}",
        )
        return
    try:
        result = _orchestrator(context).prepare_linkedin_publish(post_id, database=_database(context))
    except NetworkOrchestratorError as exc:
        logger.info("LinkedIn preview rejected safely: %s", type(exc).__name__)
        await _reply(update, "Could not prepare that LinkedIn publish preview. Confirm the package is approved, current, and fully validated.")
        return
    assets = result.get("assets", [])
    if result.get("format") in {"single_image", "multi_image"} and update.effective_message:
        for asset in assets:
            try:
                await update.effective_message.reply_photo(photo=asset["path"], caption=f"Approved image: {asset['filename']}\nAlt text: {asset.get('alt_text') or '-'}")
            except Exception:
                logger.warning("Could not render frozen image preview for request_id=%s", result["request_id"])
    await _reply(update, _format_publish_preview(result))


async def confirm_publish(update: Any, context: Any) -> None:
    """Consume one explicit request ID; freeform consent is never accepted."""
    request_id = _parse_int(_command_payload(update).strip(), "request_id")
    if request_id is None:
        await _reply(update, "Usage: /confirm_publish <request_id>")
        return
    try:
        result = _orchestrator(context).confirm_linkedin_publish(request_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not complete that publish request. It may be expired, stale, already consumed, or uncertain. Run /publish_request for its safe status.")
        return
    if result.get("status") == "published_linkedin":
        await _reply(update, f"Published to LinkedIn successfully.\nPost ID: {result['provider_post_id']}\nRequest: {request_id}.")
    else:
        await _reply(update, result.get("message", "Nothing was published to LinkedIn."))


async def cancel_publish(update: Any, context: Any) -> None:
    request_id = _parse_int(_command_payload(update).strip(), "request_id")
    if request_id is None:
        await _reply(update, "Usage: /cancel_publish <request_id>")
        return
    try:
        _orchestrator(context).cancel_linkedin_publish(request_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "That publish request cannot be cancelled.")
        return
    await _reply(update, "Publish request cancelled. Nothing was published.")


async def publish_request(update: Any, context: Any) -> None:
    request_id = _parse_int(_command_payload(update).strip(), "request_id")
    if request_id is None:
        await _reply(update, "Usage: /publish_request <request_id>")
        return
    try:
        result = _orchestrator(context).get_linkedin_publish_request(request_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Publish request not found.")
        return
    await _reply(update, _format_publish_request(result))


async def publish_history(update: Any, context: Any) -> None:
    try:
        rows = _orchestrator(context).list_linkedin_publish_history(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "LinkedIn publish history is unavailable.")
        return
    await _reply(update, "No LinkedIn publish requests yet." if not rows else "\n".join(_format_publish_request(row) for row in rows))


async def resolve_publish_uncertain(update: Any, context: Any) -> None:
    parts = _command_payload(update).split()
    if len(parts) != 2 or parts[1] not in {"posted", "not_posted"}:
        await _reply(update, "Usage: /resolve_publish_uncertain <request_id> posted|not_posted")
        return
    request_id = _parse_int(parts[0], "request_id")
    if request_id is None:
        await _reply(update, "Usage: /resolve_publish_uncertain <request_id> posted|not_posted")
        return
    try:
        result = _orchestrator(context).resolve_linkedin_publish_uncertain(request_id, parts[1] == "posted", database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "That request is not awaiting manual uncertainty resolution.")
        return
    await _reply(update, _format_publish_request(result))


def _format_linkedin_access_check(result: dict[str, Any]) -> str:
    missing = result.get("missing", [])
    lines = [f"LinkedIn access check: {result['status']}"]
    if missing:
        lines.append("Missing:\n" + "\n".join(f"- {name}" for name in missing))
    lines.extend([
        f"Client ID configured: {'yes' if result['client_id_configured'] else 'no'}",
        f"Client Secret configured: {'yes' if result['client_secret_configured'] else 'no'}",
        f"Redirect URI valid HTTPS: {'yes' if result['redirect_uri_valid'] else 'no'}",
        f"OAuth scopes allowlisted: {'yes' if result['scopes_allowlisted'] else 'no'}",
        f"w_member_social requested: {'yes' if result['w_member_social_requested'] else 'no'}",
        f"Token encryption key valid: {'yes' if result['token_encryption_key_valid'] else 'no'}",
        f"Credential table available: {'yes' if result['credential_table_available'] else 'no'}",
        f"Active credential: {'yes' if result['active_credential_available'] else 'no'}",
        f"Member identity resolved: {'yes' if result['member_identity_resolved'] else 'no'}",
        f"Publishing mode: {result['publishing_mode']}",
        f"Real publishing enabled: {'yes' if result['real_publish_enabled'] else 'no'}",
        "Real publishing: disabled until Phase 8G-B2",
        "Next action: /linkedin_connect",
    ])
    return "\n".join(lines)


async def briefing_now(update: Any, context: Any) -> None:
    """Run one manual briefing; scheduled-disabled state never suppresses a reply."""
    logger.info("briefing_now command received")
    dry_run = _command_payload(update).strip().lower() == "dry_run"
    try:
        result = _orchestrator(context).build_daily_briefing(
            database=_database(context), run_type="manual", dry_run=dry_run
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not build a briefing right now. Check the bot logs for details.")
        return
    if result.get("status") == "skipped":
        await _reply(update, "A briefing already ran for this window. No duplicate work was created.")
        return
    await _reply(update, _format_briefing_result(result))


async def briefing_status(update: Any, context: Any) -> None:
    """Show briefing configuration and latest run, including disabled state."""
    logger.info("briefing_status command received")
    try:
        result = _orchestrator(context).get_briefing_status(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Briefing configuration is unavailable. Check database initialization and bot logs.")
        return
    last = result.get("last_run")
    last_text = "No briefing runs have been recorded yet." if last is None else f"Last run: #{last.get('id')} {last.get('status')}"
    await _reply(update, f"Briefing status: {'enabled' if result['enabled'] else 'disabled'}\nTime: {result['briefing_time']} ({result['timezone']})\nDry run: {result['dry_run']}\n{last_text}")


async def briefing_history(update: Any, context: Any) -> None:
    """Show recent briefing executions with a clean empty state."""
    logger.info("briefing_history command received")
    try:
        runs = _orchestrator(context).list_briefing_runs(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load briefing history. Check the bot logs for details.")
        return
    if not runs:
        await _reply(update, "No briefing runs have been recorded yet.")
        return
    await _reply(update, "\n".join(f"#{run['id']} {run['run_type']} | {run['status']} | packages={run['packages_prepared_count']}" for run in runs))


async def briefing_run(update: Any, context: Any) -> None:
    """Show one stored run summary."""
    run_id = _parse_int(_command_payload(update).strip(), "run_id")
    if run_id is None:
        await _reply(update, "Usage: /briefing_run <run_id>")
        return
    try:
        runs = _orchestrator(context).list_briefing_runs(database=_database(context), limit=100)
    except NetworkOrchestratorError:
        await _reply(update, "Could not load that briefing run.")
        return
    run = next((item for item in runs if item["id"] == run_id), None)
    if run is None:
        await _reply(update, f"No briefing run found for id={run_id}.")
        return
    await _reply(update, f"Briefing #{run_id}: {run['status']}\nSources: {run['sources_succeeded_count']}\nNew signals: {run['new_signals_count']}\nScored: {run['signals_scored_count']}\nPackages: {run['packages_prepared_count']}\nFollow-ups: {run['followups_due_count']}")


async def scan_now(update: Any, context: Any) -> None:
    """Perform ingestion only; no scoring, briefing, or package preparation."""
    try:
        result = _orchestrator(context).scan_enabled_signal_sources(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not scan enabled sources right now.")
        return
    await _reply(update, f"Scan complete. Sources: {result['sources_scanned']}. New signals: {result['new_signals']}. Duplicates: {result['duplicates']}. Failures: {result['failures']}.")


async def daily_briefing(update: Any, context: Any) -> None:
    """Change persistent configuration only; this never launches a scheduler."""
    payload = _command_payload(update).strip().split()
    if not payload:
        await _reply(update, "Usage: /daily_briefing on|off|time <HH:MM>")
        return
    try:
        if payload[0] == "on":
            result = _orchestrator(context).update_briefing_settings(enabled=True, database=_database(context))
        elif payload[0] == "off":
            result = _orchestrator(context).update_briefing_settings(enabled=False, database=_database(context))
        elif payload[0] == "time" and len(payload) == 2:
            result = _orchestrator(context).update_briefing_settings(briefing_time=payload[1], database=_database(context))
        else:
            await _reply(update, "Usage: /daily_briefing on|off|time <HH:MM>")
            return
    except NetworkOrchestratorError:
        await _reply(update, "Could not update briefing configuration.")
        return
    await _reply(update, f"Briefing configuration saved: {'enabled' if result['enabled'] else 'disabled'}, {result['briefing_time']} {result['timezone']}.")


async def discover_candidates(update: Any, context: Any) -> None:
    """Create review-only candidates from stored public signal metadata."""
    try:
        candidates = _orchestrator(context).discover_prospect_candidates(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not discover source-backed candidates right now.")
        return
    await _reply(update, "No new candidates found in stored approved signals." if not candidates else "\n".join(f"Candidate #{item['id']}: {item['full_name']} | score {item['total_score']:.0f} | {item['recommended_rationale']}" for item in candidates))


async def prospect_candidates(update: Any, context: Any) -> None:
    """List review-only prospect candidates without CRM insertion."""
    try:
        candidates = _orchestrator(context).list_prospect_candidates(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load prospect candidates.")
        return
    await _reply(update, "No prospect candidates have been recorded yet." if not candidates else "\n".join(f"#{item['id']} {item['full_name']} | {item['status']} | score {item['total_score']:.0f}" for item in candidates))


async def approve_candidate(update: Any, context: Any) -> None:
    """Explicitly approve a candidate for CRM insertion; no outreach is sent."""
    candidate_id = _parse_int(_command_payload(update).strip(), "candidate_id")
    if candidate_id is None:
        await _reply(update, "Usage: /approve_candidate <candidate_id>")
        return
    try:
        result = _orchestrator(context).approve_prospect_candidate(candidate_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not approve that candidate. Check the candidate ID and status.")
        return
    await _reply(update, f"Candidate approved and added to CRM as prospect #{_get_value(result['prospect'], 'id')}. No outreach was sent.")


async def add_prospect(update: Any, context: Any) -> None:
    """Parse a pipe-delimited prospect and route it through the orchestrator."""
    raw_payload = _command_payload(update)
    fields = [field.strip() for field in raw_payload.split("|")]
    if len(fields) > 6:
        await _reply(update, "Usage: /add_prospect name | profile_url | location | role_title | company | notes")
        return
    fields.extend([""] * (6 - len(fields)))
    name, profile_url, location, role_title, company, notes = fields
    if not name:
        await _reply(update, "Prospect name is required.")
        return

    result = _orchestrator(context).add_prospect(
        name=name,
        profile_url=_none_if_empty(profile_url),
        location=_none_if_empty(location),
        role_title=_none_if_empty(role_title),
        company=_none_if_empty(company),
        notes=_none_if_empty(notes),
        database=_database(context),
    )
    prospect = result["prospect"]
    await _reply(
        update,
        f"Prospect added: {_get_value(prospect, 'name')} (id={_get_value(prospect, 'id')})",
    )


async def draft_outreach(update: Any, context: Any) -> None:
    """Draft a LinkedIn connection request for manual sending."""
    parts = _command_payload(update).split()
    if len(parts) != 2:
        await _reply(update, "Usage: /draft_outreach <prospect_id> <ask_type>")
        return
    prospect_id_text, ask_type = parts
    if ask_type not in ALLOWED_ASK_TYPES:
        await _reply(
            update,
            "Invalid ask_type. Use one of: career_guidance, general_chat, resume_review.",
        )
        return
    prospect_id = _parse_int(prospect_id_text, "prospect_id")
    if prospect_id is None:
        await _reply(update, "prospect_id must be a number.")
        return

    try:
        result = _orchestrator(context).draft_outreach(
            prospect_id=prospect_id,
            ask_type=ask_type,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(
            update,
            f"Could not draft outreach for prospect_id={prospect_id}. "
            "Please check the prospect ID.",
        )
        return
    _store_outreach_draft_context(
        context,
        prospect_id=prospect_id,
        interaction_id=_get_value(result, "draft_interaction_id"),
        ask_type=ask_type,
        draft_text=str(result["draft"].get("draft_text", "")),
    )
    await _reply(
        update,
        _format_outreach_draft(result),
        reply_markup=_outreach_approval_markup(
            prospect_id,
            _get_value(result, "draft_interaction_id"),
        ),
    )


async def draft_followup(update: Any, context: Any) -> None:
    """Draft a LinkedIn follow-up for manual sending."""
    prospect_id = _parse_int(_command_payload(update).strip(), "prospect_id")
    if prospect_id is None:
        await _reply(update, "Usage: /draft_followup <prospect_id>")
        return

    try:
        result = _orchestrator(context).draft_followup(
            prospect_id=prospect_id,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(
            update,
            f"Could not draft follow-up for prospect_id={prospect_id}. "
            "Please check the prospect ID.",
        )
        return
    await _reply(
        update,
        _format_outreach_draft(result),
        reply_markup=_outreach_approval_markup(
            prospect_id,
            _get_value(result, "draft_interaction_id"),
        ),
    )


async def followups_due(update: Any, context: Any) -> None:
    """Show prospects due for follow-up."""
    due = _orchestrator(context).get_followups_due(database=_database(context))
    if not due:
        await _reply(update, "No follow-ups due.")
        return
    await _reply(update, "\n".join(_format_due_line(item) for item in due))


async def meeting_confirmed(update: Any, context: Any) -> None:
    """Confirm a meeting only from explicit command input."""
    parts = _command_payload(update).split()
    if len(parts) not in {3, 4}:
        await _reply(
            update,
            "Usage: /meeting_confirmed <prospect_id> <date:YYYY-MM-DD> <start_time:HH:MM> [end_time:HH:MM]",
        )
        return

    prospect_id = _parse_int(parts[0], "prospect_id")
    if prospect_id is None:
        await _reply(update, "prospect_id must be a number.")
        return
    if not _is_valid_date(parts[1]) or not _is_valid_time(parts[2]):
        await _reply(update, "Date/time must be YYYY-MM-DD and HH:MM.")
        return
    if len(parts) == 4 and not _is_valid_time(parts[3]):
        await _reply(update, "end_time must be HH:MM.")
        return

    timezone = settings.google_calendar_timezone
    try:
        zone = ZoneInfo(timezone)
        start = datetime.strptime(
            f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=zone)
        end = (
            datetime.strptime(f"{parts[1]} {parts[3]}", "%Y-%m-%d %H:%M").replace(tzinfo=zone)
            if len(parts) == 4
            else start + timedelta(hours=1)
        )
        result = await _orchestrator(context).create_confirmed_meeting_event(
            prospect_id=prospect_id,
            start=start,
            end=end,
            timezone=timezone,
            database=_database(context),
        )
    except Exception as exc:
        logger.warning("Meeting confirmation failed: %s", type(exc).__name__)
        await _reply(update, "Could not sync this confirmed meeting. Please try again.")
        return
    event = result["event"]
    status = getattr(event, "status", None)
    if status == "created" and getattr(event, "was_existing", False):
        message = f"Meeting was already scheduled for prospect {prospect_id}."
    else:
        message = f"Meeting scheduled for prospect {prospect_id}."
    link = getattr(event, "event_url", None)
    if link:
        message += f"\nCalendar link: {link}"
    await _reply(update, message)


async def draft_post(update: Any, context: Any) -> None:
    """Draft a content post with optional pending uploaded/generated image."""
    topic = _command_payload(update).strip()
    if not topic:
        await _reply(update, "Usage: /draft_post <topic>")
        return
    pending_image = _pop_pending_content_image(context)
    user_image_path = pending_image.get("image_path")
    result = _orchestrator(context).draft_content_post(
        topic=topic,
        inspiration_notes=None,
        user_image_path=user_image_path,
        generate_image=_generate_image_enabled(context) and user_image_path is None,
        database=_database(context),
    )
    post = result["post"]
    await _reply(
        update,
        _format_post_draft_response(post),
        reply_markup=_post_approval_markup(_get_value(post, "id")),
    )


async def photo_reply(update: Any, context: Any) -> None:
    """Store uploaded photo context for the next `/draft_post` command."""
    if not getattr(update.effective_message, "photo", None):
        await _reply(
            update,
            "Unsupported image type. Please upload a standard Telegram photo.",
        )
        return
    user_image_path = await _save_largest_photo(update)
    _store_pending_content_image(
        context,
        image_path=user_image_path,
        caption=getattr(update.effective_message, "caption", None),
    )
    await _reply(
        update,
        "Image saved for your next /draft_post.",
    )


async def pending_drafts(update: Any, context: Any) -> None:
    """Show pending outreach and content drafts."""
    drafts = _orchestrator(context).get_pending_drafts(database=_database(context))
    outreach = drafts.get("outreach", [])
    content = drafts.get("content", [])
    if not outreach and not content:
        await _reply(update, "No pending drafts right now.")
        return
    lines = _format_pending_drafts(outreach, content)
    await _reply(update, "\n".join(lines))


async def brand_profile(update: Any, context: Any) -> None:
    """Display the concise active personal-brand profile summary."""
    try:
        summary = _orchestrator(context).get_brand_profile_summary(
            database=_database(context)
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not load the personal-brand profile.")
        return
    if summary is None:
        await _reply(
            update,
            "No personal-brand profile is configured. Initialize the profile seed first.",
        )
        return
    await _reply(update, _format_brand_profile_summary(summary))


async def brand_profile_versions(update: Any, context: Any) -> None:
    """Display recent immutable personal-brand profile versions."""
    try:
        versions = _orchestrator(context).list_brand_profile_versions(
            database=_database(context),
            limit=10,
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not load personal-brand profile versions.")
        return
    if not versions:
        await _reply(
            update,
            "No personal-brand profile versions exist. Initialize the profile seed first.",
        )
        return
    await _reply(update, _format_brand_profile_versions(versions))


async def activate_brand_profile(update: Any, context: Any) -> None:
    """Activate an immutable profile version by version number."""
    version = _parse_int(_command_payload(update).strip(), "version")
    if version is None:
        await _reply(update, "Usage: /activate_brand_profile <version>")
        return
    try:
        result = _orchestrator(context).activate_brand_profile(
            version=version,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(
            update,
            f"Could not activate personal-brand profile version {version}. Please check the version.",
        )
        return
    await _reply(
        update,
        f"Personal-brand profile version {result['version']} is now active.",
    )


async def set_brand_field(update: Any, context: Any) -> None:
    """Create a new personal-brand version from one supported field edit."""
    raw_payload = _command_payload(update)
    if "|" not in raw_payload:
        await _reply(update, "Usage: /set_brand_field <field> | <value>")
        return
    field_name, value = (part.strip() for part in raw_payload.split("|", 1))
    if not field_name or not value:
        await _reply(update, "Usage: /set_brand_field <field> | <value>")
        return
    try:
        result = _orchestrator(context).update_brand_profile_field(
            field_name=field_name,
            value=value,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(
            update,
            "Could not update that personal-brand field. Check the field name and value.",
        )
        return
    await _reply(
        update,
        f"Created and activated personal-brand profile version {result['version']}.",
    )


async def add_signal_source(update: Any, context: Any) -> None:
    """Create a pending RSS or Atom source through the orchestrator."""
    raw_payload = _command_payload(update)
    if "|" not in raw_payload:
        await _reply(update, "Usage: /add_signal_source <name> | <rss_or_atom_url>")
        return
    name, url = (part.strip() for part in raw_payload.split("|", 1))
    if not name or not url:
        await _reply(update, "Usage: /add_signal_source <name> | <rss_or_atom_url>")
        return
    try:
        source = _orchestrator(context).add_signal_source(
            name=name,
            url=url,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not add that signal source. Check the public feed URL.")
        return
    await _reply(
        update,
        f"Signal source added as pending approval. Source ID: {source['id']}.",
    )


async def signal_sources(update: Any, context: Any) -> None:
    """List stored public feed sources."""
    try:
        sources = _orchestrator(context).list_signal_sources(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load signal sources.")
        return
    if not sources:
        await _reply(update, "No signal sources have been added.")
        return
    await _reply(update, _format_signal_sources(sources))


async def approve_signal_source(update: Any, context: Any) -> None:
    """Approve one source without starting a scan."""
    await _set_signal_source_approval(update, context, "approved")


async def reject_signal_source(update: Any, context: Any) -> None:
    """Reject one source and leave it disabled."""
    await _set_signal_source_approval(update, context, "rejected")


async def enable_signal_source(update: Any, context: Any) -> None:
    """Enable one approved source for future manual scans."""
    await _set_signal_source_enabled(update, context, True)


async def disable_signal_source(update: Any, context: Any) -> None:
    """Disable one source without deleting its audit record."""
    await _set_signal_source_enabled(update, context, False)


async def scan_signal_source(update: Any, context: Any) -> None:
    """Manually fetch and ingest one approved enabled source."""
    source_id = _parse_int(_command_payload(update).strip(), "source_id")
    if source_id is None:
        await _reply(update, "Usage: /scan_signal_source <source_id>")
        return
    try:
        result = _orchestrator(context).scan_signal_source(
            source_id=source_id,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not scan that signal source. Check approval and enabled state.")
        return
    await _reply(update, _format_signal_scan(result))


async def scan_signals(update: Any, context: Any) -> None:
    """Manually scan all approved enabled sources without scheduling."""
    await _reply(update, "Signal scan started. I’ll send the result when it finishes.")
    try:
        result = await _run_bounded_operation(
            context,
            "scan_signals",
            lambda: _orchestrator(context).scan_enabled_signal_sources(
                database=_database(context)
            ),
        )
    except BackgroundOperationBusy:
        await _reply(update, "A signal scan is already running. Please check back shortly.")
        return
    except asyncio.TimeoutError:
        await _reply(update, "Signal scan timed out. Check the logs and try again later.")
        return
    except NetworkOrchestratorError:
        await _reply(update, "Could not scan enabled signal sources.")
        return
    await _reply(
        update,
        "Scanned {sources_scanned} sources. New signals: {new_signals}. "
        "Duplicates: {duplicates}. Failures: {failures}.".format(**result),
    )


async def signals(update: Any, context: Any) -> None:
    """Display recent deterministic signals without relevance scoring."""
    try:
        recent = _orchestrator(context).get_recent_signals(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load stored signals.")
        return
    if not recent:
        await _reply(update, "No signals have been stored yet.")
        return
    await _reply(update, _format_signals(recent))


async def signal(update: Any, context: Any) -> None:
    """Display one attributed signal without downstream content actions."""
    signal_id = _parse_int(_command_payload(update).strip(), "signal_id")
    if signal_id is None:
        await _reply(update, "Usage: /signal <signal_id>")
        return
    try:
        item = _orchestrator(context).get_signal(
            signal_id=signal_id,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, f"Could not find signal id={signal_id}.")
        return
    await _reply(update, _format_signal(item))


async def score_signal(update: Any, context: Any) -> None:
    """Score one stored signal; this command never scans a source."""
    parts = _command_payload(update).strip().split()
    signal_id = _parse_int(parts[0], "signal_id") if parts else None
    if signal_id is None:
        await _reply(update, "Usage: /score_signal <signal_id> [force]")
        return
    try:
        result = _orchestrator(context).score_signal(signal_id=signal_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, f"Could not score signal id={signal_id}. Check the stored signal ID.")
        return
    await _reply(update, _format_scoring_result(result))


async def score_signals(update: Any, context: Any) -> None:
    """Run a bounded scoring pass over existing normalized signals only."""
    parts = _command_payload(update).strip().split()
    force = "force" in parts
    numeric = [part for part in parts if part != "force"]
    limit = 10 if not numeric else _parse_int(numeric[0], "limit")
    if limit is None or limit < 1:
        await _reply(update, "Usage: /score_signals [positive_limit]")
        return
    await _reply(update, "Signal evaluation started. I’ll send the result when it finishes.")
    try:
        result = await _run_bounded_operation(
            context,
            "score_signals",
            lambda: _orchestrator(context).score_recent_signals(
                limit=limit, force=force, database=_database(context)
            ),
        )
    except BackgroundOperationBusy:
        await _reply(update, "Signal evaluation is already running. Please check back shortly.")
        return
    except asyncio.TimeoutError:
        await _reply(update, "Signal evaluation timed out. Check the logs and try again later.")
        return
    except NetworkOrchestratorError:
        await _reply(update, "Could not score stored signals right now.")
        return
    await _reply(update, _format_scoring_run(result))


async def scoring_queue(update: Any, context: Any) -> None:
    """Display the next publication-first candidates without scoring them."""
    payload = _command_payload(update).strip()
    limit = 10 if not payload else _parse_int(payload, "limit")
    if limit is None or limit < 1:
        await _reply(update, "Usage: /scoring_queue [positive_limit]")
        return
    try:
        queue = _orchestrator(context).get_scoring_queue(limit=limit, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load the scoring queue.")
        return
    await _reply(update, "No normalized signals are waiting for evaluation." if not queue else "\n".join(f"#{item['signal_id']} | {item['published_at'] or 'no publication date'} | age {item['age_days'] if item['age_days'] is not None else '?'} days | {item['title']} | {item['queue_reason']}" for item in queue))


async def ranked_signals(update: Any, context: Any) -> None:
    """Show stored scores in review order without creating any draft."""
    try:
        ranked = _orchestrator(context).get_ranked_signals(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load ranked signals.")
        return
    await _reply(update, _format_ranked_signals(ranked) if ranked else "No ranked eligible signals yet.")


async def scoring_diagnostics(update: Any, context: Any) -> None:
    """Show read-only scoring gates and the most common rejection evidence."""
    try:
        diagnostic = _orchestrator(context).get_scoring_diagnostics(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load scoring diagnostics.")
        return
    reasons = diagnostic.get("common_ineligibility_reasons", [])
    reason_text = "None" if not reasons else "; ".join(f"{item['reason']}: {item['count']} (e.g. {', '.join(map(str, item['example_ids']))})" for item in reasons[:3])
    await _reply(update, f"Scoring config v{diagnostic['config_version']}\nFreshness window: {diagnostic['maximum_age_days']} days\nMinimum final score: {diagnostic['minimum_final_score']}\nMinimum credibility: {diagnostic['minimum_credibility_score']}\nMaximum factual risk: {diagnostic['maximum_factual_risk']}\nMaximum generic-content risk: {diagnostic['maximum_generic_commentary_risk']}\nModel-assisted: {diagnostic['model_assisted']}\nLatest evaluations: {diagnostic['latest_counts']}\nCommon reasons: {reason_text}")


async def content_opportunities(update: Any, context: Any) -> None:
    """Show reviewable pre-draft opportunities and their human actions."""
    try:
        opportunities = _orchestrator(context).list_content_opportunities(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load content opportunities.")
        return
    if not opportunities:
        await _reply(update, "No content opportunities yet. Score qualifying stored signals first.")
        return
    for item in opportunities:
        await _reply(update, _format_content_opportunity(item), reply_markup=_opportunity_markup(item["id"]))


async def content_opportunity(update: Any, context: Any) -> None:
    """Show a single opportunity detail without producing a post draft."""
    opportunity_id = _parse_int(_command_payload(update).strip(), "opportunity_id")
    if opportunity_id is None:
        await _reply(update, "Usage: /content_opportunity <opportunity_id>")
        return
    try:
        item = _orchestrator(context).get_content_opportunity(opportunity_id=opportunity_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, f"Could not find content opportunity id={opportunity_id}.")
        return
    await _reply(update, _format_content_opportunity(item, detailed=True), reply_markup=_opportunity_markup(opportunity_id))


async def prepare_content(update: Any, context: Any) -> None:
    """Prepare a review package from a stored opportunity; never publish it."""
    opportunity_id = _parse_int(_command_payload(update).strip(), "opportunity_id")
    if opportunity_id is None:
        await _reply(update, "Usage: /prepare_content <opportunity_id>")
        return
    try:
        post = _orchestrator(context).generate_content_package(opportunity_id=opportunity_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not prepare that content package. Check the opportunity ID and its review state.")
        return
    await _reply(update, _format_content_package(post), reply_markup=_package_markup(post["id"]))


async def content_packages(update: Any, context: Any) -> None:
    """List package-backed drafts awaiting a human decision."""
    try:
        packages = _orchestrator(context).list_pending_content_packages(database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not load content packages.")
        return
    if not packages:
        await _reply(update, "No content packages are awaiting review.")
        return
    await _reply(update, "\n".join(f"#{item['id']}: {item.get('topic') or 'Content package'} | {item['status']} | v{item['package_version']} | image={item['image_source']}" for item in packages))


async def content_package(update: Any, context: Any) -> None:
    """Show one package draft and its review controls."""
    post_id = _parse_int(_command_payload(update).strip(), "post_id")
    if post_id is None:
        await _reply(update, "Usage: /content_package <post_id>")
        return
    try:
        readiness = _orchestrator(context).get_content_publish_readiness(
            post_id=post_id,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not inspect that content post safely.")
        return
    if not readiness["exists"]:
        await _reply(update, f"Content post id={post_id} does not exist.")
        return
    if not readiness["package_backed"]:
        await _reply(
            update,
            f"Post #{post_id} exists, but it is a plain topic draft rather than a "
            "source-grounded content package. Use /content_opportunities to start "
            "the package workflow.",
        )
        return
    try:
        post = _orchestrator(context).get_content_package(post_id=post_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, f"Could not find content package id={post_id}.")
        return
    await _reply(update, _format_content_package(post), reply_markup=_package_markup(post_id))


async def content_sources(update: Any, context: Any) -> None:
    """Display safe stored source attribution for one package."""
    await _show_package_json(update, context, "source_references_json", "Sources")


async def content_claims(update: Any, context: Any) -> None:
    """Display stored factual-claim validation records for one package."""
    await _show_package_json(update, context, "factual_claims_json", "Factual claims")


async def revise_content(update: Any, context: Any) -> None:
    """Route a tightly scoped content revision through the orchestrator."""
    parts = _command_payload(update).split(maxsplit=2)
    post_id = _parse_int(parts[0], "post_id") if parts else None
    if post_id is None or len(parts) < 2:
        await _reply(update, "Usage: /revise_content <post_id> <revision_type> [notes]")
        return
    try:
        post = _orchestrator(context).revise_content_package(post_id=post_id, revision_type=parts[1], database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, "Could not revise that package. Check the ID and revision type.")
        return
    await _reply(update, _format_content_package(post), reply_markup=_package_markup(post_id))


async def _show_package_json(update: Any, context: Any, field: str, label: str) -> None:
    post_id = _parse_int(_command_payload(update).strip(), "post_id")
    if post_id is None:
        await _reply(update, f"Usage: /{'content_sources' if field == 'source_references_json' else 'content_claims'} <post_id>")
        return
    try:
        post = _orchestrator(context).get_content_package(post_id=post_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, f"Could not find content package id={post_id}.")
        return
    await _reply(update, f"{label}:\n{post.get(field) or 'None'}")


async def record_outcome(update: Any, context: Any) -> None:
    """Record an explicit user-reported outcome for refinement."""
    parsed = _parse_record_outcome_payload(_command_payload(update))
    if parsed is None:
        await _reply(
            update,
            "Usage: /record_outcome <outreach|content> <id> <outcome> [notes]",
        )
        return
    target_type, target_id, outcome, notes = parsed
    valid_outcomes = OUTREACH_OUTCOMES if target_type == "outreach" else CONTENT_OUTCOMES
    if outcome not in valid_outcomes:
        await _reply(
            update,
            f"Invalid {target_type} outcome. Use one of: {', '.join(sorted(valid_outcomes))}.",
        )
        return
    try:
        result = _orchestrator(context).record_outcome(
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            notes=notes,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(
            update,
            f"Could not record {target_type} outcome for id={target_id}. Please check the ID.",
        )
        return
    await _reply(
        update,
        (
            f"Outcome recorded for {target_type} id={target_id}: {outcome}. "
            f"Refinement outcome id={result.get('id')}."
        ),
    )


async def suggest_refinements(update: Any, context: Any) -> None:
    """Run report-only refinement suggestions without applying them."""
    try:
        report = _orchestrator(context).suggest_refinements(
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not suggest refinements right now.")
        return
    suggestions = report.get("suggestions", [])
    if not suggestions:
        await _reply(update, _format_refinement_report(report))
        return
    _store_refinement_proposals(context, suggestions)
    await _reply(
        update,
        _format_refinement_report(report),
        reply_markup=_refinement_markup(suggestions),
    )


async def rollback_refinement(update: Any, context: Any) -> None:
    """Rollback one applied refinement by refinement_history id."""
    payload = _command_payload(update).strip()
    refinement_id = _parse_int(payload, "refinement_id")
    if refinement_id is None:
        await _reply(update, "Usage: /rollback_refinement <refinement_id>")
        return
    try:
        result = _orchestrator(context).rollback_refinement(
            refinement_id=refinement_id,
            database=_database(context),
        )
    except NetworkOrchestratorError as exc:
        message = str(exc)
        if "parameter has changed since it was applied" in message:
            await _reply(
                update,
                "This refinement cannot be rolled back automatically because the parameter has changed since it was applied. Please review manually.",
            )
        elif "does not exist" in message:
            await _reply(
                update,
                f"Could not rollback refinement_id={refinement_id}. Please check the refinement ID.",
            )
        elif "Only applied refinements" in message:
            await _reply(update, "Only applied refinements can be rolled back.")
        elif "missing rollback values" in message:
            await _reply(
                update,
                "This refinement is missing rollback values. Please review manually.",
            )
        elif "not refinable" in message:
            await _reply(
                update,
                "Rollback target parameter is not currently refinable. Please review manually.",
            )
        elif "failed validation" in message or "checker" in message:
            await _reply(update, "Rollback failed safety validation. No changes were applied.")
        else:
            await _reply(update, "Could not rollback refinement. No changes were applied.")
        return
    await _reply(
        update,
        (
            f"Rollback applied for {result.get('parameter_name')}. "
            "Restored previous value. Core intent was not changed."
        ),
    )


async def refinement_status(update: Any, context: Any) -> None:
    """Show read-only refinement loop status."""
    try:
        status = _orchestrator(context).get_refinement_status(
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not load refinement status right now.")
        return
    await _reply(update, _format_refinement_status(status))


async def refinement_report(update: Any, context: Any) -> None:
    """Show read-only refinement reporting summary."""
    try:
        report = _orchestrator(context).get_refinement_report(
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not load refinement report right now.")
        return
    await _reply(update, _format_refinement_reporting_summary(report))


async def refinement_history(update: Any, context: Any) -> None:
    """Show recent refinement audit events."""
    try:
        history = _orchestrator(context).get_refinement_history(
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, "Could not load refinement history right now.")
        return
    if not history:
        await _reply(update, "No refinement history yet.")
        return
    await _reply(
        update,
        _format_refinement_history(history),
    )


async def system_check(update: Any, context: Any) -> None:
    """Run operator-only read diagnostics.

    Intentional exception: this diagnostic command calls SystemIntegrityAgent
    directly because it is read-only operator tooling, not product workflow.
    """
    result = SystemIntegrityAgent().run_full_integrity_check(_database(context))
    await _reply(update, _format_system_check(result))


async def button_callback(update: Any, context: Any) -> None:
    """Handle inline approval/discard button callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "linkedin_disconnect_confirm":
        try:
            _orchestrator(context).disconnect_linkedin(database=_database(context))
        except NetworkOrchestratorError:
            await query.edit_message_text("Could not revoke the LinkedIn connection.")
            return
        await query.edit_message_text("LinkedIn connection revoked. Nothing was published.")
        return
    if data.startswith("outreach_manual_sent:") or data.startswith("manual_sent:"):
        callback = _parse_outreach_callback(data)
        if callback is None:
            await query.edit_message_text(
                "Invalid outreach action. Please draft again."
            )
            return
        draft_context = _pop_outreach_draft_context(context, callback["prospect_id"])
        try:
            _orchestrator(context).mark_outreach_sent(
                prospect_id=callback["prospect_id"],
                ask_type=draft_context.get("ask_type"),
                draft_text=draft_context.get("draft_text"),
                source="telegram_button",
                draft_interaction_id=callback.get("interaction_id"),
                database=_database(context),
            )
        except NetworkOrchestratorError:
            await query.edit_message_text(
                f"Could not mark prospect_id={callback['prospect_id']} as manually sent. "
                "Please check the prospect ID."
            )
            return
        await query.edit_message_text(
            "Marked as manually sent on LinkedIn. I'll track this for follow-up."
        )
        return
    if data.startswith("outreach_discard:"):
        interaction_id = _callback_id(data, "outreach_discard")
        if interaction_id is None:
            await query.edit_message_text("Invalid outreach action. Please draft again.")
            return
        try:
            _orchestrator(context).discard_outreach_draft(
                interaction_id=interaction_id,
                database=_database(context),
            )
        except NetworkOrchestratorError:
            await query.edit_message_text(
                "Could not discard that outreach draft. Please draft again."
            )
            return
        await query.edit_message_text("Discarded draft.")
        return
    if data.startswith("post_save:"):
        post_id = _callback_id(data, "post_save")
        if post_id is None:
            await query.edit_message_text("Invalid content draft action. Please draft again.")
            return
        try:
            _orchestrator(context).save_content_draft(
                post_id=post_id,
                database=_database(context),
            )
        except NetworkOrchestratorError:
            await query.edit_message_text(
                "Could not save that content draft. Please draft again."
            )
            return
        await query.edit_message_text("Saved as draft.")
        return
    if data.startswith("post_approve_later:"):
        post_id = _callback_id(data, "post_approve_later")
        if post_id is None:
            await query.edit_message_text("Invalid content draft action. Please draft again.")
            return
        try:
            _orchestrator(context).approve_content_draft_for_later_posting(
                post_id=post_id,
                database=_database(context),
            )
        except NetworkOrchestratorError:
            await query.edit_message_text(
                "This plain draft cannot be approved for LinkedIn publishing. "
                "Create a source-grounded package from /content_opportunities."
            )
            return
        await query.edit_message_text(
            "Content package approved for later posting. Nothing has been published."
        )
        return
    if data.startswith("post_discard:"):
        post_id = _callback_id(data, "post_discard")
        if post_id is None:
            await query.edit_message_text("Invalid content draft action. Please draft again.")
            return
        try:
            _orchestrator(context).discard_content_draft(
                post_id=post_id,
                database=_database(context),
            )
        except NetworkOrchestratorError:
            await query.edit_message_text(
                "Could not discard that content draft. Please draft again."
            )
            return
        await query.edit_message_text("Discarded draft.")
        return
    if data.startswith("package_"):
        await _handle_package_callback(query, context, data)
        return
    if data.startswith("opportunity_"):
        await _handle_opportunity_callback(query, context, data)
        return
    if data.startswith("refinement_apply:"):
        proposal_id = _callback_token(data, "refinement_apply")
        if proposal_id is None:
            await query.edit_message_text("Invalid refinement action. Please suggest again.")
            return
        try:
            _orchestrator(context).apply_refinement_proposal(
                proposal_id=proposal_id,
                database=_database(context),
            )
        except NetworkOrchestratorError as exc:
            message = str(exc)
            if "report-only" in message:
                await query.edit_message_text(
                    "The refinement loop is currently report-only. No changes were applied."
                )
            elif "already applied" in message:
                await query.edit_message_text("This refinement was already applied.")
            elif "already rejected" in message:
                await query.edit_message_text("This refinement was already rejected.")
            elif "stale" in message:
                await query.edit_message_text(
                    "This proposal is stale because the parameter changed. Please run /suggest_refinements again."
                )
            else:
                await query.edit_message_text("Could not apply refinement. No changes were made.")
            return
        await query.edit_message_text("Refinement applied. Core intent was not changed.")
        return
    if data.startswith("refinement_reject:"):
        proposal_id = _callback_token(data, "refinement_reject")
        if proposal_id is None:
            await query.edit_message_text("Invalid refinement action. Please suggest again.")
            return
        try:
            _orchestrator(context).reject_refinement_proposal(
                proposal_id=proposal_id,
                database=_database(context),
            )
        except NetworkOrchestratorError as exc:
            message = str(exc)
            if "already applied" in message:
                await query.edit_message_text("This refinement was already applied.")
            elif "already rejected" in message:
                await query.edit_message_text("This refinement was already rejected.")
            else:
                await query.edit_message_text("Could not reject refinement. No changes were made.")
            return
        await query.edit_message_text("Refinement rejected. No changes were made.")
        return
    if data.startswith("refinement_reason:"):
        proposal_id = _callback_token(data, "refinement_reason")
        if proposal_id is None:
            await query.edit_message_text("Invalid refinement action. Please suggest again.")
            return
        try:
            proposal = _orchestrator(context).get_refinement_reasoning(
                proposal_id=proposal_id,
                database=_database(context),
            )
        except NetworkOrchestratorError:
            await query.edit_message_text("Missing refinement proposal. Please suggest again.")
            return
        await query.edit_message_text(_format_refinement_reasoning(proposal))
        return
    if data == "discard":
        await query.edit_message_text("Invalid draft action. Please draft again.")
        return
    await query.edit_message_text("Invalid draft action. Please draft again.")


async def handle_error(update: Any, context: Any) -> None:
    """Log handler exceptions and send a generic user-safe message."""
    logger.exception("Telegram handler failed", exc_info=context.error)
    if update is not None and getattr(update, "effective_message", None) is not None:
        await update.effective_message.reply_text(
            "Something went wrong, please try again"
        )


def _orchestrator(context: Any) -> Any:
    app = getattr(context, "application", None)
    bot_data = getattr(app, "bot_data", {}) if app is not None else {}
    return bot_data.get("orchestrator") or NetworkOrchestrator()


def _bot_data(context: Any) -> dict[str, Any]:
    app = getattr(context, "application", None)
    bot_data = getattr(app, "bot_data", None) if app is not None else None
    if isinstance(bot_data, dict):
        return bot_data
    return {}


def _database(context: Any) -> str:
    bot_data = _bot_data(context)
    return str(bot_data.get("database_path") or settings.database_path)


def _command_payload(update: Any) -> str:
    text = getattr(update.effective_message, "text", "") or ""
    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) == 2 else ""


async def _reply(
    update: Any,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    await update.effective_message.reply_text(text, reply_markup=reply_markup)


class BackgroundOperationBusy(RuntimeError):
    """Raised when the bounded Telegram background-work pool is full."""


async def _run_bounded_operation(context: Any, name: str, operation: Any) -> Any:
    """Run blocking orchestration off the Telegram event loop with bounds."""
    active = context.application.bot_data.setdefault("background_operations", set())
    if name in active or len(active) >= settings.max_background_operations:
        raise BackgroundOperationBusy("A similar operation is already running.")
    active.add(name)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(operation),
            timeout=settings.background_operation_timeout_seconds,
        )
    finally:
        active.discard(name)


def _none_if_empty(value: str) -> str | None:
    return value or None


def _parse_int(value: str, field_name: str) -> int | None:
    _ = field_name
    try:
        return int(value)
    except ValueError:
        return None


def _parse_record_outcome_payload(
    payload: str,
) -> tuple[str, int, str, str | None] | None:
    try:
        parts = shlex.split(payload)
    except ValueError:
        return None
    if len(parts) < 3:
        return None
    target_type = parts[0]
    if target_type not in {"outreach", "content"}:
        return None
    target_id = _parse_int(parts[1], "target_id")
    if target_id is None:
        return None
    notes = " ".join(parts[3:]).strip() or None
    return target_type, target_id, parts[2], notes


def _format_outreach_draft(result: dict[str, Any]) -> str:
    draft = result["draft"]
    lines = [
        "Draft:",
        str(draft.get("draft_text", "")),
        f"Characters: {draft.get('character_count', len(str(draft.get('draft_text', ''))))}",
    ]
    warning = result.get("context_warning")
    if warning:
        lines.extend(
            [
                "",
                "Context warning:",
                str(warning.get("recommendation", warning)),
            ]
        )
    return "\n".join(lines)


def _format_brand_profile_summary(summary: dict[str, Any]) -> str:
    fields = [
        ("Professional identity", summary.get("professional_identity")),
        ("Current program", summary.get("current_program")),
        ("Institutions", summary.get("institutions")),
        ("Career focus", summary.get("career_focus")),
        ("Content pillars", summary.get("content_pillars")),
        ("Target audiences", summary.get("target_audiences")),
        ("Preferred tone", summary.get("preferred_tone")),
        ("Preferred depth", summary.get("preferred_depth")),
        ("Humor boundaries", summary.get("humor_preferences")),
        (
            "Personal-claim safeguards",
            summary.get("claims_requiring_confirmation"),
        ),
        ("Topics to avoid", summary.get("topics_to_avoid")),
        ("Networking goals", summary.get("networking_goals")),
    ]
    lines = [f"Personal-brand profile v{summary.get('version')} (active)"]
    for label, value in fields:
        if isinstance(value, list) and value:
            lines.append(f"{label}: {', '.join(str(item) for item in value)}")
        elif isinstance(value, str) and value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _format_brand_profile_versions(versions: list[dict[str, Any]]) -> str:
    lines = ["Personal-brand profile versions:"]
    for profile in versions:
        marker = " active" if profile.get("is_active") else ""
        lines.append(
            "v{version} (id={id}){marker} created={created} activated={activated}".format(
                version=profile.get("version"),
                id=profile.get("id"),
                marker=marker,
                created=profile.get("created_at"),
                activated=profile.get("activated_at") or "-",
            )
        )
    return "\n".join(lines)


async def _set_signal_source_approval(update: Any, context: Any, status: str) -> None:
    source_id = _parse_int(_command_payload(update).strip(), "source_id")
    command = "approve" if status == "approved" else "reject"
    if source_id is None:
        await _reply(update, f"Usage: /{command}_signal_source <source_id>")
        return
    try:
        method = (
            _orchestrator(context).approve_signal_source
            if status == "approved"
            else _orchestrator(context).reject_signal_source
        )
        source = method(source_id=source_id, database=_database(context))
    except NetworkOrchestratorError:
        await _reply(update, f"Could not {command} signal source id={source_id}.")
        return
    await _reply(update, f"Signal source {source['id']} is {source['approval_status']}.")


async def _set_signal_source_enabled(update: Any, context: Any, enabled: bool) -> None:
    source_id = _parse_int(_command_payload(update).strip(), "source_id")
    command = "enable" if enabled else "disable"
    if source_id is None:
        await _reply(update, f"Usage: /{command}_signal_source <source_id>")
        return
    try:
        source = _orchestrator(context).set_signal_source_enabled(
            source_id=source_id,
            enabled=enabled,
            database=_database(context),
        )
    except NetworkOrchestratorError:
        await _reply(update, f"Could not {command} signal source id={source_id}.")
        return
    state = "enabled" if source["enabled"] else "disabled"
    await _reply(update, f"Signal source {source['id']} is {state}.")


def _format_signal_sources(sources: list[dict[str, Any]]) -> str:
    lines = ["Signal sources:"]
    for source in sources:
        lines.append(
            "{id}: {name} [{source_type}] {approval} enabled={enabled} "
            "last_fetch={last_fetch}".format(
                id=source.get("id"),
                name=source.get("name"),
                source_type=source.get("source_type"),
                approval=source.get("approval_status"),
                enabled=source.get("enabled"),
                last_fetch=source.get("last_fetch_status") or "-",
            )
        )
    return "\n".join(lines)


def _format_signal_scan(result: dict[str, Any]) -> str:
    lines = [
        f"Signal scan status: {result.get('status')}",
        f"Items fetched: {result.get('items_fetched')}",
        f"New signals: {result.get('new_signals')}",
        f"Duplicates: {result.get('duplicates')}",
        f"Failures: {result.get('failures')}",
    ]
    if result.get("not_modified"):
        lines.append("Feed was not modified since the prior scan.")
    if result.get("warnings"):
        lines.append(f"Warnings: {', '.join(result['warnings'])}")
    if result.get("errors"):
        lines.append(f"Errors: {', '.join(result['errors'])}")
    return "\n".join(lines)


def _format_signals(signals: list[dict[str, Any]]) -> str:
    lines = ["Recent signals:"]
    for item in signals:
        lines.append(
            "{id}: {title} | {source} | {published} | {status}".format(
                id=item.get("id"),
                title=item.get("title") or "Untitled",
                source=item.get("source_name"),
                published=item.get("published_at") or "date unavailable",
                status=item.get("status"),
            )
        )
    return "\n".join(lines)


def _format_signal(item: dict[str, Any]) -> str:
    lines = [
        f"Signal {item.get('id')}: {item.get('title') or 'Untitled'}",
        f"Source: {item.get('source_name')}",
        f"Author: {item.get('author') or '-'}",
        f"Published: {item.get('published_at') or '-'}",
        f"Status: {item.get('status')}",
    ]
    if item.get("summary"):
        lines.append(f"Summary: {item['summary']}")
    if item.get("canonical_url"):
        lines.append(f"URL: {item['canonical_url']}")
    if item.get("duplicate_of_id"):
        lines.append(f"Duplicate of signal: {item['duplicate_of_id']}")
    return "\n".join(lines)


def _format_scoring_result(result: dict[str, Any]) -> str:
    if not result.get("eligible"):
        return "\n".join([
            f"Signal {result.get('signal_id')}: {result.get('title') or 'Untitled'} is ineligible.",
            f"Reasons: {'; '.join(result.get('reasons', []))}",
            f"Publication date: {result.get('published_at') or 'unknown'} | Age: {result.get('age_days') if result.get('age_days') is not None else 'unknown'} days | Freshness limit: {result.get('freshness_threshold_days')} days",
            f"Credibility: {result.get('credibility_score', 0):.0f}/100 (minimum {result.get('minimum_credibility_score')})",
            f"Profile matches: {', '.join(result.get('profile_matches', [])) or 'none'}",
            "No model call was made.",
            "No opportunity was created.",
        ])
    score = result.get("score", {})
    deterministic = score.get("deterministic", {})
    return "\n".join([
        f"Signal: {result.get('title') or result.get('signal_id')}",
        "Eligibility: eligible",
        f"Final score: {score.get('final_score', 0):.1f}/100",
        f"Confidence: {score.get('confidence', 0):.2f}",
        f"Positive factors: topic {deterministic.get('topic_relevance', 0):.0f}, credibility {deterministic.get('credibility', 0):.0f}",
        f"Penalties: factual risk {deterministic.get('factual_risk', 0):.0f}, generic risk {deterministic.get('generic_commentary_risk', 0):.0f}",
        f"Scoring mode: {result.get('mode')}",
        "No post has been drafted yet.",
    ])


def _format_scoring_run(result: dict[str, Any]) -> str:
    text = ("Signal evaluation complete. Considered: {considered}. Eligible: {eligible}. "
            "Ineligible: {ineligible}. Evaluated: {evaluated}. Ranked: {ranked}. "
            "Opportunities: {opportunities_created}. Skipped already evaluated: {skipped_already_evaluated}. Failures: {failures}.").format(**result)
    if result.get("selected_publication_oldest"):
        text += f"\nSelected publication range: {result['selected_publication_oldest']} to {result['selected_publication_newest']}"
    reasons = result.get("ineligibility_summary", [])
    if reasons:
        text += "\nIneligibility summary: " + "; ".join(f"{item['reason']}: {item['count']} (e.g. {', '.join(map(str, item['example_ids']))})" for item in reasons[:3])
    return text


def _format_ranked_signals(items: list[dict[str, Any]]) -> str:
    lines = ["Ranked signals:"]
    for item in items:
        reasons = _json_list(item.get("eligibility_reasons_json"))
        reason = reasons[0] if reasons else "scored against active brand profile"
        lines.append(f"{item.get('id')}: {item.get('title') or 'Untitled'} | {item.get('source_name')} | {item.get('total_score', 0):.1f} | {item.get('eligibility_status')} | {reason}")
    return "\n".join(lines)


def _format_content_opportunity(item: dict[str, Any], detailed: bool = False) -> str:
    references = _json_list(item.get("source_references_json"))
    lines = [
        f"Opportunity {item.get('id')}: {item.get('headline')}",
        f"Angle: {item.get('suggested_angle')}",
        f"Why it fits: {item.get('rationale')}",
        f"Audience: {item.get('target_audience')}",
        f"Score: {item.get('total_score', 0):.1f}/100 | Risk: factual {item.get('factual_risk', 0):.0f}, generic {item.get('generic_commentary_risk', 0):.0f}",
        f"Sources: {len(references)} | Status: {item.get('status')}",
    ]
    if detailed:
        lines.extend([
            f"Format: {item.get('recommended_format')}",
            f"Treatment: {item.get('suggested_treatment')}",
            f"Confidence: {item.get('confidence', 0):.2f}",
            "No post has been drafted yet.",
        ])
    return "\n".join(lines)


def _format_content_package(post: dict[str, Any]) -> str:
    hooks = _json_list(post.get("alternative_hooks_json"))
    claims = _json_list(post.get("factual_claims_json"))
    return "\n".join([
        f"Content package #{post.get('id')} | {post.get('status')} | v{post.get('package_version')}",
        post.get("draft_text") or "",
        "Alternative hooks: " + "; ".join(str(hook.get("text", "")) for hook in hooks),
        f"Unresolved claims: {sum(bool(item.get('confirmation_required')) for item in claims if isinstance(item, dict))}",
        f"Image: {post.get('image_source')} | Alt text: {post.get('image_alt_text') or '-'}",
        "Nothing has been published.",
    ])


def _format_publish_preview(result: dict[str, Any]) -> str:
    assets = result.get("assets", [])
    asset_lines = [
        f"- {asset.get('filename')} | sha256 {str(asset.get('sha256', ''))[:12]} | {asset.get('mime_type')}"
        for asset in assets
    ]
    return "\n".join([
        "REAL LINKEDIN PUBLISH PREVIEW",
        f"Request: {result['request_id']}",
        f"Package: {result['post_id']}, version {result['package_version']}",
        f"Format: {result['format']}",
        f"Visibility: {result['visibility']}",
        "Complete commentary:",
        result.get("commentary") or "",
        "Assets:",
        *(asset_lines or ["- none"]),
        f"Payload fingerprint: {result['payload_fingerprint']}",
        f"Expires: {result['expires_at']}",
        f"Confirm with /confirm_publish {result['request_id']}",
        "Warning: in real mode, confirmation publishes immediately. Preview creation itself contacted no provider.",
    ])


def _format_publish_request(result: dict[str, Any]) -> str:
    lines = [
        f"Request #{result['request_id']} | {result['status']}",
        f"Package {result['post_id']} v{result['package_version']} | {result['format']}",
        f"Assets: {len(result.get('assets', []))} | Provider assets: {len(result.get('provider_asset_urns', []))}",
        f"Post ID: {result.get('provider_post_id') or '-'}",
    ]
    if result.get("safe_error_summary"):
        lines.append(f"Safe failure: {result['safe_error_summary']}")
    return "\n".join(lines)


def _package_markup(post_id: Any) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Save Draft", callback_data=f"package_save:{post_id}"), InlineKeyboardButton("Approve for Later Posting", callback_data=f"package_approve:{post_id}"), InlineKeyboardButton("Reject", callback_data=f"package_reject:{post_id}")],
        [InlineKeyboardButton("View Sources", callback_data=f"package_sources:{post_id}"), InlineKeyboardButton("View Claims", callback_data=f"package_claims:{post_id}"), InlineKeyboardButton("Make More Personal", callback_data=f"package_personal:{post_id}")],
        [InlineKeyboardButton("Make More Analytical", callback_data=f"package_analytical:{post_id}"), InlineKeyboardButton("Make More Concise", callback_data=f"package_concise:{post_id}"), InlineKeyboardButton("Make Funnier", callback_data=f"package_funny:{post_id}")],
    ])


async def _handle_package_callback(query: Any, context: Any, data: str) -> None:
    parts = data.split(":", 1)
    post_id = _parse_int(parts[1], "post_id") if len(parts) == 2 else None
    if post_id is None:
        await query.edit_message_text("Invalid or stale content package action.")
        return
    action = parts[0]
    try:
        orchestrator = _orchestrator(context)
        if action == "package_save":
            orchestrator.save_content_draft(post_id=post_id, database=_database(context))
            message = "Content package saved. Nothing has been published."
        elif action == "package_approve":
            result = orchestrator.approve_content_package_for_later(
                post_id=post_id, database=_database(context)
            )
            message = result["message"]
        elif action == "package_reject":
            orchestrator.reject_content_package(post_id=post_id, database=_database(context))
            message = "Content package rejected. Nothing has been published."
        elif action in {"package_personal", "package_analytical", "package_concise", "package_funny"}:
            revision = {"package_personal": "make_more_personal", "package_analytical": "make_more_analytical", "package_concise": "make_more_concise", "package_funny": "make_funnier"}[action]
            post = orchestrator.revise_content_package(
                post_id=post_id, revision_type=revision, database=_database(context)
            )
            await query.edit_message_text(_format_content_package(post))
            return
        elif action in {"package_sources", "package_claims"}:
            post = orchestrator.get_content_package(
                post_id=post_id, database=_database(context)
            )
            field = (
                "source_references_json"
                if action == "package_sources"
                else "factual_claims_json"
            )
            await query.edit_message_text(post.get(field) or "None")
            return
        else:
            await query.edit_message_text("Invalid or stale content package action.")
            return
    except NetworkOrchestratorError:
        await query.edit_message_text("That content package is unavailable or cannot make that transition.")
        return
    await query.edit_message_text(message)


async def _handle_opportunity_callback(query: Any, context: Any, data: str) -> None:
    """Route one pre-draft opportunity action through the orchestrator."""
    parts = data.split(":", 1)
    opportunity_id = _parse_int(parts[1], "opportunity_id") if len(parts) == 2 else None
    if opportunity_id is None:
        await query.edit_message_text("Invalid or stale content opportunity action.")
        return
    action = parts[0]
    try:
        orchestrator = _orchestrator(context)
        if action == "opportunity_view":
            item = orchestrator.get_content_opportunity(opportunity_id=opportunity_id, database=_database(context))
            await query.edit_message_text(_format_content_opportunity(item, detailed=True))
            return
        if action == "opportunity_save":
            orchestrator.save_content_opportunity(opportunity_id=opportunity_id, database=_database(context))
            message = "Content opportunity saved for review. No post was drafted."
        elif action == "opportunity_select":
            orchestrator.select_content_opportunity(opportunity_id=opportunity_id, database=_database(context))
            message = "Content opportunity selected for a future approved drafting phase. No post was drafted."
        elif action == "opportunity_dismiss":
            orchestrator.dismiss_content_opportunity(opportunity_id=opportunity_id, database=_database(context))
            message = "Content opportunity dismissed."
        elif action == "opportunity_more":
            orchestrator.record_opportunity_preference(opportunity_id=opportunity_id, feedback_type="more_like_this", database=_database(context))
            message = "Preference saved: more like this."
        elif action == "opportunity_less":
            orchestrator.record_opportunity_preference(opportunity_id=opportunity_id, feedback_type="less_like_this", database=_database(context))
            message = "Preference saved: less like this."
        elif action == "opportunity_sources":
            item = orchestrator.get_content_opportunity(opportunity_id=opportunity_id, database=_database(context))
            await query.edit_message_text("Sources:\n" + "\n".join(str(ref) for ref in _json_list(item.get("source_references_json"))))
            return
        else:
            await query.edit_message_text("Invalid or stale content opportunity action.")
            return
    except NetworkOrchestratorError:
        await query.edit_message_text("That content opportunity is no longer available. Please refresh the list.")
        return
    await query.edit_message_text(message)


def _opportunity_markup(opportunity_id: Any) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View", callback_data=f"opportunity_view:{opportunity_id}"), InlineKeyboardButton("Save", callback_data=f"opportunity_save:{opportunity_id}"), InlineKeyboardButton("Select", callback_data=f"opportunity_select:{opportunity_id}")],
        [InlineKeyboardButton("Dismiss", callback_data=f"opportunity_dismiss:{opportunity_id}"), InlineKeyboardButton("More Like This", callback_data=f"opportunity_more:{opportunity_id}"), InlineKeyboardButton("Less Like This", callback_data=f"opportunity_less:{opportunity_id}")],
        [InlineKeyboardButton("Show Sources", callback_data=f"opportunity_sources:{opportunity_id}")],
    ])


def _json_list(raw: Any) -> list[Any]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _outreach_approval_markup(
    prospect_id: int,
    interaction_id: Any,
) -> InlineKeyboardMarkup:
    manual_callback = (
        f"outreach_manual_sent:{prospect_id}:{interaction_id}"
        if interaction_id is not None
        else f"manual_sent:{prospect_id}"
    )
    discard_callback = (
        f"outreach_discard:{interaction_id}"
        if interaction_id is not None
        else "discard"
    )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Mark as Manually Sent",
                    callback_data=manual_callback,
                ),
                InlineKeyboardButton("Discard Draft", callback_data=discard_callback),
            ]
        ]
    )


def _store_outreach_draft_context(
    context: Any,
    *,
    prospect_id: int,
    interaction_id: Any,
    ask_type: str | None,
    draft_text: str | None,
) -> None:
    bot_data = _bot_data(context)
    drafts = bot_data.setdefault("outreach_drafts", {})
    drafts[str(prospect_id)] = {
        "interaction_id": str(interaction_id) if interaction_id is not None else None,
        "ask_type": ask_type,
        "draft_text": draft_text,
    }


def _pop_outreach_draft_context(context: Any, prospect_id: int) -> dict[str, str | None]:
    drafts = _bot_data(context).get("outreach_drafts", {})
    if not isinstance(drafts, dict):
        return {}
    draft_context = drafts.pop(str(prospect_id), {})
    if not isinstance(draft_context, dict):
        return {}
    return {
        "ask_type": draft_context.get("ask_type"),
        "draft_text": draft_context.get("draft_text"),
    }


def _callback_prospect_id(data: str) -> int | None:
    try:
        prefix, prospect_id_text = data.split(":", 1)
    except ValueError:
        return None
    if prefix != "manual_sent":
        return None
    return _parse_int(prospect_id_text, "prospect_id")


def _parse_outreach_callback(data: str) -> dict[str, int] | None:
    if data.startswith("manual_sent:"):
        prospect_id = _callback_prospect_id(data)
        return {"prospect_id": prospect_id} if prospect_id is not None else None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "outreach_manual_sent":
        return None
    prospect_id = _parse_int(parts[1], "prospect_id")
    interaction_id = _parse_int(parts[2], "interaction_id")
    if prospect_id is None or interaction_id is None:
        return None
    return {"prospect_id": prospect_id, "interaction_id": interaction_id}


def _callback_id(data: str, expected_prefix: str) -> int | None:
    try:
        prefix, raw_id = data.split(":", 1)
    except ValueError:
        return None
    if prefix != expected_prefix:
        return None
    return _parse_int(raw_id, "callback_id")


def _callback_token(data: str, expected_prefix: str) -> str | None:
    try:
        prefix, raw_value = data.split(":", 1)
    except ValueError:
        return None
    if prefix != expected_prefix or not raw_value:
        return None
    return raw_value


def _store_refinement_proposals(
    context: Any,
    suggestions: list[dict[str, Any]],
) -> None:
    proposals = {}
    for index, proposal in enumerate(suggestions, start=1):
        proposals[str(index)] = proposal
    _bot_data(context)["refinement_proposals"] = proposals


def _get_refinement_proposal(context: Any, proposal_id: int) -> dict[str, Any] | None:
    proposals = _bot_data(context).get("refinement_proposals", {})
    if not isinstance(proposals, dict):
        return None
    proposal = proposals.get(str(proposal_id))
    return proposal if isinstance(proposal, dict) else None


def _post_approval_markup(post_id: Any) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Save Draft", callback_data=f"post_save:{post_id}"),
                InlineKeyboardButton("Discard Draft", callback_data=f"post_discard:{post_id}"),
            ]
        ]
    )


def _refinement_markup(suggestions: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for index, suggestion in enumerate(suggestions, start=1):
        if suggestion.get("status") != "pending_approval":
            continue
        proposal_id = suggestion.get("proposal_id")
        if not proposal_id:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    f"Apply Refinement {index}",
                    callback_data=f"refinement_apply:{proposal_id}",
                ),
                InlineKeyboardButton(
                    "Reject Refinement",
                    callback_data=f"refinement_reject:{proposal_id}",
                ),
                InlineKeyboardButton(
                    "View Reasoning",
                    callback_data=f"refinement_reason:{proposal_id}",
                ),
            ]
        )
    return InlineKeyboardMarkup(rows)


def _store_pending_content_image(
    context: Any,
    *,
    image_path: str,
    caption: str | None,
) -> None:
    _bot_data(context)["pending_content_image"] = {
        "image_path": image_path,
        "caption": caption,
    }


def _pop_pending_content_image(context: Any) -> dict[str, Any]:
    pending = _bot_data(context).pop("pending_content_image", {})
    if isinstance(pending, dict):
        return pending
    return {}


def _generate_image_enabled(context: Any) -> bool:
    bot_data = _bot_data(context)
    if "generate_image_for_draft_posts" in bot_data:
        return bool(bot_data["generate_image_for_draft_posts"])
    return settings.generate_image_for_draft_posts


def _format_post_draft_response(post: Any) -> str:
    image_source = _get_value(post, "image_source")
    if image_source == "uploaded":
        prefix = "Here's a LinkedIn post draft based on your uploaded image."
    elif image_source == "generated":
        prefix = "Here's a LinkedIn post draft with a suggested/generated image concept."
    else:
        prefix = "Here's a LinkedIn post draft."
    return f"{prefix}\n\nDraft post #{_get_value(post, 'id')}:\n{_get_value(post, 'draft_text')}"


def _format_briefing_result(result: dict[str, Any]) -> str:
    """Keep manual briefing feedback concise and decision-oriented."""
    scan = result.get("scan", {})
    scoring = result.get("scoring", {})
    return (
        f"Manual briefing #{result.get('run_id')}: {result.get('status')}.\n"
        f"Sources scanned: {scan.get('sources_scanned', 0)}. New signals: {scan.get('new_signals', 0)}.\n"
        f"Signals scored: {scoring.get('scored', 0)}. Packages prepared: {len(result.get('packages', []))}.\n"
        f"Follow-ups due: {len(result.get('followups', []))}.\n"
        f"Dry run: {result.get('dry_run', False)}. Nothing has been published."
    )


def _format_due_line(item: dict[str, Any]) -> str:
    last_touch = item.get("last_touch_date")
    days = "never" if not last_touch else f"{_days_since(str(last_touch))} days"
    return f"{item.get('name')} (id={item.get('prospect_id')}): last touch {days}"


def _format_pending_drafts(
    outreach: list[dict[str, Any]],
    content: list[dict[str, Any]],
) -> list[str]:
    lines = ["Pending drafts:"]
    if outreach:
        lines.append("")
        lines.append("Outreach drafts:")
        for draft in outreach:
            ask_type = draft.get("ask_type") or draft.get("interaction_type")
            lines.append(
                "- "
                f"#{draft.get('id')} "
                f"{draft.get('prospect_name')} "
                f"(prospect_id={draft.get('prospect_id')}): "
                f"{ask_type}, "
                f"status={draft.get('status')}, "
                f"created={draft.get('created_at')}"
            )
    if content:
        lines.append("")
        lines.append("Content drafts:")
        for draft in content:
            topic = draft.get("topic") or "Untitled topic"
            lines.append(
                "- "
                f"#{draft.get('id')} "
                f"{topic}: "
                f"image={draft.get('image_source')}, "
                f"status={draft.get('status')}, "
                f"created={draft.get('created_at')}"
            )
    return lines


def _format_refinement_suggestions(suggestions: list[dict[str, Any]]) -> str:
    lines = ["Suggested refinements:"]
    for index, suggestion in enumerate(suggestions, start=1):
        if suggestion.get("status") == "cap_reached":
            lines.append(
                f"{index}. {suggestion.get('agent_name')}: iteration cap reached; human review required."
            )
            continue
        proposed = suggestion.get("proposed_parameters", {})
        lines.append(
            f"{index}. {suggestion.get('agent_name')} "
            f"v{suggestion.get('current_version')} -> v{suggestion.get('proposed_version')}: "
            f"{proposed} "
            f"risk={suggestion.get('risk_level')}"
        )
    return "\n".join(lines)


def _format_refinement_report(report: dict[str, Any]) -> str:
    lines = [
        "Refinement loop report",
        "Refinements are not applied unless you tap Apply.",
        f"Run id: {report.get('run_id')}",
        f"Status: {report.get('status')}",
        f"Mode: {report.get('mode')}",
    ]
    message = report.get("message")
    if message and message != "Report-only. No changes have been applied.":
        lines.append(str(message))
    suggestions = report.get("suggestions", [])
    if not suggestions:
        lines.append("No checker-approved proposals to show.")
        return "\n".join(lines)
    lines.append("Suggestions:")
    for index, suggestion in enumerate(suggestions, start=1):
        checker = suggestion.get("checker", {})
        evidence = suggestion.get("evidence", [])
        lines.extend(
            [
                f"{index}. Target area: {suggestion.get('target_area')}",
                f"Parameter: {suggestion.get('parameter_name')}",
                f"Current: {suggestion.get('current_value')}",
                f"Proposed: {suggestion.get('proposed_value')}",
                f"Reason: {suggestion.get('reason')}",
                f"Evidence/outcomes used: {len(evidence) if isinstance(evidence, list) else 0}",
                f"Risk: {checker.get('risk_level')}",
                f"Checker: {checker.get('status')}",
            ]
        )
    return "\n".join(lines)


def _format_refinement_reasoning(proposal: dict[str, Any]) -> str:
    core_check = proposal.get("core_intent_check", proposal.get("checker", {}))
    evidence = proposal.get("evidence", [])
    return "\n".join(
        [
            "Refinement reasoning:",
            f"Agent: {proposal.get('agent_name', proposal.get('target_area'))}",
            f"Reason: {proposal.get('rationale', proposal.get('reason'))}",
            f"Evidence count: {len(evidence) if isinstance(evidence, list) else 0}",
            f"Checker passed: {core_check.get('passed')}",
            f"Checker note: {core_check.get('reason', core_check.get('warning'))}",
        ]
    )


def _format_refinement_status(status: dict[str, Any]) -> str:
    recent_run = status.get("recent_run") or {}
    return "\n".join(
        [
            "Refinement status",
            f"Mode: {status.get('mode')}",
            f"Paused: {status.get('loop_paused')}",
            f"Max proposals/run: {status.get('max_proposals_per_run')}",
            f"Max applies/run: {status.get('max_apply_per_run')}",
            f"Recent run: {recent_run.get('status', 'none')}",
            f"Pending proposals: {status.get('pending_proposals_count')}",
            f"Applied refinements: {status.get('applied_refinements_count')}",
            f"Rejected refinements: {status.get('rejected_refinements_count')}",
            f"Failed validation: {status.get('failed_validation_count')}",
        ]
    )


def _format_refinement_reporting_summary(report: dict[str, Any]) -> str:
    pending = report.get("pending_proposals", [])
    outcomes = report.get("recent_outcomes", [])
    proposal_counts = report.get("proposal_counts", {})
    event_counts = report.get("event_counts", {})
    lines = [
        "Refinement report",
        str(report.get("message", "This is a report only. No changes were applied.")),
        f"Recent outcomes: {len(outcomes)}",
        f"Recent proposals: {len(report.get('recent_proposals', []))}",
        f"Pending proposals: {proposal_counts.get('pending_approval', 0)}",
        f"Applied: {event_counts.get('proposal_applied', 0)}",
        f"Rejected: {event_counts.get('proposal_rejected', 0)}",
        f"Rollbacks applied: {report.get('rollbacks_applied_count', 0)}",
    ]
    failed_reasons = report.get("common_failed_validation_reasons", [])
    if failed_reasons:
        lines.append("Failed validation reasons:")
        for reason in failed_reasons[:3]:
            lines.append(f"- {reason.get('reason')}: {reason.get('count')}")
    else:
        lines.append("Failed validation reasons: none")
    if pending:
        lines.append("Pending proposals:")
        for proposal in pending[:5]:
            lines.append(
                "- "
                f"{proposal.get('proposal_id')} "
                f"{proposal.get('target_area')} "
                f"{proposal.get('parameter_name')} -> {proposal.get('proposed_value')} "
                f"risk={proposal.get('risk_level')} "
                f"checker={proposal.get('checker_status')} "
                f"created={proposal.get('created_at')}"
            )
    else:
        lines.append("Pending proposals: none")
    lines.append("Current parameters:")
    parameters = report.get("current_parameters", {})
    for agent_name, values in parameters.items():
        lines.append(f"- {agent_name}: {values}")
    lines.append(f"Recommended next action: {report.get('recommended_next_action')}")
    return "\n".join(lines)


def _format_refinement_history(history: list[dict[str, Any]]) -> str:
    lines = ["Recent refinement history:"]
    for event in history:
        old_value = event.get("old_value")
        new_value = event.get("new_value")
        if old_value is None and new_value is None:
            change_text = "no value change"
        else:
            change_text = f"{old_value} -> {new_value}"
        lines.append(
            "#"
            f"{event.get('refinement_id')} "
            f"{event.get('event_type')} "
            f"{event.get('parameter_name') or 'unknown_parameter'}: "
            f"{change_text} "
            f"status={event.get('status')} "
            f"at {event.get('created_at')}"
        )
        if event.get("rollback_from_refinement_id") is not None:
            lines[-1] += f" rollback_from=#{event.get('rollback_from_refinement_id')}"
    return "\n".join(lines)


def _days_since(iso_value: str) -> int:
    parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (datetime.now(UTC) - parsed.astimezone(UTC)).days


def _is_valid_date(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except ValueError:
        return False


def _is_valid_time(value: str) -> bool:
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M") == value
    except ValueError:
        return False


def _get_value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key)


def _photo_topic(update: Any) -> str | None:
    message = update.effective_message
    if getattr(message, "caption", None):
        return str(message.caption).strip()
    reply_to = getattr(message, "reply_to_message", None)
    if reply_to is None:
        return None
    text = getattr(reply_to, "text", "") or ""
    if text.startswith("/draft_post"):
        topic = text.split(maxsplit=1)
        return topic[1].strip() if len(topic) == 2 else None
    return text.strip() or None


async def _save_largest_photo(update: Any) -> str:
    PHOTO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    photo = update.effective_message.photo[-1]
    file_unique_id = getattr(photo, "file_unique_id", "uploaded-photo")
    destination = PHOTO_UPLOAD_DIR / f"{file_unique_id}.jpg"
    telegram_file = await photo.get_file()
    await telegram_file.download_to_drive(str(destination))
    return str(destination)


def _format_system_check(result: dict[str, Any]) -> str:
    lines = [
        f"System check: {result.get('overall_status', 'PASS')} "
        f"(overall_passed={result['overall_passed']})"
    ]
    for check in result["checks"]:
        if check.get("violations"):
            lines.append(f"{check['check']}: violations={check['violations']}")
        for note in check.get("notes", []):
            lines.append(f"{check['check']}: {note}")
    if len(lines) == 1:
        lines.append("No violations found.")
    return "\n".join(lines)
