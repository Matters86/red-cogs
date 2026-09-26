"""Rechte-Stufe „Bedienen“ (operate_forms) in raidhelper, poll, giveaways, scheduler, twitchlive, organigram –
sowie autoroom, onlyimagevideo, commands, example ohne Tagesgeschäft.

Pro Cog mit einem Nutzer, der auf der Seite nur „Bedienen“ hat (Lena, Rolle Support 1101):
* Seite rendert mit Bedienen-Banner, ``data-operate-forms`` passt, keine Fehlerseite
* Tagesgeschäft-POSTs laufen durch und wirken (Event/Umfrage/Gewinnspiel/Eintrag/Testmeldung/Posten)
* Einstellungs-POSTs werden zentral abgelehnt (Toast „Dafür brauchst du das Recht Bearbeiten“), Config unverändert
Dazu: „Ansehen“ (Tom) darf nichts, „Bearbeiten“ (Mia) weiterhin Einstellungen, Seiten ohne Tagesgeschäft
wirken bei „Bedienen“ wie „Ansehen“, Registrierung auch mit älterer WebCore ohne ``operate_forms``.
Optional (Playwright): JS-Sperre je Formular im Browser, keine JS-Fehler.
"""
import asyncio
import re
from datetime import datetime, timedelta
from urllib.parse import unquote_plus
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer

import gv_harness as G      # live_harness + wcm_harness + Giveaways (add_view/send-Aufzeichnung)
import sc_harness as S      # noqa: F401 – Sende-Aufzeichnung/Fehler-Simulation für den Scheduler
import tw_harness as T
import live_harness as L

nr = {"allow_redirects": False}
OWNER = {"X-Test-User": "1"}
LENA = {"X-Test-User": "11"}   # Support 1101 -> Bedienen
TOM = {"X-Test-User": "12"}    # Moderator 1102 -> Ansehen
MIA = {"X-Test-User": "14"}    # Support 1101 + Raidleitung 1103 -> Bearbeiten
TOAST_EDIT = "Dafür brauchst du das Recht Bearbeiten"
NO_RIGHTS = "Keine Bearbeitungsrechte"

OPERATE = {  # slug -> erwartete operate_forms
    "raidhelper": {"create", "edit", "action"},
    "poll": {"create", "action"},
    "giveaways": {"create", "action"},
    "scheduler": {"entry", "action"},
    "twitchlive": {"test", "toggle"},
    "organigram": {"post"},
}
NO_OPERATE = ("autoroom", "onlyimagevideo", "commands", "example")


def csrf(text):
    return re.search(r"name='csrf_token' value='([^']+)'", text).group(1)


async def make_app():
    """Echter WebCore + alle zehn Cogs (Live-Kanäle, Giveaways/Scheduler/TwitchLive dazu)."""
    wc, bot, app, gcog = await G.make_app()
    from rc.scheduler.scheduler import Scheduler
    scog = Scheduler(bot)
    bot._cogs["Scheduler"] = scog
    await scog.cog_load()
    scog._tick.cancel()
    T.install_role_ops(bot)
    tcog = await T.make_cog(bot, wc)
    for login, name in (("matters86", "Matters86"), ("lenaplays", "LenaPlays")):
        tcog.fake.add_user(login, name)
    await tcog.config.client_id.set(T.CLIENT_ID)
    await tcog.config.client_secret.set(T.SECRET)
    g1 = bot.get_guild(1000)
    await tcog.config.guild(g1).default_channel.set(1003)
    await tcog.upsert_channel(g1, "matters86", ping_role=1104)
    await tcog.upsert_channel(g1, "lenaplays", channel_id=1001)
    perms = {s: "operate" for s in (*OPERATE, *NO_OPERATE)}
    await wc.config.role_perms.set({"1000": {"1101": dict(perms),
                                             "1102": {s: "view" for s in perms},
                                             "1103": {s: "edit" for s in perms}}})
    return wc, bot, app, {"giveaways": gcog, "scheduler": scog, "twitchlive": tcog}


