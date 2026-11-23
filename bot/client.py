from telethon import TelegramClient
from telethon.sessions import StringSession
from bot.config import API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, logger

# Safe placeholders to prevent immediate crash if .env is not yet configured
_safe_api_id = API_ID if API_ID != 0 else 12345
_safe_api_hash = API_HASH if API_HASH else "0123456789abcdef0123456789abcdef"

# Initialize Telethon Bot Client (receives commands and interactions)
bot = TelegramClient('bot_session', _safe_api_id, _safe_api_hash)

# Initialize Telethon Userbot Client (used for sending scheduled posts to groups)
user = TelegramClient(StringSession(SESSION_STRING), _safe_api_id, _safe_api_hash)


async def start_clients():
    """Start both Bot and Userbot clients after validating required credentials."""
    if not API_ID or not API_HASH:
        logger.error("API_ID and API_HASH must be configured in .env to connect.")
        return

    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN is missing. Bot client will not start.")
    else:
        await bot.start(bot_token=BOT_TOKEN)
        logger.info("Telethon Bot Client started successfully.")

    if not SESSION_STRING:
        logger.warning("SESSION_STRING is missing. Userbot client will not start.")
    else:
        await user.start()
        logger.info("Telethon Userbot Client started successfully.")


async def warmup_dialog_cache():
    """Pre-load userbot dialogs to cache known entities in memory."""
    if not SESSION_STRING:
        return
    logger.info("Warming up userbot dialog cache (full scan)...")
    try:
        async for _ in user.iter_dialogs(limit=None):
            pass
        logger.info("Dialog cache warm-up completed successfully.")
    except Exception as e:
        logger.error(f"Error during dialog cache warm-up: {e}")
