"""Projekte und Aufgaben im bestehenden Kalender-Dashboard; alle Writes über den Core."""
from __future__ import annotations

from datetime import datetime, timezone

from aiohttp import web

from .models import CalendarError, format_local, input_local
from .project_models import project_progress
from .dashboard import _draft_key, _person, _redirect, _revision, _url

FORMS = {"project_save", "project_action", "task_save", "task_action", "task_assign", "task_check",
         "task_comment", "task_comment_delete", "task_board_publish", "task_board_refresh"}
STATUS = {"todo": "Offen", "in_progress": "In Arbeit", "blocked": "Blockiert", "done": "Erledigt"}
PRIORITY = {"low": "Niedrig", "normal": "Normal", "high": "Hoch", "urgent": "Dringend"}
PROJECT_STATUS = {"active": "Aktiv", "paused": "Pausiert", "completed": "Abgeschlossen", "archived": "Archiviert"}
TASK_FIELDS = ("title", "description", "project_id", "due", "priority", "event_id", "checklist", "task_timezone", "revision", "tid")
PROJECT_FIELDS = ("name", "description", "owner_id", "deadline", "task_timezone", "revision", "pid")


def _task_link(ui, guild, task):
    return "<a href='" + ui.esc(_url(guild, task=task["id"]) + "#aufgabenboard") + "'>" + ui.esc(task["title"]) + "</a>"


def _project_name(conf, pid):
    return ((conf.get("projects") or {}).get(str(pid)) or {}).get("name") or "Ohne Projekt"


def _sorted_tasks(conf):
    return sorted((dict(task, id=str(tid)) for tid, task in (conf.get("work_tasks") or {}).items()),
                  key=lambda task: (task.get("due_ts") is None, task.get("due_ts") or 0, int(task["id"]) if task["id"].isdigit() else task["id"]))


def _draft_values(data, fields):
    values = {key: str(data.get(key) or "")[:4100] for key in fields}
    if "tid" in fields:
        values.update(assignee_ids=list(data.getall("assignee_ids", []))[:10], milestone="milestone" in data)
    return values


