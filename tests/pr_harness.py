"""Harness für „Mein Bereich → Umfragen/Rollen“ (poll + autorole).

Basis: live_harness (echte Kanal-Unterklassen, send/edit-Aufzeichnung) + wcm_harness (Mein Bereich,
Nutzer Ben/Kai …). Ergänzt NUR zur Laufzeit (keine fremde Datei wird geändert):
* Kanal-Sichtbarkeit pro Mitglied: ``chan.hidden = {member_id, ...}`` -> view_channel False
* ``Member.add_roles/remove_roles`` mit Aufzeichnung (ROLE_LOG); ``member.fail_roles = True`` -> Forbidden
* Beispieldaten (seed): Umfragen + Rollen-Panels auf Server 1000 (und je eine auf 2000)

Start: python tests/pr_harness.py [port]
"""
import time
import live_harness as L          # zuerst: tauscht Guild/Bot gegen Live-Varianten
import wcm_harness as M           # Mein-Bereich-Nutzer, Demo-Seiten
import wc_harness as H


ROLE_LOG = []   # (op, guild_id, member_id, [role_ids])


# ------------------------------------------------------------ Kanal-Sichtbarkeit
_orig_perms = L._SendMixin.permissions_for


def _perms_for(self, obj):
    p = _orig_perms(self, obj)
    if getattr(obj, "id", None) in getattr(self, "hidden", set()):
        p.view_channel = False
        p.read_messages = False
    return p


L._SendMixin.permissions_for = _perms_for


# ------------------------------------------------------------ Rollen vergeben
async def _add_roles(self, *roles, reason=None):
    if getattr(self, "fail_roles", False):
        raise L.forbidden()
    ROLE_LOG.append(("add", self.guild.id, self.id, sorted(r.id for r in roles)))
    for r in roles:
        if r not in self.roles:
            self.roles.append(r)


async def _remove_roles(self, *roles, reason=None):
    if getattr(self, "fail_roles", False):
        raise L.forbidden()
    ROLE_LOG.append(("remove", self.guild.id, self.id, sorted(r.id for r in roles)))
    ids = {r.id for r in roles}
    self.roles = [r for r in self.roles if r.id not in ids]


H.Member.add_roles = _add_roles
H.Member.remove_roles = _remove_roles


# ------------------------------------------------------------ Beispieldaten
def add_roles_to_world(bot):
    g1, g2 = bot.guilds
    new = [(1201, "Rot", 3, 0xFF6B6B), (1202, "Blau", 3, 0x6CB6FF), (1203, "Grün", 3, 0x3DDC97),
           (1211, "News-Ping", 1, 0), (1212, "Event-Ping", 1, 0), (1213, "Stream-Ping", 1, 0),
           (1221, "WoW", 2, 0xF5B94A), (1222, "FiveM", 2, 0xB28DFF),
           (1229, "Oberrolle", 30, 0xFFFFFF), (1231, "Geheim-Rolle", 2, 0)]
    for rid, name, pos, col in new:
        g1.roles.append(H.Role(g1, rid, name, pos, col))
    g2.roles.append(H.Role(g2, 2201, "RP-Farbe", 3, 0xFF6B6B))
    # Hauptdarstellerin: Mia (14) sieht #support nicht, Kai (13) sieht #support nicht
    g1.get_channel(1002).hidden = {13, 14}


def _pr(role_id, label="", emoji="", style="secondary", desc=""):
    return {"role_id": role_id, "label": label, "emoji": emoji, "style": style, "description": desc}


