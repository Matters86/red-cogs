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

from aiohttp import web

from .strings import LANGUAGES

# Auf die Theme-Variablen abgestimmter Style nur für die Formularfelder.
_FORM_STYLE = """
<style>
  .ar-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .ar-form input,.ar-form select{width:100%;background:var(--panel-2);color:var(--text);
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
#  Speichern / Aktion (POST)
# --------------------------------------------------------------------------- #
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

    raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}")
