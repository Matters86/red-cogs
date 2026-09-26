"""Öffentliche Changelog-API für Launcher und Websites (über WebCore, ohne Login).

* ``GET /api/public/changelog/<guild_id>``      -> JSON
* ``GET /api/public/changelog/<guild_id>/rss``  -> RSS 2.0

Pro Server **standardmäßig aus** (Config ``public_api``). Ist sie aus – oder gibt es den Server
nicht –, antwortet die API immer gleich mit ``404 {"error": "not_found"}``; so lässt sich nicht
herausfinden, auf welchen Servern der Bot ist. Es werden keine Nutzer-IDs ausgegeben
(Autor nur als Anzeigename). Query: ``limit`` (1–50, Standard 10), ``before`` (Eintrags-ID für
die nächste Seite, z. B. ``cl12`` – siehe ``next_before`` in der Antwort).
"""

from __future__ import annotations

import functools
import html
import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape

from aiohttp import web

from .strings import t

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
_ID_RE = re.compile(r"^(?:cl)?(\d{1,12})$")
# In XML 1.0 verbotene Steuerzeichen (alles < 0x20 außer Tab/LF/CR) + Surrogates/FFFE/FFFF.
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
_SECTIONS = (("neu", "field_new", None), ("geaendert", "field_changed", "🔧"), ("fixes", "field_fixes", "🐛"))

_dumps = functools.partial(json.dumps, ensure_ascii=False)


def _num(entry_id) -> int:
    m = _ID_RE.match(str(entry_id or ""))
    return int(m.group(1)) if m else 0


def _lines(raw) -> list[str]:
    """Mehrzeiligen Rohtext wie im Embed in Stichpunkte zerlegen (ohne Aufzählungszeichen)."""
    out = []
    for line in str(raw or "").splitlines():
        clean = line.strip().lstrip("•-–*").strip()
        if clean:
            out.append(clean)
    return out


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def entry_payload(guild, rec: dict, lang: str) -> dict:
    """Ein Changelog-Eintrag als öffentliches JSON-Objekt (ohne interne Nutzer-IDs)."""
    sections = []
    for key, label_key, emoji in _SECTIONS:
        items = _lines(rec.get(key))
        if items:
            sections.append({
                "key": key,
                "title": t(lang, label_key),
                "emoji": rec.get("category_emoji") if key == "neu" else emoji,
                "items": items,
            })
    url = None
    if rec.get("channel_id") and rec.get("message_id"):
        url = f"https://discord.com/channels/{guild.id}/{int(rec['channel_id'])}/{int(rec['message_id'])}"
    return {
        "id": rec.get("id"),
        "title": rec.get("title") or "",
        "category": {"emoji": rec.get("category_emoji") or "", "label": rec.get("category_label") or ""},
        "sections": sections,
        "note": (rec.get("hinweis") or "").strip() or None,
        "created_at": _iso(rec.get("created_ts")),
        "author": rec.get("author_name") or None,
        "url": url,
    }


def select_entries(entries: dict, *, limit: int, before: int | None) -> tuple[list[dict], bool]:
    """Neueste zuerst; ``before`` = nur Einträge mit kleinerer Nummer. -> (seite, gibt_es_mehr)."""
    items = sorted((entries or {}).values(),
                   key=lambda r: (_num(r.get("id")), int(r.get("created_ts") or 0)), reverse=True)
    if before is not None:
        items = [r for r in items if _num(r.get("id")) < before]
    return items[:limit], len(items) > limit


def build_payload(guild, conf: dict, *, limit: int = DEFAULT_LIMIT, before: int | None = None) -> dict:
    lang = conf.get("language") or "de"
    page, more = select_entries(conf.get("entries") or {}, limit=limit, before=before)
    return {
        "server": guild.name,
        "entries": [entry_payload(guild, r, lang) for r in page],
        "next_before": (page[-1].get("id") if more and page else None),
    }


def _x(value) -> str:
    """Text für XML: verbotene Zeichen entfernen, dann &, <, > escapen."""
    return xml_escape(_XML_BAD.sub("", str(value or "")))


def build_rss(guild, conf: dict, payload: dict) -> str:
    link = f"https://discord.com/channels/{guild.id}"
    if conf.get("channel_id"):
        link += f"/{int(conf['channel_id'])}"
    items = []
    for e in payload["entries"]:
        html_parts = []
        for sec in e["sections"]:
            head = f"{sec['emoji']} {sec['title']}".strip()
            html_parts.append(f"<h3>{_html(head)}</h3><ul>"
                              + "".join(f"<li>{_html(i)}</li>" for i in sec["items"]) + "</ul>")
        if e["note"]:
            html_parts.append(f"<p><strong>⚠️ {_html(e['note'])}</strong></p>")
        pub = ""
        if e["created_at"]:
            dt = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
            pub = f"<pubDate>{format_datetime(dt, usegmt=True)}</pubDate>"
        items.append(
            "<item>"
            f"<title>{_x(e['title'])}</title>"
            + (f"<link>{_x(e['url'])}</link>" if e["url"] else "")
            + f"<guid isPermaLink=\"false\">changelog-{guild.id}-{_x(e['id'])}</guid>"
            + pub
            + (f"<dc:creator>{_x(e['author'])}</dc:creator>" if e["author"] else "")
            + (f"<category>{_x(e['category']['label'])}</category>" if e["category"]["label"] else "")
            + f"<description>{_x(''.join(html_parts))}</description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'
        f"<title>{_x(guild.name)} – Changelog</title>"
        f"<link>{_x(link)}</link>"
        f"<description>{_x('Server-Updates von ' + guild.name)}</description>"
        f"<language>{_x(conf.get('language') or 'de')}</language>"
        f"<lastBuildDate>{format_datetime(datetime.now(timezone.utc), usegmt=True)}</lastBuildDate>"
        + "".join(items)
        + "</channel></rss>"
    )


def _html(value) -> str:
    """HTML-Escaping für den Inhalt von <description> (wird danach zusätzlich XML-escaped)."""
    return html.escape(_XML_BAD.sub("", str(value or "")))


def _parse_limit(raw) -> int:
    try:
        return max(1, min(MAX_LIMIT, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


async def public_handler(cog, request):
    """``/api/public/changelog/<guild_id>[/rss]`` – 404 für unbekannte Server UND abgeschaltete API."""
    parts = [p for p in request.match_info.get("tail", "").split("/") if p]
    if not parts or len(parts) > 2 or not parts[0].isdigit() or len(parts[0]) > 20 \
            or (len(parts) == 2 and parts[1] != "rss"):
        raise web.HTTPNotFound()
    guild = cog.bot.get_guild(int(parts[0]))
    if guild is None:
        raise web.HTTPNotFound()
    conf = await cog.config.guild(guild).all()
    if not conf.get("public_api"):
        raise web.HTTPNotFound()

    before = None
    raw_before = request.query.get("before", "").strip()
    if raw_before:
        m = _ID_RE.match(raw_before)
        if not m:
            raise web.HTTPBadRequest()
        before = int(m.group(1))
    payload = build_payload(guild, conf, limit=_parse_limit(request.query.get("limit")), before=before)
    if len(parts) == 2:
        return web.Response(text=build_rss(guild, conf, payload), content_type="application/rss+xml",
                            charset="utf-8")
    return web.json_response(payload, dumps=_dumps)
