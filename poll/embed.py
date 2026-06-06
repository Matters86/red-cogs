"""Umfrage-Embed für den Poll-Cog.

Baut aus einem Umfrage-Datensatz das Discord-Embed mit Balkenanzeige und
Prozentwerten. Reine Daten kommen aus dem Cog; hier nur Darstellung.

Datensatz einer Umfrage (relevante Felder)::

    {
        "id": "p-0042",
        "question": str,
        "options": [str, ...],
        "channel_id": int, "message_id": int | None,
        "author_id": int, "created_ts": int, "end_ts": int | None,
        "multiple": bool, "anonymous": bool,
        "closed": bool, "ended": bool, "announced": bool,
        "votes": { "<user_id>": {"name": str, "choices": [idx, ...]} },
    }
"""

from __future__ import annotations

import discord

from .strings import t

DEFAULT_COLOR = 0x3DDC97
CLOSED_COLOR = 0x8B97A7
BAR_SEGMENTS = 12
BAR_FULL = "█"
BAR_EMPTY = "░"
# Ziffern-Emojis als visueller Anker (gleiche Nummern wie auf den Buttons).
NUMBER_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def option_emoji(idx: int) -> str:
    """Ziffern-Emoji für Option ``idx`` (ab 10 schlichte Nummerierung)."""
    if idx < len(NUMBER_EMOJI):
        return NUMBER_EMOJI[idx]
    return f"`{idx + 1}.`"


def vote_counts(poll: dict) -> tuple[list[int], int, int]:
    """(Stimmen je Option, Stimmen gesamt, Teilnehmer)."""
    options = poll.get("options") or []
    counts = [0] * len(options)
    total = 0
    voters = 0
    for entry in (poll.get("votes") or {}).values():
        choices = entry.get("choices") or []
        if choices:
            voters += 1
        for i in choices:
            if 0 <= i < len(counts):
                counts[i] += 1
                total += 1
    return counts, total, voters


def _bar(pct: float) -> str:
    filled = int(round(pct * BAR_SEGMENTS))
    filled = max(0, min(BAR_SEGMENTS, filled))
    return BAR_FULL * filled + BAR_EMPTY * (BAR_SEGMENTS - filled)


def is_ended_or_closed(poll: dict) -> bool:
    return bool(poll.get("closed") or poll.get("ended"))


def winner_info(poll: dict) -> dict:
    """Ermittelt Gewinner/Unentschieden für die Ergebnis-Ansage."""
    counts, total, _ = vote_counts(poll)
    options = poll.get("options") or []
    if total == 0 or not counts:
        return {"type": "none"}
    top = max(counts)
    winners = [options[i] for i, c in enumerate(counts) if c == top]
    pct = int(round((top / total) * 100)) if total else 0
    if len(winners) == 1:
        return {"type": "win", "option": winners[0], "votes": top, "pct": pct}
    return {"type": "tie", "options": winners, "votes": top}


def result_text(poll: dict, lang: str) -> str:
    info = winner_info(poll)
    if info["type"] == "none":
        return t(lang, "result_none")
    if info["type"] == "tie":
        joined = ", ".join(f"**{o}**" for o in info["options"])
        return t(lang, "result_tie", options=joined, votes=info["votes"])
    return t(lang, "result_winner", option=info["option"], votes=info["votes"], pct=info["pct"])


def build_poll_embed(poll: dict, lang: str, *, overrides: dict | None = None) -> discord.Embed:
    """Erzeugt das vollständige Umfrage-Embed."""
    counts, total, voters = vote_counts(poll)
    options = poll.get("options") or []
    closed = is_ended_or_closed(poll)
    winning = max(counts) if counts else 0

    # Kopf-Tags (Modus, Anonymität, Endzeit / Status).
    tags: list[str] = []
    if poll.get("author_id"):
        tags.append(t(lang, "embed_by", author=f"<@{poll['author_id']}>"))
    tags.append(t(lang, "embed_multiple") if poll.get("multiple") else t(lang, "embed_single"))
    if poll.get("anonymous"):
        tags.append(t(lang, "embed_anonymous"))
    if poll.get("ended"):
        tags.append(t(lang, "embed_ended"))
    elif poll.get("closed"):
        tags.append(t(lang, "embed_closed"))
    elif poll.get("end_ts"):
        tags.append(t(lang, "embed_ends", rel=f"<t:{poll['end_ts']}:R>"))

    header = "  ·  ".join(tags)

    # Optionen mit Balken.
    if total == 0:
        body = (overrides or {}).get("embed_no_votes") or t(lang, "embed_no_votes")
    else:
        lines = []
        for idx, opt in enumerate(options):
            c = counts[idx]
            pct = (c / total) if total else 0.0
            mark = " " + t(lang, "embed_winner_tag") if (closed and c == winning and c > 0) else ""
            lines.append(
                f"{option_emoji(idx)} **{opt}**{mark}\n"
                f"`{_bar(pct)}`  {c} · {int(round(pct * 100))}%"
            )
        body = "\n\n".join(lines)

    description = f"{header}\n\n{body}" if header else body
    embed = discord.Embed(
        title=poll.get("question") or "Umfrage",
        description=description[:4096],
        color=CLOSED_COLOR if closed else DEFAULT_COLOR,
    )
    embed.set_footer(
        text=t(lang, "embed_total", count=total, voters=voters) + f"  ·  {poll.get('id', '')}"
    )
    return embed
