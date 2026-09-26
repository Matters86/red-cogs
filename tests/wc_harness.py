"""Test-Harness: echter WebCore (aiohttp) + echte Cog-Dashboards mit Fake-Discord-Objekten.

Welt: Server 1000 „Matters Community“ und 2000 „FiveM RP Server“, Nutzer 1 = Bot-Owner (Matters86),
11 Lena (Support), 12 Tom (Moderator), 13 Kai (VIP), 14 Mia (Support + Raidleitung).
Login wird per Header ``X-Test-User: <id>`` simuliert (nur hier, nicht im Produktivcode).

Nutzung:  import wc_harness as H; wc, bot, app = await H.make_app()
Server:   python tests/wc_harness.py [port]   (ohne Port: freier Port) -> läuft bis Strg+C
"""
import asyncio, sys, types
import bootstrap  # zuerst: Repo-Wurzel, Paket ``rc``, temporäre Red-Instanz

ROOT = bootstrap.ROOT

class Perms:
    def __init__(self, admin=False):
        self.administrator = admin; self.manage_guild = admin; self.manage_roles = admin
        self.manage_channels = admin


class Color:
    def __init__(self, v): self.value = v


class Role:
    def __init__(self, guild, rid, name, pos, color=0, default=False):
        self.guild = guild; self.id = rid; self.name = name; self.position = pos
        self.color = Color(color); self._default = default; self.managed = False
        self.permissions = Perms()
    def is_default(self): return self._default
    @property
    def members(self): return [m for m in self.guild.members if self in m.roles]
    @property
    def mention(self): return f"<@&{self.id}>"


class Member:
    def __init__(self, guild, uid, name, roles, admin=False):
        self.guild = guild; self.id = uid; self.display_name = name; self.name = name.lower()
        self.roles = [guild.default_role] + roles; self.guild_permissions = Perms(admin); self.bot = False
        self.mention = f"<@{uid}>"


class Chan:
    def __init__(self, cid, name, category=None):
        self.id = cid; self.name = name; self.category = category; self.mention = f"<#{cid}>"
        self.members = []; self.voice_channels = []; self.slowmode_delay = 0


class Guild:
    def __init__(self, gid, name):
        self.id = gid; self.name = name
        self.default_role = Role(self, gid, "@everyone", 0, default=True)
        self.roles = [self.default_role]; self.members = []
        cat = Chan(gid + 90, "Support")
        self.categories = [cat]
        self.text_channels = [Chan(gid + i, n, cat) for i, n in enumerate(["allgemein", "support", "ankündigungen", "logs"], 1)]
        self.voice_channels = [Chan(gid + 50, "Lobby")]
        self.forums = []; self.emojis = []; self.member_count = 0; self.bitrate_limit = 96000
        self.me = None; self.features = []
    @property
    def channels(self): return self.text_channels + self.voice_channels + self.categories
    def get_channel(self, cid):
        return next((c for c in self.channels if c.id == cid), None)
    get_channel_or_thread = get_channel
    def get_role(self, rid): return next((r for r in self.roles if r.id == int(rid)), None)
    def get_member(self, uid): return next((m for m in self.members if m.id == uid), None)
    async def fetch_member(self, uid):
        import discord
        m = self.get_member(uid)
        if m is None:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="nf"), "nf")
        return m


def build_world():
    g1 = Guild(1000, "Matters Community"); g2 = Guild(2000, "FiveM RP Server")
    sup = Role(g1, 1101, "Support", 5, 0x3DDC97); mod = Role(g1, 1102, "Moderator", 8, 0x6CB6FF)
    lead = Role(g1, 1103, "Raidleitung", 4, 0xF5B94A); vip = Role(g1, 1104, "VIP", 2, 0xB28DFF)
    g1.roles += [sup, mod, lead, vip]
    rp_sup = Role(g2, 2101, "RP-Support", 5, 0x3DDC97); g2.roles += [rp_sup]
    g1.members = [Member(g1, 1, "Matters86", [], admin=True), Member(g1, 11, "Lena", [sup]),
                  Member(g1, 12, "Tom", [mod]), Member(g1, 13, "Kai", [vip]),
                  Member(g1, 14, "Mia", [sup, lead])]
    g2.members = [Member(g2, 1, "Matters86", [], admin=True), Member(g2, 11, "Lena", [rp_sup])]
    for g in (g1, g2):
        g.member_count = len(g.members) * 211
    return [g1, g2]