async def handle_post(cog, request, guild, actor, data):
    wc = request.app["webcore"]
    form = str(data.get("form") or "")
    page_allowed = await (wc.can_edit(request, guild) if form == "task_board_publish" else wc.can_operate(request, guild))
    if await cog.bot.cog_disabled_in_guild(cog, guild):
        _redirect(guild, "Der Projektkalender ist deaktiviert", error=True)
    conf = await cog.config.guild(guild).all()
    actor = actor if getattr(actor, "id", None) in (getattr(cog.bot, "owner_ids", None) or set()) else guild.get_member(getattr(actor, "id", None))
    if not page_allowed or not cog.can_view(actor, conf):
        _redirect(guild, "Keine Berechtigung für diese Projektaktion", error=True)
    tid, pid = str(data.get("tid") or ""), str(data.get("pid") or "")
    task = (conf.get("work_tasks") or {}).get(tid)
    if form.startswith("project_"):
        allowed = cog.can_manage_projects(actor, conf)
    elif form == "task_board_publish":
        allowed = cog.can_configure(actor, conf)
    elif form == "task_comment_delete":
        comment = next((item for item in (task or {}).get("comments", []) if str(item.get("id")) == str(data.get("comment_id") or "")), None)
        allowed = comment is not None and (comment.get("author_id") == getattr(actor, "id", None) or cog.can_configure(actor, conf))
    elif form in {"task_comment", "task_check"}:
        allowed = task is not None and cog.can_work_task(actor, conf, task)
    elif form == "task_action" and data.get("action") != "delete":
        allowed = task is not None and cog.can_work_task(actor, conf, task)
    elif form == "task_board_refresh":
        allowed = cog.can_manage_projects(actor, conf)
    else:
        allowed = cog.can_edit_task(actor, conf, task)
    if not allowed:
        _redirect(guild, "Keine Berechtigung für diese Projektaktion", error=True, tab="aufgabenboard")
    try:
        if form in {"project_save", "task_save"}:
            if str(data.get("task_timezone") or "") != conf["timezone"]:
                raise CalendarError("Die Formular-Zeitzone fehlt oder wurde geändert. Bitte den aktuellen Stand neu laden und die Frist prüfen.")
        if form == "project_save":
            raw = {key: str(data.get(key) or "") for key in ("name", "description", "owner_id", "deadline", "task_timezone")}
            saved = await cog.update_project(guild, actor, pid, raw, revision=_revision(data)) if pid else await cog.create_project(guild, actor, raw)
            wc.drafts.discard(cog, request, guild.id, _draft_key(actor, "project", pid))
            _redirect(guild, "Projekt gespeichert", pm_project=saved["id"], tab="projekte")
        if form == "project_action":
            saved = await cog.project_action(guild, actor, pid, str(data.get("action") or ""), revision=_revision(data))
            _redirect(guild, "Projekt aktualisiert", pm_project=saved["id"] if saved else None, tab="projekte")
        if form == "task_save":
            raw = {key: str(data.get(key) or "") for key in ("title", "description", "project_id", "due", "priority", "event_id", "checklist", "task_timezone")}
            raw.update(assignee_ids=list(data.getall("assignee_ids", [])), milestone="milestone" in data)
            saved = await cog.update_task(guild, actor, tid, raw, revision=_revision(data)) if tid else await cog.create_task(guild, actor, raw)
            wc.drafts.discard(cog, request, guild.id, _draft_key(actor, "task", tid))
            _redirect(guild, "Aufgabe gespeichert", task=saved["id"], tab="aufgabenboard")
        if form == "task_action":
            saved = await cog.task_action(guild, actor, tid, str(data.get("action") or ""), revision=_revision(data))
        elif form == "task_assign":
            saved = await cog.assign_task(guild, actor, tid, list(data.getall("assignee_ids", [])), revision=_revision(data))
        elif form == "task_check":
            if data.get("done") not in ("yes", "no"):
                raise CalendarError("Ungültiger Checklistenstatus.")
            saved = await cog.toggle_checklist(guild, actor, tid, str(data.get("item_id") or ""), data.get("done") == "yes", revision=_revision(data))
        elif form == "task_comment":
            saved = await cog.add_task_comment(guild, actor, tid, str(data.get("text") or ""))
            wc.drafts.discard(cog, request, guild.id, _draft_key(actor, "comment", tid))
        elif form == "task_comment_delete":
            saved = await cog.delete_task_comment(guild, actor, tid, str(data.get("comment_id") or ""))
        elif form == "task_board_publish":
            raw = str(data.get("channel") or "")
            channel = guild.get_channel(int(raw)) if raw.isdigit() else None
            if channel is None or channel not in guild.text_channels:
                raise CalendarError("Bitte einen Textkanal dieses Servers auswählen.")
            await cog.post_task_board(guild, actor, channel)
            fresh = await cog.config.guild(guild).all()
            if fresh.get("task_board_error"):
                raise CalendarError(str(fresh["task_board_error"]))
            _redirect(guild, "Aufgabenübersicht veröffentlicht", tab="einstellungen")
        elif form == "task_board_refresh":
            if not conf.get("task_board_channel"):
                raise CalendarError("Veröffentliche zuerst eine Aufgabenübersicht in einem Teamkanal.")
            await cog.refresh_task_board(guild, actor=actor)
            fresh = await cog.config.guild(guild).all()
            if fresh.get("task_board_error"):
                raise CalendarError(str(fresh["task_board_error"]))
            _redirect(guild, "Aufgabenübersicht aktualisiert", tab="aufgabenboard")
        else:
            raise CalendarError("Unbekannte Projektaktion.")
        _redirect(guild, "Aufgabe aktualisiert", task=saved["id"] if saved else None, tab="aufgabenboard")
    except CalendarError as exc:
        if form in {"project_save", "task_save"}:
            kind, ident, fields = ("project", pid, PROJECT_FIELDS) if form == "project_save" else ("task", tid, TASK_FIELDS)
            wc.drafts.remember(cog, request, guild.id, _draft_key(actor, kind, ident), _draft_values(data, fields))
            params = {"edit_project": pid or None, "pm_new_project": "1" if not pid else None} if kind == "project" else {"edit_task": tid or None, "new_task": "1" if not tid else None}
            _redirect(guild, str(exc), error=True, pm_draft=kind, tab="projekte" if kind == "project" else "aufgabenboard", **params)
        if form == "task_comment":
            wc.drafts.remember(cog, request, guild.id, _draft_key(actor, "comment", tid), {"text": str(data.get("text") or "")[:4100]})
        fresh = await cog.config.guild(guild).all()
        _redirect(guild, str(exc), error=True, task=tid if tid in (fresh.get("work_tasks") or {}) else None,
                  pm_project=pid if pid in (fresh.get("projects") or {}) else None,
                  pm_draft="comment" if form == "task_comment" else None,
                  tab="einstellungen" if form == "task_board_publish" else "projekte" if form.startswith("project_") else "aufgabenboard")


