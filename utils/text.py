"""Small helpers for the text the bot posts on Discord."""


def cut(text, limit):
    """text cut to limit characters, ending in … when it was longer."""
    return text if len(text) <= limit else text[:limit - 1] + "…"


def inline_code(text, limit):
    """text as inline code, cut to limit characters. Backticks in it, which would end the inline code, become quotes."""
    safe = text.replace("`", "'")[:limit]
    return f"`{safe}`"
