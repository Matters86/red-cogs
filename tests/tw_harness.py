"""Harness für TwitchLive: live_harness (echte Kanal-Unterklassen, send/edit-Log) + TwitchLive mit
gemockter Twitch-API (FakeTwitch ersetzt TwitchAPI._http – kein Netz nötig).

Start: python tests/tw_harness.py [port]   (TW_NOCREDS=1: Zustand „Zugangsdaten fehlen“)
"""
import time
import live_harness as L
H = L.H

CLIENT_ID = "fakeclientid123"
SECRET = "SUPERSECRET-twitch-abc987"


class FakeTwitch:
    """Minimaler Helix-Nachbau: Token-Endpunkt, /streams, /users."""

    def __init__(self):
        self.live = {}       # login -> stream dict
        self.users = {}      # login -> user dict
        self.calls = []      # (method, path, params)
        self.tokens = set()
        self.token_n = 0
        self.fail = []       # Warteschlange: (status, headers, body) oder Exception für die nächsten Helix-Aufrufe
        self.fail_token = []

    def add_user(self, login, name=None, avatar=True):
        self.users[login] = {"id": str(abs(hash(login)) % 10**8), "login": login, "display_name": name or login,
                             "profile_image_url": f"https://static-cdn.jtvnw.net/jtv_user_pictures/{login}-profile_image-300x300.png" if avatar else ""}

    def go_live(self, login, sid="s1", title="Ranked bis Diamant", game="Valorant", viewers=42, started=None):
        started = started or time.time() - 600
        self.live[login] = {"id": sid, "user_login": login, "user_name": self.users.get(login, {}).get("display_name", login),
                            "game_name": game, "type": "live", "title": title, "viewer_count": viewers,
                            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
                            "thumbnail_url": f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-{{width}}x{{height}}.jpg"}

    async def http(self, method, url, *, params=None, data=None, headers=None):
        from rc.twitchlive.api import TOKEN_URL
        if url == TOKEN_URL:
            self.calls.append((method, "token", None))
            if self.fail_token:
                f = self.fail_token.pop(0)
                if isinstance(f, Exception):
                    raise f
                return f
            if data.get("client_id") != CLIENT_ID or data.get("client_secret") != SECRET:
                return 400, {}, {"status": 400, "message": "invalid client secret"}
            self.token_n += 1
            tok = f"tok{self.token_n}"
            self.tokens.add(tok)
            return 200, {}, {"access_token": tok, "expires_in": 5000000, "token_type": "bearer"}
        path = url.rsplit("/", 1)[1]
        self.calls.append((method, path, list(params or [])))
        if self.fail:
            f = self.fail.pop(0)
            if isinstance(f, Exception):
                raise f
            return f
        if headers.get("Client-Id") != CLIENT_ID:
            return 401, {}, {"message": "bad client id"}
        tok = headers.get("Authorization", "").replace("Bearer ", "")
        if tok not in self.tokens:
            return 401, {}, {"message": "Invalid OAuth token"}
        if path == "streams":
            logins = [v for k, v in params if k == "user_login"]
            assert len(logins) <= 100, len(logins)
            return 200, {}, {"data": [self.live[l] for l in logins if l in self.live], "pagination": {}}
        if path == "users":
            logins = [v for k, v in params if k == "login"]
            assert len(logins) <= 100, len(logins)
            return 200, {}, {"data": [self.users[l] for l in logins if l in self.users]}
        return 404, {}, None


def install_role_ops(bot):
    """add_roles/remove_roles für Fake-Mitglieder (zeichnet in L.LOG auf)."""
    for g in bot.guilds:
        for m in g.members:
            def mk(mem):
                async def add_roles(*roles, reason=None):
                    for r in roles:
                        if r not in mem.roles:
                            mem.roles.append(r)
                    L.log("add_roles", mem.id, roles=[r.id for r in roles])
                async def remove_roles(*roles, reason=None):
                    for r in roles:
                        if r in mem.roles:
                            mem.roles.remove(r)
                    L.log("remove_roles", mem.id, roles=[r.id for r in roles])
                return add_roles, remove_roles
            m.add_roles, m.remove_roles = mk(m)
        g.owner_id = 1


async def make_cog(bot, wc=None, fake=None):
    from rc.twitchlive.twitchlive import TwitchLive
    fake = fake or FakeTwitch()
    cog = TwitchLive(bot)
    cog.api._http = fake.http
    cog.fake = fake
    bot._cogs["TwitchLive"] = cog
    if wc is not None:
        cog._register_dashboard(wc)
    return cog


async def make_app(seed_data=True):
    wc, bot, app = await L.make_app()
    install_role_ops(bot)
    cog = await make_cog(bot, wc)
    if seed_data:
        await seed(cog, bot, wc)
    return wc, bot, app, cog


async def seed(cog, bot, wc):
    f = cog.fake
    for login, name in (("matters86", "Matters86"), ("lenaplays", "LenaPlays"), ("kaigaming", "KaiGaming"),
                        ("mia_art", "Mia_Art")):
        f.add_user(login, name)
    await cog.config.client_id.set(CLIENT_ID)
    await cog.config.client_secret.set(SECRET)
    g = bot.get_guild(1000)
    gc = cog.config.guild(g)
    await gc.default_channel.set(1003)                 # #ankündigungen
    await cog.upsert_channel(g, "matters86", ping_role=1104)
    await cog.upsert_channel(g, "lenaplays", channel_id=1001,
                             message="🎨 {ping} **{streamer}** streamt: *{title}* – {url}")
    await cog.upsert_channel(g, "kaigaming", enabled=False)
    await cog.upsert_channel(g, "mia_art")
    await gc.links.set({"11": "lenaplays", "1": "matters86"})
    await gc.live_role.set(1104)
    f.go_live("matters86", "s-100", "Ranked-Grind bis Diamant – !discord", "Valorant", 1234)
    f.go_live("lenaplays", "s-200", "Digital Painting & Chill", "Art", 87)
    await cog.poll_once()
    import os
    if os.environ.get("TW_NOCREDS"):     # Zustand „Zugangsdaten fehlen“ zeigen
        await cog.config.client_secret.set("")
        cog.status.update(state="no_credentials")
    # WebCore-Rollen-Rechte: Support (Lena) = Bearbeiten, Moderator (Tom) = Ansehen
    await wc.config.role_perms.set({"1000": {"1101": {"twitchlive": "edit"}, "1102": {"twitchlive": "view"}}})


if __name__ == "__main__":
    H.main(make_app)
