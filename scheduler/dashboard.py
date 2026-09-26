"""WebCore-Dashboard „Geplante Nachrichten“ (``/cogs/scheduler``) – komplett ohne JavaScript bedienbar.

* GET                    -> Reiter Nachrichten · Neue Nachricht · Einstellungen
* GET ?edit=<id>         -> Bearbeiten + Vorschau + Status (letzte Ausführung, Fehler)
* POST form=entry        -> action=save (anlegen/ändern) oder action=preview (nur Vorschau, nichts gespeichert)
* POST form=action       -> test · pause · resume · delete
* POST form=settings     -> Zeitzone, Sprache

Nur UI-Kit, alle Werte mit ``html.escape``. Server nur über ``visible_guilds``.
"""

from __future__ import annotations

import html
import time
from datetime import datetime
from urllib.parse import quote

from . import timing
from .strings import LANGUAGES, t

SLUG = "scheduler"
TITLE = "Geplante Nachrichten"
_DRAFT_TTL = 900
_DRAFT_MAX = 200
_DRAFT_FIELDS = ("name", "channel", "content", "ping_role", "embed_title", "embed_description", "embed_color",
                 "embed_image", "type", "date", "time", "day", "interval", "interval_unit", "start_date",
                 "end_date", "delete_previous", "eid")
_TYPES = [("once", "Einmalig"), ("daily", "Täglich"), ("weekly", "Wöchentlich (an Wochentagen)"),
          ("monthly", "Monatlich (am Tag X)"), ("interval", "Alle N Minuten/Stunden")]
_WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _plain(text: str) -> str:
    return (text or "").replace("**", "").replace("`", "")


def rel(ts, now) -> str:
    diff = int(ts - now)
    future = diff >= 0
    diff = abs(diff)
    if diff < 60:
        return "gleich" if future else "gerade eben"
    if diff < 3600:
        n, unit = diff // 60, "Min."
    elif diff < 86400:
        n, unit = diff // 3600, "Std."
    else:
        n = diff // 86400
        unit = "Tag" if n == 1 else "Tagen"
    return f"in {n} {unit}" if future else f"vor {n} {unit}"


def absolute(ts, tz_name) -> str:
    return datetime.fromtimestamp(int(ts), tz=timing.get_tz(tz_name)).strftime("%a, %d.%m.%Y %H:%M") \
        .replace("Mon", "Mo").replace("Tue", "Di").replace("Wed", "Mi").replace("Thu", "Do") \
        .replace("Fri", "Fr").replace("Sat", "Sa").replace("Sun", "So")


# ----- Entwurf (Fehler/Vorschau) im RAM, Schlüssel = CSRF-Token der Sitzung ----- #
def _save_draft(cog, request, data):
    drafts = cog.__dict__.setdefault("_dash_drafts", {})
    now = time.monotonic()
    for key in [k for k, (ts, _v) in drafts.items() if now - ts > _DRAFT_TTL]:
        drafts.pop(key, None)
    while len(drafts) >= _DRAFT_MAX:
        drafts.pop(next(iter(drafts)))
    values = {k: str(data.get(k) or "")[:4100] for k in _DRAFT_FIELDS if data.get(k) is not None}
    values["weekdays"] = [str(v) for v in data.getall("weekdays", [])][:7]
    drafts[request.get("webcore_csrf", "")] = (now, values)


def _load_draft(cog, request) -> dict:
    if request.query.get("draft") != "1":
        return {}
    item = cog.__dict__.get("_dash_drafts", {}).get(request.get("webcore_csrf", ""))
    if not item or time.monotonic() - item[0] > _DRAFT_TTL:
        return {}
    return item[1]


