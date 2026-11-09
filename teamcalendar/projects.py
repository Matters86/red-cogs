"""Gemeinsame Projekt- und Aufgabenlogik für Discord und WebCore."""
from __future__ import annotations

import asyncio
import copy
import logging

import discord

from .models import CalendarError
from .project_models import MAX_PROJECTS, MAX_TASKS, MAX_COMMENTS, normalize_project, normalize_task

log = logging.getLogger("red.red-cogs.teamcalendar.projects")


def register_project_config(cog):
    cog.config.register_guild(projects={}, project_counter=0, work_tasks={}, task_counter=0,
        task_edit_mode="team", task_board_channel=None, task_board_message_id=None,
        task_board_error=None, task_reminder_minutes=[1440, 60, 0])


def prepare_event_project(conf, values):
    """Strukturierte Verknüpfung prüfen; ältere freie Projekttexte erhalten."""
    ident = str(values.get("project_id") or "")
    if ident and ident not in (conf.get("projects") or {}):
        raise CalendarError("Das verknüpfte Projekt existiert auf diesem Server nicht mehr.")
    if "project_id" in values:
        values["project_id"] = ident
    return values


class ProjectMixin:
    def can_edit_task(self, member, conf, task=None):
        return self._lead(member, conf) or (conf.get("task_edit_mode", "team") == "team" and self.can_view(member, conf))

    def can_manage_projects(self, member, conf):
        return self.can_edit_task(member, conf)

    def can_work_task(self, member, conf, task):
        return self.can_edit_task(member, conf, task) or (conf.get("task_edit_mode", "team") == "assigned"
            and self.can_view(member, conf) and getattr(member, "id", None) in (task.get("assignee_ids") or []))

    async def _project_actor(self, guild, actor, conf, *, task=None, work=False, projects=False):
        actor = await self._authorize(guild, actor, conf, view=True)
        predicate = self.can_manage_projects(actor, conf) if projects else (
            self.can_work_task(actor, conf, task) if work and task is not None else self.can_edit_task(actor, conf, task))
        if not predicate:
            raise CalendarError("Für diese Änderung fehlen dir die Projekt- oder Aufgabenrechte.")
        return actor

    @staticmethod
    def _record(conf, container, ident, revision=None):
        record = (conf.get(container) or {}).get(str(ident))
        if not isinstance(record, dict):
            raise CalendarError("Dieses Projekt oder diese Aufgabe existiert nicht mehr.")
        if revision is not None:
            try:
                valid = int(revision) == record.get("revision", 1)
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise CalendarError("Der Eintrag wurde inzwischen geändert. Bitte neu laden und erneut prüfen.")
        return record

    def _activity(self, task, actor, kind, text):
        activity = task.setdefault("activity", [])
        activity.append({"kind": kind, "actor_id": getattr(actor, "id", actor) or 0,
                         "at": self._now(), "text": text[:200]})
        del activity[:-50]

    def _touch(self, record, actor):
        record.update(updated_by=actor.id, updated_at=self._now(), revision=record.get("revision", 1) + 1)

    def _validate_owner(self, guild, conf, owner):
        if owner in (getattr(self.bot, "owner_ids", None) or set()):
            return
        if owner:
            member = guild.get_member(owner)
            if member is None or getattr(member, "bot", False) or not self.can_view(member, conf):
                raise CalendarError("Die verantwortliche Person muss aktuell zum berechtigten Team gehören.")

    def _task_references(self, guild, conf, values, previous=None):
        previous = previous or {}
        project_id = str(values.get("project_id") or "")
        if project_id:
            project = self._record(conf, "projects", project_id)
            if project.get("status") in {"completed", "archived"} and previous.get("project_id") != project_id:
                raise CalendarError("Neue Aufgaben brauchen ein aktives oder pausiertes Projekt. Bitte das Projekt zuerst aktivieren.")
        for uid in values.get("assignee_ids") or []:
            member = guild.get_member(uid)
            if member is None or getattr(member, "bot", False) or not self.can_view(member, conf):
                raise CalendarError("Zuweisungen sind nur an aktuelle Teammitglieder dieses Servers möglich.")
        event_id = str(values.get("event_id") or "")
        if event_id and event_id not in (conf.get("events") or {}):
            raise CalendarError("Der verknüpfte Termin existiert auf diesem Server nicht mehr.")

    async def create_project(self, guild, actor, data):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._project_actor(guild, actor, conf, projects=True)
            if len(conf["projects"]) >= MAX_PROJECTS:
                raise CalendarError(f"Höchstens {MAX_PROJECTS} Projekte je Server.")
            values = normalize_project(data, conf, now=self._now())
            values["owner_id"] = values.get("owner_id") or actor.id
            self._validate_owner(guild, conf, values["owner_id"])
            ident = str(conf["project_counter"] + 1)
            record = {**values, "id": ident, "status": "active", "created_by": actor.id, "updated_by": actor.id,
                      "created_at": self._now(), "updated_at": self._now(), "revision": 1}
            conf["project_counter"] = int(ident)
            conf["projects"][ident] = record
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            return copy.deepcopy(record)

    async def update_project(self, guild, actor, pid, data, revision=None):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._project_actor(guild, actor, conf, projects=True)
            previous = self._record(conf, "projects", pid, revision)
            values = normalize_project(data, conf, previous=previous, now=self._now())
            self._validate_owner(guild, conf, values.get("owner_id"))
            previous.update(values)
            self._touch(previous, actor)
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            await self._refresh_board_locked(guild)
            return copy.deepcopy(previous)

    async def project_action(self, guild, actor, pid, action, revision=None):
        if action not in {"pause", "activate", "complete", "archive", "delete"}:
            raise CalendarError("Unbekannte Projektaktion.")
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._project_actor(guild, actor, conf, projects=True)
            project = self._record(conf, "projects", pid, revision)
            tasks = [task for task in conf["work_tasks"].values() if task.get("project_id") == str(pid)]
            if action == "complete" and any(task.get("status") != "done" for task in tasks):
                raise CalendarError("Das Projekt hat noch offene Aufgaben. Bitte diese zuerst abschließen oder einem anderen Projekt zuordnen.")
            if action == "delete":
                if tasks or any(event.get("project_id") == str(pid) for event in conf["events"].values()):
                    raise CalendarError("Das Projekt wird noch von Aufgaben oder Terminen verwendet. Bitte stattdessen archivieren.")
                del conf["projects"][str(pid)]
                result = None
            else:
                project["status"] = {"pause": "paused", "activate": "active", "complete": "completed", "archive": "archived"}[action]
                self._touch(project, actor)
                result = copy.deepcopy(project)
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            return result

    async def create_task(self, guild, actor, data):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._project_actor(guild, actor, conf)
            if len(conf["work_tasks"]) >= MAX_TASKS:
                raise CalendarError(f"Höchstens {MAX_TASKS} Aufgaben je Server. Bitte alte Aufgaben exportieren und bei Bedarf ausdrücklich löschen.")
            values = normalize_task(data, conf, now=self._now())
            self._task_references(guild, conf, values)
            ident = str(conf["task_counter"] + 1)
            record = {**values, "id": ident, "status": "todo", "comments": [], "comment_counter": 0,
                      "activity": [], "reminders_sent": {}, "created_by": actor.id, "updated_by": actor.id,
                      "created_at": self._now(), "updated_at": self._now(), "revision": 1}
            self._activity(record, actor, "created", "Aufgabe erstellt")
            conf["task_counter"] = int(ident)
            conf["work_tasks"][ident] = record
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            return copy.deepcopy(record)

    async def update_task(self, guild, actor, tid, data, revision=None):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            previous = self._record(conf, "work_tasks", tid, revision)
            actor = await self._project_actor(guild, actor, conf, task=previous)
            values = normalize_task(data, conf, previous=previous, now=self._now())
            self._task_references(guild, conf, values, previous)
            previous.update(values)
            self._touch(previous, actor)
            self._activity(previous, actor, "updated", "Aufgabe bearbeitet")
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            return copy.deepcopy(previous)

    async def assign_task(self, guild, actor, tid, assignee_ids, revision=None):
        return await self.update_task(guild, actor, tid, {"assignee_ids": assignee_ids}, revision)

    async def task_action(self, guild, actor, tid, action, revision=None):
        if action not in {"todo", "in_progress", "blocked", "done", "delete"}:
            raise CalendarError("Unbekannte Aufgabenaktion.")
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            task = self._record(conf, "work_tasks", tid, revision)
            actor = await self._project_actor(guild, actor, conf, task=task, work=action != "delete")
            if action == "delete":
                del conf["work_tasks"][str(tid)]
                result = None
            else:
                project = conf.get("projects", {}).get(task.get("project_id")) or {}
                if (action != "done" and task.get("status") == "done"
                        and project.get("status") in {"completed", "archived"}):
                    raise CalendarError("Bitte zuerst das abgeschlossene oder archivierte Projekt aktivieren.")
                task["status"] = action
                self._touch(task, actor)
                self._activity(task, actor, "status", {"todo": "Offen", "in_progress": "In Arbeit", "blocked": "Blockiert", "done": "Erledigt"}[action])
                result = copy.deepcopy(task)
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            return result

    async def toggle_checklist(self, guild, actor, tid, item_id, done, revision=None):
        if not isinstance(done, bool):
            raise CalendarError("Ungültiger Checklistenstatus.")
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            task = self._record(conf, "work_tasks", tid, revision)
            actor = await self._project_actor(guild, actor, conf, task=task, work=True)
            item = next((item for item in task.get("checklist") or [] if item.get("id") == str(item_id)), None)
            if item is None:
                raise CalendarError("Dieser Checklistenpunkt existiert nicht mehr.")
            if item.get("done") != done:
                item["done"] = done
                self._touch(task, actor)
                self._activity(task, actor, "checklist", "Checklistenpunkt abgehakt" if done else "Checklistenpunkt wieder geöffnet")
                await self.config.guild(guild).set(conf)
                await self._refresh_task_board_locked(guild)
            return copy.deepcopy(task)

    async def add_task_comment(self, guild, actor, tid, text):
        text = str(text or "").strip()
        if not 1 <= len(text) <= 1000 or "\x00" in text:
            raise CalendarError("Kommentare brauchen 1 bis 1000 Zeichen.")
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            task = self._record(conf, "work_tasks", tid)
            actor = await self._project_actor(guild, actor, conf, task=task, work=True)
            comments = task.setdefault("comments", [])
            if len(comments) >= MAX_COMMENTS:
                raise CalendarError(f"Höchstens {MAX_COMMENTS} Kommentare je Aufgabe.")
            task["comment_counter"] = task.get("comment_counter", 0) + 1
            comments.append({"id": str(task["comment_counter"]), "author_id": actor.id, "text": text, "created_at": self._now()})
            task.update(updated_by=actor.id, updated_at=self._now())
            self._activity(task, actor, "comment", "Kommentar hinzugefügt")
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            return copy.deepcopy(task)

    async def delete_task_comment(self, guild, actor, tid, comment_id):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._authorize(guild, actor, conf, view=True)
            task = self._record(conf, "work_tasks", tid)
            comments = task.get("comments") or []
            comment = next((item for item in comments if str(item.get("id")) == str(comment_id)), None)
            if comment is None:
                raise CalendarError("Dieser Kommentar existiert nicht mehr.")
            if comment.get("author_id") != actor.id and not self._lead(actor, conf):
                raise CalendarError("Nur der Verfasser oder die Projektverwaltung darf diesen Kommentar entfernen.")
            task["comments"] = [item for item in comments if item is not comment]
            task.update(updated_by=actor.id, updated_at=self._now())
            self._activity(task, actor, "comment_deleted", "Kommentar entfernt")
            await self.config.guild(guild).set(conf)
            await self._refresh_task_board_locked(guild)
            return copy.deepcopy(task)

    def _unlink_event_tasks(self, conf, eid, actor):
        for task in conf.get("work_tasks", {}).values():
            if task.get("event_id") == str(eid):
                task["event_id"] = ""
                self._touch(task, actor)
                self._activity(task, actor, "event_unlinked", "Verknüpfter Termin entfernt")

    def _task_board_embed(self, guild, conf):
        visible = [task for task in conf.get("work_tasks", {}).values() if task.get("status") != "done"
                   and (conf.get("projects", {}).get(task.get("project_id")) or {}).get("status") != "archived"]
        priority = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        visible.sort(key=lambda task: (task.get("due_ts") is None, task.get("due_ts") or 0,
                                       priority.get(task.get("priority"), 2), task["id"]))
        lines = []
        for task in visible[:15]:
            title = discord.utils.escape_markdown(task["title"][:59] + ("…" if len(task["title"]) > 59 else ""))
            label = {"todo": "Offen", "in_progress": "In Arbeit", "blocked": "Blockiert"}.get(task.get("status"), "Offen")
            due = f" · <t:{task['due_ts']}:d>" if task.get("due_ts") else ""
            checked = task.get("checklist") or []
            progress = f" · {sum(bool(item.get('done')) for item in checked)}/{len(checked)}" if checked else ""
            lines.append(f"`#{task['id']}` **{title}** · {label}{due}{progress}")
        if len(visible) > 15:
            lines.append(f"\nWeitere {len(visible) - 15} Aufgaben in der Auswahl oder im Dashboard.")
        return discord.Embed(title="Projektaufgaben · " + guild.name[:100], description="\n".join(lines) or "Keine offenen Aufgaben.", color=0x3DDC97)

    async def _refresh_task_board_locked(self, guild):
        try:
            if self._unloading:
                return
            conf = await self.config.guild(guild).all()
            channel = self._channel(guild, conf.get("task_board_channel"))
            if channel is None:
                if conf.get("task_board_channel"):
                    await self.config.guild(guild).task_board_error.set("Der Aufgabenkanal ist nicht erreichbar. Kanal und Rechte prüfen.")
                return
            if not conf.get("task_board_message_id"):
                return
            try:
                message = await channel.fetch_message(conf["task_board_message_id"])
            except discord.NotFound:
                message = None
            if self._unloading:
                return
            from .task_views import build_task_board_view
            kwargs = dict(embed=self._task_board_embed(guild, conf), view=build_task_board_view(),
                          allowed_mentions=discord.AllowedMentions.none())
            if message is not None:
                if not message.embeds or message.embeds[0].to_dict() != kwargs["embed"].to_dict() or not getattr(message, "components", None):
                    await message.edit(**kwargs)
            else:
                async def send_checkpoint():
                    if not self._unloading:
                        posted = await channel.send(**kwargs)
                        await self.config.guild(guild).task_board_message_id.set(posted.id)
                transaction = asyncio.create_task(send_checkpoint())
                try:
                    await asyncio.shield(transaction)
                except asyncio.CancelledError:
                    await transaction
                    raise
            await self.config.guild(guild).task_board_error.set(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Aufgabenübersicht für Server %s nicht aktualisiert", guild.id)
            try:
                await self.config.guild(guild).task_board_error.set("Aufgabenübersicht nicht aktualisiert. Kanalrechte prüfen und erneut versuchen.")
            except Exception:
                log.exception("Aufgabenstatus für Server %s nicht speicherbar", guild.id)

    async def refresh_task_board(self, guild, actor=None):
        async with self._lock(guild):
            if self._unloading or await self.bot.cog_disabled_in_guild(self, guild):
                return
            if actor is not None:
                await self._project_actor(guild, actor, await self.config.guild(guild).all())
            await self._refresh_task_board_locked(guild)

    async def post_task_board(self, guild, actor, channel=None):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._authorize(guild, actor, conf, configure=channel is not None, view=channel is None)
            if channel is None and not self.can_edit_task(actor, conf):
                raise CalendarError("Nur die Aufgabenverwaltung darf die Übersicht veröffentlichen.")
            target = self._valid_channel(guild, getattr(channel, "id", channel) if channel is not None else conf.get("task_board_channel"))
            if target is None:
                raise CalendarError("Bitte zuerst einen Aufgabenkanal auswählen.")
            if target.id == conf.get("task_board_channel") and conf.get("task_board_message_id"):
                await self._refresh_task_board_locked(guild)
                return
            old_channel = self._channel(guild, conf.get("task_board_channel"))
            old_id = conf.get("task_board_message_id")
            from .task_views import build_task_board_view
            async def publish():
                if self._unloading:
                    raise CalendarError("Das Projektmanagement wird gerade entladen.")
                message = await target.send(embed=self._task_board_embed(guild, conf), view=build_task_board_view(),
                                            allowed_mentions=discord.AllowedMentions.none())
                conf.update(task_board_channel=target.id, task_board_message_id=message.id, task_board_error=None)
                await self.config.guild(guild).set(conf)
                if old_channel is not None and old_id:
                    try:
                        await (await old_channel.fetch_message(old_id)).delete()
                    except discord.HTTPException:
                        await self.config.guild(guild).task_board_error.set("Neue Übersicht veröffentlicht; alte Nachricht bitte manuell entfernen.")
            transaction = asyncio.create_task(publish())
            try:
                await asyncio.shield(transaction)
            except asyncio.CancelledError:
                await transaction
                raise
            except discord.HTTPException:
                raise CalendarError("Aufgabenübersicht nicht veröffentlicht. Bitte Kanalrechte prüfen.") from None

    async def _tick_projects_locked(self, guild, conf, now):
        tasks = conf.get("work_tasks") or {}
        channel = self._channel(guild, conf.get("task_board_channel") or conf.get("reminder_channel") or conf.get("calendar_channel"))
        candidates = []
        if channel is not None and not self._unloading:
            for task in tasks.values():
                due = task.get("due_ts")
                project = (conf.get("projects") or {}).get(task.get("project_id")) or {}
                if not due or task.get("status") == "done" or project.get("status") in {"paused", "archived", "completed"}:
                    continue
                sent = task.setdefault("reminders_sent", {})
                eligible = []
                for offset in conf.get("task_reminder_minutes", [1440, 60, 0]):
                    key = f"{due}:{offset}"
                    marker = sent.get(key) or {}
                    when = due - int(offset) * 60
                    until = due + 7 * 86400 if int(offset) == 0 else when + 300
                    if (now < when or now > until or marker.get("state") in {"reserved", "sent", "skipped"}
                            or marker.get("attempts", 0) >= 3 or marker.get("retry_at", 0) > now):
                        continue
                    eligible.append(int(offset))
                if eligible:
                    candidates.append((task, min(eligible), eligible))
            candidates.sort(key=lambda item: (item[0]["due_ts"], item[0]["id"]))
            selected = candidates[:10]
            if selected:
                for task, offset, eligible in selected:
                    sent = task["reminders_sent"]
                    for skipped in eligible:
                        if skipped != offset:
                            sent[f"{task['due_ts']}:{skipped}"] = {"state": "skipped", "at": now}
                    key = f"{task['due_ts']}:{offset}"
                    attempts = (sent.get(key) or {}).get("attempts", 0) + 1
                    sent[key] = {"state": "reserved", "at": now, "attempts": attempts}
                await self.config.guild(guild).work_tasks.set(tasks)
                lines = [f"`#{task['id']}` **{discord.utils.escape_markdown(task['title'][:100])}** · <t:{task['due_ts']}:R>"
                         for task, _, _ in selected]
                try:
                    await channel.send(embed=discord.Embed(title="Aufgaben: Fälligkeit prüfen", description="\n".join(lines), color=0xF5B94A),
                                       allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException as exc:
                    if 400 <= exc.status < 500:
                        for task, offset, _ in selected:
                            task["reminders_sent"][f"{task['due_ts']}:{offset}"].update(state="failed", retry_at=now + 60)
                else:
                    for task, offset, _ in selected:
                        task["reminders_sent"][f"{task['due_ts']}:{offset}"]["state"] = "sent"
                await self.config.guild(guild).work_tasks.set(tasks)
        await self._refresh_task_board_locked(guild)

    def _scrub_projects_locked(self, conf, uid):
        for project in conf.get("projects", {}).values():
            if project.get("owner_id") == uid:
                project["revision"] = project.get("revision", 1) + 1
            for key in ("owner_id", "created_by", "updated_by"):
                if project.get(key) == uid:
                    project[key] = 0
        for task in conf.get("work_tasks", {}).values():
            previous_assignees = task.get("assignee_ids") or []
            task["assignee_ids"] = [ident for ident in previous_assignees if ident != uid]
            if task["assignee_ids"] != previous_assignees:
                task["revision"] = task.get("revision", 1) + 1
            task["comments"] = [comment for comment in task.get("comments") or [] if comment.get("author_id") != uid]
            for key in ("created_by", "updated_by"):
                if task.get(key) == uid:
                    task[key] = 0
            for entry in task.get("activity") or []:
                if entry.get("actor_id") == uid:
                    entry["actor_id"] = 0
