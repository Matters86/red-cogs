"""WebCore: Bot-Status, Fehlerprotokoll (Handler, Maskierung, kein doppelter Handler), Sichern & Wiederherstellen,
Audit-Log als ui.table – nur Owner, CSRF."""
import asyncio
import json
import logging
import re

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

import ws_harness as WH
from rc.webcore import errorlog
from rc.webcore import backup as bk
import rc.webcore.webcore as wcmod

nr = {"allow_redirects": False}
OWNER = {"X-Test-User": "1"}
LENA = {"X-Test-User": "11"}   # Team (Rollen-Rechte auf Server 1000)
KAI = {"X-Test-User": "13"}    # nur Mitglied („Mein Bereich“)


def csrf(html):
    return re.search(r"name='csrf_token' value='([^']+)'", html).group(1)


def upload(tok, guild, content: bytes, *, name="backup.json", form="preview"):
    fd = FormData()
    fd.add_field("csrf_token", tok)
    fd.add_field("form", form)
    fd.add_field("guild", str(guild))
    fd.add_field("backup", content, filename=name, content_type="application/json")
    return fd


async def main():
    wc, bot, app = await WH.make_app()
    g1, g2 = bot.guilds
    demo = bot._cogs["WsDemo"]
    tickets = bot._cogs["Tickets"]
    client = TestClient(TestServer(app))
    await client.start_server()
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "edit"}}})
    await wc.config.member_portal.set({"1000": True})

    # ------------------------------------------------------------ Rechte
    r = await client.get("/status?guild=1000", headers=OWNER); t = await r.text()
    assert r.status == 200, r.status
    for href in ("/status", "/errors", "/backup"):
        assert f'href="{href}"' in t, href
    r = await client.get("/cogs/tickets?guild=1000", headers=LENA); t = await r.text()
    assert r.status == 200 and 'href="/status"' not in t and 'href="/backup"' not in t and 'href="/errors"' not in t
    for who in (LENA, KAI):
        for path in ("/status", "/errors", "/backup", "/backup?guild=1000"):
            r = await client.get(path, headers=who, **nr)
            assert r.status == 403, (who, path, r.status)
        for path in ("/errors", "/backup"):
            r = await client.post(path, headers=who, data={"csrf_token": "x", "form": "clear", "guild": "1000"}, **nr)
            assert r.status == 403, (who, path, r.status)
    r = await client.get("/backup", **nr); t = await r.text()
    assert "Mit Discord anmelden" in t and "Sichern" not in t
    r = await client.post("/backup", headers=LENA, data=upload("x", 1000, b"{}"), **nr)
    assert r.status == 403
    print("Rechte: nur Owner sieht/erreicht Bot-Status, Fehlerprotokoll, Sichern (Team/Mitglied 403) – OK")

    # ------------------------------------------------------------ Bot-Status
    r = await client.get("/status", headers=OWNER); t = await r.text()
    assert r.status == 200
    for needle in ("Laufzeit", "42 ms", "Python", wcmod.PY_VERSION, "discord.py", wcmod.DPY_VERSION,
                   "Red-DiscordBot", "Arbeitsspeicher", " MB", "Geladene Cogs", "WsDemo", "/cogs/tickets",
                   "/me/wsdemo", "/api/public/wsdemo", "id='wc-cogs'", "wc-table"):
        assert needle in t, needle
    assert "psutil" in t
    # Fallback ohne psutil
    orig_psutil, orig_proc = wcmod.psutil, wc._process
    wcmod.psutil, wc._process = None, None
    try:
        info = wc._process_info()
        assert info["source"] == "resource" and info["rss_mb"] > 0 and info["threads"] >= 1, info
        r = await client.get("/status", headers=OWNER); t = await r.text()
        assert "Spitze" in t and "resource" in t
    finally:
        wcmod.psutil, wc._process = orig_psutil, orig_proc
    print("Bot-Status: Laufzeit, Latenz, Server, Cogs + Registrierungen, RAM/CPU (psutil + resource), Versionen – OK")

    # ------------------------------------------------------------ Fehlerprotokoll
    assert errorlog.installed_count() == 1
    lg = logging.getLogger("red.red-cogs.fakecog")
    lg.info("nur Info – darf nicht erscheinen")
    lg.warning("Warnung <script>alert(1)</script> mit token=abc123456 und Authorization: Bearer xyz987654321")
    try:
        raise ValueError(f"kaputt client_secret={WH.CLIENT_SECRET}&x=1 password: hunter22 <b>fett</b>")
    except ValueError:
        lg.exception("Fehler beim Speichern von %s", "Einstellungen")
    logging.getLogger("red.tickets").error("Ticket-Kanal fehlt (Secret %s)", WH.CLIENT_SECRET)
    recs = wc._errorlog.snapshot()
    assert [r["level"] for r in recs] == ["ERROR", "ERROR", "WARNING"], [r["level"] for r in recs]
    assert recs[0]["source"] == "tickets" and recs[1]["source"] == "fakecog" and recs[1]["logger"] == "red.red-cogs.fakecog"
    assert "ValueError" in recs[1]["traceback"] and "Traceback" in recs[1]["traceback"]
    raw_all = json.dumps(recs)
    for secret in ("abc123456", "xyz987654321", WH.CLIENT_SECRET, "hunter22"):
        assert secret not in raw_all, secret
    r = await client.get("/errors", headers=OWNER); t = await r.text()
    assert r.status == 200 and "nur Info" not in t
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in t and "<script>alert(1)" not in t
    assert "&lt;b&gt;fett&lt;/b&gt;" in t and "<details class='wc-trace'>" in t
    assert "Fehler beim Speichern von Einstellungen" in t and "fakecog" in t and "tickets" in t
    for secret in ("abc123456", "xyz987654321", WH.CLIENT_SECRET, "hunter22"):
        assert secret not in t, secret
    assert "token=••••••" in t and "Bearer ••••••" in t and "client_secret=••••••" in t
    # Filter: Stufe, Quelle, Suche
    t = await (await client.get("/errors?level=ERROR", headers=OWNER)).text()
    assert "Fehler beim Speichern" in t and "Ticket-Kanal" in t and "Warnung &lt;script" not in t
    t = await (await client.get("/errors?source=tickets", headers=OWNER)).text()
    assert "Ticket-Kanal" in t and "Fehler beim Speichern" not in t
    t = await (await client.get("/errors?q=ValueError", headers=OWNER)).text()
    assert "Fehler beim Speichern" in t and "Ticket-Kanal" not in t and "1 von 3" in t
    t = await (await client.get("/errors?q=gibtsnicht", headers=OWNER)).text()
    assert "Keine passenden Einträge" in t
    # Maskierung direkt
    m = errorlog.mask_secrets
    assert m('{"access_token": "abcdef123", "ok": 1}') == '{"access_token": "••••••", "ok": 1}'
    assert m("Authorization: Bot MTAx.abc.def") == "Authorization: Bot ••••••"
    assert m("GET /x?client_id=1&client_secret=s3cr3tvalue") == "GET /x?client_id=1&client_secret=••••••"
    assert m("nichts Geheimes hier") == "nichts Geheimes hier"
    assert m("Wert GEHEIM-12345 drin", known=["GEHEIM-12345"]) == "Wert •••••• drin"
    fake_bot_token = "MTAxMjM0NTY3ODkwMTIzNDU2Nzg5.GabcDE.abcdefghijklmnopqrstuvwxyz0123"
    assert fake_bot_token not in m(f"Login mit {fake_bot_token} fehlgeschlagen")
    # Leeren: CSRF + Audit
    r = await client.post("/errors", headers=OWNER, data={"form": "clear"}, **nr)
    assert r.status == 400 and len(wc._errorlog.records) == 3
    tok = csrf(await (await client.get("/errors", headers=OWNER)).text())
    r = await client.post("/errors", headers=OWNER, data={"csrf_token": tok, "form": "clear"}, **nr)
    assert r.status == 302 and "ok=" in r.headers["Location"] and len(wc._errorlog.records) == 0
    audit = await wc.config.audit()
    assert audit[0]["page"] == "errors" and audit[0]["action"] == "clear" and "3 Einträge" in audit[0]["result"]
    t = await (await client.get("/errors", headers=OWNER)).text()
    assert "Keine Warnungen oder Fehler protokolliert" in t
    print("Fehlerprotokoll: fängt Warnung/Exception, Traceback escaped, Filter/Suche, Maskierung, Leeren (CSRF) – OK")

    # ------------------------------------------------------------ Export
    await demo.config.guild(g1).greeting.set("Moin")
    await demo.config.guild(g1).channels.set([1002, 1003])
    await demo.config.guild(g1).api_token.set("SEHRGEHEIM-G1")
    await demo.config.guild(g2).api_token.set("KEEPME-G2")
    await demo.config.client_secret.set("GLOBALSECRET-XYZ")
    await demo.config.nested.set({"mode": "a", "password": "pw-geheim-123"})
    await tickets.config.guild(g1).language.set("en")
    t = await (await client.get("/backup?guild=1000", headers=OWNER)).text()
    assert "WsDemo" in t and "Tickets" in t and "enctype='multipart/form-data'" in t
    tok = csrf(t)
    r = await client.post("/backup", headers=OWNER, data={"form": "export", "guild": "1000"}, **nr)
    assert r.status == 400
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "export", "guild": "1000"}, **nr)
    assert r.status == 200 and r.content_type == "application/json", (r.status, r.content_type)
    assert "attachment" in r.headers["Content-Disposition"] and "1000" in r.headers["Content-Disposition"]
    body = await r.text()
    exp = json.loads(body)
    assert exp["format"] == "red-cogs-backup" and exp["version"] == 1 and exp["guild_id"] == 1000
    assert exp["guild_name"] == "Matters Community" and exp["created"]
    assert "WebCore" not in exp["cogs"] and "Tickets" in exp["cogs"] and "WsDemo" in exp["cogs"]
    d = exp["cogs"]["WsDemo"]
    assert d["identifier"] == str(WH.DEMO_IDENTIFIER) and "global" not in d
    assert d["guild"]["greeting"] == "Moin" and d["guild"]["channels"] == [1002, 1003] and "api_token" not in d["guild"]
    assert exp["cogs"]["Tickets"]["guild"]["language"] == "en"
    assert "SEHRGEHEIM" not in body and "GLOBALSECRET" not in body and "pw-geheim" not in body
    r = await client.post("/backup", headers=OWNER, **nr,
                          data={"csrf_token": tok, "form": "export", "guild": "1000", "include_global": "on"})
    body_g = await r.text(); exp_g = json.loads(body_g)
    dg = exp_g["cogs"]["WsDemo"]["global"]
    assert dg == {"public_name": "Demo", "nested": {"mode": "a"}}, dg
    assert "GLOBALSECRET" not in body_g and "pw-geheim" not in body_g and WH.CLIENT_SECRET not in body_g
    audit = await wc.config.audit()
    assert audit[0]["page"] == "backup" and audit[0]["action"] == "export" and audit[0]["guild_id"] == 1000
    print("Export: JSON-Format korrekt, alle Cogs mit Seite, keine Secrets (Server + botweit) – OK")

    # ------------------------------------------------------------ Import mit Vorschau
    imp = json.loads(body_g)
    w = imp["cogs"]["WsDemo"]
    w["guild"].update({"greeting": "Servus", "limit": "zehn", "unknown_key": 1, "api_token": "HACK",
                       "options": {"color": "red"}})
    w["global"].update({"public_name": "Neu", "client_secret": "HACK2", "nested": {"mode": "b"}})
    imp["cogs"]["NichtGeladen"] = {"identifier": "1", "guild": {"x": 1}}
    imp["cogs"]["Poll"]["identifier"] = "123"   # anderer Cog gleichen Namens -> übersprungen
    raw = json.dumps(imp).encode()
    before_poll = await bot._cogs["Poll"].config.guild(g2).all()
    t = await (await client.get("/backup?guild=2000", headers=OWNER)).text()
    tok = csrf(t)
    # CSRF beim Upload
    r = await client.post("/backup?guild=2000", headers=OWNER, data=upload("falsch", 2000, raw), **nr)
    assert r.status == 400
    r = await client.post("/backup?guild=2000", headers=OWNER, data=upload(tok, 2000, raw), **nr)
    loc = r.headers["Location"]
    assert r.status == 302 and "preview=" in loc, loc
    pid = re.search(r"preview=([^&]+)", loc).group(1)
    r = await client.get(loc, headers=OWNER); t = await r.text()
    assert r.status == 200
    for needle in ("Vorschau", "anderen Server", "Kanal- und Rollen-IDs", "greeting", "options", "unknown_key",
                   "limit (Zahl erwartet, Text)", "api_token", "NichtGeladen", "übersprungen", "language",
                   "Botweite Einstellungen übernehmen", "Import ausführen", "id='wc-import-plan'"):
        assert needle in t, needle
    assert await demo.config.guild(g2).greeting() == "Hallo", "Vorschau darf nichts ändern"
    plan = await bk.plan_import(wc, g2, imp)
    wsg = next(i for i in plan["cogs"] if i["name"] == "WsDemo")["guild"]
    assert wsg["unknown"] == ["unknown_key"] and wsg["secret"] == ["api_token"], wsg
    assert [k for k, *_ in wsg["type_errors"]] == ["limit"] and set(wsg["changed"]) == {"greeting", "channels", "options"}, wsg
    assert "Unverändert" in t and "unbekannt, wird ignoriert" in t
    # Vorschau gehört zu Server 2000 – Bestätigung für 1000 wird abgelehnt
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "confirm", "guild": "1000",
                                                          "preview": pid}, **nr)
    assert "err=" in r.headers["Location"] and await demo.config.guild(g1).greeting() == "Moin"
    r = await client.post("/backup", headers=OWNER, data={"form": "confirm", "guild": "2000", "preview": pid}, **nr)
    assert r.status == 400
    # Bestätigen (ohne botweit)
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "confirm", "guild": "2000",
                                                          "preview": pid}, **nr)
    loc = r.headers["Location"]
    assert r.status == 302 and "ok=" in loc and "ignoriert" in loc.replace("+", " "), loc
    gd = await demo.config.guild(g2).all()
    assert gd["greeting"] == "Servus" and gd["channels"] == [1002, 1003] and gd["options"] == {"color": "red"}
    assert gd["limit"] == 5 and gd["api_token"] == "KEEPME-G2" and "unknown_key" not in gd, gd
    assert await tickets.config.guild(g2).language() == "en"
    assert await bot._cogs["Poll"].config.guild(g2).all() == before_poll
    assert await demo.config.public_name() == "Demo" and await demo.config.client_secret() == "GLOBALSECRET-XYZ"
    audit = await wc.config.audit()
    assert audit[0]["page"] == "backup" and audit[0]["action"] == "import" and audit[0]["guild_id"] == 2000
    # dieselbe Vorschau lässt sich nicht zweimal ausführen
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "confirm", "guild": "2000",
                                                          "preview": pid}, **nr)
    assert "err=" in r.headers["Location"]
    print("Import: Vorschau ohne Änderung, Bestätigung, unbekannte Keys/Typfehler/Secrets ignoriert, anderer Server – OK")

    # ------------------------------------------------------------ Rückgängig
    t = await (await client.get("/backup?guild=2000", headers=OWNER)).text()
    assert "Rückgängig machen" in t and "id='wc-undo'" in t
    uid = re.search(r"name='undo' value='([^']+)'", t).group(1)
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "undo", "guild": "1000",
                                                          "undo": uid}, **nr)
    assert "err=" in r.headers["Location"], "Rückgängig nur auf dem Server des Imports"
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "undo", "guild": "2000",
                                                          "undo": uid}, **nr)
    assert "ok=" in r.headers["Location"], r.headers["Location"]
    gd = await demo.config.guild(g2).all()
    assert gd["greeting"] == "Hallo" and gd["channels"] == [] and gd["options"] == {"color": "blue"}
    assert gd["api_token"] == "KEEPME-G2"
    assert await tickets.config.guild(g2).language() == "de"
    assert (await wc.config.audit())[0]["action"] == "undo"
    t = await (await client.get("/backup?guild=2000", headers=OWNER)).text()
    assert "id='wc-undo'" not in t
    print("Rückgängig: Ist-Zustand vor dem Import wiederhergestellt, Audit – OK")

    # ------------------------------------------------------------ Import inkl. botweit
    r = await client.post("/backup?guild=2000", headers=OWNER, data=upload(tok, 2000, raw), **nr)
    pid = re.search(r"preview=([^&]+)", r.headers["Location"]).group(1)
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "confirm", "guild": "2000",
                                                          "preview": pid, "include_global": "on"}, **nr)
    assert "ok=" in r.headers["Location"]
    assert await demo.config.public_name() == "Neu" and await demo.config.client_secret() == "GLOBALSECRET-XYZ"
    assert await demo.config.nested() == {"mode": "b", "password": "pw-geheim-123"}, await demo.config.nested()
    assert "botweit" in (await wc.config.audit())[0]["action"]
    t = await (await client.get("/backup?guild=2000", headers=OWNER)).text()
    uid = re.search(r"name='undo' value='([^']+)'", t).group(1)
    await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "undo", "guild": "2000", "undo": uid}, **nr)
    assert await demo.config.public_name() == "Demo" and await demo.config.nested() == {"mode": "a", "password": "pw-geheim-123"}
    print("Import botweit (nur mit Häkchen, Secrets bleiben) + Rückgängig – OK")

    # ------------------------------------------------------------ Fehlerfälle beim Upload
    async def up(content, **kw):
        r = await client.post("/backup?guild=2000", headers=OWNER, data=upload(tok, 2000, content, **kw), **nr)
        return r.status, r.headers.get("Location", "")
    st, loc = await up(b"x" * (bk.MAX_BYTES + 10))
    assert st == 302 and "gro%C3%9F" in loc, (st, loc)
    st, loc = await up(b"x" * (3 * 1024 * 1024))          # weit drüber: Abbruch schon am Content-Length
    assert st == 302 and "gro%C3%9F" in loc, (st, loc)
    big =json.dumps({"format": "red-cogs-backup", "version": 1, "guild_id": 1000, "cogs": {
        "Padding": {"guild": {"blob": "x" * 1_500_000}}, "WsDemo": {"guild": {"greeting": "Gross"}}}}).encode()
    st, loc = await up(big)
    assert st == 302 and "preview=" in loc, (st, loc)   # 1,5 MB > aiohttp-Standardlimit 1 MiB, aber < 2 MB
    st, loc = await up(b"{kein json")
    assert "err=" in loc and "JSON" in loc, loc
    st, loc = await up(json.dumps({"format": "anders"}).encode())
    assert "err=" in loc, loc
    st, loc = await up(json.dumps({"format": "red-cogs-backup", "version": 99, "cogs": {}}).encode())
    assert "err=" in loc and "Version" in loc, loc
    st, loc = await up(b"")
    assert "err=" in loc, loc
    r = await client.post("/backup", headers=OWNER, **nr, data={"csrf_token": tok, "form": "preview", "guild": "2000"})
    assert "err=" in r.headers["Location"]
    # Abbrechen verwirft die Vorschau
    st, loc = await up(raw)
    pid = re.search(r"preview=([^&]+)", loc).group(1)
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "cancel", "guild": "2000",
                                                          "preview": pid}, **nr)
    assert "ok=" in r.headers["Location"] and pid not in wc._import_pending
    t = await (await client.get(f"/backup?guild=2000&preview={pid}", headers=OWNER)).text()
    assert "abgelaufen" in t and "Import ausführen" not in t
    # abgelaufene Vorschau
    st, loc = await up(raw)
    pid = re.search(r"preview=([^&]+)", loc).group(1)
    wc._import_pending[pid]["created"] -= wcmod.IMPORT_PREVIEW_TTL + 1
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "confirm", "guild": "2000",
                                                          "preview": pid}, **nr)
    assert "err=" in r.headers["Location"] and await demo.config.guild(g2).greeting() == "Hallo"
    # Import ohne Änderungen -> kein Rückgängig-Eintrag
    same = json.dumps({"format": "red-cogs-backup", "version": 1, "guild_id": 2000,
                       "cogs": {"WsDemo": {"guild": {"greeting": "Hallo"}}}}).encode()
    st, loc = await up(same)
    pid = re.search(r"preview=([^&]+)", loc).group(1)
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "confirm", "guild": "2000",
                                                          "preview": pid}, **nr)
    assert "Keine+%C3%84nderungen" in r.headers["Location"] and not wc._import_undo.get(2000)
    print("Upload-Fehler: zu groß, 1,5 MB ok, kein JSON, falsches Format/Version, leer, keine Datei, Abbrechen, abgelaufen – OK")

    # ------------------------------------------------------------ Audit-Log als ui.table
    t = await (await client.get("/audit?guild=1000", headers=OWNER)).text()
    assert "class='table wc-table' id='wc-audit'" in t and "id='wc-audit-q'" in t and "id='wc-audit-g'" in t
    assert "data-guild='2000'" in t and "Sichern &amp; Wiederherstellen" in t and "Fehlerprotokoll" in t
    print("Audit-Log: ui.table (Handy-Karten) mit Suche + Server-Filter, neue Seiten benannt – OK")

    # ------------------------------------------------------------ kein doppelter Handler
    before = len(wc._errorlog.records)
    logging.getLogger("red.red-cogs.fakecog").warning("vor dem Neuladen")
    wc._install_error_log()
    wc._install_error_log()
    assert errorlog.installed_count() == 1
    wc2 = wcmod.WebCore(bot)                 # „[p]reload webcore“: neue Instanz, alter Handler hängt noch
    wc2._install_error_log()
    assert errorlog.installed_count() == 1
    assert any(r["message"] == "vor dem Neuladen" for r in wc2._errorlog.records), "Puffer wird übernommen"
    assert len(wc2._errorlog.records) == before + 1
    logging.getLogger("red.red-cogs.fakecog").error("nach dem Neuladen")
    assert wc2._errorlog.records[-1]["message"] == "nach dem Neuladen"
    await wc2.cog_unload()
    assert errorlog.installed_count() == 0 and wc2._errorlog is None
    await wc.cog_unload()                    # alter Handler bereits ersetzt – darf nicht stören
    assert errorlog.installed_count() == 0
    assert not any(getattr(h, "_webcore_errorlog", False) for h in logging.getLogger("red").handlers)
    print("Fehlerprotokoll: kein doppelter Handler nach zweimaligem Laden, cog_unload entfernt ihn – OK")

    await client.close()
    print("ALLE WS-TESTS OK")


asyncio.run(main())
