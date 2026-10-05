"""Formatting text for Discord messages."""

from datetime import datetime

# How much of an error message is posted, to keep messages well under Discord's 2000 characters
ERROR_LIMIT = 500


def cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def inline_code(text: str, limit: int) -> str:
    # Backticks would end the inline code early
    safe = text.replace("`", "'")[:limit]
    return f"`{safe}`"


def error_code(error: BaseException, limit: int = ERROR_LIMIT) -> str:
    return inline_code(f"{type(error).__name__}: {error}", limit)


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def discord_time(moment: datetime, style: str = "F") -> str:
    # Each reader sees the timestamp in their own timezone; style "R" shows it relative, such as "in 2 days"
    return f"<t:{int(moment.timestamp())}:{style}>"


def period(start: datetime, end: datetime) -> str:
    return f"{discord_time(start)} to {discord_time(end)}"
