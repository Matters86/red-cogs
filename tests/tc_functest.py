"""Funktionstests „Meine Tickets“ (Mitglieder-Bereich) + öffentliche Changelog-API."""
import asyncio, json, re
import xml.etree.ElementTree as ET
import tc_harness as T
import tc_seed
L = T.L
from aiohttp.test_utils import TestClient, TestServer

OK = []


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    OK.append(msg)


def csrf_of(html):
    m = re.search(r"name='csrf_token' value='([^']+)'", html)
    return m.group(1) if m else None


async def main():
    wc, bot, app, tk, cl = await T.make_app()
    await tc_seed.seed(bot, tk, cl)
    g = bot.guilds[0]
    gc = tk.config.guild(g)
    client = TestClient(TestServer(app)); await client.start_server()
    H = lambda uid: {"X-Test-User": str(uid)}
    nr = {"allow_redirects": False}

    async def get(uid, path, **kw):
        r = await client.get(path, headers=H(uid), **kw)
        return r, await r.text()

    async def post(uid, path, data, **kw):
        r = await client.post(path, headers=H(uid), data=data, **kw)
        return r, await r.text()

    tickets = await gc.tickets()
    by_num = {r["num"]: (cid, r) for cid, r in tickets.items()}
    trs = {tr["num"]: tr for tr in await gc.transcripts()}
    # Seed: #1 Kai geschlossen, #2 Kai offen, #3 Nina geschlossen (Kai hinzugefügt), #4 Nina offen
    check(set(trs) == {1, 3} and trs[3]["members"] == [13], "Seed: Transcripts #1/#3, #3 mit Kai als Mitglied")

    # ------------------------------------------------------------------ #
    #  Sichtbarkeit: nur eigene Tickets
    # ------------------------------------------------------------------ #
    r, t = await get(13, "/me/tickets?guild=1000")
    check(r.status == 200 and "Meine Tickets" in t, "Kai: /me/tickets lädt")
    check("Ticket #2" in t and "Ticket #1" in t and "Ticket #3" in t and "Ticket #4" not in t,
          "Kai sieht #2 (offen), #1 (eigenes Transcript), #3 (hinzugefügt), NICHT Ninas #4")
    check(f"https://discord.com/channels/1000/{by_num[2][0]}" in t and by_num[4][0] not in t,
          "Link zum eigenen Kanal, keine fremde Kanal-ID")
    check("Absturz" not in t and "geheim" not in t, "keine fremden Antworten/Inhalte")
    r, t = await get(15, "/me/tickets?guild=1000")
    check("Ticket #4" in t and "In Bearbeitung" in t and "Ticket #2" not in t and "Ticket #1" not in t,
          "Nina sieht nur ihre Tickets, Status „In Bearbeitung“ (übernommen)")
    check("Lena" not in t.split("wc-main")[-1] if "wc-main" in t else True, "kein Name des Team-Mitglieds")

    # ------------------------------------------------------------------ #
    #  Transcripts – ID-Raten
    # ------------------------------------------------------------------ #
    r, t = await get(13, "/me/tickets?guild=1000&transcript=1")
    check(r.status == 200 and "Hallo &lt;b&gt;Team&lt;/b&gt; &amp; co" in t and "<b>Team</b>" not in t,
          "Kai: eigenes Transcript #1 (escaped wie im Team-Dashboard)")
    team = await client.get("/cogs/tickets?guild=1000&transcript=1", headers=H(1)); team_t = await team.text()
    check(team_t == t, "Transcript identisch mit der Team-Ansicht")
    r, t = await get(13, "/me/tickets?guild=1000&transcript=3")
    check(r.status == 200 and "&lt;script&gt;" in t and "<script>alert" not in t, "Kai: #3 (hinzugefügt) sichtbar, escaped")
    for uid, num in ((15, 1), (13, 4), (13, 999), (13, "../1000-1.html"), (13, "1%00"), (12, 1), (12, 3)):
        r, t = await get(uid, f"/me/tickets?guild=1000&transcript={num}")
        check(r.status == 404 and "Bewerbung" not in t, f"User {uid}: fremdes/erfundenes Transcript {num!r} -> 404")
    # fremder Server / kein Mitglied
    r, t = await get(13, "/me/tickets?guild=2000&transcript=1", **nr)
    check(r.status in (302, 303) and "err=" in r.headers.get("Location", ""), "Kai: Server 2000 -> abgelehnt (Redirect mit err)")
    r, t = await get(21, "/me/tickets?guild=1000", **nr)
    check(r.status in (302, 303, 403), "Ben (nicht auf 1000, Portal auf 2000 aus) -> kein Zugang")
    r, t = await get(99, "/me/tickets?guild=1000&transcript=1", **nr)
    check(r.status in (302, 303, 403), "Fremder -> kein Zugang")

    # ------------------------------------------------------------------ #
    #  [p]ticket add / remove speichern Mitglieder
    # ------------------------------------------------------------------ #
    cid4 = by_num[4][0]
    ch4 = g.get_channel(int(cid4))
    sent = []

    async def csend(*a, **k):
        sent.append(a)
    ctx = types_ns(guild=g, channel=ch4, author=g.get_member(11), send=csend)
    await tk.ticket_add.callback(tk, ctx, g.get_member(12))
    check((await gc.tickets())[cid4].get("members") == [12], "[p]ticket add speichert Mitglied")
    r, t = await get(12, "/me/tickets?guild=1000")
    check("Ticket #4" in t and "Hinzugefügt" in t, "Tom sieht Ticket #4 als „Hinzugefügt“")
    await tk.ticket_remove.callback(tk, ctx, g.get_member(12))
    check((await gc.tickets())[cid4].get("members") == [], "[p]ticket remove entfernt Mitglied")
    r, t = await get(12, "/me/tickets?guild=1000")
    check("Ticket #4" not in t, "Tom sieht #4 nach remove nicht mehr")

    # ------------------------------------------------------------------ #
    #  Neues Ticket – Panels, Formular, Erstellen wie der Button
    # ------------------------------------------------------------------ #
    r, t = await get(14, "/me/tickets?guild=1000")
    check("new=pa" in t and "new=pb" in t and "reason=r1" in t and "new=ph" not in t and "new=pn" not in t,
          "Mia: sieht Panels pa/pb, NICHT #team-intern (ph) und ungepostetes pn")
    check("&lt;b&gt;Bug&lt;/b&gt; melden" in t and "<b>Bug</b>" not in t, "Grund-Label escaped")
    check("&lt;:custom:123&gt;" not in t and ":custom:" not in t, "Server-Emoji nicht als Text")
    r, t = await get(1, "/me/tickets?guild=1000")
    check("new=ph" in t, "Owner (Admin) sieht auch das Panel in #team-intern")
    r, t = await get(14, "/me/tickets?guild=1000&new=pb&reason=r2")
    check(r.status == 200 and "name='q0'" in t and "required" in t and "name='q1'" in t and "(optional)" in t
          and "maxlength='1000'" in t, "Formular mit den Fragen des Panels (Pflicht/optional/max. 1000)")
    tok = csrf_of(t)
    for q, ok in (("new=ph&reason=_", False), ("new=pn&reason=_", False), ("new=pb&reason=zz", False),
                  ("new=pb&reason=_", False), ("new=pa&reason=r1", False), ("new=pa&reason=_", True)):
        r, _ = await get(14, f"/me/tickets?guild=1000&{q}", **nr)
        check((r.status == 200) == ok, f"GET Formular {q}: {'ok' if ok else 'abgelehnt'}")

    base = {"csrf_token": tok, "form": "open", "guild": "1000"}
    n_before = len(await gc.tickets())
    bad = [
        ({"panel": "ph", "reason": "_"}, "nicht (mehr) verfügbar"),
        ({"panel": "pn", "reason": "_"}, "nicht (mehr) verfügbar"),
        ({"panel": "pb", "reason": "zz", "q0": "x"}, "nicht (mehr) verfügbar"),
        ({"panel": "pb", "reason": "_", "q0": "x"}, "nicht (mehr) verfügbar"),
        ({"panel": "pb", "reason": "r2", "q0": "   "}, "Pflichtfrage"),
        ({"panel": "pb", "reason": "r2", "q0": "x" * 1001}, "zu lang"),
        ({"panel": "pb", "reason": "r2", "q0": "ok", "q1": "y" * 1001}, "zu lang"),
    ]
    from urllib.parse import unquote_plus
    for data, needle in bad:
        r, _ = await post(14, "/me/tickets", {**base, **data}, **nr)
        loc = unquote_plus(r.headers.get("Location", ""))
        check(r.status in (302, 303) and needle in loc, f"POST {data.get('panel')}/{data.get('reason')} abgelehnt: {needle}")
    check(len(await gc.tickets()) == n_before, "keine Tickets durch ungültige Anfragen")
    r, _ = await post(14, "/me/tickets", {**base, "csrf_token": "falsch", "panel": "pa", "reason": "_"}, **nr)
    check(r.status == 400, "falsches CSRF-Token -> 400")

    L.LOG.clear(); T.ROLE_LOG.clear()
    r, _ = await post(14, "/me/tickets", {**base, "panel": "pb", "reason": "r2",
                                          "q0": "Spiel stürzt ab\nzweite Zeile", "q1": "Details <b>fett</b>\r\nZeile 2"}, **nr)
    loc = r.headers.get("Location", "")
    check(r.status in (302, 303) and "created=" in loc and "ok=" in loc, "Mia: Ticket über die Website erstellt -> Redirect mit Link")
    new_cid = re.search(r"created=(\d+)", loc).group(1)
    rec = (await gc.tickets())[new_cid]
    check(rec["owner_id"] == 14 and rec["reason_id"] == "r2" and rec["panel_id"] == "pb" and rec["status"] == "open",
          "Datensatz wie beim Button (Inhaber, Panel, Grund, offen)")
    check(rec["answers"] == {"Worum geht es?": "Spiel stürzt ab zweite Zeile", "Details": "Details <b>fett</b>\nZeile 2"},
          "Antworten: Kurzfeld einzeilig, langes Feld mit Zeilenumbruch, Schlüssel = Frage")
    ops = [x[0] for x in L.LOG]
    check(ops == ["channel_create", "send", "send"], f"Discord: Kanal + Begrüßung + Log wie beim Button ({ops})")
    ch = g.get_channel(int(new_cid))
    msg = list(ch._messages.values())[0]
    fields = [(f.name, f.value) for f in msg.embeds[0].fields]
    check(fields[1:] == [("Worum geht es?", "Spiel stürzt ab zweite Zeile"), ("Details", "Details <b>fett</b>\nZeile 2")]
          and "<@&1102>" in (msg.content or ""), "Embed-Felder + Ping-Rolle wie beim Button")
    check(T.ROLE_LOG == [("add", 14, [1104])], "Inhaber-Rolle vergeben")
    check(ch.name == "b-bug-b-melden-5", f"Kanalname nach Grund ({ch.name})")
    r, t = await get(14, loc)
    check("Dein Ticket <b>#5</b> wurde erstellt" in t and f"channels/1000/{new_cid}" in t, "Bestätigung mit Link zum neuen Kanal")
    r, t = await get(14, f"/me/tickets?guild=1000&created={by_num[4][0]}")
    check("wurde erstellt" not in t, "created= mit fremder Kanal-ID zeigt nichts")

    # Limit (max_open=1)
    L.LOG.clear()
    r, _ = await post(14, "/me/tickets", {**base, "panel": "pa", "reason": "_"}, **nr)
    check("maximale Anzahl" in unquote_plus(r.headers.get("Location", "")) and not L.LOG, "Limit greift (max. 1 offen), nichts in Discord")
    r, t = await get(14, "/me/tickets?guild=1000")
    check("maximale Anzahl offener Tickets (1)" in t and "new=pa" not in t, "Neues Ticket: Hinweis statt Panels bei erreichtem Limit")
    r, t = await get(14, "/me/tickets?guild=1000&new=pa&reason=_")
    check("maximale Anzahl" in t and "name='q0'" not in t and "form" in t, "Formularseite zeigt Limit-Hinweis")
    # gleicher Nutzer: Discord-Button nach Web-Ticket -> gleiche Sperre
    rec_i = []
    await tk.on_interaction(T.Inter(rec_i, g, g.get_member(14), custom_id="tickets:open:pa:_"))
    check(rec_i and "maximale Anzahl" in rec_i[0][1], "Discord-Button erkennt das Web-Ticket (gemeinsames Limit)")

    # Doppel-Absenden gleichzeitig (Tom hat kein Ticket)
    r, t = await get(12, "/me/tickets?guild=1000&new=pa&reason=_"); tok12 = csrf_of(t)
    b12 = {"csrf_token": tok12, "form": "open", "guild": "1000", "panel": "pa", "reason": "_"}
    res = await asyncio.gather(*(client.post("/me/tickets", headers=H(12), data=b12, allow_redirects=False) for _ in range(3)))
    n_tom = sum(1 for x in (await gc.tickets()).values() if x["owner_id"] == 12 and x["status"] == "open")
    check(n_tom == 1 and sum("created=" in x.headers.get("Location", "") for x in res) == 1,
          "3x gleichzeitig absenden -> genau 1 Ticket (Lock wie beim Button)")
    # max_open=2 -> Tom darf ein zweites
    await gc.max_open.set(2)
    r, _ = await post(12, "/me/tickets", {**b12}, **nr)
    check("created=" in r.headers.get("Location", ""), "max_open=2: zweites Ticket erlaubt")
    await gc.max_open.set(1)

    # Fehler bei der Erstellung (Forum ohne Kanal) -> neutrale Meldung
    await gc.ticket_type.set("forum")
    r, t = await get(13, "/me/tickets?guild=1000")
    # Kai hat ein offenes Ticket -> Limit; Nina auch. Owner nimmt es:
    r, t = await get(1, "/me/tickets?guild=1000&new=pa&reason=_"); tok1 = csrf_of(t)
    r, _ = await post(1, "/me/tickets", {"csrf_token": tok1, "form": "open", "guild": "1000", "panel": "pa", "reason": "_"}, **nr)
    check("konnte nicht erstellt werden" in unquote_plus(r.headers.get("Location", "")), "Erstellung fehlgeschlagen -> Meldung")
    await gc.ticket_type.set("category")

    # ------------------------------------------------------------------ #
    #  Schalter im Team-Dashboard
    # ------------------------------------------------------------------ #
    r, t = await get(1, "/cogs/tickets?guild=1000")
    check("Im Mitglieder-Bereich anzeigen" in t and "Tickets über die Website öffnen erlauben" in t
          and "name='portal_enabled' checked" in t and "name='portal_create' checked" in t, "Team-Dashboard: beide Schalter, Standard an")
    tokt = csrf_of(t)
    conf = await gc.all()
    settings = {"csrf_token": tokt, "form": "settings", "guild": "1000", "language": "de", "ticket_type": "category",
                "max_open": "1", "name_template": "ticket-{num}", "portal_enabled": "on",
                "close_confirmation": "on", "user_can_close": "on", "support_roles": "1101", "owner_role": "1104",
                "category_open": str(conf["category_open"]), "log_channel": str(conf["log_channel"]), "ping_roles": "1102"}
    r, _ = await post(1, "/cogs/tickets", settings, **nr)
    check(await gc.portal_enabled() is True and await gc.portal_create() is False, "Schalter speichern (anzeigen an, erstellen aus)")
    r, t = await get(13, "/me/tickets?guild=1000")
    check("Neues Ticket" not in t.split("<main")[-1] and "Ticket #2" in t, "Erstellen aus: kein Reiter „Neues Ticket“, Übersicht bleibt")
    r, t = await get(13, "/me/tickets?guild=1000&new=pa&reason=_", **nr)
    check(r.status in (302, 303), "Erstellen aus: Formular gesperrt")
    r, _ = await post(13, "/me/tickets", {**base, "panel": "pa", "reason": "_"}, **nr)
    check("nicht über die Website" in unquote_plus(r.headers.get("Location", "")), "Erstellen aus: POST abgelehnt")
    settings.pop("portal_enabled")
    r, _ = await post(1, "/cogs/tickets", settings, **nr)
    r, t = await get(13, "/me/tickets?guild=1000")
    check("Auf diesem Server nicht verfügbar" in t and "Ticket #2" not in t, "Anzeigen aus: neutrale Meldung, keine Tickets")
    r, t = await get(13, "/me/tickets?guild=1000&transcript=1")
    check(r.status == 404, "Anzeigen aus: Transcript 404")
    settings.update(portal_enabled="on", portal_create="on")
    r, _ = await post(1, "/cogs/tickets", settings, **nr)

    # ------------------------------------------------------------------ #
    #  Changelog – öffentliche API
    # ------------------------------------------------------------------ #
    cc = cl.config.guild(g)
    check(await cc.public_api() is False, "Changelog-API Standard: aus")
    bodies = []
    for path in ("/api/public/changelog/1000", "/api/public/changelog/1000/rss", "/api/public/changelog/5555",
                 "/api/public/changelog/5555/rss", "/api/public/changelog/2000", "/api/public/changelog/abc",
                 "/api/public/changelog/1000/foo", "/api/public/changelog"):
        r = await client.get(path); b = await r.text(); bodies.append(b)
        check(r.status == 404 and json.loads(b) == {"error": "not_found"}, f"aus/unbekannt -> 404 ({path})")
    check(len(set(bodies)) == 1, "404-Antworten identisch (verrät nicht, ob der Server existiert)")

    r, t = await get(1, "/cogs/changelog?guild=1000")
    check("Für Launcher &amp; Website freigeben" in t and "https://dash.example.org/api/public/changelog/1000" in t
          and "/rss" in t and "öffentlich erreichbar" in t, "Dashboard-Karte mit fertiger URL + Hinweis")
    check("&lt;script&gt;alert(1)&lt;/script&gt;" in t and "<script>alert(1)" not in t, "Beispiel-JSON escaped")
    tokc = csrf_of(t)
    cconf = await cc.all()
    cs = {"csrf_token": tokc, "form": "settings", "guild": "1000", "channel": str(cconf["channel_id"]), "language": "de",
          "color": "#3DDC97", "categories": "🚗|Fahrzeuge", "public_api": "on"}
    r, _ = await post(1, "/cogs/changelog", cs, **nr)
    check(await cc.public_api() is True, "Freigabe per Dashboard eingeschaltet")

    r = await client.get("/api/public/changelog/1000"); d = await r.json()
    check(r.status == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
          and "max-age=60" in r.headers.get("Cache-Control", "") and r.content_type == "application/json",
          "JSON 200 + CORS * + Cache 60 s")
    check(d["server"] == "Matters Community" and len(d["entries"]) == 10 and d["next_before"] == "cl3",
          "Standard limit=10, neueste zuerst, next_before")
    e0 = d["entries"][0]
    check(e0["id"] == "cl12" and e0["title"] == tc_seed.TRICKY_TITLE and e0["note"] == "Server-Neustart um 20 Uhr"
          and e0["category"] == {"emoji": "🚗", "label": "Fahrzeuge"}, "Eintrag: id/Titel (roh im JSON)/Kategorie/Hinweis")
    check(e0["sections"][0] == {"key": "neu", "title": "Neu", "emoji": "🚗", "items": ["Neues Auto 11", "Zweiter Punkt & <mehr>"]},
          "Abschnitte strukturiert (Stichpunkte ohne Aufzählungszeichen)")
    check(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", e0["created_at"]) and e0["author"] == "Matters86"
          and re.fullmatch(r"https://discord\.com/channels/1000/1003/\d+", e0["url"]), "created_at ISO-8601, Autor-Name, Discord-Link")
    raw = await (await client.get("/api/public/changelog/1000?limit=50")).text()
    check(not re.search(r"author_id|channel_id|message_id|\"(1|11)\"", raw), "keine internen Nutzer-IDs")
    ids = []
    before = None
    while True:
        q = "limit=4" + (f"&before={before}" if before else "")
        d = await (await client.get(f"/api/public/changelog/1000?{q}")).json()
        ids += [e["id"] for e in d["entries"]]
        before = d["next_before"]
        if not before:
            break
    check(ids == [f"cl{i}" for i in range(12, 0, -1)], "Paging mit before: alle 12 ohne Lücke/Doppelte")
    for q, n in (("limit=0", 1), ("limit=-5", 1), ("limit=999", 12), ("limit=abc", 10), ("limit=3&before=12", 3),
                 ("before=cl1", 0), ("before=5", 4)):
        d = await (await client.get(f"/api/public/changelog/1000?{q}")).json()
        check(len(d["entries"]) == n, f"?{q} -> {n} Einträge")
    r = await client.get("/api/public/changelog/1000?before=abc")
    check(r.status == 400 and (await r.json()) == {"error": "bad_request"}, "before ungültig -> 400")
    r = await client.options("/api/public/changelog/1000/rss")
    check(r.status == 204 and r.headers.get("Access-Control-Allow-Origin") == "*", "OPTIONS-Preflight 204 + CORS")

    r = await client.get("/api/public/changelog/1000/rss?limit=3"); x = await r.text()
    check(r.status == 200 and r.content_type == "application/rss+xml" and r.headers.get("Access-Control-Allow-Origin") == "*",
          "RSS 200 application/rss+xml + CORS")
    root = ET.fromstring(x.encode())
    items = root.findall("./channel/item")
    check(root.tag == "rss" and root.get("version") == "2.0" and len(items) == 3, "RSS 2.0 gültiges XML, limit greift")
    it = items[0]
    check(it.findtext("title") == tc_seed.TRICKY_TITLE.replace("\x07", ""), "Titel korrekt escaped (<, &, \", ]]>, Steuerzeichen entfernt)")
    desc = it.findtext("description")
    check("<li>Zweiter Punkt &amp; &lt;mehr&gt;</li>" in desc and "<h3>" in desc, "description = HTML, Inhalte HTML-escaped")
    check(it.findtext("{http://purl.org/dc/elements/1.1/}creator") == "Matters86" and it.findtext("pubDate").endswith("GMT")
          and it.findtext("link").startswith("https://discord.com/channels/1000/1003/"), "creator/pubDate/link")
    check("<script>" not in x, "kein rohes <script> im RSS")
    check(root.findtext("./channel/title") == "Matters Community – Changelog", "Kanal-Titel")
    r = await client.get("/api/public/changelog/2000")
    check(r.status == 404, "Server 2000 (nicht freigegeben) -> 404")
    # Ausschalten -> wieder 404
    cs.pop("public_api")
    r, _ = await post(1, "/cogs/changelog", cs, **nr)
    r = await client.get("/api/public/changelog/1000")
    check(r.status == 404 and await cc.public_api() is False, "wieder ausgeschaltet -> 404")
    # red_delete_data_for_user: Autor anonymisiert
    await cc.public_api.set(True)
    await cl.red_delete_data_for_user(requester="user", user_id=1)
    d = await (await client.get("/api/public/changelog/1000?limit=50")).json()
    check("Matters86" not in json.dumps(d, ensure_ascii=False), "nach Datenlöschung kein Autorname mehr")

    await client.close()
    for m in OK:
        print("OK ", m)
    print(f"{len(OK)} Prüfungen OK")


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


asyncio.run(main())
