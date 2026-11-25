import asyncio
from aiohttp import web, ClientSession, ClientTimeout
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
    """Keep-alive task to ping the bot's health endpoint every 10 minutes to prevent Koyeb sleep."""
    ping_url = f"{APP_URL}/health" if not APP_URL.endswith("/health") else APP_URL
    logger.info(f"Keep-alive auto-ping service started for URL: {ping_url} (every {PING_INTERVAL_SECONDS}s)")

    if "0.0.0.0" in APP_URL or "127.0.0.1" in APP_URL or "localhost" in APP_URL:
        logger.warning(
            "APP_URL is currently pointing to localhost/0.0.0.0. "
            "To prevent Koyeb free-tier sleep, set APP_URL to your public Koyeb app URL "
            "(e.g., https://your-service-name.koyeb.app) in Koyeb Environment Variables."
        )

    # Initial brief pause so the web server finishes binding before the first ping
    await asyncio.sleep(5)

    timeout = ClientTimeout(total=15)
    while True:
        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.get(ping_url) as response:
                    if response.status == 200:
                        logger.info(f"Self-ping successful: {ping_url} returned status {response.status}")
                    else:
                        logger.warning(f"Self-ping received unexpected status {response.status} from {ping_url}")
        except Exception as e:
            logger.error(f"Auto-ping request to {ping_url} failed: {e}")

        await asyncio.sleep(PING_INTERVAL_SECONDS)
