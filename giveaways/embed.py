"""Embed und Buttons für Gewinnspiele (Discord-Limits: Titel 256, Beschreibung 4096, Feld 1024).

custom_id-Schema des persistenten Teilnahme-Buttons::

    gw:join:<guild_id>:<giveaway_id>

Die View hat ``timeout=None`` und nur Elemente mit fester ``custom_id`` -> sie ist persistent.
Beim Laden des Cogs registriert ``Giveaways._restore_views`` für jedes laufende Gewinnspiel eine
View per ``bot.add_view(view, message_id=…)`` – Klicks funktionieren damit auch nach einem
Neustart. Der Callback sucht den Cog jedes Mal frisch (``client.get_cog``), damit auch nach
einem ``[p]reload`` nie eine alte Cog-Instanz antwortet.
"""

from __future__ import annotations

import discord

from .core import MAX_ROLE_LIST, status_of
from .strings import t

CID_JOIN = "gw:join"
COLOR_ENDED = 0x2B2D31
COLOR_CANCELLED = 0x6B6F76


def _mentions(ids, limit=MAX_ROLE_LIST) -> str:
    ids = [int(i) for i in (ids or [])][:limit]
    return ", ".join(f"<@&{i}>" for i in ids)


def _color(value, default=0xF5B94A) -> int:
    try:
        return int(str(value).lstrip("#"), 16) if value else default
    except ValueError:
        return default


def build_embed(gw: dict, lang: str, *, color=None) -> discord.Embed:
    status = status_of(gw)
    end_ts = int(gw.get("end_ts") or 0)
    prize = (gw.get("prize") or "?")[:200]
    lines = []
    desc = (gw.get("description") or "").strip()
    if desc:
        lines += [desc[:1500], ""]

    if status == "running":
        lines.append("⏳ " + t(lang, "embed_ends", rel=f"<t:{end_ts}:R>", abs=f"<t:{end_ts}:f>"))
        lines.append("🏆 " + t(lang, "embed_winners_count", n=int(gw.get("winner_count") or 1)))
        emb_color = _color(color)
    elif status == "cancelled":
        lines.append(t(lang, "embed_cancelled"))
        emb_color = COLOR_CANCELLED
    else:
        ended = int(gw.get("ended_ts") or end_ts)
        lines.append("🏁 " + t(lang, "embed_ended", rel=f"<t:{ended}:R>"))
        emb_color = COLOR_ENDED
    if gw.get("host_id"):
        lines.append("👤 " + t(lang, "embed_host", host=f"<@{int(gw['host_id'])}>"))

    emb = discord.Embed(title=f"🎉 {prize}", description="\n".join(lines)[:4000], color=emb_color)

    if status == "ended":
        winners = [int(w) for w in gw.get("winner_ids") or []]
        value = " ".join(f"<@{w}>" for w in winners) if winners else t(lang, "embed_no_winners")
        emb.add_field(name=t(lang, "embed_winners"), value=value[:1024], inline=False)

    if status == "running":
        req = []
        if gw.get("required_roles"):
            req.append(t(lang, "req_required", roles=_mentions(gw["required_roles"])))
        if gw.get("excluded_roles"):
            req.append(t(lang, "req_excluded", roles=_mentions(gw["excluded_roles"])))
        if int(gw.get("min_member_days") or 0) > 0:
            req.append(t(lang, "req_days", days=int(gw["min_member_days"])))
        if req:
            emb.add_field(name=t(lang, "embed_requirements"), value="\n".join(f"• {r}" for r in req)[:1024],
                          inline=False)
        bonus = gw.get("bonus_roles") or {}
        if bonus:
            val = "\n".join(t(lang, "bonus_line", role=f"<@&{int(rid)}>", n=int(n)) for rid, n in bonus.items())
            emb.add_field(name=t(lang, "embed_bonus"), value=val[:1024], inline=True)

    emb.add_field(name=t(lang, "embed_entries"), value=str(len(gw.get("entrants") or {})), inline=True)
    footer = "embed_footer" if status == "running" else "embed_footer_done"
    emb.set_footer(text=t(lang, footer, id=gw.get("id", "?")))
    return emb


class JoinView(discord.ui.View):
    """Persistente Teilnahme-View (ein Button, feste custom_id)."""

    is_giveaway_view = True  # Marker für das Aufräumen in cog_unload (auch nach Reload erkennbar)

    def __init__(self, guild_id: int, gw: dict, lang: str):
        super().__init__(timeout=None)
        self.gw_id = str(gw.get("id"))
        self.guild_id = int(guild_id)
        status = status_of(gw)
        count = len(gw.get("entrants") or {})
        if status == "running":
            label = f"{t(lang, 'button_join')} · {count}"
        else:
            label = t(lang, "button_cancelled" if status == "cancelled" else "button_ended") + f" · {count}"
        button = discord.ui.Button(
            style=discord.ButtonStyle.success if status == "running" else discord.ButtonStyle.secondary,
            emoji="🎉", label=label[:80], custom_id=f"{CID_JOIN}:{self.guild_id}:{self.gw_id}",
            disabled=status != "running",
        )
        button.callback = self._on_click
        self.add_item(button)

    async def _on_click(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Giveaways") if interaction.client else None
        if cog is None:
            return
        await cog.handle_join_click(interaction, self.gw_id)


class LeaveConfirmView(discord.ui.View):
    """Ephemere Rückfrage „Wirklich austreten?“ nach erneutem Klick (nicht persistent)."""

    def __init__(self, gw_id: str, lang: str, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.gw_id = str(gw_id)
        # Zufällige custom_id (nicht persistent): gleichzeitige Rückfragen mehrerer Mitglieder kollidieren nicht.
        button = discord.ui.Button(style=discord.ButtonStyle.danger, label=t(lang, "button_leave"))
        button.callback = self._on_leave
        self.add_item(button)

    async def _on_leave(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Giveaways") if interaction.client else None
        if cog is None:
            return
        self.stop()
        await cog.handle_leave_click(interaction, self.gw_id)
