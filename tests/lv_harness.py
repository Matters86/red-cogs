"""Harness für levels: live_harness (echte Kanal-Unterklassen, send-Aufzeichnung) + wcm_harness (Mein Bereich,
Nutzer Ben/Kai …) + Levels. Ergänzt NUR zur Laufzeit (keine fremde Datei wird geändert):

* ``Member.add_roles/remove_roles`` mit Aufzeichnung (ROLE_LOG); ``member.fail_roles = True`` -> Forbidden
* DMs werden in DMS aufgezeichnet (``member.dm_closed = True`` -> Forbidden)
* Voice-States (``set_voice(member, channel, mute=…)``), Sprachkanäle „Gaming“ und „AFK“ (= AFK-Kanal)
* Belohnungsrollen auf Server 1000: Level 5 (Pos. 3), Level 10 (Pos. 4), Stammgast (Pos. 6),
  Mod-Rolle (Pos. 3, darf Nachrichten verwalten), Über Bot (Pos. 25), Booster (Pos. 2)
* Rollen-Rechte: Support (Lena, 11) = Bearbeiten, Moderator (Tom, 12) = Ansehen; Mitglieder-Bereich auf 1000 an

Start: python tests/lv_harness.py [port]   (mit Beispieldaten)
"""
import random
import types

import live_harness as L          # zuerst: tauscht Guild/Bot gegen Live-Varianten
import wcm_harness as M           # Mein-Bereich-Nutzer (Ben), Demo-Seiten
import wc_harness as H

ROLE_LOG = []   # (op, guild_id, member_id, [role_ids])
DMS = []        # (member_id, content)


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


async def _dm(self, content=None, *, embed=None, allowed_mentions=None, **kw):
    if getattr(self, "dm_closed", False):
        raise L.forbidden()
    L.validate_message(content, [embed] if embed else [], None, [])
    DMS.append((self.id, content))


H.Member.add_roles = _add_roles
H.Member.remove_roles = _remove_roles
H.Member.send = _dm


def set_voice(member, channel, *, mute=False, deaf=False, self_mute=False, self_deaf=False):
    """Mitglied in ``channel`` setzen (None = raus) – pflegt ``channel.members`` und ``member.voice``."""
    for ch in member.guild.voice_channels:
        if member in ch.members:
            ch.members.remove(member)
    if channel is None:
        member.voice = None
        return
    channel.members.append(member)
    member.voice = types.SimpleNamespace(channel=channel, mute=mute, deaf=deaf, self_mute=self_mute,
                                         self_deaf=self_deaf)


def msg(guild, author, channel, *, webhook=False):
    return types.SimpleNamespace(guild=guild, author=author, channel=channel, id=next(L._ids),
                                 webhook_id=12345 if webhook else None)


def add_world(bot):
    g1 = bot.guilds[0]
    for m in g1.members:
        m.voice = None
    gaming = L.FakeVoice.make(g1, g1.id + 52, "Gaming", None, 52)
    afk = L.FakeVoice.make(g1, g1.id + 51, "AFK", None, 51)
    g1.voice_channels += [gaming, afk]
    g1.afk_channel = afk
    bot.guilds[1].afk_channel = None
    roles = {}
    for rid, name, pos in ((1301, "Level 5", 3), (1302, "Level 10", 4), (1303, "Stammgast", 6),
                           (1304, "Mod-Rolle", 3), (1305, "Über Bot", 25), (1306, "Booster", 2)):
        r = H.Role(g1, rid, name, pos, 0x3DDC97)
        g1.roles.append(r)
        roles[rid] = r
    roles[1304].permissions.manage_messages = True
    return roles


async def make_app():
    wc, bot, app = await M.make_app()
    add_world(bot)
    from rc.levels.levels import Levels
    cog = Levels(bot)
    bot._cogs["Levels"] = cog
    cog._register_dashboard(wc)
    await wc.config.member_portal.set({"1000": True})
    await wc.config.role_perms.set({"1000": {"1101": {"levels": "edit"}, "1102": {"levels": "view"}}})
    return wc, bot, app, cog


async def seed(cog, bot):
    """Beispieldaten: XP für alle Mitglieder + ein paar Zusatzmitglieder, Belohnungen, Multiplikator."""
    g = bot.guilds[0]
    rnd = random.Random(86)
    names = ["Jonas", "Emma", "Luca", "Sophie", "Noah <b>fett</b>", "Hannah", "Elias", "Lina", "Finn", "Clara",
             "Ben der sehr lange Anzeigename mit Überlänge", "Marie"]
    for i, name in enumerate(names):
        m = H.Member(g, 3000 + i, name, [])
        m.display_avatar = L.FakeAsset(m.id); m.avatar = m.display_avatar; m.voice = None
        g.members.append(m)
    gconf = cog.config.guild(g)
    await gconf.rewards.set({"5": 1301, "10": 1302})
    await gconf.multipliers.set({"1104": 1.5})
    for m in g.members:
        if m.bot:
            continue
        await cog.set_xp(m, rnd.randint(50, 12000), announce=False)
    await cog.set_xp(g.get_member(13), 2600, announce=False)
    await cog.flush()


async def make_demo():
    wc, bot, app, cog = await make_app()
    await seed(cog, bot)
    return wc, bot, app


if __name__ == "__main__":
    H.main(make_demo)
