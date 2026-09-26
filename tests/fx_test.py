"""tickets + raidhelper + twitchlive: Datenlöschung (Tickets), „Neu posten“ (Raidplaner) und die
öffentlichen Launcher-APIs /api/public/raids/<id> und /api/public/twitch/<id>."""
import asyncio
import json
import re
import types

import bootstrap
import tc_harness as T          # zuerst: patcht Member/Kanäle für Tickets (created_at, add_roles …)
import tc_seed
import rm_harness as M
import tw_harness as TW
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


def H(uid):
    return {"X-Test-User": str(uid)}


NR = {"allow_redirects": False}


# =========================================================================== #
#  1. Tickets: red_delete_data_for_user
# =========================================================================== #
async def tickets_section():
    wc, bot, app, tk, cl = await T.make_app()
    await tc_seed.seed(bot, tk, cl)
    g = bot.guilds[0]
    gc = tk.config.guild(g)
    kai, nina, lena = g.get_member(13), g.get_member(15), g.get_member(11)
    await gc.max_open.set(5)
    panels = await gc.panels()
    pa = panels[0]

    # Zusätzliche Tickets: #5 Nina, Kai hinzugefügt + schreibt selbst, Nina erwähnt Kai; #6 Nina, von Kai geschlossen
    r = await tk.open_ticket(g, nina, pa, None, {"Frage": "Ninas Anliegen"})
    ch5 = r.target
    for author, text in ((nina, "Ninas Frage zum Server"), (kai, "KAI-GEHEIM: ich habe das auch"),
                         (nina, "Danke <@13> für den Hinweis"), (lena, "Team-Antwort von Lena")):
        m = L.FakeMessage(ch5, author, text)
        ch5._messages[m.id] = m
    async with gc.tickets() as tickets:
        tickets[str(ch5.id)]["members"] = [13]
        tickets[str(ch5.id)]["claimed_by"] = 11
    rec = (await gc.tickets())[str(ch5.id)]
    await tk._close_ticket(g, ch5, rec, lena, await gc.all())
    r = await tk.open_ticket(g, nina, pa, None, {})
    ch6 = r.target
    rec = (await gc.tickets())[str(ch6.id)]
    await tk._close_ticket(g, ch6, rec, kai, await gc.all())
    # Übernahme-Statistik
    async with gc.stats() as stats:
        stats.setdefault("claims", {}).update({"11": 3, "13": 1})

    tickets = await gc.tickets()
    by_num = {r["num"]: (cid, r) for cid, r in tickets.items()}
    trs = {t["num"]: t for t in await gc.transcripts()}
    check(set(trs) == {1, 3, 5, 6}, f"Seed: Transcripts #1/#3/#5/#6 ({sorted(trs)})")
    tdir = tk.transcripts_dir
    f5 = tdir / trs[5]["file"]
    doc5 = f5.read_text(encoding="utf-8")
    check("data-uid='13'" in doc5 and "<!--/msg-->" in doc5 and "KAI-GEHEIM" in doc5,
          "neues Transcript markiert Nachrichten mit data-uid + Endmarke")
    n_msgs = doc5.count("<!--/msg-->")
    doc6 = (tdir / trs[6]["file"]).read_text(encoding="utf-8")
    check("Geschlossen von: <span data-uid='13'>kai</span>" in doc6, "Kopf „Geschlossen von“ mit data-uid")
    check("Inhaber: <span data-uid='15'>" in doc5, "Kopf „Inhaber“ mit data-uid")

    # Waisen-Dateien: Ersteller Nina ohne Metadaten; Altbestand ohne data-uid mit Erwähnung von Nina
    orphan = tdir / "1000-900.html"
    orphan.write_text("<div class='meta'>Inhaber: <span data-uid='15'>nina</span></div>", encoding="utf-8")
    legacy = tdir / "1000-901.html"
    legacy.write_text("<div class='msg'><span class='name'>X</span><div class='content'>hi &lt;@15&gt; und "
                      "&lt;@!15&gt; und &lt;@150&gt;</div></div>", encoding="utf-8")
    other_guild = tdir / "2000-1.html"
    other_guild.write_text("<div class='msg' data-uid='13'><div class='av'>K</div><div class='body'>"
                           "<span class='name'>Kai</span><span class='time'>t</span><div class='content'>x13x</div>"
                           "<div class='att'>a</div></div></div><!--/msg--><div class='msg' data-uid='5'>"
                           "<span class='time'>t2</span>bleibt</div><!--/msg-->", encoding="utf-8")

    # ---- Kai, requester="user"
    await tk.red_delete_data_for_user(requester="user", user_id=13)
    trs = {t["num"]: t for t in await gc.transcripts()}
    check(1 not in trs and not (tdir / "1000-1.html").exists(), "user: Kais eigenes Transcript #1 gelöscht (Datei + Metadaten)")
    check(3 in trs and 13 not in trs[3]["members"] and 13 not in trs[5]["members"],
          "user: Kai aus „hinzugefügt“ fremder Transcripts entfernt")
    doc5 = f5.read_text(encoding="utf-8")
    check("KAI-GEHEIM" not in doc5 and "data-uid='13'" not in doc5 and "Nachricht entfernt (Datenlöschung)" in doc5
          and "Gelöschter Nutzer" in doc5, "user: Kais Nachricht in Ninas Transcript geschwärzt")
    check("Ninas Frage zum Server" in doc5 and "Team-Antwort von Lena" in doc5 and doc5.count("<!--/msg-->") == n_msgs >= 4,
          "fremde Nachrichten bleiben, Aufbau intakt")
    check("&lt;@13&gt;" not in doc5 and "Danke @Gelöschter Nutzer für den Hinweis" in doc5, "Erwähnung <@13> ersetzt")
    doc6 = (tdir / trs[6]["file"]).read_text(encoding="utf-8")
    check("Geschlossen von: Gelöschter Nutzer" in doc6 and "data-uid='13'" not in doc6, "Kopf „Geschlossen von“ anonymisiert")
    og = other_guild.read_text(encoding="utf-8")
    check("x13x" not in og and "bleibt" in og and og.count("<!--/msg-->") == 2 and "<span class='time'>t</span>" in og,
          "anderer Server: Nachricht mit Anhang exakt ersetzt, Zeit bleibt")
    tickets = await gc.tickets()
    cid1, rec1 = by_num[1]
    check(tickets[cid1]["owner_id"] == 0 and tickets[cid1]["answers"] == {}, "user: geschlossenes Ticket #1 ohne ID/Antworten")
    cid2, _ = by_num[2]
    check(tickets[cid2]["owner_id"] == 13 and tickets[cid2]["status"] == "open",
          "user: offenes Ticket #2 bleibt (Betriebsdaten)")
    cid5 = str(ch5.id)
    check(13 not in tickets[cid5]["members"], "user: aus geschlossenem Ticket #5 entfernt")
    stats = await gc.stats()
    check("13" not in stats["claims"] and stats["claims"].get("11") == 3, "user: eigene Übernahme-Statistik gelöscht")

    client = TestClient(TestServer(app)); await client.start_server()
    r = await client.get("/me/tickets?guild=1000", headers=H(13)); t = await r.text()
    check(r.status == 200 and "Ticket #1" not in t and "Ticket #3" not in t and "Ticket #2" in t,
          "„Meine Tickets“: keine Transcripts mehr, offenes Ticket bleibt")
    r = await client.get("/cogs/tickets?guild=1000&transcript=5", headers=H(1)); t = await r.text()
    check(r.status == 200 and "KAI-GEHEIM" not in t and "Gelöschter Nutzer" in t, "Team-Ansicht zeigt geschwärztes Transcript")
    r = await client.get("/cogs/tickets?guild=1000", headers=H(1))
    check(r.status == 200, "Tickets-Dashboard lädt nach der Löschung")

    # ---- Lena (Team), requester="owner": Übernahmen
    await tk.red_delete_data_for_user(requester="owner", user_id=11)
    tickets = await gc.tickets()
    cid3, _ = by_num[3]
    cid4, _ = by_num[4]
    check(tickets[cid3]["claimed_by"] is None and tickets[cid5]["claimed_by"] is None,
          "owner: Übernahme geschlossener Tickets entfernt")
    check(tickets[cid4]["claimed_by"] == 11, "owner: offenes Ticket #4 behält Übernahme (Betrieb)")
    check("11" not in (await gc.stats())["claims"], "owner: Übernahme-Statistik gelöscht")
    doc5 = f5.read_text(encoding="utf-8")
    check("Team-Antwort von Lena" not in doc5 and "Ninas Frage zum Server" in doc5, "owner: Lenas Nachricht geschwärzt")

    # ---- Nina, requester="user_strict": offene Tickets behalten ID, Antworten weg
    async with gc.tickets() as tk_:
        tk_[cid4]["answers"] = {"Frage": "privat"}
    await tk.red_delete_data_for_user(requester="user_strict", user_id=15)
    tickets = await gc.tickets()
    trs = {t["num"]: t for t in await gc.transcripts()}
    check(set(trs) == set() and not f5.exists(), "user_strict: alle Transcripts mit Nina als Erstellerin gelöscht")
    check(not orphan.exists(), "Waisen-Datei (ohne Metadaten) über data-uid im Kopf erkannt und gelöscht")
    lg = legacy.read_text(encoding="utf-8")
    check("&lt;@15&gt;" not in lg and "&lt;@!15&gt;" not in lg and "&lt;@150&gt;" in lg,
          "Altbestand: Erwähnungen ersetzt, andere IDs unberührt")
    check(tickets[cid4]["owner_id"] == 15 and tickets[cid4]["answers"] == {},
          "user_strict: offenes Ticket behält ID, Formular-Antworten gelöscht")
    check(tickets[cid5]["owner_id"] == 0, "user_strict: geschlossenes Ticket ohne Inhaber-ID")

    # ---- Nina, requester="discord_deleted_user": auch offene Tickets
    await tk.red_delete_data_for_user(requester="discord_deleted_user", user_id=15)
    tickets = await gc.tickets()
    check(tickets[cid4]["owner_id"] == 0 and tickets[cid4]["status"] == "open",
          "discord_deleted_user: Inhaber-ID auch im offenen Ticket entfernt")
    check(tickets[cid2]["owner_id"] == 13, "fremde offene Tickets unberührt")
    raw = json.dumps(await gc.all())
    check('"owner_id": 15' not in raw, "keine Inhaber-ID 15 mehr in der Config")
    # Liste im Befehl zeigt „Gelöschter Nutzer“ statt 0
    sent = []

    class Ctx:
        guild = g; author = g.get_member(1); clean_prefix = "!"; channel = g.get_channel(1001)
        async def send(self, text=None, embed=None, **kw): sent.append(embed.description if embed else text)
    await tk.ticket_list.callback(tk, Ctx(), "all")
    check(sent and "Gelöschter Nutzer" in sent[0] and "· 0 ·" not in sent[0],
          f"Ticket-Liste: „Gelöschter Nutzer“ statt ID 0 ({sent[:1]})")
    # erneuter Aufruf ist harmlos
    await tk.red_delete_data_for_user(requester="user", user_id=13)
    check(True, "erneute Löschung ohne Fehler")
    info = json.loads((bootstrap.ROOT / "tickets" / "info.json").read_text("utf-8"))
    check("Gelöschter Nutzer" in info["end_user_data_statement"], "info.json: end_user_data_statement beschreibt Löschung")
    await client.close()


