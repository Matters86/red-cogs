"""WebCore-Dashboard für den Changelog-Cog.

Aufgaben (gleiches Muster wie poll/dashboard.py):
* GET                 -> Übersicht: Einstellungen + Historie-Tabelle
* GET ?entry=<id>     -> Detailansicht eines Changelogs (read-only)
* POST form=settings  -> Einstellungen speichern (Post/Redirect/Get)
* POST form=action    -> Changelog löschen (optional inkl. Discord-Nachricht)

Es werden nur die Theme-Klassen (card-x, table, stat, mono, btn-accent) plus die
ohnehin geladenen Bootstrap-Klassen genutzt – kein eigenes Design. Nutzereingaben
werden mit ``html.escape`` abgesichert. Die Server-Auswahl ist auf die für den
eingeloggten User sichtbaren Server beschränkt (``visible_guilds``).
"""

from __future__ import annotations

import html
from urllib.parse import quote

from aiohttp import web

from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

_FORM_STYLE = """
<style>
  .cl-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .cl-form input,.cl-form select,.cl-form textarea{width:100%;background:var(--panel-2);
    color:var(--text);border:1px solid var(--border);border-radius:9px;
    padding:9px 11px;font-family:inherit;font-size:.92rem}
  .cl-form input[type=color]{padding:4px;height:42px}
  .cl-form textarea{min-height:110px;resize:vertical;line-height:1.5}
  .cl-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .cl-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .cl-check input{width:auto}
  .cl-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .cl-title{font-family:"Archivo",sans-serif;font-weight:700;font-size:1.15rem;margin:0 0 14px}
  .cl-spacer{height:24px}
  .cl-bar{display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}
  .cl-actions{display:flex;gap:6px;flex-wrap:wrap}
  .cl-actions button,.cl-actions a{font-size:.78rem;padding:5px 9px;border-radius:8px;
    border:1px solid var(--border);background:var(--panel-2);color:var(--text);
    text-decoration:none;cursor:pointer}
  .cl-actions .danger{border-color:var(--danger);color:var(--danger)}
  .cl-sec{margin:14px 0}
  .cl-sec h4{margin:0 0 6px;font-size:.95rem}
  .cl-sec ul{margin:0;padding-left:20px;color:var(--text)}
  .cl-note{border:1px solid var(--danger);border-radius:9px;padding:10px 12px;margin-top:12px}
  .cl-hint{color:var(--muted);font-size:.82rem;margin-top:4px}
</style>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _options(items, selected_ids, *, none_label: str | None = None) -> str:
    sel = {str(s) for s in (selected_ids or [])}
    out = []
    if none_label is not None:
        out.append(f"<option value=''{'' if sel else ' selected'}>{_esc(none_label)}</option>")
    for ident, label in items:
        is_sel = " selected" if str(ident) in sel else ""
        out.append(f"<option value='{_esc(ident)}'{is_sel}>{_esc(label)}</option>")
    return "".join(out)


def _lines_html(raw: str) -> str:
    """Mehrzeiligen Rohtext als HTML-Liste (Bullets) darstellen."""
    lines = [ln.strip().lstrip("•-–*").strip() for ln in (raw or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    return "<ul>" + "".join(f"<li>{_esc(ln)}</li>" for ln in lines) + "</ul>"


def _parse_color(text: str | None) -> int | None:
    if not text:
        return None
    value = str(text).strip().lstrip("#")
    if len(value) == 6:
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None


async def _visible_guilds(cog, request):
    webcore = request.app.get("webcore")
    if webcore is not None:
        guilds = await webcore.visible_guilds(request)
    else:  # Fallback (sollte im Normalbetrieb nicht eintreten)
        guilds = list(cog.bot.guilds)
    return sorted(guilds, key=lambda g: g.name.lower())


def _pick_guild(guilds, request):
    gid = request.query.get("guild")
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                return g
    return guilds[0] if guilds else None


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    guilds = await _visible_guilds(cog, request)
    guild = _pick_guild(guilds, request)
    if guild is None:
        return {"title": "Changelog", "content": "<div class='card-x'>Keine Server verfügbar.</div>"}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    entries = conf.get("entries") or {}

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='cl-flash'>{_esc(request.query.get('ok'))}</div>"

    guild_opts = _options([(g.id, g.name) for g in guilds], [guild.id])
    bar = (
        "<div class='cl-bar'>"
        "<form method='get' action='/cogs/changelog' class='cl-form' style='margin:0'>"
        f"<select name='guild' onchange='this.form.submit()'>{guild_opts}</select>"
        "</form>"
        f"<span class='mono' style='color:var(--muted)'>{_esc(guild.name)}</span>"
        "</div>"
    )

    # Detailansicht eines Changelogs?
    sel = request.query.get("entry")
    if sel and sel in entries:
        return {"title": "Changelog", "content": _FORM_STYLE + bar + _render_detail(guild, entries[sel])}

    settings = _render_settings(cog, guild, conf, csrf)
    history = _render_history(guild, entries, csrf)
    return {
        "title": "Changelog",
        "content": _FORM_STYLE + bar + flash + settings + "<div class='cl-spacer'></div>" + history,
    }


def _render_settings(cog, guild, conf, csrf) -> str:
    channel_opts = _options(
        [(c.id, f"#{c.name}") for c in guild.text_channels],
        [conf.get("channel_id")],
        none_label="— kein Kanal —",
    )
    role_items = [(r.id, r.name) for r in guild.roles if not r.is_default()]
    poster_opts = _options(role_items, conf.get("poster_roles") or [])
    ping_opts = _options(role_items, [conf.get("ping_role_id")], none_label="— keine —")
    lang_opts = _options(list(LANGUAGES.items()), [conf.get("language", "de")])
    ping_checked = "checked" if conf.get("ping_enabled") else ""
    color_hex = f"#{int(conf.get('color', 0x3DDC97)):06X}"

    cats = cog._categories(conf)
    cats_text = "\n".join(f"{c.get('emoji', '')}|{c.get('label', '')}" for c in cats)

    overrides = conf.get("messages") or {}
    override_fields = ""
    for key in OVERRIDABLE_KEYS:
        current = overrides.get(key, "")
        default = STRINGS["de"].get(key, "")
        override_fields += (
            f"<label>{_esc(key)}</label>"
            f"<input name='ovr_{key}' value='{_esc(current)}' placeholder='{_esc(default)}'>"
        )

    return (
        "<div class='card-x'><div class='cl-title'>Einstellungen</div>"
        "<form class='cl-form' method='post' action='/cogs/changelog'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        "<input type='hidden' name='form' value='settings'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        "<div class='row2'>"
        f"<div><label>Ziel-Kanal</label><select name='channel'>{channel_opts}</select></div>"
        f"<div><label>Sprache</label><select name='language'>{lang_opts}</select></div>"
        "</div>"
        "<div class='row2'>"
        f"<div><label>Poster-Rollen (Mehrfachauswahl)</label>"
        f"<select name='poster_roles' multiple size='5'>{poster_opts}</select></div>"
        f"<div><label>Ping-Rolle</label><select name='ping_role'>{ping_opts}</select>"
        f"<div class='cl-check'><input type='checkbox' name='ping_enabled' {ping_checked}>"
        "<span>Ping-Rolle vor dem Embed anpingen</span></div></div>"
        "</div>"
        "<div class='row2'>"
        f"<div><label>Embed-Farbe</label><input type='color' name='color' value='{_esc(color_hex)}'></div>"
        "<div></div>"
        "</div>"
        "<label>Kategorien (eine pro Zeile, Format: Emoji|Bezeichnung)</label>"
        f"<textarea name='categories' placeholder='🚗|Fahrzeuge&#10;🌾|Landwirtschaft'>{_esc(cats_text)}</textarea>"
        "<div class='cl-hint'>Die postende Person wählt beim Befehl <span class='mono'>/changelog</span> eine dieser Kategorien als Emoji für den „Neu\"-Bereich.</div>"
        "<div class='cl-spacer'></div>"
        "<div class='cl-title' style='font-size:1rem'>Texte überschreiben</div>"
        f"{override_fields}"
        "<div class='cl-hint'>Platzhalter beibehalten: <span class='mono'>{title}</span> im Titel, <span class='mono'>{author}</span> in der Fußzeile.</div>"
        "<div class='cl-spacer'></div>"
        "<button class='btn-accent' type='submit'>Speichern</button>"
        "</form></div>"
    )


def _render_history(guild, entries, csrf) -> str:
    if not entries:
        return "<div class='card-x'>Für diesen Server sind noch keine Changelogs gespeichert.</div>"
    rows = ""
    for r in sorted(entries.values(), key=lambda x: x.get("created_ts", 0), reverse=True):
        eid = _esc(r.get("id"))
        ts = r.get("created_ts", 0)
        # Discord-Zeitstempel rendern im Web nicht – daher lesbares Datum bauen.
        when_txt = _fmt_ts(ts)
        channel = guild.get_channel(r.get("channel_id")) if r.get("channel_id") else None
        ch_name = f"#{channel.name}" if channel is not None else "—"
        cat = f"{_esc(r.get('category_emoji', ''))}"
        detail_link = f"<a href='/cogs/changelog?guild={guild.id}&entry={eid}'>Ansehen</a>"
        jump = ""
        if channel is not None and r.get("message_id"):
            url = f"https://discord.com/channels/{guild.id}/{channel.id}/{r['message_id']}"
            jump = f"<a href='{url}' target='_blank' rel='noopener'>Zur Nachricht</a>"
        delete_form = (
            "<form method='post' action='/cogs/changelog' style='display:inline' "
            f"onsubmit=\"return confirm('Changelog {eid} wirklich löschen?')\">"
            f"<input type='hidden' name='csrf_token' value='{csrf}'>"
            "<input type='hidden' name='form' value='action'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='entry_id' value='{eid}'>"
            "<button class='danger' name='action' value='delete'>Löschen</button>"
            "</form>"
        )
        rows += (
            f"<tr><td class='mono'>{eid}</td><td>{_esc(when_txt)}</td><td>{cat}</td>"
            f"<td>{_esc((r.get('title') or '')[:70])}</td><td>{_esc(ch_name)}</td>"
            f"<td>{_esc(r.get('author_name', '?'))}</td>"
            f"<td><div class='cl-actions'>{detail_link}{jump}{delete_form}</div></td></tr>"
        )
    return (
        "<div class='card-x'><div class='cl-title'>Historie</div>"
        "<table class='table'><thead><tr><th>ID</th><th>Datum</th><th>Kat.</th>"
        "<th>Titel</th><th>Kanal</th><th>Autor</th><th>Aktionen</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _render_detail(guild, r: dict) -> str:
    channel = guild.get_channel(r.get("channel_id")) if r.get("channel_id") else None
    ch_name = f"#{channel.name}" if channel is not None else "—"
    meta = f"{_esc(_fmt_ts(r.get('created_ts', 0)))} · {ch_name} · {_esc(r.get('author_name', '?'))}"

    sections = ""
    new_html = _lines_html(r.get("neu", ""))
    if new_html:
        sections += f"<div class='cl-sec'><h4>{_esc(r.get('category_emoji', ''))} Neu</h4>{new_html}</div>"
    changed_html = _lines_html(r.get("geaendert", ""))
    if changed_html:
        sections += f"<div class='cl-sec'><h4>🔧 Geändert</h4>{changed_html}</div>"
    fixes_html = _lines_html(r.get("fixes", ""))
    if fixes_html:
        sections += f"<div class='cl-sec'><h4>🐛 Fixes</h4>{fixes_html}</div>"
    note = (r.get("hinweis") or "").strip()
    if note:
        sections += f"<div class='cl-note'>⚠️ <strong>{_esc(note)}</strong></div>"

    jump = ""
    if channel is not None and r.get("message_id"):
        url = f"https://discord.com/channels/{guild.id}/{channel.id}/{r['message_id']}"
        jump = f" · <a href='{url}' target='_blank' rel='noopener' style='color:var(--accent)'>Zur Nachricht</a>"
    back = f"<a href='/cogs/changelog?guild={guild.id}' style='color:var(--accent)'>&larr; Zurück</a>"

    return (
        "<div class='card-x'>"
        f"<div class='cl-title'>🆕 {_esc(r.get('title', '(ohne Titel)'))} "
        f"<span class='mono' style='color:var(--muted);font-size:.8rem'>{_esc(r.get('id'))}</span></div>"
        f"<div style='color:var(--muted);margin-bottom:14px'>{meta}{jump}</div>"
        f"{sections or '<div style=\"color:var(--muted)\">Kein Inhalt.</div>'}"
        f"<div class='cl-spacer'></div>{back}</div>"
    )


def _fmt_ts(ts) -> str:
    """Unix-Sekunden -> lesbares UTC-Datum (im Web, wo Discord-Tags nicht greifen)."""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")

    # Server-Auswahl serverseitig gegen die sichtbaren Server prüfen.
    guilds = await _visible_guilds(cog, request)
    guild = None
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                guild = g
                break
    if guild is None:
        raise web.HTTPFound("/cogs/changelog?ok=" + quote("Server nicht gefunden"))

    gconf = cog.config.guild(guild)

    if form == "settings":
        # Ziel-Kanal
        ch = data.get("channel")
        if ch and ch.isdigit() and guild.get_channel(int(ch)) is not None:
            await gconf.channel_id.set(int(ch))
        else:
            await gconf.channel_id.set(None)

        # Sprache
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)

        # Poster-Rollen
        roles = [int(r) for r in data.getall("poster_roles", []) if str(r).isdigit()]
        await gconf.poster_roles.set(roles)

        # Ping-Rolle + Schalter
        pr = data.get("ping_role")
        if pr and pr.isdigit() and guild.get_role(int(pr)) is not None:
            await gconf.ping_role_id.set(int(pr))
        else:
            await gconf.ping_role_id.set(None)
        await gconf.ping_enabled.set("ping_enabled" in data)

        # Farbe
        color = _parse_color(data.get("color"))
        if color is not None:
            await gconf.color.set(color)

        # Kategorien (Emoji|Bezeichnung pro Zeile)
        cats = []
        for line in (data.get("categories") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                emoji, label = line.split("|", 1)
            else:
                parts = line.split(None, 1)
                emoji, label = (parts[0], parts[1] if len(parts) > 1 else "")
            emoji = emoji.strip()[:16]
            label = label.strip()[:80]
            if emoji:
                cats.append({"emoji": emoji, "label": label or emoji})
            if len(cats) >= 25:
                break
        await gconf.categories.set(cats)

        # Text-Overrides
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)

        raise web.HTTPFound(f"/cogs/changelog?guild={guild.id}&ok=" + quote("Gespeichert"))

    if form == "action" and data.get("action") == "delete":
        entry_id = data.get("entry_id")
        snapshot = None
        async with gconf.entries() as entries:
            snapshot = entries.pop(entry_id, None)
        if snapshot and snapshot.get("channel_id") and snapshot.get("message_id"):
            channel = guild.get_channel(snapshot["channel_id"])
            if channel is not None:
                try:
                    msg = await channel.fetch_message(snapshot["message_id"])
                    await msg.delete()
                except Exception:  # noqa: BLE001
                    pass
        raise web.HTTPFound(f"/cogs/changelog?guild={guild.id}&ok=" + quote("Gelöscht"))

    raise web.HTTPFound(f"/cogs/changelog?guild={guild.id}")
