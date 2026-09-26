"""Funktions- und Rechte-Test der fivemadmin-WebCore-Seite (bindet keinen Port)."""
import asyncio, re, sys, types
from urllib.parse import unquote_plus as unquote
import fivem_harness as FH
from aiohttp.test_utils import TestServer, TestClient

OWNER, LENA, TOM, KAI = ({"X-Test-User": u} for u in ("1", "11", "12", "13"))
URL = "/cogs/fivemadmin"
results = []


def check(cond, label):
    results.append((bool(cond), label))
    print(("OK   " if cond else "FAIL ") + label)


def csrf(t):
    return re.search(r"name='csrf_token' value='([^']+)'", t).group(1)


async def main():
    wc, bot, app, cog = await FH.make_app()
    from rc.fivemadmin import db, dashboard as D
    from rc.fivemadmin.adminpanel import ALL_PERMS, PRESETS
    client = TestClient(TestServer(app)); await client.start_server()

    async def get(h, guild=1000):
        r = await client.get(f"{URL}?guild={guild}", headers=h); return r.status, await r.text()

    async def post(h, **data):
        _, t = await get(h, data.get("guild", 1000))
        if "csrf_token" not in t:  # Seite ohne Formular: Token der (gemeinsamen Test-)Sitzung vom Owner holen
            _, t = await get(OWNER)
        data.setdefault("guild", "1000")
        r = await client.post(URL, headers=h, data={"csrf_token": csrf(t), **data}, allow_redirects=False)
        return r.status, unquote(r.headers.get("Location", ""))

    BAN_DATA = ["Kevin Krawall", "Cheating (Aimbot)", "Lisa Lärm", "RDM im Stadtpark", "XYZ98765", "MNO11111"]
    ACTION_DATA = ["Restart in 10 Minuten", "RST33333", "LMN22222", "Spieler offline", "add 25.000"]
    secrets = [FH.SECRET_API_KEY, FH.SECRET_API_KEY[-8:], FH.SECRET_OAUTH, "123456789012345678"]

    # ---------- Owner sieht alles
    s, t = await get(OWNER)
    check(s == 200 and "ro-banner" not in t, "Owner: Seite 200, nicht schreibgeschützt")
    for needle in ("data-tab='uebersicht'", "data-tab='sperren'", "data-tab='rechte'", "data-tab='einstellungen'",
                   "Lockdown aktivieren", "name='form' value='unban'", "name='form' value='sso'",
                   "name='form' value='rights'", "name='form' value='settings'", "Live-Panel öffnen",
                   "Kevin Krawall", "Restart in 10 Minuten"):
        check(needle in t, f"Owner sieht: {needle}")
    check("<script>alert(1)</script>" not in t and "&lt;script&gt;alert(1)&lt;/script&gt;" in t, "Ban-Name wird escaped")
    check(not any(x in t for x in secrets), "Owner-HTML enthält keine Secrets")
    check("?login=" not in t, "kein Login-Token im HTML")

    # ---------- Tom: WebCore „Ansehen“ -> read-only, POST zentral abgelehnt
    s, t = await get(TOM)
    check(s == 200 and "ro-banner" in t, "Tom (Ansehen): read-only-Banner")
    check(not any(x in t for x in secrets), "Tom-HTML enthält keine Secrets")
    check("Anmelden per Dashboard braucht" in t, "Tom: SSO-Hinweis statt Button (nur Ansicht)")
    check("Kevin Krawall" in t and "Cheating (Aimbot)" in t, "Tom (moderator = ban): sieht Sperrliste")
    check(not any(x in t for x in ACTION_DATA) and "Recht <b>„Audit“</b>" in t, "Tom (ohne audit): keine Aufträge, Hinweis")
    check("name='role:" not in t and "name='user:" not in t and "sehen und ändern nur <b>Discord-Administratoren</b>" in t,
          "Tom (kein Admin): keine Rollen-/Personen-Zuordnungen, Hinweis")
    # Tom nur mit Preset editor (weder ban noch audit): keine Namen/Gründe/Aufträge
    await cog.config.guild_from_id(1000).role_map.set({"1101": "support", "1102": "editor", "1999": "admin"})
    s, t = await get(TOM)
    check(s == 200 and "ro-banner" in t and not any(x in t for x in BAN_DATA + ACTION_DATA),
          "Tom (Ansehen, editor ohne ban/audit): keine Namen/Gründe/Aufträge im HTML")
    check("Recht <b>„Bannen“</b>" in t and "Recht <b>„Audit“</b>" in t and ">4<" in t,
          "Tom (editor): Hinweise statt Daten, Kennzahl „aktive Sperren“ bleibt")
    await cog.config.guild_from_id(1000).role_map.set({"1101": "support", "1102": "moderator", "1999": "admin"})
    s, loc = await post(TOM, form="unban", cid="ABC12345")
    check(s == 302 and "Keine Bearbeitungsrechte" in loc and db.get_ban("ABC12345"), "Tom (Ansehen): Entbannen abgelehnt, Ban bleibt")

    # ---------- Lena: WebCore „Bearbeiten“, Preset support (ohne ban)
    s, t = await get(LENA)
    check(s == 200 and "ro-banner" not in t, "Lena (Bearbeiten): nicht schreibgeschützt")
    check("name='form' value='unban'" not in t and "Recht <b>„Bannen“</b>" in t,
          "Lena: kein Entbannen-Button, Hinweis auf fehlendes Recht")
    check(not any(x in t for x in BAN_DATA + ACTION_DATA) and "Recht <b>„Audit“</b>" in t and "name='role:" not in t,
          "Lena (support): keine Ban-/Auftragsdaten, keine Rollen-Zuordnungen")
    check("name='form' value='lockdown'" not in t and "name='form' value='rights'" not in t
          and "name='form' value='settings'" not in t, "Lena: keine Lockdown/Rechte/Einstellungs-Formulare")
    check(not any(x in t for x in secrets), "Lena-HTML enthält keine Secrets")
    s, loc = await post(LENA, form="unban", cid="ABC12345")
    check("err=" in loc and "Bannen" in loc and db.get_ban("ABC12345"), "Lena: Entbannen ohne Preset-Recht abgelehnt (serverseitig)")
    s, loc = await post(LENA, form="lockdown", state="on")
    check("err=" in loc and not await cog.config.locked(), "Lena: Lockdown abgelehnt")
    s, loc = await post(LENA, form="rights", **{"role:1104": "admin"})
    rm = await cog.config.guild_from_id(1000).role_map()
    check("err=" in loc and "1104" not in rm, "Lena: Rollen-Zuordnung abgelehnt")
    s, loc = await post(LENA, form="settings", money_max="999999", item_max="5", public_url="")
    check("err=" in loc and await cog.config.money_max() is None, "Lena: botweite Einstellungen abgelehnt")

    # ---------- SSO (Lena hat Panel-Recht support)
    s, loc = await post(LENA, form="sso")
    m = re.match(r"^https://panel\.example\.test/\?login=([A-Za-z0-9_\-]+)$", loc)
    check(s == 302 and m, f"SSO: Redirect auf Live-Panel mit Token ({loc[:48]}…)")
    if m:
        import sqlite3
        con = sqlite3.connect(db.DB_PATH)
        row = con.execute("SELECT user_id, guild_id, display_name, used FROM login_tokens WHERE token=?", (m.group(1),)).fetchone()
        check(row == ("11", "1000", "Lena", 0), f"SSO: Token in DB für Lena/Server 1000 ({row})")
        sess = db.redeem_login_token(m.group(1))
        check(sess and sess["user_id"] == "11", "SSO: Token im Live-Panel einlösbar (redeem_login_token)")
    wa = await wc.config.audit()
    check(any(e["page"] == "fivemadmin" and e["action"] == "sso" and e["ok"] for e in wa)
          and not any("login=" in str(e.get("result")) for e in wa), "WebCore-Audit: SSO protokolliert, ohne Token")

    # ---------- Kai: Bearbeiten, aber keine Panel-Rechte -> Hinweis statt SSO
    await wc.config.role_perms.set({"1000": {"1101": {"fivemadmin": "edit"}, "1102": {"fivemadmin": "view"},
                                             "1104": {"fivemadmin": "edit"}}})
    s, t = await get(KAI)
    check(s == 200 and "keine Panel-Rechte" in t and "name='form' value='sso'" not in t, "Kai: keine Panel-Rechte -> Hinweis statt Button")
    s, loc = await post(KAI, form="sso")
    check("err=" in loc and "keine Panel-Rechte" in loc, "Kai: SSO-POST abgelehnt")

    # ---------- Tom bekommt Bearbeiten -> Moderator darf entbannen, aber keinen Lockdown
    await wc.config.role_perms.set({"1000": {"1101": {"fivemadmin": "edit"}, "1102": {"fivemadmin": "edit"}}})
    bot.sent.clear()
    s, loc = await post(TOM, form="unban", cid="ABC12345")
    check("ok=" in loc and not db.get_ban("ABC12345"), "Tom (Bearbeiten + moderator): Entbannen erfolgreich")
    check(any(cid == 1004 and "Unban" in txt and "Tom (Dashboard)" in txt for cid, txt in bot.sent), "fivemadmin-Audit-Kanal: Unban gemeldet")
    s, loc = await post(TOM, form="lockdown", state="on")
    check("err=" in loc and not await cog.config.locked(), "Tom (kein Discord-Admin): Lockdown abgelehnt")

    # ---------- Owner: Lockdown verwirft offene Aufträge
    pend = db.get_pending_actions()
    check(len(pend) == 3, f"vorher {len(pend)} offene Aufträge")
    bot.sent.clear()
    s, loc = await post(OWNER, form="lockdown", state="on")
    check("ok=" in loc and "3 offene" in loc and await cog.config.locked(), "Owner: Lockdown an, 3 Aufträge verworfen")
    check(db.get_pending_actions() == [], "keine offenen Aufträge mehr")
    dropped = [db.get_action(a["id"]) for a in pend]
    check(all(a["status"] == "failed" and a["result"] == "Verworfen durch Lockdown (Matters86 (Dashboard))" for a in dropped),
          "verworfene Aufträge exakt wie beim Befehl markiert")
    check(any("LOCKDOWN AKTIVIERT" in txt for _, txt in bot.sent), "Audit-Kanal: Lockdown gemeldet")
    s, t = await get(OWNER)
    check("Lockdown aufheben" in t and "Lockdown ist aktiv" in t, "Owner-Ansicht: Lockdown aktiv")
    s, loc = await post(OWNER, form="lockdown", state="off")
    check("ok=" in loc and not await cog.config.locked(), "Owner: Lockdown aus")

    # Befehl `ap lockdown on` nutzt dieselbe Hilfsfunktion
    db.add_action("heal", "X1", None, "web:Test")
    sent = []
    ctx = types.SimpleNamespace(author=types.SimpleNamespace(display_name="Cmd"), send=lambda m: _append(sent, m))
    await cog.ap_lockdown.callback(cog, ctx, "on")
    check(await cog.config.locked() and db.get_pending_actions() == [] and "**1** offene" in sent[-1], "Befehl ap lockdown on: gleiche Wirkung")
    await cog.ap_lockdown.callback(cog, ctx, "off")
    check(not await cog.config.locked(), "Befehl ap lockdown off")

    # ---------- Owner: Panel-Rechte
    bot.sent.clear()
    s, loc = await post(OWNER, form="rights", **{"role:1104": "admin", "role:1999": "", "role:1101": "support",
                                                 "user:14": "", "add_user": "Kai", "add_preset": "moderator"})
    rm = await cog.config.guild_from_id(1000).role_map(); um = await cog.config.guild_from_id(1000).user_map()
    check("ok=" in loc and rm == {"1101": "support", "1102": "moderator", "1104": "admin"} and um == {"13": "moderator"},
          f"Owner: Rollen/Personen gespeichert ({rm}, {um})")
    check(sum("Rollen-Mapping" in t or "Einzel-Zugriff" in t for _, t in bot.sent) == 4, "Audit-Kanal: 4 Rechte-Änderungen gemeldet")
    s, loc = await post(OWNER, form="rights", **{"role:1103": "gott"})
    check("err=" in loc and "1103" not in await cog.config.guild_from_id(1000).role_map(), "unbekanntes Preset abgelehnt")
    s, loc = await post(OWNER, form="rights", add_user="Niemand")
    check("err=" in loc, "unbekannte Person abgelehnt")

    # Schutz vor Selbst-Hochstufung (Hilfsfunktion + Durchsetzung im Handler)
    sup = set(PRESETS["support"])
    check(D._may_assign(sup, None, "support") and not D._may_assign(sup, None, "admin")
          and not D._may_assign(sup, "admin", None) and D._may_assign(set(ALL_PERMS), "admin", "editor"),
          "_may_assign: kein Preset über den eigenen Rechten")
    fake_actor = D.Actor(user={"id": 12, "name": "Tom"}, member=bot.get_guild(1000).get_member(12), full=False,
                         panel_perms=set(PRESETS["moderator"]), discord_admin=True)
    from multidict import MultiDict
    res = await D._post_rights(cog, bot.get_guild(1000), fake_actor, MultiDict({"role:1103": "admin", "role:1101": "moderator"}))
    rm = await cog.config.guild_from_id(1000).role_map()
    check("err=" in res["redirect"] and "1103" not in rm and rm["1101"] == "moderator",
          "Selbst-Hochstufung: moderator darf admin nicht vergeben, moderator schon")

    # ---------- Owner: Einstellungen
    s, loc = await post(OWNER, form="settings", audit_channel="1004", alert_channel="1003", money_max="100000",
                        item_max="250", public_url="https://neu.example.test/")
    c = await cog.config.all()
    check("ok=" in loc and c["alert_channel"] == 1003 and c["money_max"] == 100000 and c["item_max"] == 250
          and c["public_url"] == "https://neu.example.test" and cog.money_max == 100000, "Owner: Einstellungen gespeichert")
    s, loc = await post(OWNER, form="settings", audit_channel="2001", alert_channel="", money_max="1", item_max="1", public_url="")
    check("err=" in loc and (await cog.config.audit_channel()) == 1004, "Kanal eines fremden Servers abgelehnt")
    s, loc = await post(OWNER, form="settings", audit_channel="1004", alert_channel="", money_max="1", item_max="1",
                        public_url="javascript:alert(1)")
    check("err=" in loc and (await cog.config.public_url()) == "https://neu.example.test", "ungültige URL abgelehnt")
    s, loc = await post(OWNER, form="settings", audit_channel="1004", alert_channel="1003", money_max="0", item_max="1",
                        public_url="https://neu.example.test")
    check("err=" in loc, "Limit 0 abgelehnt")

    # SSO ohne Panel-URL
    await cog.config.public_url.set(None)
    s, t = await get(LENA)
    check("Keine <b>Panel-URL</b>" in t and "name='form' value='sso'" not in t and "bi-box-arrow-up-right" not in t,
          "ohne Panel-URL: Hinweis, kein SSO/Öffnen")
    s, loc = await post(LENA, form="sso")
    check("err=" in loc and "Panel-URL" in loc, "ohne Panel-URL: SSO-POST abgelehnt")

    # WebCore-Audit enthält abgelehnte Versuche
    wa = await wc.config.audit()
    check(any(e["page"] == "fivemadmin" and not e["ok"] and e["action"] == "unban" for e in wa), "WebCore-Audit: abgelehnter Unban protokolliert")

    # Secrets: alle Nutzer, abschließend
    for h in (OWNER, LENA, TOM, KAI):
        s, t = await get(h)
        check(not any(x in t for x in secrets), f"keine Secrets im HTML für User {h['X-Test-User']}")

    await client.close()
    bad = [l for ok, l in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} OK" + (" – FEHLER: " + "; ".join(bad) if bad else " – alle OK"))
    sys.exit(1 if bad else 0)


async def _append(lst, m):
    lst.append(m)

asyncio.run(main())
