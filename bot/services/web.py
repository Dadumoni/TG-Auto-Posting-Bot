import asyncio
from aiohttp import web, ClientSession
from bot.config import PORT, APP_URL, PING_INTERVAL_SECONDS, logger


async def web_health_check(request):
    """Health check endpoint handler for cloud hosting platforms."""
    return web.Response(text="Bot is running and healthy!", status=200)


async def start_web_server():
    """Start the lightweight HTTP server for Koyeb / Render / PaaS health checks."""
    app = web.Application()
    app.router.add_get('/', web_health_check)
    app.router.add_get('/health', web_health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Health check web server running on port {PORT}")


async def auto_ping_server():
    """Keep-alive task to ping the bot's health endpoint periodically."""
    logger.info(f"Keep-alive auto-ping service started for URL: {APP_URL}")
    while True:
        try:
            async with ClientSession() as session:
                async with session.get(APP_URL) as response:
                    logger.debug(f"Self-ping response status: {response.status}")
        except Exception as e:
            logger.error(f"Auto-ping request failed: {e}")

        await asyncio.sleep(PING_INTERVAL_SECONDS)
