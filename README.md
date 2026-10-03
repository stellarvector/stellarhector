# Stellar Hector

Stellar Vector's personal Butler!

## Running the bot

1. `cp .env.example .env`
2. Fill in all details in the `.env` file
3. `docker-compose build`
4. `docker-compose up -d`

That's all!

## Configuration

All settings live in `.env`; see `.env.example` for the full list.

### Roles

Role names (not IDs), as they appear on the server:

- `ADMIN_ROLE`: admins (e.g. `sv{admin}`).
- `MANAGER_ROLE`: managers (e.g. `sv{manager}`), may run the CTF management commands (create, release, archive and remove CTFs, add and remove players, unsolve challenges, archive channels, post the CTFtime table).
- `MODERATOR_ROLE`: moderators (e.g. `sv{moderator}`).
- `CORE_PLAYER_ROLE`, `KNOWN_PLAYER_ROLE`, `PLAYER_ROLE`: the player tiers.
- `MEMBER_ROLE`: every member of the team.

In code, `bot.STAFF_ROLES` (admin, manager, moderator) and `bot.MANAGER_ROLES` (admin, manager) are the role groups commands check with `@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)`. Roles that are not set are left out.

### Channels

Channel IDs (right-click the channel with developer mode on, then "Copy Channel ID"). A feature whose channel ID is not set is switched off: its job does nothing and its command replies that it is not configured. The bot logs a warning at startup for each one that is missing, and starts normally.

