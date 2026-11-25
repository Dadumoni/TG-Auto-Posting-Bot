import asyncio
import time
from telethon import events, utils, Button
from bot.config import logger, ADMIN_ID
from bot.database import (
    is_posting_active,
    is_flood_locked,
    get_flood_safety_lock,
    is_group_exists,
    get_group_db,
    add_group_db,
    update_group_link_type,
    update_group_text_policy,
    remove_group_db,
    remove_all_groups_db,
    get_all_groups_db,
)
from bot.services import post_to_single_group, calculate_next_post_timestamp
from bot.utils import (
    parse_chat_target,
    resolve_chat_entity,
    detect_group_cooldown,
    schedule_message_cleanup,
)


def escape_md(text: str) -> str:
    """Strip markdown characters from group titles to prevent parsing failures."""
    if not text:
        return "Unknown"
    for char in ['*', '_', '`', '[', ']', '~']:
        text = text.replace(char, '')
    return text.strip()


def _is_authorized(event) -> bool:
    """Verify sender is authorized admin when ADMIN_ID is configured."""
    return ADMIN_ID == 0 or event.sender_id == ADMIN_ID


async def process_add_group(event, raw_target, source_desc=""):
    """
    Resolve and save a target chat into the database, detect slowmode cooldown,
    send interactive inline buttons for policy selection, and dispatch an immediate initial post.
    """
    status_msg = await event.respond("🔍 Detecting target and verifying userbot access...")
    try:
        chat = await resolve_chat_entity(raw_target)
        chat_id = utils.get_peer_id(chat)
        raw_title = getattr(chat, 'title', getattr(chat, 'first_name', 'Target Group'))
        group_title = escape_md(raw_title)

        if is_group_exists(chat_id):
            await status_msg.edit(
                f"⚠️ **Group Already Saved!** {source_desc}\n"
                f"📌 **Title:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`"
            )
            schedule_message_cleanup(status_msg, event, delay=10.0)
            return

        # Detect native Telegram slowmode/cooldown timer
        cooldown_seconds = await detect_group_cooldown(chat)
        initial_next_post = calculate_next_post_timestamp({"cooldown_seconds": cooldown_seconds})

        # Save with default policy (link_type="t_me", allow_text=True)
        saved = add_group_db(
            chat_id=chat_id,
            title=group_title,
            cooldown_seconds=cooldown_seconds,
            link_type="t_me",
            allow_text=True,
            next_post_at=initial_next_post,
        )
        if not saved:
            await status_msg.edit(
                "❌ **Failed to Save Group:** Database is not connected (`MONGO_URI` missing or unreachable)."
            )
            return

        logger.info(
            f"[GROUP] Added '{group_title}' (chat_id={chat_id}, cooldown={cooldown_seconds}s) {source_desc}"
        )

        cooldown_display = f"`{cooldown_seconds}s`" if cooldown_seconds > 0 else "`None`"
        is_active = is_posting_active()
        is_locked = is_flood_locked()

        if is_locked:
            status_note = "🛑 Emergency 6-hour FloodWait safety lock active. Initial post queued until lock clears."
        elif not is_active:
            status_note = "⏸️ Auto-posting is currently paused (/stop). Initial post queued until /restart."
        else:
            status_note = "🔄 Dispatching immediate initial post to group..."

        await status_msg.edit(
            f"✅ **Group Added Successfully!** {source_desc}\n\n"
            f"📌 **Title:** {group_title}\n"
            f"🆔 **ID:** `{chat_id}`\n"
            f"⏱️ **Cooldown Timer:** {cooldown_display}\n"
            f"📎 **Initial Link Policy:** `t.me only`\n\n"
            f"{status_note}"
        )
        # Clean up confirmation status and user's /add_group command after 10 seconds
        schedule_message_cleanup(status_msg, event, delay=10.0)

        # Prompt Admin via interactive inline buttons to choose supported link type (Step 1 of 2)
        prompt_text = (
            f"📌 **Configure Group Policy (Step 1 of 2):**\n\n"
            f"• **Title:** {group_title}\n"
            f"• **Chat ID:** `{chat_id}`\n"
            f"• **Cooldown / Slowmode:** {cooldown_display}\n\n"
            f"🔗 **Select Supported Link Type for this group:**\n"
            f"_Choose whether this group allows external domain links or only internal t.me links:_"
        )
        buttons = [
            [
                Button.inline("🔗 t.me only", data=f"linktype:{chat_id}:t_me"),
                Button.inline("🌐 Domain / External", data=f"linktype:{chat_id}:domain"),
            ]
        ]
        try:
            await event.respond(prompt_text, buttons=buttons)
        except Exception as e:
            logger.error(f"Failed to send link-type selection prompt: {e}")

        # Trigger immediate first post asynchronously so UI stays non-blocking
        if is_active and not is_locked:
            asyncio.create_task(post_to_single_group(chat_id, group_title))

    except Exception as e:
        logger.error(f"Error adding group {raw_target}: {e}")
        await status_msg.edit(
            f"❌ **Failed to Add Group:** `{str(e)}`\n\n"
            f"💡 _Tip: Run `/debug {raw_target}` to verify whether your userbot account is a member of this chat._"
        )


