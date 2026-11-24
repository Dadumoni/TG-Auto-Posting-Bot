"""Database package for MongoDB operations."""
from .mongo import (
    get_custom_message,
    set_custom_message,
    get_all_custom_messages,
    is_group_exists,
    get_group_db,
    add_group_db,
    update_group_link_type,
    update_group_cooldown,
    update_group_schedule,
    remove_group_db,
    remove_all_groups_db,
    get_all_groups_db,
    update_last_posted,
)

__all__ = [
    "get_custom_message",
    "set_custom_message",
    "get_all_custom_messages",
    "is_group_exists",
    "get_group_db",
    "add_group_db",
    "update_group_link_type",
    "update_group_cooldown",
    "update_group_schedule",
    "remove_group_db",
    "remove_all_groups_db",
    "get_all_groups_db",
    "update_last_posted",
]