# =========================================================================== #
#  2. Raidplaner: Neu posten + öffentliche API
# =========================================================================== #
async def raids_section():
    wc, bot, app, rh, ev = await M.make_app()
    g1 = bot.guilds[0]
    client = TestClient(TestServer(app)); await client.start_server()
    gcf = rh.config.guild(g1)

    async def events():
        return await gcf.events()

    async def page(uid, path="/cogs/raidhelper?guild=1000"):
        r = await client.get(path, headers=H(uid))
        return r, await r.text()

    main = ev["main"]
    e = (await events())[main]
    old_mid = e["message_id"]
    ch1 = g1.get_channel(1001)
    r, t = await page(1)
    check(r.status == 200 and "value='repost'" not in t and "Nachricht fehlt" not in t,
          "alle Nachrichten vorhanden -> kein „Neu posten“")

    # ---- Nachricht in Discord gelöscht -> Listener merkt es
    await ch1._messages[old_mid].delete()
    await rh.on_raw_message_delete(types.SimpleNamespace(guild_id=1000, channel_id=1001, message_id=old_mid))
    check((await events())[main]["message_id"] is None, "on_raw_message_delete: message_id geleert")
    await rh.on_raw_message_delete(types.SimpleNamespace(guild_id=1000, channel_id=1001, message_id=123))
    await rh.on_raw_message_delete(types.SimpleNamespace(guild_id=None, channel_id=1, message_id=1))
    check(True, "fremde/DM-Löschungen ohne Fehler")
    r, t = await page(1)
    check(t.count("value='repost'") == 1 and "Nachricht fehlt" in t, "Event-Tabelle: genau ein „Neu posten“ + Badge")
    tok = csrf_of(t)

    # ---- Rechte: Mitglied Kai darf nicht
    L.LOG.clear()
    r = await client.post("/cogs/raidhelper", headers=H(13), data={"csrf_token": tok, "form": "action",
                          "guild": "1000", "event_id": main, "action": "repost"}, **NR)
    check(r.status in (302, 303, 400, 403) and not [x for x in L.LOG if x[0] == "send"]
          and (await events())[main]["message_id"] is None, f"Kai (ohne Recht): abgelehnt ({r.status})")

    # ---- Fehlende Bot-Rechte -> Fehler-Toast, nichts gepostet
    ch1.forbid = {"send"}
    r = await client.post("/cogs/raidhelper", headers=H(1), data={"csrf_token": tok, "form": "action",
                          "guild": "1000", "event_id": main, "action": "repost"}, **NR)
    loc = r.headers.get("Location", "")
    check(r.status == 302 and "err=" in loc and "nicht%20posten" in loc and not [x for x in L.LOG if x[0] == "send"],
          f"fehlende Rechte -> Fehler-Toast ({loc})")
    ch1.forbid = set()

    # ---- Neu posten klappt
    r = await client.post("/cogs/raidhelper", headers=H(1), data={"csrf_token": tok, "form": "action",
                          "guild": "1000", "event_id": main, "action": "repost"}, **NR)
    loc = r.headers.get("Location", "")
    e = (await events())[main]
    sends = [x for x in L.LOG if x[0] == "send" and x[1] == 1001]
    check(r.status == 302 and "ok=" in loc and e["message_id"] and e["message_id"] != old_mid
          and e["message_id"] in ch1._messages and len(sends) == 1 and sends[0][2]["embeds"] == 1 and sends[0][2]["view"],
          "Neu posten: neue Nachricht mit Embed + Buttons, neue ID gespeichert")
    check(len(e["signups"]) == 6, "Anmeldungen bleiben erhalten")
    r, t = await page(1)
    check("value='repost'" not in t, "danach kein „Neu posten“ mehr")

    # ---- Nachricht existiert noch -> alte wird ersetzt (Befehl), keine Doppelten
    sent = []

    class Ctx:
        guild = g1; clean_prefix = "!"; author = g1.get_member(1)
        async def send(self, text=None, **kw): sent.append(text)
    mid_before = e["message_id"]
    await rh.raid_repost.callback(rh, Ctx(), main)
    e = (await events())[main]
    check(mid_before not in ch1._messages and e["message_id"] in ch1._messages and e["message_id"] != mid_before
          and "neu gepostet" in sent[-1] and f"/1000/1001/{e['message_id']}" in sent[-1],
          "[p]raid repost: alte Nachricht gelöscht, neue ID, Antwort mit Link")
    # Löschen der alten Nachricht durch den Bot selbst darf die neue ID nicht leeren
    await rh.on_raw_message_delete(types.SimpleNamespace(guild_id=1000, channel_id=1001, message_id=mid_before))
    check((await events())[main]["message_id"] == e["message_id"], "Listener ignoriert veraltete IDs")
    await rh.raid_repost.callback(rh, Ctx(), "rh-9999")
    check("nicht gefunden" in sent[-1], "Befehl: unbekanntes Event")
    kctx = Ctx(); kctx.author = g1.get_member(13)
    await rh.raid_repost.callback(rh, kctx, main)
    check("Berechtigung" in sent[-1], "Befehl: ohne Manager-Recht abgelehnt")

    # ---- Posten beim Anlegen fehlgeschlagen (message_id None) -> Button; Kanal gelöscht -> Anmelde-Kanal
    locked = g1.get_channel(1007)
    import time
    fail = await rh.create_event(g1, game="wow_retail", title="Fehlgeschlagen", description=None, leader_id=1,
                                 channel_id=1007, start_ts=int(time.time()) + 86400)
    check(fail["message_id"] is None, "Posten in gesperrtem Kanal fehlgeschlagen")
    r, t = await page(1)
    check(t.count("value='repost'") == 1, "fehlgeschlagenes Posten -> „Neu posten“")
    locked.forbid = set()
    await rh.repost_event(g1, fail["id"])
    check((await events())[fail["id"]]["message_id"] in locked._messages, "nach Rechte-Fix: Neu posten im selben Kanal")
    locked._messages.clear()
    g1._remove_channel(locked)
    r, t = await page(1)
    check(t.count("value='repost'") == 1, "Kanal gelöscht -> „Neu posten“")
    ne = await rh.repost_event(g1, fail["id"])
    check(ne["channel_id"] == 1001 and ne["message_id"] in ch1._messages, "Kanal weg -> in den Anmelde-Kanal gepostet")
    # refresh_event_message erkennt gelöschte Nachricht
    ch1._messages.pop(ne["message_id"])
    await rh.refresh_event_message(g1, ne)
    check((await events())[fail["id"]]["message_id"] is None, "refresh_event_message: NotFound -> message_id geleert")

    # ------------------------------------------------------------------ #
    #  Öffentliche API /api/public/raids/<id>
    # ------------------------------------------------------------------ #
    check(await gcf.public_api() is False, "Raid-API Standard: aus")
    bodies = []
    for path in ("/api/public/raids/1000", "/api/public/raids/2000", "/api/public/raids/5555",
                 "/api/public/raids/abc", "/api/public/raids/1000/foo", "/api/public/raids"):
        r = await client.get(path); b = await r.text(); bodies.append(b)
        check(r.status == 404 and json.loads(b) == {"error": "not_found"}, f"aus/unbekannt -> 404 ({path})")
    check(len(set(bodies)) == 1, "404-Antworten identisch")

    r, t = await page(1)
    check("Für Launcher &amp; Website freigeben" in t and "http://localhost/api/public/raids/1000" in t
          and "öffentlich erreichbar" in t and "@everyone" in t and "name='public_api'" in t,
          "Dashboard-Reiter „Launcher & Website“ mit URL, Hinweis und Schalter")
    tok = csrf_of(t)
    data = {"csrf_token": tok, "form": "settings", "guild": "1000", "language": "de", "default_game": "wow_retail",
            "signup_channel": "1001", "timezone": "Europe/Berlin", "cleanup_days": "30", "reminders": "on",
            "member_page": "on", "public_api": "on"}
    r = await client.post("/cogs/raidhelper", headers=H(13), data=data, **NR)
    check(await gcf.public_api() is False, "Mitglied kann die API nicht freigeben")
    r = await client.post("/cogs/raidhelper", headers=H(1), data=data, **NR)
    check(r.status == 302 and await gcf.public_api() is True and await gcf.member_page() is True,
          "Owner gibt API frei (andere Einstellungen bleiben)")

    r = await client.get("/api/public/raids/1000"); d = await r.json(); raw = await r.text()
    check(r.status == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
          and "max-age=60" in r.headers.get("Cache-Control", "") and r.content_type == "application/json",
          "JSON 200 + CORS * + Cache 60 s")
    titles = [x["title"] for x in d["events"]]
    check(d["server"] == "Matters Community", "server-Name")
    check("Gildenintern: Taktikbesprechung" not in titles, "Event im für @everyone versteckten Kanal ausgelassen")
    check("Vergangener Raid" not in titles and "Fremder Server Raid" not in titles, "vergangene/fremde Events fehlen")
    check({"Mythic Undermine", "Molten Core", "Heroic Farm (geschlossen)", "M+ Abend", "Fehlgeschlagen"} == set(titles),
          f"kommende öffentliche Events: {titles}")
    starts = [x["start"] for x in d["events"]]
    check(starts == sorted(starts) and all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s) for s in starts),
          "nach Start sortiert, ISO-8601")
    mu = next(x for x in d["events"] if x["title"] == "Mythic Undermine")
    check(set(mu) == {"id", "title", "game", "start", "deadline", "signups", "max", "full", "roles", "other", "closed", "url"},
          f"Felder: {sorted(mu)}")
    check(mu["id"] == main and mu["game"] == "WoW – Retail" and mu["signups"] == 4 and mu["max"] == 20
          and mu["closed"] is False and mu["full"] is False, "Mythic: id/Spiel/Roster/max/offen")
    check(mu["roles"]["tank"] == {"label": "Tanks", "emoji": "🛡️", "signups": 2, "max": 2}
          and mu["roles"]["healer"]["signups"] == 1 and mu["roles"]["healer"]["max"] == 4
          and mu["roles"]["mdps"]["signups"] == 0 and mu["roles"]["mdps"]["max"] is None and mu["roles"]["rdps"]["signups"] == 1,
          f"Rollen-Belegung: {mu['roles']}")
    check(mu["other"] == {"bench": 0, "late": 1, "tentative": 1, "absence": 0}, "weitere Rückmeldungen als Zahlen")
    check(re.fullmatch(rf"https://discord\.com/channels/1000/1001/{(await events())[main]['message_id']}", mu["url"]),
          "url = Discord-Link zur Event-Nachricht")
    by = {x["title"]: x for x in d["events"]}
    check(by["Heroic Farm (geschlossen)"]["closed"] is True and by["M+ Abend"]["closed"] is True,
          "closed: geschlossen bzw. Anmeldeschluss vorbei")
    check(by["Fehlgeschlagen"]["url"] == "https://discord.com/channels/1000/1001", "ohne Nachricht: Kanal-Link")
    for bad in ("Matters86", "Mia", "Lena", "Arthas", "Jaina", "Tom", "leader", "\"name\"", "5001", "5002",
                "signups\": {", "user", "\"14\"", "\"11\""):
        check(bad not in raw, f"keine Nutzernamen/-IDs im JSON ({bad})")
    for q, n in (("limit=1", 1), ("limit=0", 1), ("limit=-3", 1), ("limit=999", 5), ("limit=abc", 5), ("limit=2", 2)):
        dd = await (await client.get(f"/api/public/raids/1000?{q}")).json()
        check(len(dd["events"]) == n, f"?{q} -> {n} Events")
    r = await client.options("/api/public/raids/1000")
    check(r.status == 204 and r.headers.get("Access-Control-Allow-Origin") == "*", "OPTIONS-Preflight 204 + CORS")
    r = await client.get("/api/public/raids/2000")
    check(r.status == 404, "Server 2000 (nicht freigegeben) -> 404")
    r, t = await page(1)
    ex = t.split("Beispiel-Antwort")[-1][:4000]
    check("M+ Abend" in ex and "&quot;r1&quot;" not in ex, "Beispiel-JSON zeigt echtes nächstes Event")
    data.pop("public_api")
    r = await client.post("/cogs/raidhelper", headers=H(1), data=data, **NR)
    r = await client.get("/api/public/raids/1000")
    check(r.status == 404 and await gcf.public_api() is False, "wieder aus -> 404")
    await gcf.public_api.set(True)
    wc.unregister_owner(rh)
    r = await client.get("/api/public/raids/1000")
    check(r.status == 404, "nach cog_unload (unregister_owner) -> 404")
    await client.close()


