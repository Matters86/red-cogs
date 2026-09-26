"""Funktionstests TwitchLive mit gemockter Twitch-API (FakeTwitch) und live_harness-Kanälen."""
import asyncio, contextlib, re, time
import tw_harness as T
import live_harness as L
from aiohttp.test_utils import TestClient, TestServer

MENTIONS = []   # (channel_id, allowed_mentions) je send
_orig_send = L._SendMixin.send


async def _send(self, content=None, **kw):
    MENTIONS.append((self.id, kw.get("allowed_mentions")))
    return await _orig_send(self, content, **kw)
L._SendMixin.send = _send


def ops(kind=None, since=0):
    return [e for e in L.LOG[since:] if kind is None or e[0] == kind]


def csrf(html):
    return re.search(r"name='csrf_token' value='([^']+)'", html).group(1)


class Ctx:
    def __init__(self, bot, guild, author):
        self.bot = bot; self.guild = guild; self.author = author; self.clean_prefix = "!"
        self.sent = []; self.deleted = False
        me = self

        class Msg:
            async def delete(self_inner):
                me.deleted = True
        self.message = Msg()

    async def send(self, content=None, **kw):
        self.sent.append(content)

    @contextlib.asynccontextmanager
    async def typing(self):
        yield


passed = []


def ok(name):
    passed.append(name); print("OK ", name)


