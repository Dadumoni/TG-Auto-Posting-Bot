import asyncio
import time
from bot.config import logger, SCHEDULER_CHECK_INTERVAL, POST_INTERVAL_SECONDS
from bot.database import get_all_groups_db
from bot.services.poster import post_to_single_group


async def auto_post_scheduler():
    """
    Background scheduler task that checks saved groups periodically
    and dispatches posts if the randomized post interval or cooldown has elapsed.
    """
    logger.info("Auto-Post Scheduler service started with randomized human-like intervals.")
    while True:
        try:
            current_time = time.time()
            groups = get_all_groups_db()

            for group in groups:
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
