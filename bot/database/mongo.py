import time
from typing import List, Dict, Any, Optional
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.results import DeleteResult
from bot.config import MONGO_URI, DB_NAME, logger

mongo_client: Optional[MongoClient] = None
groups_collection: Optional[Collection] = None
config_collection: Optional[Collection] = None

try:
    if MONGO_URI:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        groups_collection = db["groups"]
        config_collection = db["config"]
        logger.info(f"Successfully connected to MongoDB database: {DB_NAME}")
    else:
        logger.warning("MONGO_URI not provided. Database functionality will be disabled.")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")


def is_posting_active() -> bool:
    """
    Check whether global auto-posting is active or paused via /stop.
    Returns True by default if not set.
    """
    if config_collection is None:
        return True
    try:
        doc = config_collection.find_one({"type": "bot_status"})
        if doc and "active" in doc:
            return bool(doc["active"])
    except Exception as e:
        logger.error(f"Error checking bot posting status: {e}")
    return True


def set_bot_posting_status(active: bool) -> bool:
    """Save global auto-posting state (True for running, False for stopped)."""
    if config_collection is None:
        logger.error("Cannot set posting status: MongoDB is not connected.")
        return False
    try:
        config_collection.update_one(
            {"type": "bot_status"},
            {
                "$set": {
                    "active": active,
                    "status": "running" if active else "stopped",
                    "updated_at": time.time(),
                }
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error updating bot posting status: {e}")
        return False


def _resolve_config_type(msg_type: str) -> str:
    """Normalize message type key for MongoDB config collection."""
    clean_type = (msg_type or "").lower().strip()
    if clean_type in ["tme", "t_me", "t.me"]:
        return "post_message_tme"
    if clean_type in ["domain", "ext", "external"]:
        return "post_message_domain"
    return "post_message"


def get_custom_message(msg_type: str = "default") -> str:
    """
    Retrieve the configured post message.
    If a specific type (e.g. t_me or domain) is requested but not set,
    falls back to the default post_message.
    """
    if config_collection is None:
        return "Custom post message is not configured. Please use /set_message first."

    target_type = _resolve_config_type(msg_type)
    try:
        # Try specific type first
        if target_type != "post_message":
            specific_cfg = config_collection.find_one({"type": target_type})
            if specific_cfg and specific_cfg.get("text"):
                return specific_cfg["text"]

        # Fallback to default post_message
        default_cfg = config_collection.find_one({"type": "post_message"})
        if default_cfg and default_cfg.get("text"):
            return default_cfg["text"]
    except Exception as e:
        logger.error(f"Error reading custom message ({msg_type}) from DB: {e}")

    return "Custom post message is not configured. Please use /set_message first."


def set_custom_message(text: str, msg_type: str = "default") -> bool:
    """Save or update custom post message by type (default, t_me, or domain)."""
    if config_collection is None:
        logger.error("Cannot set custom message: MongoDB is not connected.")
        return False

    target_type = _resolve_config_type(msg_type)
    try:
        config_collection.update_one(
            {"type": target_type},
            {"$set": {"text": text, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error updating custom message ({target_type}) in DB: {e}")
        return False


def get_all_custom_messages() -> Dict[str, Optional[str]]:
    """Retrieve all configured custom messages."""
    result: Dict[str, Optional[str]] = {"default": None, "t_me": None, "domain": None}
    if config_collection is None:
        return result
    try:
        for doc in config_collection.find({"type": {"$in": ["post_message", "post_message_tme", "post_message_domain"]}}):
            dtype = doc.get("type")
            text = doc.get("text")
            if dtype == "post_message":
                result["default"] = text
            elif dtype == "post_message_tme":
                result["t_me"] = text
            elif dtype == "post_message_domain":
                result["domain"] = text
    except Exception as e:
        logger.error(f"Error fetching all custom messages: {e}")
    return result


def is_group_exists(chat_id: int) -> bool:
    """Check if a group with the given chat_id already exists in the database."""
    if groups_collection is None:
        return False
    try:
        return groups_collection.find_one({"chat_id": chat_id}) is not None
    except Exception as e:
        logger.error(f"Error checking group existence for {chat_id}: {e}")
        return False


def get_group_db(chat_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single group record by chat_id."""
    if groups_collection is None:
        return None
    try:
        return groups_collection.find_one({"chat_id": chat_id})
    except Exception as e:
        logger.error(f"Error fetching group {chat_id}: {e}")
        return None


def add_group_db(
    chat_id: int,
    title: str,
    cooldown_seconds: int = 0,
    link_type: str = "t_me",
    next_post_at: Optional[float] = None,
) -> bool:
    """Add or update a group record with cooldown, link type, and scheduling metadata."""
    if groups_collection is None:
        logger.error("Cannot add group: MongoDB is not connected.")
        return False

    now = time.time()
    update_data: Dict[str, Any] = {
        "title": title,
        "last_posted": now,
        "cooldown_seconds": cooldown_seconds,
        "link_type": link_type,
        "next_post_at": next_post_at if next_post_at is not None else now,
    }
    try:
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$set": update_data},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error saving group {chat_id} to DB: {e}")
        return False


def update_group_link_type(chat_id: int, link_type: str) -> bool:
    """Update supported link type ('t_me' or 'domain') for a group."""
    if groups_collection is None:
        return False
    clean_type = "domain" if link_type.lower() in ["domain", "ext", "external"] else "t_me"
    try:
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"link_type": clean_type}},
        )
        return True
    except Exception as e:
        logger.error(f"Error updating link_type for group {chat_id}: {e}")
        return False


def update_group_cooldown(chat_id: int, cooldown_seconds: int) -> bool:
    """Update slowmode/cooldown timer in seconds for a group."""
    if groups_collection is None:
        return False
    try:
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"cooldown_seconds": max(0, int(cooldown_seconds))}},
        )
        return True
    except Exception as e:
        logger.error(f"Error updating cooldown for group {chat_id}: {e}")
        return False


def update_group_schedule(chat_id: int, last_posted: float, next_post_at: float) -> bool:
    """Update both last_posted and next_post_at timestamps for a group."""
    if groups_collection is None:
        return False
    try:
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"last_posted": last_posted, "next_post_at": next_post_at}},
        )
        return True
    except Exception as e:
        logger.error(f"Error updating schedule for group {chat_id}: {e}")
        return False


def update_last_posted(chat_id: int, post_time: float) -> bool:
    """Backward-compatible helper to update last_posted timestamp."""
    return update_group_schedule(chat_id, last_posted=post_time, next_post_at=post_time)


def remove_group_db(chat_id: int) -> bool:
    """Remove a single group from the database by chat_id."""
    if groups_collection is None:
        return False
    try:
        res = groups_collection.delete_one({"chat_id": chat_id})
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"Error removing group {chat_id} from DB: {e}")
        return False


def remove_all_groups_db() -> Optional[DeleteResult]:
    """Remove all groups from the groups collection."""
    if groups_collection is None:
        return None
    try:
        return groups_collection.delete_many({})
    except Exception as e:
        logger.error(f"Error removing all groups from DB: {e}")
        return None


def get_all_groups_db() -> List[Dict[str, Any]]:
    """Retrieve all saved groups from the database."""
    if groups_collection is None:
        return []
    try:
        return list(groups_collection.find({}))
    except Exception as e:
        logger.error(f"Error fetching groups from DB: {e}")
        return []