def raw_from_form(data) -> dict:
    """Formularfelder -> Rohdaten für ``Scheduler.normalize`` (funktioniert mit dict und MultiDict)."""
    def get(k):
        return str(data.get(k) or "").strip()
    getall = data.getall if hasattr(data, "getall") else (lambda k, d=None: data.get(k, d or []))
    kind = get("type") or "daily"
    sched = {"type": kind, "time": get("time")}
    if kind == "once":
        sched["date"] = get("date")
    elif kind == "weekly":
        sched["weekdays"] = sorted({int(x) for x in getall("weekdays", []) if str(x).isdigit() and 0 <= int(x) <= 6})
    elif kind == "monthly":
        sched["day"] = get("day") or None
    elif kind == "interval":
        n = get("interval")
        mult = 60 if get("interval_unit") == "hours" else 1
        sched["minutes"] = int(n) * mult if n.isdigit() else None
        if not sched["time"]:
            sched.pop("time")
    return {
        "name": get("name"), "channel_id": get("channel"), "content": str(data.get("content") or ""),
        "ping_role_id": get("ping_role") or None,
        "embed": {"title": get("embed_title"), "description": str(data.get("embed_description") or ""),
                  "color": get("embed_color") or "#5865f2", "image_url": get("embed_image")},
        "schedule": sched, "start_date": get("start_date") or None, "end_date": get("end_date") or None,
        "delete_previous": bool(data.get("delete_previous")),
    }