async def render(cog, request, guild, actor, conf):
    wc, ui = request.app["webcore"], request.app["webcore"].ui
    operating = await wc.can_operate(request, guild)
    managing = operating and cog.can_manage_projects(actor, conf)
    head = ""
    selected = str(request.query.get("task") or "")
    if selected:
        task = (conf.get("work_tasks") or {}).get(selected)
        if task is None:
            raise web.HTTPNotFound(text="Aufgabe nicht gefunden")
        head += _detail(cog, request, ui, guild, actor, conf, dict(task, id=selected), operating)
    if conf.get("task_board_error"):
        retry = ui.form("/cogs/teamcalendar", ui.button("Aufgabenübersicht erneut aktualisieren", small=True, kind="ghost"),
                        csrf=request.get("webcore_csrf", ""), hidden={"guild": guild.id, "form": "task_board_refresh"}, operate=True) if managing and conf.get("task_board_channel") else ""
        head += ui.callout("Discord-Aufgabenübersicht: " + ui.esc(conf["task_board_error"]) + retry, tone="warn")
    tabs = ui.tab("projekte", "Projekte", "bi-folder", _projects(cog, request, ui, guild, actor, conf, managing))
    tabs += ui.tab("aufgabenboard", "Aufgabenboard", "bi-kanban", _board(cog, request, ui, guild, actor, conf, operating))
    tabs += ui.tab("meine-aufgaben", "Meine Aufgaben", "bi-person-check", _mine(ui, guild, actor, conf))
    return head, tabs


