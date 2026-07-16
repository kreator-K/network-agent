"""Deny-by-default Telegram private-beta authorization helpers."""

from __future__ import annotations

import logging
from typing import Any

from telegram.ext import ApplicationHandlerStop

from config.settings import settings


logger = logging.getLogger(__name__)


def parse_user_ids(raw: str) -> frozenset[int]:
    """Parse strictly numeric Telegram IDs; malformed entries fail closed."""
    values: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit():
            raise ValueError("Telegram allowlist IDs must be numeric.")
        values.add(int(item))
    return frozenset(values)


def allowed_user_ids() -> frozenset[int]:
    return parse_user_ids(settings.telegram_allowed_user_ids)


def admin_user_ids() -> frozenset[int]:
    return parse_user_ids(settings.telegram_admin_user_ids)


def update_user_id(update: Any) -> int | None:
    user = getattr(update, "effective_user", None)
    value = getattr(user, "id", None)
    return value if isinstance(value, int) else None


def is_authorized(update: Any) -> bool:
    user_id = update_user_id(update)
    return user_id is not None and user_id in allowed_user_ids()


def is_admin(update: Any) -> bool:
    user_id = update_user_id(update)
    return user_id is not None and user_id in admin_user_ids()


async def authorization_guard(update: Any, context: Any) -> None:
    """Reject unauthorized messages and callbacks before business handlers."""
    _ = context
    if is_authorized(update):
        return
    user_id = update_user_id(update)
    logger.warning("Unauthorized Telegram update rejected: user_id_present=%s", user_id is not None)
    query = getattr(update, "callback_query", None)
    if query is not None:
        await query.answer("Access denied.", show_alert=True)
    else:
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text("Access denied.")
    raise ApplicationHandlerStop