def values_from_entry(entry: dict) -> dict:
    s = entry.get("schedule") or {}
    e = entry.get("embed") or {}
    minutes = int(s.get("minutes") or 60)
    hours = minutes % 60 == 0
    return {
        "name": entry.get("name", ""), "channel": entry.get("channel_id"), "content": entry.get("content", ""),
        "ping_role": entry.get("ping_role_id") or "", "embed_title": e.get("title", ""),
        "embed_description": e.get("description", ""), "embed_color": e.get("color") or "#5865f2",
        "embed_image": e.get("image_url", ""), "type": s.get("type", "daily"), "date": s.get("date", ""),
        "time": s.get("time", ""), "weekdays": [str(d) for d in s.get("weekdays") or []],
        "day": s.get("day", ""), "interval": str(minutes // 60 if hours else minutes),
        "interval_unit": "hours" if hours else "minutes", "start_date": entry.get("start_date") or "",
        "end_date": entry.get("end_date") or "", "delete_previous": "on" if entry.get("delete_previous") else "",
    }


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


async def _guilds(request):
    return sorted(await request.app["webcore"].visible_guilds(request), key=lambda g: g.name.lower())


def _pick(guilds, raw):
    raw = str(raw or "")
    if raw.isdigit():
        for g in guilds:
            if g.id == int(raw):
                return g
    return None


def _status(entry) -> tuple[str, str]:
    if entry.get("auto_paused"):
        return "automatisch pausiert", "bad"
    if entry.get("paused"):
        return "pausiert", "warn"
    if entry.get("next_run_ts") is None:
        return "abgeschlossen", "muted"
    return "aktiv", "ok"


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
    tz = conf.get("timezone") or "Europe/Berlin"
    now = cog._now()
    entries = {k: v for k, v in (conf.get("entries") or {}).items() if isinstance(v, dict)}
    draft = _load_draft(cog, request)
    show_preview = request.query.get("preview") == "1" and bool(draft)

    eid = request.query.get("edit")
    if eid and eid in entries:
        return {"title": f"{TITLE} · Bearbeiten",
                "content": _render_edit(cog, ui, guild, conf, entries[eid], csrf, now, draft, show_preview)}

    active = [e for e in entries.values() if not e.get("paused") and e.get("next_run_ts")]
    paused = [e for e in entries.values() if e.get("paused")]
    auto = [e for e in entries.values() if e.get("auto_paused")]
    upcoming = min((e["next_run_ts"] for e in active), default=None)
    head = ui.hero("bi-clock-history", "",
                   "Der Bot postet Nachrichten automatisch nach Zeitplan – einmalig, täglich, an Wochentagen, "
                   f"monatlich oder im Intervall. Alle Zeiten gelten in <b>{_esc(tz)}</b> (Sommerzeit inklusive).")
    stats = ui.stats([
        ("Geplant", len(entries), "bi-collection", None, None),
        ("Aktiv", len(active), "bi-play-circle", None, "ok" if active else None),
        ("Pausiert", len(paused), "bi-pause-circle", f"{len(auto)} wegen Fehlern" if auto else None,
         "bad" if auto else None),
        ("Nächste Ausführung", rel(upcoming, now) if upcoming else "—", "bi-alarm",
         absolute(upcoming, tz) if upcoming else None, None),
    ])
    alert = ""
    if auto:
        items = "".join(
            f"<li><b>#{_esc(e.get('id'))} {_esc(e.get('name'))}</b>: {_esc(e.get('last_error') or 'unbekannter Fehler')} "
            f"<a href='/cogs/{SLUG}?guild={guild.id}&edit={quote(str(e.get('id')))}'>Bearbeiten</a></li>"
            for e in auto)
        alert = ui.callout(f"<b>Automatisch pausiert</b> nach {timing.MAX_FAILS} Fehlern in Folge – Ursache beheben "
                           f"(z. B. Kanal/Rechte) und dann „Fortsetzen“ klicken:<ul>{items}</ul>", tone="bad")
    new_values = draft if draft and not draft.get("eid") else {}
    create = ""
    if show_preview and new_values:
        create = _preview_card(cog, ui, guild, conf, new_values, now)
    create += _entry_form(ui, guild, conf, csrf, new_values, None)
    body = (
        ui.tab("nachrichten", "Nachrichten", "bi-list-task", alert + _table(cog, ui, guild, entries, csrf, tz, now),
               count=len(entries))
        + ui.tab("neu", "Neue Nachricht", "bi-plus-square", create)
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", _render_settings(ui, guild, conf, csrf, now))
    )
    return {"title": TITLE, "content": head + stats + body}


def _action_form(ui, csrf, guild, eid, action, label, icon, *, kind="ghost", confirm=None, back=None):
    hidden = {"form": "action", "guild": guild.id, "eid": eid, "action": action}
    if back:
        hidden["back"] = back
    return ui.form(f"/cogs/{SLUG}", ui.button(label, icon=icon, kind=kind, small=True,
                                              attrs={"title": label or action}),
                   csrf=csrf, hidden=hidden, confirm=confirm)


def _next_cell(e, tz, now) -> str:
    if e.get("paused"):
        return "<span class='wc-muted'>—</span>"
    if not e.get("next_run_ts"):
        last = e.get("last_run_ts")
        return "<span class='wc-muted'>kein weiterer Termin</span>" + (
            f"<div class='wc-cell-sub'>zuletzt {_esc(absolute(last, tz))}</div>" if last else "")
    ts = e["next_run_ts"]
    return f"{_esc(rel(ts, now))}<div class='wc-cell-sub'>{_esc(absolute(ts, tz))}</div>"


def _table(cog, ui, guild, entries, csrf, tz, now) -> str:
    if not entries:
        return ui.card(body=ui.empty("bi-clock-history", "Noch keine Nachricht geplant.",
                                     "Lege im Reiter „Neue Nachricht“ eine an oder in Discord mit "
                                     "<code>[p]schedule add #kanal \"täglich 09:00\" Text</code>."))
    rows = []
    order = sorted(entries.values(), key=lambda e: (bool(e.get("paused")), e.get("next_run_ts") is None,
                                                    e.get("next_run_ts") or 0))
    for e in order:
        eid = str(e.get("id"))
        ch = cog._channel(guild, e.get("channel_id"))
        label, tone = _status(e)
        snippet = (e.get("content") or (e.get("embed") or {}).get("title") or (e.get("embed") or {}).get("description")
                   or "")[:90]
        sched = timing.describe(e.get("schedule") or {}, "de")
        rng = []
        if e.get("start_date"):
            rng.append("ab " + (timing.parse_date(e["start_date"]).strftime("%d.%m.%Y")))
        if e.get("end_date"):
            rng.append("bis " + (timing.parse_date(e["end_date"]).strftime("%d.%m.%Y")))
        edit = ui.button("Bearbeiten", icon="bi-pencil", kind="ghost", small=True,
                         href=f"/cogs/{SLUG}?guild={guild.id}&edit={quote(eid)}")
        test = _action_form(ui, csrf, guild, eid, "test", "Testen", "bi-send",
                            confirm="Die Nachricht jetzt einmal in ihren Kanal posten (ohne Rollen-Ping)?")
        toggle = (_action_form(ui, csrf, guild, eid, "resume", "Fortsetzen", "bi-play") if e.get("paused")
                  else _action_form(ui, csrf, guild, eid, "pause", "Pausieren", "bi-pause"))
        delete = _action_form(ui, csrf, guild, eid, "delete", "", "bi-trash", kind="danger",
                              confirm="Diese geplante Nachricht löschen? Bereits gesendete Nachrichten bleiben stehen.")
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(e.get('name'))}</div>"
            f"<div class='wc-cell-sub'><span class='mono'>#{_esc(eid)}</span> · {_esc(snippet)}</div>",
            f"#{_esc(ch.name)}" if ch is not None else "<span class='wc-muted'>— Kanal gelöscht —</span>",
            f"{_esc(sched)}" + (f"<div class='wc-cell-sub'>{_esc(' · '.join(rng))}</div>" if rng else ""),
            _next_cell(e, tz, now),
            ui.badge(label, tone) + (f"<div class='wc-cell-sub'>{int(e.get('fail_count') or 0)} Fehler</div>"
                                     if e.get("fail_count") else ""),
            f"><div class='wc-row-actions'>{edit}{test}{toggle}{delete}</div>",
        ))
    return ui.card("Geplante Nachrichten", ui.table(
        ["Nachricht", "Kanal", "Zeitplan", "Nächste Ausführung", "Status", ">"], rows, search=True,
        search_placeholder="Nach Name, Text, Kanal oder ID suchen …", id="sc-entries"),
        icon="bi-list-task", desc="Aktive zuerst, nach nächster Ausführung sortiert.")


