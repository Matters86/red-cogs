"""Projektkalender im WebCore: Teamrechte plus Seitenrechte, ohne öffentliche Datenroute."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from .models import CalendarError, calendar_ics, duplicate_values, format_local, input_local, parse_reminders

SLUG = "teamcalendar"
TITLE = "Projektmanagement"
MONTHS = ("", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember")
STATUSES = {"scheduled": ("Geplant", "info"), "cancelled": ("Abgesagt", "bad"), "completed": ("Erledigt", "ok")}
RSVP = {"yes": "Dabei", "maybe": "Vielleicht", "no": "Nicht dabei"}
EVENT_FIELDS = ("title", "description", "project", "project_id", "location", "owner_id", "start", "end", "reminder_preset", "reminder_custom", "eid", "revision", "event_timezone")


def _zone(conf):
    try:
        return ZoneInfo(conf.get("timezone") or "Europe/Berlin")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


async def _actor(cog, request, guild):
    wc = request.app["webcore"]
    user = await wc.current_user(request) or {}
    uid = int(user.get("id") or 0)
    member = guild.get_member(uid) if uid else None
    if member is None and uid:
        try:
            member = await guild.fetch_member(uid)
        except Exception:
            member = None
    if member is None and uid in (getattr(cog.bot, "owner_ids", None) or set()):
        member = SimpleNamespace(id=uid, name=user.get("name") or "Bot-Owner", display_name=user.get("name") or "Bot-Owner", guild=guild)
    return member


def _pick(guilds, raw):
    raw = str(raw or "")
    return next((guild for guild in guilds if raw.isdigit() and guild.id == int(raw)), None)


def _url(guild, **params):
    return f"/cogs/{SLUG}?guild={guild.id}" + "".join(f"&{key}={quote_plus(str(value))}" for key, value in params.items() if value is not None)


def _redirect(guild, text, *, error=False, tab=None, **params):
    target = _url(guild, **params, **{"err" if error else "ok": text})
    raise web.HTTPFound(target + ("#" + quote_plus(tab) if tab else ""))


def _events(conf):
    from .project_models import label_project
    return sorted((dict(event, id=str(eid), project=label_project(conf, event)) for eid, event in (conf.get("events") or {}).items()),
                  key=lambda event: (int(event.get("start_ts") or 0), event["id"]))


def _draft_key(actor, kind, eid=""):
    return f"teamcalendar:{getattr(actor, 'id', 0)}:{kind}:{eid or 'new'}"


def discard_user(cog, user_id):
    """Kurzlebige Kalenderentwürfe einer Person bei einer Red-Löschanfrage verwerfen."""
    drafts = cog.__dict__.get("_ux_drafts", {})
    prefix = f"teamcalendar:{int(user_id)}:"
    for key in list(drafts):
        if len(key) >= 3 and str(key[2]).startswith(prefix):
            drafts.pop(key, None)


async def dashboard_handler(cog, request):
    wc = request.app["webcore"]
    guilds = await wc.visible_guilds(request)
    data = await request.post() if request.method == "POST" else request.query
    raw = data.get("guild")
    guild = _pick(guilds, raw) if raw is not None else (guilds[0] if guilds else None)
    if guild is None:
        if raw is not None:
            raise web.HTTPNotFound(text="Server nicht gefunden")
        return {"title": TITLE, "content": wc.ui.card(body=wc.ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    actor = await _actor(cog, request, guild)
    conf = await cog.config.guild(guild).all()
    if not cog.can_view(actor, conf):
        raise web.HTTPForbidden(text="Kein Zugriff auf den Projektkalender. Eine Team- oder Kalenderverwaltungsrolle ist erforderlich.")
    if request.method == "POST":
        from . import project_dashboard
        if str(data.get("form") or "") in project_dashboard.FORMS:
            return await project_dashboard.handle_post(cog, request, guild, actor, data)
        return await _post(cog, request, guild, actor, conf, data)
    if request.query.get("download") == "tasks_csv":
        from .project_models import tasks_csv
        payload = tasks_csv(conf.get("work_tasks") or {}, conf.get("projects") or {},
                            {member.id: member.display_name for member in guild.members}, conf["timezone"])
        return web.Response(body=payload, content_type="text/csv", charset="utf-8",
                            headers={"Content-Disposition": f'attachment; filename="tasks-{guild.id}.csv"', "Cache-Control": "private, no-store"})
    if request.query.get("download") == "ics":
        payload = calendar_ics(_events(conf), guild.id, guild.name)
        return web.Response(body=payload, content_type="text/calendar", charset="utf-8",
                            headers={"Content-Disposition": f'attachment; filename="teamcalendar-{guild.id}.ics"',
                                     "Cache-Control": "private, no-store"})
    return await _render(cog, request, guild, actor, conf)


async def _post(cog, request, guild, actor, conf, data):
    wc = request.app["webcore"]
    form = str(data.get("form") or "")
    operate = form in {"event_save", "event_action", "rsvp", "board_refresh"}
    page_allowed = await (wc.can_operate(request, guild) if operate else wc.can_edit(request, guild))
    if await cog.bot.cog_disabled_in_guild(cog, guild):
        _redirect(guild, "Der Projektkalender ist auf diesem Server deaktiviert", error=True)
    conf = await cog.config.guild(guild).all()
    actor = actor if getattr(actor, "id", None) in (getattr(cog.bot, "owner_ids", None) or set()) else guild.get_member(getattr(actor, "id", None))
    if operate:
        allowed = page_allowed and (cog.can_view(actor, conf) if form == "rsvp" else cog.can_manage(actor, conf))
    else:
        allowed = page_allowed and cog.can_configure(actor, conf)
    if not allowed:
        _redirect(guild, "Keine Berechtigung für diese Kalenderaktion", error=True)
    eid = str(data.get("eid") or "")
    try:
        if form == "event_save":
            values = {field: str(data.get(field) or "") for field in EVENT_FIELDS}
            if values["event_timezone"] != conf["timezone"]:
                raise CalendarError("Die Formular-Zeitzone fehlt oder wurde inzwischen geändert. Deine Eingaben bleiben erhalten; bitte den aktuellen Stand neu laden und die Zeiten prüfen.")
            raw = {key: values[key] for key in ("title", "description", "project", "location", "owner_id", "start", "end")}
            if "project_id" in data:
                raw["project_id"] = values["project_id"]
            raw["event_timezone"] = values["event_timezone"]
            raw["reminder_minutes"] = _reminders(values["reminder_custom"] if values["reminder_preset"] == "custom" else values["reminder_preset"])
            if eid:
                saved = await cog.update_event(guild, actor, eid, raw, revision=_revision(data))
            else:
                saved = await cog.create_event(guild, actor, raw)
            wc.drafts.discard(cog, request, guild.id, _draft_key(actor, "event", eid))
            _redirect(guild, "Termin gespeichert", event=saved["id"], tab="agenda")
        if form == "event_action":
            saved = await cog.event_action(guild, actor, eid, str(data.get("action") or ""), revision=_revision(data))
            _redirect(guild, "Termin aktualisiert", event=saved["id"] if saved else None, tab="agenda")
        if form == "rsvp":
            await cog.set_rsvp(guild, actor, eid, str(data.get("status") or ""))
            _redirect(guild, "Rückmeldung gespeichert", event=eid, tab="agenda")
        if form == "settings":
            raw = {key: str(data.get(key) or "") for key in ("timezone", "reminder_channel", "keep_days")}
            raw.update(team_roles=list(data.getall("team_roles", [])), manager_roles=list(data.getall("manager_roles", [])),
                       team_can_manage="team_can_manage" in data,
                       reminder_minutes=_reminders(data.get("reminder_minutes") or ""))
            if "task_edit_mode" in data:
                raw["task_edit_mode"] = str(data.get("task_edit_mode") or "")
            if "task_reminder_minutes" in data:
                raw["task_reminder_minutes"] = str(data.get("task_reminder_minutes") or "")
            await cog.save_settings(guild, actor, raw)
            wc.drafts.discard(cog, request, guild.id, _draft_key(actor, "settings"))
            _redirect(guild, "Kalendereinstellungen gespeichert", tab="einstellungen")
        if form == "board_publish":
            raw_channel = str(data.get("channel") or "")
            channel = guild.get_channel(int(raw_channel)) if raw_channel.isdigit() else None
            if channel is None or channel not in guild.text_channels:
                raise CalendarError("Bitte einen Textkanal dieses Servers auswählen.")
            await cog.post_board(guild, actor, channel)
            fresh = await cog.config.guild(guild).all()
            if fresh.get("board_error"):
                raise CalendarError(str(fresh["board_error"]))
            _redirect(guild, "Kalender in Discord veröffentlicht", tab="einstellungen")
        if form == "board_refresh":
            if not conf.get("calendar_channel"):
                raise CalendarError("Veröffentliche zuerst den Kalender in einem Teamkanal.")
            await cog.refresh_board(guild, actor=actor)
            fresh = await cog.config.guild(guild).all()
            if fresh.get("board_error"):
                raise CalendarError("Discord-Aktualisierung fehlgeschlagen: " + str(fresh["board_error"]))
            _redirect(guild, "Discord-Kalender aktualisiert")
        raise CalendarError("Unbekannte Kalenderaktion.")
    except CalendarError as exc:
        if form == "event_save":
            wc.drafts.remember(cog, request, guild.id, _draft_key(actor, "event", eid),
                               {field: str(data.get(field) or "")[:4100] for field in EVENT_FIELDS})
            _redirect(guild, str(exc), error=True, edit=eid or None, draft="event", tab="planen")
        if form == "settings":
            wc.drafts.remember(cog, request, guild.id, _draft_key(actor, "settings"),
                               {**dict(data), "team_roles": list(data.getall("team_roles", [])), "manager_roles": list(data.getall("manager_roles", [])),
                                "team_can_manage": "team_can_manage" in data})
            _redirect(guild, str(exc), error=True, draft="settings", tab="einstellungen")
        _redirect(guild, str(exc), error=True, event=eid or None, tab="einstellungen" if form == "board_publish" else "agenda")


def _revision(data):
    try:
        value = int(data.get("revision"))
        if value < 1:
            raise ValueError()
        return value
    except (TypeError, ValueError):
        raise CalendarError("Der Bearbeitungsstand fehlt. Bitte den Termin neu öffnen.") from None


def _reminders(raw):
    return parse_reminders(str(raw or "").strip())


def _stamp(event, conf):
    return format_local(event["start_ts"], conf["timezone"]) + " – " + format_local(event["end_ts"], conf["timezone"])


def _person(guild, uid):
    member = guild.get_member(int(uid)) if str(uid or "").isdigit() else None
    return member.display_name if member is not None else (f"ID {uid}" if uid else "Nicht zugewiesen")


def _event_link(ui, guild, event):
    return f"<a href='{ui.esc(_url(guild, event=event['id']))}'>{ui.esc(event.get('title') or 'Termin')}</a>"


async def _render(cog, request, guild, actor, conf):
    wc, ui = request.app["webcore"], request.app["webcore"].ui
    csrf = request.get("webcore_csrf", "")
    managing = cog.can_manage(actor, conf) and await wc.can_operate(request, guild)
    configuring = cog.can_configure(actor, conf) and await wc.can_edit(request, guild)
    rsvp_allowed = await wc.can_operate(request, guild)
    events = _events(conf)
    project = str(request.query.get("project") or "")
    filtered = [event for event in events if not project or event.get("project") == project]
    now = int(datetime.now(timezone.utc).timestamp())
    upcoming = [event for event in filtered if event.get("status") == "scheduled" and event.get("end_ts", 0) >= now]
    active_tasks = [task for task in (conf.get("work_tasks") or {}).values() if task.get("status") != "done"
                    and ((conf.get("projects") or {}).get(str(task.get("project_id") or "")) or {}).get("status") not in {"archived", "completed"}]
    head = ui.hero("bi-kanban", "", "Projekte, Aufgaben und Termine für dein Team. Plane Arbeit gemeinsam, verteile Zuständigkeiten und behalte Fristen im Blick. "
                   "<b>Zeitzone:</b> " + ui.esc(conf["timezone"]) + ".",
                   actions=ui.button("Kalender exportieren (.ics)", href=_url(guild, download="ics"), icon="bi-download", kind="ghost"))
    head += ui.stats([("Projekte", len(conf.get("projects") or {}), "bi-folder"),
                      ("Offene Aufgaben", len(active_tasks), "bi-check2-square", "Ohne abgeschlossene und archivierte Projekte"),
                      ("Überfällige Aufgaben", sum(task.get("due_ts") is not None and task["due_ts"] < now for task in active_tasks), "bi-exclamation-circle"),
                      ("Anstehende Termine", sum(event.get("status") == "scheduled" and event.get("end_ts", 0) >= now for event in events), "bi-calendar-event")])
    if not conf.get("team_roles"):
        head += ui.callout("Noch keine Teamrollen eingerichtet. Unter <b>Einstellungen</b> Teamrollen auswählen; "
                           "sie benötigen in WebCore zusätzlich <b>Bedienen</b> für den Projektkalender. Neue Kalender sind zunächst nur für die Kalenderverwaltung zugänglich.", tone="warn")
    if not managing:
        head += ui.callout("Du liest diesen Kalender. Termine ändern braucht die Kalender-Teamrechte und in WebCore mindestens <b>Bedienen</b>.", tone="info")
    if conf.get("board_error") and managing:
        retry = ui.form(f"/cogs/{SLUG}", ui.button("Discord-Aktualisierung erneut versuchen", kind="ghost", small=True),
                        csrf=csrf, hidden={"guild": guild.id, "form": "board_refresh"}, operate=True) if conf.get("calendar_channel") else ""
        head += ui.callout("Discord-Übersicht: " + ui.esc(conf["board_error"]) + retry, tone="warn")
    selected = str(request.query.get("event") or "")
    if selected:
        event = next((event for event in events if event["id"] == selected), None)
        if event is None:
            raise web.HTTPNotFound(text="Termin nicht gefunden")
        head += _detail(ui, guild, conf, event, actor, csrf, managing, rsvp_allowed)
    from . import project_dashboard
    project_head, project_tabs = await project_dashboard.render(cog, request, guild, actor, conf)
    head += project_head
    agenda = _agenda(ui, guild, conf, filtered, upcoming, project, request.query.get("range", "upcoming"))
    month = _month(ui, guild, conf, filtered, request.query.get("month"), project)
    body = project_tabs + ui.tab("agenda", "Agenda", "bi-list-ul", agenda) + ui.tab("monat", "Monat", "bi-calendar3", month)
    if managing:
        body += ui.tab("planen", "Termin planen", "bi-calendar-plus", _editor(cog, request, ui, guild, actor, conf, csrf))
    if configuring:
        body += ui.tab("einstellungen", "Einstellungen", "bi-sliders", _settings(cog, request, ui, guild, actor, conf, csrf))
    return {"title": TITLE, "content": head + body}


def _agenda(ui, guild, conf, events, upcoming, project, selected_range):
    projects = sorted({event.get("project") for event in _events(conf) if event.get("project")}, key=str.casefold)
    filters = ui.form(f"/cogs/{SLUG}", ui.grid(
        ui.field("Projekt", ui.select("project", [(value, value) for value in projects], project, none_label="Alle Projekte")),
        ui.field("Zeitraum", ui.select("range", [("upcoming", "Anstehende Termine"), ("all", "Alle Termine und Absagen")], selected_range)),
    ) + ui.button("Anzeigen", icon="bi-funnel", kind="ghost"), csrf="", hidden={"guild": guild.id}, method="get")
    shown = events if selected_range == "all" else upcoming
    rows = []
    for event in shown[:200]:
        status, tone = STATUSES.get(event.get("status"), ("Unbekannt", "muted"))
        counts = event.get("participants") or {}
        summary = " · ".join(f"{label}: {sum(value == key for value in counts.values())}" for key, label in RSVP.items())
        rows.append(ui.row(_event_link(ui, guild, event), ui.esc(_stamp(event, conf)), ui.esc(event.get("project") or "—"),
                           ui.esc(_person(guild, event.get("owner_id"))), ui.badge(status, tone), ui.esc(summary)))
    more = ui.callout(f"Die Agenda zeigt die ersten 200 von {len(shown)} Terminen. Grenze die Auswahl über das Projekt ein oder nutze die Monatsansicht.", tone="info") if len(shown) > 200 else ""
    return ui.card("Termine", filters + ui.table(["Termin", "Zeit", "Projekt", "Verantwortlich", "Status", "Rückmeldungen"], rows,
        empty_text="Keine Termine für diese Auswahl.", search=len(rows) > 8, id="teamcalendar-agenda") + more,
        desc="Alle Zeiten in " + ui.esc(conf["timezone"]) + ". Termin öffnen für Details, Rückmeldung und Bearbeitung.", icon="bi-list-ul")


def _month(ui, guild, conf, events, raw_month, project):
    today = datetime.now(_zone(conf)).date()
    try:
        first = date.fromisoformat(str(raw_month) + "-01") if raw_month else today.replace(day=1)
        if not 2 <= first.year <= 9998:
            raise ValueError()
    except ValueError:
        first = today.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    label = f"{MONTHS[first.month]} {first.year}"
    actions = ui.button("Voriger Monat", href=_url(guild, month=previous.strftime("%Y-%m"), project=project) + "#monat", kind="ghost", small=True)
    actions += ui.button("Heute", href=_url(guild, project=project) + "#monat", kind="ghost", small=True)
    actions += ui.button("Nächster Monat", href=_url(guild, month=next_month.strftime("%Y-%m"), project=project) + "#monat", kind="ghost", small=True)
    weeks, occupied = [], False
    for week in calendar.monthcalendar(first.year, first.month):
        cells = []
        for number in week:
            if not number:
                cells.append({"day": "", "body": "", "muted": True})
                continue
            day = first.replace(day=number)
            begin = datetime.combine(day, datetime.min.time(), _zone(conf)).timestamp()
            end = datetime.combine(day + timedelta(days=1), datetime.min.time(), _zone(conf)).timestamp()
            on_day = [event for event in events if event.get("start_ts", 0) < end and event.get("end_ts", 0) > begin]
            occupied = occupied or bool(on_day)
            body = []
            for event in on_day:
                time = datetime.fromtimestamp(event["start_ts"], _zone(conf)).strftime("%H:%M")
                badge = "" if event.get("status") == "scheduled" else " · " + STATUSES.get(event.get("status"), ("", ""))[0]
                body.append("<div class='wc-month-entry'>" + _event_link(ui, guild, event) + f"<small> {ui.esc(time + badge)}</small></div>")
            cells.append({"day": str(number), "body": "".join(body), "today": day == today})
        weeks.append(cells)
    return ui.card(label, ui.month_grid(weeks, label=label) + (ui.empty("bi-calendar3", "Keine Termine in diesem Monat.") if not occupied else ""), actions=actions, icon="bi-calendar3",
                   desc="Mehrtagestermine erscheinen an jedem betroffenen Tag. Zeiten: " + ui.esc(conf["timezone"]) + ".")


def _detail(ui, guild, conf, event, actor, csrf, managing, rsvp_allowed):
    status, tone = STATUSES.get(event.get("status"), ("Unbekannt", "muted"))
    description = ui.esc(event.get("description") or "Keine Beschreibung.").replace("\n", "<br>")
    body = ui.badge(status, tone) + "<p>" + ui.esc(_stamp(event, conf)) + "</p><p>" + description + "</p>"
    body += ui.grid(ui.field("Projekt", ui.esc(event.get("project") or "—")),
                    ui.field("Ort / Link", ui.esc(event.get("location") or "—")),
                    ui.field("Verantwortlich", ui.esc(_person(guild, event.get("owner_id")))),
                    ui.field("Erinnerungen", ui.esc(", ".join(f"{value} Min. vorher" for value in event.get("reminder_minutes", [])) or "Keine")))
    participants = event.get("participants") or {}
    body += ui.columns(*(ui.card(label, "<br>".join(ui.esc(_person(guild, uid)) for uid, value in participants.items() if value == key) or "—")
                         for key, label in RSVP.items()), cols=3)
    if rsvp_allowed and event.get("status") == "scheduled" and event.get("end_ts", 0) > datetime.now(timezone.utc).timestamp():
        body += ui.form(f"/cogs/{SLUG}", ui.field("Deine Rückmeldung", ui.select("status", [("remove", "Keine Rückmeldung"), *RSVP.items()],
            participants.get(str(getattr(actor, "id", 0)), "remove"))) + ui.button("Rückmeldung speichern", small=True),
            csrf=csrf, hidden={"guild": guild.id, "form": "rsvp", "eid": event["id"]}, operate=True)
    if managing:
        body += ui.button("Bearbeiten", href=_url(guild, edit=event["id"]) + "#planen", icon="bi-pencil", kind="ghost")
        body += ui.button("Als neuen Termin +7 Tage kopieren", href=_url(guild, copy=event["id"]) + "#planen", icon="bi-copy", kind="ghost")
        controls = []
        actions = [("cancel", "Absagen"), ("complete", "Erledigt")] if event.get("status") == "scheduled" else [("reopen", "Wieder planen")]
        actions += [("delete", "Löschen")]
        for action, title in actions:
            controls.append(ui.form(f"/cogs/{SLUG}", ui.button(title, small=True, kind="danger" if action in ("cancel", "delete") else "ghost"),
                csrf=csrf, hidden={"guild": guild.id, "form": "event_action", "eid": event["id"], "revision": event.get("revision"), "action": action},
                confirm=f"Termin „{event.get('title') or 'Termin'}“ endgültig löschen?" if action == "delete" else
                        (f"Termin „{event.get('title') or 'Termin'}“ absagen?" if action == "cancel" else None), operate=True))
        body += "<div class='wc-row-actions'>" + "".join(controls) + "</div>"
    return ui.card(event.get("title") or "Termin", body, icon="bi-calendar-event")


def _editor(cog, request, ui, guild, actor, conf, csrf):
    eid, copied = str(request.query.get("edit") or ""), str(request.query.get("copy") or "")
    event = (conf.get("events") or {}).get(eid or copied) if (eid or copied) else None
    if (eid or copied) and event is None:
        raise web.HTTPNotFound(text="Termin nicht gefunden")
    local = datetime.now(_zone(conf)).replace(second=0, microsecond=0) + timedelta(hours=1)
    values = {"start": local.strftime("%Y-%m-%dT%H:%M"), "end": (local + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
              "owner_id": str(getattr(actor, "id", "")), "event_timezone": conf["timezone"],
              "reminder_preset": ",".join(str(value) for value in conf.get("reminder_minutes", []))}
    if event:
        values.update({field: event.get(field) or "" for field in ("title", "description", "project", "location", "owner_id")})
        if copied and not eid:
            values.update(duplicate_values(event, conf["timezone"]))
        else:
            values.update(start=input_local(event["start_ts"], conf["timezone"]), end=input_local(event["end_ts"], conf["timezone"]))
        values["reminder_preset"] = ",".join(str(value) for value in event.get("reminder_minutes", []))
        values["project_id"] = event.get("project_id") or ""
    known = ("", "60", "1440", "1440,60")
    if values.get("reminder_preset") not in known:
        values.update(reminder_custom=values.get("reminder_preset", ""), reminder_preset="custom")
    if request.query.get("draft") == "event":
        values.update(request.app["webcore"].drafts.restore(cog, request, guild.id, _draft_key(actor, "event", eid)))
    members = [(member.id, f"{member.display_name} (@{member.name})") for member in guild.members if not member.bot and cog.can_view(member, conf)]
    content = ui.grid(
        ui.field("Titel", ui.text_input("title", values.get("title", ""), attrs={"required": True, "maxlength": 100}), wide=True),
        ui.field("Beginn", ui.text_input("start", values.get("start"), type="datetime-local", attrs={"required": True}), help="Ortszeit in " + ui.esc(values.get("event_timezone") or conf["timezone"])),
        ui.field("Ende", ui.text_input("end", values.get("end"), type="datetime-local", attrs={"required": True})),
        ui.field("Projekt verknüpfen", ui.select("project_id", [(str(pid), item["name"]) for pid, item in (conf.get("projects") or {}).items()], values.get("project_id"), none_label="Kein Projekt verknüpft"), help="Verwendet den aktuellen Projektnamen und verknüpft diesen Termin mit dem Projekt."),
        ui.field("Freie Projektbezeichnung", ui.text_input("project", values.get("project", ""), attrs={"maxlength": 80}), help="Bestehende freie Angaben bleiben verwendbar. Gilt, wenn kein Projekt verknüpft ist."),
        ui.field("Verantwortlich", ui.select("owner_id", members, values.get("owner_id"), none_label="Nicht zugewiesen")),
        ui.field("Ort / Besprechungslink", ui.text_input("location", values.get("location", ""), attrs={"maxlength": 200}), wide=True),
        ui.field("Beschreibung", ui.textarea("description", values.get("description", ""), rows=4), help="Höchstens 2000 Zeichen.", wide=True),
        ui.field("Erinnerungen", ui.select("reminder_preset", [("", "Keine"), ("60", "1 Stunde vorher"), ("1440", "24 Stunden vorher"),
                 ("1440,60", "24 Stunden und 1 Stunde vorher"), ("custom", "Eigene Minuten")], values.get("reminder_preset", "")),
                 help="Im eingerichteten Erinnerungskanal; ohne Rollen- oder Nutzer-Pings."),
        ui.conditional("reminder_preset", ["custom"], ui.field("Minuten vor Beginn", ui.text_input("reminder_custom", values.get("reminder_custom", "")),
                       help="Mit Komma trennen, z. B. <code>1440,60</code>; höchstens drei Werte zwischen 1 Minute und 7 Tagen.")),
    )
    hidden = {"guild": guild.id, "form": "event_save", "eid": eid,
              "revision": values.get("revision") or (event or {}).get("revision") if eid else "",
              "event_timezone": values.get("event_timezone") or ""}
    notice = ui.callout("Kopie mit Beginn und Ende sieben lokale Kalendertage später. Zu- und Absagen werden nicht übernommen. Erst Speichern legt den neuen Termin an.") if copied and not eid else ""
    if request.query.get("draft") == "event":
        notice += ui.callout("Deine Eingaben bleiben erhalten. Falls der Termin inzwischen geändert wurde: "
                            + ui.button("Aktuellen Stand neu laden", href=_url(guild, edit=eid or None) + "#planen", kind="ghost", small=True))
        if values.get("event_timezone") != conf["timezone"]:
            notice += ui.callout("Die Kalender-Zeitzone ist jetzt <b>" + ui.esc(conf["timezone"]) + "</b>; dieses Formular stammt aus <b>"
                                + ui.esc(values.get("event_timezone") or "unbekannter Zeitzone") + "</b>. Neu laden und Zeiten prüfen, bevor du speicherst.", tone="warn")
    return ui.card("Termin bearbeiten" if eid else "Neuer Termin", notice + ui.form(f"/cogs/{SLUG}", content + ui.save_row("Änderungen speichern" if eid else "Termin anlegen"),
                   csrf=csrf, hidden=hidden, savebar=True, operate=True), icon="bi-calendar-plus",
                   desc="Alle berechtigten Teammitglieder dürfen die Termine verwalten. Verantwortlichkeit schränkt die Bearbeitung nicht ein.")


def _settings(cog, request, ui, guild, actor, conf, csrf):
    values = dict(conf)
    if request.query.get("draft") == "settings":
        values.update(request.app["webcore"].drafts.restore(cog, request, guild.id, _draft_key(actor, "settings")))
    roles = [(role.id, role.name) for role in sorted(guild.roles, key=lambda role: role.position, reverse=True) if not role.is_default()]
    channels = [(channel.id, "#" + channel.name) for channel in guild.text_channels]
    reminder_value = values.get("reminder_minutes", [])
    if not isinstance(reminder_value, str):
        reminder_value = ",".join(str(value) for value in reminder_value)
    content = ui.grid(
        ui.field("Teamrollen", ui.select("team_roles", roles, values.get("team_roles"), multiple=True),
                 help="Teammitglieder lesen den Kalender und geben Rückmeldungen. Mit dem folgenden Schalter verwalten alle auch fremde Termine."),
        ui.field("Kalenderverwaltung", ui.select("manager_roles", roles, values.get("manager_roles"), multiple=True),
                 help="Zusätzliche Rollen für Termine und Einrichtung. Administratoren, Server- und Bot-Owner behalten Zugriff."),
        ui.field("Terminverwaltung im Team", ui.switch("team_can_manage", "Alle Teammitglieder dürfen Termine verwalten", bool(values.get("team_can_manage", True))), wide=True),
        ui.field("Projekt- und Aufgabenverwaltung", ui.select("task_edit_mode", [("team", "Das ganze Team verwaltet Projekte und Aufgaben"),
                 ("assigned", "Verwaltung plant; Zuständige bearbeiten Fortschritt und Kommentare")], values.get("task_edit_mode", "team")),
                 help="Standard: alle berechtigten Teammitglieder. Im zugewiesenen Modus bleiben Erstellen, vollständiges Bearbeiten und Zuweisen der Kalenderverwaltung vorbehalten.", wide=True),
        ui.field("Zeitzone", ui.text_input("timezone", values.get("timezone", "Europe/Berlin")), help="IANA-Zeitzone, z. B. <code>Europe/Berlin</code> oder <code>UTC</code>. Bestehende Zeitpunkte bleiben erhalten."),
        ui.field("Standard-Erinnerungen (Minuten)", ui.text_input("reminder_minutes", reminder_value), help="Für neue Termine, z. B. <code>1440,60</code>. Leer = keine Erinnerungen."),
        ui.field("Aufgaben-Erinnerungen (Minuten)", ui.text_input("task_reminder_minutes", ",".join(str(value) for value in values.get("task_reminder_minutes", [1440, 60, 0])) if not isinstance(values.get("task_reminder_minutes"), str) else values["task_reminder_minutes"]),
                 help="Für offene Aufgaben mit Frist. Höchstens drei Werte von 0 bis 10080; 0 = bei Fälligkeit. Leer = aus."),
        ui.field("Erinnerungskanal", ui.select("reminder_channel", channels, values.get("reminder_channel"), none_label="Kalenderkanal verwenden"),
                 help="Termininhalte sind für alle Leser dieses Kanals sichtbar. Wähle einen privaten Teamkanal."),
        ui.field("Aufbewahrung vergangener Termine", ui.number("keep_days", values.get("keep_days", 180), min=1, max=3650, unit="Tage")),
    )
    settings = ui.card("Zugriff und Zeiten", ui.callout("Teamrollen brauchen in <b>WebCore → Zugriff &amp; Rollen</b> zusätzlich mindestens <b>Bedienen</b> für den Projektkalender. "
                         "Einrichtung braucht <b>Bearbeiten</b> und Kalenderverwaltung. Der Standard erlaubt allen Teammitgliedern die Terminverwaltung.")
                       + ui.form(f"/cogs/{SLUG}", content + ui.save_row(), csrf=csrf,
                                 hidden={"guild": guild.id, "form": "settings"}, savebar=True), icon="bi-sliders")
    board_body = ui.callout("Veröffentliche den Kalender nur in einem passenden Teamkanal. Alle Kanal-Leser können die dort gezeigten Termine sehen. "
                            "Ansichten und Export veröffentlichen nichts; der folgende Button postet ausdrücklich in Discord. Ein bereits veröffentlichter Kalender wird bei Änderungen aktualisiert.")
    board_body += ui.form(f"/cogs/{SLUG}", ui.field("Kalenderkanal", ui.select("channel", channels, conf.get("calendar_channel"), none_label="Kanal auswählen"))
                         + ui.button("Kalender dort veröffentlichen", icon="bi-send"), csrf=csrf,
                         hidden={"guild": guild.id, "form": "board_publish"},
                         confirm="Kalender in diesem Discord-Kanal veröffentlichen? Alle Kanal-Leser können die Termine sehen.")
    if conf.get("calendar_channel"):
        if conf.get("board_message_id"):
            jump = f"https://discord.com/channels/{guild.id}/{conf['calendar_channel']}/{conf['board_message_id']}"
            board_body += ui.button("In Discord öffnen", href=jump, kind="ghost", icon="bi-box-arrow-up-right")
        board_body += ui.form(f"/cogs/{SLUG}", ui.button("Aktualisierung erneut versuchen", kind="ghost", icon="bi-arrow-clockwise"),
                              csrf=csrf, hidden={"guild": guild.id, "form": "board_refresh"}, operate=True)
    if conf.get("board_error"):
        board_body += ui.callout("Letzte Discord-Aktualisierung: " + ui.esc(conf["board_error"]), tone="bad")
    from . import project_dashboard
    return settings + ui.card("Kalender in Discord", board_body, icon="bi-discord") + project_dashboard.settings(ui, guild, conf, csrf)
