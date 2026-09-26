"""serverstats: Zählung, Puffer/Flush, Aufbewahrung, keine Personendaten, SVG-Diagramme, CSV, Befehle, Dashboard."""
import asyncio
import csv
import io
import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import st_harness as S
from aiohttp.test_utils import TestClient, TestServer
import discord

L = S.L
NR = {"allow_redirects": False}
OWNER = {"X-Test-User": "1"}
LENA = {"X-Test-User": "11"}
TOM = {"X-Test-User": "12"}
KAI = {"X-Test-User": "13"}


def csrf(html):
    return re.search(r"name='csrf_token' value='([^']+)'", html).group(1)


class Ctx:
    def __init__(self, guild, author, channel):
        self.guild = guild; self.author = author; self.channel = channel; self.clean_prefix = "!"
        self.sent = []

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))
        return await self.channel.send(content, **{k: v for k, v in kw.items() if k in ("embed", "allowed_mentions")})


class FakeThread(discord.Thread):
    @classmethod
    def make(cls, tid, parent):
        o = object.__new__(cls)
        o.id = tid; o.parent_id = parent.id; o.guild = parent.guild
        return o


def ts(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp()


async def main():
    wc, bot, app, cog = await S.make_app()
    g = bot.guilds[0]
    allg, sup, ann, logs = g.text_channels
    lobby, gaming, afk = g.voice_channels
    lena, tom, kai, mia = (g.get_member(i) for i in (11, 12, 13, 14))
    now = [ts(2026, 9, 20, 12)]
    cog._clock = lambda: now[0]
    gconf = cog.config.guild(g)

    # ------------------------------------------------------------ 1) Zählung + Puffer
    for _ in range(3):
        await cog.on_message(S.msg(g, kai, allg))
    await cog.on_message(S.msg(g, lena, sup))
    await cog.on_message(S.msg(g, g.me, allg))                    # Bot -> nicht zählen
    await cog.on_message(S.msg(g, kai, allg, webhook=True))       # Webhook -> nicht zählen
    await cog.on_message(S.msg(g, kai, FakeThread.make(555, ann)))  # Thread -> Elternkanal
    await cog.on_message(S.msg(None, kai, allg))                  # DM -> nichts
    await cog.on_member_join(kai); await cog.on_member_join(mia); await cog.on_member_remove(tom)
    assert await gconf.days() == {}, "vor dem Flush darf nichts geschrieben sein"
    pend = cog._pending[g.id]["2026-09-20"]
    assert pend["messages"] == {str(allg.id): 3, str(sup.id): 1, str(ann.id): 1}, pend
    assert pend["joins"] == 2 and pend["leaves"] == 1, pend
    # Dashboard/Auswertung sieht den Puffer bereits
    days = await cog.get_days(g, 7)
    assert days[-1][0] == "2026-09-20" and sum(days[-1][1]["messages"].values()) == 5
    written = await cog.flush()
    assert written >= 1 and cog._pending == {}
    stored = (await gconf.days())["2026-09-20"]
    assert stored["messages"][str(allg.id)] == 3 and stored["joins"] == 2 and stored["leaves"] == 1
    assert stored["members"] == g.member_count, stored
    # zweiter Flush ohne Änderungen: nichts neu schreiben
    assert await cog.flush() == 0
    # gezählt wird weiter addiert
    await cog.on_message(S.msg(g, kai, allg)); await cog.flush()
    assert (await gconf.days())["2026-09-20"]["messages"][str(allg.id)] == 4
    print("Zählung (Bots/Webhooks/DMs ausgenommen, Threads -> Elternkanal) + Puffer/Flush OK")

    # Ignorierte Kanäle
    ctx = Ctx(g, g.get_member(1), logs)
    await cog.statsset_ignore.callback(cog, ctx, sup)
    assert "nicht mehr gezählt" in ctx.sent[-1][0] and sup.id in await gconf.ignored_channels()
    await cog.on_message(S.msg(g, kai, sup)); await cog.flush()
    assert (await gconf.days())["2026-09-20"]["messages"][str(sup.id)] == 1
    await cog.statsset_ignore.callback(cog, ctx, sup)
    assert "wieder gezählt" in ctx.sent[-1][0] and sup.id not in await gconf.ignored_channels()
    print("Ignorierte Kanäle OK")

    # ------------------------------------------------------------ 2) Voice
    B = S.vstate
    await cog.on_voice_state_update(kai, B(None), B(lobby))
    await cog.on_voice_state_update(mia, B(None), B(afk))          # AFK -> nicht zählen
    await cog.on_voice_state_update(g.me, B(None), B(lobby))       # Bot -> nicht zählen
    assert (g.id, kai.id) in cog._voice and (g.id, mia.id) not in cog._voice and (g.id, 999) not in cog._voice
    now[0] += 120
    await cog.on_voice_state_update(kai, B(lobby), B(lobby))       # nur stumm geschaltet -> Sitzung läuft weiter
    await cog.on_voice_state_update(kai, B(lobby), B(gaming))      # Wechsel: 120 s für Lobby
    now[0] += 60
    await cog.on_voice_state_update(kai, B(gaming), B(afk))        # 60 s Gaming, AFK zählt nicht
    now[0] += 300
    await cog.on_voice_state_update(kai, B(afk), B(None))
    await cog.flush()
    v = (await gconf.days())["2026-09-20"]["voice_sec"]
    assert v == {str(lobby.id): 120, str(gaming.id): 60}, v
    # Laufende Sitzung: Flush schreibt die Zeit bis jetzt, Sitzung läuft weiter
    await cog.on_voice_state_update(lena, B(None), B(gaming))
    now[0] += 90
    await cog.flush()
    assert (await gconf.days())["2026-09-20"]["voice_sec"][str(gaming.id)] == 150
    assert cog._voice[(g.id, lena.id)][1] == now[0]
    await cog.on_voice_state_update(lena, B(gaming), B(None))
    # Mitternacht: Sitzung 23:59 -> 00:02 wird auf beide Tage verteilt
    now[0] = ts(2026, 9, 20, 23, 59)
    await cog.on_voice_state_update(tom, B(None), B(lobby))
    now[0] = ts(2026, 9, 21, 0, 2)
    await cog.on_voice_state_update(tom, B(lobby), B(None))
    await cog.flush()
    d = await gconf.days()
    assert d["2026-09-20"]["voice_sec"][str(lobby.id)] == 180 and d["2026-09-21"]["voice_sec"][str(lobby.id)] == 120, d
    # Startbestand: wer beim Laden schon in Voice sitzt
    lobby.members = [kai, g.me]; afk.members = [mia]
    await cog.start_voice_sessions()
    assert (g.id, kai.id) in cog._voice and (g.id, mia.id) not in cog._voice and (g.id, 999) not in cog._voice
    lobby.members = []; afk.members = []
    cog._voice.clear()
    print("Voice-Zeit (AFK/Bots ausgenommen, Kanalwechsel, laufende Sitzung, Mitternacht, Startbestand) OK")

    # ------------------------------------------------------------ 3) Keine Personendaten
    raw = await cog.config.all_guilds()
    dump = json.dumps(raw)
    for name in ("Kai", "Lena", "Mia", "Tom", "Matters86"):
        assert name not in dump, name
    allowed_ch = {str(c.id) for c in g.channels}
    for day, rec in raw[g.id]["days"].items():
        assert set(rec) <= {"joins", "leaves", "members", "messages", "voice_sec"}, rec
        assert set(rec["messages"]) <= allowed_ch and set(rec["voice_sec"]) <= allowed_ch, rec
    await cog.on_voice_state_update(kai, B(None), B(lobby))
    await cog.red_delete_data_for_user(requester="user", user_id=kai.id)
    assert (g.id, kai.id) not in cog._voice
    assert json.dumps(await cog.config.all_guilds()) == dump, "Datenlöschung darf keine Statistik verändern"
    print("Keine Personendaten gespeichert, red_delete_data_for_user = no-op (nur RAM-Sitzung) OK")

    # ------------------------------------------------------------ 4) Aufbewahrung
    now[0] = ts(2026, 9, 26, 12)
    await gconf.days.set({"2026-01-01": {"joins": 1}, "2026-06-28": {"joins": 1}, "2026-06-29": {"joins": 1},
                          "2026-09-26": {"joins": 1}})
    removed = await cog.cleanup()
    assert removed == 2 and sorted(await gconf.days()) == ["2026-06-29", "2026-09-26"], await gconf.days()
    await cog.statsset_retention.callback(cog, ctx, 3)
    assert "zwischen 7 und 730" in ctx.sent[-1][0] and await gconf.retention_days() == 90
    await cog.statsset_retention.callback(cog, ctx, 7)
    assert await gconf.retention_days() == 7
    await cog.cleanup()
    assert sorted(await gconf.days()) == ["2026-09-26"]
    await gconf.retention_days.set(90)
    # Fehler in einem Server beendet den Loop nicht / verliert keine Daten
    await cog.on_message(S.msg(g, kai, allg))
    g2 = bot.guilds[1]
    await cog.on_message(S.msg(g2, g2.get_member(11), g2.text_channels[0]))
    orig = cog.config.guild_from_id

    def broken(gid):
        if gid == g.id:
            raise RuntimeError("kaputt")
        return orig(gid)
    cog.config.guild_from_id = broken
    logging.getLogger("red.red-cogs.serverstats").disabled = True   # erwarteter Fehler, nicht ins Log
    await cog._loop.coro(cog)                  # eine Loop-Runde direkt
    logging.getLogger("red.red-cogs.serverstats").disabled = False
    cog.config.guild_from_id = orig
    assert cog._pending.get(g.id), "Puffer muss nach Fehler erhalten bleiben"
    assert (await cog.config.guild(g2).days())["2026-09-26"]["messages"][str(g2.text_channels[0].id)] == 1
    await cog.flush()
    assert (await gconf.days())["2026-09-26"]["messages"][str(allg.id)] == 1
    print("Aufbewahrung (Loop-Aufräumen, Grenzen) + Fehler je Server isoliert OK")

    # ------------------------------------------------------------ 5) Diagramme (reine SVG-Funktionen)
    from rc.serverstats import charts
    svg = charts.line_chart(["01.09.", "02.09.", "03.09."], [100, None, 120], label="Mitglieder <x>")
    assert svg.startswith("<svg viewBox=") and "width='100%'" in svg and "<polyline" in svg
    assert "Mitglieder &lt;x&gt;" in svg and "<x>" not in svg and "<style" not in svg and "<script" not in svg
    assert svg.count("<polyline") == 2, "Lücke (None) muss die Linie teilen"
    bars = charts.bar_chart(["a", "b"], [0, 1234], label="N", tips=["a: 0", "b: 1.234 Nachrichten"])
    assert "<title>b: 1.234 Nachrichten</title>" in bars and "var(--" in bars
    h = charts.hbar_chart([("<script>", 5), ("leer", 0)], label="Top")
    assert "&lt;script&gt;" in h and "leer" not in h
    assert "Noch keine Daten" in charts.bar_chart(["a"], [0], label="x")
    assert charts.fmt_num(1234567) == "1.234.567" and charts.fmt_num(2.5) == "2,5"
    print("SVG-Bausteine (viewBox, Tooltips, Escaping, Lücken, leerer Zustand) OK")

    # ------------------------------------------------------------ 6) Dashboard
    await S.seed(cog, bot)
    now[0] = time.time()
    client = TestClient(TestServer(app)); await client.start_server()
    r = await client.get("/cogs/serverstats?guild=1000", headers=OWNER); t = await r.text()
    assert r.status == 200, r.status
    for s in ("data-title='Übersicht'", "data-title='Kanäle'", "data-title='Einstellungen'", "Netto-Wachstum",
              "Voice-Stunden", "Top-10-Textkanäle", "Offene Tickets", "Kommende Raids", "CSV je Tag"):
        assert s in t, s
    assert t.count("<svg viewBox") >= 6, t.count("<svg viewBox")
    data30 = await cog.get_days(g, 30)
    day = data30[-5]
    n_msgs = sum(day[1]["messages"].values())
    tip = f"{day[0][8:10]}.{day[0][5:7]}.{day[0][0:4]}: {charts.fmt_num(n_msgs)} Nachrichten"
    assert f"<title>{tip}</title>" in t, tip
    s30 = cog.summarize(data30)
    assert charts.fmt_num(s30["messages"]) in t
    # Offene Tickets = 1, Kommende Raids = 1 (vergangene zählen nicht)
    assert re.search(r"Offene Tickets</span>.*?wc-stat-value'>1<", t, re.S)
    assert re.search(r"Kommende Raids</span>.*?wc-stat-value'>1<", t, re.S)
    r = await client.get("/cogs/serverstats?guild=1000&range=7", headers=OWNER); t7 = await r.text()
    r = await client.get("/cogs/serverstats?guild=1000&range=90", headers=OWNER); t90 = await r.text()
    assert "Mitglieder, letzte 7 Tage" in t7 and "Mitglieder, letzte 90 Tage" in t90
    assert t90.count("Nachrichten</title>") > t7.count("Nachrichten</title>")
    r = await client.get("/cogs/serverstats?guild=1000&range=999", headers=OWNER)
    assert "letzte 30 Tage" in await r.text()
    # fremde Cogs fehlen oder werfen -> Seite läuft trotzdem
    tk = bot._cogs.pop("Tickets"); rh = bot._cogs["RaidHelper"]
    rh_conf = rh.config; rh.config = None
    r = await client.get("/cogs/serverstats?guild=1000", headers=OWNER); t2 = await r.text()
    assert r.status == 200 and "Offene Tickets" not in t2 and "Kommende Raids" not in t2
    class Boom:
        def guild(self, g): raise RuntimeError("x")
    rh.config = Boom()
    r = await client.get("/cogs/serverstats?guild=1000", headers=OWNER)
    assert r.status == 200 and "Kommende Raids" not in await r.text()
    rh.config = rh_conf; bot._cogs["Tickets"] = tk
    print("Dashboard: Kennzahlen, 6 SVG-Diagramme mit erwarteten Werten, Zeitraum 7/30/90, Kacheln robust OK")

    # CSV
    r = await client.get("/cogs/serverstats?guild=1000&range=7&export=days", headers=OWNER)
    body = (await r.read()).decode("utf-8")
    assert r.status == 200 and r.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in r.headers["Content-Disposition"] and body.startswith("﻿")
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    assert rows[0] == ["datum", "beitritte", "abgaenge", "netto", "mitglieder", "nachrichten", "voice_minuten"]
    assert len(rows) == 8, len(rows)
    d7 = await cog.get_days(g, 7)
    assert rows[3][0] == d7[2][0] and int(rows[3][5]) == sum(d7[2][1]["messages"].values()), rows[3]
    assert int(rows[3][3]) == d7[2][1]["joins"] - d7[2][1]["leaves"]
    sup.name = "=HYPERLINK(\"x\")"
    r = await client.get("/cogs/serverstats?guild=1000&range=30&export=channels", headers=OWNER)
    crow = list(csv.reader(io.StringIO((await r.read()).decode("utf-8").lstrip("﻿"))))
    assert crow[0] == ["kanal_id", "kanal", "nachrichten", "voice_minuten"]
    hit = [x for x in crow if x[0] == str(sup.id)][0]
    assert hit[1].startswith("'="), hit
    sup.name = "support"
    r = await client.get("/cogs/serverstats?guild=1000&export=days", headers=KAI, **NR)
    assert r.status in (302, 403), r.status
    print("CSV-Export (Tage/Kanäle, BOM, Formel-Schutz, Rechte) OK")

    # Speichern + Rechte
    tok = csrf(t)
    r = await client.post("/cogs/serverstats", headers=OWNER, **NR, data={
        "csrf_token": tok, "form": "settings", "guild": "1000", "range": "7", "retention_days": "30",
        "language": "en", "ignored": [str(logs.id), str(gaming.id)]})
    assert "ok=" in r.headers["Location"] and "range=7" in r.headers["Location"], r.headers["Location"]
    assert await gconf.retention_days() == 30 and await gconf.language() == "en"
    assert await gconf.ignored_channels() == [logs.id, gaming.id]
    assert await cog.ignored_channels(g) == {logs.id, gaming.id}, "Cache muss nach dem Speichern neu geladen sein"
    for bad, msg in (({"retention_days": "5"}, "Aufbewahrung"), ({"retention_days": "x"}, "Zahl"),
                     ({"ignored": "424242"}, "Kanal"), ({"language": "fr"}, "Sprache")):
        d = {"csrf_token": tok, "form": "settings", "guild": "1000", "retention_days": "30", "language": "de"}
        d.update(bad)
        r = await client.post("/cogs/serverstats", headers=OWNER, **NR, data=d)
        assert "err=" in r.headers["Location"] and msg in unquote_plus(r.headers["Location"]), (bad, r.headers["Location"])
    assert await gconf.retention_days() == 30
    # Tom (Ansehen): Seite ja, Speichern nein
    r = await client.get("/cogs/serverstats?guild=1000", headers=TOM); tt = await r.text()
    assert r.status == 200 and "Netto-Wachstum" in tt
    r = await client.post("/cogs/serverstats", headers=TOM, **NR, data={
        "csrf_token": csrf(tt), "form": "settings", "guild": "1000", "retention_days": "60", "language": "de"})
    assert r.status in (302, 403) and await gconf.retention_days() == 30
    # Lena (Bearbeiten) darf, aber nicht auf Server 2000
    r = await client.get("/cogs/serverstats?guild=1000", headers=LENA); lt = await r.text()
    r = await client.post("/cogs/serverstats", headers=LENA, **NR, data={
        "csrf_token": csrf(lt), "form": "settings", "guild": "1000", "retention_days": "60", "language": "de"})
    assert "ok=" in r.headers["Location"] and await gconf.retention_days() == 60
    r = await client.post("/cogs/serverstats", headers=LENA, **NR, data={
        "csrf_token": csrf(lt), "form": "settings", "guild": "2000", "retention_days": "60", "language": "de"})
    assert r.status in (302, 403) and await cog.config.guild(g2).retention_days() == 90
    # Kai: kein Zugriff
    r = await client.get("/cogs/serverstats?guild=1000", headers=KAI, **NR)
    assert r.status in (302, 403), r.status
    # Zurücksetzen (mit Bestätigung)
    assert "data-confirm='Wirklich alle Statistikdaten" in t
    r = await client.post("/cogs/serverstats", headers=OWNER, **NR, data={"csrf_token": tok, "form": "reset", "guild": "1000"})
    assert "ok=" in r.headers["Location"] and await gconf.days() == {}
    r = await client.get("/cogs/serverstats?guild=1000", headers=OWNER); t = await r.text()
    assert "Noch keine Daten" in t and "Noch keine Aktivität gezählt" in t
    # XSS über Kanalnamen
    await cog.on_message(S.msg(g, kai, allg)); await cog.flush()
    allg.name = "<script>alert(1)</script>"
    r = await client.get("/cogs/serverstats?guild=1000", headers=OWNER); t = await r.text()
    assert "<script>alert(1)</script>" not in t and "&lt;script&gt;alert(1)" in t
    allg.name = "allgemein"
    print("Dashboard speichern, Validierung, Rechte (Owner/Bearbeiten/Ansehen/kein Zugriff), Reset, XSS OK")
    await client.close()

    # ------------------------------------------------------------ 7) Befehle
    await gconf.language.set("de")
    await cog.on_message(S.msg(g, kai, allg)); await cog.on_member_join(kai)
    await cog.stats.callback(cog, ctx, 7)
    emb = ctx.sent[-1][1]["embed"]
    names = [f.name for f in emb.fields]
    assert names[:4] == ["Mitglieder", "Netto-Wachstum", "Nachrichten", "Voice-Stunden"], names
    assert "Aktivste Kanäle" in names and "#allgemein" in emb.fields[-1].value
    assert emb.fields[1].value.startswith("+1 (1 rein")
    L.validate_embed(emb)
    await cog.stats.callback(cog, ctx, 500)
    assert "**90**" in ctx.sent[-1][1]["embed"].description
    await cog.statsset_language.callback(cog, ctx, "en")
    await cog.stats.callback(cog, ctx, None)
    assert ctx.sent[-1][1]["embed"].fields[0].name == "Members"
    await cog.statsset_language.callback(cog, ctx, "xx")
    assert "Unknown language" in ctx.sent[-1][0]
    await cog.statsset_settings.callback(cog, ctx)
    assert ctx.sent[-1][1]["embed"].fields[0].value == "60 days"
    await cog.statsset_language.callback(cog, ctx, "de")
    print("Befehle stats / statsset (retention, ignore, language, settings) OK")

    # ------------------------------------------------------------ 8) Entladen: Puffer sichern, Seite weg
    await cog.on_message(S.msg(g, kai, ann))
    assert "serverstats" in wc.pages
    await cog.cog_unload()
    assert "serverstats" not in wc.pages and cog._pending == {}
    today = time.strftime("%Y-%m-%d", time.gmtime(now[0]))
    assert sum((await gconf.days())[today]["messages"].values()) >= 2
    print("cog_unload: Puffer geschrieben, Dashboard-Seite entfernt OK")
    print("ALLE SERVERSTATS-TESTS OK")


asyncio.run(main())
