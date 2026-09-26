"""Stufe „Bedienen“ (Tagesgeschäft) in den Cogs tickets, warns, guard, fivemadmin, welcome, sticky, changelog,
autorole, levels, serverstats: erlaubte Tagesgeschäft-POSTs, Ablehnung von Einstellungs-POSTs (Toast), Oberfläche
(Banner, data-operate, Test-/Schließen-Formulare) und Cogs ohne Tagesgeschäft (Bedienen = Ansehen)."""
import asyncio
import re
from urllib.parse import unquote_plus

from aiohttp.test_utils import TestClient, TestServer
from multidict import MultiDict

import tc_harness as T          # zuerst: live_harness + Ticket-Patches (add_roles, Kanal-edit, created_at)
import tc_seed
import wl_harness as W
import fivem_harness as F
import lv_harness as LV
import st_harness as ST

H = T.H
NR = {"allow_redirects": False}
OWNER = {"X-Test-User": "1"}
LENA = {"X-Test-User": "11"}   # Support (1101)
TOM = {"X-Test-User": "12"}    # Moderator (1102)
KAI = {"X-Test-User": "13"}    # VIP (1104)
MIA = {"X-Test-User": "14"}    # Support (1101) + Raidleitung (1103)
TOAST_EDIT = "Dafür brauchst du das Recht Bearbeiten"
NO_RIGHTS = "Keine Bearbeitungsrechte"


def csrf(text):
    return re.search(r"name='csrf_token' value='([^']+)'", text).group(1)


async def page(client, headers, path):
    r = await client.get(path, headers=headers)
    t = await r.text()
    assert r.status == 200, (path, r.status, t[:500])
    assert "Traceback" not in t and "wc-error" not in t, (path, t[:800])
    return t


async def post(client, headers, slug, data):
    """POST mit Feldern als dict oder Liste von Paaren -> (Status, dekodierte Location)."""
    r = await client.post(f"/cogs/{slug}", headers=headers, data=data, **NR)
    return r.status, unquote_plus(r.headers.get("Location", ""))


def assert_operate_page(t, forms):
    assert 'data-operate="1"' in t and 'data-readonly="0"' in t, t[:1500]
    assert f'data-operate-forms="{forms}"' in t, re.search(r'data-operate-forms="[^"]*"', t)
    assert "op-banner" in t and "Nur Ansicht." not in t


def assert_readonly_page(t):
    assert 'data-readonly="1"' in t and "data-operate" not in t and "Nur Ansicht." in t, t[:1500]
    assert "op-banner" not in t


async def denied_edit(client, headers, slug, tok, cases, check_unchanged=None):
    """Jeder Fall muss mit dem Toast „Bearbeiten nötig“ abgelehnt werden, ohne dass sich etwas ändert."""
    before = await check_unchanged() if check_unchanged else None
    for fields in cases:
        data = [("csrf_token", tok), ("guild", "1000")] + (list(fields.items()) if isinstance(fields, dict) else fields)
        st, loc = await post(client, headers, slug, data)
        assert st == 302 and f"err={TOAST_EDIT}" in loc, (slug, fields, loc)
    if check_unchanged:
        assert await check_unchanged() == before, f"{slug}: Ablehnung hat trotzdem etwas geändert"


