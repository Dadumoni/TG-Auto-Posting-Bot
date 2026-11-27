import asyncio
import time
from typing import Optional
from telethon import Button
from bot.client import bot as telethon_bot
from bot.config import ADMIN_ID, logger
from bot.database import (
    set_bot_posting_status,
    set_flood_safety_lock,
    get_flood_safety_lock,
    clear_flood_safety_lock,
    is_flood_locked,
)
from bot.utils import notify_admin

FLOOD_LOCK_DURATION: int = 6 * 3600  # 6 hours in seconds (21600s)
FLOOD_UPDATE_INTERVAL: int = 600  # 10 minutes update interval (600s)

_active_flood_updater_task: Optional[asyncio.Task] = None


async def _safe_edit_or_notify(alert_msg_id: int, text: str, buttons=None):
    """Edit the existing flood alert message or send a fresh notification if editing fails."""
    try:
        if alert_msg_id and ADMIN_ID != 0 and telethon_bot.is_connected():
            await telethon_bot.edit_message(ADMIN_ID, alert_msg_id, text, buttons=buttons)
            return
    except Exception as e:
        logger.debug(f"Failed to edit flood lock alert message {alert_msg_id}: {e}")
    await notify_admin(text, buttons=buttons)


def _cooloff_completed_payload():
    """Return completion message text and Ok / Restart inline buttons."""
    text = (
        "✅ **6-HOUR SAFETY COOLOFF COMPLETED!**\n\n"
        "Your Userbot account has completed the 6-hour safety cooloff period.\n\n"
        "• **⏳ Ok (Wait 6h):** Wait another 6 hours before resuming.\n"
        "• **▶️ Restart:** Resume scheduled auto-posting immediately."
    )
    buttons = [
        [
            Button.inline("⏳ Ok (Wait 6h)", data=b"floodcool:wait6h"),
            Button.inline("▶️ Restart", data=b"floodcool:restart"),
        ]
    ]
    return text, buttons


async def extend_flood_cooloff_6h(alert_msg_id: int = 0) -> float:
    """Extend safety wait for another 6 hours when Admin clicks Ok on cooloff completed prompt."""
    global _active_flood_updater_task

    set_bot_posting_status(False)
    cooloff_until = time.time() + FLOOD_LOCK_DURATION
    set_flood_safety_lock(cooloff_until=cooloff_until, alert_msg_id=alert_msg_id)

    extended_text = (
        "⏳ **EXTENDED 6-HOUR SAFETY WAIT ACTIVE**\n\n"
        "Admin chose to wait another **6 HOURS** before resuming posting.\n\n"
        "🛑 **Status:** Safety Wait Active\n"
        "⏱️ **Time Remaining:** `6 hours 00 mins`\n\n"
        "🔄 _Auto-updating every 10 minutes._"
    )
    await _safe_edit_or_notify(alert_msg_id, extended_text, buttons=None)

    if _active_flood_updater_task and not _active_flood_updater_task.done():
        _active_flood_updater_task.cancel()
    _active_flood_updater_task = asyncio.create_task(
        flood_lock_periodic_updater(alert_msg_id=alert_msg_id, cooloff_until=cooloff_until)
    )
    return cooloff_until


def cancel_flood_updater_task():
    """Cancel the active background flood countdown updater task, if running."""
    global _active_flood_updater_task
    if _active_flood_updater_task and not _active_flood_updater_task.done():
        _active_flood_updater_task.cancel()
        _active_flood_updater_task = None
        logger.info("Flood safety lock periodic updater stopped due to manual override.")


