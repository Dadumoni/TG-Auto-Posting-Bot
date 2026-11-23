from telethon import events, utils
from bot.database import (
    get_all_groups_db,
    get_custom_message,
    set_custom_message,
)
from bot.utils import parse_chat_target, resolve_chat_entity


def register_base_commands(bot):
    """Register core utility and configuration bot commands."""

    @bot.on(events.NewMessage(pattern=r'^/start$'))
    async def start_cmd(event):
        if not event.is_private:
            return
        groups_count = len(get_all_groups_db())
        await event.respond(
            f"👋 **Welcome to Group Manager & Auto-Scheduler Bot!**\n"
            f"📊 **Total Active Groups:** `{groups_count}`\n\n"
            "**Ways to Add Groups:**\n"
            "1. Send a public or private Telegram link / @username.\n"
            "2. Forward any message directly from the target group.\n"
            "3. Use `/add_group <target>` command.\n\n"
            "**Available Commands:**\n"
            "• `/set_message <text>` - Configure promotional post message\n"
            "• `/get_message` - View the saved post message\n"
            "• `/add_group <target>` - Add group by link, username, or ID\n"
            "• `/remove_group <id>` - Remove a group from scheduler\n"
            "• `/remove_all` - Clear all groups from database\n"
            "• `/all_groups` - List all scheduled groups and countdowns\n"
            "• `/debug <target>` - Check Userbot access to a group"
        )

    @bot.on(events.NewMessage(pattern=r'^/debug'))
    async def debug_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/debug https://t.me/...` or `/debug -100123456789`")
            return

        raw_target = parse_chat_target(parts[1])
        status_msg = await event.respond(f"🔍 Checking Userbot access for `{raw_target}`...")
        try:
            chat = await resolve_chat_entity(raw_target)
            peer_id = utils.get_peer_id(chat)
            title = getattr(chat, 'title', getattr(chat, 'first_name', 'Target'))
            await status_msg.edit(
                f"✅ **Target Accessible by Userbot!**\n\n"
                f"• **Title:** {title}\n"
                f"• **Peer ID:** `{peer_id}`\n"
                f"• **Entity Type:** `{type(chat).__name__}`"
            )
        except Exception as e:
            await status_msg.edit(
                f"❌ **NOT FOUND or INACCESSIBLE!**\n\n"
                f"**Error:** `{e}`\n\n"
                "**Check:** Ensure the account associated with `SESSION_STRING` has joined this chat."
            )

    @bot.on(events.NewMessage(pattern=r'^/set_message'))
    async def set_message_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_message Enter your post text here...`")
            return
        custom_text = parts[1]
        if set_custom_message(custom_text):
            await event.respond(f"✅ **New Post Message Saved!**\n\n**Preview:**\n{custom_text}")
        else:
            await event.respond("❌ Failed to save message. Database connection error.")

    @bot.on(events.NewMessage(pattern=r'^/get_message$'))
    async def get_message_cmd(event):
        if not event.is_private:
            return
        msg = get_custom_message()
        await event.respond(f"📌 **Current Saved Post Message:**\n\n{msg}")