def _projects(cog, request, ui, guild, actor, conf, managing):
    projects = sorted((dict(project, id=str(pid)) for pid, project in (conf.get("projects") or {}).items()), key=lambda item: (item.get("status") in {"archived", "completed"}, item.get("name", "").casefold(), item["id"]))
    pid = str(request.query.get("pm_project") or "")
    if pid and pid not in (conf.get("projects") or {}):
        raise web.HTTPNotFound(text="Projekt nicht gefunden")
    body = ""
    if managing:
        body += ui.button("Neues Projekt", href=_url(guild, pm_new_project=1) + "#projekte", icon="bi-folder-plus")
        if request.query.get("edit_project") or request.query.get("pm_new_project"):
            body += _project_editor(cog, request, ui, guild, actor, conf)
    cards = []
    for project in projects:
        progress = project_progress(conf, project["id"])
        content = ui.badge(PROJECT_STATUS.get(project.get("status"), "Unbekannt"))
        content += "<p>" + ui.esc(project.get("description") or "Keine Beschreibung.").replace("\n", "<br>") + "</p>"
        content += "<p>" + ui.esc(f"{progress['done']} von {progress['total']} Aufgaben erledigt · {progress['percent']} % · {progress['blocked']} blockiert") + "</p>"
        content += "<p>Verantwortlich: " + ui.esc(_person(guild, project.get("owner_id"))) + "<br>Frist: " + ui.esc(format_local(project["deadline_ts"], conf["timezone"]) if project.get("deadline_ts") else "Keine") + "</p>"
        content += ui.button("Aufgaben öffnen", href=_url(guild, pm_project=project["id"]) + "#aufgabenboard", small=True, kind="ghost")
        if managing:
            content += ui.button("Projekt bearbeiten", href=_url(guild, edit_project=project["id"]) + "#projekte", small=True, kind="ghost")
            actions = [("activate", "Aktivieren")] if project.get("status") != "active" else [("pause", "Pausieren")]
            if project.get("status") not in {"completed", "archived"}:
                actions += [("complete", "Abschließen"), ("archive", "Archivieren")]
            actions += [("delete", "Leeres Projekt löschen")]
            content += "<div class='wc-row-actions'>" + "".join(ui.form("/cogs/teamcalendar", ui.button(label, small=True, kind="danger" if action == "delete" else "ghost"),
                csrf=request.get("webcore_csrf", ""), hidden={"guild": guild.id, "form": "project_action", "pid": project["id"], "revision": project["revision"], "action": action},
                operate=True, confirm=f"Projekt „{project['name']}“ löschen? Nur ohne zugehörige Aufgaben möglich." if action == "delete" else None) for action, label in actions) + "</div>"
        milestones = [task for task in _sorted_tasks(conf) if task.get("project_id") == project["id"] and task.get("milestone")]
        if milestones:
            content += "<p><b>Meilensteine</b></p>" + "<br>".join(_task_link(ui, guild, task) + " · " + ui.esc(STATUS.get(task.get("status"), "")) for task in milestones)
        cards.append(ui.card(project["name"], content, icon="bi-folder", tone="info" if pid == project["id"] else None))
    return body + (ui.columns(*cards, cols=2) if cards else ui.card(body=ui.empty("bi-folder", "Noch keine Projekte.", "Beginne mit einem Projekt und ergänze danach seine Aufgaben.")))


def _members(cog, guild, conf):
    return [(member.id, f"{member.display_name} (@{member.name})") for member in guild.members if not member.bot and cog.can_view(member, conf)]


def _project_editor(cog, request, ui, guild, actor, conf):
    pid = str(request.query.get("edit_project") or "")
    project = (conf.get("projects") or {}).get(pid)
    if pid and project is None:
        raise web.HTTPNotFound(text="Projekt nicht gefunden")
    values = {**(project or {}), "deadline": input_local((project or {}).get("deadline_ts"), conf["timezone"]), "task_timezone": conf["timezone"]}
    if request.query.get("pm_draft") == "project":
        values.update(request.app["webcore"].drafts.restore(cog, request, guild.id, _draft_key(actor, "project", pid)))
    body = ui.grid(ui.field("Projektname", ui.text_input("name", values.get("name", ""), attrs={"required": True, "maxlength": 80}), wide=True),
                   ui.field("Beschreibung", ui.textarea("description", values.get("description", ""), rows=3), help="Höchstens 2000 Zeichen.", wide=True),
                   ui.field("Verantwortlich", ui.select("owner_id", _members(cog, guild, conf), values.get("owner_id"), none_label="Nicht zugewiesen")),
                   ui.field("Projektfrist", ui.text_input("deadline", values.get("deadline", ""), type="datetime-local"), help="Optional, Ortszeit in " + ui.esc(values.get("task_timezone") or conf["timezone"])))
    return ui.card("Projekt bearbeiten" if pid else "Neues Projekt", _draft_notice(ui, guild, request, conf, values, "project", pid) + ui.form("/cogs/teamcalendar", body + ui.save_row("Projekt speichern"),
                   csrf=request.get("webcore_csrf", ""), hidden={"guild": guild.id, "form": "project_save", "pid": pid, "revision": values.get("revision", ""), "task_timezone": values.get("task_timezone", "")}, savebar=True, operate=True), icon="bi-folder-plus")


