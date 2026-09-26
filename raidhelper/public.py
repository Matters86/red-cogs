"""Öffentliche Raid-API für Launcher und Websites (über WebCore, ohne Login).

* ``GET /api/public/raids/<guild_id>``  -> JSON mit den kommenden Events

Pro Server **standardmäßig aus** (Config ``public_api``). Ist sie aus – oder gibt es den Server
nicht –, antwortet die API immer gleich mit ``404``; so lässt sich nicht herausfinden, auf welchen
Servern der Bot ist. Ausgegeben werden **nur Events in Kanälen, die @everyone sehen darf** (die
API ist öffentlich!) und **keine Nutzernamen oder -IDs** (auch nicht die Raidleitung) – nur die
Belegung als Zahlen. Query: ``limit`` (1–50, Standard 10).
"""

from __future__ import annotations

import functools
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from aiohttp import web

from . import games
from .embed import signup_counts
from .strings import role_name

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
# Weitere Rückmeldungen neben dem Roster (Status -> JSON-Schlüssel)
_OTHER = ("bench", "late", "tentative", "absence")

_dumps = functools.partial(json.dumps, ensure_ascii=False)


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def public_channel(guild, event: dict):
    """Kanal des Events, wenn **@everyone** ihn sehen darf – sonst ``None`` (API ist öffentlich)."""
    cid = event.get("channel_id")
    if not cid:
        return None
    getter = getattr(guild, "get_channel_or_thread", None) or guild.get_channel
    channel = getter(cid)
    if channel is None or not hasattr(channel, "permissions_for"):
        return None
    try:
        perms = channel.permissions_for(guild.default_role)
    except Exception:  # noqa: BLE001 – im Zweifel verbergen
        return None
    return channel if getattr(perms, "view_channel", False) else None


def event_payload(guild, event: dict, lang: str, now: int) -> dict:
    """Ein Event als öffentliches JSON-Objekt – nur Zahlen zur Belegung, keine Personen."""
    game_id = event.get("game") or games.DEFAULT_GAME
    signups = event.get("signups") or {}
    limits = event.get("role_limits") or {}
    _total, roster = signup_counts(event)
    roles = {}
    for role in games.role_order(game_id):
        count = sum(1 for e in signups.values() if e.get("status") == "signed" and e.get("role") == role)
        limit = limits.get(role)
        roles[role] = {
            "label": role_name(lang, role),
            "emoji": games.role_meta(game_id, role).get("emoji") or "",
            "signups": count,
            "max": int(limit) if limit else None,
        }
    other = {st: sum(1 for e in signups.values() if e.get("status") == st) for st in _OTHER}
    cap = event.get("max_signups")
    deadline = event.get("deadline_ts")
    closed = bool(event.get("closed")) or bool(deadline and now >= int(deadline))
    url = f"https://discord.com/channels/{guild.id}/{int(event['channel_id'])}"
    if event.get("message_id"):
        url += f"/{int(event['message_id'])}"
    return {
        "id": event.get("id"),
        "title": event.get("title") or "",
        "game": games.game_label(game_id),
        "start": _iso(event.get("start_ts")),
        "deadline": _iso(deadline) if deadline else None,
        "signups": roster,
        "max": int(cap) if cap else None,
        "full": bool(cap and roster >= int(cap)),
        "roles": roles,
        "other": other,
        "closed": closed,
        "url": url,
    }


def upcoming_public_events(guild, conf: dict, now: int) -> list[dict]:
    """Kommende, nicht abgeschlossene Events in für @everyone sichtbaren Kanälen, nach Start sortiert."""
    out = []
    for event in (conf.get("events") or {}).values():
        if not isinstance(event, dict) or event.get("completed") or int(event.get("start_ts") or 0) <= now:
            continue
        if public_channel(guild, event) is None:
            continue
        out.append(event)
    out.sort(key=lambda e: (int(e.get("start_ts") or 0), str(e.get("id", ""))))
    return out


def build_payload(guild, conf: dict, *, limit: int = DEFAULT_LIMIT, now: int | None = None) -> dict:
    now = int(now if now is not None else datetime.now(tz=timezone.utc).timestamp())
    lang = conf.get("language") or "de"
    events = upcoming_public_events(guild, conf, now)[:limit]
    return {"server": guild.name, "events": [event_payload(guild, e, lang, now) for e in events]}


def parse_limit(raw) -> int:
    try:
        return max(1, min(MAX_LIMIT, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


async def public_handler(cog, request):
    """``/api/public/raids/<guild_id>`` – 404 für unbekannte Server UND abgeschaltete API."""
    parts = [p for p in request.match_info.get("tail", "").split("/") if p]
    if len(parts) != 1 or not parts[0].isdigit() or len(parts[0]) > 20:
        raise web.HTTPNotFound()
    guild = cog.bot.get_guild(int(parts[0]))
    if guild is None:
        raise web.HTTPNotFound()
    conf = await cog.config.guild(guild).all()
    if not conf.get("public_api"):
        raise web.HTTPNotFound()
    payload = build_payload(guild, conf, limit=parse_limit(request.query.get("limit")))
    return web.json_response(payload, dumps=_dumps)


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