class FakeBot:
    def __init__(self, guilds):
        self.guilds = guilds; self.owner_ids = {1}; self.latency = 0.042; self.shard_count = 1
        self.user = types.SimpleNamespace(id=999, name="Matters Bot",
                                          display_avatar=types.SimpleNamespace(url="https://cdn.discordapp.com/embed/avatars/2.png"))
        self.users = []; self.cogs = {}; self.commands = []; self.uptime = None
        self._cogs = {}
    def get_guild(self, gid): return next((g for g in self.guilds if g.id == gid), None)
    def get_cog(self, name): return self._cogs.get(name)
    def walk_commands(self): return iter([])
    def dispatch(self, *a, **k): pass
    async def is_owner(self, u): return getattr(u, "id", None) in self.owner_ids
    async def cog_disabled_in_guild(self, cog, guild): return False
    async def wait_until_red_ready(self): pass


# Anzeigenamen für die Login-Simulation (Obermenge aller Harnesses)
NAMES = {"1": "Matters86", "11": "Lena", "12": "Tom", "13": "Kai", "14": "Mia", "15": "Nina", "21": "Ben",
         "99": "Fremder"}


def install_fake_login(wc, names=None):
    """Ersetzt den Discord-OAuth-Login: Nutzer-ID kommt aus Header ``X-Test-User`` oder ``?_as=``."""
    names = NAMES if names is None else names

    async def fake_user(request):
        uid = request.headers.get("X-Test-User") or request.query.get("_as")
        if not uid:
            return None
        from rc.webcore import access as acl
        return {"id": int(uid), "name": names.get(uid, uid), "avatar": acl.avatar_url(int(uid), None)}
    wc._get_user = fake_user


async def make_webcore(bot):
    """Echter WebCore-Cog mit Test-OAuth-Werten und Fake-Login; die aiohttp-App wird aufgebaut,
    ohne einen Port zu binden (Tests nutzen ``aiohttp.test_utils.TestServer``)."""
    from aiohttp import web
    from rc.webcore.webcore import WebCore
    import rc.webcore.webcore as wcm
    wc = WebCore(bot)
    bot._cogs["WebCore"] = wc
    await wc.config.client_id.set("123"); await wc.config.client_secret.set("x")
    await wc.config.redirect_uri.set("http://localhost/callback")
    install_fake_login(wc)

    class NoSite:
        def __init__(self, runner, host, port): pass
        async def start(self): pass
        async def stop(self): pass
    orig_site = web.TCPSite
    wcm.web.TCPSite = NoSite
    try:
        await wc._start_webserver()
    finally:
        wcm.web.TCPSite = orig_site
    return wc


async def make_app():
    guilds = build_world()
    bot = FakeBot(guilds)
    wc = await make_webcore(bot)
    # Cogs registrieren
    from rc.tickets.tickets import Tickets
    from rc.poll.poll import Poll
    from rc.guard.guard import Guard
    from rc.sticky.sticky import Sticky
    from rc.raidhelper.raidhelper import RaidHelper
    from rc.autorole.autorole import Autorole
    from rc.organigram.organigram import Organigram
    from rc.changelog.changelog import Changelog
    from rc.onlyimagevideo.onlyimagevideo import OnlyImageVideo
    from rc.commands.commands import Commands
    from rc.autoroom.autoroom import AutoRoom
    from rc.example.example import Example
    for cls in (Tickets, Poll, Guard, Sticky, RaidHelper, Autorole, Organigram, Changelog, OnlyImageVideo, Commands, AutoRoom, Example):
        c = cls(bot); bot._cogs[cls.__name__] = c; c._register_dashboard(wc)
    return wc, bot, wc.app


async def serve(port=0, make=None):
    """Startet eine Harness als echten Webserver (zum Klicken im Browser). ``port=0`` = freier Port."""
    from aiohttp import web
    res = await (make or make_app)()
    app = res[2]
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port); await site.start()
    port = runner.addresses[0][1]
    print(f"läuft auf http://127.0.0.1:{port}  (Login per Header X-Test-User: 1 = Owner)", flush=True)
    while True:
        await asyncio.sleep(3600)


def main(make=None):
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    try:
        asyncio.run(serve(port, make))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
