"""WebCore-Dashboard für den RaidHelper-Cog.

Aufgaben (gleiches Muster wie tickets/dashboard.py):
* GET                     -> Seite mit Reitern: Events · Einstellungen · Texte · Launcher & Website · Spec-Icons
* GET ?event=<id>         -> Roster eines Events (read-only)
* GET ?edit=<id>          -> Event bearbeiten (Formular)
* POST form=create        -> Neues Event anlegen + posten (dieselbe Funktion wie ``[p]raid create``)
* POST form=edit          -> Event ändern + Discord-Nachricht bearbeiten (``RaidHelper.update_event``)
* POST form=settings      -> Einstellungen speichern  (Post/Redirect/Get)
* POST form=action        -> Event schließen/öffnen/löschen/neu posten (``RaidHelper.repost_event``)
* POST form=icons         -> Spec-Icons hochladen/entfernen (nur Bot-Owner)

Rechte: ``create``/``edit``/``action`` sind Tagesgeschäft (Stufe „Bedienen“ reicht, siehe
``register_page(operate_forms=…)``), ``settings`` braucht „Bearbeiten“, ``icons`` den Bot-Owner.

Die Mitglieder-Seite „Raids“ (``/me/raids``) liegt in ``member.py``, die öffentliche API in ``public.py``.

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``) – kein
eigenes CSS. Datumsangaben werden in der Server-Zeitzone gerendert (kein
Discord-``<t:>`` im Web).
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from . import games
from .embed import signup_counts
from .public import build_payload as build_public_payload, public_base
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS, role_name, t

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


def _tz(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _fmt(ts: int | None, tz_name: str) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, _tz(tz_name)).strftime("%d.%m.%Y %H:%M")


def _tz_label(tz_name: str) -> str:
    """'Europe/Berlin (UTC+02:00)' – aktueller Versatz der Server-Zeitzone."""
    off = datetime.now(_tz(tz_name)).strftime("%z")
    off = f"UTC{off[:3]}:{off[3:]}" if off else "UTC"
    return f"{tz_name} ({off})"


def _date_time(ts: int | None, tz_name: str) -> tuple[str, str]:
    """(YYYY-MM-DD, HH:MM) in der Server-Zeitzone – Werte für <input type=date/time>."""
    if not ts:
        return "", ""
    dt = datetime.fromtimestamp(ts, _tz(tz_name))
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _plain(text: str) -> str:
    """Discord-Markdown aus Meldungen für den Toast entfernen."""
    return text.replace("`", "").replace("**", "")


# Rückmeldungen für Eingabefehler: Discord-Texte aus strings.py (deutsch), außer wo der
# Befehlstext auf Discord-Befehle verweist.
_DASH_ERR_KEYS = {"create_no_channel": "dash_no_channel"}


def _err_text(err) -> str:
    return _plain(t("de", _DASH_ERR_KEYS.get(err.key, err.key), **err.kwargs))


_RECURRENCE = [("none", "Einmalig"), ("daily", "Täglich"), ("weekly", "Wöchentlich"),
               ("biweekly", "Alle zwei Wochen")]


def _all_roles() -> list[str]:
    """Rollen-IDs aller Spiele (Reihenfolge wie im ersten Spiel) – für die Limit-Felder."""
    out: list[str] = []
    for gid, _label in games.list_games():
        for role in games.role_order(gid):
            if role not in out:
                out.append(role)
    return out


# ----- Formulareingaben nach einem Fehler (Post/Redirect/Get ohne Datenverlust) ----- #
# Gespeichert im RAM des Cogs, Schlüssel = CSRF-Token der Sitzung (nur dieselbe Sitzung sieht sie).
_DRAFT_TTL = 900
_DRAFT_MAX = 200
_DRAFT_FIELDS = ("title", "description", "game", "channel", "date", "time", "deadline_date",
                 "deadline_time", "recurrence", "max_signups")


def _draft_key(request, kind: str) -> str:
    return f"{request.get('webcore_csrf', '')}|{kind}"


def _save_draft(cog, request, kind: str, data) -> None:
    drafts = cog.__dict__.setdefault("_dash_drafts", {})
    now = time.monotonic()
    for key in [k for k, (ts, _v) in drafts.items() if now - ts > _DRAFT_TTL]:
        drafts.pop(key, None)
    while len(drafts) >= _DRAFT_MAX:
        drafts.pop(next(iter(drafts)))
    values = {k: str(data.get(k) or "")[:4000] for k in _DRAFT_FIELDS if data.get(k) is not None}
    values.update({k: str(v)[:10] for k, v in data.items() if k.startswith("limit_")})
    drafts[_draft_key(request, kind)] = (now, values)


def _load_draft(cog, request, kind: str) -> dict:
    if request.query.get("draft") != "1":
        return {}
    item = cog.__dict__.get("_dash_drafts", {}).get(_draft_key(request, kind))
    if not item or time.monotonic() - item[0] > _DRAFT_TTL:
        return {}
    return item[1]


async def _author_id(cog, request) -> int:
    """Discord-ID des eingeloggten Dashboard-Nutzers (wird Raidleitung des neuen Events)."""
    webcore = request.app.get("webcore")
    getter = getattr(webcore, "current_user", None) or getattr(webcore, "_get_user", None)
    user = await getter(request) if getter else None
    if user and str(user.get("id", "")).isdigit():
        return int(user["id"])
    return cog.bot.user.id


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
    # Bearbeiten-Ansicht?
    edit_id = request.query.get("edit")
    if edit_id and isinstance(events.get(edit_id), dict):
        draft = _load_draft(cog, request, f"edit:{edit_id}")
        return {"title": "Raidplaner · Event bearbeiten",
                "content": bar + _render_edit(ui, guild, conf, events[edit_id], tz_name, csrf, draft)}

    now = int(datetime.now(tz=timezone.utc).timestamp())
    upcoming = sum(1 for e in events.values() if (e.get("start_ts") or 0) >= now)
    total_signups = sum(signup_counts(e)[0] for e in events.values())

    head = ui.hero(
        "bi-calendar-event", "",
        "Lege Events im Reiter „Neues Event“ oder in Discord mit <code>[p]raid create</code> an – der Bot "
        "postet sie mit Anmelde-Buttons, Mitglieder melden sich dort mit Klasse und Spezialisierung an. "
        "Hier siehst und bearbeitest du alle Events samt Roster und stellst Sprache, Kanal, Zeitzone und "
        "Erinnerungen ein.",
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
        + ui.tab("neu", "Neues Event", "bi-calendar-plus",
                 _render_create(ui, guild, conf, tz_name, csrf, _load_draft(cog, request, "create")))
        + _render_settings(ui, guild, conf, tz_name, csrf, portal=await _portal_state(request, guild),
                           public=await public_base(request))
        + ui.tab("icons", "Spec-Icons", "bi-person-badge", icons, count=len(spec_emojis) if full else None)
    )
    return {"title": "Raidplaner", "content": bar + head + body}


async def _portal_state(request, guild) -> bool | None:
    """Ist WebCores „Mein Bereich“ auf diesem Server an? ``None`` = unbekannt (ältere WebCore)."""
    webcore = request.app.get("webcore")
    if webcore is None or not hasattr(webcore, "register_member_page"):
        return None
    try:
        portal = await webcore.config.member_portal() or {}
    except Exception:  # noqa: BLE001
        return None
    return bool(portal.get(str(guild.id)))


def _render_public(ui, guild, conf, base: str, public_host: bool) -> str:
    """Karte „Für Launcher & Website freigeben“ (Schalter + URL + Beispiel) – wie beim Changelog."""
    json_url = f"{base}/api/public/raids/{guild.id}"
    inp = ui.text_input("", json_url, attrs={"readonly": True, "onclick": "this.select()"})
    copy = ui.button("", icon="bi-clipboard", kind="ghost", type="button",
                     attrs={"title": "Kopieren", "onclick": "navigator.clipboard&&navigator.clipboard.writeText("
                            "this.previousElementSibling.value);this.querySelector('i').className='bi bi-check2'"})
    example = build_public_payload(guild, conf, limit=1)
    if not example["events"]:
        example["events"] = [{
            "id": "r1", "title": "Mythic Undermine", "game": "WoW – Retail",
            "start": "2026-10-01T18:00:00Z", "deadline": None, "signups": 14, "max": 20, "full": False,
            "roles": {"tank": {"label": "Tanks", "emoji": "🛡️", "signups": 2, "max": 2},
                      "healer": {"label": "Heiler", "emoji": "✚", "signups": 3, "max": 4}},
            "other": {"bench": 1, "late": 0, "tentative": 2, "absence": 0},
            "closed": False, "url": f"https://discord.com/channels/{guild.id}/123/456",
        }]
    example_json = json.dumps(example, ensure_ascii=False, indent=2)
    state = ui.badge("freigegeben", "ok") if conf.get("public_api") else ui.badge("aus", "muted")
    hint = ui.callout(
        "Damit ein Launcher oder eine Website die Daten abrufen kann, muss das Dashboard <b>öffentlich erreichbar</b> "
        "sein (Reverse-Proxy mit HTTPS, siehe WebCore-README). Ohne Freigabe – oder für unbekannte Server – antwortet "
        "die Adresse mit <code>404</code>. Die Adresse ist <b>für jeden abrufbar</b>: ausgegeben werden nur kommende "
        "Events aus Kanälen, die <b>@everyone</b> sehen darf, mit Titel, Spiel, Termin und Belegung als Zahlen – "
        "keine Namen oder IDs von Mitgliedern.",
        tone="info" if public_host else "warn",
    )
    if not public_host:
        hint += ui.callout(
            f"Die Adresse unten stammt von <code>{_esc(base)}</code> – das sieht nicht nach einer öffentlichen "
            "HTTPS-Adresse aus. Trage in WebCore die öffentliche Redirect-URI ein, dann stimmt der Link.", tone="warn")
    body = (
        ui.switches(ui.switch("public_api", "Kommende Raids öffentlich abrufbar machen", conf.get("public_api"),
                              desc="JSON-Schnittstelle für diesen Server freigeben (Standard: aus)."))
        + ui.divider()
        + ui.field("JSON-Adresse", f"<div class='wc-input-group'>{inp}{copy}</div>",
                   help="Parameter: <code>?limit=1–50</code> (Standard 10). Antwort wird bis zu 60 Sekunden "
                        "zwischengespeichert.")
        + hint
        + ui.field("Beispiel-Antwort",
                   f"<textarea class='wc-input mono' rows='16' readonly>{_esc(example_json)}</textarea>",
                   help="Nächstes öffentliches Event dieses Servers (bzw. ein Beispiel, solange es keines gibt).")
    )
    return ui.card("Für Launcher & Website freigeben", body, icon="bi-broadcast", actions=state,
                   desc="Öffentliche Schnittstelle, mit der z. B. dein Launcher die nächsten Raids anzeigt.")


def _render_settings(ui, guild, conf, tz_name, csrf, *, portal: bool | None = None,
                     public: tuple[str, bool] | None = None) -> str:
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

    if portal is None:
        portal_note = ui.callout("Diese WebCore-Version hat noch keinen Mitglieder-Bereich.", tone="warn")
    else:
        portal_note = ui.callout(
            "Der Mitglieder-Bereich selbst ist auf diesem Server <b>"
            + ("eingeschaltet" if portal else "ausgeschaltet") + "</b>. Der Bot-Owner schaltet ihn unter "
            "<b>Verwaltung → Zugriff &amp; Rollen</b> (Karte „Mitglieder-Bereich“) oder mit "
            "<code>[p]webcore portal on</code> ein.", tone="info" if portal else "warn")
    member_card = ui.card("Mitglieder-Bereich", ui.switches(
        ui.switch("member_page", "Im Mitglieder-Bereich anzeigen", conf.get("member_page", True),
                  desc="Mitglieder sehen unter „Mein Bereich → Raids“ die kommenden Events aus Kanälen, die sie "
                       "lesen dürfen, und melden sich dort an – mit denselben Regeln wie über die Buttons.")
    ) + portal_note, icon="bi-person-badge")

    cleanup = ui.card("Aufräumen", ui.grid(
        ui.field("Abgeschlossene Events löschen nach",
                 ui.number("cleanup_days", conf.get("cleanup_days", 30), min=0, max=3650, unit="Tage"),
                 help="Events, deren Termin länger als so viele Tage vorbei ist, verschwinden aus der Liste. "
                      "Nur die gespeicherten Daten werden gelöscht – die Nachricht in Discord bleibt stehen, "
                      "ihre Buttons melden dann „Event existiert nicht mehr“. Wiederholungsserien bleiben "
                      "erhalten. <b>0</b> = nie löschen."),
    ), icon="bi-trash3", desc="Hält die Event-Liste schlank. Läuft automatisch etwa stündlich.")

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
        ui.tab("einstellungen", "Einstellungen", "bi-sliders",
                 general + reminders + member_card + cleanup + save)
        + ui.tab("texte", "Texte", "bi-chat-left-text", texts + save)
        + ui.tab("launcher", "Launcher & Website", "bi-broadcast",
                 _render_public(ui, guild, conf, *(public or ("", False))) + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _message_missing(guild, event: dict) -> bool:
    """Fehlt die Discord-Nachricht des Events (nie gepostet/Posten fehlgeschlagen, gelöscht, Kanal weg)?

    Gelöschte Nachrichten merkt sich der Cog über ``on_raw_message_delete`` bzw. beim Aktualisieren
    (``message_id`` -> ``None``) – hier also keine Discord-Anfrage pro Event.
    """
    if not event.get("message_id"):
        return True
    return not event.get("channel_id") or guild.get_channel(event["channel_id"]) is None


def _render_events(ui, conf, events: dict, guild, tz_name: str, csrf: str, now: int) -> str:
    hint = ""
    if not conf.get("signup_channel"):
        hint = ui.callout("Kein <b>Anmelde-Kanal</b> gesetzt – <code>[p]raid create</code> braucht einen "
                          "(Reiter „Einstellungen“). Im Reiter „Neues Event“ und mit "
                          "<code>[p]raid quickcreate</code> wählst du den Kanal pro Event.",
                          tone="warn")
    if not events:
        return hint + ui.card(body=ui.empty(
            "bi-calendar-x", "Für diesen Server sind keine Events gespeichert.",
            "Lege eines im Reiter „Neues Event“ an oder in Discord mit "
            "<code>[p]raid create 13.06.2026 20:00 Titel</code>.",
            action=ui.goto("Neues Event anlegen", "neu", icon="bi-calendar-plus", kind="accent", small=False)))

    rows = []
    for e in sorted(events.values(), key=lambda x: x.get("start_ts", 0)):
        total, roster = signup_counts(e)
        eid = e["id"]
        closed = bool(e.get("closed"))
        past = (e.get("start_ts") or 0) < now
        hidden = {"form": "action", "guild": guild.id, "event_id": eid}
        roster_btn = ui.button("Roster", icon="bi-people", kind="ghost", small=True,
                               href=f"/cogs/raidhelper?guild={guild.id}&event={quote(str(eid))}")
        edit_btn = ui.button("Bearbeiten", icon="bi-pencil", kind="ghost", small=True,
                             href=f"/cogs/raidhelper?guild={guild.id}&edit={quote(str(eid))}",
                             attrs={"title": "Titel, Beschreibung, Termin und Limits ändern"})
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
        repost = ""
        missing = _message_missing(guild, e)
        if missing:
            repost = ui.form(
                "/cogs/raidhelper",
                ui.button("Neu posten", icon="bi-send", kind="accent", small=True,
                          attrs={"title": "Die Event-Nachricht fehlt in Discord (gelöscht oder Posten "
                                          "fehlgeschlagen) – jetzt neu posten"}),
                csrf=csrf, hidden={**hidden, "action": "repost"},
            )
        cap = e.get("max_signups")
        roster_txt = f"{roster} / {int(cap)}" if cap else str(roster)
        status = ui.badge("geschlossen", "muted") if closed else ui.badge("offen", "ok")
        if missing:
            status += " " + ui.badge("Nachricht fehlt", "warn")
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(e.get('title') or '—')}</div>"
            f"<div class='wc-cell-sub'><span class='mono'>{_esc(eid)}</span> · {_esc(games.game_label(e.get('game')))}</div>",
            f"<span class='mono'>{_esc(_fmt(e.get('start_ts'), tz_name))}</span>"
            + ("<div class='wc-cell-sub'>vorbei</div>" if past else ""),
            f"<span class='mono'>{_esc(roster_txt)}</span>"
            f"<div class='wc-cell-sub'>{total} Rückmeldung{'' if total == 1 else 'en'}</div>",
            status,
            f"><div class='wc-row-actions'>{repost}{roster_btn}{edit_btn}{toggle}{delete}</div>",
        ))
    table = ui.card(
        "Events", ui.table(["Event", "Start", "Im Roster", "Status", ">"], rows,
                           search=True, search_placeholder="Nach Titel, ID oder Spiel suchen …", id="rh-events"),
        icon="bi-calendar-event",
        desc=f"Zeiten in der Zeitzone <b>{_esc(tz_name)}</b>. „Bearbeiten“ ändert Titel, "
             "Termin und Limits – die Discord-Nachricht wird mitgeändert. „Schließen“ beendet nur die "
             "Anmeldung, das Event bleibt bestehen. Fehlt die Nachricht in Discord (gelöscht oder Posten "
             "fehlgeschlagen), erscheint „Neu posten“ – Anmeldungen bleiben erhalten.",
        actions=ui.goto("Neues Event", "neu", icon="bi-calendar-plus", kind="accent"),
    )
    return hint + table


# --------------------------------------------------------------------------- #
#  Event anlegen / bearbeiten (gemeinsame Formularfelder)
# --------------------------------------------------------------------------- #
def _event_cards(ui, guild, conf, tz_name: str, values: dict, *, event: dict | None = None) -> str:
    """Karten „Event“, „Termin“, „Teilnehmer“. ``event`` gesetzt = Bearbeiten (Spiel/Kanal fest)."""
    v = values.get
    now_local = datetime.now(_tz(tz_name))
    completed = bool(event and event.get("completed"))

    # ---- Event
    if event is None:
        text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]
        default_ch = conf.get("signup_channel")
        game_field = ui.field(
            "Spiel / Vorlage", ui.select("game", games.list_games(), v("game") or conf.get("default_game")),
            help="Bestimmt Klassen, Spezialisierungen und Rollen im Anmelde-Menü.")
        channel_field = ui.field(
            "Anmelde-Kanal",
            ui.select("channel", text_items, v("channel") or default_ch,
                      none_label=None if default_ch else "— bitte wählen —", attrs={"required": True}),
            help="Hier postet der Bot das Event mit den Anmelde-Buttons. Vorbelegt ist der Standard-Kanal aus "
                 "„Einstellungen“. Der Bot braucht dort „Nachrichten senden“ und „Links einbetten“.")
    else:
        ch = guild.get_channel(event.get("channel_id")) if event.get("channel_id") else None
        game_field = ui.field(
            "Spiel / Vorlage", ui.text_input("_game", games.game_label(event.get("game")), attrs={"disabled": True}),
            help="Lässt sich nachträglich nicht ändern (bestehende Anmeldungen hängen daran).")
        channel_field = ui.field(
            "Anmelde-Kanal",
            ui.text_input("_channel", f"#{ch.name}" if ch is not None else "— Kanal gelöscht —",
                          attrs={"disabled": True}),
            help="Die vorhandene Nachricht wird bearbeitet – für einen anderen Kanal ein neues Event anlegen.")
    main = ui.card("Event", ui.grid(
        ui.field("Titel", ui.text_input("title", v("title", ""), placeholder="z. B. Mythic Undermine",
                                        attrs={"maxlength": 256, "required": True}), wide=True),
        ui.field("Beschreibung (optional)",
                 ui.textarea("description", v("description", ""), rows=4,
                             placeholder="Treffpunkt, Voraussetzungen, Taktik-Link …"),
                 help="Erscheint im Event-Text über dem Roster. Max. 1400 Zeichen, Discord-Formatierung "
                      "(<code>**fett**</code>, Links) funktioniert.", wide=True),
        game_field, channel_field,
    ), icon="bi-card-text")

    # ---- Termin
    date_attrs = {"required": True, "min": None if event else now_local.strftime("%Y-%m-%d")}
    time_attrs = {"required": True}
    if completed:
        date_attrs = time_attrs = {"disabled": True}
    tz_help = (f"Datum und Uhrzeit gelten in der Zeitzone des Servers: <b>{_esc(_tz_label(tz_name))}</b> "
               f"(jetzt dort {now_local.strftime('%d.%m.%Y, %H:%M')}&nbsp;Uhr). In Discord sieht jedes Mitglied "
               "den Termin automatisch in seiner eigenen Zeitzone. Die Zeitzone stellst du unter "
               "„Einstellungen“ um.")
    when = (ui.callout("Das Event ist abgeschlossen – der Termin lässt sich nicht mehr ändern.", tone="warn")
            if completed else ui.callout(tz_help, icon="bi-globe2"))
    # Auf der Bearbeiten-Seite gibt es keine Reiter -> normaler Link statt Reiter-Sprung.
    settings_link = (ui.goto("Einstellungen", "einstellungen", icon="bi-sliders") if event is None else
                     ui.button("Einstellungen", icon="bi-sliders", kind="ghost", small=True,
                               href=f"/cogs/raidhelper?guild={guild.id}#einstellungen"))
    when += ui.grid(
        ui.field("Datum", ui.text_input("date", v("date", ""), type="date", placeholder="TT.MM.JJJJ",
                                        attrs=date_attrs),
                 help="Kalender öffnen oder eintippen, z. B. <code>13.06.2026</code>."),
        ui.field("Uhrzeit (Start)", ui.text_input("time", v("time", ""), type="time", placeholder="HH:MM",
                                                  attrs=time_attrs),
                 help="24-Stunden-Format, z. B. <code>20:00</code>."),
        ui.field("Anmeldeschluss – Datum", ui.text_input("deadline_date", v("deadline_date", ""), type="date",
                                                         placeholder="TT.MM.JJJJ"),
                 help="Optional. Leer = Anmeldung bis zum Start offen."),
        ui.field("Anmeldeschluss – Uhrzeit", ui.text_input("deadline_time", v("deadline_time", ""), type="time",
                                                           placeholder="HH:MM"),
                 help="Muss vor dem Start liegen."),
        ui.field("Wiederholung", ui.select("recurrence", _RECURRENCE, v("recurrence") or "none"),
                 help="Nach dem Termin legt der Bot automatisch den nächsten an (gleiche Uhrzeit, "
                      "gleiche Limits, neue Nachricht)."),
        ui.field("Erinnerungen",
                 f"<div class='wc-help'>{'an' if conf.get('reminders') else 'aus'} – 60 und 15 Minuten vor "
                 "Start im Kanal. Gilt für alle Events dieses Servers.</div>"
                 + ui.actions(settings_link)),
    )
    termin = ui.card("Termin", when, icon="bi-clock")

    # ---- Teilnehmer
    game_id = (event or {}).get("game") or v("game") or conf.get("default_game") or games.DEFAULT_GAME
    roles = games.role_order(event["game"]) if event else _all_roles()
    limit_fields = []
    for role in roles:
        meta = games.role_meta(game_id, role) or {}
        label = f"{meta.get('emoji', '')} {role_name('de', role)}".strip()
        limit_fields.append(ui.field(
            label, ui.number(f"limit_{role}", v(f"limit_{role}", ""), min=0, max=1000, placeholder="∞",
                             unit="max.")))
    people = ui.card("Teilnehmer", ui.grid(
        ui.field("Maximale Anmeldungen", ui.number("max_signups", v("max_signups", ""), min=0, max=1000,
                                                  placeholder="unbegrenzt", unit="Plätze"),
                 help="Zählt alle im Roster (ohne Bank, Spät, Vielleicht, Abwesend). Leer oder 0 = unbegrenzt.",
                 wide=True),
        *limit_fields,
    ), icon="bi-people", desc="Rollen-Limits: höchstens so viele pro Rolle. Leer oder 0 = kein Limit.")
    return main + termin + people


def _render_create(ui, guild, conf, tz_name: str, csrf: str, draft: dict) -> str:
    hint = ""
    if not guild.text_channels:
        hint = ui.callout("Auf diesem Server gibt es keinen Textkanal, in den der Bot posten könnte.", tone="warn")
    body = hint + _event_cards(ui, guild, conf, tz_name, draft) + ui.actions(
        ui.button("Event erstellen & posten", icon="bi-send"),
        "<span class='wc-help'>Der Bot postet das Event sofort im gewählten Kanal – du wirst als Raidleitung "
        "eingetragen.</span>")
    return ui.form("/cogs/raidhelper", body, csrf=csrf, hidden={"form": "create", "guild": guild.id})


def _render_edit(ui, guild, conf, event: dict, tz_name: str, csrf: str, draft: dict) -> str:
    eid = event.get("id")
    start = event.get("start_ts")
    deadline = event.get("deadline_ts")
    d, tm = _date_time(start, tz_name)
    dd, dt = ("", "") if not deadline or deadline == start else _date_time(deadline, tz_name)
    values = {
        "title": event.get("title") or "", "description": event.get("description") or "",
        "date": d, "time": tm, "deadline_date": dd, "deadline_time": dt,
        "recurrence": event.get("recurrence") or "none",
        "max_signups": event.get("max_signups") or "",
        **{f"limit_{r}": n for r, n in (event.get("role_limits") or {}).items()},
    }
    values.update(draft)
    back = ui.button("Zurück zu den Events", icon="bi-arrow-left", kind="ghost", small=True,
                     href=f"/cogs/raidhelper?guild={guild.id}#events")
    msg_note = ("Beim Speichern wird die vorhandene Event-Nachricht in Discord aktualisiert – Anmeldungen "
                "bleiben erhalten." if event.get("message_id") else
                "Zu diesem Event gibt es keine Discord-Nachricht (Posten war fehlgeschlagen).")
    head = ui.hero(
        "bi-pencil-square", event.get("title") or "Event",
        f"<span class='mono'>{_esc(eid)}</span> · {_esc(games.game_label(event.get('game')))} · "
        f"{_esc(_fmt(start, tz_name))} · {_esc(msg_note)}<br><br>{back}",
    )
    body = _event_cards(ui, guild, conf, tz_name, values, event=event) + ui.save_row(
        "Speichern & Nachricht aktualisieren")
    return head + ui.form("/cogs/raidhelper", body, csrf=csrf, savebar=True,
                          hidden={"form": "edit", "guild": guild.id, "event_id": eid})


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
        raise web.HTTPFound("/cogs/raidhelper?err=Server+nicht+gefunden")

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
        await gconf.member_page.set("member_page" in data)
        await gconf.public_api.set("public_api" in data)
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)
        raw_days = (data.get("cleanup_days") or "").strip()
        try:
            days = int(raw_days) if raw_days else 30
        except ValueError:
            days = -1
        if not 0 <= days <= 3650:
            raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&err="
                                + quote("Gespeichert – aber „Löschen nach“ muss zwischen 0 und 3650 Tagen liegen"))
        await gconf.cleanup_days.set(days)
        removed = await cog.cleanup_old_events(guild) if days else []
        msg = "Gespeichert" + (f" – {len(removed)} alte Events gelöscht" if removed else "")
        raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=" + quote(msg))

    if form == "create":
        return await _post_create(cog, request, guild, data)

    if form == "edit":
        return await _post_edit(cog, request, guild, data)

    if form == "action" and data.get("action") == "repost":
        # Gleiche Rechte wie die anderen Event-Aktionen (Tagesgeschäft: Server mit mind. „Bedienen“),
        # gleiche Prüf-/Post-Logik wie beim Anlegen (``RaidHelper.repost_event``).
        from .raidhelper import EventInputError  # zur Laufzeit (vermeidet Import-Zyklus)
        try:
            await cog.repost_event(guild, str(data.get("event_id") or ""))
        except EventInputError as err:
            raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&err=" + quote(_err_text(err)))
        raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&ok=" + quote("Event-Nachricht neu gepostet"))

    if form == "action":
        event_id = data.get("event_id")
        action = data.get("action")
        async with gconf.events() as events:
            event = events.get(event_id)
            if event is None:
                raise web.HTTPFound(f"/cogs/raidhelper?guild={guild.id}&err=Event+nicht+gefunden")
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


def _limits_from(data) -> dict:
    """``limit_<rolle>``-Felder -> {rolle: wert} (leere Felder weglassen)."""
    return {k[len("limit_"):]: str(v) for k, v in data.items()
            if k.startswith("limit_") and str(v).strip()}


async def _post_create(cog, request, guild, data):
    """Neues Event – dieselbe Prüf-/Anlege-Logik wie ``[p]raid create``/``quickcreate``."""
    from .raidhelper import EventInputError  # zur Laufzeit (vermeidet Import-Zyklus)

    base = f"/cogs/raidhelper?guild={guild.id}"
    raw_ch = (data.get("channel") or "").strip()
    channel = guild.get_channel(int(raw_ch)) if raw_ch.isdigit() else None
    try:
        if raw_ch and channel is None:
            raise EventInputError("create_no_channel")
        event = await cog.create_event_from_input(
            guild,
            author_id=await _author_id(cog, request),
            date_s=data.get("date"), time_s=data.get("time"),
            title=data.get("title"), description=data.get("description"),
            game=(data.get("game") or "").strip() or None, channel=channel,
            max_signups=data.get("max_signups"), role_limits=_limits_from(data),
            recurrence=data.get("recurrence"),
            deadline_date=data.get("deadline_date"), deadline_time=data.get("deadline_time"),
        )
    except EventInputError as err:
        _save_draft(cog, request, "create", data)
        raise web.HTTPFound(f"{base}&draft=1&err=" + quote(_err_text(err)) + "#neu")
    if not event.get("message_id"):
        raise web.HTTPFound(f"{base}&err=" + quote(t("de", "dash_created_unposted", id=event["id"])) + "#events")
    raise web.HTTPFound(f"{base}&ok=" + quote(t("de", "dash_created", id=event["id"])) + "#events")


def _changed_ts(cog, date_s, time_s, shown: tuple[str, str], tz_name: str):
    """Termin-Feld auswerten: ``...`` = unverändert (wie angezeigt), ``None`` = leer, sonst Zeitstempel."""
    if date_s is None and time_s is None:  # deaktivierte Felder (abgeschlossenes Event)
        return ...
    cur = ((date_s or "").strip(), (time_s or "").strip())
    if cur == shown:
        return ...
    if cur == ("", ""):
        return None
    return cog._parse_when(cur[0], cur[1], tz_name)


async def _post_edit(cog, request, guild, data):
    """Event ändern – ``RaidHelper.update_event`` (wie die Befehle ``[p]raid title/time/…``)."""
    from .raidhelper import EventInputError

    base = f"/cogs/raidhelper?guild={guild.id}"
    event_id = (data.get("event_id") or "").strip()
    events = await cog.config.guild(guild).events()
    event = events.get(event_id)
    if not isinstance(event, dict):
        raise web.HTTPFound(f"{base}&err=Event+nicht+gefunden#events")
    tz_name = await cog.config.guild(guild).timezone()
    start = event.get("start_ts")
    deadline = event.get("deadline_ts")
    try:
        changes = {
            "title": data.get("title"),
            "description": data.get("description"),
            "max_signups": data.get("max_signups"),
            "role_limits": _limits_from(data),
            "recurrence": data.get("recurrence"),
        }
        new_start = _changed_ts(cog, data.get("date"), data.get("time"), _date_time(start, tz_name), tz_name)
        if new_start is None:
            raise EventInputError("create_bad_date")
        if new_start is not ...:
            changes["start_ts"] = new_start
        shown_dl = ("", "") if not deadline or deadline == start else _date_time(deadline, tz_name)
        new_dl = _changed_ts(cog, data.get("deadline_date"), data.get("deadline_time"), shown_dl, tz_name)
        if new_dl is not ...:
            changes["deadline_ts"] = new_dl  # None = wieder „bis zum Start“
        new, before = await cog.update_event(guild, event_id, **changes)
    except EventInputError as err:
        _save_draft(cog, request, f"edit:{event_id}", data)
        raise web.HTTPFound(f"{base}&edit={quote(event_id)}&draft=1&err=" + quote(_err_text(err)))
    key = "dash_updated" if new != before else "dash_updated_nochange"
    raise web.HTTPFound(f"{base}&ok=" + quote(t("de", key, id=event_id)) + "#events")
