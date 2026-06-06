"""Event-Embed für den RaidHelper-Cog.

Baut aus einem Event-Datensatz + Spiel-Template das Discord-Embed. Die
Anmeldungen werden nach **Rolle** gruppiert (Rolle = Spec-Rolle aus
``games.py``). Reine Daten kommen aus dem Cog; hier nur Darstellung.

Datensatz eines Events (relevante Felder)::

    {
        "id": "rh-0042", "game": "wow_retail",
        "title": str, "description": str, "color": int|None,
        "leader_id": int, "channel_id": int, "message_id": int|None,
        "start_ts": int, "deadline_ts": int|None,
        "max_signups": int|None, "role_limits": {role: int},
        "recurrence": str|None, "closed": bool,
        "signups": { "<user_id>": {
            "name": str, "class": str|None, "spec": str|None,
            "role": str|None, "status": str, "at": int } },
    }

``status`` ist eines von: ``signed`` (im Roster), ``bench``, ``late``,
``tentative``, ``absence``.
"""

from __future__ import annotations

import discord

from . import games
from .strings import role_name, t

DEFAULT_COLOR = 0x3DDC97
MAX_LINES_PER_FIELD = 28  # Schutz gegen das 1024-Zeichen-Limit eines Embed-Feldes

_STATUS_EMOJI = {
    "bench": "🪑",
    "late": "🕐",
    "tentative": "❔",
    "absence": "❌",
}
_STATUS_ORDER = ["bench", "late", "tentative", "absence"]


def _ordered_signups(event: dict) -> list[tuple[str, dict]]:
    """Anmeldungen nach Anmeldezeit sortiert -> stabile Nummerierung."""
    items = list((event.get("signups") or {}).items())
    items.sort(key=lambda kv: (kv[1].get("at") or 0, kv[0]))
    return items


def _member_line(order_no: int, game_id: str, entry: dict, emojis: dict | None = None) -> str:
    """Eine Roster-Zeile: 'n. [Icon] [Spec] Name'."""
    name = entry.get("name") or "?"
    cid = entry.get("class")
    sid = entry.get("spec")
    icon = ""
    if cid and emojis and emojis.get(cid):
        icon = f"{emojis[cid]} "
    if cid and sid:
        tag = f"`{games.spec_label(game_id, cid, sid)}` "
    elif cid:
        tag = f"`{games.class_label(game_id, cid)}` "
    else:
        tag = ""
    return f"`{order_no}` {icon}{tag}{name}"


def _field_value(lines: list[str], lang: str) -> str:
    if not lines:
        return "—"
    if len(lines) > MAX_LINES_PER_FIELD:
        extra = len(lines) - MAX_LINES_PER_FIELD
        lines = lines[:MAX_LINES_PER_FIELD] + [t(lang, "roster_more", n=extra)]
    return "\n".join(lines)


def signup_counts(event: dict) -> tuple[int, int]:
    """(Anmeldungen gesamt, im Roster)."""
    signups = event.get("signups") or {}
    total = len(signups)
    roster = sum(1 for e in signups.values() if e.get("status") == "signed")
    return total, roster


def build_event_embed(event: dict, lang: str, *, overrides: dict | None = None,
                      emojis: dict | None = None) -> discord.Embed:
    """Erzeugt das vollständige Event-Embed."""
    game_id = event.get("game") or games.DEFAULT_GAME
    color = event.get("color") or DEFAULT_COLOR
    embed = discord.Embed(
        title=event.get("title") or "Event",
        description=event.get("description") or None,
        color=color,
    )

    # Kopf: Leitung + Zeit
    leader_id = event.get("leader_id")
    if leader_id:
        embed.add_field(
            name="\u200b",
            value=t(lang, "embed_leader", leader=f"<@{leader_id}>"),
            inline=False,
        )
    start = event.get("start_ts")
    if start:
        when = t(lang, "embed_when", time=f"<t:{start}:F>", rel=f"<t:{start}:R>")
        embed.add_field(name="\u200b", value=when, inline=False)
    if event.get("deadline_ts"):
        embed.add_field(
            name="\u200b",
            value=t(lang, "embed_deadline", time=f"<t:{event['deadline_ts']}:t>"),
            inline=True,
        )
    if event.get("recurrence"):
        embed.add_field(
            name="\u200b",
            value=t(lang, "embed_recurring", rule=event["recurrence"]),
            inline=True,
        )
    if event.get("closed"):
        embed.add_field(name="\u200b", value=t(lang, "embed_closed"), inline=False)

    # Roster nach Rolle
    ordered = _ordered_signups(event)
    order_index = {uid: i + 1 for i, (uid, _) in enumerate(ordered)}

    by_role: dict[str, list[str]] = {r: [] for r in games.role_order(game_id)}
    by_status: dict[str, list[str]] = {s: [] for s in _STATUS_ORDER}
    for uid, entry in ordered:
        status = entry.get("status") or "signed"
        if status == "signed":
            role = entry.get("role") or games.spec_role(game_id, entry.get("class"), entry.get("spec"))
            if role not in by_role:
                by_role.setdefault(role, [])
            by_role[role].append(_member_line(order_index[uid], game_id, entry, emojis))
        elif status in by_status:
            by_status[status].append(_member_line(order_index[uid], game_id, entry, emojis))

    total, roster = signup_counts(event)

    if roster == 0:
        no_sign = (overrides or {}).get("embed_no_signups") or t(lang, "embed_no_signups")
        embed.add_field(name="\u200b", value=no_sign, inline=False)
    else:
        for role in games.role_order(game_id):
            meta = games.role_meta(game_id, role)
            count = len(by_role.get(role, []))
            limit = (event.get("role_limits") or {}).get(role)
            head = f"{meta.get('emoji','')} {role_name(lang, role)} ({count}{'/' + str(limit) if limit else ''})"
            embed.add_field(name=head, value=_field_value(by_role.get(role, []), lang), inline=True)

    # Status-Felder (nur wenn belegt)
    status_chunks = []
    for st in _STATUS_ORDER:
        people = by_status.get(st, [])
        if people:
            status_chunks.append(f"{_STATUS_EMOJI[st]} **{t(lang, 'status_' + st)}** ({len(people)})")
    if status_chunks:
        embed.add_field(name="\u200b", value="  ·  ".join(status_chunks), inline=False)

    # Fußzeile
    embed.set_footer(text=t(lang, "embed_signups", count=total, roster=roster) + f"  ·  {event.get('id','')}  ·  {games.game_label(game_id)}")
    return embed
