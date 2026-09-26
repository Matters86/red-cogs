"""scheduler: nächster Termin (alle Typen, Sommerzeit Europe/Berlin, Monatsende), Downtime-Regel, Auto-Pause,
allowed_mentions, „vorherige löschen“, Dashboard-Formulare (ohne JS), Vorschau, Befehle + Rechte, Datenlöschung."""
import asyncio, re, time
from datetime import datetime, date
from urllib.parse import unquote, urlparse, parse_qs
from zoneinfo import ZoneInfo
import sc_harness as S
from aiohttp.test_utils import TestServer, TestClient

NR = dict(allow_redirects=False)
OWNER = {"X-Test-User": "1"}; TOM = {"X-Test-User": "12"}; LENA = {"X-Test-User": "11"}
B = ZoneInfo("Europe/Berlin")


def ts(y, mo, d, h=0, mi=0, tz=B):
    return int(datetime(y, mo, d, h, mi, tzinfo=tz).timestamp())


def local(t):
    return datetime.fromtimestamp(t, B).strftime("%Y-%m-%d %H:%M %z")


def csrf(text):
    return re.search(r"name='csrf_token' value='([^']+)'", text).group(1)


def loc(r):
    q = parse_qs(urlparse(r.headers["Location"]).query)
    return {k: unquote(v[0]) for k, v in q.items()}, r.headers["Location"]


class Ctx:
    def __init__(self, guild, author, channel):
        self.guild = guild; self.author = author; self.channel = channel; self.sent = []
    async def send(self, content=None, **kw):
        assert content is None or len(content) <= 2000
        self.sent.append(content)
    @property
    def last(self): return self.sent[-1]


