"""WebCore-Dashboard für den Sticky-Cog.

Aufgaben:
* GET  -> Seite rendern (Sticky-Liste, Editor, Einstellungen)
* POST -> Formular speichern, danach Redirect (Post/Redirect/Get). ``save``/``toggle``/``delete``
  (einzelne Stickies) sind Tagesgeschäft und gehen schon mit der WebCore-Stufe „Bedienen“;
  ``settings`` braucht „Bearbeiten“.

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``): Reiter
Stickies · Editor · Einstellungen – kein eigenes CSS.
"""

from __future__ import annotations

import html
from urllib.parse import quote_plus

import discord
from aiohttp import web

from .strings import LANGUAGES
from .validate import validate_sticky

# Blendet Embed-/Webhook-Felder im Editor passend zu Modus/Schalter ein.
_EDITOR_JS = """
<script>
(function(){
  var f=document.getElementById('st-editor'); if(!f) return;
  var mode=f.querySelector("select[name='mode']"), hook=f.querySelector("input[name='webhook']");
  var embedBox=document.getElementById('st-embed-fields'), hookBox=document.getElementById('st-webhook-fields');
  function sync(){
    if(embedBox&&mode) embedBox.style.display=(mode.value==='embed')?'':'none';
    if(hookBox&&hook) hookBox.style.display=hook.checked?'':'none';
  }
  if(mode) mode.addEventListener('change',sync);
  if(hook) hook.addEventListener('change',sync);
  sync();
})();
</script>
"""

# Erfolgsmeldungen der Redirects – alles andere wird im Editor zusätzlich als Hinweis gezeigt.
_OK_MESSAGES = {"Einstellungen gespeichert", "Sticky gespeichert", "Status geändert", "Sticky gelöscht"}


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


async def _visible_guilds(cog, request):
    webcore = request.app.get("webcore")
    if webcore is not None:
        guilds = await webcore.visible_guilds(request)
    else:  # Fallback (sollte im Normalbetrieb nicht eintreten)
        guilds = list(cog.bot.guilds)
    return sorted(guilds, key=lambda g: g.name.lower())


def _pick_guild(guilds, request):
    gid = request.query.get("guild")
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                return g
    return guilds[0] if guilds else None


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(cog, request)
    guild = _pick_guild(guilds, request)
    if guild is None:
        return {"title": "Sticky", "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    stickies = conf.get("stickies", {})
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]

    guild_picker = ui.card(body=ui.form(
        "/cogs/sticky",
        ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
        csrf="", method="get",
    ))
    # Globaler Server-Wechsler von WebCore aktiv -> eigenes Dropdown ausblenden.
    if request.get("wc_switcher"):
        guild_picker = ""

    n_active = sum(1 for s in stickies.values() if s.get("enabled"))
    head = ui.hero(
        "bi-pin-angle", "",
        "Eine Sticky-Nachricht bleibt immer die <b>letzte Nachricht im Kanal</b>: Schreibt jemand etwas, löscht der "
        "Bot die alte Sticky und postet sie unten neu – ideal für Regeln, Hinweise oder Links.",
    ) + ui.stats([
        ("Stickies", len(stickies), "bi-pin-angle", None, None),
        ("Aktiv", n_active, "bi-play-circle", None, "ok" if n_active else None),
        ("Pausiert", len(stickies) - n_active, "bi-pause-circle", None, None),
        ("Cooldown", f"{int(conf['cooldown'])} s", "bi-stopwatch", "Mindestabstand beim Neu-Posten", None),
    ])

    is_edit = bool(request.query.get("channel") and stickies.get(str(request.query.get("channel"))))
    body = (
        ui.tab("stickies", "Stickies", "bi-pin-angle", _render_table(ui, guild, stickies, csrf), count=len(stickies))
        + ui.tab("editor", "Bearbeiten" if is_edit else "Neue Sticky", "bi-pencil-square" if is_edit else "bi-plus-square",
                 _render_editor(ui, guild, stickies, text_items, csrf, request))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", _render_settings(ui, guild, conf, csrf))
    )
    return {"title": "Sticky", "content": head + guild_picker + body}