# =========================================================================== #
#  tickets + changelog
# =========================================================================== #
async def tickets_changelog():
    wc, bot, app, tk, cl = await T.make_app()
    await tc_seed.seed(bot, tk, cl)
    g = bot.guilds[0]
    gc = tk.config.guild(g)
    assert wc.pages["tickets"].operate_forms == {"ticket_close"}
    assert callable(wc.pages["changelog"].operate_forms)
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "operate", "changelog": "operate"},
                                             "1102": {"tickets": "view", "changelog": "view"},
                                             "1103": {"tickets": "edit", "changelog": "edit"}}})
    client = TestClient(TestServer(app))
    await client.start_server()

    # ---- Oberfläche
    t = await page(client, LENA, "/cogs/tickets?guild=1000")
    assert_operate_page(t, "ticket_close")
    assert "Offene Tickets" in t and t.count("value='ticket_close'") == 2, t.count("value='ticket_close'")
    assert "Du kannst Aktionen ausführen, aber keine Einstellungen ändern." in t
    tok = csrf(t)
    t = await page(client, TOM, "/cogs/tickets?guild=1000")
    assert_readonly_page(t)
    assert "Offene Tickets" in t
    t = await page(client, MIA, "/cogs/tickets?guild=1000")
    assert 'data-readonly="0"' in t and "data-operate" not in t and "op-banner" not in t

    # ---- Tagesgeschäft: Ticket schließen
    open_ids = {r["owner_id"]: (cid, r) for cid, r in (await gc.tickets()).items() if r["status"] == "open"}
    cid_kai, rec_kai = open_ids[13]
    closed_before = (await gc.stats()).get("closed", 0)
    n_tr = len(await gc.transcripts())
    st, loc = await post(client, LENA, "tickets", {"csrf_token": tok, "guild": "1000", "form": "ticket_close",
                                                    "channel_id": cid_kai})
    assert st == 302 and f"ok=Ticket #{rec_kai['num']} geschlossen" in loc, loc
    rec = (await gc.tickets())[cid_kai]
    assert rec["status"] == "closed" and rec.get("closed_at"), rec
    assert (await gc.stats())["closed"] == closed_before + 1 and len(await gc.transcripts()) == n_tr + 1
    doc = (tk.transcripts_dir / (await gc.transcripts())[-1]["file"]).read_text(encoding="utf-8")
    assert "lena" in doc, "Transcript nennt die schließende Person (Dashboard-User)"
    st, loc = await post(client, LENA, "tickets", {"csrf_token": tok, "guild": "1000", "form": "ticket_close",
                                                    "channel_id": cid_kai})
    assert "err=" in loc and "bereits geschlossen" in loc, loc
    assert (await gc.stats())["closed"] == closed_before + 1, "kein zweites Schließen"
    st, loc = await post(client, LENA, "tickets", {"csrf_token": tok, "guild": "1000", "form": "ticket_close",
                                                    "channel_id": "12345"})
    assert "err=Ticket nicht gefunden" in loc, loc
    # verwaister Eintrag (Kanal in Discord gelöscht)
    async with gc.tickets() as tickets:
        tickets["987654"] = {"num": 99, "owner_id": 13, "status": "open", "created_at": "2026-09-01T10:00:00+00:00"}
    t = await page(client, LENA, "/cogs/tickets?guild=1000")
    assert "Kanal fehlt" in t and "existiert nicht mehr" in t
    st, loc = await post(client, LENA, "tickets", {"csrf_token": tok, "guild": "1000", "form": "ticket_close",
                                                    "channel_id": "987654"})
    assert "ok=Ticket #99: Kanal existiert nicht mehr – Eintrag entfernt" in loc, loc
    assert "987654" not in await gc.tickets()
    # Ansehen darf nicht schließen, Bearbeiten schon
    cid_nina, rec_nina = open_ids[15]
    tok_t = csrf(await page(client, TOM, "/cogs/tickets?guild=1000"))
    st, loc = await post(client, TOM, "tickets", {"csrf_token": tok_t, "guild": "1000", "form": "ticket_close",
                                                   "channel_id": cid_nina})
    assert NO_RIGHTS in loc and (await gc.tickets())[cid_nina]["status"] == "open", loc
    tok_m = csrf(await page(client, MIA, "/cogs/tickets?guild=1000"))
    st, loc = await post(client, MIA, "tickets", {"csrf_token": tok_m, "guild": "1000", "form": "ticket_close",
                                                   "channel_id": cid_nina})
    assert f"ok=Ticket #{rec_nina['num']} geschlossen" in loc and (await gc.tickets())[cid_nina]["status"] == "closed"
    t = await page(client, LENA, "/cogs/tickets?guild=1000")
    assert "Keine offenen Tickets." in t
    # Schließende Person ohne Server-Mitgliedschaft (z. B. Bot-Owner)
    from rc.tickets.dashboard import _DashboardCloser
    c = _DashboardCloser(1, "Matters86 (Dashboard)")
    assert str(c) == "Matters86 (Dashboard)" and c.mention == "<@1>" and c.id == 1

    # ---- Einstellungen & Panels: Bearbeiten nötig
    async def snapshot():
        conf = await gc.all()
        return {k: conf[k] for k in ("language", "support_roles", "admin_roles", "owner_role", "panels", "max_open")}
    panel = (await gc.panels())[0]
    await denied_edit(client, LENA, "tickets", tok, [
        {"form": "settings", "language": "en", "ticket_type": "thread", "max_open": "3", "admin_roles": "1101"},
        {"form": "panel_create", "channel_id": "1002", "title": "Neu"},
        {"form": "panel_save", "panel_id": panel["id"], "title": "Geändert", "channel_id": "1002"},
        {"form": "panel_routing", "panel_id": panel["id"]},
        {"form": "panel_delete", "panel_id": panel["id"]},
        [("form", "ticket_close"), ("form", "settings"), ("channel_id", cid_nina)],
    ], snapshot)
    print("tickets: Offene Tickets + Schließen mit Bedienen (Transcript, doppelt, verwaist, unbekannt), "
          "Ansehen/Bearbeiten, Einstellungen/Panels/Zuordnung abgelehnt – OK")

    # ---- changelog
    from rc.changelog.dashboard import is_operate_post
    assert is_operate_post({"form": "action", "action": "delete"})
    assert not is_operate_post({"form": "action", "action": "edit"}) and not is_operate_post({"form": "settings"})
    assert not is_operate_post(MultiDict([("form", "action"), ("action", "delete"), ("action", "x")]))
    assert not is_operate_post(MultiDict([("form", "action"), ("form", "settings"), ("action", "delete")]))
    assert is_operate_post(MultiDict([("form", "action"), ("action", "delete"), ("entry_id", "CL001")]))
    cc = cl.config.guild(g)
    t = await page(client, LENA, "/cogs/changelog?guild=1000")
    assert_operate_page(t, "")
    assert "data-wc-operate='1'" in t, "Löschen-Formular als Tagesgeschäft markiert"
    entries = await cc.entries()
    eid = sorted(entries)[0]
    st, loc = await post(client, LENA, "changelog", {"csrf_token": tok, "guild": "1000", "form": "action",
                                                      "action": "delete", "entry_id": eid})
    assert "ok=Gelöscht" in loc and eid not in await cc.entries(), loc

    async def cl_snapshot():
        conf = await cc.all()
        return {k: conf[k] for k in ("channel_id", "language", "poster_roles", "public_api", "entries", "categories")}
    eid2 = sorted(await cc.entries())[0]
    await denied_edit(client, LENA, "changelog", tok, [
        {"form": "settings", "channel": "1002", "language": "en", "public_api": "on", "poster_roles": "1101"},
        {"form": "action", "action": "other", "entry_id": eid2},
        [("form", "action"), ("action", "delete"), ("action", "x"), ("entry_id", eid2)],
    ], cl_snapshot)
    st, loc = await post(client, TOM, "changelog", {"csrf_token": tok_t, "guild": "1000", "form": "action",
                                                     "action": "delete", "entry_id": eid2})
    assert NO_RIGHTS in loc and eid2 in await cc.entries()
    print("changelog: Callable (nur form=action+action=delete), Löschen mit Bedienen, Einstellungen/API-Freigabe "
          "abgelehnt – OK")
    await client.close()


