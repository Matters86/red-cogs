"""Funktionstests: „Mein Bereich → Umfragen“ (poll) und „Mein Bereich → Rollen“ (autorole)."""
import asyncio, re
from urllib.parse import unquote, urlparse, parse_qs
import pr_harness as P
import live_harness as L
from aiohttp.test_utils import TestServer, TestClient

NR = dict(allow_redirects=False)
KAI = {"X-Test-User": "13"}; OWNER = {"X-Test-User": "1"}; BEN = {"X-Test-User": "21"}; LENA = {"X-Test-User": "11"}


def csrf(text):
    m = re.search(r"name='csrf_token' value='([^']+)'", text)
    return m.group(1)


def loc(r):
    q = parse_qs(urlparse(r.headers["Location"]).query)
    return {k: unquote(v[0]) for k, v in q.items()}, r.headers["Location"]


async def main():
    wc, bot, app, ids = await P.make_app()
    g1, g2 = bot.guilds
    kai = g1.get_member(13)
    pl = bot.get_cog("Poll"); ar = bot.get_cog("Autorole")
    c = TestClient(TestServer(app)); await c.start_server()

    # ================================================================== UMFRAGEN
    r = await c.get("/me?guild=1000", headers=KAI); t = await r.text()
    assert r.status == 200 and "An laufenden Umfragen teilnehmen" in t and "Rollen selbst wählen" in t
    assert "/me/umfragen" in t and "/me/rollen" in t and "bi-bar-chart" in t and "bi-person-badge" in t
    r = await c.get("/me/umfragen?guild=1000", headers=KAI); t = await r.text()
    assert r.status == 200
    for q in ("Beste Pizza?", "Wann soll der nächste Raid", "Neues Server-Logo?", "Geschlossene Umfrage"):
        assert q in t, q
    for q in ("Geheime Team-Umfrage", "Alte Umfrage (20 Tage)", "Ungepostet", "RP-Umfrage"):
        assert q not in t, q
    assert "<script>alert" not in t and "&lt;script&gt;" in t
    assert "Salami" in t and "67%" in t          # Ergebnis live wie im Embed
    assert "Lena" not in t and "Tom" not in t    # keine Namen (Embed zeigt auch keine)
    assert "data-tab='laufend'" in t and "data-tab='beendet'" in t
    tok = csrf(t)
    r = await c.get("/me/umfragen?guild=1000", headers=LENA); t2 = await r.text()
    assert "Geheime Team-Umfrage" in t2          # Lena sieht #support
    print("Umfragen: Sichtbarkeit nach Kanal, ungepostet/alt/fremder Server ausgeblendet, kein XSS – OK")

    p1, p2, p3, p4, p6 = ids["p1"], ids["p2"], ids["p3"], ids["p4"], ids["p6"]

    async def vote(pid, opt, headers=KAI, guild="1000", token=None):
        wc._member_limiter._hits.clear()   # Test-Tempo: 30/min-Limit hier nicht relevant (unten separat geprüft)
        data = {"csrf_token": token or tok, "form": "vote", "guild": guild, "poll": pid, "option": str(opt)}
        return await c.post("/me/umfragen", headers=headers, data=data, **NR)

    async def votes(pid, uid="13"):
        return ((await pl.config.guild(g1).polls())[pid]["votes"].get(uid) or {}).get("choices")

    msg_id = (await pl.config.guild(g1).polls())[p1]["message_id"]
    L.LOG.clear()
    r = await vote(p1, 1); q, where = loc(r)
    assert q.get("ok") == "✅ Stimme für Salami gezählt." and where.endswith("#pl-" + p1), where
    assert await votes(p1) == [1]
    edits = [e for e in L.LOG if e[0] == "edit" and e[2]["message"] == msg_id]
    assert edits, L.LOG
    msg = g1.get_channel(1001)._messages[msg_id]
    labels = [ch.label for ch in msg.view.children]
    assert labels[1].endswith("·  2"), labels         # Button-Zähler aktualisiert
    r = await vote(p1, 2); q, _ = loc(r)
    assert q["ok"].startswith("🔄 Stimme geändert zu Hawaii") and await votes(p1) == [2]
    r = await vote(p1, 2); q, _ = loc(r)
    assert q["ok"].startswith("↩️ Deine Stimme für Hawaii") and await votes(p1) is None
    print("Einfachwahl: wählen, ändern, zurückziehen + Discord-Nachricht aktualisiert – OK")

    r = await vote(p2, 0); r = await vote(p2, 2)
    assert await votes(p2) == [0, 2]
    r = await vote(p2, 0); q, _ = loc(r)
    assert "zurückgezogen" in q["ok"] and await votes(p2) == [2]
    print("Mehrfachwahl: Optionen an-/abwählen – OK")

    before = await pl.config.guild(g1).polls()
    for pid, opt, expect in [(p6, 0, "Diese Umfrage ist geschlossen."), (p4, 1, "Diese Umfrage ist beendet."),
                             (p3, 0, "Diese Umfrage existiert nicht mehr."), ("p-0099", 0, "Diese Umfrage existiert nicht mehr."),
                             ("p-7777", 0, "Diese Umfrage existiert nicht mehr."), ("", 0, "Diese Umfrage existiert nicht mehr."),
                             (p1, "abc", "Option nicht erkannt – bitte erneut versuchen."),
                             (p1, "-1", "Option nicht erkannt – bitte erneut versuchen."),
                             (p1, "99", "Option nicht erkannt – bitte erneut versuchen.")]:
        r = await vote(pid, opt); q, _ = loc(r)
        assert q.get("err") == expect, (pid, opt, q)
    assert await pl.config.guild(g1).polls() == before
    # fremder Server (Kai ist dort kein Mitglied / Portal aus)
    r = await vote(p1, 0, guild="2000"); assert r.status == 302 and "err=" in r.headers["Location"]
    assert await pl.config.guild(g1).polls() == before
    assert (await pl.config.guild(g2).polls())["p-0001"]["votes"] == {}
    r = await c.get("/me/umfragen?guild=2000", headers=KAI, **NR); assert r.status == 302 and "err=" in r.headers["Location"]
    r = await c.get("/me/umfragen?guild=2000", headers=BEN, **NR); assert r.status in (302, 403)
    # CSRF
    r = await c.post("/me/umfragen", headers=KAI, data={"form": "vote", "guild": "1000", "poll": p1, "option": "0"}, **NR)
    assert r.status == 400 and await pl.config.guild(g1).polls() == before
    # Kanal wird unsichtbar -> Umfrage weg + Stimme abgelehnt
    g1.get_channel(1001).hidden = {13}
    r = await c.get("/me/umfragen?guild=1000", headers=KAI); t = await r.text()
    assert "Beste Pizza?" not in t
    r = await vote(p1, 0); q, _ = loc(r); assert q.get("err") == "Diese Umfrage existiert nicht mehr."
    g1.get_channel(1001).hidden = set()
    assert await pl.config.guild(g1).polls() == before
    print("Abgelehnt: geschlossen, beendet, unsichtbar, ungepostet, unbekannt, ungültige Option, fremder Server, "
          "CSRF, Kanal nachträglich gesperrt – nichts geändert – OK")

    # Team-Dashboard: Schalter + closed_ts
    r = await c.get("/cogs/poll?guild=1000", headers=OWNER); t = await r.text()
    assert "Im Mitglieder-Bereich anzeigen" in t and "Zugriff &amp; Rollen" in t and "name='member_page' checked" in t
    otok = csrf(t)
    settings = {"csrf_token": otok, "form": "settings", "guild": "1000", "language": "de", "allow_create": "manager",
                "max_options": "10"}
    r = await c.post("/cogs/poll", headers=OWNER, data=settings, **NR)
    assert r.status == 302 and await pl.config.guild(g1).member_page() is False
    r = await c.get("/me/umfragen?guild=1000", headers=KAI); t = await r.text()
    assert "ausgeschaltet" in t and "Beste Pizza?" not in t
    r = await vote(p1, 0); q, _ = loc(r); assert "ausgeschaltet" in q["err"] and await votes(p1) is None
    r = await c.post("/cogs/poll", headers=OWNER, data={**settings, "member_page": "on"}, **NR)
    assert await pl.config.guild(g1).member_page() is True
    r = await c.post("/cogs/poll", headers=OWNER, data={"csrf_token": otok, "form": "action", "guild": "1000",
                                                        "poll_id": p1, "action": "close"}, **NR)
    assert (await pl.config.guild(g1).polls())[p1].get("closed_ts")
    r = await c.get("/me/umfragen?guild=1000", headers=KAI); t = await r.text()
    beendet = t[t.index("data-tab='beendet'"):]
    assert "Beste Pizza?" in beendet and "endete vor" in beendet
    r = await vote(p1, 0); q, _ = loc(r); assert q["err"] == "Diese Umfrage ist geschlossen."
    r = await c.post("/cogs/poll", headers=OWNER, data={"csrf_token": otok, "form": "action", "guild": "1000",
                                                        "poll_id": p1, "action": "reopen"}, **NR)
    assert "closed_ts" not in (await pl.config.guild(g1).polls())[p1]
    # Auto-Ende setzt closed_ts ebenfalls
    await pl._end_poll(g1, p2, "de")
    assert (await pl.config.guild(g1).polls())[p2].get("closed_ts")
    print("Team-Dashboard: Schalter (Standard an) + Hinweis, aus = Seite/Abstimmen gesperrt; closed_ts bei "
          "Schließen/Auto-Ende, Wiederöffnen entfernt ihn – OK")

    # ==================================================================== ROLLEN
    r = await c.get("/me/rollen?guild=1000", headers=KAI); t = await r.text()
    assert r.status == 200
    for s in ("Namensfarbe", "Benachrichtigungen", "Welche Spiele spielst du?", "Deine Hauptfarbe (Dropdown)"):
        assert s in t, s
    for s in ("Team intern", "Entwurf", "RP-Farbe", "Geheim-Rolle"):
        assert s not in t, s
    assert "<b>kein HTML</b>" not in t and "&lt;b&gt;kein HTML" in t
    rtok = csrf(t)

    async def btn(pid, role, guild="1000", form="btn"):
        wc._member_limiter._hits.clear()
        return await c.post("/me/rollen", headers=KAI, data={"csrf_token": rtok, "form": form, "guild": guild,
                                                              "panel": pid, "role": str(role)}, **NR)

    async def sel(pid, roles, guild="1000", form="sel"):
        wc._member_limiter._hits.clear()
        data = [("csrf_token", rtok), ("form", form), ("guild", guild), ("panel", pid)] + [("roles", str(x)) for x in roles]
        return await c.post("/me/rollen", headers=KAI, data=data, **NR)

    def held():
        return {r.id for r in kai.roles}

    P.ROLE_LOG.clear()
    r = await btn("aaaa0001", 1201); q, where = loc(r)
    assert q["ok"] == "✅ Rot hinzugefügt." and 1201 in held() and where.endswith("#ar-aaaa0001")
    r = await btn("aaaa0001", 1202); q, _ = loc(r)
    assert q["ok"] == "✅ Du hast jetzt nur noch Blau aus dieser Gruppe." and 1202 in held() and 1201 not in held()
    r = await btn("aaaa0001", 1202); q, _ = loc(r)
    assert q["ok"] == "🗑️ Blau entfernt." and not ({1201, 1202} & held())
    print("Buttons „nur eine“ + an/ab: nehmen, tauschen, abgeben – OK")

    r = await btn("aaaa0003", 1221); q, _ = loc(r); assert q["ok"] == "✅ WoW hinzugefügt." and 1221 in held()
    n = len(P.ROLE_LOG)
    r = await btn("aaaa0003", 1221); q, _ = loc(r); assert q["ok"] == "Du hast WoW bereits." and len(P.ROLE_LOG) == n
    r = await btn("aaaa0003", 1229); q, _ = loc(r)
    assert q["err"] == "⚠️ Diese Rolle kann ich dir gerade nicht geben." and 1229 not in held()
    print("Buttons „nur vergeben“: kein Abgeben, Rolle über dem Bot abgelehnt (Hierarchie) – OK")

    r = await sel("aaaa0002", [1211, 1212]); q, _ = loc(r)
    assert q["ok"] == "➕ News-Ping, Event-Ping" and {1211, 1212} <= held()
    r = await sel("aaaa0002", [1212]); q, _ = loc(r); assert q["ok"] == "➖ News-Ping" and 1211 not in held()
    r = await sel("aaaa0002", []); q, _ = loc(r); assert q["ok"] == "➖ Event-Ping" and not ({1211, 1212, 1213} & held())
    r = await sel("aaaa0002", []); q, _ = loc(r); assert q["ok"] == "Nichts geändert."
    r = await sel("aaaa0006", [1201]); q, _ = loc(r); assert q["ok"] == "➕ Rot" and 1201 in held()
    r = await sel("aaaa0006", [1202]); q, _ = loc(r); assert q["ok"] == "➕ Blau • ➖ Rot" and 1201 not in held()
    r = await sel("aaaa0006", [""]); q, _ = loc(r); assert q["ok"] == "➖ Blau" and 1202 not in held()
    print("Dropdown: Mehrfachauswahl = neuer Stand, „nur eine“ tauschen/keine – OK")

    snap = (held(), len(P.ROLE_LOG))
    rejects = [
        (btn("aaaa0001", 1104), "Diese Rolle gehört nicht zu diesem Panel"),          # eigene VIP-Rolle
        (btn("aaaa0001", 1101), "Diese Rolle gehört nicht zu diesem Panel"),          # Support (Team-Rolle)
        (btn("aaaa0001", 2201), "Diese Rolle gehört nicht zu diesem Panel"),          # Rolle vom anderen Server
        (btn("aaaa0001", "abc"), "Diese Rolle gehört nicht zu diesem Panel"),
        (sel("aaaa0002", [1211, 1229]), "Diese Rolle gehört nicht zu diesem Panel"),
        (sel("aaaa0002", ["x"]), "Diese Rolle gehört nicht zu diesem Panel"),
        (sel("aaaa0006", [1201, 1202]), "Bei diesem Panel ist nur eine Rolle möglich"),
        (btn("bbbb0001", 2201), "Dieses Panel gibt es nicht mehr."),                  # Panel-ID von Server 2000
        (btn("aaaa0004", 1231), "Dieses Panel gibt es nicht mehr."),                  # Kanal unsichtbar
        (btn("aaaa0005", 1221), "Dieses Panel gibt es nicht mehr."),                  # nicht gepostet
        (btn("ffff9999", 1221), "Dieses Panel gibt es nicht mehr."),
        (sel("aaaa0001", [1201]), "Unbekannte Aktion"),                               # Buttons-Panel per Dropdown
        (btn("aaaa0002", 1211, form="btn"), "Unbekannte Aktion"),                     # Dropdown-Panel per Button
        (btn("aaaa0001", 1201, form="hack"), "Unbekannte Aktion"),
    ]
    for coro, expect in rejects:
        r = await coro; q, _ = loc(r)
        assert q.get("err", "").startswith(expect), (expect, q)
    r = await btn("aaaa0001", 1201, guild="2000"); assert "err=" in r.headers["Location"]
    r = await c.get("/me/rollen?guild=2000", headers=KAI, **NR); assert "err=" in r.headers["Location"]
    r = await c.post("/me/rollen", headers=KAI, data={"form": "btn", "guild": "1000", "panel": "aaaa0001", "role": "1201"}, **NR)
    assert r.status == 400
    assert (held(), len(P.ROLE_LOG)) == snap
    print("Abgelehnt: fremde Rollen-IDs (auch anderer Server), Panel-ID anderer Server, unsichtbar/ungepostet, "
          "mehrere bei „nur eine“, falsche Bedienart, fremder Server, CSRF – keine Rolle geändert – OK")

    g1.me.guild_permissions.manage_roles = False
    r = await c.get("/me/rollen?guild=1000", headers=KAI); t = await r.text()
    assert "darf gerade keine Rollen vergeben" in t
    r = await btn("aaaa0001", 1201); q, _ = loc(r)
    assert q["err"].startswith("⚠️ Mir fehlt die Berechtigung Rollen verwalten")
    g1.me.guild_permissions.manage_roles = True
    kai.fail_roles = True
    r = await btn("aaaa0001", 1201); q, _ = loc(r); assert q["err"].startswith("⚠️ Das hat nicht geklappt")
    kai.fail_roles = False
    assert (held(), len(P.ROLE_LOG)) == snap
    print("Bot ohne „Rollen verwalten“ / Discord-Fehler: Meldung wie beim Button – OK")

    r = await c.get("/cogs/autorole?guild=1000", headers=OWNER); t = await r.text()
    assert "Im Mitglieder-Bereich anzeigen" in t and "Zugriff &amp; Rollen" in t and "name='member_page' checked" in t
    atok = csrf(t)
    base = {"csrf_token": atok, "form": "settings", "guild": "1000", "language": "de", "screening": "auto",
            "delay": "0", "min_account_age": "0", "enabled": "on"}
    r = await c.post("/cogs/autorole", headers=OWNER, data=base, **NR)
    assert await ar.config.guild(g1).member_page() is False
    r = await c.get("/me/rollen?guild=1000", headers=KAI); t = await r.text()
    assert "ausgeschaltet" in t and "Namensfarbe" not in t
    r = await btn("aaaa0001", 1201); q, _ = loc(r); assert "ausgeschaltet" in q["err"] and 1201 not in held()
    r = await c.post("/cogs/autorole", headers=OWNER, data={**base, "member_page": "on"}, **NR)
    assert await ar.config.guild(g1).member_page() is True
    print("Team-Dashboard Autorole: Schalter (Standard an) + Hinweis, aus = Seite/Aktionen gesperrt – OK")

    # Rate-Limit von WebCore greift auch hier (31. POST pro Minute)
    wc._member_limiter._hits.clear()
    for i in range(31):
        r = await c.post("/me/rollen", headers=KAI, data={"csrf_token": rtok, "form": "btn", "guild": "1000",
                                                          "panel": "aaaa0003", "role": "1221"}, **NR)
    assert r.status == 429
    print("Rate-Limit 30/min – OK")

    # Discord-Buttons laufen weiter über dieselbe Funktion (Sichtprobe; Vergleich alt/neu: pr_btncmp.py)
    await c.close()
    print("ALLE PR-TESTS OK")

asyncio.run(main())