def _entry_form(ui, guild, conf, csrf, values, entry) -> str:
    v = values.get
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    role_items = [(r.id, r.name) for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                  if not r.is_default() and not getattr(r, "managed", False)]
    tz = conf.get("timezone") or "Europe/Berlin"
    now_local = datetime.now(timing.get_tz(tz))
    msg = ui.card("Nachricht", ui.grid(
        ui.field("Name (intern)", ui.text_input("name", v("name", ""), placeholder="z. B. Morgengruß",
                                                attrs={"maxlength": 80}),
                 help="Nur zur Übersicht im Dashboard. Leer = Anfang des Textes."),
        ui.field("Kanal", ui.select("channel", text_items, v("channel"), none_label="— bitte wählen —",
                                    attrs={"required": True})),
        ui.field("Text", ui.textarea("content", v("content", ""), rows=4,
                                     placeholder="Guten Morgen zusammen! ☀️"),
                 help="Max. 1900 Zeichen, Discord-Formatierung funktioniert. @everyone/@here pingen nie.", wide=True),
        ui.field("Rollen-Ping (optional)", ui.select("ping_role", role_items, v("ping_role"), none_label="— kein Ping —"),
                 help="Wird vor den Text gesetzt; gepingt wird <b>nur</b> diese Rolle (Bot braucht ggf. "
                      "„@everyone, @here und alle Rollen erwähnen“, wenn die Rolle nicht erwähnbar ist).", wide=True),
    ), icon="bi-chat-left-text", desc="Text und/oder Embed – mindestens eins von beiden.")
    embed = ui.card("Embed (optional)", ui.grid(
        ui.field("Titel", ui.text_input("embed_title", v("embed_title", ""), attrs={"maxlength": 256})),
        ui.field("Farbe", ui.color_input("embed_color", v("embed_color") or "#5865f2")),
        ui.field("Text", ui.textarea("embed_description", v("embed_description", ""), rows=4), wide=True,
                 help="Max. 4000 Zeichen."),
        ui.field("Bild-URL", ui.text_input("embed_image", v("embed_image", ""), type="url",
                                           placeholder="https://…/bild.png"), wide=True),
    ), icon="bi-card-heading", desc="Leer lassen, wenn nur Text gesendet werden soll.")
    weekday_items = [(str(i), n) for i, n in enumerate(_WEEKDAY_NAMES)]
    sched = ui.card("Zeitplan", ui.callout(
        f"Zeiten gelten in <b>{_esc(tz)}</b> (jetzt dort {now_local.strftime('%d.%m.%Y, %H:%M')}&nbsp;Uhr), "
        "Sommer-/Winterzeit wird automatisch berücksichtigt. Je nach Art sind nur einige Felder nötig.",
        icon="bi-globe2") + ui.grid(
        ui.field("Art", ui.select("type", _TYPES, v("type") or "daily")),
        ui.field("Uhrzeit", ui.text_input("time", v("time", ""), type="time", placeholder="HH:MM"),
                 help="Für alle Arten außer Intervall (dort optional: Startuhrzeit zusammen mit Startdatum)."),
        ui.field("Datum (nur einmalig)", ui.text_input("date", v("date", ""), type="date",
                                                       attrs={"min": now_local.strftime("%Y-%m-%d")})),
        ui.field("Tag im Monat (nur monatlich)", ui.number("day", v("day", ""), min=1, max=31, placeholder="1–31"),
                 help="29.–31.: in kürzeren Monaten am letzten Tag des Monats."),
        ui.field("Wochentage (nur wöchentlich)", ui.select("weekdays", weekday_items, v("weekdays") or [],
                                                           multiple=True, placeholder="Tage wählen …"), wide=True),
        ui.field("Intervall (nur „Alle N …“)", ui.number("interval", v("interval", ""), min=1, max=44640,
                                                        placeholder="z. B. 2"),
                 help="Mindestens 10 Minuten."),
        ui.field("Einheit", ui.select("interval_unit", [("minutes", "Minuten"), ("hours", "Stunden")],
                                      v("interval_unit") or "hours")),
        ui.field("Startdatum (optional)", ui.text_input("start_date", v("start_date", ""), type="date"),
                 help="Vorher wird nichts gesendet."),
        ui.field("Enddatum (optional)", ui.text_input("end_date", v("end_date", ""), type="date"),
                 help="Letzter Tag (inklusive), danach ist der Eintrag abgeschlossen."),
    ), icon="bi-calendar-week")
    opts = ui.card("Optionen", ui.switches(ui.switch(
        "delete_previous", "Vorherige Nachricht löschen", bool(v("delete_previous")),
        desc="Nach dem Senden wird die zuletzt von diesem Eintrag gesendete Nachricht gelöscht – so steht immer "
             "nur die aktuelle im Kanal.")), icon="bi-toggles")
    hidden = {"form": "entry", "guild": guild.id}
    if entry is not None:
        hidden["eid"] = entry.get("id")
    buttons = ui.actions(
        ui.button("Änderungen speichern" if entry else "Nachricht planen", icon="bi-check2", name="action",
                  value="save"),
        ui.button("Vorschau", icon="bi-eye", kind="ghost", name="action", value="preview"),
    )
    return ui.form(f"/cogs/{SLUG}", msg + embed + sched + opts + buttons, csrf=csrf, hidden=hidden,
                   savebar=entry is not None)


