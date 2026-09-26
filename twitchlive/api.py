"""Schlanker Twitch-Helix-Client (App-Access-Token per Client-Credentials).

* Token wird im Speicher gecacht (nie in Config/Logs) und kurz vor Ablauf erneuert.
* Bei ``401`` wird der Token genau einmal erneuert und die Anfrage wiederholt.
* ``429`` -> :class:`RateLimited` (mit Sekunden bis zum Reset), 5xx/Netzwerk -> :class:`TwitchError`.
* Client-ID/Secret werden im **Body** an den Token-Endpunkt geschickt (nicht in der URL),
  damit sie in keiner Fehlermeldung/URL auftauchen. Exceptions tragen nur Statuscodes.

Der gesamte Netzverkehr läuft über :meth:`TwitchAPI._http` – Tests ersetzen genau diese
Methode und brauchen so kein echtes Netz.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger("red.red-cogs.twitchlive")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix"
MAX_PER_REQUEST = 100


class TwitchError(Exception):
    """Vorübergehender Fehler (Netzwerk, 5xx, unerwartete Antwort)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RateLimited(TwitchError):
    def __init__(self, retry_after: float):
        super().__init__(f"Twitch-Rate-Limit (Reset in {retry_after:.0f} s)", 429)
        self.retry_after = retry_after


class AuthError(TwitchError):
    """Client-ID/Secret ungültig oder Token wird dauerhaft abgelehnt."""


class NoCredentials(TwitchError):
    pass


def chunks(items: list, size: int = MAX_PER_REQUEST):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class TwitchAPI:
    def __init__(self, credentials: Callable[[], Awaitable[tuple[str, str]]], *, clock=time.time):
        self._credentials = credentials
        self._clock = clock
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()
        self._session: aiohttp.ClientSession | None = None
        self.token_requests = 0

    # ------------------------------------------------------------------ #
    #  HTTP (in Tests ersetzt)
    # ------------------------------------------------------------------ #
    async def _http(self, method: str, url: str, *, params=None, data=None, headers=None):
        """-> (status, headers, json|None). Wirft TwitchError bei Netzwerkfehlern."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        try:
            async with self._session.request(method, url, params=params, data=data, headers=headers) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:  # noqa: BLE001 – kaputtes/leeres JSON
                    body = None
                return resp.status, dict(resp.headers), body
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # Bewusst nur der Typ – aiohttp-Meldungen können URLs enthalten.
            raise TwitchError(f"Netzwerkfehler ({type(exc).__name__})") from None

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def reset_token(self):
        self._token = None
        self._token_expires = 0.0

    @property
    def has_token(self) -> bool:
        return bool(self._token) and self._clock() < self._token_expires

    # ------------------------------------------------------------------ #
    #  Token
    # ------------------------------------------------------------------ #
    async def get_token(self, *, force: bool = False) -> str:
        async with self._token_lock:
            if not force and self.has_token:
                return self._token  # type: ignore[return-value]
            client_id, secret = await self._credentials()
            if not client_id or not secret:
                raise NoCredentials("Keine Twitch-Zugangsdaten gesetzt")
            self.token_requests += 1
            status, headers, body = await self._http(
                "POST", TOKEN_URL,
                data={"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"},
            )
            if status in (400, 401, 403):
                self.reset_token()
                raise AuthError("Twitch lehnt Client-ID/Secret ab", status)
            if status == 429:
                raise RateLimited(_retry_after(headers, self._clock()))
            if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
                raise TwitchError(f"Token-Abruf fehlgeschlagen (HTTP {status})", status)
            self._token = str(body["access_token"])
            expires_in = int(body.get("expires_in") or 3600)
            # 5 min Puffer, damit der Token nicht mitten in einer Anfrage abläuft.
            self._token_expires = self._clock() + max(60, expires_in - 300)
            return self._token

    # ------------------------------------------------------------------ #
    #  Helix
    # ------------------------------------------------------------------ #
    async def helix(self, path: str, params) -> dict:
        client_id, _ = await self._credentials()
        retried = False
        while True:
            token = await self.get_token(force=retried)
            status, headers, body = await self._http(
                "GET", f"{HELIX}/{path}", params=params,
                headers={"Client-Id": client_id, "Authorization": f"Bearer {token}"},
            )
            if status == 401 and not retried:
                log.info("Twitch-Token abgelehnt (401) – wird einmal erneuert")
                self.reset_token()
                retried = True
                continue
            if status == 401:
                self.reset_token()
                raise AuthError("Twitch lehnt den erneuerten Token ab", 401)
            if status == 429:
                raise RateLimited(_retry_after(headers, self._clock()))
            if status != 200 or not isinstance(body, dict):
                raise TwitchError(f"Twitch-API antwortet mit HTTP {status}", status)
            return body

    async def streams(self, logins: list[str]) -> dict[str, dict]:
        """Live-Streams der Logins -> {login: stream}. Nur ``type == live``."""
        out: dict[str, dict] = {}
        for part in chunks(sorted(set(logins))):
            params = [("user_login", login) for login in part] + [("first", str(MAX_PER_REQUEST))]
            body = await self.helix("streams", params)
            for s in body.get("data") or []:
                if not isinstance(s, dict) or (s.get("type") or "live") != "live":
                    continue
                login = str(s.get("user_login") or "").lower()
                if login:
                    out[login] = s
        return out

    async def users(self, logins: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for part in chunks(sorted(set(logins))):
            body = await self.helix("users", [("login", login) for login in part])
            for u in body.get("data") or []:
                if isinstance(u, dict) and u.get("login"):
                    out[str(u["login"]).lower()] = u
        return out


def _retry_after(headers: dict | None, now: float) -> float:
    """Sekunden bis zum Reset aus ``Ratelimit-Reset`` (Unix-Zeit) oder ``Retry-After``."""
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    try:
        reset = float(headers.get("ratelimit-reset"))
        return max(1.0, min(900.0, reset - now))
    except (TypeError, ValueError):
        pass
    try:
        return max(1.0, min(900.0, float(headers.get("retry-after"))))
    except (TypeError, ValueError):
        return 60.0
