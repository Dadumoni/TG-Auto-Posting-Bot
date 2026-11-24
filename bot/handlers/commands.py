import asyncio
import re
import time
from telethon import events, Button
from telethon.tl.types import Channel
from bot.client import bot, user
from bot.config import ADMIN_ID, logger
from bot.database import (
    is_posting_active,
    set_bot_posting_status,
    get_all_groups_db,
    remove_group_db,
    remove_all_groups_db,
    get_all_custom_messages,
    set_custom_message,
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
from bot.utils import parse_chat_target, resolve_chat_entity, detect_group_cooldown

# In-memory storage for interactive /set_message link prompt flow
pending_link_config = {}


def register_command_handlers():
    """Register core utility and configuration bot commands."""

    @bot.on(events.NewMessage(pattern=r'(?i)^/start(?:@\w+)?(?:\s|$)'))
    async def start_cmd(event):
        if not event.is_private:
            return
        try:
            groups_count = len(get_all_groups_db())
            if is_flood_locked():
                lock_info = get_flood_safety_lock() or {}
                rem_secs = max(0, int(lock_info.get("cooloff_until", 0) - time.time()))
                rem_hrs = int(rem_secs // 3600)
                rem_mins = int((rem_secs % 3600) // 60)
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
                "• `/add_text <texts>` - Add custom texts {text1, text2}\n"
                "• `/set_message` - Configure links & post text\n"
                "• `/get_message` - View configured links & previews\n"
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

            lock_note = ""
            if is_flood_locked():
                clear_flood_safety_lock()
                lock_note = "\n• ⚠️ Emergency 6-hour FloodWait safety lock was cleared by Admin override."

            set_bot_posting_status(True)
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

    @bot.on(events.NewMessage(pattern=r'(?i)^/debug(?:@\w+)?(?:\s|$)'))
    async def debug_cmd(event):
        if not event.is_private:
            return
        parts = event.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/debug <group_id|username|link>`")
            return

        target = parts[1].strip()
        chat_identifier = parse_chat_target(target)
        status_msg = await event.respond(f"🔍 Inspecting `{target}` with Userbot...")

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

    @bot.on(events.NewMessage(pattern=r'(?i)^/remove_all(?:@\w+)?(?:\s|$)'))
    async def remove_all_cmd(event):
        if not event.is_private:
            return
        try:
            res = remove_all_groups_db()
            deleted = res.deleted_count if res else 0
            await event.respond(f"🗑️ Successfully removed **{deleted}** groups from the database.")
        except Exception as e:
            logger.error(f"Error in remove_all_cmd: {e}")
            await event.respond("❌ Failed to clear groups from database.")

    @bot.on(events.NewMessage(pattern=r'(?i)^/remove_group(?:@\w+)?(?:\s|$)'))
    async def remove_group_cmd(event):
        if not event.is_private:
            return
        parts = event.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/remove_group <chat_id>`")
            return

        try:
            target_id = int(parts[1].strip())
            if remove_group_db(target_id):
                await event.respond(f"✅ Group `{target_id}` removed from database.")
            else:
                await event.respond(f"⚠️ Group `{target_id}` not found in database.")
        except ValueError:
            await event.respond("❌ Invalid chat ID. Please provide a numeric group ID.")
        except Exception as e:
            logger.error(f"Error in remove_group_cmd: {e}")
            await event.respond(f"❌ Failed to remove group: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/all_groups(?:@\w+)?(?:\s|$)'))
    async def all_groups_cmd(event):
        if not event.is_private:
            return
        try:
            groups = get_all_groups_db()
            if not groups:
                await event.respond("📭 No groups are currently scheduled in the database.")
                return

            now = time.time()
            header = f"📊 **Scheduled Groups ({len(groups)} total):**\n\n"
            group_lines = []

            for i, g in enumerate(groups, start=1):
                raw_title = str(g.get('title', 'Unknown Group'))
                safe_title = (
                    raw_title.replace('*', '')
                    .replace('_', ' ')
                    .replace('`', '')
                    .replace('[', '(')
                    .replace(']', ')')
                )
                chat_id = g.get('chat_id', 'Unknown')
                cooldown = g.get('cooldown_seconds', 0)
                link_type = g.get('link_type', 't_me')
                allow_text = g.get('allow_text', True)
                next_post_at = g.get('next_post_at', 0)

                if next_post_at > now:
                    remaining = int(next_post_at - now)
                    next_str = f"in {remaining}s"
                else:
                    next_str = "due now"

                cooldown_str = f"{cooldown}s" if cooldown > 0 else "None"
                link_badge = "t.me" if link_type == "t_me" else "Domain"
                mode_badge = "Text+Emoji" if allow_text else "LinkOnly"

                group_lines.append(
                    f"{i}. **{safe_title}**\n"
                    f"   • ID: `{chat_id}` | Cooldown: `{cooldown_str}`\n"
                    f"   • Policy: `{link_badge}` | `{mode_badge}`\n"
                    f"   • Next Post: `{next_str}`"
                )

            # Split message into chunks if larger than 3500 characters
            chunk = header
            for line in group_lines:
                if len(chunk) + len(line) + 2 > 3500:
                    await event.respond(chunk)
                    chunk = ""
                chunk += line + "\n\n"

            if chunk.strip():
                await event.respond(chunk)

        except Exception as e:
            logger.error(f"Error in all_groups_cmd: {e}")
            await event.respond(f"❌ Failed to retrieve groups: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/set_message(?:@\w+)?(?:\s|$)'))
    async def set_message_interactive_cmd(event):
        """
        Interactive /set_message handler:
        Asks whether the admin wants to configure t.me link or External/Domain link,
        or set the base promo message text directly.
        """
        if not event.is_private:
            return
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized. Only the bot admin can set message templates.")
            return

        parts = event.text.split(maxsplit=1)
        # If user passed text directly with command
        if len(parts) > 1:
            raw_text = parts[1].strip()
            # If it looks like a URL, save as link
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

        # Interactive inline button prompt
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

    @bot.on(events.CallbackQuery(pattern=r'^cfglink_'))
    async def link_config_callback(event):
        """Handle inline button selection for /set_message."""
        user_id = event.sender_id
        if ADMIN_ID != 0 and user_id != ADMIN_ID:
            await event.answer("⚠️ Unauthorized", alert=True)
            return

        action = event.data.decode("utf-8")
        if action == "cfglink_cancel":
            await event.delete()
            return

        if action == "cfglink_tme":
            pending_link_config[user_id] = {"target": "t_me", "time": time.time()}
            prompt_text = (
                "🔗 **Please send your `t.me` link now:**\n\n"
                "_Example:_ `https://t.me/hivezonebd` or `t.me/mychannel`\n\n"
                "⏱️ _Reply within 60 seconds._"
            )
        elif action == "cfglink_domain":
            pending_link_config[user_id] = {"target": "domain", "time": time.time()}
            prompt_text = (
                "🌐 **Please send your External / Domain link now:**\n\n"
                "_Example:_ `https://hivezonebd.pages.dev`\n\n"
                "⏱️ _Reply within 60 seconds._"
            )
        elif action == "cfglink_text":
            pending_link_config[user_id] = {"target": "text", "time": time.time()}
            prompt_text = (
                "📝 **Please send the Post Header Text:**\n\n"
                "_Example:_ `Best Channel For Updates`\n\n"
                "⏱️ _Reply within 60 seconds._"
            )
        else:
            return

        await event.edit(prompt_text, buttons=[Button.inline("❌ Cancel", data=b"cfglink_cancel")])
        await event.answer()

    @bot.on(events.NewMessage())
    async def capture_link_input(event):
        """Capture text reply for pending /set_message configuration and auto-clean messages."""
        if not event.is_private:
            return
        user_id = event.sender_id
        if user_id not in pending_link_config:
            return

        # Skip if message is a command
        if (event.text or "").startswith("/"):
            return

        pending = pending_link_config.pop(user_id)
        if time.time() - pending.get("time", 0) > 120:
            return

        target = pending.get("target")
        raw_val = (event.text or "").strip()

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

        # Auto-delete confirmation and prompt after 2 seconds to keep chat clean
        await asyncio.sleep(2)
        try:
            await saved_msg.delete()
            await event.delete()
        except Exception as e:
            logger.debug(f"Could not auto-delete link setup messages: {e}")

    # Legacy command variants for backwards compatibility
    @bot.on(events.NewMessage(pattern=r'(?i)^/set_tme_message(?:@\w+)?(?:\s|$)'))
    async def set_tme_msg_cmd(event):
        if not event.is_private:
            return
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized.")
            return
        parts = event.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_tme_message <t.me link>`")
            return
        link = parts[1].strip()
        set_link_db("t_me", link)
        await event.respond(f"✅ **t.me Link Saved!**\n\n`{link}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/set_domain_message(?:@\w+)?(?:\s|$)'))
    async def set_domain_msg_cmd(event):
        if not event.is_private:
            return
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized.")
            return
        parts = event.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("❌ **Usage:** `/set_domain_message <external url>`")
            return
        link = parts[1].strip()
        set_link_db("domain", link)
        await event.respond(f"✅ **Domain / External Link Saved!**\n\n`{link}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/add_text(?:@\w+)?(?:\s|$)'))
    async def add_text_cmd(event):
        """Add single or multiple custom promotional texts to rotation pool."""
        if not event.is_private:
            return
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized. Only the bot admin can add custom texts.")
            return

        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2:
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
        # Remove surrounding curly braces if present
        if raw.startswith('{') and raw.endswith('}'):
            raw = raw[1:-1].strip()

        # Split by comma
        new_items = [t.strip() for t in raw.split(',') if t.strip()]
        if not new_items:
            await event.respond("❌ Please provide at least one valid text.")
            return

        updated_list = add_custom_texts_db(new_items)
        added_str = "\n".join(f"• `{t}`" for t in new_items)
        total_str = "\n".join(f"{i+1}. `{t}`" for i, t in enumerate(updated_list))

        await event.respond(
            f"✅ **Custom Text(s) Saved to Rotation Pool!**\n\n"
            f"➕ **Newly Added ({len(new_items)}):**\n{added_str}\n\n"
            f"📋 **Total Texts in Pool ({len(updated_list)}):**\n{total_str}\n\n"
            "🎲 _The bot will randomly pick one of these texts + emoji for each group post._"
        )

    @bot.on(events.NewMessage(pattern=r'(?i)^/(?:clear_texts|clear_text)(?:@\w+)?(?:\s|$)'))
    async def clear_texts_cmd(event):
        """Clear custom texts rotation pool."""
        if not event.is_private:
            return
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.respond("⚠️ Unauthorized. Only the bot admin can clear texts.")
            return

        clear_custom_texts_db()
        await event.respond("🗑️ **Custom texts pool cleared.** Bot will use fallback header or links.")

    @bot.on(events.NewMessage(pattern=r'(?i)^/get_message(?:@\w+)?(?:\s|$)'))
    async def get_message_cmd(event):
        if not event.is_private:
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
