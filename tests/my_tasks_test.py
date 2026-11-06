"""Echte persönliche Aufgabenübersicht: Rechte pro Quelle, Termine, Störungen und sichere Links."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import tc_harness as T
from aiohttp.test_utils import TestClient, TestServer

from rc.raidhelper.raidhelper import RaidHelper
from rc.scheduler.scheduler import Scheduler
from rc.organigram.organigram import Organigram
from rc.sticky.sticky import Sticky
from rc.poll.poll import Poll
from rc.guard.guard import Guard
from rc.autoroom.autoroom import AutoRoom


async def main():
    wc, bot, app, tickets, _ = await T.make_app()
    guild = bot.guilds[0]
    cogs = {}
    for cls in (RaidHelper, Scheduler, Organigram, Sticky, Poll, Guard, AutoRoom):
        cog = cls(bot)
        bot._cogs[cog.qualified_name] = cog
        cog._register_dashboard(wc)
        cogs[cog.qualified_name] = cog
    raid, schedule, organigram = (cogs[name] for name in ("RaidHelper", "Scheduler", "Organigram"))
    sticky, poll, guard, rooms = (cogs[name] for name in ("Sticky", "Poll", "Guard", "AutoRoom"))
    now = datetime.now(timezone.utc)
    await tickets.config.guild(guild).tickets.set({
        "101": {"num": 901, "status": "open", "claimed_by": 11, "waiting_for": "team", "priority": "urgent"},
        "102": {"num": 902, "status": "open", "claimed_by": 12},
        "103": {"num": 903, "status": "closed", "claimed_by": 11},
    })
    original_due = getattr(tickets, "support_due", None)
    tickets.support_due = lambda record, conf, now=None: now - timedelta(minutes=10)
    await raid.config.guild(guild).events.set({
        "own": {"title": "Mein Leitungsraid", "leader_id": 11, "start_ts": (now + timedelta(hours=2)).timestamp(), "message_id": 44},
        "signup": {"title": "Meine Anmeldung", "leader_id": 1, "start_ts": (now + timedelta(days=2)).timestamp(),
                   "message_id": 45, "signups": {"11": {"status": "signed"}}},
        "absent": {"title": "Abgesagter Termin", "leader_id": 1, "start_ts": (now + timedelta(hours=2)).timestamp(),
                   "signups": {"11": {"status": "absent"}}},
        "other": {"title": "Anderer persönlicher Raid", "leader_id": 12, "start_ts": (now + timedelta(hours=3)).timestamp()},
        "old": {"title": "Alt erledigt", "leader_id": 11, "completed": True, "start_ts": now.timestamp()},
    })
    await schedule.config.guild(guild).entries.set({
        "1": {"name": "Meine Nachricht", "creator_id": 11, "next_run_ts": (now + timedelta(days=1)).timestamp()},
        "2": {"name": "Fremde Nachricht", "creator_id": 12, "next_run_ts": now.timestamp()},
        "3": {"name": "Pausiert", "creator_id": 11, "paused": True, "next_run_ts": now.timestamp()},
        "4": {"name": "<script>nicht ausführen</script>", "creator_id": 11, "auto_paused": True, "last_error": "private diagnostic"},
    })
    await organigram.config.guild(guild).charts.set({
        "team": {"name": "Organigramm reparieren", "posts": [{"channel_id": 1001, "last_error": "hidden secret diagnostic"}]},
    })
    await sticky.config.guild(guild).stickies.set({"1001": {"enabled": True, "delivery_error": "private trace"}})
    await poll.config.guild(guild).polls.set({"private": {"question": "Verborgene Umfrage", "channel_id": 1001, "message_id": None}})
    await guard.config.guild(guild).lockdown_recovering.set(True)
    await rooms.config.guild(guild).active_rooms.set({"999": {"cleanup_error": "private room failure"}})
    await wc.config.role_perms.set({"1000": {
        "1101": {"tickets": "view", "raidhelper": "view", "scheduler": "view", "organigram": "operate",
                 "sticky": "operate", "poll": "view", "guard": "operate", "autoroom": "view"},
        "1102": {"poll": "operate"},
    }})
    snapshots = {name: json.dumps(await cog.config.guild(guild).all(), sort_keys=True)
                 for name, cog in (("tickets", tickets), *cogs.items())}
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async def get(uid, suffix=""):
            response = await client.get("/tasks?guild=1000" + suffix, headers={"X-Test-User": str(uid)})
            return response, await response.text()

        response, html = await get(11)
        assert response.status == 200, html
        for expected in ("Ticket #901", "Mein Leitungsraid", "Meine Anmeldung", "Meine Nachricht",
                         "Organigramm reparieren", "Notmodus: Wiederherstellung", "Fällig", "Dringend", "data-wc-localtime"):
            assert expected in html, expected
        for hidden in ("Ticket #902", "Ticket #903", "Abgesagter Termin", "Anderer persönlicher Raid",
                       "Fremde Nachricht", "Verborgene Umfrage", "Raumbereinigung ausstehend", "private diagnostic", "private trace"):
            assert hidden not in html, hidden
        assert "&lt;script&gt;nicht ausführen&lt;/script&gt;" in html
        assert "<script>nicht ausführen</script>" not in html
        assert response.headers.get("Cache-Control") == "no-store"
        _, filtered = await get(11, "&kind=tickets")
        assert "Ticket #901" in filtered and "Mein Leitungsraid" not in filtered
        _, overdue = await get(11, "&kind=due")
        assert "Ticket #901" in overdue and "Meine Nachricht" not in overdue
        _, other_user = await get(12)
        assert "Verborgene Umfrage" in other_user and "Ticket #901" not in other_user
        assert "Meine Nachricht" not in other_user and "Organigramm reparieren" not in other_user
        for uid in (13, 99):
            response, html = await get(uid)
            assert response.status in (302, 303, 403) or "Kein Zugriff" in html
            assert "Ticket #901" not in html and "Verborgene Umfrage" not in html
        for raw in ("2000", "nonsense"):
            response = await client.get("/tasks?guild=" + raw, headers={"X-Test-User": "11"})
            assert response.status == 403
        response = await client.post("/tasks?guild=1000", headers={"X-Test-User": "11"}, data={"action": "delete"})
        assert response.status == 405
        print("Aufgaben: persönlich, pro Modul/Server geschützt, Filter, fällige Termine, sichere Ausgabe – OK")

        # Nicht berechtigte Quellen werden überhaupt nicht gelesen.
        original_poll_conf = poll.config
        reads = []
        async def broken():
            reads.append(True)
            raise RuntimeError("hidden diagnostic data")
        poll.config = SimpleNamespace(guild=lambda ignored: SimpleNamespace(all=broken))
        response, html = await get(11)
        assert response.status == 200 and not reads
        response, html = await get(12)
        assert response.status == 200 and reads and "Nicht alle Aufgabenquellen" in html
        assert "hidden diagnostic data" not in html
        poll.config = original_poll_conf
        original_disabled = bot.cog_disabled_in_guild
        async def disabled(cog, current_guild):
            return cog is sticky
        bot.cog_disabled_in_guild = disabled
        _, html = await get(11)
        assert "Sticky #" not in html and "Ticket #901" in html
        bot.cog_disabled_in_guild = original_disabled
        for name, cog in (("tickets", tickets), *cogs.items()):
            assert json.dumps(await cog.config.guild(guild).all(), sort_keys=True) == snapshots[name]
        assert not [entry for entry in T.L.LOG if entry[0] in ("send", "channel_delete")]
        print("Quellenausfall isoliert, entladene/gesperrte Quellen verborgen, GET ohne Discord-/Config-Schreibzugriff – OK")
    finally:
        if original_due is None:
            del tickets.support_due
        else:
            tickets.support_due = original_due
        await client.close()
        await wc.cog_unload()
    print("ALLE MEINE-AUFGABEN-TESTS OK")


if __name__ == "__main__":
    asyncio.run(main())
