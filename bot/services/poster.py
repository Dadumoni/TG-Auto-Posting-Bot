import asyncio
import time
from telethon.errors import FloodWaitError
from bot.client import user
from bot.config import logger, POST_DELAY_SECONDS
from bot.database import get_custom_message, update_last_posted
from bot.utils import resolve_chat_entity, notify_admin

# Posting lock to ensure only one post runs at any given time
posting_lock = asyncio.Lock()


async def post_to_single_group(chat_id: int, group_title: str) -> bool:
    """
    Send the configured promotional/custom post to a single Telegram group using the Userbot.
    Enforces sequential posting via posting_lock.
    """
    async with posting_lock:
        logger.info(f"Attempting post to group: '{group_title}' (ID: {chat_id})...")

        success = False
        post_timestamp = time.time()

        try:
            chat = await resolve_chat_entity(chat_id)
            post_text = get_custom_message()
            sent_message = await user.send_message(chat, post_text)

            success = True
            success_msg = (
                f"✅ **Post Successful!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"📨 **Message ID:** `{sent_message.id}`"
            )
            logger.info(f"SUCCESS: Posted to '{group_title}' ({chat_id})")
            await notify_admin(success_msg)

        except FloodWaitError as e:
            err_msg = (
                f"❌ **Post Failed (FloodWait)!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⏱️ **Wait Required:** `{e.seconds}` seconds"
            )
            logger.error(f"FAILED: Post to '{group_title}' ({chat_id}) - FloodWait: {e.seconds}s")
            await notify_admin(err_msg)

        except Exception as e:
            err_msg = (
                f"❌ **Post Failed!**\n\n"
                f"📌 **Group:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ **Error:** `{str(e)}`"
            )
            logger.error(f"FAILED: Post to '{group_title}' ({chat_id}) - {str(e)}")
            await notify_admin(err_msg)

        finally:
            update_last_posted(chat_id, post_timestamp)
            await asyncio.sleep(POST_DELAY_SECONDS)

        return success
