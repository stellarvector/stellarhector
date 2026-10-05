"""The bot's features as discord.py cogs: their slash commands, buttons and scheduled jobs. The cogs only talk to
Discord; the work is done in ctf/, feeds/ and archive/."""

from cogs.blog_feed import BlogFeed
from cogs.calendar_feed import CalendarFeed
from cogs.challenges import Challenges
from cogs.channel_archive import ChannelArchiving
from cogs.ctf_lifecycle import CtfLifecycle
from cogs.ctftime_feed import CtftimeFeed
from cogs.help import Help
from cogs.players import Players

# In the order they are added to the bot, and so their jobs run: each tick syncs the calendar before the CTFtime check
# reads its sessions
ALL = [Help, CtfLifecycle, Players, Challenges, ChannelArchiving, CalendarFeed, CtftimeFeed, BlogFeed]
