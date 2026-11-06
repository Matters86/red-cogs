"""Organigramm: Rollen-Schnellstart, Baumeditor, Veröffentlichungsstatus und automatische Updates."""
import asyncio
import re
from types import SimpleNamespace
from urllib.parse import unquote_plus
from unittest.mock import patch

import live_harness as L
from aiohttp.test_utils import TestClient, TestServer
from rc.organigram.organigram import Organigram


async def main():
    guilds = L.H.build_world()
    bot = L.H.FakeBot(guilds)
    guild = guilds[0]
    cog = Organigram(bot)
    wc = await L.H.make_webcore(bot)
    cog._register_dashboard(wc)
    await wc.config.role_perms.set({"1000": {"1101": {"organigram": "operate"},
                                             "1102": {"organigram": "view"}}})
    client = TestClient(TestServer(wc.app))
    await client.start_server()
    tokens = {}
    scheduled = []
    cog._schedule = lambda gid, cid: scheduled.append((gid, cid))

    async def page(uid=1, suffix=""):
        response = await client.get("/cogs/organigram?guild=1000" + suffix,
                                    headers={"X-Test-User": str(uid)})
        html = await response.text()
        assert response.status == 200, html[:400]
        tokens[uid] = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
        return html

    async def post(uid=1, **data):
        if uid not in tokens:
            await page(uid)
        pairs = [("csrf_token", tokens[uid]), ("guild", "1000")]
        for key, value in data.items():
            pairs.extend((key, item) for item in value) if isinstance(value, list) else pairs.append((key, value))
        response = await client.post("/cogs/organigram", headers={"X-Test-User": str(uid)},
                                     data=pairs, allow_redirects=False)
        assert response.status == 302, (response.status, await response.text())
        return unquote_plus(response.headers["Location"])

    try:
        html = await page()
        assert "Schnellstart" in html and "Layout-Beispiele" in html
        before = await cog.config.guild(guild).charts()
        for uid in (11, 12):
            await post(uid, form="quickstart", name="Unerlaubt", roles=["1101", "1102"])
            assert await cog.config.guild(guild).charts() == before
        loc = await post(form="quickstart", name="Schnellteam", roles=["1101", "1103", "1102"], structure="chain")
        cid = re.search(r"chart=([0-9a-f]+)", loc).group(1)
        chart = (await cog.config.guild(guild).charts())[cid]
        ordered = sorted(chart["nodes"], key=lambda nid: chart["nodes"][nid]["order"])
        assert [chart["nodes"][nid]["role_id"] for nid in ordered] == [1102, 1101, 1103]
        assert chart["nodes"][ordered[0]]["parent"] is None
        assert chart["nodes"][ordered[1]]["parent"] == ordered[0]
        assert chart["nodes"][ordered[2]]["parent"] == ordered[1]
        assert chart["posts"] == [] and chart["draft"] is True
        assert not any(channel._messages for channel in guild.text_channels), "Vorschau darf nichts veröffentlichen"
        response = await client.get(f"/cogs/organigram?guild=1000&preview={cid}", headers={"X-Test-User": "1"})
        assert response.status == 200 and (await response.read()).startswith(b"\x89PNG")
        assert not any(channel._messages for channel in guild.text_channels)
        loc = await post(form="quickstart", name="Falsche Rolle", roles=["1101", "999999"])
        assert "err=" in loc and len(await cog.config.guild(guild).charts()) == 1
        print("Schnellstart: Rollen validiert, Hierarchie sortiert, Entwurf/Vorschau ohne Veröffentlichung, Rechte – OK")

        parent = ordered[0]
        html = await page(suffix=f"&chart={cid}&parent={parent}")
        assert "role='tree'" in html and "Unterposition" in html and "Nach oben" in html
        assert f"value='{parent}' selected" in html
        await post(form="node_save", chart=cid, parent=parent, label="Zusätzlicher Bereich", role_id="1104")
        chart = (await cog.config.guild(guild).charts())[cid]
        child = next(nid for nid, nd in chart["nodes"].items() if nd["label"] == "Zusätzlicher Bereich")
        sibling = ordered[1]
        await post(form="node_move", chart=cid, node=child, direction="down")
        nodes = (await cog.config.guild(guild).charts())[cid]["nodes"]
        assert nodes[child]["order"] > nodes[sibling]["order"]
        assert nodes[child]["parent"] == parent and nodes[ordered[2]]["parent"] == sibling
        unchanged = await cog.config.guild(guild).charts()
        await post(11, form="node_move", chart=cid, node=child, direction="up")
        await post(11, form="pattern_apply", chart=cid, pattern="horizontal")
        assert await cog.config.guild(guild).charts() == unchanged
        await post(form="pattern_apply", chart=cid, pattern="horizontal")
        assert (await cog.config.guild(guild).charts())[cid]["pattern"] == "horizontal"
        print("Baumeditor: Unterposition vorgewählt, Geschwister verschoben, Struktur erhalten, Bearbeiten nötig – OK")

        channel = guild.text_channels[0]
        await post(11, form="post", chart=cid, channel=str(channel.id), mode="text")
        posted = (await cog.config.guild(guild).charts())[cid]
        assert posted["draft"] is False
        entry = posted["posts"][0]
        assert entry["last_success_at"] and entry["last_error"] is None
        initial_id = entry["message_id"]
        channel.forbid.add("history")
        await post(11, form="post", chart=cid, channel=str(channel.id), mode="embed")
        loc = await post(11, form="retry", chart=cid, channel_id=str(channel.id))
        failed = (await cog.config.guild(guild).charts())[cid]["posts"][0]
        assert "err=" in loc and failed["last_error"] and failed["message_id"] == initial_id
        assert failed["mode"] == "embed", "Wiederholen muss den zuletzt gewählten Modus verwenden"
        assert failed["last_success_at"] == entry["last_success_at"] and len(channel._messages) == 1
        html = await page(11, suffix=f"&chart={cid}")
        assert "In Discord öffnen" in html and "Erneut versuchen" in html and "Aktualisierung fehlgeschlagen" in html
        channel.forbid.clear()
        loc = await post(11, form="retry", chart=cid, channel_id=str(channel.id))
        success = (await cog.config.guild(guild).charts())[cid]["posts"][0]
        assert "ok=" in loc and "fehlgeschlagen" not in loc
        assert success["last_error"] is None and success["message_id"] == initial_id
        assert success["last_success_at"] >= entry["last_success_at"] and len(channel._messages) == 1
        assert (await channel.fetch_message(initial_id)).embed is not None
        snap = await cog.config.guild(guild).charts()
        await post(12, form="retry", chart=cid, channel_id=str(channel.id))
        assert await cog.config.guild(guild).charts() == snap
        print("Veröffentlichung: Status/Zeiten/Discord-Link, gezielter Retry, keine Duplikate, Bedienen/Ansehen – OK")

        scheduled.clear()
        member = guild.get_member(11)
        before_member = SimpleNamespace(roles=member.roles, display_name=member.display_name, display_avatar="old")
        after_member = SimpleNamespace(roles=member.roles, display_name=member.display_name,
                                       display_avatar="new", guild=guild, bot=True)
        await cog.on_member_update(before_member, after_member)
        assert (guild.id, cid) in scheduled, "Auch Bot-/Guild-Avataränderungen müssen neu rendern"
        scheduled.clear()
        before_user = SimpleNamespace(id=member.id, name="lena", global_name="Lena", display_avatar="old")
        after_user = SimpleNamespace(id=member.id, name="lena", global_name="Neuer Name", display_avatar="new")
        await cog.on_user_update(before_user, after_user)
        assert (guild.id, cid) in scheduled
        scheduled.clear()
        await cog._reconcile_on_ready()
        assert (guild.id, cid) in scheduled
        print("Automatik: Neustart holt Abgleich nach, globale Namen/Avatare und Bots lösen Update aus – OK")

        # Ein neues Ereignis darf ein bereits laufendes Update nicht zwischen Senden/Speichern abbrechen.
        debounce = Organigram(bot)
        entered, release = asyncio.Event(), asyncio.Event()
        completed = []

        async def slow_refresh(gid, chart_id, **kwargs):
            entered.set()
            await release.wait()
            completed.append(chart_id)

        debounce._refresh_chart = slow_refresh
        with patch("rc.organigram.organigram.REFRESH_DELAY", 0):
            debounce._schedule(guild.id, cid)
            await asyncio.wait_for(entered.wait(), 5)
            first_task = next(iter(debounce._running))
            debounce._schedule(guild.id, cid)
            await asyncio.sleep(0)
            assert not first_task.cancelled() and not first_task.done()
            release.set()
            await first_task
            if (guild.id, cid) in debounce._pending:
                await debounce._pending[(guild.id, cid)]
            assert len(completed) == 2
            async with debounce.config.guild(guild).charts() as charts:
                charts[cid]["auto_update"] = False
            debounce._schedule(guild.id, cid)
            waiting = debounce._pending[(guild.id, cid)]
            await waiting
            assert len(completed) == 2, "Ausgeschaltetes Auto-Update muss auch vorgemerkte Ereignisse stoppen"
        await debounce.cog_unload()
        print("Nebenläufigkeit: neue Ereignisse brechen laufende Veröffentlichungen nicht ab – OK")
    finally:
        await client.close()
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