# =========================================================================== #
#  welcome, warns, guard, sticky, autorole
# =========================================================================== #
async def welcome_warns_guard_sticky_autorole():
    wc, bot, app = await W.make_app()
    await W.seed(bot)
    g = bot.guilds[0]
    allg = g.text_channels[0]
    assert wc.pages["welcome"].operate_forms == {"test"}
    assert wc.pages["warnings"].operate_forms == {"warn", "revoke"}
    assert wc.pages["guard"].operate_forms == {"lockdown"}
    assert wc.pages["sticky"].operate_forms == {"save", "toggle", "delete"}
    assert not wc.pages["autorole"].supports_operate
    slugs = ("welcome", "warnings", "guard", "sticky", "autorole")
    await wc.config.role_perms.set({"1000": {"1101": {s: "operate" for s in slugs},
                                             "1102": {s: "view" for s in slugs}}})
    client = TestClient(TestServer(app))
    await client.start_server()

    # ---------------------------------------------------------------- welcome
    wl = bot._cogs["Welcome"]
    wconf = wl.config.guild(g)
    seen = []

    async def fake_card(member, conf):   # kein echtes Rendern/Laden der Bild-URL im Test
        seen.append((conf["card_bg_color"], conf["card_bg_url"], conf["card_headline"]))
        return b"\x89PNG\r\n\x1a\nfake", None
    wl.render_card = fake_card
    saved_bg = await wconf.card_bg_color()
    q = "/cogs/welcome?guild=1000&preview=card&bg=%23ff0000&headline=HACK&url=https%3A%2F%2Fevil.example%2Fx.png"
    for who, expect in ((LENA, (saved_bg, "", "")), (TOM, (saved_bg, "", "")),
                        (OWNER, ("#ff0000", "https://evil.example/x.png", "HACK"))):
        r = await client.get(q, headers=who)
        assert r.status == 200 and r.headers["Content-Type"] == "image/png", r.status
        assert seen[-1] == expect, (who, seen[-1])
    t = await page(client, LENA, "/cogs/welcome?guild=1000")
    assert_operate_page(t, "test")
    assert t.count("name='form' value='test'") == 4 and "Testen" in t and "data-wc-operate='1'" in t
    assert "addEventListener('input',later)" not in t, "Live-Vorschau-Skript nur mit Bearbeiten"
    tok = csrf(t)
    t = await page(client, OWNER, "/cogs/welcome?guild=1000")
    assert "addEventListener('input',later)" in t and "name='form' value='test'" not in t, "Bearbeiten: Speichern + Test wie bisher"
    t = await page(client, TOM, "/cogs/welcome?guild=1000")
    assert_readonly_page(t)
    assert "name='form' value='test'" not in t

    async def wl_snapshot():
        return await wconf.all()
    before = await wl_snapshot()
    n_log = len(W.L.LOG)
    st, loc = await post(client, LENA, "welcome", {"csrf_token": tok, "guild": "1000", "form": "test", "kind": "welcome"})
    assert "ok=Testnachricht gepostet in #allgemein" in loc, loc
    assert any(op == "send" and cid == allg.id for op, cid, _ in W.L.LOG[n_log:]), W.L.LOG[n_log:]
    n_dm = len(W.SENT_DMS)
    st, loc = await post(client, LENA, "welcome", {"csrf_token": tok, "guild": "1000", "form": "test", "kind": "dm"})
    assert "ok=Test-DM gesendet" in loc and W.SENT_DMS[n_dm][0] == 11, loc
    st, loc = await post(client, LENA, "welcome", {"csrf_token": tok, "guild": "1000", "form": "test", "kind": "leave"})
    assert "err=Test fehlgeschlagen: Kein Kanal gesetzt" in loc, loc
    st, loc = await post(client, LENA, "welcome", {"csrf_token": tok, "guild": "1000", "form": "test", "kind": "card"})
    assert "err=Unbekannte Nachricht" in loc, loc
    assert await wl_snapshot() == before, "Test ohne Speichern ändert nichts"
    await denied_edit(client, LENA, "welcome", tok, [
        {"form": "welcome", "enabled": "on", "channel": str(allg.id), "mode": "text", "text": "HACK",
         "color": "#ffffff", "language": "de", "do": "test"},
        {"form": "welcome", "enabled": "on", "channel": str(allg.id), "mode": "text", "text": "HACK",
         "color": "#ffffff", "language": "de"},
        {"form": "card", "card_bg_url": "https://evil.example/x.png", "card_bg_color": "#000000",
         "card_accent": "#000000", "card_text_color": "#ffffff", "do": "test"},
        {"form": "dm", "enabled": "on", "mode": "text", "text": "x", "color": "#ffffff"},
    ], wl_snapshot)
    tok_t = csrf(await page(client, TOM, "/cogs/welcome?guild=1000"))
    st, loc = await post(client, TOM, "welcome", {"csrf_token": tok_t, "guild": "1000", "form": "test", "kind": "welcome"})
    assert NO_RIGHTS in loc, loc
    # Bearbeiten: Speichern + Test wie bisher
    st, loc = await post(client, OWNER, "welcome", {
        "csrf_token": csrf(await page(client, OWNER, "/cogs/welcome?guild=1000")), "guild": "1000", "form": "welcome",
        "enabled": "on", "channel": str(allg.id), "mode": "text", "text": "Hallo {user}", "color": "#3ddc97",
        "language": "de", "do": "test"})
    assert "ok=Willkommen gespeichert – Testnachricht gepostet in #allgemein" in loc, loc
    print("welcome: Vorschau mit URL-Parametern nur mit Bearbeiten (can_edit), Test ohne Speichern mit Bedienen "
          "(welcome/dm/Fehler), Speichern/Speichern+Test abgelehnt – OK")

    # ---------------------------------------------------------------- warns
    wa = bot._cogs["Warns"]
    aconf = wa.config.guild(g)
    t = await page(client, LENA, "/cogs/warnings?guild=1000")
    assert_operate_page(t, "revoke,warn")
    assert "Aufheben" in t and "nur <b>Ansehen</b>" not in t
    t = await page(client, TOM, "/cogs/warnings?guild=1000")
    assert_readonly_page(t)
    assert "mindestens <b>Bedienen</b>" in t
    st, loc = await post(client, LENA, "warnings", {"csrf_token": tok, "guild": "1000", "form": "warn",
                                                     "member": "Kai (13)", "reason": "Test aus Bedienen", "points": "1"})
    m = re.search(r"ok=Verwarnung #(\d+) für Kai", loc)
    assert m, loc
    wid = m.group(1)
    st, loc = await post(client, LENA, "warnings", {"csrf_token": tok, "guild": "1000", "form": "revoke", "id": wid})
    assert f"ok=Verwarnung #{wid} aufgehoben" in loc, loc
    # Hierarchie-Prüfung bleibt: Lena (Support, Pos. 5) darf Tom (Moderator, Pos. 8) nicht verwarnen
    st, loc = await post(client, LENA, "warnings", {"csrf_token": tok, "guild": "1000", "form": "warn",
                                                     "member": "Tom (12)", "reason": "x", "points": "1"})
    assert "err=" in loc and TOAST_EDIT not in loc, loc

    async def wa_snapshot():
        conf = await aconf.all()
        return {k: conf[k] for k in ("timeout_at", "kick_at", "ban_at", "mod_roles", "log_channel", "dm_text")}
    await denied_edit(client, LENA, "warnings", tok, [
        {"form": "actions", "timeout_at": "1", "timeout_minutes": "5", "kick_at": "0", "ban_at": "2"},
        {"form": "settings", "mod_roles": "1101", "expiry_days": "0", "default_points": "1", "language": "de"},
    ], wa_snapshot)
    print("warns: Verwarnen/Aufheben mit Bedienen (Hierarchie bleibt), Maßnahmen/Einstellungen abgelehnt – OK")

    # ---------------------------------------------------------------- guard
    gu = bot._cogs["Guard"]
    uconf = gu.config.guild(g)
    t = await page(client, LENA, "/cogs/guard?guild=1000")
    assert_operate_page(t, "lockdown")
    assert "Notmodus jetzt aktivieren" in t
    st, loc = await post(client, LENA, "guard", {"csrf_token": tok, "guild": "1000", "form": "lockdown", "state": "on"})
    assert "ok=Notmodus aktiviert" in loc and await uconf.lockdown_until(), loc
    st, loc = await post(client, LENA, "guard", {"csrf_token": tok, "guild": "1000", "form": "lockdown", "state": "off"})
    assert "ok=Notmodus beendet" in loc and not await uconf.lockdown_until(), loc

    async def gu_snapshot():
        conf = await uconf.all()
        return {k: conf[k] for k in ("whitelist_roles", "log_channel", "hp_channel", "language", "hp_action")}
    await denied_edit(client, LENA, "guard", tok, [
        {"form": "settings", "whitelist_roles": "1101", "language": "en", "hp_action": "ban"},
    ], gu_snapshot)
    st, loc = await post(client, TOM, "guard", {"csrf_token": tok_t, "guild": "1000", "form": "lockdown", "state": "on"})
    assert NO_RIGHTS in loc and not await uconf.lockdown_until()
    print("guard: Notmodus an/aus mit Bedienen, Einstellungen abgelehnt, Ansehen nichts – OK")

    # ---------------------------------------------------------------- sticky
    sk = bot._cogs["Sticky"]
    kconf = sk.config.guild(g)
    t = await page(client, LENA, "/cogs/sticky?guild=1000")
    assert_operate_page(t, "delete,save,toggle")
    cid = str(allg.id)
    st, loc = await post(client, LENA, "sticky", {"csrf_token": tok, "guild": "1000", "form": "save", "channel": cid,
                                                   "mode": "text", "text": "Bitte Regeln lesen"})
    assert "ok=Sticky gespeichert" in loc or "ok=Gespeichert" in loc, loc
    assert (await kconf.stickies())[cid]["text"] == "Bitte Regeln lesen"
    st, loc = await post(client, LENA, "sticky", {"csrf_token": tok, "guild": "1000", "form": "toggle", "channel": cid})
    assert "ok=Status geändert" in loc and (await kconf.stickies())[cid]["enabled"] is False, loc
    st, loc = await post(client, LENA, "sticky", {"csrf_token": tok, "guild": "1000", "form": "delete", "channel": cid})
    assert "ok=Sticky gelöscht" in loc and cid not in await kconf.stickies(), loc

    async def sk_snapshot():
        conf = await kconf.all()
        return {k: conf[k] for k in ("language", "cooldown", "ignore_bots")}
    await denied_edit(client, LENA, "sticky", tok, [{"form": "settings", "language": "en", "cooldown": "99"}],
                      sk_snapshot)
    print("sticky: anlegen/pausieren/löschen mit Bedienen, Einstellungen abgelehnt – OK")

    # ---------------------------------------------------------------- autorole (ohne Tagesgeschäft)
    ar = bot._cogs["Autorole"]
    rconf = ar.config.guild(g)
    t = await page(client, LENA, "/cogs/autorole?guild=1000")
    assert_readonly_page(t)

    async def ar_snapshot():
        conf = await rconf.all()
        return {k: conf[k] for k in ("enabled", "join_roles", "bot_roles", "panels")}
    await denied_edit(client, LENA, "autorole", tok, [
        {"form": "settings", "enabled": "on", "join_roles": "1104"},
        {"form": "applyall"},
        {"form": "panel_create", "name": "X"},
        {"form": "panel_post", "panel": "x"},
    ], ar_snapshot)
    print("autorole: ohne Tagesgeschäft – Bedienen wirkt wie Ansehen, alle POSTs abgelehnt – OK")
    await client.close()


