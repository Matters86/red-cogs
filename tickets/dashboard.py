"""WebCore-Dashboard für den Tickets-Cog.

Drei Aufgaben:
* GET  -> Einstellungs-Seite (Settings, Panels, Transcripts, Statistik) rendern
* POST -> Formular speichern, danach Redirect (Post/Redirect/Get)
* GET ?transcript=<num> -> gespeichertes Transcript als eigene Seite ausliefern

Es werden nur die Theme-Klassen (card-x, table, stat, …) plus die ohnehin im
Theme geladenen Bootstrap-Formularklassen genutzt – kein eigenes Design.
"""

from __future__ import annotations

import html
import uuid

from aiohttp import web

from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS, t

# Kleiner, auf die Theme-Variablen abgestimmter Style nur für Formularfelder.
_FORM_STYLE = """
<style>
  .tk-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .tk-form input,.tk-form select,.tk-form textarea{width:100%;
    background:var(--panel-2);color:var(--text);border:1px solid var(--border);
    border-radius:9px;padding:9px 11px;font-family:inherit;font-size:.92rem}
  .tk-form textarea{min-height:78px;resize:vertical;font-family:"IBM Plex Mono",monospace}
  .tk-form select[multiple]{min-height:120px}
  .tk-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .tk-form .hint{color:var(--muted);font-size:.78rem;margin-top:4px}
  .tk-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .tk-check input{width:auto}
  .tk-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .tk-section-title{font-family:"Archivo",sans-serif;font-weight:700;
    font-size:1.15rem;margin:0 0 14px}
  .tk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px}
  .tk-spacer{height:26px}
</style>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _options(items, selected_ids, *, none_label: str | None = None) -> str:
    """``items``: Liste von (id, label). ``selected_ids``: Menge/Container von ids."""
    sel = {str(s) for s in (selected_ids or [])}
    out = []
    if none_label is not None:
        chosen = "" if not sel else None
        is_sel = " selected" if not sel else ""
        out.append(f"<option value=''{is_sel}>{_esc(none_label)}</option>")
    for ident, label in items:
        is_sel = " selected" if str(ident) in sel else ""
        out.append(f"<option value='{_esc(ident)}'{is_sel}>{_esc(label)}</option>")
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Einstiegspunkt
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    if request.query.get("transcript"):
        return await _serve_transcript(cog, request)
    return await _render(cog, request)


def _selected_guild(cog, request):
    gid = request.query.get("guild")
    if gid:
        g = cog.bot.get_guild(int(gid)) if gid.isdigit() else None
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
        return {"title": "Tickets", "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

    conf = await cog.config.guild(guild).all()

    # Auswahllisten
    guild_opts = _options(
        [(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())],
        [guild.id],
    )
    role_items = [(r.id, r.name) for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()]
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    cat_items = [(c.id, c.name) for c in guild.categories]
    forum_items = [(c.id, f"#{c.name}") for c in getattr(guild, "forums", [])]

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='tk-flash'>{_esc(request.query.get('ok'))}</div>"

    lang_opts = "".join(
        f"<option value='{code}'{' selected' if conf['language'] == code else ''}>{_esc(name)}</option>"
        for code, name in LANGUAGES.items()
    )

    def type_sel(value):
        return " selected" if conf["ticket_type"] == value else ""

    overrides = conf.get("messages") or {}
    override_fields = ""
    for key in OVERRIDABLE_KEYS:
        current = overrides.get(key, "")
        default = STRINGS["de"].get(key, "")
        override_fields += (
            f"<label>{_esc(key)}</label>"
            f"<input name='ovr_{key}' value='{_esc(current)}' placeholder='{_esc(default)}'>"
        )

    settings_form = f"""
    <div class='card-x'>
      <div class='tk-section-title'>Einstellungen</div>
      <form class='tk-form' method='post' action='/cogs/tickets'>
        <input type='hidden' name='form' value='settings'>
        <input type='hidden' name='guild' value='{guild.id}'>

        <div class='row2'>
          <div>
            <label>Sprache</label>
            <select name='language'>{lang_opts}</select>
          </div>
          <div>
            <label>Ticket-Typ</label>
            <select name='ticket_type'>
              <option value='category'{type_sel('category')}>Kategorie (eigener Kanal)</option>
              <option value='thread'{type_sel('thread')}>Privater Thread</option>
              <option value='forum'{type_sel('forum')}>Forum-Beitrag</option>
            </select>
          </div>
        </div>

        <label>Support-Rollen (mitlesen &amp; übernehmen)</label>
        <select name='support_roles' multiple>{_options(role_items, conf['support_roles'])}</select>

        <label>Admin-Rollen (volle Rechte)</label>
        <select name='admin_roles' multiple>{_options(role_items, conf['admin_roles'])}</select>

        <label>View-Rollen (nur lesen, v. a. im Kategorie-Modus)</label>
        <select name='view_roles' multiple>{_options(role_items, conf['view_roles'])}</select>

        <div class='row2'>
          <div>
            <label>Ping-Rollen (Benachrichtigung beim Öffnen)</label>
            <select name='ping_roles' multiple>{_options(role_items, conf['ping_roles'])}</select>
          </div>
          <div>
            <label>Inhaber-Rolle (automatisch an Ersteller)</label>
            <select name='owner_role'>{_options(role_items, [conf['owner_role']] if conf['owner_role'] else [], none_label='— keine —')}</select>
          </div>
        </div>

        <div class='row2'>
          <div>
            <label>Kategorie für offene Tickets</label>
            <select name='category_open'>{_options(cat_items, [conf['category_open']] if conf['category_open'] else [], none_label='— keine —')}</select>
          </div>
          <div>
            <label>Kategorie für geschlossene Tickets</label>
            <select name='category_close'>{_options(cat_items, [conf['category_close']] if conf['category_close'] else [], none_label='— keine —')}</select>
          </div>
        </div>

        <div class='row2'>
          <div>
            <label>Basis-Kanal (Thread-Modus)</label>
            <select name='thread_base'>{_options(text_items, [conf['thread_base']] if conf['thread_base'] else [], none_label='— keiner —')}</select>
          </div>
          <div>
            <label>Forum-Kanal (Forum-Modus)</label>
            <select name='forum_channel'>{_options(forum_items, [conf['forum_channel']] if conf['forum_channel'] else [], none_label='— keiner —')}</select>
          </div>
        </div>

        <div class='row2'>
          <div>
            <label>Log-Kanal</label>
            <select name='log_channel'>{_options(text_items, [conf['log_channel']] if conf['log_channel'] else [], none_label='— keiner —')}</select>
          </div>
          <div>
            <label>Max. offene Tickets pro Nutzer</label>
            <input name='max_open' type='number' min='1' value='{int(conf['max_open'])}'>
          </div>
        </div>

        <label>Kanalname-Vorlage</label>
        <input name='name_template' value='{_esc(conf['name_template'])}'>
        <div class='hint'>Platzhalter: <code>{{num}}</code> (Ticketnummer), <code>{{user}}</code> (Name).</div>

        <div class='tk-check'><input type='checkbox' name='close_confirmation' {'checked' if conf['close_confirmation'] else ''}><span>Vor dem Schließen bestätigen</span></div>
        <div class='tk-check'><input type='checkbox' name='user_can_close' {'checked' if conf['user_can_close'] else ''}><span>Ersteller darf eigenes Ticket schließen</span></div>
        <div class='tk-check'><input type='checkbox' name='delete_on_close' {'checked' if conf['delete_on_close'] else ''}><span>Beim Schließen direkt löschen (statt archivieren)</span></div>

        <div class='tk-spacer'></div>
        <div class='tk-section-title'>Eigene Texte (überschreiben die Sprachpakete)</div>
        {override_fields}
        <div class='hint'>Leer = Standardtext der gewählten Sprache (im Feld als Platzhalter sichtbar).</div>

        <div class='tk-spacer'></div>
        <button class='btn-accent' type='submit'>Speichern</button>
      </form>
    </div>
    """

    panels_html = _render_panels(guild, conf, role_items, text_items)
    transcripts_html = _render_transcripts(guild, conf)
    stats_html = await _render_stats(cog, guild, conf)

    guild_picker = f"""
    <div class='card-x' style='margin-bottom:20px'>
      <form method='get' action='/cogs/tickets' class='tk-form' style='margin:0'>
        <label style='margin-top:0'>Server</label>
        <select name='guild' onchange='this.form.submit()'>{guild_opts}</select>
      </form>
    </div>
    """

    content = (
        _FORM_STYLE
        + flash
        + guild_picker
        + settings_form
        + "<div class='tk-spacer'></div>"
        + panels_html
        + "<div class='tk-spacer'></div>"
        + stats_html
        + "<div class='tk-spacer'></div>"
        + transcripts_html
    )
    return {"title": "Tickets", "content": content}


def _render_panels(guild, conf, role_items, text_items) -> str:
    rows = []
    for p in conf.get("panels", []):
        ch = guild.get_channel(p.get("channel_id")) if p.get("channel_id") else None
        ch_name = f"#{ch.name}" if ch else "—"
        n_reasons = len(p.get("reasons") or [])
        n_q = len(p.get("modal_questions") or [])
        rows.append(
            "<tr>"
            f"<td>{_esc(p.get('title') or '—')}</td>"
            f"<td>{_esc(ch_name)}</td>"
            f"<td>{_esc(p.get('mode'))}</td>"
            f"<td class='mono'>{n_reasons}</td>"
            f"<td class='mono'>{n_q}</td>"
            "<td>"
            f"<form method='post' action='/cogs/tickets' onsubmit=\"return confirm('Panel löschen?')\">"
            f"<input type='hidden' name='form' value='panel_delete'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='panel_id' value='{_esc(p.get('id'))}'>"
            "<button class='btn-accent' style='padding:5px 12px'>Löschen</button>"
            "</form></td>"
            "</tr>"
        )
    table = (
        "<table class='table'><thead><tr>"
        "<th>Titel</th><th>Kanal</th><th>Modus</th><th>Gründe</th><th>Fragen</th><th></th>"
        "</tr></thead><tbody>"
        + ("".join(rows) or "<tr><td colspan='6' style='color:var(--muted)'>Noch keine Panels.</td></tr>")
        + "</tbody></table>"
    )

    create = f"""
      <div class='tk-spacer'></div>
      <div class='tk-section-title' style='font-size:1rem'>Neues Panel</div>
      <form class='tk-form' method='post' action='/cogs/tickets'>
        <input type='hidden' name='form' value='panel_create'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <div class='row2'>
          <div><label>Kanal (wo das Panel gepostet wird)</label>
            <select name='channel_id'>{_options(text_items, [])}</select></div>
          <div><label>Modus</label>
            <select name='mode'><option value='button'>Buttons</option><option value='dropdown'>Dropdown</option></select></div>
        </div>
        <label>Titel</label><input name='title' value='Support-Ticket'>
        <label>Beschreibung</label><textarea name='description'>Klicke unten, um ein Ticket zu öffnen.</textarea>
        <label>Gründe (eine Zeile je Grund)</label>
        <textarea name='reasons' placeholder='Allgemein | 🎫 | Allgemeine Fragen&#10;Bug melden | 🐞 |'></textarea>
        <div class='hint'>Format: <code>Label | Emoji | Beschreibung</code> (Emoji/Beschreibung optional). Leer lassen = ein einzelner „Ticket öffnen“-Button.</div>
        <label>Modal-Fragen (max. 5, eine je Zeile)</label>
        <textarea name='questions' placeholder='Worum geht es? | Kurz beschreiben | ja | lang'></textarea>
        <div class='hint'>Format: <code>Label | Platzhalter | pflicht(ja/nein) | lang(ja/nein)</code>.</div>
        <div class='tk-spacer'></div>
        <button class='btn-accent' type='submit'>Panel erstellen &amp; posten</button>
      </form>
    """

    return f"<div class='card-x'><div class='tk-section-title'>Panels</div>{table}{create}</div>"


def _render_transcripts(guild, conf) -> str:
    items = list(reversed(conf.get("transcripts", [])))[:100]
    rows = []
    for tr in items:
        link = f"/cogs/tickets?guild={guild.id}&transcript={_esc(tr.get('num'))}"
        rows.append(
            "<tr>"
            f"<td class='mono'>#{_esc(tr.get('num'))}</td>"
            f"<td>{_esc(tr.get('channel_name'))}</td>"
            f"<td>{_esc(tr.get('owner'))}</td>"
            f"<td>{_esc(tr.get('reason') or '—')}</td>"
            f"<td>{_esc(tr.get('closed') or '—')}</td>"
            f"<td><a class='btn-accent' style='padding:5px 12px' href='{link}' target='_blank'>Öffnen</a></td>"
            "</tr>"
        )
    table = (
        "<table class='table'><thead><tr>"
        "<th>#</th><th>Kanal</th><th>Inhaber</th><th>Grund</th><th>Geschlossen</th><th></th>"
        "</tr></thead><tbody>"
        + ("".join(rows) or "<tr><td colspan='6' style='color:var(--muted)'>Noch keine Transcripts.</td></tr>")
        + "</tbody></table>"
    )
    return f"<div class='card-x'><div class='tk-section-title'>Transcripts</div>{table}</div>"


async def _render_stats(cog, guild, conf) -> str:
    stats = conf.get("stats") or {}
    tickets = conf.get("tickets") or {}
    open_now = sum(1 for r in tickets.values() if r.get("status") == "open")
    opened = int(stats.get("opened", 0))
    closed = int(stats.get("closed", 0))
    dur_sum = int(stats.get("duration_sum", 0))
    avg = dur_sum // closed if closed else 0
    avg_str = _fmt_duration(avg)

    claims = stats.get("claims") or {}
    claim_rows = []
    for uid, count in sorted(claims.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        member = guild.get_member(int(uid)) if str(uid).isdigit() else None
        name = member.display_name if member else f"ID {uid}"
        claim_rows.append(f"<tr><td>{_esc(name)}</td><td class='mono'>{int(count)}</td></tr>")
    claim_table = (
        "<table class='table'><thead><tr><th>Support-Mitglied</th><th>Übernahmen</th></tr></thead><tbody>"
        + ("".join(claim_rows) or "<tr><td colspan='2' style='color:var(--muted)'>Noch keine.</td></tr>")
        + "</tbody></table>"
    )

    cards = (
        "<div class='tk-grid'>"
        f"<div><div class='stat-label'>Offen</div><div class='stat'>{open_now}</div></div>"
        f"<div><div class='stat-label'>Geöffnet gesamt</div><div class='stat'>{opened}</div></div>"
        f"<div><div class='stat-label'>Geschlossen gesamt</div><div class='stat'>{closed}</div></div>"
        f"<div><div class='stat-label'>Ø Laufzeit</div><div class='stat'>{avg_str}</div></div>"
        "</div>"
    )
    return f"<div class='card-x'><div class='tk-section-title'>Statistik</div>{cards}<div class='tk-spacer'></div>{claim_table}</div>"


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
def _ids(values) -> list[int]:
    out = []
    for v in values:
        if v and str(v).isdigit():
            out.append(int(v))
    return out


def _one_id(value):
    return int(value) if value and str(value).isdigit() else None


async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guild = cog.bot.get_guild(int(gid)) if gid and gid.isdigit() else None
    if guild is None:
        raise web.HTTPFound("/cogs/tickets?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        await gconf.language.set(data.get("language") or "de")
        await gconf.ticket_type.set(data.get("ticket_type") or "category")
        await gconf.support_roles.set(_ids(data.getall("support_roles", [])))
        await gconf.admin_roles.set(_ids(data.getall("admin_roles", [])))
        await gconf.view_roles.set(_ids(data.getall("view_roles", [])))
        await gconf.ping_roles.set(_ids(data.getall("ping_roles", [])))
        await gconf.owner_role.set(_one_id(data.get("owner_role")))
        await gconf.category_open.set(_one_id(data.get("category_open")))
        await gconf.category_close.set(_one_id(data.get("category_close")))
        await gconf.thread_base.set(_one_id(data.get("thread_base")))
        await gconf.forum_channel.set(_one_id(data.get("forum_channel")))
        await gconf.log_channel.set(_one_id(data.get("log_channel")))
        try:
            await gconf.max_open.set(max(1, int(data.get("max_open", 1))))
        except (TypeError, ValueError):
            await gconf.max_open.set(1)
        await gconf.name_template.set((data.get("name_template") or "ticket-{num}").strip())
        await gconf.close_confirmation.set("close_confirmation" in data)
        await gconf.user_can_close.set("user_can_close" in data)
        await gconf.delete_on_close.set("delete_on_close" in data)

        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)
        raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok=Einstellungen+gespeichert")

    if form == "panel_create":
        panel = {
            "id": uuid.uuid4().hex[:8],
            "channel_id": _one_id(data.get("channel_id")),
            "message_id": None,
            "title": (data.get("title") or "Support-Ticket").strip(),
            "description": (data.get("description") or "").strip(),
            "mode": "dropdown" if data.get("mode") == "dropdown" else "button",
            "button_label": "🎟️ Ticket",
            "placeholder": "Grund auswählen …",
            "reasons": _parse_reasons(data.get("reasons", "")),
            "modal_questions": _parse_questions(data.get("questions", "")),
            "lang": None,
        }
        msg_id = await cog.post_panel(guild, panel)
        panel["message_id"] = msg_id
        async with gconf.panels() as panels:
            panels.append(panel)
        ok = "Panel+erstellt" if msg_id else "Panel+gespeichert+(Posten+fehlgeschlagen)"
        raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok={ok}")

    if form == "panel_delete":
        pid = data.get("panel_id")
        removed = None
        async with gconf.panels() as panels:
            for i, p in enumerate(panels):
                if p.get("id") == pid:
                    removed = panels.pop(i)
                    break
        if removed:
            await cog.delete_panel_message(guild, removed)
        raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok=Panel+gelöscht")

    raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}")


def _parse_reasons(raw: str) -> list[dict]:
    reasons = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0]
        if not label:
            continue
        reasons.append(
            {
                "id": uuid.uuid4().hex[:6],
                "label": label[:80],
                "emoji": (parts[1] if len(parts) > 1 and parts[1] else None),
                "description": (parts[2] if len(parts) > 2 and parts[2] else None),
            }
        )
    return reasons[:25]


def _parse_questions(raw: str) -> list[dict]:
    out = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0]
        if not label:
            continue
        required = True
        if len(parts) > 2 and parts[2].lower() in ("nein", "no", "false", "0"):
            required = False
        style = "long" if len(parts) > 3 and parts[3].lower() in ("lang", "long", "ja", "yes", "1") else "short"
        out.append(
            {
                "label": label[:45],
                "placeholder": (parts[1] if len(parts) > 1 and parts[1] else None),
                "required": required,
                "style": style,
            }
        )
    return out[:5]


# --------------------------------------------------------------------------- #
#  Transcript ausliefern
# --------------------------------------------------------------------------- #
async def _serve_transcript(cog, request):
    guild = _selected_guild(cog, request)
    num = request.query.get("transcript")
    if guild is None or not num:
        return web.Response(text="Nicht gefunden.", status=404)
    records = await cog.config.guild(guild).transcripts()
    record = next((r for r in records if str(r.get("num")) == str(num)), None)
    if not record:
        return web.Response(text="Transcript nicht gefunden.", status=404)
    path = cog.transcripts_dir / record.get("file", "")
    if not path.exists():
        return web.Response(text="Transcript-Datei fehlt.", status=404)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return web.Response(text="Transcript konnte nicht gelesen werden.", status=500)
    return web.Response(text=text, content_type="text/html")
