"""WebCore-Dashboard für den Guard-Cog.

Aufgaben (gleiches Muster wie poll/raidhelper):
* GET                 -> Übersicht: Statistik, Notmodus-Schalter, Einstellungen, Verlauf
* POST form=settings  -> Alle Einstellungen speichern (Post/Redirect/Get)
* POST form=lockdown  -> Notmodus an-/ausschalten

Es werden nur die Theme-Klassen (card-x, table, stat, …) plus die ohnehin
geladenen Bootstrap-Klassen genutzt – kein eigenes Design. Nutzereingaben werden
mit ``html.escape`` abgesichert.
"""

from __future__ import annotations

import html
import time
from urllib.parse import quote

from aiohttp import web

from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

ACTIONS = (
    ("ban", "Bann"),
    ("softban", "Softban (Kick + Nachrichten weg)"),
    ("kick", "Kick"),
    ("timeout", "Timeout"),
)
JOIN_ACTIONS = (
    ("none", "Nichts tun"),
    ("kick", "Kicken"),
    ("timeout", "Timeout"),
)

# Checkbox-Felder (Anwesenheit im Formular = an).
BOOL_FIELDS = (
    "hp_enabled", "spam_enabled", "ignore_bots", "use_modlog",
    "s_rate", "s_repeat", "s_repeat_crosschannel", "s_mentions",
    "s_invites", "s_links", "s_walls", "s_newaccount",
    "delete_violations", "raid_enabled", "lockdown_pause_invites",
)

# Zahlenfelder: name -> (min, max).
INT_FIELDS = {
    "hp_delete_seconds": (0, 604800),
    "hp_timeout_minutes": (1, 40320),
    "s_rate_count": (1, 100),
    "s_rate_seconds": (1, 3600),
    "s_repeat_count": (1, 50),
    "s_repeat_seconds": (1, 3600),
    "s_mentions_max": (1, 100),
    "s_walls_attachments": (1, 100),
    "s_walls_emojis": (1, 200),
    "s_walls_newlines": (1, 500),
    "s_newaccount_hours": (1, 8760),
    "pts_rate": (0, 100), "pts_repeat": (0, 100), "pts_mentions": (0, 100),
    "pts_invite": (0, 100), "pts_link": (0, 100), "pts_wall": (0, 100),
    "pts_newaccount": (0, 100),
    "decay_seconds": (5, 86400),
    "warn_at": (1, 1000), "timeout_at": (1, 1000), "kick_at": (1, 1000), "ban_at": (1, 1000),
    "spam_timeout_minutes": (1, 40320),
    "raid_joins": (2, 1000),
    "raid_seconds": (1, 3600),
    "lockdown_slowmode": (0, 21600),
    "lockdown_auto_minutes": (0, 1440),
}

