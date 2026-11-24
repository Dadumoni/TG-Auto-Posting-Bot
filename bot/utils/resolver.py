from typing import Union, Any, Dict
from telethon import utils
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel
from bot.client import user
from bot.config import logger


async def resolve_chat_entity(chat_identifier: Union[int, str]) -> Any:
    """
    Resolve a Telegram chat entity using the Userbot client.
    Attempts direct resolution first, then scans user dialogs if necessary.
    """
    try:
        return await user.get_entity(chat_identifier)
    except Exception:
        logger.info(f"Direct entity resolution failed for '{chat_identifier}', scanning dialogs...")
        async for dialog in user.iter_dialogs(limit=None):
            peer_id = utils.get_peer_id(dialog.entity)
            if peer_id == chat_identifier or dialog.id == chat_identifier:
                return dialog.entity

            username = getattr(dialog.entity, 'username', None)
            if (
                username
                and isinstance(chat_identifier, str)
                and username.lower() == chat_identifier.lower()
            ):
                return dialog.entity

        raise ValueError(
            f"Target '{chat_identifier}' could not be resolved in the Userbot dialogs. "
            "Please ensure the Userbot account has joined the target chat."
        )


async def detect_group_cooldown(chat_entity) -> int:
    """
    Detect the native Telegram slowmode cooldown timer (in seconds) set on a group/channel.
    Returns 0 if no slowmode cooldown is active.
    """
    try:
        if isinstance(chat_entity, Channel):
            full_channel = await user(GetFullChannelRequest(chat_entity))
            slowmode = getattr(full_channel.full_chat, 'slowmode_seconds', None)
            if slowmode:
                return int(slowmode)
    except Exception as e:
        logger.debug(f"Could not retrieve full channel slowmode metadata: {e}")
    return 0


