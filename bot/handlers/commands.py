import asyncio
import time
from telethon import events, Button
from telethon.tl.types import Channel
from bot.client import bot
from bot.config import ADMIN_ID, logger
from bot.database import (
    is_posting_active,
    set_bot_posting_status,
    get_all_groups_db,
    get_link_db,
    set_link_db,
    get_base_text_db,
    set_base_text_db,
    generate_group_post,
    get_custom_texts_db,
    add_custom_texts_db,
    clear_custom_texts_db,
    is_flood_locked,
    get_flood_safety_lock,
    clear_flood_safety_lock,
)
from bot.services.emergency import cancel_flood_updater_task, extend_flood_cooloff_6h
from bot.utils import (
    parse_chat_target,
    resolve_chat_entity,
    detect_group_cooldown,
    schedule_message_cleanup,
)

# In-memory storage for interactive /set_message link prompt flow
pending_link_config = {}


def is_user_waiting_input(user_id: int) -> bool:
    """Check if the user has an active interactive prompt pending in /set_message."""
    return user_id in pending_link_config


def _is_authorized(event) -> bool:
    """Verify sender is authorized admin when ADMIN_ID is configured."""
    return ADMIN_ID == 0 or event.sender_id == ADMIN_ID


def register_command_handlers(bot_instance=None):
    """Register core utility and configuration bot commands."""
    target_bot = bot_instance or bot

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/start(?:@\w+)?(?:\s|$)'))
    async def start_cmd(event):
        if not event.is_private:
            return
        try:
            groups_count = len(get_all_groups_db())
            if is_flood_locked():
                lock_info = get_flood_safety_lock() or {}
                rem_secs = max(0, int(lock_info.get("cooloff_until", 0) - time.time()))
                rem_hrs, rem_mins = divmod(rem_secs // 60, 60)
                status_icon = f"🛑 Flood Locked ({rem_hrs}h {rem_mins}m left)"
            elif is_posting_active():
                status_icon = "🟢 Active"
            else:
                status_icon = "🔴 Stopped"

            await event.respond(
                f"👋 **Group Auto-Poster Bot**\n\n"
                f"⚡ **Status:** {status_icon} | 📊 **Groups:** `{groups_count}`\n\n"
                "📋 **Commands:**\n"
                "• `/all_groups` - View scheduled groups & policies\n"
                "• `/add_group <target>` - Add group (detects cooldown & link policy)\n"
                "• `/remove_group <id>` - Remove a group\n"
                "• `/remove_all` - Clear all saved groups\n"
                "• `/add_text <texts>` - Add custom texts {text1, text2}\n"
                "• `/clear_texts` - Clear custom texts pool\n"
                "• `/set_message` - Configure links & post text\n"
                "• `/get_message` - View configured links & previews\n"
                "• `/stop` / `/restart` - Pause / resume auto-posting\n"
                "• `/debug <target>` - Test group access & slowmode"
            )
        except Exception as e:
            logger.error(f"Error in start_cmd: {e}")
            await event.respond("❌ An error occurred. Please verify database connectivity.")

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/stop(?:@\w+)?(?:\s|$)'))
    async def stop_cmd(event):
        if not event.is_private:
            return
        try:
            if not _is_authorized(event):
                await event.respond("⚠️ Unauthorized. Only the bot admin can stop auto-posting.")
                return

            set_bot_posting_status(False)
            logger.info(f"[CMD] /stop executed by {event.sender_id}")
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

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/(?:restart|resume)(?:@\w+)?(?:\s|$)'))
    async def restart_cmd(event):
        if not event.is_private:
            return
        try:
            if not _is_authorized(event):
                await event.respond("⚠️ Unauthorized. Only the bot admin can restart auto-posting.")
                return

            lock_note = ""
            if is_flood_locked() or get_flood_safety_lock():
                clear_flood_safety_lock()
                cancel_flood_updater_task()
                lock_note = "\n• ⚠️ Emergency 6-hour FloodWait safety lock was cleared by Admin override."

            set_bot_posting_status(True)
            logger.info(f"[CMD] /restart executed by {event.sender_id}")
            await event.respond(
                "▶️ **Auto-Posting Resumed & Restarted!**\n\n"
                "The bot is now fully active.\n"
                "• Scheduled posts will continue according to their randomized intervals.\n"
                f"• Cooldowns and link type policies remain fully enforced.{lock_note}\n\n"
                "💡 _Use `/stop` to pause posting whenever needed._"
            )
        except Exception as e:
            logger.error(f"Error in restart_cmd: {e}")
            await event.respond(f"❌ Failed to restart auto-posting: `{e}`")

    @target_bot.on(events.CallbackQuery(pattern=r'^floodcool:(wait6h|restart)$'))
    async def flood_cooloff_callback(event):
        """Handle Ok (Wait 6h) or Restart inline buttons on 6-hour cooloff completion."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized.", alert=True)
                return

            raw_act = event.pattern_match.group(1)
            action = raw_act.decode("utf-8") if isinstance(raw_act, bytes) else str(raw_act)

            if action == "wait6h":
                msg_id = getattr(event, "message_id", 0) or 0
                await extend_flood_cooloff_6h(alert_msg_id=msg_id)
                logger.info("[FLOOD-COOLOFF] Admin chose Ok: waiting another 6 hours.")
                await event.answer("⏳ Waiting another 6 hours before next check.")
            elif action == "restart":
                clear_flood_safety_lock()
                cancel_flood_updater_task()
                set_bot_posting_status(True)
                logger.info("[FLOOD-COOLOFF] Admin chose Restart: auto-posting resumed.")
                await event.answer("▶️ Auto-posting restarted!")
                try:
                    await event.delete()
                except Exception as del_err:
                    logger.debug(f"Could not delete cooloff prompt: {del_err}")
        except Exception as e:
            logger.error(f"Error in flood_cooloff_callback: {e}")

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/debug(?:@\w+)?(?:\s|$)'))
    async def debug_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can run diagnostics.")
            return

        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await event.respond("❌ **Usage:** `/debug <group_id|username|link>`")
            return

        target = parts[1].strip()
        chat_identifier = parse_chat_target(target)
        status_msg = await event.respond(f"🔍 Inspecting `{target}` with Userbot...")
        logger.info(f"[CMD] /debug inspecting target={chat_identifier!r}")

        try:
            entity = await resolve_chat_entity(chat_identifier)
            title = getattr(entity, 'title', getattr(entity, 'first_name', 'Unknown'))
            entity_id = entity.id
            is_channel = isinstance(entity, Channel)
            is_megagroup = getattr(entity, 'megagroup', False)

            cooldown = await detect_group_cooldown(entity)
            cooldown_info = f"`{cooldown}s`" if cooldown > 0 else "None (0s)"

            report = (
                "✅ **Target Diagnostic Result:**\n\n"
                f"📌 **Title:** {title}\n"
                f"🆔 **Entity ID:** `{entity_id}`\n"
                f"📁 **Type:** `{'Supergroup / Megagroup' if is_megagroup else ('Channel' if is_channel else 'Chat')}`\n"
                f"⏱️ **Detected Slowmode Cooldown:** {cooldown_info}\n"
                f"🤖 **Userbot Access:** Authorized"
            )
            await status_msg.edit(report)
        except Exception as e:
            logger.error(f"Debug command error for '{target}': {e}")
            await status_msg.edit(
                f"❌ **Failed to Inspect Target:**\n\n"
                f"• **Error:** `{e}`\n"
                "• Ensure the Userbot has joined the chat and has view permissions."
            )

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/set_message(?:@\w+)?(?:\s|$)'))
    async def set_message_interactive_cmd(event):
        """
        Interactive /set_message handler:
        Asks whether the admin wants to configure t.me link or External/Domain link,
        or set the base promo message text directly.
        """
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can set message templates.")
            return

        parts = (event.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            raw_text = parts[1].strip()
            if "t.me" in raw_text:
                set_link_db("t_me", raw_text)
                await event.respond(f"✅ **t.me Link Configured Successfully!**\n\n`{raw_text}`")
            elif raw_text.startswith("http://") or raw_text.startswith("https://"):
                set_link_db("domain", raw_text)
                await event.respond(f"✅ **External Domain Link Configured Successfully!**\n\n`{raw_text}`")
            else:
                set_base_text_db(raw_text)
                await event.respond(f"✅ **Base Post Text Configured Successfully!**\n\n_{raw_text}_")
            return

        buttons = [
            [
                Button.inline("🔗 t.me Link", data=b"cfglink_tme"),
                Button.inline("🌐 External / Domain", data=b"cfglink_domain"),
            ],
            [
                Button.inline("📝 Post Text", data=b"cfglink_text"),
                Button.inline("❌ Cancel", data=b"cfglink_cancel"),
            ],
        ]
        await event.respond(
            "⚙️ **Post Message Configuration:**\n\n"
            "What would you like to configure?\n\n"
            "• **t.me Link:** Used in groups that restrict outside domains\n"
            "• **External / Domain:** Used in groups that allow custom web links\n"
            "• **Post Text:** Base header text above links",
            buttons=buttons,
        )

    @target_bot.on(events.CallbackQuery(pattern=r'^cfglink_'))
    async def link_config_callback(event):
        """Handle inline button selection for /set_message."""
        user_id = event.sender_id
        if not _is_authorized(event):
            await event.answer("⚠️ Unauthorized", alert=True)
            return

        action = event.data.decode("utf-8")
        if action == "cfglink_cancel":
            pending_link_config.pop(user_id, None)
            try:
                await event.delete()
            except Exception:
                pass
            await event.answer("Cancelled")
            return

        if action == "cfglink_tme":
            prompt_text = (
                "🔗 **Please send your `t.me` link now:**\n\n"
                "_Example:_ `https://t.me/hivezonebd` or `t.me/mychannel`\n\n"
                "⏱️ _Reply within 120 seconds._"
            )
            cfg_target = "t_me"
        elif action == "cfglink_domain":
            prompt_text = (
                "🌐 **Please send your External / Domain link now:**\n\n"
                "_Example:_ `https://hivezonebd.pages.dev`\n\n"
                "⏱️ _Reply within 120 seconds._"
            )
            cfg_target = "domain"
        elif action == "cfglink_text":
            prompt_text = (
                "📝 **Please send the Post Header Text:**\n\n"
                "_Example:_ `Best Channel For Updates`\n\n"
                "⏱️ _Reply within 120 seconds._"
            )
            cfg_target = "text"
        else:
            return

        prompt_msg = await event.edit(prompt_text, buttons=[Button.inline("❌ Cancel", data=b"cfglink_cancel")])
        pending_link_config[user_id] = {
            "target": cfg_target,
            "time": time.time(),
            "prompt_msg": prompt_msg,
        }
        await event.answer()

    @target_bot.on(events.NewMessage())
    async def capture_link_input(event):
        """Capture text reply for pending /set_message configuration and auto-clean messages."""
        if not event.is_private:
            return
        user_id = event.sender_id
        if user_id not in pending_link_config:
            return

        raw_val = (event.text or "").strip()
        # If user enters a new slash command instead, exit pending prompt cleanly and let the command run
        if raw_val.startswith("/"):
            pending_link_config.pop(user_id, None)
            return

        pending = pending_link_config.pop(user_id)
        if time.time() - pending.get("time", 0) > 120:
            return

        target = pending.get("target")
        prompt_msg = pending.get("prompt_msg")

        if not raw_val:
            await event.respond("❌ Empty input ignored. Please run `/set_message` again.")
            raise events.StopPropagation

        if target == "t_me":
            set_link_db("t_me", raw_val)
            saved_msg = await event.respond(f"✅ **`t.me` Link Set Successfully!**\n\n`{raw_val}`")
        elif target == "domain":
            set_link_db("domain", raw_val)
            saved_msg = await event.respond(f"✅ **External / Domain Link Set Successfully!**\n\n`{raw_val}`")
        elif target == "text":
            set_base_text_db(raw_val)
            saved_msg = await event.respond(f"✅ **Post Header Text Set Successfully!**\n\n_{raw_val}_")
        else:
            return

        logger.info(f"[CMD] /set_message updated '{target}' via interactive flow")
        schedule_message_cleanup(prompt_msg, event, saved_msg, delay=2.0)
        raise events.StopPropagation

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/set_tme_message(?:@\w+)?(?:\s|$)'))
    async def set_tme_msg_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized.")
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await event.respond("❌ **Usage:** `/set_tme_message <t.me link>`")
            return
        link = parts[1].strip()
        set_link_db("t_me", link)
        await event.respond(f"✅ **t.me Link Saved!**\n\n`{link}`")

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/set_domain_message(?:@\w+)?(?:\s|$)'))
    async def set_domain_msg_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized.")
            return
        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await event.respond("❌ **Usage:** `/set_domain_message <external url>`")
            return
        link = parts[1].strip()
        set_link_db("domain", link)
        await event.respond(f"✅ **Domain / External Link Saved!**\n\n`{link}`")

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/add_text(?:@\w+)?(?:\s|$)'))
    async def add_text_cmd(event):
        """Add single or multiple custom promotional texts to rotation pool."""
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can add custom texts.")
            return

        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            existing = get_custom_texts_db()
            existing_str = "\n".join(f"{i+1}. `{t}`" for i, t in enumerate(existing)) if existing else "_(No custom texts added yet)_"
            await event.respond(
                "❌ **Usage:** `/add_text {text1, text2, text3}` or `/add_text {single text}`\n\n"
                "**Examples:**\n"
                "• `/add_text {Join our VIP channel, Best discounts daily, Check this out}`\n"
                "• `/add_text {Special offer today!}`\n"
                "• `/add_text Direct text without brackets`\n\n"
                f"📋 **Current Active Texts Pool ({len(existing)}):**\n{existing_str}"
            )
            return

        raw = parts[1].strip()
        if raw.startswith('{') and raw.endswith('}'):
            raw = raw[1:-1].strip()

        new_items = [t.strip() for t in raw.split(',') if t.strip()]
        if not new_items:
            await event.respond("❌ Please provide at least one valid text.")
            return

        updated_list = add_custom_texts_db(new_items)
        added_str = "\n".join(f"• `{t}`" for t in new_items)
        total_str = "\n".join(f"{i+1}. `{t}`" for i, t in enumerate(updated_list))

        logger.info(f"[CMD] /add_text added {len(new_items)} items (pool={len(updated_list)})")
        await event.respond(
            f"✅ **Custom Text(s) Saved to Rotation Pool!**\n\n"
            f"➕ **Newly Added ({len(new_items)}):**\n{added_str}\n\n"
            f"📋 **Total Texts in Pool ({len(updated_list)}):**\n{total_str}\n\n"
            "🎲 _The bot will randomly pick one of these texts + emoji for each group post._"
        )

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/(?:clear_texts|clear_text)(?:@\w+)?(?:\s|$)'))
    async def clear_texts_cmd(event):
        """Clear custom texts rotation pool."""
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can clear texts.")
            return

        clear_custom_texts_db()
        logger.info(f"[CMD] /clear_texts executed by {event.sender_id}")
        await event.respond("🗑️ **Custom texts pool cleared.** Bot will use fallback header or links.")

    @target_bot.on(events.NewMessage(pattern=r'(?i)^/get_message(?:@\w+)?(?:\s|$)'))
    async def get_message_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized.")
            return
        try:
            tme_link = get_link_db("t_me") or "_(Not set)_"
            domain_link = get_link_db("domain") or "_(Not set)_"
            custom_texts = get_custom_texts_db()

            if custom_texts:
                texts_display = "\n".join(f"{i+1}. `{t}`" for i, t in enumerate(custom_texts))
            else:
                base_fallback = get_base_text_db()
                texts_display = f"1. `{base_fallback}`" if base_fallback else "_(Not set - uses emoji only)_"

            preview_text_domain = generate_group_post("domain", allow_text=True)
            preview_linkonly_domain = generate_group_post("domain", allow_text=False)

            reply = (
                "📋 **Configured Post Message & Links:**\n\n"
                f"📝 **Custom Texts Pool ({len(custom_texts)}):**\n"
                f"{texts_display}\n\n"
                f"🔗 **t.me Link:**\n{tme_link}\n\n"
                f"🌐 **External / Domain Link:**\n{domain_link}\n\n"
                "────────────────────────\n"
                "👁️ **Preview: Text + Emoji Allowed Group:**\n\n"
                f"{preview_text_domain}\n\n"
                "────────────────────────\n"
                "👁️ **Preview: Link-Only Group (No Text/Emoji):**\n\n"
                f"{preview_linkonly_domain}\n\n"
                "💡 _Use `/add_text` to add more texts, `/set_message` to change links._"
            )
            await event.respond(reply)
        except Exception as e:
            logger.error(f"Error in get_message_cmd: {e}")
            await event.respond(f"❌ Failed to retrieve message settings: `{e}`")


# Alias for backwards compatibility
register_base_commands = register_command_handlers
