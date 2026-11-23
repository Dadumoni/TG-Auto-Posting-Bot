from bot.client import bot
from bot.config import ADMIN_ID, logger


async def notify_admin(text: str) -> bool:
    """Send an alert or status notification to the bot administrator."""
    if not ADMIN_ID:
        return False
    try:
        await bot.send_message(ADMIN_ID, text)
        return True
    except Exception as e:
        logger.error(f"Failed to send notification to Admin ({ADMIN_ID}): {e}")
        return False
