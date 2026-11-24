"""Bot event handlers registry."""
from .commands import register_command_handlers, register_base_commands
from .groups import register_group_handlers
from .messages import register_message_handlers


def register_all_handlers(bot):
    """Register all command and message handlers with the Telethon bot instance."""
    register_command_handlers(bot)
    register_group_handlers(bot)
    register_message_handlers(bot)
