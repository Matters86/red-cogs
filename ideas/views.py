"""Discord-Oberfläche des Ideas-Cogs: Panel-Button (persistent), Kategorie-Auswahl, Formular (Modal).

Ablauf beim Einreichen (Entscheidung „zweistufig“):

1. Persistenter Button ``ideas:submit`` im angepinnten Panel-Beitrag (eine View für alle Server,
   registriert mit ``bot.add_view`` – funktioniert nach Neustart/Reload weiter).
2. Sind Kategorien eingestellt: ephemere Auswahlliste (nur für den Klickenden sichtbar) mit den
   Kategorien + „Ohne Kategorie“. Ohne Kategorien entfällt der Schritt.
3. Modal mit Titel (max. 100) und Beschreibung (max. 1000). Die Kategorie kommt aus Schritt 2 –
   dadurch kann sie nicht falsch geschrieben werden (ein Modal kann in allen discord.py-Versionen,
   die Red 3.5 mitbringt, keine Auswahlliste enthalten).

Die eigentliche Prüfung und das Anlegen macht ``Ideas.submit`` – dieselbe Funktion wie die Webseite.
"""

from __future__ import annotations

import discord

from .strings import t

CID_SUBMIT = "ideas:submit"
MAX_TITLE = 100
MAX_DESC = 1000


class PanelView(discord.ui.View):
    """Persistente View des Panels – ``custom_id`` fest, Server kommt aus der Interaktion."""

    def __init__(self, cog, lang: str = "de"):
        super().__init__(timeout=None)
        self.cog = cog
        button = discord.ui.Button(style=discord.ButtonStyle.success, label=t(lang, "panel_button"),
                                   emoji="💡", custom_id=CID_SUBMIT)
        button.callback = self._submit
        self.add_item(button)

    async def _submit(self, interaction: discord.Interaction):
        await self.cog.open_submit(interaction)


class CategorySelect(discord.ui.Select):
    def __init__(self, cog, categories, lang):
        options = [discord.SelectOption(label=c[:100], value=c[:100]) for c in categories[:24]]
        options.append(discord.SelectOption(label=t(lang, "cat_none"), value="__none__", emoji="➖"))
        super().__init__(placeholder=t(lang, "cat_placeholder"), min_values=1, max_values=1, options=options)
        self.cog = cog
        self.lang = lang

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0] if self.values else "__none__"
        category = None if value == "__none__" else value
        await interaction.response.send_modal(IdeaModal(self.cog, self.lang, category))


class CategoryView(discord.ui.View):
    """Ephemere Kategorie-Auswahl (Schritt 2) – nicht persistent, läuft nach 3 Minuten ab."""

    def __init__(self, cog, categories, lang):
        super().__init__(timeout=180)
        self.select = CategorySelect(cog, categories, lang)
        self.add_item(self.select)


class IdeaModal(discord.ui.Modal):
    def __init__(self, cog, lang: str, category: str | None = None):
        title = t(lang, "modal_title")
        if category:
            title = f"{title} · {category}"
        super().__init__(title=title[:45], timeout=900)
        self.cog = cog
        self.lang = lang
        self.category = category
        self.idea_title = discord.ui.TextInput(
            label=t(lang, "modal_field_title"), placeholder=t(lang, "modal_title_ph")[:100],
            max_length=MAX_TITLE, min_length=1, required=True,
        )
        self.idea_desc = discord.ui.TextInput(
            label=t(lang, "modal_field_desc"), placeholder=t(lang, "modal_desc_ph")[:100],
            style=discord.TextStyle.paragraph, max_length=MAX_DESC, required=False,
        )
        self.add_item(self.idea_title)
        self.add_item(self.idea_desc)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.submit_from_modal(interaction, str(self.idea_title.value), str(self.idea_desc.value),
                                         self.category)
