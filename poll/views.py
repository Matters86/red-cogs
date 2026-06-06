"""Discord-UI-Komponenten für den Poll-Cog.

Wie im RaidHelper-/Tickets-Cog nutzen alle Buttons **stabile** ``custom_id``s,
in die die Umfrage-ID und der Options-Index eingebettet sind. Die Auswertung
passiert zentral in ``Poll.on_interaction`` – dadurch funktionieren die Buttons
auch nach einem Bot-Neustart, ohne dass pro Umfrage eine View registriert
werden muss.

custom_id-Schema::

    poll:vote:<poll_id>:<option_index>

Als visueller Anker zwischen Embed und Button dient die **Nummer** der Option
(Embed: 1️⃣/2️⃣/…, Button: ``1.``/``2.``/…).
"""

from __future__ import annotations

import discord

from .embed import vote_counts

CID_VOTE = "poll:vote"

# Discord erlaubt max. 5 Komponenten je Reihe und 5 Reihen -> 25 Buttons.
MAX_OPTION_BUTTONS = 25


def build_poll_view(poll: dict) -> discord.ui.View:
    """Abstimm-View unter der Umfrage: ein Button je Option mit Live-Zähler."""
    view = discord.ui.View(timeout=None)
    poll_id = poll["id"]
    options = (poll.get("options") or [])[:MAX_OPTION_BUTTONS]
    counts, _, _ = vote_counts(poll)
    disabled = bool(poll.get("closed") or poll.get("ended"))

    for idx, opt in enumerate(options):
        count = counts[idx] if idx < len(counts) else 0
        # Label: "<n>. <Option>  ·  <Zähler>" auf 80 Zeichen begrenzt (Discord-Limit).
        prefix = f"{idx + 1}. "
        suffix = f"  ·  {count}"
        room = 80 - len(prefix) - len(suffix)
        text = (opt[: room - 1] + "…") if len(opt) > room else opt
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=f"{prefix}{text}{suffix}",
                custom_id=f"{CID_VOTE}:{poll_id}:{idx}",
                row=idx // 5,
                disabled=disabled,
            )
        )
    return view
