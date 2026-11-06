"""Persistente Raumsteuerung; Rechte werden bei jeder Aktion frisch geprüft."""
import discord


def room_controls(room_id):
    view = discord.ui.View(timeout=None)
    for action, label in (("public", "Öffentlich"), ("locked", "Gesperrt"), ("private", "Privat"),
                          ("limit", "Personenlimit"), ("transfer", "Übergeben"), ("claim", "Übernehmen")):
        view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary,
                                       custom_id=f"autoroom:{action}:{room_id}"))
    return view


class RoomLimitModal(discord.ui.Modal, title="Personenlimit ändern"):
    def __init__(self, cog, room_id):
        super().__init__()
        self.cog, self.room_id = cog, room_id
        self.limit = discord.ui.TextInput(label="0 bis 99 (0 = unbegrenzt)", max_length=2)
        self.add_item(self.limit)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        value = self.limit.value.strip()
        if not value.isdigit() or not 0 <= int(value) <= 99:
            return await interaction.followup.send("Bitte eine ganze Zahl von 0 bis 99 eingeben.", ephemeral=True)
        error = await self.cog.change_room(interaction.guild, self.room_id, interaction.user, "limit", int(value))
        await interaction.followup.send(error or "Personenlimit geändert.", ephemeral=True)


class RoomTransferView(discord.ui.View):
    def __init__(self, cog, room_id, requester_id):
        super().__init__(timeout=120)
        self.cog, self.room_id, self.requester_id = cog, room_id, requester_id
        self.select = discord.ui.UserSelect(placeholder="Neuer Besitzer (muss im Raum sein)", min_values=1, max_values=1)
        self.select.callback = self.selected
        self.add_item(self.select)

    async def selected(self, interaction):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message("Diese Auswahl gehört einer anderen Person.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        error = await self.cog.change_room(interaction.guild, self.room_id, interaction.user,
                                           "transfer", self.select.values[0].id)
        await interaction.followup.send(error or "Raum übergeben.", ephemeral=True)
        if not error:
            self.stop()
            await interaction.edit_original_response(content="Raum übergeben.", view=None)
