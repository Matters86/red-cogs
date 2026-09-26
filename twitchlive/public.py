"""Öffentliche Twitch-Status-API für Launcher und Websites (über WebCore, ohne Login).

* ``GET /api/public/twitch/<guild_id>``  -> JSON: die in diesem Server eingetragenen Streamer mit Live-Status

Pro Server **standardmäßig aus** (Config ``public_api``). Ist sie aus – oder gibt es den Server
nicht –, antwortet die API immer gleich mit ``404``; so lässt sich nicht herausfinden, auf welchen
Servern der Bot ist. Die Daten stammen **ausschließlich aus dem Cache des Cogs** (letzte Abfrage der
Hintergrund-Schleife + zwischengespeicherte Profildaten) – ein API-Aufruf löst nie eine Anfrage an
Twitch aus. Ausgegeben werden nur öffentliche Twitch-Daten, keine Discord-Nutzer oder -Verknüpfungen.
"""

from __future__ import annotations

import functools
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from aiohttp import web

from .embed import stream_url

THUMB_SIZE = ("640", "360")

_dumps = functools.partial(json.dumps, ensure_ascii=False)


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _https(url) -> str | None:
    url = str(url or "")
    return url if url.startswith("https://") else None


def _thumb(url) -> str | None:
    url = _https(url)
    if not url:
        return None
    return url.replace("{width}", THUMB_SIZE[0]).replace("{height}", THUMB_SIZE[1])


def streamer_payload(cog, login: str, entry: dict, sess: dict | None) -> dict:
    """Ein Streamer als öffentliches JSON-Objekt (nur Daten aus Config/Cache)."""
    user = cog.user_info(login) or {}
    display = (user.get("display_name") or (sess or {}).get("name") or (entry or {}).get("display_name") or login)
    avatar = _https(user.get("profile_image_url") or (sess or {}).get("avatar"))
    live = sess is not None
    return {
        "login": login,
        "display_name": str(display),
        "live": live,
        "title": (sess.get("title") or None) if live else None,
        "game": (sess.get("game") or None) if live else None,
        "viewers": int(sess.get("viewers") or 0) if live else None,
        "started_at": _iso(sess.get("started_at")) if live else None,
        "url": stream_url(login),
        "thumbnail": _thumb(sess.get("thumbnail_url")) if live else None,
        "avatar": avatar,
    }


def build_payload(cog, guild, conf: dict) -> dict:
    """Aktive (nicht pausierte) Streamer des Servers: live zuerst (meiste Zuschauer), dann alphabetisch."""
    chans = conf.get("channels") or {}
    state = conf.get("state") or {}
    items = [streamer_payload(cog, login, entry or {}, state.get(login))
             for login, entry in chans.items() if (entry or {}).get("enabled", True)]
    items.sort(key=lambda s: (not s["live"], -(s["viewers"] or 0), s["login"]))
    return {"server": guild.name, "streamers": items}


async def public_handler(cog, request):
    """``/api/public/twitch/<guild_id>`` – 404 für unbekannte Server UND abgeschaltete API."""
    parts = [p for p in request.match_info.get("tail", "").split("/") if p]
    if len(parts) != 1 or not parts[0].isdigit() or len(parts[0]) > 20:
        raise web.HTTPNotFound()
    guild = cog.bot.get_guild(int(parts[0]))
    if guild is None:
        raise web.HTTPNotFound()
    conf = await cog.config.guild(guild).all()
    if not conf.get("public_api"):
        raise web.HTTPNotFound()
    return web.json_response(build_payload(cog, guild, conf), dumps=_dumps)


async def public_base(request) -> tuple[str, bool]:
    """Basis-URL des Dashboards: aus der OAuth-``redirect_uri`` (öffentliche Adresse), sonst die
    aktuelle Anfrage. Zweiter Wert: ``True``, wenn die Adresse öffentlich per HTTPS aussieht."""
    webcore = request.app.get("webcore")
    redirect = ""
    try:
        redirect = str(await webcore.config.redirect_uri() or "") if webcore is not None else ""
    except Exception:  # noqa: BLE001
        redirect = ""
    parts = urlsplit(redirect)
    if parts.scheme in ("http", "https") and parts.netloc:
        host = parts.hostname or ""
        public = parts.scheme == "https" and host not in ("localhost", "127.0.0.1", "::1")
        return f"{parts.scheme}://{parts.netloc}", public
    return f"{request.scheme}://{request.host}", False
