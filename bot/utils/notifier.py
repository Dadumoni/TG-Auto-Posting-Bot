from bot.client import bot
from bot.config import ADMIN_ID, logger


async def notify_admin(text: str) -> bool:
    """Send an alert or status notification to the bot administrator."""
    if not ADMIN_ID or not bot.is_connected():
        return False
    try:
        await bot.send_message(ADMIN_ID, text)
        return True
    except Exception as e:
        # Retry as plain text in case raw error strings break Markdown parsing
        try:
            await bot.send_message(ADMIN_ID, text, parse_mode=None)
            return True
        except Exception as inner_e:
            logger.error(f"Failed to send notification to Admin ({ADMIN_ID}): {inner_e} (initial: {e})")
            return False
