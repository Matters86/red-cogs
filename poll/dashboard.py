"""WebCore-Dashboard für den Poll-Cog.

Aufgaben (gleiches Muster wie raidhelper/dashboard.py):
* GET                  -> Übersicht: Statistik, Einstellungen, Neue Umfrage, Tabelle
* GET ?poll=<id>       -> Ergebnis-Detail einer Umfrage (read-only)
* POST form=settings   -> Einstellungen speichern (Post/Redirect/Get)
* POST form=create     -> Neue Umfrage anlegen und posten
* POST form=action     -> Umfrage schließen/öffnen/löschen

Es werden nur die Theme-Klassen (card-x, table, stat, …) plus die ohnehin
geladenen Bootstrap-Klassen genutzt – kein eigenes Design. Nutzereingaben werden
mit ``html.escape`` abgesichert.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote

from aiohttp import web

from .embed import vote_counts
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

HARD_OPTION_LIMIT = 25

_FORM_STYLE = """
<style>
  .pl-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .pl-form input,.pl-form select,.pl-form textarea{width:100%;background:var(--panel-2);
    color:var(--text);border:1px solid var(--border);border-radius:9px;
    padding:9px 11px;font-family:inherit;font-size:.92rem}
  .pl-form textarea{min-height:120px;resize:vertical;line-height:1.5}
  .pl-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .pl-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .pl-check input{width:auto}
  .pl-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .pl-title{font-family:"Archivo",sans-serif;font-weight:700;font-size:1.15rem;margin:0 0 14px}
  .pl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px}
  .pl-actions{display:flex;gap:6px;flex-wrap:wrap}
  .pl-actions button,.pl-actions a{font-size:.78rem;padding:5px 9px;border-radius:8px;
    border:1px solid var(--border);background:var(--panel-2);color:var(--text);
    text-decoration:none;cursor:pointer}
  .pl-actions .danger{border-color:var(--danger);color:var(--danger)}
  .pl-spacer{height:24px}
  .pl-bar{display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}
  .pl-opt{margin:14px 0}
  .pl-opt-head{display:flex;justify-content:space-between;gap:12px;margin-bottom:5px}
  .pl-opt-head .name{font-weight:600}
  .pl-opt-head .num{color:var(--muted);font-size:.85rem}
  .pl-track{background:var(--panel-2);border:1px solid var(--border);border-radius:8px;
    height:22px;overflow:hidden}
  .pl-fill{height:100%;background:var(--accent);border-radius:7px 0 0 7px;min-width:2px}
  .pl-voters{color:var(--muted);font-size:.82rem;margin-top:5px}
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