async def diagnose_group_failure(chat_id: int, original_error: Exception) -> Dict[str, Any]:
    """
    Perform deep inspection of a failed group using GetFullChannelRequest
    to determine exact failure reasons:
    - Telegram Stars / Paid Messages required
    - Userbot banned / muted / kicked
    - Channel broadcast mode (admin-only)
    - Group deleted, suspended, or inaccessible
    """
    err_str = str(original_error)
    err_type = type(original_error).__name__

    diag: Dict[str, Any] = {
        "reason": "Unknown Error",
        "description": err_str,
        "recommendation": f"Run `/debug {chat_id}` or check group manually.",
        "stars_detected": False,
        "banned": False,
    }

    # 1. Error string heuristic check for Telegram Stars / Paid Messages
    upper_err = (err_str + " " + err_type).upper()
    if any(k in upper_err for k in ["PAID_MESSAGES", "PAID_BROADCAST", "STARS_REQUIRED", "PAYMENT_REQUIRED", "STARS"]):
        diag["reason"] = "⭐ Telegram Stars Required (Paid Messages)"
        diag["description"] = "Group owner has enabled Telegram Stars payment for sending messages. Free posting is not allowed."
        diag["recommendation"] = f"Remove this group using `/remove_group {chat_id}` because posting requires Telegram Stars."
        diag["stars_detected"] = True
        return diag

    # 2. Deep inspection using GetFullChannelRequest
    try:
        chat = await resolve_chat_entity(chat_id)
        if isinstance(chat, Channel):
            full_info = await user(GetFullChannelRequest(chat))
            full_chat = getattr(full_info, 'full_chat', None)
            channel_entity = full_info.chats[0] if full_info.chats else chat

            # Check Star / Paid attributes in ChannelFull metadata
            full_dict = full_chat.to_dict() if full_chat else {}
            for k, v in full_dict.items():
                if ("PAID" in str(k).upper() or "STAR" in str(k).upper()) and v:
                    diag["reason"] = "⭐ Telegram Stars Required (Paid Messages)"
                    diag["description"] = f"Detected Telegram Stars requirement (`{k}: {v}`) in group metadata."
                    diag["recommendation"] = f"Remove this group using `/remove_group {chat_id}`."
                    diag["stars_detected"] = True
                    return diag

            # Check if Userbot is banned or kicked
            if getattr(channel_entity, 'left', False):
                diag["reason"] = "🚪 Userbot Not a Member"
                diag["description"] = "Userbot account is no longer in this group (may have been kicked or removed)."
                diag["recommendation"] = f"Re-join the group with your userbot or remove using `/remove_group {chat_id}`."
                return diag

            if getattr(channel_entity, 'kicked', False):
                diag["reason"] = "🚫 Userbot Banned / Kicked"
                diag["description"] = "Userbot account has been kicked or banned by group administrators."
                diag["recommendation"] = f"Remove group using `/remove_group {chat_id}`."
                diag["banned"] = True
                return diag

            # Check userbot's specific banned_rights
            banned_rights = getattr(channel_entity, 'banned_rights', None)
            if banned_rights:
                if getattr(banned_rights, 'send_messages', False):
                    diag["reason"] = "🔇 Userbot Muted / Restricted"
                    diag["description"] = "Group admin has specifically restricted or muted the Userbot account."
                    diag["recommendation"] = f"Remove group using `/remove_group {chat_id}`."
                    diag["banned"] = True
                    return diag

            # Check default_banned_rights (group-wide mute)
            default_banned = getattr(channel_entity, 'default_banned_rights', None)
            if default_banned and getattr(default_banned, 'send_messages', False):
                diag["reason"] = "🔒 Group Muted by Admins"
                diag["description"] = "Group administrators have disabled message sending for all regular members."
                diag["recommendation"] = "Group is currently locked for normal members."
                return diag

            # Check if target is a broadcast channel
            if getattr(channel_entity, 'broadcast', False) and not getattr(channel_entity, 'megagroup', False):
                diag["reason"] = "📢 Broadcast Channel (Admins Only)"
                diag["description"] = "Target is a Telegram Channel, not a discussion group. Regular members cannot post."
                diag["recommendation"] = f"Remove using `/remove_group {chat_id}` unless userbot is promoted to admin."
                return diag

            # Check if Telegram restricted the channel
            if getattr(channel_entity, 'restricted', False):
                reason_str = str(getattr(channel_entity, 'restriction_reason', 'Flagged by Telegram'))
                diag["reason"] = "⚠️ Group Restricted by Telegram"
                diag["description"] = f"Telegram has restricted this group: {reason_str}"
                diag["recommendation"] = f"Remove using `/remove_group {chat_id}`."
                return diag

    except Exception as inspect_err:
        inspect_str = str(inspect_err).upper()
        if "PRIVATE" in inspect_str or "INVITE" in inspect_str:
            diag["reason"] = "🔒 Group Private or Inaccessible"
            diag["description"] = "Userbot cannot access this private chat. Invite link expired or userbot was removed."
            diag["recommendation"] = f"Remove using `/remove_group {chat_id}`."
            return diag
        elif "INVALID" in inspect_str or "DEACTIVATED" in inspect_str or "BANNED" in inspect_str:
            diag["reason"] = "❌ Group Deleted or Suspended"
            diag["description"] = "This group has been deleted, deactivated, or suspended by Telegram."
            diag["recommendation"] = f"Remove using `/remove_group {chat_id}`."
            return diag

    # If ChatWriteForbiddenError occurred and no specific rights were found
    if "ChatWriteForbiddenError" in err_type or "CHATWRITEFORBIDDEN" in upper_err or "WRITE FORBIDDEN" in upper_err or "CANNOT WRITE" in upper_err:
        diag["reason"] = "⛔ Write Access Forbidden (Possible Telegram Stars or Admin Only)"
        diag["description"] = "Telegram rejected message submission (Write Forbidden). Most commonly caused by Telegram Stars paid message requirement or admin-only broadcast restrictions."
        diag["recommendation"] = f"Check group manually or remove via `/remove_group {chat_id}`."

    return diag
