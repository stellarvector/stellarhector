import bot

def load(load_commands):
    for handler in load_commands:
        __import__(f"command_handlers.{handler}")

async def register():
    synced = await bot.client.tree.sync(guild=bot.guild)
    print(f"Synced commands: {len(synced)} commands registered")
