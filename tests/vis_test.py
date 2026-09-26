"""Mein Bereich: visible()-Callback blendet Kacheln und Navigation je Server aus."""
import asyncio
import wcm_harness as M
from aiohttp.test_utils import TestServer, TestClient
async def main():
    wc, bot, app = await M.make_app()
    client = TestClient(TestServer(app)); await client.start_server()
    kai = {"X-Test-User": "13"}
    await wc.config.member_portal.set({"1000": True})
    g = bot.get_guild(1000)
    r = await client.get("/me?guild=1000", headers=kai); t = await r.text()
    assert "/me/raids" in t and "/me/umfragen" in t, "Kacheln fehlen"
    await bot._cogs["RaidHelper"].config.guild(g).member_page.set(False)
    await bot._cogs["Poll"].config.guild(g).member_page.set(False)
    for path in ("/me?guild=1000", "/me/rollen?guild=1000"):
        r = await client.get(path, headers=kai); t = await r.text()
        assert r.status == 200 and "/me/raids" not in t and "/me/umfragen" not in t and "/me/rollen" in t, path
    print("visible()-Callback: Kacheln + Navigation je Server ausgeblendet – OK")
    await client.close()
asyncio.run(main())