def _preview_html(cog, guild, entry: dict) -> str:
    """Nachricht ungefähr so, wie Discord sie zeigt (Text, Rollen-Ping, Embed mit Farbleiste)."""
    parts = []
    rid = entry.get("ping_role_id")
    if rid:
        role = guild.get_role(int(rid))
        parts.append(f"<span class='wc-pill info'>@{_esc(getattr(role, 'name', rid))}</span>")
    if entry.get("content"):
        parts.append(f"<div style='white-space:pre-wrap'>{_esc(entry['content'])}</div>")
    e = entry.get("embed") or {}
    if e.get("title") or e.get("description") or e.get("image_url"):
        color = _esc(e.get("color") or "#5865f2")
        emb = (f"<div class='card-x' style='border-left:4px solid {color};margin-top:8px;padding:12px 14px'>"
               + (f"<b>{_esc(e['title'])}</b>" if e.get("title") else "")
               + (f"<div style='white-space:pre-wrap;margin-top:4px'>{_esc(e['description'])}</div>"
                  if e.get("description") else "")
               + (f"<div class='wc-help' style='margin-top:6px'><i class='bi bi-image'></i> {_esc(e['image_url'])}</div>"
                  if e.get("image_url") else "")
               + "</div>")
        parts.append(emb)
    return "".join(parts) or "<span class='wc-muted'>(leer)</span>"


def _preview_card(cog, ui, guild, conf, values, now) -> str:
    raw = raw_from_form(_Multi(values))
    fields, err = cog.normalize(guild, raw)
    if err:
        return ui.callout("Vorschau nicht möglich: " + _esc(_plain(t("de", err[0], **err[1]))), tone="warn")
    tz = conf.get("timezone") or "Europe/Berlin"
    probe = {**fields, "anchor_ts": int(now)}
    upcoming, after = [], now
    for _ in range(5):
        nxt = cog.next_for(probe, tz, after)
        if nxt is None:
            break
        upcoming.append(nxt)
        after = nxt
    times = "".join(f"<li>{_esc(absolute(ts, tz))} <span class='wc-muted'>({_esc(rel(ts, now))})</span></li>"
                    for ts in upcoming) or "<li>kein künftiger Termin</li>"
    ch = cog._channel(guild, fields["channel_id"])
    body = (f"<div class='wc-muted'>#{_esc(getattr(ch, 'name', '?'))} · {_esc(timing.describe(fields['schedule']))}"
            f"</div><div class='wc-divider'></div>{_preview_html(cog, guild, fields)}"
            f"<div class='wc-divider'></div><div class='wc-help'><b>Nächste Termine:</b><ul>{times}</ul></div>")
    return ui.card("Vorschau (noch nicht gespeichert)", body, icon="bi-eye")


