"""Private Projekt-/Aufgabenbedienung über dauerhaft auswertbare Discord-IDs."""
from __future__ import annotations

from datetime import datetime

import discord

from .models import CalendarError, format_local, get_timezone
from .project_models import label_project, project_progress
from .views import _context, _name, _now, _say

PREFIX = "teamcalendar:pm:"
PAGE_SIZE = 25
STATUSES = {"todo": "Offen", "in_progress": "In Arbeit", "blocked": "Blockiert", "done": "Erledigt"}
PRIORITIES = {"low": "Niedrig", "normal": "Normal", "high": "Hoch", "urgent": "Dringend"}
PROJECT_STATUSES = {"active": "Aktiv", "paused": "Pausiert", "completed": "Abgeschlossen", "archived": "Archiviert"}


def _revision(record):
    return int(record.get("revision", 1))


def _record(conf, kind, ident, revision=None):
    record = (conf.get("work_tasks" if kind == "task" else "projects") or {}).get(str(ident))
    label = "Aufgabe" if kind == "task" else "Projekt"
    if not isinstance(record, dict):
        raise CalendarError(f"{label} nicht gefunden. Bitte die Liste neu öffnen.")
    if revision is not None and str(_revision(record)) != str(revision):
        raise CalendarError(f"{label} wurde inzwischen geändert. Bitte neu öffnen und erneut prüfen.")
    return record


def _project_label(conf, record):
    pid = str(record.get("project_id") or "")
    if not pid:
        return "Ohne Projekt"
    return label_project(conf, record) + f" · #{pid}"


def _names(guild, ids, maximum=10):
    ids = list(ids or [])
    names = [_name(guild, uid) for uid in ids[:maximum]]
    if len(ids) > maximum:
        names.append(f"… und {len(ids) - maximum} weitere")
    return ", ".join(names)[:1024] or "Noch niemand zugewiesen"


def _due(value, conf):
    if value is None:
        return "Keine Frist"
    return f"{format_local(value, conf.get('timezone'))} ({conf.get('timezone') or 'Europe/Berlin'})\n<t:{int(value)}:R>"


def task_embed(guild, task, conf):
    embed = discord.Embed(title=("🏁 " if task.get("milestone") else "") + str(task.get("title") or "Aufgabe")[:100],
                          description=str(task.get("description") or "Keine Notizen.")[:2000],
                          color=0x3DDC97 if task.get("status") == "done" else 0x6CB6FF)
    embed.add_field(name="Status", value=STATUSES.get(task.get("status"), "Offen"), inline=True)
    embed.add_field(name="Priorität", value=PRIORITIES.get(task.get("priority"), "Normal"), inline=True)
    embed.add_field(name="Projekt", value=_project_label(conf, task)[:200], inline=True)
    embed.add_field(name="Zuständig", value=_names(guild, task.get("assignee_ids")), inline=False)
    embed.add_field(name="Fällig", value=_due(task.get("due_ts"), conf)[:1024], inline=False)
    checklist = task.get("checklist") or []
    done = sum(bool(item.get("done")) for item in checklist)
    if checklist:
        lines = []
        for item in checklist[:10]:
            line = ("☑ " if item.get("done") else "☐ ") + str(item.get("text") or "Punkt")[:80]
            if len("\n".join([*lines, line])) > 920:
                break
            lines.append(line)
        if len(checklist) > len(lines):
            lines.append(f"… und {len(checklist) - len(lines)} weitere Punkte")
        embed.add_field(name=f"Checkliste · {done}/{len(checklist)} erledigt", value="\n".join(lines)[:1024], inline=False)
    if task.get("event_id"):
        event = (conf.get("events") or {}).get(str(task["event_id"]))
        embed.add_field(name="Verknüpfter Termin", value=(str(event.get("title") or "Termin") + f" · #{task['event_id']}")[:200]
                        if event else "Termin nicht mehr verfügbar", inline=False)
    comments = task.get("comments") or []
    if comments:
        lines = [f"{_name(guild, comment.get('author_id'))}: {str(comment.get('text') or '')[:180]}" for comment in comments[-2:]]
        embed.add_field(name=f"Letzte Kommentare · insgesamt {len(comments)}", value="\n\n".join(lines)[:1024], inline=False)
    embed.set_footer(text=f"Aufgabe #{task.get('id', '?')} · Version {_revision(task)} · Änderungen gelten für das Team"[:2048])
    return embed


