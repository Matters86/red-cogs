"""rc_harness – Raidplaner-Harness: echter WebCore + NUR der RaidHelper-Cog.

Basis: live_harness.py (Fake-Kanäle bestehen isinstance-Prüfungen, send/edit werden in L.LOG
aufgezeichnet und wie von Discord geprüft). Zusätzlich ein Kanal ``#gesperrt`` ohne Senderechte.
Nutzung:  import rc_harness as R; wc, bot, app, rh = await R.make_app()
Server:   python tests/rc_harness.py [port]   (Login per Header X-Test-User, 1 = Owner)
"""
import time
import live_harness as L   # patcht wc_harness (LiveGuild/LiveBot)
H = L.H


async def make_app(seed=True):
    guilds = H.build_world()
    for g in guilds:
        locked = L.FakeText.make(g, g.id + 7, "gesperrt", g.categories[0], 7)
        locked.forbid = {"send"}
        g.text_channels.append(locked)
    bot = H.FakeBot(guilds)
    wc = await H.make_webcore(bot)
    from rc.raidhelper.raidhelper import RaidHelper
    rh = RaidHelper(bot); bot._cogs["RaidHelper"] = rh; rh._register_dashboard(wc)
    if seed:
        g = guilds[0]
        await rh.config.guild(g).signup_channel.set(g.id + 1)
        now = int(time.time())
        await rh.create_event(g, game="wow_retail", title="Mythic Undermine", description="Treffpunkt Orgrimmar.",
                              leader_id=1, channel_id=g.id + 1, start_ts=now + 3 * 86400, max_signups=20,
                              role_limits={"tank": 2, "healer": 4})
        await rh.create_event(g, game="wow_classic", title="Molten Core", description=None, leader_id=14,
                              channel_id=g.id + 1, start_ts=now + 6 * 86400, recurrence="weekly")
    return wc, bot, wc.app, rh


if __name__ == "__main__":
    H.main(make_app)