async def main():
    wc, bot, app = await L.make_app()
    T.install_role_ops(bot)
    g1, g2 = bot.get_guild(1000), bot.get_guild(2000)
    cog = await T.make_cog(bot, wc)
    f = cog.fake
    clock = [time.time()]
    cog._now = lambda: clock[0]
    for login in ("matters86", "lenaplays", "kaigaming"):
        f.add_user(login, login.capitalize())
    await cog.config.client_id.set(T.CLIENT_ID); await cog.config.client_secret.set(T.SECRET)
    gc = cog.config.guild(g1)
    await gc.default_channel.set(1003)

    # --- ohne Zugangsdaten: keine Abfrage ---------------------------------------------------------
    await cog.config.client_secret.set("")
    d = await cog.poll_once()
    assert cog.status["state"] == "no_credentials" and not f.calls and d == 60, (cog.status, f.calls, d)
    await cog.config.client_secret.set(T.SECRET)
    ok("ohne Zugangsdaten: keine Anfrage, Status no_credentials, Intervall 60 s")

    # --- Hinzufügen (mit Login-Prüfung) -----------------------------------------------------------
    new, err = await cog.upsert_channel(g1, "matters86", ping_role=1104)
    assert new and err is None
    new, err = await cog.upsert_channel(g1, "gibtsnicht")
    assert err == "unknown_login", err
    assert f.token_n == 1
    ok("upsert: Login wird über /users geprüft (unbekannt -> Fehler), Token 1x geholt")

    # --- live -> genau eine Meldung ----------------------------------------------------------------
    f.go_live("matters86", "s1", title="Hallo @everyone <@&1101> **fett**", viewers=5)
    n0 = len(L.LOG); MENTIONS.clear()
    await cog.poll_once()
    sends = ops("send", n0)
    assert len(sends) == 1 and sends[0][1] == 1003, sends
    am = MENTIONS[-1][1]
    assert am.everyone is False and am.users is False and [r.id for r in am.roles] == [1104], am.to_dict()
    msg = g1.get_channel(1003)._messages[sends[0][2]["message"]]
    emb = msg.embeds[0]
    assert "<@&1104>" in msg.content and emb.image.url.startswith(
        "https://static-cdn.jtvnw.net/previews-ttv/live_user_matters86-1280x720.jpg?t="), emb.image.url
    assert emb.thumbnail.url.endswith("matters86-profile_image-300x300.png")
    btn = msg.view.children[0]
    assert btn.url == "https://www.twitch.tv/matters86" and btn.label == "Zum Stream"
    ok("live -> genau 1 Meldung, allowed_mentions nur @VIP, Vorschaubild 1280x720 + Cache-Buster, Profilbild, Link-Button")

    n0 = len(L.LOG)
    clock[0] += 60; await cog.poll_once()
    clock[0] += 60; await cog.poll_once()
    assert not ops("send", n0) and not ops("edit", n0), ops(None, n0)
    ok("erneuter Poll -> keine zweite Meldung, kein Edit vor dem Update-Takt")

    clock[0] += 601; f.live["matters86"]["viewer_count"] = 77
    await cog.poll_once()
    assert len(ops("edit", n0)) == 1 and not ops("send", n0)
    st = (await gc.state())["matters86"]
    assert st["viewers"] == 77 and st["peak_viewers"] == 77
    ok("nach 10 min: Meldung aktualisiert (Zuschauer), keine neue")

    # --- Neustart: neuer Cog, gleiche Config -> keine zweite Meldung -------------------------------
    cog2 = await T.make_cog(bot, None, fake=f)
    cog2._now = lambda: clock[0]
    n0 = len(L.LOG)
    clock[0] += 60; await cog2.poll_once()
    assert not ops("send", n0), ops(None, n0)
    ok("Neustart (neue Instanz, Stream-ID aus Config) -> keine Doppelmeldung")

    # --- offline -> bearbeiten ---------------------------------------------------------------------
    await gc.links.set({"1": "matters86"})
    del f.live["matters86"]
    n0 = len(L.LOG)
    clock[0] += 60; await cog.poll_once()
    assert not ops("edit", n0), "Kulanz 5 min"
    clock[0] += 301; await cog.poll_once()
    edits = ops("edit", n0)
    assert len(edits) == 1 and "war live" in edits[0][2]["content"], edits
    assert "<@&" not in msg.content and msg.embeds[0].footer.text == "Twitch · Stream beendet"
    assert msg.view.children[0].label == "Zum Kanal"
    assert "matters86" not in await gc.state()
    ok("offline (nach 5 min Kulanz) -> Nachricht bearbeitet: „war live“ + Dauer, Ping entfernt")

    # --- gleiche Stream-ID taucht wieder auf -> still -----------------------------------------------
    f.go_live("matters86", "s1")
    n0 = len(L.LOG)
    clock[0] += 60; await cog.poll_once()
    assert not ops("send", n0)
    ok("gleiche Stream-ID nach Ende erneut gesehen -> keine zweite Meldung")
    del f.live["matters86"]; clock[0] += 400; await cog.poll_once()

    # --- neuer Stream + Live-Rolle + löschen bei Ende ----------------------------------------------
    await gc.live_role.set(1104)
    await gc.end_action.set("delete")
    f.go_live("matters86", "s2")
    n0 = len(L.LOG)
    clock[0] += 60; await cog.poll_once()
    assert len(ops("send", n0)) == 1 and ops("add_roles", n0), ops(None, n0)
    owner_member = g1.get_member(1)
    assert any(r.id == 1104 for r in owner_member.roles)
    del f.live["matters86"]
    clock[0] += 400; await cog.poll_once()
    assert len(ops("delete", n0)) == 1 and ops("remove_roles", n0)
    assert not any(r.id == 1104 for r in owner_member.roles)
    ok("neue Stream-ID -> neue Meldung; Live-Rolle vergeben/entfernt; Ende mit „löschen“ -> gelöscht")
    await gc.end_action.set("edit"); await gc.live_role.set(None)

    # --- Meldung manuell gelöscht -> nie neu posten --------------------------------------------------
    f.go_live("matters86", "s3")
    clock[0] += 60; await cog.poll_once()
    sid = (await gc.state())["matters86"]["message_id"]
    ch = g1.get_channel(1003); ch._messages.pop(sid)
    n0 = len(L.LOG)
    for _ in range(3):
        clock[0] += 700; await cog.poll_once()
    assert not ops("send", n0), ops(None, n0)
    ok("Meldung vom Team gelöscht -> Update merkt es, keine Neu-Meldung")
    del f.live["matters86"]; clock[0] += 400; await cog.poll_once()

    # --- Posten scheitert (Rechte) -> später erneut versuchen ---------------------------------------
    ch.forbid.add("send")
    f.go_live("matters86", "s4")
    n0 = len(L.LOG)
    clock[0] += 60; await cog.poll_once()
    assert not ops("send", n0) and (await gc.state())["matters86"]["post_failed"]
    ch.forbid.discard("send")
    clock[0] += 601; await cog.poll_once()
    assert len(ops("send", n0)) == 1
    clock[0] += 601; await cog.poll_once()
    assert len(ops("send", n0)) == 1
    ok("Posten ohne Rechte scheitert -> nach Rechte-Fix genau 1 Nachmeldung")
    del f.live["matters86"]; clock[0] += 400; await cog.poll_once()

    # --- 401 -> Token-Refresh ------------------------------------------------------------------------
    f.tokens.clear()
    before = f.token_n
    await cog.poll_once()
    assert f.token_n == before + 1 and cog.status["state"] == "ok", (f.token_n, cog.status)
    f.fail = [(401, {}, None), (401, {}, None)]
    d = await cog.poll_once()
    assert cog.status["state"] == "auth_error" and d > 60, (cog.status, d)
    await cog.poll_once(); assert cog.status["state"] == "ok"
    ok("401 -> Token genau einmal erneuert; 2x 401 -> auth_error + Backoff; danach wieder ok")

    # --- 429 / 5xx / Netzwerk ---------------------------------------------------------------------------
    f.fail = [(429, {"Ratelimit-Reset": str(int(clock[0] + 200))}, None)]
    d = await cog.poll_once()
    assert cog.status["state"] == "rate_limited" and d >= 199, (cog.status, d)
    f.fail = [(503, {}, None)]
    d2 = await cog.poll_once()
    assert cog.status["state"] == "error" and d2 > d - 1 and d2 <= 900, d2
    from rc.twitchlive.api import TwitchError, TwitchAPI
    f.fail = [TwitchError("Netzwerkfehler (ClientConnectorError)")]
    await cog.poll_once(); assert cog.status["state"] == "error"
    await cog.poll_once(); assert cog.status["state"] == "ok" and cog._failures == 0
    ok("429 -> Pause bis Ratelimit-Reset; 5xx/Netzwerk -> Backoff (max 15 min); danach Reset")

    # echter aiohttp-Weg: nicht erreichbarer Port -> TwitchError ohne URL/Secret in der Meldung
    api = TwitchAPI(lambda: asyncio.sleep(0, (T.CLIENT_ID, T.SECRET)))
    import rc.twitchlive.api as apimod
    old = apimod.TOKEN_URL; apimod.TOKEN_URL = "http://127.0.0.1:9/oauth2/token"
    try:
        await api.get_token()
        raise AssertionError("kein Fehler")
    except TwitchError as exc:
        assert "Netzwerkfehler" in str(exc) and T.SECRET not in str(exc) and "127.0.0.1" not in str(exc), str(exc)
    finally:
        apimod.TOKEN_URL = old
        await api.close()
    assert api._session is None
    ok("echter aiohttp-Netzfehler -> TwitchError ohne URL/Secret; Session wird geschlossen")

    # --- Hintergrund-Schleife überlebt Fehler ---------------------------------------------------------
    async def fast():
        return 0.05
    cog._interval = fast
    import rc.twitchlive.twitchlive as tlm
    tlm_max = tlm.MAX_BACKOFF; tlm.MAX_BACKOFF = 0.2
    orig_pg = cog._process_guild
    boom = {"n": 0}

    async def flaky(guild, streams):
        if boom["n"] == 0:
            boom["n"] += 1
            raise RuntimeError("Absturz in einem Server")
        return await orig_pg(guild, streams)
    cog._process_guild = flaky
    orig_poll = cog.poll_once
    pc = {"n": 0}

    async def counting():
        pc["n"] += 1
        if pc["n"] == 2:
            raise ValueError("unerwartet")
        return await orig_poll()
    cog.poll_once = counting
    f.fail = [TwitchError("Netzwerkfehler (X)"), (429, {"Retry-After": "0"}, None), (500, {}, None)]
    import rc.twitchlive.twitchlive as tl
    tl_sleep = tl.asyncio.wait_for

    async def short_wait(aw, timeout):   # 300-s-Pause nach unerwartetem Fehler im Test verkürzen
        return await tl_sleep(aw, timeout=min(timeout, 0.1))
    tl.asyncio.wait_for = short_wait
    f.go_live("kaigaming", "k1")
    await cog.upsert_channel(g1, "kaigaming")
    n0 = len(L.LOG)
    cog._wake = asyncio.Event()
    task = asyncio.create_task(cog._runner())
    await asyncio.sleep(3.5)
    alive = not task.done()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    tl.asyncio.wait_for = tl_sleep
    tlm.MAX_BACKOFF = tlm_max
    cog.poll_once = orig_poll; cog._process_guild = orig_pg
    del cog._interval
    assert alive and pc["n"] >= 5, pc
    assert len([e for e in ops("send", n0) if "Kaigaming" in (e[2]["content"] or "")]) == 1, ops("send", n0)
    ok(f"Schleife: Netzfehler, 429, 500, Exception in poll und in einem Server überstanden ({pc['n']} Runden), 1 Meldung")

    # --- >100 Streamer gebündelt, dedupliziert ----------------------------------------------------------
    await gc.channels.set({f"user{i:03d}": {"channel_id": 1001, "enabled": True} for i in range(100)})
    await cog.config.guild(g2).channels.set({f"user{i:03d}": {"channel_id": 2001, "enabled": True}
                                             for i in range(50, 150)})
    await gc.state.set({}); await cog.config.guild(g2).state.set({})
    for i in (5, 75, 140):
        f.add_user(f"user{i:03d}")
        f.go_live(f"user{i:03d}", f"b{i}")
    f.calls.clear(); n0 = len(L.LOG)
    await cog.poll_once()
    sc = [c for c in f.calls if c[1] == "streams"]
    logins = [v for c in sc for k, v in c[2] if k == "user_login"]
    assert len(sc) == 2 and len(logins) == 150 and len(set(logins)) == 150, (len(sc), len(logins))
    assert all(len([1 for k, _ in c[2] if k == "user_login"]) <= 100 for c in sc)
    uc = [c for c in f.calls if c[1] == "users"]
    assert all(len(c[2]) <= 100 for c in uc) and len(uc) == 2, [len(c[2]) for c in uc]
    s = ops("send", n0)
    assert len(s) == 4, len(s)   # user005 (g1), user075 (g1+g2), user140 (g2)
    assert cog.status["watched"] == 200 and cog.status["live"] == 3
    f.calls.clear(); await cog.poll_once()
    assert not [c for c in f.calls if c[1] == "users"], "Nutzer-Cache (TTL) greift"
    ok("150 eindeutige Logins aus 2 Servern -> 2 gebündelte /streams-Anfragen (<=100), 4 Meldungen, Nutzer-Cache")
    await gc.channels.set({}); await cog.config.guild(g2).channels.set({})
    await gc.state.set({}); await cog.config.guild(g2).state.set({})
    f.live.clear()

    # --- Platzhalter & Limits ------------------------------------------------------------------------
    from rc.twitchlive.embed import render_template
    out = render_template("{streamer.__class__} {title} {game} {url} {unbekannt} {{streamer}}", streamer="A",
                          title="{game}", game="G", url="U", ping="")
    assert out == "{streamer.__class__} {game} G U {unbekannt} {A}", out
    assert render_template("x", streamer="", title="", game="", url="", ping="<@&5>") == "<@&5> x"
    await cog.upsert_channel(g1, "lenaplays", channel_id=1002, ping_role=1101,
                             message="{url} " * 300 + "{title}", verify=False)
    long_title = "T" * 300
    f.go_live("lenaplays", "L1", title=long_title, game="G" * 2000, viewers=10**9)
    n0 = len(L.LOG)
    await cog.poll_once()
    s = ops("send", n0)
    assert len(s) == 1, ops(None, n0)       # live_harness prüft Discord-Limits (sonst 400)
    m = g1.get_channel(1002)._messages[s[0][2]["message"]]
    assert len(m.content) <= 2000 and len(m.embeds[0].title) <= 256
    assert m.content.startswith("<@&1101> "), m.content[:30]
    ok("Platzhalter: nur {streamer}{title}{game}{url}{ping}, keine Format-Injection; Nachricht<=2000, Titel<=256, Feld<=1024")
    await cog.remove_channel(g1, "lenaplays"); f.live.clear()

    # --- Testmeldung ---------------------------------------------------------------------------------
    await cog.upsert_channel(g1, "kaigaming", ping_role=1104, verify=False)
    MENTIONS.clear(); n0 = len(L.LOG)
    msgt, cht = await cog.send_test(g1, "kaigaming")
    assert msgt is not None and cht.id == 1003 and "Testmeldung" in msgt.content
    am = MENTIONS[-1][1]
    assert not am.roles and not am.everyone and not am.users
    ok("Testmeldung: offline -> Beispieldaten, gepostet ohne echten Ping")

    # --- Befehle -------------------------------------------------------------------------------------
    owner = g1.get_member(1); lena = g1.get_member(11)
    ctx = Ctx(bot, g1, owner)
    await cog.tw_add.callback(cog, ctx, "https://www.twitch.tv/LenaPlays", g1.get_channel(1001), None)
    assert "wird beobachtet" in ctx.sent[-1], ctx.sent
    await cog.tw_add.callback(cog, ctx, "a!", None, None)
    assert "kein gültiger" in ctx.sent[-1]
    await cog.tw_role.callback(cog, ctx, "lenaplays", g1.get_role(1101))
    await cog.tw_message.callback(cog, ctx, "lenaplays", text="{streamer} ist da: {url}")
    await cog.tw_channel.callback(cog, ctx, "lenaplays", None)
    assert "Standardkanal" in ctx.sent[-1]
    await cog.tw_toggle.callback(cog, ctx, "lenaplays")
    e = (await gc.channels())["lenaplays"]
    assert e["ping_role"] == 1101 and e["message"].startswith("{streamer}") and e["channel_id"] is None and not e["enabled"], e
    await cog.tw_toggle.callback(cog, ctx, "lenaplays")
    await cog.tw_list.callback(cog, ctx)
    assert "lenaplays" in ctx.sent[-1] and "eigener Text" in ctx.sent[-1]
    await cog.tw_role.callback(cog, ctx, "niemand", None)
    assert "nicht beobachtet" in ctx.sent[-1]
    await cog.tw_test.callback(cog, ctx, "lenaplays")
    assert "gesendet" in ctx.sent[-1], ctx.sent[-1]
    # live und dann per Befehl entfernen -> Meldung wird beendet
    f.go_live("lenaplays", "L2"); n0 = len(L.LOG)
    await cog.poll_once()
    await cog.tw_remove.callback(cog, ctx, "lenaplays")
    assert ops("edit", n0) and "lenaplays" not in await gc.channels() and "lenaplays" not in await gc.state()
    ok("Befehle add/role/message/channel/toggle/list/test/remove (remove beendet laufende Meldung)")

    ctx = Ctx(bot, g1, owner)
    await cog.ts_creds.callback(cog, ctx, T.CLIENT_ID, T.SECRET)
    assert ctx.deleted and "erfolgreich" in ctx.sent[-1] and T.SECRET not in " ".join(ctx.sent), ctx.sent
    await cog.ts_creds.callback(cog, ctx, T.CLIENT_ID, "falsch")
    assert "fehlgeschlagen" in ctx.sent[-1] and "falsch" not in ctx.sent[-1]
    await cog.ts_creds.callback(cog, ctx, T.CLIENT_ID, T.SECRET)
    await cog.ts_show.callback(cog, ctx)
    assert T.SECRET not in ctx.sent[-1] and T.CLIENT_ID not in ctx.sent[-1] and "gesetzt: ja" in ctx.sent[-1]
    ok("[p]twitchset creds: Nachricht gelöscht, Token geprüft, Secret/ID nie ausgegeben")

    ctx = Ctx(bot, g1, lena)
    await cog.ts_liverole.callback(cog, ctx, g1.get_role(1102))   # Moderator über Lenas Rolle
    assert "nicht automatisch" in ctx.sent[-1] and await gc.live_role() is None
    ctx = Ctx(bot, g1, owner)
    await cog.ts_liverole.callback(cog, ctx, g1.get_role(1104))
    assert await gc.live_role() == 1104
    await cog.ts_endaction.callback(cog, ctx, "quatsch"); assert "Erlaubt" in ctx.sent[-1]
    await cog.ts_endaction.callback(cog, ctx, "delete"); assert await gc.end_action() == "delete"
    await cog.ts_interval.callback(cog, ctx, 5); assert "zwischen" in ctx.sent[-1]
    await cog.ts_language.callback(cog, ctx, "en"); assert await gc.language() == "en"
    await cog.ts_language.callback(cog, ctx, "de")
    await cog.ts_endaction.callback(cog, ctx, "edit")
    await cog.tw_link.callback(cog, ctx, lena, "LenaPlays")
    assert (await gc.links())["11"] == "lenaplays"
    ok("Live-Rolle: Selbst-Hochstufung blockiert, Owner darf; endaction/interval/language/link validiert")

    # --- Datenschutz ---------------------------------------------------------------------------------
    await cog.red_delete_data_for_user(requester="user", user_id=11)
    assert "11" not in await gc.links()
    ok("red_delete_data_for_user entfernt die Verknüpfung")

    # --- Dashboard -----------------------------------------------------------------------------------
    await wc.config.role_perms.set({"1000": {"1101": {"twitchlive": "edit"}, "1102": {"twitchlive": "view"}}})
    await gc.links.set({"11": "lenaplays"})
    client = TestClient(TestServer(app)); await client.start_server()
    O = {"X-Test-User": "1"}; LE = {"X-Test-User": "11"}; TO = {"X-Test-User": "12"}; KA = {"X-Test-User": "13"}
    f.add_user("evil", "<script>alert(1)</script>")
    r = await client.get("/cogs/twitchlive?guild=1000", headers=O); html = await r.text()
    assert r.status == 200 and T.SECRET not in html and T.CLIENT_ID not in html and "gesetzt" in html
    tok = csrf(html)

    async def post(headers, **data):
        r = await client.post("/cogs/twitchlive", headers=headers, allow_redirects=False,
                              data={"csrf_token": tok if headers is O else tokl, **data})
        from urllib.parse import unquote
        return unquote(r.headers.get("Location", ""))
    r = await client.get("/cogs/twitchlive?guild=1000", headers=LE); tokl = csrf(await r.text())

    loc = await post(O, action="add", guild="1000", login="https://twitch.tv/Evil", channel="1002",
                     ping_role="1101", message="<img src=x onerror=alert(1)> {streamer}", enabled="on")
    assert "evil hinzugefügt" in loc, loc
    loc = await post(O, action="add", guild="1000", login="gibtsnicht", channel="", enabled="on")
    assert "kennt keinen" in loc, loc
    loc = await post(O, action="add", guild="1000", login="x", channel="")
    assert "Ungültiger" in loc
    loc = await post(O, action="add", guild="1000", login="okname", channel="999999")
    assert "Kanal nicht gefunden" in loc
    loc = await post(O, action="add", guild="1000", login="evil", channel="1002", message="x" * 1501)
    assert "zu lang" in loc
    r = await client.get("/cogs/twitchlive?guild=1000&preview=evil", headers=O); html = await r.text()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    ok("Dashboard: hinzufügen (URL-Login, Twitch-Prüfung, Validierung), XSS escaped, keine Secrets im HTML")

    loc = await post(O, action="save", guild="1000", login="evil", channel="", ping_role="", message="", enabled="")
    e = (await gc.channels())["evil"]
    assert "gespeichert" in loc and e["channel_id"] is None and e["ping_role"] is None and not e["enabled"], (loc, e)
    loc = await post(O, action="toggle", guild="1000", login="evil"); assert "fortgesetzt" in loc
    n0 = len(L.LOG)
    loc = await post(O, action="test", guild="1000", login="evil"); assert "Testmeldung in #ankündigungen" in loc, loc
    assert len(ops("send", n0)) == 1
    loc = await post(O, action="settings", guild="1000", default_channel="1004", end_action="delete",
                     language="en", default_message="{streamer} live!")
    conf = await gc.all()
    assert conf["default_channel"] == 1004 and conf["end_action"] == "delete" and conf["language"] == "en"
    await post(O, action="settings", guild="1000", default_channel="1003", end_action="edit", language="de",
               default_message="")
    loc = await post(O, action="delete", guild="1000", login="evil"); assert "entfernt" in loc
    assert "evil" not in await gc.channels()
    ok("Dashboard: bearbeiten, pausieren/fortsetzen, Testmeldung, Einstellungen, entfernen")

    loc = await post(LE, action="liverole", guild="1000", live_role="1102")
    assert "nicht automatisch" in loc, loc
    loc = await post(LE, action="liverole", guild="1000", live_role="")
    assert "ausgeschaltet" in loc and await gc.live_role() is None
    loc = await post(LE, action="interval", guild="1000", interval="120")
    assert "Nur der Bot-Owner" in loc and await cog.config.poll_interval() == 60
    loc = await post(O, action="interval", guild="1000", interval="120")
    assert await cog.config.poll_interval() == 120
    await cog.config.poll_interval.set(60)
    loc = await post(LE, action="link", guild="1000", user="14", login="mia_art")
    assert (await gc.links())["14"] == "mia_art", loc
    loc = await post(LE, action="unlink", guild="1000", user="14"); assert "gelöst" in loc
    loc = await post(LE, action="add", guild="2000", login="kaigaming", channel="2001")
    assert "Bearbeitungsrechte" in loc or "nicht gefunden" in loc, loc
    assert "kaigaming" not in await cog.config.guild(g2).channels()
    ok("Rechte: Team-Bearbeiter (Lena) ohne Selbst-Hochstufung, ohne botweite Werte, nur eigener Server")

    r = await client.get("/cogs/twitchlive?guild=1000", headers=TO); th = await r.text()
    assert r.status == 200 and "ro-banner" in th and "Beobachtet (alle Server)" not in th
    tokt = csrf(th)
    r = await client.post("/cogs/twitchlive", headers=TO, allow_redirects=False,
                          data={"csrf_token": tokt, "action": "delete", "guild": "1000", "login": "kaigaming"})
    assert "kaigaming" in await gc.channels()
    r = await client.get("/cogs/twitchlive?guild=1000", headers=KA)
    assert r.status == 403
    ok("Nur-Ansicht (Tom): Seite schreibgeschützt, POST abgelehnt; ohne Rechte (Kai) 403")
    await client.close()

    # --- Aufräumen -----------------------------------------------------------------------------------
    import aiohttp
    cog._task = asyncio.create_task(asyncio.sleep(100))
    cog.api._session = aiohttp.ClientSession()
    sess = cog.api._session
    wc.register_page(owner=cog, slug="twitchlive", name="Twitch-Live", icon="bi-twitch", handler=cog.dashboard_page)
    await cog.cog_unload()
    await asyncio.sleep(0)
    assert sess.closed and cog._task.cancelled() and "twitchlive" not in wc.pages
    ok("cog_unload: Task abgebrochen, ClientSession geschlossen, Dashboard-Seite abgemeldet")

    print(f"\n{len(passed)} Testblöcke bestanden.")


asyncio.run(main())
