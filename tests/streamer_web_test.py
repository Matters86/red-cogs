"""Streamer im echten WebCore: Einrichtung, Rollen, Filter und sichere Zugangsdaten."""
import asyncio
import copy
import re
from urllib.parse import unquote_plus

from aiohttp.test_utils import TestClient, TestServer

import streamer_harness as S


async def main():
    wc, bot, app, cog = await S.make_app()
    guild = bot.guilds[0]
    gc = cog.config.guild(guild)
    await wc.config.role_perms.set({"1000": {
        "1101": {"streamer": "edit"}, "1102": {"streamer": "operate"},
        "1104": {"streamer": "view"},
    }})
    client = TestClient(TestServer(app))
    await client.start_server()
    tokens = {}
    checks = 0

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
        print("OK   " + message)

    async def page(uid=1, **params):
        response = await client.get("/cogs/streamer", params={"guild": "1000", **params},
                                    headers={"X-Test-User": str(uid)}, allow_redirects=False)
        text = await response.text()
        token = re.search(r"name=['\"]csrf_token['\"] value=['\"]([^'\"]+)['\"]", text)
        if token:
            tokens[uid] = token.group(1)
        return response, text

    async def post(uid, form, fields=None, *, token=None):
        if uid not in tokens:
            await page(uid)
        response = await client.post("/cogs/streamer", headers={"X-Test-User": str(uid)},
            data={"csrf_token": (tokens.get(uid) or next(iter(tokens.values()), "")) if token is None else token,
                  "guild": "1000", "form": form, **(fields or {})}, allow_redirects=False)
        return response, unquote_plus(response.headers.get("Location", ""))

    def rejected(response, location):
        return response.status == 403 or (response.status == 302 and (
            "err=" in location or "Keine Bearbeitungsrechte" in location or "Recht Bearbeiten" in location))

    try:
        before_log = len(S.L.LOG)
        response, text = await page(1)
        check(response.status == 200 and "Streamer" in text and "Twitch" in text and "YouTube" in text
              and "name='title_filter'" in text and len(S.L.LOG) == before_log,
              "Dashboard bietet Einrichtung für beide Plattformen, ohne beim Ansehen zu posten")
        check(all(secret not in text for secret in (S.TWITCH_ID, S.TWITCH_SECRET, S.YOUTUBE_KEY))
              and "type='password'" in text,
              "Vorhandene Zugangsdaten erscheinen nie im HTML; Eingabefelder sind geschützt")
        for uid in (11, 12, 13):
            response, text = await page(uid)
            assert response.status == 200, (uid, response.status, text[:300])
        response, text = await page(14)
        # Mia hat ebenfalls die Supportrolle; sie ist in diesem Test eine Bearbeiterin.
        assert response.status == 200
        check(True, "Ansehen, Bedienen und Bearbeiten erlauben die jeweils freigegebene Seite")

        response, location = await post(11, "settings", {
            "channel_id": "1003", "title_filter": "DNP", "enabled": "on"})
        check(response.status == 302 and "ok=" in location and await gc.channel_id() == 1003
              and await gc.title_filter() == "DNP", "Bearbeiter richtet Kanal und optionalen Titelfilter ein")
        for provider, source in (("twitch", "matters86"), ("youtube", "@projektteam")):
            response, location = await post(11, "add", {"provider": provider, "source": source})
            assert response.status == 302 and "ok=" in location, location
        check(len(await gc.sources()) == 2, "Twitch- und YouTube-Quellen können im Browser hinzugefügt werden")

        initial = copy.deepcopy(await gc.all())
        for uid in (12, 13):
            for form, fields in (
                    ("settings", {"channel_id": "1001", "title_filter": "fremd", "enabled": "on"}),
                    ("add", {"provider": "twitch", "source": "lenaplays"}),
                    ("remove", {"key": "twitch:matters86"})):
                response, location = await post(uid, form, fields)
                assert rejected(response, location), (uid, form, response.status, location)
                assert await gc.all() == initial
        check(True, "Bedienen und Ansehen können Quellen und Einstellungen nicht verändern")

        key = "twitch:matters86"
        response, location = await post(12, "toggle", {"key": key})
        check(response.status == 302 and "ok=" in location and not (await gc.sources())[key]["enabled"],
              "Bedienen darf eine eingerichtete Quelle pausieren")
        await post(12, "toggle", {"key": key})
        fake = cog.api
        fake.go_live(key, title="DNP Twitch")
        fake.go_live("youtube:" + S.YOUTUBE_ID, "video-1", title="DNP YouTube")
        response, location = await post(12, "check")
        check(response.status == 302 and "ok=" in location and len(await gc.state()) == 2,
              "Bedienen darf jetzt prüfen und aktuelle Streams veröffentlichen")
        before = copy.deepcopy(await gc.all())
        calls = len(fake.calls)
        for form, fields in (("toggle", {"key": key}), ("check", {})):
            response, location = await post(13, form, fields)
            assert rejected(response, location), (form, response.status, location)
        check(await gc.all() == before and len(fake.calls) == calls,
              "Ansehen darf weder pausieren noch eine Abfrage auslösen")

        # Zielserver kommt aus der sichtbaren Berechtigungsliste, nicht aus beliebigen Formular-IDs.
        before_second = copy.deepcopy(await cog.config.guild(bot.guilds[1]).all())
        response, location = await post(11, "settings", {
            "guild": "2000", "channel_id": "2001", "title_filter": "Fremd", "enabled": "on"})
        check(rejected(response, location) and await cog.config.guild(bot.guilds[1]).all() == before_second,
              "Gefälschte Ziel-Guild kann keine Einstellungen eines anderen Servers ändern")
        before = copy.deepcopy(await gc.all())
        for fields in ({"channel_id": "2001", "title_filter": "DNP", "enabled": "on"},
                       {"channel_id": "1003", "title_filter": "x" * 101, "enabled": "on"}):
            response, location = await post(11, "settings", fields)
            assert response.status == 302 and "err=" in location, location
            assert await gc.all() == before
        response, _ = await post(11, "settings", {"channel_id": "1001"}, token="ungueltig")
        check(response.status == 400 and await gc.all() == before,
              "Fremde Kanäle, überlange Filter und fehlendes CSRF-Recht bleiben ohne Änderung")

        # Botweite Zugangsdaten erfordern einen separat autorisierten vollen Zugriff.
        for uid in (11, 12, 13):
            response, location = await post(uid, "credentials", {
                "provider": "youtube", "youtube_api_key": "nicht-erlaubt"})
            assert rejected(response, location), (uid, response.status, location)
            assert await cog.config.youtube_api_key() == S.YOUTUBE_KEY
        check(True, "Serverrollen dürfen keine botweiten API-Zugangsdaten überschreiben")
        await wc.config.allowed_users.set([11])
        response, location = await post(11, "credentials", {
            "provider": "youtube", "youtube_api_key": "auch-auf-allowlist-nicht-erlaubt"})
        check(response.status == 403 and await cog.config.youtube_api_key() == S.YOUTUBE_KEY,
              "Ein Allowlist-Zugang ersetzt bei API-Zugangsdaten keine Bot-Owner-Berechtigung")
        await wc.config.allowed_users.set([])
        response, location = await post(1, "credentials", {
            "provider": "youtube", "youtube_api_key": ""})
        check(response.status == 302 and "err=" in location and await cog.config.youtube_api_key() == S.YOUTUBE_KEY,
              "Leere Zugangsfelder löschen gespeicherte Secrets nicht versehentlich")
        new_secret = "new-youtube-secret-not-in-drafts-or-html"
        response, location = await post(1, "credentials", {
            "provider": "youtube", "youtube_api_key": new_secret})
        assert response.status == 302 and "ok=" in location and await cog.config.youtube_api_key() == new_secret
        response, text = await page(1)
        check(new_secret not in text and new_secret not in repr(vars(wc.drafts)),
              "Owner kann Zugangsdaten speichern; Secret erscheint weder im HTML noch im Formularentwurf")

        # Öffentliche Kanalnamen und Streamtitel sind weiterhin nicht vertrauenswürdiger Inhalt.
        payload = "<img src=x onerror=alert('streamer')>"
        async with gc.sources() as sources:
            sources[key]["name"] = payload
        async with gc.state() as state:
            for record in state.values():
                record["stream"]["title"] = payload
                record["stream"]["name"] = payload
        response, text = await page(11)
        check(response.status == 200 and payload not in text and "&lt;img" in text,
              "Quellennamen und Streamtitel werden im Dashboard sicher als Text angezeigt")

        response, location = await post(11, "remove", {"key": key})
        check(response.status == 302 and "ok=" in location and key not in await gc.sources(),
              "Bearbeiter kann eine Quelle wieder entfernen")
        print(f"\n{checks} Streamer-Web-Prüfungen bestanden.")
    finally:
        await client.close()
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
