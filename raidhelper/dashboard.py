"""WebCore-Dashboard für den RaidHelper-Cog.

Aufgaben (gleiches Muster wie tickets/dashboard.py):
* GET                     -> Seite mit Reitern: Events · Einstellungen · Texte · Spec-Icons
* GET ?event=<id>         -> Roster eines Events (read-only)
* POST form=settings      -> Einstellungen speichern  (Post/Redirect/Get)
* POST form=action        -> Event schließen/öffnen/löschen
* POST form=icons         -> Spec-Icons hochladen/entfernen (nur Bot-Owner)

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``) – kein
eigenes CSS. Datumsangaben werden in der Server-Zeitzone gerendert (kein
Discord-``<t:>`` im Web).
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from . import games
from .embed import signup_counts
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS, role_name

_EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_]+):(\d+)>")


def _emoji_img(emoji_str) -> str | None:
    """CDN-Bild-URL aus einem Custom-Emoji-String '<:name:id>' / '<a:name:id>'."""
    if not emoji_str:
        return None
    m = _EMOJI_RE.fullmatch(str(emoji_str).strip())
    if not m:
        return None
    ext = "gif" if m.group(1) == "a" else "png"
    return f"https://cdn.discordapp.com/emojis/{m.group(3)}.{ext}"


_STATUS_LABEL_DE = {
    "bench": "Bank", "late": "Spät", "tentative": "Vielleicht", "absence": "Abwesend",
}
_STATUS_ICON = {
    "bench": "bi-hourglass-split", "late": "bi-clock-history", "tentative": "bi-question-circle",
    "absence": "bi-x-circle",
}

# Beschriftung + Hilfe der überschreibbaren Texte (Schlüssel aus strings.OVERRIDABLE_KEYS)
_OVERRIDE_LABELS = {
    "embed_no_signups": ("Leeres Roster", "Steht im Event, solange sich noch niemand angemeldet hat."),
    "reminder": ("Erinnerung im Kanal",
                 "Platzhalter: <code>{title}</code> (Event), <code>{rel}</code> (z. B. „in 15 Minuten“), "
                 "<code>{signups}</code> (Anzahl Anmeldungen)."),
}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _one_id(value):
    return int(value) if value and str(value).isdigit() else None


def _fmt(ts: int | None, tz_name: str) -> str:
    if not ts:
        return "—"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m.%Y %H:%M")


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


async def _visible_guilds(cog, request):
    """Nur die für den eingeloggten User sichtbaren Server (WebCore-Rechtemodell)."""
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


def _guild_bar(ui, guilds, guild, request) -> str:
    """Cog-eigene Server-Auswahl – nur ohne globalen WebCore-Server-Wechsler."""
    if request.get("wc_switcher"):
        return ""
    return ui.form(
        "/cogs/raidhelper",
        ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
        csrf="", method="get",
    )


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(cog, request)
    guild = _selected_guild(guilds, request)
    if guild is None:
        return {"title": "Raidplaner",
                "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    tz_name = conf.get("timezone", "Europe/Berlin")
    events = conf.get("events") or {}
    bar = _guild_bar(ui, guilds, guild, request)

    # Roster-Detailansicht?
    sel_event = request.query.get("event")
    if sel_event and sel_event in events:
        return {"title": "Raidplaner · Roster",
                "content": bar + _render_roster(ui, events[sel_event], guild.id, tz_name)}

    now = int(datetime.now(tz=timezone.utc).timestamp())
    upcoming = sum(1 for e in events.values() if (e.get("start_ts") or 0) >= now)
    total_signups = sum(signup_counts(e)[0] for e in events.values())

    head = ui.hero(
        "bi-calendar-event", "",
        "Events legst du in Discord mit <code>[p]raid create</code> an – Mitglieder melden sich dort per "
        "Button mit Klasse und Spezialisierung an. Hier siehst du alle Events samt Roster und stellst "
        "Sprache, Kanal, Zeitzone und Erinnerungen ein.",
    ) + ui.stats([
        ("Kommende Events", upcoming, "bi-calendar-event", None, "ok" if upcoming else None),
        ("Events gesamt", len(events), "bi-collection", f"Standard-Spiel: {games.game_label(conf.get('default_game'))}", None),
        ("Anmeldungen", total_signups, "bi-person-check", "über alle Events", None),
        ("Erinnerungen", "an" if conf.get("reminders") else "aus", "bi-bell",
         "60 & 15 Min. vor Start", "ok" if conf.get("reminders") else None),
    ])

    # Spec-Icons sind Application Emojis und gelten botweit -> nur Owner/Allowlist.
    webcore = request.app.get("webcore")
    full = await webcore.has_full_scope(request) if webcore is not None else True
    spec_emojis = await cog._spec_emojis()
    if full:
        icons = _render_icons(ui, csrf, guild.id, spec_emojis, cog._supports_app_emojis(),
                              cog._known_spec_structure())
    else:
        icons = ui.card(body=ui.empty(
            "bi-lock", "Nur für den Bot-Owner",
            "Spec-Icons gelten botweit (für alle Server) und können nur vom Bot-Owner verwaltet werden."))

    body = (
        ui.tab("events", "Events", "bi-calendar-event",
               _render_events(ui, conf, events, guild, tz_name, csrf, now), count=len(events))
        + _render_settings(ui, guild, conf, tz_name, csrf)
        + ui.tab("icons", "Spec-Icons", "bi-person-badge", icons, count=len(spec_emojis) if full else None)
    )
    return {"title": "Raidplaner", "content": bar + head + body}


def _render_settings(ui, guild, conf, tz_name, csrf) -> str:
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]

    general = ui.card("Allgemein", ui.grid(
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf.get("language", "de")),
                 help="Sprache der Event-Nachrichten, Buttons und Erinnerungen."),
        ui.field("Standard-Spiel", ui.select("default_game", games.list_games(), conf.get("default_game")),
                 help="Wird bei <code>[p]raid create</code> verwendet (Klassen, Specs und Rollen)."),
        ui.field("Anmelde-Kanal", ui.select("signup_channel", text_items, conf.get("signup_channel"),
                                            none_label="— kein Kanal —"),
                 help="Standard-Kanal, in dem neue Events gepostet werden."),
        ui.field("Zeitzone", ui.text_input("timezone", tz_name, placeholder="Europe/Berlin"),
                 help="IANA-Name wie <code>Europe/Berlin</code> – gilt für Datumseingaben und Zeiten hier. "
                      "Ungültige Werte werden ignoriert."),
    ), icon="bi-gear", desc="Grundeinstellungen für neue Events auf diesem Server.")

    reminders = ui.card("Erinnerungen", "<div class='wc-switches'>"
        + ui.switch("reminders", "Erinnerungen senden", conf.get("reminders"),
                    desc="60 und 15 Minuten vor dem Start im Event-Kanal.")
        + ui.switch("ping_signed_up", "Angemeldete per DM erinnern", conf.get("ping_signed_up"),
                    desc="Zusätzlich eine Direktnachricht an alle im Roster und Verspäteten.")
        + "</div>", icon="bi-bell")

    overrides = conf.get("messages") or {}
    fields = []
    for key in OVERRIDABLE_KEYS:
        label, hint = _OVERRIDE_LABELS.get(key, (key, None))
        fields.append(ui.field(label, ui.text_input(f"ovr_{key}", overrides.get(key, ""),
                                                    placeholder=STRINGS["de"].get(key, "")),
                               help=hint, wide=True))
    texts = ui.card("Eigene Texte", ui.grid(*fields), icon="bi-chat-left-text",
                    desc="Leer lassen = Standardtext der gewählten Sprache (als grauer Platzhalter sichtbar).")

    save = ui.save_row("Einstellungen speichern")
    # Ein Formular über zwei Reiter (Einstellungen + Texte) – beide speichern alles.
    return ui.form(
        "/cogs/raidhelper",
        ui.tab("einstellungen", "Einstellungen", "bi-sliders", general + reminders + save)
        + ui.tab("texte", "Texte", "bi-chat-left-text", texts + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _render_events(ui, conf, events: dict, guild, tz_name: str, csrf: str, now: int) -> str:
    hint = ""
    if not conf.get("signup_channel"):
        hint = ui.callout("Kein <b>Anmelde-Kanal</b> gesetzt – <code>[p]raid create</code> braucht einen "
                          "(Reiter „Einstellungen“) oder du nutzt <code>[p]raid quickcreate</code> mit Kanal.",
                          tone="warn")
    if not events:
        return hint + ui.card(body=ui.empty(
            "bi-calendar-x", "Für diesen Server sind keine Events gespeichert.",
            "Lege in Discord mit <code>[p]raid create 13.06.2026 20:00 Titel</code> ein Event an."))

    rows = []
    for e in sorted(events.values(), key=lambda x: x.get("start_ts", 0)):
        total, roster = signup_counts(e)
        eid = e["id"]
        closed = bool(e.get("closed"))
        past = (e.get("start_ts") or 0) < now
        hidden = {"form": "action", "guild": guild.id, "event_id": eid}
        roster_btn = ui.button("Roster", icon="bi-people", kind="ghost", small=True,
                               href=f"/cogs/raidhelper?guild={guild.id}&event={quote(str(eid))}")
        toggle = ui.form(
            "/cogs/raidhelper",
            ui.button("Öffnen" if closed else "Schließen", icon="bi-unlock" if closed else "bi-lock",
                      kind="ghost", small=True,
                      attrs={"title": "Anmeldung wieder öffnen" if closed else "Anmeldung schließen"}),
            csrf=csrf, hidden={**hidden, "action": "reopen" if closed else "close"},
        )
        delete = ui.form(
            "/cogs/raidhelper",
            ui.button("", icon="bi-trash", kind="danger", small=True, attrs={"title": "Event löschen"}),
            csrf=csrf, hidden={**hidden, "action": "delete"},
            confirm=f"Event „{e.get('title') or eid}“ und seine Discord-Nachricht werden gelöscht.",
        )
        cap = e.get("max_signups")
        roster_txt = f"{roster} / {int(cap)}" if cap else str(roster)
        status = ui.badge("geschlossen", "muted") if closed else ui.badge("offen", "ok")
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(e.get('title') or '—')}</div>"
            f"<div class='wc-cell-sub'><span class='mono'>{_esc(eid)}</span> · {_esc(games.game_label(e.get('game')))}</div>",
            f"<span class='mono'>{_esc(_fmt(e.get('start_ts'), tz_name))}</span>"
            + ("<div class='wc-cell-sub'>vorbei</div>" if past else ""),
            f"<span class='mono'>{_esc(roster_txt)}</span>"
            f"<div class='wc-cell-sub'>{total} Rückmeldung{'' if total == 1 else 'en'}</div>",
            status,
            f"><div class='wc-row-actions'>{roster_btn}{toggle}{delete}</div>",
        ))
    table = ui.card(
        "Events", ui.table(["Event", "Start", "Im Roster", "Status", ">"], rows,
                           search=True, search_placeholder="Nach Titel, ID oder Spiel suchen …", id="rh-events"),
        icon="bi-calendar-event",
        desc=f"Zeiten in der Zeitzone <b>{_esc(tz_name)}</b>. „Schließen“ beendet nur die Anmeldung, "
             "das Event bleibt bestehen.",
    )
    return hint + table


def _render_icons(ui, csrf: str, guild_id: int, emojis: dict, supported: bool, structure) -> str:
    rows = []
    for cid, clabel, specs in structure:
        for sid, slabel in specs:
            cur = emojis.get(f"{cid}:{sid}")
            img = _emoji_img(cur)
            if img:
                cell = f"<img src='{_esc(img)}' width='24' height='24' alt='{_esc(slabel)}'>"
            elif cur:
                cell = f"<span class='mono'>{_esc(cur)}</span>"
            else:
                cell = "<span class='wc-muted'>—</span>"
            rows.append(ui.row(
                f"<div class='wc-cell-title'>{_esc(slabel)}</div><div class='wc-cell-sub'>{_esc(clabel)}</div>",
                f"<span class='mono wc-muted'>{_esc(cid)}_{_esc(sid)}</span>",
                cell,
                f"><label class='wc-muted'><input type='checkbox' name='remove_{_esc(cid)}_{_esc(sid)}'> entfernen</label>",
            ))

    warning = ""
    if not supported:
        warning = ui.callout(
            "Dieser Bot unterstützt keine Application-Emojis (discord.py &lt; 2.4). Der Upload funktioniert nicht – "
            "bitte Red aktualisieren oder Icons per Befehl <code>[p]raidset specicon</code> setzen.", tone="bad")
    file_attrs = " disabled" if not supported else ""
    upload = ui.card("Icons hochladen", warning + ui.field(
        "Bilddateien (mehrere möglich)",
        f"<input class='wc-input' type='file' name='icons' accept='image/png,image/gif,image/jpeg' multiple{file_attrs}>",
        help="Dateiname = <code>klasse_spec</code>, z. B. <code>krieger_furor.png</code>. Pro Datei max. 256&nbsp;KB, "
             "insgesamt möglichst unter 1&nbsp;MB. Unbekannte Namen werden übersprungen.",
    ) + ui.save_row("Hochladen & Änderungen speichern"), icon="bi-upload",
        desc="Icons gelten <b>botweit</b> (Application Emojis) für jede Spezialisierung – auf allen Servern.")

    table = ui.card("Aktuelle Icons", ui.table(
        ["Spezialisierung", "Dateiname", "Icon", ">Entfernen"], rows,
        search=True, search_placeholder="Klasse oder Spec suchen …", id="rh-icons",
    ) + ui.save_row("Hochladen & Änderungen speichern"), icon="bi-grid-3x3-gap",
        desc="Zum Entfernen Haken setzen und speichern.")

    # ui.form() kennt kein enctype -> Formular-Tag selbst schreiben (Datei-Upload). Ohne Speicherleiste:
    # deren Serialisierung hält <input type=file multiple> für ein Mehrfach-Select (JS-Fehler).
    return (
        "<form class='wc-form' method='post' action='/cogs/raidhelper' enctype='multipart/form-data'>"
        f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
        "<input type='hidden' name='form' value='icons'>"
        f"<input type='hidden' name='guild' value='{_esc(guild_id)}'>"
        + upload + table + "</form>"
    )


def _render_roster(ui, event: dict, guild_id: int, tz_name: str) -> str:
    game_id = event.get("game") or games.DEFAULT_GAME
    signups = event.get("signups") or {}
    ordered = sorted(signups.items(), key=lambda kv: (kv[1].get("at") or 0, kv[0]))

    by_role = {r: [] for r in games.role_order(game_id)}
    by_status = {s: [] for s in _STATUS_LABEL_DE}
    for _uid, e in ordered:
        st = e.get("status") or "signed"
        spec = games.spec_label(game_id, e.get("class"), e.get("spec")) if e.get("class") else ""
        entry = (_esc(e.get("name")), _esc(spec))
        if st == "signed":
            role = e.get("role") or games.spec_role(game_id, e.get("class"), e.get("spec"))
            by_role.setdefault(role, []).append(entry)
        elif st in by_status:
            by_status[st].append(entry)

    def _list(entries) -> str:
        if not entries:
            return "<div class='wc-muted'>Noch niemand.</div>"
        items = "".join(
            f"<li><span class='mono wc-muted'>{i}.</span><span>{name}</span>"
            + (f"<span class='wc-muted'>{spec}</span>" if spec else "") + "</li>"
            for i, (name, spec) in enumerate(entries, 1)
        )
        return f"<ul class='wc-list'>{items}</ul>"

    role_cards = []
    for role in games.role_order(game_id):
        meta = games.role_meta(game_id, role)
        people = by_role.get(role, [])
        title = f"{meta.get('emoji', '')} {role_name('de', role)}".strip()
        role_cards.append(ui.card(f"{title} ({len(people)})", _list(people)))

    status_cards = [
        ui.card(f"{label} ({len(by_status[st])})", _list(by_status[st]), icon=_STATUS_ICON.get(st))
        for st, label in _STATUS_LABEL_DE.items() if by_status.get(st)
    ]

    total, roster = signup_counts(event)
    cap = event.get("max_signups")
    back = ui.button("Zurück zu den Events", icon="bi-arrow-left", kind="ghost", small=True,
                     href=f"/cogs/raidhelper?guild={guild_id}#events")
    status = "geschlossen" if event.get("closed") else "Anmeldung offen"
    # Zurück-Button im Kopftext (ui.hero(actions=…) bricht auf dem Handy nicht um).
    head = ui.hero(
        "bi-people", event.get("title") or "Event",
        f"<span class='mono'>{_esc(event.get('id'))}</span> · {_esc(games.game_label(game_id))} · "
        f"{_esc(_fmt(event.get('start_ts'), tz_name))} · {_esc(status)}<br><br>{back}",
    ) + ui.stats([
        ("Im Roster", f"{roster} / {int(cap)}" if cap else roster, "bi-people", None, "ok" if roster else None),
        ("Rückmeldungen", total, "bi-person-lines-fill", "inkl. Bank, Spät, Vielleicht, Abwesend", None),
    ])
    out = head + ui.columns(*role_cards, cols=2)
    if status_cards:
        out += "<h3 class='wc-sub'>Weitere Rückmeldungen</h3>" + ui.columns(*status_cards, cols=2)
    return out


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guilds = await _visible_guilds(cog, request)
    guild = None
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                guild = g
                break
    if guild is None:
        raise web.HTTPFound("/cogs/raidhelper?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)
        game = data.get("default_game") or games.DEFAULT_GAME
        if games.get_game(game) is not None:
            await gconf.default_game.set(game)
        await gconf.signup_channel.set(_one_id(data.get("signup_channel")))
        tz = (data.get("timezone") or "Europe/Berlin").strip()
        try:
            ZoneInfo(tz)
            await gconf.timezone.set(tz)
        except (ZoneInfoNotFoundError, ValueError):
            pass
        await gconf.reminders.set("reminders" in data)
        await gconf.ping_signed_up.set("ping_signed_up" in data)
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)
        raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Gespeichert")

    if form == "action":
        event_id = data.get("event_id")
        action = data.get("action")
        async with gconf.events() as events:
            event = events.get(event_id)
            if event is None:
                raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Event+nicht+gefunden")
            if action in ("close", "reopen"):
                event["closed"] = action == "close"
                events[event_id] = event
                snapshot = dict(event)
            elif action == "delete":
                snapshot = events.pop(event_id, None)
            else:
                snapshot = None
        if action in ("close", "reopen") and snapshot:
            await cog.refresh_event_message(guild, snapshot)
            raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Aktualisiert")
        if action == "delete" and snapshot:
            if snapshot.get("channel_id") and snapshot.get("message_id"):
                channel = guild.get_channel(snapshot["channel_id"])
                if channel is not None:
                    try:
                        msg = await channel.fetch_message(snapshot["message_id"])
                        await msg.delete()
                    except Exception:  # noqa: BLE001
                        pass
            raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=Gel%C3%B6scht")

    if form == "icons":
        webcore = request.app.get("webcore")
        if webcore is not None and not await webcore.has_full_scope(request):
            raise web.HTTPFound(
                f"/cogs/raidhelper?guild={guild.id}&ok=" + quote("Spec-Icons darf nur der Bot-Owner ändern")
            )
        pairs = cog._known_pair_set()  # {(class_id, spec_id), …}
        removed = 0
        for cid, sid in list(pairs):
            if f"remove_{cid}_{sid}" in data:
                await cog._delete_spec_emoji(cid, sid)
                removed += 1
        unsupported = not cog._supports_app_emojis()
        files = [] if unsupported else data.getall("icons", [])
        ok = skipped = 0
        for field in files:
            filename = getattr(field, "filename", "") or ""
            fileobj = getattr(field, "file", None)
            if not filename or fileobj is None:
                continue
            stem = filename.rsplit(".", 1)[0].lower()
            parts = stem.split("_", 1)  # IDs sind unterstrichfrei -> erster "_" trennt Klasse/Spec
            if len(parts) != 2 or (parts[0], parts[1]) not in pairs:
                skipped += 1
                continue
            cid, sid = parts
            try:
                fileobj.seek(0)
                raw = fileobj.read()
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            if not raw or len(raw) > 256 * 1024:
                skipped += 1
                continue
            try:
                await cog._set_spec_emoji_from_bytes(cid, sid, raw)
                ok += 1
            except Exception:  # noqa: BLE001
                skipped += 1
        if unsupported and data.getall("icons", []):
            raise web.HTTPFound(
                f"/cogs/raidhelper?guild={guild.id}&ok=" + quote("Application-Emojis werden nicht unterstützt")
            )
        msg = f"{ok} Icon(s) gesetzt, {removed} entfernt, {skipped} übersprungen"
        raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=" + quote(msg))

    raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}")
