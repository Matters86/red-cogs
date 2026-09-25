"""HTML der Owner-Seiten „Zugriff & Rollen“ und „Audit-Log“.

Reine Darstellung (nur ``html``), die Daten kommen aus ``webcore.py``.
Alle dynamischen Werte werden escaped.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from .access import EDIT, NONE, VIEW, parse_level

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
    """Audit-Log-Tabelle (neueste zuerst) mit Client-seitigem Filter."""
    if not entries:
        return (
            "<div class='card-x'><div class='wc-empty'><i class='bi bi-journal-text'></i>"
            "<div>Noch keine Änderungen über das Dashboard protokolliert.</div></div></div>"
        )
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
        badge = "<span class='wc-badge ok'>OK</span>" if ok else "<span class='wc-badge bad'>abgelehnt</span>"
        rows.append(
            f"<tr data-guild='{_esc(gid or '')}'>"
            f"<td class='mono' style='white-space:nowrap'>{_esc(_fmt_ts(e.get('ts')))}</td>"
            f"<td><div class='wc-who'>{_esc(e.get('user_name') or '?')}<small class='mono'>{_esc(e.get('user_id') or '')}</small></div></td>"
            f"<td>{_esc(gname)}</td>"
            f"<td>{_esc(page)}</td>"
            f"<td class='mono'>{_esc(e.get('action') or '—')}</td>"
            f"<td>{badge} <span class='wc-muted'>{_esc(e.get('result') or '')}</span></td>"
            "</tr>"
        )
    return (
        "<div class='card-x'>"
        "<div class='wc-toolbar'>"
        "<input id='wc-audit-q' type='search' placeholder='Suchen (Nutzer, Seite, Aktion …)'>"
        f"<select id='wc-audit-g'><option value=''>Alle Server</option>{guild_opts}</select>"
        f"<span class='wc-hint'>{len(entries)} Einträge · die letzten 300 werden aufbewahrt</span>"
        "</div>"
        "<div class='wc-scroll'><table class='table' id='wc-audit'>"
        "<thead><tr><th>Zeit</th><th>Nutzer</th><th>Server</th><th>Seite</th><th>Aktion</th><th>Ergebnis</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></div>"
        "<script>(function(){var q=document.getElementById('wc-audit-q'),g=document.getElementById('wc-audit-g');"
        "function f(){var t=q.value.toLowerCase(),gv=g.value;"
        "document.querySelectorAll('#wc-audit tbody tr').forEach(function(r){"
        "var ok=(!t||r.textContent.toLowerCase().indexOf(t)>-1)&&(!gv||r.dataset.guild===gv);"
        "r.style.display=ok?'':'none';});}q.addEventListener('input',f);g.addEventListener('change',f);})();</script>"
    )
