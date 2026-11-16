"""Twitch/YouTube über ihre offiziellen APIs, ohne Abhängigkeit auf andere Cogs.

YouTube trennt die Suche nach neuen Lives von der Prüfung bekannter Videos:
bekannte IDs werden bei jedem Poll geprüft, neue Lives standardmäßig alle 30
Minuten gesucht (bei vielen Kanälen entsprechend seltener). Maximal 80 Suchen
pro Tag lassen Puffer im separaten Search-Queries-Kontingent. Reservierungen,
Suchzeitpunkte und Kandidaten überleben bei gesetzten State-Callbacks Neustarts.
API-Ausfälle sind keine Offline-Meldung; nur gültige Antworten dürfen [] liefern.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import math
import re
import time
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import aiohttp


TWITCH_TOKEN = "https://id.twitch.tv/oauth2/token"
TWITCH_HELIX = "https://api.twitch.tv/helix"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_SEARCH_BUDGET = 80
YOUTUBE_DISCOVERY_MIN = 1800
_LOGIN = re.compile(r"[a-z0-9_]{3,25}\Z")
_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
_VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_HANDLE = re.compile(r"@[^\s/@?#\\:]{3,30}\Z")


class ProviderError(Exception):
    """Öffentlich anzeigbarer Fehler: niemals API-Antworttexte oder Secrets."""

    def __init__(self, message: str, *, retry_after: float = 60, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.retry_after = max(1, min(86400, float(retry_after)))
        self.code = code


def _parts(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _retry(headers, now):
    values = {str(k).lower(): v for k, v in (headers or {}).items()}
    try:
        return max(1, min(900, float(values["ratelimit-reset"]) - now))
    except (KeyError, TypeError, ValueError):
        try:
            return max(1, min(900, float(values.get("retry-after", 60))))
        except (TypeError, ValueError):
            return 60


def _list(body, name, provider):
    if not isinstance(body, dict) or not isinstance(body.get(name), list):
        raise ProviderError(f"{provider} liefert eine unvollständige Antwort.")
    if not all(isinstance(item, dict) for item in body[name]):
        raise ProviderError(f"{provider} liefert eine ungültige Antwort.")
    return body[name]


def _timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _input(raw, hosts):
    raw = str(raw or "").strip()
    if len(raw) > 300:
        raise ProviderError("Der Kanal-Link ist zu lang.", code="input")
    if "://" in raw or "/" in raw:
        try:
            parsed = urlsplit(raw if "://" in raw else "https://" + raw)
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname in hosts
                     and not parsed.username and not parsed.password and parsed.port is None)
        except ValueError:
            valid = False
        if not valid:
            raise ProviderError("Bitte einen gültigen Twitch- oder YouTube-Kanallink verwenden.", code="input")
        return unquote(parsed.path).strip("/")
    return raw


class StreamAPI:
    def __init__(self, credentials, *, clock=time.time, youtube_state_get=None, youtube_state_set=None):
        self._credentials = credentials
        self._clock = clock
        self._youtube_state_get = youtube_state_get
        self._youtube_state_set = youtube_state_set
        self._youtube_memory = {}
        self._session = None
        self._token = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()
        self._youtube_lock = asyncio.Lock()
        self._blocked = {}
        self.youtube_status = {}

    async def _http(self, method, url, *, params=None, data=None, headers=None):
        """Einzige Netzgrenze; Tests ersetzen sie durch einen Fake."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        try:
            async with self._session.request(method, url, params=params, data=data, headers=headers) as response:
                try:
                    body = await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    body = None
                return response.status, dict(response.headers), body
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ProviderError("Die Streaming-Plattform ist vorübergehend nicht erreichbar.") from None

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def reset_credentials(self):
        self._token = None
        self._token_expires = 0.0
        self._blocked.clear()

    def _check_backoff(self, provider):
        wait = float(self._blocked.get(provider, 0)) - self._clock()
        if wait > 0:
            raise ProviderError(f"{provider} pausiert nach einem API-Fehler kurz.", retry_after=wait, code="backoff")

    async def _twitch_token(self, *, force=False):
        async with self._token_lock:
            if not force and self._token and self._clock() < self._token_expires:
                return self._token
            credentials = await self._credentials()
            cid, secret = credentials.get("twitch_client_id"), credentials.get("twitch_client_secret")
            if not cid or not secret:
                raise ProviderError("Twitch-Zugangsdaten fehlen.", code="credentials")
            status, headers, body = await self._http("POST", TWITCH_TOKEN, data={
                "client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
            if status != 200 or not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
                if status == 429:
                    delay = _retry(headers, self._clock())
                    self._blocked["Twitch"] = self._clock() + delay
                    raise ProviderError("Twitch begrenzt die Anfragen vorübergehend.", retry_after=delay, code="rate_limit")
                if status in {400, 401, 403}:
                    raise ProviderError("Twitch-Zugangsdaten sind ungültig.", code="credentials")
                raise ProviderError("Der Twitch-Zugang ist vorübergehend nicht erreichbar.")
            try:
                lifetime = int(body["expires_in"])
            except (KeyError, TypeError, ValueError):
                raise ProviderError("Twitch liefert einen ungültigen Zugangstoken.") from None
            if not body["access_token"] or lifetime <= 0:
                raise ProviderError("Twitch liefert einen ungültigen Zugangstoken.")
            self._token = body["access_token"]
            self._token_expires = self._clock() + max(1, lifetime - min(300, lifetime / 2))
            return self._token

    async def _twitch(self, path, params):
        self._check_backoff("Twitch")
        credentials = await self._credentials()
        if not credentials.get("twitch_client_id") or not credentials.get("twitch_client_secret"):
            raise ProviderError("Twitch-Zugangsdaten fehlen.", code="credentials")
        for attempt in range(2):
            token = await self._twitch_token(force=attempt == 1)
            status, headers, body = await self._http("GET", f"{TWITCH_HELIX}/{path}", params=params,
                headers={"Client-Id": credentials["twitch_client_id"], "Authorization": "Bearer " + token})
            if status == 401 and attempt == 0:
                self._token = None
                continue
            if status == 429:
                delay = _retry(headers, self._clock())
                self._blocked["Twitch"] = self._clock() + delay
                raise ProviderError("Twitch begrenzt die Anfragen vorübergehend.", retry_after=delay, code="rate_limit")
            if status in {401, 403}:
                raise ProviderError("Twitch lehnt die Zugangsdaten ab.", code="credentials")
            if status != 200:
                raise ProviderError(f"Twitch ist vorübergehend nicht erreichbar (HTTP {status}).")
            return _list(body, "data", "Twitch")
        raise ProviderError("Twitch lehnt den erneuerten Zugangstoken ab.", code="credentials")

    async def _youtube(self, path, params):
        self._check_backoff("YouTube")
        credentials = await self._credentials()
        key = credentials.get("youtube_api_key")
        if not key:
            raise ProviderError("YouTube-API-Schlüssel fehlt.", code="credentials")
        # Der Schlüssel steht im Header und erscheint weder in URLs noch Fehlermeldungen.
        status, headers, body = await self._http("GET", f"{YOUTUBE_API}/{path}", params=params,
                                               headers={"X-Goog-Api-Key": key})
        if status == 429:
            delay = _retry(headers, self._clock())
            self._blocked["YouTube"] = self._clock() + delay
            raise ProviderError("YouTube begrenzt die Anfragen vorübergehend.", retry_after=delay, code="rate_limit")
        if status == 403:
            error = body.get("error") if isinstance(body, dict) else None
            errors = error.get("errors") if isinstance(error, dict) else None
            quota = isinstance(errors, list) and any(isinstance(e, dict) and e.get("reason") in {
                "quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"} for e in errors)
            if quota:
                raise ProviderError("Das YouTube-API-Kontingent ist aufgebraucht.", code="quota")
        if status in {400, 401, 403}:
            raise ProviderError("YouTube lehnt den API-Schlüssel oder die Anfrage ab.", code="credentials")
        if status != 200:
            raise ProviderError(f"YouTube ist vorübergehend nicht erreichbar (HTTP {status}).")
        return _list(body, "items", "YouTube")

    async def resolve(self, provider, raw):
        provider = str(provider or "").strip().lower()
        if provider == "twitch":
            login = _input(raw, {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}).lstrip("@").lower()
            if not _LOGIN.fullmatch(login):
                raise ProviderError("Bitte einen Twitch-Kanalnamen oder Twitch-Kanallink eingeben.", code="input")
            users = await self._twitch("users", [("login", login)])
            matches = [u for u in users if u.get("login") == login and isinstance(u.get("id"), str)]
            if not matches:
                raise ProviderError("Dieser Twitch-Kanal wurde nicht gefunden.", code="input")
            return {"provider": provider, "identifier": login, "name": str(matches[0].get("display_name") or login),
                    "key": f"twitch:{login}"}
        if provider == "youtube":
            value = _input(raw, {"youtube.com", "www.youtube.com", "m.youtube.com"})
            # Kanal-Links werden häufig aus einem bestimmten Reiter kopiert.
            # Nur bekannte letzte Tabs entfernen; weitere Pfadteile bleiben ungültig.
            if "/" in value and value.rsplit("/", 1)[-1] in {"streams", "videos", "featured", "live"}:
                value = value.rsplit("/", 1)[0]
            if value.startswith("channel/"):
                value = value[len("channel/"):]
            if _CHANNEL.fullmatch(value):
                query = ("id", value)
            elif _HANDLE.fullmatch(value):
                query = ("forHandle", value)
            else:
                raise ProviderError("Bitte eine YouTube-Kanal-ID (UC…), einen @Handle oder den zugehörigen Kanallink eingeben.", code="input")
            channels = await self._youtube("channels", [("part", "snippet"), query])
            matches = [c for c in channels if _CHANNEL.fullmatch(str(c.get("id") or ""))]
            if not matches:
                raise ProviderError("Dieser YouTube-Kanal wurde nicht gefunden.", code="input")
            channel = matches[0]
            if query[0] == "id" and channel["id"] != value:
                raise ProviderError("YouTube liefert einen anderen Kanal als angefordert.")
            snippet = channel.get("snippet")
            if not isinstance(snippet, dict) or not isinstance(snippet.get("title"), str):
                raise ProviderError("YouTube liefert unvollständige Kanaldaten.")
            source = {"provider": provider, "identifier": channel["id"], "name": snippet["title"],
                      "key": f"youtube:{channel['id']}"}
            custom_url = snippet.get("customUrl")
            if isinstance(custom_url, str) and _HANDLE.fullmatch(custom_url):
                source["handles"] = [custom_url.casefold()]
            return source
        raise ProviderError("Bitte Twitch oder YouTube als Plattform wählen.", code="input")

    async def streams(self, provider, sources, *, known=None):
        if not sources:
            return {}
        if provider == "twitch":
            return await self._twitch_streams(sources)
        if provider == "youtube":
            async with self._youtube_lock:
                return await self._youtube_streams(sources, known or {})
        raise ProviderError("Unbekannte Streaming-Plattform.", code="input")

    async def _twitch_streams(self, sources):
        by_login = {str(source["identifier"]): key for key, source in sources.items()}
        out = {key: [] for key in sources}
        for part in _parts(sorted(by_login), 100):
            rows = await self._twitch("streams", [("user_login", login) for login in part] + [("first", "100")])
            for stream in rows:
                if (not isinstance(stream.get("id"), str) or not stream["id"]
                        or not isinstance(stream.get("user_login"), str)
                        or not isinstance(stream.get("title"), str)
                        or not isinstance(stream.get("type"), str)):
                    raise ProviderError("Twitch liefert unvollständige Streamdaten.")
                login = stream["user_login"].lower()
                if login not in part or stream["type"] != "live":
                    continue
                key = by_login[login]
                thumbnail = str(stream.get("thumbnail_url") or "").replace("{width}", "1280").replace("{height}", "720")
                out[key].append({"id": stream["id"], "provider": "twitch", "source_key": key,
                    "name": str(stream.get("user_name") or sources[key].get("name") or login),
                    "title": stream["title"], "url": f"https://www.twitch.tv/{login}", "thumbnail": thumbnail,
                    "game": str(stream.get("game_name") or ""), "viewers": self._viewers(stream.get("viewer_count")),
                    "started_at": str(stream.get("started_at") or "")})
        return out

    @staticmethod
    def _viewers(value):
        try:
            return max(0, int(value))
        except (ValueError, TypeError):
            return 0

    async def _load_youtube_state(self):
        state = await self._youtube_state_get() if self._youtube_state_get else self._youtube_memory
        state = deepcopy(state) if isinstance(state, dict) else {}
        now = datetime.fromtimestamp(self._clock(), ZoneInfo("America/Los_Angeles"))
        day = now.strftime("%Y-%m-%d")
        if state.get("day") != day:
            state.update(day=day, used=0, search_blocked_until=0)
        for name in ("last_search", "candidates"):
            if not isinstance(state.get(name), dict):
                state[name] = {}
        try:
            state["used"] = max(0, int(state.get("used") or 0))
        except (ValueError, TypeError):
            state["used"] = YOUTUBE_SEARCH_BUDGET
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return state, midnight

    async def _save_youtube_state(self, state):
        if self._youtube_state_set:
            await self._youtube_state_set(deepcopy(state))
        self._youtube_memory = deepcopy(state)

    async def _youtube_streams(self, sources, known):
        credentials = await self._credentials()
        if not credentials.get("youtube_api_key"):
            raise ProviderError("YouTube-API-Schlüssel fehlt.", code="credentials")
        state, midnight = await self._load_youtube_state()
        now = self._clock()
        interval = max(YOUTUBE_DISCOVERY_MIN, math.ceil(len(sources) * 86400 / YOUTUBE_SEARCH_BUDGET))
        warning = ""
        due = []
        for key in sources:
            last = state["last_search"].get(key)
            if not isinstance(last, (int, float)) or now - last >= interval:
                due.append(key)
        # Nie abgefragte und am längsten wartende Kanäle zuerst.
        due.sort(key=lambda key: (state["last_search"].get(key, float("-inf")), key))
        for key in due:
            if state["used"] >= YOUTUBE_SEARCH_BUDGET or now < float(state.get("search_blocked_until") or 0):
                warning = "YouTube-Live-Suche pausiert bis zum nächsten Kontingent-Tag; bekannte Streams werden weiter geprüft."
                break
            # VOR der Anfrage reservieren: auch Fehler/Neustarts dürfen das Kontingent nicht umgehen.
            state["used"] += 1
            state["last_search"][key] = now
            await self._save_youtube_state(state)
            try:
                rows = await self._youtube("search", [("part", "snippet"), ("type", "video"),
                    ("eventType", "live"), ("channelId", sources[key]["identifier"]), ("maxResults", "50")])
            except ProviderError as error:
                if error.code != "quota":
                    raise
                state["search_blocked_until"] = midnight
                await self._save_youtube_state(state)
                warning = "YouTube-Live-Suchkontingent aufgebraucht; bekannte Streams werden weiter geprüft."
                break
            candidates = []
            for row in rows:
                identifier = row.get("id")
                video_id = identifier.get("videoId") if isinstance(identifier, dict) else None
                if not isinstance(video_id, str) or not _VIDEO.fullmatch(video_id):
                    raise ProviderError("YouTube liefert unvollständige Suchergebnisse.")
                candidates.append(video_id)
            previous = state["candidates"].get(key)
            previous = previous if isinstance(previous, list) else []
            state["candidates"][key] = list(dict.fromkeys(previous + candidates))
            await self._save_youtube_state(state)

        # Nicht auf die Suchantwort allein vertrauen: IDs immer über Videos prüfen.
        # IDs aus persistenten Meldungen sichern die Offline-Erkennung nach Neustart.
        ids = set()
        for key in sources:
            cached = state["candidates"].get(key) or []
            ids.update(v for v in cached if isinstance(v, str) and _VIDEO.fullmatch(v))
            ids.update(v for v in known.get(key, []) if isinstance(v, str) and _VIDEO.fullmatch(v))
        out = {key: [] for key in sources}
        by_channel = {source["identifier"]: key for key, source in sources.items()}
        active = {key: [] for key in sources}
        for part in _parts(sorted(ids), 50):
            rows = await self._youtube("videos", [("part", "snippet,liveStreamingDetails"), ("id", ",".join(part))])
            for video in rows:
                video_id, snippet = video.get("id"), video.get("snippet")
                if (not isinstance(video_id, str) or video_id not in part or not isinstance(snippet, dict)
                        or not isinstance(snippet.get("channelId"), str)
                        or not isinstance(snippet.get("title"), str)
                        or not isinstance(snippet.get("liveBroadcastContent"), str)):
                    raise ProviderError("YouTube liefert unvollständige Videodaten.")
                key = by_channel.get(snippet["channelId"])
                if key is None:
                    raise ProviderError("YouTube liefert Videodaten eines anderen Kanals.")
                details = video.get("liveStreamingDetails")
                if snippet["liveBroadcastContent"] != "live":
                    continue
                if not isinstance(details, dict) or not _timestamp(details.get("actualStartTime")):
                    raise ProviderError("YouTube liefert unvollständige Live-Daten.")
                if details.get("actualEndTime"):
                    if not _timestamp(details["actualEndTime"]):
                        raise ProviderError("YouTube liefert ungültige Live-Zeitstempel.")
                    continue
                thumbnails = snippet.get("thumbnails") or {}
                image = next((thumbnails[size].get("url", "") for size in ("maxres", "standard", "high", "medium", "default")
                              if isinstance(thumbnails.get(size), dict)), "") if isinstance(thumbnails, dict) else ""
                out[key].append({"id": video_id, "provider": "youtube", "source_key": key,
                    "name": str(snippet.get("channelTitle") or sources[key].get("name") or snippet["channelId"]),
                    "title": snippet["title"], "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail": str(image), "game": "", "viewers": self._viewers(details.get("concurrentViewers")),
                    "started_at": str(details["actualStartTime"])})
                active[key].append(video_id)
        # Beendete/entfernte Videos nicht endlos abfragen; Live-IDs bleiben auch ohne Titeltreffer erhalten.
        for key in sources:
            state["candidates"][key] = list(dict.fromkeys(active[key]))
        await self._save_youtube_state(state)
        next_times = [float(state["last_search"].get(key, now - interval)) + interval for key in sources]
        next_search = max(now, min(next_times)) if next_times else None
        if state["used"] >= YOUTUBE_SEARCH_BUDGET or now < float(state.get("search_blocked_until") or 0):
            warning = warning or "YouTube-Live-Suche pausiert bis zum nächsten Kontingent-Tag; bekannte Streams werden weiter geprüft."
            next_search = max(next_search or midnight, midnight)
        self.youtube_status = {"discovery_interval": interval, "remaining_searches": max(0, YOUTUBE_SEARCH_BUDGET - state["used"]),
            "next_search": next_search, "warning": warning}
        return out
