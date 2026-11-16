"""WebCore-Oberfläche für aktive Twitch- und YouTube-Streams.

Zugriff wird bei jedem POST geprüft. Zugangsdaten werden weder zurückgerendert
noch als Formularentwurf gespeichert.
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote, urlencode, urlsplit

from aiohttp import web

from .providers import ProviderError

BASE = "/cogs/streamer"
TITLE = "Streamer"
PROVIDERS = {"twitch": "Twitch", "youtube": "YouTube"}
OPERATE_FORMS = {"check", "toggle"}


def _esc(value):
    return escape(str(value or ""), quote=True)


def _pick(guilds, value):
    raw = str(value or "")
    return next((g for g in guilds if str(g.id) == raw), None)


def _redirect(guild, text, *, error=False, tab="overview"):
    values = {"guild": guild.id, "err" if error else "ok": text}
    return {"redirect": BASE + "?" + urlencode(values) + "#" + tab}


async def _owner(cog, wc, request):
    # Full scope umfasst auch die Dashboard-Allowlist. Zugangsdaten bleiben
    # ausschließlich bei tatsächlichen Bot-Ownern.
    if not await wc.has_full_scope(request):
        return False
    user = await wc.current_user(request)
    return bool(user and user.get("id") in cog.bot.owner_ids)


async def dashboard_handler(cog, request):
    wc = request.app["webcore"]
    guilds = sorted(await wc.visible_guilds(request), key=lambda g: g.name.casefold())
    if request.method == "POST":
        data = await request.post()
        guild = _pick(guilds, data.get("guild"))
        if guild is None:
            raise web.HTTPForbidden(text="Kein Zugriff auf diesen Server.")
        kind = str(data.get("form") or "")
        can_edit = await wc.can_edit(request, guild)
        if kind in OPERATE_FORMS:
            permitted = await wc.can_operate(request, guild) if hasattr(wc, "can_operate") else can_edit
        else:
            permitted = can_edit
        if not permitted:
            raise web.HTTPForbidden(text="Für diese Aktion fehlen die Rechte.")
        tab = "settings" if kind == "settings" else "access" if kind == "credentials" else "overview"
        try:
            if kind == "settings":
                raw = str(data.get("channel_id") or "")
                if not raw.isdigit():
                    raise ValueError("Bitte einen Zielkanal auswählen.")
                values = {"channel_id": int(raw), "title_filter": str(data.get("title_filter") or ""),
                          "enabled": bool(data.get("enabled"))}
                # Alte, noch geöffnete Formulare ändern die neue Rollenoption nicht.
                if "watched_role_id" in data:
                    role_raw = str(data.get("watched_role_id") or "").strip()
                    if role_raw and not role_raw.isdigit():
                        raise ValueError("Bitte eine gültige Rolle dieses Servers wählen.")
                    role_id = int(role_raw or 0)
                    role = guild.get_role(role_id) if role_id else None
                    if role_id and (role is None or role.is_default()):
                        raise ValueError("Bitte eine gültige Rolle dieses Servers wählen; @everyone ist nicht möglich.")
                    values["watched_role_id"] = role_id
                await cog.configure(guild, **values)
                message = "Einstellungen gespeichert."
            elif kind == "add":
                provider = str(data.get("provider") or "")
                if provider not in PROVIDERS:
                    raise ValueError("Bitte Twitch oder YouTube wählen.")
                source = await cog.add_source(guild, provider, str(data.get("source") or ""))
                message = f"{source.get('name') or source.get('identifier')} hinzugefügt."
            elif kind == "remove":
                await cog.remove_source(guild, str(data.get("key") or ""))
                message = "Quelle entfernt. Ihre Ankündigungen werden bereinigt."
            elif kind == "toggle":
                await cog.toggle_source(guild, str(data.get("key") or ""))
                message = "Quelle umgeschaltet."
            elif kind == "check":
                await cog.poll_once()
                message = "Prüfung abgeschlossen. Den aktuellen Verbindungsstatus siehst du unten."
            elif kind == "credentials":
                if not await _owner(cog, wc, request):
                    raise web.HTTPForbidden(text="Zugangsdaten darf nur der Bot-Owner ändern.")
                provider = str(data.get("provider") or "")
                if provider == "twitch":
                    client_id = str(data.get("twitch_client_id") or "").strip()
                    secret = str(data.get("twitch_client_secret") or "").strip()
                    if not client_id or not secret:
                        raise ValueError("Bitte Twitch-Client-ID und Client-Secret gemeinsam eintragen.")
                    await cog.set_credentials(twitch_client_id=client_id, twitch_client_secret=secret)
                elif provider == "youtube":
                    key = str(data.get("youtube_api_key") or "").strip()
                    if not key:
                        raise ValueError("Bitte einen YouTube-API-Key eintragen.")
                    await cog.set_credentials(youtube_api_key=key)
                else:
                    raise ValueError("Plattform nicht erkannt.")
                message = "Zugang gespeichert."
            else:
                raise ValueError("Aktion nicht erkannt.")
        except (ValueError, ProviderError) as exc:
            return _redirect(guild, str(exc), error=True, tab=tab)
        return _redirect(guild, message, tab=tab)
    return await _render(cog, request, guilds)


def _source_url(source):
    provider = source.get("provider")
    identifier = quote(str(source.get("identifier") or ""), safe="")
    if provider == "twitch":
        return "https://www.twitch.tv/" + identifier
    if provider == "youtube":
        return "https://www.youtube.com/channel/" + identifier
    return ""


def _role_source_url(source):
    # Rollenstreams können YouTube-Video-URLs statt Kanal-IDs enthalten.
    # Nur Links zu den unterstützten Plattformen in die Oberfläche übernehmen.
    value = str(source.get("url") or "")
    try:
        url = urlsplit(value)
        if (url.scheme == "https" and url.hostname in {
                "twitch.tv", "www.twitch.tv", "youtube.com", "www.youtube.com", "youtu.be"}
                and not url.username and not url.password and url.port in (None, 443)):
            return value
    except ValueError:
        pass
    return ""


def _stream_url(stream):
    if stream.get("provider") == "youtube":
        return "https://www.youtube.com/watch?v=" + quote(str(stream.get("id") or ""), safe="")
    if stream.get("provider") == "twitch":
        identifier = str(stream.get("source_key") or "").removeprefix("twitch:")
        return "https://www.twitch.tv/" + quote(identifier, safe="")
    return ""


def _link(url, label):
    if not url:
        return _esc(label)
    return f"<a href='{_esc(url)}' target='_blank' rel='noopener noreferrer'>{_esc(label)}</a>"


def _status(ui, value):
    state = str((value or {}).get("state") or "idle")
    if state == "ok":
        return ui.badge("Verbunden", "ok")
    if state in {"missing", "no_credentials"}:
        return ui.badge("Zugang fehlt", "warn")
    if state in {"error", "auth_error", "rate_limited"}:
        return ui.badge("Prüfung gestört", "warn")
    return ui.badge("Noch nicht geprüft", "muted")


async def _render(cog, request, guilds):
    wc, ui = request.app["webcore"], request.app["webcore"].ui
    raw = request.query.get("guild")
    guild = _pick(guilds, raw) if raw else (guilds[0] if guilds else None)
    if guild is None:
        return {"title": TITLE, "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    conf = await cog.config.guild(guild).all()
    edit = await wc.can_edit(request, guild)
    operate = await wc.can_operate(request, guild) if hasattr(wc, "can_operate") else edit
    full = await _owner(cog, wc, request)
    csrf = request.get("webcore_csrf", "")
    sources, state = conf.get("sources") or {}, conf.get("state") or {}
    role_watch = cog.role_watch_status(guild, conf)
    role_sources = role_watch.get("sources") or {}
    messages = [record for record in state.values() if record.get("message_id")]
    check = ui.form(BASE, ui.button("Jetzt prüfen", icon="bi-arrow-repeat", kind="ghost"),
                    csrf=csrf, hidden={"form": "check", "guild": guild.id}, operate=True) if operate else ""
    head = ui.hero("bi-broadcast", "", "Zeige aktive <b>Twitch- und YouTube-Streams</b> automatisch über eine Discord-Rolle "
                   "oder über eingetragene Kanäle. Ankündigungen verschwinden beim Stream-Ende oder wenn der Titel nicht mehr passt.",
                   actions=check)
    if not request.get("wc_switcher"):
        head += ui.form(BASE, ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds],
                                                         guild.id, autosubmit=True)), csrf="", method="get")
    head += ui.stats([
        ("Quellen", len(set(sources) | set(role_sources)), "bi-person-video3",
         f"{len(sources)} API-Kanäle · {len(role_sources)} über Rolle", None),
        ("Ankündigungen", len(messages), "bi-broadcast", "Vom Bot verwaltete Nachrichten", None),
        ("Titelfilter", conf.get("title_filter") or "Aus", "bi-funnel", "Groß-/Kleinschreibung wird ignoriert", None),
    ])
    if not conf.get("enabled", True):
        head += ui.callout("<b>Streamer ist für diesen Server ausgeschaltet.</b> Bestehende Ankündigungen werden entfernt.", tone="warn")
    if not conf.get("channel_id"):
        head += ui.callout("Wähle zuerst einen <b>Zielkanal</b> unter Einstellungen. " + ui.goto("Einstellungen öffnen", "settings"), tone="warn")
    if conf.get("last_error"):
        head += ui.callout(_esc(conf["last_error"]), tone="warn")
    if role_watch.get("warning"):
        head += ui.callout(f"<b>Discord-Rolle:</b> {_esc(role_watch['warning'])}", tone="warn")
    for provider, label in PROVIDERS.items():
        status = (cog.status or {}).get(provider) or {}
        if status.get("error") and any(source.get("provider") == provider for source in sources.values()):
            head += ui.callout(f"<b>{label}:</b> {_esc(status['error'])} Bestehende Meldungen werden bei API-Fehlern nicht als offline gelöscht.", tone="warn")
    youtube_status = getattr(cog.api, "youtube_status", None) or {}
    if youtube_status.get("warning") and any(source.get("provider") == "youtube" for source in sources.values()):
        head += ui.callout(f"<b>YouTube-Live-Suche:</b> {_esc(youtube_status['warning'])}", tone="warn")
    overview = _role_overview(ui, role_watch) + _overview(ui, guild, sources, state, csrf, edit, operate)
    if sources:
        overview += _connections(ui, cog.status or {})
    if any(s.get("provider") == "youtube" for s in sources.values()):
        overview += _youtube_notice(ui)
    settings = _settings(ui, guild, conf, csrf) if edit else ui.card("Einstellungen", ui.empty(
        "bi-lock", "Nur Ansicht", "Zielkanal und Titelfilter können mit der Stufe „Bearbeiten“ geändert werden."))
    access = await _access(cog, ui, guild, csrf) if full and edit else ui.card("Zugang", ui.empty(
        "bi-lock", "Bot-Owner erforderlich", "Der Bot-Owner hinterlegt den Twitch- und YouTube-Zugang einmal für alle Server."))
    return {"title": TITLE, "content": head + ui.tab("overview", "Übersicht", "bi-broadcast", overview)
            + ui.tab("settings", "Einstellungen", "bi-sliders", settings)
            + ui.tab("access", "Zugang", "bi-key", access)}


def _overview(ui, guild, sources, state, csrf, edit, operate):
    live_rows = []
    for record in sorted(state.values(), key=lambda r: str((r.get("stream") or {}).get("name") or "").casefold()):
        if not record.get("message_id"):
            continue
        stream = record.get("stream") or {}
        provider = stream.get("provider") or record.get("provider")
        name = stream.get("name") or record.get("source_key") or "Stream"
        ids = [record.get("channel_id"), record.get("message_id")]
        message_url = f"https://discord.com/channels/{guild.id}/{ids[0]}/{ids[1]}" if all(str(v).isdigit() for v in ids) else ""
        status = ui.badge("Prüfung/Bereinigung offen", "warn") if record.get("error") else ui.badge("Angekündigt", "ok")
        live_rows.append(ui.row(_link(_stream_url(stream), name), _esc(stream.get("title") or "Ohne Titel"),
                                _esc(PROVIDERS.get(provider, provider)), status, _link(message_url, "In Discord öffnen")))
    content = ui.card("Verwaltete Ankündigungen", ui.table(
        ["Stream", "Titel", "Plattform", "Status", "Nachricht"], live_rows,
        empty_text="Noch keine passenden Live-Streams. Die Übersicht füllt sich automatisch."), icon="bi-broadcast",
        desc="Der Bot verwaltet und löscht ausschließlich seine eigenen Stream-Ankündigungen.")
    rows = []
    for key, source in sorted(sources.items(), key=lambda item: str(item[1].get("name") or item[0]).casefold()):
        enabled = source.get("enabled", True)
        controls = []
        if operate:
            controls.append(ui.form(BASE, ui.button("Pausieren" if enabled else "Fortsetzen", kind="ghost", small=True,
                                                   icon="bi-pause" if enabled else "bi-play"), csrf=csrf,
                                    hidden={"form": "toggle", "guild": guild.id, "key": key}, operate=True))
        if edit:
            controls.append(ui.form(BASE, ui.button("Entfernen", icon="bi-trash", kind="danger", small=True), csrf=csrf,
                                    hidden={"form": "remove", "guild": guild.id, "key": key},
                                    confirm=f"Quelle „{source.get('name') or key}“ entfernen und ihre Ankündigungen löschen?"))
        rows.append(ui.row(_link(_source_url(source), source.get("name") or source.get("identifier") or key),
                           _esc(PROVIDERS.get(source.get("provider"), source.get("provider"))),
                           ui.badge("Aktiv" if enabled else "Pausiert", "ok" if enabled else "muted"),
                           f"<div class='wc-row-actions'>{''.join(controls)}</div>"))
    body = ui.table(["Kanal", "Plattform", "Überwachung", ">Aktionen"], rows,
                    empty_text="Keine zusätzlichen API-Kanäle. Für die automatische Rolle sind hier keine Einträge nötig.",
                    search=len(rows) > 8, id="streamer-sources")
    if edit:
        add = ui.form(BASE, ui.grid(
            ui.field("Plattform", ui.select("provider", list(PROVIDERS.items()), "twitch")),
            ui.field("Streamer-Kanal", ui.text_input("source", "", placeholder="Twitch-Name oder YouTube-@Handle / Kanal-URL",
                                                     attrs={"maxlength": 200, "required": True}),
                     help="YouTube: @Handle, Kanal-ID (UC…) oder Kanal-URL. Twitch: Name oder Kanal-URL."),
        ) + ui.save_row("Kanal hinzufügen"), csrf=csrf, hidden={"form": "add", "guild": guild.id})
        body += ui.divider() + add
    return content + ui.card("Zusätzliche API-Kanäle", body, icon="bi-person-video3",
                            desc="Optional: feste Kanäle unabhängig vom Discord-Status überwachen. Hierfür wird der jeweilige API-Zugang benötigt.")


def _role_overview(ui, status):
    if not status.get("role_id"):
        return ui.card("Automatisch über Rolle", ui.empty(
            "bi-people", "Eine Rolle für eure Streamer wählen",
            "Alle Mitglieder dieser Rolle werden anhand ihres öffentlichen Discord-Streamingstatus erkannt. Keine API-Zugangsdaten nötig.",
            action=ui.goto("Rolle einrichten", "settings")), icon="bi-people")
    sources = status.get("sources") or {}
    summary = ui.stats([
        ("Mitglieder", status.get("members") or 0, "bi-people", None, None),
        ("Streamingstatus", status.get("live") or 0, "bi-broadcast", "Der Titelfilter gilt zusätzlich", None),
    ])
    if status.get("ready") and status.get("role_name") and not status.get("warning"):
        summary += ui.callout("<b>Rollen-Erkennung bereit.</b> Ein Twitch- oder YouTube-Stream erscheint, sobald ein Mitglied "
                              "dieser Rolle die passende Streamingaktivität in Discord anzeigt. API-Zugangsdaten sind dafür nicht nötig.", tone="ok")
    rows = [ui.row(_link(_role_source_url(source), source.get("name") or source.get("identifier") or key),
                   _esc(PROVIDERS.get(source.get("provider"), source.get("provider"))))
            for key, source in sorted(sources.items(), key=lambda item: str(item[1].get("name") or item[0]).casefold())]
    summary += ui.table(["Erkannter Stream", "Plattform"], rows,
                        empty_text="Aktuell zeigt kein Mitglied dieser Rolle einen unterstützten öffentlichen Streamingstatus.")
    return ui.card("Automatisch über Rolle", summary, icon="bi-people",
                   desc=f"Rolle: {_esc(status.get('role_name') or 'Nicht mehr vorhanden')}. Der gemeinsame Zielkanal und Titelfilter gelten auch hier.")


def _connections(ui, status):
    rows = [ui.row(_esc(label), _status(ui, status.get(provider))) for provider, label in PROVIDERS.items()]
    return ui.card("Verbindungen", ui.table(["Plattform", "Status"], rows), icon="bi-plug")


def _settings(ui, guild, conf, csrf):
    channels = sorted(guild.text_channels, key=lambda c: (getattr(c, "position", 0), c.id))
    body = ui.switches(ui.switch("enabled", "Stream-Ankündigungen aktiv", conf.get("enabled", True),
                                 desc="Beim Ausschalten werden bestehende Stream-Ankündigungen entfernt.")) + ui.divider()
    body += ui.grid(
        ui.field("Zielkanal", ui.select("channel_id", [(c.id, f"#{c.name}") for c in channels], conf.get("channel_id"),
                                         none_label="— Kanal wählen —"),
                 help="Für alle Twitch- und YouTube-Streams dieses Servers. Andere Nachrichten bleiben erhalten."),
        ui.field("Titel muss enthalten", ui.text_input("title_filter", conf.get("title_filter") or "",
                                                       placeholder="Optional, z. B. DNP", attrs={"maxlength": 100}),
                 help="Leer zeigt alle Live-Streams. „DNP“ findet auch „dnp“ und „#DNP“. Titeländerungen werden mitgeprüft."),
        ui.field("Streamer automatisch über Rolle erkennen", ui.select(
            "watched_role_id", [(r.id, r.name) for r in sorted(guild.roles, key=lambda r: (-r.position, r.id))
                                if not r.is_default()], conf.get("watched_role_id"), none_label="— ausgeschaltet —"),
                 help="Optional: z. B. die Rolle „Streamer“. Erkennt deren Twitch-/YouTube-Streamingstatus ohne API-Zugang. "
                      "Die Rolle wird dabei nicht vom Bot vergeben.", wide=True),
    )
    body += ui.disclosure("Discord für die Rollen-Erkennung vorbereiten", ui.callout(
        "Im <b>Discord Developer Portal → Bot → Privileged Gateway Intents</b> müssen <b>Presence Intent</b> und "
        "<b>Server Members Intent</b> eingeschaltet sein. Auch Red muss mit beiden Intents gestartet sein. "
        "Danach den Bot gegebenenfalls neu starten. Mitglieder müssen ihre <b>Streamingaktivität öffentlich anzeigen</b> lassen; "
        "eine Discord-Bildschirmfreigabe oder „Go Live“ allein ist kein solcher Streamingstatus."))
    body += ui.callout("Der Bot braucht im Zielkanal <b>Kanal ansehen</b>, <b>Nachrichten senden</b>, "
                       "<b>Links einbetten</b> und <b>Nachrichtenverlauf lesen</b>. Er löscht seine eigenen Meldungen; "
                       "„Nachrichten verwalten“ ist dafür nicht erforderlich.")
    return ui.form(BASE, ui.card("Ankündigungen", body, icon="bi-sliders") + ui.save_row("Einstellungen speichern"),
                   csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True)


def _youtube_notice(ui):
    return ui.callout("<b>YouTube:</b> Bereits bekannte Streams werden etwa minütlich geprüft. Die Suche nach neuen "
                       "Streams läuft wegen des YouTube-Suchlimits frühestens alle 30 Minuten, bei vielen Kanälen seltener. "
                       "Neue Streams können deshalb verzögert erscheinen. „Jetzt prüfen“ umgeht dieses Suchlimit nicht.",
                       icon="bi-youtube")


async def _access(cog, ui, guild, csrf):
    twitch_ready = bool(await cog.config.twitch_client_id() and await cog.config.twitch_client_secret())
    youtube_ready = bool(await cog.config.youtube_api_key())
    password = {"autocomplete": "new-password", "maxlength": 500, "required": True}
    twitch = ui.callout("1. In der <a href='https://dev.twitch.tv/console/apps' target='_blank' rel='noopener noreferrer'>"
                        "Twitch Developer Console</a> eine Anwendung registrieren. Als OAuth-Redirect kann "
                        "<code>http://localhost</code> dienen. 2. Client-ID und Client-Secret hier eintragen. "
                        "Für öffentliche Livestreams ist keine Anmeldung jedes Streamers nötig.")
    twitch += ui.form(BASE, ui.grid(
        ui.field("Twitch-Client-ID", ui.text_input("twitch_client_id", "", type="password", attrs=password)),
        ui.field("Twitch-Client-Secret", ui.text_input("twitch_client_secret", "", type="password", attrs=password)),
    ) + ui.save_row("Twitch-Zugang speichern"), csrf=csrf,
        hidden={"form": "credentials", "provider": "twitch", "guild": guild.id}, attrs={"autocomplete": "off"})
    youtube = ui.callout("1. In der <a href='https://console.cloud.google.com/apis/library/youtube.googleapis.com' "
                         "target='_blank' rel='noopener noreferrer'>Google Cloud Console</a> die <b>YouTube Data API v3</b> "
                         "aktivieren. 2. Einen API-Key erstellen und auf diese API einschränken. 3. Key hier speichern. "
                         "Der Key gilt botweit und sollte ausschließlich für diesen Bot verwendet werden.")
    youtube += ui.form(BASE, ui.field("YouTube-API-Key", ui.text_input("youtube_api_key", "", type="password", attrs=password))
                       + ui.save_row("YouTube-Zugang speichern"), csrf=csrf,
                       hidden={"form": "credentials", "provider": "youtube", "guild": guild.id}, attrs={"autocomplete": "off"})
    youtube += _youtube_notice(ui)
    youtube += "<p class='wc-muted'>Der Bot reserviert höchstens 80 Live-Suchen pro Tag. " \
               "<a href='https://developers.google.com/youtube/data/determine_quota_cost' target='_blank' " \
               "rel='noopener noreferrer'>YouTube-Quotas</a></p>"
    return ui.callout("<b>Optional für zusätzliche API-Kanäle:</b> Die automatische Rollen-Erkennung funktioniert ohne diese Zugangsdaten.") \
        + ui.callout("<b>Botweite Zugangsdaten:</b> Sie gelten für alle Server. Gespeicherte Werte werden hier niemals "
                       "angezeigt; die leeren Felder dienen ausschließlich zum Ersetzen.") + ui.card(
        "Twitch", twitch, icon="bi-twitch", actions=ui.badge("Eingerichtet" if twitch_ready else "Fehlt", "ok" if twitch_ready else "warn")) \
        + ui.card("YouTube", youtube, icon="bi-youtube", actions=ui.badge("Eingerichtet" if youtube_ready else "Fehlt", "ok" if youtube_ready else "warn"))
