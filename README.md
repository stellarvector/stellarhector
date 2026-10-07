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
- `MANAGER_ROLE`: managers (e.g. `sv{manager}`), may run the CTF management commands (set up, release, archive and remove CTFs, add and remove players, archive channels, post the CTFtime table).
- `MODERATOR_ROLE`: moderators (e.g. `sv{moderator}`), may add and remove players of a CTF, make its last call and unsolve challenges.
- `CORE_PLAYER_ROLE`, `KNOWN_PLAYER_ROLE`, `PLAYER_ROLE`: the player tiers. Core and known players (and staff) join a CTF with its Join button right away; players wait for a moderator; anyone else can't join that way.
- `FOLLOWER_ROLE`: members who chose "follower" in onboarding; the others get `PLAYER_ROLE`. Players and followers together are the team's members: a released CTF is opened to both. Core and known players also have the player role.

In code, `settings.roles.staff` (admin, manager, moderator), `settings.roles.managers` (admin, manager) and `settings.roles.admins` (admin) are the role groups; commands check them with `@checks.staff_only()`, `@checks.managers_only()` and `@checks.admins_only()` from `core/checks.py`. Roles that are not set are left out.

### Channels

Channel IDs (right-click the channel with developer mode on, then "Copy Channel ID"). A feature whose channel ID is not set is switched off: its job does nothing and its command replies that it is not configured. The bot logs a warning at startup for each one that is missing, and starts normally.