def _render_settings(ui, guild, conf, csrf) -> str:
    general = ui.card("Verhalten", ui.grid(
        ui.field("Sprache der Bot-Antworten", ui.select("language", list(LANGUAGES.items()), conf["language"]),
                 help="Gilt für Rückmeldungen der Befehle – der Sticky-Inhalt selbst wird nicht übersetzt."),
        ui.field("Cooldown", ui.number("cooldown", int(conf["cooldown"]), min=0, max=3600, unit="Sekunden"),
                 help="Frühestens so oft wird in aktiven Kanälen neu gepostet (0 = sofort)."),
    ) + "<div class='wc-switches'>" + ui.switch(
        "ignore_bots", "Nachrichten anderer Bots ignorieren", conf["ignore_bots"],
        desc="Nachrichten von Bots lösen kein Neu-Posten der Sticky aus.",
    ) + "</div>", icon="bi-gear", desc="Gilt für alle Stickies auf diesem Server.")
    return ui.form(
        "/cogs/sticky", general + ui.save_row("Einstellungen speichern"),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _render_table(ui, guild, stickies, csrf) -> str:
    rows = []
    for cid, s in stickies.items():
        ch = guild.get_channel(int(cid)) if str(cid).isdigit() else None
        ch_name = f"#{ch.name}" if ch else f"{cid} (gelöscht)"
        preview = (s.get("text") or s.get("embed_title") or "").replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:80] + "…"
        enabled = s.get("enabled")
        hidden = {"guild": guild.id, "channel": cid}
        edit = ui.button("", icon="bi-pencil", kind="ghost", small=True, attrs={"title": "Bearbeiten"},
                         href=f"/cogs/sticky?guild={guild.id}&channel={cid}#editor")
        toggle = ui.form(
            "/cogs/sticky",
            ui.button("", icon="bi-pause-fill" if enabled else "bi-play-fill", kind="ghost", small=True,
                      attrs={"title": "Deaktivieren (Nachricht wird entfernt)" if enabled else "Aktivieren (wird sofort gepostet)"}),
            csrf=csrf, hidden={"form": "toggle", **hidden},
        )
        delete = ui.form(
            "/cogs/sticky",
            ui.button("", icon="bi-trash", kind="danger", small=True, attrs={"title": "Sticky löschen"}),
            csrf=csrf, hidden={"form": "delete", **hidden},
            confirm=f"Die Sticky in {ch_name} wird gelöscht und ihre Nachricht entfernt.",
        )
        tags = (ui.badge("Embed", "info") if s.get("mode") == "embed" else ui.badge("Text")) + (
            " " + ui.badge("Webhook") if s.get("webhook") else "")
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(ch_name)} {tags}</div>"
            f"<div class='wc-cell-sub'>{_esc(preview) or '—'}</div>",
            ui.badge("aktiv", "ok") if enabled else ui.badge("pausiert", "warn"),
            f"><div class='wc-row-actions'>{edit}{toggle}{delete}</div>",
        ))
    if not rows:
        return ui.card(body=ui.empty(
            "bi-pin-angle", "Noch keine Stickies.", "Lege im Reiter „Neue Sticky“ die erste an.",
            action=ui.button("Neue Sticky anlegen", icon="bi-plus-lg", href=f"/cogs/sticky?guild={guild.id}#editor"),
        ))
    table = ui.table(["Kanal / Vorschau", "Status", ">"], rows,
                     search=len(rows) > 5, search_placeholder="Kanal oder Text suchen …", id="st-list")
    return ui.card("Deine Stickies", table, icon="bi-pin-angle",
                   desc="Pausieren entfernt die Nachricht aus dem Kanal, Aktivieren postet sie sofort neu.")


