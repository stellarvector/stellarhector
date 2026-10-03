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
- `MANAGER_ROLE`: managers (e.g. `sv{manager}`), may run the CTF management commands (set up, release, archive and remove CTFs, add and remove players, unsolve challenges, archive channels, post the CTFtime table).
- `MODERATOR_ROLE`: moderators (e.g. `sv{moderator}`), may add and remove players of a CTF.
- `CORE_PLAYER_ROLE`, `KNOWN_PLAYER_ROLE`, `PLAYER_ROLE`: the player tiers. Core and known players (and staff) join a CTF with its Join button right away; players wait for a moderator; anyone else can't join that way.
- `MEMBER_ROLE`: every member of the team.

In code, `bot.STAFF_ROLES` (admin, manager, moderator), `bot.MANAGER_ROLES` (admin, manager) and `bot.ADMIN_ROLES` (admin) are the role groups commands check with `@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)`. Roles that are not set are left out.

### Channels

Channel IDs (right-click the channel with developer mode on, then "Copy Channel ID"). A feature whose channel ID is not set is switched off: its job does nothing and its command replies that it is not configured. The bot logs a warning at startup for each one that is missing, and starts normally.

- `ADMIN_CHANNEL_ID`: shared admin channel for all bot alerts (feed failures, CTFtime changes before a CTF is set up, removal reminders).
- `CTF_SELECTION_CHANNEL_ID`: #ctf-selection.
- `UPCOMING_CTFS_CHANNEL_ID`: #upcoming-ctfs, where each CTF's join message is posted.
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