# =========================================================================== #
#  fivemadmin
# =========================================================================== #
async def fivemadmin():
    from rc.fivemadmin import db
    wc, bot, app, cog = await F.make_app()
    g = bot.guilds[0]
    assert wc.pages["fivemadmin"].operate_forms == {"sso", "lockdown", "unban"}
    g.get_member(13).guild_permissions = H.Perms(admin=True)   # Kai: Discord-Administrator
    await wc.config.role_perms.set({"1000": {"1101": {"fivemadmin": "operate"},   # Lena: Preset support
                                             "1102": {"fivemadmin": "operate"},   # Tom: Preset moderator
                                             "1104": {"fivemadmin": "operate"}}})  # Kai: Discord-Admin
    client = TestClient(TestServer(app))
    await client.start_server()
    t = await page(client, LENA, "/cogs/fivemadmin?guild=1000")
    assert_operate_page(t, "lockdown,sso,unban")
    assert "Im Live-Panel anmelden" in t and "braucht auf dieser Seite" not in t
    assert F.SECRET_API_KEY not in t and F.SECRET_OAUTH not in t
    tok = csrf(t)
    # Anmelden (SSO): Bedienen reicht, echte Panel-Rechte nötig
    st, loc = await post(client, LENA, "fivemadmin", {"csrf_token": tok, "guild": "1000", "form": "sso"})
    assert loc.startswith(F.PUBLIC_URL + "/?login="), loc
    # Entbannen: Bedienen + Panel-Recht „ban“ (Support hat es nicht, Moderator schon)
    st, loc = await post(client, LENA, "fivemadmin", {"csrf_token": tok, "guild": "1000", "form": "unban",
                                                       "cid": "ABC12345"})
    assert "err=" in loc and "Panel-Recht" in loc, loc
    st, loc = await post(client, TOM, "fivemadmin", {"csrf_token": tok, "guild": "1000", "form": "unban",
                                                      "cid": "ABC12345"})
    assert "ok=Sperre für ABC12345 aufgehoben" in loc, loc
    assert "ABC12345" not in {b["citizenid"] for b in await asyncio.to_thread(db.get_active_bans)}
    # Not-Aus: Bedienen + Discord-Administrator
    st, loc = await post(client, LENA, "fivemadmin", {"csrf_token": tok, "guild": "1000", "form": "lockdown",
                                                       "state": "on"})
    assert "err=" in loc and "Discord-Administratoren" in loc and not await cog.config.locked(), loc
    st, loc = await post(client, KAI, "fivemadmin", {"csrf_token": tok, "guild": "1000", "form": "lockdown",
                                                      "state": "on"})
    assert "ok=Lockdown aktiv" in loc and await cog.config.locked(), loc
    st, loc = await post(client, KAI, "fivemadmin", {"csrf_token": tok, "guild": "1000", "form": "lockdown",
                                                      "state": "off"})
    assert "ok=Lockdown aufgehoben" in loc and not await cog.config.locked(), loc

    async def fa_snapshot():
        gconf = await cog.config.guild(g).all()
        return (gconf["role_map"], gconf["user_map"], await cog.config.money_max(), await cog.config.public_url())
    for who in (LENA, KAI):   # auch ein Discord-Administrator braucht für Panel-Rechte WebCore-„Bearbeiten“
        await denied_edit(client, who, "fivemadmin", tok, [
            {"form": "rights", "role:1101": "admin", "user_add": "13", "user_preset": "admin"},
            {"form": "settings", "money_max": "999999", "public_url": "https://evil.example"},
        ], fa_snapshot)
    print("fivemadmin: Anmelden/Entbannen/Not-Aus mit Bedienen (Panel-Recht bzw. Discord-Admin weiter geprüft), "
          "Panel-Rechte/Einstellungen abgelehnt – OK")
    await client.close()


