"""WebCore-Dashboard für den RaidHelper-Cog.

Aufgaben (gleiches Muster wie tickets/dashboard.py):
* GET                     -> Übersicht: Statistik, Einstellungen, Event-Tabelle
* GET ?event=<id>         -> Roster eines Events (read-only)
* POST form=settings      -> Einstellungen speichern  (Post/Redirect/Get)
* POST form=action        -> Event schließen/öffnen/löschen

Es werden nur die Theme-Klassen (card-x, table, stat, …) plus die ohnehin
geladenen Bootstrap-Formularklassen genutzt – kein eigenes Design. Datums-
angaben werden in der Server-Zeitzone gerendert (kein Discord-``<t:>`` im Web).
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from . import games
from .embed import signup_counts
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS, role_name

_EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_]+):(\d+)>")


def _emoji_img(emoji_str) -> str | None:
    """CDN-Bild-URL aus einem Custom-Emoji-String '<:name:id>' / '<a:name:id>'."""
    if not emoji_str:
        return None
    m = _EMOJI_RE.fullmatch(str(emoji_str).strip())
    if not m:
        return None
    ext = "gif" if m.group(1) == "a" else "png"
    return f"https://cdn.discordapp.com/emojis/{m.group(3)}.{ext}"

_STATUS_LABEL_DE = {
    "bench": "Bank", "late": "Spät", "tentative": "Vielleicht", "absence": "Abwesend",
}

_FORM_STYLE = """
<style>
  .rh-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .rh-form input,.rh-form select{width:100%;background:var(--panel-2);
    color:var(--text);border:1px solid var(--border);border-radius:9px;
    padding:9px 11px;font-family:inherit;font-size:.92rem}
  .rh-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .rh-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .rh-check input{width:auto}
  .rh-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .rh-title{font-family:"Archivo",sans-serif;font-weight:700;font-size:1.15rem;margin:0 0 14px}
  .rh-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px}
  .rh-actions{display:flex;gap:6px;flex-wrap:wrap}
  .rh-actions button,.rh-actions a{font-size:.78rem;padding:5px 9px;border-radius:8px;
    border:1px solid var(--border);background:var(--panel-2);color:var(--text);
    text-decoration:none;cursor:pointer}
  .rh-actions .danger{border-color:var(--danger);color:var(--danger)}
  .rh-roster{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:16px}
  .rh-roster ol{margin:6px 0 0;padding-left:20px}
  .rh-spacer{height:24px}
  .rh-bar{display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}
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


def _one_id(value):
    return int(value) if value and str(value).isdigit() else None


def _fmt(ts: int | None, tz_name: str) -> str:
    if not ts:
        return "—"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m.%Y %H:%M")


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