Admins and managers can run it in any channel; it always posts in `CTF_SELECTION_CHANNEL_ID`. It lists every CTF on CTFtime starting in `months` months (default 2) from `start-month` (default next month; a month number such as `11` means the next time that month comes around, `2026-11` is that exact month). The first month is marked (validate), the later ones (preview). Each CTF is one line of fixed-width columns (dates in `TIMEZONE`, name, format, weight, online/onsite) in inline code, followed by a CTFtime link without a preview. A CTF that has a session in the calendar (see [CTF sessions](#ctf-sessions-and-the-daily-ctftime-check)) is marked ✅, or ⚠️ when a session falls outside the CTF. The bot only knows the sessions it created a Discord event for, those within `ICS_LOOKAHEAD_DAYS`, so a CTF whose sessions are further away is not marked yet. Messages are split between lines to stay under Discord's 2000 characters.

The lines are built by `utils/ctftime_table.py`; `post_table` posts it, so the monthly post can call the same code.

### Monthly post

On the 1st of every month at 10:00 `TIMEZONE`, the `monthly-ctftime-table` job posts what `/ctftime-table` posts with its defaults (next month to validate, the month after as a preview). If CTFtime can't be reached it is retried every tick, and after a day of failing one alert is posted in `ADMIN_CHANNEL_ID`. If Discord refuses a message, the table may be half posted, so it is not retried: an alert is posted in `ADMIN_CHANNEL_ID` straight away to run `/ctftime-table` by hand. Nothing is posted when `CTF_SELECTION_CHANNEL_ID` is not set.

## CTFs

Every CTF the bot set up is a row in the `ctfs` table: its name, its CTFtime ID with that event's start and finish (empty for a CTF without one), the IDs of its role, category, main channel, #bot channel, guide message and join message, and when each lifecycle step was done (last call, release, lock, archive, removal reminder, removed). A removed CTF keeps its row. The table is read and written through `utils/ctfs.py`.

### `/setup-ctf <name> [ctftime-id]`

Admins and managers can run it in any channel. It creates:

- the role `⚡ <name>` (color `CTF_ROLE_COLOR_HEX`, mentionable, just above `MEMBER_ROLE`);
- the category `⚡ <name>`, hidden from @everyone and members, visible to the CTF role, admins, managers and moderators (admins can also manage its channels);
- the main channel `<name>` at the top of the category, synced to it. Its first message is a pinned guide on how to work with the bot in this CTF, with a **Leave** button; its text is `utils/templates/ctf_guide.md`;
- the `#bot` channel, only visible to admins, managers and moderators. Staff run the CTF's commands there, and the bot posts the CTF's alerts there;
- the join message in `UPCOMING_CTFS_CHANNEL_ID` (skipped when that is not set), see [Joining a CTF](#joining-a-ctf).

The bot also gives itself access to the category and #bot, so it can post and pin there without Administrator.

With a CTFtime ID the event's start and finish are fetched from CTFtime and stored; the name stays what was typed. It is refused, and nothing is created, when CTFtime does not know the event or can't be reached, or when a CTF that is not removed already has that name (ignoring case) or CTFtime ID; the reply links to the existing CTF. When Discord refuses one of the steps halfway, what was created is deleted again and nothing is stored. The setup itself is `setup_ctf()` in `utils/ctf_setup.py`.

### Joining a CTF

The join message shows the CTF's name, CTFtime link, start and finish, the on-campus sessions on the calendar that link to its CTFtime event (see [Calendar sync](#calendar-sync)), and who plays (the first 20 by name, then "and N more"). It is kept up to date whenever someone joins or leaves, also through `/add-player` and `/remove-player`.

Its **Join** button, answered only to whoever clicks it:

- core players, known players and staff get the CTF role and are on the player list right away;
- players are put on the list as `pending`, and an approval card is posted in the CTF's #bot (see below); clicking again while pending posts no second card;
- anyone else is told to ask a moderator;
- once the CTF is released or locked, joining is closed.

The **Leave** button on the guide takes the CTF role away and takes the player off the list.

The approval card shows who asks to join, their roles, when they joined the server and how many CTFs they joined before. Only admins, managers and moderators can use its buttons (anyone else gets a reply only they see):

- **Accept** gives the CTF role and marks the player `joined`; **Accept + known player** also gives `KNOWN_PLAYER_ROLE`, so they join right away from then on (the button is left out when that role is not set);
- **Decline** takes them off the list, so they can click Join again later, and DMs them to go see a moderator on-site;
- the card then loses its buttons and says who decided what, e.g. "✅ Accepted by @mod" or "❌ Declined by @mod (DM failed)" (if the card can't be edited, the decision still stands and the clicker is told). A click on a card that was already handled, or whose player left the CTF or asked again since, only gets a reply that it was already handled. Someone who left the server can only be declined (the card says "left the server").

All these buttons keep working after a restart: their `custom_id` holds the CTF's ID (`ctf:join:<id>`, `ctf:leave:<id>`, and `ctf:card:<accept|known|decline>:<id>:<user id>` on approval cards), and `ctf_join.register()` handles them for every CTF at startup. The logic is in `utils/ctf_join.py`.

### Where CTF commands run

Commands find their CTF from the channel they are run in, by the IDs in `ctfs`, so renaming a CTF's channels, category or role by hand breaks nothing. `locate()` in `utils/ctf_places.py` tells what the channel is: the CTF's main channel, its #bot, a category channel (any other channel in its category), a challenge thread (a thread in a category channel), or not a place in a CTF. Run in the wrong place, a command replies, only to the user, where to run it.

- `/add-player <player>`, `/remove-player <player>`: admins, managers and moderators, in #bot. They give or take away the CTF role and put the player on, or take them off, the CTF's player list (the `ctf_players` table: CTF, user, `joined` or `pending`, approval card message, joined at).
- `/release-ctf`: admins and managers, in #bot. #bot stays visible to staff only.
- `/archive-ctf`: admins and managers, in #bot. Archives the CTF's channels, except #bot, and records when it was archived.
- `/remove-ctf [force]`: admins and managers, in #bot. Refused when the CTF was never archived, unless `force` is set. Deletes the CTF's channels and role, then #bot and the category, and marks it removed. When a channel or the role can't be deleted it stops before #bot, so it can be run again; once #bot is gone the admins are told in `ADMIN_CHANNEL_ID`.
- `/create-challenge`: players of the CTF, in its main channel, a challenge channel or a challenge thread.
- `/solved`, `/unsolve`: in a challenge channel (for now a category channel, until challenges become threads).

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
- An event that is already running in Discord but moved to later in the calendar is replaced the same way, since Discord can't move the start of a running event.

A sync that changes nothing in the calendar makes no changes on Discord.

An event the bot created that is removed from the calendar, or set to `STATUS:CANCELLED` there (also a single occurrence of a recurring event), is cancelled: its Discord event is deleted and the bot replies to the announcement that it was cancelled, pinging nobody. An event moved beyond the window is not cancelled, it is updated. Note that an event that becomes unreadable in the feed counts as removed. Once an event is over, the bot forgets it, and quietly deletes its Discord event if that is still there (for example when the event was moved into the past in the calendar).

The bot keeps the occurrence (ICS `UID`, plus for an occurrence of a recurring event the start it has in the series, even when it was moved) → Discord event, announcement and end in the `calendar_occurrences` table, so it never creates an event twice, also after a restart, and it only ever touches the events it created itself. Moving a one-off event or a single occurrence keeps it the same event; changing the start of a whole recurring series makes its occurrences new ones, cancelling the old ones. An event Discord refuses is logged and tried again on the next sync.

If the feed can't be downloaded, returns an error or doesn't parse, the sync is skipped: a warning is logged, nothing changes in Discord or in the database, and the next sync is tried after `ICS_POLL_MINUTES` as usual. A feed that parses but has no events while the bot manages at least one is skipped the same way, so a hiccup of the calendar provider can't cancel every event at once (an empty feed while the bot manages nothing is a normal sync). This also means that emptying the calendar on purpose doesn't cancel the last events: remove them while at least one other event stays in the calendar. After 10 skipped syncs in a row (about 2.5 hours at the default interval) one alert is posted in `ADMIN_CHANNEL_ID`, and on the first successful sync after that a short "calendar sync recovered" message (tried again on the next successful sync if it can't be posted). Any successful sync starts the count again; the count is kept in memory, so a restart starts it again too. A sync that fails for another reason, such as Discord refusing to list the server's events, is retried every tick like any job, and alerted once it has kept failing for as long (`alert_after`).

The bot needs the **Create Events** and **Manage Events** permissions on the server, and permission to send messages and embeds in `CALENDAR_CHANNEL_ID`.

The sync itself is `sync_calendar()` in `command_handlers/calendar_sync.py`; it returns a summary of what it created, updated (recreated events included) and cancelled, or raises the `FeedError` of a skipped sync. The `calendar-sync` job runs it through `run_calendar_sync()`, which only logs a skipped sync. One lock is held around the sync, so the job and `/calendar-sync` never run at the same time and never create an event twice; a sync that was stopped by its timeout while creating or editing an event finishes that in the background, and the next sync waits for it. The ICS parsing, the planning of what to create, update, recreate, cancel and forget, the announcement and the `/calendar-sync` replies are pure functions in `utils/calendar_sync.py`.

### `/calendar-sync`

Admins (`ADMIN_ROLE`) can run it in any channel to sync right away instead of waiting for the next poll, for example right after editing the calendar. It runs the same sync as the job (waiting for a scheduled sync that is running) and replies, only to the admin, with how many events were created, updated and cancelled, or with the reason the sync was skipped. A skipped sync counts toward the alert like any skipped scheduled sync. When `ICS_URL` is not set it replies that there is no calendar to sync.

### CTF sessions and the daily CTFtime check

A calendar event whose `URL` links to a CTFtime event (`ctftime.org/event/<id>`), or, when `URL` has no such link, whose description does, is a **CTF session**: the on-campus night of that CTF, not the whole CTF. The CTF's own start and finish always come from CTFtime, and several sessions can link to the same CTF. Events without a link (meetups etc.) are never checked. Every sync stores the start, title and CTFtime ID of each occurrence the bot has an event for in `calendar_occurrences`.

Every day at 12:00 `TIMEZONE` the `ctftime-check` job asks CTFtime about every CTF linked from a session that is not over yet, and keeps what it found per CTF in the `ctftime_events` table (title, start, finish, when it was checked, and the start and finish the admins were last told about):

- The first time a CTF is seen its dates are stored. When a session already falls outside the CTF (probably a typo in the calendar), that is alerted straight away.
- When CTFtime's start or finish differ from what the admins were last told: one alert with the CTF, the old and new dates and the linked sessions, :warning: when at least one session falls outside the new dates, :information_source: when they all still fall within them. Nothing is posted while the dates stay the same.
- When CTFtime no longer knows the CTF (404): one :warning: alert, not repeated on the next days.
- When CTFtime can't be reached or answers with an error, that CTF is skipped until the next check (logged, no alert).
- An alert that can't be posted is logged and posted on the next check.

Alerts go to `ADMIN_CHANNEL_ID`. Alerts list at most 5 sessions, to stay within one Discord message. The check itself is `check()` in `utils/ctftime_check.py`; deciding what to post and store is the pure `decide()` there.

### `/ctftime-check`

Admins (`ADMIN_ROLE`) can run it in any channel to run the daily check right away (waiting for a check that is running). It replies, only to the admin, with how many CTFs were checked and how many alerts were posted, and how many CTFs were skipped because CTFtime could not be reached.

## Blog feed

Every 10 minutes the bot checks [Stellar Vector's blog](https://blog.stellarvector.be/) and shares its new posts as forum posts in `LEARNING_FORUM_ID` (#learning). Without `LEARNING_FORUM_ID` the feature is off.

The check downloads the blog's RSS feed (`https://blog.stellarvector.be/index.xml`) and creates a forum post for every item whose `guid` is not in the `blog_posts_seen` table yet, oldest first. The very first check (empty table) only records the items that are already there and posts nothing, so the blog's history is not posted.

- A writeup (a link under `/writeups/<year>/<ctf-slug>/`) gets the title `[SV writeup] <CTF> / <title>` and the tags `writeup` and `Stellar Vector`. The CTF is the item's `<category domain="ctf">` when it has one, else the CTF slug from the link in title case.
- Any other post gets the title `[SV blog] <title>` and the tag `Stellar Vector`.
- Titles are cut to Discord's 100 characters. The post says what it is, followed by the item's description (when it has one) and the link.
- Tags are looked up on the forum by name, ignoring case. A tag the forum doesn't have is left out with a logged warning; the bot never creates tags.

A feed that can't be downloaded or parsed changes nothing and is logged. A forum post that can't be created is logged, and its item is tried again on the next check. A check fails when the feed can't be read, or when it had new items and none of their forum posts could be created; failures are only logged, as the next check is 10 minutes later anyway. A check that takes longer than 3 minutes is stopped and fails too; the next check carries on where it left off. Once the checks have been failing for 24 hours in a row, one alert is posted in `ADMIN_CHANNEL_ID`, and one message when it works again; a message that can't be posted is tried again on the next check. This is kept in memory, so a restart starts counting again. A failing `/blog-check` counts toward the alert like a failing scheduled check. Other errors that reach the scheduler are alerted through the job's `alert_after` of 24 hours. The scheduled check and `/blog-check` take turns, so they never post the same item twice. The check itself is `check()` in `utils/blog_feed.py`.

### `/blog-check`

Admins (`ADMIN_ROLE`) can run it in any channel to run the check right away (waiting for a check that is running). It replies, only to the admin, with how many forum posts were created.
