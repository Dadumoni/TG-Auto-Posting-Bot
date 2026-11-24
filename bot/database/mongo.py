import random
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


def set_flood_safety_lock(cooloff_until: float, alert_msg_id: int = 0) -> bool:
    """Set emergency 6-hour safety lock state in MongoDB."""
    if config_collection is None:
        return False
    try:
        config_collection.update_one(
            {"type": "flood_safety_lock"},
            {
                "$set": {
                    "active": True,
                    "cooloff_until": cooloff_until,
                    "alert_msg_id": alert_msg_id,
                    "locked_at": time.time(),
                }
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error setting flood safety lock in DB: {e}")
        return False


def get_flood_safety_lock() -> Optional[Dict[str, Any]]:
    """Retrieve flood safety lock details from MongoDB."""
    if config_collection is None:
        return None
    try:
        doc = config_collection.find_one({"type": "flood_safety_lock"})
        if doc and doc.get("active"):
            return doc
    except Exception as e:
        logger.error(f"Error reading flood safety lock from DB: {e}")
    return None


def clear_flood_safety_lock() -> bool:
    """Clear emergency flood safety lock from MongoDB."""
    if config_collection is None:
        return False
    try:
        config_collection.update_one(
            {"type": "flood_safety_lock"},
            {"$set": {"active": False, "cooloff_until": 0, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error clearing flood safety lock in DB: {e}")
        return False


def is_flood_locked() -> bool:
    """Check if emergency flood safety lock is currently active."""
    lock = get_flood_safety_lock()
    if not lock:
        return False
    cooloff_until = lock.get("cooloff_until", 0)
    return time.time() < cooloff_until


# Selected emoji pool for randomized human-like post variation per group
EMOJI_POOL = [
    "👇", "😍", "🥵", "✅", "👁", "😱", "😈", "☠️",
    "🐱", "🐙", "🌝", "💦", "🍑", "🍓", "📌", "❤️", "🔥",
]


def clean_url_format(url: str) -> str:
    """Ensure URL is properly formatted with https:// prefix."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.startswith("http://") and not raw.startswith("https://"):
        return f"https://{raw}"
    return raw


def get_link_db(link_type: str) -> Optional[str]:
    """Retrieve configured URL for link_type ('t_me' or 'domain')."""
    if config_collection is None:
        return None
    clean_type = "domain" if (link_type or "").lower() in ["domain", "ext", "external"] else "t_me"
    try:
        doc = config_collection.find_one({"type": f"link_{clean_type}"})
        if doc and doc.get("url"):
            return clean_url_format(doc["url"])

        # Fallback to legacy post_message keys if present
        legacy_key = "post_message_domain" if clean_type == "domain" else "post_message_tme"
        leg_doc = config_collection.find_one({"type": legacy_key})
        if leg_doc and leg_doc.get("text"):
            for word in leg_doc["text"].split():
                if "t.me" in word or "http" in word or "." in word:
                    return clean_url_format(word)
    except Exception as e:
        logger.error(f"Error fetching link ({link_type}) from DB: {e}")
    return None


def set_link_db(link_type: str, url: str) -> bool:
    """Save or update URL for link_type ('t_me' or 'domain')."""
    if config_collection is None:
        logger.error("Cannot set link: MongoDB is not connected.")
        return False
    clean_type = "domain" if (link_type or "").lower() in ["domain", "ext", "external"] else "t_me"
    formatted_url = clean_url_format(url)
    try:
        config_collection.update_one(
            {"type": f"link_{clean_type}"},
            {"$set": {"url": formatted_url, "updated_at": time.time()}},
            upsert=True,
        )
        # Update legacy key for backward compatibility
        legacy_key = "post_message_domain" if clean_type == "domain" else "post_message_tme"
        config_collection.update_one(
            {"type": legacy_key},
            {"$set": {"text": formatted_url, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error setting link ({clean_type}) in DB: {e}")
        return False


def get_base_text_db() -> str:
    """Retrieve base header text for posts."""
    if config_collection is None:
        return ""
    try:
        doc = config_collection.find_one({"type": "base_text"})
        if doc and doc.get("text") is not None:
            return doc["text"].strip()

        # Legacy fallback
        doc_legacy = config_collection.find_one({"type": "post_message"})
        if doc_legacy and doc_legacy.get("text"):
            txt = doc_legacy["text"].strip()
            # If legacy text is not just a bare URL, return it
            if not txt.startswith("http://") and not txt.startswith("https://"):
                return txt
    except Exception as e:
        logger.error(f"Error fetching base text from DB: {e}")
    return ""


def set_base_text_db(text: str) -> bool:
    """Save base header text for posts."""
    if config_collection is None:
        logger.error("Cannot set base text: MongoDB is not connected.")
        return False
    clean_text = (text or "").strip()
    try:
        config_collection.update_one(
            {"type": "base_text"},
            {"$set": {"text": clean_text, "updated_at": time.time()}},
            upsert=True,
        )
        config_collection.update_one(
            {"type": "post_message"},
            {"$set": {"text": clean_text, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error saving base text to DB: {e}")
        return False


def get_custom_texts_db() -> List[str]:
    """Retrieve list of all active custom promotional texts."""
    if config_collection is None:
        return []
    try:
        doc = config_collection.find_one({"type": "custom_texts_pool"})
        if doc and isinstance(doc.get("texts"), list) and doc["texts"]:
            return [t.strip() for t in doc["texts"] if t.strip()]
    except Exception as e:
        logger.error(f"Error fetching custom texts pool: {e}")
    # Fallback to single base_text if pool is empty
    base = get_base_text_db()
    return [base] if base else []


def add_custom_texts_db(new_texts: List[str]) -> List[str]:
    """Add single or multiple texts to the custom texts pool without duplicates."""
    if config_collection is None:
        logger.error("Cannot add custom texts: MongoDB is not connected.")
        return []
    current = get_custom_texts_db()
    for t in new_texts:
        clean = t.strip()
        if clean and clean not in current:
            current.append(clean)
    try:
        config_collection.update_one(
            {"type": "custom_texts_pool"},
            {"$set": {"texts": current, "updated_at": time.time()}},
            upsert=True,
        )
        # Also keep base_text updated to the latest text
        if current:
            set_base_text_db(current[-1])
    except Exception as e:
        logger.error(f"Error saving custom texts pool: {e}")
    return current


def clear_custom_texts_db() -> bool:
    """Clear all custom texts from the pool."""
    if config_collection is None:
        return False
    try:
        config_collection.update_one(
            {"type": "custom_texts_pool"},
            {"$set": {"texts": [], "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error clearing custom texts pool: {e}")
        return False


def get_random_custom_text() -> str:
    """Pick a random text from custom texts pool."""
    texts = get_custom_texts_db()
    if texts:
        return random.choice(texts)
    return get_base_text_db()


def generate_group_post(link_type: str = "t_me", allow_text: bool = True) -> str:
    """
    Generate dynamic post content for a group:
    If allow_text is False:
        Returns single link only: {link}
    If allow_text is True:
        Returns:
        {custom text} (random emoji from selected pool)
        \n\n
        {link}
        {link}
    """
    clean_type = "domain" if (link_type or "").lower() in ["domain", "ext", "external"] else "t_me"
    link = get_link_db(clean_type)

    if not link:
        # Fallback to alternate link if requested type not configured
        alt_type = "domain" if clean_type == "t_me" else "t_me"
        link = get_link_db(alt_type)

    if not link:
        link = "https://t.me"

    # In Link-Only groups: return only single clean link (no text, no emojis)
    if not allow_text:
        return link

    # Text + Emojis mode
    custom_text = get_random_custom_text()
    random_emoji = random.choice(EMOJI_POOL)
    if custom_text:
        header = f"{custom_text} {random_emoji}"
    else:
        header = f"{random_emoji}"

    # Double new line after header, single new line between repeated links
    return f"{header}\n\n{link}\n{link}"


def get_custom_message(msg_type: str = "default", allow_text: bool = True) -> str:
    """Retrieve dynamic generated post message for the specified link type and text policy."""
    return generate_group_post(msg_type, allow_text=allow_text)


def set_custom_message(text: str, msg_type: str = "default") -> bool:
    """
    Save or update custom post message or link based on type.
    Maintains backward compatibility for /set_message command variants.
    """
    clean_type = (msg_type or "").lower().strip()
    if clean_type in ["tme", "t_me", "t.me"]:
        return set_link_db("t_me", text)
    if clean_type in ["domain", "ext", "external"]:
        return set_link_db("domain", text)
    # If text is a URL, detect and save as link
    stripped = text.strip()
    if "t.me" in stripped:
        return set_link_db("t_me", stripped)
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return set_link_db("domain", stripped)
    return set_base_text_db(text)


def get_all_custom_messages() -> Dict[str, Optional[str]]:
    """Retrieve all configured custom messages and links."""
    return {
        "default": get_base_text_db(),
        "t_me": get_link_db("t_me"),
        "domain": get_link_db("domain"),
    }


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
    allow_text: bool = True,
    next_post_at: Optional[float] = None,
) -> bool:
    """Add or update a group record with cooldown, link type, text policy, and scheduling metadata."""
    if groups_collection is None:
        logger.error("Cannot add group: MongoDB is not connected.")
        return False

    now = time.time()
    update_data: Dict[str, Any] = {
        "title": title,
        "last_posted": now,
        "cooldown_seconds": cooldown_seconds,
        "link_type": link_type,
        "allow_text": bool(allow_text),
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


def update_group_text_policy(chat_id: int, allow_text: bool) -> bool:
    """Update whether a group allows custom text & emojis or link only."""
    if groups_collection is None:
        return False
    try:
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"allow_text": bool(allow_text)}},
        )
        return True
    except Exception as e:
        logger.error(f"Error updating text policy for group {chat_id}: {e}")
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
