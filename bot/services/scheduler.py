import asyncio
import time
from bot.config import logger, POST_INTERVAL_SECONDS, SCHEDULER_CHECK_INTERVAL
from bot.database import get_all_groups_db
from bot.services.poster import post_to_single_group


async def auto_post_scheduler():
    """
    Background scheduler task that checks saved groups periodically
    and dispatches posts if the configured post interval has elapsed.
    """
    logger.info("Auto-Post Scheduler service started.")
    while True:
        try:
            current_time = time.time()
            groups = get_all_groups_db()

            for group in groups:
                chat_id = group.get("chat_id")
                title = group.get("title", "Group")
                last_posted = group.get("last_posted", 0)

                if (current_time - last_posted) >= POST_INTERVAL_SECONDS:
                    await post_to_single_group(chat_id, title)

        except Exception as e:
            logger.error(f"Error encountered in Auto-Post Scheduler loop: {e}")

        await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)