def test_timing():
    from rc.scheduler import timing as T
    nr = T.next_run
    # täglich 09:00 über die Umstellung auf Sommerzeit (29.03.2026): bleibt 09:00 Ortszeit
    t = ts(2026, 3, 27, 12)
    seq = []
    for _ in range(3):
        t = nr({"type": "daily", "time": "09:00"}, "Europe/Berlin", t); seq.append(local(t))
    assert seq == ["2026-03-28 09:00 +0100", "2026-03-29 09:00 +0200", "2026-03-30 09:00 +0200"], seq
    # Uhrzeit in der Lücke (02:30 am 29.03.) -> 03:30 Sommerzeit, danach wieder 02:30
    t = nr({"type": "daily", "time": "02:30"}, "Europe/Berlin", ts(2026, 3, 28, 12))
    assert local(t) == "2026-03-29 03:30 +0200", local(t)
    assert local(nr({"type": "daily", "time": "02:30"}, "Europe/Berlin", t)) == "2026-03-30 02:30 +0200"
    # doppelte Stunde am 25.10.2026: nur einmal (erste, Sommerzeit)
    t = nr({"type": "daily", "time": "02:30"}, "Europe/Berlin", ts(2026, 10, 24, 12))
    assert local(t) == "2026-10-25 02:30 +0200"
    assert local(nr({"type": "daily", "time": "02:30"}, "Europe/Berlin", t)) == "2026-10-26 02:30 +0100"
    # wöchentlich Mo+Fr über die Winterzeit-Umstellung
    t = ts(2026, 10, 22, 12); seq = []
    for _ in range(3):
        t = nr({"type": "weekly", "time": "18:00", "weekdays": [0, 4]}, "Europe/Berlin", t); seq.append(local(t))
    assert seq == ["2026-10-23 18:00 +0200", "2026-10-26 18:00 +0100", "2026-10-30 18:00 +0100"], seq
    # monatlich am 31. -> Monatsende sauber (inkl. Schaltjahr 2028)
    t = ts(2027, 12, 31, 13); seq = []
    for _ in range(4):
        t = nr({"type": "monthly", "time": "12:00", "day": 31}, "Europe/Berlin", t); seq.append(local(t)[:10])
    assert seq == ["2028-01-31", "2028-02-29", "2028-03-31", "2028-04-30"], seq
    assert local(nr({"type": "monthly", "time": "12:00", "day": 30}, "Europe/Berlin", ts(2027, 2, 1)))[:10] == "2027-02-28"
    # einmalig: Zukunft / Vergangenheit
    once = {"type": "once", "date": "2026-12-24", "time": "18:00"}
    assert nr(once, "Europe/Berlin", ts(2026, 12, 1)) == ts(2026, 12, 24, 18)
    assert nr(once, "Europe/Berlin", ts(2026, 12, 24, 18)) is None
    # Intervall: echte Zeit (über die Umstellung konstant 2 h), Anker = Anlegen bzw. Startdatum
    a = ts(2026, 3, 29, 0)
    t1 = nr({"type": "interval", "minutes": 120}, "Europe/Berlin", a + 1, anchor_ts=a)
    t2 = nr({"type": "interval", "minutes": 120}, "Europe/Berlin", t1, anchor_ts=a)
    assert t1 == a + 7200 and t2 - t1 == 7200 and local(t2) == "2026-03-29 05:00 +0200"
    assert nr({"type": "interval", "minutes": 30}, "Europe/Berlin", ts(2026, 5, 1), start_date="2026-05-03") == ts(2026, 5, 3)
    # Start-/Enddatum
    d = {"type": "daily", "time": "10:00"}
    assert nr(d, "Europe/Berlin", ts(2026, 5, 1), start_date="2026-05-10") == ts(2026, 5, 10, 10)
    assert nr(d, "Europe/Berlin", ts(2026, 5, 10, 11), end_date="2026-05-10") is None
    assert nr(d, "Europe/Berlin", ts(2026, 5, 10, 9), end_date="2026-05-10") == ts(2026, 5, 10, 10)
    # andere Zeitzone
    assert nr(d, "America/New_York", ts(2026, 7, 1, 0, tz=ZoneInfo("UTC"))) == ts(2026, 7, 1, 10, tz=ZoneInfo("America/New_York"))
    # Validierung / Parser
    assert T.validate({"type": "interval", "minutes": 9}) == "err_interval"
    assert T.validate({"type": "interval", "minutes": 10}) is None
    assert T.validate({"type": "weekly", "time": "10:00", "weekdays": []}) == "err_weekdays"
    assert T.validate({"type": "daily", "time": "25:00"}) == "err_time"
    assert T.validate({"type": "monthly", "time": "10:00", "day": 32}) == "err_day"
    assert T.validate(d, start_date="2026-05-10", end_date="2026-05-01") == "err_range"
    assert T.parse_spec("wöchentlich mo,mi,fr 18:00") == ({"type": "weekly", "weekdays": [0, 2, 4], "time": "18:00"}, None)
    assert T.parse_spec("weekly sun,mon 07:30")[0]["weekdays"] == [0, 6]
    assert T.parse_spec("täglich 09:00")[0] == {"type": "daily", "time": "09:00"}
    assert T.parse_spec("einmalig 24.12.2026 18:00")[0] == once
    assert T.parse_spec("monatlich 31. 12:00")[0] == {"type": "monthly", "day": 31, "time": "12:00"}
    assert T.parse_spec("alle 1h30m")[0] == {"type": "interval", "minutes": 90}
    assert T.parse_spec("every 5m") == (None, "err_interval")
    assert T.parse_spec("irgendwann") == (None, "err_spec")
    assert T.parse_spec("wöchentlich xx 18:00") == (None, "err_weekdays")
    assert T.describe({"type": "weekly", "weekdays": [0, 4], "time": "18:00"}) == "wöchentlich Mo, Fr um 18:00"
    assert "letzten Tag" in T.describe({"type": "monthly", "day": 31, "time": "12:00"})
    # Downtime-Regel
    daily = {"type": "daily", "time": "09:00"}
    first = ts(2026, 6, 1, 9)
    assert T.catch_up(daily, "Europe/Berlin", first, first + 300) == first            # 5 min zu spät -> senden
    assert T.catch_up(daily, "Europe/Berlin", first, first + 900) is None             # 15 min -> überspringen
    assert T.catch_up(daily, "Europe/Berlin", first, first + 86400 + 120) == first + 86400   # letzter < 10 min
    iv = {"type": "interval", "minutes": 10}
    assert T.catch_up(iv, "Europe/Berlin", first, first + 3 * 3600 + 60, anchor_ts=first - 600) == first + 3 * 3600
    print("Zeitplan: alle Typen, Sommerzeit (Lücke/Doppelung/konstante Ortszeit), Monatsende, Intervall, "
          "Start/Ende, Parser, Downtime-Regel – OK")


