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
- `MANAGER_ROLE`: managers (e.g. `sv{manager}`), may run the CTF management commands (create, release, archive and remove CTFs, add and remove players, unsolve challenges, archive channels).
- `MODERATOR_ROLE`: moderators (e.g. `sv{moderator}`).
- `CORE_PLAYER_ROLE`, `KNOWN_PLAYER_ROLE`, `PLAYER_ROLE`: the player tiers.
- `MEMBER_ROLE`: every member of the team.

In code, `bot.STAFF_ROLES` (admin, manager, moderator) and `bot.MANAGER_ROLES` (admin, manager) are the role groups commands check with `@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)`. Roles that are not set are left out.

### Channels

Channel IDs (right-click the channel with developer mode on, then "Copy Channel ID"). A feature whose channel ID is not set is switched off: its job does nothing and its command replies that it is not configured. The bot logs a warning at startup for each one that is missing, and starts normally.

- `ADMIN_CHANNEL_ID`: shared admin channel for all bot alerts (feed failures, CTFtime changes before a CTF is set up, removal reminders).
- `CTF_SELECTION_CHANNEL_ID`: #ctf-selection.
- `UPCOMING_CTFS_CHANNEL_ID`: #upcoming-ctfs.
- `CALENDAR_CHANNEL_ID`: calendar announcements.
- `LEARNING_FORUM_ID`: the #learning forum, where new blog posts are shared.

Features read these with `bot.channel_id("ADMIN_CHANNEL_ID")`, which returns `None` when the ID is not set.

### Other settings

- `TIMEZONE`: timezone used wherever times are shown or scheduled (default `Europe/Brussels`).
- `DATABASE_PATH`: SQLite database file holding all bot state (default `./data/stellarhector.db`). Keep it under `./data`, which is mounted into the container, so it survives `docker-compose down && up`. The bot creates it on first start and applies any new migrations (`core/migrations/`) on every start.
- `WATCHDOG_TIMEOUT_MINUTES`: how long the scheduler may go without a tick before the watchdog restarts the bot (default `20`, must be more than the 5-minute tick interval).

## Scheduled jobs

`core/scheduler.py` runs one loop inside the bot that wakes up every 5 minutes and runs the jobs that are due. A feature registers a job with `scheduler.register(scheduler.Job(name, is_due, run))`, where `is_due` comes from `every_minutes(n)`, `daily_at("HH:MM", tz)` or `monthly_on(day, "HH:MM", tz)` and `run` is a plain async function that a slash command can call too. The last successful run of each job is kept in the `job_runs` table, so a daily or monthly job does not run twice after a restart. A new daily or monthly job first runs at its next slot, not right after deploy.

If a job raises or runs longer than its timeout (4 minutes by default, keep it below the watchdog limit), it is logged and retried on the next tick. If the loop itself crashes, it is restarted. If the event loop gets blocked and no tick happens for `WATCHDOG_TIMEOUT_MINUTES`, a watchdog thread logs a critical message and exits the process, and Docker's `restart: always` starts it again. Blocking work (such as the git push of the archiver) must go through `asyncio.to_thread` so it does not stop the ticks.

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
- `await list_events(start, finish)` returns every event starting in `[start, finish)`. CTFtime filters on an event's finish and ignores `offset`, so the client asks 30 days past `finish`, pages by moving `start` forward, and drops what starts outside the range.
- `parse_ctftime_id(text)` returns the id from the first `ctftime.org/event/<id>` link in a text, or `None`.

Network errors, timeouts, error responses other than a 404 on an event, and responses that are not the expected JSON raise `CtftimeError`. `list_events` relies on CTFtime sorting events by start (checked against the live API).
