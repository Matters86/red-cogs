"""giveaways: Teilnahme-Regeln, persistente Buttons (Neustart), faire Auslosung, Nachholen nach Downtime,
Reroll/Ende/Abbruch, gedrosseltes Embed-Update, Befehle + Rechte, Dashboard, Mitgliederseite, Datenlöschung."""
import asyncio, re, secrets, time
from collections import Counter
from urllib.parse import unquote, urlparse, parse_qs
import gv_harness as G
import live_harness as L
import wc_harness as H
import discord
from aiohttp.test_utils import TestServer, TestClient

NR = dict(allow_redirects=False)
OWNER = {"X-Test-User": "1"}; LENA = {"X-Test-User": "11"}; KAI = {"X-Test-User": "13"}
NINA = {"X-Test-User": "15"}; TOM = {"X-Test-User": "12"}


def csrf(text):
    return re.search(r"name='csrf_token' value='([^']+)'", text).group(1)


def loc(r):
    q = parse_qs(urlparse(r.headers["Location"]).query)
    return {k: unquote(v[0]) for k, v in q.items()}, r.headers["Location"]


class Ctx:
    def __init__(self, guild, author, channel):
        self.guild = guild; self.author = author; self.channel = channel; self.sent = []
    async def send(self, content=None, *, embed=None, **kw):
        assert content is None or len(content) <= 2000
        self.sent.append(content)
    @property
    def last(self): return self.sent[-1]


