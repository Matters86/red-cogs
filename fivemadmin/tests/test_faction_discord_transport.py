"""Artificial in-memory HTTP sessions verify one POST only; never network."""
import sys
import types
import unittest

import test_faction_discord as harness
from fd_test_package.faction_discord_transport import SingleAttemptCreates, CreateRejected, CreateDeferred


class Response:
    def __init__(self, status=200, data=None, headers=None):
        self.status, self.data, self.headers = status, data or {"id": "10000000000700001"}, headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.data


class Session:
    closed = False

    def __init__(self, response):
        self.response, self.calls = response, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class TransportTests(unittest.IsolatedAsyncioTestCase):
    loop_factory = harness.OfflineLoop

    async def asyncSetUp(self):
        self.previous = sys.modules.get("aiohttp")
        sys.modules["aiohttp"] = types.SimpleNamespace(ClientTimeout=lambda **kw: kw)
        self.session = Session(Response())
        http = types.SimpleNamespace(token="ARTIFICIAL-NOT-A-CREDENTIAL", user_agent="artificial",
            _global_over=types.SimpleNamespace(is_set=lambda: True), proxy=None, proxy_auth=None)
        setattr(http, "_HTTPClient__session", self.session)
        self.bot = types.SimpleNamespace(http=http)
        self.transport = SingleAttemptCreates(self.bot)
        self.guild = harness.Guild()

    async def asyncTearDown(self):
        if self.previous is None:
            sys.modules.pop("aiohttp", None)
        else:
            sys.modules["aiohttp"] = self.previous

    async def test_success_fixed_route_no_redirect_zero_permissions(self):
        obj = await self.transport.role(self.guild, "LSPD")
        self.assertEqual(obj.id, 10000000000700001)
        self.assertEqual(len(self.session.calls), 1)
        method, url, kwargs = self.session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://discord.com/api/v10/guilds/10000000000900000/roles")
        self.assertEqual(kwargs["json"]["permissions"], "0")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], {"total": 15})

    async def test_500_never_retried_by_transport(self):
        self.session.response = Response(500)
        with self.assertRaisesRegex(RuntimeError, "result_unknown"):
            await self.transport.role(self.guild, "LSPD")
        self.assertEqual(len(self.session.calls), 1)

    async def test_known_403_rejected_without_retry(self):
        self.session.response = Response(403)
        with self.assertRaises(CreateRejected) as found:
            await self.transport.role(self.guild, "LSPD")
        self.assertEqual(found.exception.status, 403)
        self.assertEqual(len(self.session.calls), 1)

    async def test_429_global_retry_after_blocks_further_calls(self):
        self.session.response = Response(429, {"retry_after": 300, "global": True})
        with self.assertRaises(CreateRejected):
            await self.transport.role(self.guild, "LSPD")
        with self.assertRaises(CreateDeferred):
            await self.transport.role(self.guild, "LSPD")
        self.assertFalse(self.transport.available())
        self.assertEqual(len(self.session.calls), 1)

    async def test_remaining_zero_bucket_delay_honored(self):
        self.session.response = Response(headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "120"})
        await self.transport.role(self.guild, "LSPD")
        with self.assertRaises(CreateDeferred):
            await self.transport.role(self.guild, "LSPD")
        self.assertEqual(len(self.session.calls), 1)

    async def test_missing_http_shape_fails_closed(self):
        self.bot.http = object()
        with self.assertRaises(CreateDeferred):
            await self.transport.role(self.guild, "LSPD")
        self.assertEqual(self.session.calls, [])

    async def test_bad_endpoint_cannot_send_authorization_elsewhere(self):
        with self.assertRaises(CreateDeferred):
            await self.transport.post(self.guild, "https://elsewhere.test", {})
        self.assertEqual(self.session.calls, [])

    async def test_explicit_channel_overwrites_and_parent(self):
        overwrite = types.SimpleNamespace(pair=lambda: (types.SimpleNamespace(value=4), types.SimpleNamespace(value=8)))
        await self.transport.channel(self.guild, "text", "lspd", {self.guild.default_role: overwrite, self.guild.me: overwrite},
                                     types.SimpleNamespace(id=10000000000777777))
        payload = self.session.calls[0][2]["json"]
        self.assertEqual(payload["type"], 0)
        self.assertEqual(payload["parent_id"], "10000000000777777")
        self.assertEqual([row["type"] for row in payload["permission_overwrites"]], [0, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
