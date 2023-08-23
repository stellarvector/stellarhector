import logging

async def default(interaction, error):
    logging.getLogger("bot").error(f"Command error: {error}")

    await interaction.response.send_message(f"Sorry, an unknown error occurred, please ask an admin for help.", ephemeral=True)