_FORM_STYLE = """
<style>
  .gd-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .gd-form input,.gd-form select,.gd-form textarea{width:100%;background:var(--panel-2);
    color:var(--text);border:1px solid var(--border);border-radius:9px;
    padding:9px 11px;font-family:inherit;font-size:.92rem}
  .gd-form textarea{min-height:70px;resize:vertical;line-height:1.5}
  .gd-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
  .gd-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .gd-check input{width:auto}
  .gd-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .gd-title{font-family:"Archivo",sans-serif;font-weight:700;font-size:1.15rem;margin:0 0 14px}
  .gd-sub{font-family:"Archivo",sans-serif;font-weight:700;font-size:1rem;margin:22px 0 6px}
  .gd-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}
  .gd-spacer{height:24px}
  .gd-bar{display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}
  .gd-pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:.78rem;
    border:1px solid var(--border)}
  .gd-on{color:var(--accent);border-color:var(--accent)}
  .gd-off{color:var(--muted)}
  .gd-hint{color:var(--muted);font-size:.8rem;margin-top:4px}
</style>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _options(items, selected, *, none_label=None) -> str:
    sel = {str(s) for s in (selected if isinstance(selected, (list, tuple, set)) else [selected])}
    out = []
    if none_label is not None:
        out.append(f"<option value=''{'' if any(sel) else ' selected'}>{_esc(none_label)}</option>")
    for ident, label in items:
        is_sel = " selected" if str(ident) in sel else ""
        out.append(f"<option value='{_esc(ident)}'{is_sel}>{_esc(label)}</option>")
    return "".join(out)


def _num(name, label, value, *, hint=None) -> str:
    lo, hi = INT_FIELDS[name]
    h = f"<div class='gd-hint'>{_esc(hint)}</div>" if hint else ""
    return (
        f"<div><label>{_esc(label)}</label>"
        f"<input type='number' name='{name}' min='{lo}' max='{hi}' value='{int(value)}'>{h}</div>"
    )


def _check(name, label, checked) -> str:
    c = "checked" if checked else ""
    return f"<div class='gd-check'><input type='checkbox' name='{name}' {c}><span>{_esc(label)}</span></div>"


# --------------------------------------------------------------------------- #
#  Einstieg / Guild-Auswahl
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
        return {"title": "Guard", "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='gd-flash'>{_esc(request.query.get('ok'))}</div>"

    guild_opts = _options([(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())], guild.id)
    bar = (
        "<div class='gd-bar'>"
        "<form method='get' action='/cogs/guard' class='gd-form' style='margin:0'>"
        f"<select name='guild' onchange='this.form.submit()'>{guild_opts}</select>"
        "</form>"
        f"<span class='mono' style='color:var(--muted)'>{_esc(guild.name)}</span>"
        "</div>"
    )

    stats = _render_stats(guild, conf)
    lockdown = _render_lockdown(guild, conf, csrf)
    settings = _render_settings(guild, conf, csrf)
    history = _render_history(guild, conf)

    return {
        "title": "Guard",
        "content": _FORM_STYLE + bar + flash + stats
        + "<div class='gd-spacer'></div>" + lockdown
        + "<div class='gd-spacer'></div>" + settings
        + "<div class='gd-spacer'></div>" + history,
    }


def _render_stats(guild, conf) -> str:
    today = sum(1 for r in (conf.get("history") or []) if time.time() - r.get("ts", 0) <= 86400)
    hp = "<span class='gd-pill gd-on'>an</span>" if conf.get("hp_enabled") else "<span class='gd-pill gd-off'>aus</span>"
    spam = "<span class='gd-pill gd-on'>an</span>" if conf.get("spam_enabled") else "<span class='gd-pill gd-off'>aus</span>"
    ld = "<span class='gd-pill gd-on'>aktiv</span>" if conf.get("lockdown_until") else "<span class='gd-pill gd-off'>aus</span>"
    return (
        "<div class='gd-grid'>"
        f"<div class='stat'><div class='stat-label'>Auslösungen gesamt</div><div>{int(conf.get('stats_total', 0))}</div></div>"
        f"<div class='stat'><div class='stat-label'>Letzte 24 h</div><div>{today}</div></div>"
        f"<div class='stat'><div class='stat-label'>Honeypot</div><div>{hp}</div></div>"
        f"<div class='stat'><div class='stat-label'>Spamschutz</div><div>{spam}</div></div>"
        f"<div class='stat'><div class='stat-label'>Notmodus</div><div>{ld}</div></div>"
        "</div>"
    )


def _render_lockdown(guild, conf, csrf) -> str:
    active = bool(conf.get("lockdown_until"))
    if active:
        until = conf.get("lockdown_until")
        when = f"endet automatisch <t:{int(until)}:R>" if until and until > 0 else "bis zur manuellen Aufhebung"
        btn = "<button class='btn-accent' name='state' value='off'>Notmodus beenden</button>"
        note = f"<div class='gd-hint'>Aktiv – {when}.</div>"
    else:
        btn = "<button class='btn-accent' name='state' value='on'>Notmodus jetzt aktivieren</button>"
        note = "<div class='gd-hint'>Setzt Slowmode, pausiert (falls möglich) Einladungen und behandelt neue Beitritte gemäß Einstellung.</div>"
    return (
        "<div class='card-x'><div class='gd-title'>Notmodus (Lockdown)</div>"
        "<form class='gd-form' method='post' action='/cogs/guard' style='margin:0'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        "<input type='hidden' name='form' value='lockdown'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        f"{btn}{note}</form></div>"
    )


def _render_settings(guild, conf, csrf) -> str:
    text_channels = [(c.id, f"#{c.name}") for c in guild.text_channels]
    roles = [(r.id, r.name) for r in guild.roles if not r.is_default()]

    lang_opts = _options(list(LANGUAGES.items()), conf.get("language", "de"))
    log_opts = _options(text_channels, conf.get("log_channel"), none_label="— keiner —")
    hp_chan_opts = _options(text_channels, conf.get("hp_channel"), none_label="— keiner —")
    hp_action_opts = _options(ACTIONS, conf.get("hp_action", "softban"))
    join_opts = _options(JOIN_ACTIONS, conf.get("lockdown_action_joins", "none"))
    role_opts = _options(roles, conf.get("whitelist_roles") or [])
    chan_opts = _options(text_channels, conf.get("whitelist_channels") or [])
    wl_users = " ".join(str(u) for u in (conf.get("whitelist_users") or []))

    overrides = conf.get("messages") or {}
    override_fields = ""
    for key in OVERRIDABLE_KEYS:
        cur = overrides.get(key, "")
        default = STRINGS["de"].get(key, "")
        override_fields += (
            f"<label>Text „{_esc(key)}\"</label>"
            f"<textarea name='ovr_{key}' placeholder='{_esc(default)}'>{_esc(cur)}</textarea>"
        )

    # ---- Module & Allgemein
    general = (
        "<div class='gd-sub'>Module & Allgemein</div>"
        + _check("hp_enabled", "Honeypot aktiv", conf.get("hp_enabled"))
        + _check("spam_enabled", "Spamschutz aktiv", conf.get("spam_enabled"))
        + _check("ignore_bots", "Andere Bots ignorieren", conf.get("ignore_bots", True))
        + _check("use_modlog", "Aktionen zusätzlich in Reds modlog spiegeln", conf.get("use_modlog", True))
        + "<div class='gd-row'>"
        + f"<div><label>Sprache</label><select name='language'>{lang_opts}</select></div>"
        + f"<div><label>Log-Kanal</label><select name='log_channel'>{log_opts}</select></div>"
        + "</div>"
    )

    # ---- Honeypot
    honeypot = (
        "<div class='gd-sub'>Honeypot</div>"
        "<div class='gd-row'>"
        f"<div><label>Honeypot-Kanal (bestehenden markieren)</label><select name='hp_channel'>{hp_chan_opts}</select>"
        "<div class='gd-hint'>Neuen Kanal anlegen: <span class='mono'>[p]guardset honeypot create</span></div></div>"
        f"<div><label>Aktion bei Auslösung</label><select name='hp_action'>{hp_action_opts}</select></div>"
        "</div>"
        "<div class='gd-row'>"
        + _num("hp_delete_seconds", "Nachrichten löschen (Sek., bei Bann/Softban)", conf.get("hp_delete_seconds", 86400),
               hint="0–604800 (max. 7 Tage)")
        + _num("hp_timeout_minutes", "Timeout-Dauer (Min., falls Aktion = Timeout)", conf.get("hp_timeout_minutes", 60))
        + "</div>"
    )

    # ---- Spamschutz-Heuristiken
    spam = (
        "<div class='gd-sub'>Spamschutz – Heuristiken</div>"
        + _check("s_rate", "Nachrichten-Rate", conf.get("s_rate", True))
        + "<div class='gd-row'>"
        + _num("s_rate_count", "max. Nachrichten", conf.get("s_rate_count", 6))
        + _num("s_rate_seconds", "im Zeitfenster (Sek.)", conf.get("s_rate_seconds", 5))
        + "</div>"
        + _check("s_repeat", "Wiederholungen", conf.get("s_repeat", True))
        + _check("s_repeat_crosschannel", "Wiederholungen kanalübergreifend zählen", conf.get("s_repeat_crosschannel", True))
        + "<div class='gd-row'>"
        + _num("s_repeat_count", "gleiche Nachrichten ab", conf.get("s_repeat_count", 4))
        + _num("s_repeat_seconds", "im Zeitfenster (Sek.)", conf.get("s_repeat_seconds", 20))
        + "</div>"
        + _check("s_mentions", "Massen-Erwähnungen", conf.get("s_mentions", True))
        + "<div class='gd-row'>"
        + _num("s_mentions_max", "max. Erwähnungen je Nachricht", conf.get("s_mentions_max", 5))
        + "</div>"
        + _check("s_invites", "Einladungslinks erkennen", conf.get("s_invites", True))
        + _check("s_links", "Alle externen Links erkennen", conf.get("s_links", False))
        + _check("s_walls", "Anhang-/Emoji-/Zeilen-Walls", conf.get("s_walls", True))
        + "<div class='gd-row'>"
        + _num("s_walls_attachments", "max. Anhänge", conf.get("s_walls_attachments", 6))
        + _num("s_walls_emojis", "max. Custom-Emojis", conf.get("s_walls_emojis", 12))
        + _num("s_walls_newlines", "max. Zeilenumbrüche", conf.get("s_walls_newlines", 12))
        + "</div>"
        + _check("s_newaccount", "Sehr neue Konten strenger behandeln (verstärkt andere Treffer)", conf.get("s_newaccount", True))
        + "<div class='gd-row'>"
        + _num("s_newaccount_hours", "Konto jünger als (Std.)", conf.get("s_newaccount_hours", 24))
        + "</div>"
    )

    # ---- Punkte & Eskalation
    escalation = (
        "<div class='gd-sub'>Punkte & Eskalation</div>"
        "<div class='gd-row'>"
        + _num("pts_rate", "Punkte: Rate", conf.get("pts_rate", 3))
        + _num("pts_repeat", "Punkte: Wiederholung", conf.get("pts_repeat", 3))
        + _num("pts_mentions", "Punkte: Erwähnungen", conf.get("pts_mentions", 4))
        + _num("pts_invite", "Punkte: Einladung", conf.get("pts_invite", 5))
        + _num("pts_link", "Punkte: Link", conf.get("pts_link", 2))
        + _num("pts_wall", "Punkte: Wall", conf.get("pts_wall", 2))
        + _num("pts_newaccount", "Punkte: neues Konto", conf.get("pts_newaccount", 2))
        + _num("decay_seconds", "Punkte verfallen nach (Sek.)", conf.get("decay_seconds", 60))
        + "</div>"
        "<div class='gd-row'>"
        + _num("warn_at", "Verwarnen ab Punkten", conf.get("warn_at", 3))
        + _num("timeout_at", "Timeout ab Punkten", conf.get("timeout_at", 6))
        + _num("kick_at", "Kick ab Punkten", conf.get("kick_at", 9))
        + _num("ban_at", "Bann ab Punkten", conf.get("ban_at", 12))
        + _num("spam_timeout_minutes", "Timeout-Dauer Spam (Min.)", conf.get("spam_timeout_minutes", 10))
        + "</div>"
        + _check("delete_violations", "Auslösende Nachricht löschen", conf.get("delete_violations", True))
    )

    # ---- Raid / Notmodus
    raid = (
        "<div class='gd-sub'>Raid-Erkennung & Notmodus</div>"
        + _check("raid_enabled", "Raid-Erkennung aktiv (zu viele Beitritte → Notmodus)", conf.get("raid_enabled", True))
        + "<div class='gd-row'>"
        + _num("raid_joins", "Beitritte ab", conf.get("raid_joins", 8))
        + _num("raid_seconds", "im Zeitfenster (Sek.)", conf.get("raid_seconds", 20))
        + "</div>"
        + _check("lockdown_pause_invites", "Im Notmodus Einladungen pausieren (falls von Discord unterstützt)", conf.get("lockdown_pause_invites", True))
        + "<div class='gd-row'>"
        + _num("lockdown_slowmode", "Slowmode im Notmodus (Sek.)", conf.get("lockdown_slowmode", 10))
        + _num("lockdown_auto_minutes", "Notmodus automatisch beenden nach (Min., 0 = manuell)", conf.get("lockdown_auto_minutes", 10))
        + f"<div><label>Neue Beitritte im Notmodus</label><select name='lockdown_action_joins'>{join_opts}</select></div>"
        + "</div>"
    )

    # ---- Ausnahmen
    exemptions = (
        "<div class='gd-sub'>Ausnahmen</div>"
        "<div class='gd-hint'>Owner, Admins/„Server verwalten\", der Bot selbst und Reds Immunität "
        "(<span class='mono'>[p]immune</span>) sind ohnehin immer ausgenommen.</div>"
        "<div class='gd-row'>"
        f"<div><label>Rollen ausnehmen</label><select name='whitelist_roles' multiple size='5'>{role_opts}</select></div>"
        f"<div><label>Kanäle (nur Spamschutz)</label><select name='whitelist_channels' multiple size='5'>{chan_opts}</select></div>"
        "</div>"
        f"<label>Nutzer ausnehmen (IDs, mit Leerzeichen getrennt)</label>"
        f"<input name='whitelist_users' value='{_esc(wl_users)}' placeholder='z. B. 123456789012345678 987654321098765432'>"
        "<div class='gd-spacer'></div>"
        f"{override_fields}"
    )

    return (
        "<div class='card-x'><div class='gd-title'>Einstellungen</div>"
        "<form class='gd-form' method='post' action='/cogs/guard'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        "<input type='hidden' name='form' value='settings'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        f"{general}{honeypot}{spam}{escalation}{raid}{exemptions}"
        "<div class='gd-spacer'></div>"
        "<button class='btn-accent' type='submit'>Speichern</button>"
        "</form></div>"
    )


def _render_history(guild, conf) -> str:
    hist = conf.get("history") or []
    if not hist:
        return "<div class='card-x'><div class='gd-title'>Verlauf</div>Noch keine Aktionen protokolliert.</div>"
    kind_label = {"honeypot": "Honeypot", "spam": "Spam", "raid": "Raid/Notmodus",
                  "lockdown_join": "Beitritt (Notmodus)", "lockdown_end": "Notmodus beendet"}
    action_label = {"ban": "Bann", "softban": "Softban", "kick": "Kick", "timeout": "Timeout",
                    "warn": "Verwarnung", "delete": "gelöscht", "none": "—"}
    rule_label = {"honeypot": "Honeypot", "rate": "Rate", "repeat": "Wiederholung",
                  "mentions": "Erwähnungen", "invite": "Einladung", "link": "Link",
                  "wall": "Wall", "newaccount": "neues Konto", "lockdown_join": "Beitritt"}
    rows = ""
    for r in hist[:HISTORY_LIMIT]:
        rules = ", ".join(rule_label.get(x, x) for x in (r.get("rules") or [])) or "—"
        chan = f"#{r['channel']}" if r.get("channel") else "—"
        user = r.get("user") or "—"
        pts = r.get("points")
        pts_cell = "—" if pts is None else str(pts)
        rows += (
            f"<tr><td>{_esc(_ago(r.get('ts', 0)))}</td>"
            f"<td>{_esc(kind_label.get(r.get('kind'), r.get('kind')))}</td>"
            f"<td>{_esc(user)}</td>"
            f"<td>{_esc(rules)}</td>"
            f"<td>{_esc(action_label.get(r.get('action'), r.get('action')))}</td>"
            f"<td>{_esc(chan)}</td>"
            f"<td class='mono'>{_esc(pts_cell)}</td></tr>"
        )
    return (
        "<div class='card-x'><div class='gd-title'>Verlauf (letzte Aktionen)</div>"
        "<table class='table'><thead><tr><th>Wann</th><th>Auslöser</th><th>Nutzer</th>"
        "<th>Regel(n)</th><th>Aktion</th><th>Kanal</th><th>Punkte</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


HISTORY_LIMIT = 50


def _ago(ts: int) -> str:
    if not ts:
        return "—"
    secs = int(time.time() - ts)
    if secs < 60:
        return f"vor {secs}s"
    if secs < 3600:
        return f"vor {secs // 60}min"
    if secs < 86400:
        return f"vor {secs // 3600}h"
    return f"vor {secs // 86400}d"


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guild = cog.bot.get_guild(int(gid)) if gid and gid.isdigit() else None
    if guild is None:
        raise web.HTTPFound("/cogs/guard?ok=" + quote("Server nicht gefunden"))

    gconf = cog.config.guild(guild)

    if form == "lockdown":
        state = data.get("state")
        if state == "on":
            await cog._start_lockdown(guild, reason_kind="manual")
            raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&ok=" + quote("Notmodus aktiviert"))
        if state == "off":
            await cog._end_lockdown(guild)
            raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&ok=" + quote("Notmodus beendet"))
        raise web.HTTPFound(f"/cogs/guard?guild={guild.id}")

    if form == "settings":
        # Booleans (Checkbox-Anwesenheit)
        for field in BOOL_FIELDS:
            await gconf.set_raw(field, value=(field in data))

        # Zahlen mit Grenzen
        for field, (lo, hi) in INT_FIELDS.items():
            raw = data.get(field)
            if raw is None:
                continue
            try:
                val = int(raw)
            except (TypeError, ValueError):
                continue
            await gconf.set_raw(field, value=max(lo, min(hi, val)))

        # Sprache
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)

        # Selects: Aktionen
        hp_action = (data.get("hp_action") or "softban").lower()
        if hp_action in {a for a, _ in ACTIONS}:
            await gconf.hp_action.set(hp_action)
        join_action = (data.get("lockdown_action_joins") or "none").lower()
        if join_action in {a for a, _ in JOIN_ACTIONS}:
            await gconf.lockdown_action_joins.set(join_action)

        # Kanäle (gegen echte Guild-Objekte prüfen)
        def _valid_channel(value):
            if value and str(value).isdigit():
                ch = guild.get_channel(int(value))
                if ch is not None:
                    return ch.id
            return None

        await gconf.log_channel.set(_valid_channel(data.get("log_channel")))
        await gconf.hp_channel.set(_valid_channel(data.get("hp_channel")))

        # Multiselect: Rollen / Kanäle
        valid_role_ids = {r.id for r in guild.roles}
        roles = [int(r) for r in data.getall("whitelist_roles", []) if str(r).isdigit() and int(r) in valid_role_ids]
        await gconf.whitelist_roles.set(roles)
        valid_chan_ids = {c.id for c in guild.channels}
        chans = [int(c) for c in data.getall("whitelist_channels", []) if str(c).isdigit() and int(c) in valid_chan_ids]
        await gconf.whitelist_channels.set(chans)

        # Nutzer-IDs (Freitext)
        users = []
        for token in (data.get("whitelist_users") or "").replace(",", " ").split():
            if token.isdigit():
                users.append(int(token))
        await gconf.whitelist_users.set(users)

        # Text-Overrides
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)

        raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&ok=" + quote("Gespeichert"))

    raise web.HTTPFound(f"/cogs/guard?guild={guild.id}")
