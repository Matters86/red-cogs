"""Discord-UI-Komponenten für den Tickets-Cog.

Panel- und Steuer-Buttons nutzen **stabile** ``custom_id``s und werden zentral
in ``Tickets.on_interaction`` ausgewertet – dadurch funktionieren sie auch nach
einem Bot-Neustart (echte Persistenz), ohne dass pro Panel/Ticket eine View
registriert werden muss.

Transiente Elemente (Modal beim Öffnen, Schließen-Bestätigung) nutzen das
normale View-/Modal-Callback-Modell, da sie nur kurzlebig sind.
"""

from __future__ import annotations

from typing import Awaitable, Callable

import discord

from .strings import t

# custom_id-Präfixe
CID_OPEN = "tickets:open"      # tickets:open:<panel_id>:<reason_id>
CID_SELECT = "tickets:select"  # tickets:select:<panel_id>   (value = reason_id)
CID_CLOSE = "tickets:close"
CID_CLAIM = "tickets:claim"
CID_UNCLAIM = "tickets:unclaim"
CID_LOCK = "tickets:lock"
CID_UNLOCK = "tickets:unlock"


def build_panel_view(panel: dict) -> discord.ui.View:
    """Baut die View eines Panels (Buttons ODER Dropdown) anhand der Config."""
    view = discord.ui.View(timeout=None)
    panel_id = panel["id"]
    reasons = panel.get("reasons") or []
    mode = panel.get("mode", "button")

    if mode == "dropdown" and reasons:
        options = []
        for r in reasons:
            options.append(
                discord.SelectOption(
                    label=(r.get("label") or "Ticket")[:100],
                    value=r["id"],
                    description=(r.get("description") or None),
                    emoji=(r.get("emoji") or None),
                )
            )
        view.add_item(
            discord.ui.Select(
                custom_id=f"{CID_SELECT}:{panel_id}",
                placeholder=panel.get("placeholder") or "Auswahl …",
                options=options[:25],
                min_values=1,
                max_values=1,
            )
        )
        return view

    # Button-Modus
    if reasons:
        for r in reasons:
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label=(r.get("label") or "Ticket")[:80],
                    emoji=(r.get("emoji") or None),
                    custom_id=f"{CID_OPEN}:{panel_id}:{r['id']}",
                )
            )
    else:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.success,
                label=(panel.get("button_label") or "🎟️ Ticket")[:80],
                custom_id=f"{CID_OPEN}:{panel_id}:_",
            )
        )
    return view


def build_controls_view(lang: str, *, claimed: bool = False, locked: bool = False) -> discord.ui.View:
    """Steuerleiste innerhalb eines Tickets (statische custom_ids → persistent)."""
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label=t(lang, "btn_close"),
            emoji="🔒",
            custom_id=CID_CLOSE,
        )
    )
    if claimed:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=t(lang, "btn_unclaim"),
                custom_id=CID_UNCLAIM,
            )
        )
    else:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=t(lang, "btn_claim"),
                emoji="🙋",
                custom_id=CID_CLAIM,
            )
        )
    if locked:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=t(lang, "btn_unlock"),
                custom_id=CID_UNLOCK,
            )
        )
    else:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=t(lang, "btn_lock"),
                custom_id=CID_LOCK,
            )
        )
    return view


class TicketModal(discord.ui.Modal):
    """Fragt beim Öffnen bis zu 5 frei definierte Fragen ab (transient)."""

    def __init__(self, cog, panel_id: str, reason_id: str, questions: list[dict], lang: str):
        super().__init__(title=t(lang, "modal_title")[:45])
        self._cog = cog
        self._panel_id = panel_id
        self._reason_id = reason_id
        self._inputs: list[discord.ui.TextInput] = []
        for q in (questions or [])[:5]:
            style = discord.TextStyle.paragraph if q.get("style") == "long" else discord.TextStyle.short
            field = discord.ui.TextInput(
                label=(q.get("label") or "Frage")[:45],
                placeholder=(q.get("placeholder") or None),
                required=bool(q.get("required", True)),
                style=style,
                max_length=1000,
            )
            self._inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        answers = {f.label: f.value for f in self._inputs}
        await self._cog.create_ticket_from_interaction(
            interaction, self._panel_id, self._reason_id, answers
        )


class ConfirmView(discord.ui.View):
    """Kurzlebige Ja/Nein-Bestätigung (z. B. fürs Schließen)."""

    def __init__(self, callback: Callable[[discord.Interaction], Awaitable[None]], lang: str):
        super().__init__(timeout=60)
        self._callback = callback
        self._lang = lang

        yes = discord.ui.Button(style=discord.ButtonStyle.danger, label=t(lang, "confirm_yes"))
        no = discord.ui.Button(style=discord.ButtonStyle.secondary, label=t(lang, "confirm_no"))
        yes.callback = self._on_yes
        no.callback = self._on_no
        self.add_item(yes)
        self.add_item(no)

    async def _on_yes(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        self.stop()
        await self._callback(interaction)

    async def _on_no(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        self.stop()
        await interaction.response.edit_message(content=t(self._lang, "cancelled"), view=self)
