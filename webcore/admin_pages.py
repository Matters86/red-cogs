"""HTML der Owner-Seiten „Zugriff & Rollen“, „Audit-Log“ und der Übersicht „Mein Bereich“.

Reine Darstellung (nur ``html``), die Daten kommen aus ``webcore.py``.
Alle dynamischen Werte werden escaped.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from . import ui
from .access import EDIT, LEVEL_LABEL, NONE, VIEW, parse_level

_MODE_TEXT = {
    "owner": "Nur Bot-Owner (plus die hier vergebenen Rollen-Rechte).",
    "admin": "Owner plus Discord-Administratoren – jeweils für ihren eigenen Server (plus Rollen-Rechte).",
    "allowlist": "Owner plus freigegebene Nutzer mit voller Sicht (plus Rollen-Rechte).",
}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _level_select(name: str, level: int) -> str:
    opts = [(NONE, "—"), (VIEW, "Ansehen"), (EDIT, "Bearbeiten")]
    inner = "".join(
        f"<option value='{v}'{' selected' if v == level else ''}>{label}</option>"
        for v, label in opts
    )
    cls = {NONE: "lv-none", VIEW: "lv-view", EDIT: "lv-edit"}[level]
    return f"<select class='wc-lv {cls}' name='{_esc(name)}' onchange='wcLv(this)'>{inner}</select>"


def render_access(*, guild, roles, pages, guild_perms: dict, csrf: str, access_mode: str) -> str:
    """Rechte-Matrix eines Servers.

    roles  : [(role_id, name, color_hex|None, member_count, position)] – alle Rollen des Servers
    pages  : [(slug, name, icon)]
    guild_perms : {role_id(str): {slug: 'view'|'edit'}}
    """
    role_by_id = {str(r[0]): r for r in roles}
    configured = [rid for rid in guild_perms if rid in role_by_id]
    configured.sort(key=lambda rid: -role_by_id[rid][4])
    stale = [rid for rid in guild_perms if rid not in role_by_id]

    head_cells = "".join(
        f"<th class='wc-col'><i class='bi {_esc(icon)}'></i><span>{_esc(name)}</span></th>"
        for _slug, name, icon in pages
    )
    rows = []
    for rid in configured:
        _id, rname, color, count, _pos = role_by_id[rid]
        dot = f"<span class='wc-role-dot' style='background:{_esc(color)}'></span>" if color else "<span class='wc-role-dot'></span>"
        cells = "".join(
            f"<td class='wc-col'>{_level_select(f'p:{rid}:{slug}', parse_level(guild_perms[rid].get(slug)))}</td>"
            for slug, _n, _i in pages
        )
        rows.append(
            "<tr>"
            f"<td class='wc-role'>{dot}<span>{_esc(rname)}</span>"
            f"<small>{int(count)} Mitglied{'er' if count != 1 else ''}</small>"
            f"<input type='hidden' name='roles' value='{_esc(rid)}'></td>"
            f"{cells}"
            f"<td class='wc-col'><button class='wc-icon-btn' name='remove' value='{_esc(rid)}' "
            "title='Rolle entfernen' onclick=\"return confirm('Alle Rechte dieser Rolle entfernen?')\">"
            "<i class='bi bi-x-lg'></i></button></td>"
            "</tr>"
        )
    if rows:
        matrix = (
            "<form method='post' action='/access'>"
            f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
            "<input type='hidden' name='form' value='matrix'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            "<div class='wc-scroll'><table class='table wc-matrix'>"
            f"<thead><tr><th>Rolle</th>{head_cells}<th></th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            "<div class='wc-actions'>"
            "<button class='btn-accent' type='submit'><i class='bi bi-check2'></i> Rechte speichern</button>"
            "<span class='wc-hint'>„Ansehen“ öffnet die Seite schreibgeschützt, „Bearbeiten“ erlaubt Speichern. "
            "Bei mehreren Rollen zählt die höchste Stufe.</span>"
            "</div></form>"
        )
    else:
        matrix = (
            "<div class='wc-empty'><i class='bi bi-shield-lock'></i>"
            "<div>Auf diesem Server hat noch keine Rolle Dashboard-Rechte.</div>"
            "<small>Füge unten eine Rolle hinzu.</small></div>"
        )

    free_roles = [r for r in sorted(roles, key=lambda r: -r[4]) if str(r[0]) not in guild_perms]
    role_opts = "".join(
        f"<option value='{r[0]}'>{_esc(r[1])} ({int(r[3])})</option>" for r in free_roles
    )
    add_form = (
        "<form method='post' action='/access' class='wc-inline-form'>"
        f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
        "<input type='hidden' name='form' value='add_role'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        "<label>Rolle<select name='role_id' required>"
        f"<option value=''>— Rolle wählen —</option>{role_opts}</select></label>"
        "<label>Startwert für alle Seiten<select name='default'>"
        "<option value='1'>Ansehen</option><option value='2'>Bearbeiten</option>"
        "</select></label>"
        "<button class='btn-accent' type='submit'><i class='bi bi-plus-lg'></i> Hinzufügen</button>"
        "</form>"
    ) if free_roles else "<div class='wc-hint'>Alle Rollen dieses Servers sind bereits eingetragen.</div>"

    stale_note = ""
    if stale:
        stale_note = (
            "<form method='post' action='/access' class='wc-note'>"
            f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
            "<input type='hidden' name='form' value='cleanup'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<i class='bi bi-exclamation-triangle'></i> {len(stale)} Eintrag/Einträge gehören zu gelöschten Rollen. "
            "<button class='wc-link-btn' type='submit'>Aufräumen</button></form>"
        )

    return (
        "<div class='card-x wc-intro'>"
        "<div class='wc-intro-icon'><i class='bi bi-person-lock'></i></div>"
        "<div><div class='section-title' style='margin-bottom:6px'>Wie funktioniert der Zugriff?</div>"
        "<p>Mitglieder mit einer hier eingetragenen Rolle können sich mit Discord anmelden und sehen "
        "<b>nur die freigegebenen Seiten</b> – und nur für <b>diesen Server</b>. Nur du als Bot-Owner "
        "kannst diese Rechte ändern.</p>"
        f"<p class='wc-hint' style='margin:0'>Grundmodus (<span class='mono'>[p]webcore access</span>): "
        f"<b>{_esc(access_mode)}</b> – {_esc(_MODE_TEXT.get(access_mode, ''))}</p></div></div>"
        "<div class='card-x' style='margin-top:16px'>"
        f"<div class='section-title'>Rollen-Rechte · {_esc(guild.name)}</div>"
        f"{stale_note}{matrix}</div>"
        "<div class='card-x' style='margin-top:16px'>"
        f"<div class='section-title'>Rolle hinzufügen</div>{add_form}</div>"
        "<script>function wcLv(s){s.className='wc-lv '+({0:'lv-none',1:'lv-view',2:'lv-edit'})[s.value];}</script>"
    )


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


def render_audit(entries: list, *, page_names: dict, guild_names: dict) -> str:
    """Audit-Log als ``ui.table`` (auf dem Handy Karten) mit Suche und Server-Filter (Client-seitig)."""
    if not entries:
        return ui.card(None, ui.empty("bi-journal-text", "Noch keine Änderungen über das Dashboard protokolliert."))
    guild_opts = "".join(
        f"<option value='{_esc(gid)}'>{_esc(name)}</option>"
        for gid, name in sorted(guild_names.items(), key=lambda kv: kv[1].lower())
    )
    rows = []
    for e in entries:
        gid = e.get("guild_id")
        gname = guild_names.get(str(gid)) or e.get("guild_name") or ("—" if not gid else str(gid))
        page = page_names.get(e.get("page")) or e.get("page") or "—"
        ok = e.get("ok", True)
        badge = ui.badge("OK", "ok") if ok else ui.badge("abgelehnt", "bad")
        rows.append(ui.row(
            f"<span class='mono nowrap'>{_esc(_fmt_ts(e.get('ts')))}</span>",
            f"<div class='wc-who'>{_esc(e.get('user_name') or '?')}<small class='mono'>{_esc(e.get('user_id') or '')}</small></div>",
            _esc(gname),
            _esc(page),
            f"<span class='mono'>{_esc(e.get('action') or '—')}</span>",
            f"{badge} <span class='wc-muted'>{_esc(e.get('result') or '')}</span>",
            attrs={"data-guild": gid or ""},
        ))
    tools = (
        "<div class='wc-table-tools'>"
        "<div class='wc-search'><i class='bi bi-search'></i>"
        "<input id='wc-audit-q' type='search' placeholder='Suchen (Nutzer, Seite, Aktion …)' aria-label='Suchen'></div>"
        f"<select class='wc-input' id='wc-audit-g' aria-label='Server' style='width:auto;max-width:100%'>"
        f"<option value=''>Alle Server</option>{guild_opts}</select>"
        "</div>"
    )
    table = ui.table(["Zeit", "Nutzer", "Server", "Seite", "Aktion", "Ergebnis"], rows, id="wc-audit")
    body = (
        tools + table
        + f"<p class='wc-hint' style='margin:10px 0 0'><span id='wc-audit-n'>{len(entries)}</span> Einträge · "
        "die letzten 300 werden aufbewahrt</p>"
        "<script>(function(){var q=document.getElementById('wc-audit-q'),g=document.getElementById('wc-audit-g'),"
        "n=document.getElementById('wc-audit-n');"
        "function f(){var t=q.value.toLowerCase(),gv=g.value,c=0;"
        "document.querySelectorAll('#wc-audit tbody tr').forEach(function(r){"
        "var ok=(!t||r.textContent.toLowerCase().indexOf(t)>-1)&&(!gv||r.dataset.guild===gv);"
        "r.style.display=ok?'':'none';if(ok)c++;});n.textContent=c;}"
        "q.addEventListener('input',f);g.addEventListener('change',f);})();</script>"
    )
    return ui.card("Protokoll", body, icon="bi-journal-text",
                   desc="Jede speichernde Dashboard-Aktion und jeder abgelehnte Zugriff – neueste zuerst.")


# --------------------------------------------------------------------------- #
#  Mitglieder-Bereich („Mein Bereich“)
# --------------------------------------------------------------------------- #
def render_portal_card(*, guild, enabled: bool, csrf: str, member_pages: list) -> str:
    """Karte „Mitglieder-Bereich“ auf „Zugriff & Rollen“. member_pages: [(name, icon, description)]."""
    if member_pages:
        items = "".join(
            f"<li><i class='bi {_esc(icon)}'></i><span><b>{_esc(name)}</b>"
            + (f" <span class='wc-muted'>– {_esc(desc)}</span>" if desc else "") + "</span></li>"
            for name, icon, desc in member_pages
        )
        pages_html = f"<ul class='wc-list'>{items}</ul>"
    else:
        pages_html = ui.callout(
            "Noch kein geladenes Modul bietet Mitglieder-Seiten an. Mitglieder sehen dann nur eine leere "
            "Übersicht – sobald ein Modul Seiten registriert, erscheinen sie automatisch.", tone="info")
    status = ui.badge("An", "ok") if enabled else ui.badge("Aus", "muted")
    body = (
        "<p class='wc-hint' style='margin-top:0'>Ist der Mitglieder-Bereich an, können sich <b>alle Mitglieder</b> "
        f"von <b>{_esc(guild.name)}</b> mit Discord anmelden. Sie sehen <b>ausschließlich „Mein Bereich“</b> mit "
        "diesen Seiten – und dort nur ihre eigenen Daten:</p>"
        + pages_html
        + "<p class='wc-hint'>Team-Seiten, „Zugriff &amp; Rollen“ und das Audit-Log bleiben für sie gesperrt. "
        "Befehl im Server: <span class='mono'>[p]webcore portal on|off</span></p>"
        + ui.form(
            "/access",
            ui.switch("portal", "Mein Bereich für Mitglieder freischalten", enabled,
                      desc="Gilt nur für diesen Server. Team und Owner können „Mein Bereich“ auch bei "
                           "ausgeschaltetem Schalter als Vorschau öffnen.")
            + ui.actions(
                ui.button("Speichern", icon="bi-check2"),
                ui.button("Vorschau öffnen", icon="bi-box-arrow-up-right", kind="ghost", href=f"/me?guild={guild.id}"),
            ),
            csrf=csrf, hidden={"form": "portal", "guild": guild.id}, savebar=False,
        )
    )
    return "<div style='margin-top:16px'>" + ui.card(
        "Mitglieder-Bereich („Mein Bereich“)", body, icon="bi-person-badge", actions=status,
        desc="Selbstbedienung für normale Server-Mitglieder",
    ) + "</div>"


def render_audit_channel(*, guild, channels: list, current, csrf: str, active: list) -> str:
    """Karte „Log-Kanal in Discord“ auf dem Audit-Log. channels: [(id, name)], active: [(server, kanal)]."""
    items = [(cid, f"#{name}") for cid, name in channels]
    control = ui.select("channel", items, current, none_label="— aus (nicht posten)")
    summary = ""
    if active:
        summary = "<p class='wc-hint' style='margin:10px 0 0'>Aktiv: " + " · ".join(
            f"<b>{_esc(g)}</b> → {_esc(c)}" for g, c in active) + "</p>"
    body = ui.form(
        "/audit",
        ui.grid(ui.field(f"Log-Kanal für {guild.name}", control,
                         help="Jeder Eintrag dieses Servers (auch abgelehnte Zugriffe) erscheint dort als Embed – "
                              "ohne Pings. Befehl: <span class='mono'>[p]webcore auditchannel [#kanal]</span>"),
                cols=1)
        + ui.actions(ui.button("Speichern", icon="bi-check2")),
        csrf=csrf, hidden={"guild": guild.id, "form": "auditchannel"},
    ) + summary
    return ui.card("Log-Kanal in Discord", body, icon="bi-discord",
                   desc="Gilt für den oben gewählten Server.") + "<div style='height:16px'></div>"


def render_member_home(*, guild, member, pages: list) -> str:
    """Übersicht „Mein Bereich“: Kacheln aller Mitglieder-Seiten. pages: [(slug, name, icon, description)]."""
    name = getattr(member, "display_name", None) or getattr(member, "name", "")
    parts = [ui.hero("bi-person-badge", "",
                     f"Hallo <b>{_esc(name)}</b>! Hier findest du deine persönlichen Bereiche auf "
                     f"<b>{_esc(guild.name)}</b>.")]
    if pages:
        tiles = "".join(
            f"<a class='tile' href='/me/{_esc(slug)}?guild={guild.id}'>"
            f"<span class='ti'><i class='bi {_esc(icon)}'></i></span>"
            f"<span style='min-width:0'><div class='tn'>{_esc(title)}</div>"
            + (f"<div class='td'>{_esc(desc)}</div>" if desc else "")
            + "</span></a>"
            for slug, title, icon, desc in pages
        )
        parts.append(ui.card("Deine Seiten", f"<div class='tiles'>{tiles}</div>", icon="bi-grid",
                             desc="Du siehst und änderst hier nur deine eigenen Daten."))
    else:
        parts.append(ui.card(None, ui.empty("bi-inboxes", "Noch keine Seiten verfügbar",
                                            "Sobald ein Modul Seiten für Mitglieder anbietet, erscheinen sie hier.")))
    return "".join(parts)


# --------------------------------------------------------------------------- #
#  Bot-Status
# --------------------------------------------------------------------------- #
def _kv(rows) -> str:
    return "<dl class='wc-kv'>" + "".join(f"<dt>{_esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def _links(items, prefix: str) -> str:
    if not items:
        return "<span class='wc-muted'>—</span>"
    return "<div class='wc-keys'>" + "".join(
        f"<a href='{_esc(prefix + slug)}'><code>{_esc(label)}</code></a>" if prefix else f"<code>{_esc(label)}</code>"
        for slug, label in items
    ) + "</div>"


def render_status(info: dict) -> str:
    """Owner-Seite „Bot-Status“. ``info`` kommt aus ``WebCore._collect_status``."""
    proc = info["process"]
    errs = info["errors"]
    err_tone = "bad" if errs["error"] else ("warn" if errs["warning"] else "ok")
    head = ui.hero(
        "bi-activity", "",
        "Zustand des Bots auf einen Blick: Laufzeit, Verbindung, Ressourcen, Versionen und welche Module "
        "welche Dashboard-Seiten anbieten.",
        actions=ui.button("Aktualisieren", icon="bi-arrow-clockwise", kind="ghost", href="/status", small=True),
    )
    lat = info["latency"]
    stats = ui.stats([
        ("Laufzeit", info["uptime"], "bi-clock-history", f"seit {info['started']}", None),
        ("Latenz", f"{lat} ms" if lat is not None else "—", "bi-wifi", "Discord-Gateway",
         None if lat is None else ("ok" if lat < 250 else "warn")),
        ("Server", info["guild_count"], "bi-hdd-network", None, None),
        ("Mitglieder", info["member_total"], "bi-people", f"{info['user_count']} Nutzer im Cache", None),
        ("Cogs", info["cog_count"], "bi-puzzle", f"{info['page_count']} Dashboard-Seiten", None),
        ("Fehler", errs["error"], "bi-bug", f"+ {errs['warning']} Warnung(en) im Protokoll", err_tone),
    ])

    if proc.get("source") == "psutil":
        prows = [
            ("Arbeitsspeicher", f"<span class='mono'>{proc['rss_mb']} MB</span>"
             + (f" <span class='wc-muted'>({proc['mem_pct']} % des Systems)</span>" if proc.get("mem_pct") is not None else "")),
            ("CPU", f"<span class='mono'>{proc['cpu_pct']} %</span>"
             + (f" <span class='wc-muted'>({proc['cpu_count']} Kerne)</span>" if proc.get("cpu_count") else "")),
            ("Threads", f"<span class='mono'>{_esc(proc.get('threads', '—'))}</span>"),
            ("Prozess-ID", f"<span class='mono'>{_esc(proc.get('pid', '—'))}</span>"),
            ("Messung", "psutil"),
        ]
    elif proc.get("source") == "resource":
        prows = [
            ("Arbeitsspeicher (Spitze)", f"<span class='mono'>{proc['rss_mb']} MB</span>"),
            ("CPU-Zeit gesamt", f"<span class='mono'>{_esc(proc['cpu_time'])}</span>"),
            ("Threads", f"<span class='mono'>{_esc(proc.get('threads', '—'))}</span>"),
            ("Prozess-ID", f"<span class='mono'>{_esc(proc.get('pid', '—'))}</span>"),
            ("Messung", "resource <span class='wc-muted'>(psutil nicht installiert – nur Spitzenwerte)</span>"),
        ]
    else:
        prows = [("Messung", "<span class='wc-muted'>nicht verfügbar auf diesem System</span>")]
    process_card = ui.card("Prozess", _kv(prows), icon="bi-cpu", desc="Ressourcen des Bot-Prozesses.")
    versions = ui.card("Versionen", _kv([(k, f"<span class='mono'>{_esc(v)}</span>") for k, v in info["versions"]]),
                       icon="bi-box-seam", desc="Laufzeitumgebung und Bibliotheken.")

    rows = []
    for c in info["cogs"]:
        origin = ui.badge("Red-Core", "info") if c["core"] else ui.badge(c["package"] or "Modul", "muted")
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(c['name'])}</div>",
            origin,
            f">{_esc(c['commands']) if c['commands'] is not None else '—'}",
            _links(c["pages"], "/cogs/"),
            _links(c["member_pages"], "/me/"),
            _links(c["apis"], ""),
            attrs={"data-core": "1" if c["core"] else "0"},
        ))
    cog_table = ui.table(["Cog", "Herkunft", ">Befehle", "Dashboard-Seiten", "Mein Bereich", "Öffentliche API"],
                         rows, search=True, search_placeholder="Cog suchen …", id="wc-cogs",
                         empty_text="Keine Cogs geladen.")
    cogs_card = ui.card("Geladene Cogs", cog_table, icon="bi-puzzle",
                        desc="Alle geladenen Cogs und was sie bei WebCore registriert haben "
                             "(Team-Seiten unter /cogs, Mitglieder-Seiten unter /me, öffentliche API unter /api/public).")

    if errs["recent"]:
        items = "".join(
            f"<li><span class='wc-pill {'bad' if r['levelno'] >= 40 else 'warn'}'>{_esc(r['level'])}</span>"
            f"<span style='min-width:0'><b>{_esc(r['source'])}</b> <span class='wc-muted'>{_esc(r['time'])}</span>"
            f"<div class='wc-msg'>{_esc(r['message'][:200])}</div></span></li>"
            for r in errs["recent"]
        )
        err_body = f"<ul class='wc-list'>{items}</ul>"
    else:
        err_body = ui.empty("bi-check2-circle", "Keine Warnungen oder Fehler seit dem Start des Protokolls.")
    err_card = ui.card("Letzte Meldungen", err_body, icon="bi-bug",
                       actions=ui.button("Fehlerprotokoll", icon="bi-arrow-right", kind="ghost", href="/errors", small=True))
    return head + stats + ui.columns(process_card, versions) + err_card + "<div style='height:16px'></div>" + cogs_card


# --------------------------------------------------------------------------- #
#  Fehlerprotokoll
# --------------------------------------------------------------------------- #
_LEVEL_TONE = {"WARNING": "warn", "ERROR": "bad", "CRITICAL": "bad"}


def render_errors(records: list, *, total: int, sources: list, level: str, source: str, query: str,
                  csrf: str, active: bool, capacity: int) -> str:
    """Fehlerprotokoll: Filter (GET), Tabelle (auf dem Handy Karten), Leeren (POST + Bestätigung)."""
    head = ui.hero(
        "bi-bug", "",
        "Warnungen und Fehler aller Cogs (Logger <span class='mono'>red.*</span>) seit dem Laden von WebCore – "
        f"nur im Arbeitsspeicher, höchstens {int(capacity)} Einträge. Tokens und Passwörter werden maskiert.",
    )
    if not active:
        head += ui.callout("Das Fehlerprotokoll ist gerade nicht aktiv (WebCore wurde ohne Protokoll-Handler gestartet).",
                           tone="warn")
    level_items = [("WARNING", "ab Warnung"), ("ERROR", "ab Fehler"), ("CRITICAL", "nur kritisch")]
    filters = ui.form(
        "/errors",
        ui.grid(
            ui.field("Stufe", ui.select("level", level_items, level, none_label="Alle Stufen")),
            ui.field("Quelle (Cog)", ui.select("source", [(s, s) for s in sources], source, none_label="Alle Quellen")),
            ui.field("Suche", ui.text_input("q", query, placeholder="Text in Meldung/Traceback …", type="search")),
            cols=3,
        )
        + ui.actions(ui.button("Filtern", icon="bi-funnel"),
                     ui.button("Zurücksetzen", icon="bi-x-lg", kind="ghost", href="/errors")),
        csrf="", method="get",
    )
    rows = []
    for r in records:
        tb = ""
        if r.get("traceback"):
            tb = (f"<details class='wc-trace'><summary>Traceback</summary>"
                  f"<pre>{_esc(r['traceback'])}</pre></details>")
        rows.append(ui.row(
            f"<span class='mono nowrap'>{_esc(r['time'])}</span>",
            ui.badge(r["level"], _LEVEL_TONE.get(r["level"], "muted")),
            f"<div class='wc-cell-title'>{_esc(r['source'])}</div><div class='wc-cell-sub mono'>{_esc(r['logger'])}</div>",
            f"<div class='wc-msg'>{_esc(r['message'])}</div>{tb}",
            attrs={"data-level": r["level"]},
        ))
    filtered = bool(level or source or query)
    shown = f"{len(records)} von {total}" if filtered else f"{total}"
    table = ui.table(["Zeit", "Stufe", "Quelle", "Meldung"], rows, id="wc-errors",
                     empty_text="Keine passenden Einträge." if filtered else "Keine Warnungen oder Fehler protokolliert.")
    clear = ui.form(
        "/errors", ui.button("Leeren", icon="bi-trash3", kind="danger", small=True),
        csrf=csrf, hidden={"form": "clear"},
        confirm="Alle Einträge des Fehlerprotokolls löschen? Das lässt sich nicht rückgängig machen.",
    ) if total else ""
    card = ui.card(f"Einträge ({shown})", table, icon="bi-list-ul", actions=clear,
                   desc="Neueste zuerst. Traceback per Klick aufklappen.")
    return head + ui.card("Filter", filters, icon="bi-funnel") + "<div style='height:16px'></div>" + card


# --------------------------------------------------------------------------- #
#  Sichern & Wiederherstellen
# --------------------------------------------------------------------------- #
def _key_list(keys, limit: int = 12) -> str:
    if not keys:
        return "<span class='wc-muted'>—</span>"
    shown = "".join(f"<code>{_esc(k)}</code>" for k in keys[:limit])
    more = f" <span class='wc-muted'>+{len(keys) - limit}</span>" if len(keys) > limit else ""
    return f"<div class='wc-keys'>{shown}{more}</div>"


def _fmt_iso(value) -> str:
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(value or "—")


def _render_webcore_plan(wplan: dict, *, page_names: dict, can_import: bool) -> tuple[str, str]:
    """Block „Dashboard-Einstellungen“ der Import-Vorschau. -> (Diff-HTML, Schalter fürs Bestätigungsformular)."""
    def page(slug):
        return _esc(page_names.get(slug, slug))

    def lvl(name):
        return _esc(LEVEL_LABEL[parse_level(name)])

    def items(pairs, fmt):
        if not pairs:
            return "<span class='wc-muted'>—</span>"
        return "<div class='wc-keys'>" + "".join(f"<code>{fmt(p)}</code>" for p in pairs) + "</div>"

    rows = [
        ui.row(
            f"<div class='wc-cell-title'>{_esc(r['name'])}</div><div class='wc-cell-sub mono'>{_esc(r['id'])}</div>",
            items(r["gain"], lambda p: f"{page(p[0])}: {lvl(p[1])}"),
            items(r["lose"], lambda p: f"{page(p[0])} ({lvl(p[1])})"),
            items(r["change"], lambda p: f"{page(p[0])}: {lvl(p[1])} → {lvl(p[2])}"),
        )
        for r in wplan["roles"]
    ]
    parts = ["<div class='wc-sub'><i class='bi bi-shield-lock'></i> Dashboard-Einstellungen</div>"]
    if wplan["role_perms"] is not None:
        parts.append(ui.table(["Rolle", "Bekommt", "Verliert", "Ändert"], rows, id="wc-import-webcore",
                              empty_text="Rollen-Rechte: keine Änderungen."))
        parts.append("<p class='wc-hint' style='margin:8px 0 12px'>"
                     + ("Gleicher Server: die Rechte-Matrix wird auf den Stand der Sicherung gesetzt – Rollen, die "
                        "dort fehlen, verlieren ihre Rechte." if wplan["same_guild"] else
                        "Anderer Server: nur Rollen aus der Sicherung, die es hier gibt, werden gesetzt – alle "
                        "anderen Rollen behalten ihre Rechte.") + "</p>")
    kv = []
    portal = wplan.get("portal")
    if portal:
        onoff = {True: "an", False: "aus"}
        kv.append(("Mein Bereich", (f"{onoff[portal['old']]} → <b>{onoff[portal['new']]}</b> "
                                    + ui.badge("Änderung", "warn")) if portal["changed"]
                   else f"{onoff[portal['old']]} " + ui.badge("unverändert", "ok")))
    chan = wplan.get("audit_channel")
    if chan:
        def cname(cid, name):
            if not cid:
                return "aus"
            return f"#{_esc(name)}" if name else f"<span class='mono'>{_esc(cid)}</span>"
        old_c, new_c = cname(chan["old"], chan["old_name"]), cname(chan["new"], chan["new_name"])
        kv.append(("Log-Kanal (Audit)", f"{old_c} → <b>{new_c}</b> " + ui.badge("Änderung", "warn")
                   if chan["changed"] else f"{old_c} " + ui.badge("unverändert", "ok")))
    if kv:
        parts.append(_kv(kv))
    problems = []
    if wplan["skipped_roles"]:
        problems.append("Rollen gibt es auf diesem Server nicht (übersprungen): " + _key_list(wplan["skipped_roles"]))
    if wplan["unknown_slugs"]:
        problems.append("Unbekannte Seiten (übersprungen): " + _key_list(wplan["unknown_slugs"]))
    if wplan["invalid_levels"]:
        problems.append("Ungültige Stufe (übersprungen, bisheriger Wert bleibt): " + _key_list(
            [f"{role} / {slug}: {val}" for role, slug, val in wplan["invalid_levels"]]))
    if wplan["skipped_channel"] is not None:
        problems.append("Log-Kanal gibt es auf diesem Server nicht (übersprungen): "
                        f"<span class='mono'>{_esc(wplan['skipped_channel'])}</span>")
    for err in wplan["errors"]:
        problems.append("Ungültig (übersprungen): " + _esc(err))
    if problems:
        parts.append("<div style='height:10px'></div>" + ui.callout("<br>".join(problems), tone="warn"))
    switch = ""
    if not can_import:
        parts.append(ui.callout("Dashboard-Einstellungen (Rollen-Rechte) importiert nur der Bot-Owner – "
                                "sie werden übersprungen.", tone="info", icon="bi-shield-lock"))
    elif wplan["changes"]:
        switch = ui.switch("include_webcore", "Dashboard-Einstellungen übernehmen", False,
                           desc=f"{int(wplan['changes'])} Änderung(en) an Rollen-Rechten, Mein Bereich bzw. "
                                "Log-Kanal dieses Servers. <b>Sicherheitsrelevant</b> – bitte die Liste oben prüfen.")
    else:
        parts.append("<p class='wc-hint' style='margin:10px 0 0'>Dashboard-Einstellungen: keine Änderungen.</p>")
    return "".join(parts), switch


def render_backup_preview(*, guild, data: dict, plan: dict, token: str, csrf: str, filename: str,
                          page_names: dict | None = None, can_webcore: bool = False) -> str:
    """Vorschau eines hochgeladenen Backups mit Bestätigung."""
    src_id, src_name = data.get("guild_id"), data.get("guild_name") or "?"
    info = _kv([
        ("Datei", f"<span class='mono'>{_esc(filename or 'backup.json')}</span>"),
        ("Erstellt", _esc(_fmt_iso(data.get("created")))),
        ("Quelle", f"{_esc(src_name)} <span class='wc-muted mono'>{_esc(src_id)}</span>"),
        ("Ziel", f"<b>{_esc(guild.name)}</b> <span class='wc-muted mono'>{guild.id}</span>"),
    ])
    notes = ""
    if str(src_id) != str(guild.id):
        notes += ui.callout(
            "Die Sicherung stammt von <b>einem anderen Server</b>. Einstellungen werden übernommen, aber "
            "<b>Kanal- und Rollen-IDs passen dann nicht</b> – prüfe danach Kanäle und Rollen in den Modulen.",
            tone="warn")
    if plan["missing"]:
        notes += ui.callout("Nicht geladen (werden übersprungen): " + ", ".join(_esc(m) for m in plan["missing"]),
                            tone="info")
    rows, unchanged = [], []
    for item in plan["cogs"]:
        if item["status"] == "ok" and not any(
                sc and (sc["changed"] or sc["unknown"] or sc["type_errors"] or sc["secret"])
                for sc in (item.get("guild"), item.get("global"))):
            unchanged.append(item["name"])
            continue
        if item["status"] != "ok":
            why = "anderer Cog (identifier passt nicht)" if item["status"] == "identifier" else "ungültiger Eintrag"
            rows.append(ui.row(f"<div class='wc-cell-title'>{_esc(item['name'])}</div>", ui.badge("übersprungen", "bad"),
                               f"<span class='wc-muted'>{_esc(why)}</span>", "—", "—"))
            continue
        for scope_key, scope_label in (("guild", "Server"), ("global", "Botweit")):
            sc = item.get(scope_key)
            if sc is None:
                continue
            problems = []
            if sc["unknown"]:
                problems.append("<div class='wc-cell-sub'>unbekannt, wird ignoriert:</div>" + _key_list(sc["unknown"]))
            if sc["type_errors"]:
                problems.append("<div class='wc-cell-sub'>falscher Typ, wird ignoriert:</div>" + _key_list(
                    [f"{k} ({want} erwartet, {got})" for k, want, got in sc["type_errors"]]))
            if sc["secret"]:
                problems.append("<div class='wc-cell-sub'>geschützt (Secret), wird ignoriert:</div>" + _key_list(sc["secret"]))
            badge = ui.badge(f"{len(sc['changed'])} Änderung(en)", "warn") if sc["changed"] else ui.badge("unverändert", "ok")
            rows.append(ui.row(
                f"<div class='wc-cell-title'>{_esc(item['name'])}</div><div class='wc-cell-sub'>{scope_label}</div>",
                badge,
                _key_list(sc["changed"]),
                f">{len(sc['same'])}",
                "".join(problems) or "<span class='wc-muted'>—</span>",
                attrs={"data-scope": scope_key},
            ))
    table = ui.table(["Cog", "Status", "Wird überschrieben", ">Gleich", "Hinweise"], rows, id="wc-import-plan",
                     empty_text=("Keine Änderungen – alle Einstellungen sind bereits so." if unchanged
                                 else "Die Sicherung enthält keine Einstellungen geladener Cogs."))
    if unchanged:
        table += ("<p class='wc-hint' style='margin:10px 0 0'><b>Unverändert</b> (bereits identisch): "
                  + ", ".join(_esc(n) for n in unchanged) + "</p>")
    wc_block, wc_switch = "", ""
    if plan.get("webcore") is not None:
        wc_block, wc_switch = _render_webcore_plan(plan["webcore"], page_names=page_names or {},
                                                   can_import=can_webcore)
        table += ui.divider() + wc_block
    glob = ""
    if plan["has_global"]:
        glob = ui.switch("include_global", "Botweite Einstellungen übernehmen", False,
                         desc="Gilt für alle Server. Secrets (Tokens, Passwörter) sind nie in der Sicherung und "
                              "bleiben unverändert.")
    confirm_form = ui.form(
        "/backup",
        (ui.switches(*[x for x in (glob, wc_switch) if x]) if glob or wc_switch else "") + ui.actions(
            ui.button("Import ausführen", icon="bi-upload", kind="danger", name="form", value="confirm",
                      confirm=f"Einstellungen auf „{guild.name}“ jetzt überschreiben? Rückgängig ist möglich, "
                              "solange der Bot läuft."),
            ui.button("Abbrechen", icon="bi-x-lg", kind="ghost", name="form", value="cancel",
                      attrs={"formnovalidate": True}),
        ),
        csrf=csrf, hidden={"guild": guild.id, "preview": token},
    )
    body = info + "<div style='height:12px'></div>" + notes + table + ui.divider() + confirm_form
    return ui.card("Vorschau: diese Einstellungen werden überschrieben", body, icon="bi-eye", tone="warn",
                   desc="Es wird erst etwas geändert, wenn du den Import bestätigst.")


def render_backup(*, guild, cogs: list, csrf: str, undo: list, preview: str = "", webcore_export: bool = False) -> str:
    """Owner-Seite „Sichern & Wiederherstellen“. cogs: [(name, n_guild_keys, n_global_keys)],
    undo: [{"id", "time", "user", "cogs", "keys", "source"}]."""
    head = ui.hero(
        "bi-cloud-arrow-down", "",
        f"Server-Einstellungen aller Module von <b>{_esc(guild.name)}</b> als JSON-Datei sichern und wieder "
        "einspielen – z. B. vor größeren Umbauten oder um einen zweiten Server gleich einzurichten.",
    )
    if cogs:
        items = "".join(
            f"<li><i class='bi bi-puzzle'></i><span style='min-width:0'><b>{_esc(n)}</b> "
            f"<span class='wc-muted'>– {int(g)} Server-Einstellung(en)"
            + (f", {int(gl)} botweit" if gl else "") + "</span></span></li>"
            for n, g, gl in cogs
        )
        cog_list = f"<ul class='wc-list'>{items}</ul>"
    else:
        cog_list = ui.empty("bi-puzzle", "Kein geladenes Modul mit Dashboard-Seite und Einstellungen.")
    if webcore_export:
        cog_list += ("<ul class='wc-list'><li><i class='bi bi-shield-lock'></i><span style='min-width:0'>"
                     "<b>Dashboard-Einstellungen</b> <span class='wc-muted'>– Rollen-Rechte, Mein Bereich und "
                     "Log-Kanal nur dieses Servers</span></span></li></ul>")
    export = ui.card(
        "Sichern (Export)",
        cog_list + ui.divider() + ui.form(
            "/backup",
            ui.switch("include_global", "Botweite Einstellungen mitsichern", False,
                      desc="Einstellungen, die für alle Server gelten – immer <b>ohne</b> Tokens, Secrets und "
                           "Passwörter.")
            + ui.actions(ui.button("JSON herunterladen", icon="bi-download")),
            csrf=csrf, hidden={"form": "export", "guild": guild.id},
        ),
        icon="bi-download", desc="Enthält alle Server-Einstellungen der Module mit Dashboard-Seite.",
    )
    restore = ui.card(
        "Wiederherstellen (Import)",
        ui.form(
            f"/backup?guild={guild.id}",
            ui.grid(ui.field("Sicherungsdatei (.json, höchstens 2 MB)",
                             "<input class='wc-input' type='file' name='backup' accept='.json,application/json' required>",
                             help="Zuerst siehst du eine Vorschau, was überschrieben wird. Nur Einstellungen, die das "
                                  "Modul kennt, werden übernommen."), cols=1)
            + ui.actions(ui.button("Vorschau anzeigen", icon="bi-eye")),
            csrf=csrf, hidden={"form": "preview", "guild": guild.id}, enctype="multipart/form-data",
        ),
        icon="bi-upload", desc=f"Spielt eine Sicherung auf <b>{_esc(guild.name)}</b> ein (auch von einem anderen Server).",
    )
    parts = [head]
    if preview:
        parts.append(preview + "<div style='height:16px'></div>")
    if undo:
        rows = []
        for u in undo:
            rows.append(ui.row(
                f"<span class='mono nowrap'>{_esc(u['time'])}</span>",
                _esc(u["user"]),
                _esc(u["source"]),
                _key_list(u["cogs"], limit=6),
                f">{int(u['keys'])}",
                ui.form("/backup", ui.button("Rückgängig", icon="bi-arrow-counterclockwise", kind="ghost", small=True),
                        csrf=csrf, hidden={"form": "undo", "guild": guild.id, "undo": u["id"]},
                        confirm="Die Einstellungen dieses Imports auf den Stand davor zurücksetzen? "
                                "Spätere Änderungen an denselben Einstellungen gehen dabei verloren."),
            ))
        parts.append(ui.card(
            "Rückgängig machen",
            ui.table(["Zeit", "Durch", "Quelle", "Cogs", ">Einstellungen", ""], rows, id="wc-undo"),
            icon="bi-arrow-counterclockwise",
            desc="Vor jedem Import wird der Ist-Zustand im Arbeitsspeicher vorgehalten – bis zum Neustart des Bots "
                 "bzw. Neuladen von WebCore.",
        ) + "<div style='height:16px'></div>")
    parts.append(ui.columns(export, restore))
    return "".join(parts)