def _render_editor(ui, guild, stickies, text_items, csrf, request) -> str:
    # Vorbefüllung, wenn ein Kanal über ?channel= ausgewählt ist.
    sel_cid = request.query.get("channel")
    s = stickies.get(str(sel_cid)) if sel_cid else None
    s = s or {}
    is_edit = bool(s)

    mode = s.get("mode", "text")
    color = (s.get("embed_color") or "#3ddc97").strip()
    if not color.startswith("#"):
        color = "#" + color

    # Kanäle mit vorhandener Sticky kennzeichnen (Wert bleibt die Kanal-ID).
    items = [(cid, f"{label}  · hat Sticky" if str(cid) in stickies else label) for cid, label in text_items]
    channel_select = (
        f"<select class='wc-input' name='channel' required>"
        f"{_options(items, [sel_cid] if sel_cid else [], none_label='— Kanal wählen —')}</select>"
    )

    notice = ""
    msg = request.query.get("err") or request.query.get("ok")
    if msg and msg not in _OK_MESSAGES:
        notice = ui.callout(_esc(msg), tone="warn")

    actions = ""
    title = "Neue Sticky"
    if is_edit:
        ch = guild.get_channel(int(sel_cid)) if str(sel_cid).isdigit() else None
        title = f"Sticky bearbeiten: #{ch.name}" if ch else "Sticky bearbeiten"
        actions = ui.button("Neue Sticky", icon="bi-plus-lg", kind="ghost", small=True,
                            href=f"/cogs/sticky?guild={guild.id}#editor")
    content = ui.card(title, ui.grid(
        ui.field("Kanal", channel_select,
                 help="Pro Kanal gibt es eine Sticky – eine vorhandene wird beim Speichern ersetzt."),
        ui.field("Modus", ui.select("mode", [("text", "Text"), ("embed", "Embed")], mode),
                 help="Embed = Kasten mit Titel, Farbe, Bild und Footer."),
        ui.field("Text / Embed-Beschreibung", ui.textarea("text", s.get("text", ""), rows=5,
                                                          placeholder="Deine Sticky-Nachricht …"),
                 help="Platzhalter: <code>{membercount}</code>, <code>{servername}</code>, "
                      "<code>{channel}</code>, <code>{channelname}</code>.", wide=True),
    ), icon="bi-pencil-square" if is_edit else "bi-plus-square", actions=actions,
        desc="Beim Speichern wird die Sticky sofort (neu) im Kanal gepostet.")

    embed = ui.card("Embed", ui.grid(
        ui.field("Titel (optional)", ui.text_input("embed_title", s.get("embed_title", ""))),
        ui.field("Farbe", ui.text_input("embed_color", color, type="color",
                                                attrs={"style": "height:42px;padding:4px 6px;cursor:pointer"})),
        ui.field("Bild-URL (optional)", ui.text_input("embed_image", s.get("embed_image", ""), placeholder="https://…")),
        ui.field("Footer (optional)", ui.text_input("embed_footer", s.get("embed_footer", ""))),
    ), icon="bi-palette", desc="Nur im Modus „Embed“.")

    webhook = ui.card("Absender", "<div class='wc-switches'>" + ui.switch(
        "webhook", "Webhook-Modus", s.get("webhook"),
        desc="Postet mit eigenem Namen &amp; Avatar statt als Bot – benötigt das Recht „Webhooks verwalten“.",
    ) + "</div><div id='st-webhook-fields'>" + ui.grid(
        ui.field("Webhook-Name (optional)", ui.text_input("webhook_name", s.get("webhook_name", ""))),
        ui.field("Webhook-Avatar-URL (optional)", ui.text_input("webhook_avatar", s.get("webhook_avatar", ""),
                                                                placeholder="https://…")),
    ) + "</div>", icon="bi-person-badge")

    form = ui.form(
        "/cogs/sticky",
        content + f"<div id='st-embed-fields'>{embed}</div>" + webhook
        + ui.save_row("Speichern & posten"),
        csrf=csrf, hidden={"form": "save", "guild": guild.id}, savebar=True, id="st-editor",
    )
    return notice + form + _EDITOR_JS


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    # Server-Auswahl serverseitig gegen die sichtbaren Server prüfen.
    guilds = await _visible_guilds(cog, request)
    guild = None
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                guild = g
                break
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

        candidate = {
            "mode": mode, "text": text, "embed_title": embed_title, "embed_image": embed_image,
            "embed_footer": (data.get("embed_footer") or "").strip(),
            "webhook": "webhook" in data,
            "webhook_name": (data.get("webhook_name") or "").strip(),
            "webhook_avatar": (data.get("webhook_avatar") or "").strip(),
        }
        err = validate_sticky(candidate)
        if err:
            # Vorher wurde gespeichert, das Posten scheiterte an Discord-Limits – und die
            # alte Sticky war dann schon gelöscht. Jetzt: gar nicht erst speichern.
            raise web.HTTPFound(f"/cogs/sticky?guild={guild.id}&channel={cid}&err=" + quote_plus(err))

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
