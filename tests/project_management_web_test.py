"""Projekt-/Aufgaben-Dashboard: echte HTTP-Anfragen, Team-/Zuständigenmodus und Kalenderbestand."""
import asyncio
import re
from copy import deepcopy
from urllib.parse import unquote_plus

import live_harness as L
from aiohttp.test_utils import TestClient, TestServer
from rc.teamcalendar.teamcalendar import TeamCalendar
from rc.teamcalendar.dashboard import discard_user


async def main():
    bot = L.H.FakeBot(L.H.build_world())
    wc = await L.H.make_webcore(bot)
    cog = TeamCalendar(bot)
    bot._cogs["TeamCalendar"] = cog
    cog._register_dashboard(wc)
    guild, foreign = bot.guilds
    gc = cog.config.guild(guild)
    readrole = L.H.Role(guild, 1117, "Projekt lesen", 1)
    guild.roles.append(readrole)
    guild.members.append(L.H.Member(guild, 17, "Nur Ansicht", [readrole]))
    await gc.team_roles.set([1101, 1102, 1117])
    await gc.manager_roles.set([1103])
    await wc.config.role_perms.set({"1000": {"1101": {"teamcalendar": "operate"}, "1102": {"teamcalendar": "operate"},
        "1103": {"teamcalendar": "edit"}, "1104": {"teamcalendar": "edit"}, "1117": {"teamcalendar": "view"}}})
    legacy = await cog.create_event(guild, guild.get_member(11), {"title": "Bestehender Termin", "project": "Altbestand freier Text",
        "start": "2035-06-12T18:00", "end": "2035-06-12T19:00", "owner_id": 11, "reminder_minutes": []})
    events_before = deepcopy(await gc.events())
    client = TestClient(TestServer(wc.app))
    second = TestClient(TestServer(wc.app))
    await client.start_server()
    await second.start_server()
    tokens, calls = {}, []

    async def page(uid=11, params=None, session=None):
        response = await (session or client).get("/cogs/teamcalendar", params={"guild": "1000", **(params or {})},
            headers={"X-Test-User": str(uid)}, allow_redirects=False)
        text = await response.text()
        match = re.search(r"name='csrf_token' value='([^']+)'", text)
        if match and session is None:
            tokens[uid] = match.group(1)
        return response, text

    async def post(uid, form, data=None, token=None):
        if uid not in tokens:
            await page(uid)
        response = await client.post("/cogs/teamcalendar", headers={"X-Test-User": str(uid)}, allow_redirects=False,
            data={"csrf_token": token if token is not None else tokens.get(uid) or next(iter(tokens.values()), ""),
                  "guild": "1000", "form": form, **(data or {})})
        return response, unquote_plus(response.headers.get("Location", ""))

    async def publish(guild, actor, channel=None):
        calls.append((guild.id, actor.id, getattr(channel, "id", None)))

    old_publish = cog.post_task_board
    cog.post_task_board = publish
    project_data = {"name": "Projekt <A>", "description": "Planung <script>alert(1)</script>", "owner_id": "11",
                    "deadline": "2035-07-01T18:00", "task_timezone": "Europe/Berlin"}
    task_data = {"title": "Meilenstein <img src=x onerror=alert(2)>", "description": "Arbeit im Team", "project_id": "1",
                 "assignee_ids": ["11", "12"], "due": "2035-06-11T18:00", "priority": "high", "milestone": "on",
                 "event_id": legacy["id"], "checklist": "Planen\nPrüfen", "task_timezone": "Europe/Berlin"}
    try:
        response, text = await page(11)
        assert response.status == 200 and "Noch keine Projekte" in text and "wc-kanban" in text
        assert "<details class='wc-disclosure'><summary>Aufgaben filtern</summary>" in text
        assert "Altbestand freier Text" in text and not calls
        response, location = await post(11, "project_save", project_data)
        assert response.status == 302 and "pm_project=1" in location and location.endswith("#projekte"), location
        response, location = await post(12, "task_save", task_data)
        assert response.status == 302 and "task=1" in location and location.endswith("#aufgabenboard"), location
        assert await gc.events() == events_before and not calls
        task = (await gc.work_tasks())["1"]
        assert task["created_by"] == 12 and task["assignee_ids"] == [11, 12] and len(task["checklist"]) == 2
        response, text = await page(11, {"task": "1"})
        assert response.status == 200 and "Projekt &lt;A&gt;" in text and "Meilenstein &lt;img" in text
        assert "<script>alert" not in text and "<img src=x" not in text and "Kalendertermin: Bestehender Termin" in text
        assert "name='task_timezone'" not in text  # Entwürfe werden erst ausdrücklich geöffnet.
        before = deepcopy(await gc.all())
        response, location = await post(11, "project_action", {"pid": "1", "action": "complete", "revision": "1"})
        assert "err=" in location and await gc.all() == before
        response, location = await post(11, "project_action", {"pid": "1", "action": "delete", "revision": "1"})
        assert "err=" in location and await gc.all() == before
        response, location = await post(11, "task_action", {"tid": "1", "action": "in_progress", "revision": "1"})
        assert "ok=" in location and (await gc.work_tasks())["1"]["status"] == "in_progress"
        before = deepcopy(await gc.all())
        response, location = await post(12, "task_action", {"tid": "1", "action": "delete", "revision": "1"})
        assert "err=" in location and await gc.all() == before
        item = (await gc.work_tasks())["1"]["checklist"][0]
        response, location = await post(11, "task_check", {"tid": "1", "item_id": item["id"], "done": "yes", "revision": "2"})
        assert "ok=" in location and (await gc.work_tasks())["1"]["checklist"][0]["done"] is True
        response, location = await post(12, "task_save", {**task_data, "tid": "1", "revision": "3", "checklist": "Prüfen\nPlanen"})
        assert "ok=" in location
        task = (await gc.work_tasks())["1"]
        assert next(point for point in task["checklist"] if point["text"] == "Planen") == {**item, "done": True}
        response, location = await post(12, "task_assign", {"tid": "1", "assignee_ids": ["11"], "revision": str(task["revision"])})
        assert "ok=" in location and (await gc.work_tasks())["1"]["assignee_ids"] == [11]
        response, location = await post(12, "task_comment", {"tid": "1", "text": "Mein Kommentar <b>", "author_id": "1"})
        assert "ok=" in location and (await gc.work_tasks())["1"]["comments"][0]["author_id"] == 12
        print("Gemeinsame Projekte/Aufgaben, Kalenderbestand, Verknüpfung, Versionen und Checklisten-Identität – OK")

        task = (await gc.work_tasks())["1"]
        current = deepcopy(await gc.all())
        response, location = await post(11, "task_save", {**task_data, "title": "Mein Entwurf <b>", "due": "kaputt", "tid": "1", "revision": str(task["revision"])})
        assert "err=" in location and location.endswith("#aufgabenboard") and await gc.all() == current
        _, text = await page(11, {"edit_task": "1", "pm_draft": "task"})
        assert "value='Mein Entwurf &lt;b&gt;'" in text and "Aktuellen Stand neu laden" in text
        _, text = await page(12, {"edit_task": "1", "pm_draft": "task"})
        assert "Mein Entwurf" not in text
        _, text = await page(11, {"edit_task": "1", "pm_draft": "task"}, session=second)
        assert "Mein Entwurf" not in text
        discard_user(cog, 11)
        _, text = await page(11, {"edit_task": "1", "pm_draft": "task"})
        assert "Mein Entwurf" not in text
        await gc.timezone.set("UTC")
        zone_before = deepcopy(await gc.all())
        for form, data in (("project_save", {**project_data, "pid": "1", "revision": "1"}),
                           ("task_save", {**task_data, "tid": "1", "revision": str(task["revision"])})):
            _, location = await post(11, form, data)
            assert "err=" in location and await gc.all() == zone_before
        await gc.timezone.set("Europe/Berlin")
        response, text = await page(17, {"task": "1"})
        assert response.status == 200 and "Mein Kommentar &lt;b&gt;" in text
        for form in ("task_save", "task_action", "task_check", "task_assign", "task_comment", "project_save"):
            assert f"name='form' value='{form}'" not in text
        before = deepcopy(await gc.all())
        response, location = await post(17, "task_action", {"tid": "1", "action": "done", "revision": str(task["revision"])})
        assert response.status in (302, 403) and await gc.all() == before
        response, _ = await post(11, "task_action", {"tid": "1", "action": "done", "revision": str(task["revision"])}, token="falsch")
        assert response.status == 400 and await gc.all() == before
        await wc.config.allowed_users.set([13])
        response, text = await page(13, {"download": "tasks_csv"})
        assert response.status == 403 and "Meilenstein" not in text
        print("Entwurfsisolation/Löschung, Zeitzonenschutz, Read-only, XSS und CSRF – OK")

        # Projekt-/Aufgabenrechte bleiben unabhängig von einer reinen Kalender-Leseeinstellung.
        await gc.team_can_manage.set(False)
        response, location = await post(12, "project_save", {**project_data, "pid": "1", "revision": "1"})
        assert "ok=" in location and (await gc.projects())["1"]["revision"] == 2
        await gc.team_can_manage.set(True)
        await gc.task_edit_mode.set("assigned")
        before = deepcopy(await gc.all())
        revision = (await gc.work_tasks())["1"]["revision"]
        for uid, form, data in ((11, "task_save", {**task_data, "tid": "1", "revision": str(revision)}),
                               (11, "task_assign", {"tid": "1", "assignee_ids": ["12"], "revision": str(revision)}),
                               (11, "task_action", {"tid": "1", "action": "delete", "revision": str(revision)}),
                               (11, "project_save", project_data),
                               (12, "task_action", {"tid": "1", "action": "done", "revision": str(revision)})):
            _, location = await post(uid, form, data)
            assert "err=" in location and await gc.all() == before, (uid, form, location)
        response, location = await post(11, "task_action", {"tid": "1", "action": "blocked", "revision": str(revision)})
        assert "ok=" in location and (await gc.work_tasks())["1"]["status"] == "blocked"
        response, location = await post(11, "task_comment", {"tid": "1", "text": "Zuständig arbeitet weiter"})
        assert "ok=" in location
        # Autor bleibt für seinen Kommentar verantwortlich, auch nach Entzug der Zuweisung.
        response, location = await post(12, "task_comment_delete", {"tid": "1", "comment_id": "1"})
        assert "ok=" in location and len((await gc.work_tasks())["1"]["comments"]) == 1
        before = deepcopy(await gc.all())
        response, location = await post(12, "task_comment_delete", {"tid": "1", "comment_id": "2"})
        assert "err=" in location and await gc.all() == before
        response, location = await post(14, "task_save", {**task_data, "title": "=FORMEL()", "milestone": "", "assignee_ids": ["12"], "event_id": ""})
        assert "ok=" in location
        response, text = await page(17, {"download": "tasks_csv"})
        assert response.status == 200 and response.content_type == "text/csv" and "'=FORMEL()" in text
        assert response.headers["Cache-Control"] == "private, no-store" and "Mein Kommentar" not in text
        _, text = await page(11)
        mine = text.split("data-tab='meine-aufgaben'", 1)[1].split("data-tab='agenda'", 1)[0]
        assert "Meilenstein &lt;img" in mine and "=FORMEL()" not in mine
        _, text = await page(11, {"assignee": "self", "task_status": "blocked"})
        assert "<details class='wc-disclosure' open><summary>Aufgaben filtern</summary>" in text
        board = text.split("data-tab='aufgabenboard'", 1)[1].split("data-tab='meine-aufgaben'", 1)[0]
        assert "Meilenstein &lt;img" in board and "=FORMEL()" not in board
        print("Zuständigenmodus, eigene Kommentare, Aufgabenfilter, persönliche Liste und formelsicherer CSV-Export – OK")

        response, location = await post(11, "task_board_publish", {"channel": "1001"})
        assert response.status == 302 and not calls
        response, location = await post(14, "task_board_publish", {"channel": "1001"})
        assert response.status == 302 and "ok=" in location and calls == [(1000, 14, 1001)]
        foreign_conf = cog.config.guild(foreign)
        foreign_before = deepcopy(await foreign_conf.all())
        await wc.config.allowed_users.set([11, 13])
        response = await client.post("/cogs/teamcalendar", headers={"X-Test-User": "11"}, data={
            "csrf_token": tokens[11], "guild": "2000", "form": "task_save", **task_data}, allow_redirects=False)
        assert response.status == 403 and await foreign_conf.all() == foreign_before
        disabled_before = deepcopy(await gc.all())
        old_disabled = bot.cog_disabled_in_guild

        async def disabled(cog, guild):
            return True

        bot.cog_disabled_in_guild = disabled
        for form, data in (("project_save", project_data), ("task_save", task_data), ("task_comment", {"tid": "1", "text": "Nein"}),
                           ("task_board_publish", {"channel": "1001"}), ("task_board_refresh", {})):
            _, location = await post(14, form, data)
            assert "deaktiviert" in location and await gc.all() == disabled_before and len(calls) == 1
        bot.cog_disabled_in_guild = old_disabled
        assert await gc.events() == events_before
        # Strukturierte Projekte werden tatsächlich am alten Termin gespeichert; freier Alttext bleibt erhalten.
        response, location = await post(11, "event_save", {"eid": legacy["id"], "revision": str(legacy["revision"]),
            "title": legacy["title"], "project": legacy["project"], "project_id": "1", "start": "2035-06-12T18:00", "end": "2035-06-12T19:00",
            "owner_id": "11", "event_timezone": "Europe/Berlin", "reminder_preset": ""})
        assert "ok=" in location and (await gc.events())["1"]["project_id"] == "1"
        assert (await gc.events())["1"]["project"] == "Altbestand freier Text"
        response, location = await post(14, "project_save", {**project_data, "pid": "1", "revision": "2", "name": "Aktueller Projektname"})
        assert "ok=" in location
        _, text = await page(11)
        agenda = text.split("data-tab='agenda'", 1)[1].split("data-tab='monat'", 1)[0]
        assert "Aktueller Projektname" in agenda and "Altbestand freier Text" not in agenda
        # Gemeinsame Kennzahlen zählen strukturierte Projekte und aktive Aufgaben statt freie Termintexte.
        stats_before = deepcopy(await gc.all())
        stats_conf = deepcopy(stats_before)
        stats_conf["projects"]["1"]["status"] = "archived"
        stats_conf["projects"]["88"] = {**stats_conf["projects"]["1"], "id": "88", "name": "Abgeschlossen", "status": "completed"}
        source = stats_conf["work_tasks"]["1"]
        stats_conf["work_tasks"]["88"] = {**source, "id": "88", "project_id": "88", "status": "todo", "due_ts": 1_000_000_000}
        stats_conf["work_tasks"]["99"] = {**source, "id": "99", "project_id": "", "status": "todo", "due_ts": 1_000_000_000}
        stats_conf["work_tasks"]["77"] = {**source, "id": "77", "project_id": "", "status": "done", "due_ts": 1_000_000_000}
        await gc.set(stats_conf)
        _, text = await page(11)
        for label, expected in (("Projekte", 2), ("Offene Aufgaben", 1), ("Überfällige Aufgaben", 1), ("Anstehende Termine", 1)):
            match = re.search(r"<span>" + re.escape(label) + r"</span>.*?<div class='wc-stat-value'>(\d+)</div>", text, re.S)
            assert match and int(match.group(1)) == expected, (label, match.group(1) if match else None)
        await gc.set(stats_before)
        print("Explizites Publizieren, fremder Server und deaktivierter Cog ohne Seiteneffekte – OK")
    finally:
        cog.post_task_board = old_publish
        await client.close()
        await second.close()
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
