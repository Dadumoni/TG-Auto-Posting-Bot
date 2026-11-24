from telethon import events, utils
from bot.config import ADMIN_ID
from bot.database import (
    is_posting_active,
    set_bot_posting_status,
    get_all_groups_db,
    get_all_custom_messages,
    set_custom_message,
)
from bot.utils import parse_chat_target, resolve_chat_entity, detect_group_cooldown


def register_base_commands(bot):
    """Register core utility and configuration bot commands."""

    @bot.on(events.NewMessage(pattern=r'^/start$'))
    async def start_cmd(event):
        if not event.is_private:
            return
        groups_count = len(get_all_groups_db())
        status_icon = "🟢 Active (Running)" if is_posting_active() else "🔴 Stopped (Paused)"
        await event.respond(
            f"👋 **Welcome to Group Manager & Auto-Scheduler Bot!**\n\n"
            f"⚡ **Bot Status:** {status_icon}\n"
            f"📊 **Total Active Groups:** `{groups_count}`\n\n"
            "**Control Commands:**\n"
            "• `/stop` - Stop all auto-posting across all groups\n"
            "• `/restart` - Resume/restart scheduled auto-posting\n\n"
            "**Ways to Add Groups:**\n"
            "1. Send a public or private Telegram link / @username.\n"
            "2. Forward any message directly from the target group.\n"
            "3. Use `/add_group <target>` command.\n\n"
            "**Message Template Commands:**\n"
            "• `/set_message <text>` - Set default post message\n"
            "• `/set_tme_message <text>` - Set post message with t.me link only\n"
            "• `/set_domain_message <text>` - Set post message with domain/external link\n"
            "• `/get_message` - View all configured message templates\n\n"
            "**Group Management Commands:**\n"
            "• `/add_group <target>` - Add group (detects cooldown & sends initial post)\n"
            "• `/remove_group <id>` - Remove a group from scheduler\n"
            "• `/remove_all` - Clear all groups from database\n"
            "• `/all_groups` - List scheduled groups, link types, and countdowns\n"
            "• `/debug <target>` - Check Userbot access & slowmode cooldown"
        )

    @bot.on(events.NewMessage(pattern=r'^/stop$'))
    async def stop_cmd(event):
        if not event.is_private:
            return
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized. Only the bot admin can stop auto-posting.")
            return

        set_bot_posting_status(False)
        await event.respond(
            "🛑 **Auto-Posting Paused!**\n\n"
            "The bot has been stopped and will **not** post to any group.\n"
            "• All automatic scheduler cycles are paused.\n"
            "• Any newly added groups will be registered but won't receive posts until resumed.\n\n"
            "💡 _Use `/restart` or `/resume` to resume auto-posting at any time._"
        )

    @bot.on(events.NewMessage(pattern=r'^/(?:restart|resume)$'))
    async def restart_cmd(event):
        if not event.is_private:
            return
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized. Only the bot admin can restart auto-posting.")
            return

        set_bot_posting_status(True)
        await event.respond(
            "▶️ **Auto-Posting Resumed & Restarted!**\n\n"
            "The bot is now fully active.\n"
            "• Scheduled posts will continue according to their randomized intervals.\n"
            "• Cooldowns and link type policies remain fully enforced.\n\n"
            "💡 _Use `/stop` to pause posting whenever needed._"
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
            cooldown_val = await detect_group_cooldown(chat)
            cooldown_str = f"`{cooldown_val}s`" if cooldown_val > 0 else "`None`"

            await status_msg.edit(
                f"✅ **Target Accessible by Userbot!**\n\n"
                f"• **Title:** {title}\n"
                f"• **Peer ID:** `{peer_id}`\n"
                f"• **Entity Type:** `{type(chat).__name__}`\n"
                f"• **Slowmode Cooldown:** {cooldown_str}"
            )
        except Exception as e:
            await status_msg.edit(
                f"❌ **NOT FOUND or INACCESSIBLE!**\n\n"
                f"**Error:** `{e}`\n\n"
                "**Check:** Ensure the account associated with `SESSION_STRING` has joined this chat."
            )

    @bot.on(events.NewMessage(pattern=r'^/set_message(?:\s|$)'))
    async def set_message_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_message Enter your default post text here...`")
            return
        custom_text = parts[1]
        if set_custom_message(custom_text, msg_type="default"):
            await event.respond(f"✅ **Default Post Message Saved!**\n\n**Preview:**\n{custom_text}")
        else:
            await event.respond("❌ Failed to save message. Database connection error.")

    @bot.on(events.NewMessage(pattern=r'^/(?:set_tme_message|set_message_tme)(?:\\s|$)'))
    async def set_tme_message_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_tme_message Enter text with t.me link here...`")
            return
        custom_text = parts[1]
        if set_custom_message(custom_text, msg_type="t_me"):
            await event.respond(f"✅ **t.me Only Post Message Saved!**\n\n**Preview:**\n{custom_text}")
        else:
            await event.respond("❌ Failed to save message. Database connection error.")

    @bot.on(events.NewMessage(pattern=r'^/(?:set_domain_message|set_message_domain)(?:\\s|$)'))
    async def set_domain_message_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_domain_message Enter text with external domain link here...`")
            return
        custom_text = parts[1]
        if set_custom_message(custom_text, msg_type="domain"):
            await event.respond(f"✅ **Domain / External Post Message Saved!**\n\n**Preview:**\n{custom_text}")
        else:
            await event.respond("❌ Failed to save message. Database connection error.")

    @bot.on(events.NewMessage(pattern=r'^/get_message$'))
    async def get_message_cmd(event):
        if not event.is_private:
            return
        all_msgs = get_all_custom_messages()
        default_txt = all_msgs.get("default") or "_(Not set - uses fallback)_"
        tme_txt = all_msgs.get("t_me") or "_(Not set - falls back to default)_"
        domain_txt = all_msgs.get("domain") or "_(Not set - falls back to default)_"

        reply = (
            "📌 **Configured Post Message Templates:**\n\n"
            f"**1. Default Post Message:**\n{default_txt}\n\n"
            "──────────────────\n"
            f"**2. t.me Only Template:**\n{tme_txt}\n\n"
            "──────────────────\n"
            f"**3. Domain / External Template:**\n{domain_txt}\n\n"
            "💡 _Use `/set_message`, `/set_tme_message`, and `/set_domain_message` to customize._"
        )
        await event.respond(reply)
