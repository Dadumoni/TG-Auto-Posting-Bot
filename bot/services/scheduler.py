import asyncio
import time
from bot.config import logger, SCHEDULER_CHECK_INTERVAL, POST_INTERVAL_SECONDS
from bot.database import get_all_groups_db, is_posting_active, is_flood_locked
from bot.services.poster import post_to_single_group
from bot.services.emergency import check_and_resume_flood_lock


async def auto_post_scheduler():
    """
    Background scheduler task that checks saved groups periodically
    and dispatches posts if the randomized post interval or cooldown has elapsed.
    Respects /stop and /restart commands.
    """
    logger.info("Auto-Post Scheduler service started with randomized human-like intervals.")
    check_and_resume_flood_lock()

    while True:
        try:
            # Check if auto-posting has been locked due to Telegram flood wait
            if is_flood_locked():
                logger.debug("Auto-posting is currently in 6-hour FloodWait safety cooloff. Skipping scheduler cycle.")
                await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)
                continue

            # Check if auto-posting has been paused by the admin via /stop
            if not is_posting_active():
                logger.debug("Auto-posting is currently paused via /stop. Skipping scheduler cycle.")
                await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)
                continue

            current_time = time.time()
            groups = get_all_groups_db()

            for group in groups:
                # Re-check lock/pause state inside loop so FloodWait or /stop halts remaining groups immediately
                if is_flood_locked() or not is_posting_active():
                    logger.info("Scheduler cycle halted mid-pass due to FloodLock or /stop.")
                    break

                # Skip group while awaiting admin confirmation on a failed post
                if group.get("awaiting_admin_action"):
                    continue

                chat_id = group.get("chat_id")
                title = group.get("title", "Group")
                last_posted = group.get("last_posted", 0)

                # Use dynamic next_post_at, or fallback to last_posted + default interval
                next_post_at = group.get("next_post_at")
                if next_post_at is None:
                    next_post_at = last_posted + POST_INTERVAL_SECONDS

                if current_time >= next_post_at:
                    await post_to_single_group(chat_id, title, group_data=group)

        except Exception as e:
            logger.error(f"Error encountered in Auto-Post Scheduler loop: {e}")

        await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)
