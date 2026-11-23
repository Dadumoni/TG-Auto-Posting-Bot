import asyncio
from bot.config import logger
from bot.client import bot, start_clients, warmup_dialog_cache
from bot.handlers import register_all_handlers
from bot.services import (
    start_web_server,
    auto_ping_server,
    auto_post_scheduler,
)


async def main():
    """Main application lifecycle runner."""
    logger.info("Initializing Telegram Auto-Posting Bot...")

    # Start health check web server for cloud hosting
    await start_web_server()

    # Start Telethon Bot & Userbot clients
    await start_clients()

    # Register all command and message handlers
    register_all_handlers(bot)
    logger.info("Bot event handlers successfully registered.")

    # Warm up dialog cache for fast entity resolution
    await warmup_dialog_cache()

    # Launch background scheduler and auto-ping tasks
    asyncio.create_task(auto_post_scheduler())
    asyncio.create_task(auto_ping_server())

    logger.info("Telegram Auto-Posting Bot is fully operational and waiting for events.")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutting down gracefully.")
