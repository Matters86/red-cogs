"""WebCore-Dashboard für den Commands-Cog.

Eine Seite unter ``/cogs/commands``:

* **GET**  – Befehlsliste aller geladenen Cogs mit Stufen-Spalten
  (Jeder/Mod/Admin/Owner), Detail-Metadaten, Suche/Filter (clientseitig).
  - ``?guild=<id>&member=<id|name>`` blendet eine exakte Mitglieds-Prüfung als
    zusätzliche Spalte ein.
  - ``?hidden=1`` zeigt zusätzlich die ausgeblendeten Einträge.
  - ``?export=md`` liefert die (gefilterte) Liste als Markdown-Datei.
* **POST** – schaltet die Sichtbarkeit einzelner Cogs/Befehle um (CSRF-geschützt),
  danach Redirect (Post/Redirect/Get).

Es werden nur Theme-Klassen (card-x, table, stat, btn-accent …) plus die ohnehin
geladenen Bootstrap-Klassen genutzt – kein eigenes Grunddesign, nur ein kleiner,
auf die Theme-Variablen abgestimmter Style für Tabelle/Badges/Formularfelder.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote

from aiohttp import web

from .inspector import (
    TIER_LABELS,
    build_command_info,
    cog_names,
    evaluate_member,
    member_privilege_level,
    walk_all_commands,
)

# --------------------------------------------------------------------------- #
#  Style + clientseitige Filterung
# --------------------------------------------------------------------------- #
_STYLE = """
<style>
  .cx-bar{display:flex;flex-wrap:wrap;gap:18px;margin-bottom:18px}
  .cx-stat{padding:14px 18px;min-width:120px}
  .cx-controls{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-bottom:14px}
  .cx-controls .grp{display:flex;flex-direction:column;gap:4px}
  .cx-controls label{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em}
  .cx-controls input,.cx-controls select{background:var(--panel-2);color:var(--text);
    border:1px solid var(--border);border-radius:9px;padding:8px 11px;font-family:inherit;font-size:.9rem}
  .cx-controls input[type=text]{min-width:230px}
  .cx-links{display:flex;gap:14px;flex-wrap:wrap;margin-left:auto;align-items:center}
  .cx-links a{color:var(--accent);text-decoration:none;font-size:.88rem}
  .cx-links a:hover{text-decoration:underline}
  .cx-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);color:var(--text);
    border-radius:10px;padding:10px 14px;margin-bottom:16px}
  .cx-err{background:rgba(255,107,107,.12);border:1px solid #ff6b6b;color:var(--text);
    border-radius:10px;padding:10px 14px;margin-bottom:16px}
  .cx-legend{color:var(--muted);font-size:.8rem;margin:6px 0 16px;line-height:1.5}
  table.cx-tbl{width:100%;border-collapse:collapse;font-size:.9rem}
  table.cx-tbl th,table.cx-tbl td{border-bottom:1px solid var(--border);padding:7px 9px;text-align:left;vertical-align:top}
  table.cx-tbl th{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
  table.cx-tbl th.cx-c,table.cx-tbl td.cx-yes,table.cx-tbl td.cx-no{text-align:center;width:64px}
  tr.cx-grp td{background:var(--panel-2);border-top:2px solid var(--border)}
  .cx-grp-name{font-family:"Archivo",sans-serif;font-weight:700;font-size:1rem}
  .cx-grp-count{color:var(--muted);margin-left:8px;font-size:.8rem}
  code.cx-cmd{color:var(--text);font-family:"IBM Plex Mono",monospace}
  .cx-sig{color:var(--muted);font-family:"IBM Plex Mono",monospace;font-size:.82rem}
  .cx-alias{color:var(--muted);font-size:.8rem}
  .cx-tag{background:rgba(61,220,151,.14);color:var(--accent);border-radius:6px;padding:1px 6px;font-size:.7rem;margin-left:4px}
  .cx-cogcell{color:var(--muted);white-space:nowrap}
  .cx-yes{color:var(--accent);font-weight:700}
  .cx-no{color:var(--border)}
  .cx-desc{color:var(--muted)}
  .cx-muted{color:var(--muted)}
  .cx-chip{display:inline-block;background:var(--panel-2);border:1px solid var(--border);
    border-radius:6px;padding:1px 7px;font-size:.74rem;margin:0 4px 4px 0;white-space:nowrap}
  .cx-chip-perm{border-color:var(--accent);color:var(--accent)}
  .cx-chip-off{border-color:#ff6b6b;color:#ff8585}
  .cx-verdict-ok{color:var(--accent);font-weight:700;white-space:nowrap}
  .cx-verdict-no{color:#ff8585;font-weight:700;white-space:nowrap}
  .cx-note{color:var(--muted);font-weight:400;font-size:.72rem}
  form.cx-inline{display:inline;margin:0}
  .cx-mini{background:transparent;border:1px solid var(--border);color:var(--muted);
    border-radius:7px;padding:2px 9px;font-size:.74rem;cursor:pointer}
  .cx-mini:hover{border-color:var(--accent);color:var(--accent)}
  .cx-mini-off:hover{border-color:#ff6b6b;color:#ff8585}
  .cx-check{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;
    background:var(--panel-2);border:1px solid var(--border);border-radius:11px;padding:12px 14px;margin-bottom:16px}
  .cx-check .grp{display:flex;flex-direction:column;gap:4px}
  .cx-check label{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em}
  .cx-check input,.cx-check select{background:var(--bg,#0c0f14);color:var(--text);
    border:1px solid var(--border);border-radius:9px;padding:8px 11px;font-family:inherit;font-size:.9rem}
  .cx-check .who{color:var(--text);font-size:.9rem;margin-right:6px}
</style>
<script>
  function cxFilter(){
    var qEl=document.getElementById('cx-q');
    var cogEl=document.getElementById('cx-cog');
    var tierEl=document.getElementById('cx-tier');
    var q=(qEl?qEl.value:'').toLowerCase();
    var cog=cogEl?cogEl.value:'';
    var tier=tierEl?tierEl.value:'';
    var counts={};
    document.querySelectorAll('tr.cx-row').forEach(function(r){
      var okText=!q||(r.getAttribute('data-text')||'').indexOf(q)!==-1;
      var okCog=!cog||r.getAttribute('data-cog')===cog;
      var okTier=(tier==='')||(parseInt(r.getAttribute('data-tier'),10)<=parseInt(tier,10));
      var show=okText&&okCog&&okTier;
      r.style.display=show?'':'none';
      if(show){var c=r.getAttribute('data-cog');counts[c]=(counts[c]||0)+1;}
    });
    document.querySelectorAll('tr.cx-grp').forEach(function(h){
      var c=h.getAttribute('data-cog');
      h.style.display=counts[c]?'':'none';
    });
  }
  document.addEventListener('DOMContentLoaded',function(){
    ['cx-q','cx-cog','cx-tier'].forEach(function(id){
      var el=document.getElementById(id);
      if(el){el.addEventListener('input',cxFilter);el.addEventListener('change',cxFilter);}
    });
  });
</script>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _qs(**params) -> str:
    parts = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        parts.append(f"{key}={quote(str(value))}")
    return ("?" + "&".join(parts)) if parts else ""


def _tier_label(info) -> str:
    if info.guild_owner_only:
        return "Server-Owner"
    return TIER_LABELS[info.required_tier]


def _resolve_member(guild, query: str):
    query = (query or "").strip()
    if not query:
        return None
    digits = "".join(ch for ch in query if ch.isdigit())
    if digits and (query.startswith("<@") or query.isdigit()):
        found = guild.get_member(int(digits))
        if found is not None:
            return found
    found = guild.get_member_named(query)
    if found is not None:
        return found
    if digits:
        return guild.get_member(int(digits))
    return None


def _group(infos) -> dict:
    groups: dict = {}
    for info in infos:
        groups.setdefault(info.cog, []).append(info)
    return groups


# --------------------------------------------------------------------------- #
#  HTML-Bausteine
# --------------------------------------------------------------------------- #
def _status_badges(info) -> str:
    chips = []
    for label in info.perm_labels:
        chips.append(f"<span class='cx-chip cx-chip-perm'>oder: {_esc(label)}</span>")
    if info.guild_owner_only:
        chips.append("<span class='cx-chip'>Server-Owner</span>")
    if info.custom_checks:
        chips.append("<span class='cx-chip'>Extra-Pr&#252;fung</span>")
    if not info.enabled:
        chips.append("<span class='cx-chip cx-chip-off'>deaktiviert</span>")
    if info.hidden:
        chips.append("<span class='cx-chip'>versteckt</span>")
    if info.is_hidden_cfg:
        chips.append("<span class='cx-chip cx-chip-off'>ausgeblendet</span>")
    return "".join(chips) or "<span class='cx-muted'>&mdash;</span>"


def _tier_cells(info) -> str:
    cells = []
    for ok in info.allowed_tiers:
        cells.append("<td class='cx-yes'>&#10003;</td>" if ok else "<td class='cx-no'>&middot;</td>")
    return "".join(cells)


def _verdict_cell(info) -> str:
    if info.verdict is None:
        return "<td class='cx-no'>&middot;</td>"
    note = f"<div class='cx-note'>{_esc(info.verdict_note)}</div>" if info.verdict_note else ""
    if info.verdict:
        return f"<td class='cx-verdict-ok'>&#10003; darf{note}</td>"
    return f"<td class='cx-verdict-no'>&#10007; gesperrt{note}</td>"


def _toggle_button(action: str, kind: str, value: str, label: str, csrf: str) -> str:
    return (
        "<form method='post' action='/cogs/commands' class='cx-inline'>"
        f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
        f"<input type='hidden' name='action' value='{action}'>"
        f"<input type='hidden' name='kind' value='{kind}'>"
        f"<input type='hidden' name='value' value='{_esc(value)}'>"
        f"<button class='cx-mini cx-mini-off'>{_esc(label)}</button>"
        "</form>"
    )


def _command_cell(info, csrf: str) -> str:
    pad = 9 + info.depth * 18
    grp = " <span class='cx-tag'>Gruppe</span>" if info.is_group else ""
    sig = f" <span class='cx-sig'>{_esc(info.signature)}</span>" if info.signature else ""
    alias = ""
    if info.aliases:
        alias = " <span class='cx-alias'>(" + _esc(", ".join(info.aliases)) + ")</span>"
    if info.is_hidden_cfg:
        btn = _toggle_button("show", "command", info.qualified_name, "einblenden", csrf)
    else:
        btn = _toggle_button("hide", "command", info.qualified_name, "ausblenden", csrf)
    return (
        f"<td style='padding-left:{pad}px'>"
        f"<code class='cx-cmd'>{_esc(info.qualified_name)}</code>{sig}{grp}{alias} {btn}"
        "</td>"
    )


def _row(info, csrf: str, show_member: bool) -> str:
    joined = (info.qualified_name + " " + " ".join(info.aliases) + " " + info.short).lower()
    cog_cell = _esc(info.cog) if info.cog else "<span class='cx-muted'>&mdash;</span>"
    extra = _verdict_cell(info) if show_member else ""
    return (
        f"<tr class='cx-row' data-cog='{_esc(info.cog.lower())}' "
        f"data-text='{_esc(joined)}' data-tier='{info.required_tier}'>"
        + _command_cell(info, csrf)
        + f"<td class='cx-cogcell'>{cog_cell}</td>"
        + _tier_cells(info)
        + f"<td>{_status_badges(info)}</td>"
        + extra
        + f"<td class='cx-desc'>{_esc(info.short)}</td>"
        + "</tr>"
    )


def _group_header(cog_name: str, count: int, hidden_cog: bool, csrf: str, colspan: int) -> str:
    title = _esc(cog_name) if cog_name else "Sonstige"
    if hidden_cog:
        btn = _toggle_button("show", "cog", cog_name, "Cog einblenden", csrf)
        badge = " <span class='cx-chip cx-chip-off'>ausgeblendet</span>"
    else:
        btn = _toggle_button("hide", "cog", cog_name, "Cog ausblenden", csrf)
        badge = ""
    return (
        f"<tr class='cx-grp' data-cog='{_esc(cog_name.lower())}'>"
        f"<td colspan='{colspan}'>"
        f"<span class='cx-grp-name'>{title}</span>"
        f"<span class='cx-grp-count'>{count} Befehle</span>{badge} {btn}"
        "</td></tr>"
    )


def _guild_options(bot, selected) -> str:
    opts = ["<option value=''>Server w&#228;hlen &hellip;</option>"]
    for guild in sorted(bot.guilds, key=lambda g: g.name.lower()):
        sel = " selected" if str(guild.id) == str(selected) else ""
        opts.append(f"<option value='{guild.id}'{sel}>{_esc(guild.name)}</option>")
    return "".join(opts)


def _cog_filter_options(names) -> str:
    opts = ["<option value=''>Alle Cogs</option>"]
    for name in names:
        opts.append(f"<option value='{_esc(name.lower())}'>{_esc(name)}</option>")
    return "".join(opts)


def _tier_filter_options() -> str:
    opts = ["<option value=''>Alle Stufen</option>"]
    for idx, label in enumerate(TIER_LABELS):
        opts.append(f"<option value='{idx}'>{_esc(label)}</option>")
    return "".join(opts)


# --------------------------------------------------------------------------- #
#  Markdown-Export
# --------------------------------------------------------------------------- #
def _md(text) -> str:
    return (str(text) if text is not None else "").replace("|", "&#124;").replace("\n", " ").strip()


def _build_markdown(infos, guild, member) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    show_member = member is not None
    groups = _group(infos)
    lines = ["# Befehle", "", f"_Stand: {now}_"]
    if show_member:
        lines.append(f"_Gepr\u00fcft f\u00fcr: {member.display_name} auf {guild.name}_")
    lines.append("")
    lines.append(f"Insgesamt **{len(infos)}** Befehle in **{len(groups)}** Cogs.")
    lines.append("")
    for cog in sorted(groups, key=lambda c: (c or "").lower()):
        lines.append(f"## {cog or 'Sonstige'}")
        lines.append("")
        if show_member:
            lines.append("| Befehl | Mindeststufe | Rechte | Darf | Beschreibung |")
            lines.append("|---|---|---|---|---|")
        else:
            lines.append("| Befehl | Mindeststufe | Rechte | Beschreibung |")
            lines.append("|---|---|---|---|")
        for info in sorted(groups[cog], key=lambda i: i.qualified_name.lower()):
            sig = (" " + info.signature) if info.signature else ""
            cmd = "`[p]" + info.qualified_name + sig + "`"
            tier = _tier_label(info)
            perms = ", ".join(info.perm_labels) or "—"
            desc = _md(info.short) or "—"
            if show_member:
                verdict = "—"
                if info.verdict is True:
                    verdict = "✓"
                elif info.verdict is False:
                    verdict = "✗"
                lines.append(f"| {_md(cmd)} | {tier} | {_md(perms)} | {verdict} | {desc} |")
            else:
                lines.append(f"| {_md(cmd)} | {tier} | {_md(perms)} | {desc} |")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Haupteinstieg
# --------------------------------------------------------------------------- #
async def render(cog, request):
    bot = cog.bot
    csrf = request.get("webcore_csrf", "")

    # --- POST: Sichtbarkeit umschalten (CSRF ist bereits zentral geprüft) ---
    if request.method == "POST":
        form = await request.post()
        action = form.get("action")
        kind = form.get("kind")
        value = (form.get("value") or "").strip()
        if action in ("hide", "show") and kind in ("cog", "command") and value:
            await cog.set_visibility(kind, value, hide=(action == "hide"))
        return {"redirect": "/cogs/commands?ok=1"}

    query = request.query
    show_hidden = query.get("hidden") == "1"
    gid = query.get("guild") or ""
    member_query = (query.get("member") or "").strip()

    hidden_cogs = set(await cog.config.hidden_cogs())
    hidden_cmds = set(await cog.config.hidden_commands())

    infos = [build_command_info(c) for c in walk_all_commands(bot)]
    for info in infos:
        info.is_hidden_cfg = (info.cog in hidden_cogs) or (info.qualified_name in hidden_cmds)

    visible = [i for i in infos if show_hidden or not i.is_hidden_cfg]

    # --- optionale Mitglieds-Prüfung ---
    guild = None
    member = None
    member_error = ""
    if gid.isdigit():
        guild = bot.get_guild(int(gid))
    if guild is not None and member_query:
        member = _resolve_member(guild, member_query)
        if member is None:
            member_error = "Mitglied nicht gefunden (evtl. nicht im Bot-Cache)."
        else:
            member_priv = await member_privilege_level(bot, member)
            for info in visible:
                verdict, note = evaluate_member(info, member, member_priv)
                info.verdict = verdict
                info.verdict_note = note
    show_member = member is not None

    # --- Markdown-Export? ---
    if query.get("export") == "md":
        text = _build_markdown(visible, guild, member)
        return web.Response(
            text=text,
            content_type="text/markdown",
            charset="utf-8",
            headers={"Content-Disposition": 'attachment; filename="befehle.md"'},
        )

    # --- Kennzahlen ---
    names = cog_names(bot)
    n_total = len(infos)
    n_hidden = sum(1 for i in infos if i.is_hidden_cfg)
    n_shown = len(visible)

    # --- Links (Filter beim Wechsel beibehalten) ---
    hidden_now = "1" if show_hidden else None
    toggle_href = "/cogs/commands" + _qs(
        hidden=(None if show_hidden else "1"), guild=gid, member=member_query
    )
    toggle_label = "ausgeblendete verbergen" if show_hidden else "ausgeblendete anzeigen"
    export_href = "/cogs/commands" + _qs(
        export="md", hidden=hidden_now, guild=gid, member=member_query
    )

    colspan = 9 if show_member else 8

    # --- Tabelle ---
    parts = []
    parts.append(_STYLE)

    if query.get("ok") == "1":
        parts.append("<div class='cx-flash'>Gespeichert.</div>")
    if member_error:
        parts.append(f"<div class='cx-err'>{_esc(member_error)}</div>")

    # Kennzahlen-Karten
    parts.append("<div class='cx-bar'>")
    parts.append(f"<div class='card-x cx-stat'><div class='stat'>{len(names)}</div><div class='stat-label'>Cogs</div></div>")
    parts.append(f"<div class='card-x cx-stat'><div class='stat'>{n_total}</div><div class='stat-label'>Befehle gesamt</div></div>")
    parts.append(f"<div class='card-x cx-stat'><div class='stat'>{n_shown}</div><div class='stat-label'>angezeigt</div></div>")
    parts.append(f"<div class='card-x cx-stat'><div class='stat'>{n_hidden}</div><div class='stat-label'>ausgeblendet</div></div>")
    if show_member:
        usable = sum(1 for i in visible if i.verdict)
        parts.append(
            "<div class='card-x cx-stat'>"
            f"<div class='stat'>{usable}/{n_shown}</div>"
            f"<div class='stat-label'>{_esc(member.display_name)} darf</div></div>"
        )
    parts.append("</div>")

    # Mitglieds-Prüfung (GET-Formular)
    reset = ""
    if show_member:
        reset = " <a class='who' href='/cogs/commands" + _qs(hidden=hidden_now) + "'>zur&#252;cksetzen</a>"
    hidden_field = "<input type='hidden' name='hidden' value='1'>" if show_hidden else ""
    parts.append(
        "<form method='get' action='/cogs/commands' class='cx-check'>"
        "<div class='grp'><label>Server</label>"
        f"<select name='guild'>{_guild_options(bot, gid)}</select></div>"
        "<div class='grp'><label>Mitglied (ID oder Name)</label>"
        f"<input type='text' name='member' value='{_esc(member_query)}' placeholder='z. B. 123456789012345678'></div>"
        f"{hidden_field}"
        "<button class='btn-accent'>Pr&#252;fen</button>"
        f"{reset}"
        "</form>"
    )

    # Filterleiste + Links
    parts.append("<div class='cx-controls'>")
    parts.append("<div class='grp'><label>Suche</label><input type='text' id='cx-q' placeholder='Befehl, Alias oder Text&hellip;'></div>")
    parts.append(f"<div class='grp'><label>Cog</label><select id='cx-cog'>{_cog_filter_options(names)}</select></div>")
    parts.append(f"<div class='grp'><label>Nutzbar f&#252;r</label><select id='cx-tier'>{_tier_filter_options()}</select></div>")
    parts.append("<div class='cx-links'>")
    parts.append(f"<a href='{_esc(toggle_href)}'>{toggle_label}</a>")
    parts.append(f"<a href='{_esc(export_href)}'>&#8681; Markdown-Export</a>")
    parts.append("</div></div>")

    # Legende
    parts.append(
        "<div class='cx-legend'>"
        "Die Spalten <b>Jeder/Mod/Admin/Owner</b> zeigen, ab welcher Red-Stufe ein Befehl "
        "freigegeben ist (&#10003; = gen&#252;gt). <b>Owner</b> = Bot-Owner. Zus&#228;tzliche "
        "Discord-Rechte stehen als Badge 'oder: &hellip;' &ndash; wer sie hat, darf den Befehl "
        "auch ohne die Stufe. Die exakte Antwort pro Person liefert die Mitglieds-Pr&#252;fung oben."
        "</div>"
    )

    # Tabelle aufbauen (gruppiert nach Cog)
    parts.append("<div class='card-x'><table class='cx-tbl'>")
    head_member = "<th class='cx-c'>Pr&#252;fung</th>" if show_member else ""
    parts.append(
        "<thead><tr>"
        "<th>Befehl</th><th>Cog</th>"
        "<th class='cx-c'>Jeder</th><th class='cx-c'>Mod</th>"
        "<th class='cx-c'>Admin</th><th class='cx-c'>Owner</th>"
        "<th>Rechte / Status</th>"
        f"{head_member}"
        "<th>Beschreibung</th>"
        "</tr></thead><tbody>"
    )

    groups = _group(visible)
    if not groups:
        parts.append(f"<tr><td colspan='{colspan}' class='cx-muted'>Keine Befehle gefunden.</td></tr>")
    else:
        for cog_name in sorted(groups, key=lambda c: (c or "").lower()):
            rows = sorted(groups[cog_name], key=lambda i: i.qualified_name.lower())
            cog_hidden = cog_name in hidden_cogs
            parts.append(_group_header(cog_name, len(rows), cog_hidden, csrf, colspan))
            for info in rows:
                parts.append(_row(info, csrf, show_member))

    parts.append("</tbody></table></div>")

    return {"title": "Befehle", "content": "".join(parts)}
