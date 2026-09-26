"""Funktionstest Raidplaner-Mitgliederseite /me/raids (Sichtbarkeit, Aktionen, Ablehnungen, Discord-Update)."""
import asyncio, re, sys
from urllib.parse import urlparse, parse_qs
import rm_harness as M
L = M.L
from aiohttp.test_utils import TestServer, TestClient

OK = []
def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg); OK.append(bool(cond))

def loc(r):
    u = urlparse(r.headers.get("Location", "")); return u.path, parse_qs(u.query)

KAI = {"X-Test-User": "13"}; MIA = {"X-Test-User": "14"}; BEN = {"X-Test-User": "21"}; OWNER = {"X-Test-User": "1"}


async def main():
    wc, bot, app, rh, ev = await M.make_app()
    g = bot.guilds[0]
    client = TestClient(TestServer(app)); await client.start_server()

    async def page(path, h):
        r = await client.get(path, headers=h, allow_redirects=False)
        return r, await r.text()

    async def token(h):
        _r, t = await page("/me/raids?guild=1000", h)
        m = re.search(r"name='csrf_token' value='([^']+)'", t)
        return m.group(1) if m else ""

    async def post(h, **data):
        data.setdefault("guild", "1000")
        data.setdefault("csrf_token", await token(h))
        wc._member_limiter._hits.clear()  # Rate-Limit (30/min) gilt pro Nutzer – für den Testlauf zurücksetzen
        r = await client.post("/me/raids", data=data, headers=h, allow_redirects=False)
        return r, loc(r)

    async def evs():
        return await rh.config.guild(g).events()

    def msg_embed(e):
        return g.get_channel(e["channel_id"])._messages[e["message_id"]].embeds[0].to_dict()

    # ---- Kachel + Sichtbarkeit
    r, t = await page("/me?guild=1000", KAI)
    check(r.status == 200 and "/me/raids?guild=1000" in t and "Kommende Raids ansehen und dich anmelden" in t,
          "Kachel „Raids“ mit Beschreibung auf /me")
    r, t = await page("/me/raids?guild=1000", KAI)
    check(r.status == 200, f"Kai: /me/raids -> 200 ({r.status})")
    check("Mythic Undermine" in t and "Molten Core" in t and "Heroic Farm" in t and "M+ Abend" in t,
          "Kai sieht die Events in sichtbaren Kanälen")
    check("Taktikbesprechung" not in t, "Kai sieht das Event im versteckten Kanal NICHT")
    check("Vergangener Raid" not in t and "Fremder Server" not in t, "kein vergangenes/abgeschlossenes, kein fremdes Event")
    check("In Discord öffnen" in t and "https://discord.com/channels/1000/1001/" in t, "Link „In Discord öffnen“")
    check("geschlossen" in t and "Anmeldeschluss vorbei" in t and "offen" in t, "Status-Pills offen/geschlossen/Anmeldeschluss")
    check("Tanks 2/2" in t and "Heiler 1/4" in t and "Im Roster" in t and "4 / 20" in t, "Belegung gesamt und je Rolle")
    check("Europe/Berlin" in t and re.search(r"in \d Tag", t) and " Uhr" in t, "Termin in Server-Zeitzone + relativ")
    check("…" in t and "**" not in t, "Beschreibung gekürzt, ohne Markdown")
    check("<optgroup label='Krieger'>" in t and "value='krieger:furor'" in t, "Klasse+Spec gruppiert (Vorlage)")
    r, t = await page("/me/raids?guild=1000", MIA)
    check("Taktikbesprechung" in t, "Mia (Raidleitung) sieht das Event im internen Kanal")
    check("Du bist <b>angemeldet</b> als <b>Heilig Priester</b>" in t, "eigener Status hervorgehoben (Mia)")
    r, _ = await page(f"/me/raids?guild=1000&event={ev['hidden']}", KAI)
    check(r.status == 302 and "err" in loc(r)[1], "Detail des versteckten Events -> abgelehnt")
    r, t = await page(f"/me/raids?guild=1000&event={ev['main']}", KAI)
    check(r.status == 200 and "Roster" in t and "Arthas" in t and "Jaina" in t and "Vielleicht (1)" in t
          and "Spät (1)" in t, "Detailansicht mit Roster und weiteren Rückmeldungen")
    check("Raidleitung" in t and "Mia" in t, "Raidleitung in der Detailansicht")

    # ---- Anmelden
    main = ev["main"]
    L.LOG.clear()
    r, (path, q) = await post(KAI, event_id=main, action="signup", pick="krieger:furor", back="detail")
    e = (await evs())[main]
    s = e["signups"].get("13")
    check(q.get("ok") == ["✅ Angemeldet als Furor Krieger (Nahkampf)."] and q.get("event") == [main],
          f"Anmelden -> Toast wie Button + zurück zur Detailansicht ({q})")
    check(s and s["class"] == "krieger" and s["spec"] == "furor" and s["role"] == "mdps" and s["status"] == "signed"
          and s["name"] == "Kai", f"Config: {s}")
    edits = [x for x in L.LOG if x[0] == "edit" and x[2]["message"] == e["message_id"]]
    check(len(edits) == 1, f"Discord-Nachricht aktualisiert ({len(edits)} Edit)")
    check("Kai" in str(msg_embed(e)), "Kai steht im Embed-Roster")
    rem = await rh.config.user_from_id(13).remember()
    check(rem.get("wow_retail:krieger") == "furor", f"Spec gemerkt wie beim Button: {rem}")
    at0 = s["at"]

    # ---- Spec wechseln
    r, (path, q) = await post(KAI, event_id=main, action="signup", pick="krieger:waffen")
    s = (await evs())[main]["signups"]["13"]
    check(q.get("ok") == ["🔄 Spec geändert auf Waffen Krieger."] and s["spec"] == "waffen" and s["at"] == at0
          and "event" not in q, f"Spec wechseln -> spec_changed, Zeitpunkt bleibt, zurück zur Liste ({q})")
    # Rolle voll (Tanks 2/2)
    r, (path, q) = await post(KAI, event_id=main, action="signup", pick="krieger:schutz")
    s = (await evs())[main]["signups"]["13"]
    check(q.get("err") == ["Diese Rolle ist voll (Tanks: 2)."] and s["spec"] == "waffen", f"Rolle voll abgelehnt ({q})")
    # ungültige Klasse/Spec
    for pick in ("krieger:heilig", "foo:bar", "", "krieger", "paladin:schutz:x"):
        L.LOG.clear()
        r, (path, q) = await post(KAI, event_id=main, action="signup", pick=pick)
        s = (await evs())[main]["signups"]["13"]
        check(q.get("err") == ["Auswahl nicht erkannt – bitte erneut versuchen."] and s["spec"] == "waffen"
              and not [x for x in L.LOG if x[0] == "edit"], f"ungültige Auswahl {pick!r} abgelehnt, nichts geändert")

    # ---- Status
    L.LOG.clear()
    r, (path, q) = await post(KAI, event_id=main, action="status", status="late", back="detail")
    s = (await evs())[main]["signups"]["13"]
    check(q.get("ok") == ["✅ Du stehst jetzt auf: Spät."] and s["status"] == "late" and s["class"] == "krieger",
          f"Status Spät (Klasse bleibt) ({q})")
    check(any(x[0] == "edit" for x in L.LOG), "Status: Discord-Nachricht aktualisiert")
    r, (path, q) = await post(KAI, event_id=main, action="status", status="signed")
    check(q.get("err") == ["Auswahl nicht erkannt – bitte erneut versuchen."], "status=signed per Status-Formular abgelehnt")
    r, t = await page(f"/me/raids?guild=1000&event={main}", KAI)
    check("Du stehst auf <b>Spät</b>" in t and "aria-pressed='true'" in t, "Detail zeigt eigenen Status Spät")
    # zurück ins Roster -> signed (nicht spec_changed)
    r, (path, q) = await post(KAI, event_id=main, action="signup", pick="krieger:furor")
    check(q.get("ok") == ["✅ Angemeldet als Furor Krieger (Nahkampf)."], "von Spät zurück ins Roster -> signed")

    # ---- Abmelden
    L.LOG.clear()
    r, (path, q) = await post(KAI, event_id=main, action="leave", back="detail")
    check(q.get("ok") == ["↩️ Du wurdest vom Event abgemeldet."] and "13" not in (await evs())[main]["signups"]
          and any(x[0] == "edit" for x in L.LOG), "Abmelden -> Config + Discord-Update")
    r, (path, q) = await post(KAI, event_id=main, action="leave")
    check(q.get("err") == ["Du bist für dieses Event nicht angemeldet."], "Abmelden ohne Anmeldung -> not_signed")

    # ---- geschlossen / Anmeldeschluss
    r, (path, q) = await post(KAI, event_id=ev["closed"], action="signup", pick="krieger:furor")
    check(q.get("err") == ["Die Anmeldung für dieses Event ist geschlossen."], "geschlossen -> abgelehnt")
    r, (path, q) = await post(KAI, event_id=ev["closed"], action="status", status="absence")
    check(q.get("err") == ["Die Anmeldung für dieses Event ist geschlossen."], "Status bei geschlossen -> abgelehnt")
    r, (path, q) = await post(KAI, event_id=ev["deadline"], action="signup", pick="magier:frost")
    check(q.get("err") == ["Der Anmeldeschluss ist bereits vorbei."], "Anmeldeschluss -> abgelehnt")
    check("13" not in (await evs())[ev["closed"]]["signups"] and "13" not in (await evs())[ev["deadline"]]["signups"],
          "keine Daten bei Ablehnung")

    # ---- voll
    async with rh.config.guild(g).events() as es:
        es[ev["mc"]]["max_signups"] = 1
        es[ev["mc"]]["signups"]["11"] = {"name": "Lena", "class": "magier", "spec": "frost", "role": "rdps",
                                         "status": "signed", "at": 1}
    r, (path, q) = await post(KAI, event_id=ev["mc"], action="signup", pick="krieger:furor")
    check(q.get("err") == ["Das Event ist voll (1 Plätze)."], f"Event voll -> abgelehnt ({q})")
    r, (path, q) = await post(KAI, event_id=ev["mc"], action="status", status="bench")
    check(q.get("ok") == ["✅ Du stehst jetzt auf: Bank."], "voll: Bank weiterhin möglich (wie Button)")
    r, t = await page("/me/raids?guild=1000", KAI)
    check(">voll<" in t, "Pill „voll“")

    # ---- versteckter Kanal / fremder Server / fremdes Event
    r, (path, q) = await post(KAI, event_id=ev["hidden"], action="signup", pick="krieger:furor")
    check(q.get("err") == ["Dieses Event existiert nicht mehr."] and "13" not in (await evs())[ev["hidden"]]["signups"],
          "Aktion auf Event im versteckten Kanal -> abgelehnt")
    r, (path, q) = await post(MIA, event_id=ev["hidden"], action="signup", pick="priester:heilig")
    check("ok" in q, "Mia (sieht den Kanal) kann sich dort anmelden")
    r, (path, q) = await post(KAI, event_id="rh-9999", action="signup", pick="krieger:furor")
    check(q.get("err") == ["Dieses Event existiert nicht mehr."], "unbekannte Event-ID -> abgelehnt")
    r, (path, q) = await post(KAI, event_id=ev["foreign"], action="signup", pick="krieger:furor", guild="2000")
    check(r.status == 302 and q.get("err") == ["Kein Zugriff auf diesen Server"] and path == "/me/raids", f"fremder Server (guild=2000) -> abgelehnt ({path} {q})")
    g2ev = await rh.config.guild(bot.guilds[1]).events()
    check("13" not in g2ev[ev["foreign"]]["signups"], "fremder Server: nichts geändert")
    r, t = await page("/me/raids?guild=2000", KAI)
    check(r.status == 302 and "err" in loc(r)[1], "GET fremder Server -> Umleitung mit Fehler")
    r, t = await page("/me/raids?guild=2000", BEN)
    check(r.status in (302, 403), f"Ben (Portal auf 2000 aus) -> kein Zugriff ({r.status})")
    r = await client.post("/me/raids", data={"guild": "1000", "event_id": main, "action": "leave"}, headers=KAI,
                          allow_redirects=False)
    check(r.status == 400, "ohne CSRF-Token -> 400")
    r, (path, q) = await post(KAI, event_id=main, action="hack")
    check("err" in q, "unbekannte Aktion -> abgelehnt")

    # ---- nur eigene Daten: Formularfelder mit fremder user-id werden ignoriert
    r, (path, q) = await post(KAI, event_id=main, action="leave", user_id="14", member="14")
    check("14" in (await evs())[main]["signups"], "fremde Anmeldung (Mia) unangetastet")

    # ---- Einstellung „Im Mitglieder-Bereich anzeigen“
    kai_tok = await token(KAI)  # ausgeschaltet enthält die Seite kein Formular mehr
    r, t = await page("/cogs/raidhelper?guild=1000", OWNER)
    check("name='member_page'" in t and "Zugriff &amp; Rollen" in t and "eingeschaltet" in t,
          "Team-Dashboard: Schalter + Hinweis auf Zugriff & Rollen")
    tok = re.search(r"name='csrf_token' value='([^']+)'", t).group(1)
    data = {"csrf_token": tok, "form": "settings", "guild": "1000", "language": "de", "default_game": "wow_retail",
            "signup_channel": "1001", "timezone": "Europe/Berlin", "cleanup_days": "30", "reminders": "on"}
    r = await client.post("/cogs/raidhelper", data=data, headers=OWNER, allow_redirects=False)
    check(r.status == 302 and await rh.config.guild(g).member_page() is False, "Schalter aus gespeichert")
    r, t = await page("/me/raids?guild=1000", KAI)
    check("nicht freigeschaltet" in t and "Mythic Undermine" not in t, "ausgeschaltet: Mitglied sieht Hinweis statt Events")
    r, (path, q) = await post(KAI, event_id=main, action="signup", pick="krieger:furor", csrf_token=kai_tok)
    check(q.get("err") == ["Die Raid-Anmeldung ist im Mitglieder-Bereich dieses Servers ausgeschaltet."] and "13" not in (await evs())[main]["signups"], "ausgeschaltet: POST abgelehnt")
    data["member_page"] = "on"
    r = await client.post("/cogs/raidhelper", data=data, headers=OWNER, allow_redirects=False)
    check(await rh.config.guild(g).member_page() is True, "Schalter wieder an")
    await wc.config.member_portal.set({})
    r, t = await page("/cogs/raidhelper?guild=1000", OWNER)
    check("ausgeschaltet" in t, "Hinweis zeigt: Mitglieder-Bereich aus")
    await wc.config.member_portal.set({"1000": True})

    # ---- Lena-Sicht: Team mit eigener Anmeldung
    r, t = await page("/me/raids?guild=1000", {"X-Test-User": "11"})
    check(r.status == 200 and "Frost Magier" in t, "Team-Mitglied Lena sieht eigene Anmeldung")

    await client.close()
    print(f"\n{sum(OK)}/{len(OK)} OK")
    if not all(OK):
        sys.exit(1)

asyncio.run(main())
