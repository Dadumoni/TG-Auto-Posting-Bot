import asyncio
from typing import Dict, Any
from telethon import events, utils, Button
from bot.config import ADMIN_ID, logger
from bot.database import (
    is_posting_active,
    set_bot_posting_status,
    get_all_groups_db,
    get_all_custom_messages,
    set_custom_message,
    get_link_db,
    set_link_db,
    get_base_text_db,
    set_base_text_db,
    generate_group_post,
)
from bot.utils import parse_chat_target, resolve_chat_entity, detect_group_cooldown

# Temporary state for interactive /set_message flow
PENDING_SET_CONFIG: Dict[int, Dict[str, Any]] = {}


def is_user_waiting_input(user_id: int) -> bool:
    """Check if the user is currently awaiting link or text input."""
    return user_id in PENDING_SET_CONFIG


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
                "• `/set_message` - Configure links & post text\n"
                "• `/get_message` - View configured links & post preview\n"
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
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized. Only the bot admin can configure post messages.")
            return

        parts = (event.text or "").split(maxsplit=1)
        if len(parts) >= 2:
            # Direct value provided via command argument
            user_input = parts[1].strip()
            if "t.me" in user_input:
                set_link_db("t_me", user_input)
                await event.respond(f"✅ **t.me Link Saved!**\n\n`{user_input}`")
            elif user_input.startswith("http://") or user_input.startswith("https://"):
                set_link_db("domain", user_input)
                await event.respond(f"✅ **External / Domain Link Saved!**\n\n`{user_input}`")
            else:
                set_base_text_db(user_input)
                await event.respond(f"✅ **Custom Header Text Saved!**\n\n`{user_input}`")
            return

        # Interactive inline button prompt
        buttons = [
            [
                Button.inline("🔗 t.me Link", data="setlink:t_me"),
                Button.inline("🌐 External Link", data="setlink:domain"),
            ],
            [
                Button.inline("📝 Custom Text", data="setlink:text"),
            ],
        ]
        prompt_text = (
            "⚙️ **Configure Auto-Post Message & Links:**\n\n"
            "Choose which element you want to configure:\n"
            "• `🔗 t.me Link` - For groups allowing only Telegram links\n"
            "• `🌐 External Link` - For groups allowing external domain links\n"
            "• `📝 Custom Text` - Promotional header text shown above links\n\n"
            "👉 _Click an option below:_"
        )
        await event.respond(prompt_text, buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=r'^setlink:(\w+)'))
    async def set_link_callback(event):
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.answer("⚠️ Unauthorized. Only the bot admin can configure settings.", alert=True)
            return

        choice = event.pattern_match.group(1).lower()
        PENDING_SET_CONFIG[event.sender_id] = {
            "target": choice,
            "msg_id": event.message_id,
        }

        if choice == "t_me":
            prompt = (
                "🔗 **Please send your t.me link now:**\n\n"
                "Example: `https://t.me/your_channel` or `https://t.me/+joinchat`\n\n"
                "_Type `/cancel` to abort._"
            )
        elif choice == "domain":
            prompt = (
                "🌐 **Please send your External / Domain link now:**\n\n"
                "Example: `https://hivezonebd.pages.dev`\n\n"
                "_Type `/cancel` to abort._"
            )
        else:
            prompt = (
                "📝 **Please send your Custom Header Text now:**\n\n"
                "Example: `Join our exclusive channel today!`\n\n"
                "_Type `/cancel` to abort._"
            )

        await event.edit(prompt, buttons=None)
        await event.answer("Waiting for your input...")

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not (e.text or "").startswith('/')))
    async def pending_config_input_handler(event):
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            return
        if event.sender_id not in PENDING_SET_CONFIG:
            return

        state = PENDING_SET_CONFIG.pop(event.sender_id)
        target = state.get("target")
        prompt_msg_id = state.get("msg_id")
        user_input = (event.text or "").strip()

        if target == "t_me":
            set_link_db("t_me", user_input)
            label = "🔗 t.me Link"
        elif target == "domain":
            set_link_db("domain", user_input)
            label = "🌐 External / Domain Link"
        elif target == "text":
            set_base_text_db(user_input)
            label = "📝 Custom Post Text"
        else:
            return

        confirm_msg = await event.respond(
            f"✅ **{label} Configured Successfully!**\n\n"
            f"`{user_input}`\n\n"
            "🧹 _Cleaning up in 2 seconds..._"
        )

        # Wait 2 seconds and delete messages to keep chat clean
        await asyncio.sleep(2)
        try:
            await confirm_msg.delete()
        except Exception:
            pass
        try:
            await event.delete()
        except Exception:
            pass
        if prompt_msg_id:
            try:
                await bot.delete_messages(event.chat_id, prompt_msg_id)
            except Exception:
                pass

    @bot.on(events.NewMessage(pattern=r'(?i)^/cancel(?:@\w+)?(?:\s|$)'))
    async def cancel_cmd(event):
        if not event.is_private:
            return
        if event.sender_id in PENDING_SET_CONFIG:
            state = PENDING_SET_CONFIG.pop(event.sender_id)
            prompt_msg_id = state.get("msg_id")
            if prompt_msg_id:
                try:
                    await bot.delete_messages(event.chat_id, prompt_msg_id)
                except Exception:
                    pass
            await event.respond("🚫 Operation cancelled.")

    @bot.on(events.NewMessage(pattern=r'(?i)^/(?:set_tme_message|set_message_tme)(?:@\w+)?(?:\s|$)'))
    async def set_tme_message_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_tme_message <t.me_link>`\nExample: `/set_tme_message https://t.me/your_channel`")
            return
        link = parts[1].strip()
        set_link_db("t_me", link)
        await event.respond(f"✅ **t.me Only Link Saved!**\n\n`{link}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/(?:set_domain_message|set_message_domain)(?:@\w+)?(?:\s|$)'))
    async def set_domain_message_cmd(event):
        if not event.is_private:
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_domain_message <domain_link>`\nExample: `/set_domain_message https://hivezonebd.pages.dev`")
            return
        link = parts[1].strip()
        set_link_db("domain", link)
        await event.respond(f"✅ **Domain / External Link Saved!**\n\n`{link}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/get_message(?:@\w+)?(?:\s|$)'))
    async def get_message_cmd(event):
        if not event.is_private:
            return
        try:
            tme_link = get_link_db("t_me") or "_(Not set)_"
            domain_link = get_link_db("domain") or "_(Not set)_"
            base_text = get_base_text_db() or "_(Not set)_"

            sample_tme = generate_group_post("t_me")
            sample_domain = generate_group_post("domain")

            reply = (
                "📋 **Configured Post Message & Links:**\n\n"
                f"📝 **Custom Text:**\n`{base_text}`\n\n"
                f"🔗 **t.me Link:**\n{tme_link}\n\n"
                f"🌐 **External / Domain Link:**\n{domain_link}\n\n"
                "────────────────────────\n"
                "👁️ **Preview (t.me Groups):**\n\n"
                f"{sample_tme}\n\n"
                "────────────────────────\n"
                "👁️ **Preview (Domain Groups):**\n\n"
                f"{sample_domain}\n\n"
                "💡 _Use `/set_message` to change links or text anytime._"
            )
            await event.respond(reply)
        except Exception as e:
            logger.error(f"Error in get_message_cmd: {e}")
            await event.respond(f"❌ Failed to retrieve message settings: `{e}`")