def _selected_guild(cog, request):
    gid = request.query.get("guild")
    if gid and gid.isdigit():
        g = cog.bot.get_guild(int(gid))
        if g is not None:
            return g
    guilds = sorted(cog.bot.guilds, key=lambda g: g.name.lower())
    return guilds[0] if guilds else None


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    guild = _selected_guild(cog, request)
    if guild is None:
        return {"title": "Raidplaner", "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    tz_name = conf.get("timezone", "Europe/Berlin")
    events = conf.get("events") or {}

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='rh-flash'>{_esc(request.query.get('ok'))}</div>"

    # Server-Auswahl
    guild_opts = _options([(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())], [guild.id])
    bar = f"""
    <div class='rh-bar'>
      <form method='get' action='/cogs/raidhelper' class='rh-form' style='margin:0'>
        <select name='guild' onchange='this.form.submit()'>{guild_opts}</select>
      </form>
      <span class='mono' style='color:var(--muted)'>{_esc(guild.name)}</span>
    </div>
    """

    # Roster-Detailansicht?
    sel_event = request.query.get("event")
    if sel_event and sel_event in events:
        return {"title": "Raidplaner", "content": _FORM_STYLE + bar + _render_roster(events[sel_event], guild.id)}

    # Statistik-Kacheln
    now = int(datetime.now(tz=timezone.utc).timestamp())
    upcoming = sum(1 for e in events.values() if (e.get("start_ts") or 0) >= now)
    total_signups = sum(signup_counts(e)[0] for e in events.values())
    stats = f"""
    <div class='rh-grid'>
      <div class='stat'><div class='stat-label'>Kommende Events</div><div>{upcoming}</div></div>
      <div class='stat'><div class='stat-label'>Anmeldungen gesamt</div><div>{total_signups}</div></div>
      <div class='stat'><div class='stat-label'>Standard-Spiel</div><div>{_esc(games.game_label(conf.get('default_game')))}</div></div>
    </div>
    <div class='rh-spacer'></div>
    """

    # Einstellungs-Formular
    lang_opts = _options(list(LANGUAGES.items()), [conf.get("language", "de")])
    game_opts = _options(games.list_games(), [conf.get("default_game")])
    channel_opts = _options([(c.id, f"#{c.name}") for c in guild.text_channels],
                            [conf.get("signup_channel")], none_label="— kein Kanal —")
    overrides = conf.get("messages") or {}
    override_fields = ""
    for key in OVERRIDABLE_KEYS:
        current = overrides.get(key, "")
        default = STRINGS["de"].get(key, "")
        override_fields += (
            f"<label>{_esc(key)}</label>"
            f"<input name='ovr_{key}' value='{_esc(current)}' placeholder='{_esc(default)}'>"
        )
    rem_checked = "checked" if conf.get("reminders") else ""
    ping_checked = "checked" if conf.get("ping_signed_up") else ""

    settings = f"""
    <div class='card-x'>
      <div class='rh-title'>Einstellungen</div>
      <form class='rh-form' method='post' action='/cogs/raidhelper'>
        <input type='hidden' name='csrf_token' value='{csrf}'>
        <input type='hidden' name='form' value='settings'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <div class='row2'>
          <div><label>Sprache</label><select name='language'>{lang_opts}</select></div>
          <div><label>Standard-Spiel</label><select name='default_game'>{game_opts}</select></div>
        </div>
        <div class='row2'>
          <div><label>Anmelde-Kanal</label><select name='signup_channel'>{channel_opts}</select></div>
          <div><label>Zeitzone</label><input name='timezone' value='{_esc(tz_name)}'></div>
        </div>
        <div class='rh-check'><input type='checkbox' name='reminders' {rem_checked}><span>Erinnerungen senden (60 & 15 Min vorher)</span></div>
        <div class='rh-check'><input type='checkbox' name='ping_signed_up' {ping_checked}><span>Angemeldete zusätzlich per DM erinnern</span></div>
        <div class='rh-spacer'></div>
        <div class='rh-title' style='font-size:1rem'>Texte überschreiben</div>
        {override_fields}
        <div class='rh-spacer'></div>
        <button class='btn-accent' type='submit'>Speichern</button>
      </form>
    </div>
    <div class='rh-spacer'></div>
    """

    # Event-Tabelle
    table = _render_events_table(events, guild.id, tz_name, csrf)

    # Spec-Icons
    spec_emojis = await cog._spec_emojis()
    supported = cog._supports_app_emojis()
    structure = cog._known_spec_structure()
    icons_card = _render_icons(csrf, guild.id, spec_emojis, supported, structure)

    return {"title": "Raidplaner",
            "content": _FORM_STYLE + bar + flash + stats + settings + table + "<div class='rh-spacer'></div>" + icons_card}


def _render_icons(csrf: str, guild_id: int, emojis: dict, supported: bool, structure) -> str:
    rows = ""
    for cid, clabel, specs in structure:
        rows += (
            f"<tr><td colspan='4' style='padding-top:12px;color:#fff;font-weight:700'>{_esc(clabel)}</td></tr>"
        )
        for sid, slabel in specs:
            key = f"{cid}:{sid}"
            cur = emojis.get(key)
            img = _emoji_img(cur)
            if img:
                cell = f"<img src='{img}' width='22' height='22' style='border-radius:5px;vertical-align:middle'>"
            elif cur:
                cell = f"<span class='mono'>{_esc(cur)}</span>"
            else:
                cell = "<span style='color:var(--muted)'>—</span>"
            rows += (
                f"<tr><td style='padding-left:18px'>{_esc(slabel)}</td>"
                f"<td class='mono' style='color:var(--muted)'>{_esc(cid)}_{_esc(sid)}</td>"
                f"<td>{cell}</td>"
                f"<td><label class='rh-check' style='margin:0'><input type='checkbox' name='remove_{_esc(cid)}_{_esc(sid)}'>"
                f"<span>entfernen</span></label></td></tr>"
            )
    warning = ""
    if not supported:
        warning = (
            "<div class='rh-flash' style='background:rgba(255,107,107,.12);border-color:var(--danger);color:#ffd9d9'>"
            "Dieser Bot unterst&uuml;tzt keine Application-Emojis (discord.py &lt; 2.4). Der Upload funktioniert nicht – "
            "bitte Red aktualisieren oder Icons per Befehl <span class='mono'>[p]raidset specicon</span> setzen."
            "</div>"
        )
    disabled = " disabled" if not supported else ""
    return f"""
    <div class='card-x'>
      <div class='rh-title'>Spec-Icons</div>
      <div style='color:var(--muted);font-size:.85rem;margin-bottom:14px'>
        Icons gelten <b>botweit</b> (Application Emojis) und pro Spezialisierung. Pro Datei max. 256&nbsp;KB,
        Gesamt-Upload m&ouml;glichst unter 1&nbsp;MB. Dateiname = <span class='mono'>klasse_spec</span>,
        z.&nbsp;B. <span class='mono'>krieger_furor.png</span>.
      </div>
      {warning}
      <form class='rh-form' method='post' action='/cogs/raidhelper' enctype='multipart/form-data'>
        <input type='hidden' name='csrf_token' value='{csrf}'>
        <input type='hidden' name='form' value='icons'>
        <input type='hidden' name='guild' value='{guild_id}'>
        <table class='table'>
          <thead><tr><th>Spec</th><th>Datei-ID</th><th>Aktuelles Icon</th><th>Aktion</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
        <label>Icons hochladen (mehrere Dateien m&ouml;glich)</label>
        <input type='file' name='icons' accept='image/png,image/gif,image/jpeg' multiple{disabled}>
        <div class='rh-spacer'></div>
        <button class='btn-accent' type='submit'>Hochladen / &Auml;nderungen speichern</button>
      </form>
    </div>
    """


def _render_events_table(events: dict, guild_id: int, tz_name: str, csrf: str) -> str:
    if not events:
        return "<div class='card-x'>Für diesen Server sind keine Events gespeichert.</div>"
    rows = ""
    for e in sorted(events.values(), key=lambda x: x.get("start_ts", 0)):
        total, roster = signup_counts(e)
        status = "geschlossen" if e.get("closed") else "offen"
        eid = _esc(e["id"])
        toggle = "reopen" if e.get("closed") else "close"
        toggle_label = "Öffnen" if e.get("closed") else "Schließen"
        action_form = (
            f"<form method='post' action='/cogs/raidhelper' style='display:inline'>"
            f"<input type='hidden' name='csrf_token' value='{csrf}'>"
            f"<input type='hidden' name='form' value='action'>"
            f"<input type='hidden' name='guild' value='{guild_id}'>"
            f"<input type='hidden' name='event_id' value='{eid}'>"
            f"<button name='action' value='{toggle}'>{toggle_label}</button>"
            f"</form>"
        )
        delete_form = (
            f"<form method='post' action='/cogs/raidhelper' style='display:inline' "
            f"onsubmit=\"return confirm('Event {eid} wirklich löschen?')\">"
            f"<input type='hidden' name='csrf_token' value='{csrf}'>"
            f"<input type='hidden' name='form' value='action'>"
            f"<input type='hidden' name='guild' value='{guild_id}'>"
            f"<input type='hidden' name='event_id' value='{eid}'>"
            f"<button class='danger' name='action' value='delete'>Löschen</button>"
            f"</form>"
        )
        roster_link = f"<a href='/cogs/raidhelper?guild={guild_id}&event={eid}'>Roster</a>"
        rows += (
            f"<tr><td class='mono'>{eid}</td><td>{_esc(e.get('title'))}</td>"
            f"<td>{_esc(games.game_label(e.get('game')))}</td>"
            f"<td>{_esc(_fmt(e.get('start_ts'), tz_name))}</td>"
            f"<td>{total} ({roster})</td><td>{status}</td>"
            f"<td><div class='rh-actions'>{roster_link}{action_form}{delete_form}</div></td></tr>"
        )
    return f"""
    <div class='card-x'>
      <div class='rh-title'>Events</div>
      <table class='table'>
        <thead><tr><th>ID</th><th>Titel</th><th>Spiel</th><th>Start</th>
        <th>Anmeldungen</th><th>Status</th><th>Aktionen</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


def _render_roster(event: dict, guild_id: int) -> str:
    game_id = event.get("game") or games.DEFAULT_GAME
    signups = event.get("signups") or {}
    ordered = sorted(signups.items(), key=lambda kv: (kv[1].get("at") or 0, kv[0]))

    by_role = {r: [] for r in games.role_order(game_id)}
    by_status = {s: [] for s in _STATUS_LABEL_DE}
    for uid, e in ordered:
        st = e.get("status") or "signed"
        name = _esc(e.get("name"))
        spec = _esc(games.spec_label(game_id, e.get("class"), e.get("spec"))) if e.get("class") else ""
        spec_html = f"<span class='mono'>{spec}</span> " if spec else ""
        line = f"<li>{spec_html}{name}</li>"
        if st == "signed":
            role = e.get("role") or games.spec_role(game_id, e.get("class"), e.get("spec"))
            by_role.setdefault(role, []).append(line)
        elif st in by_status:
            by_status[st].append(line)

    cols = ""
    for role in games.role_order(game_id):
        meta = games.role_meta(game_id, role)
        items = "".join(by_role.get(role, [])) or "<li style='color:var(--muted)'>—</li>"
        cols += (
            f"<div><div class='stat-label'>{_esc(meta.get('emoji',''))} "
            f"{_esc(role_name('de', role))} ({len(by_role.get(role, []))})</div>"
            f"<ol>{items}</ol></div>"
        )
    status_cols = ""
    for st, label in _STATUS_LABEL_DE.items():
        people = by_status.get(st, [])
        if people:
            status_cols += f"<div><div class='stat-label'>{_esc(label)} ({len(people)})</div><ol>{''.join(people)}</ol></div>"

    total, roster = signup_counts(event)
    back = f"<a href='/cogs/raidhelper?guild={guild_id}' style='color:var(--accent)'>&larr; Zurück</a>"
    return f"""
    <div class='card-x'>
      <div class='rh-title'>{_esc(event.get('title'))} <span class='mono' style='color:var(--muted);font-size:.8rem'>{_esc(event.get('id'))}</span></div>
      <div style='color:var(--muted);margin-bottom:14px'>{_esc(games.game_label(game_id))} · {total} Anmeldungen · {roster} im Roster</div>
      <div class='rh-roster'>{cols}</div>
      {("<div class='rh-spacer'></div><div class='rh-roster'>" + status_cols + "</div>") if status_cols else ""}
      <div class='rh-spacer'></div>{back}
    </div>
    """


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guild = cog.bot.get_guild(int(gid)) if gid and gid.isdigit() else None
    if guild is None:
        raise web.HTTPFound("/cogs/raidhelper?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)
        game = data.get("default_game") or games.DEFAULT_GAME
        if games.get_game(game) is not None:
            await gconf.default_game.set(game)
        await gconf.signup_channel.set(_one_id(data.get("signup_channel")))
        tz = (data.get("timezone") or "Europe/Berlin").strip()
        try:
            ZoneInfo(tz)
            await gconf.timezone.set(tz)
        except (ZoneInfoNotFoundError, ValueError):
            pass
        await gconf.reminders.set("reminders" in data)
        await gconf.ping_signed_up.set("ping_signed_up" in data)
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)
        raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Gespeichert")

    if form == "action":
        event_id = data.get("event_id")
        action = data.get("action")
        async with gconf.events() as events:
            event = events.get(event_id)
            if event is None:
                raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Event+nicht+gefunden")
            if action in ("close", "reopen"):
                event["closed"] = action == "close"
                events[event_id] = event
                snapshot = dict(event)
            elif action == "delete":
                snapshot = events.pop(event_id, None)
            else:
                snapshot = None
        if action in ("close", "reopen") and snapshot:
            await cog.refresh_event_message(guild, snapshot)
            raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Aktualisiert")
        if action == "delete" and snapshot:
            if snapshot.get("channel_id") and snapshot.get("message_id"):
                channel = guild.get_channel(snapshot["channel_id"])
                if channel is not None:
                    try:
                        msg = await channel.fetch_message(snapshot["message_id"])
                        await msg.delete()
                    except Exception:  # noqa: BLE001
                        pass
            raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Gel%C3%B6scht")

    if form == "icons":
        pairs = cog._known_pair_set()  # {(class_id, spec_id), …}
        removed = 0
        for cid, sid in list(pairs):
            if f"remove_{cid}_{sid}" in data:
                await cog._delete_spec_emoji(cid, sid)
                removed += 1
        unsupported = not cog._supports_app_emojis()
        files = [] if unsupported else data.getall("icons", [])
        ok = skipped = 0
        for field in files:
            filename = getattr(field, "filename", "") or ""
            fileobj = getattr(field, "file", None)
            if not filename or fileobj is None:
                continue
            stem = filename.rsplit(".", 1)[0].lower()
            parts = stem.split("_", 1)  # IDs sind unterstrichfrei -> erster "_" trennt Klasse/Spec
            if len(parts) != 2 or (parts[0], parts[1]) not in pairs:
                skipped += 1
                continue
            cid, sid = parts
            try:
                fileobj.seek(0)
                raw = fileobj.read()
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            if not raw or len(raw) > 256 * 1024:
                skipped += 1
                continue
            try:
                await cog._set_spec_emoji_from_bytes(cid, sid, raw)
                ok += 1
            except Exception:  # noqa: BLE001
                skipped += 1
        if unsupported and data.getall("icons", []):
            raise web.HTTPFound(
                f"/cogs/raidhelper?guild={guild.id}&ok=" + quote("Application-Emojis werden nicht unterstützt")
            )
        msg = f"{ok} Icon(s) gesetzt, {removed} entfernt, {skipped} übersprungen"
        raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=" + quote(msg))

    raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}")