def project_embed(guild, project, conf):
    pid = str(project["id"])
    progress = project_progress(conf, pid)
    embed = discord.Embed(title=str(project.get("name") or "Projekt")[:100],
                          description=str(project.get("description") or "Keine Beschreibung.")[:2000], color=0xB28DFF)
    embed.add_field(name="Status", value=PROJECT_STATUSES.get(project.get("status"), "Aktiv"), inline=True)
    embed.add_field(name="Verantwortlich", value=_name(guild, project.get("owner_id")), inline=True)
    embed.add_field(name="Frist", value=_due(project.get("deadline_ts"), conf)[:1024], inline=False)
    embed.add_field(name="Fortschritt", value=f"{progress['done']} von {progress['total']} Aufgaben erledigt · {progress['percent']} %", inline=False)
    milestones = progress["milestones"]
    if milestones:
        lines = [f"{'☑' if task.get('status') == 'done' else '☐'} {str(task.get('title') or 'Meilenstein')[:75]} · #{task['id']}"
                 for task in milestones[:10]]
        if len(milestones) > 10:
            lines.append(f"… und {len(milestones) - 10} weitere")
        embed.add_field(name="Meilensteine", value="\n".join(lines)[:1024], inline=False)
    embed.set_footer(text=f"Projekt #{pid} · Version {_revision(project)}")
    return embed


def _button(view, label, action, *parts, row=0, style=discord.ButtonStyle.secondary, disabled=False):
    view.add_item(discord.ui.Button(label=label, style=style, row=row, disabled=disabled,
                  custom_id=PREFIX + action + (":" + ":".join(str(part) for part in parts) if parts else "")))


def build_task_board_view():
    view = discord.ui.View(timeout=None)
    _button(view, "Aufgabenliste", "tasks")
    _button(view, "Aufgabe erstellen", "newtask", style=discord.ButtonStyle.primary)
    _button(view, "Projekte ansehen", "projects")
    return view


def build_task_view(task, requester_id, can_edit=False, can_work=False):
    view = discord.ui.View(timeout=None)
    tid, revision = str(task["id"]), _revision(task)
    if can_work:
        options = [discord.SelectOption(label=label, value=status, default=task.get("status", "todo") == status)
                   for status, label in STATUSES.items()]
        view.add_item(discord.ui.Select(custom_id=f"{PREFIX}status:{requester_id}:{tid}:{revision}",
                      options=options, placeholder="Status ändern …", row=0))
    if can_edit:
        _button(view, "Bearbeiten", "edittask", requester_id, tid, revision, row=1, style=discord.ButtonStyle.primary)
        _button(view, "Zuweisen", "assign", requester_id, tid, revision, row=1)
        _button(view, "Priorität", "priorities", requester_id, tid, revision, row=1)
    if can_work:
        _button(view, "Checkliste", "checklist", requester_id, tid, revision, 0, row=1)
        _button(view, "Kommentar schreiben", "comment", requester_id, tid, revision, row=1)
    _button(view, "Kommentare ansehen", "comments", requester_id, tid, 0, row=2)
    if can_edit:
        _button(view, "Löschen", "deletetask", requester_id, tid, revision, row=2, style=discord.ButtonStyle.danger)
    _button(view, "Aufgabenliste", "tasks", requester_id, "all", 0, row=2)
    _button(view, "Projekte", "projects", requester_id, 0, row=2)
    return view


def _project_view(project, uid, managing):
    view = discord.ui.View(timeout=None)
    pid, revision = str(project["id"]), _revision(project)
    if managing:
        _button(view, "Bearbeiten", "editproject", uid, pid, revision, style=discord.ButtonStyle.primary)
        actions = [("pause", "Pausieren")] if project.get("status") == "active" else [("activate", "Aktivieren")]
        if project.get("status") != "completed":
            actions.append(("complete", "Abschließen"))
        if project.get("status") != "archived":
            actions.append(("archive", "Archivieren"))
        for action, label in actions:
            _button(view, label, "projectaction", uid, pid, revision, action)
        _button(view, "Löschen", "deleteproject", uid, pid, revision, style=discord.ButtonStyle.danger)
    _button(view, "Projektaufgaben", "projecttasks", uid, pid, 0, row=1)
    _button(view, "Projektliste", "projects", uid, 0, row=1)
    return view


