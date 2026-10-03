"""The CTF lifecycle settings from .env, as the commands and the automatic timeline (command_handlers/ctf_timeline.py)
pass them to utils."""
import core.bot as bot
import core.config as config_helpers
from utils import ctf_lock, ctf_setup


def setup_settings():
    def role(key):
        return config_helpers.role_name(bot.config, key)

    return ctf_setup.Settings(admin_role=role("ADMIN_ROLE"), manager_role=role("MANAGER_ROLE"),
                              moderator_role=role("MODERATOR_ROLE"), member_role=bot.MEMBER_ROLE,
                              role_color=int(bot.config.get("CTF_ROLE_COLOR_HEX"), 16),
                              upcoming_channel_id=bot.channel_id("UPCOMING_CTFS_CHANNEL_ID"))


def lock_roles():
    return ctf_lock.LockRoles(member=bot.MEMBER_ROLE, writers=frozenset(bot.STAFF_ROLES))
