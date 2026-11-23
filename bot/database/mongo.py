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


def get_custom_message() -> str:
    """Retrieve the saved custom post message from the database."""
    if config_collection is None:
        return "Custom post message is not configured. Please use /set_message first."
    try:
        config = config_collection.find_one({"type": "post_message"})
        if config and "text" in config:
            return config["text"]
    except Exception as e:
        logger.error(f"Error reading custom message from DB: {e}")
    return "Custom post message is not configured. Please use /set_message first."


def set_custom_message(text: str) -> bool:
    """Save or update the custom post message in the database."""
    if config_collection is None:
        logger.error("Cannot set custom message: MongoDB is not connected.")
        return False
    try:
        config_collection.update_one(
            {"type": "post_message"},
            {"$set": {"text": text}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error updating custom message in DB: {e}")
        return False


def is_group_exists(chat_id: int) -> bool:
    """Check if a group with the given chat_id already exists in the database."""
    if groups_collection is None:
        return False
    try:
        return groups_collection.find_one({"chat_id": chat_id}) is not None
    except Exception as e:
        logger.error(f"Error checking group existence for {chat_id}: {e}")
        return False


def add_group_db(chat_id: int, title: str) -> bool:
    """Add or update a group record in the database."""
    if groups_collection is None:
        logger.error("Cannot add group: MongoDB is not connected.")
        return False
    try:
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"title": title, "last_posted": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error saving group {chat_id} to DB: {e}")
        return False


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


def update_last_posted(chat_id: int, post_time: float) -> bool:
    """Update the last_posted timestamp for a group."""
    if groups_collection is None:
        return False
    try:
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"last_posted": post_time}},
        )
        return True
    except Exception as e:
        logger.error(f"Error updating last_posted for {chat_id}: {e}")
        return False
