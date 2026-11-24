import time
from telethon import events, utils, Button
from bot.config import logger, ADMIN_ID
from bot.database import (
    is_posting_active,
    is_group_exists,
    add_group_db,
    update_group_link_type,
    remove_group_db,
    remove_all_groups_db,
    get_all_groups_db,
)
from bot.services import post_to_single_group, calculate_next_post_timestamp
from bot.utils import parse_chat_target, resolve_chat_entity, detect_group_cooldown


async def process_add_group(event, raw_target, source_desc=""):
    """
    Resolve and save a target chat into the database, detect slowmode cooldown,
    send an immediate first post, and prompt the admin via inline buttons for supported link type.
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

        # Detect native Telegram slowmode/cooldown timer
        cooldown_seconds = await detect_group_cooldown(chat)
        initial_next_post = calculate_next_post_timestamp({"cooldown_seconds": cooldown_seconds})

        # Save with default link_type="t_me"
        add_group_db(
            chat_id=chat_id,
            title=group_title,
            cooldown_seconds=cooldown_seconds,
            link_type="t_me",
            next_post_at=initial_next_post,
        )

        cooldown_display = f"`{cooldown_seconds}s`" if cooldown_seconds > 0 else "`None`"
        is_active = is_posting_active()
        status_note = (
            "🔄 Dispatching immediate initial post to queue..."
            if is_active
            else "⏸️ Auto-posting is currently paused (/stop). Initial post will be queued until resumed (/restart)."
        )

        await status_msg.edit(
            f"✅ **Group Added Successfully!** {source_desc}\n\n"
            f"📌 **Title:** {group_title}\n"
            f"🆔 **ID:** `{chat_id}`\n"
            f"⏱️ **Cooldown Timer:** {cooldown_display}\n"
            f"📎 **Initial Link Policy:** `t.me only`\n\n"
            f"{status_note}"
        )

        # Trigger immediate first post to this newly added group if posting is active
        if is_active:
            await post_to_single_group(chat_id, group_title)

        # Prompt Admin via interactive inline buttons to choose supported link type
        if ADMIN_ID != 0:
            prompt_text = (
                f"📌 **New Group Registered:**\n\n"
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
                from bot.client import bot as telethon_bot
                await telethon_bot.send_message(ADMIN_ID, prompt_text, buttons=buttons)
            except Exception as e:
                logger.error(f"Failed to send link-type selection prompt to Admin: {e}")

    except Exception as e:
        logger.error(f"Error adding group {raw_target}: {e}")
        await status_msg.edit(
            f"❌ **Failed to Add Group:** `{str(e)}`\n\n"
            f"💡 _Tip: Run `/debug {raw_target}` to verify whether your userbot account is a member of this chat._"
        )


def register_group_handlers(bot):
    """Register all group-management command handlers and callbacks with the bot client."""

    @bot.on(events.CallbackQuery(pattern=r'^linktype:(-?\d+):(\w+)'))
    async def link_type_callback(event):
        """Handle inline button selection for group supported link type."""
        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            await event.answer("⚠️ Unauthorized. Only the bot admin can configure link types.", alert=True)
            return

        chat_id = int(event.pattern_match.group(1))
        chosen_type = event.pattern_match.group(2)  # 't_me' or 'domain'

        update_group_link_type(chat_id, chosen_type)
        type_label = "🔗 t.me only" if chosen_type == "t_me" else "🌐 Domain / External"
        await event.answer(f"Saved: {type_label}")

        buttons = [
            [
                Button.inline(f"{'✅ ' if chosen_type == 't_me' else ''}🔗 t.me only", data=f"linktype:{chat_id}:t_me"),
                Button.inline(f"{'✅ ' if chosen_type == 'domain' else ''}🌐 Domain / External", data=f"linktype:{chat_id}:domain"),
            ]
        ]
        await event.edit(
            f"📌 **Group Link Policy Configured!**\n\n"
            f"🆔 **Chat ID:** `{chat_id}`\n"
            f"📎 **Active Link Type:** **{type_label}**\n\n"
            f"✅ Future scheduled posts to this group will use this link template.",
            buttons=buttons,
        )

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

        status_header = "🟢 Status: Active (Posting Enabled)" if is_posting_active() else "🔴 Status: Paused via /stop"
        text = f"📊 **Total Scheduled Groups:** `{total_count}` | {status_header}\n\n"
        current_time = time.time()
        for group in groups:
            title = group.get("title", "Unknown")
            cid = group.get("chat_id")
            link_type = group.get("link_type", "t_me")
            link_badge = "🔗 t.me only" if link_type == "t_me" else "🌐 Domain / External"
            cooldown_val = group.get("cooldown_seconds", 0)
            cooldown_badge = f"`{cooldown_val}s`" if cooldown_val > 0 else "`None`"

            next_post_at = group.get("next_post_at", current_time)
            remaining_secs = max(0, int(next_post_at - current_time))
            time_left_mins = int(remaining_secs / 60)

            text += (
                f"• **{title}** (`{cid}`)\n"
                f"  ├ 📎 Policy: {link_badge}\n"
                f"  ├ ⏱️ Cooldown: {cooldown_badge}\n"
                f"  └ ⏳ Next Post: in ~{time_left_mins} mins ({remaining_secs}s)\n\n"
            )

        await event.respond(text)