def _filters(ui, guild, conf, request):
    items = [(str(pid), project["name"]) for pid, project in (conf.get("projects") or {}).items()]
    fields = ui.grid(ui.field("Projekt", ui.select("pm_project", items, request.query.get("pm_project"), none_label="Alle Projekte")),
        ui.field("Status", ui.select("task_status", list(STATUS.items()), request.query.get("task_status"), none_label="Alle")),
        ui.field("Zuständig", ui.select("assignee", [("self", "Mir zugewiesen"), ("unassigned", "Nicht zugewiesen"), *[(member.id, member.display_name) for member in guild.members if not member.bot]], request.query.get("assignee"), none_label="Alle")),
        ui.field("Priorität", ui.select("task_priority", list(PRIORITY.items()), request.query.get("task_priority"), none_label="Alle")),
        ui.field("Suche", ui.text_input("task_search", request.query.get("task_search", ""), placeholder="Titel oder Beschreibung")),
        ui.field("Frist", ui.select("task_due", [("overdue", "Überfällig")], request.query.get("task_due"), none_label="Alle Fristen")))
    form = ui.form("/cogs/teamcalendar", fields + ui.button("Aufgaben filtern", icon="bi-funnel", kind="ghost"), csrf="", hidden={"guild": guild.id}, method="get")
    active = any(request.query.get(key) for key in ("pm_project", "task_status", "assignee", "task_priority", "task_search", "task_due"))
    return ui.disclosure("Aufgaben filtern", form, expanded=active)


def _filtered(conf, request, actor):
    result = _sorted_tasks(conf)
    q = request.query
    for field, key in (("pm_project", "project_id"), ("task_status", "status"), ("task_priority", "priority")):
        if q.get(field):
            result = [task for task in result if str(task.get(key) or "") == q[field]]
    assignee = q.get("assignee")
    if assignee == "unassigned":
        result = [task for task in result if not task.get("assignee_ids")]
    elif assignee:
        uid = getattr(actor, "id", 0) if assignee == "self" else int(assignee) if assignee.isdigit() else 0
        result = [task for task in result if uid in task.get("assignee_ids", [])]
    if q.get("task_due") == "overdue":
        now = datetime.now(timezone.utc).timestamp()
        result = [task for task in result if task.get("due_ts") and task["due_ts"] < now and task.get("status") != "done"]
    if q.get("task_search"):
        needle = q["task_search"].casefold()
        result = [task for task in result if needle in (task.get("title", "") + " " + task.get("description", "")).casefold()]
    return result


def _board(cog, request, ui, guild, actor, conf, operating):
    body = _filters(ui, guild, conf, request)
    if operating and cog.can_edit_task(actor, conf):
        body += ui.button("Neue Aufgabe", href=_url(guild, new_task=1, pm_project=request.query.get("pm_project")) + "#aufgabenboard", icon="bi-plus-lg")
        if request.query.get("new_task") or request.query.get("edit_task"):
            body += _task_editor(cog, request, ui, guild, actor, conf)
    body += ui.button("Aufgaben als CSV exportieren", href=_url(guild, download="tasks_csv"), icon="bi-download", kind="ghost")
    tasks = _filtered(conf, request, actor)
    columns = []
    for status, label in STATUS.items():
        matching = [task for task in tasks if task.get("status") == status]
        cards = [_task_card(cog, request, ui, guild, actor, conf, task, operating) for task in matching[:100]]
        if len(matching) > 100:
            cards.append(ui.callout(f"100 von {len(matching)} Aufgaben; bitte die Filter eingrenzen."))
        columns.append({"title": label, "count": len(matching), "body": "".join(cards) or ui.empty("bi-check2-square", "Keine Aufgaben.")})
    return ui.card("Aufgabenboard", body + ui.kanban(columns), icon="bi-kanban", desc="Status direkt über die Auswahl ändern. Aufgaben öffnen für Checklisten, Kommentare und Verlauf.")


