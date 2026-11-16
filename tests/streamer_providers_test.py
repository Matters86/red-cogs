"""Stream-Provider: offizielle APIs, aktive Videos, Fehler und persistente Suchbudgets."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone

import aiohttp
import bootstrap  # temporäre Red-Instanz und rc-Paket
from rc.streamer.providers import (
    ProviderError, StreamAPI, TWITCH_TOKEN, YOUTUBE_SEARCH_BUDGET,
)


CHANNEL_A = "UC" + "A" * 22
CHANNEL_B = "UC" + "B" * 22
VIDEO_A = "video000001"
VIDEO_B = "video000002"
VIDEO_C = "video000003"
VIDEO_D = "video000004"
CREDS = {"twitch_client_id": "test-client", "twitch_client_secret": "secret-never-output",
         "youtube_api_key": "yt-key-never-output"}


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.tokens = 0
        self.twitch = {}
        self.search = {CHANNEL_A: [VIDEO_A], CHANNEL_B: []}
        self.videos = {}
        self.fail = {}
        self.before_search = None
        self.youtube_custom_url = "@DNPTeam"

    def video(self, identifier=VIDEO_A, *, channel=CHANNEL_A, mode="live", title="DNP live"):
        details = {"actualStartTime": "2026-11-16T10:00:00Z", "concurrentViewers": "42"}
        if mode == "ended":
            details["actualEndTime"] = "2026-11-16T11:00:00Z"
        if mode == "upcoming":
            details = {"scheduledStartTime": "2026-11-17T10:00:00Z"}
        self.videos[identifier] = {"id": identifier, "snippet": {"channelId": channel,
            "channelTitle": "DNP Team", "title": title,
            "liveBroadcastContent": "upcoming" if mode == "upcoming" else "none" if mode == "vod" else "live",
            "thumbnails": {"high": {"url": "https://i.ytimg.com/live.jpg"}}},
            "liveStreamingDetails": details}

    async def http(self, method, url, *, params=None, data=None, headers=None):
        params, headers = list(params or []), dict(headers or {})
        path = "token" if url == TWITCH_TOKEN else ("yt:" if "googleapis" in url else "tw:") + url.rsplit("/", 1)[-1]
        self.calls.append((path, params, headers, deepcopy(data)))
        if self.fail.get(path):
            return self.fail[path].pop(0)
        if path == "token":
            assert data["client_secret"] == CREDS["twitch_client_secret"]
            self.tokens += 1
            return 200, {}, {"access_token": f"token-{self.tokens}", "expires_in": 3600}
        query = dict(params)
        if path == "tw:users":
            return 200, {}, {"data": [{"id": "1", "login": query["login"], "display_name": "DNP Team"}]}
        if path == "tw:streams":
            logins = [v for k, v in params if k == "user_login"]
            assert len(logins) <= 100
            return 200, {}, {"data": [deepcopy(self.twitch[v]) for v in logins if v in self.twitch]}
        assert headers["X-Goog-Api-Key"] == CREDS["youtube_api_key"]
        assert "key" not in query
        if path == "yt:channels":
            channel = query.get("id", CHANNEL_A)
            snippet = {"title": "DNP Team"}
            if self.youtube_custom_url is not None:
                snippet["customUrl"] = self.youtube_custom_url
            return 200, {}, {"items": [{"id": channel, "snippet": snippet}]}
        if path == "yt:search":
            assert query["type"] == "video" and query["eventType"] == "live"
            if self.before_search:
                self.before_search()
            return 200, {}, {"items": [{"id": {"videoId": v}} for v in self.search[query["channelId"]]]}
        if path == "yt:videos":
            ids = query["id"].split(",")
            assert len(ids) <= 50
            return 200, {}, {"items": [deepcopy(self.videos[v]) for v in ids if v in self.videos]}
        raise AssertionError(path)


async def main():
    assert bootstrap.ROOT.is_dir()
    clock = [datetime(2026, 11, 16, 12, tzinfo=timezone.utc).timestamp()]
    stored = {}
    creds = deepcopy(CREDS)
    fake = FakeAPI()

    async def credentials():
        return deepcopy(creds)

    async def get_state():
        return deepcopy(stored)

    async def set_state(value):
        stored.clear()
        stored.update(deepcopy(value))

    def make_api():
        api = StreamAPI(credentials, clock=lambda: clock[0], youtube_state_get=get_state, youtube_state_set=set_state)
        api._http = fake.http
        return api

    api = make_api()
    checks = 0

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
        print("OK   " + message)

    async def denied(call, *, code=None):
        try:
            await call
        except ProviderError as error:
            assert all(value not in str(error) for value in CREDS.values())
            if code:
                assert error.code == code, (error.code, code)
            return error
        raise AssertionError("ProviderError erwartet")

    twitch = await api.resolve("twitch", "https://www.twitch.tv/DNP_Team?ref=example")
    check(twitch["key"] == "twitch:dnp_team" and twitch["identifier"] == "dnp_team", "Twitch-Link wird kanonisch aufgelöst")
    youtube = await api.resolve("youtube", "https://www.youtube.com/@DNPTeam")
    check(youtube["key"] == "youtube:" + CHANNEL_A, "YouTube-Handle wird über channels auf die stabile Kanal-ID aufgelöst")
    check(youtube.get("handles") == ["@dnpteam"], "Öffentlicher YouTube-Handle wird aus vorhandenem Kanal-Snippet ohne weitere Anfrage übernommen")
    for custom_url in (None, "alter-custom-url-name", "https://youtube.com/@DNPTeam", "@bad/path"):
        fake.youtube_custom_url = custom_url
        assert "handles" not in await api.resolve("youtube", CHANNEL_A)
    fake.youtube_custom_url = "@DNPTeam"
    check(True, "Fehlende oder ungeeignete Custom-URLs erzeugen keinen Handle-Alias")
    assert (await api.resolve("youtube", "https://youtube.com/channel/" + CHANNEL_A))["identifier"] == CHANNEL_A
    for channel_path in ("@DNPTeam", "channel/" + CHANNEL_A):
        for tab in ("streams", "videos", "featured", "live"):
            result = await api.resolve("youtube", "https://youtube.com/" + channel_path + "/" + tab)
            assert result["identifier"] == CHANNEL_A
    check(True, "YouTube-Kanallinks aus Streams-, Videos-, Featured- und Live-Reitern werden erkannt")
    before = len(fake.calls)
    for provider, raw in (("twitch", "https://evil.example/name"), ("youtube", "https://evil.example/@name"),
                          ("youtube", "https://youtube.com:bad/@name"), ("youtube", "https://youtube.com/watch?v=secret"),
                          ("youtube", "https://youtube.com/@name/unknown"),
                          ("youtube", "https://youtube.com/@name/videos/streams"),
                          ("youtube", "https://youtube.com/user/legacy"), ("other", "name")):
        await denied(api.resolve(provider, raw), code="input")
    check(len(fake.calls) == before, "Fremde URLs, ungültige Ports und ungeeignete YouTube-Links erzeugen keinen Netzaufruf")
    check(all("key" not in dict(params) for path, params, _headers, _data in fake.calls if path.startswith("yt:")),
          "YouTube-Key wird ausschließlich als Header übertragen")

    fake.twitch["dnp_team"] = {"id": "stream-1", "user_login": "dnp_team", "user_name": "DNP Team", "type": "live",
        "title": "dnp Rollenspiel", "game_name": "GTA V", "viewer_count": 50,
        "thumbnail_url": "https://static-cdn.jtvnw.net/live-{width}x{height}.jpg", "started_at": "2026-11-16T10:00:00Z"}
    rows = await api.streams("twitch", {twitch["key"]: twitch})
    check(rows[twitch["key"]][0]["title"] == "dnp Rollenspiel"
          and "1280x720" in rows[twitch["key"]][0]["thumbnail"], "Twitch-Live-Daten sind normalisiert und ungefiltert")
    fake.twitch.clear()
    check(await api.streams("twitch", {twitch["key"]: twitch}) == {twitch["key"]: []}, "Nur gültige leere Twitch-Antwort bedeutet offline")
    many = {f"twitch:user{i:03}": {"identifier": f"user{i:03}", "provider": "twitch"} for i in range(105)}
    before = len(fake.calls)
    await api.streams("twitch", many)
    check(sum(path == "tw:streams" for path, *_ in fake.calls[before:]) == 2, "Twitch bündelt mehr als 100 Kanäle in passende Anfragen")

    fake.fail["tw:streams"] = [(401, {}, {"message": "secret-never-output"})]
    token_before = fake.tokens
    await api.streams("twitch", {twitch["key"]: twitch})
    check(fake.tokens == token_before + 1, "Twitch 401 erneuert den Token genau einmal")
    fake.fail["tw:streams"] = [(401, {}, {}), (401, {}, {"message": CREDS["twitch_client_secret"]})]
    await denied(api.streams("twitch", {twitch["key"]: twitch}), code="credentials")
    for body in ({}, {"data": None}, {"data": [None]}, {"data": [{"id": "partial"}]}):
        fake.fail["tw:streams"] = [(200, {}, body)]
        await denied(api.streams("twitch", {twitch["key"]: twitch}))
    check(True, "Unvollständige Twitch-Antworten und dauerhafte Auth-Fehler werden niemals zu offline")
    fake.fail["tw:streams"] = [(429, {"Retry-After": "60"}, {"message": CREDS["twitch_client_secret"]})]
    await denied(api.streams("twitch", {twitch["key"]: twitch}), code="rate_limit")
    before = len(fake.calls)
    await denied(api.streams("twitch", {twitch["key"]: twitch}), code="backoff")
    check(len(fake.calls) == before, "Twitch-Rate-Limit wird vor weiteren Netzaufrufen beachtet")
    clock[0] += 61
    await api.streams("twitch", {twitch["key"]: twitch})

    fake.search[CHANNEL_A] = [VIDEO_A, VIDEO_B, VIDEO_C, VIDEO_D]
    fake.video(VIDEO_A)
    fake.video(VIDEO_B, mode="upcoming")
    fake.video(VIDEO_C, mode="ended")
    fake.video(VIDEO_D, mode="vod")
    fake.before_search = lambda: check(stored.get("used") == 1, "YouTube-Suche wird vor dem Netzaufruf persistent reserviert")
    yts = {youtube["key"]: youtube}
    rows = await api.streams("youtube", yts)
    fake.before_search = None
    check([row["id"] for row in rows[youtube["key"]]] == [VIDEO_A], "YouTube zeigt nur tatsächlich gestartete und noch laufende Videos")
    check(api.youtube_status["discovery_interval"] == 1800 and stored["candidates"][youtube["key"]] == [VIDEO_A],
          "Discovery startet mit 30 Minuten und behält ausschließlich aktive Kandidaten")
    before = len(fake.calls)
    clock[0] += 60
    fake.video(VIDEO_A, title="Titel wurde auf dnp geändert")
    rows = await api.streams("youtube", yts)
    check(rows[youtube["key"]][0]["title"] == "Titel wurde auf dnp geändert"
          and [path for path, *_ in fake.calls[before:]] == ["yt:videos"], "Bekannte YouTube-Lives und Titel werden ohne neue Suche bei jedem Poll geprüft")

    restarted = make_api()
    before = len(fake.calls)
    await restarted.streams("youtube", yts, known={youtube["key"]: [VIDEO_A]})
    check([path for path, *_ in fake.calls[before:]] == ["yt:videos"] and stored["used"] == 1,
          "Neustart erhält Suchzeitpunkte, Kandidaten und verbrauchtes Kontingent")

    stored["used"] = YOUTUBE_SEARCH_BUDGET
    clock[0] += 3600
    fake.video(VIDEO_A, mode="ended")
    before = len(fake.calls)
    rows = await restarted.streams("youtube", yts, known={youtube["key"]: [VIDEO_A]})
    check(rows == {youtube["key"]: []} and [path for path, *_ in fake.calls[before:]] == ["yt:videos"]
          and restarted.youtube_status["warning"], "Verbrauchtes Suchbudget stoppt nicht die Offline-Erkennung bekannter Streams")
    clock[0] += 86400
    fake.video(VIDEO_A)
    rows = await restarted.streams("youtube", yts)
    check(stored["used"] == 1 and rows[youtube["key"]], "Suchbudget wird am neuen pazifischen Kontingent-Tag erneuert")

    # Auch ein von Google gemeldetes Suchlimit darf laufende Videos weiter prüfen.
    clock[0] += 1801
    fake.fail["yt:search"] = [(403, {}, {"error": {"errors": [{"reason": "quotaExceeded"}]}})]
    fake.video(VIDEO_A, mode="ended")
    rows = await restarted.streams("youtube", yts, known={youtube["key"]: [VIDEO_A]})
    check(rows == {youtube["key"]: []} and stored["search_blocked_until"] > clock[0]
          and restarted.youtube_status["warning"], "Googles Suchkontingent-403 lässt die Detailprüfung und Offline-Erkennung weiterlaufen")

    fake.video(VIDEO_A)
    for body in ({}, {"items": None}, {"items": [None]}, {"items": [{"id": VIDEO_A}]}):
        fake.fail["yt:videos"] = [(200, {}, body)]
        await denied(restarted.streams("youtube", yts, known={youtube["key"]: [VIDEO_A]}))
    fake.fail["yt:videos"] = [(500, {}, {"error": CREDS["youtube_api_key"]})]
    await denied(restarted.streams("youtube", yts, known={youtube["key"]: [VIDEO_A]}))
    fake.videos[VIDEO_A]["liveStreamingDetails"]["actualEndTime"] = "kein-zeitstempel"
    await denied(restarted.streams("youtube", yts, known={youtube["key"]: [VIDEO_A]}))
    check(True, "Ungültige YouTube-Videodaten und 5xx sind Fehler statt Offline-Antworten; Secrets bleiben verborgen")

    creds["youtube_api_key"] = ""
    before = len(fake.calls)
    await denied(restarted.streams("youtube", yts), code="credentials")
    check(len(fake.calls) == before, "Fehlender YouTube-Key erzeugt keine Anfrage")
    creds.update(CREDS)
    token_before = fake.tokens
    api.reset_credentials()
    await api.streams("twitch", {twitch["key"]: twitch})
    check(fake.tokens == token_before + 1, "Geänderte Zugangsdaten verwerfen den gecachten Twitch-Token")

    class FailedSession:
        closed = False

        def request(self, *args, **kwargs):
            raise aiohttp.ClientError(CREDS["youtube_api_key"])

        async def close(self):
            self.closed = True

    network_api = make_api()
    network_api._http = StreamAPI._http.__get__(network_api, StreamAPI)
    network_api._session = FailedSession()
    await denied(network_api._http("GET", "https://www.googleapis.com/youtube/v3/videos"))
    check(True, "Transportfehler geben weder Original-URL noch Schlüssel weiter")
    await api.close()
    await restarted.close()
    await network_api.close()
    print(f"\n{checks} Streamer-Provider-Prüfungen bestanden.")


if __name__ == "__main__":
    asyncio.run(main())
