"""Projektkalender im echten WebCore: gemeinsames Team, Versionen, Export und Einrichtung."""
import asyncio
import re
from copy import deepcopy
from urllib.parse import unquote_plus

import live_harness as L
from aiohttp.test_utils import TestClient, TestServer
from rc.teamcalendar.teamcalendar import TeamCalendar
from rc.teamcalendar.dashboard import discard_user


async def main():
    bot = L.H.FakeBot(L.H.build_world())
    wc = await L.H.make_webcore(bot)
    cog = TeamCalendar(bot)
    bot._cogs["TeamCalendar"] = cog
    cog._register_dashboard(wc)
    guild = bot.guilds[0]
    gc = cog.config.guild(guild)
    viewer = L.H.Member(guild, 17, "Team nur Ansicht", [guild.get_role(1105)] if guild.get_role(1105) else [])
    view_role = L.H.Role(guild, 1117, "Kalender lesen", 1)
    guild.roles.append(view_role)
    viewer.roles.append(view_role)
    guild.members.append(viewer)
    setup_outsider = L.H.Member(guild, 18, "Nur Server verwalten", [])
    setup_outsider.guild_permissions.manage_guild = True
    guild.members.append(setup_outsider)
    await wc.config.role_perms.set({"1000": {
        "1101": {"teamcalendar": "operate"}, "1102": {"teamcalendar": "operate"},
        "1103": {"teamcalendar": "edit"}, "1104": {"teamcalendar": "edit"},
        "1117": {"teamcalendar": "view"},
    }})
    client = TestClient(TestServer(wc.app))
    second = TestClient(TestServer(wc.app))
    await client.start_server()
    await second.start_server()
    tokens = {}
    calls = []

    async def page(uid=1, params=None, session=None):
        response = await (session or client).get("/cogs/teamcalendar", params={"guild": "1000", **(params or {})},
            headers={"X-Test-User": str(uid)}, allow_redirects=False)
        text = await response.text()
        token = re.search(r"name='csrf_token' value='([^']+)'", text)
        if token and session is None:
            tokens[uid] = token.group(1)
        return response, text

    async def post(uid, form, values=None, *, token=None):
        if uid not in tokens:
            await page(uid)
        session_token = tokens.get(uid) or next(iter(tokens.values()), "")
        response = await client.post("/cogs/teamcalendar", headers={"X-Test-User": str(uid)},
            data={"csrf_token": token if token is not None else session_token, "guild": "1000", "form": form, **(values or {})},
            allow_redirects=False)
        return response, unquote_plus(response.headers.get("Location", ""))

    async def fake_post(guild, actor, channel=None):
        calls.append(("publish", guild.id, actor.id, getattr(channel, "id", None)))

    async def fake_refresh(guild, *, actor=None):
        calls.append(("refresh", guild.id))

    original_post, original_refresh = cog.post_board, cog.refresh_board
    cog.post_board, cog.refresh_board = fake_post, fake_refresh
    values = {"title": "Teamplanung <script>alert(1)</script>", "project": "Projekt <A>",
              "description": "Notiz <img src=x onerror=alert(2)>", "location": "https://example.org/team",
              "owner_id": "11", "start": "2035-06-12T18:00", "end": "2035-06-12T19:00",
              "reminder_preset": "1440,60", "event_timezone": "Europe/Berlin"}
    try:
        response, text = await page(11)
        assert response.status == 403 and "Teamplanung" not in text
        response, text = await page(1)
        assert response.status == 200 and "Noch keine Teamrollen" in text and "Teammitglieder dürfen Termine verwalten" in text
        assert not calls and not await gc.events()
        await gc.team_roles.set([1101, 1102, 1117])
        await gc.manager_roles.set([1103])
        for uid in (11, 12, 14, 17):
            response, text = await page(uid)
            assert response.status == 200, (uid, response.status, text[:200])
        response, text = await page(13)
        assert response.status == 403
        # Ein voller WebCore-Zugang oder Manage Guild ersetzt keine Kalenderrolle.
        await wc.config.allowed_users.set([13, 18])
        for uid in (13, 18):
            response, text = await page(uid)
            assert response.status == 403
        response, location = await post(11, "event_save", {**values, "created_by": "1"})
        assert response.status == 302 and "ok=" in location, location
        assert "event=1" in location and location.endswith("#agenda"), location
        event = (await gc.events())["1"]
        assert event["created_by"] == 11 and event["owner_id"] == 11 and event["participants"] == {}
        assert not calls
        # Ein anderes Teammitglied darf den Termin vollständig bearbeiten.
        response, location = await post(12, "event_save", {**values, "title": "Gemeinsam geändert", "eid": "1", "revision": "1"})
        assert response.status == 302 and "ok=" in location
        assert "event=1" in location and location.endswith("#agenda"), location
        event = (await gc.events())["1"]
        assert event["updated_by"] == 12 and event["revision"] == 2 and event["created_by"] == 11
        before = deepcopy(await gc.all())
        for form, payload in (("event_save", {**values, "eid": "1", "revision": "1"}),
                              ("event_action", {"eid": "1", "revision": "1", "action": "delete"}),
                              ("event_action", {"eid": "1", "action": "delete"})):
            response, location = await post(11, form, payload)
            assert response.status == 302 and "err=" in location and await gc.all() == before, (form, location)
        print("Gemeinsame Verwaltung aller Teammitglieder; Seitenrechte, Fremdzugriff und Versionskonflikte – OK")

        # Validierungsfehler erhalten Eingaben; Neuaufruf lädt bewusst den aktuellen Versionsstand.
        invalid = {**values, "title": "Mein ungesicherter Entwurf <b>", "end": values["start"], "eid": "1", "revision": "2"}
        response, location = await post(11, "event_save", invalid)
        assert "err=" in location and "draft=event" in location and await gc.all() == before
        assert location.endswith("#planen"), location
        response, text = await page(11, {"edit": "1", "draft": "event"})
        assert response.status == 200 and "Mein ungesicherter Entwurf &lt;b&gt;" in text and "Aktuellen Stand neu laden" in text
        response, text = await page(11, {"edit": "1"})
        assert "value='Gemeinsam geändert'" in text and "name='revision' value='2'" in text
        # Ein anderer Login und eine andere Sitzung erhalten diesen Entwurf nicht.
        _, text = await page(12, {"edit": "1", "draft": "event"})
        assert "Mein ungesicherter Entwurf" not in text
        _, text = await page(11, {"edit": "1", "draft": "event"}, session=second)
        assert "Mein ungesicherter Entwurf" not in text
        # Ein in Berlin geöffnetes Formular darf nach Zeitzonenwechsel keine UTC-Zeit verschieben.
        await gc.timezone.set("UTC")
        zone_before = deepcopy(await gc.all())
        response, location = await post(11, "event_save", {**values, "eid": "1", "revision": "2"})
        assert "err=" in location and "Zeitzone" in location and await gc.all() == zone_before
        _, text = await page(11, {"edit": "1", "draft": "event"})
        assert "Europe/Berlin" in text and "dieses Formular stammt" in text
        _, text = await page(11, {"edit": "1"})
        assert "name='event_timezone' value='UTC'" in text and "2035-06-12T16:00" in text
        missing_zone = {key: value for key, value in values.items() if key != "event_timezone"}
        response, location = await post(11, "event_save", missing_zone)
        assert "err=" in location and await gc.all() == zone_before
        await gc.timezone.set("Europe/Berlin")
        discard_user(cog, 11)
        _, text = await page(11, {"edit": "1", "draft": "event"})
        assert "Mein ungesicherter Entwurf" not in text
        response, text = await page(12, {"copy": "1"})
        assert response.status == 200 and "2035-06-19T18:00" in text and "name='eid' value=''" in text
        assert await gc.all() == before and not calls
        response, text = await page(17, {"event": "1", "month": "2035-06"})
        assert response.status == 200 and "class='wc-month'" in text and "Notiz &lt;img" in text
        assert "<img src=x" not in text and "Projekt &lt;A&gt;" in text
        assert "name='form' value='event_save'" not in text and "name='form' value='rsvp'" not in text
        response, _ = await post(17, "event_action", {"eid": "1", "revision": "2", "action": "delete"})
        assert response.status in (302, 403) and await gc.all() == before
        response, _ = await post(11, "event_save", {**values, "title": "Ohne CSRF"}, token="wrong")
        assert response.status == 400 and await gc.all() == before
        for month in ("<script>", "0001-01", "9999-12", "2035-06"):
            response, text = await page(11, {"month": month})
            assert response.status == 200 and "class='wc-month'" in text
        print("Fehlerentwürfe getrennt und löschbar; Kopieren/Monatsansicht ohne Schreibeffekte, XSS und CSRF – OK")

        response, location = await post(12, "rsvp", {"eid": "1", "status": "yes", "user_id": "11"})
        assert response.status == 302 and "ok=" in location
        assert (await gc.events())["1"]["participants"] == {"12": "yes"}
        assert (await gc.events())["1"]["revision"] == 2
        response, text = await page(17, {"download": "ics"})
        assert response.status == 200 and response.content_type == "text/calendar"
        assert "BEGIN:VCALENDAR" in text and "teamcalendar-1000-1@red-cogs.local" in text
        assert response.headers["Cache-Control"] == "private, no-store" and "ATTENDEE" not in text
        response, text = await page(13, {"download": "ics"})
        assert response.status == 403 and "BEGIN:VCALENDAR" not in text
        foreign = bot.guilds[1]
        foreign_conf = cog.config.guild(foreign)
        await foreign_conf.events.set({"42": {**event, "id": "42", "title": "FREMDER-SERVER-GEHEIM"}})
        foreign_before = deepcopy(await foreign_conf.all())
        before = deepcopy(await gc.all())
        # Sogar ein WebCore-Bearbeiter braucht die zusätzliche Kalenderverwaltung für Einstellungen.
        await wc.config.allowed_users.set([11, 13, 18])
        response = await client.get("/cogs/teamcalendar?guild=2000", headers={"X-Test-User": "11"}, allow_redirects=False)
        assert response.status == 403 and "FREMDER-SERVER-GEHEIM" not in await response.text()
        response = await client.post("/cogs/teamcalendar", headers={"X-Test-User": "11"}, data={
            "csrf_token": tokens[11], "guild": "2000", "form": "event_action", "eid": "42", "revision": "2", "action": "delete"},
            allow_redirects=False)
        assert response.status == 403 and await foreign_conf.all() == foreign_before
        response, location = await post(11, "settings", {"timezone": "UTC", "keep_days": "10", "team_roles": "1101"})
        assert response.status == 302 and "err=" in location and await gc.all() == before
        response, location = await post(14, "settings", {"timezone": "UTC", "keep_days": "90", "team_roles": ["1101", "1102", "1117"],
            "manager_roles": ["1103"], "team_can_manage": "on", "reminder_minutes": "60", "reminder_channel": ""})
        assert response.status == 302 and "ok=" in location, location
        assert location.endswith("#einstellungen"), location
        assert (await gc.all())["timezone"] == "UTC" and (await gc.all())["team_can_manage"] is True
        await gc.team_can_manage.set(False)
        read_only = deepcopy(await gc.all())
        response, text = await page(11, {"event": "1"})
        assert "name='form' value='event_save'" not in text and "name='form' value='rsvp'" in text
        response, location = await post(11, "event_action", {"eid": "1", "revision": "2", "action": "delete"})
        assert "err=" in location and await gc.all() == read_only
        await gc.team_can_manage.set(True)
        response, location = await post(11, "board_publish", {"channel": "1001"})
        assert response.status == 302 and "err=" in location and not calls
        response, location = await post(14, "board_publish", {"channel": "1001"})
        assert response.status == 302 and "ok=" in location and calls == [("publish", 1000, 14, 1001)]
        response, location = await post(14, "board_publish", {"channel": "2001"})
        assert "err=" in location and len(calls) == 1
        # Auch der bislang systemische Refresh darf bei deaktiviertem Cog nicht veröffentlichen.
        await gc.calendar_channel.set(1001)
        disabled_before = deepcopy(await gc.all())
        original_disabled = bot.cog_disabled_in_guild

        async def disabled(cog, guild):
            return True

        bot.cog_disabled_in_guild = disabled
        for uid, form, payload in ((11, "board_refresh", {}), (11, "rsvp", {"eid": "1", "status": "yes"}),
                                   (11, "event_save", {**values, "event_timezone": "UTC"}),
                                   (14, "board_publish", {"channel": "1001"}),
                                   (14, "settings", {"timezone": "Europe/Berlin"})):
            response, location = await post(uid, form, payload)
            assert response.status == 302 and "deaktiviert" in location
            assert await gc.all() == disabled_before and len(calls) == 1
        bot.cog_disabled_in_guild = original_disabled
        # Rollenentzug wird vor jedem GET und POST erneut berücksichtigt.
        guild.get_member(12).roles = [guild.default_role]
        before = deepcopy(await gc.all())
        response, text = await page(12, {"download": "ics"})
        assert response.status in (302, 403) and "BEGIN:VCALENDAR" not in text
        response, _ = await post(12, "event_save", {**values, "eid": "1", "revision": "2"})
        assert response.status in (302, 403) and await gc.all() == before
        print("Eigene Rückmeldungen, geschützter ICS-Export, Einrichtung, explizites Publizieren und Rollenentzug – OK")
    finally:
        cog.post_board, cog.refresh_board = original_post, original_refresh
        await client.close()
        await second.close()
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
