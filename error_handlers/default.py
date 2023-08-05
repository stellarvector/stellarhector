
async def default(interaction, error):
    await interaction.response.send_message(f"Sorry, an unknown error occurred, please ask an admin for help.", ephemeral=True)
    print(f"Error: {error}")