async def _task_details(cog, interaction, guild, actor, conf, task):
    await _say(interaction, embed=task_embed(guild, task, conf), view=build_task_view(task, actor.id,
               can_edit=cog.can_edit_task(actor, conf, task), can_work=cog.can_work_task(actor, conf, task)))


async def show_task(cog, interaction, task_id):
    try:
        guild, actor, conf = await _context(cog, interaction)
        await _task_details(cog, interaction, guild, actor, conf, _record(conf, "task", task_id))
    except CalendarError as exc:
        await _say(interaction, str(exc))


def _sort_tasks(tasks):
    ranks = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    return sorted(tasks, key=lambda task: (task.get("status") == "done", task.get("due_ts") or 10**12,
                                          ranks.get(task.get("priority"), 2), str(task["id"])))


def _page_view(records, uid, page, action, *, extra=()):
    pages = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(int(page), pages - 1))
    view = discord.ui.View(timeout=None)
    if pages > 1:
        _button(view, "Zurück", action, uid, *extra, page - 1, row=1, disabled=page == 0)
        _button(view, "Weiter", action, uid, *extra, page + 1, row=1, disabled=page == pages - 1)
    return view, records[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], page, pages


async def _show_tasks(cog, interaction, guild, actor, conf, mode="all", page=0, project_id=None):
    tasks = list((conf.get("work_tasks") or {}).values())
    if project_id is not None:
        _record(conf, "project", project_id)
        tasks = [task for task in tasks if str(task.get("project_id") or "") == str(project_id)]
    elif mode == "mine":
        tasks = [task for task in tasks if actor.id in task.get("assignee_ids", [])]
    records = _sort_tasks(tasks)
    action, extra = ("projecttasks", (project_id,)) if project_id is not None else ("tasks", (mode,))
    view, shown, page, pages = _page_view(records, actor.id, page, action, extra=extra)
    options = [discord.SelectOption(label=f"#{task['id']} · {task.get('title') or 'Aufgabe'}"[:100], value=str(task["id"]),
        description=f"{STATUSES.get(task.get('status'), 'Offen')} · {PRIORITIES.get(task.get('priority'), 'Normal')} · {_project_label(conf, task)}"[:100]) for task in shown]
    if options:
        view.add_item(discord.ui.Select(custom_id=f"{PREFIX}taskselect:{actor.id}", options=options, placeholder="Aufgabe auswählen …", row=0))
    if cog.can_edit_task(actor, conf):
        _button(view, "Aufgabe erstellen", "newtask", row=2, style=discord.ButtonStyle.primary)
    _button(view, "Meine Aufgaben", "mytasks", actor.id, row=2)
    _button(view, "Alle Aufgaben", "alltasks", actor.id, row=2)
    _button(view, "Projekte", "projects", actor.id, 0, row=2)
    heading = "Projektaufgaben" if project_id is not None else "Meine Aufgaben" if mode == "mine" else "Alle Aufgaben"
    text = f"**{heading} · Seite {page + 1}/{pages}**\n{len(records)} Aufgaben. Erledigte stehen am Ende." if records else f"**{heading}**\nNoch keine Aufgaben in dieser Auswahl."
    await _say(interaction, text, view=view)


async def show_projects(cog, interaction, page=0):
    try:
        guild, actor, conf = await _context(cog, interaction)
        projects = sorted((conf.get("projects") or {}).values(), key=lambda project: (project.get("status") == "archived", str(project.get("name") or "").casefold(), str(project["id"])))
        view, shown, page, pages = _page_view(projects, actor.id, page, "projects")
        if shown:
            options = [discord.SelectOption(label=f"#{project['id']} · {project.get('name') or 'Projekt'}"[:100], value=str(project["id"]),
                       description=PROJECT_STATUSES.get(project.get("status"), "Aktiv")) for project in shown]
            view.add_item(discord.ui.Select(custom_id=f"{PREFIX}projectselect:{actor.id}", options=options,
                          placeholder="Projekt auswählen …", row=0))
        if cog.can_manage_projects(actor, conf):
            _button(view, "Projekt erstellen", "newproject", row=2, style=discord.ButtonStyle.primary)
        _button(view, "Aufgabenliste", "tasks", actor.id, "all", 0, row=2)
        await _say(interaction, f"**Projekte · Seite {page + 1}/{pages}**\n{len(projects)} Projekte. Die Nummer steht bei jedem Projektnamen.", view=view)
    except CalendarError as exc:
        await _say(interaction, str(exc))


