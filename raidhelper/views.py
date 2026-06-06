"""Discord-UI-Komponenten für den RaidHelper-Cog.

Wie im Tickets-Cog nutzen alle Komponenten **stabile** ``custom_id``s, in die
die Event-ID eingebettet ist. Die Auswertung passiert zentral in
``RaidHelper.on_interaction`` – dadurch funktionieren die Buttons/Selects auch
nach einem Bot-Neustart, ohne dass pro Event eine View registriert werden muss.

custom_id-Schema::

    rh:cls:<event_id>            (Select, value = class_id)
    rh:spec:<event_id>:<class>  (Select, value = spec_id)   – ephemer
    rh:st:<event_id>:<status>   (Button: bench|late|tentative|absence)
    rh:leave:<event_id>         (Button)
"""

from __future__ import annotations

import discord

from . import games
from .strings import role_name, t

CID_CLASS = "rh:cls"
CID_SPEC = "rh:spec"
CID_STATUS = "rh:st"
CID_LEAVE = "rh:leave"

STATUS_EMOJI = {
    "bench": "🪑",
    "late": "🕐",
    "tentative": "❔",
    "absence": "❌",
}
STATUS_BUTTONS = ["bench", "late", "tentative", "absence"]


def build_signup_view(event: dict, lang: str, *, emojis: dict | None = None) -> discord.ui.View:
    """Anmelde-View unter dem Event: Klassen-Dropdown + Status-/Abmelde-Buttons."""
    view = discord.ui.View(timeout=None)
    game_id = event.get("game") or games.DEFAULT_GAME
    event_id = event["id"]
    closed = bool(event.get("closed"))

    if not closed:
        options = []
        for cid in games.class_order(game_id)[:25]:
            opt = discord.SelectOption(
                label=games.class_label(game_id, cid)[:100],
                value=cid,
            )
            if emojis and emojis.get(cid):
                try:
                    opt.emoji = discord.PartialEmoji.from_str(emojis[cid])
                except (ValueError, TypeError):
                    pass
            options.append(opt)
        if options:
            view.add_item(
                discord.ui.Select(
                    custom_id=f"{CID_CLASS}:{event_id}",
                    placeholder=t(lang, "select_class_placeholder"),
                    options=options,
                    min_values=1,
                    max_values=1,
                    row=0,
                )
            )

    for st in STATUS_BUTTONS:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=t(lang, f"btn_{st}"),
                emoji=STATUS_EMOJI[st],
                custom_id=f"{CID_STATUS}:{event_id}:{st}",
                row=1,
                disabled=closed,
            )
        )
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label=t(lang, "btn_leave"),
            emoji="↩️",
            custom_id=f"{CID_LEAVE}:{event_id}",
            row=1,
        )
    )
    return view


def build_spec_view(event_id: str, class_id: str, game_id: str, lang: str,
                    class_emoji: str | None = None) -> discord.ui.View:
    """Kurzlebige Spec-Auswahl (ephemer), erscheint bei Klassen mit mehreren Specs."""
    view = discord.ui.View(timeout=180)
    parsed_emoji = None
    if class_emoji:
        try:
            parsed_emoji = discord.PartialEmoji.from_str(class_emoji)
        except (ValueError, TypeError):
            parsed_emoji = None
    options = []
    for sid, label, role in games.specs_of(game_id, class_id):
        options.append(
            discord.SelectOption(
                label=label[:100],
                value=sid,
                description=role_name(lang, role)[:100],
                emoji=parsed_emoji,
            )
        )
    view.add_item(
        discord.ui.Select(
            custom_id=f"{CID_SPEC}:{event_id}:{class_id}",
            placeholder=t(lang, "select_spec_placeholder"),
            options=options[:25],
            min_values=1,
            max_values=1,
        )
    )
    return view
