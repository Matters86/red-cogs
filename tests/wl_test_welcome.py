"""Funktionstests Welcome: Beitritt/Verlassen, Bild, DM, Befehle, Dashboard (echter WebCore)."""
import asyncio, io, re, types
import wl_harness as W
L = W.L
from aiohttp.test_utils import TestServer, TestClient
from PIL import Image


def csrf(html):
    return re.search(r"name='csrf_token' value='([^']+)'", html).group(1)


class Ctx:
    def __init__(self, guild, author, channel):
        self.guild = guild; self.author = author; self.channel = channel; self.clean_prefix = "!"
        self.sent = []
    async def send(self, content=None, **kw):
        self.sent.append((content, kw))
        return await self.channel.send(content, **{k: v for k, v in kw.items() if k in ("embed", "allowed_mentions", "file")})
    def typing(self):
        class T:
            async def __aenter__(s): pass
            async def __aexit__(s, *a): pass
        return T()


async def main():
    wc, bot, app = await W.make_app()
    cog = bot._cogs["Welcome"]
    g = bot.guilds[0]
    allg, sup, ann, logs = g.text_channels
    lena = g.get_member(11); kai = g.get_member(13)
    gconf = cog.config.guild(g)

    # Mitschnitt von allowed_mentions
    calls = []
    orig_send = L.FakeText.send
    async def spy(self, content=None, **kw):
        calls.append((self.id, content, kw))
        return await orig_send(self, content, **kw)
    L.FakeText.send = spy

    # 1) Standard: aus -> nichts
    await cog.on_member_join(kai)
    assert not calls
    # 2) Text-Willkommen
    await gconf.welcome_enabled.set(True); await gconf.welcome_channel.set(allg.id)
    await cog.on_member_join(kai)
    cid, content, kw = calls[-1]
    assert cid == allg.id and "<@13>" in content and "Matters Community" in content, content
    am = kw["allowed_mentions"]
    assert am.everyone is False and am.roles is False and [u.id for u in am.users] == [13], am
    print("Text-Willkommen OK:", content)
    # Ping aus -> users False
    await gconf.ping_user.set(False)
    await cog.on_member_join(kai)
    assert calls[-1][2]["allowed_mentions"].users is False
    await gconf.ping_user.set(True)
    # 3) Platzhalter + Injection-Schutz
    await gconf.welcome_text.set("Hi {name} ({user}) – {server} hat {count}, Konto {created} {x} {user.__class__} {0}")
    await cog.on_member_join(kai)
    c = calls[-1][1]
    assert c.startswith("Hi Kai (<@13>) – Matters Community hat 1055, Konto ") and "{x} {user.__class__} {0}" in c, c
    assert re.search(r"Konto \d+ Jahre", c), c
    print("Platzhalter OK:", c)
    # 4) Embed + Bild
    await gconf.welcome_mode.set("embed"); await gconf.welcome_title.set("Hallo {name}")
    await gconf.card_enabled.set(True)
    await cog.on_member_join(kai)
    cid, content, kw = calls[-1]
    emb = kw["embed"]; f = kw["file"]
    assert emb.title == "Hallo Kai" and emb.image.url == "attachment://welcome.png" and f.filename == "welcome.png"
    assert content == "<@13>"  # Ping als Inhalt, da Embed-Erwähnungen nicht pingen
    f.fp.seek(0); im = Image.open(f.fp); assert im.size == (1000, 400), im.size
    print("Embed + Willkommensbild OK", im.size)
    # ohne Datei-Recht -> ohne Bild
    orig_perm = L._SendMixin.permissions_for
    def no_attach(self, obj):
        p = orig_perm(self, obj); p.attach_files = False; return p
    L.FakeText.permissions_for = no_attach
    await cog.on_member_join(kai)
    assert "file" not in calls[-1][2] and calls[-1][2]["embed"].image.url is None
    L.FakeText.permissions_for = orig_perm
    print("Ohne 'Dateien anhängen' -> Nachricht ohne Bild OK")
    # 5) Bots ignorieren
    n = len(calls)
    kai.bot = True
    await cog.on_member_join(kai)
    assert len(calls) == n
    await gconf.ignore_bots.set(False)
    await cog.on_member_join(kai)
    assert len(calls) == n + 1
    kai.bot = False; await gconf.ignore_bots.set(True)
    print("Bots ignorieren OK")
    # 6) Abschied
    await gconf.leave_enabled.set(True); await gconf.leave_channel.set(logs.id)
    await cog.on_member_remove(lena)
    cid, content, kw = calls[-1]
    assert cid == logs.id and "Lena" in content and kw["allowed_mentions"].users is False, (cid, content)
    print("Abschied OK:", content)
    # 7) DM (geschlossen -> still)
    await gconf.dm_enabled.set(True); await gconf.dm_text.set("Willkommen {name} auf {server}")
    await cog.on_member_join(kai)
    assert W.SENT_DMS[-1][0] == 13 and W.SENT_DMS[-1][1] == "Willkommen Kai auf Matters Community", W.SENT_DMS[-1]
    kai.dm_closed = True
    n = len(W.SENT_DMS)
    await cog.on_member_join(kai)   # darf nicht werfen
    assert len(W.SENT_DMS) == n
    kai.dm_closed = False
    print("DM OK, geschlossene DMs still ignoriert")
    # 8) Kanal ohne Senderecht -> kein Crash, Fehler-Key
    allg.forbid = {"send"}
    ok, err = await cog.post(kai, "welcome")
    assert not ok and err == "err_no_send"
    allg.forbid = set()
    # Discord-Limits: sehr langer Name/Text
    await gconf.welcome_mode.set("text"); await gconf.welcome_text.set("{user} " * 400)
    ok, err = await cog.post(kai, "welcome"); assert ok, err
    assert len(calls[-1][1]) <= 2000
    await gconf.welcome_text.set("")
    print("Fehlerfälle/Limits OK")
    # 9) Hintergrund-URL: SSRF-Schutz
    from rc.welcome import card as cardmod
    for bad in ("https://127.0.0.1/x.png", "https://localhost/x.png", "https://10.0.0.5/a.png", "http://example.com/a.png",
                "https://example.com:8443/a.png"):
        try:
            await cog.background_bytes(bad); raise AssertionError(bad)
        except cardmod.BackgroundError as e:
            print("  abgelehnt:", bad, "->", e)
    # Bild mit ungültiger URL -> Farbverlauf + Hinweis
    conf = await gconf.all(); conf["card_bg_url"] = "https://127.0.0.1/x.png"
    png, err = await cog.render_card(kai, conf); assert png[:4] == b"\x89PNG" and "intern" in err, err
    # prepare_background: Größe/Format
    buf = io.BytesIO(); Image.new("RGB", (1600, 900), (200, 20, 20)).save(buf, "JPEG")
    out = cardmod.prepare_background(buf.getvalue()); assert Image.open(io.BytesIO(out)).size == (1000, 400)
    for data, why in ((b"nope", "kein"), (b"", "leer")):
        try:
            cardmod.prepare_background(data); raise AssertionError
        except cardmod.BackgroundError as e:
            assert why in str(e), e
    # Download-Pfad gemockt (Cache + Bild)
    async def fake_dl(url): return buf.getvalue()
    real_dl = cog._download; cog._download = fake_dl
    b1 = await cog.background_bytes("https://example.com/bg.jpg"); b2 = await cog.background_bytes("https://example.com/bg.jpg")
    assert b1 is b2
    cog._download = real_dl
    print("Hintergrundbild (SSRF-Schutz, Prüfung, Cache) OK")
    # Avatar: Timeout -> kein Absturz
    class SlowAsset:
        key = "slow"; url = "https://x"
        async def read(self): await asyncio.sleep(30)
    import rc.welcome.welcome as wm
    wm.AVATAR_TIMEOUT = 0.2
    slow = types.SimpleNamespace(id=77, display_avatar=SlowAsset())
    assert await cog.avatar_bytes(slow) is None
    print("Avatar-Timeout OK")

    # 10) Befehle
    ctx = Ctx(g, lena, sup)
    await cog.ws_test.callback(cog, ctx, "welcome")
    assert ctx.sent and "Test" in ctx.sent[0][0]
    assert calls[-1][0] == sup.id and calls[-1][2]["allowed_mentions"].users is False
    await cog.ws_test.callback(cog, ctx, "dm")
    assert W.SENT_DMS[-1][0] == 11 and "Test-DM" in ctx.sent[-1][0]
    await cog.ws_color.callback(cog, ctx, "leave", "zzz"); assert "Ungültige Farbe" in ctx.sent[-1][0]
    await cog.ws_color.callback(cog, ctx, "leave", "ff0000"); assert await gconf.leave_color() == "#ff0000"
    await cog.ws_image.callback(cog, ctx, "welcome", "javascript:alert(1)"); assert "Ungültige" in ctx.sent[-1][0]
    await cog.ws_toggle.callback(cog, ctx, "leave", None); assert await gconf.leave_enabled() is False
    await cog.ws_channel.callback(cog, ctx, "leave", None); assert await gconf.leave_channel() is None
    await cog.ws_toggle.callback(cog, ctx, "leave", True); assert "setze noch einen Kanal" in ctx.sent[-1][0]
    await cog.ws_message.callback(cog, ctx, "welcome", text="x" * 2001); assert "zu lang" in ctx.sent[-1][0]
    await cog.ws_settings.callback(cog, ctx)
    await cog.ws_language.callback(cog, ctx, "en"); await cog.ws_language.callback(cog, ctx, "fr")
    assert "Unknown language" in ctx.sent[-1][0]
    await cog.ws_language.callback(cog, ctx, "de")
    print("Befehle OK")

    # 11) Dashboard
    client = TestClient(TestServer(app)); await client.start_server()
    owner = {"X-Test-User": "1"}; lena_h = {"X-Test-User": "11"}; tom_h = {"X-Test-User": "12"}; kai_h = {"X-Test-User": "13"}
    r = await client.get("/cogs/welcome?guild=1000", headers=owner); t = await r.text()
    assert r.status == 200 and "Testnachricht posten" in t and "wl-card-preview" in t, r.status
    for tab in ("Willkommen", "Abschied", "DM", "Bild"):
        assert f"data-title='{tab}'" in t, tab
    tok = csrf(t)
    # Speichern Willkommen
    r = await client.post("/cogs/welcome", headers=owner, allow_redirects=False, data={
        "csrf_token": tok, "form": "welcome", "guild": "1000", "enabled": "on", "channel": str(ann.id),
        "mode": "embed", "text": "Servus {user} <b>x</b>", "title": "T", "color": "#112233", "image": "",
        "ping_user": "on", "language": "de"})
    assert r.status == 302 and "ok=" in r.headers["Location"], r.headers.get("Location")
    c = await gconf.all()
    assert c["welcome_channel"] == ann.id and c["welcome_mode"] == "embed" and c["welcome_color"] == "#112233"
    assert c["ignore_bots"] is False and c["ping_user"] is True
    # ungültige Eingaben
    for bad, msg in (({"channel": "123"}, "Kanal"), ({"color": "red"}, "Farbe"), ({"image": "http://x.y/a.png"}, "Bild-URL"),
                     ({"mode": "xx"}, "Darstellung"), ({"text": "a" * 2001}, "zu+lang")):
        d = {"csrf_token": tok, "form": "welcome", "guild": "1000", "channel": str(ann.id), "mode": "text", "color": "#112233"}
        d.update(bad)
        r = await client.post("/cogs/welcome", headers=owner, allow_redirects=False, data=d)
        assert "err=" in r.headers["Location"] and msg in r.headers["Location"], (bad, r.headers["Location"])
    assert (await gconf.welcome_channel()) == ann.id  # nichts überschrieben
    # Test-Knopf: Willkommen -> postet in #ankündigungen mit Owner als Beispiel
    n = len(calls)
    r = await client.post("/cogs/welcome", headers=owner, allow_redirects=False, data={
        "csrf_token": tok, "form": "welcome", "guild": "1000", "enabled": "on", "channel": str(ann.id), "mode": "text",
        "text": "Test {name}", "color": "#112233", "language": "de", "ping_user": "on", "ignore_bots": "on", "do": "test"})
    assert "Testnachricht" in r.headers["Location"], r.headers["Location"]
    assert len(calls) == n + 1 and calls[-1][0] == ann.id and calls[-1][1].startswith("Test Matters86"), calls[-1][1]
    assert calls[-1][2]["allowed_mentions"].users is False
    # DM-Test
    r = await client.post("/cogs/welcome", headers=owner, allow_redirects=False, data={
        "csrf_token": tok, "form": "dm", "guild": "1000", "enabled": "on", "mode": "text", "text": "", "color": "#3ddc97",
        "do": "test"})
    assert "Test-DM+gesendet" in r.headers["Location"] and W.SENT_DMS[-1][0] == 1, r.headers["Location"]
    # Bild speichern + Test
    r = await client.post("/cogs/welcome", headers=owner, allow_redirects=False, data={
        "csrf_token": tok, "form": "card", "guild": "1000", "card_enabled": "on", "card_bg_color": "#000000",
        "card_accent": "#ff00ff", "card_text_color": "#ffffff", "card_headline": "Hallo", "card_bg_url": "", "do": "test"})
    assert "Testnachricht" in r.headers["Location"] and calls[-1][2].get("file") is not None, r.headers["Location"]
    assert (await gconf.card_accent()) == "#ff00ff" and (await gconf.card_headline()) == "Hallo"
    print("Dashboard-Formulare + Test-Knöpfe OK")
    # Vorschau
    r = await client.get("/cogs/welcome?guild=1000&preview=card&bg=%23ff0000&accent=%2300ff00&headline=Neu", headers=owner)
    body = await r.read()
    assert r.status == 200 and r.headers["Content-Type"] == "image/png"
    im = Image.open(io.BytesIO(body)).convert("RGB"); px = im.getpixel((2, 2))
    assert px[2] < 30 and px[0] > 40, px   # Rot/Grün-Verlauf ohne Blau (Live-Werte übernommen)
    r = await client.get("/cogs/welcome?guild=1000&preview=card&url=https%3A%2F%2F127.0.0.1%2Fa.png", headers=owner)
    assert "X-Bg-Error" in r.headers, dict(r.headers)
    # Tom (nur Ansehen): Seite ja, Live-Werte ignoriert, POST abgelehnt
    r = await client.get("/cogs/welcome?guild=1000", headers=tom_h); t = await r.text()
    assert r.status == 200 and "<script>(function(){var f=document.getElementById('wl-card-form')" not in t
    r = await client.get("/cogs/welcome?guild=1000&preview=card&bg=%23ff0000&url=https%3A%2F%2F127.0.0.1%2Fa.png", headers=tom_h)
    im = Image.open(io.BytesIO(await r.read())).convert("RGB"); px = im.getpixel((2, 2))
    assert px[2] > 30, px   # gespeicherter Verlauf schwarz->magenta, nicht die Live-Werte
    assert "X-Bg-Error" not in r.headers
    await gconf.leave_enabled.set(False)
    r = await client.post("/cogs/welcome", headers=tom_h, allow_redirects=False, data={
        "csrf_token": csrf(t), "form": "leave", "guild": "1000", "enabled": "on", "mode": "text", "color": "#000000"})
    assert "Keine+Bearbeitungsrechte" in r.headers["Location"] and not await gconf.leave_enabled(), r.headers["Location"]
    # Lena (Bearbeiten) darf speichern, fremder Server 2000 nicht
    r = await client.get("/cogs/welcome?guild=1000", headers=lena_h); t = await r.text(); tk = csrf(t)
    r = await client.post("/cogs/welcome", headers=lena_h, allow_redirects=False, data={
        "csrf_token": tk, "form": "leave", "guild": "1000", "enabled": "on", "channel": str(logs.id), "mode": "text", "color": "#000000"})
    assert "ok=" in r.headers["Location"] and await gconf.leave_enabled()
    r = await client.post("/cogs/welcome", headers=lena_h, allow_redirects=False, data={
        "csrf_token": tk, "form": "leave", "guild": "2000", "enabled": "on", "mode": "text", "color": "#000000"})
    assert "Keine" in r.headers["Location"] or "nicht+gefunden" in r.headers["Location"], r.headers["Location"]
    # Kai: kein Zugriff
    r = await client.get("/cogs/welcome?guild=1000", headers=kai_h)
    assert r.status in (302, 403), r.status
    r = await client.get("/cogs/welcome?guild=1000&preview=card", headers=kai_h, allow_redirects=False)
    assert r.status in (302, 403), r.status
    # XSS: Text mit HTML wird escaped
    await gconf.welcome_text.set("<script>alert(1)</script>")
    r = await client.get("/cogs/welcome?guild=1000", headers=owner); t = await r.text()
    assert "<script>alert(1)</script>" not in t and "&lt;script&gt;alert(1)" in t
    print("Rechte (Owner/Bearbeiten/Ansehen/kein Zugriff), Vorschau, XSS OK")
    await client.close()
    await cog.cog_unload()
    print("ALLE WELCOME-TESTS OK")

asyncio.run(main())
