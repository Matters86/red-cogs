"""Harness Gewinnspiele (giveaways): echter WebCore + Mein Bereich + Giveaways-Cog mit Fake-Discord.

Basis: live_harness (echte Kanal-Unterklassen, send/edit-Aufzeichnung, Discord-Limits) und
wcm_harness (Mitglieder Ben/Kai, Mein Bereich). Ergänzt NUR zur Laufzeit:
* ``bot.add_view(view, message_id=…)`` -> ``VIEWS`` (persistente Views)
* jede Kanal-Nachricht mit ``allowed_mentions``/``reference`` -> ``SENT``
* Kanal-Sichtbarkeit pro Mitglied: ``chan.hidden = {member_id, …}`` -> ``view_channel`` False
* ``joined_at`` für alle Mitglieder (Kai erst seit 3 Tagen auf Server 1000)
* Fake-Interaktionen (``Inter``) mit aufgezeichneten Antworten

Start (Browser):  python tests/gv_harness.py [port]   – mit Beispieldaten, Login per X-Test-User
"""
import time
from datetime import datetime, timedelta, timezone
import live_harness as L          # zuerst: Live-Kanäle/-Bot
import wcm_harness as M
import wc_harness as H
import discord

VIEWS = []   # (view, message_id)
SENT = []    # {"channel", "content", "allowed_mentions", "reference", "message"}


def _add_view(self, view, *, message_id=None):
    assert view.timeout is None and all(getattr(i, "custom_id", None) for i in view.children), "View nicht persistent"
    VIEWS.append((view, message_id))


H.FakeBot.add_view = _add_view

_orig_send = L._SendMixin.send


async def _send(self, content=None, **kw):
    msg = await _orig_send(self, content, **kw)
    SENT.append({"channel": self.id, "content": content, "allowed_mentions": kw.get("allowed_mentions"),
                 "reference": kw.get("reference"), "message": msg})
    return msg


L._SendMixin.send = _send

_orig_perms = L._SendMixin.permissions_for


def _perms_for(self, obj):
    p = _orig_perms(self, obj)
    if getattr(obj, "id", None) in getattr(self, "hidden", set()):
        p.view_channel = False
        p.read_messages = False
    return p


L._SendMixin.permissions_for = _perms_for


# ------------------------------------------------------------------ Interaktionen
class Resp:
    def __init__(self, rec):
        self.rec = rec; self._done = False

    def is_done(self):
        return self._done

    async def send_message(self, content=None, *, ephemeral=False, view=None, **kw):
        self._done = True
        self.rec.append({"op": "send_message", "content": content, "ephemeral": ephemeral, "view": view})

    async def edit_message(self, *, content=None, view=None, **kw):
        self._done = True
        self.rec.append({"op": "edit_message", "content": content, "view": view})


class Inter:
    def __init__(self, bot, guild, user, custom_id=""):
        self.rec = []
        self.type = discord.InteractionType.component
        self.data = {"custom_id": custom_id}
        self.client = bot; self.guild = guild; self.user = user
        self.response = Resp(self.rec)

    @property
    def last(self):
        return self.rec[-1]


async def click(bot, guild, user, view):
    """Klickt den (einzigen) Button einer View wie Discord es täte und gibt die Interaktion zurück."""
    btn = view.children[0]
    inter = Inter(bot, guild, user, btn.custom_id)
    await btn.callback(inter)
    return inter


def find_view(custom_id):
    for view, mid in reversed(VIEWS):
        for item in view.children:
            if getattr(item, "custom_id", None) == custom_id:
                return view, mid
    return None, None


# ------------------------------------------------------------------ Welt
def prepare_world(bot):
    g1, g2 = bot.guilds
    now = datetime.now(timezone.utc)
    for g in (g1, g2):
        for m in g.members:
            m.joined_at = now - timedelta(days=400)
    g1.get_member(13).joined_at = now - timedelta(days=3)      # Kai: neu auf dem Server
    g1.members.append(H.Member(g1, 15, "Nina", []))
    g1.get_member(15).joined_at = now - timedelta(days=50)
    g1.get_member(15).display_avatar = L.FakeAsset(15)
    g1.roles.append(H.Role(g1, 1105, "Booster", 3, 0xF47FFF))
    g1.roles.append(H.Role(g1, 1106, "Gesperrt", 1, 0x888888))
    g1.get_channel(1002).hidden = {13, 15}                        # #support: Kai/Nina sehen ihn nicht


async def make_app(loop=False):
    wc, bot, app = await M.make_app()
    prepare_world(bot)
    await wc.config.member_portal.set({"1000": True})
    from rc.giveaways.giveaways import Giveaways
    cog = Giveaways(bot)
    bot._cogs["Giveaways"] = cog
    await cog.cog_load()
    if not loop:
        cog._tick.cancel()          # Tests rufen process_due() gezielt mit eigener Zeit auf
    return wc, bot, app, cog


async def seed(bot, cog):
    g1 = bot.guilds[0]
    ch = g1.get_channel(1001)
    now = int(time.time())
    gw1, _ = await cog.create_giveaway(g1, ch, host_id=1, prize="Discord Nitro (1 Monat)",
                                       description="Einfach auf 🎉 klicken!\nDie Auslosung ist Freitag.",
                                       end_ts=now + 2 * 86400, winner_count=2, bonus_roles={"1105": 2})
    gw2, _ = await cog.create_giveaway(g1, g1.get_channel(1003), host_id=1, prize="Steam-Key <b>Elden Ring</b>",
                                       end_ts=now + 3 * 3600, winner_count=1, required_roles=[1104, 1101],
                                       excluded_roles=[1106], min_member_days=30)
    gw3, _ = await cog.create_giveaway(g1, g1.get_channel(1002), host_id=1, prize="Team-Gewinnspiel (intern)",
                                       end_ts=now + 86400, winner_count=1)
    gw4, _ = await cog.create_giveaway(g1, ch, host_id=1, prize="Merch-Paket", end_ts=now + 600, winner_count=1)
    members = {m.id: m for m in g1.members}
    for uid in (1, 11, 12, 14, 15):
        await cog.join(g1, members[uid], gw1["id"])
    for uid in (11, 12, 13, 15):
        await cog.join(g1, members[uid], gw4["id"])
    await cog.end_giveaway(g1, gw4["id"], by="manual")
    gw5, _ = await cog.create_giveaway(g1, ch, host_id=1, prize="Abgebrochenes Gewinnspiel", end_ts=now + 600,
                                       winner_count=1)
    await cog.cancel_giveaway(g1, gw5["id"])
    return {"gw1": gw1["id"], "gw2": gw2["id"], "gw3": gw3["id"], "gw4": gw4["id"], "gw5": gw5["id"]}


async def make_demo():
    wc, bot, app, cog = await make_app(loop=True)
    await seed(bot, cog)
    return wc, bot, app, cog


if __name__ == "__main__":
    H.main(make_demo)
