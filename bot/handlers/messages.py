from telethon import events, utils
from bot.handlers.commands import is_user_waiting_input
from bot.handlers.groups import process_add_group
from bot.utils import parse_chat_target


def register_message_handlers(bot):
    """Register incoming message detectors for links and forwarded posts."""

    @bot.on(events.NewMessage(incoming=True))
    async def auto_link_and_forward_detector(event):
        if not event.is_private:
            return

        # Do not process as group add if user is currently configuring links in /set_message
        if is_user_waiting_input(event.sender_id):
            return

        try:
            text = (event.raw_text or "").strip()
            if not text or text.startswith('/'):
                return

            # Check for forwarded message from group or channel
            if event.message.forward:
                forward_info = event.message.forward
                if getattr(forward_info, 'chat', None):
                    target_peer = utils.get_peer_id(forward_info.chat)
                    await process_add_group(event, target_peer, source_desc="(Forwarded message)")
                    return
                elif getattr(forward_info, 'from_id', None):
                    target_peer = utils.get_peer_id(forward_info.from_id)
                    await process_add_group(event, target_peer, source_desc="(Forwarded message)")
                    return

            # Check for direct t.me link or @username
            if 't.me/' in text or text.startswith('@'):
                target_peer = parse_chat_target(text)
                if target_peer:
                    await process_add_group(event, target_peer, source_desc="(Direct link/username)")
                    return
        except Exception as e:
            from bot.config import logger
            logger.error(f"Error in auto_link_and_forward_detector: {e}")
