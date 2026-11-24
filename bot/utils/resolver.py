from typing import Union, Any
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
