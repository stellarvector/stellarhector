import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Brussels"


def role_names(config, *keys):
    """Names of the roles behind the given keys, skipping roles that are not configured."""
    names = [(config.get(key) or "").strip() for key in keys]

    return [name for name in names if name]


def channel_id(config, key):
    """The channel ID behind the key, or None when it is not set, so the feature using it is off."""
    value = (config.get(key) or "").strip()

    if not value:
        return None

    if not value.isdigit():
        logging.getLogger("bot").warning(f"{key} is not a valid channel ID ({value!r}), treating it as unset")
        return None

    return int(value)


def timezone(config):
    value = (config.get("TIMEZONE") or "").strip()

    if not value:
        return DEFAULT_TIMEZONE

    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        logging.getLogger("bot").warning(f"TIMEZONE {value!r} is unknown, using {DEFAULT_TIMEZONE}")
        return DEFAULT_TIMEZONE

    return value
