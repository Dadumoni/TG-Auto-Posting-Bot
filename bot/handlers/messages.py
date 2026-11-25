from telethon import events, utils
from telethon.tl.types import PeerChannel, PeerChat
from bot.config import ADMIN_ID, logger
from bot.handlers.commands import is_user_waiting_input
from bot.handlers.groups import process_add_group
from bot.utils import parse_chat_target


def register_message_handlers(bot):
    """Register incoming message detectors for links and forwarded posts."""

    @bot.on(events.NewMessage(incoming=True))
    async def auto_link_and_forward_detector(event):
        if not event.is_private:
            return

        if ADMIN_ID != 0 and event.sender_id != ADMIN_ID:
            return

        # Do not process as group add if user is currently configuring links in /set_message
        if is_user_waiting_input(event.sender_id):
            return

        try:
            text = (event.raw_text or "").strip()

            # Check for forwarded message from group or channel (even if media has no caption text)
            if event.message and event.message.forward:
                forward_info = event.message.forward
                target_peer = None

                if getattr(forward_info, 'chat', None):
                    target_peer = utils.get_peer_id(forward_info.chat)
                elif isinstance(getattr(forward_info, 'from_id', None), (PeerChannel, PeerChat)):
                    target_peer = utils.get_peer_id(forward_info.from_id)
                elif isinstance(getattr(forward_info, 'saved_from_peer', None), (PeerChannel, PeerChat)):
                    target_peer = utils.get_peer_id(forward_info.saved_from_peer)

                if target_peer:
                    logger.info(f"[AUTO-ADD] Forwarded group detected: peer={target_peer}")
                    await process_add_group(event, target_peer, source_desc="(Forwarded message)")
                    return

                await event.respond(
                    "⚠️ **Could not detect group from forwarded message.**\n\n"
                    "Telegram hides the source group when forwarding messages sent by regular members.\n"
                    "💡 _Please use `/add_group <group_link_or_id>` instead._"
                )
                return

            if not text or text.startswith('/'):
                return

            # Check for direct t.me link or @username
            if 't.me/' in text or text.startswith('@'):
                target_peer = parse_chat_target(text)
                if target_peer:
                    logger.info(f"[AUTO-ADD] Direct link/username detected: target={target_peer}")
                    await process_add_group(event, target_peer, source_desc="(Direct link/username)")
                    return
        except Exception as e:
            logger.error(f"Error in auto_link_and_forward_detector: {e}")