async def main():
    wc, bot, app, cogs = await make_app()
    g1 = bot.get_guild(1000)
    client = TestClient(TestServer(app))
    await client.start_server()

    async def page(slug, headers, query=""):
        r = await client.get(f"/cogs/{slug}?guild=1000{query}", headers=headers)
        t = await r.text()
        assert r.status == 200, (slug, r.status, t[:500])
        assert "Traceback" not in t, (slug, t[:800])
        return t

    tokens = {}

    async def post(slug, headers=LENA, **fields):
        key = headers["X-Test-User"]
        if key not in tokens:
            tokens[key] = csrf(await page("example", headers))
        fields.setdefault("guild", "1000")
        r = await client.post(f"/cogs/{slug}", headers=headers, data={"csrf_token": tokens[key], **fields}, **nr)
        assert r.status == 302, (slug, fields, r.status, (await r.text())[:500])
        return unquote_plus(r.headers.get("Location", ""))

    async def denied(slug, **fields):
        before = len(await wc.config.audit())
        loc = await post(slug, **fields)
        assert f"err={TOAST_EDIT}" in loc and "guild=1000" in loc, (slug, fields, loc)
        au = (await wc.config.audit())[0]
        assert len(await wc.config.audit()) == before + 1 and au["ok"] is False and au["page"] == slug, au
        assert "Bedienen" in au["result"], au
        return loc

    # ------------------------------------------------------------ Registrierung
    for slug, forms in OPERATE.items():
        p = wc.pages[slug]
        assert p.supports_operate and set(p.operate_forms) == forms, (slug, p.operate_forms)
    for slug in NO_OPERATE:
        assert not wc.pages[slug].supports_operate, slug

    class OldWebCore:
        """WebCore vor „Bedienen“: register_page ohne operate_forms, keine Stufen-Konstanten."""
        def __init__(self):
            self.pages = {}

        def register_page(self, owner, slug, name, handler, icon="bi-grid"):
            self.pages[slug] = name
    old = OldWebCore()
    for name in ("RaidHelper", "Poll", "Giveaways", "Scheduler", "TwitchLive", "Organigram", "AutoRoom",
                 "OnlyImageVideo", "Commands", "Example"):
        bot._cogs[name]._register_dashboard(old)
    assert set(old.pages) == set(OPERATE) | set(NO_OPERATE), old.pages
    print("Registrierung: operate_forms je Cog, vier Seiten ohne Tagesgeschäft, ältere WebCore ohne operate_forms – OK")

    # ------------------------------------------------------------ Oberfläche (Bedienen / Ansehen / Bearbeiten)
    for slug, forms in OPERATE.items():
        t = await page(slug, LENA)
        assert 'data-operate="1"' in t and f'data-operate-forms="{",".join(sorted(forms))}"' in t, (slug, t[:1500])
        assert "op-banner" in t and "Nur Ansicht." not in t, slug
        nav = re.search(rf'href="/cogs/{slug}">(.*?)</a>', t, re.S).group(1)
        assert "Bedienen" in nav, (slug, nav)
        t = await page(slug, TOM)
        assert 'data-readonly="1"' in t and "data-operate" not in t, slug
        t = await page(slug, MIA)
        assert 'data-readonly="0"' in t and "op-banner" not in t, slug
    for slug in NO_OPERATE:
        t = await page(slug, LENA)
        assert 'data-readonly="1"' in t and "data-operate" not in t and "Nur Ansicht." in t, slug
    print("Oberfläche: Bedienen-Banner + data-operate-forms je Cog, Ansehen/Bearbeiten unverändert, "
          "ohne Tagesgeschäft = Nur Ansicht – OK")

    # ------------------------------------------------------------ raidhelper
    rh = bot._cogs["RaidHelper"]
    rconf = rh.config.guild(g1)
    lang0 = await rconf.language()
    when = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(days=2)
    d = when.strftime("%Y-%m-%d")
    L.LOG.clear()
    loc = await post("raidhelper", form="create", title="Bedienen-Raid", description="", game="wow_classic",
                     channel="1001", date=d, time="20:30", deadline_date="", deadline_time="", recurrence="none",
                     max_signups="", limit_tank="", limit_healer="", limit_mdps="", limit_rdps="")
    assert "ok=" in loc, loc
    events = await rconf.events()
    eid, ev = next((k, v) for k, v in events.items() if v["title"] == "Bedienen-Raid")
    assert ev["leader_id"] == 11 and ev.get("message_id") and any(op == "send" for op, *_ in L.LOG), ev
    loc = await post("raidhelper", form="edit", event_id=eid, title="Bedienen-Raid 2", description="neu",
                     date=d, time="20:30", deadline_date="", deadline_time="", recurrence="none", max_signups="10")
    assert "ok=" in loc and (await rconf.events())[eid]["title"] == "Bedienen-Raid 2", loc
    loc = await post("raidhelper", form="action", event_id=eid, action="close")
    assert "ok=Aktualisiert" in loc and (await rconf.events())[eid]["closed"] is True, loc
    loc = await post("raidhelper", form="action", event_id=eid, action="reopen")
    assert (await rconf.events())[eid]["closed"] is False, loc
    async with rconf.events() as evs:
        evs[eid]["message_id"] = None          # Nachricht „verloren“ -> neu posten
    loc = await post("raidhelper", form="action", event_id=eid, action="repost")
    assert "neu gepostet" in loc and (await rconf.events())[eid]["message_id"], loc
    t = await page("raidhelper", LENA)
    assert "Bedienen-Raid 2" in t
    t = await page("raidhelper", LENA, f"&edit={eid}")
    assert "name='form' value='edit'" in t, "Bearbeiten-Ansicht rendert"
    await denied("raidhelper", form="settings", language="en", timezone="UTC", cleanup_days="5")
    await denied("raidhelper", form="icons")
    assert await rconf.language() == lang0 and await rconf.timezone() == "Europe/Berlin"
    assert await rconf.cleanup_days() != 5 and not await rconf.public_api()
    # Mischwerte (Tagesgeschäft + Einstellungen in einem POST) -> abgelehnt
    r = await client.post("/cogs/raidhelper", headers=LENA, **nr,
                          data=[("csrf_token", tokens["11"]), ("guild", "1000"), ("form", "action"),
                                ("form", "settings"), ("public_api", "on")])
    assert TOAST_EDIT in unquote_plus(r.headers["Location"]) and not await rconf.public_api()
    loc = await post("raidhelper", form="action", event_id=eid, action="delete")
    assert "ok=Gel" in loc and eid not in await rconf.events(), loc
    # Ansehen: auch Tagesgeschäft abgelehnt; Bearbeiten: Einstellungen erlaubt
    loc = await post("raidhelper", TOM, form="create", title="x", channel="1001", date=d, time="20:00")
    assert NO_RIGHTS in loc, loc
    loc = await post("raidhelper", MIA, form="settings", language="en", default_game="wow_classic",
                     signup_channel="", timezone="Europe/Berlin", cleanup_days="30")
    assert "ok=Gespeichert" in loc and await rconf.language() == "en", loc
    await rconf.language.set(lang0)
    print("raidhelper: Bedienen legt an, bearbeitet, schließt/öffnet, postet neu, löscht; Einstellungen/Icons/"
          "Mischwerte abgelehnt; Ansehen nichts, Bearbeiten Einstellungen – OK")

    # ------------------------------------------------------------ poll
    pl = bot._cogs["Poll"]
    pconf = pl.config.guild(g1)
    loc = await post("poll", form="create", question="Bedienen?", options="Ja\nNein", channel="1001", duration="")
    assert "ok=Umfrage erstellt" in loc, loc
    pid, p = next((k, v) for k, v in (await pconf.polls()).items() if v["question"] == "Bedienen?")
    assert p.get("message_id"), p
    loc = await post("poll", form="action", poll_id=pid, action="close")
    assert "ok=Aktualisiert" in loc and (await pconf.polls())[pid]["closed"] is True
    loc = await post("poll", form="action", poll_id=pid, action="reopen")
    assert (await pconf.polls())[pid]["closed"] is False
    mgr0 = await pconf.manager_roles()
    await denied("poll", form="settings", language="en", allow_create="everyone", manager_roles="1101")
    assert await pconf.manager_roles() == mgr0 and await pconf.allow_create() == "manager"
    loc = await post("poll", form="action", poll_id=pid, action="delete")
    assert "ok=Gelöscht" in loc and pid not in await pconf.polls(), loc
    loc = await post("poll", TOM, form="action", poll_id=pid, action="close")
    assert NO_RIGHTS in loc
    print("poll: Bedienen legt an, schließt/öffnet, löscht; Einstellungen/Manager-Rollen abgelehnt – OK")

    # ------------------------------------------------------------ giveaways
    gcog = cogs["giveaways"]
    gconf = gcog.config.guild(g1)
    loc = await post("giveaways", form="create", prize="Bedienen-Preis", description="", channel="1001",
                     winners="1", duration="2h", min_days="0")
    assert "ok=Gewinnspiel gestartet" in loc, loc
    gid, gw = next((k, v) for k, v in (await gconf.giveaways()).items() if v["prize"] == "Bedienen-Preis")
    assert gw["status"] == "running" and gw["host_id"] == 11, gw
    for uid in (11, 12, 14):
        await gcog.join(g1, g1.get_member(uid), gid)
    loc = await post("giveaways", form="action", gw=gid, action="end")
    assert "ok=" in loc and (await gconf.giveaways())[gid]["status"] == "ended", loc
    loc = await post("giveaways", form="action", gw=gid, action="reroll")
    assert "ok=" in loc, loc
    loc = await post("giveaways", form="create", prize="Abbruch-Preis", channel="1001", winners="1", duration="1h")
    gid2 = next(k for k, v in (await gconf.giveaways()).items() if v["prize"] == "Abbruch-Preis")
    loc = await post("giveaways", form="action", gw=gid2, action="cancel")
    assert "ok=" in loc and (await gconf.giveaways())[gid2]["status"] == "cancelled", loc
    loc = await post("giveaways", form="action", gw=gid2, action="delete")
    assert "ok=Eintrag entfernt" in loc and gid2 not in await gconf.giveaways(), loc
    await denied("giveaways", form="settings", language="en", timezone="UTC", color="#000000", keep_days="1",
                 manager_roles="1101")
    assert await gconf.manager_roles() == [] and await gconf.timezone() in (None, "Europe/Berlin")
    t = await page("giveaways", LENA, f"&gw={gid}")
    assert "Bedienen-Preis" in t
    print("giveaways: Bedienen startet, beendet, lost neu aus, bricht ab, entfernt; Einstellungen/Manager-Rollen "
          "abgelehnt – OK")

    # ------------------------------------------------------------ scheduler
    scog = cogs["scheduler"]
    sconf = scog.config.guild(g1)
    entry = dict(form="entry", name="Bedienen-Gruß", channel="1001", content="Hallo Team", ping_role="1103",
                 type="daily", time="09:00")
    loc = await post("scheduler", action="preview", **entry)
    assert "preview=1" in loc and not await sconf.entries(), loc
    loc = await post("scheduler", action="save", **entry)
    assert "ok=Nachricht geplant" in loc, loc
    seid, se = next(iter((await sconf.entries()).items()))
    assert se["name"] == "Bedienen-Gruß" and se.get("ping_role_id") == 1103, se
    loc = await post("scheduler", action="save", eid=seid, **{**entry, "content": "Hallo Team 2"})
    assert "ok=Gespeichert" in loc and (await sconf.entries())[seid]["content"] == "Hallo Team 2", loc
    n = len(S.SENT)
    loc = await post("scheduler", form="action", eid=seid, action="test")
    assert "ok=Testnachricht gesendet" in loc and len(S.SENT) == n + 1, loc
    loc = await post("scheduler", form="action", eid=seid, action="pause")
    assert (await sconf.entries())[seid]["paused"] is True, loc
    loc = await post("scheduler", form="action", eid=seid, action="resume")
    assert not (await sconf.entries())[seid]["paused"], loc
    tz0 = await sconf.timezone()
    await denied("scheduler", form="settings", timezone="UTC", language="en")
    assert await sconf.timezone() == tz0
    t = await page("scheduler", LENA, f"&edit={seid}")
    assert "Bedienen-Gruß" in t
    loc = await post("scheduler", form="action", eid=seid, action="delete")
    assert "ok=Gelöscht" in loc and not await sconf.entries(), loc
    print("scheduler: Bedienen plant (Vorschau/Speichern), bearbeitet, testet, pausiert/setzt fort, löscht; "
          "Zeitzone/Sprache abgelehnt – OK")

    # ------------------------------------------------------------ twitchlive
    tcog = cogs["twitchlive"]
    tconf = tcog.config.guild(g1)
    loc = await post("twitchlive", action="test", login="lenaplays")
    assert "ok=Testmeldung in #allgemein gepostet" in loc, loc
    loc = await post("twitchlive", action="toggle", login="lenaplays")
    assert "pausiert" in loc and (await tconf.channels())["lenaplays"]["enabled"] is False, loc
    loc = await post("twitchlive", action="toggle", login="lenaplays")
    assert "fortgesetzt" in loc and (await tconf.channels())["lenaplays"]["enabled"] is True, loc
    chans0 = await tconf.channels()
    await denied("twitchlive", action="add", login="neuerstreamer", channel="1001", enabled="on")
    await denied("twitchlive", action="save", login="lenaplays", channel="1002", enabled="on")
    await denied("twitchlive", action="delete", login="lenaplays")
    await denied("twitchlive", action="settings", default_channel="1001", end_action="delete", language="en")
    await denied("twitchlive", action="liverole", live_role="1104")
    await denied("twitchlive", action="link", user="11", login="lenaplays")
    await denied("twitchlive", action="public_api", public_api="on")
    assert await tconf.channels() == chans0 and await tconf.live_role() is None and not await tconf.public_api()
    assert await tconf.default_channel() == 1003 and not await tconf.links()
    loc = await post("twitchlive", TOM, action="test", login="lenaplays")
    assert NO_RIGHTS in loc
    t = await page("twitchlive", LENA)
    assert T.SECRET not in t
    print("twitchlive: Bedienen postet Testmeldung, pausiert/setzt fort; Streamer/Einstellungen/Live-Rolle/"
          "Verknüpfung/API abgelehnt – OK")

    # ------------------------------------------------------------ organigram
    og = bot._cogs["Organigram"]
    oconf = og.config.guild(g1)
    loc = await post("organigram", OWNER, form="chart_new", name="Team", title="Unser Team", pattern="baum",
                     mode="text", accent="#3ddc97")
    cid = re.search(r"chart=([0-9a-f]+)", loc).group(1)
    await post("organigram", OWNER, form="node_save", chart=cid, label="Leitung", role_id="1102")
    t = await page("organigram", LENA, f"&chart={cid}")
    assert "name='form' value='post'" in t
    loc = await post("organigram", form="post", chart=cid, channel="1003", mode="text")
    assert "ok=Gepostet" in loc and len((await oconf.charts())[cid]["posts"]) == 1, loc
    loc = await post("organigram", form="post", chart=cid, channel="1003", mode="text")
    assert "ok=Gepostet" in loc and len((await oconf.charts())[cid]["posts"]) == 1, "Aktualisieren statt neu"
    charts0 = await oconf.charts()
    await denied("organigram", form="chart_new", name="Fremd")
    await denied("organigram", form="chart_settings", chart=cid, name="Umbenannt", pattern="liste")
    await denied("organigram", form="node_save", chart=cid, label="Chef", role_id="1101")
    await denied("organigram", form="node_delete", chart=cid, node=next(iter(charts0[cid]["nodes"])))
    await denied("organigram", form="chart_delete", chart=cid)
    assert await oconf.charts() == charts0
    print("organigram: Bedienen postet/aktualisiert; Organigramme/Einstellungen/Positionen abgelehnt – OK")

    # ------------------------------------------------------------ Seiten ohne Tagesgeschäft
    ar = bot._cogs["AutoRoom"]
    await denied("autoroom", action="access", guild_id="1000", admin_access="on", mod_access="on")
    await denied("autoroom", action="add", guild_id="1000", channel_id="1050")
    assert not await ar.config.guild(g1).mod_access() and not await ar.config.guild(g1).sources()
    oiv = bot._cogs["OnlyImageVideo"]
    ch0 = await oiv.config.guild(g1).channels()
    await denied("onlyimagevideo", form="settings", channels="1001")
    assert await oiv.config.guild(g1).channels() == ch0
    await denied("commands", action="hide", kind="cog", value="Poll")
    await denied("example", note="Bedienen-Notiz")
    assert await bot._cogs["Example"].config.guild(g1).note() == ""
    loc = await post("example", MIA, note="Bearbeiten-Notiz")
    assert "ok=Notiz gespeichert" in loc and await bot._cogs["Example"].config.guild(g1).note() == "Bearbeiten-Notiz"
    print("autoroom, onlyimagevideo, commands, example: Bedienen = Ansehen (jeder POST abgelehnt), Bearbeiten "
          "speichert – OK")

    await js_check(client, {"organigram": f"&chart={cid}"})
    await client.close()
    print("ALLE BEDIENEN-TESTS (opb) OK")


