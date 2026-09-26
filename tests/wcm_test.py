"""Tests: „Mein Bereich“ (Mitglieder-Portal), öffentliche API, Audit-Log nach Discord."""
import asyncio, re, types
import wcm_harness as M
from aiohttp.test_utils import TestServer, TestClient


def csrf(text):
    m = re.search(r"name='csrf_token' value='([^']+)'", text) or re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1)


async def settle():
    await asyncio.sleep(0.05)


async def main():
    wc, bot, app = await M.make_app()
    client = TestClient(TestServer(app)); await client.start_server()
    owner = {"X-Test-User": "1"}; lena = {"X-Test-User": "11"}; tom = {"X-Test-User": "12"}
    kai = {"X-Test-User": "13"}; ben = {"X-Test-User": "21"}
    nr = dict(allow_redirects=False)

    # ---------------------------------------------------------------- Portal aus
    assert await wc.config.member_portal() == {}
    r = await client.get("/", headers=kai); t = await r.text()
    assert r.status == 403 and "keinen Zugriff" in t, (r.status, t[:200])
    r = await client.get("/me", headers=kai); t = await r.text()
    assert r.status == 403 and "keinen Zugriff" in t
    r = await client.get("/me/profil?guild=1000", headers=kai)
    assert r.status == 403
    print("Portal aus: reines Mitglied bekommt „Kein Zugriff“ wie bisher – OK")

    # ------------------------------------------------- Owner: Audit-Kanal + Portal
    r = await client.get("/audit", headers=owner, **nr)
    assert r.status == 302 and "guild=" in r.headers["Location"]
    r = await client.get("/audit?guild=1000", headers=owner); t = await r.text()
    assert r.status == 200 and "Log-Kanal in Discord" in t and "#logs" in t and "tb-guild" in t
    tok = csrf(t)
    r = await client.post("/audit", headers=owner, data={"csrf_token": tok, "guild": "1000", "channel": "1004"}, **nr)
    assert r.status == 302 and "ok=" in r.headers["Location"], r.headers.get("Location")
    r = await client.post("/audit", headers=owner, data={"csrf_token": tok, "guild": "2000", "channel": "2004"}, **nr)
    assert await wc.config.audit_channels() == {"1000": 1004, "2000": 2004}
    r = await client.post("/audit", headers=owner, data={"csrf_token": tok, "guild": "1000", "channel": "2004"}, **nr)
    assert "err=" in r.headers["Location"]  # Kanal eines anderen Servers
    assert await wc.config.audit_channels() == {"1000": 1004, "2000": 2004}
    await settle()
    assert any(cid == 1004 for cid, _ in M.SENT), M.SENT
    print("Audit-Seite: Kanal-Auswahl speichert, fremder Kanal abgelehnt, Bestätigung als Embed – OK")

    r = await client.get("/access?guild=1000", headers=owner); t = await r.text()
    assert "Mitglieder-Bereich" in t and "Mein Profil" in t and "Meine Tickets" in t and "name='portal'" in t
    M.SENT.clear()
    r = await client.post("/access", headers=owner, data={"csrf_token": tok, "form": "portal", "guild": "1000", "portal": "on"}, **nr)
    assert r.status == 302 and "eingeschaltet" in r.headers["Location"], r.headers["Location"]
    assert await wc.config.member_portal() == {"1000": True}
    audit = await wc.config.audit()
    assert audit[0]["page"] == "access" and audit[0]["action"] == "portal" and audit[0]["ok"] and audit[0]["guild_id"] == 1000
    await settle()
    assert len(M.SENT) == 1 and M.SENT[0][0] == 1004
    emb = M.SENT[0][1]["embed"]; am = M.SENT[0][1]["allowed_mentions"]
    assert emb.colour.value == 0x3DDC97 and "<@1>" in emb.fields[1].value and "Zugriff & Rollen" in emb.fields[2].value
    assert am.users is False and am.roles is False and am.everyone is False
    print("Portal-Schalter auf /access: gespeichert + Audit + grünes Embed ohne Pings – OK")

    # ------------------------------------------------------------ reines Mitglied
    r = await client.get("/", headers=kai, **nr)
    assert r.status == 302 and r.headers["Location"] == "/me"
    r = await client.get("/me", headers=kai, **nr)
    assert r.status == 302 and "guild=1000" in r.headers["Location"]
    r = await client.get("/me?guild=1000", headers=kai); t = await r.text()
    assert r.status == 200 and "Mein Profil" in t and "Meine Tickets" in t and "Mitglied" in t
    assert "/cogs/" not in t and "/access" not in t and "/audit" not in t and "Vorschau" not in t
    assert "Deine Rollen und ein Test-Zähler." in t
    r = await client.get("/me/profil?guild=1000", headers=kai); t = await r.text()
    assert r.status == 200 and "Kai" in t and "VIP" in t and "tb-guild" in t
    tok_k = csrf(t)
    for path in ("/cogs/tickets?guild=1000", "/cogs/example", "/access", "/audit", "/access?guild=1000"):
        r = await client.get(path, headers=kai, **nr)
        assert r.status in (302, 403), (path, r.status)
        if r.status == 302:
            assert r.headers["Location"] == "/me", (path, r.headers["Location"])
        else:
            assert "Mein Bereich" in await r.text()
    r = await client.get("/api/overview", headers=kai); assert r.status == 403
    r = await client.post("/access", headers=kai, data={"csrf_token": tok_k, "form": "portal", "guild": "1000"}, **nr)
    assert r.status == 403 and await wc.config.member_portal() == {"1000": True}
    r = await client.post("/cogs/tickets", headers=kai, data={"csrf_token": tok_k, "guild": "1000", "language": "en"}, **nr)
    assert r.status == 403
    assert await bot._cogs["Tickets"].config.guild(bot.guilds[0]).language() == "de"
    print("Reines Mitglied: Login -> /me, nur Mitglieder-Seiten, Team-/Owner-Seiten 403/Redirect – OK")

    # fremder Server über ?guild=
    M.SENT.clear()
    r = await client.get("/me/profil?guild=2000", headers=kai, **nr)
    assert r.status == 302 and "guild=1000" in r.headers["Location"] and "err=" in r.headers["Location"]
    r = await client.get("/me?guild=2000", headers=kai, **nr)
    assert r.status == 302 and "guild=1000" in r.headers["Location"]
    r = await client.get("/me/profil?guild=abc", headers=kai, **nr)
    assert r.status == 302 and "guild=1000" in r.headers["Location"]
    r = await client.post("/me/profil", headers=kai, data={"csrf_token": tok_k, "form": "click", "guild": "2000"}, **nr)
    assert r.status == 302 and "err=" in r.headers["Location"]
    assert M.COUNTERS.get((2000, 13)) is None and M.COUNTERS.get((1000, 13)) is None
    audit = await wc.config.audit()
    denied = [a for a in audit if a["user_id"] == 13 and not a["ok"]]
    assert any(a["guild_id"] == 2000 and "Server" in (a["result"] or "") for a in denied), denied
    await settle()
    red = [k["embed"] for cid, k in M.SENT if cid == 2004]
    assert red and red[0].colour.value == 0xFF6B6B and "<@13>" in red[0].fields[1].value, M.SENT
    print("Fremder Server per ?guild=/Formular abgelehnt, protokolliert, rotes Embed im Log-Kanal – OK")

    # CSRF-Pflicht
    r = await client.post("/me/profil?guild=1000", headers=kai, data={"form": "click", "guild": "1000"}, **nr)
    assert r.status == 400
    r = await client.post("/me/profil?guild=1000", headers=kai, data={"csrf_token": "falsch", "form": "click"}, **nr)
    assert r.status == 400 and M.COUNTERS.get((1000, 13)) is None
    # gültiger POST (Server aus Formular) -> ok, NICHT im Audit-Log
    n_audit = len(await wc.config.audit())
    r = await client.post("/me/profil", headers=kai, data={"csrf_token": tok_k, "form": "click", "guild": "1000"}, **nr)
    assert r.status == 302 and "ok=" in r.headers["Location"], r.headers["Location"]
    assert M.COUNTERS[(1000, 13)] == 1
    # Server nur aus der Query
    r = await client.post("/me/profil?guild=1000", headers=kai, data={"csrf_token": tok_k, "form": "click"}, **nr)
    assert r.status == 302 and M.COUNTERS[(1000, 13)] == 2
    assert len(await wc.config.audit()) == n_audit, "Mitglieder-POSTs dürfen nicht ins Audit-Log"
    print("CSRF-Pflicht bei /me-POST, gültige Mitglieder-Aktion ohne Audit-Eintrag – OK")

    # Rate-Limit 30/Minute
    wc._member_limiter.reset()
    codes = []
    for _ in range(31):
        r = await client.post("/me/profil", headers=kai, data={"csrf_token": tok_k, "form": "click", "guild": "1000"}, **nr)
        codes.append(r.status)
    assert codes[:30] == [302] * 30 and codes[30] == 429, codes
    t = await r.text()
    assert "Zu viele Anfragen" in t and "wcToast" in t and r.headers.get("Retry-After")
    assert M.COUNTERS[(1000, 13)] == 32
    r = await client.post("/me/profil", headers={**kai, "Accept": "application/json"},
                          data={"csrf_token": tok_k, "form": "click", "guild": "1000"}, **nr)
    assert r.status == 429 and (await r.json())["error"] == "rate_limited"
    # Tom (anderer Nutzer) ist nicht betroffen
    r = await client.get("/me/profil?guild=1000", headers=tom); tok_t = csrf(await r.text())
    r = await client.post("/me/profil", headers=tom, data={"csrf_token": tok_t, "form": "click", "guild": "1000"}, **nr)
    assert r.status == 302
    audit = await wc.config.audit()
    assert sum(1 for a in audit if a["user_id"] == 13 and "Rate-Limit" in (a["result"] or "")) == 1
    print("Rate-Limit: 30 POSTs/Minute, dann 429 + Toast (JSON bei Accept), pro Nutzer, einmal protokolliert – OK")

    # Ben: nur auf Server 2000 (Portal aus) -> kein Zugriff, auch nicht über ?guild=1000
    r = await client.get("/me?guild=1000", headers=ben); t = await r.text()
    assert r.status == 403 and "keinen Zugriff" in t
    r = await client.get("/", headers=ben); assert r.status == 403
    print("Mitglied nur auf Server ohne Portal: kein Zugang, auch nicht per ?guild= – OK")

    # ------------------------------------------------------------ Team + Owner
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "edit"}}})
    r = await client.get("/cogs/tickets?guild=1000", headers=lena); t = await r.text()
    assert r.status == 200 and "/cogs/tickets" in t and 'href="/me/profil"' in t and "Mein Bereich" in t
    assert "role-pill team" in t
    r = await client.get("/me/profil?guild=1000", headers=lena); t = await r.text()
    assert r.status == 200 and "Lena" in t and "/cogs/tickets" in t and "Vorschau" not in t
    r = await client.get("/me/profil?guild=2000", headers=lena, **nr)   # Portal aus, kein Team-Recht dort
    assert r.status == 302 and "guild=1000" in r.headers["Location"]
    r = await client.get("/me?guild=2000", headers=owner); t = await r.text()
    assert r.status == 200 and "Vorschau" in t
    r = await client.get("/me/profil?guild=2000", headers=owner); t = await r.text()
    assert r.status == 200 and "Vorschau." in t and "Matters86" in t
    r = await client.get("/cogs/tickets?guild=1000", headers=owner); t = await r.text()
    assert "/me/profil" in t and "Zugriff &amp; Rollen" in t
    print("Team sieht Team-Seiten + „Mein Bereich“, Owner zusätzlich Vorschau auf Servern ohne Portal – OK")

    # member_context / portal_guilds als Helfer
    from aiohttp.test_utils import make_mocked_request
    req = make_mocked_request("GET", "/me/profil?guild=1000", headers=kai, app=app)
    assert [g.id for g in await wc.portal_guilds(req)] == [1000]
    ctx = await wc.member_context(req)
    assert ctx and ctx[0].id == 1000 and ctx[1].id == 13
    req = make_mocked_request("GET", "/x?guild=2000", headers=kai, app=app)
    assert await wc.member_context(req) is None
    req = make_mocked_request("GET", "/x", headers=ben, app=app)
    assert await wc.portal_guilds(req) == [] and await wc.member_context(req) is None
    print("Helfer portal_guilds/member_context – OK")

    # ------------------------------------------------------------ öffentliche API
    r = await client.get("/api/public/status")
    j = await r.json()
    assert r.status == 200 and j["ok"] and j["tail"] == ""
    assert r.headers["Access-Control-Allow-Origin"] == "*" and r.headers["Cache-Control"] == "public, max-age=60"
    assert "Set-Cookie" not in r.headers
    r = await client.get("/api/public/status/server/1000/online"); j = await r.json()
    assert j["tail"] == "server/1000/online"
    r = await client.options("/api/public/status/x")
    assert r.status == 204 and "GET" in r.headers["Access-Control-Allow-Methods"] and "POST" not in r.headers["Access-Control-Allow-Methods"]
    r = await client.post("/api/public/status"); assert r.status == 405
    r = await client.get("/api/public/boom"); t = await r.text()
    assert r.status == 500 and '"internal_error"' in t and "geheim" not in t and "Traceback" not in t
    assert r.headers["Access-Control-Allow-Origin"] == "*"
    r = await client.get("/api/public/gibtsnicht"); assert r.status == 404
    wc._public_limiter.reset()
    codes = [(await client.get("/api/public/status")).status for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, codes
    r = await client.get("/api/public/status"); assert r.status == 429 and r.headers.get("Retry-After")
    # hinter lokalem Reverse-Proxy: X-Forwarded-For zählt pro echtem Client
    r = await client.get("/api/public/status", headers={"X-Forwarded-For": "8.8.8.8"}); assert r.status == 200
    from rc.webcore.webcore import client_ip
    fake = lambda remote, xff: types.SimpleNamespace(remote=remote, headers={"X-Forwarded-For": xff})
    assert client_ip(fake("127.0.0.1", "8.8.8.8")) == "8.8.8.8"
    assert client_ip(fake("172.17.0.1", "1.1.1.1, 8.8.8.8")) == "8.8.8.8"      # Client schmuggelt vorne etwas ein
    assert client_ip(fake("9.9.9.9", "8.8.8.8")) == "9.9.9.9"                   # öffentliche Gegenstelle: XFF ignoriert
    assert client_ip(fake("::1", "")) == "::1"
    print("Öffentliche API: CORS/Cache-Header, Tail, OPTIONS, 404, 500-JSON ohne Details, 429 nach 60/min, XFF nur von Proxy – OK")

    # ------------------------------------------------------------ Befehle
    sent = []
    async def ctx_send(content=None, **kw): sent.append(content)
    ctx = types.SimpleNamespace(guild=bot.guilds[1], author=types.SimpleNamespace(id=1, display_name="Matters86", display_avatar=None),
                                send=ctx_send, clean_prefix="!")
    M.SENT.clear()
    await wc.webcore_portal.callback(wc, ctx, "on")
    assert await wc.config.member_portal() == {"1000": True, "2000": True} and "ist auf diesem Server an" in sent[-1]
    await wc.webcore_portal.callback(wc, ctx, "off")
    assert await wc.config.member_portal() == {"1000": True}
    await wc.webcore_portal.callback(wc, ctx, "vielleicht")
    assert "on" in sent[-1]
    chan = bot.guilds[1].text_channels[0]
    await wc.webcore_auditchannel.callback(wc, ctx, chan)
    assert (await wc.config.audit_channels())["2000"] == chan.id
    await wc.webcore_auditchannel.callback(wc, ctx, None)
    assert "2000" not in await wc.config.audit_channels()
    audit = await wc.config.audit()
    assert [a["action"] for a in audit[:4]] == ["auditchannel (Befehl)", "auditchannel (Befehl)", "portal (Befehl)", "portal (Befehl)"], audit[:4]
    await settle()
    assert any(cid == 2004 for cid, _ in M.SENT)   # portal on/off-Einträge im (damals gesetzten) Kanal 2004
    # Portal über /access wieder aus (Schalter nicht gesendet)
    r = await client.post("/access", headers=owner, data={"csrf_token": tok, "form": "portal", "guild": "1000"}, **nr)
    assert "ausgeschaltet" in r.headers["Location"] and await wc.config.member_portal() == {}
    r = await client.get("/me", headers=kai); assert r.status == 403
    print("Befehle portal/auditchannel + Schalter aus – OK")

    # ------------------------------------------------------------ Kanal-Fehler blockiert nichts
    async def broken_send(self, *a, **k): raise RuntimeError("Discord down")
    M.H.Chan.send = broken_send
    await wc.config.member_portal.set({"1000": True})
    r = await client.post("/access", headers=owner, data={"csrf_token": tok, "form": "portal", "guild": "1000", "portal": "1"}, **nr)
    assert r.status == 302
    await settle()
    M.H.Chan.send = M._send
    print("Fehler beim Posten ins Log wird nur geloggt – OK")

    # ------------------------------------------------------------ unregister_owner
    wc.unregister_owner(M.DEMO)
    assert not any(p.owner is M.DEMO for p in wc.member_pages.values()) and not any(a.owner is M.DEMO for a in wc.public_apis.values())
    r = await client.get("/me/profil?guild=1000", headers=kai); assert r.status == 404
    r = await client.get("/api/public/status"); assert r.status in (404, 429)
    wc._public_limiter.reset()
    r = await client.get("/api/public/status"); assert r.status == 404
    r = await client.get("/me?guild=1000", headers=kai); t = await r.text()
    assert r.status == 200 and "/me/profil" not in t
    print("unregister_owner entfernt Mitglieder-Seiten und öffentliche API – OK")

    await client.close()
    print("ALLE MEIN-BEREICH-TESTS OK")

asyncio.run(main())
