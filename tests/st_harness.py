"""Harness für serverstats: live_harness (echter WebCore, Fake-Discord mit echten Kanal-Unterklassen)
+ ServerStats. Ergänzt nur zur Laufzeit: Sprachkanäle „Gaming“ und „AFK“ (= AFK-Kanal) auf Server 1000,
Fake-Nachrichten/Voice-States, Rollen-Rechte Support (Lena, 11) = Bearbeiten, Moderator (Tom, 12) = Ansehen.

Start: python tests/st_harness.py [port]   (mit 90 Tagen Beispieldaten)
"""
import random
import time
import types

import live_harness as L

H = L.H


def msg(guild, author, channel, *, webhook=False):
    return types.SimpleNamespace(guild=guild, author=author, channel=channel, id=next(L._ids),
                                 webhook_id=12345 if webhook else None)


def vstate(channel):
    return types.SimpleNamespace(channel=channel, self_mute=False, mute=False, self_deaf=False, deaf=False)


def add_channels(bot):
    g = bot.guilds[0]
    gaming = L.FakeVoice.make(g, g.id + 52, "Gaming", None, 52)
    afk = L.FakeVoice.make(g, g.id + 51, "AFK", None, 51)
    g.voice_channels += [gaming, afk]
    g.afk_channel = afk
    bot.guilds[1].afk_channel = None
    return gaming, afk


async def make_app():
    wc, bot, app = await L.make_app()
    add_channels(bot)
    from rc.serverstats.serverstats import ServerStats
    cog = ServerStats(bot)
    bot._cogs["ServerStats"] = cog
    cog._register_dashboard(wc)
    await wc.config.role_perms.set({"1000": {"1101": {"serverstats": "edit"}, "1102": {"serverstats": "view"}}})
    return wc, bot, app, cog


async def seed(cog, bot, days=95):
    """Beispieldaten für die letzten ``days`` Tage direkt in die Config (wie nach echtem Betrieb)."""
    rnd = random.Random(86)
    g = bot.guilds[0]
    now = time.time()
    members = 900
    out = {}
    text_ids = [c.id for c in g.text_channels]
    voice_ids = [c.id for c in g.voice_channels if c.name != "AFK"]
    from datetime import timedelta

    from rc.serverstats.serverstats import local_date
    today = local_date(now, await cog.guild_tz(g))          # Tage in der Zeitzone des Servers
    for i in range(days, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        joins, leaves = rnd.randint(0, 9), rnd.randint(0, 5)
        members += joins - leaves
        weekend = (i % 7) in (0, 1)
        out[d] = {
            "joins": joins, "leaves": leaves, "members": members,
            "messages": {str(c): rnd.randint(20, 260) * (2 if weekend else 1) // (k + 1) for k, c in enumerate(text_ids)},
            "voice_sec": {str(c): rnd.randint(0, 5 * 3600) for c in voice_ids},
        }
    await cog.config.guild(g).days.set(out)
    g.member_count = members
    tk = bot.get_cog("Tickets")
    if tk is not None:
        await tk.config.guild(g).tickets.set({"1001": {"num": 1, "owner_id": 13, "status": "open"},
                                              "1002": {"num": 2, "owner_id": 14, "status": "closed"}})
    rh = bot.get_cog("RaidHelper")
    if rh is not None:
        await rh.config.guild(g).events.set({"e1": {"id": "e1", "start_ts": int(now + 2 * 86400), "title": "Raid"},
                                             "e2": {"id": "e2", "start_ts": int(now - 86400), "title": "alt"}})


async def make_demo():
    wc, bot, app, cog = await make_app()
    await seed(cog, bot)
    return wc, bot, app


if __name__ == "__main__":
    H.main(make_demo)