def _status_word(poll: dict) -> str:
    if poll.get("ended"):
        return "beendet"
    if poll.get("closed"):
        return "geschlossen"
    return "offen"


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
        return {"title": "Umfragen", "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    polls = conf.get("polls") or {}

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='pl-flash'>{_esc(request.query.get('ok'))}</div>"

    guild_opts = _options([(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())], [guild.id])
    bar = (
        "<div class='pl-bar'>"
        "<form method='get' action='/cogs/poll' class='pl-form' style='margin:0'>"
        f"<select name='guild' onchange='this.form.submit()'>{guild_opts}</select>"
        "</form>"
        f"<span class='mono' style='color:var(--muted)'>{_esc(guild.name)}</span>"
        "</div>"
    )

    # Ergebnis-Detailansicht?
    sel = request.query.get("poll")
    if sel and sel in polls:
        return {"title": "Umfragen", "content": _FORM_STYLE + bar + _render_results(guild, polls[sel])}

    now = int(datetime.now(tz=timezone.utc).timestamp())
    active = sum(1 for p in polls.values() if not (p.get("closed") or p.get("ended")))
    total_votes = sum(vote_counts(p)[1] for p in polls.values())
    anon_default = "anonym" if conf.get("default_anonymous") else "öffentlich"
    stats = (
        "<div class='pl-grid'>"
        f"<div class='stat'><div class='stat-label'>Aktive Umfragen</div><div>{active}</div></div>"
        f"<div class='stat'><div class='stat-label'>Stimmen gesamt</div><div>{total_votes}</div></div>"
        f"<div class='stat'><div class='stat-label'>Standard-Sichtbarkeit</div><div>{anon_default}</div></div>"
        "</div><div class='pl-spacer'></div>"
    )

    settings = _render_settings(guild, conf, csrf)
    create = _render_create_form(guild, conf, csrf)
    table = _render_polls_table(guild, polls, csrf)

    return {
        "title": "Umfragen",
        "content": _FORM_STYLE + bar + flash + stats + settings
        + "<div class='pl-spacer'></div>" + create
        + "<div class='pl-spacer'></div>" + table,
    }


def _render_settings(guild, conf, csrf) -> str:
    lang_opts = _options(list(LANGUAGES.items()), [conf.get("language", "de")])
    create_opts = _options([("manager", "Nur Mods/Manager"), ("everyone", "Alle Mitglieder")],
                           [conf.get("allow_create", "manager")])
    role_opts = _options([(r.id, r.name) for r in guild.roles if not r.is_default()],
                         conf.get("manager_roles") or [])
    overrides = conf.get("messages") or {}
    override_fields = ""
    for key in OVERRIDABLE_KEYS:
        current = overrides.get(key, "")
        default = STRINGS["de"].get(key, "")
        override_fields += (
            f"<label>{_esc(key)}</label>"
            f"<input name='ovr_{key}' value='{_esc(current)}' placeholder='{_esc(default)}'>"
        )
    mult_checked = "checked" if conf.get("default_multiple") else ""
    anon_checked = "checked" if conf.get("default_anonymous") else ""

    return (
        "<div class='card-x'><div class='pl-title'>Einstellungen</div>"
        "<form class='pl-form' method='post' action='/cogs/poll'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        "<input type='hidden' name='form' value='settings'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        "<div class='row2'>"
        f"<div><label>Sprache</label><select name='language'>{lang_opts}</select></div>"
        f"<div><label>Erstellen erlaubt für</label><select name='allow_create'>{create_opts}</select></div>"
        "</div>"
        "<div class='row2'>"
        f"<div><label>Max. Optionen (2–{HARD_OPTION_LIMIT})</label>"
        f"<input type='number' name='max_options' min='2' max='{HARD_OPTION_LIMIT}' value='{int(conf.get('max_options', 10))}'></div>"
        f"<div><label>Manager-Rollen (Mehrfachauswahl)</label>"
        f"<select name='manager_roles' multiple size='4'>{role_opts}</select></div>"
        "</div>"
        f"<div class='pl-check'><input type='checkbox' name='default_multiple' {mult_checked}><span>Standard: Mehrfachauswahl erlauben</span></div>"
        f"<div class='pl-check'><input type='checkbox' name='default_anonymous' {anon_checked}><span>Standard: anonym (nur Zähler, keine Namen)</span></div>"
        "<div class='pl-spacer'></div>"
        "<div class='pl-title' style='font-size:1rem'>Texte überschreiben</div>"
        f"{override_fields}"
        "<div class='pl-spacer'></div>"
        "<button class='btn-accent' type='submit'>Speichern</button>"
        "</form></div>"
    )


def _render_create_form(guild, conf, csrf) -> str:
    channel_opts = _options([(c.id, f"#{c.name}") for c in guild.text_channels], [])
    mult_checked = "checked" if conf.get("default_multiple") else ""
    anon_checked = "checked" if conf.get("default_anonymous") else ""
    max_opts = int(conf.get("max_options", 10))
    return (
        "<div class='card-x'><div class='pl-title'>Neue Umfrage</div>"
        "<form class='pl-form' method='post' action='/cogs/poll'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        "<input type='hidden' name='form' value='create'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        "<label>Frage</label><input name='question' maxlength='256' placeholder='Beste Pizza?'>"
        f"<label>Optionen (eine pro Zeile, 2–{max_opts})</label>"
        "<textarea name='options' placeholder='Margherita&#10;Salami&#10;Hawaii'></textarea>"
        "<div class='row2'>"
        f"<div><label>Kanal</label><select name='channel'>{channel_opts}</select></div>"
        "<div><label>Laufzeit (optional)</label><input name='duration' placeholder='z. B. 2h, 30m, 1d – leer = kein Limit'></div>"
        "</div>"
        f"<div class='pl-check'><input type='checkbox' name='multiple' {mult_checked}><span>Mehrfachauswahl erlauben</span></div>"
        f"<div class='pl-check'><input type='checkbox' name='anonymous' {anon_checked}><span>Anonym abstimmen</span></div>"
        "<div class='pl-spacer'></div>"
        "<button class='btn-accent' type='submit'>Umfrage posten</button>"
        "</form></div>"
    )


def _render_polls_table(guild, polls, csrf) -> str:
    if not polls:
        return "<div class='card-x'>Für diesen Server sind keine Umfragen gespeichert.</div>"
    rows = ""
    for p in sorted(polls.values(), key=lambda x: x.get("created_ts", 0), reverse=True):
        _, total, voters = vote_counts(p)
        status = _status_word(p)
        pid = _esc(p["id"])
        channel = guild.get_channel(p.get("channel_id")) if p.get("channel_id") else None
        ch_name = f"#{channel.name}" if channel is not None else "—"
        toggle = "reopen" if (p.get("closed") or p.get("ended")) else "close"
        toggle_label = "Öffnen" if (p.get("closed") or p.get("ended")) else "Schließen"
        action_form = (
            "<form method='post' action='/cogs/poll' style='display:inline'>"
            f"<input type='hidden' name='csrf_token' value='{csrf}'>"
            "<input type='hidden' name='form' value='action'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='poll_id' value='{pid}'>"
            f"<button name='action' value='{toggle}'>{toggle_label}</button>"
            "</form>"
        )
        delete_form = (
            "<form method='post' action='/cogs/poll' style='display:inline' "
            f"onsubmit=\"return confirm('Umfrage {pid} wirklich löschen?')\">"
            f"<input type='hidden' name='csrf_token' value='{csrf}'>"
            "<input type='hidden' name='form' value='action'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='poll_id' value='{pid}'>"
            f"<button class='danger' name='action' value='delete'>Löschen</button>"
            "</form>"
        )
        results_link = f"<a href='/cogs/poll?guild={guild.id}&poll={pid}'>Ergebnis</a>"
        rows += (
            f"<tr><td class='mono'>{pid}</td><td>{_esc((p.get('question') or '')[:70])}</td>"
            f"<td>{_esc(ch_name)}</td><td>{total} ({voters})</td><td>{status}</td>"
            f"<td><div class='pl-actions'>{results_link}{action_form}{delete_form}</div></td></tr>"
        )
    return (
        "<div class='card-x'><div class='pl-title'>Umfragen</div>"
        "<table class='table'><thead><tr><th>ID</th><th>Frage</th><th>Kanal</th>"
        "<th>Stimmen (Teiln.)</th><th>Status</th><th>Aktionen</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _render_results(guild, poll: dict) -> str:
    counts, total, voters = vote_counts(poll)
    options = poll.get("options") or []
    anonymous = bool(poll.get("anonymous"))
    winning = max(counts) if counts else 0

    blocks = ""
    for idx, opt in enumerate(options):
        c = counts[idx] if idx < len(counts) else 0
        pct = int(round((c / total) * 100)) if total else 0
        trophy = " 🏆" if (poll.get("closed") or poll.get("ended")) and c == winning and c > 0 else ""
        voters_line = ""
        if not anonymous:
            names = [
                _esc(v.get("name", "?"))
                for v in (poll.get("votes") or {}).values()
                if idx in (v.get("choices") or [])
            ]
            if names:
                voters_line = f"<div class='pl-voters'>{', '.join(names)}</div>"
        blocks += (
            "<div class='pl-opt'>"
            f"<div class='pl-opt-head'><span class='name'>{idx + 1}. {_esc(opt)}{trophy}</span>"
            f"<span class='num'>{c} · {pct}%</span></div>"
            f"<div class='pl-track'><div class='pl-fill' style='width:{pct}%'></div></div>"
            f"{voters_line}</div>"
        )

    meta = []
    meta.append("Mehrfachauswahl" if poll.get("multiple") else "Eine Stimme")
    meta.append("anonym" if anonymous else "öffentlich")
    meta.append(_status_word(poll))
    back = f"<a href='/cogs/poll?guild={guild.id}' style='color:var(--accent)'>&larr; Zurück</a>"
    return (
        "<div class='card-x'>"
        f"<div class='pl-title'>{_esc(poll.get('question'))} "
        f"<span class='mono' style='color:var(--muted);font-size:.8rem'>{_esc(poll.get('id'))}</span></div>"
        f"<div style='color:var(--muted);margin-bottom:14px'>{' · '.join(meta)} · {total} Stimmen · {voters} Teilnehmer</div>"
        f"{blocks}"
        f"<div class='pl-spacer'></div>{back}</div>"
    )


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guild = cog.bot.get_guild(int(gid)) if gid and gid.isdigit() else None
    if guild is None:
        raise web.HTTPFound("/cogs/poll?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)
        mode = (data.get("allow_create") or "manager").lower()
        if mode in ("everyone", "manager"):
            await gconf.allow_create.set(mode)
        try:
            mx = int(data.get("max_options") or 10)
            await gconf.max_options.set(max(2, min(HARD_OPTION_LIMIT, mx)))
        except (TypeError, ValueError):
            pass
        roles = []
        for rid in data.getall("manager_roles", []):
            if str(rid).isdigit():
                roles.append(int(rid))
        await gconf.manager_roles.set(roles)
        await gconf.default_multiple.set("default_multiple" in data)
        await gconf.default_anonymous.set("default_anonymous" in data)
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)
        raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=Gespeichert")

    if form == "create":
        from .poll import parse_duration  # zur Laufzeit (vermeidet Import-Zyklus)

        question = (data.get("question") or "").strip()
        options = [o.strip() for o in (data.get("options") or "").splitlines() if o.strip()]
        max_opts = await gconf.max_options()
        if not question or len(options) < 2:
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote("Bitte Frage und mind. 2 Optionen angeben"))
        if len(options) > max_opts:
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote(f"Zu viele Optionen (max. {max_opts})"))
        channel = guild.get_channel(_one_id(data.get("channel")) or 0)
        if channel is None:
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote("Bitte einen Kanal wählen"))
        end_ts = None
        dur = (data.get("duration") or "").strip()
        if dur:
            secs = parse_duration(dur)
            if secs is None:
                raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote("Dauer nicht erkannt (z. B. 2h, 30m, 1d)"))
            end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + secs
        await cog.create_poll(
            guild, question=question, options=options, channel_id=channel.id,
            author_id=cog.bot.user.id, end_ts=end_ts,
            multiple="multiple" in data, anonymous="anonymous" in data,
        )
        raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote("Umfrage erstellt"))

    if form == "action":
        poll_id = data.get("poll_id")
        action = data.get("action")
        async with gconf.polls() as polls:
            poll = polls.get(poll_id)
            if poll is None:
                raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=Umfrage+nicht+gefunden")
            if action == "close":
                poll["closed"] = True
                polls[poll_id] = poll
                snapshot = dict(poll)
            elif action == "reopen":
                poll["closed"] = False
                poll["ended"] = False
                poll["announced"] = False
                poll["end_ts"] = None
                polls[poll_id] = poll
                snapshot = dict(poll)
            elif action == "delete":
                snapshot = polls.pop(poll_id, None)
            else:
                snapshot = None
        if action in ("close", "reopen") and snapshot:
            await cog.refresh_poll_message(guild, snapshot)
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=Aktualisiert")
        if action == "delete" and snapshot:
            if snapshot.get("channel_id") and snapshot.get("message_id"):
                channel = guild.get_channel(snapshot["channel_id"])
                if channel is not None:
                    try:
                        msg = await channel.fetch_message(snapshot["message_id"])
                        await msg.delete()
                    except Exception:  # noqa: BLE001
                        pass
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote("Gelöscht"))

    raise web.HTTPFound(f"/cogs/poll?guild={guild.id}")