def _task_card(cog, request, ui, guild, actor, conf, task, operating):
    body = "<div class='wc-cell-title'>" + _task_link(ui, guild, task) + "</div>"
    body += ui.badge(PRIORITY.get(task.get("priority"), "Normal"), "bad" if task.get("priority") == "urgent" else "muted")
    if task.get("milestone"):
        body += ui.badge("Meilenstein", "info")
    body += "<p>" + ui.esc(_project_name(conf, task.get("project_id"))) + "<br>" + ui.esc(", ".join(_person(guild, uid) for uid in task.get("assignee_ids", [])) or "Nicht zugewiesen") + "</p>"
    if task.get("due_ts"):
        late = task["due_ts"] < datetime.now(timezone.utc).timestamp() and task.get("status") != "done"
        body += ui.badge(("Überfällig · " if late else "Frist · ") + format_local(task["due_ts"], conf["timezone"]), "bad" if late else "muted")
    checklist = task.get("checklist") or []
    if checklist:
        body += "<p>" + ui.esc(f"{sum(bool(item.get('done')) for item in checklist)}/{len(checklist)} Checklistenpunkte") + "</p>"
    if operating and cog.can_work_task(actor, conf, task):
        body += ui.form("/cogs/teamcalendar", ui.select("action", list(STATUS.items()), task.get("status")) + ui.button("Status setzen", small=True, kind="ghost"),
            csrf=request.get("webcore_csrf", ""), hidden={"guild": guild.id, "form": "task_action", "tid": task["id"], "revision": task["revision"]}, operate=True)
    return ui.card(body=body)


def _task_editor(cog, request, ui, guild, actor, conf):
    tid = str(request.query.get("edit_task") or "")
    task = (conf.get("work_tasks") or {}).get(tid)
    if tid and task is None:
        raise web.HTTPNotFound(text="Aufgabe nicht gefunden")
    if not cog.can_edit_task(actor, conf, task):
        return ui.callout("Du darfst diese Aufgabe nicht vollständig bearbeiten.", tone="warn")
    values = {**(task or {}), "project_id": (task or {}).get("project_id") or request.query.get("pm_project", ""),
              "due": input_local((task or {}).get("due_ts"), conf["timezone"]), "task_timezone": conf["timezone"],
              "checklist": "\n".join(item.get("text", "") for item in (task or {}).get("checklist", []))}
    if request.query.get("pm_draft") == "task":
        values.update(request.app["webcore"].drafts.restore(cog, request, guild.id, _draft_key(actor, "task", tid)))
    projects = [(str(pid), project["name"]) for pid, project in (conf.get("projects") or {}).items()]
    events = [(str(eid), event["title"]) for eid, event in (conf.get("events") or {}).items()]
    content = ui.grid(ui.field("Titel", ui.text_input("title", values.get("title", ""), attrs={"required": True, "maxlength": 100}), wide=True),
        ui.field("Projekt", ui.select("project_id", projects, values.get("project_id"), none_label="Ohne Projekt")),
        ui.field("Zuständig", ui.select("assignee_ids", _members(cog, guild, conf), values.get("assignee_ids") or [], multiple=True), help="Höchstens zehn Teammitglieder."),
        ui.field("Frist", ui.text_input("due", values.get("due", ""), type="datetime-local"), help="Optional, Ortszeit in " + ui.esc(values.get("task_timezone") or conf["timezone"])),
        ui.field("Priorität", ui.select("priority", list(PRIORITY.items()), values.get("priority", "normal"))),
        ui.field("Beschreibung", ui.textarea("description", values.get("description", ""), rows=4), help="Höchstens 2000 Zeichen.", wide=True),
        ui.field("Meilenstein", ui.switch("milestone", "Als Meilenstein markieren", bool(values.get("milestone")))),
        ui.field("Kalendertermin", ui.select("event_id", events, values.get("event_id"), none_label="Kein Termin verknüpft"), help="Verknüpft einen vorhandenen Termin; erzeugt und verändert keinen Termin."),
        ui.field("Checkliste", ui.textarea("checklist", values.get("checklist", ""), rows=4), help="Ein Punkt pro Zeile, höchstens 25. Vorhandene Häkchen bleiben bei gleichem Text erhalten.", wide=True))
    return ui.card("Aufgabe bearbeiten" if tid else "Neue Aufgabe", _draft_notice(ui, guild, request, conf, values, "task", tid) + ui.form("/cogs/teamcalendar", content + ui.save_row("Aufgabe speichern"),
        csrf=request.get("webcore_csrf", ""), hidden={"guild": guild.id, "form": "task_save", "tid": tid, "revision": values.get("revision", ""), "task_timezone": values.get("task_timezone", "")}, savebar=True, operate=True), icon="bi-check2-square")