class _Multi(dict):
    """Entwurfs-Dict mit ``getall`` wie aiohttps MultiDict (für ``raw_from_form``)."""

    def getall(self, key, default=None):
        val = self.get(key)
        if val is None:
            return default if default is not None else []
        return val if isinstance(val, list) else [val]


def _render_edit(cog, ui, guild, conf, entry, csrf, now, draft, show_preview) -> str:
    tz = conf.get("timezone") or "Europe/Berlin"
    eid = str(entry.get("id"))
    values = draft if draft and draft.get("eid") == eid else values_from_entry(entry)
    label, tone = _status(entry)
    back = ui.button("Zurück zur Übersicht", icon="bi-arrow-left", kind="ghost", small=True,
                     href=f"/cogs/{SLUG}?guild={guild.id}#nachrichten")
    head = ui.hero("bi-clock-history", entry.get("name") or "Geplante Nachricht",
                   f"<span class='mono'>#{_esc(eid)}</span> · {ui.badge(label, tone)} · "
                   f"{_esc(timing.describe(entry.get('schedule') or {}))}<br><br>{back}")
    info = "<dl class='wc-kv'>"
    info += f"<dt>Nächste Ausführung</dt><dd>{_next_cell(entry, tz, now)}</dd>"
    if entry.get("last_run_ts"):
        info += (f"<dt>Zuletzt gesendet</dt><dd>{_esc(absolute(entry['last_run_ts'], tz))} "
                 f"({_esc(rel(entry['last_run_ts'], now))})</dd>")
    info += f"<dt>Ausführungen</dt><dd>{int(entry.get('run_count') or 0)}</dd>"
    if entry.get("last_skipped_ts"):
        info += (f"<dt>Übersprungen</dt><dd>{_esc(absolute(entry['last_skipped_ts'], tz))} – Bot war offline "
                 "(verpasste Termine werden nur bis 10 Minuten nachgeholt)</dd>")
    if entry.get("fail_count") or entry.get("last_error"):
        info += (f"<dt>Fehler in Folge</dt><dd>{int(entry.get('fail_count') or 0)} / {timing.MAX_FAILS}</dd>"
                 f"<dt>Letzter Fehler</dt><dd>{_esc(entry.get('last_error') or '—')}</dd>")
    info += "</dl>"
    toggle = (_action_form(ui, csrf, guild, eid, "resume", "Fortsetzen", "bi-play", kind="accent", back="edit")
              if entry.get("paused") else
              _action_form(ui, csrf, guild, eid, "pause", "Pausieren", "bi-pause", back="edit"))
    actions = ui.actions(
        _action_form(ui, csrf, guild, eid, "test", "Jetzt testen", "bi-send", back="edit",
                     confirm="Die Nachricht jetzt einmal in ihren Kanal posten (ohne Rollen-Ping)?"),
        toggle,
        _action_form(ui, csrf, guild, eid, "delete", "Löschen", "bi-trash", kind="danger",
                     confirm="Diese geplante Nachricht löschen?"),
    )
    warn = ""
    if entry.get("auto_paused"):
        warn = ui.callout(f"Automatisch pausiert nach {timing.MAX_FAILS} Fehlern in Folge. Ursache beheben und "
                          "„Fortsetzen“ klicken.", tone="bad")
    status = ui.card("Status", warn + info + "<div class='wc-divider'></div>" + actions, icon="bi-activity")
    if show_preview and draft.get("eid") == eid:
        preview = _preview_card(cog, ui, guild, conf, values, now)
    else:
        preview = ui.card("Vorschau (gespeicherter Stand)", _preview_html(cog, guild, entry), icon="bi-eye",
                          desc="So ungefähr erscheint die Nachricht in Discord.")
    return head + status + preview + _entry_form(ui, guild, conf, csrf, values, entry)


