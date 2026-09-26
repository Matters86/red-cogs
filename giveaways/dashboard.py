"""WebCore-Dashboard „Gewinnspiele“ (``/cogs/giveaways``).

* GET                -> Reiter Laufend · Beendet · Neues Gewinnspiel · Einstellungen
* GET ?gw=<id>       -> Detail: Daten, Gewinner (einzeln neu auslosen), Teilnehmerliste, Aktionen
* POST form=settings -> Einstellungen speichern
* POST form=create   -> Gewinnspiel anlegen und posten (bei Fehler: Entwurf bleibt erhalten)
* POST form=action   -> end · cancel · reroll · reroll_one · delete (alle mit Bestätigung im UI)

Rechte: ``create``/``action`` sind Tagesgeschäft (Stufe „Bedienen“ reicht), ``settings`` braucht „Bearbeiten“.

Nur UI-Kit, alle eigenen Werte mit ``html.escape``. Server nur über ``visible_guilds``.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord

from .core import (MAX_BONUS_PER_ROLE, MAX_BONUS_ROLES, MAX_DESC_LEN, MAX_MEMBER_DAYS, MAX_PRIZE_LEN,
                   MAX_WINNERS, eligibility, parse_duration, tickets_for)
from .strings import LANGUAGES, t

SLUG = "giveaways"
TITLE = "Gewinnspiele"
_DRAFT_TTL = 900
_DRAFT_MAX = 200
_DRAFT_FIELDS = ("prize", "description", "channel", "winners", "end_date", "end_time", "duration",
                 "min_days") + tuple(f"bonus_role_{i}" for i in range(MAX_BONUS_ROLES)) \
    + tuple(f"bonus_n_{i}" for i in range(MAX_BONUS_ROLES))
_DRAFT_LISTS = ("required_roles", "excluded_roles")
_BONUS_ROWS = 3


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _plain(text: str) -> str:
    return (text or "").replace("**", "").replace("`", "")


def _tz(name):
    try:
        return ZoneInfo(name or "Europe/Berlin")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _abs(ts, tz) -> str:
    return datetime.fromtimestamp(int(ts), tz=tz).strftime("%d.%m.%Y, %H:%M")


def _rel(ts, now) -> str:
    from .member import rel
    return rel(int(ts), now)


def parse_local(date_s: str, time_s: str, tz) -> int | None:
    """Datum (``YYYY-MM-DD`` oder ``TT.MM.JJJJ``) + Uhrzeit (``HH:MM``) in der Server-Zeitzone -> UTC-Zeitstempel."""
    date_s, time_s = (date_s or "").strip(), (time_s or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date_s) or re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_s)
    tm = re.fullmatch(r"(\d{1,2}):(\d{2})", time_s)
    if not m or not tm:
        return None
    a, b, c = (int(x) for x in m.groups())
    y, mo, d = (a, b, c) if a > 31 else (c, b, a)
    try:
        return int(datetime(y, mo, d, int(tm.group(1)), int(tm.group(2)), tzinfo=tz).timestamp())
    except ValueError:
        return None


def _role_items(guild):
    return [(r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
            for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default() and not getattr(r, "managed", False)]


def _role_names(guild, ids) -> str:
    names = [getattr(guild.get_role(int(r)), "name", None) for r in ids or []]
    return ", ".join(n for n in names if n) or "—"


def _member_name(guild, uid, entrants=None) -> str:
    m = guild.get_member(int(uid))
    if m is not None:
        return m.display_name
    e = (entrants or {}).get(str(uid)) or {}
    return e.get("name") or f"Nutzer {uid}"


# ----- Entwurf nach Eingabefehler (RAM, Schlüssel = CSRF-Token der Sitzung) ----- #
def _save_draft(cog, request, data):
    drafts = cog.__dict__.setdefault("_dash_drafts", {})
    now = time.monotonic()
    for key in [k for k, (ts, _v) in drafts.items() if now - ts > _DRAFT_TTL]:
        drafts.pop(key, None)
    while len(drafts) >= _DRAFT_MAX:
        drafts.pop(next(iter(drafts)))
    values = {k: str(data.get(k) or "")[:4000] for k in _DRAFT_FIELDS if data.get(k) is not None}
    for k in _DRAFT_LISTS:
        values[k] = [str(v) for v in data.getall(k, [])][:25]
    drafts[request.get("webcore_csrf", "")] = (now, values)


def _load_draft(cog, request) -> dict:
    if request.query.get("draft") != "1":
        return {}
    item = cog.__dict__.get("_dash_drafts", {}).get(request.get("webcore_csrf", ""))
    if not item or time.monotonic() - item[0] > _DRAFT_TTL:
        return {}
    return item[1]


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


async def _guilds(request):
    guilds = await request.app["webcore"].visible_guilds(request)
    return sorted(guilds, key=lambda g: g.name.lower())


def _pick(guilds, raw):
    raw = str(raw or "")
    if raw.isdigit():
        for g in guilds:
            if g.id == int(raw):
                return g
    return None


# --------------------------------------------------------------------------- #
#  GET
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    ui = request.app["webcore"].ui
    guilds = await _guilds(request)
    guild = _pick(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": TITLE, "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    tz = _tz(conf.get("timezone"))
    now = cog._now()
    gws = {k: v for k, v in (conf.get("giveaways") or {}).items() if isinstance(v, dict)}

    sel = request.query.get("gw")
    if sel and sel in gws:
        return {"title": f"{TITLE} · Details", "content": _render_detail(cog, ui, guild, gws[sel], csrf, tz, now)}

    running = sorted((g for g in gws.values() if g.get("status") == "running"), key=lambda g: int(g.get("end_ts") or 0))
    done = sorted((g for g in gws.values() if g.get("status") != "running"),
                  key=lambda g: -int(g.get("ended_ts") or g.get("end_ts") or 0))
    entries = sum(len(g.get("entrants") or {}) for g in running)
    head = ui.hero("bi-gift", "", "Starte Gewinnspiele mit Teilnahme-Button, Voraussetzungen und Bonus-Losen. "
                                  "Die Auslosung passiert automatisch zum Ende – fair per Zufall, auch wenn der "
                                  "Bot zwischendurch offline war.")
    stats = ui.stats([
        ("Laufend", len(running), "bi-broadcast", None, "ok" if running else None),
        ("Teilnahmen (laufend)", entries, "bi-people", None, None),
        ("Beendet", sum(1 for g in done if g.get("status") == "ended"), "bi-flag", None, None),
        ("Nächste Auslosung", _rel(running[0]["end_ts"], now) if running else "—", "bi-hourglass-split",
         _abs(running[0]["end_ts"], tz) if running else None, None),
    ])
    body = (
        ui.tab("laufend", "Laufend", "bi-broadcast", _table_running(cog, ui, guild, running, csrf, tz, now),
               count=len(running))
        + ui.tab("beendet", "Beendet", "bi-flag", _table_done(cog, ui, guild, done, csrf, tz, now), count=len(done))
        + ui.tab("neu", "Neues Gewinnspiel", "bi-plus-square",
                 _render_create(ui, guild, conf, csrf, tz, _load_draft(cog, request)))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", _render_settings(ui, guild, conf, csrf))
    )
    return {"title": TITLE, "content": head + stats + body}


def _action_form(ui, csrf, guild, gw_id, action, label, icon, *, kind="ghost", confirm=None, extra=None, back=None):
    hidden = {"form": "action", "guild": guild.id, "gw": gw_id, "action": action, **(extra or {})}
    if back:
        hidden["back"] = back
    return ui.form(f"/cogs/{SLUG}", ui.button(label, icon=icon, kind=kind, small=True), csrf=csrf,
                   hidden=hidden, confirm=confirm)


def _prize_cell(gw) -> str:
    return (f"<div class='wc-cell-title'>{_esc((gw.get('prize') or '')[:80])}</div>"
            f"<div class='wc-cell-sub'><span class='mono'>#{_esc(gw.get('id'))}</span> · "
            f"{int(gw.get('winner_count') or 1)} Gewinner</div>")


def _chan(cog, guild, gw) -> str:
    ch = cog._channel(guild, gw.get("channel_id"))
    return f"#{_esc(ch.name)}" if ch is not None else "<span class='wc-muted'>— Kanal gelöscht —</span>"


def _table_running(cog, ui, guild, running, csrf, tz, now) -> str:
    if not running:
        return ui.card(body=ui.empty("bi-gift", "Gerade läuft kein Gewinnspiel.",
                                     "Starte eins im Reiter „Neues Gewinnspiel“ oder in Discord mit "
                                     "<code>[p]giveaway start 1d 1 Preis</code>."))
    rows = []
    for gw in running:
        gid = str(gw.get("id"))
        details = ui.button("Details", icon="bi-people", kind="ghost", small=True,
                            href=f"/cogs/{SLUG}?guild={guild.id}&gw={quote(gid)}")
        end = _action_form(ui, csrf, guild, gid, "end", "Beenden", "bi-flag",
                           confirm="Jetzt beenden und sofort die Gewinner auslosen?")
        cancel = _action_form(ui, csrf, guild, gid, "cancel", "", "bi-x-circle", kind="danger",
                              confirm="Gewinnspiel abbrechen? Es wird NICHT ausgelost.")
        rows.append(ui.row(
            _prize_cell(gw), _chan(cog, guild, gw),
            f"{_esc(_rel(gw['end_ts'], now))}<div class='wc-cell-sub'>{_esc(_abs(gw['end_ts'], tz))}</div>",
            f"<span class='mono'>{len(gw.get('entrants') or {})}</span>",
            f"><div class='wc-row-actions'>{details}{end}{cancel}</div>",
        ))
    return ui.card("Laufende Gewinnspiele", ui.table(
        ["Preis", "Kanal", "Endet", "Teilnehmer", ">"], rows, search=True,
        search_placeholder="Nach Preis, ID oder Kanal suchen …", id="gv-running"),
        icon="bi-broadcast", desc="Nach Ende sortiert. „Beenden“ lost sofort aus, „Abbrechen“ beendet ohne Auslosung.")


def _table_done(cog, ui, guild, done, csrf, tz, now) -> str:
    if not done:
        return ui.card(body=ui.empty("bi-flag", "Noch kein Gewinnspiel beendet."))
    rows = []
    for gw in done:
        gid = str(gw.get("id"))
        cancelled = gw.get("status") == "cancelled"
        ts = int(gw.get("ended_ts") or gw.get("end_ts") or 0)
        winners = [_esc(_member_name(guild, w, gw.get("entrants"))) for w in gw.get("winner_ids") or []]
        details = ui.button("Details", icon="bi-people", kind="ghost", small=True,
                            href=f"/cogs/{SLUG}?guild={guild.id}&gw={quote(gid)}")
        reroll = "" if cancelled else _action_form(
            ui, csrf, guild, gid, "reroll", "Neu auslosen", "bi-arrow-repeat",
            confirm="Alle Gewinner neu auslosen? Die bisherigen Gewinner werden ersetzt und im Kanal "
                    "werden die neuen Gewinner angepingt.")
        delete = _action_form(ui, csrf, guild, gid, "delete", "", "bi-trash", kind="danger",
                              confirm="Eintrag samt Teilnehmerliste entfernen? Die Discord-Nachricht bleibt stehen.")
        rows.append(ui.row(
            _prize_cell(gw), _chan(cog, guild, gw),
            f"{_esc(_rel(ts, now))}<div class='wc-cell-sub'>{_esc(_abs(ts, tz))}</div>",
            ", ".join(winners) if winners else "<span class='wc-muted'>—</span>",
            ui.badge("abgebrochen", "warn") if cancelled else ui.badge("beendet", "muted"),
            f"><div class='wc-row-actions'>{details}{reroll}{delete}</div>",
        ))
    return ui.card("Beendete Gewinnspiele", ui.table(
        ["Preis", "Kanal", "Beendet", "Gewinner", "Status", ">"], rows, search=True,
        search_placeholder="Nach Preis, ID, Kanal oder Gewinner suchen …", id="gv-done"),
        icon="bi-flag", desc="Neueste zuerst. Einträge werden nach der eingestellten Aufbewahrungszeit entfernt.")


def _render_create(ui, guild, conf, csrf, tz, draft) -> str:
    v = draft.get
    now_local = datetime.now(tz)
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    roles = _role_items(guild)
    main = ui.card("Gewinnspiel", ui.grid(
        ui.field("Preis", ui.text_input("prize", v("prize", ""), placeholder="z. B. Discord Nitro (1 Monat)",
                                        attrs={"maxlength": MAX_PRIZE_LEN, "required": True}), wide=True),
        ui.field("Beschreibung (optional)", ui.textarea("description", v("description", ""), rows=3,
                                                        placeholder="Worum geht es, wie wird der Gewinn übergeben …"),
                 help=f"Max. {MAX_DESC_LEN} Zeichen, Discord-Formatierung funktioniert.", wide=True),
        ui.field("Kanal", ui.select("channel", text_items, v("channel"), none_label="— bitte wählen —",
                                    attrs={"required": True}),
                 help="Hier postet der Bot das Gewinnspiel mit dem 🎉-Button und später die Gewinner."),
        ui.field("Anzahl Gewinner", ui.number("winners", v("winners", "1"), min=1, max=MAX_WINNERS, unit="Gewinner")),
    ), icon="bi-gift")
    when = ui.card("Laufzeit", ui.callout(
        f"Datum und Uhrzeit gelten in der Server-Zeitzone <b>{_esc(conf.get('timezone') or 'Europe/Berlin')}</b> "
        f"(jetzt dort {now_local.strftime('%d.%m.%Y, %H:%M')}&nbsp;Uhr). In Discord sieht jedes Mitglied "
        "das Ende in seiner eigenen Zeitzone.", icon="bi-globe2") + ui.grid(
        ui.field("Ende – Datum", ui.text_input("end_date", v("end_date", ""), type="date",
                                               attrs={"min": now_local.strftime("%Y-%m-%d")})),
        ui.field("Ende – Uhrzeit", ui.text_input("end_time", v("end_time", ""), type="time", placeholder="HH:MM")),
        ui.field("… oder Dauer", ui.text_input("duration", v("duration", ""), placeholder="z. B. 2d, 12h, 1d12h"),
                 help="Wenn ausgefüllt, gilt die Dauer ab jetzt (hat Vorrang vor Datum/Uhrzeit). "
                      "Mindestens 1 Minute, höchstens 60 Tage."),
    ), icon="bi-clock")
    rules = ui.card("Teilnahme-Regeln (optional)", ui.grid(
        ui.field("Benötigte Rollen", ui.select("required_roles", roles, v("required_roles") or [], multiple=True,
                                               placeholder="Rollen suchen …"),
                 help="Teilnehmen darf, wer <b>mindestens eine</b> dieser Rollen hat. Leer = alle.", wide=True),
        ui.field("Ausgeschlossene Rollen", ui.select("excluded_roles", roles, v("excluded_roles") or [],
                                                     multiple=True, placeholder="Rollen suchen …"),
                 help="Wer eine dieser Rollen hat, kann nicht teilnehmen (z. B. Team).", wide=True),
        ui.field("Mindest-Mitgliedschaft", ui.number("min_days", v("min_days", "0"), min=0, max=MAX_MEMBER_DAYS,
                                                     unit="Tage"),
                 help="So lange muss man schon auf dem Server sein. 0 = keine Vorgabe."),
    ), icon="bi-shield-check", desc="Die Regeln werden beim Teilnehmen und noch einmal bei der Auslosung geprüft.")
    bonus_rows = []
    for i in range(_BONUS_ROWS):
        bonus_rows.append(ui.field(f"Bonus-Rolle {i + 1}", ui.select(f"bonus_role_{i}", roles, v(f"bonus_role_{i}"),
                                                                     none_label="— keine —")))
        bonus_rows.append(ui.field("Zusätzliche Lose", ui.number(f"bonus_n_{i}", v(f"bonus_n_{i}", "1"), min=1,
                                                                  max=MAX_BONUS_PER_ROLE, unit="Lose")))
    bonus = ui.card("Bonus-Lose (optional)", ui.grid(*bonus_rows), icon="bi-stars",
                    desc="Mitglieder mit diesen Rollen bekommen zusätzliche Lose (werden addiert, max. 25 Lose "
                         "pro Person). Jeder hat mindestens 1 Los.")
    return ui.form(f"/cogs/{SLUG}", main + when + rules + bonus + ui.actions(
        ui.button("Gewinnspiel starten", icon="bi-send"),
        "<span class='wc-help'>Der Bot postet das Gewinnspiel sofort im gewählten Kanal.</span>"),
        csrf=csrf, hidden={"form": "create", "guild": guild.id})


def _render_settings(ui, guild, conf, csrf) -> str:
    general = ui.card("Allgemein", ui.grid(
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf.get("language", "de")),
                 help="Sprache von Embed, Button, Antworten und Gewinner-Ansage."),
        ui.field("Zeitzone", ui.text_input("timezone", conf.get("timezone") or "Europe/Berlin",
                                           placeholder="Europe/Berlin"),
                 help="IANA-Name, z. B. <code>Europe/Berlin</code>. Gilt für Datum/Uhrzeit im Dashboard."),
        ui.field("Embed-Farbe", ui.color_input("color", conf.get("color") or "#f5b94a"),
                 help="Farbe laufender Gewinnspiele (beendete werden grau)."),
        ui.field("Aufbewahrung", ui.number("keep_days", int(conf.get("keep_days") or 90), min=0, max=3650,
                                           unit="Tage"),
                 help="Beendete/abgebrochene Gewinnspiele danach automatisch entfernen. 0 = nie."),
    ), icon="bi-sliders")
    rights = ui.card("Rechte", ui.field(
        "Gewinnspiel-Manager", ui.select("manager_roles", _role_items(guild), conf.get("manager_roles") or [],
                                         multiple=True, placeholder="Rollen suchen …"),
        help="Dürfen in Discord <code>[p]giveaway start/end/reroll/cancel/list</code> nutzen. Wer „Server "
             "verwalten“ hat, darf das immer. Das Dashboard selbst regelt „Zugriff &amp; Rollen“.", wide=True),
        icon="bi-shield-lock")
    portal = ui.card("Mitglieder-Bereich", ui.switch(
        "member_page", "Im Mitglieder-Bereich anzeigen", conf.get("member_page", True),
        desc="Mitglieder sehen unter „Mein Bereich → Gewinnspiele“ laufende Gewinnspiele aus Kanälen, die sie "
             "lesen können, nehmen dort genauso teil wie per Button und sehen ihre eigenen Gewinne.",
    ) + ui.callout("Den Mitglieder-Bereich selbst schaltet der Bot-Owner pro Server unter <b>Verwaltung → Zugriff "
                   "&amp; Rollen</b> ein (oder mit <code>[p]webcore portal on</code>)."),
        icon="bi-person-badge")
    return ui.form(f"/cogs/{SLUG}", general + rights + portal + ui.save_row("Einstellungen speichern"),
                   csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True)


def _render_detail(cog, ui, guild, gw, csrf, tz, now) -> str:
    gid = str(gw.get("id"))
    status = gw.get("status", "running")
    entrants = gw.get("entrants") or {}
    back = ui.button("Zurück zur Übersicht", icon="bi-arrow-left", kind="ghost", small=True,
                     href=f"/cogs/{SLUG}?guild={guild.id}#{'laufend' if status == 'running' else 'beendet'}")
    badge = {"running": ui.badge("läuft", "ok"), "ended": ui.badge("beendet", "muted"),
             "cancelled": ui.badge("abgebrochen", "warn")}.get(status, "")
    head = ui.hero("bi-gift", gw.get("prize") or "Gewinnspiel",
                   f"<span class='mono'>#{_esc(gid)}</span> · {badge}<br><br>{back}")
    total_tickets = 0
    rows = []
    for uid, e in sorted(entrants.items(), key=lambda kv: kv[1].get("ts", 0)):
        m = guild.get_member(int(uid))
        if m is None:
            state, n = ui.badge("nicht mehr auf dem Server", "bad"), 0
        else:
            err = eligibility(m, gw, now, check_running=False)
            n = tickets_for(m, gw) if err is None else 0
            state = ui.badge("gültig", "ok") if err is None else ui.badge(
                _plain(cog.text(guild, "de", err[0], err[1], web=True)), "warn")
        total_tickets += n
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(_member_name(guild, uid, entrants))}</div>"
            f"<div class='wc-cell-sub mono'>{_esc(uid)}</div>",
            f"><span class='mono'>{n}</span>",
            _esc(_abs(e.get("ts", 0), tz)),
            state,
        ))
    stats = ui.stats([
        ("Teilnehmer", len(entrants), "bi-people", None, None),
        ("Lose (aktuell gültig)", total_tickets, "bi-ticket", None, None),
        ("Gewinner", f"{len(gw.get('winner_ids') or [])} / {int(gw.get('winner_count') or 1)}", "bi-trophy",
         None, None),
    ])
    ch = cog._channel(guild, gw.get("channel_id"))
    link = ""
    if ch is not None and gw.get("message_id"):
        link = (f" · <a href='https://discord.com/channels/{guild.id}/{ch.id}/{int(gw['message_id'])}' "
                "target='_blank' rel='noopener'>Nachricht öffnen</a>")
    end_line = (f"{_esc(_abs(gw.get('end_ts', 0), tz))} ({_esc(_rel(gw.get('end_ts', 0), now))})")
    bonus = ", ".join(f"{_esc(getattr(guild.get_role(int(r)), 'name', r))} +{int(n)}"
                      for r, n in (gw.get("bonus_roles") or {}).items()) or "—"
    host = _member_name(guild, gw["host_id"]) if gw.get("host_id") else "—"
    info = (
        "<dl class='wc-kv'>"
        f"<dt>Kanal</dt><dd>{_chan(cog, guild, gw)}{link}</dd>"
        f"<dt>Ende</dt><dd>{end_line}</dd>"
        + (f"<dt>Beendet</dt><dd>{_esc(_abs(gw['ended_ts'], tz))} "
           f"({'automatisch' if gw.get('ended_by') == 'auto' else 'manuell'})</dd>"
           if gw.get("ended_ts") and status == "ended" else "")
        + f"<dt>Benötigte Rollen</dt><dd>{_esc(_role_names(guild, gw.get('required_roles')))}</dd>"
        f"<dt>Ausgeschlossen</dt><dd>{_esc(_role_names(guild, gw.get('excluded_roles')))}</dd>"
        f"<dt>Mindest-Mitgliedschaft</dt><dd>{int(gw.get('min_member_days') or 0)} Tage</dd>"
        f"<dt>Bonus-Lose</dt><dd>{bonus}</dd>"
        f"<dt>Veranstalter</dt><dd>{_esc(host)}</dd>"
        "</dl>"
    )
    if gw.get("description"):
        info += f"<div class='wc-divider'></div><div style='white-space:pre-line'>{_esc(gw['description'])}</div>"
    actions = []
    back_key = "detail"
    if status == "running":
        actions.append(_action_form(ui, csrf, guild, gid, "end", "Jetzt beenden & auslosen", "bi-flag", kind="accent",
                                    confirm="Jetzt beenden und sofort die Gewinner auslosen?", back=back_key))
        actions.append(_action_form(ui, csrf, guild, gid, "cancel", "Abbrechen", "bi-x-circle", kind="danger",
                                    confirm="Gewinnspiel abbrechen? Es wird NICHT ausgelost.", back=back_key))
    else:
        if status == "ended":
            actions.append(_action_form(ui, csrf, guild, gid, "reroll", "Alle neu auslosen", "bi-arrow-repeat",
                                        confirm="Alle Gewinner neu auslosen? Bisherige Gewinner werden ersetzt.",
                                        back=back_key))
        actions.append(_action_form(ui, csrf, guild, gid, "delete", "Eintrag entfernen", "bi-trash", kind="danger",
                                    confirm="Eintrag samt Teilnehmerliste entfernen?"))
    body = ui.card("Details", info + "<div class='wc-divider'></div>" + ui.actions(*actions), icon="bi-info-circle")
    if status == "ended":
        wrows = []
        for w in gw.get("winner_ids") or []:
            wrows.append(ui.row(
                f"<div class='wc-cell-title'>🏆 {_esc(_member_name(guild, w, entrants))}</div>"
                f"<div class='wc-cell-sub mono'>{_esc(w)}</div>",
                "><div class='wc-row-actions'>" + _action_form(
                    ui, csrf, guild, gid, "reroll_one", "Neu auslosen", "bi-arrow-repeat",
                    confirm="Diesen Gewinner durch eine neue Auslosung ersetzen?",
                    extra={"user": str(w)}, back=back_key) + "</div>"))
        body += ui.card("Gewinner", ui.table(["Gewinner", ">"], wrows, empty_text="Keine gültigen Teilnahmen."),
                        icon="bi-trophy", desc="Einzeln ersetzen, z. B. wenn sich jemand nicht meldet. "
                                               "Ersetzte Gewinner können nicht erneut gezogen werden.")
    body += ui.card("Teilnehmer", ui.table(["Mitglied", ">Lose", "Beigetreten", "Status"], rows, search=True,
                                           search_placeholder="Nach Name oder ID suchen …", id="gv-entrants",
                                           empty_text="Noch keine Teilnahmen."),
                    icon="bi-people", desc="Lose und Status nach den aktuellen Rollen – so zählen sie bei der Auslosung.")
    return head + stats + body


# --------------------------------------------------------------------------- #
#  POST
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    guild = _pick(await _guilds(request), data.get("guild"))
    if guild is None:
        return {"redirect": f"/cogs/{SLUG}?err=" + quote("Server nicht gefunden oder keine Bearbeitungsrechte")}
    base = f"/cogs/{SLUG}?guild={guild.id}"
    form = data.get("form")
    gconf = cog.config.guild(guild)

    if form == "settings":
        lang = (data.get("language") or "de").lower()
        tzname = (data.get("timezone") or "Europe/Berlin").strip()
        try:
            ZoneInfo(tzname)
        except (ZoneInfoNotFoundError, ValueError):
            return {"redirect": base + "&err=" + quote(f"Unbekannte Zeitzone: {tzname[:60]}") + "#einstellungen"}
        color = (data.get("color") or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#f5b94a"
        try:
            keep = max(0, min(3650, int(data.get("keep_days") or 0)))
        except ValueError:
            keep = 90
        roles = [int(r) for r in data.getall("manager_roles", []) if str(r).isdigit() and guild.get_role(int(r))]
        await gconf.language.set(lang if lang in LANGUAGES else "de")
        await gconf.timezone.set(tzname)
        await gconf.color.set(color)
        await gconf.keep_days.set(keep)
        await gconf.manager_roles.set(roles)
        await gconf.member_page.set("member_page" in data)
        return {"redirect": base + "&ok=" + quote("Einstellungen gespeichert")}

    if form == "create":
        err = await _create(cog, request, guild, data)
        if err:
            _save_draft(cog, request, data)
            return {"redirect": base + "&draft=1&err=" + quote(err) + "#neu"}
        return {"redirect": base + "&ok=" + quote("Gewinnspiel gestartet") + "#laufend"}

    if form == "action":
        gw_id = str(data.get("gw") or "")
        action = data.get("action")
        back = base + (f"&gw={quote(gw_id)}" if data.get("back") == "detail" else "")
        if action == "end":
            key, kw = await cog.end_giveaway(guild, gw_id, by="manual")
            ok = key == "ended_ok"
        elif action == "cancel":
            key, kw = await cog.cancel_giveaway(guild, gw_id)
            ok = key == "cancelled_ok"
        elif action in ("reroll", "reroll_one"):
            user = data.get("user") if action == "reroll_one" else None
            if action == "reroll_one" and not str(user or "").isdigit():
                return {"redirect": back + "&err=" + quote("Kein Gewinner gewählt")}
            key, kw, picks = await cog.reroll(guild, gw_id, int(user) if user else None)
            ok = key == "rerolled_ok"
            if ok:
                kw = {"mentions": ", ".join(_member_name(guild, p) for p in picks)}
        elif action == "delete":
            if await cog.delete_giveaway(guild, gw_id):
                return {"redirect": base + "&ok=" + quote("Eintrag entfernt") + "#beendet"}
            return {"redirect": base + "&err=" + quote("Nur beendete oder abgebrochene Gewinnspiele lassen sich entfernen")}
        else:
            return {"redirect": base + "&err=" + quote("Unbekannte Aktion")}
        text = _plain(t("de", key, **kw))
        return {"redirect": back + ("&ok=" if ok else "&err=") + quote(text)}

    return {"redirect": base + "&err=" + quote("Unbekanntes Formular")}


async def _create(cog, request, guild, data) -> str | None:
    """Neues Gewinnspiel aus dem Formular. Rückgabe: Fehlermeldung oder ``None``."""
    conf = await cog.config.guild(guild).all()
    tz = _tz(conf.get("timezone"))
    raw = str(data.get("channel") or "")
    channel = cog._channel(guild, raw) if raw.isdigit() else None
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return "Bitte einen Textkanal wählen"
    now = int(cog._now())
    dur = (data.get("duration") or "").strip()
    if dur:
        secs = parse_duration(dur)
        if secs is None:
            return "Dauer nicht erkannt (z. B. 2d, 12h, 1d12h – 1 Minute bis 60 Tage)"
        end_ts = now + secs
    else:
        end_ts = parse_local(data.get("end_date"), data.get("end_time"), tz)
        if end_ts is None:
            return "Bitte Ende (Datum und Uhrzeit) oder eine Dauer angeben"
        if end_ts <= now:
            return "Das Ende liegt in der Vergangenheit"
    bonus = {}
    for i in range(MAX_BONUS_ROLES):
        rid = str(data.get(f"bonus_role_{i}") or "")
        if rid.isdigit():
            try:
                n = int(data.get(f"bonus_n_{i}") or 1)
            except ValueError:
                n = 1
            bonus[rid] = max(1, min(MAX_BONUS_PER_ROLE, n))
    try:
        min_days = int(data.get("min_days") or 0)
    except ValueError:
        return "Mindest-Mitgliedschaft muss eine Zahl sein"
    try:
        winners = int(data.get("winners") or 0)
    except ValueError:
        winners = 0
    user = await request.app["webcore"].current_user(request)
    gw, err = await cog.create_giveaway(
        guild, channel, host_id=(user or {}).get("id") or 0, prize=data.get("prize"),
        description=data.get("description") or "", end_ts=end_ts, winner_count=winners,
        required_roles=data.getall("required_roles", []), excluded_roles=data.getall("excluded_roles", []),
        min_member_days=min_days, bonus_roles=bonus,
    )
    if err:
        return _plain(t("de", err[0], **err[1]))
    return None
