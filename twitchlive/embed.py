"""Embeds, Link-Button und Textvorlagen für Live-Meldungen (alle Discord-Limits gekappt)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import discord

from .strings import t

TWITCH_COLOR = 0x9146FF
ENDED_COLOR = 0x6C6C75

LIMIT_TITLE = 256
LIMIT_DESC = 4096
LIMIT_FIELD = 1024
LIMIT_AUTHOR = 256
LIMIT_CONTENT = 2000
LIMIT_BUTTON_LABEL = 80
LIMIT_TEMPLATE = 1500   # Vorlagen-Länge (Platzhalter werden danach noch ersetzt und gekappt)

PLACEHOLDERS = ("streamer", "title", "game", "url", "ping")
_PH_RE = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


def cap(text, limit: int) -> str:
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def stream_url(login: str) -> str:
    return f"https://www.twitch.tv/{login}"


def parse_ts(value) -> float | None:
    """Twitch-Zeitstempel (``2026-09-25T18:00:00Z``) -> Unix-Zeit."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fmt_duration(seconds: float, lang: str = "de") -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if lang == "en":
        return f"{h} h {m} min" if h else f"{m} min"
    return f"{h} Std. {m} Min." if h else f"{m} Min."


def render_template(template: str, *, streamer: str, title: str, game: str, url: str, ping: str) -> str:
    """Ersetzt genau die fünf Platzhalter (ein Durchgang, kein ``str.format`` -> keine
    Attribut-Zugriffe wie ``{streamer.__class__}``, Werte werden nicht erneut ersetzt).

    Ist eine Ping-Rolle gewählt, die Vorlage enthält aber kein ``{ping}``, wird der Ping
    vorangestellt – sonst würde die gewählte Rolle nie erwähnt.
    """
    values = {"streamer": streamer, "title": title, "game": game, "url": url, "ping": ping}
    out = _PH_RE.sub(lambda m: values[m.group(1)], template or "")
    if ping and "{ping}" not in (template or ""):
        out = f"{ping} {out}"
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return cap(out, LIMIT_CONTENT)


def thumbnail(stream: dict, now: float) -> str | None:
    url = (stream or {}).get("thumbnail_url") or ""
    if not url.startswith(("http://", "https://")):
        return None
    url = url.replace("{width}", "1280").replace("{height}", "720")
    # Cache-Buster: Discord cacht Bild-URLs sonst dauerhaft (altes Vorschaubild).
    return f"{url}{'&' if '?' in url else '?'}t={int(now)}"


def _author(embed: discord.Embed, name: str, login: str, avatar: str | None):
    kw = {"name": cap(name, LIMIT_AUTHOR), "url": stream_url(login)}
    if avatar and str(avatar).startswith(("http://", "https://")):
        kw["icon_url"] = avatar
    embed.set_author(**kw)


def live_embed(*, login: str, name: str, avatar: str | None, stream: dict, lang: str, now: float,
               test: bool = False) -> discord.Embed:
    title = cap((stream.get("title") or "").strip() or t(lang, "no_title"), LIMIT_TITLE)
    game = cap(stream.get("game_name") or t(lang, "no_game"), LIMIT_FIELD)
    started = parse_ts(stream.get("started_at"))
    embed = discord.Embed(title=title, url=stream_url(login), color=TWITCH_COLOR,
                          timestamp=datetime.fromtimestamp(started or now, tz=timezone.utc))
    _author(embed, name, login, avatar)
    embed.add_field(name=t(lang, "field_game"), value=game, inline=True)
    embed.add_field(name=t(lang, "field_viewers"), value=f"{int(stream.get('viewer_count') or 0):,}".replace(",", "."),
                    inline=True)
    img = thumbnail(stream, now)
    if img:
        embed.set_image(url=img)
    if avatar and str(avatar).startswith(("http://", "https://")):
        embed.set_thumbnail(url=avatar)
    embed.set_footer(text=t(lang, "footer_test" if test else "footer_live"))
    return embed


def ended_embed(*, login: str, name: str, avatar: str | None, session: dict, lang: str) -> discord.Embed:
    started = session.get("started_at") or session.get("announced_at") or 0
    ended = session.get("last_seen") or started
    duration = fmt_duration(ended - started, lang) if started else "—"
    title = cap((session.get("title") or "").strip() or t(lang, "no_title"), LIMIT_TITLE)
    embed = discord.Embed(
        title=title, url=stream_url(login), color=ENDED_COLOR,
        description=cap(t(lang, "ended_desc", streamer=discord.utils.escape_markdown(name), duration=duration),
                        LIMIT_DESC),
        timestamp=datetime.fromtimestamp(ended or 0, tz=timezone.utc) if ended else None,
    )
    _author(embed, name, login, avatar)
    games = [g for g in (session.get("games") or []) if g]
    embed.add_field(name=t(lang, "field_games"), value=cap(", ".join(games) or t(lang, "no_game"), LIMIT_FIELD),
                    inline=True)
    embed.add_field(name=t(lang, "field_duration"), value=duration, inline=True)
    if session.get("peak_viewers"):
        embed.add_field(name=t(lang, "field_peak"), value=f"{int(session['peak_viewers']):,}".replace(",", "."),
                        inline=True)
    if avatar and str(avatar).startswith(("http://", "https://")):
        embed.set_thumbnail(url=avatar)
    embed.set_footer(text=t(lang, "footer_ended"))
    return embed


def link_view(login: str, lang: str, *, ended: bool = False) -> discord.ui.View:
    """Nur ein Link-Button – braucht keine Interaktionsbehandlung und keine Persistenz."""
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link,
        label=cap(t(lang, "button_channel" if ended else "button_watch"), LIMIT_BUTTON_LABEL),
        url=stream_url(login),
    ))
    return view
