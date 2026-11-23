import logging
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging format and level
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("TG-Auto-Poster")

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
DB_NAME = os.getenv("DB_NAME", "telegram_bot_db")

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

APP_URL = os.getenv("APP_URL", f"http://0.0.0.0:{PORT}/health")

# Timing Configurations (in seconds)
POST_INTERVAL_SECONDS = int(os.getenv("POST_INTERVAL_SECONDS", "3600"))
POST_DELAY_SECONDS = int(os.getenv("POST_DELAY_SECONDS", "3"))
PING_INTERVAL_SECONDS = int(os.getenv("PING_INTERVAL_SECONDS", "300"))
SCHEDULER_CHECK_INTERVAL = int(os.getenv("SCHEDULER_CHECK_INTERVAL", "30"))
