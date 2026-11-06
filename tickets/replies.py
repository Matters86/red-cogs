"""Schnellantwort auswählen → bearbeiten → prüfen → ausdrücklich senden."""
import discord


class ReplyPicker(discord.ui.View):
    def __init__(self, cog, requester_id, replies):
        super().__init__(timeout=180)
        self.cog, self.requester_id = cog, requester_id
        self.select = discord.ui.Select(placeholder="Schnellantwort auswählen", options=[
            discord.SelectOption(label=reply["label"][:100], value=reply["id"]) for reply in replies[:25]])
        self.select.callback = self.selected
        self.add_item(self.select)

    async def selected(self, interaction):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message("Diese Auswahl gehört einer anderen Person.", ephemeral=True)
        error, text = await self.cog._prepare_reply(interaction.guild, interaction.channel, interaction.user, self.select.values[0])
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        await interaction.response.send_modal(ReplyModal(self.cog, self.requester_id, text))


class ReplyModal(discord.ui.Modal, title="Schnellantwort bearbeiten"):
    def __init__(self, cog, requester_id, text):
        super().__init__(timeout=180)
        self.cog, self.requester_id = cog, requester_id
        self.body = discord.ui.TextInput(label="Antwort (wird erst nach Vorschau gesendet)",
            style=discord.TextStyle.paragraph, default=text, max_length=2000, required=True)
        self.add_item(self.body)

    async def on_submit(self, interaction):
        error = await self.cog._reply_access(interaction.guild, interaction.channel, interaction.user)
        if interaction.user.id != self.requester_id or error:
            return await interaction.response.send_message(error or "Keine Berechtigung.", ephemeral=True)
        text = self.body.value.strip()
        await interaction.response.send_message("**Vorschau – noch nicht gesendet**",
            embed=discord.Embed(description=text, color=0x3DDC97),
            view=ReplyPreview(self.cog, self.requester_id, text), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())


class ReplyPreview(discord.ui.View):
    def __init__(self, cog, requester_id, text):
        super().__init__(timeout=180)
        self.cog, self.requester_id, self.text = cog, requester_id, text
        self.sending = False
        send = discord.ui.Button(label="Antwort jetzt senden", style=discord.ButtonStyle.primary)
        edit = discord.ui.Button(label="Bearbeiten", style=discord.ButtonStyle.secondary)
        send.callback, edit.callback = self.send, self.edit
        self.add_item(send)
        self.add_item(edit)

    async def edit(self, interaction):
        if interaction.user.id != self.requester_id or self.sending:
            return await interaction.response.send_message("Diese Vorschau ist nicht verfügbar.", ephemeral=True)
        error = await self.cog._reply_access(interaction.guild, interaction.channel, interaction.user)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        await interaction.response.send_modal(ReplyModal(self.cog, self.requester_id, self.text))

    async def send(self, interaction):
        if interaction.user.id != self.requester_id or self.sending:
            return await interaction.response.send_message("Diese Vorschau ist nicht verfügbar.", ephemeral=True)
        self.sending = True
        await interaction.response.defer(ephemeral=True)
        error = await self.cog._send_support_reply(interaction.guild, interaction.channel, interaction.user, self.text)
        if error:
            self.sending = False
        else:
            self.stop()
            for child in self.children:
                child.disabled = True
            try:
                await interaction.edit_original_response(content="Antwort gesendet.", embed=None, view=self)
            except discord.HTTPException:
                pass
        await interaction.followup.send(error or "Antwort gesendet.", ephemeral=True)


class PriorityView(discord.ui.View):
    def __init__(self, cog, requester_id, priority):
        super().__init__(timeout=120)
        self.cog, self.requester_id = cog, requester_id
        self.select = discord.ui.Select(placeholder="Priorität auswählen", options=[
            discord.SelectOption(label=label, value=value, default=priority == value)
            for value, label in (("normal", "Normal"), ("urgent", "Dringend"))])
        self.select.callback = self.selected
        self.add_item(self.select)

    async def selected(self, interaction):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message("Diese Auswahl gehört einer anderen Person.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        error = await self.cog._set_priority(interaction.guild, interaction.channel, self.select.values[0], interaction.user)
        await interaction.followup.send(error or "Priorität aktualisiert.", ephemeral=True)
