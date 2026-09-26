"""WebCore: Login, Server-Wechsler, Rollen-Rechte-Matrix, Nur-Ansicht, Selbst-Hochstufung, Audit-Log, Modus admin."""
import asyncio, re
import wc_harness as H
from aiohttp.test_utils import TestServer, TestClient

def csrf(html):
    m = re.search(r"name='csrf_token' value='([^']+)'", html) or re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1)

async def main():
    wc, bot, app = await H.make_app()
    client = TestClient(TestServer(app)); await client.start_server()
    owner = {"X-Test-User": "1"}; lena = {"X-Test-User": "11"}; kai = {"X-Test-User": "13"}; tom = {"X-Test-User": "12"}

    # nicht angemeldet -> Login-Seite
    r = await client.get("/"); t = await r.text()
    assert "Mit Discord anmelden" in t, t[:300]
    # Owner: Seite ohne ?guild -> Redirect auf zuletzt gewählten/ersten Server
    r = await client.get("/cogs/tickets", headers=owner, allow_redirects=False)
    assert r.status == 302 and "guild=" in r.headers["Location"], r.status
    r = await client.get("/cogs/tickets?guild=2000", headers=owner); t = await r.text()
    assert r.status == 200 and "ro-banner" not in t and "tb-guild" in t
    assert "Zugriff &amp; Rollen" in t  # Owner-Navigation
    # Sitzung merkt Server: nächste Seite ohne guild -> 2000
    r = await client.get("/cogs/poll", headers=owner, allow_redirects=False)
    assert "guild=2000" in r.headers["Location"], r.headers["Location"]
    print("Owner: Redirect/Server-Wechsler/Sitzung OK")

    # Kai (keine Rechte) -> Kein Zugriff
    r = await client.get("/", headers=kai); t = await r.text()
    assert r.status == 403 and "keinen Zugriff" in t
    print("Ohne Rechte: 'Kein Zugriff'-Seite OK")

    # Owner vergibt Rechte über /access
    r = await client.get("/access?guild=1000", headers=owner); t = await r.text()
    tok = csrf(t)
    r = await client.post("/access", headers=owner, allow_redirects=False,
                          data={"csrf_token": tok, "form": "add_role", "guild": "1000", "role_id": "1101", "default": "1"})
    assert r.status == 302 and "hinzugef" in r.headers["Location"], r.headers.get("Location")
    # Matrix: Support -> tickets edit, poll view, rest none
    data = [("csrf_token", tok), ("form", "matrix"), ("guild", "1000"), ("roles", "1101")]
    for slug in wc.pages:
        data.append((f"p:1101:{slug}", {"tickets": "edit", "poll": "view"}.get(slug, "none")))
    r = await client.post("/access", headers=owner, data=data, allow_redirects=False)
    perms = await wc.config.role_perms()
    assert perms == {"1000": {"1101": {"tickets": "edit", "poll": "view"}}}, perms
    print("Owner: Rechte-Matrix gespeichert:", perms)

    # Lena (Support)
    r = await client.get("/", headers=lena); t = await r.text()
    assert r.status == 200 and "/cogs/tickets" in t and "/cogs/poll" in t and "/cogs/guard" not in t and "/access" not in t
    assert "Team" in t
    r = await client.get("/cogs/guard?guild=1000", headers=lena)
    assert r.status == 403
    r = await client.get("/cogs/poll?guild=1000", headers=lena); t = await r.text()
    assert r.status == 200 and "ro-banner" in t
    r = await client.get("/cogs/tickets?guild=2000", headers=lena, allow_redirects=False)
    assert r.status == 302 and "guild=1000" in r.headers["Location"]
    r = await client.get("/cogs/tickets?guild=1000", headers=lena); t = await r.text()
    assert "ro-banner" not in t
    tok_l = csrf(t)
    # Speichern auf Umfragen (nur Ansehen) -> abgelehnt
    r = await client.post("/cogs/poll", headers=lena, allow_redirects=False,
                          data={"csrf_token": tok_l, "form": "settings", "guild": "1000", "language": "en"})
    assert "Keine+Bearbeitungsrechte" in r.headers["Location"], r.headers["Location"]
    assert await bot._cogs["Poll"].config.guild(bot.guilds[0]).language() == "de"
    # Speichern auf Tickets (Bearbeiten) -> ok
    r = await client.post("/cogs/tickets", headers=lena, allow_redirects=False,
                          data={"csrf_token": tok_l, "form": "settings", "guild": "1000", "language": "en",
                                "ticket_type": "category", "max_open": "2", "name_template": "ticket-{num}"})
    assert r.status == 302 and "gespeichert" in r.headers["Location"].lower(), r.headers["Location"]
    assert await bot._cogs["Tickets"].config.guild(bot.guilds[0]).language() == "en"
    # Tickets-POST auf fremden Server (keine Rechte) -> abgelehnt
    r = await client.post("/cogs/tickets", headers=lena, allow_redirects=False,
                          data={"csrf_token": tok_l, "form": "settings", "guild": "2000", "language": "en"})
    assert "Keine+Bearbeitungsrechte" in r.headers["Location"]
    assert await bot._cogs["Tickets"].config.guild(bot.guilds[1]).language() == "de"
    # Schutz vor Selbst-Hochstufung: Lena bekommt Autorole-Bearbeiten
    perms = await wc.config.role_perms(); perms["1000"]["1101"]["autorole"] = "edit"; await wc.config.role_perms.set(perms)
    r = await client.post("/cogs/autorole", headers=lena, allow_redirects=False,
                          data={"csrf_token": tok_l, "form": "settings", "guild": "1000", "language": "de",
                                "join_roles": ["1102", "1104"]})  # Moderator (über ihr) + VIP (unter ihr)
    ar_roles = await bot._cogs["Autorole"].config.guild(bot.guilds[0]).join_roles()
    assert ar_roles == [1104], ar_roles
    assert "nicht+%C3%BCbernommen" in r.headers["Location"] or "nicht übernommen" in r.headers["Location"], r.headers["Location"]
    r = await client.post("/cogs/tickets", headers=lena, allow_redirects=False,
                          data={"csrf_token": tok_l, "form": "settings", "guild": "1000", "owner_role": "1102",
                                "ticket_type": "category", "max_open": "1"})
    assert await bot._cogs["Tickets"].config.guild(bot.guilds[0]).owner_role() is None
    r = await client.post("/cogs/tickets", headers=lena, allow_redirects=False,
                          data={"csrf_token": tok_l, "form": "settings", "guild": "1000", "owner_role": "1104",
                                "ticket_type": "category", "max_open": "1"})
    assert await bot._cogs["Tickets"].config.guild(bot.guilds[0]).owner_role() == 1104
    # Owner darf alles
    r = await client.get("/cogs/autorole?guild=1000", headers=owner); tok_o = csrf(await r.text())
    await client.post("/cogs/autorole", headers=owner, allow_redirects=False,
                      data={"csrf_token": tok_o, "form": "settings", "guild": "1000", "join_roles": ["1102"]})
    assert await bot._cogs["Autorole"].config.guild(bot.guilds[0]).join_roles() == [1102]
    print("Selbst-Hochstufung verhindert (Autorole/Ticket-Inhaberrolle), Owner unbeschränkt – OK")

    # Owner-Seiten für Lena gesperrt
    for path in ("/access", "/audit"):
        r = await client.get(path, headers=lena); assert r.status == 403, path
    print("Lena (Support): Navigation, Nur-Ansicht, Speichern erlaubt/abgelehnt, Owner-Seiten gesperrt – OK")

    # Mia hat Support + Raidleitung (ohne eigene Rechte) -> wie Support
    r = await client.get("/cogs/tickets?guild=1000", headers={"X-Test-User": "14"})
    assert r.status == 200
    # Tom (Moderator ohne Rechte) -> kein Zugriff
    r = await client.get("/", headers=tom); assert r.status == 403

    # Audit-Log
    r = await client.get("/audit", headers=owner); t = await r.text()
    audit = await wc.config.audit()
    assert len(audit) >= 4 and "Lena" in t and "abgelehnt" in t, audit[:3]
    print("Audit-Log:", [(a["user_name"], a["page"], a["action"], a["ok"]) for a in audit[:5]])

    # Zugriffsmodus admin: Server-Admin bekommt Bearbeiten auf seinem Server
    await wc.config.access_mode.set("admin")
    bot.guilds[1].members.append(H.Member(bot.guilds[1], 77, "Admin2", [], admin=True))
    r = await client.get("/cogs/guard?guild=2000", headers={"X-Test-User": "77"}); t = await r.text()
    assert r.status == 200 and "ro-banner" not in t and "Server-Admin" in t
    r = await client.get("/cogs/guard?guild=1000", headers={"X-Test-User": "77"}, allow_redirects=False)
    assert "guild=2000" in r.headers["Location"]
    print("Modus admin: Server-Admin nur auf eigenem Server – OK")
    await client.close()
    print("ALLE WEBCORE-TESTS OK")

asyncio.run(main())