def _draft_notice(ui, guild, request, conf, values, kind, ident):
    if request.query.get("pm_draft") != kind:
        return ""
    params = {"edit_project": ident or None, "pm_new_project": "1" if not ident else None} if kind == "project" else {"edit_task": ident or None, "new_task": "1" if not ident else None}
    text = "Deine Eingaben bleiben erhalten. Nach zwischenzeitlichen Änderungen die gespeicherte Fassung erneut prüfen. "
    if values.get("task_timezone") != conf["timezone"]:
        text += "Die Kalender-Zeitzone wurde geändert; bitte neu laden und die Frist prüfen. "
    return ui.callout(text + ui.button("Aktuellen Stand neu laden", href=_url(guild, **params) + ("#projekte" if kind == "project" else "#aufgabenboard"), small=True, kind="ghost"))


def _detail(cog, request, ui, guild, actor, conf, task, operating):
    csrf = request.get("webcore_csrf", "")
    working = operating and cog.can_work_task(actor, conf, task)
    editing = operating and cog.can_edit_task(actor, conf, task)
    body = ui.badge(STATUS.get(task.get("status"), "Unbekannt")) + ui.badge(PRIORITY.get(task.get("priority"), "Normal"))
    if task.get("milestone"):
        body += ui.badge("Meilenstein", "info")
    body += "<p>" + ui.esc(task.get("description") or "Keine Beschreibung.").replace("\n", "<br>") + "</p>"
    body += ui.grid(ui.field("Projekt", ui.esc(_project_name(conf, task.get("project_id")))),
                    ui.field("Frist", ui.esc(format_local(task["due_ts"], conf["timezone"]) if task.get("due_ts") else "Keine")),
                    ui.field("Zuständig", ui.esc(", ".join(_person(guild, uid) for uid in task.get("assignee_ids", [])) or "Nicht zugewiesen")))
    event = (conf.get("events") or {}).get(str(task.get("event_id") or ""))
    if event:
        body += ui.button("Kalendertermin: " + event["title"], href=_url(guild, event=event["id"]) + "#agenda", icon="bi-calendar-event", kind="ghost")
    if editing:
        body += ui.button("Aufgabe bearbeiten", href=_url(guild, edit_task=task["id"]) + "#aufgabenboard", kind="ghost", icon="bi-pencil")
        body += ui.form("/cogs/teamcalendar", ui.button("Aufgabe löschen", kind="danger", small=True), csrf=csrf,
            hidden={"guild": guild.id, "form": "task_action", "tid": task["id"], "revision": task["revision"], "action": "delete"},
            confirm=f"Aufgabe „{task['title']}“ mit Checkliste und Kommentaren endgültig löschen?", operate=True)
        body += ui.form("/cogs/teamcalendar", ui.field("Zuständige ändern", ui.select("assignee_ids", _members(cog, guild, conf), task.get("assignee_ids") or [], multiple=True))
                        + ui.button("Zuweisung speichern", small=True), csrf=csrf,
                        hidden={"guild": guild.id, "form": "task_assign", "tid": task["id"], "revision": task["revision"]}, operate=True)
    checklist = []
    for item in task.get("checklist", []):
        title = ("✓ " if item.get("done") else "○ ") + item["text"]
        control = ui.esc(title)
        if working:
            control = ui.form("/cogs/teamcalendar", ui.button(title, kind="ghost", small=True), csrf=csrf,
                hidden={"guild": guild.id, "form": "task_check", "tid": task["id"], "revision": task["revision"], "item_id": item["id"], "done": "no" if item.get("done") else "yes"}, operate=True)
        checklist.append(control)
    body += ui.card("Checkliste", "".join(checklist) or ui.empty("bi-list-check", "Noch keine Checklistenpunkte."))
    comments = []
    for comment in task.get("comments", []):
        text = "<b>" + ui.esc(_person(guild, comment.get("author_id"))) + "</b> · " + ui.esc(format_local(comment.get("created_at"), conf["timezone"]))
        text += "<p>" + ui.esc(comment.get("text") or "").replace("\n", "<br>") + "</p>"
        if operating and (comment.get("author_id") == getattr(actor, "id", None) or cog.can_configure(actor, conf)):
            text += ui.form("/cogs/teamcalendar", ui.button("Kommentar löschen", kind="danger", small=True), csrf=csrf,
                           hidden={"guild": guild.id, "form": "task_comment_delete", "tid": task["id"], "comment_id": comment["id"]}, confirm="Diesen Kommentar löschen?", operate=True)
        comments.append(ui.card(body=text))
    if working:
        draft = request.app["webcore"].drafts.restore(cog, request, guild.id, _draft_key(actor, "comment", task["id"])) if request.query.get("pm_draft") == "comment" else {}
        comments.append(ui.form("/cogs/teamcalendar", ui.field("Kommentar", ui.textarea("text", draft.get("text", ""), rows=3), help="1–1000 Zeichen; nur nach Absenden gespeichert.") + ui.button("Kommentar hinzufügen", small=True),
                               csrf=csrf, hidden={"guild": guild.id, "form": "task_comment", "tid": task["id"]}, operate=True))
    body += ui.disclosure("Kommentare", "".join(comments) or ui.empty("bi-chat-left", "Noch keine Kommentare."), expanded=True)
    activity = "<br>".join(ui.esc(format_local(item.get("at"), conf["timezone"]) + " · " + _person(guild, item.get("actor_id")) + " · " + str(item.get("text") or item.get("kind") or "Änderung")) for item in reversed(task.get("activity", [])))
    body += ui.disclosure("Änderungsverlauf", activity or "Noch keine Änderungen.")
    return ui.card(task["title"], body, icon="bi-check2-square")


