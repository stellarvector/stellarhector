import commands
import bot

async def handle():
    await commands.register()
    print(f'Logged on as {bot.client.user}!')
