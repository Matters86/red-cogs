"""Projekte/Aufgaben: gemeinsame und zugewiesene Rechte, Referenzen, Rennen und Ausfälle."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import discord
import tc_harness as T
from rc.teamcalendar.teamcalendar import TeamCalendar
from rc.teamcalendar.models import CalendarError


async def denied(call):
    try:
        await call
    except CalendarError:
        return
    raise AssertionError("Ungültige oder unberechtigte Projektaktion wurde ausgeführt")


class Ctx:
    def __init__(self, guild, author):
        self.guild, self.author = guild, author
        self.sent, self.deferred = [], []
    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
    async def defer(self, **kwargs):
        self.deferred.append(kwargs)


async def main():
    wc, bot, app, _, _ = await T.make_app()
    cog = TeamCalendar(bot)
    bot._cogs["TeamCalendar"] = cog
    guild, other_guild = bot.guilds
    admin, lena, tom, mia, guest = (guild.get_member(uid) for uid in (1, 11, 12, 14, 15))
    gc = cog.config.guild(guild)
    clock = [int(datetime(2026, 11, 9, 12, tzinfo=timezone.utc).timestamp())]
    cog._now = lambda: clock[0]
    iso = lambda stamp: datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    await cog.save_settings(guild, admin, {"team_roles": [1101, 1102], "manager_roles": [1103]})
    legacy = await cog.create_event(guild, lena, {"title": "Bestehender Kalendertermin", "project": "Altes freies Projekt",
        "start": iso(clock[0] + 86400), "end": iso(clock[0] + 90000), "reminder_minutes": []})
    assert (await gc.events())[legacy["id"]]["project"] == "Altes freies Projekt"
    assert await gc.counter() == 1 and await gc.project_counter() == 0 and await gc.task_counter() == 0
    assert cog.can_manage_projects(lena, await gc.all()) and cog.can_edit_task(tom, await gc.all())
    assert not cog.can_edit_task(guest, await gc.all())
    await cog.save_settings(guild, admin, {"team_can_manage": False})
    assert cog.can_edit_task(lena, await gc.all()) and not cog.can_manage(lena, await gc.all())
    await denied(cog.create_event(guild, lena, {"title": "Kalender bleibt getrennt", "start": iso(clock[0] + 3600), "end": iso(clock[0] + 7200)}))
    await denied(cog.create_project(guild, guest, {"name": "Verboten"}))
    await denied(cog.save_settings(guild, tom, {"task_edit_mode": "assigned"}))
    await denied(cog.save_settings(guild, admin, {"task_edit_mode": "unknown"}))
    project = await cog.create_project(guild, lena, {"name": "Serverstart", "owner_id": tom.id, "deadline": "2026-11-20"})
    await cog.save_settings(guild, admin, {"team_can_manage": True})
    pid = project["id"]
    assert project["owner_id"] == tom.id and project["status"] == "active" and project["deadline_ts"]
    project = await cog.update_project(guild, tom, pid, {"description": "Gemeinsam bearbeitet"}, revision=1)
    assert project["revision"] == 2 and project["created_by"] == lena.id
    await denied(cog.update_project(guild, lena, pid, {"name": "Veraltet"}, revision=1))
    await denied(cog.create_project(guild, lena, {"name": "Falscher Owner", "owner_id": guest.id}))
    task = await cog.create_task(guild, lena, {"title": "Erste Aufgabe", "description": "Planen", "project_id": pid,
        "assignee_ids": [lena.id, tom.id], "due": iso(clock[0] + 3600), "priority": "high",
        "checklist": "Entwurf\nTest", "milestone": True, "event_id": legacy["id"]})
    tid = task["id"]
    assert task["status"] == "todo" and len(task["checklist"]) == 2 and task["milestone"]
    await cog.config.guild(other_guild).projects.set({"999": {"id": "999", "name": "Fremd"}})
    await cog.config.guild(other_guild).events.set({"999": {"id": "999"}})
    for raw in ({"project_id": "999"}, {"event_id": "999"}, {"assignee_ids": [guest.id]}, {"assignee_ids": [21]}, {"assignee_ids": [guild.me.id]}):
        await denied(cog.update_task(guild, lena, tid, raw))
    assert (await gc.work_tasks())[tid]["assignee_ids"] == [lena.id, tom.id]
    await denied(cog.project_action(guild, tom, pid, "complete"))
    await denied(cog.project_action(guild, tom, pid, "delete"))

    item = task["checklist"][0]
    task = await cog.toggle_checklist(guild, tom, tid, item["id"], True, revision=1)
    assert task["revision"] == 2 and task["checklist"][0]["done"]
    await denied(cog.toggle_checklist(guild, lena, tid, "foreign-item", True))
    await denied(cog.toggle_checklist(guild, lena, tid, item["id"], "false"))
    revision = task["revision"]
    task = await cog.add_task_comment(guild, lena, tid, "Lenas Kommentar")
    assert task["revision"] == revision
    comment_id = task["comments"][-1]["id"]
    task = await cog.update_task(guild, tom, tid, {"description": "Nach Kommentar bearbeitet"}, revision=revision)
    assert task["comments"][-1]["text"] == "Lenas Kommentar" and task["checklist"][0]["done"]
    await denied(cog.delete_task_comment(guild, tom, tid, comment_id))
    task = await cog.delete_task_comment(guild, lena, tid, comment_id)
    assert not task["comments"]
    results = await asyncio.gather(cog.task_action(guild, lena, tid, "in_progress", task["revision"]),
        cog.task_action(guild, tom, tid, "blocked", task["revision"]), return_exceptions=True)
    assert sum(isinstance(result, CalendarError) for result in results) == 1
    task = (await gc.work_tasks())[tid]
    task = await cog.task_action(guild, tom, tid, "done", revision=task["revision"])
    await cog.project_action(guild, lena, pid, "complete")
    await denied(cog.create_task(guild, tom, {"title": "Zu spät", "project_id": pid}))
    await denied(cog.task_action(guild, tom, tid, "todo"))
    await cog.project_action(guild, lena, pid, "activate")
    await cog.task_action(guild, tom, tid, "todo")

    # Modus „zugewiesen“: Team liest; nur Zuständige arbeiten, Verwaltung plant.
    await cog.save_settings(guild, admin, {"task_edit_mode": "assigned"})
    assert not cog.can_edit_task(lena, await gc.all(), task) and cog.can_work_task(lena, await gc.all(), task)
    await denied(cog.create_task(guild, lena, {"title": "Nicht geplant"}))
    await denied(cog.update_task(guild, tom, tid, {"title": "Unbefugte Vollbearbeitung"}))
    await denied(cog.assign_task(guild, lena, tid, [lena.id]))
    await denied(cog.create_project(guild, tom, {"name": "Nicht erlaubt"}))
    await denied(cog.task_action(guild, tom, tid, "delete"))
    await cog.assign_task(guild, admin, tid, [lena.id])
    await denied(cog.task_action(guild, tom, tid, "done"))
    await cog.task_action(guild, lena, tid, "in_progress")
    await cog.toggle_checklist(guild, lena, tid, item["id"], False)
    task = await cog.add_task_comment(guild, lena, tid, "Eigener Kommentar nach Zuweisung")
    own_comment = task["comments"][-1]["id"]
    await cog.assign_task(guild, admin, tid, [tom.id])
    await denied(cog.add_task_comment(guild, lena, tid, "Nicht mehr zuständig"))
    await cog.delete_task_comment(guild, lena, tid, own_comment)  # eigener Kommentar trotz späterer Übergabe
    await cog.add_task_comment(guild, tom, tid, "Tom bleibt erhalten")
    await cog.add_task_comment(guild, admin, tid, "Admin-Kommentar")
    await denied(cog.delete_task_comment(guild, tom, tid, (await gc.work_tasks())[tid]["comments"][-1]["id"]))
    await cog.delete_task_comment(guild, admin, tid, (await gc.work_tasks())[tid]["comments"][-1]["id"])

    # Rollenentzug während eine Aktion am Guild-Lock wartet.
    await cog._lock(guild).acquire()
    pending = asyncio.create_task(cog.task_action(guild, tom, tid, "done"))
    await asyncio.sleep(0)
    roles = tom.roles
    tom.roles = [guild.default_role]
    cog._lock(guild).release()
    await denied(pending)
    tom.roles = roles
    await cog.save_settings(guild, admin, {"task_edit_mode": "team"})

    # Kalenderverknüpfung und Löschschutz bleiben konsistent.
    event = await cog.create_event(guild, tom, {"title": "Projekttermin", "project_id": pid, "project": "Altes Freitextfeld",
        "start": iso(clock[0] + 7200), "end": iso(clock[0] + 10800), "reminder_minutes": []})
    assert event["project_id"] == pid and event["project"] == "Altes Freitextfeld"
    await denied(cog.create_event(guild, tom, {"title": "Fremd", "project_id": "999", "start": iso(clock[0] + 7200), "end": iso(clock[0] + 10800)}))
    await cog.update_task(guild, tom, tid, {"event_id": event["id"]})
    before_revision = (await gc.work_tasks())[tid]["revision"]
    await cog.event_action(guild, lena, event["id"], "delete")
    task = (await gc.work_tasks())[tid]
    assert task["event_id"] == "" and task["revision"] == before_revision + 1
    await cog.task_action(guild, tom, tid, "delete")
    await cog.project_action(guild, lena, pid, "delete")
    assert pid not in await gc.projects() and legacy["id"] in await gc.events()
    assert (await gc.events())[legacy["id"]]["project"] == "Altes freies Projekt"

    # Board-Fehler dürfen gespeicherte Aufgaben nicht zurückrollen; NotFound repariert.
    task = await cog.create_task(guild, lena, {"title": "Board-Aufgabe", "assignee_ids": [tom.id]})
    channel = guild.get_channel(1002)
    await cog.post_task_board(guild, admin, channel)
    board_id = await gc.task_board_message_id()
    await cog.post_task_board(guild, tom)
    assert await gc.task_board_message_id() == board_id
    await denied(cog.post_task_board(guild, tom, guild.get_channel(1001)))
    await denied(cog.refresh_task_board(guild, guest))
    await channel._messages[board_id].delete()
    await cog.refresh_task_board(guild, tom)
    assert await gc.task_board_message_id() != board_id
    channel.forbid.add("history")
    saved = await cog.create_task(guild, tom, {"title": "Trotz Fehler behalten"})
    assert saved["id"] in await gc.work_tasks() and await gc.task_board_error()
    channel.forbid.remove("history")
    await cog.refresh_task_board(guild, tom)
    assert not await gc.task_board_error()
    configured_id = await gc.task_board_message_id()
    await gc.task_board_channel.set(999999)
    await cog.refresh_task_board(guild)
    assert await gc.task_board_error() and await gc.task_board_message_id() == configured_id
    await gc.task_board_channel.set(channel.id)
    await cog.refresh_task_board(guild)
    context = Ctx(guild, tom)
    await cog.work_details.callback(cog, context, task["id"])
    assert context.sent[-1][1]["ephemeral"] and context.sent[-1][1]["view"].children
    await cog.work_status.callback(cog, context, task["id"], "delete")
    assert task["id"] in await gc.work_tasks()
    await cog.work_status.callback(cog, context, task["id"], "arbeit")
    assert context.deferred

    # Ein Digest mit höchstens zehn Aufgaben, nach Neustart keine doppelten Marker.
    await cog.save_settings(guild, admin, {"task_reminder_minutes": [0]})
    reminder_tasks = []
    for index in range(12):
        reminder_tasks.append(await cog.create_task(guild, lena, {"title": f"Fällig {index}", "due": iso(clock[0] - 3600)}))
    send, notices = channel.send, []
    async def tracked_send(*args, **kwargs):
        notices.append(kwargs)
        return await send(*args, **kwargs)
    channel.send = tracked_send
    await cog._tick_once()
    assert len(notices) == 1 and notices[-1]["embed"].description.count("`#") == 10
    assert notices[-1]["allowed_mentions"].everyone is False
    restarted = TeamCalendar(bot)
    restarted._now = cog._now
    await restarted._tick_once()
    assert len(notices) == 2 and notices[-1]["embed"].description.count("`#") == 2
    await restarted._tick_once()
    assert len(notices) == 2
    stable = reminder_tasks[0]
    await cog.update_task(guild, tom, stable["id"], {"description": "Nur Metadaten geändert"})
    await cog.task_action(guild, tom, stable["id"], "done")
    await cog.task_action(guild, tom, stable["id"], "todo")
    await restarted._tick_once()
    assert len(notices) == 2
    silent_project = await cog.create_project(guild, lena, {"name": "Pausierte Frist"})
    silent = await cog.create_task(guild, tom, {"title": "Pausiert", "project_id": silent_project["id"], "due": iso(clock[0] - 60)})
    await cog.project_action(guild, tom, silent_project["id"], "pause")
    await cog._tick_once()
    assert len(notices) == 2 and not (await gc.work_tasks())[silent["id"]]["reminders_sent"]
    await cog.project_action(guild, tom, silent_project["id"], "archive")
    await cog._tick_once()
    assert len(notices) == 2
    await cog.project_action(guild, tom, silent_project["id"], "activate")
    await cog._tick_once()
    assert len(notices) == 3

    retry = await cog.create_task(guild, tom, {"title": "Retry", "due": iso(clock[0] - 60)})
    channel.forbid.add("send")
    await cog._tick_once()
    key = f"{retry['due_ts']}:0"
    assert (await gc.work_tasks())[retry["id"]]["reminders_sent"][key]["state"] == "failed"
    channel.forbid.remove("send")
    clock[0] += 61
    await cog._tick_once()
    assert (await gc.work_tasks())[retry["id"]]["reminders_sent"][key]["state"] == "sent"
    uncertain = await cog.create_task(guild, tom, {"title": "Unklare Antwort", "due": iso(clock[0] - 60)})
    async def server_error(*args, **kwargs):
        raise discord.HTTPException(SimpleNamespace(status=503, reason="Unavailable"), "Unklar")
    channel.send = server_error
    await cog._tick_once()
    assert (await gc.work_tasks())[uncertain["id"]]["reminders_sent"][f"{uncertain['due_ts']}:0"]["state"] == "reserved"
    channel.send = tracked_send
    before = len(notices)
    await restarted._tick_once()
    assert len(notices) == before
    cancelled = await cog.create_task(guild, tom, {"title": "Abbruch beim Senden", "due": iso(clock[0] - 60)})
    entered = asyncio.Event()
    async def suspended_send(*args, **kwargs):
        entered.set()
        await asyncio.Future()
    channel.send = suspended_send
    pending = asyncio.create_task(cog._tick_once())
    await entered.wait()
    pending.cancel()
    try:
        await pending
    except asyncio.CancelledError:
        pass
    assert (await gc.work_tasks())[cancelled["id"]]["reminders_sent"][f"{cancelled['due_ts']}:0"]["state"] == "reserved"
    channel.send = tracked_send
    before = len(notices)
    await restarted._tick_once()
    assert len(notices) == before

    # Datenschutz entfernt Kommentare/Identitäten, erhält fremde Arbeit und die Kalenderdaten.
    personal_project = await cog.create_project(guild, lena, {"name": "Datenschutz", "owner_id": lena.id})
    personal = await cog.create_task(guild, lena, {"title": "Gemeinsame Arbeit", "project_id": personal_project["id"],
        "assignee_ids": [lena.id, tom.id], "checklist": "Prüfung"})
    await cog.add_task_comment(guild, lena, personal["id"], "LENA-PERSÖNLICH")
    await cog.add_task_comment(guild, tom, personal["id"], "Toms Beitrag")
    cog._ux_drafts = {("s", guild.id, f"teamcalendar:{lena.id}:task:new"): {"text": "privat"},
                      ("s", guild.id, f"teamcalendar:{tom.id}:task:new"): {"text": "anderer"}}
    await cog.red_delete_data_for_user(requester="owner", user_id=lena.id)
    after = (await gc.work_tasks())[personal["id"]]
    assert after["assignee_ids"] == [tom.id] and after["created_by"] == 0
    assert after["revision"] == personal["revision"] + 1
    await denied(cog.update_task(guild, tom, personal["id"], {"assignee_ids": [lena.id, tom.id]}, revision=personal["revision"]))
    await denied(cog.update_project(guild, tom, personal_project["id"], {"owner_id": lena.id}, revision=personal_project["revision"]))
    await denied(cog.update_event(guild, tom, legacy["id"], {"title": legacy["title"], "project": legacy["project"],
        "owner_id": lena.id, "start": iso(legacy["start_ts"]), "end": iso(legacy["end_ts"])}, revision=legacy["revision"]))
    assert (await gc.work_tasks())[personal["id"]]["assignee_ids"] == [tom.id]
    assert (await gc.projects())[personal_project["id"]]["owner_id"] == 0
    assert (await gc.events())[legacy["id"]]["owner_id"] == 0
    assert [comment["text"] for comment in after["comments"]] == ["Toms Beitrag"]
    assert not any(entry["actor_id"] == lena.id for entry in after["activity"])
    assert (await gc.projects())[personal_project["id"]]["owner_id"] == 0
    assert len(cog._ux_drafts) == 1 and legacy["id"] in await gc.events()
    # Kalender-Aufbewahrung löscht keine Aufgaben, Kommentare oder Fortschrittshistorie.
    async with gc.work_tasks() as tasks:
        tasks[personal["id"]].update(status="done", updated_at=clock[0] - 181 * 86400)
        tasks[stable["id"]].update(updated_at=clock[0] - 181 * 86400, milestone=True)
    await cog._tick_once()
    assert personal["id"] in await gc.work_tasks() and stable["id"] in await gc.work_tasks()
    assert (await gc.work_tasks())[personal["id"]]["comments"][0]["text"] == "Toms Beitrag"
    async with gc.events() as events:
        events["9999"] = {**legacy, "id": "9999", "status": "completed",
                          "start_ts": clock[0] - 200 * 86400, "end_ts": clock[0] - 199 * 86400}
    linked_old = await cog.create_task(guild, tom, {"title": "Aufgabe bleibt nach Kalender-Aufbewahrung", "event_id": "9999"})
    await cog._tick_once()
    assert "9999" not in await gc.events() and linked_old["id"] in await gc.work_tasks()
    assert (await gc.work_tasks())[linked_old["id"]]["event_id"] == ""
    assert await gc.counter() == 2 and (await gc.events())[legacy["id"]]["project"] == "Altes freies Projekt"
    assert len(after["activity"]) <= 50
    other_guild.members = [member for member in other_guild.members if member.id != 1]
    owner_project = await cog.create_project(other_guild, SimpleNamespace(id=1), {"name": "Owner ohne Servermitgliedschaft"})
    assert owner_project["owner_id"] == 1
    print("project_management_core_test: PASS – Team/zugewiesen, Referenzen, Revisionen, Boards, Digest, Datenschutz")


asyncio.run(main())
