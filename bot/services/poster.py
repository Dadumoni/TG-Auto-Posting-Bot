import asyncio
import random
import time
from typing import Optional, Dict, Any
from telethon.errors import FloodWaitError, SlowModeWaitError
from bot.client import user
from bot.config import (
    logger,
    POST_DELAY_SECONDS,
    POST_INTERVAL_MIN,
    POST_INTERVAL_MAX,
    COOLDOWN_BUFFER_SECONDS,
)
from bot.database import (
    is_posting_active,
    get_custom_message,
    get_group_db,
    update_group_schedule,
    update_group_cooldown,
)
from bot.utils import resolve_chat_entity, notify_admin

# Posting lock to ensure only one post runs at any given time
posting_lock = asyncio.Lock()


def calculate_next_post_timestamp(group_data: Optional[Dict[str, Any]] = None) -> float:
    """
    Calculate next post timestamp with human-like randomized timing,
    taking into account group slowmode cooldown.
    """
    now = time.time()
    random_interval = random.randint(POST_INTERVAL_MIN, POST_INTERVAL_MAX)

    cooldown = 0
    if group_data:
        cooldown = int(group_data.get("cooldown_seconds", 0))

    if cooldown > 0:
        # Respect group slowmode + random buffer
        effective_interval = max(
            random_interval,
            cooldown + COOLDOWN_BUFFER_SECONDS + random.randint(30, 90),
        )
    else:
        effective_interval = random_interval

    return now + effective_interval


async def post_to_single_group(
    chat_id: int,
    group_title: str,
    group_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send the configured promotional post to a single Telegram group using the Userbot.
    Enforces sequential posting via posting_lock, human-randomized scheduling,
    and slowmode cooldown handling.
    """
    async with posting_lock:
        if not is_posting_active():
            logger.info(f"Skipping post to '{group_title}' ({chat_id}): Auto-posting is stopped via /stop.")
            return False

        logger.info(f"Attempting post to group: '{group_title}' (ID: {chat_id})...")

        if group_data is None:
            group_data = get_group_db(chat_id) or {}

        link_type = group_data.get("link_type", "t_me")
        success = False
        post_timestamp = time.time()
        next_post_at = calculate_next_post_timestamp(group_data)

        try:
            chat = await resolve_chat_entity(chat_id)
            post_text = get_custom_message(link_type)
            sent_message = await user.send_message(chat, post_text)

            success = True
            link_badge = "🔗 t.me only" if link_type == "t_me" else "🌐 Domain / External"
            cooldown_val = group_data.get("cooldown_seconds", 0)
            cooldown_info = f"`{cooldown_val}s`" if cooldown_val > 0 else "None"

            success_msg = (
                f"✅ **Post Successful!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"📎 **Link Type:** {link_badge}\n"
                f"⏱️ **Cooldown:** {cooldown_info}\n"
                f"📨 **Message ID:** `{sent_message.id}`"
            )
            logger.info(f"SUCCESS: Posted to '{group_title}' ({chat_id}) using link type '{link_type}'")
            await notify_admin(success_msg)

        except SlowModeWaitError as e:
            # Telegram slowmode cooldown triggered
            update_group_cooldown(chat_id, e.seconds)
            next_post_at = time.time() + e.seconds + random.randint(30, 90)

            err_msg = (
                f"⏳ **Post Delayed (Slowmode Cooldown Active)!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⏱️ **Wait Required:** `{e.seconds}` seconds\n\n"
                f"🔄 Next post automatically rescheduled after cooldown."
            )
            logger.warning(f"SLOWMODE: Post to '{group_title}' ({chat_id}) delayed for {e.seconds}s")
            await notify_admin(err_msg)

        except FloodWaitError as e:
            next_post_at = time.time() + e.seconds + random.randint(30, 90)
            err_msg = (
                f"❌ **Post Failed (FloodWait)!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⏱️ **Wait Required:** `{e.seconds}` seconds"
            )
            logger.error(f"FAILED: Post to '{group_title}' ({chat_id}) - FloodWait: {e.seconds}s")
            await notify_admin(err_msg)

        except Exception as e:
            err_msg = (
                f"❌ **Post Failed!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ **Error:** `{str(e)}`"
            )
            logger.error(f"FAILED: Post to '{group_title}' ({chat_id}) - {str(e)}")
            await notify_admin(err_msg)

        finally:
            update_group_schedule(chat_id, last_posted=post_timestamp, next_post_at=next_post_at)
            # Add human random pause between group posts
            human_pause = POST_DELAY_SECONDS + random.uniform(1.0, 3.0)
            await asyncio.sleep(human_pause)

        return success
