"""Projektverwaltung in Discord: echte Modals/Selects, Teamrechte und Versionsschutz."""
import asyncio
import copy

import discord
import tc_harness as T
from teamcalendar_discord_test import Interaction, button

from rc.teamcalendar.teamcalendar import TeamCalendar
from rc.teamcalendar import task_views as V, views


def fill(modal, **values):
    for name, value in values.items():
        getattr(modal, name + "_field")._value = str(value)
    for field in modal.children:
        if field._value is None:
            field._value = str(field.default or "")


def select(view, token):
    return next(child for child in view.children if isinstance(child, (discord.ui.Select, discord.ui.UserSelect)) and token in child.custom_id)


async def main():
    wc, bot, _, _, _ = await T.make_app()
    guild = bot.guilds[0]
    cog = TeamCalendar(bot)
    bot._cogs["TeamCalendar"] = cog
    gc = cog.config.guild(guild)
    await gc.team_roles.set([1101, 1102])
    now = 2_000_000_000
    cog._now = lambda: now
    a, b = guild.get_member(11), guild.get_member(12)
    sent_before = len(T.L.LOG)

    async def act(uid, cid, values=None):
        interaction = Interaction(guild, guild.get_member(uid), cid, values)
        await views.handle_interaction(cog, interaction)
        return interaction

    async def submit(modal, uid=11):
        inter = Interaction(guild, guild.get_member(uid), kind=discord.InteractionType.modal_submit)
        await modal.on_submit(inter)
        return inter

    async def task(tid, uid=11):
        inter = await act(uid, f"{V.PREFIX}task:{uid}:{tid}")
        assert inter.last.get("embed"), inter.last
        return inter

    async def project(pid, uid=11):
        inter = await act(uid, f"{V.PREFIX}project:{uid}:{pid}")
        assert inter.last.get("embed"), inter.last
        return inter

    try:
        board = views.build_board_view()
        assert board.is_persistent() and len(board.children) == 5
        ids = {child.custom_id for child in board.children}
        assert {"teamcalendar:new", "teamcalendar:list", "teamcalendar:export", "teamcalendar:pm:newtask", "teamcalendar:pm:tasks"} == ids
        assert V.build_task_board_view().is_persistent()
        for uid in (11, 12):
            listing = await act(uid, V.PREFIX + "tasks")
            assert "Noch keine Aufgaben" in listing.last["content"]
        for cid in (V.PREFIX + "tasks", V.PREFIX + "projects", V.PREFIX + "newtask", V.PREFIX + "newproject"):
            denied = await act(13, cid)
            assert "Kalender-Team" in denied.last["content"]
        unknown = await act(11, V.PREFIX + "unknown")
        assert not unknown.messages

        opening = await act(11, V.PREFIX + "newproject")
        modal = opening.response.modal
        fill(modal, name="Server-Ausbau", description="Gemeinsames Projekt", deadline="2033-06-01")
        saved = await submit(modal)
        assert saved.last.get("embed"), saved.last
        pid = next(iter(await gc.projects()))
        opening = await act(12, V.PREFIX + "newtask")
        modal = opening.response.modal
        assert len(modal.children) == 5
        fill(modal, title="Neue Map planen", description="Notizen @everyone", due="2033-05-25", project=pid,
             checklist="[ ] Entwurf\n[x] Team befragen")
        saved = await submit(modal, 12)
        assert saved.last.get("embed"), saved.last
        tid = next(iter(await gc.work_tasks()))
        before_repeat = copy.deepcopy(await gc.work_tasks())
        repeated = await submit(modal, 12)
        assert "bereits abgesendet" in repeated.last["content"] and await gc.work_tasks() == before_repeat
        record = (await gc.work_tasks())[tid]
        assert record["created_by"] == 12 and record["project_id"] == pid
        assert [item["done"] for item in record["checklist"]] == [False, True]
        before_tamper = copy.deepcopy(await gc.all())
        denied = await act(11, f"{V.PREFIX}status:11:{tid}:{record['revision']}", ["delete"])
        assert "Bestätigung" in denied.last["content"] and await gc.all() == before_tamper
        project_rev = (await gc.projects())[pid]["revision"]
        denied = await act(11, f"{V.PREFIX}projectaction:11:{pid}:{project_rev}:delete")
        assert "Bestätigung" in denied.last["content"] and await gc.all() == before_tamper
        detail = await task(tid)
        project_detail = await project(pid, 12)
        paused = await act(12, button(project_detail.last["view"], "Pausieren"))
        assert (await gc.projects())[pid]["status"] == "paused"
        activated = await act(12, button(paused.last["view"], "Aktivieren"))
        assert (await gc.projects())[pid]["status"] == "active"
        incomplete = await act(12, button(activated.last["view"], "Abschließen"))
        assert "offene Aufgaben" in incomplete.last["content"]
        opening = await act(11, button(detail.last["view"], "Bearbeiten"))
        fill(opening.response.modal, title="Von anderem Teammitglied bearbeitet")
        assert (await submit(opening.response.modal)).last.get("embed")
        assert (await gc.work_tasks())[tid]["title"] == "Von anderem Teammitglied bearbeitet"
        assert [item["done"] for item in (await gc.work_tasks())[tid]["checklist"]] == [False, True]
        print("Fünf dauerhafte Board-Einstiege, Projekte/Aufgaben durch beide Teamrollen, fremdes Teammitglied bearbeitet und Checklistenstand bleibt erhalten – OK")

        detail = await task(tid)
        opening = await act(11, button(detail.last["view"], "Zuweisen"))
        picker = select(opening.last["view"], ":assignees:")
        assert isinstance(picker, discord.ui.UserSelect) and picker.max_values == 10 and picker.min_values == 0
        assert (await act(11, picker.custom_id, ["11", "12"])).last.get("embed")
        assert (await gc.work_tasks())[tid]["assignee_ids"] == [11, 12]
        stale = await act(11, picker.custom_id, ["11"])
        assert "geändert" in stale.last["content"]
        detail = await task(tid)
        opening = await act(11, button(detail.last["view"], "Priorität"))
        assert (await act(11, select(opening.last["view"], ":priority:").custom_id, ["urgent"])).last.get("embed")
        assert (await gc.work_tasks())[tid]["priority"] == "urgent"
        detail = await task(tid)
        status = select(detail.last["view"], ":status:")
        await act(11, status.custom_id, ["in_progress"])
        assert (await gc.work_tasks())[tid]["status"] == "in_progress"
        detail = await task(tid)
        checklist = await act(11, button(detail.last["view"], "Checkliste"))
        point = select(checklist.last["view"], ":checktoggle:")
        await act(11, point.custom_id, [point.options[0].value])
        assert (await gc.work_tasks())[tid]["checklist"][0]["done"]
        detail = await task(tid, 12)
        opening = await act(12, button(detail.last["view"], "Kommentar schreiben"))
        opening.response.modal.text._value = "Abstimmung abgeschlossen @everyone"
        assert (await submit(opening.response.modal, 12)).last.get("embed")
        assert (await gc.work_tasks())[tid]["comments"][0]["author_id"] == 12
        comments = await act(11, f"{V.PREFIX}comments:11:{tid}:0")
        assert not any("deletecomment" in child.custom_id for child in comments.last["view"].children)
        comments = await act(12, f"{V.PREFIX}comments:12:{tid}:0")
        remove = await act(12, button(comments.last["view"], "Kommentar 1 löschen"))
        assert len((await gc.work_tasks())[tid]["comments"]) == 1
        await act(12, button(remove.last["view"], "Kommentar endgültig löschen"))
        assert not (await gc.work_tasks())[tid]["comments"]
        print("Namensauswahl bis zehn Zuständige, Versionsschutz, Priorität/Status/Checkliste und nur eigene Kommentare nach Bestätigung löschen – OK")

        # Assigned mode: only assigned members work, full editing/assignment stays
        # with managers. Team members can still read all tasks.
        await gc.task_edit_mode.set("assigned")
        detail = await task(tid)
        labels = [getattr(child, "label", None) for child in detail.last["view"].children]
        assert "Bearbeiten" not in labels and "Zuweisen" not in labels and "Kommentar schreiben" in labels
        rev = (await gc.work_tasks())[tid]["revision"]
        for action in ("edittask", "assign", "priorities", "deletetask"):
            denied = await act(11, f"{V.PREFIX}{action}:11:{tid}:{rev}")
            assert "darfst" in denied.last["content"]
        denied = await act(11, V.PREFIX + "newtask")
        assert "darfst" in denied.last["content"]
        lead = guild.get_member(1)
        await cog.assign_task(guild, lead, tid, [11], revision=rev)
        detail = await task(tid, 12)
        assert not any(":status:" in child.custom_id for child in detail.last["view"].children)
        denied = await act(12, f"{V.PREFIX}status:12:{tid}:{(await gc.work_tasks())[tid]['revision']}", ["done"])
        assert "darfst" in denied.last["content"]
        detail = await task(tid)
        await act(11, select(detail.last["view"], ":status:").custom_id, ["blocked"])
        assert (await gc.work_tasks())[tid]["status"] == "blocked"
        await gc.task_edit_mode.set("team")

        # Stale task modals, revoked roles and a timezone switch cannot overwrite
        # a task or silently shift its due date.
        detail = await task(tid)
        opening = await act(11, button(detail.last["view"], "Bearbeiten"))
        fill(opening.response.modal, title="Veralteter Text")
        record = (await gc.work_tasks())[tid]
        await cog.update_task(guild, b, tid, {"title": "Neuere Bearbeitung"}, revision=record["revision"])
        stale = await submit(opening.response.modal)
        assert "geändert" in stale.last["content"] and (await gc.work_tasks())[tid]["title"] == "Neuere Bearbeitung"
        opening = await act(11, V.PREFIX + "newtask")
        fill(opening.response.modal, title="Darf nicht gespeichert werden", due="2033-05-25", checklist="", project="")
        roles = list(a.roles)
        a.roles = [guild.default_role]
        before = copy.deepcopy(await gc.work_tasks())
        denied = await submit(opening.response.modal)
        assert "Kalender-Team" in denied.last["content"] and await gc.work_tasks() == before
        a.roles = roles
        detail = await task(tid)
        opening = await act(11, button(detail.last["view"], "Bearbeiten"))
        fill(opening.response.modal, title="Zeitzone unverändert prüfen")
        await gc.timezone.set("UTC")
        denied = await submit(opening.response.modal)
        assert "Zeitzone" in denied.last["content"]
        await gc.timezone.set("Europe/Berlin")
        project_open = await act(11, V.PREFIX + "newproject")
        fill(project_open.response.modal, name="Zeitzonenprojekt", deadline="2033-06-01")
        await gc.timezone.set("UTC")
        denied = await submit(project_open.response.modal)
        assert "Zeitzone" in denied.last["content"]
        await gc.timezone.set("Europe/Berlin")
        print("Zugewiesenen-Modus, aktuelle Rollen, fremde Formulare, veraltete Bearbeitung und Zeitzonen-Schutz für Aufgaben/Projekte – OK")

        opening = await act(11, V.PREFIX + "newtask")
        fill(opening.response.modal, title="Fremdes Formular", due="", project="", checklist="")
        before = copy.deepcopy(await gc.work_tasks())
        denied = await submit(opening.response.modal, 12)
        assert "anderen Person" in denied.last["content"] and await gc.work_tasks() == before
        foreign = Interaction(bot.guilds[1], bot.guilds[1].get_member(11), kind=discord.InteractionType.modal_submit)
        await opening.response.modal.on_submit(foreign)
        assert "anderen Server" in foreign.last["content"] and await gc.work_tasks() == before
        original_disabled = bot.cog_disabled_in_guild
        async def disabled(*args):
            return True
        bot.cog_disabled_in_guild = disabled
        try:
            for cid in (V.PREFIX + "tasks", V.PREFIX + "projects", V.PREFIX + "newtask", V.PREFIX + "newproject"):
                denied = await act(11, cid)
                assert "deaktiviert" in denied.last["content"]
            denied = await submit(opening.response.modal)
            assert "deaktiviert" in denied.last["content"] and await gc.work_tasks() == before
        finally:
            bot.cog_disabled_in_guild = original_disabled

        # Existing valid checklists may exceed Discord's 4000-char textarea limit.
        # Editing another field must preserve every item, not save a clipped list.
        record = (await gc.work_tasks())[tid]
        await cog.update_task(guild, a, tid, {"checklist": "\n".join("[x] " + str(i) + "x" * 195 for i in range(25))}, revision=record["revision"])
        before_checklist = copy.deepcopy((await gc.work_tasks())[tid]["checklist"])
        detail = await task(tid)
        opening = await act(11, button(detail.last["view"], "Bearbeiten"))
        assert opening.response.modal.large_checklist
        fill(opening.response.modal, title="Lange Checkliste behalten")
        assert (await submit(opening.response.modal)).last.get("embed")
        assert (await gc.work_tasks())[tid]["checklist"] == before_checklist
        detail = await task(tid)
        opening = await act(11, button(detail.last["view"], "Bearbeiten"))
        fill(opening.response.modal, checklist="Unvollständiger Ersatz")
        denied = await submit(opening.response.modal)
        assert "zu lang" in denied.last["content"] and (await gc.work_tasks())[tid]["checklist"] == before_checklist

        # Paging also keeps entries beyond Discord's 25-option ceiling reachable.
        base = (await gc.work_tasks())[tid]
        many = {str(i): {**copy.deepcopy(base), "id": str(i), "title": "Aufgabe " + "x" * 100} for i in range(100, 161)}
        await gc.work_tasks.set(many)
        first = await act(11, V.PREFIX + "tasks")
        second = await act(11, button(first.last["view"], "Weiter"))
        third = await act(11, button(second.last["view"], "Weiter"))
        all_ids = {option.value for inter in (first, second, third) for option in select(inter.last["view"], ":taskselect:").options}
        assert all_ids == set(many) and len(select(third.last["view"], ":taskselect:").options) == 11
        mine = await act(12, f"{V.PREFIX}tasks:12:mine:0")
        assert "Noch keine Aufgaben" in mine.last["content"]
        await gc.work_tasks.set({tid: base})

        detail = await task(tid)
        remove = await act(11, button(detail.last["view"], "Löschen"))
        assert tid in await gc.work_tasks()
        confirm = button(remove.last["view"], "Endgültig löschen")
        other = await act(12, confirm)
        assert "andere" in other.last["content"]
        expired = await act(11, confirm.rsplit(":", 1)[0] + f":{now - 1}")
        assert "abgelaufen" in expired.last["content"]
        await act(11, confirm)
        assert tid not in await gc.work_tasks()
        detail = await project(pid)
        remove = await act(11, button(detail.last["view"], "Löschen"))
        assert pid in await gc.projects()
        await act(11, button(remove.last["view"], "Endgültig löschen"))
        assert pid not in await gc.projects()
        assert len(T.L.LOG) == sent_before and not T.ROLE_LOG
        print("Lange Checklisten ohne Datenverlust, 61 Aufgaben erreichbar, eigene Aufgabenfilter und explizites nutzer-/zeitgebundenes Löschen – OK")
        print("project_management_discord_test: PASS")
    finally:
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
