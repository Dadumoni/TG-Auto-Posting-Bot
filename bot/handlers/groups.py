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
    set_group_retry_6h,
    record_failure_action_db,
    remove_group_db,
    remove_all_groups_db,
    get_all_groups_db,
    generate_group_post,
)
from bot.services import post_to_single_group, calculate_next_post_timestamp
from bot.utils import (
    parse_chat_target,
    resolve_chat_entity,
    detect_group_cooldown,
    schedule_message_cleanup,
)

# Temporary state for "Failed to Add Group" Retry/Skip buttons keyed by status message ID
pending_add_retries = {}


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


async def _execute_add_group(event, status_msg, raw_target, source_desc=""):
    """
    Core shared flow for adding or retrying a target group.
    Dispatches a single t.me link (no text/emoji/multiple links) as the initial post.
    """
    try:
        chat = await resolve_chat_entity(raw_target)
        chat_id = utils.get_peer_id(chat)
        raw_title = getattr(chat, 'title', getattr(chat, 'first_name', 'Target Group'))
        group_title = escape_md(raw_title)

        if is_group_exists(chat_id):
            await status_msg.edit(
                f"⚠️ **Group Already Saved!** {source_desc}\n"
                f"📌 **Title:** {group_title}\n"
                f"🆔 **ID:** `{chat_id}`",
                buttons=None,
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
                "❌ **Failed to Save Group:** Database is not connected (`MONGO_URI` missing or unreachable).",
                buttons=None,
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
            status_note = "🔄 Dispatching initial single t.me link post to group..."

        await status_msg.edit(
            f"✅ **Group Added Successfully!** {source_desc}\n\n"
            f"📌 **Title:** {group_title}\n"
            f"🆔 **ID:** `{chat_id}`\n"
            f"⏱️ **Cooldown Timer:** {cooldown_display}\n"
            f"📎 **Initial Post:** Single `t.me` link only\n\n"
            f"{status_note}",
            buttons=None,
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

        # Trigger immediate initial post with ONLY the single t.me link (no text, no emoji, no double links)
        if is_active and not is_locked:
            asyncio.create_task(
                post_to_single_group(chat_id, group_title, force_link_only_tme=True)
            )

    except Exception as e:
        logger.error(f"Error adding group {raw_target}: {e}")
        msg_id = getattr(status_msg, "id", 0)
        pending_add_retries[msg_id] = {
            "target": raw_target,
            "source": source_desc,
            "orig_event": event,
        }
        retry_buttons = [
            [
                Button.inline("🔄 Retry", data=f"addretry:{msg_id}"),
                Button.inline("⏭️ Skip", data=f"addskip:{msg_id}"),
            ]
        ]
        await status_msg.edit(
            f"❌ **Failed to Add Group:** `{str(e)}`\n\n"
            f"💡 _Tip: Run `/debug {raw_target}` to verify whether your userbot account is a member of this chat._",
            buttons=retry_buttons,
        )


async def process_add_group(event, raw_target, source_desc=""):
    """Respond with initial detecting message and execute add-group workflow."""
    status_msg = await event.respond("🔍 Detecting target and verifying userbot access...")
    await _execute_add_group(event, status_msg, raw_target, source_desc=source_desc)


GROUPS_PER_PAGE = 10


def _get_scheduler_status_header(current_time: float) -> str:
    """Return formatted scheduler status label for /all_groups header."""
    if is_flood_locked():
        lock_info = get_flood_safety_lock() or {}
        rem_secs = max(0, int(lock_info.get("cooloff_until", 0) - current_time))
        rem_hrs, rem_mins = divmod(rem_secs // 60, 60)
        return f"🛑 Flood Locked ({rem_hrs}h {rem_mins}m left)"
    if is_posting_active():
        return "🟢 Active (Posting Enabled)"
    return "🔴 Paused via /stop"


def _build_groups_page(page: int = 1):
    """
    Build paginated inline-button message for scheduled groups (up to 10 per page).
    Pagination controls appear only when total groups exceed 10.
    """
    groups = get_all_groups_db()
    total_count = len(groups)
    if total_count == 0:
        return None, None, 0

    total_pages = (total_count + GROUPS_PER_PAGE - 1) // GROUPS_PER_PAGE
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * GROUPS_PER_PAGE
    page_groups = groups[start_idx : start_idx + GROUPS_PER_PAGE]

    status_header = _get_scheduler_status_header(time.time())
    header = (
        f"📊 **Total Scheduled Groups:** `{total_count}` | {status_header}\n\n"
        "👇 _Click any group below to view full details:_"
    )

    buttons = []
    for g in page_groups:
        cid = g.get("chat_id")
        title = escape_md(g.get("title", "Unknown Group")) or "Unknown Group"
        btn_label = title if len(title) <= 45 else f"{title[:42]}..."
        buttons.append([Button.inline(btn_label, data=f"grpview:{cid}:{page}")])

    # Add pagination row ONLY if more than 10 groups exist
    if total_count > GROUPS_PER_PAGE:
        prev_btn = (
            Button.inline("⬅️ Prev", data=f"grppage:{page - 1}")
            if page > 1
            else Button.inline("⬅️ Prev", data=b"grppage_noop:first")
        )
        center_btn = Button.inline(f"📄 {page}/{total_pages}", data=f"grppage_noop:page_{page}_{total_pages}")
        next_btn = (
            Button.inline("Next ➡️", data=f"grppage:{page + 1}")
            if page < total_pages
            else Button.inline("Next ➡️", data=b"grppage_noop:last")
        )
        buttons.append([prev_btn, center_btn, next_btn])

    return header, buttons, total_count


def _format_elapsed(timestamp: float, current_time: float) -> str:
    """Format a past timestamp into a human-readable relative duration."""
    if not timestamp or timestamp <= 0:
        return "Not posted yet"
    ago = max(0, int(current_time - timestamp))
    if ago < 60:
        return f"{ago}s ago"
    mins, secs = divmod(ago, 60)
    if mins < 60:
        return f"{mins}m {secs}s ago"
    hrs, rem_mins = divmod(mins, 60)
    return f"{hrs}h {rem_mins}m ago"


def _format_group_detail(group: dict, index_num: int) -> str:
    """Format detailed status card for a single selected group including Last Post and Total Posts."""
    current_time = time.time()
    title = escape_md(group.get("title", "Unknown"))
    cid = group.get("chat_id")
    link_type = group.get("link_type", "t_me")
    link_badge = "🔗 t.me" if link_type == "t_me" else "🌐 Domain"
    cooldown_val = group.get("cooldown_seconds", 0)
    cooldown_str = f"{cooldown_val}s" if cooldown_val > 0 else "None"

    next_post_at = group.get("next_post_at", current_time)
    remaining_secs = max(0, int(next_post_at - current_time))
    time_left_mins = remaining_secs // 60
    if group.get("awaiting_admin_action"):
        next_label = "⏸️ Awaiting admin confirmation"
    elif remaining_secs > 0:
        next_label = f"in ~{time_left_mins}m ({remaining_secs}s)"
    else:
        next_label = "due now"

    allow_text = group.get("allow_text", True)
    text_badge = "✅ Text+Emoji" if allow_text else "🚫 Link Only"

    total_posts = int(group.get("total_posts", 0))
    last_success_ts = group.get("last_success_at", 0)
    last_post_label = _format_elapsed(last_success_ts, current_time) if total_posts > 0 or last_success_ts else "Not posted yet"

    return (
        f"**{index_num}. {title}** (`{cid}`)\n"
        f"   ├ 📎 Policy: {link_badge} | {text_badge}\n"
        f"   ├ ⏱️ Cooldown: `{cooldown_str}`\n"
        f"   ├ ⏳ Next Post: `{next_label}`\n"
        f"   ├ 🕒 Last Post: `{last_post_label}`\n"
        f"   └ 📊 Total Posts: `{total_posts}`"
    )


def _build_policy_editor(group: dict, chat_id: int, page: int):
    """Build policy update view showing current format and interactive toggle buttons."""
    title = escape_md(group.get("title", "Unknown"))
    link_type = group.get("link_type", "t_me")
    allow_text = group.get("allow_text", True)

    cur_link_label = "🔗 t.me only" if link_type == "t_me" else "🌐 Domain / External"
    cur_mode_label = "✅ Text + Emoji (Double Link)" if allow_text else "🚫 Link Only (Single Link)"
    format_preview = generate_group_post(link_type=link_type, allow_text=allow_text)

    text = (
        f"⚙️ **Update Group Policy:**\n\n"
        f"📌 **Group:** {title} (`{chat_id}`)\n"
        f"📎 **Current Link Type:** {cur_link_label}\n"
        f"📝 **Current Posting Format:** {cur_mode_label}\n\n"
        f"👁️ **Current Post Preview:**\n"
        f"```\n{format_preview}\n```\n"
        "👇 _Click any button below to update policy immediately:_"
    )

    tme_btn = Button.inline(
        f"{'✓ ' if link_type == 't_me' else ''}🔗 t.me only",
        data=f"polset:link:t_me:{chat_id}:{page}",
    )
    dom_btn = Button.inline(
        f"{'✓ ' if link_type != 't_me' else ''}🌐 Domain / External",
        data=f"polset:link:domain:{chat_id}:{page}",
    )
    yes_btn = Button.inline(
        f"{'✓ ' if allow_text else ''}✅ Text + Emoji",
        data=f"polset:text:yes:{chat_id}:{page}",
    )
    no_btn = Button.inline(
        f"{'✓ ' if not allow_text else ''}🚫 Link Only",
        data=f"polset:text:no:{chat_id}:{page}",
    )
    nav_row = [
        Button.inline("⬅️ Back to Details", data=f"grpview:{chat_id}:{page}"),
        Button.inline("📋 All Groups", data=f"grppage:{page}"),
    ]

    buttons = [[tme_btn, dom_btn], [yes_btn, no_btn], nav_row]
    return text, buttons


def register_group_handlers(bot):
    """Register all group-management command handlers and callbacks with the bot client."""

    @bot.on(events.CallbackQuery(pattern=r'^addretry:(\d+)$'))
    async def add_retry_callback(event):
        """Retry failed /add_group operation on the same status message."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized.", alert=True)
                return

            msg_id = int(event.pattern_match.group(1))
            entry = pending_add_retries.pop(msg_id, None)
            if not entry:
                await event.answer("⚠️ Retry session expired. Please send /add_group again.", alert=True)
                return

            await event.answer("🔄 Retrying...")
            status_msg = await event.edit("🔄 Retrying target detection and verifying userbot access...", buttons=None)
            await _execute_add_group(
                entry.get("orig_event"),
                status_msg,
                entry["target"],
                source_desc=entry.get("source", ""),
            )
        except Exception as e:
            logger.error(f"Error in add_retry_callback: {e}")

    @bot.on(events.CallbackQuery(pattern=r'^addskip:(\d+)$'))
    async def add_skip_callback(event):
        """Skip failed group add and clean up both the error prompt and original request."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized.", alert=True)
                return

            msg_id = int(event.pattern_match.group(1))
            entry = pending_add_retries.pop(msg_id, None)
            await event.answer("⏭️ Skipped")

            try:
                await event.delete()
            except Exception as del_err:
                logger.debug(f"Could not delete failed add message: {del_err}")

            orig_event = entry.get("orig_event") if entry else None
            if orig_event is not None:
                try:
                    await orig_event.delete()
                except Exception as del_err:
                    logger.debug(f"Could not delete original add request: {del_err}")
        except Exception as e:
            logger.error(f"Error in add_skip_callback: {e}")

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

    @bot.on(events.CallbackQuery(pattern=r'^failact:(retry6h|remove):(-?\d+)$'))
    async def failure_action_callback(event):
        """Handle admin decision (Retry After 6 Hours or Remove Group) on failed post alerts."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized. Only the bot admin can take action.", alert=True)
                return

            raw_act = event.pattern_match.group(1)
            action = raw_act.decode("utf-8") if isinstance(raw_act, bytes) else str(raw_act)
            chat_id = int(event.pattern_match.group(2))

            if action == "retry6h":
                if not is_group_exists(chat_id):
                    await event.answer("⚠️ Group is no longer in the database.", alert=True)
                else:
                    retry_at = set_group_retry_6h(chat_id, admin_id=event.sender_id)
                    record_failure_action_db(chat_id, "retry_6h", admin_id=event.sender_id)
                    logger.info(f"[FAILURE-ACTION] Group {chat_id} paused for 6 hours (retry_at={retry_at})")
                    await event.answer("♻️ Paused for 6 hours. Will retry automatically after 6h.")
            elif action == "remove":
                removed = remove_group_db(chat_id)
                record_failure_action_db(chat_id, "remove_group", admin_id=event.sender_id)
                logger.info(f"[FAILURE-ACTION] Group {chat_id} removed from DB (existed={removed})")
                await event.answer("🗑️ Group removed from database.")

            try:
                await event.delete()
            except Exception as del_err:
                logger.debug(f"Could not delete failed alert message: {del_err}")
        except Exception as e:
            logger.error(f"Error in failure_action_callback: {e}")

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
            reply_msg = await event.respond("❌ **Usage:** `/remove_group <chat_id>`\nExample: `/remove_group -100123456789`")
            schedule_message_cleanup(reply_msg, event, delay=10.0)
            return
        try:
            chat_id = int(parts[1].strip())
            if not is_group_exists(chat_id):
                reply_msg = await event.respond(f"⚠️ Group `{chat_id}` was not found in the database.")
            else:
                remove_group_db(chat_id)
                logger.info(f"[CMD] /remove_group removed chat_id={chat_id}")
                reply_msg = await event.respond(f"✅ Group `{chat_id}` has been removed from database and scheduler.")
        except ValueError:
            reply_msg = await event.respond("❌ Invalid chat ID. Please provide a numeric Group ID.")
        except Exception as e:
            logger.error(f"Error in remove_group_cmd: {e}")
            reply_msg = await event.respond(f"❌ Error removing group: `{e}`")

        schedule_message_cleanup(reply_msg, event, delay=10.0)

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

    @bot.on(events.CallbackQuery(pattern=r'^grppage:(\d+)$'))
    async def groups_page_callback(event):
        """Navigate between /all_groups pages cleanly on the same message."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized.", alert=True)
                return

            page = int(event.pattern_match.group(1))
            text, buttons, total_count = _build_groups_page(page)
            if total_count == 0:
                await event.edit("📭 **Total Groups:** `0`\nNo groups are currently scheduled in the database.")
                await event.answer()
                return

            await event.edit(text, buttons=buttons)
            await event.answer()
        except Exception as e:
            logger.error(f"Error in groups_page_callback: {e}")

    @bot.on(events.CallbackQuery(pattern=r'^grppage_noop:(\w+)$'))
    async def groups_page_noop_callback(event):
        """Provide feedback when tapping boundary/page-indicator buttons."""
        raw_tag = event.pattern_match.group(1)
        tag = raw_tag.decode("utf-8") if isinstance(raw_tag, bytes) else str(raw_tag)
        if tag == "first":
            await event.answer("Already on the first page.")
        elif tag == "last":
            await event.answer("Already on the last page.")
        else:
            await event.answer("Current page indicator.")

    @bot.on(events.CallbackQuery(pattern=r'^grpview:(-?\d+):(\d+)$'))
    async def group_detail_callback(event):
        """Show full group details with Update Policy and Back to Groups buttons."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized.", alert=True)
                return

            chat_id = int(event.pattern_match.group(1))
            page = int(event.pattern_match.group(2))

            groups = get_all_groups_db()
            target_group = None
            index_num = 1
            for idx, g in enumerate(groups, start=1):
                if g.get("chat_id") == chat_id:
                    target_group = g
                    index_num = idx
                    break

            if not target_group:
                await event.answer("⚠️ Group was removed from database.", alert=True)
                text, buttons, total_count = _build_groups_page(page)
                if total_count > 0:
                    await event.edit(text, buttons=buttons)
                else:
                    await event.edit("📭 **Total Groups:** `0`\nNo groups are currently scheduled in the database.")
                return

            detail_text = _format_group_detail(target_group, index_num)
            detail_buttons = [
                [
                    Button.inline("⚙️ Update Policy", data=f"grppol:{chat_id}:{page}"),
                    Button.inline("⬅️ Back to Groups", data=f"grppage:{page}"),
                ]
            ]
            await event.edit(detail_text, buttons=detail_buttons)
            await event.answer()
        except Exception as e:
            logger.error(f"Error in group_detail_callback: {e}")

    @bot.on(events.CallbackQuery(pattern=r'^grppol:(-?\d+):(\d+)$'))
    async def group_policy_open_callback(event):
        """Open interactive policy editor for the selected group."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized.", alert=True)
                return

            chat_id = int(event.pattern_match.group(1))
            page = int(event.pattern_match.group(2))
            group = get_group_db(chat_id)
            if not group:
                await event.answer("⚠️ Group not found in database.", alert=True)
                return

            text, buttons = _build_policy_editor(group, chat_id, page)
            await event.edit(text, buttons=buttons)
            await event.answer()
        except Exception as e:
            logger.error(f"Error in group_policy_open_callback: {e}")

    @bot.on(events.CallbackQuery(pattern=r'^polset:(link|text):(\w+):(-?\d+):(\d+)$'))
    async def group_policy_set_callback(event):
        """Update link type or text/emoji posting format directly from /all_groups policy editor."""
        try:
            if not _is_authorized(event):
                await event.answer("⚠️ Unauthorized.", alert=True)
                return

            raw_field = event.pattern_match.group(1)
            raw_val = event.pattern_match.group(2)
            field = raw_field.decode("utf-8") if isinstance(raw_field, bytes) else str(raw_field)
            val = raw_val.decode("utf-8") if isinstance(raw_val, bytes) else str(raw_val)
            chat_id = int(event.pattern_match.group(3))
            page = int(event.pattern_match.group(4))

            if field == "link":
                update_group_link_type(chat_id, val)
                toast = "✅ Link Type updated to t.me" if val == "t_me" else "✅ Link Type updated to Domain"
            else:
                allow_text = (val == "yes")
                update_group_text_policy(chat_id, allow_text)
                toast = "✅ Posting Format: Text + Emoji" if allow_text else "✅ Posting Format: Link Only"

            logger.info(f"[POLICY] Group {chat_id} updated via /all_groups ({field}={val})")
            group = get_group_db(chat_id)
            if not group:
                await event.answer("⚠️ Group not found.", alert=True)
                return

            text, buttons = _build_policy_editor(group, chat_id, page)
            await event.edit(text, buttons=buttons)
            await event.answer(toast)
        except Exception as e:
            logger.error(f"Error in group_policy_set_callback: {e}")

    @bot.on(events.NewMessage(pattern=r'(?i)^(?:/all_groups|/allgroups|all\s*groups)(?:@\w+)?(?:\s|$)'))
    async def all_groups_cmd(event):
        if not event.is_private:
            return
        if not _is_authorized(event):
            await event.respond("⚠️ Unauthorized. Only the bot admin can view groups.")
            return

        # Delete user's /all_groups command message after 10 seconds
        schedule_message_cleanup(event, delay=10.0)

        try:
            text, buttons, total_count = _build_groups_page(page=1)
            if total_count == 0:
                empty_msg = await event.respond(
                    "📭 **Total Groups:** `0`\nNo groups are currently scheduled in the database."
                )
                schedule_message_cleanup(empty_msg, delay=10.0)
                return

            list_msg = await event.respond(text, buttons=buttons)
            # Auto-delete group list message from DM after 10 minutes
            schedule_message_cleanup(list_msg, delay=600.0)

        except Exception as e:
            logger.error(f"Error in all_groups_cmd: {e}")
            await event.respond(f"❌ **Failed to retrieve groups:** `{e}`")
