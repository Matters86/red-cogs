"""WebCore-Dashboard für den Sticky-Cog.

Aufgaben:
* GET  -> Seite rendern (Einstellungen, Sticky-Liste, Editor)
* POST -> Formular speichern, danach Redirect (Post/Redirect/Get)

Es werden nur die Theme-Klassen (card-x, table, stat, btn-accent …) plus die
ohnehin geladenen Bootstrap-Formularklassen genutzt – kein eigenes Design.
"""

from __future__ import annotations

import html

import discord
from aiohttp import web

from .strings import LANGUAGES

# Kleiner, auf die Theme-Variablen abgestimmter Style nur für Formularfelder.
_FORM_STYLE = """
<style>
  .st-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .st-form input,.st-form select,.st-form textarea{width:100%;
    background:var(--panel-2);color:var(--text);border:1px solid var(--border);
    border-radius:9px;padding:9px 11px;font-family:inherit;font-size:.92rem}
  .st-form textarea{min-height:90px;resize:vertical;font-family:"IBM Plex Mono",monospace}
  .st-form input[type=color]{height:42px;padding:4px;cursor:pointer}
  .st-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .st-form .hint{color:var(--muted);font-size:.78rem;margin-top:4px}
  .st-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .st-check input{width:auto}
  .st-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .st-section-title{font-family:"Archivo",sans-serif;font-weight:700;
    font-size:1.15rem;margin:0 0 14px}
  .st-spacer{height:26px}
  .st-actions{display:flex;gap:8px;flex-wrap:wrap}
  .st-actions form{margin:0}
  .st-btn-sm{padding:5px 12px}
</style>
<script>
  function stSyncEditor(){
    var mode = document.getElementById('st-mode');
    var hook = document.getElementById('st-webhook');
    var embedBox = document.getElementById('st-embed-fields');
    var hookBox = document.getElementById('st-webhook-fields');
    if(embedBox && mode){ embedBox.style.display = (mode.value === 'embed') ? 'block' : 'none'; }
    if(hookBox && hook){ hookBox.style.display = hook.checked ? 'block' : 'none'; }
  }
  document.addEventListener('DOMContentLoaded', stSyncEditor);
</script>
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
        return {"title": "Sticky", "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    stickies = conf.get("stickies", {})

    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='st-flash'>{_esc(request.query.get('ok'))}</div>"

    guild_opts = _options(
        [(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())],
        [guild.id],
    )
    guild_picker = f"""
    <div class='card-x' style='margin-bottom:20px'>
      <form method='get' action='/cogs/sticky' class='st-form' style='margin:0'>
        <label style='margin-top:0'>Server</label>
        <select name='guild' onchange='this.form.submit()'>{guild_opts}</select>
      </form>
    </div>
    """

    settings_form = _render_settings(guild, conf, csrf)
    table_html = _render_table(guild, stickies, csrf)
    editor_html = _render_editor(guild, stickies, text_items, csrf, request)

    content = (
        _FORM_STYLE
        + flash
        + guild_picker
        + settings_form
        + "<div class='st-spacer'></div>"
        + table_html
        + "<div class='st-spacer'></div>"
        + editor_html
    )
    return {"title": "Sticky", "content": content}


def _render_settings(guild, conf, csrf) -> str:
    lang_opts = "".join(
        f"<option value='{code}'{' selected' if conf['language'] == code else ''}>{_esc(name)}</option>"
        for code, name in LANGUAGES.items()
    )
    return f"""
    <div class='card-x'>
      <div class='st-section-title'>Einstellungen</div>
      <form class='st-form' method='post' action='/cogs/sticky'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='settings'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <div class='row2'>
          <div>
            <label>Sprache der Bot-Antworten</label>
            <select name='language'>{lang_opts}</select>
          </div>
          <div>
            <label>Cooldown (Sekunden)</label>
            <input name='cooldown' type='number' min='0' max='3600' value='{int(conf['cooldown'])}'>
            <div class='hint'>Frühestens so oft wird in aktiven Kanälen neu gepostet (0 = sofort).</div>
          </div>
        </div>
        <div class='st-check'>
          <input type='checkbox' name='ignore_bots' {'checked' if conf['ignore_bots'] else ''}>
          <span>Nachrichten anderer Bots ignorieren (lösen kein Neu-Posten aus)</span>
        </div>
        <div class='st-spacer'></div>
        <button class='btn-accent' type='submit'>Speichern</button>
      </form>
    </div>
    """


def _render_table(guild, stickies, csrf) -> str:
    rows = []
    for cid, s in stickies.items():
        ch = guild.get_channel(int(cid)) if str(cid).isdigit() else None
        ch_name = f"#{ch.name}" if ch else f"{cid} (gelöscht)"
        mode = "Embed" if s.get("mode") == "embed" else "Text"
        state = "aktiv" if s.get("enabled") else "aus"
        via = "Webhook" if s.get("webhook") else "Bot"
        preview = (s.get("text") or "").replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:60] + "…"
        toggle_label = "Deaktivieren" if s.get("enabled") else "Aktivieren"
        edit_link = f"/cogs/sticky?guild={guild.id}&channel={_esc(cid)}"
        rows.append(
            "<tr>"
            f"<td>{_esc(ch_name)}</td>"
            f"<td>{_esc(mode)}</td>"
            f"<td>{_esc(state)}</td>"
            f"<td>{_esc(via)}</td>"
            f"<td style='color:var(--muted)'>{_esc(preview) or '—'}</td>"
            "<td><div class='st-actions'>"
            f"<a class='btn-accent st-btn-sm' href='{edit_link}'>Bearbeiten</a>"
            f"<form method='post' action='/cogs/sticky'>"
            f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
            f"<input type='hidden' name='form' value='toggle'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='channel' value='{_esc(cid)}'>"
            f"<button class='btn-accent st-btn-sm'>{_esc(toggle_label)}</button></form>"
            f"<form method='post' action='/cogs/sticky' onsubmit=\"return confirm('Sticky löschen?')\">"
            f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
            f"<input type='hidden' name='form' value='delete'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='channel' value='{_esc(cid)}'>"
            "<button class='btn-accent st-btn-sm'>Löschen</button></form>"
            "</div></td>"
            "</tr>"
        )
    table = (
        "<table class='table'><thead><tr>"
        "<th>Kanal</th><th>Modus</th><th>Status</th><th>Posten via</th><th>Vorschau</th><th></th>"
        "</tr></thead><tbody>"
        + ("".join(rows) or "<tr><td colspan='6' style='color:var(--muted)'>Noch keine Stickies.</td></tr>")
        + "</tbody></table>"
    )
    return f"<div class='card-x'><div class='st-section-title'>Stickies</div>{table}</div>"


def _render_editor(guild, stickies, text_items, csrf, request) -> str:
    # Vorbefüllung, wenn ein Kanal über ?channel= ausgewählt ist.
    sel_cid = request.query.get("channel")
    s = stickies.get(str(sel_cid)) if sel_cid else None
    s = s or {}
    is_edit = bool(s)

    mode = s.get("mode", "text")
    color = (s.get("embed_color") or "#3ddc97").strip()
    if not color.startswith("#"):
        color = "#" + color

    channel_select = _options(text_items, [sel_cid] if sel_cid else [], none_label="— Kanal wählen —")
    text_sel_de = " selected" if mode == "text" else ""
    embed_sel_de = " selected" if mode == "embed" else ""

    title = "Sticky bearbeiten" if is_edit else "Neue Sticky"

    return f"""
    <div class='card-x'>
      <div class='st-section-title'>{_esc(title)}</div>
      <form class='st-form' method='post' action='/cogs/sticky'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='save'>
        <input type='hidden' name='guild' value='{guild.id}'>

        <div class='row2'>
          <div>
            <label>Kanal</label>
            <select name='channel' required>{channel_select}</select>
          </div>
          <div>
            <label>Modus</label>
            <select name='mode' id='st-mode' onchange='stSyncEditor()'>
              <option value='text'{text_sel_de}>Text</option>
              <option value='embed'{embed_sel_de}>Embed</option>
            </select>
          </div>
        </div>

        <label>Text / Embed-Beschreibung</label>
        <textarea name='text' placeholder='Deine Sticky-Nachricht …'>{_esc(s.get('text', ''))}</textarea>
        <div class='hint'>Platzhalter: <code>{{membercount}}</code>, <code>{{servername}}</code>, <code>{{channel}}</code>, <code>{{channelname}}</code>.</div>

        <div id='st-embed-fields'>
          <div class='row2'>
            <div>
              <label>Embed-Titel (optional)</label>
              <input name='embed_title' value='{_esc(s.get('embed_title', ''))}'>
            </div>
            <div>
              <label>Embed-Farbe</label>
              <input type='color' name='embed_color' value='{_esc(color)}'>
            </div>
          </div>
          <label>Embed-Bild-URL (optional)</label>
          <input name='embed_image' value='{_esc(s.get('embed_image', ''))}' placeholder='https://…'>
          <label>Embed-Footer (optional)</label>
          <input name='embed_footer' value='{_esc(s.get('embed_footer', ''))}'>
        </div>

        <div class='st-check'>
          <input type='checkbox' name='webhook' id='st-webhook' onchange='stSyncEditor()' {'checked' if s.get('webhook') else ''}>
          <span>Webhook-Modus (eigener Name &amp; Avatar) – benötigt „Webhooks verwalten"</span>
        </div>
        <div id='st-webhook-fields'>
          <div class='row2'>
            <div>
              <label>Webhook-Name (optional)</label>
              <input name='webhook_name' value='{_esc(s.get('webhook_name', ''))}'>
            </div>
            <div>
              <label>Webhook-Avatar-URL (optional)</label>
              <input name='webhook_avatar' value='{_esc(s.get('webhook_avatar', ''))}' placeholder='https://…'>
            </div>
          </div>
        </div>

        <div class='st-spacer'></div>
        <button class='btn-accent' type='submit'>Speichern &amp; posten</button>
      </form>
      <script>stSyncEditor();</script>
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
        raise web.HTTPFound("/cogs/sticky?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        lang = data.get("language") or "de"
        await gconf.language.set(lang if lang in LANGUAGES else "de")
        try:
            cd = int(data.get("cooldown", 5))
        except (TypeError, ValueError):
            cd = 5
        await gconf.cooldown.set(max(0, min(3600, cd)))
        await gconf.ignore_bots.set("ignore_bots" in data)
        raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}&ok=Einstellungen+gespeichert")

    if form == "save":
        cid = data.get("channel")
        channel = guild.get_channel(int(cid)) if cid and cid.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}&ok=Ung%C3%BCltiger+Kanal")

        mode = "embed" if data.get("mode") == "embed" else "text"
        text = (data.get("text") or "").strip()
        embed_title = (data.get("embed_title") or "").strip()
        embed_image = (data.get("embed_image") or "").strip()

        # Validierung: es muss etwas Sichtbares geben.
        if mode == "text" and not text:
            raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}&channel={cid}&ok=Bitte+Text+angeben")
        if mode == "embed" and not (text or embed_title or embed_image):
            raise web.HTTPFound(
                f"/cogs/sticky?guild={guild.id}&channel={cid}&ok=Embed+braucht+Text%2C+Titel+oder+Bild"
            )

        async with gconf.stickies() as stickies:
            entry = {
                "enabled": True,
                "mode": mode,
                "text": text,
                "embed_title": embed_title,
                "embed_color": (data.get("embed_color") or "#3ddc97").strip(),
                "embed_image": embed_image,
                "embed_footer": (data.get("embed_footer") or "").strip(),
                "webhook": "webhook" in data,
                "webhook_name": (data.get("webhook_name") or "").strip(),
                "webhook_avatar": (data.get("webhook_avatar") or "").strip(),
                # IDs der zuletzt geposteten Nachricht aus vorhandenem Eintrag übernehmen.
                "message_id": stickies.get(str(cid), {}).get("message_id"),
                "webhook_id": stickies.get(str(cid), {}).get("webhook_id"),
            }
            stickies[str(cid)] = entry

        ok = "Sticky+gespeichert" if await cog.post_now(channel) else "Gespeichert+(Posten+fehlgeschlagen%2C+Rechte%3F)"
        raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}&channel={cid}&ok={ok}")

    if form == "toggle":
        cid = data.get("channel")
        channel = guild.get_channel(int(cid)) if cid and cid.isdigit() else None
        async with gconf.stickies() as stickies:
            entry = stickies.get(str(cid))
            if entry is None:
                raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}")
            new_state = not entry.get("enabled")
            entry["enabled"] = new_state
        if channel is not None:
            if new_state:
                await cog.post_now(channel)
            else:
                await cog.delete_current(channel)
        raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}&ok=Status+ge%C3%A4ndert")

    if form == "delete":
        cid = data.get("channel")
        channel = guild.get_channel(int(cid)) if cid and cid.isdigit() else None
        if channel is not None:
            await cog.delete_current(channel)
        async with gconf.stickies() as stickies:
            stickies.pop(str(cid), None)
        raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}&ok=Sticky+gel%C3%B6scht")

    raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}")
