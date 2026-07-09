"""Thin Telegram command handlers for Network Growth Agent."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agents.orchestrator import NetworkOrchestrator
from agents.system_integrity_agent import SystemIntegrityAgent
from config.settings import settings


logger = logging.getLogger(__name__)
ALLOWED_ASK_TYPES = {"resume_review", "career_guidance", "general_chat"}
PHOTO_UPLOAD_DIR = Path("/tmp/network-agent-telegram-photos")


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
                "/system_check",
            ]
        ),
    )


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

    result = _orchestrator(context).draft_outreach(
        prospect_id=prospect_id,
        ask_type=ask_type,
        database=_database(context),
    )
    await _reply(
        update,
        _format_outreach_draft(result),
        reply_markup=_outreach_approval_markup(prospect_id),
    )


async def draft_followup(update: Any, context: Any) -> None:
    """Draft a LinkedIn follow-up for manual sending."""
    prospect_id = _parse_int(_command_payload(update).strip(), "prospect_id")
    if prospect_id is None:
        await _reply(update, "Usage: /draft_followup <prospect_id>")
        return

    result = _orchestrator(context).draft_followup(
        prospect_id=prospect_id,
        database=_database(context),
    )
    await _reply(
        update,
        _format_outreach_draft(result),
        reply_markup=_outreach_approval_markup(prospect_id),
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

    result = _orchestrator(context).confirm_meeting(
        prospect_id=prospect_id,
        meeting_date=parts[1],
        start_time=parts[2],
        end_time=parts[3] if len(parts) == 4 else None,
        database=_database(context),
    )
    await _reply(
        update,
        f"Meeting confirmed for prospect {prospect_id}. calendar_synced={result['calendar_synced']}",
    )


async def draft_post(update: Any, context: Any) -> None:
    """Draft a content post without image unless a photo reply is used."""
    topic = _command_payload(update).strip()
    if not topic:
        await _reply(update, "Usage: /draft_post <topic>")
        return
    result = _orchestrator(context).draft_content_post(
        topic=topic,
        inspiration_notes=None,
        user_image_path=None,
        generate_image=False,
        database=_database(context),
    )
    post = result["post"]
    await _reply(
        update,
        f"Draft post #{_get_value(post, 'id')}:\n{_get_value(post, 'draft_text')}",
        reply_markup=_post_approval_markup(_get_value(post, "id")),
    )


async def photo_reply(update: Any, context: Any) -> None:
    """Save a replied photo and create a draft post using that uploaded image."""
    topic = _photo_topic(update)
    if not topic:
        await _reply(update, "Reply to a draft-post prompt with a photo and topic text.")
        return
    user_image_path = await _save_largest_photo(update)
    result = _orchestrator(context).draft_content_post(
        topic=topic,
        inspiration_notes=None,
        user_image_path=user_image_path,
        generate_image=False,
        database=_database(context),
    )
    post = result["post"]
    await _reply(
        update,
        f"Draft post #{_get_value(post, 'id')} with uploaded image:\n{_get_value(post, 'draft_text')}",
        reply_markup=_post_approval_markup(_get_value(post, "id")),
    )


async def pending_drafts(update: Any, context: Any) -> None:
    """Show pending content drafts."""
    drafts = _orchestrator(context).get_pending_content_drafts(database=_database(context))
    if not drafts:
        await _reply(update, "No pending drafts.")
        return
    lines = [
        f"#{draft.get('id')}: {draft.get('draft_text', '')}"
        for draft in drafts
    ]
    await _reply(update, "\n".join(lines))


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
    if data.startswith("outreach_sent:"):
        prospect_id = int(data.split(":", 1)[1])
        _orchestrator(context).mark_outreach_sent(
            prospect_id=prospect_id,
            database=_database(context),
        )
        await query.edit_message_text(
            f"Outreach marked sent for prospect {prospect_id}."
        )
        return
    if data == "discard":
        await query.edit_message_text("Discarded.")
        return
    if data.startswith("post_approve:"):
        await query.edit_message_text("Post approved for future publishing flow.")
        return
    if data.startswith("post_regenerate:"):
        await query.edit_message_text("Regenerate requested.")
        return
    await query.edit_message_text("Action received.")


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


def _database(context: Any) -> str:
    app = getattr(context, "application", None)
    bot_data = getattr(app, "bot_data", {}) if app is not None else {}
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


def _none_if_empty(value: str) -> str | None:
    return value or None


def _parse_int(value: str, field_name: str) -> int | None:
    _ = field_name
    try:
        return int(value)
    except ValueError:
        return None


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


def _outreach_approval_markup(prospect_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve & Mark Sent",
                    callback_data=f"outreach_sent:{prospect_id}",
                ),
                InlineKeyboardButton("Discard", callback_data="discard"),
            ]
        ]
    )


def _post_approval_markup(post_id: Any) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"post_approve:{post_id}"),
                InlineKeyboardButton(
                    "Regenerate",
                    callback_data=f"post_regenerate:{post_id}",
                ),
                InlineKeyboardButton("Discard", callback_data="discard"),
            ]
        ]
    )


def _format_due_line(item: dict[str, Any]) -> str:
    last_touch = item.get("last_touch_date")
    days = "never" if not last_touch else f"{_days_since(str(last_touch))} days"
    return f"{item.get('name')} (id={item.get('prospect_id')}): last touch {days}"


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
    lines = [f"System check overall_passed={result['overall_passed']}"]
    for check in result["checks"]:
        if check.get("violations"):
            lines.append(f"{check['check']}: violations={check['violations']}")
        for note in check.get("notes", []):
            lines.append(f"{check['check']}: {note}")
    if len(lines) == 1:
        lines.append("No violations found.")
    return "\n".join(lines)