# =========================================================================== #
#  levels, serverstats (ohne Tagesgeschäft)
# =========================================================================== #
async def levels_serverstats():
    wc, bot, app, cog = await LV.make_app()
    assert not wc.pages["levels"].supports_operate
    await wc.config.role_perms.set({"1000": {"1101": {"levels": "operate"}}})
    client = TestClient(TestServer(app))
    await client.start_server()
    t = await page(client, LENA, "/cogs/levels?guild=1000")
    assert_readonly_page(t)
    tok = csrf(t)
    g = bot.guilds[0]
    lena = g.get_member(11)

    async def lv_snapshot():
        conf = await cog.config.guild(g).all()
        return ({k: conf[k] for k in ("rewards", "multipliers", "enabled")}, await cog.config.member(lena).xp())
    await denied_edit(client, LENA, "levels", tok, [
        {"form": "xp", "member": "11", "action": "give", "amount": "5000"},
        {"form": "reward_add", "level": "1", "role": "1303"},
        {"form": "sync"},
        {"form": "settings", "enabled": "on"},
    ], lv_snapshot)
    await client.close()
    print("levels: ohne Tagesgeschäft – Bedienen wirkt wie Ansehen, XP/Belohnungen/Abgleich abgelehnt – OK")

    wc, bot, app, cog = await ST.make_app()
    assert not wc.pages["serverstats"].supports_operate
    await wc.config.role_perms.set({"1000": {"1101": {"serverstats": "operate"}}})
    client = TestClient(TestServer(app))
    await client.start_server()
    t = await page(client, LENA, "/cogs/serverstats?guild=1000")
    assert_readonly_page(t)
    tok = csrf(t)
    g = bot.guilds[0]

    async def st_snapshot():
        return await cog.config.guild(g).all()
    await denied_edit(client, LENA, "serverstats", tok, [
        {"form": "settings", "retention_days": "7"},
        {"form": "reset"},
    ], st_snapshot)
    await client.close()
    print("serverstats: ohne Tagesgeschäft – Bedienen wirkt wie Ansehen, Einstellungen/Zurücksetzen abgelehnt – OK")


async def main():
    await tickets_changelog()
    await welcome_warns_guard_sticky_autorole()
    await fivemadmin()
    await levels_serverstats()
    print("ALLE BEDIENEN-TESTS DER COGS OK")


asyncio.run(main())
