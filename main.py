import bot
import commands
import events

LOAD_EVENTS = [
    "on_ready",
]
LOAD_COMMANDS = [
    "create_ctf",
    "create_challenge",
    "add_player",
]

if __name__ == "__main__":
    bot.init()
    events.load(LOAD_EVENTS)
    events.register(LOAD_EVENTS)
    commands.load(LOAD_COMMANDS)
    bot.run()