# =========================================================================== #
#  3. TwitchLive: öffentliche API
# =========================================================================== #
async def twitch_section():
    wc, bot, app, cog = await TW.make_app()
    g = bot.get_guild(1000)
    gcf = cog.config.guild(g)
    client = TestClient(TestServer(app)); await client.start_server()
    check(await gcf.public_api() is False, "Twitch-API Standard: aus")
    bodies = []
    for path in ("/api/public/twitch/1000", "/api/public/twitch/2000", "/api/public/twitch/5555",
                 "/api/public/twitch/x1", "/api/public/twitch/1000/foo", "/api/public/twitch"):
        r = await client.get(path); b = await r.text(); bodies.append(b)
        check(r.status == 404 and json.loads(b) == {"error": "not_found"}, f"aus/unbekannt -> 404 ({path})")
    check(len(set(bodies)) == 1, "404-Antworten identisch")

    r = await client.get("/cogs/twitchlive?guild=1000", headers=H(1)); t = await r.text()
    check(r.status == 200 and "Für Launcher &amp; Website freigeben" in t
          and "http://localhost/api/public/twitch/1000" in t and "öffentlich erreichbar" in t
          and "name='public_api'" in t and "keine zusätzlichen Twitch-Anfragen" in t,
          "Dashboard-Reiter „Launcher & Website“ mit URL, Hinweis und Schalter")
    check("&quot;login&quot;: &quot;matters86&quot;" in t, "Beispiel-JSON mit echten Daten (escaped)")
    tok = csrf_of(t)
    r = await client.post("/cogs/twitchlive", headers=H(12),
                          data={"csrf_token": tok, "action": "public_api", "guild": "1000", "public_api": "on"}, **NR)
    check(await gcf.public_api() is False, "Tom (nur Ansehen) kann nicht freigeben")
    r = await client.post("/cogs/twitchlive", headers=H(1),
                          data={"csrf_token": tok, "action": "public_api", "guild": "1000", "public_api": "on"}, **NR)
    check(r.status == 302 and "ok=" in r.headers.get("Location", "") and await gcf.public_api() is True,
          "Owner gibt API frei")

    calls = len(cog.fake.calls)
    r = await client.get("/api/public/twitch/1000"); d = await r.json(); raw = await r.text()
    for _ in range(3):
        await client.get("/api/public/twitch/1000")
    check(len(cog.fake.calls) == calls, "API-Aufrufe lösen keine Twitch-Anfragen aus (nur Cache)")
    check(r.status == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
          and "max-age=60" in r.headers.get("Cache-Control", "") and r.content_type == "application/json",
          "JSON 200 + CORS * + Cache 60 s")
    logins = [s["login"] for s in d["streamers"]]
    check(d["server"] == "Matters Community" and logins == ["matters86", "lenaplays", "mia_art"],
          f"nur konfigurierte, aktive Streamer; live zuerst (Zuschauer), pausierter fehlt: {logins}")
    m = d["streamers"][0]
    check(set(m) == {"login", "display_name", "live", "title", "game", "viewers", "started_at", "url", "thumbnail", "avatar"},
          f"Felder: {sorted(m)}")
    check(m["live"] is True and m["display_name"] == "Matters86" and m["title"] == "Ranked-Grind bis Diamant – !discord"
          and m["game"] == "Valorant" and m["viewers"] == 1234 and m["url"] == "https://www.twitch.tv/matters86"
          and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", m["started_at"])
          and m["thumbnail"] == "https://static-cdn.jtvnw.net/previews-ttv/live_user_matters86-640x360.jpg"
          and m["avatar"].startswith("https://static-cdn.jtvnw.net/"), f"Live-Streamer korrekt: {m}")
    off = d["streamers"][2]
    check(off["live"] is False and off["title"] is None and off["viewers"] is None and off["started_at"] is None
          and off["thumbnail"] is None and off["display_name"] == "Mia_Art", f"Offline-Streamer: {off}")
    for bad in ("\"1104\"", "\"11\"", "links", "role", "channel_id", "message_id", "Lena\"", "1003"):
        check(bad not in raw, f"keine Discord-IDs/Verknüpfungen im JSON ({bad})")
    # Stream endet (nach Karenzzeit) -> offline, weiterhin ohne Twitch-Anfrage beim Abruf
    cog.fake.live.pop("lenaplays")
    real_now = cog._now
    cog._now = lambda: real_now() + 400
    await cog.poll_once()
    cog._now = real_now
    calls = len(cog.fake.calls)
    d = await (await client.get("/api/public/twitch/1000?x=1")).json()
    check([s["live"] for s in d["streamers"]] == [True, False, False] and len(cog.fake.calls) == calls,
          "nach Stream-Ende offline (Cache der letzten Abfrage)")
    r = await client.options("/api/public/twitch/1000")
    check(r.status == 204 and r.headers.get("Access-Control-Allow-Origin") == "*", "OPTIONS-Preflight 204 + CORS")
    r = await client.get("/api/public/twitch/2000")
    check(r.status == 404, "Server 2000 (nicht freigegeben) -> 404")
    r = await client.post("/cogs/twitchlive", headers=H(1),
                          data={"csrf_token": tok, "action": "public_api", "guild": "1000"}, **NR)
    r = await client.get("/api/public/twitch/1000")
    check(r.status == 404 and await gcf.public_api() is False, "wieder aus -> 404")
    await gcf.public_api.set(True)
    await cog.cog_unload()
    r = await client.get("/api/public/twitch/1000")
    check(r.status == 404, "nach cog_unload -> 404")
    await client.close()


async def main():
    await tickets_section()
    await raids_section()
    await twitch_section()
    for m in OK:
        print("OK ", m)
    print(f"ALLE FX-TESTS OK ({len(OK)} Prüfungen)")


asyncio.run(main())
