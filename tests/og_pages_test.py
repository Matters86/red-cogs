"""Organigramm-Seiten: Vollständigkeit, ZIP, stabile IDs, Teilfehler und sichere Verkleinerung."""
import asyncio
import io
import re
import zipfile
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import live_harness as L
from aiohttp.test_utils import TestClient, TestServer
from rc.organigram.organigram import Organigram, resolve_node_people
from rc.organigram.pages import plan_pages, render_page
from rc.organigram.render import _Renderer


async def main():
    guilds = L.H.build_world()
    bot = L.H.FakeBot(guilds)
    guild = guilds[0]
    cog = Organigram(bot)
    support, lead = guild.get_role(1101), guild.get_role(1103)
    for index in range(22):
        roles = [support, lead] if index < 5 else [support]
        member = L.H.Member(guild, 9000 + index, f"Mitglied {index + 1:02d}", roles)
        member.display_avatar = L.FakeAsset(member.id)
        guild.members.append(member)
    chart = {"name": "../ Team ü", "show_avatars": False, "show_vacant": True,
             "image_mode": "pages", "page_size": 5, "nodes": {
                 "lead": {"label": "Leitung", "role_id": 1103, "parent": None, "order": 0},
                 "support": {"label": "Support", "role_id": 1101, "parent": "lead", "order": 0},
                 "external": {"label": "Externe", "manual_names": [f"Gast {i:02d}" for i in range(11)],
                              "parent": "lead", "order": 1}}, "posts": []}
    gc = cog.config.guild(guild)
    await gc.charts.set({"pages": chart})
    model = await cog._resolve(guild, chart)
    specs = plan_pages(model, 5)
    assert len(specs) > 10
    expected = Counter()
    paths = {"lead": "Leitung", "support": "Leitung › Support", "external": "Leitung › Externe"}
    for nid, people in resolve_node_people(guild, chart).items():
        expected.update((paths[nid], member.id if member else None, name) for name, member in people)
    actual = Counter((page.path, person.member_id, person.name)
                     for page in specs if page.kind == "people" for person in page.people)
    assert actual == expected, "Jede Position und Person muss ohne Sieben-Personen-Kürzung enthalten sein"
    assert specs[0].kind == "overview" and len(specs[0].positions) == 3
    assert [page.title for page in specs] == await cog._image_manifest(guild, chart)
    highest = dict(chart, member_display="highest")
    unique = plan_pages(await cog._resolve(guild, highest), 5)
    ids = [p.member_id for page in unique for p in page.people if p.member_id is not None]
    assert len(ids) == len(set(ids))
    assert len(await cog._image_manifest(guild, dict(chart, image_mode="single"))) == 1
    drawn = []
    original_text = _Renderer._text

    def record_text(renderer, xy, text, *args, **kwargs):
        drawn.append(text)
        return original_text(renderer, xy, text, *args, **kwargs)

    with patch.object(_Renderer, "_text", record_text):
        for index, page in enumerate(specs):
            assert render_page(model, page, index, len(specs)).startswith(b"\x89PNG")
    assert all(name in drawn for _, _, name in expected), "Auch Namen hinter Platz sieben müssen gezeichnet werden"
    archive = await cog._export_images_zip(guild, chart)
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        assert len(opened.namelist()) == len(specs)
        assert all("/" not in name and "\\" not in name and ".." not in name for name in opened.namelist())
        assert all(opened.read(name).startswith(b"\x89PNG") for name in opened.namelist())
    print("Plan/Bilder/ZIP: alle Identitäten und Namen, höchste Position, stabile Reihenfolge, sichere Dateinamen – OK")

    channel = guild.text_channels[0]
    ok, error = await cog._post_and_save(guild, "pages", channel, "text")
    assert ok, error
    legacy_id = (await gc.charts())["pages"]["posts"][0]["message_id"]
    async with gc.charts() as charts:
        charts["pages"]["posts"] = [{"channel_id": channel.id, "message_id": legacy_id, "mode": "text"}]
    original_send = channel.send
    sends = []

    async def fail_third_send(*args, **kwargs):
        sends.append(1)
        if len(sends) == 3:
            raise L.forbidden()
        return await original_send(*args, **kwargs)

    channel.send = fail_third_send
    ok, error = await cog._post_and_save(guild, "pages", channel, "image")
    assert not ok and error
    partial = (await gc.charts())["pages"]["posts"][0]
    assert partial["message_id"] == legacy_id
    assert set(partial["message_ids"]) == set(channel._messages)
    assert len(partial["message_ids"]) == 3 and partial["last_error"] and partial["error_at"]
    assert partial["attempted_mode"] == "image"
    partial_ids = list(partial["page_message_ids"])
    channel.send = original_send
    ok, error = await cog._post_and_save(guild, "pages", channel, "image")
    assert ok, error
    entry = (await gc.charts())["pages"]["posts"][0]
    original_ids = list(entry["page_message_ids"])
    assert original_ids[:3] == partial_ids
    assert len(original_ids) == len(specs) and set(original_ids) == set(channel._messages)
    await cog._post_and_save(guild, "pages", channel, "image")
    assert (await gc.charts())["pages"]["posts"][0]["page_message_ids"] == original_ids
    assert len(channel._messages) == len(specs)
    assert all(len(info.get("files", [])) <= 1 for op, cid, info in L.LOG if op == "send" and cid == channel.id)
    before_ops = len(L.LOG)
    await cog._refresh_chart(guild.id, "pages", force=False)
    assert not [op for op, cid, _ in L.LOG[before_ops:] if cid == channel.id and op in {"send", "edit", "fetch", "delete"}]
    guild.get_member(9021).display_name = "ZZZ letztes Mitglied"
    before_ops = len(L.LOG)
    await cog._refresh_chart(guild.id, "pages", force=False)
    assert len([op for op, cid, _ in L.LOG[before_ops:] if cid == channel.id and op == "edit"]) == 1
    requests = []
    original_schedule = cog._schedule

    def record_repair(gid, cid, *, verify_ids=()):
        requests.append((gid, cid, set(verify_ids)))

    cog._schedule = record_repair
    try:
        await cog.on_raw_message_delete(SimpleNamespace(guild_id=guild.id, message_id=123456))
        assert requests == [], "Fremde Nachrichten dürfen keinen Abgleich auslösen"
        missing = original_ids[3]
        channel._messages.pop(missing)
        await cog.on_raw_message_delete(SimpleNamespace(guild_id=guild.id, message_id=missing))
        assert requests == [(guild.id, "pages", {missing})]
        before_ops = len(L.LOG)
        await cog._refresh_chart(guild.id, "pages", force=False, verify_ids={missing})
        repaired = (await gc.charts())["pages"]["posts"][0]["page_message_ids"]
        assert repaired[:3] == original_ids[:3] and repaired[4:] == original_ids[4:]
        assert repaired[3] != missing and len(channel._messages) == len(specs)
        assert not [op for op, cid, _ in L.LOG[before_ops:] if cid == channel.id and op == "edit"]
        original_ids = repaired
        requests.clear()
        deleted = {original_ids[4], original_ids[5]}
        for mid in deleted:
            channel._messages.pop(mid)
        await cog.on_raw_bulk_message_delete(SimpleNamespace(guild_id=guild.id, message_ids=deleted | {123456}))
        assert requests == [(guild.id, "pages", deleted)]
        await cog._refresh_chart(guild.id, "pages", force=False, verify_ids=deleted)
        original_ids = (await gc.charts())["pages"]["posts"][0]["page_message_ids"]
        assert set(original_ids) == set(channel._messages) and len(channel._messages) == len(specs)
        # Während der Bot offline war gelöschte Seiten werden beim Start einmal geprüft.
        requests.clear()
        offline_missing = original_ids[2]
        channel._messages.pop(offline_missing)
        await cog._verify_after_downtime(guild, "pages", (await gc.charts())["pages"])
        assert requests == [(guild.id, "pages", {offline_missing})]
        await cog._refresh_chart(guild.id, "pages", force=False, verify_ids={offline_missing})
        original_ids = (await gc.charts())["pages"]["posts"][0]["page_message_ids"]
        requests.clear()
        async with gc.charts() as charts:
            charts["pages"]["auto_update"] = False
        await cog.on_raw_message_delete(SimpleNamespace(guild_id=guild.id, message_id=original_ids[0]))
        assert requests == []
        async with gc.charts() as charts:
            charts["pages"]["auto_update"] = True
    finally:
        cog._schedule = original_schedule
    print("Veröffentlichung >10 Seiten: Altbestand migriert, Teilfehler sofort verfolgt, Retry ohne Doppelposts – OK")
    print("Löschereignisse/Offline-Abgleich: nur betroffene Seiten repariert, normale Hash-Updates bleiben ohne Fetch – OK")

    # Fehler beim Ersetzen darf alte, noch benötigte Seiten niemals vorzeitig löschen.
    async with gc.charts() as charts:
        charts["pages"]["page_size"] = 50
    failing = channel._messages[original_ids[1]]
    original_edit = failing.edit

    async def denied_edit(**kwargs):
        raise L.forbidden()

    failing.edit = denied_edit
    ok, _ = await cog._post_and_save(guild, "pages", channel, "image")
    assert not ok and set(channel._messages) == set(original_ids)
    failing.edit = original_edit
    channel.forbid.add("delete")
    ok, _ = await cog._post_and_save(guild, "pages", channel, "image")
    assert not ok
    cleanup = (await gc.charts())["pages"]["posts"][0]
    assert len(cleanup["page_message_ids"]) == 4
    assert len(cleanup["retired_message_ids"]) == len(original_ids) - 4
    assert set(cleanup["message_ids"]) == set(channel._messages)
    channel.forbid.clear()
    ok, error = await cog._post_and_save(guild, "pages", channel, "image")
    assert ok, error
    cleaned = (await gc.charts())["pages"]["posts"][0]
    assert cleaned["page_message_ids"] == original_ids[:4] and cleaned["retired_message_ids"] == []
    assert set(cleaned["message_ids"]) == set(channel._messages) and len(channel._messages) == 4
    channel.forbid.add("history")
    ok, _ = await cog._post_and_save(guild, "pages", channel, "image")
    assert not ok and len(channel._messages) == 4
    channel.forbid.clear()
    with patch("rc.organigram.organigram.MAX_EXPORT_BYTES", 100):
        ok, _ = await cog._post_and_save(guild, "pages", channel, "image")
        assert not ok and len(channel._messages) == 4
    with patch("rc.organigram.pages.MAX_PAGES", 1):
        ok, _ = await cog._post_and_save(guild, "pages", channel, "image")
        assert not ok and len(channel._messages) == 4
    guild.filesize_limit = 100
    ok, _ = await cog._post_and_save(guild, "pages", channel, "image")
    assert not ok and len(channel._messages) == 4
    del guild.filesize_limit
    ok, error = await cog._post_and_save(guild, "pages", channel, "embed")
    assert ok, error
    assert set(channel._messages) == {legacy_id}
    assert (await channel.fetch_message(legacy_id)).embed is not None
    print("Verkleinern/Moduswechsel: erst Ersatz, dann alte Seiten; Löschfehler/Lesefehler/Limits bewahren IDs – OK")

    # Abbruch nach Discord-Senden: die neue ID muss vor dem Abbruch gesichert werden.
    cancel_chart = deepcopy(chart)
    cancel_chart["posts"] = []
    async with gc.charts() as charts:
        charts["cancel"] = cancel_chart
    cancel_channel = guild.text_channels[1]
    cancel_send = cancel_channel.send
    sent, release = asyncio.Event(), asyncio.Event()

    async def delayed_send(*args, **kwargs):
        msg = await cancel_send(*args, **kwargs)
        sent.set()
        await release.wait()
        return msg

    cancel_channel.send = delayed_send
    task = asyncio.create_task(cog._post_and_save(guild, "cancel", cancel_channel, "image"))
    await asyncio.wait_for(sent.wait(), 10)
    task.cancel()
    release.set()
    try:
        await task
    except asyncio.CancelledError:
        pass
    partial_cancel = (await gc.charts())["cancel"]["posts"][0]
    assert set(partial_cancel["message_ids"]) == set(cancel_channel._messages)
    assert len(cancel_channel._messages) == 1
    cancel_channel.send = cancel_send
    print("Abbruch während Senden: neue Nachrichten-ID bleibt gesichert – OK")

    wc = await L.H.make_webcore(bot)
    cog._register_dashboard(wc)
    await wc.config.role_perms.set({"1000": {"1102": {"organigram": "view"}}})
    client = TestClient(TestServer(wc.app))
    await client.start_server()
    try:
        view = {"X-Test-User": "12"}
        response = await client.get("/cogs/organigram?guild=1000&chart=pages&page=2", headers=view)
        html = await response.text()
        assert response.status == 200 and "Bildseite auswählen" in html and "Alle Seiten als ZIP" in html
        response = await client.get("/cogs/organigram?guild=1000&preview=pages&page=2", headers=view)
        assert response.status == 200 and (await response.read()).startswith(b"\x89PNG")
        response = await client.get("/cogs/organigram?guild=1000&preview=pages&page=9999", headers=view)
        assert response.status == 404
        response = await client.get("/cogs/organigram?guild=1000&download=pages", headers=view)
        assert response.status == 200 and response.content_type == "application/zip"
        assert zipfile.is_zipfile(io.BytesIO(await response.read()))
        response = await client.get("/cogs/organigram?guild=2000&download=pages", headers=view, allow_redirects=False)
        assert response.status in (302, 403, 404)
        token = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
        snapshot = await gc.charts()
        response = await client.post("/cogs/organigram", headers=view, allow_redirects=False,
            data={"csrf_token": token, "guild": "1000", "form": "chart_settings", "chart": "pages",
                  "name": "../ Team ü", "image_mode": "single", "page_size": "5"})
        assert response.status == 302 and await gc.charts() == snapshot
    finally:
        await client.close()
        await cog.cog_unload()
        await wc.cog_unload()
    print("Dashboard: einzelne Seiten/ZIP, Seitenauswahl und Ansehen-Rechte ohne Schreibzugriff – OK")


if __name__ == "__main__":
    asyncio.run(main())
