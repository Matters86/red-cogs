"""Ticket-Arbeitsablauf: Wartestatus, eigene Tickets und 1h-Erinnerung ohne verfrühtes Schließen."""
import asyncio
import importlib
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import tc_harness as T
import discord
from aiohttp.test_utils import TestClient, TestServer

from rc.tickets.tickets import Tickets
from rc.tickets.views import CID_KEEP_OPEN, CID_CLOSE, CID_WAIT_USER, CID_WAIT_TEAM

UTC = timezone.utc
DAY = timedelta(hours=24)


async def main():
    wc, bot, app, cog, _ = await T.make_app()
    guild = bot.guilds[0]
    owner, staff, other_staff = (guild.get_member(i) for i in (13, 11, 14))
    gc = cog.config.guild(guild)
    await gc.category_open.set(guild.categories[0].id)
    await gc.support_roles.set([1101])
    await gc.max_open.set(20)
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "operate"}, "1102": {"tickets": "view"}}})
    current = [datetime(2026, 11, 6, 12, tzinfo=UTC)]
    module = importlib.import_module("rc.tickets.tickets")
    original_datetime = module.datetime

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz) if tz is not None else current[0].replace(tzinfo=None)

    module.datetime = Clock
    histories = {}

    async def new_ticket():
        await gc.panels.set([{"id": "workflow", "title": "Support"}])
        result = await cog.open_ticket(guild, owner, {"id": "workflow", "title": "Support"}, None, {})
        assert result.status == "ok"
        channel = result.target
        histories[channel.id] = []
        original_history = channel.history

        async def history(*, after=None, limit=None, oldest_first=False, **kw):
            if after is None:
                async for item in original_history(limit=limit, oldest_first=oldest_first, **kw):
                    yield item
            else:
                for item in sorted(histories[channel.id], key=lambda item: item.created_at, reverse=True):
                    if item.created_at > after:
                        yield item

        channel.history = history
        return channel

    async def record(channel):
        return await cog._get_record(guild, channel.id)

    def message(channel, author, stamp=None, *, webhook_id=None, kind=discord.MessageType.default):
        return SimpleNamespace(guild=guild, channel=channel, author=author, created_at=stamp or current[0],
                               webhook_id=webhook_id, type=kind)

    async def say(channel, author, stamp=None, **kw):
        msg = message(channel, author, stamp, **kw)
        histories[channel.id].append(msg)
        await cog.on_message(msg)

    def reminders(channel):
        return [msg for msg in channel._messages.values() if "bei weiterer Inaktivität" in msg.content]

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        channel = await new_ticket()
        assert (await record(channel))["waiting_for"] == "team"
        await say(channel, staff)
        assert (await record(channel))["waiting_for"] == "user"
        current[0] += timedelta(minutes=1)
        await say(channel, owner)
        assert (await record(channel))["waiting_for"] == "team"
        await say(channel, staff, current[0] - timedelta(hours=1))
        assert (await record(channel))["waiting_for"] == "team", "Verspätete Nachrichten dürfen Status nicht zurückdrehen"
        for author, kw in ((SimpleNamespace(id=999, bot=True), {}), (staff, {"webhook_id": 44}),
                           (staff, {"kind": discord.MessageType.pins_add})):
            await cog.on_message(message(channel, author, **kw))
        assert (await record(channel))["waiting_for"] == "team"
        responses = []
        await cog.on_interaction(T.Inter(responses, guild, owner, channel, CID_WAIT_USER))
        assert (await record(channel))["waiting_for"] == "team"
        await cog.on_interaction(T.Inter(responses, guild, staff, channel, CID_WAIT_USER))
        assert (await record(channel))["waiting_for"] == "user"
        await cog.on_interaction(T.Inter(responses, guild, staff, channel, CID_WAIT_TEAM))
        assert (await record(channel))["waiting_for"] == "team"
        await cog._refresh_controls(guild, channel, None, "de")
        opening = await channel.fetch_message((await record(channel))["message_id"])
        assert "Wartet auf Team" in opening.embeds[0].footer.text
        print("Ticket-Wartestatus: Nutzer/Team, alte Events, Bots/System, Buttons und Rechte – OK")

        assigned_other, unassigned = await new_ticket(), await new_ticket()
        assert await cog._assign_ticket(guild, channel, staff, staff) is None
        assert await cog._assign_ticket(guild, assigned_other, other_staff, staff) is None
        for view, shown, hidden in (("mine", [channel], [assigned_other, unassigned]),
                                    ("unassigned", [unassigned], [channel, assigned_other])):
            response = await client.get("/cogs/tickets", params={"guild": "1000", "view": view}, headers={"X-Test-User": "11"})
            html = await response.text()
            assert response.status == 200
            table = re.search(r"<table[^>]*id=['\"]tk-open['\"][^>]*>(.*?)</table>", html, re.S).group(1)
            for item in shown:
                assert f"value='{item.id}'" in table
            for item in hidden:
                assert f"value='{item.id}'" not in table
        response = await client.get("/cogs/tickets?guild=1000", headers={"X-Test-User": "12"})
        html = await response.text()
        token = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
        response = await client.post("/cogs/tickets", headers={"X-Test-User": "12"}, allow_redirects=False,
                                     data={"csrf_token": token, "guild": "1000", "form": "ticket_waiting",
                                           "channel_id": str(channel.id), "waiting": "user"})
        assert response.status in (302, 303, 403) and (await record(channel))["waiting_for"] == "team"
        print("Ticket-Übersicht: Meine Tickets/Nicht zugewiesen filtern, Ansehen verändert keinen Wartestatus – OK")

        reminder_channel = await new_ticket()
        started = current[0]
        await cog._set_ticket_autoclose(guild, reminder_channel, True, staff, await gc.all())
        deadline = datetime.fromisoformat((await record(reminder_channel))["auto_close_at"])
        assert deadline == started + DAY
        current[0] = deadline - timedelta(minutes=55)
        await cog._check_autoclose()
        assert len(reminders(reminder_channel)) == 1
        notice = reminders(reminder_channel)[0]
        assert {button.custom_id for button in notice.view.children} == {CID_KEEP_OPEN, CID_CLOSE}
        assert (await record(reminder_channel))["auto_close_reminded_for"] == deadline.isoformat()
        await cog._check_autoclose()
        restarted = Tickets(bot)
        await restarted._check_autoclose()
        assert len(reminders(reminder_channel)) == 1, "Auch nach Neustart nur eine Erinnerung je unveränderter Frist"
        current[0] += timedelta(minutes=1)
        await say(reminder_channel, owner)
        extended = datetime.fromisoformat((await record(reminder_channel))["auto_close_at"])
        assert extended == current[0] + DAY and not (await record(reminder_channel)).get("auto_close_reminded_for")
        await cog._check_autoclose()
        assert len(reminders(reminder_channel)) == 1
        current[0] = extended - timedelta(minutes=50)
        await cog._check_autoclose()
        assert len(reminders(reminder_channel)) == 2
        responses = []
        await cog.on_interaction(T.Inter(responses, guild, owner, reminder_channel, CID_KEEP_OPEN))
        assert not (await record(reminder_channel))["auto_close_at"]
        current[0] += 2 * DAY
        await cog._check_autoclose()
        assert len(reminders(reminder_channel)) == 2 and (await record(reminder_channel))["status"] == "open"
        print("Ticket-Erinnerung: einmal je Frist, neue Nachricht verlängert, neuer Timer erinnert neu, Abbruch hält offen – OK")

        offline = await new_ticket()
        await cog._set_ticket_autoclose(guild, offline, True, staff, await gc.all())
        old_deadline = datetime.fromisoformat((await record(offline))["auto_close_at"])
        current[0] = old_deadline - timedelta(minutes=40)
        offline_msg = message(offline, owner, current[0] - timedelta(minutes=5))
        histories[offline.id].append(offline_msg)  # Bot war offline: kein on_message.
        restarted = Tickets(bot)
        await restarted._check_autoclose()
        assert not reminders(offline)
        assert datetime.fromisoformat((await record(offline))["auto_close_at"]) == offline_msg.created_at + DAY
        current[0] = old_deadline + timedelta(minutes=1)
        await restarted._check_autoclose()
        assert (await record(offline))["status"] == "open"

        unreadable = await new_ticket()
        await cog._set_ticket_autoclose(guild, unreadable, True, staff, await gc.all())
        current[0] = datetime.fromisoformat((await record(unreadable))["auto_close_at"]) - timedelta(minutes=35)

        async def bad_history(**kw):
            raise T.L.forbidden()
            yield  # noqa: unreachable – Discord liefert einen asynchronen Iterator.

        unreadable.history = bad_history
        await restarted._check_autoclose()
        assert not reminders(unreadable) and (await record(unreadable))["status"] == "open"
        assert not (await record(unreadable)).get("auto_close_reminded_for")
        print("Ticket-Downtime: Offline-Antwort verschiebt Erinnerung/Schließen; ohne lesbaren Verlauf kein falscher Hinweis – OK")
    finally:
        module.datetime = original_datetime
        await client.close()
    print("ALLE TICKET-WORKFLOW-TESTS OK")


asyncio.run(main())
