import gc
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import MemorySession, StringSession
from bot.config import API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, logger

# Safe placeholders to prevent immediate crash if .env is not yet configured
_safe_api_id = API_ID if API_ID != 0 else 12345
_safe_api_hash = API_HASH if API_HASH else "0123456789abcdef0123456789abcdef"

# Lightweight Telethon Bot Client (in-memory session avoids SQLite disk lock overhead)
bot = TelegramClient(
    MemorySession(),
    _safe_api_id,
    _safe_api_hash,
    entity_cache_limit=200,
    request_retries=3,
    connection_retries=5,
    auto_reconnect=True,
)

# Lightweight Telethon Userbot Client:
# receive_updates=False disables background channel difference polling ("Got difference for channel ...")
# flood_sleep_threshold=0 surfaces FloodWaitError immediately so the 6-hour safety lock engages right away
user = TelegramClient(
    StringSession(SESSION_STRING),
    _safe_api_id,
    _safe_api_hash,
    receive_updates=False,
    entity_cache_limit=2000,
    flood_sleep_threshold=0,
    request_retries=3,
    connection_retries=5,
    auto_reconnect=True,
)


async def start_clients():
    """Start both Bot and Userbot clients after validating required credentials."""
    if not API_ID or not API_HASH:
        logger.error("API_ID and API_HASH must be configured in .env to connect.")
        return

    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN is missing. Bot client will not start.")
    else:
        await bot.start(bot_token=BOT_TOKEN)
        me_bot = await bot.get_me()
        logger.info(f"Telethon Bot Client started: @{getattr(me_bot, 'username', 'bot')} (ID: {me_bot.id})")

    if not SESSION_STRING:
        logger.warning("SESSION_STRING is missing. Userbot client will not start.")
    else:
        await user.start()
        me_user = await user.get_me()
        logger.info(
            f"Telethon Userbot Client started: {getattr(me_user, 'first_name', 'User')} "
            f"(ID: {me_user.id}, receive_updates=False)"
        )


async def warmup_dialog_cache():
    """Pre-load userbot dialog entities in memory while keeping RAM usage minimal."""
    if not SESSION_STRING or not user.is_connected():
        return
    logger.info("Warming up userbot entity cache...")
    count = 0
    try:
        async for _ in user.iter_dialogs(limit=None):
            count += 1
        gc.collect()
        logger.info(f"Entity cache warm-up completed ({count} dialogs indexed).")
    except FloodWaitError as e:
        logger.warning(f"FloodWait ({e.seconds}s) during dialog warm-up; remaining chats will resolve on demand.")
    except Exception as e:
        logger.error(f"Error during dialog cache warm-up: {e}")
