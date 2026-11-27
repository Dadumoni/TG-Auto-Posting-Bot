import asyncio
import random
import time
from typing import Optional, Dict, Any
from telethon import Button
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
    is_flood_locked,
    get_custom_message,
    get_group_db,
    update_group_schedule,
    update_group_cooldown,
    mark_group_failure_pending,
    generate_group_post,
)
from bot.utils import (
    resolve_chat_entity,
    notify_admin,
    diagnose_group_failure,
    build_message_link,
    schedule_message_cleanup,
)

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
    force_link_only_tme: bool = False,
) -> bool:
    """
    Send the configured promotional post to a single Telegram group using the Userbot.
    When force_link_only_tme=True (used on newly added groups), sends only the single t.me link
    without custom text, emojis, or multiple links.
    """
    async with posting_lock:
        if is_flood_locked():
            logger.info(f"Skipping post to '{group_title}' ({chat_id}): 6-hour FloodWait safety lock active.")
            return False

        if not is_posting_active():
            logger.info(f"Skipping post to '{group_title}' ({chat_id}): Auto-posting is stopped via /stop.")
            return False

        if not user.is_connected():
            logger.warning(f"Skipping post to '{group_title}' ({chat_id}): Userbot is not connected.")
            return False

        logger.info(f"Attempting post to group: '{group_title}' (ID: {chat_id})...")

        if group_data is None:
            group_data = get_group_db(chat_id) or {}

        if group_data.get("awaiting_admin_action"):
            logger.info(f"Skipping post to '{group_title}' ({chat_id}): Awaiting admin failure confirmation.")
            return False

        if force_link_only_tme:
            link_type = "t_me"
            allow_text = False
        else:
            link_type = group_data.get("link_type", "t_me")
            allow_text = group_data.get("allow_text", True)

        success = False
        clear_failure = False
        increment_count = False
        post_timestamp = time.time()
        next_post_at = calculate_next_post_timestamp(group_data)

        try:
            chat = await resolve_chat_entity(chat_id)
            post_text = generate_group_post(link_type=link_type, allow_text=allow_text)
            sent_message = await user.send_message(chat, post_text)

            success = True
            clear_failure = True
            increment_count = True
            link_badge = "🔗 t.me only" if link_type == "t_me" else "🌐 Domain / External"
            if force_link_only_tme:
                mode_badge = "🚫 Single t.me Link (Initial)"
            else:
                mode_badge = "✅ Text + Emojis" if allow_text else "🚫 Link Only"
            cooldown_val = group_data.get("cooldown_seconds", 0)
            cooldown_info = f"`{cooldown_val}s`" if cooldown_val > 0 else "None"

            msg_link = build_message_link(chat, chat_id, sent_message.id)
            buttons = [[Button.url("🔗 View Message", msg_link)]] if msg_link else None

            success_msg = (
                f"✅ **Post Successful!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"📎 **Link Type:** {link_badge}\n"
                f"📝 **Post Mode:** {mode_badge}\n"
                f"⏱️ **Cooldown:** {cooldown_info}"
            )
            logger.info(f"SUCCESS: Posted to '{group_title}' ({chat_id}) using link type '{link_type}'")
            sent_alert = await notify_admin(success_msg, buttons=buttons)
            schedule_message_cleanup(sent_alert, delay=600.0)

        except SlowModeWaitError as e:
            # Telegram slowmode cooldown triggered
            clear_failure = True
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
            sent_alert = await notify_admin(err_msg)
            schedule_message_cleanup(sent_alert, delay=10.0)

        except FloodWaitError as e:
            # Reschedule far in advance (6 hours)
            clear_failure = True
            next_post_at = time.time() + 21600
            logger.error(f"FAILED: Post to '{group_title}' ({chat_id}) - FloodWait: {e.seconds}s. Enforcing 6-hour emergency lock.")
            from bot.services.emergency import trigger_flood_emergency_lock
            await trigger_flood_emergency_lock(
                flood_wait_seconds=e.seconds,
                group_title=group_title,
                chat_id=chat_id,
            )

        except Exception as e:
            logger.error(f"FAILED: Post to '{group_title}' ({chat_id}) - {type(e).__name__}: {str(e)}")
            diag = await diagnose_group_failure(chat_id, e)
            mark_group_failure_pending(chat_id, diag["reason"])
            star_badge = " ⭐ (Paid Messages Required)" if diag.get("stars_detected") else ""
            banned_badge = " 🚫 (Banned / Kicked)" if diag.get("banned") else ""

            err_msg = (
                f"❌ **Post Failed to Group!**{star_badge}{banned_badge}\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n\n"
                f"🔍 **Diagnostic Inspection:**\n"
                f"• **Cause:** {diag['reason']}\n"
                f"• **Details:** {diag['description']}\n"
                f"• **Raw Error:** `{type(e).__name__}: {str(e)}`\n\n"
                f"💡 **Recommended Action:**\n"
                f"{diag['recommendation']}"
            )
            fail_buttons = [
                [
                    Button.inline("♻️ Retry After 6 Hours", data=f"failact:retry6h:{chat_id}"),
                    Button.inline("🗑️ Remove Group", data=f"failact:remove:{chat_id}"),
                ]
            ]
            await notify_admin(err_msg, buttons=fail_buttons)

        finally:
            update_group_schedule(
                chat_id,
                last_posted=post_timestamp,
                next_post_at=next_post_at,
                clear_failure=clear_failure,
                increment_post_count=increment_count,
            )
            # Add human random pause between group posts
            human_pause = POST_DELAY_SECONDS + random.uniform(1.0, 3.0)
            await asyncio.sleep(human_pause)

        return success