def _render_settings(ui, guild, conf, csrf, now) -> str:
    tz = conf.get("timezone") or "Europe/Berlin"
    local = datetime.fromtimestamp(now, timing.get_tz(tz)).strftime("%d.%m.%Y, %H:%M")
    card = ui.card("Allgemein", ui.grid(
        ui.field("Zeitzone", ui.text_input("timezone", tz, placeholder="Europe/Berlin"),
                 help=f"IANA-Name, z. B. <code>Europe/Berlin</code>, <code>Europe/Vienna</code>, <code>UTC</code>. "
                      f"Jetzt dort: {_esc(local)}. Beim Ändern werden alle Termine neu berechnet."),
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf.get("language", "de")),
                 help="Sprache der Bot-Antworten auf <code>[p]schedule</code>."),
    ), icon="bi-sliders")
    rule = ui.callout(
        "<b>Bot offline?</b> Verpasste Termine werden <b>nicht</b> nachgeholt – außer der letzte liegt weniger als "
        "10 Minuten zurück (z. B. bei einem kurzen Neustart). So kommen nach längerer Downtime keine alten "
        f"Nachrichten auf einmal. Nach {timing.MAX_FAILS} Fehlern in Folge (z. B. Kanal gelöscht, Rechte fehlen) "
        "pausiert ein Eintrag automatisch.")
    return ui.form(f"/cogs/{SLUG}", card + rule + ui.save_row("Einstellungen speichern"), csrf=csrf,
                   hidden={"form": "settings", "guild": guild.id}, savebar=True)


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

    if form == "settings":
        tz = (data.get("timezone") or "").strip()
        if not timing.valid_tz(tz):
            return {"redirect": base + "&err=" + quote(f"Unbekannte Zeitzone: {tz[:60]}") + "#einstellungen"}
        lang = (data.get("language") or "de").lower()
        gconf = cog.config.guild(guild)
        changed = tz != await gconf.timezone()
        await gconf.timezone.set(tz)
        await gconf.language.set(lang if lang in LANGUAGES else "de")
        if changed:
            await cog.recompute_all(guild)
        return {"redirect": base + "&ok=" + quote("Einstellungen gespeichert") + "#einstellungen"}

    if form == "entry":
        eid = str(data.get("eid") or "")
        target = base + (f"&edit={quote(eid)}" if eid else "")
        anchor = "" if eid else "#neu"
        if data.get("action") == "preview":
            _save_draft(cog, request, data)
            return {"redirect": target + "&draft=1&preview=1" + anchor}
        raw = raw_from_form(data)
        user = await request.app["webcore"].current_user(request)
        uid = (user or {}).get("id") or 0
        if eid:
            entry, err = await cog.update_entry(guild, eid, raw, editor_id=uid)
        else:
            entry, err = await cog.add_entry(guild, raw, creator_id=uid)
        if err:
            _save_draft(cog, request, data)
            return {"redirect": target + "&draft=1&err=" + quote(_plain(t("de", err[0], **err[1]))) + anchor}
        msg = "Gespeichert" if eid else "Nachricht geplant"
        if entry.get("next_run_ts"):
            msg += " – nächste Ausführung " + absolute(entry["next_run_ts"], await cog.config.guild(guild).timezone())
        return {"redirect": base + "&ok=" + quote(msg) + "#nachrichten"}

    if form == "action":
        eid = str(data.get("eid") or "")
        action = data.get("action")
        back = base + (f"&edit={quote(eid)}" if data.get("back") == "edit" and action != "delete" else "")
        if action == "test":
            ok, err = await cog.test_entry(guild, eid)
            return {"redirect": back + ("&ok=" + quote("Testnachricht gesendet (ohne Ping)") if ok
                                        else "&err=" + quote("Test fehlgeschlagen: " + _plain(err or "")))}
        if action in ("pause", "resume"):
            entry = await cog.set_paused(guild, eid, action == "pause")
            if entry is None:
                return {"redirect": base + "&err=" + quote("Eintrag nicht gefunden")}
            return {"redirect": back + "&ok=" + quote("Pausiert" if action == "pause" else "Fortgesetzt")}
        if action == "delete":
            ok = await cog.remove_entry(guild, eid)
            return {"redirect": base + ("&ok=" + quote("Gelöscht") if ok else "&err=" + quote("Eintrag nicht gefunden"))
                    + "#nachrichten"}
        return {"redirect": base + "&err=" + quote("Unbekannte Aktion")}

    return {"redirect": base + "&err=" + quote("Unbekanntes Formular")}
