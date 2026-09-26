"""rm_harness – Raidplaner-Mitgliederseite: echter WebCore + NUR RaidHelper, Mein Bereich an.

Basis: rc_harness.py (live_harness-Fakes: Kanäle bestehen isinstance-Prüfungen, send/edit -> L.LOG).
Zusätzlich:
* Kanal ``#raid-intern`` (1008), den nur Admins und die Rolle „Raidleitung“ (1103) sehen dürfen
* Mein Bereich auf Server 1000 an, Nutzer 21 „Ben“ auf Server 2000
* Demo-Events (sichtbar, versteckt, geschlossen, Anmeldeschluss vorbei, anderer Server, abgeschlossen)
Nutzung:  import rm_harness as M; wc, bot, app, rh, ev = await M.make_app()
Server:   python tests/rm_harness.py [port]   (Login per Header X-Test-User: 1 Owner, 13 Kai = Mitglied, 14 Mia = Raidleitung)
"""
import time
import rc_harness as R
L = R.L
H = L.H
import discord

HIDDEN_ROLE = 1103


def _hidden_perms(ch):
    def permissions_for(obj):
        p = discord.Permissions.all()
        roles = {r.id for r in getattr(obj, "roles", [])}
        admin = getattr(getattr(obj, "guild_permissions", None), "administrator", False)
        if not admin and HIDDEN_ROLE not in roles and getattr(obj, "id", None) != 999:
            p.view_channel = False
        return p
    ch.permissions_for = permissions_for


async def make_app(seed=True):
    wc, bot, app, rh = await R.make_app(seed=False)
    g1, g2 = bot.guilds
    g2.members.append(H.Member(g2, 21, "Ben", []))
    hidden = L.FakeText.make(g1, 1008, "raid-intern", g1.categories[0], 8)
    _hidden_perms(hidden)
    g1.text_channels.append(hidden)
    await wc.config.member_portal.set({"1000": True})
    ev = {}
    if seed:
        now = int(time.time())
        await rh.config.guild(g1).signup_channel.set(1001)
        mk = rh.create_event
        e = await mk(g1, game="wow_retail", title="Mythic Undermine",
                     description="Treffpunkt **Orgrimmar** 19:45. Bitte Flasks, Food und Runen mitbringen – "
                                 "wir raiden bis ca. 23 Uhr. Logs werden hochgeladen, Taktik-Videos im Kanal "
                                 "#taktik. Wer nicht kann, bitte rechtzeitig auf Abwesend stellen.",
                     leader_id=14, channel_id=1001, start_ts=now + 3 * 86400 + 3600, max_signups=20,
                     role_limits={"tank": 2, "healer": 4})
        ev["main"] = e["id"]
        e = await mk(g1, game="wow_classic", title="Molten Core", description=None, leader_id=14,
                     channel_id=1001, start_ts=now + 6 * 86400, recurrence="weekly")
        ev["mc"] = e["id"]
        e = await mk(g1, game="wow_retail", title="Gildenintern: Taktikbesprechung", description="Nur Raidleitung.",
                     leader_id=14, channel_id=1008, start_ts=now + 2 * 86400)
        ev["hidden"] = e["id"]
        e = await mk(g1, game="wow_retail", title="Heroic Farm (geschlossen)", description=None, leader_id=1,
                     channel_id=1002, start_ts=now + 4 * 86400)
        ev["closed"] = e["id"]
        e = await mk(g1, game="wow_retail", title="M+ Abend", description="Keys ab +10.", leader_id=1,
                     channel_id=1002, start_ts=now + 86400, deadline_ts=now - 600)
        ev["deadline"] = e["id"]
        e = await mk(g1, game="wow_retail", title="Vergangener Raid", description=None, leader_id=1,
                     channel_id=1001, start_ts=now - 86400)
        ev["past"] = e["id"]
        e = await mk(g2, game="wow_retail", title="Fremder Server Raid", description=None, leader_id=1,
                     channel_id=2001, start_ts=now + 86400)
        ev["foreign"] = e["id"]
        async with rh.config.guild(g1).events() as evs:
            evs[ev["closed"]]["closed"] = True
            evs[ev["past"]]["completed"] = True
            evs[ev["past"]]["closed"] = True
            s = evs[ev["main"]]["signups"]
            base = now - 7200
            for i, (uid, name, cls, spec, role, st) in enumerate([
                (1, "Matters86", "paladin", "schutz", "tank", "signed"),
                (14, "Mia", "priester", "heilig", "healer", "signed"),
                (11, "Lena", "magier", "frost", "rdps", "signed"),
                (12, "Tom", "schurke", "meucheln", "mdps", "late"),
                (5001, "Arthas", "todesritter", "blut", "tank", "signed"),
                (5002, "Jaina", "magier", "feuer", "rdps", "tentative"),
            ]):
                s[str(uid)] = {"name": name, "class": cls, "spec": spec, "role": role, "status": st, "at": base + i}
    return wc, bot, wc.app, rh, ev


if __name__ == "__main__":
    H.main(make_app)
