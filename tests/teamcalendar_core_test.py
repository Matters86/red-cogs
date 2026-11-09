"""Projektkalender: jedes Teammitglied verwaltet alle Termine; sichere Persistenz und Fehlerfälle."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import discord
import tc_harness as T
from rc.teamcalendar.teamcalendar import TeamCalendar
from rc.teamcalendar.models import CalendarError


async def rejects(call):
    try:
        await call
    except CalendarError:
        return
    raise AssertionError("Kalenderaktion muss abgelehnt werden")


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
    guild = bot.guilds[0]
    admin, lena, tom, mia, guest = (guild.get_member(uid) for uid in (1, 11, 12, 14, 15))
    conf = cog.config.guild(guild)
    clock = [int(datetime(2026, 11, 9, 12, tzinfo=timezone.utc).timestamp())]
    cog._now = lambda: clock[0]

    async def board_view():
        return discord.ui.View(timeout=None)
    cog._board_view = board_view  # Native Komponenten haben eine eigene Integrationstest-Suite.

    def values(title="Projektbesprechung", start=None, **extra):
        stamp = clock[0] + 3600 if start is None else start
        return {"title": title, "description": "Abstimmung im Team", "project": "Gemeinsames Projekt",
                "location": "Discord", "start": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(stamp + 3600, timezone.utc).isoformat(), **extra}

    assert not cog.can_manage(lena, await conf.all())
    await rejects(cog.create_event(guild, lena, values()))
    await cog.save_settings(guild, admin, {"team_roles": [1101, 1102], "manager_roles": [1103], "team_can_manage": True})
    assert cog.can_view(tom, await conf.all()) and cog.can_manage(lena, await conf.all())
    assert cog.can_configure(mia, await conf.all()) and not cog.can_configure(tom, await conf.all())
    await rejects(cog.save_settings(guild, tom, {"manager_roles": [1102]}))
    await rejects(cog.save_settings(guild, admin, {"team_roles": [2101]}))
    await rejects(cog.save_settings(guild, admin, {"calendar_channel": 2001}))
    await rejects(cog.save_settings(guild, admin, {"timezone": "unbekannt/zone"}))

    first = await cog.create_event(guild, lena, values())
    preview_conf = await conf.all()
    preview_conf["events"] = {str(index): {**first, "id": str(index), "title": "*" * 100, "project": "_" * 80}
                              for index in range(1, 17)}
    preview = cog._board_embed(guild, preview_conf)
    assert len(preview.description) <= 4096 and preview.description.count("`#") == 15 and "Weitere 1" in preview.description
    changed = await cog.update_event(guild, tom, first["id"], values("Tom bearbeitet Lenas Termin"), revision=1)
    assert changed["created_by"] == lena.id and changed["updated_by"] == tom.id and changed["revision"] == 2
    await rejects(cog.update_event(guild, lena, first["id"], values(), revision=1))
    await rejects(cog.create_event(guild, guest, values()))
    await rejects(cog.set_rsvp(guild, guest, first["id"], "yes"))
    await cog.set_rsvp(guild, lena, first["id"], "yes")
    await cog.set_rsvp(guild, tom, first["id"], "maybe")
    rec = await cog.set_rsvp(guild, tom, first["id"], "remove")
    assert rec["participants"] == {str(lena.id): "yes"} and rec["revision"] == 2
    await cog.event_action(guild, tom, first["id"], "cancel", revision=2)
    await rejects(cog.set_rsvp(guild, lena, first["id"], "yes"))
    rec = await cog.event_action(guild, lena, first["id"], "reopen")
    assert rec["status"] == "scheduled"
    results = await asyncio.gather(
        cog.update_event(guild, lena, first["id"], values("A"), rec["revision"]),
        cog.update_event(guild, tom, first["id"], values("B"), rec["revision"]), return_exceptions=True)
    assert sum(isinstance(value, CalendarError) for value in results) == 1
    assert sum(isinstance(value, dict) for value in results) == 1

    # Ausstehende Aktion nutzt nach dem Lock die aktuelle Mitgliedschaft.
    await cog._lock(guild).acquire()
    pending = asyncio.create_task(cog.create_event(guild, lena, values("Nicht mehr berechtigt")))
    await asyncio.sleep(0)
    original = lena.roles
    lena.roles = [guild.default_role]
    cog._lock(guild).release()
    await rejects(pending)
    lena.roles = original
    await cog.save_settings(guild, admin, {"team_can_manage": False})
    assert cog.can_view(tom, await conf.all()) and not cog.can_manage(tom, await conf.all())
    await rejects(cog.event_action(guild, tom, first["id"], "delete"))
    await cog.set_rsvp(guild, tom, first["id"], "yes")
    await cog.save_settings(guild, admin, {"team_can_manage": True})
    ctx = Ctx(guild, tom)
    await cog.calendar_details.callback(cog, ctx, first["id"])
    assert ctx.sent[-1][1]["ephemeral"] and ctx.sent[-1][1]["view"].children
    await cog.calendar_rsvp.callback(cog, ctx, first["id"], "ja")
    assert ctx.deferred and ctx.sent[-1][1]["ephemeral"]

    # Übersicht: Fehler nach erfolgreichem Speichern verlieren keinen Termin.
    channel = guild.get_channel(1002)
    await cog.post_board(guild, admin, channel)
    board_id = await conf.board_message_id()
    assert board_id in channel._messages
    await cog.post_board(guild, tom)
    assert await conf.board_message_id() == board_id
    await rejects(cog.post_board(guild, tom, guild.get_channel(1001)))
    await rejects(cog.refresh_board(guild, actor=guest))
    await cog._lock(guild).acquire()
    refresh_pending = asyncio.create_task(cog.refresh_board(guild, actor=tom))
    await asyncio.sleep(0)
    saved_roles = tom.roles
    tom.roles = [guild.default_role]
    cog._lock(guild).release()
    await rejects(refresh_pending)
    tom.roles = saved_roles
    await channel._messages[board_id].delete()
    enabled_check = bot.cog_disabled_in_guild
    async def disabled(cog, guild):
        return True
    bot.cog_disabled_in_guild = disabled
    await cog.refresh_board(guild, actor=tom)
    await rejects(cog.create_event(guild, tom, values()))
    assert await conf.board_message_id() == board_id and board_id not in channel._messages
    bot.cog_disabled_in_guild = enabled_check
    cog._unloading = True
    await cog.refresh_board(guild)
    assert await conf.board_message_id() == board_id and board_id not in channel._messages
    cog._unloading = False
    await cog.refresh_board(guild)
    assert await conf.board_message_id() != board_id
    channel.forbid.add("history")
    saved = await cog.create_event(guild, tom, values("Trotz Discord-Fehler gespeichert"))
    assert saved["id"] in await conf.events() and await conf.board_error()
    broken_id = await conf.board_message_id()
    channel.forbid.remove("history")
    await cog.refresh_board(guild)
    assert await conf.board_message_id() == broken_id and not await conf.board_error()
    await conf.calendar_channel.set(9999999)
    await cog.refresh_board(guild)
    assert await conf.board_message_id() == broken_id and await conf.board_error()
    await conf.calendar_channel.set(channel.id)
    await cog.refresh_board(guild)

    # Neustart und Datenschutz erhalten Marker, keine fremden Teilnahmen werden entfernt.
    async with conf.events() as events:
        for event in events.values():
            event["reminder_minutes"] = []
    reminder = await cog.create_event(guild, lena, values("Einmal erinnern", reminder_minutes=[60]))
    await cog.set_rsvp(guild, lena, reminder["id"], "yes")
    await cog.set_rsvp(guild, tom, reminder["id"], "no")
    calls = []
    send = channel.send

    async def tracked_send(*args, **kwargs):
        calls.append(kwargs)
        return await send(*args, **kwargs)
    channel.send = tracked_send
    await cog._tick_once()
    assert len(calls) == 1 and calls[0]["allowed_mentions"].everyone is False
    await cog.update_event(guild, tom, reminder["id"], values("Titel geändert", reminder_minutes=[60]), revision=1)
    await cog.event_action(guild, lena, reminder["id"], "cancel")
    await cog.event_action(guild, tom, reminder["id"], "reopen")
    restarted = TeamCalendar(bot)
    restarted._now = cog._now
    restarted._board_view = board_view
    await restarted._tick_once()
    assert len(calls) == 1
    restarted._ux_drafts = {("session", 1000, f"teamcalendar:{lena.id}:edit"): {"secret": "draft"},
                             ("session", 1000, f"teamcalendar:{tom.id}:edit"): {"secret": "other"}}
    await restarted.red_delete_data_for_user(requester="discord_deleted_user", user_id=lena.id)
    assert len(restarted._ux_drafts) == 1 and str(tom.id) in next(iter(restarted._ux_drafts))[2]
    record = (await conf.events())[reminder["id"]]
    assert str(lena.id) not in record["participants"] and record["participants"][str(tom.id)] == "no"
    assert record["created_by"] == 0 and record["owner_id"] == 0
    assert record["reminders_sent"]

    # Bekannter Sendefehler wird begrenzt erneut versucht; unklarer Abbruch nie doppelt.
    retry = await cog.create_event(guild, tom, values("Retry", reminder_minutes=[60]))
    channel.forbid.add("send")
    await cog._tick_once()
    reminder_key = f"{retry['start_ts']}:60"
    marker = (await conf.events())[retry["id"]]["reminders_sent"][reminder_key]
    assert marker["state"] == "failed" and marker["attempts"] == 1
    clock[0] += 61
    channel.forbid.remove("send")
    await cog._tick_once()
    assert (await conf.events())[retry["id"]]["reminders_sent"][reminder_key]["state"] == "sent"
    uncertain = await cog.create_event(guild, tom, values("Abbruch", reminder_minutes=[60]))
    entered = asyncio.Event()
    async def cancelled_send(*args, **kwargs):
        entered.set()
        await asyncio.Future()
    channel.send = cancelled_send
    task = asyncio.create_task(cog._tick_once())
    await entered.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert (await conf.events())[uncertain["id"]]["reminders_sent"][f"{uncertain['start_ts']}:60"]["state"] == "reserved"
    channel.send = tracked_send
    before = len(calls)
    await restarted._tick_once()
    assert len(calls) == before
    server_error = await cog.create_event(guild, tom, values("Unklare Serverantwort", reminder_minutes=[60]))
    async def uncertain_error(*args, **kwargs):
        raise discord.HTTPException(SimpleNamespace(status=503, reason="Unavailable"), "Unklar")
    channel.send = uncertain_error
    await cog._tick_once()
    assert (await conf.events())[server_error["id"]]["reminders_sent"][f"{server_error['start_ts']}:60"]["state"] == "reserved"
    channel.send = tracked_send
    before = len(calls)
    await restarted._tick_once()
    assert len(calls) == before
    late = await cog.create_event(guild, tom, values("Zu spät", reminder_minutes=[60]))
    clock[0] += 3601
    before = len(calls)
    await cog._tick_once()
    assert len(calls) == before and not (await conf.events())[late["id"]]["reminders_sent"]

    # Nur ausdrücklich erledigte/abgesagte alte Einträge verfallen.
    async with conf.events() as events:
        for ident, status in (("old-done", "completed"), ("old-cancelled", "cancelled"), ("old-open", "scheduled")):
            events[ident] = {**first, "id": ident, "status": status, "start_ts": clock[0] - 200 * 86400,
                             "end_ts": clock[0] - 199 * 86400}
    await cog._tick_once()
    remaining = await conf.events()
    assert "old-done" not in remaining and "old-cancelled" not in remaining and "old-open" in remaining
    await cog.event_action(guild, lena, first["id"], "delete")
    assert first["id"] not in await conf.events()

    # Datenschutz über mehrere Server, ohne andere Nutzeridentitäten zu überschreiben.
    other = bot.guilds[1]
    await cog.config.guild(other).events.set({"1": {**first, "owner_id": tom.id, "created_by": lena.id,
        "updated_by": tom.id, "participants": {str(lena.id): "yes", str(tom.id): "maybe"}}})
    await cog.red_delete_data_for_user(requester="owner", user_id=lena.id)
    record = (await cog.config.guild(other).events())["1"]
    assert record["owner_id"] == tom.id and record["updated_by"] == tom.id and record["created_by"] == 0
    assert record["participants"] == {str(tom.id): "maybe"}
    assert cog.can_configure(SimpleNamespace(id=1), await conf.all())
    async def ready():
        return None
    bot.wait_until_ready = ready
    await cog.cog_load()
    loop = cog._tick.get_task()
    await asyncio.sleep(0)
    assert loop is not None and not loop.done() and wc.pages["teamcalendar"].owner is cog
    await cog.cog_unload()
    try:
        await loop
    except asyncio.CancelledError:
        pass
    assert loop.done() and "teamcalendar" not in wc.pages
    print("teamcalendar_core_test: PASS – gemeinsame Termine, Rollen, Rennen, Board, Erinnerungen, Datenschutz")


asyncio.run(main())