async def flood_lock_periodic_updater(alert_msg_id: int, cooloff_until: float):
    """
    Background task that updates the admin alert message every 10 minutes
    with the remaining cooloff time, and prompts admin with Ok / Restart after 6 hours.
    """
    logger.info("Flood safety lock periodic updater started (10-minute update interval).")
    try:
        while True:
            await asyncio.sleep(FLOOD_UPDATE_INTERVAL)

            # Check if lock was manually cleared (e.g. admin ran /restart)
            if not is_flood_locked():
                logger.info("Flood safety lock was manually cleared or overridden. Exiting updater.")
                break

            remaining = cooloff_until - time.time()
            if remaining <= 0:
                break

            hours = int(remaining // 3600)
            mins = int((remaining % 3600) // 60)

            update_text = (
                "🚨 **TELEGRAM FLOOD SAFETY LOCK ACTIVE**\n\n"
                "Auto-posting is temporarily locked to protect your Userbot account from ban.\n\n"
                "🛑 **Status:** Emergency Safety Lock Active\n"
                f"⏱️ **Time Remaining:** `{hours} hours {mins:02d} mins`\n\n"
                "🔄 _Auto-updating every 10 minutes._"
            )

            try:
                if alert_msg_id and ADMIN_ID != 0:
                    await telethon_bot.edit_message(ADMIN_ID, alert_msg_id, update_text)
            except Exception as e:
                logger.debug(f"Failed to edit flood lock alert message: {e}")

        # After 6 hours cooloff period finishes, wait for Admin's Ok (+6h) or Restart click
        if is_flood_locked() or cooloff_until <= time.time():
            logger.info("6-hour flood safety cooloff completed! Prompting admin for Ok (wait 6h) or Restart.")
            set_bot_posting_status(False)
            clear_flood_safety_lock()

            complete_text, complete_buttons = _cooloff_completed_payload()
            await _safe_edit_or_notify(alert_msg_id, complete_text, buttons=complete_buttons)

    except asyncio.CancelledError:
        logger.info("Flood safety lock periodic updater was cancelled.")
    except Exception as e:
        logger.error(f"Error in flood_lock_periodic_updater: {e}")


async def trigger_flood_emergency_lock(
    flood_wait_seconds: int,
    group_title: str,
    chat_id: int,
):
    """
    Trigger emergency 6-hour cooloff lock upon encountering FloodWaitError.
    Pauses auto-posting, sends initial alert, and starts 10-minute periodic live updater.
    """
    global _active_flood_updater_task

    # Check if already locked to avoid double alerting
    if is_flood_locked():
        logger.warning("Flood safety lock is already active. Skipping duplicate trigger.")
        return

    logger.warning(
        f"EMERGENCY: Telegram FloodWait encountered ({flood_wait_seconds}s) on '{group_title}' ({chat_id}). "
        "Enforcing 6-hour safety pause to protect Userbot account."
    )

    # 1. Immediately pause global auto-posting
    set_bot_posting_status(False)

    cooloff_until = time.time() + FLOOD_LOCK_DURATION
    initial_msg_id = 0

    # 2. Dispatch initial alert to Admin
    if ADMIN_ID != 0:
        alert_text = (
            "🚨 **TELEGRAM FLOOD LIMIT HIT - EMERGENCY LOCK ACTIVATED!**\n\n"
            f"Telegram enforced a flood wait limit on group: **{group_title}** (`{chat_id}`).\n\n"
            "⚠️ **Account Freeze Protection:**\n"
            "Repeatedly hitting Telegram flood limits can freeze, revoke, or permanently ban your Userbot account!\n\n"
            "🛑 **Action Taken:**\n"
            "All auto-posting across all groups has been **automatically paused for 6 HOURS** to protect your account.\n\n"
            "⏱️ **Time Remaining:** `6 hours 00 mins`\n"
            "🔄 _This alert will automatically update every 10 minutes with remaining time._"
        )
        try:
            sent_msg = await telethon_bot.send_message(ADMIN_ID, alert_text)
            initial_msg_id = sent_msg.id
        except Exception as e:
            logger.error(f"Failed to send initial flood lock alert to Admin: {e}")

    # 3. Persist lock state in database
    set_flood_safety_lock(cooloff_until=cooloff_until, alert_msg_id=initial_msg_id)

    # 4. Start background 10-minute periodic updater task
    if _active_flood_updater_task and not _active_flood_updater_task.done():
        _active_flood_updater_task.cancel()

    _active_flood_updater_task = asyncio.create_task(
        flood_lock_periodic_updater(alert_msg_id=initial_msg_id, cooloff_until=cooloff_until)
    )


def check_and_resume_flood_lock():
    """
    Check if a flood safety lock was active before a bot restart/redeploy,
    and resume tracking seamlessly.
    """
    global _active_flood_updater_task
    lock = get_flood_safety_lock()
    if lock and lock.get("active"):
        cooloff_until = lock.get("cooloff_until", 0)
        alert_msg_id = lock.get("alert_msg_id", 0)

        if cooloff_until > time.time():
            remaining_mins = int((cooloff_until - time.time()) / 60)
            logger.warning(
                f"Active flood safety lock found in database! Resuming 6-hour pause (~{remaining_mins} mins remaining)."
            )
            set_bot_posting_status(False)
            if _active_flood_updater_task and not _active_flood_updater_task.done():
                _active_flood_updater_task.cancel()
            _active_flood_updater_task = asyncio.create_task(
                flood_lock_periodic_updater(alert_msg_id=alert_msg_id, cooloff_until=cooloff_until)
            )
        else:
            logger.info("Previous flood safety lock has expired. Prompting admin for Ok or Restart.")
            clear_flood_safety_lock()
            set_bot_posting_status(False)
            complete_text, complete_buttons = _cooloff_completed_payload()
            try:
                asyncio.create_task(_safe_edit_or_notify(alert_msg_id, complete_text, buttons=complete_buttons))
            except RuntimeError:
                pass
