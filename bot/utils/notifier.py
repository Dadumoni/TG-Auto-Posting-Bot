import asyncio
from typing import Any, Optional, Set
from telethon.tl.types import Channel
from bot.client import bot
from bot.config import ADMIN_ID, logger

# Track background cleanup tasks so they are not garbage-collected mid-sleep
_cleanup_tasks: Set[asyncio.Task] = set()


def schedule_message_cleanup(*messages: Any, delay: float = 10.0) -> Optional[asyncio.Task]:
    """Schedule non-blocking deletion of Telegram message(s) after `delay` seconds."""
    targets = [msg for msg in messages if msg is not None]
    if not targets:
        return None

    async def _cleanup():
        try:
            await asyncio.sleep(delay)
            for msg in targets:
                try:
                    await msg.delete()
                except Exception as e:
                    logger.debug(f"Auto-delete skipped: {e}")
        except asyncio.CancelledError:
            pass

    try:
        task = asyncio.create_task(_cleanup())
        _cleanup_tasks.add(task)
        task.add_done_callback(_cleanup_tasks.discard)
        return task
    except RuntimeError:
        return None


def build_message_link(chat: Any, chat_id: int, message_id: int) -> Optional[str]:
    """Build a direct t.me link to a posted message for public or private supergroups/channels."""
    if not message_id:
        return None
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    if isinstance(chat, Channel) or str(chat_id).startswith("-100"):
        raw_id = getattr(chat, "id", None)
        if not raw_id and str(chat_id).startswith("-100"):
            raw_id = str(chat_id)[4:]
        if raw_id:
            return f"https://t.me/c/{raw_id}/{message_id}"
    return None


async def notify_admin(text: str, buttons: Optional[Any] = None) -> Optional[Any]:
    """Send an alert or status notification to the bot administrator and return the sent Message."""
    if not ADMIN_ID or not bot.is_connected():
        return None
    try:
        return await bot.send_message(ADMIN_ID, text, buttons=buttons)
    except Exception as e:
        # Retry as plain text in case raw error strings break Markdown parsing
        try:
            return await bot.send_message(ADMIN_ID, text, buttons=buttons, parse_mode=None)
        except Exception as inner_e:
            if buttons is not None:
                try:
                    return await bot.send_message(ADMIN_ID, text, parse_mode=None)
                except Exception:
                    pass
            logger.error(f"Failed to send notification to Admin ({ADMIN_ID}): {inner_e} (initial: {e})")
            return None
