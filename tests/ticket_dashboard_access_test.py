"""Ticket-Webzugriff: gespeicherte Teams, Metadaten, Transcripts und gefälschte Aktionen."""
import asyncio
import re
from copy import deepcopy
from urllib.parse import unquote_plus

import tc_harness as T
from aiohttp.test_utils import TestClient, TestServer


async def main():
    wc, bot, app, cog, _ = await T.make_app()
    guild = bot.guilds[0]
    gc = cog.config.guild(guild)
    setup = T.H.Role(guild, 1110, "Einrichtung", 2)
    guild.roles.append(setup)
    guild.get_member(15).roles.append(setup)
    viewer_a = T.H.Member(guild, 16, "A nur Ansicht", [guild.get_role(1103)])
    guild.members.append(viewer_a)
    await gc.support_roles.set([1101])
    await gc.view_roles.set([1104])
    await gc.category_open.set(guild.categories[0].id)
    await gc.max_open.set(20)
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "operate"},
                                             "1102": {"tickets": "edit"},
                                             "1103": {"tickets": "view"},
                                             "1104": {"tickets": "operate"},
                                             "1110": {"tickets": "edit"}}})
    reason_a = {"id": "a", "label": "GEHEIM-A", "support_roles": [1103]}
    reason_b = {"id": "b", "label": "GEHEIM-B", "support_roles": [1102]}
    panel = {"id": "scope", "title": "Support", "reasons": [reason_a, reason_b]}
    normal_panel = {"id": "normal", "title": "Support", "reasons": []}
    await gc.panels.set([panel, normal_panel])

    async def create(reason, owner=15):
        result = await cog.open_ticket(guild, guild.get_member(owner), panel if reason else normal_panel, reason, {})
        assert result.target is not None
        return result.target

    a = await create(reason_a)
    b = await create(reason_b, 13)
    normal = await create(None)
    closed_a = await create(reason_a)
    await cog._close_ticket(guild, closed_a, await cog._get_record(guild, closed_a.id),
                            guild.get_member(1), await gc.all())
    closed_b = await create(reason_b, 13)
    await cog._close_ticket(guild, closed_b, await cog._get_record(guild, closed_b.id),
                            guild.get_member(1), await gc.all())
    a_num = (await cog._get_record(guild, closed_a.id))["num"]
    b_num = (await cog._get_record(guild, closed_b.id))["num"]
    # Historischer Verlauf ohne zuordenbares Ticket: nur Admins dürfen ihn öffnen.
    filename = f"{guild.id}-999.html"
    (cog.transcripts_dir / filename).write_text("LEGACY-UNBEKANNT", encoding="utf-8")
    async with gc.transcripts() as records:
        records.append({"num": 999, "owner_id": 15, "owner": "ALT-GEHEIM", "file": filename})
    # Ein Panel im fremden Ticketkanal darf dessen Name/ID nicht über Setup-Listen verraten.
    await gc.panels.set([{"id": "hidden-panel", "title": "Privates Panel", "channel_id": b.id,
                          "message_id": 99, "reasons": []}])
    async with gc.tickets() as records:
        records[str(a.id)]["claimed_by"] = 14
        records[str(b.id)]["claimed_by"] = 12
    client = TestClient(TestServer(app))
    await client.start_server()
    tokens = {}

    async def get(uid, query="", path="/cogs/tickets"):
        response = await client.get(path + "?guild=1000" + query, headers={"X-Test-User": str(uid)},
                                    allow_redirects=False)
        text = await response.text()
        if response.status == 200 and "name='csrf_token'" in text:
            tokens[uid] = re.search(r"name='csrf_token' value='([^']+)'", text).group(1)
        return response, text

    async def post(uid, form, channel, **values):
        if uid not in tokens:
            await get(uid)
        response = await client.post("/cogs/tickets", headers={"X-Test-User": str(uid)},
            data={"csrf_token": tokens[uid], "guild": "1000", "form": form,
                  "channel_id": str(channel), **values}, allow_redirects=False)
        assert response.status == 302, (response.status, await response.text())
        return unquote_plus(response.headers["Location"])

    try:
        expected = {11: {normal.id}, 14: {a.id, normal.id, closed_a.id},
                    12: {b.id, closed_b.id}, 16: {a.id, closed_a.id}, 15: set()}
        all_private = (a, b, normal, closed_a, closed_b)
        for uid, visible in expected.items():
            response, text = await get(uid)
            assert response.status == 200
            for channel in all_private:
                if channel.id not in visible:
                    assert str(channel.id) not in text, (uid, channel.id, "ID im HTML")
                    assert channel.name not in text, (uid, channel.name, "Name im HTML")
            assert "ALT-GEHEIM" not in text
            if uid in (11, 14, 12, 16):
                assert str(next(iter(visible))) in text
        response, text = await get(13)
        assert response.status == 200 and "Nur lesen für dieses Ticket" in text
        for channel in all_private:
            assert str(channel.id) in text
        assert "name='form' value='ticket_close'" not in text
        assert "name='form' value='ticket_assign'" not in text
        assert "name='form' value='ticket_priority'" not in text
        assert "ALT-GEHEIM" not in text
        response, text = await get(1)
        assert response.status == 200 and "ALT-GEHEIM" in text
        print("Gesamtes HTML: fremde Ticketnamen/-IDs aus Listen, Pickern, Panels und Verläufen entfernt – OK")

        for uid, num, allowed in ((14, a_num, True), (14, b_num, False), (11, a_num, False),
                                  (12, b_num, True), (13, a_num, True), (13, 999, False),
                                  (15, a_num, False), (1, 999, True)):
            response, text = await get(uid, f"&transcript={num}")
            assert response.status == (200 if allowed else 404), (uid, num, response.status)
        # Portal-Zugriff bleibt ausschließlich Eigentümer/ausdrücklich hinzugefügten Mitgliedern vorbehalten.
        response, text = await get(15, f"&transcript={a_num}", path="/me/tickets")
        assert response.status == 200
        response, _ = await get(14, f"&transcript={a_num}", path="/me/tickets")
        assert response.status == 404
        for foreign in ("2000", "not-an-id"):
            response = await client.get(f"/cogs/tickets?guild={foreign}", headers={"X-Test-User": "11"}, allow_redirects=False)
            if response.status == 302:
                assert response.headers["Location"] == "/cogs/tickets?guild=1000"
                redirected = await client.get(response.headers["Location"], headers={"X-Test-User": "11"})
                assert redirected.status == 200 and "Rollenspiel" not in await redirected.text()
            else:
                assert response.status in (403, 404)
        print("Transcript-Scopes, unbekannter Altbestand, getrenntes Mitgliederportal und fremde Server – OK")

        before = deepcopy(await gc.all())
        for uid in (11, 12, 13, 15):
            for form, values in (("ticket_close", {}), ("ticket_assign", {"member_id": "14"}),
                                 ("ticket_waiting", {"waiting": "user"}),
                                 ("ticket_priority", {"priority": "urgent"}),
                                 ("ticket_autoclose", {}), ("ticket_keepopen", {}),
                                 ("ticket_reply_preview", {"reply_id": "opening"}),
                                 ("ticket_reply_send", {"text": "Fremde Antwort", "token": "forged"})):
                loc = await post(uid, form, a.id, **values)
                assert "err=" in loc, (uid, form, loc)
                assert await gc.all() == before, (uid, form, "Mutation trotz fehlendem Team")
        # WebCore-Ansehen erlaubt auch einem Teammitglied keine Tagesgeschäft-POSTs.
        await post(16, "ticket_waiting", a.id, waiting="user")
        assert await gc.all() == before
        loc = await post(14, "ticket_waiting", a.id, waiting="user")
        assert "ok=" in loc and (await cog._get_record(guild, a.id))["waiting_for"] == "user"
        # Verwaiste Datensätze dürfen vor der Berechtigungsprüfung nicht entfernt werden.
        async with gc.tickets() as records:
            orphan = dict(records[str(a.id)], num=888)
            records["888888"] = orphan
        fetch_calls = []

        async def fetch_missing(cid):
            fetch_calls.append(cid)
            raise T.L.not_found()

        guild.fetch_channel = fetch_missing
        await post(12, "ticket_close", 888888)
        assert "888888" in await gc.tickets() and not fetch_calls
        # Ein Cache-Miss/fehlendes fetch oder ein Discord-Rechtefehler beweist keine Löschung.
        del guild.fetch_channel
        loc = await post(14, "ticket_close", 888888)
        assert "err=" in loc and "888888" in await gc.tickets()

        async def fetch_forbidden(cid):
            raise T.L.forbidden()

        guild.fetch_channel = fetch_forbidden
        loc = await post(14, "ticket_close", 888888)
        assert "err=" in loc and "888888" in await gc.tickets()

        async def fetch_failed(cid):
            raise T.L.bad_request("Temporary failure")

        guild.fetch_channel = fetch_failed
        loc = await post(14, "ticket_close", 888888)
        assert "err=" in loc and "888888" in await gc.tickets()
        guild.fetch_channel = fetch_missing
        loc = await post(14, "ticket_close", 888888)
        assert "ok=" in loc and "888888" not in await gc.tickets()
        # Ein voller WebCore-Allowlist-Eintrag ist keine Ticket-Teamrolle.
        await wc.config.allowed_users.set([15])
        _, text = await get(15)
        assert str(a.id) not in text and str(b.id) not in text
        before = await gc.all()
        await post(15, "ticket_waiting", a.id, waiting="team")
        assert await gc.all() == before
        # Ein vorhandener, nur nicht gecachter Ticketkanal wird geholt und regulär geschlossen.
        getter = guild.get_channel_or_thread
        guild.get_channel_or_thread = lambda cid: None if cid == a.id else getter(cid)

        async def fetch_existing(cid):
            assert cid == a.id
            return a

        guild.fetch_channel = fetch_existing
        loc = await post(14, "ticket_close", a.id)
        assert "ok=" in loc and (await cog._get_record(guild, a.id))["status"] == "closed"
        assert any(record["num"] == 1 for record in await gc.transcripts())
        guild.get_channel_or_thread = getter
        print("Gefälschte POSTs/Read-only/Setup-only/Full-WebCore/Orphan-Cleanup sicher; eigenes Team kann bedienen – OK")
    finally:
        await client.close()
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