- `ADMIN_CHANNEL_ID`: shared admin channel for all bot alerts (feed failures, CTFtime changes before a CTF is set up, removal reminders).
- `CTF_SELECTION_CHANNEL_ID`: #ctf-selection.
- `UPCOMING_CTFS_CHANNEL_ID`: #upcoming-ctfs.
- `CALENDAR_CHANNEL_ID`: calendar announcements (see [Calendar sync](#calendar-sync)).
- `LEARNING_FORUM_ID`: the #learning forum, where new blog posts are shared.

Features read these with `bot.channel_id("ADMIN_CHANNEL_ID")`, which returns `None` when the ID is not set.

### Other settings

- `TIMEZONE`: timezone used wherever times are shown or scheduled (default `Europe/Brussels`).
- `DATABASE_PATH`: SQLite database file holding all bot state (default `./data/stellarhector.db`). Keep it under `./data`, which is mounted into the container, so it survives `docker-compose down && up`. The bot creates it on first start and applies any new migrations (`core/migrations/`) on every start.
- `WATCHDOG_TIMEOUT_MINUTES`: how long the scheduler may go without a tick before the watchdog restarts the bot (default `20`, must be more than the 5-minute tick interval).

## Scheduled jobs

`core/scheduler.py` runs one loop inside the bot that wakes up every 5 minutes and runs the jobs that are due. A feature registers a job with `scheduler.register(scheduler.Job(name, is_due, run))`, where `is_due` comes from `every_minutes(n)`, `daily_at("HH:MM", tz)` or `monthly_on(day, "HH:MM", tz)` and `run` is a plain async function that a slash command can call too. The last successful run of each job is kept in the `job_runs` table, so a daily or monthly job does not run twice after a restart. A new daily or monthly job first runs at its next slot, not right after deploy.

If a job raises or runs longer than its timeout (4 minutes by default; a job may ask for a longer one, the scheduler keeps beating while it runs), it is logged and retried on the next tick. A job registered with `alert_after=timedelta(...)` posts one alert in `ADMIN_CHANNEL_ID` once it has kept failing for that long (kept in `job_runs`, so also across restarts); after a successful run a new failure period starts. If the loop itself crashes, it is restarted. If the event loop gets blocked and no tick happens for `WATCHDOG_TIMEOUT_MINUTES`, a watchdog thread logs a critical message and exits the process, and Docker's `restart: always` starts it again. Blocking work (such as the git push of the archiver) must go through `asyncio.to_thread` so it does not stop the ticks.

### Checking the watchdog by hand

1. Set `WATCHDOG_TIMEOUT_MINUTES=6` in `.env`.
2. Temporarily add a job that blocks the event loop to `main.py`, right after `scheduler.init(...)`:
   ```python
   import time
   async def block():
       time.sleep(3600)  # time.sleep, not asyncio.sleep: this blocks the whole event loop
   scheduler.register(scheduler.Job("block", scheduler.every_minutes(5), block))
   ```
3. `docker-compose up -d --build`, then `docker inspect -f '{{.RestartCount}}' $(docker-compose ps -q bot)` and note the count.
4. Wait about 7 minutes. `data/logs/debug.log` shows `No scheduler heartbeat for ...s, exiting so Docker restarts the bot`, and the restart count went up by one.
5. Remove the job, put `WATCHDOG_TIMEOUT_MINUTES` back and rebuild.

## CTFtime

`utils/ctftime.py` is the shared CTFtime client:

- `await get_event(id)` returns an `Event` (id, title, start, finish as UTC datetimes, format, weight, onsite, url, ctftime_url), or `None` when CTFtime answers 404.
- `await list_events(start, finish)` returns every event starting in `[start, finish)`. CTFtime filters on an event's finish and ignores `offset`, so the client asks a year past `finish`, pages by moving `start` forward, and drops what starts outside the range.
- `parse_ctftime_id(text)` returns the id from the first `ctftime.org/event/<id>` link in a text, or `None`.

Network errors, timeouts, error responses other than a 404 on an event, and responses that are not the expected JSON raise `CtftimeError`. `list_events` relies on CTFtime sorting events by start (checked against the live API).

### `/ctftime-table [start-month] [months]`

Admins and managers can run it in any channel; it always posts in `CTF_SELECTION_CHANNEL_ID`. It lists every CTF on CTFtime starting in `months` months (default 2) from `start-month` (default next month; a month number such as `11` means the next time that month comes around, `2026-11` is that exact month). The first month is marked (validate), the later ones (preview). Each CTF is one line of fixed-width columns (dates in `TIMEZONE`, name, format, weight, online/onsite) in inline code, followed by a CTFtime link without a preview. Messages are split between lines to stay under Discord's 2000 characters.

The lines are built by `utils/ctftime_table.py`; `post_table` posts it, so the monthly post can call the same code.

### Monthly post

On the 1st of every month at 10:00 `TIMEZONE`, the `monthly-ctftime-table` job posts what `/ctftime-table` posts with its defaults (next month to validate, the month after as a preview). If CTFtime can't be reached it is retried every tick, and after a day of failing one alert is posted in `ADMIN_CHANNEL_ID`. If Discord refuses a message, the table may be half posted, so it is not retried: an alert is posted in `ADMIN_CHANNEL_ID` straight away to run `/ctftime-table` by hand. Nothing is posted when `CTF_SELECTION_CHANNEL_ID` is not set.

## Calendar sync

With `ICS_URL` set, the `calendar-sync` job downloads the calendar every `ICS_POLL_MINUTES` and mirrors its events into the server's Discord scheduled events. Without `ICS_URL` the feature is off entirely.

- `ICS_URL`: the ICS feed of the calendar.
- `ICS_POLL_MINUTES`: minutes between syncs (default `15`; the scheduler ticks every 5 minutes, so it is rounded up to a tick).
- `ICS_LOOKAHEAD_DAYS`: events running now or starting within this many days are created (default `30`).
- `ICS_PING_ROLE`: name of the role to mention in announcements (default: nobody is pinged).

Each event in scope becomes an external Discord event: the title, the description cut to Discord's 1000 characters (followed by the event's URL if it fits) and the location (the ICS `LOCATION`, else its `URL`, else "See description"). Times without a timezone in the feed are read in the calendar's own timezone (`X-WR-TIMEZONE`) when it has one, else in `TIMEZONE`. An event that is already running starts a minute from now in Discord, since Discord refuses events that start in the past. Every new event is announced in `CALENDAR_CHANNEL_ID` with an embed (title, start and end, location, the start of the description and a link to the event); when that channel is not set, events are created without an announcement.

Recurring events (`RRULE`) become one Discord event per occurrence in the window, so later occurrences are created as the window moves forward. Excluded dates (`EXDATE`) are left out, and an occurrence that was changed on its own (`RECURRENCE-ID`) gets its own time and details. All-day events run from 00:00 on their first day to 23:59 on their last day in `TIMEZONE`.

Cancelled events and occurrences (`STATUS:CANCELLED`) are not created, and timed events without an end and events with values the bot can't read are skipped (logged as a warning).

The calendar is the source of truth: change events there, not in Discord. Once the bot created an event, every sync quietly keeps it matching the calendar, without posting a message:

- A change to the time, title, description or location updates the Discord event, and the announcement is edited to show the new details. An event moved beyond the window is updated too: the window only limits which events get created.
- An admin's edit to one of the bot's events in Discord is overwritten with the calendar's details.
- One of the bot's events deleted in Discord is created again, and the link in its announcement is edited to point to the new event.

A sync that changes nothing in the calendar makes no changes on Discord.

An event the bot created that is removed from the calendar, or set to `STATUS:CANCELLED` there (also a single occurrence of a recurring event), is cancelled: its Discord event is deleted and the bot replies to the announcement that it was cancelled, pinging nobody. An event moved beyond the window is not cancelled, it is updated. Note that an event that becomes unreadable in the feed counts as removed. Once an event is over, the bot forgets it, and quietly deletes its Discord event if that is still there (for example when the event was moved into the past in the calendar).

The bot keeps the occurrence (ICS `UID`, plus for an occurrence of a recurring event the start it has in the series, even when it was moved) → Discord event, announcement and end in the `calendar_occurrences` table, so it never creates an event twice, also after a restart, and it only ever touches the events it created itself. Moving a one-off event or a single occurrence keeps it the same event; changing the start of a whole recurring series makes its occurrences new ones, cancelling the old ones. If the feed can't be downloaded or parsed, nothing changes and the job is retried on the next tick. An event Discord refuses is logged and tried again on the next sync.

The bot needs the **Create Events** and **Manage Events** permissions on the server, and permission to send messages and embeds in `CALENDAR_CHANNEL_ID`.

The sync itself is `run_calendar_sync()` in `command_handlers/calendar_sync.py`; it returns a summary of what it created, updated (recreated events included) and cancelled. The ICS parsing, the planning of what to create, update, recreate, cancel and forget, and the announcement are pure functions in `utils/calendar_sync.py`.