def _input_date(stamp, conf):
    return datetime.fromtimestamp(int(stamp), get_timezone(conf.get("timezone"))).isoformat(timespec="minutes") if stamp is not None else ""


class TaskModal(discord.ui.Modal):
    def __init__(self, cog, guild, actor, conf, task=None):
        super().__init__(title="Aufgabe bearbeiten" if task else "Aufgabe erstellen", timeout=300)
        self.cog, self.guild_id, self.requester_id = cog, guild.id, actor.id
        self.task_id, self.revision = (str(task["id"]), _revision(task)) if task else (None, None)
        self.submitted = False
        self.timezone = conf.get("timezone") or "Europe/Berlin"
        self.initial_checklist = "\n".join(("[x] " if item.get("done") else "[ ] ") + str(item.get("text") or "") for item in (task or {}).get("checklist", []))
        self.large_checklist = len(self.initial_checklist) > 4000
        self.initial_checklist_input = self.initial_checklist[:4000]
        self.title_field = discord.ui.TextInput(label="Titel", max_length=100, default=str((task or {}).get("title") or "")[:100])
        self.description_field = discord.ui.TextInput(label="Notizen (optional)", style=discord.TextStyle.paragraph, required=False,
            max_length=2000, default=str((task or {}).get("description") or "")[:2000])
        self.due_field = discord.ui.TextInput(label=f"Fällig ({conf.get('timezone') or 'Europe/Berlin'})"[:45], required=False,
            max_length=64, default=_input_date((task or {}).get("due_ts"), conf), placeholder="TT.MM.JJJJ HH:MM oder JJJJ-MM-TT · leer = keine Frist")
        self.project_field = discord.ui.TextInput(label="Projekt-ID (optional)", required=False, max_length=32,
            default=str((task or {}).get("project_id") or ""), placeholder="Nummer aus „Projekte ansehen“ · leer = ohne Projekt")
        self.checklist_field = discord.ui.TextInput(label="Lange Checkliste: im Dashboard bearbeiten" if self.large_checklist else "Checkliste (ein Punkt je Zeile)", style=discord.TextStyle.paragraph,
            required=False, max_length=4000, default=self.initial_checklist_input, placeholder="[ ] Offener Punkt\n[x] Erledigter Punkt")
        for field in (self.title_field, self.description_field, self.due_field, self.project_field, self.checklist_field):
            self.add_item(field)

    async def on_submit(self, interaction):
        try:
            if interaction.user.id != self.requester_id or getattr(interaction.guild, "id", None) != self.guild_id:
                raise CalendarError("Dieses Formular gehört zu einer anderen Person oder einem anderen Server.")
            if self.submitted:
                raise CalendarError("Dieses Formular wurde bereits abgesendet. Bitte die Aufgabe neu öffnen.")
            self.submitted = True
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild, actor, conf = await _context(self.cog, interaction)
            task = _record(conf, "task", self.task_id, self.revision) if self.task_id else None
            if not self.cog.can_edit_task(actor, conf, task):
                raise CalendarError("Du darfst diese Aufgabe nicht vollständig bearbeiten.")
            data = {"title": self.title_field.value, "description": self.description_field.value,
                    "due": self.due_field.value, "project_id": self.project_field.value, "task_timezone": self.timezone}
            if self.large_checklist and self.checklist_field.value != self.initial_checklist_input:
                raise CalendarError("Diese Checkliste ist für das Kurzformular zu lang. Bitte im Dashboard bearbeiten oder einzelne Punkte über „Checkliste“ abhaken.")
            if task is None or self.checklist_field.value != self.initial_checklist_input:
                data["checklist"] = self.checklist_field.value
            task = await self.cog.update_task(guild, actor, self.task_id, data, revision=self.revision) if self.task_id else await self.cog.create_task(guild, actor, data)
            current = await self.cog.config.guild(guild).all()
            await _task_details(self.cog, interaction, guild, actor, current, task)
        except CalendarError as exc:
            await _say(interaction, str(exc))


