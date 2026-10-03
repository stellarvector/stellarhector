import logging

async def default(interaction, error):
    logging.getLogger("bot").error(f"Command error: {error}")

    content = "Sorry, an unknown error occurred, please ask an admin for help."
    # A deferred interaction can't be responded to again
    if interaction.response.is_done():
        await interaction.followup.send(content=content)
    else:
        await interaction.response.send_message(content=content)
