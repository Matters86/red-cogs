"""Funktionstest Raidplaner: Event im Dashboard anlegen/bearbeiten, Fehler, Rechte, Befehl raid create."""
import asyncio, re, sys
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import rc_harness as R
L = R.L
from zoneinfo import ZoneInfo
from aiohttp.test_utils import TestServer, TestClient

OK = []
def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg); OK.append(bool(cond))

def loc(r):
    u = urlparse(r.headers.get("Location", "")); q = parse_qs(u.query)
    return q, u.fragment

async def main():
    wc, bot, app, rh = await R.make_app(seed=False)
    g = bot.guilds[0]; g2 = bot.guilds[1]
    await rh.config.guild(g).signup_channel.set(g.id + 1)
    client = TestClient(TestServer(app)); await client.start_server()
    owner = {"X-Test-User": "1"}

    async def csrf(h):
        r = await client.get("/cogs/raidhelper?guild=1000", headers=h); t = await r.text()
        m = re.search(r"name='csrf_token' value='([^']+)'", t); return m.group(1) if m else "", t

    tok, page = await csrf(owner)
    check("tab-neu" in page and "name='date'" in page and "type='date'" in page and "type='time'" in page,
          "Reiter „Neues Event“ mit date/time-Feldern gerendert")
    tz = ZoneInfo("Europe/Berlin")
    when = datetime.now(tz) + timedelta(days=2)
    d, tm = when.strftime("%Y-%m-%d"), "20:30"
    base = {"csrf_token": tok, "form": "create", "guild": "1000", "title": "Dashboard-Raid", "description": "Treff **Org**",
            "game": "wow_classic", "channel": str(g.id + 3), "date": d, "time": tm, "deadline_date": "", "deadline_time": "",
            "recurrence": "weekly", "max_signups": "25", "limit_tank": "2", "limit_healer": "5", "limit_mdps": "", "limit_rdps": "0"}

    # ---- 1. Anlegen
    L.LOG.clear()
    r = await client.post("/cogs/raidhelper", data=base, headers=owner, allow_redirects=False)
    q, frag = loc(r)
    check(r.status == 302 and "ok" in q and frag == "events", f"Anlegen -> ok + #events ({q}, #{frag})")
    events = await rh.config.guild(g).events()
    ev = next(iter(events.values()))
    exp_ts = int(datetime.strptime(f"{d} {tm}", "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp())
    check(ev["id"] == "rh-0001" and ev["title"] == "Dashboard-Raid" and ev["game"] == "wow_classic"
          and ev["channel_id"] == g.id + 3 and ev["start_ts"] == exp_ts and ev["deadline_ts"] == exp_ts
          and ev["max_signups"] == 25 and ev["role_limits"] == {"tank": 2, "healer": 5}
          and ev["recurrence"] == "weekly" and ev["description"] == "Treff **Org**" and ev["leader_id"] == 1,
          f"Event in Config korrekt: {ev}")
    sends = [x for x in L.LOG if x[0] == "send"]
    check(len(sends) == 1 and sends[0][1] == g.id + 3 and sends[0][2]["view"] and sends[0][2]["embeds"] == 1,
          f"Nachricht im Fake-Kanal mit Embed+Buttons: {sends}")
    ch = g.get_channel(g.id + 3); msg = ch._messages[ev["message_id"]]
    cids = [c.custom_id for c in msg.view.children]
    check(any(c.startswith("rh:cls:rh-0001") for c in cids) and any(c.startswith("rh:leave:") for c in cids),
          f"Buttons/Select mit persistenten IDs: {cids}")
    check(msg.embeds[0].title and "Dashboard-Raid" in msg.embeds[0].title, "Embed-Titel = Event-Titel")

    # ---- 2. Validierungsfehler
    past = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    cases = [
        ({"date": past}, "Vergangenheit"),
        ({"date": "", "time": ""}, "nicht erkannt"),
        ({"channel": str(g.id + 7)}, "nicht posten"),           # #gesperrt: Bot ohne Senderechte
        ({"channel": str(g2.id + 1)}, "Textkanal"),             # Kanal eines anderen Servers
        ({"channel": str(g.id + 50)}, "Textkanal"),             # Sprachkanal
        ({"max_signups": "abc"}, "Maximale Teilnehmer"),
        ({"max_signups": "5000"}, "Maximale Teilnehmer"),
        ({"limit_tank": "-x"}, "Limit für Tanks"),
        ({"limit_druid": "3"}, "Unbekannte Rolle"),
        ({"title": "   "}, "Titel"),
        ({"title": "x" * 300}, "zu lang"),
        ({"description": "y" * 1500}, "zu lang"),
        ({"game": "lol"}, "Unbekanntes Spiel"),
        ({"recurrence": "monthly"}, ""),
        ({"deadline_date": d, "deadline_time": "23:59"}, "Anmeldeschluss"),
    ]
    L.LOG.clear()
    for over, needle in cases:
        r = await client.post("/cogs/raidhelper", data={**base, **over}, headers=owner, allow_redirects=False)
        q, frag = loc(r); err = (q.get("err") or [""])[0]
        check(r.status == 302 and err and needle.lower() in err.lower() and frag == "neu" and q.get("draft") == ["1"],
              f"Fehler {over if len(str(over)) < 60 else list(over)}: „{err}“")
    check(len(await rh.config.guild(g).events()) == 1 and not [x for x in L.LOG if x[0] == "send"],
          "Fehler legen kein Event an und posten nichts")
    # Entwurf wird nach Fehler wiederhergestellt
    r = await client.post("/cogs/raidhelper", data={**base, "date": past, "title": "Mein Entwurf <b>"},
                          headers=owner, allow_redirects=False)
    r2 = await client.get(r.headers["Location"].split("#")[0], headers=owner); t2 = await r2.text()
    check("value='Mein Entwurf &lt;b&gt;'" in t2 and f"value='{past}'" in t2, "Eingaben nach Fehler wieder im Formular (escaped)")
    r3 = await client.get("/cogs/raidhelper?guild=1000", headers=owner); t3 = await r3.text()
    check("Mein Entwurf" not in t3, "ohne draft=1 leeres Formular")
    r4 = await client.get(r.headers["Location"].split("#")[0], headers={"X-Test-User": "14"})
    check("Mein Entwurf" not in await r4.text(), "Entwurf nicht für andere Sitzung sichtbar")

    # ---- 3. Bearbeiten
    r = await client.get("/cogs/raidhelper?guild=1000&edit=rh-0001", headers=owner); t = await r.text()
    check("name='form' value='edit'" in t and f"value='{d}'" in t and "value='20:30'" in t and "value='Dashboard-Raid'" in t,
          "Bearbeiten-Formular vorbelegt")
    L.LOG.clear()
    ed = {"csrf_token": tok, "form": "edit", "guild": "1000", "event_id": "rh-0001", "title": "Neuer Titel",
          "description": "", "date": d, "time": "21:00", "deadline_date": "", "deadline_time": "",
          "recurrence": "none", "max_signups": "10", "limit_tank": "3", "limit_healer": "", "limit_mdps": "", "limit_rdps": ""}
    # Erinnerung als gesendet markieren -> muss bei Terminwechsel zurückgesetzt werden
    async with rh.config.guild(g).events() as es:
        es["rh-0001"]["reminders_sent"] = [60]
        es["rh-0001"]["signups"]["11"] = {"name": "Lena", "class": "krieger", "spec": "schutz", "role": "tank", "status": "signed", "at": 1}
    r = await client.post("/cogs/raidhelper", data=ed, headers=owner, allow_redirects=False)
    q, frag = loc(r)
    ev = (await rh.config.guild(g).events())["rh-0001"]
    check("ok" in q and frag == "events", f"Bearbeiten ok: {q}")
    check(ev["title"] == "Neuer Titel" and ev["description"] is None and ev["start_ts"] == exp_ts + 1800
          and ev["deadline_ts"] == exp_ts + 1800 and ev["max_signups"] == 10 and ev["role_limits"] == {"tank": 3}
          and ev["recurrence"] is None and ev["reminders_sent"] == [] and "11" in ev["signups"],
          f"Änderungen gespeichert, Anmeldeschluss wandert mit, Anmeldungen bleiben: {ev}")
    edits = [x for x in L.LOG if x[0] == "edit"]
    check(len(edits) == 1 and edits[0][2]["message"] == ev["message_id"] and not [x for x in L.LOG if x[0] == "send"],
          "Discord-Nachricht bearbeitet (keine neue)")
    check("Neuer Titel" in msg.embeds[0].title, "Embed zeigt neuen Titel")
    # eigener Anmeldeschluss + keine Änderung
    L.LOG.clear()
    r = await client.post("/cogs/raidhelper", data={**ed, "deadline_date": d, "deadline_time": "20:00"}, headers=owner, allow_redirects=False)
    ev = (await rh.config.guild(g).events())["rh-0001"]
    check(ev["deadline_ts"] == exp_ts - 1800, "eigener Anmeldeschluss gesetzt")
    r = await client.post("/cogs/raidhelper", data={**ed, "deadline_date": d, "deadline_time": "20:00"}, headers=owner, allow_redirects=False)
    q, _ = loc(r)
    check("nichts geändert" in q.get("ok", [""])[0], f"unverändert -> {q}")
    # Fehler beim Bearbeiten
    for over, needle in [({"time": "23:30", "deadline_time": "23:59"}, "Anmeldeschluss"),
                         ({"date": past}, "Vergangenheit"), ({"date": ""}, "nicht erkannt"),
                         ({"max_signups": "x"}, "Maximale")]:
        r = await client.post("/cogs/raidhelper", data={**ed, "deadline_date": d, "deadline_time": "20:00", **over}, headers=owner, allow_redirects=False)
        q, _ = loc(r); err = (q.get("err") or [""])[0]
        check(err and needle in err and q.get("edit") == ["rh-0001"], f"Bearbeiten-Fehler {over}: „{err}“")
    r = await client.post("/cogs/raidhelper", data={**ed, "event_id": "rh-9999"}, headers=owner, allow_redirects=False)
    check("nicht gefunden" in (loc(r)[0].get("err") or [""])[0], "unbekanntes Event")
    # abgeschlossenes Event: Datumsfelder deaktiviert (nicht gesendet) -> Titel änderbar
    async with rh.config.guild(g).events() as es:
        es["rh-0001"]["completed"] = True
    r = await client.get("/cogs/raidhelper?guild=1000&edit=rh-0001", headers=owner); t = await r.text()
    check("name='date'" in t and re.search(r"name='date'[^>]*disabled", t), "abgeschlossen: Datum deaktiviert")
    dat = {k: v for k, v in ed.items() if k not in ("date", "time")}; dat["title"] = "Nach Abschluss"
    dat.update(deadline_date=d, deadline_time="20:00")
    r = await client.post("/cogs/raidhelper", data=dat, headers=owner, allow_redirects=False)
    ev = (await rh.config.guild(g).events())["rh-0001"]
    check("ok" in loc(r)[0] and ev["title"] == "Nach Abschluss", "abgeschlossenes Event: Titel änderbar")
    ev_start = ev["start_ts"]
    r = await client.post("/cogs/raidhelper", data={**dat, "date": d, "time": "22:00"}, headers=owner, allow_redirects=False)
    check("abgeschlossen" in (loc(r)[0].get("err") or [""])[0] and (await rh.config.guild(g).events())["rh-0001"]["start_ts"] == ev_start,
          "abgeschlossenes Event: Terminwechsel abgelehnt")

    # ---- 4. Rechte
    perms = await wc.config.role_perms()
    perms["1000"] = {"1103": {"raidhelper": "edit"}, "1101": {"raidhelper": "view"}}
    await wc.config.role_perms.set(perms)
    mia = {"X-Test-User": "14"}; lena = {"X-Test-User": "11"}; kai = {"X-Test-User": "13"}
    tmia, _ = await csrf(mia)
    r = await client.post("/cogs/raidhelper", data={**base, "csrf_token": tmia, "title": "Von Mia"}, headers=mia, allow_redirects=False)
    evs = await rh.config.guild(g).events()
    check(any(e["title"] == "Von Mia" and e["leader_id"] == 14 for e in evs.values()), "Rolle mit Bearbeiten: Anlegen ok, Raidleitung = Mia")
    r = await client.post("/cogs/raidhelper", data={**base, "csrf_token": tmia, "guild": "2000", "channel": str(g2.id + 1)}, headers=mia, allow_redirects=False)
    check(len(await rh.config.guild(g2).events()) == 0, f"fremder Server abgelehnt ({r.headers.get('Location')})")
    tl, tpage = await csrf(lena)
    n = len(await rh.config.guild(g).events())
    r = await client.post("/cogs/raidhelper", data={**base, "csrf_token": tl, "title": "Von Lena"}, headers=lena, allow_redirects=False)
    r2 = await client.post("/cogs/raidhelper", data={**ed, "csrf_token": tl, "title": "Lena edit"}, headers=lena, allow_redirects=False)
    evs = await rh.config.guild(g).events()
    check(len(evs) == n and evs["rh-0001"]["title"] == "Nach Abschluss", "Nur-Ansehen: Anlegen/Bearbeiten abgelehnt")
    r = await client.get("/cogs/raidhelper?guild=1000", headers=kai)
    check(r.status in (403, 302) or "tab-neu" not in await r.text(), f"ohne Recht kein Zugriff ({r.status})")

    # ---- 5. Befehl raid create (gleiche Funktion)
    sent = []
    class Ctx:
        guild = g; clean_prefix = "!"
        author = g.get_member(1)
        async def send(self, text=None, **kw): sent.append(text)
    ctx = Ctx()
    L.LOG.clear()
    cdate = when.strftime("%d.%m.%Y")
    await rh.raid_create.callback(rh, ctx, cdate, "19:45", title="Per Befehl")
    evs = await rh.config.guild(g).events()
    ce = [e for e in evs.values() if e["title"] == "Per Befehl"]
    check(len(ce) == 1 and ce[0]["channel_id"] == g.id + 1 and ce[0]["game"] == "wow_retail" and ce[0]["description"] is None
          and ce[0]["max_signups"] is None and ce[0]["role_limits"] == {} and ce[0]["recurrence"] is None
          and ce[0]["deadline_ts"] == ce[0]["start_ts"] and ce[0]["message_id"], f"raid create: Event wie bisher {ce}")
    check("discord.com/channels/1000/1001/" in (sent[-1] or ""), f"raid create Antwort mit Link: {sent[-1]}")
    ids = sorted(evs)
    check(len(set(ids)) == len(ids) and ids[-1] == f"rh-{len(ids):04d}", f"IDs fortlaufend: {ids}")
    await rh.raid_create.callback(rh, ctx, "01.01.2020", "19:45", title="Alt"); check("Vergangenheit" in sent[-1], sent[-1])
    await rh.raid_create.callback(rh, ctx, "xx", "19:45", title="Alt"); check("nicht erkannt" in sent[-1], sent[-1])
    await rh.raid_quickcreate.callback(rh, ctx, "wow_wotlk", g.get_channel(g.id + 7), cdate, "19:45", title="Gesperrt")
    check("nicht posten" in sent[-1], sent[-1])
    await rh.raid_quickcreate.callback(rh, ctx, "foo", g.get_channel(g.id + 2), cdate, "19:45", title="X")
    check("Unbekanntes Spiel" in sent[-1], sent[-1])
    await rh.raid_quickcreate.callback(rh, ctx, "wow_wotlk", g.get_channel(g.id + 2), cdate, "19:45", title="Quick")
    check("discord.com/channels/1000/1002/" in sent[-1], sent[-1])
    await rh.config.guild(g).signup_channel.set(None)
    await rh.raid_create.callback(rh, ctx, cdate, "19:45", title="Ohne Kanal"); check("!raidset channel" in sent[-1], sent[-1])
    ctx.author = g.get_member(13)
    await rh.raid_create.callback(rh, ctx, cdate, "19:45", title="Kai"); check("Rechte" in sent[-1] or "Berechtigung" in sent[-1] or "darfst" in sent[-1], sent[-1])
    ctx.author = g.get_member(1)
    # Bearbeitungsbefehle nutzen update_event
    await rh.raid_title.callback(rh, ctx, ce[0]["id"], title="Umbenannt"); check("aktualisiert" in sent[-1], sent[-1])
    await rh.raid_time.callback(rh, ctx, ce[0]["id"], cdate, "21:15"); check("verschoben" in sent[-1], sent[-1])
    await rh.raid_maxsignups.callback(rh, ctx, ce[0]["id"], 12); await rh.raid_rolelimit.callback(rh, ctx, ce[0]["id"], "healer", 3)
    await rh.raid_deadline.callback(rh, ctx, ce[0]["id"], cdate, "23:00"); check("vor dem Start" in sent[-1], sent[-1])
    await rh.raid_deadline.callback(rh, ctx, ce[0]["id"], cdate, "20:00"); check("Anmeldeschluss" in sent[-1], sent[-1])
    e2 = (await rh.config.guild(g).events())[ce[0]["id"]]
    check(e2["title"] == "Umbenannt" and e2["max_signups"] == 12 and e2["role_limits"] == {"healer": 3}, f"Befehle ändern: {e2['title']}")

    # ---- 6. Screens des Edit-Views + Toast-Links
    await client.close()
    print(f"\n{sum(OK)}/{len(OK)} OK")
    return all(OK)

sys.exit(0 if asyncio.run(main()) else 1)
