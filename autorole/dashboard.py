"""WebCore-Dashboard für den Autorole-Cog.

Aufgaben:
* GET  -> Seite rendern (Status, Hinweise, Einstellungen, Rollen-Auswahl)
* POST -> Formular speichern bzw. Aktion ausführen, danach Redirect (Post/Redirect/Get)

Es werden nur die Theme-Klassen (card-x, stat, table, btn-accent …) plus die
ohnehin geladenen Bootstrap-Klassen genutzt – kein eigenes Design. Die
Oberfläche ist – wie im übrigen Repo – durchgängig deutsch.
"""

from __future__ import annotations

import html
from urllib.parse import quote_plus

from aiohttp import web

from .panels import MAX_ROLES, MODES, STYLES, new_panel
from .strings import LANGUAGES

# Auf die Theme-Variablen abgestimmter Style nur für die Formularfelder.
_FORM_STYLE = """
<style>
  .ar-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .ar-form input,.ar-form select,.ar-form textarea{width:100%;background:var(--panel-2);color:var(--text);
    border:1px solid var(--border);border-radius:9px;padding:9px 11px;font-family:inherit;font-size:.92rem}
  .ar-form select[multiple]{min-height:150px;padding:6px}
  .ar-form select[multiple] option{padding:4px 6px;border-radius:6px}
  .ar-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .ar-form .hint{color:var(--muted);font-size:.78rem;margin-top:4px}
  .ar-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .ar-check input{width:auto}
  .ar-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .ar-warn{background:rgba(255,107,107,.08);border:1px solid var(--danger)}
  .ar-section-title{font-family:"Archivo",sans-serif;font-weight:700;font-size:1.15rem;margin:0 0 14px}
  .ar-spacer{height:26px}
</style>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _options(items, selected_ids, *, none_label: str | None = None) -> str:
    """``items``: Liste von (id, label). ``selected_ids``: Menge/Container von ids."""
    sel = {str(s) for s in (selected_ids or [])}
    out = []
    if none_label is not None:
        is_sel = " selected" if not sel else ""
        out.append(f"<option value=''{is_sel}>{_esc(none_label)}</option>")
    for ident, label in items:
        is_sel = " selected" if str(ident) in sel else ""
        out.append(f"<option value='{_esc(ident)}'{is_sel}>{_esc(label)}</option>")
    return "".join(out)


def _ids(values) -> list[int]:
    out = []
    for v in values:
        if v and str(v).isdigit():
            out.append(int(v))
    return out


def _role_options(cog, guild, selected_ids) -> str:
    """Alle (nicht-@everyone) Rollen, höchste zuerst; nicht zuweisbare mit ⚠ markiert."""
    sel = {str(s) for s in (selected_ids or [])}
    out = []
    for r in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if r.is_default():
            continue
        mark = "⚠ " if cog._assignable_reason(guild, r) is not None else ""
        is_sel = " selected" if str(r.id) in sel else ""
        out.append(f"<option value='{r.id}'{is_sel}>{mark}{_esc(r.name)}</option>")
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Einstiegspunkt
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
        return {"title": "Autorole", "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='ar-flash'>{_esc(request.query.get('ok'))}</div>"

    # Einzelnes Panel bearbeiten?
    panels = conf.get("panels", {})
    pid = request.query.get("panel")
    if pid and pid in panels:
        content = _FORM_STYLE + flash + _render_panel_editor(cog, guild, panels[pid], csrf)
        return {"title": f"Autorole · {panels[pid].get('name', 'Panel')}", "content": content}

    guild_opts = _options(
        [(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())],
        [guild.id],
    )
    guild_picker = f"""
    <div class='card-x' style='margin-bottom:20px'>
      <form method='get' action='/cogs/autorole' class='ar-form' style='margin:0'>
        <label style='margin-top:0'>Server</label>
        <select name='guild' onchange='this.form.submit()'>{guild_opts}</select>
      </form>
    </div>
    """

    content = (
        _FORM_STYLE
        + flash
        + guild_picker
        + _render_stats(cog, guild, conf)
        + _render_warnings(cog, guild, conf)
        + _render_settings(cog, guild, conf, csrf)
        + "<div class='ar-spacer'></div>"
        + _render_apply(guild, conf, csrf)
        + "<div class='ar-spacer'></div>"
        + _render_panels(cog, guild, conf, csrf)
    )
    return {"title": "Autorole", "content": content}


def _render_stats(cog, guild, conf) -> str:
    state = "Aktiv" if conf["enabled"] else "Aus"
    gate = "Ja" if cog.gate_enabled(guild) else "Nein"
    return (
        "<div class='row g-3' style='margin-bottom:18px'>"
        f"<div class='col-6 col-lg-3'><div class='card-x'><div class='stat-label'>Status</div><div class='stat'>{state}</div></div></div>"
        f"<div class='col-6 col-lg-3'><div class='card-x'><div class='stat-label'>Mitglieder-Rollen</div><div class='stat'>{len(conf['join_roles'])}</div></div></div>"
        f"<div class='col-6 col-lg-3'><div class='card-x'><div class='stat-label'>Bot-Rollen</div><div class='stat'>{len(conf['bot_roles'])}</div></div></div>"
        f"<div class='col-6 col-lg-3'><div class='card-x'><div class='stat-label'>Regel-Verifizierung</div><div class='stat'>{gate}</div></div></div>"
        "</div>"
    )


def _render_warnings(cog, guild, conf) -> str:
    human = {
        "reason_default": "@everyone",
        "reason_managed": "von Discord verwaltet",
        "reason_too_high": "steht über meiner höchsten Rolle",
    }
    notes = []
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        notes.append("Mir fehlt die Berechtigung <b>Rollen verwalten</b> – ohne sie kann ich keine Rollen vergeben.")

    bad, seen = [], set()
    for rid in list(conf["join_roles"]) + list(conf["bot_roles"]) + list(conf["sticky_roles"]):
        if rid in seen:
            continue
        seen.add(rid)
        r = guild.get_role(int(rid))
        if r is None:
            continue
        reason = cog._assignable_reason(guild, r)
        if reason is not None:
            bad.append(f"{_esc(r.name)} ({human.get(reason, reason)})")
    if bad:
        notes.append(
            "Diese eingetragenen Rollen kann ich aktuell <b>nicht</b> vergeben (im Auswahlfeld mit ⚠ markiert): "
            + ", ".join(bad)
            + ". Verschiebe meine Bot-Rolle in den Servereinstellungen weiter nach oben oder wähle andere Rollen."
        )

    if not notes:
        return ""
    items = "".join(f"<li style='margin-bottom:6px'>{n}</li>" for n in notes)
    return (
        "<div class='card-x ar-warn' style='margin-bottom:18px'>"
        "<div class='ar-section-title'>Hinweise</div>"
        f"<ul style='margin:0;padding-left:18px;color:var(--text)'>{items}</ul>"
        "</div>"
    )


def _render_settings(cog, guild, conf, csrf) -> str:
    lang_opts = "".join(
        f"<option value='{code}'{' selected' if conf['language'] == code else ''}>{_esc(name)}</option>"
        for code, name in LANGUAGES.items()
    )
    scr = conf["screening"]
    scr_opts = "".join(
        f"<option value='{code}'{' selected' if scr == code else ''}>{_esc(label)}</option>"
        for code, label in (
            ("auto", "Automatisch – Verifizierung erkennen"),
            ("on", "Erst nach der Regel-Verifizierung"),
            ("off", "Sofort beim Beitritt"),
        )
    )
    return f"""
    <div class='card-x'>
      <div class='ar-section-title'>Einstellungen</div>
      <form class='ar-form' method='post' action='/cogs/autorole'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='settings'>
        <input type='hidden' name='guild' value='{guild.id}'>

        <div class='ar-check' style='margin-top:0'>
          <input type='checkbox' name='enabled' id='ar-enabled' {'checked' if conf['enabled'] else ''}>
          <span>Automatische Rollenvergabe aktiv</span>
        </div>

        <div class='row2'>
          <div>
            <label>Sprache der Bot-Antworten</label>
            <select name='language'>{lang_opts}</select>
          </div>
          <div>
            <label>Vergabe-Zeitpunkt</label>
            <select name='screening'>{scr_opts}</select>
            <div class='hint'>„Erst nach der Regel-Verifizierung“ wirkt nur, wenn dieser Server Discords Screening nutzt.</div>
          </div>
        </div>

        <div class='row2'>
          <div>
            <label>Verzögerung (Sekunden)</label>
            <input name='delay' type='number' min='0' max='3600' value='{int(conf['delay'])}'>
            <div class='hint'>Wartezeit nach dem Beitritt vor der Vergabe (0 = sofort).</div>
          </div>
          <div>
            <label>Mindest-Kontoalter (Stunden)</label>
            <input name='min_account_age' type='number' min='0' value='{int(conf['min_account_age'])}'>
            <div class='hint'>Jüngere Konten erhalten keine Auto-Rollen (0 = aus). Schutz gegen Wegwerf-/Raid-Accounts.</div>
          </div>
        </div>

        <label>Rollen für neue <b>Mitglieder</b></label>
        <select name='join_roles' multiple>{_role_options(cog, guild, conf['join_roles'])}</select>
        <div class='hint'>Mehrfachauswahl mit Strg/Cmd bzw. langem Tippen. Mit ⚠ markierte Rollen kann ich aktuell nicht vergeben.</div>

        <label>Rollen für neue <b>Bots</b></label>
        <select name='bot_roles' multiple>{_role_options(cog, guild, conf['bot_roles'])}</select>
        <div class='hint'>Werden vergeben, sobald ein Bot dem Server hinzugefügt wird (ohne Verifizierung).</div>

        <label><b>Sticky</b>-Rollen (kommen beim erneuten Beitritt zurück)</label>
        <select name='sticky_roles' multiple>{_role_options(cog, guild, conf['sticky_roles'])}</select>
        <div class='hint'>Diese Rollen merkt sich der Bot beim Verlassen und vergibt sie beim erneuten Beitritt wieder. <b>Keine</b> Mute-/Straf-Rolle hier eintragen.</div>

        <div class='ar-spacer'></div>
        <button class='btn-accent' type='submit'>Speichern</button>
      </form>
    </div>
    """


def _render_apply(guild, conf, csrf) -> str:
    ready = bool(conf["enabled"] and conf["join_roles"])
    disabled = "" if ready else "disabled"
    note = (
        ""
        if ready
        else "<div class='hint'>Aktiviere das System und trage Mitglieder-Rollen ein, um diese Aktion zu nutzen.</div>"
    )
    return f"""
    <div class='card-x'>
      <div class='ar-section-title'>Auf bestehende Mitglieder anwenden</div>
      <p style='color:var(--muted);margin:0 0 12px'>Vergibt die eingetragenen <b>Mitglieder-Rollen</b> nachträglich an alle Menschen auf dem Server, die sie noch nicht haben. Auf großen Servern kann das einen Moment dauern.</p>
      <form method='post' action='/cogs/autorole' onsubmit="return confirm('Mitglieder-Rollen an alle bestehenden Mitglieder vergeben?')">
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='applyall'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <button class='btn-accent' type='submit' {disabled}>Jetzt anwenden</button>
        {note}
      </form>
    </div>
    """


# --------------------------------------------------------------------------- #
#  Rollen-Panels (Übersicht + Editor)
# --------------------------------------------------------------------------- #
_BTN_COLORS = (("secondary", "Grau"), ("primary", "Blau"), ("success", "Grün"), ("danger", "Rot"))


def _text_channel_options(guild, selected_id) -> str:
    sel = str(selected_id) if selected_id else ""
    out = [f"<option value=''{'' if sel else ' selected'}>— Kanal wählen —</option>"]
    for c in sorted(getattr(guild, "text_channels", []), key=lambda c: c.position):
        is_sel = " selected" if str(c.id) == sel else ""
        out.append(f"<option value='{c.id}'{is_sel}>#{_esc(c.name)}</option>")
    return "".join(out)


def _addable_role_options(cog, guild, existing_ids) -> str:
    out = ["<option value=''>— Rolle wählen —</option>"]
    for r in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if r.is_default() or r.id in existing_ids:
            continue
        if cog._assignable_reason(guild, r) is not None:
            continue
        out.append(f"<option value='{r.id}'>{_esc(r.name)}</option>")
    return "".join(out)


def _btn_color_options(selected) -> str:
    return "".join(
        f"<option value='{v}'{' selected' if selected == v else ''}>{lbl}</option>"
        for v, lbl in _BTN_COLORS
    )


def _render_panels(cog, guild, conf, csrf) -> str:
    panels = conf.get("panels", {})
    rows = ""
    for pid, p in panels.items():
        ch = guild.get_channel(int(p["channel_id"])) if p.get("channel_id") else None
        chname = f"#{_esc(ch.name)}" if ch is not None else "<span style='color:var(--muted)'>—</span>"
        style = "Buttons" if p.get("style") == "buttons" else "Dropdown"
        mode = "Toggle" if p.get("mode") == "toggle" else "Nur vergeben"
        if p.get("unique"):
            mode += " · nur eine"
        status = (
            "<span style='color:var(--accent)'>● gepostet</span>"
            if p.get("message_id")
            else "<span style='color:var(--muted)'>○ nicht gepostet</span>"
        )
        edit_btn = (
            f"<a class='btn-accent' style='padding:5px 10px;font-size:.82rem;text-decoration:none' "
            f"href='/cogs/autorole?guild={guild.id}&panel={_esc(pid)}'>Bearbeiten</a>"
        )
        post_btn = (
            f"<form method='post' action='/cogs/autorole' style='display:inline;margin-left:6px'>"
            f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
            f"<input type='hidden' name='form' value='panel_post'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='panel' value='{_esc(pid)}'>"
            f"<button class='btn-accent' type='submit' style='padding:5px 10px;font-size:.82rem'>Posten</button></form>"
        )
        rows += (
            f"<tr><td><b>{_esc(p['name'])}</b>"
            f"<div class='mono' style='color:var(--muted);font-size:.74rem'>{_esc(pid)}</div></td>"
            f"<td>{chname}</td><td>{style}</td><td>{mode}</td>"
            f"<td>{len(p.get('roles', []))}</td><td>{status}</td>"
            f"<td style='white-space:nowrap'>{edit_btn}{post_btn}</td></tr>"
        )
    if rows:
        table = (
            "<table class='table' style='margin-bottom:18px'><thead><tr>"
            "<th>Name</th><th>Kanal</th><th>Stil</th><th>Verhalten</th><th>Rollen</th><th>Status</th><th></th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        table = "<p style='color:var(--muted);margin:0 0 16px'>Noch keine Panels – erstelle unten dein erstes.</p>"

    create = (
        "<form class='ar-form' method='post' action='/cogs/autorole' "
        "style='display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap'>"
        f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
        "<input type='hidden' name='form' value='panel_create'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        "<div style='flex:1;min-width:220px'><label style='margin-top:0'>Neues Panel – Name</label>"
        "<input name='name' maxlength='100' placeholder='z. B. Farb-Rollen' required></div>"
        "<button class='btn-accent' type='submit'>Panel erstellen</button></form>"
    )
    return (
        "<div class='card-x'><div class='ar-section-title'>Rollen-Panels "
        f"<span style='color:var(--muted);font-weight:400;font-size:.9rem'>({len(panels)})</span></div>"
        "<p style='color:var(--muted);margin:0 0 14px'>Eine gepostete Nachricht mit Buttons oder einem Dropdown, "
        "über die sich Mitglieder selbst Rollen geben oder nehmen. Verhalten und Aussehen sind je Panel einstellbar; "
        "die Buttons funktionieren auch nach einem Neustart weiter.</p>"
        f"{table}{create}</div>"
    )


def _render_panel_editor(cog, guild, panel, csrf) -> str:
    pid = panel["id"]
    back = (
        f"<a href='/cogs/autorole?guild={guild.id}' "
        "style='color:var(--accent);text-decoration:none'>← Zurück zur Übersicht</a>"
    )
    style_opts = "".join(
        f"<option value='{v}'{' selected' if panel.get('style') == v else ''}>{lbl}</option>"
        for v, lbl in (("buttons", "Buttons"), ("select", "Dropdown (Select-Menü)"))
    )
    mode_opts = "".join(
        f"<option value='{v}'{' selected' if panel.get('mode') == v else ''}>{lbl}</option>"
        for v, lbl in (("toggle", "Toggle – Klick gibt/entfernt"), ("add", "Nur vergeben (kein Entfernen)"))
    )
    props = f"""
    <div class='card-x'>
      <div class='ar-section-title'>Eigenschaften</div>
      <form class='ar-form' method='post' action='/cogs/autorole'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='panel_save'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <input type='hidden' name='panel' value='{_esc(pid)}'>
        <div class='row2'>
          <div><label style='margin-top:0'>Name</label>
            <input name='name' maxlength='100' value='{_esc(panel.get("name"))}'></div>
          <div><label style='margin-top:0'>Kanal</label>
            <select name='channel_id'>{_text_channel_options(guild, panel.get("channel_id"))}</select></div>
        </div>
        <div class='row2'>
          <div><label>Darstellung</label><select name='style'>{style_opts}</select></div>
          <div><label>Klick-Verhalten</label><select name='mode'>{mode_opts}</select></div>
        </div>
        <div class='ar-check'>
          <input type='checkbox' name='unique' id='ar-uniq' {'checked' if panel.get('unique') else ''}>
          <span>Nur <b>eine</b> Rolle aus diesem Panel gleichzeitig (z. B. Farb-Rollen)</span>
        </div>
        <div class='ar-check'>
          <input type='checkbox' name='use_embed' id='ar-embed' {'checked' if panel.get('use_embed') else ''}>
          <span>Als Embed posten (mit Titel &amp; Farbe)</span>
        </div>
        <div class='row2'>
          <div><label>Titel</label><input name='title' maxlength='256' value='{_esc(panel.get("title"))}'></div>
          <div><label>Embed-Farbe (Hex)</label>
            <input name='color' maxlength='7' placeholder='#3ddc97' value='{_esc(panel.get("color"))}'></div>
        </div>
        <label>Text</label>
        <textarea name='text' rows='3'>{_esc(panel.get("text"))}</textarea>
        <div class='ar-spacer'></div>
        <button class='btn-accent' type='submit'>Eigenschaften speichern</button>
      </form>
    </div>
    """

    role_rows = ""
    for r in panel.get("roles", []):
        role = guild.get_role(int(r["role_id"]))
        if role is None:
            rname = f"<i style='color:var(--danger)'>Unbekannt ({_esc(r['role_id'])})</i>"
        else:
            warn = " ⚠" if cog._assignable_reason(guild, role) is not None else ""
            rname = f"{_esc(role.name)}{warn}"
        role_rows += f"""
        <tr>
          <td style='min-width:110px'><b>{rname}</b></td>
          <td>
            <form method='post' action='/cogs/autorole'
              style='display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:0'>
              <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
              <input type='hidden' name='form' value='panel_role_update'>
              <input type='hidden' name='guild' value='{guild.id}'>
              <input type='hidden' name='panel' value='{_esc(pid)}'>
              <input type='hidden' name='role_id' value='{_esc(r["role_id"])}'>
              <input name='label' maxlength='80' placeholder='Label'
                value='{_esc(r.get("label"))}' style='width:130px'>
              <input name='emoji' maxlength='64' placeholder='Emoji'
                value='{_esc(r.get("emoji"))}' style='width:80px'>
              <select name='style' style='width:90px'>{_btn_color_options(r.get("style"))}</select>
              <input name='description' maxlength='100' placeholder='Beschreibung (Dropdown)'
                value='{_esc(r.get("description"))}' style='width:190px'>
              <button class='btn-accent' type='submit' style='padding:6px 10px;font-size:.82rem'>Speichern</button>
            </form>
          </td>
          <td>
            <form method='post' action='/cogs/autorole' style='margin:0'>
              <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
              <input type='hidden' name='form' value='panel_role_remove'>
              <input type='hidden' name='guild' value='{guild.id}'>
              <input type='hidden' name='panel' value='{_esc(pid)}'>
              <input type='hidden' name='role_id' value='{_esc(r["role_id"])}'>
              <button type='submit' style='background:transparent;border:1px solid var(--danger);
                color:var(--danger);border-radius:8px;padding:6px 10px;font-size:.82rem;cursor:pointer'>Entfernen</button>
            </form>
          </td>
        </tr>
        """
    if role_rows:
        roles_table = (
            "<table class='table'><thead><tr><th>Rolle</th><th>Anzeige</th><th></th></tr></thead>"
            f"<tbody>{role_rows}</tbody></table>"
        )
    else:
        roles_table = "<p style='color:var(--muted);margin:0 0 8px'>Noch keine Rollen in diesem Panel.</p>"

    existing_ids = {int(r["role_id"]) for r in panel.get("roles", [])}
    add_role = f"""
    <form class='ar-form' method='post' action='/cogs/autorole' style='margin-top:14px'>
      <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
      <input type='hidden' name='form' value='panel_role_add'>
      <input type='hidden' name='guild' value='{guild.id}'>
      <input type='hidden' name='panel' value='{_esc(pid)}'>
      <div class='row2'>
        <div><label style='margin-top:0'>Rolle hinzufügen</label>
          <select name='role_id'>{_addable_role_options(cog, guild, existing_ids)}</select></div>
        <div><label style='margin-top:0'>Label (optional)</label>
          <input name='label' maxlength='80' placeholder='Standard: Rollenname'></div>
      </div>
      <div class='row2'>
        <div><label>Emoji (optional)</label>
          <input name='emoji' maxlength='64' placeholder='🎮 oder &lt;:name:id&gt;'></div>
        <div><label>Button-Farbe</label><select name='style'>{_btn_color_options("secondary")}</select></div>
      </div>
      <div class='ar-spacer'></div>
      <button class='btn-accent' type='submit'>Rolle hinzufügen</button>
      <div class='hint'>Max. {MAX_ROLES} Rollen pro Panel. Mit ⚠ markierte Rollen kann ich aktuell nicht vergeben.</div>
    </form>
    """
    roles_card = f"<div class='card-x'><div class='ar-section-title'>Rollen</div>{roles_table}{add_role}</div>"

    posted = bool(panel.get("message_id"))
    actions = f"""
    <div class='card-x'>
      <div class='ar-section-title'>Aktionen</div>
      <div style='display:flex;gap:10px;flex-wrap:wrap'>
        <form method='post' action='/cogs/autorole' style='margin:0'>
          <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
          <input type='hidden' name='form' value='panel_post'>
          <input type='hidden' name='guild' value='{guild.id}'>
          <input type='hidden' name='panel' value='{_esc(pid)}'>
          <button class='btn-accent' type='submit'>{'Nachricht aktualisieren' if posted else 'Jetzt posten'}</button>
        </form>
        <form method='post' action='/cogs/autorole' style='margin:0'
          onsubmit="return confirm('Panel wirklich löschen? Die gepostete Nachricht wird ebenfalls entfernt.')">
          <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
          <input type='hidden' name='form' value='panel_delete'>
          <input type='hidden' name='guild' value='{guild.id}'>
          <input type='hidden' name='panel' value='{_esc(pid)}'>
          <button type='submit' style='background:transparent;border:1px solid var(--danger);
            color:var(--danger);border-radius:9px;padding:9px 16px;cursor:pointer'>Panel löschen</button>
        </form>
      </div>
      <div class='hint' style='margin-top:10px'>{
        'Gepostet – Änderungen an Eigenschaften und Rollen werden automatisch in die Nachricht übernommen.'
        if posted else
        'Noch nicht gepostet. Wähle oben einen Kanal, speichere die Eigenschaften und klicke dann „Jetzt posten".'
      }</div>
    </div>
    """
    return (
        back
        + "<div style='height:14px'></div>"
        + props
        + "<div class='ar-spacer'></div>"
        + roles_card
        + "<div class='ar-spacer'></div>"
        + actions
    )


# --------------------------------------------------------------------------- #
#  Speichern / Aktion (POST)
# --------------------------------------------------------------------------- #
def _panel_redirect(guild_id, pid=None, ok=""):
    url = f"/cogs/autorole?guild={guild_id}"
    if pid:
        url += f"&panel={quote_plus(str(pid))}"
    if ok:
        url += f"&ok={quote_plus(ok)}"
    return web.HTTPFound(url)


_POST_MSG = {
    "panel_posted": "Panel gepostet bzw. aktualisiert",
    "panel_post_no_channel": "Kein gültiger Kanal gesetzt",
    "panel_post_no_roles": "Das Panel hat noch keine Rollen",
    "panel_post_no_send": "Mir fehlen Senderechte im Zielkanal",
    "panel_post_failed": "Posten fehlgeschlagen",
}


async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guild = cog.bot.get_guild(int(gid)) if gid and gid.isdigit() else None
    if guild is None:
        raise web.HTTPFound("/cogs/autorole?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        lang = data.get("language") or "de"
        await gconf.language.set(lang if lang in LANGUAGES else "de")
        scr = data.get("screening") or "auto"
        await gconf.screening.set(scr if scr in ("auto", "on", "off") else "auto")
        await gconf.enabled.set("enabled" in data)
        try:
            delay = int(data.get("delay", 0))
        except (TypeError, ValueError):
            delay = 0
        await gconf.delay.set(max(0, min(3600, delay)))
        try:
            age = int(data.get("min_account_age", 0))
        except (TypeError, ValueError):
            age = 0
        await gconf.min_account_age.set(max(0, age))
        await gconf.join_roles.set(_ids(data.getall("join_roles", [])))
        await gconf.bot_roles.set(_ids(data.getall("bot_roles", [])))
        await gconf.sticky_roles.set(_ids(data.getall("sticky_roles", [])))
        raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}&ok=Einstellungen+gespeichert")

    if form == "applyall":
        result = await cog.apply_to_existing(guild)
        if result is None:
            raise web.HTTPFound(
                f"/cogs/autorole?guild={guild.id}&ok=Nichts+anzuwenden+%28System+aus%2C+keine+Rollen+oder+keine+Rechte%29"
            )
        added, members = result
        raise web.HTTPFound(
            f"/cogs/autorole?guild={guild.id}&ok={added}+Rollen-Vergaben+an+{members}+Mitglieder"
        )

    # ---- Rollen-Panels ----
    if form == "panel_create":
        name = (data.get("name") or "").strip()[:100] or "Panel"
        panel = new_panel(name)
        async with gconf.panels() as panels:
            panels[panel["id"]] = panel
        raise _panel_redirect(guild.id, panel["id"], "Panel erstellt")

    if form == "panel_save":
        pid = data.get("panel")
        panels = await gconf.panels()
        if not pid or pid not in panels:
            raise _panel_redirect(guild.id, ok="Panel nicht gefunden")
        style = data.get("style")
        mode = data.get("mode")
        ch = data.get("channel_id")
        async with gconf.panels() as panels:
            p = panels[pid]
            p["name"] = (data.get("name") or p["name"]).strip()[:100] or "Panel"
            p["channel_id"] = int(ch) if ch and ch.isdigit() else None
            p["style"] = style if style in STYLES else "buttons"
            p["mode"] = mode if mode in MODES else "toggle"
            p["unique"] = "unique" in data
            p["use_embed"] = "use_embed" in data
            p["title"] = (data.get("title") or "")[:256]
            p["color"] = (data.get("color") or "").strip()[:7]
            p["text"] = (data.get("text") or "")[:2000]
        await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid, "Eigenschaften gespeichert")

    if form == "panel_role_add":
        pid = data.get("panel")
        rid = data.get("role_id")
        panels = await gconf.panels()
        if not pid or pid not in panels:
            raise _panel_redirect(guild.id, ok="Panel nicht gefunden")
        role = guild.get_role(int(rid)) if rid and rid.isdigit() else None
        if role is None:
            raise _panel_redirect(guild.id, pid, "Rolle nicht gefunden")
        if cog._assignable_reason(guild, role) is not None:
            raise _panel_redirect(guild.id, pid, "Diese Rolle kann ich nicht vergeben")
        existing = panels[pid].get("roles", [])
        if any(int(r["role_id"]) == role.id for r in existing):
            raise _panel_redirect(guild.id, pid, "Rolle ist bereits im Panel")
        if len(existing) >= MAX_ROLES:
            raise _panel_redirect(guild.id, pid, f"Panel voll (max. {MAX_ROLES})")
        label = (data.get("label") or role.name).strip()[:80] or role.name[:80]
        emoji = (data.get("emoji") or "").strip()[:64]
        bstyle = data.get("style")
        bstyle = bstyle if bstyle in ("primary", "secondary", "success", "danger") else "secondary"
        async with gconf.panels() as panels:
            panels[pid]["roles"].append(
                {"role_id": role.id, "label": label, "emoji": emoji, "style": bstyle, "description": ""}
            )
        await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid, "Rolle hinzugefügt")

    if form == "panel_role_update":
        pid = data.get("panel")
        rid = data.get("role_id")
        panels = await gconf.panels()
        if not pid or pid not in panels or not (rid and rid.isdigit()):
            raise _panel_redirect(guild.id, pid or None, "Nicht gefunden")
        bstyle = data.get("style")
        bstyle = bstyle if bstyle in ("primary", "secondary", "success", "danger") else "secondary"
        async with gconf.panels() as panels:
            for r in panels[pid]["roles"]:
                if int(r["role_id"]) == int(rid):
                    r["label"] = (data.get("label") or "").strip()[:80]
                    r["emoji"] = (data.get("emoji") or "").strip()[:64]
                    r["style"] = bstyle
                    r["description"] = (data.get("description") or "").strip()[:100]
                    break
        await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid, "Rolle aktualisiert")

    if form == "panel_role_remove":
        pid = data.get("panel")
        rid = data.get("role_id")
        panels = await gconf.panels()
        if pid and pid in panels and rid and rid.isdigit():
            async with gconf.panels() as panels:
                panels[pid]["roles"] = [
                    r for r in panels[pid]["roles"] if int(r["role_id"]) != int(rid)
                ]
            await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid or None, "Rolle entfernt")

    if form == "panel_post":
        pid = data.get("panel")
        panel = await cog._get_panel(guild, pid) if pid else None
        if panel is None:
            raise _panel_redirect(guild.id, ok="Panel nicht gefunden")
        ok, key = await cog._panel_post(guild, panel)
        raise _panel_redirect(guild.id, pid, _POST_MSG.get(key, "OK"))

    if form == "panel_delete":
        pid = data.get("panel")
        panel = await cog._get_panel(guild, pid) if pid else None
        if panel is not None:
            await cog._panel_delete_message(guild, panel)
            async with gconf.panels() as panels:
                panels.pop(pid, None)
        raise _panel_redirect(guild.id, ok="Panel gelöscht")

    raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}")