def register_group_handlers(bot):
    """Register all group-management command handlers and callbacks with the bot client."""

    @bot.on(events.CallbackQuery(pattern=r'^linktype:(-?\d+):(\w+)$'))
    async def link_type_callback(event):
        """Handle inline button selection for group supported link type (Step 1)."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized. Only the bot admin can configure link types.", alert=True)
                return

            chat_id = int(event.pattern_match.group(1))
            raw_chosen = event.pattern_match.group(2)
            chosen_type = raw_chosen.decode("utf-8") if isinstance(raw_chosen, bytes) else str(raw_chosen)

            update_group_link_type(chat_id, chosen_type)
            type_label = "🔗 t.me only" if chosen_type == "t_me" else "🌐 Domain / External"
            logger.info(f"[POLICY] Group {chat_id} link_type updated to '{chosen_type}'")
            await event.answer(f"✅ Link: {type_label}")

            # Prompt Step 2: Does this group allow Custom Text & Emojis?
            group_data = get_group_db(chat_id) or {}
            group_title = escape_md(group_data.get("title", "Target Group"))
            step2_prompt = (
                f"⚙️ **Group Policy Configuration (Step 2 of 2):**\n\n"
                f"• **Group:** {group_title}\n"
                f"• **Chat ID:** `{chat_id}`\n"
                f"• **Link Type:** {type_label}\n\n"
                "📝 **Does this group allow Custom Text & Emojis?**\n"
                "_Choose 'No (Link Only)' if this group bans promotional text or emojis, so the bot only sends a single clean link._"
            )
            step2_buttons = [
                [
                    Button.inline("✅ Yes (Text + Emoji)", data=f"textpolicy:{chat_id}:yes"),
                    Button.inline("🚫 No (Link Only)", data=f"textpolicy:{chat_id}:no"),
                ]
            ]
            await event.edit(step2_prompt, buttons=step2_buttons)
        except Exception as e:
            logger.error(f"Error in link_type_callback: {e}")

    @bot.on(events.CallbackQuery(pattern=r'^textpolicy:(-?\d+):(yes|no)$'))
    async def text_policy_callback(event):
        """Handle inline button selection for group custom text & emoji support (Step 2)."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized. Only the bot admin can configure group policies.", alert=True)
                return

            chat_id = int(event.pattern_match.group(1))
            raw_choice = event.pattern_match.group(2)
            choice = raw_choice.decode("utf-8") if isinstance(raw_choice, bytes) else str(raw_choice)
            allow_text = (choice == "yes")

            update_group_text_policy(chat_id, allow_text)
            mode_label = "✅ Text & Emojis Allowed" if allow_text else "🚫 Link Only Mode"
            logger.info(f"[POLICY] Group {chat_id} allow_text updated to {allow_text}")
            await event.answer(f"✅ Group Configured: {mode_label}")

            try:
                await event.delete()
            except Exception as del_err:
                logger.debug(f"Could not delete policy prompt message: {del_err}")
        except Exception as e:
            logger.error(f"Error in text_policy_callback: {e}")

    @bot.on(events.NewMessage(pattern=r'(?i)^/add_group(?:@\w+)?(?:\s|$)'))
    async def add_group_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can add groups.")
            return

        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await event.respond(
                "❌ **Usage:** `/add_group <link_or_id>`\n\n"
                "**Examples:**\n"
                "• `/add_group @groupusername`\n"
                "• `/add_group https://t.me/c/1234567890/123`\n"
                "• `/add_group -1001234567890`"
            )
            return

        raw_target = parse_chat_target(parts[1])
        logger.info(f"[CMD] /add_group by {event.sender_id} target='{raw_target}'")
        await process_add_group(event, raw_target, source_desc="(/add_group command)")

    @bot.on(events.NewMessage(pattern=r'(?i)^/remove_group(?:@\w+)?(?:\s|$)'))
    async def remove_group_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can remove groups.")
            return

        parts = (event.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await event.respond("❌ **Usage:** `/remove_group <chat_id>`\nExample: `/remove_group -100123456789`")
            return
        try:
            chat_id = int(parts[1].strip())
            if not is_group_exists(chat_id):
                await event.respond(f"⚠️ Group `{chat_id}` was not found in the database.")
                return
            remove_group_db(chat_id)
            logger.info(f"[CMD] /remove_group removed chat_id={chat_id}")
            await event.respond(f"✅ Group `{chat_id}` has been removed from database and scheduler.")
        except ValueError:
            await event.respond("❌ Invalid chat ID. Please provide a numeric Group ID.")
        except Exception as e:
            logger.error(f"Error in remove_group_cmd: {e}")
            await event.respond(f"❌ Error removing group: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^/(?:remove_all|removeall)(?:@\w+)?(?:\s|$)'))
    async def remove_all_groups_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can clear groups.")
            return

        try:
            result = remove_all_groups_db()
            deleted_count = result.deleted_count if result else 0
            logger.info(f"[CMD] /remove_all cleared {deleted_count} groups")
            await event.respond(f"🗑️ A total of **{deleted_count}** groups were removed from the database.")
        except Exception as e:
            logger.error(f"Error in remove_all_groups_cmd: {e}")
            await event.respond(f"❌ Error clearing groups: `{e}`")

    @bot.on(events.NewMessage(pattern=r'(?i)^(?:/all_groups|/allgroups|all\s*groups)(?:@\w+)?(?:\s|$)'))
    async def all_groups_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can view groups.")
            return

        try:
            groups = get_all_groups_db()
            total_count = len(groups)
            if not groups:
                await event.respond("📭 **Total Groups:** `0`\nNo groups are currently scheduled in the database.")
                return

            current_time = time.time()
            if is_flood_locked():
                lock_info = get_flood_safety_lock() or {}
                rem_secs = max(0, int(lock_info.get("cooloff_until", 0) - current_time))
                rem_hrs, rem_mins = divmod(rem_secs // 60, 60)
                status_header = f"🛑 Status: Flood Locked ({rem_hrs}h {rem_mins}m left)"
            elif is_posting_active():
                status_header = "🟢 Status: Active (Posting Enabled)"
            else:
                status_header = "🔴 Status: Paused via /stop"

            header = f"📊 **Total Scheduled Groups:** `{total_count}` | {status_header}\n\n"
            chunk = header

            for i, group in enumerate(groups, start=1):
                raw_title = group.get("title", "Unknown")
                title = escape_md(raw_title)
                cid = group.get("chat_id")
                link_type = group.get("link_type", "t_me")
                link_badge = "🔗 t.me" if link_type == "t_me" else "🌐 Domain"
                cooldown_val = group.get("cooldown_seconds", 0)
                cooldown_badge = f"`{cooldown_val}s`" if cooldown_val > 0 else "`None`"

                next_post_at = group.get("next_post_at", current_time)
                remaining_secs = max(0, int(next_post_at - current_time))
                time_left_mins = remaining_secs // 60

                allow_text = group.get("allow_text", True)
                text_badge = "✅ Text+Emoji" if allow_text else "🚫 Link Only"
                next_label = f"in ~{time_left_mins}m ({remaining_secs}s)" if remaining_secs > 0 else "due now"

                entry = (
                    f"{i}. **{title}** (`{cid}`)\n"
                    f"   ├ 📎 Policy: {link_badge} | {text_badge}\n"
                    f"   ├ ⏱️ Cooldown: {cooldown_badge}\n"
                    f"   └ ⏳ Next Post: `{next_label}`\n\n"
                )

                if len(chunk) + len(entry) > 3500:
                    await event.respond(chunk)
                    chunk = ""
                chunk += entry

            if chunk.strip():
                await event.respond(chunk)

        except Exception as e:
            logger.error(f"Error in all_groups_cmd: {e}")
            await event.respond(f"❌ **Failed to retrieve groups:** `{e}`")
