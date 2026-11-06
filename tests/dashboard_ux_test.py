"""Dashboard-Bedienung: echte Vorschau-/Formularanfragen, Rechte, Entwürfe und historische Daten."""
import asyncio
import csv
import io
import re
from datetime import date, datetime, timezone

import tc_harness as T
import wl_harness as W
import tw_harness as TW
from aiohttp.test_utils import TestClient, TestServer

from rc.welcome.welcome import Welcome, MAX_TEXT
from rc.twitchlive.embed import LIMIT_TEMPLATE
from rc.levels.levels import Levels
from rc.giveaways.giveaways import Giveaways
from rc.scheduler.scheduler import Scheduler
from rc.serverstats.serverstats import ServerStats
from rc.webcore import drafts


async def main():
    wc, bot, app, _, _ = await T.make_app()
    W.patch_members(bot)
    guild = bot.guilds[0]
    welcome, levels, giveaways, scheduler, stats = (cls(bot) for cls in (Welcome, Levels, Giveaways, Scheduler, ServerStats))
    twitch = await TW.make_cog(bot, wc)
    for cog in (welcome, levels, giveaways, scheduler, stats):
        bot._cogs[cog.qualified_name] = cog
        cog._register_dashboard(wc)
    slugs = ("welcome", "levels", "giveaways", "scheduler", "serverstats", "twitchlive")
    await wc.config.role_perms.set({"1000": {
        "1101": dict.fromkeys(slugs, "edit"), "1102": dict.fromkeys(slugs, "view"),
        "1104": dict.fromkeys(slugs, "operate"),
    }})
    duplicate = T.H.Member(guild, 77, "Kai", [])
    duplicate.display_avatar = T.L.FakeAsset(77)
    guild.members.append(duplicate)
    await welcome.config.guild(guild).welcome_text.set("Gespeicherter Gruß {name}")
    await welcome.config.guild(guild).welcome_mode.set("text")
    await twitch.config.guild(guild).default_channel.set(1001)
    await twitch.upsert_channel(guild, "alpha", message="GESPEICHERT_ALPHA", verify=False)
    await twitch.upsert_channel(guild, "beta", message="GESPEICHERT_BETA", verify=False)
    client = TestClient(TestServer(app))
    other_session = TestClient(TestServer(app))
    await client.start_server()
    await other_session.start_server()

    async def get(slug, uid=1, params=None, session=None):
        return await (session or client).get(f"/cogs/{slug}", params={"guild": "1000", **(params or {})},
                                              headers={"X-Test-User": str(uid)})

    async def page(slug, uid=1, params=None, session=None):
        response = await get(slug, uid, params, session)
        html = await response.text()
        assert response.status == 200, html[:300]
        match = re.search(r"name='csrf_token' value='([^']+)'", html)
        return html, match.group(1) if match else ""

    async def post(slug, token, values, uid=1):
        return await client.post(f"/cogs/{slug}", headers={"X-Test-User": str(uid)}, allow_redirects=False,
                                  data={"csrf_token": token, "guild": "1000", **values})

    try:
        html, _ = await page("levels")
        assert 'id="wc-module-search"' in html and 'id="wc-favorites"' in html
        assert 'data-module="levels"' in html and 'data-user-id="1"' in html
        assert "data-wc-member-picker" in html and "level-members" in html
        assert "Kai (@kai) · 13" in html and "Kai (@kai) · 77" in html
        _, token = await page("levels")
        response = await post("levels", token, {"form": "xp", "member": "77", "action": "give", "amount": "12"})
        assert "ok=" in response.headers.get("Location", "")
        assert (await levels.member_record(guild, 77))["xp"] == 12
        assert (await levels.member_record(guild, 13))["xp"] == 0
        _, token = await page("levels", 13)
        response = await post("levels", token, {"form": "xp", "member": "13", "action": "give", "amount": "100"}, 13)
        assert response.status in (302, 303, 403) and (await levels.member_record(guild, 13))["xp"] == 0
        html, _ = await page("giveaways")
        assert "<details class='wc-disclosure'>" in html and "Erweitert: Teilnahme-Regeln und Bonus-Lose" in html
        html, _ = await page("scheduler")
        assert "data-wc-when='type'" in html and "data-wc-values='weekly'" in html
        print("Navigation, eindeutige Mitgliederauswahl, XP-Rechte, optionale/abhängige Felder – OK")

        # Ungespeicherte Vorschauen: Bearbeiten sieht Entwurf, Ansehen/Bedienen nur gespeicherte Werte.
        welcome_before = await welcome.config.guild(guild).all()
        twitch_before = await twitch.config.guild(guild).all()
        sent_before = len(T.L.LOG)
        attack = "ENTWURF_<script>alert(1)</script> {name}"
        for uid, editable in ((1, True), (12, False), (13, False)):
            if editable:
                _, token = await page("welcome", uid)
                response = await post("welcome", token, {"form": "message_preview", "kind": "welcome", "text": attack, "mode": "text"}, uid)
            else:
                response = await get("welcome", uid, {"preview": "message", "kind": "welcome", "text": attack, "mode": "text"})
            body = await response.json()
            assert response.status == 200 and ("ENTWURF_" in body["html"]) == editable
            assert "<script>" not in body["html"]
            if editable:
                _, token = await page("twitchlive", uid)
                response = await post("twitchlive", token, {"action": "editor_preview", "login": "alpha", "message": attack, "ping_role": "1101"}, uid)
            else:
                response = await get("twitchlive", uid, {"livepreview": "1", "login": "alpha", "message": attack, "ping_role": "1101"})
            body = await response.json()
            assert response.status == 200 and ("ENTWURF_" in body["html"]) == editable
            assert "<script>" not in body["html"]
        _, token = await page("welcome")
        response = await post("welcome", token, {"form": "message_preview", "kind": "welcome", "text": "😀" * MAX_TEXT,
                                                "mode": "embed", "title": "Titel", "color": "#123456", "image": "https://example.com/welcome.png"})
        body = await response.json()
        assert response.status == 200 and "😀" in body["html"] and "#123456" in body["html"]
        assert 'src="https://example.com/welcome.png"' in body["html"] or "src='https://example.com/welcome.png'" in body["html"]
        _, token = await page("twitchlive")
        response = await post("twitchlive", token, {"action": "editor_preview", "login": "alpha", "message": "😀" * LIMIT_TEMPLATE})
        assert response.status == 200 and "😀" in (await response.json())["html"]
        _, token = await page("welcome", 13)
        response = await post("welcome", token, {"form": "message_preview", "kind": "welcome", "text": "UNERLAUBT"}, 13)
        assert response.status in (302, 303, 403)
        assert await welcome.config.guild(guild).all() == welcome_before
        assert await twitch.config.guild(guild).all() == twitch_before
        assert not any(op[0] in ("send", "webhook_send") for op in T.L.LOG[sent_before:])
        response = await get("welcome", 12, {"preview": "message", "kind": "welcome", "guild": "2000", "text": "FREMD"})
        assert response.status in (302, 303, 403, 404) or str(response.url.query.get("guild")) != "2000"
        print("Vorschauen: keine Speicherung/Discord-Nachricht, sichere Escapes, Rechte und Servergrenzen – OK")

        # Fehlgeschlagene Formulare behalten den Entwurf, getrennt nach Sitzung/Guild/Formular.
        _, token = await page("welcome")
        welcome_values = {"form": "welcome", "channel": "999999", "mode": "text", "text": "DRAFT_WELCOME_<script>", "color": "#123456"}
        response = await post("welcome", token, welcome_values)
        assert "err=" in response.headers["Location"]
        html, _ = await page("welcome", params={"draft": "welcome"})
        assert "DRAFT_WELCOME_&lt;script&gt;" in html and "DRAFT_WELCOME_<script>" not in html
        html, _ = await page("welcome", params={"draft": "leave"})
        assert "DRAFT_WELCOME_" not in html
        html, _ = await page("welcome", params={"draft": "welcome"}, session=other_session)
        assert "DRAFT_WELCOME_" not in html
        html, _ = await page("welcome", params={"draft": "welcome", "guild": "2000"})
        assert "DRAFT_WELCOME_" not in html
        response = await post("welcome", "invalid-token", welcome_values)
        assert response.status == 400
        html, _ = await page("welcome", params={"draft": "welcome"})
        assert "DRAFT_WELCOME_" in html
        _, token = await page("twitchlive")
        for login in ("alpha", "beta"):
            response = await post("twitchlive", token, {"action": "save", "login": login, "channel": "999999",
                                                       "message": "DRAFT_" + login})
            assert "err=" in response.headers["Location"]
        html, _ = await page("twitchlive", params={"draft": "1", "edit": "alpha"})
        assert "DRAFT_alpha" in html and "DRAFT_beta" not in html
        switch = re.search(r"<input[^>]*name='enabled'[^>]*>", html).group(0)
        assert "checked" not in switch
        assert await welcome.config.guild(guild).all() == welcome_before
        assert await twitch.config.guild(guild).all() == twitch_before
        print("Entwürfe: Fehler-Erhalt, CSRF/Sitzung/Server/Formular/Streamer-Isolierung – OK")

        # Historischer Zeitraum: damalige Mitgliederzahl, aktueller Puffer, Vergleich und passende CSV-Zeilen.
        stats._clock = lambda: datetime(2026, 11, 6, 12, tzinfo=timezone.utc).timestamp()
        await stats.config.guild(guild).days.set({
            "2026-10-29": {"members": 100},
            "2026-10-30": {"members": 101, "messages": {"1001": 2}},
            "2026-10-31": {"members": 102, "messages": {"1001": 3}},
            "2026-11-01": {"members": 110, "messages": {"1001": 4}},
            "2026-11-02": {"messages": {"1001": 6}},
        })
        guild.member_count = 9999
        data = await stats.get_period(guild, date(2026, 11, 1), date(2026, 11, 2))
        assert [row[1]["members"] for row in data] == [110, 110]
        params = {"start": "2026-11-01", "end": "2026-11-02"}
        html, _ = await page("serverstats", params=params)
        assert "Stand 02.11.2026" in html and "Vergleich" in html and "30.10.2026" in html
        assert re.search(r"<td>Nachrichten</td>\s*<td>10</td>\s*<td>5</td>\s*<td>\+5</td>", html)
        response = await get("serverstats", params={**params, "export": "days"})
        rows = list(csv.DictReader(io.StringIO((await response.text()).lstrip("\ufeff"))))
        assert [row["datum"] for row in rows] == ["2026-11-01", "2026-11-02"]
        assert [int(row["nachrichten"]) for row in rows] == [4, 6]
        assert [int(row["mitglieder"]) for row in rows] == [110, 110]
        for bad in ({"start": "2026-11-02", "end": "2026-11-01"}, {"start": "falsch", "end": "2026-11-02"},
                    {"start": "0001-01-01", "end": "0001-01-01"}, {"start": "2026-11-01", "end": "2099-11-02"}):
            response = await get("serverstats", params={**bad, "export": "days"})
            assert response.status == 400, (bad, response.status, await response.text())
        print("Statistik: historische Mitglieder, Datumsvergleich/CSV und ungültige Bereiche – OK")

        # Ohne gespeicherte Seite weiterverwendbare Entwürfe bleiben wirklich formulargetrennt.
        req = {"webcore_csrf": "session-a"}
        drafts.remember(welcome, req, 1000, "welcome", {"text": "A"})
        assert drafts.restore(welcome, req, 1000, "welcome")["text"] == "A"
        assert not drafts.restore(welcome, {"webcore_csrf": "session-b"}, 1000, "welcome")
        assert not drafts.restore(welcome, req, 2000, "welcome") and not drafts.restore(welcome, req, 1000, "leave")
        drafts.discard(welcome, req, 1000, "welcome")
        assert not drafts.restore(welcome, req, 1000, "welcome")
    finally:
        await client.close()
        await other_session.close()
        await twitch.cog_unload()
    print("ALLE DASHBOARD-UX-TESTS OK")


asyncio.run(main())
