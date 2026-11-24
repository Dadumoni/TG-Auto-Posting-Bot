from telethon import events, utils
from bot.config import ADMIN_ID, logger
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

    @bot.on(events.NewMessage(pattern=r'(?i)^/start(?:@\w+)?(?:\s|$)'))
    async def start_cmd(event):
        if not event.is_private:
            return
        try:
            groups_count = len(get_all_groups_db())
            status_icon = "🟢 Active" if is_posting_active() else "🔴 Stopped"
            await event.respond(
                f"👋 **Group Auto-Poster Bot**\n\n"
                f"⚡ **Status:** {status_icon} | 📊 **Groups:** `{groups_count}`\n\n"
                "📋 **Commands:**\n"
                "• `/all_groups` - View scheduled groups & countdowns\n"
                "• `/add_group <target>` - Add group (or forward message/link)\n"
                "• `/remove_group <id>` - Remove a group\n"
                "• `/set_message <text>` - Set post message\n"
                "• `/get_message` - View message templates\n"
                "• `/stop` / `/restart` - Pause / resume auto-posting\n"
                "• `/debug <target>` - Test group access & slowmode"
            )
        except Exception as e:
            logger.error(f"Error in start_cmd: {e}")
            await event.respond("❌ An error occurred. Please verify database connectivity.")

    @bot.on(events.NewMessage(pattern=r'(?i)^/stop(?:@\w+)?(?:\s|$)'))
    async def stop_cmd(event):
        if not event.is_private:
            return
        try:
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
        except Exception as e:
            logger.error(f"Error in stop_cmd: {e}")
            await event.respond(f"❌ Failed to stop auto-posting: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/(?:restart|resume)(?:@\w+)?(?:\s|$)'))
    async def restart_cmd(event):
        if not event.is_private:
            return
        try:
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
        except Exception as e:
            logger.error(f"Error in restart_cmd: {e}")
            await event.respond(f"❌ Failed to restart auto-posting: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/debug(?:@\w+)?(?:\s|$)'))
    async def debug_cmd(event):
        if not event.is_private:
            return
        try:
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
        except Exception as e:
            logger.error(f"Error in debug_cmd: {e}")
            await event.respond(f"❌ Debug command failed: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/set_message(?:@\w+)?(?:\s|$)'))
    async def set_message_cmd(event):
        if not event.is_private:
            return
        try:
            parts = (event.text or "").split(maxsplit=1)
            if len(parts) < 2:
                await event.respond("❌ **Usage:** `/set_message Enter your default post text here...`")
                return
            custom_text = parts[1]
            if set_custom_message(custom_text, msg_type="default"):
                await event.respond(f"✅ **Default Post Message Saved!**\n\n**Preview:**\n{custom_text}")
            else:
                await event.respond("❌ Failed to save message. Database connection error.")
        except Exception as e:
            logger.error(f"Error in set_message_cmd: {e}")
            await event.respond(f"❌ Failed to save default message: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/(?:set_tme_message|set_message_tme)(?:@\w+)?(?:\s|$)'))
    async def set_tme_message_cmd(event):
        if not event.is_private:
            return
        try:
            parts = (event.text or "").split(maxsplit=1)
            if len(parts) < 2:
                await event.respond("❌ **Usage:** `/set_tme_message Enter text with t.me link here...`")
                return
            custom_text = parts[1]
            if set_custom_message(custom_text, msg_type="t_me"):
                await event.respond(f"✅ **t.me Only Post Message Saved!**\n\n**Preview:**\n{custom_text}")
            else:
                await event.respond("❌ Failed to save message. Database connection error.")
        except Exception as e:
            logger.error(f"Error in set_tme_message_cmd: {e}")
            await event.respond(f"❌ Failed to save t.me message: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/(?:set_domain_message|set_message_domain)(?:@\w+)?(?:\s|$)'))
    async def set_domain_message_cmd(event):
        if not event.is_private:
            return
        try:
            parts = (event.text or "").split(maxsplit=1)
            if len(parts) < 2:
                await event.respond("❌ **Usage:** `/set_domain_message Enter text with external domain link here...`")
                return
            custom_text = parts[1]
            if set_custom_message(custom_text, msg_type="domain"):
                await event.respond(f"✅ **Domain / External Post Message Saved!**\n\n**Preview:**\n{custom_text}")
            else:
                await event.respond("❌ Failed to save message. Database connection error.")
        except Exception as e:
            logger.error(f"Error in set_domain_message_cmd: {e}")
            await event.respond(f"❌ Failed to save domain message: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/get_message(?:@\w+)?(?:\s|$)'))
    async def get_message_cmd(event):
        if not event.is_private:
            return
        try:
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
        except Exception as e:
            logger.error(f"Error in get_message_cmd: {e}")
            await event.respond(f"❌ Failed to retrieve messages: `{e}`")