async def seed(bot):
    now = int(time.time())
    g1, g2 = bot.guilds
    add_roles_to_world(bot)
    pl = bot.get_cog("Poll")
    mk = pl.create_poll
    p1 = await mk(g1, question="Beste Pizza?", options=["Margherita", "Salami", "Hawaii <script>alert(1)</script>"],
                  channel_id=1001, author_id=1, end_ts=now + 7200)
    p2 = await mk(g1, question="Wann soll der nächste Raid stattfinden? (mehrere Tage möglich)",
                  options=["Freitag", "Samstag", "Sonntag", "Eine sehr lange Option, die auf dem Handy sicher umbrechen muss"],
                  channel_id=1001, author_id=1, multiple=True, anonymous=True)
    p3 = await mk(g1, question="Geheime Team-Umfrage", options=["A", "B"], channel_id=1002, author_id=1)
    p4 = await mk(g1, question="Neues Server-Logo?", options=["Ja", "Nein"], channel_id=1003, author_id=1)
    p5 = await mk(g1, question="Alte Umfrage (20 Tage)", options=["X", "Y"], channel_id=1001, author_id=1)
    p6 = await mk(g1, question="Geschlossene Umfrage", options=["Rot", "Blau"], channel_id=1003, author_id=1)
    async with pl.config.guild(g1).polls() as polls:
        polls[p1["id"]]["votes"] = {"1": {"name": "Matters86", "choices": [0]}, "11": {"name": "Lena", "choices": [1]},
                                    "12": {"name": "Tom", "choices": [0]}}
        polls[p2["id"]]["votes"] = {"1": {"name": "A", "choices": [0, 1]}, "11": {"name": "B", "choices": [1]}}
        polls[p4["id"]].update(ended=True, closed=True, end_ts=now - 3 * 86400, closed_ts=now - 3 * 86400,
                               votes={"1": {"name": "M", "choices": [0]}, "13": {"name": "Kai", "choices": [0]},
                                      "11": {"name": "L", "choices": [1]}})
        polls[p5["id"]].update(closed=True, closed_ts=now - 20 * 86400, votes={"1": {"name": "M", "choices": [1]}})
        polls[p6["id"]].update(closed=True, closed_ts=now - 3600)
        # ungepostete Umfrage (Posten fehlgeschlagen) -> nirgends sichtbar
        polls["p-0099"] = dict(polls[p1["id"]], id="p-0099", question="Ungepostet", message_id=None, votes={})
    await mk(g2, question="RP-Umfrage auf Server 2", options=["Ja", "Nein"], channel_id=2001, author_id=1)

    ar = bot.get_cog("Autorole")
    panels = {
        "aaaa0001": {"id": "aaaa0001", "name": "Farben", "channel_id": 1001, "message_id": None, "style": "buttons",
                     "mode": "toggle", "unique": True, "use_embed": True, "title": "Namensfarbe",
                     "color": "", "text": "Such dir eine Farbe aus.\nNur eine gleichzeitig!",
                     "roles": [_pr(1201, "Rot", "🔴", "danger"), _pr(1202, "Blau", "🔵", "primary"), _pr(1203, "Grün", "🟢", "success")]},
        "aaaa0002": {"id": "aaaa0002", "name": "Pings", "channel_id": 1003, "message_id": None, "style": "select",
                     "mode": "toggle", "unique": False, "use_embed": True, "title": "Benachrichtigungen",
                     "color": "", "text": "Welche Pings möchtest du?",
                     "roles": [_pr(1211, "News", "📰", desc="Neuigkeiten"), _pr(1212, "Events", "🎉"), _pr(1213, "Stream", "📺")]},
        "aaaa0003": {"id": "aaaa0003", "name": "Spiele", "channel_id": 1001, "message_id": None, "style": "buttons",
                     "mode": "add", "unique": False, "use_embed": False, "title": "", "color": "",
                     "text": "Welche Spiele spielst du? <b>kein HTML</b>",
                     "roles": [_pr(1221, "WoW"), _pr(1222, "FiveM"), _pr(1229, "Oberrolle")]},
        "aaaa0004": {"id": "aaaa0004", "name": "Geheim", "channel_id": 1002, "message_id": None, "style": "buttons",
                     "mode": "toggle", "unique": False, "use_embed": True, "title": "Team intern", "color": "",
                     "text": "", "roles": [_pr(1231, "Geheim")]},
        "aaaa0005": {"id": "aaaa0005", "name": "Ungepostet", "channel_id": 1001, "message_id": None, "style": "buttons",
                     "mode": "toggle", "unique": False, "use_embed": True, "title": "Entwurf", "color": "",
                     "text": "", "roles": [_pr(1221, "WoW")]},
        "aaaa0006": {"id": "aaaa0006", "name": "Region", "channel_id": 1003, "message_id": None, "style": "select",
                     "mode": "add", "unique": True, "use_embed": True, "title": "Deine Hauptfarbe (Dropdown)", "color": "",
                     "text": "", "roles": [_pr(1201, "Rot"), _pr(1202, "Blau")]},
    }
    await ar.config.guild(g1).panels.set(panels)
    for pid in ("aaaa0001", "aaaa0002", "aaaa0003", "aaaa0004", "aaaa0006"):
        ok, key = await ar._panel_post(g1, panels[pid])
        assert ok, (pid, key)
    p2panel = {"id": "bbbb0001", "name": "RP", "channel_id": 2001, "message_id": None, "style": "buttons",
               "mode": "toggle", "unique": False, "use_embed": True, "title": "RP", "color": "", "text": "",
               "roles": [_pr(2201, "RP-Farbe")]}
    await ar.config.guild(g2).panels.set({"bbbb0001": p2panel})
    ok, key = await ar._panel_post(g2, p2panel)
    assert ok, key
    return {"p1": p1["id"], "p2": p2["id"], "p3": p3["id"], "p4": p4["id"], "p5": p5["id"], "p6": p6["id"]}


async def make_app():
    wc, bot, app = await M.make_app()
    await wc.config.member_portal.set({"1000": True})
    ids = await seed(bot)
    return wc, bot, app, ids


if __name__ == "__main__":
    H.main(make_app)
