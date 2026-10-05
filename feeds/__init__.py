"""The outside sources the bot follows: the ICS calendar, the blog's RSS feed and CTFtime."""


class FeedError(Exception):
    """A feed could not be downloaded or read; nothing was changed."""
