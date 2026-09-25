"""WebCore-Dashboard für den OnlyImageVideo-Cog.

* GET                 -> Seite mit Reitern Übersicht · Einstellungen · Hinweis
* POST form=settings  -> Einstellungen speichern (Post/Redirect/Get)

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``), kein
eigenes CSS. Nutzereingaben werden mit ``html.escape`` abgesichert.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from aiohttp import web

from .detect import MEDIA_HOSTS
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

NOTIFY_MIN = 2
NOTIFY_MAX = 60


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _channel_items(guild):
    items = []
    for c in guild.text_channels:
        items.append((c.id, f"# {c.name}"))
    for c in getattr(guild, "forums", []):
        items.append((c.id, f"[Forum] {c.name}"))
    for c in guild.voice_channels:
        items.append((c.id, f"[Voice] {c.name}"))
    return items


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


def _selected_guild(guilds, request):
    gid = request.query.get("guild")
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                return g
    return guilds[0] if guilds else None


async def _render(cog, request):
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(cog, request)
    guild = _selected_guild(guilds, request)
    if guild is None:
        return {"title": "Nur Medien", "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")

    # Eigene Server-Auswahl nur ohne globalen Server-Wechsler von WebCore.
    bar = ""
    if not request.get("wc_switcher"):
        bar = ui.form("/cogs/onlyimagevideo",
                      ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True),
                      csrf="", method="get", cls="wc-inline-form")

    n_channels = len(conf.get("channels") or [])
    n_roles = len(conf.get("exempt_roles") or [])
    deleted = int(conf.get("deleted_total", 0))
    head = ui.hero(
        "bi-images", "",
        "In den gewählten Kanälen (und ihren Threads) sind nur Beiträge mit <b>Bild, Video oder GIF</b> erlaubt – "
        "reine Textnachrichten löscht der Bot automatisch.",
        actions=bar,
    ) + ui.stats([
        ("Überwachte Kanäle", n_channels, "bi-hash", None if n_channels else "Regel greift nirgends",
         "ok" if n_channels else "warn"),
        ("Ausnahme-Rollen", n_roles, "bi-person-check", None, None),
        ("Gelöschte Nachrichten", deleted, "bi-trash", None, None),
    ])

    body = (
        ui.tab("uebersicht", "Übersicht", "bi-speedometer2", _render_overview(ui, guild, conf))
        + _render_settings(ui, guild, conf, csrf)
    )
    return {"title": "Nur Medien", "content": head + body}


def _render_overview(ui, guild, conf) -> str:
    checks = []
    if not conf.get("channels"):
        checks.append(("warn", "Noch <b>keine Kanäle</b> gewählt – die Regel greift nirgends. Wähle sie im Reiter „Einstellungen“."))
    else:
        missing = [c for c in conf.get("channels") or [] if guild.get_channel(int(c)) is None]
        if missing:
            checks.append(("warn", f"{len(missing)} gewählte(r) Kanal/Kanäle existieren nicht mehr – bitte in den Einstellungen prüfen."))
    if not conf.get("notify"):
        checks.append(("info", "Der <b>Hinweis beim Löschen</b> ist aus – Mitglieder erfahren nicht, warum ihre Nachricht verschwindet."))
    checks.append(("info", "Der Bot braucht in den Kanälen das Recht <code>Nachrichten verwalten</code>, sonst kann er nicht löschen."))
    setup = ui.card("Einrichtung", "".join(ui.callout(text, tone=tone) for tone, text in checks),
                    icon="bi-clipboard-check")
    return ui.columns(setup, _render_info(ui, conf))


def _render_settings(ui, guild, conf, csrf) -> str:
    roles = [
        (r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()
    ]
    save = ui.save_row("Einstellungen speichern")

    channels = ui.card("Kanäle", ui.grid(
        ui.field("Nur-Medien-Kanäle", ui.select("channels", _channel_items(guild), conf.get("channels") or [],
                                                multiple=True, placeholder="Kanäle suchen …"),
                 help="Threads in diesen Kanälen erben die Regel automatisch.", wide=True),
        cols=1), icon="bi-hash", desc="In diesen Kanälen werden Nachrichten ohne Medium gelöscht.")
    media = ui.card("Was zählt als Medium?", "<div class='wc-switches'>"
        + ui.switch("allow_links", "Links zu Mediendateien", conf.get("allow_links"),
                    desc="Direkte Links auf z. B. <code>.png</code> oder <code>.mp4</code>.")
        + ui.switch("allow_hosts", "GIF-/Medien-Dienste", conf.get("allow_hosts"),
                    desc="Links von Tenor, Giphy, Imgur …")
        + ui.switch("allow_stickers", "Sticker", conf.get("allow_stickers"),
                    desc="Sticker zählen als Bild.")
        + "</div>", icon="bi-image",
        desc="Hochgeladene Bilder und Videos (inkl. GIF) zählen immer.")
    exempt = ui.card("Ausnahmen", ui.grid(
        ui.field("Ausnahme-Rollen", ui.select("exempt_roles", roles, conf.get("exempt_roles") or [],
                                              multiple=True, placeholder="Rollen suchen …"),
                 help="Mitglieder mit diesen Rollen dürfen auch reinen Text schreiben.", wide=True),
        cols=1) + "<div class='wc-switches'>"
        + ui.switch("ignore_bots", "Bots/Webhooks ausnehmen", conf.get("ignore_bots"),
                    desc="Nachrichten von Bots und Webhooks bleiben stehen.")
        + "</div>", icon="bi-person-check")

    overrides = conf.get("messages") or {}
    text_fields = []
    for key in OVERRIDABLE_KEYS:
        text_fields.append(ui.field(
            "Eigener Hinweistext" if key == "notice" else key,
            ui.textarea(f"ovr_{key}", overrides.get(key, ""), rows=3, placeholder=STRINGS["de"].get(key, "")),
            help="Platzhalter <code>{user}</code> wird durch die Erwähnung ersetzt. Leer lassen = Standardtext der gewählten Sprache.",
            wide=True,
        ))
    notice = ui.card("Hinweis beim Löschen", "<div class='wc-switches'>"
        + ui.switch("notify", "Hinweis senden", conf.get("notify"),
                    desc="Kurze Nachricht im Kanal, warum der Beitrag entfernt wurde.")
        + "</div>" + ui.grid(
            ui.field("Hinweis verschwindet nach", ui.number("notify_delete_after", int(conf.get("notify_delete_after", 6)),
                                                             min=NOTIFY_MIN, max=NOTIFY_MAX, unit="Sek."),
                     help=f"{NOTIFY_MIN}–{NOTIFY_MAX} Sekunden."),
            ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf.get("language", "de")),
                     help="Sprache des Standard-Hinweises."),
            *text_fields,
        ), icon="bi-chat-left-text")

    # Ein Formular über beide Einstellungs-Reiter – ein Speichern sendet alles.
    return ui.form(
        "/cogs/onlyimagevideo",
        ui.tab("einstellungen", "Einstellungen", "bi-sliders", channels + media + exempt + save)
        + ui.tab("hinweis", "Hinweis", "bi-chat-left-text", notice + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _render_info(ui, conf) -> str:
    items = ["Hochgeladene Bilder und Videos (inkl. <code>.gif</code>)"]
    if conf.get("allow_stickers"):
        items.append("Sticker")
    if conf.get("allow_links"):
        items.append("Direkte Links zu Mediendateien (z. B. <code>.png</code>, <code>.mp4</code>)")
    if conf.get("allow_hosts"):
        hosts = ", ".join(f"<code>{_esc(h)}</code>" for h in MEDIA_HOSTS[:5])
        items.append(f"Links von GIF-/Medien-Diensten ({hosts} …)")
    li = "".join(f"<li><i class='bi bi-check2'></i><span>{i}</span></li>" for i in items)
    return ui.card("Das zählt aktuell als Medium", f"<ul class='wc-list'>{li}</ul>", icon="bi-info-circle",
                   desc="Alles andere wird in den überwachten Kanälen gelöscht – außer von Bots/Webhooks "
                        "(falls ausgenommen) und Mitgliedern mit Ausnahme-Rolle.")


async def _handle_post(cog, request):
    data = await request.post()
    if data.get("form") != "settings":
        raise web.HTTPFound("/cogs/onlyimagevideo")
    gid = data.get("guild")
    guilds = await _visible_guilds(cog, request)
    guild = None
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                guild = g
                break
    if guild is None:
        raise web.HTTPFound("/cogs/onlyimagevideo?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    lang = (data.get("language") or "de").lower()
    if lang in LANGUAGES:
        await gconf.language.set(lang)

    channels = [int(c) for c in data.getall("channels", []) if str(c).isdigit()]
    await gconf.channels.set(channels)
    roles = [int(r) for r in data.getall("exempt_roles", []) if str(r).isdigit()]
    await gconf.exempt_roles.set(roles)

    await gconf.allow_links.set("allow_links" in data)
    await gconf.allow_hosts.set("allow_hosts" in data)
    await gconf.allow_stickers.set("allow_stickers" in data)
    await gconf.ignore_bots.set("ignore_bots" in data)
    await gconf.notify.set("notify" in data)

    try:
        secs = int(data.get("notify_delete_after") or 6)
        await gconf.notify_delete_after.set(max(NOTIFY_MIN, min(NOTIFY_MAX, secs)))
    except (TypeError, ValueError):
        pass

    overrides = {}
    for key in OVERRIDABLE_KEYS:
        val = (data.get(f"ovr_{key}") or "").strip()
        if val:
            overrides[key] = val
    await gconf.messages.set(overrides)

    raise web.HTTPFound(f"/cogs/onlyimagevideo?guild={guild.id}&ok=" + quote("Gespeichert"))