async def main():
    wc, bot, app, cog = await G.make_app()
    from rc.giveaways import core
    from rc.giveaways.giveaways import Giveaways
    g1, g2 = bot.guilds
    owner, lena, tom, kai, mia, nina = (g1.get_member(i) for i in (1, 11, 12, 13, 14, 15))
    allg = g1.get_channel(1001)
    booster, gesperrt, vip = g1.get_role(1105), g1.get_role(1106), g1.get_role(1104)
    base = time.time()

    # ================================================================ Reine Logik
    assert core.parse_duration("30m") == 1800 and core.parse_duration("1d12h") == 129600
    for bad in ("", "abc", "0m", "30s", "61d", "5x", "1d abc"):
        assert core.parse_duration(bad) is None, bad
    assert isinstance(core._RNG, secrets.SystemRandom)
    # Fairness: gleiche Lose -> gleichverteilt, doppelte Lose -> doppelte Chance
    cnt = Counter(core.weighted_sample([(1, 1), (2, 1), (3, 1)], 1)[0] for _ in range(6000))
    assert all(1800 < cnt[i] < 2200 for i in (1, 2, 3)), cnt
    cnt = Counter(core.weighted_sample([(1, 1), (2, 2), (3, 1)], 1)[0] for _ in range(6000))
    assert 2700 < cnt[2] < 3300 and 1300 < cnt[1] < 1700, cnt
    for _ in range(200):
        picks = core.weighted_sample([(i, 1 + i % 3) for i in range(10)], 4)
        assert len(picks) == 4 == len(set(picks))
    assert sorted(core.weighted_sample([(1, 1), (2, 5)], 5)) == [1, 2]      # nie mehr als vorhanden
    assert core.weighted_sample([], 3) == [] and core.weighted_sample([(1, 0)], 1) == []
    gwx = {"status": "running", "end_ts": base + 99, "bonus_roles": {"1105": 2, "1104": 30}}
    assert core.tickets_for(nina, gwx) == 1
    nina.roles.append(booster); assert core.tickets_for(nina, gwx) == 3
    nina.roles.append(vip); assert core.tickets_for(nina, gwx) == 13      # 1 + 2 + min(30, 10)
    nina.roles.remove(vip)
    print("Logik: Dauer, SystemRandom, faire gewichtete Ziehung ohne Zurücklegen, Bonus-Lose – OK")

    # ================================================================ Befehl start + Rechte
    ck = Ctx(g1, kai, allg)
    await cog.giveaway_start.callback(cog, ck, "1d", 1, preis="Test")
    assert "Berechtigung" in ck.last and not await cog.config.guild(g1).giveaways()
    cl = Ctx(g1, lena, allg)
    await cog.giveaway_managerrole.callback(cog, cl, g1.get_role(1101))
    assert "Server verwalten" in cl.last                       # Manager-Rolle setzen nur mit Server verwalten
    co = Ctx(g1, owner, allg)
    await cog.giveaway_managerrole.callback(cog, co, g1.get_role(1101))
    assert "hinzugefügt" in co.last and await cog.config.guild(g1).manager_roles() == [1101]
    await cog.giveaway_start.callback(cog, cl, "99x", 1, preis="Test")
    assert "Dauer nicht erkannt" in cl.last
    await cog.giveaway_start.callback(cog, cl, "1h", 0, preis="Test")
    assert "zwischen 1 und 20" in cl.last
    await cog.giveaway_start.callback(cog, cl, "1h", 2, preis="x" * 201)
    assert "Preis" in cl.last
    G.VIEWS.clear()
    await cog.giveaway_start.callback(cog, cl, "1h", 2, preis="Nitro @everyone")
    assert "gestartet" in cl.last, cl.last
    gws = await cog.config.guild(g1).giveaways()
    gw = gws["1"]
    assert gw["status"] == "running" and gw["winner_count"] == 2 and gw["host_id"] == 11
    msg = allg._messages[gw["message_id"]]
    emb = msg.embeds[0]
    assert emb.title == "🎉 Nitro @everyone" and "Gewinner: **2**" in emb.description and "<t:" in emb.description
    btn = msg.view.children[0]
    assert btn.custom_id == "gw:join:1000:1" and btn.label.startswith("Teilnehmen")
    view, mid = G.find_view("gw:join:1000:1")
    assert view is not None and mid == gw["message_id"], G.VIEWS          # bot.add_view mit message_id
    print("Befehl start: Rechte (Manager-Rolle/Owner), Validierung, Embed, persistente View registriert – OK")

    # ================================================================ Teilnahme per Button
    cog.REFRESH_THROTTLE = 0.3
    async with cog.config.guild(g1).giveaways() as s:
        s["1"]["bonus_roles"] = {"1105": 2}
    L.LOG.clear()
    i = await G.click(bot, g1, nina, msg.view)
    assert i.last["ephemeral"] and "nimmst jetzt teil" in i.last["content"] and "**3**" in i.last["content"], i.last
    i = await G.click(bot, g1, nina, msg.view)                            # erneuter Klick -> Rückfrage
    assert i.last["ephemeral"] and "wirklich austreten" in i.last["content"] and i.last["view"] is not None
    leave_view = i.last["view"]
    i2 = await G.click(bot, g1, nina, leave_view)
    assert i2.last["op"] == "edit_message" and "nicht mehr" in i2.last["content"] and i2.last["view"] is None
    assert "15" not in (await cog.config.guild(g1).giveaways())["1"]["entrants"]
    i = await G.click(bot, g1, nina, msg.view); assert "nimmst jetzt teil" in i.last["content"]
    for m in (owner, tom, mia):
        await G.click(bot, g1, m, msg.view)
    # Regeln
    async with cog.config.guild(g1).giveaways() as s:
        s["1"].update(required_roles=[1104, 1101], excluded_roles=[1106], min_member_days=30)
    i = await G.click(bot, g1, kai, msg.view)          # VIP, aber erst 3 Tage da
    assert "30 Tage" in i.last["content"], i.last
    kai.joined_at = None
    i = await G.click(bot, g1, kai, msg.view); assert "30 Tage" in i.last["content"]      # unbekannt = nicht prüfbar
    kai.joined_at = G.datetime.now(G.timezone.utc) - G.timedelta(days=31)
    lena.roles.append(gesperrt)
    i = await G.click(bot, g1, lena, msg.view); assert "nicht teilnehmen" in i.last["content"]
    lena.roles.remove(gesperrt)
    nina_noroles = H.Member(g1, 16, "Neu", []); nina_noroles.joined_at = kai.joined_at
    g1.members.append(nina_noroles)
    i = await G.click(bot, g1, nina_noroles, msg.view)
    assert "eine dieser Rollen" in i.last["content"] and "<@&1104>" in i.last["content"], i.last
    botm = H.Member(g1, 17, "Botti", [vip]); botm.bot = True; botm.joined_at = kai.joined_at
    i = await G.click(bot, g1, botm, msg.view); assert "Bots" in i.last["content"]
    i = await G.click(bot, g1, kai, msg.view); assert "nimmst jetzt teil" in i.last["content"]
    await G.click(bot, g1, lena, msg.view)
    async with cog.config.guild(g1).giveaways() as s:
        s["1"].update(required_roles=[], excluded_roles=[], min_member_days=0)
    entrants = (await cog.config.guild(g1).giveaways())["1"]["entrants"]
    assert set(entrants) == {"15", "1", "12", "14", "13", "11"}, entrants
    print("Teilnahme per Button: ephemer, erneuter Klick = Rückfrage + Austreten, Rollen/ausgeschlossen/"
          "Mindestdauer/Bots – OK")

    # Drosselung: viele Klicks -> wenige Edits, am Ende korrekter Zähler
    await asyncio.sleep(0.4)
    edits = [e for e in L.LOG if e[0] == "edit" and e[2]["message"] == gw["message_id"]]
    assert 1 <= len(edits) <= 5, len(edits)          # 12 Klicks -> höchstens ein paar Aktualisierungen
    assert msg.view.children[0].label.endswith("· 6"), msg.view.children[0].label
    assert any(f.name == "Teilnehmer" and f.value == "6" for f in msg.embeds[0].fields)
    print(f"Gedrosseltes Update: {len(edits)} Edits für viele Klicks, Zähler stimmt – OK")

    # ================================================================ Neustart: persistente View
    await cog.cog_unload()
    assert all(v.is_finished() for v, _ in G.VIEWS if getattr(v, "is_giveaway_view", False))
    G.VIEWS.clear()
    cog2 = Giveaways(bot); bot._cogs["Giveaways"] = cog2
    await cog2.cog_load(); cog2._tick.cancel()
    cog2.REFRESH_THROTTLE = 0.2
    view, mid = G.find_view("gw:join:1000:1")
    assert view is not None and mid == gw["message_id"] and view.timeout is None
    i = await G.click(bot, g1, nina, view)
    assert "bereits teil" in i.last["content"]                             # Daten da, neue Cog-Instanz antwortet
    extra = H.Member(g1, 18, "Ole", []); extra.joined_at = kai.joined_at; g1.members.append(extra)
    i = await G.click(bot, g1, extra, view); assert "nimmst jetzt teil" in i.last["content"]
    cog = cog2
    print("Neustart: bot.add_view registriert laufende Gewinnspiele neu, Klick nach Neustart funktioniert – OK")

    # ================================================================ Auslosung, Ansage, Ende
    G.SENT.clear()
    ck = Ctx(g1, kai, allg)
    await cog.giveaway_end.callback(cog, ck, "1"); assert "Berechtigung" in ck.last
    extra.roles = [g1.default_role]
    g1.members.remove(extra)                                                  # hat den Server verlassen
    cl = Ctx(g1, lena, allg)
    await cog.giveaway_end.callback(cog, cl, "#1"); assert "beendet und ausgelost" in cl.last, cl.last
    gw = (await cog.config.guild(g1).giveaways())["1"]
    assert gw["status"] == "ended" and gw["ended_by"] == "manual" and len(gw["winner_ids"]) == 2
    assert 18 not in gw["winner_ids"] and set(gw["winner_ids"]) <= {1, 11, 12, 13, 14, 15}
    ann = [s for s in G.SENT if s["content"] and "Glückwunsch" in s["content"]]
    assert len(ann) == 1, G.SENT
    am = ann[0]["allowed_mentions"]
    assert am.everyone is False and am.roles is False and sorted(u.id for u in am.users) == sorted(gw["winner_ids"])
    assert "@​everyone" in ann[0]["content"]                           # Preis-Text kann niemanden pingen
    assert ann[0]["reference"].message_id == gw["message_id"]
    emb = msg.embeds[0]
    assert "Beendet" in emb.description and any(f.name == "Gewinner" for f in emb.fields)
    assert msg.view.children[0].disabled and msg.view.children[0].label.startswith("Beendet")
    i = await G.click(bot, g1, owner, msg.view)
    assert "bereits beendet" in i.last["content"]
    await cog.giveaway_end.callback(cog, cl, "1"); assert "läuft nicht" in cl.last
    print("Ende: 2 Gewinner aus gültigen Teilnahmen (ausgetretene ignoriert), Ping NUR für Gewinner, "
          "Embed/Button beendet – OK")

    # Reroll einzeln + alle
    first = list(gw["winner_ids"])
    G.SENT.clear()
    await cog.giveaway_reroll.callback(cog, cl, "1", types_user(99))
    assert "kein Gewinner" in cl.last
    await cog.giveaway_reroll.callback(cog, cl, "1", types_user(first[0]))
    assert "Neu ausgelost" in cl.last, cl.last
    gw = (await cog.config.guild(g1).giveaways())["1"]
    assert gw["winner_ids"][1] == first[1] and gw["winner_ids"][0] not in first and first[0] in gw["rerolled_out"]
    reroll_ann = G.SENT[-1]
    assert [u.id for u in reroll_ann["allowed_mentions"].users] == [gw["winner_ids"][0]]
    await cog.giveaway_reroll.callback(cog, cl, "1", None)
    gw2 = (await cog.config.guild(g1).giveaways())["1"]
    assert not set(gw2["winner_ids"]) & set(gw["winner_ids"]) and not set(gw2["winner_ids"]) & set(first)
    await cog.giveaway_reroll.callback(cog, cl, "1", None)                  # nur noch 1 Kandidat übrig
    assert len((await cog.config.guild(g1).giveaways())["1"]["winner_ids"]) == 1, cl.last
    await cog.giveaway_reroll.callback(cog, cl, "1", None)
    assert "keine weiteren" in cl.last, cl.last                               # alle 6 verbraucht
    print("Reroll: einzelner Gewinner, alle, ausgeschlossen bleibt ausgeschlossen, keine Kandidaten – OK")

    # Abbrechen
    gwc, err = await cog.create_giveaway(g1, allg, host_id=1, prize="Abbruch", end_ts=time.time() + 600,
                                         winner_count=1)
    await cog.join(g1, nina, gwc["id"])
    G.SENT.clear()
    await cog.giveaway_cancel.callback(cog, cl, gwc["id"]); assert "abgebrochen" in cl.last
    gwc = (await cog.config.guild(g1).giveaways())[gwc["id"]]
    assert gwc["status"] == "cancelled" and gwc["winner_ids"] == [] and not G.SENT
    await cog.giveaway_reroll.callback(cog, cl, gwc["id"], None); assert "noch nicht beendet" in cl.last
    cmsg = allg._messages[gwc["message_id"]]
    assert "Abgebrochen" in cmsg.embeds[0].description and cmsg.view.children[0].disabled
    await cog.giveaway_list.callback(cog, cl)
    assert "#1" in cl.last and "abgebrochen" in cl.last and "beendet" in cl.last
    print("Abbrechen ohne Auslosung/Ansage, Liste – OK")

    # ================================================================ Nachholen nach Downtime
    t0 = time.time()
    due, _ = await cog.create_giveaway(g1, allg, host_id=1, prize="Downtime", end_ts=t0 + 120, winner_count=3)
    later, _ = await cog.create_giveaway(g1, allg, host_id=1, prize="Später", end_ts=t0 + 7200, winner_count=1)
    for m in (owner, lena, tom):
        await cog.join(g1, m, due["id"])
    await cog.cog_unload()                                                   # Bot „offline“
    cog3 = Giveaways(bot); bot._cogs["Giveaways"] = cog3
    cog3._now = lambda: t0 + 3 * 86400                                      # 3 Tage später wieder da
    await cog3.cog_load(); cog3._tick.cancel()
    G.SENT.clear()
    n = await cog3.process_due()
    assert n == 2, n                                                         # beide Enden lagen in der Downtime
    s = await cog3.config.guild(g1).giveaways()
    assert s[due["id"]]["status"] == "ended" and sorted(s[due["id"]]["winner_ids"]) == [1, 11, 12]
    assert s[due["id"]]["ended_by"] == "auto" and s[later["id"]]["status"] == "ended"   # 7200 s < 3 Tage
    assert len([x for x in G.SENT if "Glückwunsch" in (x["content"] or "") or "keine gültigen" in (x["content"] or "")]) == 2
    assert await cog3.process_due() == 0                                     # genau einmal
    # Robuste Schleife: Fehler bei einem Gewinnspiel stoppt die anderen nicht
    a, _ = await cog3.create_giveaway(g1, allg, host_id=1, prize="A", end_ts=t0 + 3 * 86400 + 100, winner_count=1)
    b, _ = await cog3.create_giveaway(g1, allg, host_id=1, prize="B", end_ts=t0 + 3 * 86400 + 100, winner_count=1)
    orig = cog3.end_giveaway
    async def flaky(guild, gid, **kw):
        if gid == a["id"]:
            raise RuntimeError("kaputt")
        return await orig(guild, gid, **kw)
    cog3.end_giveaway = flaky
    cog3._now = lambda: t0 + 3 * 86400 + 200
    assert await cog3.process_due() == 1
    s = await cog3.config.guild(g1).giveaways()
    assert s[a["id"]]["status"] == "running" and s[b["id"]]["status"] == "ended"
    await cog3._tick.coro(cog3)                                               # Schleifen-Körper wirft nie
    del cog3.end_giveaway
    await cog3.process_due()
    assert (await cog3.config.guild(g1).giveaways())[a["id"]]["status"] == "ended"
    # Aufräumen alter Einträge
    await cog3.config.guild(g1).keep_days.set(1)
    cog3._now = lambda: t0 + 10 * 86400
    await cog3.process_due()
    assert not await cog3.config.guild(g1).giveaways()
    await cog3.config.guild(g1).keep_days.set(90)
    cog = cog3
    cog.REFRESH_THROTTLE = 0.2
    cog._now = time.time
    print("Downtime: fällige Gewinnspiele nachgeholt (genau einmal), Fehler je Gewinnspiel isoliert, "
          "Aufräumen nach keep_days – OK")

    # ================================================================ Dashboard
    c = TestClient(TestServer(app)); await c.start_server()
    ids = await G.seed(bot, cog)
    r = await c.get("/cogs/giveaways?guild=1000", headers=OWNER); t = await r.text()
    assert r.status == 200 and "Discord Nitro (1 Monat)" in t and "Merch-Paket" in t
    assert "&lt;b&gt;Elden Ring&lt;/b&gt;" in t and "<b>Elden Ring</b>" not in t
    for tab in ("laufend", "beendet", "neu", "einstellungen"):
        assert f"data-tab='{tab}'" in t, tab
    tok = csrf(t)
    r = await c.get(f"/cogs/giveaways?guild=1000&gw={ids['gw1']}", headers=OWNER); t = await r.text()
    assert "Nina" in t and "Mia" in t and "Booster +2" in t and "Teilnehmer" in t
    # Anlegen mit Datum/Uhrzeit (Server-Zeitzone)
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    end_local = (datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(days=2)).replace(hour=20, minute=0, second=0,
                                                                                     microsecond=0)
    form = {"csrf_token": tok, "form": "create", "guild": "1000", "prize": "Dashboard-Preis", "description": "Hallo",
            "channel": "1003", "winners": "3", "end_date": end_local.strftime("%Y-%m-%d"), "end_time": "20:00",
            "duration": "", "min_days": "7", "bonus_role_0": "1105", "bonus_n_0": "4", "bonus_role_1": "",
            "required_roles": "1104"}
    r = await c.post("/cogs/giveaways", headers=OWNER, data=form, **NR)
    q, _ = loc(r); assert q.get("ok") == "Gewinnspiel gestartet", q
    new = [g for g in (await cog.config.guild(g1).giveaways()).values() if g["prize"] == "Dashboard-Preis"][0]
    assert new["end_ts"] == int(end_local.timestamp()) and new["winner_count"] == 3 and new["host_id"] == 1
    assert new["bonus_roles"] == {"1105": 4} and new["required_roles"] == [1104] and new["min_member_days"] == 7
    assert g1.get_channel(1003)._messages[new["message_id"]].embeds[0].title == "🎉 Dashboard-Preis"
    # Fehler -> Entwurf bleibt
    r = await c.post("/cogs/giveaways", headers=OWNER, data={**form, "prize": "Entwurf bleibt", "end_date": "2020-01-01"},
                     **NR)
    q, where = loc(r); assert "Vergangenheit" in q["err"] and "draft=1" in where
    r = await c.get(where.split("#")[0], headers=OWNER); t = await r.text()
    assert "value='Entwurf bleibt'" in t
    r = await c.post("/cogs/giveaways", headers=OWNER, data={**form, "duration": "3w"}, **NR)
    assert "gestartet" in loc(r)[0].get("ok", ""), loc(r)
    r = await c.post("/cogs/giveaways", headers=OWNER, data={**form, "duration": "99d"}, **NR)
    assert "Dauer" in loc(r)[0]["err"]
    r = await c.post("/cogs/giveaways", headers=OWNER, data={**form, "channel": "1050"}, **NR)   # Sprachkanal
    assert "Textkanal" in loc(r)[0]["err"]
    # Aktionen
    async def act(action, gid, **extra):
        return loc(await c.post("/cogs/giveaways", headers=OWNER, **NR, data={
            "csrf_token": tok, "form": "action", "guild": "1000", "gw": gid, "action": action, **extra}))[0]
    q = await act("end", ids["gw1"]); assert "beendet und ausgelost" in q["ok"], q
    gw1 = (await cog.config.guild(g1).giveaways())[ids["gw1"]]
    assert gw1["status"] == "ended" and len(gw1["winner_ids"]) == 2
    q = await act("reroll_one", ids["gw1"], user=str(gw1["winner_ids"][0]), back="detail")
    assert "Neu ausgelost" in q["ok"], q
    q = await act("reroll", ids["gw1"]); assert "ok" in q or "keine weiteren" in q.get("err", ""), q
    q = await act("cancel", ids["gw2"]); assert "abgebrochen" in q["ok"]
    q = await act("delete", ids["gw3"]); assert "err" in q                   # läuft noch -> nicht löschbar
    q = await act("delete", ids["gw5"]); assert q["ok"] == "Eintrag entfernt"
    assert ids["gw5"] not in await cog.config.guild(g1).giveaways()
    r = await c.get(f"/cogs/giveaways?guild=1000&gw={ids['gw1']}", headers=OWNER); t = await r.text()
    assert "reroll_one" in t and "Gewinner" in t
    # Einstellungen
    r = await c.post("/cogs/giveaways", headers=OWNER, **NR, data={
        "csrf_token": tok, "form": "settings", "guild": "1000", "language": "en", "timezone": "Mars/Base",
        "color": "#ff0000", "keep_days": "30", "manager_roles": ["1101", "999"]})
    assert "Zeitzone" in loc(r)[0]["err"]
    r = await c.post("/cogs/giveaways", headers=OWNER, **NR, data={
        "csrf_token": tok, "form": "settings", "guild": "1000", "language": "en", "timezone": "Europe/Vienna",
        "color": "#ff0000", "keep_days": "30", "manager_roles": ["1101", "999"]})
    conf = await cog.config.guild(g1).all()
    assert conf["language"] == "en" and conf["timezone"] == "Europe/Vienna" and conf["manager_roles"] == [1101]
    assert conf["member_page"] is False and conf["color"] == "#ff0000" and conf["keep_days"] == 30
    await cog.config.guild(g1).member_page.set(True); await cog.config.guild(g1).language.set("de")
    # Rechte: Tom ohne Recht, Lena nur Ansehen
    r = await c.get("/cogs/giveaways?guild=1000", headers=TOM); assert r.status == 403
    await wc.config.role_perms.set({"1000": {"1101": {"giveaways": "view"}}})
    r = await c.get("/cogs/giveaways?guild=1000", headers=LENA); t = await r.text()
    assert r.status == 200 and "Nur Ansicht" in t
    before = await cog.config.guild(g1).giveaways()
    r = await c.post("/cogs/giveaways", headers=LENA, **NR, data={
        "csrf_token": csrf(t), "form": "action", "guild": "1000", "gw": ids["gw3"], "action": "end"})
    assert "Keine" in loc(r)[0].get("ok", "") + loc(r)[0].get("err", ""), loc(r)
    assert (await cog.config.guild(g1).giveaways())[ids["gw3"]]["status"] == before[ids["gw3"]]["status"] == "running"
    await wc.config.role_perms.set({})
    print("Dashboard: Liste/Detail, Anlegen mit Datum+Zeitzone/Dauer, Validierung + Entwurf, Aktionen, "
          "Einstellungen, Rechte (403/Nur Ansicht) – OK")

    # ================================================================ Mitgliederseite
    r = await c.get("/me?guild=1000", headers=KAI); t = await r.text()
    assert "/me/gewinnspiele" in t and "bi-gift" in t
    r = await c.get("/me/gewinnspiele?guild=1000", headers=NINA); t = await r.text()
    assert r.status == 200 and "Team-Gewinnspiel (intern)" not in t          # #support unsichtbar
    assert "Dashboard-Preis" in t and "Abbruch" not in t                     # abgebrochene nicht unter „Laufend“
    mtok = tok                                                               # Sitzungs-Token (gemeinsamer Cookie-Jar)
    gw3 = ids["gw3"]
    async def me(user, action, gid):
        wc._member_limiter._hits.clear()
        return loc(await c.post("/me/gewinnspiele", headers=user, **NR, data={
            "csrf_token": mtok if user is NINA else ktok, "form": action, "guild": "1000", "gw": gid}))[0]
    r = await c.get("/me/gewinnspiele?guild=1000", headers=KAI); t = await r.text(); ktok = tok
    q = await me(NINA, "join", gw3); assert "existiert nicht" in q["err"], q                 # unsichtbarer Kanal
    dash = [g for g in (await cog.config.guild(g1).giveaways()).values() if g["prize"] == "Dashboard-Preis"][0]
    q = await me(NINA, "join", dash["id"]); assert "eine dieser Rollen" in q["err"] and "VIP" in q["err"], q
    nina.roles.append(vip)
    q = await me(NINA, "join", dash["id"]); assert "nimmst jetzt teil" in q["ok"] and "Lose: 5" in q["ok"], q   # 1 + 4 Booster
    q = await me(NINA, "join", dash["id"]); assert "bereits teil" in q["err"], q
    L.LOG.clear()
    q = await me(NINA, "leave", dash["id"]); assert "nicht mehr" in q["ok"], q
    q = await me(NINA, "leave", dash["id"]); assert "nimmst an diesem Gewinnspiel nicht teil" in q["err"], q
    await asyncio.sleep(0.4)
    assert any(e[0] == "edit" and e[2]["message"] == dash["message_id"] for e in L.LOG)      # wie beim Button
    q = await me(KAI, "join", dash["id"]); assert "nimmst jetzt teil" in q["ok"], q      # VIP, 31 Tage da
    # Eigene Gewinne
    async with cog.config.guild(g1).giveaways() as s:
        s[ids["gw4"]]["winner_ids"] = [15]
    r = await c.get("/me/gewinnspiele?guild=1000", headers=NINA); t = await r.text()
    assert "Meine Gewinne" in t and "🏆 Merch-Paket" in t
    r = await c.get("/me/gewinnspiele?guild=1000", headers=KAI); t = await r.text()
    assert "🏆 Merch-Paket" not in t
    # Schalter aus -> Seite + Aktionen gesperrt, Kachel weg
    await cog.config.guild(g1).member_page.set(False)
    r = await c.get("/me?guild=1000", headers=KAI); assert "/me/gewinnspiele" not in await r.text()
    q = await me(NINA, "join", dash["id"]); assert "ausgeschaltet" in q["err"], q
    await cog.config.guild(g1).member_page.set(True)
    # fremder Server / ohne CSRF
    r = await c.post("/me/gewinnspiele", headers=NINA, **NR, data={"form": "join", "guild": "1000", "gw": dash["id"]})
    assert r.status in (400, 403)
    print("Mitgliederseite: Sichtbarkeit nach Kanal, gleiche Regeln wie Button, Discord-Update, eigene Gewinne, "
          "Schalter, CSRF – OK")

    # ================================================================ Datenlöschung
    await cog.red_delete_data_for_user(requester="user", user_id=15)
    await cog.red_delete_data_for_user(requester="user", user_id=1)
    for g in (await cog.config.guild(g1).giveaways()).values():
        assert "15" not in g["entrants"] and 15 not in g["winner_ids"] and 15 not in g.get("rerolled_out", [])
        assert g["host_id"] != 1 and "1" not in g["entrants"]
    print("red_delete_data_for_user: Teilnahmen, Gewinner, Veranstalter entfernt – OK")

    await c.close()
    print("ALLE GIVEAWAYS-TESTS OK")


def types_user(uid):
    return discord.Object(id=uid)


asyncio.run(main())