class ProjectModal(discord.ui.Modal):
    def __init__(self, cog, guild, actor, conf, project=None):
        super().__init__(title="Projekt bearbeiten" if project else "Projekt erstellen", timeout=300)
        self.cog, self.guild_id, self.requester_id = cog, guild.id, actor.id
        self.project_id, self.revision = (str(project["id"]), _revision(project)) if project else (None, None)
        self.submitted = False
        self.timezone = conf.get("timezone") or "Europe/Berlin"
        self.name_field = discord.ui.TextInput(label="Projektname", max_length=80, default=str((project or {}).get("name") or "")[:80])
        self.description_field = discord.ui.TextInput(label="Beschreibung (optional)", style=discord.TextStyle.paragraph, required=False,
            max_length=2000, default=str((project or {}).get("description") or "")[:2000])
        self.deadline_field = discord.ui.TextInput(label=f"Frist ({conf.get('timezone') or 'Europe/Berlin'})"[:45], required=False, max_length=64,
            default=_input_date((project or {}).get("deadline_ts"), conf), placeholder="TT.MM.JJJJ HH:MM oder JJJJ-MM-TT · leer = keine Frist")
        for field in (self.name_field, self.description_field, self.deadline_field):
            self.add_item(field)

    async def on_submit(self, interaction):
        try:
            if interaction.user.id != self.requester_id or getattr(interaction.guild, "id", None) != self.guild_id:
                raise CalendarError("Dieses Formular gehört zu einer anderen Person oder einem anderen Server.")
            if self.submitted:
                raise CalendarError("Dieses Formular wurde bereits abgesendet. Bitte das Projekt neu öffnen.")
            self.submitted = True
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild, actor, conf = await _context(self.cog, interaction)
            if not self.cog.can_manage_projects(actor, conf):
                raise CalendarError("Du darfst Projekte nicht verwalten.")
            if self.project_id:
                _record(conf, "project", self.project_id, self.revision)
            data = {"name": self.name_field.value, "description": self.description_field.value, "deadline": self.deadline_field.value,
                    "task_timezone": self.timezone}
            project = await self.cog.update_project(guild, actor, self.project_id, data, revision=self.revision) if self.project_id else await self.cog.create_project(guild, actor, data)
            current = await self.cog.config.guild(guild).all()
            await _say(interaction, embed=project_embed(guild, project, current), view=_project_view(project, actor.id, True))
        except CalendarError as exc:
            await _say(interaction, str(exc))


class CommentModal(discord.ui.Modal):
    def __init__(self, cog, guild, actor, task):
        super().__init__(title="Aufgabe kommentieren", timeout=300)
        self.cog, self.guild_id, self.requester_id, self.task_id = cog, guild.id, actor.id, str(task["id"])
        self.submitted = False
        self.text = discord.ui.TextInput(label="Kommentar", style=discord.TextStyle.paragraph, max_length=1000)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        try:
            if interaction.user.id != self.requester_id or getattr(interaction.guild, "id", None) != self.guild_id:
                raise CalendarError("Dieses Formular gehört zu einer anderen Person oder einem anderen Server.")
            if self.submitted:
                raise CalendarError("Dieser Kommentar wurde bereits abgesendet.")
            self.submitted = True
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild, actor, conf = await _context(self.cog, interaction)
            task = _record(conf, "task", self.task_id)
            if not self.cog.can_work_task(actor, conf, task):
                raise CalendarError("Du darfst diese Aufgabe nicht bearbeiten.")
            await self.cog.add_task_comment(guild, actor, self.task_id, self.text.value)
            current = await self.cog.config.guild(guild).all()
            await _task_details(self.cog, interaction, guild, actor, current, _record(current, "task", self.task_id))
        except CalendarError as exc:
            await _say(interaction, str(exc))


