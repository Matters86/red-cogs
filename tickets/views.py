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
CID_AUTOCLOSE = "tickets:autoclose"
CID_KEEP_OPEN = "tickets:keep_open"
CID_ASSIGN = "tickets:assign"
CID_WAIT_USER = "tickets:wait_user"
CID_WAIT_TEAM = "tickets:wait_team"
CID_PRIORITY = "tickets:priority"
CID_REPLY = "tickets:reply"

ANSWER_MAX = 1000  # max. Zeichen je Antwort (Discord-Modal und Website)


def build_panel_view(panel: dict, *, open_label: str | None = None, emojis: bool = True) -> discord.ui.View:
    """Baut die View eines Panels (Buttons ODER Dropdown) anhand der Config.

    ``open_label``: Beschriftung des Einzel-Buttons (Override ``btn_open``), falls das
    Panel keine eigene hat. ``emojis=False`` lässt alle Emojis weg (Fallback, wenn
    Discord ein ungültiges Emoji ablehnt).
    """
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
                    description=((r.get("description") or "")[:100] or None),  # Discord-Limit 100
                    emoji=((r.get("emoji") or None) if emojis else None),
                )
            )
        view.add_item(
            discord.ui.Select(
                custom_id=f"{CID_SELECT}:{panel_id}",
                placeholder=(panel.get("placeholder") or "Auswahl …")[:150],
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
                    emoji=((r.get("emoji") or None) if emojis else None),
                    custom_id=f"{CID_OPEN}:{panel_id}:{r['id']}",
                )
            )
    else:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.success,
                label=(open_label or panel.get("button_label") or "🎟️ Ticket")[:80],
                custom_id=f"{CID_OPEN}:{panel_id}:_",
            )
        )
    return view


def build_controls_view(lang: str, *, claimed: bool = False, locked: bool = False,
                        auto_close: bool = False, waiting_for: str = "team", priority: str = "normal") -> discord.ui.View:
    """Steuerleiste innerhalb eines Tickets (statische custom_ids → persistent)."""
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label=t(lang, "btn_close"),
            emoji="🔒",
            custom_id=CID_CLOSE,
            row=0,
        )
    )
    if claimed:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=t(lang, "btn_unclaim"),
                custom_id=CID_UNCLAIM,
                row=0,
            )
        )
    else:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=t(lang, "btn_claim"),
                emoji="🙋",
                custom_id=CID_CLAIM,
                row=0,
            )
        )
    if locked:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=t(lang, "btn_unlock"),
                custom_id=CID_UNLOCK,
                row=1,
            )
        )
    else:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=t(lang, "btn_lock"),
                custom_id=CID_LOCK,
                row=1,
            )
        )
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.secondary,
        label=t(lang, "btn_keep_open" if auto_close else "btn_autoclose"),
        emoji="⏱️",
        custom_id=CID_KEEP_OPEN if auto_close else CID_AUTOCLOSE,
        row=1,
    ))
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.secondary,
        label=t(lang, "btn_assign"),
        custom_id=CID_ASSIGN,
        row=0,
    ))
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.secondary,
        label=t(lang, "btn_wait_team" if waiting_for == "user" else "btn_wait_user"),
        custom_id=CID_WAIT_TEAM if waiting_for == "user" else CID_WAIT_USER, row=1,
    ))
    view.add_item(discord.ui.Button(label="Schnellantwort", custom_id=CID_REPLY,
                                   style=discord.ButtonStyle.secondary, row=1))
    view.add_item(discord.ui.Button(label="Dringend" if priority == "urgent" else "Priorität: Normal",
                                   custom_id=CID_PRIORITY, style=discord.ButtonStyle.secondary, row=1))
    return view


def build_reminder_view(lang):
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label=t(lang, "btn_keep_open"), custom_id=CID_KEEP_OPEN,
                                   style=discord.ButtonStyle.primary))
    view.add_item(discord.ui.Button(label=t(lang, "btn_close"), custom_id=CID_CLOSE,
                                   style=discord.ButtonStyle.secondary))
    return view


def modal_fields(questions) -> list[dict]:
    """Normalisierte Modal-Fragen (max. 5) – gemeinsam für das Discord-Modal und die Website.

    ``label`` ist zugleich der Schlüssel der Antwort im Ticket-Embed (wie bisher ``f.label``).
    """
    out = []
    for q in (questions or [])[:5]:
        out.append({
            "label": (q.get("label") or "Frage")[:45],
            "placeholder": (q.get("placeholder") or None),
            "required": bool(q.get("required", True)),
            "long": q.get("style") == "long",
            "max_length": ANSWER_MAX,
        })
    return out


class TicketModal(discord.ui.Modal):
    """Fragt beim Öffnen bis zu 5 frei definierte Fragen ab (transient)."""

    def __init__(self, cog, panel_id: str, reason_id: str, questions: list[dict], lang: str):
        super().__init__(title=t(lang, "modal_title")[:45])
        self._cog = cog
        self._panel_id = panel_id
        self._reason_id = reason_id
        self._inputs: list[discord.ui.TextInput] = []
        for q in modal_fields(questions):
            style = discord.TextStyle.paragraph if q["long"] else discord.TextStyle.short
            field = discord.ui.TextInput(
                label=q["label"],
                placeholder=q["placeholder"],
                required=q["required"],
                style=style,
                max_length=q["max_length"],
            )
            self._inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        answers = {f.label: f.value for f in self._inputs}
        await self._cog.create_ticket_from_interaction(
            interaction, self._panel_id, self._reason_id, answers
        )


class AssignmentView(discord.ui.View):
    """Kurzlebige Mitgliedersuche, geöffnet über den persistenten Zuweisen-Button."""

    def __init__(self, cog, requester_id: int, lang: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.requester_id = requester_id
        self.lang = lang
        self.select = discord.ui.UserSelect(
            placeholder=t(lang, "assign_placeholder"), min_values=1, max_values=1,
        )
        self.select.callback = self._selected
        self.add_item(self.select)

    async def _selected(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message(t(self.lang, "no_permission"), ephemeral=True)
        if await self.cog._assign_from_interaction(interaction, self.select.values[0].id):
            self.stop()
            await interaction.edit_original_response(content=t(self.lang, "assignment_done"), view=None)


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