async def main():
    test_timing()
    wc, bot, app, cog = await S.make_app()
    from rc.scheduler.scheduler import Scheduler
    g1, g2 = bot.guilds
    owner, lena, tom, kai = (g1.get_member(i) for i in (1, 11, 12, 13))
    allg, sup, ann, logs = g1.text_channels
    gconf = cog.config.guild(g1)

    # ================================================================ Befehle + Rechte
    ck = Ctx(g1, kai, allg)
    await cog.schedule_add.callback(cog, ck, allg, "täglich 09:00", text="x"); assert "Berechtigung" in ck.last
    await cog.schedule_list.callback(cog, ck); assert "Berechtigung" in ck.last
    co = Ctx(g1, owner, allg)
    await cog.schedule_add.callback(cog, co, allg, "sonntags", text="x"); assert "nicht erkannt" in co.last
    await cog.schedule_add.callback(cog, co, allg, "alle 5m", text="x"); assert "10 Minuten" in co.last
    await cog.schedule_add.callback(cog, co, allg, "einmalig 01.01.2020 10:00", text="x"); assert "Vergangenheit" in co.last
    await cog.schedule_add.callback(cog, co, allg, "täglich 09:00", text="y" * 1901); assert "zu lang" in co.last
    await cog.schedule_add.callback(cog, co, allg, "täglich 09:00", text="Guten Morgen @everyone!")
    assert "angelegt" in co.last and "<t:" in co.last, co.last
    e1 = (await gconf.entries())["1"]
    assert e1["creator_id"] == 1 and e1["schedule"] == {"type": "daily", "time": "09:00"} and e1["next_run_ts"] > time.time()
    await cog.schedule_add.callback(cog, co, ann, "wöchentlich mo,fr 18:00", text="Wochenende!")
    await cog.schedule_list.callback(cog, co)
    assert "#1" in co.last and "#2" in co.last and "wöchentlich Mo, Fr um 18:00" in co.last and "Europe/Berlin" in co.last
    await cog.schedule_pause.callback(cog, co, "2"); assert "pausiert" in co.last
    assert (await gconf.entries())["2"]["paused"] is True
    await cog.schedule_list.callback(cog, co); assert "⏸️" in co.last
    await cog.schedule_resume.callback(cog, co, "#2"); assert "läuft wieder" in co.last
    await cog.schedule_pause.callback(cog, co, "99"); assert "nicht gefunden" in co.last
    S.SENT.clear()
    await cog.schedule_test.callback(cog, co, "1"); assert "Testnachricht" in co.last
    assert S.SENT[-1]["channel"] == allg.id and S.SENT[-1]["allowed_mentions"].everyone is False
    await cog.schedule_timezone.callback(cog, co, "Mars/Olympus"); assert "Unbekannte Zeitzone" in co.last
    before = (await gconf.entries())["1"]["next_run_ts"]
    await cog.schedule_timezone.callback(cog, co, "America/New_York"); assert "neu berechnet" in co.last
    after = (await gconf.entries())["1"]["next_run_ts"]
    assert datetime.fromtimestamp(after, ZoneInfo("America/New_York")).strftime("%H:%M") == "09:00" and after != before
    await cog.schedule_timezone.callback(cog, co, "Europe/Berlin")
    await cog.schedule_timezone.callback(cog, co, None); assert "Europe/Berlin" in co.last
    await cog.schedule_remove.callback(cog, co, "2"); assert "gelöscht" in co.last
    assert "2" not in await gconf.entries()
    print("Befehle: add (Zeitplan-Parser, Validierung), list, pause/resume, test (ohne Ping), timezone, remove, "
          "Rechte – OK")

    # ================================================================ Ausführen, allowed_mentions, vorherige löschen
    e, err = await cog.add_entry(g1, {"channel_id": ann.id, "content": "Raid heute! @everyone <@13>", "ping_role_id": 1103,
                                      "embed": {"title": "Raid", "description": "20 Uhr", "color": "#f5b94a",
                                                "image_url": "https://example.com/a.png"},
                                      "schedule": {"type": "daily", "time": "18:00"}, "delete_previous": True},
                                 creator_id=11)
    assert err is None, err
    due = e["next_run_ts"]
    S.SENT.clear()
    assert await cog.process_due(due - 30) == 0 and not S.SENT                    # noch nicht fällig
    assert await cog.process_due(due + 40) == 1
    m = S.SENT[-1]
    am = m["allowed_mentions"]
    assert m["content"].startswith("<@&1103>\nRaid heute!") and m["embed"].title == "Raid"
    assert [r.id for r in am.roles] == [1103] and am.users is False and am.everyone is False
    assert m["embed"].image.url == "https://example.com/a.png"
    first_msg = m["message"]
    st = (await gconf.entries())[e["id"]]
    assert st["run_count"] == 1 and st["last_message_id"] == first_msg.id and st["next_run_ts"] == due + 86400
    assert await cog.process_due(due + 60) == 0                                     # nicht doppelt
    assert await cog.process_due(due + 86400 + 5) == 1
    assert first_msg.deleted and first_msg.id not in ann._messages                   # vorherige gelöscht
    ok, _ = await cog.test_entry(g1, e["id"])
    assert ok and S.SENT[-1]["allowed_mentions"].roles is False                       # Test ohne Ping
    assert (await gconf.entries())[e["id"]]["run_count"] == 2                        # Test zählt nicht
    print("Ausführung: pünktlich, genau einmal, nur Ping-Rolle erlaubt (kein @everyone/Nutzer), Embed, "
          "vorherige Nachricht gelöscht, Test ohne Ping – OK")

    # ================================================================ Downtime
    st = (await gconf.entries())[e["id"]]
    nxt = st["next_run_ts"]                                                          # Tag 3, 18:00
    S.SENT.clear()
    assert await cog.process_due(nxt + 3 * 86400 + 3600) == 0 and not S.SENT        # 3 Tage + 1 h offline
    st = (await gconf.entries())[e["id"]]
    assert st["last_skipped_ts"] == nxt and st["next_run_ts"] == nxt + 4 * 86400 and st["fail_count"] == 0
    assert await cog.process_due(nxt + 4 * 86400 + 9 * 60) == 1                    # 9 min zu spät -> senden
    # Neustart: neue Cog-Instanz holt nichts Altes nach
    cog2 = Scheduler(bot); bot._cogs["Scheduler"] = cog2
    await cog.cog_unload(); await cog2.cog_load(); cog2._tick.cancel()
    st = (await gconf.entries())[e["id"]]
    S.SENT.clear()
    assert await cog2.process_due(st["next_run_ts"] + 11 * 60) == 0 and not S.SENT
    cog = cog2
    print("Downtime-Regel: > 10 min verpasst -> übersprungen, < 10 min -> einmal gesendet – OK")

    # ================================================================ Auto-Pause nach 5 Fehlern
    iv, _ = await cog.add_entry(g1, {"channel_id": logs.id, "content": "Ping", "schedule": {"type": "interval", "minutes": 10}})
    t = iv["next_run_ts"]
    logs.fail_next = 7
    for k in range(5):
        await cog.process_due(t + 1)
        st = (await gconf.entries())[iv["id"]]
        assert st["fail_count"] == k + 1 and "Rechte" in st["last_error"], st
        t = st["next_run_ts"] or t
    assert st["paused"] and st["auto_paused"]
    assert await cog.process_due(t + 99999) == 0                                    # pausiert = nichts
    c = TestClient(TestServer(app)); await c.start_server()
    r = await c.get("/cogs/scheduler?guild=1000", headers=OWNER); t_html = await r.text()
    assert "Automatisch pausiert" in t_html and "automatisch pausiert" in t_html and "Keine Rechte zum Senden" in t_html
    tok = csrf(t_html)
    logs.fail_next = 0
    await cog.set_paused(g1, iv["id"], False)
    st = (await gconf.entries())[iv["id"]]
    assert not st["paused"] and not st["auto_paused"] and st["fail_count"] == 0 and st["next_run_ts"] > time.time()
    # Erfolg setzt den Zähler zurück
    logs.fail_next = 2
    t = st["next_run_ts"]
    await cog.process_due(t + 1); await cog.process_due(t + 601)
    assert (await gconf.entries())[iv["id"]]["fail_count"] == 2
    await cog.process_due(t + 1201)
    st = (await gconf.entries())[iv["id"]]
    assert st["fail_count"] == 0 and st["last_error"] is None and not st["paused"]
    # gelöschter Kanal
    g1.text_channels.remove(logs)
    await cog.process_due(st["next_run_ts"] + 1)
    assert "Kanal nicht gefunden" in (await gconf.entries())[iv["id"]]["last_error"]
    g1.text_channels.append(logs)
    # robuste Schleife: Fehler in einer Guild stoppt die anderen nicht
    orig = cog.process_guild
    calls = []
    async def boom(guild, now):
        calls.append(guild.id)
        if guild.id == 1000:
            raise RuntimeError("kaputt")
        return await orig(guild, now)
    cog.process_guild = boom
    await cog.process_due()
    assert calls == [1000, 2000]
    await cog._tick.coro(cog)
    del cog.process_guild
    print("Auto-Pause nach 5 Fehlern + Hinweis im Dashboard, Fortsetzen, Erfolg setzt Zähler zurück, "
          "Fehler je Server isoliert – OK")

    # ================================================================ Dashboard-Formulare
    await gconf.entries.set({})
    async def post(data, headers=OWNER):
        return await c.post("/cogs/scheduler", headers=headers, data={"csrf_token": tok, "guild": "1000", **data}, **NR)
    base = {"form": "entry", "action": "save", "name": "", "channel": "1003", "content": "Hallo <b>Welt</b>",
            "ping_role": "", "embed_title": "", "embed_description": "", "embed_color": "#5865f2",
            "embed_image": "", "type": "daily", "date": "", "time": "08:15", "day": "", "interval": "",
            "interval_unit": "hours", "start_date": "", "end_date": ""}
    r = await post(base); q, _ = loc(r)
    assert q["ok"].startswith("Nachricht geplant – nächste Ausführung"), q
    e = list((await gconf.entries()).values())[-1]
    assert e["schedule"] == {"type": "daily", "time": "08:15"} and e["name"] == "Hallo <b>Welt</b>" and e["creator_id"] == 1
    # Wöchentlich (Mehrfachauswahl ohne JS = mehrere Felder), monatlich, einmalig, Intervall
    r = await post({**base, "type": "weekly", "weekdays": ["0", "2", "6"], "time": "19:00", "delete_previous": "on"})
    assert "ok" in loc(r)[0]
    e = list((await gconf.entries()).values())[-1]
    assert e["schedule"]["weekdays"] == [0, 2, 6] and e["delete_previous"] is True
    r = await post({**base, "type": "monthly", "day": "31", "time": "12:00", "end_date": "2099-01-01"})
    e = list((await gconf.entries()).values())[-1]
    assert e["schedule"] == {"type": "monthly", "time": "12:00", "day": 31} and e["end_date"] == "2099-01-01"
    future = date(date.today().year + 1, 1, 15).isoformat()
    r = await post({**base, "type": "once", "date": future, "time": "18:30", "ping_role": "1103",
                    "embed_title": "Neujahr", "embed_color": "#ff0000"})
    e = list((await gconf.entries()).values())[-1]
    assert e["next_run_ts"] == int(datetime.fromisoformat(future + "T18:30").replace(tzinfo=B).timestamp())
    assert e["ping_role_id"] == 1103 and e["embed"]["title"] == "Neujahr"
    r = await post({**base, "type": "interval", "interval": "2", "interval_unit": "hours", "time": ""})
    e = list((await gconf.entries()).values())[-1]
    assert e["schedule"] == {"type": "interval", "minutes": 120}
    n_entries = len(await gconf.entries())
    # Validierung (+ Entwurf bleibt erhalten)
    for bad, needle in (({"type": "interval", "interval": "5", "interval_unit": "minutes"}, "10 Minuten"),
                        ({"type": "weekly", "time": "10:00"}, "Wochentag"),
                        ({"content": "", "embed_title": ""}, "leer"),
                        ({"embed_image": "javascript:alert(1)"}, "Bild-URL"),
                        ({"channel": "999"}, "Textkanal"),
                        ({"time": "9 Uhr"}, "Uhrzeit"),
                        ({"type": "once", "date": "2020-01-01"}, "Vergangenheit"),
                        ({"ping_role": "1000"}, "Ping-Rolle"),
                        ({"start_date": "2026-05-10", "end_date": "2026-05-01"}, "Enddatum")):
        r = await post({**base, **bad, "name": "Entwurf-Test"}); q, where = loc(r)
        assert needle in q.get("err", ""), (bad, q)
        assert "draft=1" in where
    assert len(await gconf.entries()) == n_entries
    r = await c.get(where.split("#")[0], headers=OWNER); t_html = await r.text()
    assert "value='Entwurf-Test'" in t_html
    # Vorschau ohne Speichern
    r = await post({**base, "action": "preview", "content": "Vorschau-Text <script>x</script>", "ping_role": "1103",
                    "embed_title": "Titel", "type": "weekly", "weekdays": ["4"], "time": "20:00"})
    q, where = loc(r)
    assert "preview=1" in where and len(await gconf.entries()) == n_entries
    r = await c.get(where.split("#")[0], headers=OWNER); t_html = await r.text()
    assert "Vorschau (noch nicht gespeichert)" in t_html and "Nächste Termine" in t_html and "@Raidleitung" in t_html
    assert "&lt;script&gt;x&lt;/script&gt;" in t_html and "<script>x</script>" not in t_html
    assert t_html.count(" 20:00</li>") + t_html.count(" 20:00 <") >= 1 and "Fr, " in t_html
    # Liste: nächste Ausführung relativ + absolut
    r = await c.get("/cogs/scheduler?guild=1000", headers=OWNER); t_html = await r.text()
    assert re.search(r"in \d+ (Min\.|Std\.|Tag|Tagen)", t_html) and re.search(r"\d\d\.\d\d\.\d{4} \d\d:\d\d", t_html)
    assert "Hallo &lt;b&gt;Welt&lt;/b&gt;" in t_html
    # Bearbeiten
    eid = list((await gconf.entries()))[0]
    r = await c.get(f"/cogs/scheduler?guild=1000&edit={eid}", headers=OWNER); t_html = await r.text()
    assert "Vorschau (gespeicherter Stand)" in t_html and "value='08:15'" in t_html and f"name='eid' value='{eid}'" in t_html
    r = await post({**base, "eid": eid, "time": "07:45", "name": "Morgens"})
    assert loc(r)[0]["ok"].startswith("Gespeichert")
    e = (await gconf.entries())[eid]
    assert e["schedule"]["time"] == "07:45" and e["name"] == "Morgens" and e["updated_by"] == 1
    assert datetime.fromtimestamp(e["next_run_ts"], B).strftime("%H:%M") == "07:45"
    r = await post({**base, "eid": eid, "action": "preview", "content": "Neu?"})
    q, where = loc(r); assert f"edit={eid}" in where
    r = await c.get(where.split("#")[0], headers=OWNER); t_html = await r.text()
    assert "Vorschau (noch nicht gespeichert)" in t_html and "Neu?" in t_html
    assert (await gconf.entries())[eid]["content"] == "Hallo <b>Welt</b>"
    # Aktionen: testen, pausieren, fortsetzen, löschen
    S.SENT.clear()
    r = await post({"form": "action", "eid": eid, "action": "test", "back": "edit"})
    q, where = loc(r); assert q["ok"].startswith("Testnachricht") and f"edit={eid}" in where
    assert S.SENT[-1]["channel"] == ann.id
    ann.forbid.add("send")
    r = await post({"form": "action", "eid": eid, "action": "test"}); assert "Rechte" in loc(r)[0]["err"]
    ann.forbid.discard("send")
    r = await post({"form": "action", "eid": eid, "action": "pause"}); assert (await gconf.entries())[eid]["paused"]
    r = await post({"form": "action", "eid": eid, "action": "resume"}); assert not (await gconf.entries())[eid]["paused"]
    r = await post({"form": "action", "eid": eid, "action": "delete"}); assert loc(r)[0]["ok"] == "Gelöscht"
    assert eid not in await gconf.entries()
    # Einstellungen
    r = await post({"form": "settings", "timezone": "Nirgendwo/Stadt", "language": "de"}); assert "Zeitzone" in loc(r)[0]["err"]
    r = await post({"form": "settings", "timezone": "UTC", "language": "en"}); assert "ok" in loc(r)[0]
    assert await gconf.timezone() == "UTC" and await gconf.language() == "en"
    daily = [x for x in (await gconf.entries()).values() if x["schedule"]["type"] == "weekly"][0]
    assert datetime.fromtimestamp(daily["next_run_ts"], ZoneInfo("UTC")).strftime("%H:%M") == "19:00"
    await post({"form": "settings", "timezone": "Europe/Berlin", "language": "de"})
    # Rechte
    r = await c.get("/cogs/scheduler?guild=1000", headers=TOM); assert r.status == 403
    r = await post({"form": "action", "eid": daily["id"], "action": "delete"}, headers=TOM)
    assert r.status in (302, 403) and daily["id"] in await gconf.entries()
    await wc.config.role_perms.set({"1000": {"1101": {"scheduler": "view"}}})
    r = await c.get("/cogs/scheduler?guild=1000", headers=LENA); assert r.status == 200 and "Nur Ansicht" in await r.text()
    r = await post({"form": "action", "eid": daily["id"], "action": "delete"}, headers=LENA)
    assert daily["id"] in await gconf.entries()
    await wc.config.role_perms.set({})
    print("Dashboard: alle Zeitplan-Arten per Formular (ohne JS), Validierung + Entwurf, Vorschau ohne Speichern, "
          "Bearbeiten, Testen/Pausieren/Fortsetzen/Löschen, Zeitzone, Rechte – OK")

    # ================================================================ Datenlöschung
    await cog.add_entry(g1, {"channel_id": allg.id, "content": "x", "schedule": {"type": "daily", "time": "10:00"}},
                        creator_id=11)
    await cog.red_delete_data_for_user(requester="user", user_id=1)
    await cog.red_delete_data_for_user(requester="user", user_id=11)
    for x in (await gconf.entries()).values():
        assert x["creator_id"] == 0 and x["updated_by"] == 0
    print("red_delete_data_for_user: Ersteller/Bearbeiter anonymisiert – OK")

    await c.close()
    print("ALLE SCHEDULER-TESTS OK")


asyncio.run(main())