async def js_check(client, extra_query):
    """Im Browser: bei „Bedienen“ nur Tagesgeschäft-Formulare benutzbar, Einstellungen gesperrt, keine JS-Fehler."""
    try:
        from playwright.async_api import async_playwright
    except Exception:  # noqa: BLE001
        print("JS-Sperre: Playwright nicht installiert – übersprungen")
        return
    base = str(client.make_url("/")).rstrip("/")

    async def route(r):
        if r.request.url.startswith(base):
            return await r.continue_()
        return await r.abort()
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            print(f"JS-Sperre: Chromium nicht startbar ({type(exc).__name__}) – übersprungen")
            return
        errors = []
        ctx = await browser.new_context(extra_http_headers=LENA)
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.route("**/*", route)
        state_js = """() => Array.from(document.querySelectorAll('#wc-content form[method=post]')).map(f => {
            const v = n => { const e = Array.from(f.elements).find(x => x.name === n && x.type === 'hidden');
                             return e ? e.value : ''; };
            return {form: v('form'), action: v('action'), locked: f.getAttribute('data-wc-locked') === '1'};
        })"""
        for slug, forms in OPERATE.items():
            await pg.goto(f"{base}/cogs/{slug}?guild=1000{extra_query.get(slug, '')}")
            states = await pg.evaluate(state_js)
            assert states, slug
            for s in states:
                key = s["form"] or s["action"]
                assert s["locked"] == (key not in forms), (slug, s)
            assert any(not s["locked"] for s in states) and any(s["locked"] for s in states), (slug, states)
        await ctx.close()
        await browser.close()
        assert not errors, errors
    print("JS-Sperre (Chromium): je Cog nur Tagesgeschäft-Formulare offen, Einstellungen gesperrt, keine JS-Fehler – OK")


asyncio.run(main())
