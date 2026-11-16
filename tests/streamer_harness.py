"""Streamer mit echtem Red/WebCore und simulierten Twitch-/YouTube-Snapshots."""
import copy
import time

import discord
import live_harness as L


TWITCH_ID = "test-twitch-client"
TWITCH_SECRET = "test-twitch-secret-never-in-html"
YOUTUBE_KEY = "test-youtube-key-never-in-html"
YOUTUBE_ID = "UCabcdefghijklmnopqrstuv"


class FakeStreamAPI:
    def __init__(self):
        self.sources = {}
        self.aliases = {}
        self.live = {}
        self.errors = {}
        self.calls = []
        self.closed = False

    def add(self, provider, identifier, name=None, aliases=()):
        key = f"{provider}:{identifier}"
        source = {"key": key, "provider": provider, "identifier": identifier,
                  "name": name or identifier, "enabled": True}
        self.sources[key] = source
        for alias in (identifier, *aliases):
            self.aliases[(provider, alias)] = key
        return source

    async def resolve(self, provider, raw):
        key = self.aliases.get((provider, raw))
        if key is None:
            raise ValueError("Kanal nicht gefunden")
        return copy.deepcopy(self.sources[key])

    def go_live(self, key, stream_id="stream-1", title="DNP – Teamabend", **fields):
        source = self.sources[key]
        provider = source["provider"]
        stream = {"id": stream_id, "provider": provider, "source_key": key,
                  "name": source["name"], "title": title,
                  "url": (f"https://www.twitch.tv/{source['identifier']}" if provider == "twitch"
                          else f"https://www.youtube.com/watch?v={stream_id}"),
                  "thumbnail": "https://example.org/stream-preview.jpg", "game": "Grand Theft Auto V",
                  "viewers": 42, "started_at": "2026-11-16T18:00:00Z"}
        stream.update(fields)
        self.live[key] = [stream]
        return stream

    async def streams(self, provider, sources, *, known=None):
        self.calls.append((provider, copy.deepcopy(sources), copy.deepcopy(known)))
        error = self.errors.get(provider)
        if error is not None:
            raise error
        return {key: copy.deepcopy(self.live.get(key, [])) for key in sources}

    def reset_credentials(self):
        pass

    async def close(self):
        self.closed = True


async def make_cog(bot, wc=None, fake=None):
    from rc.streamer.streamer import Streamer
    cog = Streamer(bot)
    original = cog.api
    await original.close()
    cog.api = fake or FakeStreamAPI()
    bot._cogs["Streamer"] = cog
    if wc is not None:
        cog._register_dashboard(wc)
    return cog


async def make_app(seed=False):
    guilds = L.H.build_world()
    bot = L.H.FakeBot(guilds)
    bot.intents = discord.Intents.all()
    bot.is_ready = lambda: True
    for guild in guilds:
        guild.chunked = True
        guild.unavailable = False
        async def chunk(*, cache=True, _guild=guild):
            # Ein unvollständig simulierter Cache bleibt bis zur expliziten Freigabe unvollständig.
            return list(_guild.members)
        guild.chunk = chunk
        for member in guild.members:
            member.activities = ()
    wc = await L.H.make_webcore(bot)
    cog = await make_cog(bot, wc)
    clock = [time.time()]
    cog._now = lambda: clock[0]
    cog.test_clock = clock
    fake = cog.api
    fake.add("twitch", "matters86", "Matters86", ("https://twitch.tv/matters86", "@matters86"))
    fake.add("twitch", "lenaplays", "LenaPlays")
    fake.add("youtube", YOUTUBE_ID, "Projektteam", ("@projektteam", "https://youtube.com/@projektteam"))
    await cog.config.twitch_client_id.set(TWITCH_ID)
    await cog.config.twitch_client_secret.set(TWITCH_SECRET)
    await cog.config.youtube_api_key.set(YOUTUBE_KEY)
    if seed:
        guild = bot.guilds[0]
        await cog.configure(guild, channel_id=guild.id + 3, title_filter="DNP")
        await cog.add_source(guild, "twitch", "matters86")
        await cog.add_source(guild, "youtube", "@projektteam")
        fake.go_live("twitch:matters86")
        fake.go_live("youtube:" + YOUTUBE_ID, "video-1")
        await cog.poll_once()
    return wc, bot, wc.app, cog


async def make_role_app():
    """Browser-Demo: zwei Rollenstreams ohne Twitch-/YouTube-Zugangsdaten."""
    wc, bot, app, cog = await make_app()
    guild = bot.guilds[0]
    role = L.H.Role(guild, 1118, "Streamer", 3)
    guild.roles.append(role)
    for user_id, title, url in ((11, "DNP – Twitch Teamabend", "https://twitch.tv/matters86"),
                                (14, "DNP – YouTube Projektstream", "https://www.youtube.com/watch?v=ABCdef12345")):
        member = guild.get_member(user_id)
        member.roles.append(role)
        member.activities = (discord.Streaming(name=title, url=url),)
    for field in ("twitch_client_id", "twitch_client_secret", "youtube_api_key"):
        await getattr(cog.config, field).set("")
    await cog.configure(guild, channel_id=guild.id + 3, title_filter="DNP", watched_role_id=role.id)
    await cog.poll_once()
    return wc, bot, app, cog


if __name__ == "__main__":
    L.H.main(lambda: make_app(seed=True))