- `ADMIN_CHANNEL_ID`: shared admin channel for all bot alerts (feed failures, CTFtime changes before a CTF is set up, failing automatic setups, removal reminders).
- `CTF_SELECTION_CHANNEL_ID`: #ctf-selection.
- `UPCOMING_CTFS_CHANNEL_ID`: #upcoming-ctfs, where each CTF's join message is posted.
- `CALENDAR_CHANNEL_ID`: calendar announcements (see [Calendar sync](#calendar-sync)).
- `LEARNING_FORUM_ID`: the #learning forum, where new blog posts are shared.

Features read these as `settings.channels.admin`, `settings.channels.upcoming_ctfs`, ..., which are `None` when the ID is not set.

### Other settings

- `TIMEZONE`: timezone used wherever times are shown or scheduled (default `Europe/Brussels`).
- `DATABASE_PATH`: SQLite database file holding all bot state (default `./data/stellarhector.db`). Keep it under `./data`, which is mounted into the container, so it survives `docker-compose down && up`. The bot creates it on first start and applies any new migrations (`core/migrations/`) on every start.
- `WATCHDOG_TIMEOUT_MINUTES`: how long the scheduler may go without a tick before the watchdog restarts the bot (default `20`, must be more than the 5-minute tick interval).

## Code layout

- `main.py`: reads the settings, sets up logging and the database, and runs the bot.
- `bot.py`: the bot itself, `Hector`: it holds the settings, the scheduler and the archive repository, adds the cogs, and posts alerts for the admins.
- `core/`: what everything builds on: the settings from `.env` (`settings.py`), the SQLite database with its migrations (`db.py`), the job scheduler (`scheduler.py`), and the role checks and error reply of every command (`checks.py`, `errors.py`).
- `cogs/`: one discord.py cog per feature, with its slash commands, buttons and scheduled jobs, and the replies they give. Cogs only talk to Discord: the work happens in the packages below, so a command and a job share it.
- `ctf/`: the lifecycle of a CTF: setting it up, joining it, its categories and challenges, releasing, locking, archiving and removing it, and the automatic timeline that does these steps by itself.
- `feeds/`: the outside sources: the calendar (`feeds/calendar/`), the blog and CTFtime (its API client, the daily date check and the table of upcoming CTFs).
- `archive/`: the HTML archive of CTFs and channels, and the git repository it is committed to.
- `utils/`: small helpers for Discord text and objects.

Dependencies only point down this list: cogs use ctf/feeds/archive, `ctf/` uses `feeds/` and `archive/`, and those use only `core/` and `utils/`. Messages posted on Discord objects (join messages, approval cards, alerts) are written in the package that posts them; replies to a command are written in its cog.

The tests in `tests/` mirror this layout; shared fakes of Discord objects are in `tests/fakes.py`, and builders for CTFs, settings and a temporary database in `tests/factories.py`.

Run the tests with `python -m unittest discover -s tests -t .` (the archive repository tests need `git`, and are skipped without it), lint and format with `ruff check .` and `ruff format .`, and check the types with `mypy` (settings for all three in `pyproject.toml`). Every function is annotated: ruff refuses code without annotations, and mypy checks that they are right.

Dependencies: `requirements.in` lists what the bot uses directly; `requirements.txt` is generated from it with pip-tools and pins every package, with hashes, so every Docker build installs the same versions. After changing `requirements.in`, or to upgrade (add `--upgrade`), regenerate it with the command at the top of `requirements.in`.

## Scheduled jobs

`core/scheduler.py` runs one loop inside the bot that wakes up every 5 minutes and runs the jobs that are due. A feature registers a job in its cog's `cog_load` with `self.bot.scheduler.register(Job(name, is_due, run))`, where `is_due` comes from `every_minutes(n)`, `daily_at("HH:MM", tz)` or `monthly_on(day, "HH:MM", tz)` and `run` is a plain async function that a slash command can call too. The last successful run of each job is kept in the `job_runs` table, so a daily or monthly job does not run twice after a restart. A new daily or monthly job first runs at its next slot, not right after deploy.

If a job raises or runs longer than its timeout (4 minutes by default; a job may ask for a longer one, the scheduler keeps beating while it runs), it is logged and retried on the next tick. A job registered with `alert_after=timedelta(...)` posts one alert in `ADMIN_CHANNEL_ID` once it has kept failing for that long, and a short "works again" message after its next successful run (both kept in `job_runs`, so also across restarts; a message that can't be posted is tried again). A successful run starts a new failure period. This is the one way feature failures reach the admins. If the loop itself crashes, it is restarted. If the event loop gets blocked and no tick happens for `WATCHDOG_TIMEOUT_MINUTES`, a watchdog thread logs a critical message and exits the process, and Docker's `restart: always` starts it again. Blocking work (such as the git push of the archiver) must go through `asyncio.to_thread` so it does not stop the ticks.

### Checking the watchdog by hand

1. Set `WATCHDOG_TIMEOUT_MINUTES=6` in `.env`.
2. Temporarily add a job that blocks the event loop to the `cog_load` of any cog in `cogs/`:
   ```python
   async def block():
       time.sleep(3600)  # time.sleep, not asyncio.sleep: this blocks the whole event loop


   self.bot.scheduler.register(Job("block", every_minutes(5), block))
   ```
3. `docker-compose up -d --build`, then `docker inspect -f '{{.RestartCount}}' $(docker-compose ps -q bot)` and note the count.
4. Wait about 7 minutes. `data/logs/debug.log` shows `No scheduler heartbeat for ...s, exiting so Docker restarts the bot`, and the restart count went up by one.
5. Remove the job, put `WATCHDOG_TIMEOUT_MINUTES` back and rebuild.

## CTFtime

`feeds/ctftime.py` is the shared CTFtime client:

- `await get_event(id)` returns an `Event` (id, title, start, finish as UTC datetimes, format, weight, onsite, url, ctftime_url), or `None` when CTFtime answers 404.
- `await list_events(start, finish)` returns every event starting in `[start, finish)`. CTFtime filters on an event's finish and ignores `offset`, so the client asks a year past `finish`, pages by moving `start` forward, and drops what starts outside the range.
- `parse_ctftime_id(text)` returns the id from the first `ctftime.org/event/<id>` link in a text, or `None`.

Network errors, timeouts, error responses other than a 404 on an event, and responses that are not the expected JSON raise `CtftimeError`. `list_events` relies on CTFtime sorting events by start (checked against the live API).

### `/ctftime-table [start-month] [months]`

Admins and managers can run it in any channel; it always posts in `CTF_SELECTION_CHANNEL_ID`. It lists every CTF on CTFtime starting in `months` months (default 2) from `start-month`. Without `start-month` it starts at the current month and leaves out the CTFs that are already over, to keep the table short; with `start-month` (a month number such as `11` means the next time that month comes around, `2026-11` is that exact month) it lists every CTF of those months, including finished ones, so older months can be looked up. The first month is marked (validate), the later ones (preview). Each CTF is one line of fixed-width columns in inline code: its start and finish in `TIMEZONE` (`Fri 09/10 18:00 -> Sat 10/10 18:00`), name, format, weight and online/onsite. After it comes a CTFtime link without a preview, and at the very end a ⭐ for an online Jeopardy CTF with a weight above 0. A CTF that has a session in the calendar (see [CTF sessions](#ctf-sessions-and-the-daily-ctftime-check)) is marked ✅ before the link, or ⚠️ when a session falls outside the CTF. The bot only knows the sessions it created a Discord event for, those within `ICS_LOOKAHEAD_DAYS`, so a CTF whose sessions are further away is not marked yet. Messages are split between lines to stay under Discord's 2000 characters.

The lines are built by `feeds/ctftime_table.py`; `post_table` posts it, so the monthly post can call the same code.

### Monthly post

On the 1st of every month at 10:00 `TIMEZONE`, the `monthly-ctftime-table` job posts what `/ctftime-table` posts with its defaults (the current month to validate, without the CTFs that are already over, and the next month as a preview). If CTFtime can't be reached it is retried every tick, and after a day of failing one alert is posted in `ADMIN_CHANNEL_ID`. If Discord refuses a message, the table may be half posted, so it is not retried: an alert is posted in `ADMIN_CHANNEL_ID` straight away to run `/ctftime-table` by hand. Nothing is posted when `CTF_SELECTION_CHANNEL_ID` is not set.

## CTFs

Every CTF the bot set up is a row in the `ctfs` table: its name, its CTFtime ID with that event's start and finish (empty for a CTF without one), the IDs of its role, category, main channel, #bot channel, guide message and join message, and when each lifecycle step was done (last call, release, lock, archive, removal reminder, removed). A removed CTF keeps its row. The table is read and written through `ctf/store.py` (the data classes are in `ctf/models.py`).

### `/setup-ctf <name> [ctftime-id]`

Admins and managers can run it in any channel. It creates:

- the role `⚡ <name>` (color `CTF_ROLE_COLOR_HEX`, mentionable, just above the player and follower roles);
- the category `⚡ <name>`, hidden from @everyone and members, visible to the CTF role, admins, managers and moderators (admins can also manage its channels);
- the main channel `<name>` at the top of the category, synced to it. Its first message is a pinned guide on how to work with the bot in this CTF, with a **Leave** button; its text is `ctf/guide.md`;
- the `#bot` channel, only visible to admins, managers and moderators. Staff run the CTF's commands there, and the bot posts the CTF's alerts there;
- the join message in `UPCOMING_CTFS_CHANNEL_ID` (skipped when that is not set), see [Joining a CTF](#joining-a-ctf).

The bot also gives itself access to the category and #bot, so it can post and pin there without Administrator.

With a CTFtime ID the event's start and finish are fetched from CTFtime and stored; the name stays what was typed. It is refused, and nothing is created, when CTFtime does not know the event or can't be reached, or when a CTF that is not removed already has that name (ignoring case) or CTFtime ID; the reply links to the existing CTF. When Discord refuses one of the steps halfway, what was created is deleted again and nothing is stored. The setup itself is `setup_ctf()` in `ctf/setup.py`.

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

All these buttons keep working after a restart: their `custom_id` holds the CTF's ID (`ctf:join:<id>`, `ctf:leave:<id>`, and `ctf:card:<accept|known|decline>:<id>:<user id>` on approval cards), and the `Players` cog (`cogs/players.py`) handles them for every CTF. The logic is in `ctf/joining.py` (who may join), `ctf/approval.py` (approval cards), `ctf/join_message.py` (the join message and last call) and `ctf/buttons.py` (the buttons themselves).

### Where CTF commands run

Commands find their CTF from the channel they are run in, by the IDs in `ctfs`, so renaming a CTF's channels, category or role by hand breaks nothing. `locate()` in `ctf/location.py` tells what the channel is: the CTF's main channel, its #bot, a category channel (any other channel in its category), a challenge thread (a thread in a category channel), or not a place in a CTF. Run in the wrong place, a command replies, only to the user, where to run it.

- `/add-player <player>`, `/remove-player <player>`: admins, managers and moderators, in #bot. They give or take away the CTF role and put the player on, or take them off, the CTF's player list (the `ctf_players` table: CTF, user, `joined` or `pending`, approval card message, joined at).
- `/last-call`: admins, managers and moderators, in #bot. Posts the join message again at the bottom of `UPCOMING_CTFS_CHANNEL_ID` with "Last call" in its title and the same players, deletes the old one (also fine when it was already deleted by hand) and records when the last call was done. Its Join button works as before. It can be run again to move it down once more, and is refused once joining is closed.
- `/release-ctf`: admins and managers, in #bot. Opens the CTF to all members: `PLAYER_ROLE` and `FOLLOWER_ROLE` may see its category (its other permissions are kept, and writing is not denied, so members write as they do elsewhere on the server, also in the challenge threads, which are public; a private thread made by hand stays for whoever is in it), and every channel but #bot is synced to it; #bot stays visible to staff only. Joining closes: the join message says the CTF is open to all members and its Join button is disabled, and pending approval cards say "No longer needed: CTF released" and lose their buttons, their players taken off the list. The members are welcomed in the CTF's main channel ("🔓 This CTF is now open to all members. Welcome!"). Records when it was released; run again, it changes nothing and says so. A player or follower role that is configured but missing from the server is skipped with a warning in the log; the release is refused only when neither exists. A message that can't be posted (or a main channel deleted by hand) is logged and doesn't undo the release or lock. The logic is in `ctf/release.py`.
- `/lock-ctf`: admins and managers, in #bot. Makes the CTF read-only and archives it; it stays readable until it is removed with `/remove-ctf`. A CTF that was not released is released first (as `/release-ctf`). @everyone, `PLAYER_ROLE`, `FOLLOWER_ROLE` and the CTF role are denied sending messages, sending in threads, creating public and private threads and adding reactions on the category, and `ADMIN_ROLE`, `MANAGER_ROLE` and `MODERATOR_ROLE` are allowed them (an allow on one role wins over a deny on another), their other permissions kept; every channel but #bot is synced to it, and #bot is left as it is. Every thread in those channels, the active ones and the archived public and private ones (also made by hand), is archived and locked, so posting can't reopen it. Records when it was locked and posts "🔒 This CTF is over and locked. The channels stay readable, but nothing can be posted anymore." in the main channel (a CTF released by the lock gets no welcome before it), then archives it as `/archive-ctf` does. When archiving fails the lock stays, the error is posted in #bot, and `/archive-ctf` can be run by hand. Run again, it changes nothing and says so (and to run `/archive-ctf` when it was not archived). Once locked, `/add-category`, `/create-challenge`, `/solved` and `/unsolve` refuse for everyone, so nothing reopens a thread or adds one the archive misses. The logic is in `ctf/lock.py`.
- `/archive-ctf`: admins and managers, in #bot. Archives the CTF's channels, except #bot, to `<year>/<CTF folder>/` in the archive repository, the folder being the CTF name with only ASCII letters, digits and dashes (`Foo CTF` becomes `Foo-CTF`), like every folder and page in the archive (a new `<CTF folder>-<n>` folder, from 2 on, when one exists, so older archives are left as they are): a page for the main channel, its threads inline, and a folder per other text channel (its categories, and channels made by hand; voice and forum channels are left out) with an `index.html` for the messages posted in the channel itself, linking each thread at the message it was made on (or Discord's notice that it was started), and a page per thread in it (the challenges, active and archived, public and private), named after the thread like `/archive-channel` names channels (so `✅ sqli` becomes `sqli.html`, numbered when taken). Every page links the others in its navigation; attachments go in an `attachments` folder next to the page, named `<attachment id>_<file name>` with anything but letters, digits, dots, dashes and underscores in the file name made an underscore. Writes the pages (downloading the attachments) and commits and pushes them as `SHOULD_COMMIT` and `SHOULD_PUSH` say, all off the event loop, and records when it was archived. The year index links the CTF only once all its pages are written. When anything fails, no archive time is recorded and what was written is taken away again (the folders made, the edited indexes put back, a commit that could not be pushed undone), so running it again doesn't make a `<CTF folder>-<n>` copy. A category deleted by hand leaves only the main channel to archive. The logic is in `ctf/archive.py`, and the pages are built by `archive/ctf_archive.py`.
- `/remove-ctf [force]`: admins and managers, in #bot. Refused when the CTF was never archived, unless `force` is set. Deletes the CTF's channels and role, then #bot and the category, and marks it removed. When a channel or the role can't be deleted it stops before #bot, so it can be run again; once #bot is gone the admins are told in `ADMIN_CHANNEL_ID`.
- `/add-category <names>`: players of the CTF and admins, managers and moderators, in its main channel. `names` holds one or more challenge categories, comma-separated (`web, crypto, pwn`). Each becomes a text channel in the CTF's category, synced to it, in alphabetical order below the main channel; its name is the category slugified (lowercase, spaces become dashes, everything but letters, digits and dashes removed). A category the CTF already has, and a name of which nothing is left as a slug, is skipped and reported; a category whose channel was deleted by hand is created again. All positions in the category are set in one request (main channel, categories A–Z, then the rest such as #bot), so the order holds even before the bot hears of the new channels. The categories are stored in the `ctf_categories` table (CTF, slug, channel). The logic is in `ctf/categories.py`.
- `/create-challenge <name>`: players of the CTF and admins, managers and moderators, in a category channel, or in a challenge thread (then its parent channel is used). Anywhere else, also in a channel of the CTF's category not made with `/add-category`, it says to run it in a category channel and to create one with `/add-category`. The name is slugified like a category. A new challenge gets a starter message in the category channel ("🧩 `<slug>`, started by @user", pinging nobody) with a public thread on it named after the slug, which auto-archives after a week, Discord's maximum; the user is added to it and gets a link. A challenge the category already has (by slug, so also once solved and renamed) gets no new thread: the user is added to the existing one, unarchived first if needed, and pointed there. A thread deleted by hand is made again. The challenges are stored in the `ctf_challenges` table (CTF, category slug, slug, thread, solved). The logic is in `ctf/challenges.py`.
- `/solved <flag>`: players of the CTF (with its role), in a challenge thread made with `/create-challenge`; anywhere else, also in another thread, it says to run it in a challenge thread. The thread is renamed to `✅ <slug>` and stays open (people often keep talking after a solve), the solve message with the flag is posted in it, and the challenge is stored as solved. A challenge that is solved already is left as it is and the user told so.
- `/unsolve`: admins, managers and moderators, in a challenge thread. Renames the thread back to `<slug>` and stores the challenge as unsolved; a challenge that is not solved is left as it is.
- `/ctf-status`: admins, managers and moderators, anywhere; only they see the reply. One line per CTF that is not removed, by start (CTFs without dates last): its name linking to its main channel, its CTFtime link and start and finish (when it has a CTFtime ID), its stage (set up, released, locked or archived; locked means its archive failed), its next automatic step and when, or "manual" for a CTF without a CTFtime ID, and how many players joined and are pending. The lines are split over messages to stay under Discord's 2000 characters. The next step comes from `plan()` in `ctf/timeline.py`, the plan of [the automatic timeline](#the-automatic-timeline). The text is built by `ctf/status.py`.
- The challenge overview: one message in the CTF's main channel, posted and pinned when its first challenge is created, its ID stored on the `ctfs` row (`overview_message_id`). Under a mention of each category channel it mentions every challenge thread, so it shows the thread's live name, with ✅ once solved. It is edited when a challenge is created, solved or unsolved; deleted by hand, it is posted and pinned again. When it doesn't fit in one message (2000 characters), the last challenges are left out and it ends with "… and N more". The logic is in `ctf/overview.py`.

### The automatic timeline

For a CTF with a CTFtime ID, the `ctf-timeline` job runs every lifecycle step by itself at its time, every tick, with the same functions as the commands. S and F are the CTF's start and finish on CTFtime:

| When | Step | Same as |
|---|---|---|
| S − 3 days | setup, named after the CTFtime title (cut to 90 characters, for Discord's names) | `/setup-ctf <title> <id>` |
| S − 1 day | last call | `/last-call` |
| F + 1 day | release | `/release-ctf` |
| F + 5 days | lock and archive | `/lock-ctf` |
| F + 5 days + 4 weeks | a reminder in `ADMIN_CHANNEL_ID` to remove the CTF with `/remove-ctf` | — |

- **Setup** happens for every CTFtime event linked from a calendar session (see [CTF sessions](#ctf-sessions-and-the-daily-ctftime-check)) that never had a CTF set up with its ID, also when that CTF was removed since; one CTF per CTFtime ID, however many sessions link to it. Its dates come from what the daily CTFtime check stored, so a CTF it has not seen yet is set up after the next check. There is no automatic setup once it is past F + 5 days.
- **The other steps** run for every CTF that is not removed and has a CTFtime ID. A CTF set up without one never gets automatic steps.
- The steps are planned anew every tick from S, F and the times on the `ctfs` row, so when the daily CTFtime check moves S or F, the steps that haven't run move with it. A step already done, also by command (e.g. an early `/release-ctf`), is not run again, and nothing is ever undone.
- Overdue steps (the bot was down, or the calendar session was added late) run in order on the next tick, except that the last call is skipped once S has passed or joining closed, and the release once the CTF is locked (a lock releases it anyway).
- Each step done is noticed in the CTF's #bot. A step that a command did at the same time is not a failure. A step that fails is logged and tried again every tick, and the steps after it wait; its failure is posted once, in the CTF's #bot (or `ADMIN_CHANNEL_ID` for a setup), until it worked. This is kept in memory, so after a restart a failure is posted once more.
- When every calendar session linking to a set-up CTF that is not locked is cancelled (or no longer links to it), the CTF is kept, and the calendar sync posts a note in its #bot. Sessions that are only over are no reason for a note.

The plan is the pure `plan()` and `plan_setup()` in `ctf/timeline.py`, which `/ctf-status` uses too; `run()` there runs the due steps, and `TimelineActions` in `cogs/ctf_lifecycle.py` does them on the server. The job may run for 30 minutes, so a lock's archive is not stopped halfway.

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

If the feed can't be downloaded, returns an error or doesn't parse, the sync is skipped: a warning is logged, nothing changes in Discord or in the database, and the next sync is tried after `ICS_POLL_MINUTES` as usual. A feed that parses but has no events while the bot manages at least one is skipped the same way, so a hiccup of the calendar provider can't cancel every event at once (an empty feed while the bot manages nothing is a normal sync). This also means that emptying the calendar on purpose doesn't cancel the last events: remove them while at least one other event stays in the calendar. Once the scheduled syncs have kept failing for 10 poll intervals (2.5 hours at the default interval), for whatever reason, one alert is posted in `ADMIN_CHANNEL_ID`, and a short message once it works again (see [Scheduled jobs](#scheduled-jobs)). A failing `/calendar-sync` replies with the reason but doesn't count toward the alert.

The bot needs the **Create Events** and **Manage Events** permissions on the server, and permission to send messages and embeds in `CALENDAR_CHANNEL_ID`.

The sync itself is `sync_calendar()` in `cogs/calendar_feed.py`; it returns a summary of what it created, updated (recreated events included) and cancelled, or raises the `FeedError` of a skipped sync. One lock is held around the sync, so the job and `/calendar-sync` never run at the same time and never create an event twice; a sync that was stopped by its timeout while creating or editing an event finishes that in the background, and the next sync waits for it. The work is split over `feeds/calendar/`: `parse.py` reads the ICS feed, `plan.py` decides what to create, update, recreate, cancel and forget (both pure), `events.py` carries it out on Discord, `store.py` remembers the occurrences, and `sessions.py` reads the CTF sessions from them.

### `/calendar-sync`

Admins (`ADMIN_ROLE`) can run it in any channel to sync right away instead of waiting for the next poll, for example right after editing the calendar. It runs the same sync as the job (waiting for a scheduled sync that is running) and replies, only to the admin, with how many events were created, updated and cancelled, or with the reason the sync was skipped. A skipped sync counts toward the alert like any skipped scheduled sync. When `ICS_URL` is not set it replies that there is no calendar to sync.

### CTF sessions and the daily CTFtime check

A calendar event whose `URL` links to a CTFtime event (`ctftime.org/event/<id>`), or, when `URL` has no such link, whose description does, is a **CTF session**: the on-campus night of that CTF, not the whole CTF. The CTF's own start and finish always come from CTFtime, and several sessions can link to the same CTF. Events without a link (meetups etc.) are never checked. Every sync stores the start, title and CTFtime ID of each occurrence the bot has an event for in `calendar_occurrences`.

Every day at 12:00 `TIMEZONE` the `ctftime-check` job asks CTFtime about every CTF linked from a session that is not over yet, and every CTF that is set up with a CTFtime ID and not locked (also without a session), and keeps what it found per CTF in the `ctftime_events` table (title, start, finish, when it was checked, and the start and finish the admins were last told about). The start and finish are also stored on the CTF's `ctfs` row once it is set up, so its [automatic steps](#the-automatic-timeline) move with them:

- The first time a CTF is seen its dates are stored. When a session already falls outside the CTF (probably a typo in the calendar), that is alerted straight away.
- When CTFtime's start or finish differ from what the admins were last told: one alert with the CTF, the old and new dates and the linked sessions, :warning: when at least one session falls outside the new dates, :information_source: when they all still fall within them. Nothing is posted while the dates stay the same.
- When CTFtime no longer knows the CTF (404): one :warning: alert, not repeated on the next days.
- When CTFtime can't be reached or answers with an error, that CTF is skipped until the next check (logged, no alert).
- An alert that can't be posted is logged and posted on the next check.

Alerts go to the CTF's #bot once it is set up, else (or when its #bot is gone) to `ADMIN_CHANNEL_ID`. Alerts list at most 5 sessions, to stay within one Discord message. The check itself is `check()` in `feeds/ctftime_check.py`; deciding what to post and store is the pure `compare_with_ctftime()` there.

### `/ctftime-check`

Admins (`ADMIN_ROLE`) can run it in any channel to run the daily check right away (waiting for a check that is running). It replies, only to the admin, with how many CTFs were checked and how many alerts were posted, and how many CTFs were skipped because CTFtime could not be reached.

## Blog feed

Every 10 minutes the bot checks [Stellar Vector's blog](https://blog.stellarvector.be/) and shares its new posts as forum posts in `LEARNING_FORUM_ID` (#learning). Without `LEARNING_FORUM_ID` the feature is off.

The check downloads the blog's RSS feed (`https://blog.stellarvector.be/index.xml`) and creates a forum post for every item whose `guid` is not in the `blog_posts_seen` table yet, oldest first. The very first check (empty table) only records the items that are already there and posts nothing, so the blog's history is not posted.

- A writeup (a link under `/writeups/<year>/<ctf-slug>/`) gets the title `[SV writeup] <CTF> / <title>` and the tags `writeup` and `Stellar Vector`. The CTF is the item's `<category domain="ctf">` when it has one, else the CTF slug from the link in title case.
- Any other post gets the title `[SV blog] <title>` and the tag `Stellar Vector`.
- Titles are cut to Discord's 100 characters. The post says what it is, followed by the item's description (when it has one) and the link.
- Tags are looked up on the forum by name, ignoring case. A tag the forum doesn't have is left out with a logged warning; the bot never creates tags.

A feed that can't be downloaded or parsed changes nothing and is logged. A forum post that can't be created is logged, and its item is tried again on the next check. A check fails when the feed can't be read, when it had new items and none of their forum posts could be created, or when it takes longer than 3 minutes (the next check carries on where it left off). Once the scheduled checks have been failing for 24 hours, one alert is posted in `ADMIN_CHANNEL_ID`, and a short message once it works again (see [Scheduled jobs](#scheduled-jobs)). A failing `/blog-check` replies with the reason but doesn't count toward the alert. The scheduled check and `/blog-check` take turns, so they never post the same item twice. The check itself is `check()` in `feeds/blog.py`.

### `/blog-check`

Admins (`ADMIN_ROLE`) can run it in any channel to run the check right away (waiting for a check that is running). It replies, only to the admin, with how many forum posts were created.
