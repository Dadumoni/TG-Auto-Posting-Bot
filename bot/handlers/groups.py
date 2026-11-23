import time
from telethon import events, utils
from bot.config import logger
from bot.database import (
    is_group_exists,
    add_group_db,
    remove_group_db,
    remove_all_groups_db,
    get_all_groups_db,
)
from bot.services import post_to_single_group
from bot.utils import parse_chat_target, resolve_chat_entity


async def process_add_group(event, raw_target, source_desc=""):
    """
    Resolve and save a target chat into the database, then trigger an immediate first post.
    """
    status_msg = await event.respond("🔍 Detecting target and verifying userbot access...")
    try:
        chat = await resolve_chat_entity(raw_target)
        chat_id = utils.get_peer_id(chat)
        group_title = getattr(chat, 'title', getattr(chat, 'first_name', 'Target Group'))

        if is_group_exists(chat_id):
            await status_msg.edit(
                f"⚠️ **Group Already Saved!** {source_desc}\n"
                f"📌 **Title:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`"
            )
            return

        add_group_db(chat_id, group_title)
        await status_msg.edit(
            f"✅ **Group Added Successfully!** {source_desc}\n"
            f"📌 **Title:** {group_title}\n"
            f"🆔 **ID:** `{chat_id}`\n\n"
            "🔄 Dispatching immediate initial post to queue..."
        )
        await post_to_single_group(chat_id, group_title)
    except Exception as e:
        logger.error(f"Error adding group {raw_target}: {e}")
        await status_msg.edit(
            f"❌ **Failed to Add Group:** `{str(e)}`\n\n"
            f"💡 _Tip: Run `/debug {raw_target}` to verify whether your userbot account is a member of this chat._"
        )


def register_group_handlers(bot):
    """Register all group-management command handlers with the bot client."""

    @bot.on(events.NewMessage(pattern=r'^/add_group'))
    async def add_group_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond(
                "❌ **Usage:** `/add_group <link_or_id>`\n"
                "Example: `/add_group https://t.me/c/1234567890/123` or `/add_group -100123456789`"
            )
            return
        raw_target = parse_chat_target(parts[1])
        await process_add_group(event, raw_target, source_desc="(/add_group command)")

    @bot.on(events.NewMessage(pattern=r'^/remove_group'))
    async def remove_group_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split()
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/remove_group <chat_id>`\nExample: `/remove_group -100123456789`")
            return
        try:
            chat_id = int(parts[1].strip())
            if not is_group_exists(chat_id):
                await event.respond("❌ This group was not found in the database.")
                return
            remove_group_db(chat_id)
            await event.respond(f"✅ Group `{chat_id}` has been removed from database and scheduler.")
        except ValueError:
            await event.respond("❌ Please provide a valid numeric Group ID.")

    @bot.on(events.NewMessage(pattern=r'^/remove_all$'))
    async def remove_all_groups_cmd(event):
        if not event.is_private:
            return
        result = remove_all_groups_db()
        deleted_count = result.deleted_count if result else 0
        await event.respond(f"✅ A total of **{deleted_count}** groups were removed from the database.")

    @bot.on(events.NewMessage(pattern=r'^/all_groups$'))
    async def all_groups_cmd(event):
        if not event.is_private:
            return
        groups = get_all_groups_db()
        total_count = len(groups)
        if not groups:
            await event.respond("📊 **Total Groups:** `0`\n📂 No groups are currently saved in the database.")
            return

        text = f"📊 **Total Groups:** `{total_count}`\n\n📋 **Scheduled Groups in Database:**\n\n"
        current_time = time.time()
        for group in groups:
            title = group.get("title", "Unknown")
            cid = group.get("chat_id")
            last_posted = group.get("last_posted", 0)
            elapsed = current_time - last_posted
            time_left = max(0, int((3600 - elapsed) / 60))
            text += f"• **{title}** (`{cid}`)\n  └ ⏱️ Next Post In: ~{time_left} mins\n\n"

        await event.respond(text)
