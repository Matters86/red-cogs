"""One-attempt Discord creates; the SDK retries some non-idempotent POSTs.

Uses only the already logged-in bot's in-memory HTTP context, never config files.
Unknown session shape fails closed. Never logs headers, tokens or response bodies.
The two fixed Discord v10 routes are not caller-controlled URLs.
"""
import math
import re
import time
from types import SimpleNamespace
from urllib.parse import quote

import discord


class CreateRejected(Exception):
    definitive_rejection = True

    def __init__(self, status):
        super().__init__("discord_create_rejected")
        self.status = status


class CreateDeferred(Exception):
    request_not_sent = True


class SingleAttemptCreates:
    def __init__(self, bot):
        self.bot = bot
        self.delays = {}
        self.global_until = 0

    @staticmethod
    def delay(value, default=60):
        try:
            result = float(value)
            return result if math.isfinite(result) and 0 <= result <= 86400 else default
        except (ValueError, TypeError):
            return default

    def available(self):
        return time.monotonic() >= self.global_until

    @staticmethod
    def overwrites(values):
        result = []
        for target, overwrite in values.items():
            allow, deny = overwrite.pair()
            result.append({"id": str(target.id), "type": 0 if isinstance(target, discord.Role) else 1,
                           "allow": str(allow.value), "deny": str(deny.value)})
        return result

    async def post(self, guild, endpoint, payload):
        import aiohttp  # Already a dependency of the existing Cog; tests inject a fake.
        if endpoint not in ("roles", "channels") or not re.fullmatch(r"[1-9][0-9]{16,19}", str(guild.id)):
            raise CreateDeferred("unsupported_create_route")
        http = getattr(self.bot, "http", None)
        session = getattr(http, "_HTTPClient__session", None)
        token = getattr(http, "token", None)
        global_gate = getattr(http, "_global_over", None)
        if session is None or getattr(session, "closed", True) or not isinstance(token, str) or not token:
            raise CreateDeferred("single_attempt_transport_unavailable")
        route = str(guild.id) + ":" + endpoint
        if (not self.available() or time.monotonic() < self.delays.get(route, 0)
                or global_gate is None or not global_gate.is_set()):
            raise CreateDeferred("discord_rate_wait")
        headers = {"Authorization": "Bot " + token, "Content-Type": "application/json",
                   "User-Agent": getattr(http, "user_agent", "DNP-Faction-Discord/1"),
                   "X-Audit-Log-Reason": quote("DNP Fraktion: einmalige Erstellung", safe="")}
        kwargs = {"json": payload, "headers": headers, "allow_redirects": False,
                  "timeout": aiohttp.ClientTimeout(total=15)}
        if getattr(http, "proxy", None) is not None:
            kwargs["proxy"] = http.proxy
        if getattr(http, "proxy_auth", None) is not None:
            kwargs["proxy_auth"] = http.proxy_auth
        # Intentionally one HTTP attempt. No SDK request retry loop for creates.
        async with session.request("POST", "https://discord.com/api/v10/guilds/" + str(guild.id) + "/" + endpoint, **kwargs) as response:
            if response.headers.get("X-RateLimit-Remaining") == "0":
                self.delays[route] = time.monotonic() + self.delay(response.headers.get("X-RateLimit-Reset-After"))
            if response.status == 429:
                try:
                    data = await response.json()
                except Exception:
                    data = {}
                wait = max(1, self.delay(data.get("retry_after") if isinstance(data, dict) else None))
                self.delays[route] = time.monotonic() + wait
                if isinstance(data, dict) and data.get("global") is True:
                    self.global_until = time.monotonic() + wait
                raise CreateRejected(429)
            if response.status in (400, 401, 403, 404, 405, 413, 422):
                raise CreateRejected(response.status)
            if not 200 <= response.status < 300:
                raise RuntimeError("discord_create_result_unknown")
            data = await response.json()
            if not isinstance(data, dict) or not re.fullmatch(r"[1-9][0-9]{16,19}", str(data.get("id", ""))):
                raise RuntimeError("discord_create_result_unconfirmed")
            return SimpleNamespace(id=int(data["id"]))

    async def role(self, guild, name):
        return await self.post(guild, "roles", {"name": name, "permissions": "0", "hoist": False, "mentionable": False})

    async def channel(self, guild, kind, name, overwrites, category=None):
        types = {"category": 4, "text": 0, "voice": 2}
        if kind not in types:
            raise CreateDeferred("unsupported_channel_kind")
        payload = {"name": name, "type": types[kind], "permission_overwrites": self.overwrites(overwrites)}
        if category:
            payload["parent_id"] = str(category.id)
        return await self.post(guild, "channels", payload)