async def _comments(cog, interaction, guild, actor, conf, task, page):
    comments = list(reversed(task.get("comments") or []))
    pages = max(1, (len(comments) + 2) // 3)
    page = max(0, min(page, pages - 1))
    view = discord.ui.View(timeout=None)
    embed = discord.Embed(title=f"Kommentare · Aufgabe #{task['id']}"[:256], color=0x6CB6FF)
    for index, comment in enumerate(comments[page * 3:(page + 1) * 3]):
        embed.add_field(name=f"{_name(guild, comment.get('author_id'))} · {format_local(comment.get('created_at'), conf.get('timezone'))}"[:256],
                        value=str(comment.get("text") or "—")[:1000], inline=False)
        if comment.get("author_id") == actor.id or cog._lead(actor, conf):
            _button(view, f"Kommentar {index + 1} löschen", "deletecomment", actor.id, task["id"], comment["id"], row=1, style=discord.ButtonStyle.danger)
    if not comments:
        embed.description = "Noch keine Kommentare."
    embed.set_footer(text=f"Seite {page + 1}/{pages}")
    if pages > 1:
        _button(view, "Zurück", "comments", actor.id, task["id"], page - 1, row=2, disabled=page == 0)
        _button(view, "Weiter", "comments", actor.id, task["id"], page + 1, row=2, disabled=page == pages - 1)
    _button(view, "Zur Aufgabe", "task", actor.id, task["id"], row=2)
    await _say(interaction, embed=embed, view=view)


async def handle_interaction(cog, interaction):
    """Bekannte PM-IDs; auch nach einem Neustart entscheidet nur aktueller Kernzustand."""
    if getattr(interaction, "type", None) != discord.InteractionType.component:
        return
    cid = str((interaction.data or {}).get("custom_id") or "")
    if not cid.startswith(PREFIX):
        return
    parts = cid[len(PREFIX):].split(":")
    action = parts[0]
    lengths = {"newtask": (1,), "tasks": (1, 4), "alltasks": (2,), "mytasks": (2,), "taskselect": (2,), "task": (3,), "edittask": (4,),
        "status": (4,), "assign": (4,), "assignees": (4,), "priorities": (4,), "priority": (4,),
        "checklist": (5,), "checktoggle": (4,), "comment": (4,), "comments": (4,), "deletecomment": (4,),
        "confirmcomment": (5,), "deletetask": (4,), "deleteproject": (4,), "confirm": (6,),
        "projects": (1, 3), "newproject": (1,), "projectselect": (2,), "project": (3,),
        "editproject": (4,), "projectaction": (5,), "projecttasks": (4,)}
    if action not in lengths or len(parts) not in lengths[action]:
        return
    try:
        if len(parts) > 1 and (not parts[1].isdigit() or int(parts[1]) != interaction.user.id):
            raise CalendarError("Diese Auswahl gehört zu einer anderen Person. Bitte die Liste neu öffnen.")
        guild, actor, conf = await _context(cog, interaction)
        if action == "newtask":
            if not cog.can_edit_task(actor, conf):
                raise CalendarError("Du darfst keine Aufgaben erstellen.")
            return await interaction.response.send_modal(TaskModal(cog, guild, actor, conf))
        if action == "newproject":
            if not cog.can_manage_projects(actor, conf):
                raise CalendarError("Du darfst Projekte nicht verwalten.")
            return await interaction.response.send_modal(ProjectModal(cog, guild, actor, conf))
        if action in {"alltasks", "mytasks"}:
            return await _show_tasks(cog, interaction, guild, actor, conf, "mine" if action == "mytasks" else "all", 0)
        if action in {"tasks", "projecttasks"}:
            if action == "tasks":
                mode, page = (parts[2], int(parts[3])) if len(parts) > 1 else ("all", 0)
                if mode not in {"all", "mine"}:
                    raise CalendarError("Bitte eine gültige Aufgabenliste auswählen.")
                return await _show_tasks(cog, interaction, guild, actor, conf, mode, page)
            return await _show_tasks(cog, interaction, guild, actor, conf, page=int(parts[3]), project_id=parts[2])
        if action == "projects":
            return await show_projects(cog, interaction, int(parts[2]) if len(parts) > 1 else 0)
        if action in {"taskselect", "projectselect"}:
            values = (interaction.data or {}).get("values") or []
            if len(values) != 1:
                raise CalendarError("Bitte genau einen Eintrag auswählen.")
            record = _record(conf, "task" if action == "taskselect" else "project", values[0])
            if action == "taskselect":
                return await _task_details(cog, interaction, guild, actor, conf, record)
            return await _say(interaction, embed=project_embed(guild, record, conf), view=_project_view(record, actor.id, cog.can_manage_projects(actor, conf)))
        if action in {"project", "editproject", "projectaction", "deleteproject"}:
            project = _record(conf, "project", parts[2], parts[3] if len(parts) > 3 else None)
            if action == "project":
                return await _say(interaction, embed=project_embed(guild, project, conf), view=_project_view(project, actor.id, cog.can_manage_projects(actor, conf)))
            if not cog.can_manage_projects(actor, conf):
                raise CalendarError("Du darfst Projekte nicht verwalten.")
            if action == "editproject":
                return await interaction.response.send_modal(ProjectModal(cog, guild, actor, conf, project))
            if action == "projectaction":
                if parts[4] not in {"pause", "activate", "complete", "archive"}:
                    raise CalendarError("Bitte eine gültige Projektaktion auswählen. Löschen braucht eine ausdrückliche Bestätigung.")
                await interaction.response.defer(ephemeral=True, thinking=True)
                result = await cog.project_action(guild, actor, project["id"], parts[4], revision=_revision(project))
                current = await cog.config.guild(guild).all()
                return await _say(interaction, embed=project_embed(guild, result, current), view=_project_view(result, actor.id, cog.can_manage_projects(actor, current)))
        if action in {"deletetask", "deleteproject"}:
            kind = "task" if action == "deletetask" else "project"
            record = _record(conf, kind, parts[2], parts[3])
            allowed = cog.can_edit_task(actor, conf, record) if kind == "task" else cog.can_manage_projects(actor, conf)
            if not allowed:
                raise CalendarError("Du darfst diesen Eintrag nicht löschen.")
            view = discord.ui.View(timeout=None)
            _button(view, "Endgültig löschen", "confirm", actor.id, kind, record["id"], _revision(record), _now(cog) + 120,
                    style=discord.ButtonStyle.danger)
            _button(view, "Abbrechen", "task" if kind == "task" else "project", actor.id, record["id"])
            title = str(record.get("title") or record.get("name") or "Eintrag")[:100]
            return await _say(interaction, f"**{discord.utils.escape_markdown(title)}** endgültig löschen? Die Bestätigung gilt zwei Minuten.", view=view)
        if action == "confirm":
            kind, ident, revision, expires = parts[2], parts[3], parts[4], int(parts[5])
            if kind not in {"task", "project"} or expires <= _now(cog):
                raise CalendarError("Die Bestätigung ist abgelaufen. Bitte den Eintrag neu öffnen.")
            record = _record(conf, kind, ident, revision)
            allowed = cog.can_edit_task(actor, conf, record) if kind == "task" else cog.can_manage_projects(actor, conf)
            if not allowed:
                raise CalendarError("Du darfst diesen Eintrag nicht löschen.")
            await interaction.response.defer(ephemeral=True, thinking=True)
            method = cog.task_action if kind == "task" else cog.project_action
            await method(guild, actor, ident, "delete", revision=int(revision))
            return await _say(interaction, "Eintrag gelöscht.", view=build_task_board_view())
        task = _record(conf, "task", parts[2], parts[3] if action not in {"task", "comments", "deletecomment", "confirmcomment"} else None)
        editing, working = cog.can_edit_task(actor, conf, task), cog.can_work_task(actor, conf, task)
        if action == "task":
            return await _task_details(cog, interaction, guild, actor, conf, task)
        if action == "comments":
            return await _comments(cog, interaction, guild, actor, conf, task, int(parts[3]))
        if action in {"deletecomment", "confirmcomment"}:
            comment = next((item for item in task.get("comments", []) if str(item["id"]) == parts[3]), None)
            if not comment or comment.get("author_id") != actor.id and not cog._lead(actor, conf):
                raise CalendarError("Du darfst diesen Kommentar nicht löschen.")
            if action == "deletecomment":
                view = discord.ui.View(timeout=None)
                _button(view, "Kommentar endgültig löschen", "confirmcomment", actor.id, task["id"], comment["id"], _now(cog) + 120, style=discord.ButtonStyle.danger)
                _button(view, "Abbrechen", "task", actor.id, task["id"])
                return await _say(interaction, "Diesen Kommentar endgültig löschen?", view=view)
            if int(parts[4]) <= _now(cog):
                raise CalendarError("Die Bestätigung ist abgelaufen. Bitte die Kommentare neu öffnen.")
            await interaction.response.defer(ephemeral=True, thinking=True)
            await cog.delete_task_comment(guild, actor, task["id"], comment["id"])
            current = await cog.config.guild(guild).all()
            return await _task_details(cog, interaction, guild, actor, current, _record(current, "task", task["id"]))
        if action in {"edittask", "assign", "assignees", "priorities", "priority"} and not editing:
            raise CalendarError("Du darfst diese Aufgabe nicht vollständig bearbeiten oder zuweisen.")
        if action in {"status", "checklist", "checktoggle", "comment"} and not working:
            raise CalendarError("Du darfst diese Aufgabe nicht bearbeiten.")
        if action == "edittask":
            return await interaction.response.send_modal(TaskModal(cog, guild, actor, conf, task))
        if action == "comment":
            return await interaction.response.send_modal(CommentModal(cog, guild, actor, task))
        if action == "assign":
            view = discord.ui.View(timeout=None)
            defaults = [discord.SelectDefaultValue(id=int(uid), type=discord.SelectDefaultValueType.user)
                        for uid in task.get("assignee_ids") or []]
            view.add_item(discord.ui.UserSelect(custom_id=f"{PREFIX}assignees:{actor.id}:{task['id']}:{_revision(task)}",
                          min_values=0, max_values=10, default_values=defaults, placeholder="Bis zu zehn Teammitglieder auswählen …"))
            return await _say(interaction, "Wähle die Zuständigen. Eine leere Auswahl hebt die Zuweisung auf.", view=view)
        if action == "priorities":
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Select(custom_id=f"{PREFIX}priority:{actor.id}:{task['id']}:{_revision(task)}",
                options=[discord.SelectOption(label=label, value=value, default=task.get("priority", "normal") == value) for value, label in PRIORITIES.items()]))
            return await _say(interaction, "Priorität auswählen.", view=view)
        if action == "checklist":
            items = task.get("checklist") or []
            view, shown, page, pages = _page_view(items, actor.id, int(parts[4]), "checklist", extra=(task["id"], _revision(task)))
            if shown:
                view.add_item(discord.ui.Select(custom_id=f"{PREFIX}checktoggle:{actor.id}:{task['id']}:{_revision(task)}", row=0,
                    options=[discord.SelectOption(label=(("☑ " if item.get("done") else "☐ ") + str(item.get("text") or "Punkt"))[:100], value=str(item["id"])) for item in shown],
                    placeholder="Punkt abhaken oder wieder öffnen …"))
            _button(view, "Zur Aufgabe", "task", actor.id, task["id"], row=2)
            return await _say(interaction, f"Checkliste · Seite {page + 1}/{pages}. " + ("Wähle den zu ändernden Punkt." if items else "Noch keine Punkte; füge sie über Bearbeiten hinzu."), view=view)
        values = (interaction.data or {}).get("values") or []
        if action != "assignees" and len(values) != 1:
            raise CalendarError("Bitte genau einen Wert auswählen.")
        if action == "status" and values[0] not in STATUSES:
            raise CalendarError("Bitte einen gültigen Aufgabenstatus auswählen. Löschen braucht eine ausdrückliche Bestätigung.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        if action == "assignees":
            if len(values) > 10 or any(not str(value).isdigit() for value in values):
                raise CalendarError("Bitte höchstens zehn gültige Teammitglieder auswählen.")
            await cog.assign_task(guild, actor, task["id"], [int(value) for value in values], revision=_revision(task))
        elif action == "status":
            await cog.task_action(guild, actor, task["id"], values[0], revision=_revision(task))
        elif action == "priority":
            await cog.update_task(guild, actor, task["id"], {"priority": values[0]}, revision=_revision(task))
        elif action == "checktoggle":
            item = next((item for item in task.get("checklist", []) if str(item["id"]) == str(values[0])), None)
            if item is None:
                raise CalendarError("Dieser Checklistenpunkt existiert nicht mehr.")
            await cog.toggle_checklist(guild, actor, task["id"], item["id"], not item.get("done", False), revision=_revision(task))
        current = await cog.config.guild(guild).all()
        await _task_details(cog, interaction, guild, actor, current, _record(current, "task", task["id"]))
    except (ValueError, TypeError) as exc:
        await _say(interaction, str(exc) if isinstance(exc, CalendarError) else "Diese Auswahl ist ungültig. Bitte die Liste neu öffnen.")
