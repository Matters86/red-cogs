"""Harness Geplante Nachrichten (scheduler): echter WebCore + Scheduler-Cog mit Fake-Discord.

Basis: live_harness (echte Kanal-Unterklassen, Discord-Limits) + wcm_harness (Nutzer). Ergänzt NUR zur Laufzeit:
* jede Kanal-Nachricht mit ``allowed_mentions`` -> ``SENT``
* ``chan.fail_next = n`` -> die nächsten n Sendeversuche scheitern mit 403

Start (Browser):  python tests/sc_harness.py [port]   – mit Beispieldaten, Login per X-Test-User
"""
import time
import live_harness as L
import wcm_harness as M
import wc_harness as H

SENT = []   # {"channel", "content", "embed", "allowed_mentions", "message"}

_orig_send = L._SendMixin.send


async def _send(self, content=None, **kw):
    if getattr(self, "fail_next", 0):
        self.fail_next -= 1
        raise L.forbidden()
    msg = await _orig_send(self, content, **kw)
    SENT.append({"channel": self.id, "content": content, "embed": kw.get("embed"),
                 "allowed_mentions": kw.get("allowed_mentions"), "message": msg})
    return msg


L._SendMixin.send = _send


async def make_app(loop=False):
    wc, bot, app = await M.make_app()
    from rc.scheduler.scheduler import Scheduler
    cog = Scheduler(bot)
    bot._cogs["Scheduler"] = cog
    await cog.cog_load()
    if not loop:
        cog._tick.cancel()          # Tests rufen process_due() gezielt mit eigener Zeit auf
    return wc, bot, app, cog


async def seed(bot, cog):
    g1 = bot.guilds[0]
    add = cog.add_entry
    e1, _ = await add(g1, {"name": "Morgengruß", "channel_id": 1001, "content": "Guten Morgen zusammen! ☀️",
                           "schedule": {"type": "daily", "time": "09:00"}}, creator_id=1)
    e2, _ = await add(g1, {"name": "Raid-Erinnerung", "channel_id": 1003, "content": "Heute Abend Raid – bitte anmelden!",
                           "ping_role_id": 1103, "embed": {"title": "Raid heute 20:00", "description": "Treffpunkt: Dornogal",
                                                           "color": "#f5b94a", "image_url": ""},
                           "schedule": {"type": "weekly", "time": "18:00", "weekdays": [2, 4]},
                           "delete_previous": True}, creator_id=1)
    e3, _ = await add(g1, {"name": "Monatsabschluss", "channel_id": 1004, "content": "Monatsbericht fällig.",
                           "schedule": {"type": "monthly", "time": "12:00", "day": 31}}, creator_id=1)
    e4, _ = await add(g1, {"name": "Wasser trinken", "channel_id": 1001, "content": "Denkt ans Trinken 💧",
                           "schedule": {"type": "interval", "minutes": 120}}, creator_id=1)
    e5, _ = await add(g1, {"name": "Server-Geburtstag", "channel_id": 1003, "content": "",
                           "embed": {"title": "🎂 3 Jahre Matters Community!", "description": "Danke an alle!",
                                     "color": "#ff6b6b", "image_url": "https://example.com/torte.png"},
                           "schedule": {"type": "once", "date": time.strftime("%Y-12-24"), "time": "18:00"}},
                      creator_id=1)
    async with cog.config.guild(g1).entries() as entries:
        entries[e3["id"]].update(paused=True, auto_paused=True, fail_count=5,
                                 last_error="Keine Rechte zum Senden im Kanal")
    return {"e1": e1["id"], "e2": e2["id"], "e3": e3["id"], "e4": e4["id"], "e5": e5 and e5["id"]}


async def make_demo():
    wc, bot, app, cog = await make_app(loop=True)
    await seed(bot, cog)
    return wc, bot, app, cog


if __name__ == "__main__":
    H.main(make_demo)
