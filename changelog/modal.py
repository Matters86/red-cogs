"""Discord-Modal für den Changelog-Cog.

Das Modal hat genau die fünf im Plan vorgesehenen Felder (Titel, Neu, Geändert,
Fixes, Hinweis). Discord-Modals erlauben max. 5 Textfelder und keine
Dropdowns – die Kategorie-Auswahl passiert daher vor dem Modal über den
Slash-Parameter ``kategorie``.

Das Modal ist transient (kurzlebig): nach dem Absenden ruft ``on_submit`` den
Cog auf, der validiert, das Embed baut und postet.
"""

from __future__ import annotations

import discord

from .strings import t


class ChangelogModal(discord.ui.Modal):
    """Formular zum Erfassen eines Changelogs (wird pro Aufruf neu gebaut)."""

    def __init__(self, cog, *, lang: str, category_emoji: str, category_label: str):
        super().__init__(title=t(lang, "modal_title")[:45])
        self._cog = cog
        self._lang = lang
        self._category_emoji = category_emoji
        self._category_label = category_label

        self.titel = discord.ui.TextInput(
            label=t(lang, "f_title_label")[:45],
            placeholder=t(lang, "f_title_ph")[:100],
            required=True,
            max_length=230,
            style=discord.TextStyle.short,
        )
        self.neu = discord.ui.TextInput(
            label=t(lang, "f_new_label")[:45],
            placeholder=t(lang, "ph_lines")[:100],
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.geaendert = discord.ui.TextInput(
            label=t(lang, "f_changed_label")[:45],
            placeholder=t(lang, "ph_lines")[:100],
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.fixes = discord.ui.TextInput(
            label=t(lang, "f_fixes_label")[:45],
            placeholder=t(lang, "ph_lines")[:100],
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.hinweis = discord.ui.TextInput(
            label=t(lang, "f_note_label")[:45],
            placeholder=t(lang, "f_note_ph")[:100],
            required=False,
            max_length=200,
            style=discord.TextStyle.short,
        )

        for item in (self.titel, self.neu, self.geaendert, self.fixes, self.hinweis):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await self._cog.handle_modal_submit(
            interaction,
            title=self.titel.value,
            neu=self.neu.value,
            geaendert=self.geaendert.value,
            fixes=self.fixes.value,
            hinweis=self.hinweis.value,
            category_emoji=self._category_emoji,
            category_label=self._category_label,
            lang=self._lang,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):  # noqa: D401
        # Fehler nicht verschlucken, aber der Person eine saubere Rückmeldung geben.
        msg = "⚠️ " + str(error)
        if interaction.response.is_done():
            await interaction.followup.send(msg[:1900], ephemeral=True)
        else:
            await interaction.response.send_message(msg[:1900], ephemeral=True)
