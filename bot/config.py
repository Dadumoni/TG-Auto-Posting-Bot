import logging
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup clean structured logging format and silence noisy third-party loggers
_raw_log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
_log_level = getattr(logging, _raw_log_level, logging.INFO)

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

# Silence noisy Telethon background/update/network INFO logs (e.g., "Got difference for channel ... updates")
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("telethon.client.updates").setLevel(logging.ERROR)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)

logger = logging.getLogger("TG-Auto-Poster")
logger.setLevel(_log_level)

# Telegram API Configuration
raw_api_id = os.getenv("API_ID", "").strip()
if not raw_api_id:
    logger.warning("API_ID is not set in environment variables.")
    API_ID = 0
else:
    try:
        API_ID = int(raw_api_id)
    except ValueError:
        logger.error(f"Invalid API_ID: {raw_api_id}. Must be an integer.")
        API_ID = 0

API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("DB_NAME", "autoposter_userbot_db")

# Admin Configuration
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

# Web & Deployment Configuration
try:
    PORT = int(os.getenv("PORT", "8080"))
except ValueError:
    PORT = 8080

raw_app_url = os.getenv("APP_URL", "").strip()
if raw_app_url:
    if not raw_app_url.startswith("http://") and not raw_app_url.startswith("https://"):
        raw_app_url = f"https://{raw_app_url}"
    APP_URL = raw_app_url.rstrip("/")
else:
    APP_URL = f"http://0.0.0.0:{PORT}"

# Timing Configurations (in seconds)
# Default auto-ping interval: 10 minutes (600 seconds) to prevent Koyeb sleep
PING_INTERVAL_SECONDS = int(os.getenv("PING_INTERVAL_SECONDS", "600"))

# Base post interval with human-like randomized range
POST_INTERVAL_SECONDS = int(os.getenv("POST_INTERVAL_SECONDS", "3600"))
POST_INTERVAL_MIN = int(os.getenv("POST_INTERVAL_MIN", str(int(POST_INTERVAL_SECONDS * 0.85))))
POST_INTERVAL_MAX = int(os.getenv("POST_INTERVAL_MAX", str(int(POST_INTERVAL_SECONDS * 1.15))))

# Guard against misconfigured min > max
if POST_INTERVAL_MIN > POST_INTERVAL_MAX:
    POST_INTERVAL_MIN, POST_INTERVAL_MAX = POST_INTERVAL_MAX, POST_INTERVAL_MIN

POST_DELAY_SECONDS = int(os.getenv("POST_DELAY_SECONDS", "3"))
SCHEDULER_CHECK_INTERVAL = int(os.getenv("SCHEDULER_CHECK_INTERVAL", "30"))
COOLDOWN_BUFFER_SECONDS = int(os.getenv("COOLDOWN_BUFFER_SECONDS", "120"))