def _mine(ui, guild, actor, conf):
    tasks = [task for task in _sorted_tasks(conf) if getattr(actor, "id", None) in task.get("assignee_ids", []) and task.get("status") != "done"]
    rows = [ui.row(_task_link(ui, guild, task), ui.esc(_project_name(conf, task.get("project_id"))), ui.esc(STATUS.get(task.get("status"))),
                   ui.esc(format_local(task["due_ts"], conf["timezone"]) if task.get("due_ts") else "Keine"), ui.badge(PRIORITY.get(task.get("priority"), "Normal"))) for task in tasks]
    return ui.card("Meine offenen Aufgaben", ui.table(["Aufgabe", "Projekt", "Status", "Frist", "Priorität"], rows, empty_text="Dir sind keine offenen Aufgaben zugewiesen."),
                   icon="bi-person-check", desc="Zeigt nur deine eigenen Zuweisungen, unabhängig vom Projektfilter. Die gemeinsame Übersicht findest du im Aufgabenboard.")


def settings(ui, guild, conf, csrf):
    channels = [(channel.id, "#" + channel.name) for channel in guild.text_channels]
    body = ui.callout("Veröffentliche nur in einem passenden Teamkanal. Alle Kanal-Leser können die dort gezeigten Aufgaben sehen. Ansichten und Speichern von Aufgaben veröffentlichen keine neue Übersicht.")
    body += ui.form("/cogs/teamcalendar", ui.field("Aufgabenkanal", ui.select("channel", channels, conf.get("task_board_channel"), none_label="Kanal auswählen"))
                    + ui.button("Aufgabenübersicht dort veröffentlichen", icon="bi-send"), csrf=csrf,
                    hidden={"guild": guild.id, "form": "task_board_publish"}, confirm="Aufgabenübersicht in diesem Discord-Kanal veröffentlichen?",)
    if conf.get("task_board_channel") and conf.get("task_board_message_id"):
        body += ui.button("In Discord öffnen", href=f"https://discord.com/channels/{guild.id}/{conf['task_board_channel']}/{conf['task_board_message_id']}", kind="ghost")
        body += ui.form("/cogs/teamcalendar", ui.button("Aufgabenübersicht erneut aktualisieren", kind="ghost"), csrf=csrf,
                        hidden={"guild": guild.id, "form": "task_board_refresh"}, operate=True)
    return ui.card("Aufgaben in Discord", body, icon="bi-kanban")
