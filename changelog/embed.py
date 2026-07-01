"""Embed-Aufbau für den Changelog-Cog.

Baut aus den Modal-Feldern (Titel, Neu, Geändert, Fixes, Hinweis) ein
einheitliches Embed. Mehrzeilige Eingaben werden zu Bullet-Listen (``• ``),
Discord-Limits (1024 Zeichen pro Feld) werden sicher eingehalten.
"""

from __future__ import annotations

from datetime import datetime, timezone

import discord

from .strings import OVERRIDABLE_KEYS, t

FIELD_LIMIT = 1024  # Discord: max. Zeichen pro Embed-Feld


def apply_text(messages: dict | None, lang: str | None, key: str, **kwargs) -> str:
    """Wie ``t()``, berücksichtigt aber pro-Server-Overrides für sichtbare Texte."""
    messages = messages or {}
    if key in OVERRIDABLE_KEYS:
        override = messages.get(key)
        if override:
            try:
                return override.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return override
    return t(lang, key, **kwargs)


def _bulletize(raw: str | None) -> str:
    """Macht aus mehrzeiligem Text eine Bullet-Liste; hält das Feld-Limit ein."""
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return ""
    formatted: list[str] = []
    for line in lines:
        # Falls die Person schon selbst Aufzählungszeichen gesetzt hat, nicht doppeln.
        clean = line.lstrip("•-–*").strip()
        formatted.append(f"• {clean}" if clean else "")
    text = "\n".join(f for f in formatted if f)
    if len(text) > FIELD_LIMIT:
        text = text[: FIELD_LIMIT - 1].rstrip() + "…"
    return text


def build_changelog_embed(
    *,
    title: str,
    neu: str | None,
    geaendert: str | None,
    fixes: str | None,
    hinweis: str | None,
    category_emoji: str,
    author_name: str,
    author_icon: str | None,
    color: int,
    lang: str | None,
    messages: dict | None = None,
    when: datetime | None = None,
) -> discord.Embed:
    """Baut das fertige Changelog-Embed."""
    when = when or datetime.now(tz=timezone.utc)
    embed = discord.Embed(
        title=apply_text(messages, lang, "embed_title", title=title.strip()[:230]),
        color=discord.Color(color),
        timestamp=when,
    )

    new_text = _bulletize(neu)
    if new_text:
        embed.add_field(
            name=f"{category_emoji} {t(lang, 'field_new')}",
            value=new_text,
            inline=False,
        )

    changed_text = _bulletize(geaendert)
    if changed_text:
        embed.add_field(
            name=f"🔧 {t(lang, 'field_changed')}",
            value=changed_text,
            inline=False,
        )

    fixes_text = _bulletize(fixes)
    if fixes_text:
        embed.add_field(
            name=f"🐛 {t(lang, 'field_fixes')}",
            value=fixes_text,
            inline=False,
        )

    note = (hinweis or "").strip()
    if note:
        note = note[: FIELD_LIMIT - 4]
        embed.add_field(
            name=f"⚠️ {t(lang, 'field_note')}",
            value=f"**{note}**",
            inline=False,
        )

    embed.set_footer(
        text=apply_text(messages, lang, "footer", author=author_name),
        icon_url=author_icon,
    )
    return embed


def has_any_section(neu: str | None, geaendert: str | None, fixes: str | None) -> bool:
    """True, wenn mind. eines der inhaltlichen Felder befüllt ist."""
    return any((v or "").strip() for v in (neu, geaendert, fixes))
