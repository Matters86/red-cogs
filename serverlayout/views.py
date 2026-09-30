"""Bestätigung für ``[p]layout load``: Buttons „Laden“/„Abbrechen“, beim Angleichen zusätzlich ein Modal,
in das der Server-Name eingetippt werden muss."""

from __future__ import annotations

import discord

from .strings import t


class NameModal(discord.ui.Modal):
    def __init__(self, view: "ConfirmView"):
        super().__init__(title=t(view.lang, "modal_title")[:45], timeout=180)
        self.confirm_view = view
        self.server_name = discord.ui.TextInput(label=t(view.lang, "modal_label")[:45], max_length=100)
        self.add_item(self.server_name)

    async def on_submit(self, interaction: discord.Interaction):
        if str(self.server_name.value).strip() != str(self.confirm_view.guild.name).strip():
            await interaction.response.send_message(t(self.confirm_view.lang, "name_mismatch"), ephemeral=True)
            return
        await self.confirm_view.start(interaction)


class ConfirmView(discord.ui.View):
    def __init__(self, cog, ctx, lang: str, meta: dict, plan: dict):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.guild = ctx.guild
        self.author_id = ctx.author.id
        self.lang = lang
        self.meta = meta
        self.plan = plan
        self.message = None
        self.load_button.label = t(lang, "btn_load")
        self.cancel_button.label = t(lang, "btn_cancel")
        if plan["mode"] == "exact":
            self.load_button.style = discord.ButtonStyle.danger

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id and not await self.cog.bot.is_owner(interaction.user):
            await interaction.response.send_message(t(self.lang, "not_yours"), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Laden", style=discord.ButtonStyle.success)
    async def load_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.plan["mode"] == "exact":
            await interaction.response.send_modal(NameModal(self))
            return
        await self.start(interaction)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content=t(self.lang, "aborted"), view=None)

    async def start(self, interaction: discord.Interaction):
        from .serverlayout import LoadError
        self.stop()
        prefix = getattr(self.ctx, "clean_prefix", "")
        try:
            await self.cog.start_load(self.guild, self.meta["id"], mode=self.plan["mode"], parts=self.plan["parts"],
                                      user=interaction.user, expected_hash=self.plan["hash"], notify=self.ctx.channel,
                                      protect_channel_id=getattr(self.ctx.channel, "id", None))
        except LoadError as exc:
            text = t(self.lang, exc.key, prefix=prefix, **exc.kwargs)
            await interaction.response.edit_message(content=text[:1990], view=None)
            return
        await interaction.response.edit_message(
            content=t(self.lang, "started", name=self.meta["name"], mode=t(self.lang, f"mode_{self.plan['mode']}"),
                      prefix=prefix), view=None)

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(content=t(self.lang, "timeout"), view=None)
            except discord.HTTPException:
                pass
