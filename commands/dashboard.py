"""WebCore-Dashboard für den Commands-Cog.

Eine Seite unter ``/cogs/commands``:

* **GET**  – Befehlsliste aller geladenen Cogs mit Mindeststufe (Jeder/Mod/Admin/Owner),
  Rechte-/Status-Badges, Suche und Filter (clientseitig).
  - ``?guild=<id>&member=<id|name>`` blendet eine exakte Mitglieds-Prüfung als
    zusätzliche Spalte ein.
  - ``?hidden=1`` zeigt zusätzlich die ausgeblendeten Einträge (nur Bot-Owner).
  - ``?export=md`` liefert die (gefilterte) Liste als Markdown-Datei.
* **POST** – schaltet die Sichtbarkeit einzelner Cogs/Befehle um (CSRF-geschützt,
  nur Bot-Owner/volle Sicht), danach Redirect (Post/Redirect/Get).

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``): Reiter
Befehle · Sichtbarkeit (nur Bot-Owner) – kein eigenes Grunddesign.
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
#  Clientseitige Filter (Cog/Stufe) – ergänzt die Textsuche von ui.table
# --------------------------------------------------------------------------- #
# Läuft nach dem Tabellenfilter von webcore.js (DOMContentLoaded) und bündelt
# Suche + Cog + Stufe, damit sich die Filter nicht gegenseitig überschreiben und
# die Cog-Zwischenzeilen nur erscheinen, wenn darunter noch Treffer stehen.
_FILTER = """
<style>tr.cx-grp td{background:var(--panel-2)}</style>
<script>
(function(){
  function run(){
    var t=document.getElementById('cx-table'); if(!t) return;
    var s=document.querySelector("input[data-wc-filter='#cx-table']");
    var q=(s?s.value:'').trim().toLowerCase();
    var cogEl=document.getElementById('cx-cog'), tierEl=document.getElementById('cx-tier');
    var cog=cogEl?cogEl.value:'', tier=tierEl?tierEl.value:'';
    var groups={}, shown=0;
    t.querySelectorAll('tbody tr.cx-row').forEach(function(r){
      var ok=(!q||r.textContent.toLowerCase().indexOf(q)>-1)
        &&(!cog||r.getAttribute('data-cog')===cog)
        &&(tier===''||parseInt(r.getAttribute('data-tier'),10)<=parseInt(tier,10));
      r.style.display=ok?'':'none';
      if(ok){groups[r.getAttribute('data-cog')]=1;shown++;}
    });
    t.querySelectorAll('tbody tr.cx-grp').forEach(function(h){
      h.style.display=groups[h.getAttribute('data-cog')]?'':'none';
    });
    var n=document.getElementById('cx-count'); if(n) n.textContent=shown;
  }
  document.addEventListener('DOMContentLoaded',function(){
    ['cx-cog','cx-tier'].forEach(function(id){
      var el=document.getElementById(id); if(el) el.addEventListener('change',run);
    });
    var s=document.querySelector("input[data-wc-filter='#cx-table']");
    if(s) s.addEventListener('input',run);
  });
})();
</script>
"""

_TIER_TONE = ["ok", "info", "warn", "bad"]


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
def _tier_badge(ui, info) -> str:
    if info.guild_owner_only:
        return ui.badge("Server-Owner", "bad")
    return ui.badge(TIER_LABELS[info.required_tier], _TIER_TONE[info.required_tier])


def _status_badges(ui, info) -> str:
    chips = [ui.badge(f"oder: {label}", "info") for label in info.perm_labels]
    if info.custom_checks:
        chips.append(ui.badge("Extra-Prüfung"))
    if not info.enabled:
        chips.append(ui.badge("deaktiviert", "bad"))
    if info.hidden:
        chips.append(ui.badge("versteckt"))
    if info.is_hidden_cfg:
        chips.append(ui.badge("ausgeblendet", "warn"))
    if not chips:
        return "<span class='wc-muted'>—</span>"
    return " ".join(chips)


def _verdict_cell(ui, info) -> str:
    if info.verdict is None:
        return "<span class='wc-muted'>—</span>"
    note = f"<div class='wc-cell-sub'>{_esc(info.verdict_note)}</div>" if info.verdict_note else ""
    if info.verdict:
        return ui.badge("✓ darf", "ok") + note
    return ui.badge("✗ gesperrt", "bad") + note


def _toggle_form(ui, action: str, kind: str, value: str, csrf: str, *, label: str = "", title: str = "") -> str:
    """POST-Formular zum Ein-/Ausblenden (Felder: action, kind, value)."""
    hide = action == "hide"
    btn = ui.button(label, icon="bi-eye-slash" if hide else "bi-eye", kind="ghost", small=True,
                    attrs={"title": title} if title else None)
    return ui.form("/cogs/commands", btn, csrf=csrf, hidden={"action": action, "kind": kind, "value": value})


def _command_cell(info) -> str:
    sig = f" <span class='wc-muted mono'>{_esc(info.signature)}</span>" if info.signature else ""
    grp = " <span class='wc-pill'>Gruppe</span>" if info.is_group else ""
    sub = []
    if info.short:
        sub.append(_esc(info.short))
    if info.aliases:
        sub.append("Aliase: " + _esc(", ".join(info.aliases)))
    pad = f" style='padding-left:{info.depth * 18}px'" if info.depth else ""
    return (
        f"<div{pad}><div class='wc-cell-title'><span class='mono'>{_esc(info.qualified_name)}</span>{sig}{grp}</div>"
        + (f"<div class='wc-cell-sub'>{' · '.join(sub)}</div>" if sub else "")
        + "</div>"
    )


def _row(ui, info, csrf: str, show_member: bool, full: bool) -> str:
    cells = [
        _command_cell(info),
        _tier_badge(ui, info),
        _status_badges(ui, info),
    ]
    if show_member:
        cells.append(_verdict_cell(ui, info))
    if full:
        if info.is_hidden_cfg:
            cells.append(">" + _toggle_form(ui, "show", "command", info.qualified_name, csrf, title="Befehl einblenden"))
        else:
            cells.append(">" + _toggle_form(ui, "hide", "command", info.qualified_name, csrf, title="Befehl ausblenden"))
    return ui.row(*cells, attrs={
        "class": "cx-row", "data-cog": info.cog.lower(), "data-tier": info.required_tier,
    })


def _group_header(ui, cog_name: str, count: int, hidden_cog: bool, colspan: int) -> str:
    title = _esc(cog_name) if cog_name else "Sonstige"
    badge = " " + ui.badge("ausgeblendet", "warn") if hidden_cog else ""
    return (
        f"<tr class='cx-grp' data-cog='{_esc(cog_name.lower())}'><td colspan='{colspan}'>"
        f"<div class='wc-cell-title'><i class='bi bi-box'></i> {title} "
        f"<span class='wc-muted'>· {count} Befehle</span>{badge}</div>"
        "</td></tr>"
    )


async def _visible_guilds(cog, request):
    webcore = request.app.get("webcore")
    if webcore is not None:
        guilds = await webcore.visible_guilds(request)
    else:  # Fallback (sollte im Normalbetrieb nicht eintreten)
        guilds = list(cog.bot.guilds)
    return sorted(guilds, key=lambda g: g.name.lower())


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
        lines.append(f"_Geprüft für: {member.display_name} auf {guild.name}_")
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
#  Seitenteile
# --------------------------------------------------------------------------- #
def _member_check_card(ui, guilds, gid, member_query, member, member_error, show_hidden, switcher,
                       usable, n_shown) -> str:
    fields = [ui.field("Mitglied", ui.text_input("member", member_query, placeholder="ID oder Name, z. B. Lena"),
                       help="Zeigt in der Liste eine zusätzliche Spalte „Prüfung“: darf die Person den Befehl ausführen?")]
    hidden = ""
    if switcher:
        # Globaler Server-Wechsler aktiv -> geprüft wird auf dem dort gewählten Server.
        hidden = f"<input type='hidden' name='guild' value='{_esc(gid)}'>"
    else:
        fields.append(ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], gid,
                                                   none_label="Server wählen …")))
    if show_hidden:
        hidden += "<input type='hidden' name='hidden' value='1'>"
    buttons = [ui.button("Prüfen", icon="bi-person-check")]
    if member is not None:
        buttons.append(ui.button("Zurücksetzen", icon="bi-x-lg", kind="ghost",
                                 href="/cogs/commands" + _qs(hidden="1" if show_hidden else None, guild=gid)))
    form = (
        "<form class='wc-form' method='get' action='/cogs/commands'>"
        + hidden + ui.grid(*fields, cols=1 if switcher else 2) + ui.actions(*buttons)
        + "</form>"
    )
    result = ""
    if member_error:
        result = ui.callout(_esc(member_error), tone="bad")
    elif member is not None:
        result = ui.callout(
            f"<b>{_esc(member.display_name)}</b> darf <b>{usable}</b> von {n_shown} Befehlen ausführen – "
            "siehe Spalte „Prüfung“ in der Liste.", tone="ok")
    return ui.card("Mitglied prüfen", result + form, icon="bi-person-check",
                   desc="Exakte Antwort für eine bestimmte Person auf einem Server.")


def _legend_card(ui) -> str:
    rows = "".join(
        f"<dt>{ui.badge(label, _TIER_TONE[idx])}</dt><dd>{text}</dd>"
        for idx, (label, text) in enumerate(zip(TIER_LABELS, [
            "Jedes Mitglied darf den Befehl nutzen.",
            "Ab Mod-Rolle (und alle Stufen darüber).",
            "Ab Admin-Rolle (und Bot-Owner).",
            "Nur der Bot-Owner (bzw. Server-Owner, falls so markiert).",
        ]))
    )
    rows += (
        f"<dt>{ui.badge('oder: …', 'info')}</dt><dd>Wer dieses Discord-Recht hat, darf den Befehl auch ohne die Stufe.</dd>"
        f"<dt>{ui.badge('Extra-Prüfung')}</dt><dd>Der Befehl hat eigene Bedingungen, die hier nicht ausgewertet werden.</dd>"
    )
    return ui.card("So liest du die Liste", f"<dl class='wc-kv'>{rows}</dl>", icon="bi-question-circle",
                   desc="Die <b>Mindeststufe</b> ist die Red-Stufe, ab der ein Befehl freigegeben ist.")


def _list_card(ui, visible, names, hidden_cogs, csrf, show_member, full, member, card_actions) -> str:
    groups = _group(visible)
    headers = ["Befehl", "Mindeststufe", "Rechte / Status"]
    if show_member:
        headers.append("Prüfung")
    if full:
        headers.append(">Sichtbar")
    colspan = len(headers)

    if not groups:
        return ui.card("Befehlsliste", ui.empty("bi-list-check", "Keine Befehle gefunden.",
                                                "Sobald Cogs mit Befehlen geladen sind, erscheinen sie hier."),
                       icon="bi-list-check", actions=card_actions)

    rows = []
    for cog_name in sorted(groups, key=lambda c: (c or "").lower()):
        items = sorted(groups[cog_name], key=lambda i: i.qualified_name.lower())
        rows.append(_group_header(ui, cog_name, len(items), cog_name in hidden_cogs, colspan))
        for info in items:
            rows.append(_row(ui, info, csrf, show_member, full))

    cog_opts = "".join(f"<option value='{_esc(n.lower())}'>{_esc(n)}</option>" for n in names)
    tier_opts = "".join(f"<option value='{i}'>Nutzbar für: {_esc(label)}</option>" for i, label in enumerate(TIER_LABELS))
    filters = (
        "<div class='wc-toolbar'>"
        f"<select id='cx-cog' aria-label='Cog filtern'><option value=''>Alle Cogs</option>{cog_opts}</select>"
        f"<select id='cx-tier' aria-label='Stufe filtern'><option value=''>Alle Stufen</option>{tier_opts}</select>"
        f"<span class='wc-muted'><b id='cx-count'>{len(visible)}</b> Befehle</span>"
        "</div>"
    )
    table = ui.table(headers, rows, search=True, id="cx-table",
                     search_placeholder="Befehl, Alias oder Beschreibung suchen …")
    desc = "Gruppiert nach Cog. Filter und Suche wirken sofort."
    if member is not None:
        desc += f" Geprüft für <b>{_esc(member.display_name)}</b>."
    return ui.card("Befehlsliste", filters + table, icon="bi-list-check", desc=desc, actions=card_actions)


def _visibility_tab(ui, infos, names, hidden_cogs, hidden_cmds, csrf, toggle_link) -> str:
    counts: dict = {}
    for info in infos:
        counts[info.cog] = counts.get(info.cog, 0) + 1

    intro = ui.callout(
        "<b>Nur Bot-Owner.</b> Diese Einstellung gilt <b>botweit auf allen Servern</b>: Ausgeblendete Cogs und Befehle "
        "erscheinen nicht mehr in <code>[p]meinebefehle</code> und nicht in der Befehlsliste. Die Befehle selbst "
        "funktionieren weiter. Einzelne Befehle blendest du in der Befehlsliste über das Augen-Symbol aus.",
        tone="warn", icon="bi-shield-lock")

    cog_rows = []
    for name in sorted(set(names) | set(hidden_cogs), key=str.lower):
        is_hidden = name in hidden_cogs
        status = ui.badge("ausgeblendet", "warn") if is_hidden else ui.badge("sichtbar", "ok")
        if is_hidden:
            btn = ui.form("/cogs/commands", ui.button("Einblenden", icon="bi-eye", kind="ghost", small=True),
                          csrf=csrf, hidden={"action": "show", "kind": "cog", "value": name})
        else:
            btn = ui.form("/cogs/commands", ui.button("Ausblenden", icon="bi-eye-slash", kind="ghost", small=True),
                          csrf=csrf, hidden={"action": "hide", "kind": "cog", "value": name})
        cog_rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(name)}</div><div class='wc-cell-sub'>{counts.get(name, 0)} Befehle</div>",
            status, ">" + btn,
        ))
    cogs_card = ui.card(
        "Cogs", ui.table(["Cog", "Status", ">"], cog_rows, empty_text="Keine Cogs mit Befehlen geladen.",
                         search=len(cog_rows) > 8, search_placeholder="Cog suchen …", id="cx-cogs"),
        icon="bi-boxes", desc="Blendet alle Befehle eines Cogs auf einmal aus bzw. ein.",
        actions=ui.badge("nur Bot-Owner", "warn"))

    cmd_rows = []
    for qn in sorted(hidden_cmds, key=str.lower):
        btn = ui.form("/cogs/commands", ui.button("Einblenden", icon="bi-eye", kind="ghost", small=True),
                      csrf=csrf, hidden={"action": "show", "kind": "command", "value": qn})
        cmd_rows.append(ui.row(f"<span class='mono'>{_esc(qn)}</span>", ">" + btn))
    if cmd_rows:
        cmds_body = ui.table(["Befehl", ">"], cmd_rows, search=len(cmd_rows) > 8,
                             search_placeholder="Befehl suchen …", id="cx-hidden-cmds")
    else:
        cmds_body = ui.empty("bi-eye", "Keine einzeln ausgeblendeten Befehle.",
                             "Über das Augen-Symbol in der Befehlsliste kannst du einzelne Befehle ausblenden.")
    cmds_card = ui.card("Einzeln ausgeblendete Befehle", cmds_body, icon="bi-eye-slash",
                        desc="Befehle, die unabhängig von ihrem Cog ausgeblendet sind.",
                        actions=toggle_link)
    return intro + cogs_card + cmds_card


# --------------------------------------------------------------------------- #
#  Haupteinstieg
# --------------------------------------------------------------------------- #
async def render(cog, request):
    bot = cog.bot
    csrf = request.get("webcore_csrf", "")

    # Die globale Sichtbarkeits-Config (hidden_cogs/hidden_commands) ist in Discord
    # owner-only. Nur "volle Sicht" (Owner/Allowlist) darf sie hier ändern bzw.
    # ausgeblendete Einträge sehen.
    webcore = request.app.get("webcore")
    user = await webcore._get_user(request) if webcore else None
    full = await webcore._has_full_scope(user) if webcore else True

    # --- POST: Sichtbarkeit umschalten (CSRF ist bereits zentral geprüft) ---
    if request.method == "POST":
        if not full:
            return {"redirect": "/cogs/commands?err=" + quote("Nur der Bot-Owner darf die Sichtbarkeit ändern.")}
        form = await request.post()
        action = form.get("action")
        kind = form.get("kind")
        value = (form.get("value") or "").strip()[:100]
        if action in ("hide", "show") and kind in ("cog", "command") and value:
            await cog.set_visibility(kind, value, hide=(action == "hide"))
        return {"redirect": "/cogs/commands?ok=1"}

    ui = request.app["webcore"].ui
    query = request.query
    show_hidden = query.get("hidden") == "1" and full
    gid = query.get("guild") or ""
    member_query = (query.get("member") or "").strip()

    hidden_cogs = set(await cog.config.hidden_cogs())
    hidden_cmds = set(await cog.config.hidden_commands())

    infos = [build_command_info(c) for c in walk_all_commands(bot)]
    for info in infos:
        info.is_hidden_cfg = (info.cog in hidden_cogs) or (info.qualified_name in hidden_cmds)

    visible = [i for i in infos if show_hidden or not i.is_hidden_cfg]

    # --- optionale Mitglieds-Prüfung ---
    guilds = await _visible_guilds(cog, request)
    guild = None
    member = None
    member_error = ""
    if gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                guild = g
                break
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
    usable = sum(1 for i in visible if i.verdict) if show_member else 0

    # --- Links (Filter beim Wechsel beibehalten) ---
    hidden_now = "1" if show_hidden else None
    toggle_href = "/cogs/commands" + _qs(
        hidden=(None if show_hidden else "1"), guild=gid, member=member_query
    )
    export_href = "/cogs/commands" + _qs(
        export="md", hidden=hidden_now, guild=gid, member=member_query
    )
    toggle_link = ""
    if full:
        toggle_link = ui.button(
            "Ausgeblendete verbergen" if show_hidden else "Ausgeblendete anzeigen",
            icon="bi-eye-slash" if show_hidden else "bi-eye", kind="ghost", small=True, href=toggle_href,
        )

    head = ui.hero(
        "bi-list-check", "",
        "Alle Befehle der geladenen Cogs – mit der <b>Stufe</b>, ab der sie nutzbar sind, und zusätzlichen "
        "Discord-Rechten. Prüfe gezielt, was ein bestimmtes Mitglied darf, oder exportiere die Liste.",
    )
    export_btn = ui.button("Markdown-Export", icon="bi-download", kind="ghost", small=True, href=export_href)
    stat_items = [
        ("Cogs", len(names), "bi-boxes", None, None),
        ("Befehle gesamt", n_total, "bi-terminal", None, None),
        ("Angezeigt", n_shown, "bi-eye", None, None),
        ("Ausgeblendet", n_hidden, "bi-eye-slash", "botweit, vom Bot-Owner", "warn" if n_hidden else None),
    ]
    if show_member:
        stat_items.append((f"{member.display_name} darf", f"{usable}/{n_shown}", "bi-person-check", None, "ok"))
    head += ui.stats(stat_items)

    switcher = bool(request.get("wc_switcher"))
    top = ui.columns(
        _member_check_card(ui, guilds, gid, member_query, member, member_error, show_hidden, switcher,
                           usable, n_shown),
        _legend_card(ui),
    )
    body = ui.tab("befehle", "Befehle", "bi-list-check",
                  top + _list_card(ui, visible, names, hidden_cogs, csrf, show_member, full, member,
                                   export_btn + toggle_link),
                  count=n_shown)
    if full:
        body += ui.tab("sichtbarkeit", "Sichtbarkeit (Bot-Owner)", "bi-shield-lock",
                       _visibility_tab(ui, infos, names, hidden_cogs, hidden_cmds, csrf, toggle_link),
                       count=n_hidden or None)

    return {"title": "Befehle", "content": _FILTER + head + body}
