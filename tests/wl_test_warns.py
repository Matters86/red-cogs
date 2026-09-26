"""Funktionstests Warns: Befehle, Schwellen inkl. Hierarchie-Schutz, Verfall, IDs, Datenlöschung, Dashboard."""
import asyncio, re, time, types
import wl_harness as W
L = W.L; H = W.H
import discord
from aiohttp.test_utils import TestServer, TestClient


def csrf(html):
    return re.search(r"name='csrf_token' value='([^']+)'", html).group(1)


class Ctx:
    def __init__(self, guild, author):
        self.guild = guild; self.author = author; self.sent = []; self.clean_prefix = "!"
    async def send(self, content=None, *, embed=None, **kw):
        if embed is not None:
            L.validate_embed(embed)
        self.sent.append(content if content is not None else embed)
    @property
    def last(self): return self.sent[-1]


async def main():
    wc, bot, app = await W.make_app()
    cog = bot._cogs["Warns"]
    g = bot.guilds[0]
    allg, sup, ann, logs = g.text_channels
    owner, lena, tom, kai, mia = (g.get_member(i) for i in (1, 11, 12, 13, 14))
    gconf = cog.config.guild(g)
    actions = []
    async def timeout(self, until, reason=None): actions.append(("timeout", self.id, reason))
    H.Member.timeout = timeout
    async def kick(member, reason=None): actions.append(("kick", member.id, reason))
    async def ban(member, reason=None, delete_message_seconds=0): actions.append(("ban", member.id, reason))
    g.kick = kick; g.ban = ban
    await gconf.mod_roles.set([1102])          # Moderator-Rolle (Tom)
    await gconf.log_channel.set(logs.id)

    # --- Rechte ---
    c = Ctx(g, lena)
    await cog.warn.callback(cog, c, kai, reason="Spam")
    assert "Moderationsrechte" in c.last, c.last
    c = Ctx(g, tom)
    await cog.warn.callback(cog, c, kai, reason="Spam im Chat")
    assert "Verwarnung **#1**" in c.last and "Aktive Punkte: **1**" in c.last, c.last
    assert W.SENT_DMS[-1][0] == 13 and "Spam im Chat" in W.SENT_DMS[-1][1] and "#1" in W.SENT_DMS[-1][1]
    logmsg = [m for m in logs._messages.values()][-1]
    assert logmsg.embeds[0].title == "Verwarnung #1", logmsg.embeds[0].title
    print("warn durch Mod-Rolle, DM, Log OK")
    # Punkte im Grund
    await cog.warn.callback(cog, c, mia, reason="3 Beleidigung")
    e = (await cog.member_entries(g, 14))[-1]
    assert e["points"] == 3 and e["reason"] == "Beleidigung" and e["id"] == 2, e
    await cog.warn.callback(cog, c, mia, reason="101 zu viel"); assert "zwischen 1 und 100" in c.last
    # Ziele
    for target, needle in ((tom, "nicht selbst"), (owner, "Bot-Owner")):
        await cog.warn.callback(cog, c, target, reason="x"); assert needle in c.last, (target.id, c.last)
    lena.roles.append(g.get_role(1102))   # Lena auch Mod, aber Support(5)+Moderator(8) == Tom(8) -> gleich hoch
    await cog.warn.callback(cog, c, lena, reason="x"); assert "gleich hohe oder höhere Rolle" in c.last, c.last
    c2 = Ctx(g, lena); await cog.warn.callback(cog, c2, tom, reason="x"); assert "gleich hohe" in c2.last
    lena.roles.remove(g.get_role(1102))
    g.owner_id = 13
    await cog.warn.callback(cog, c, kai, reason="x"); assert "Server-Owner" in c.last
    g.owner_id = 1
    botm = types.SimpleNamespace(id=555, bot=True, display_name="Bot", top_role=g.default_role)
    assert cog.check_target(g, tom, botm) == "err_bot"
    # Owner darf alle (auch höhere Rollen)
    co = Ctx(g, owner); await cog.warn.callback(cog, co, tom, reason="Owner-Test")
    assert "Verwarnung **#3**" in co.last, co.last
    print("Prüfungen (Selbst, Bot-Owner, Server-Owner, Hierarchie, Bot, Owner-Bypass) OK")

    # --- Schwellen ---
    await gconf.timeout_at.set(2); await gconf.kick_at.set(4); await gconf.timeout_minutes.set(90)
    await cog.warn.callback(cog, c, kai, reason="zweite")   # 1 -> 2 : Timeout
    assert actions[-1][:2] == ("timeout", 13) and "Timeout (90 Min.)" in c.last, (actions, c.last)
    assert "Maßnahme" in W.SENT_DMS[-1][1]
    n = len(actions)
    await cog.warn.callback(cog, c, kai, reason="dritte")   # 2 -> 3 : nichts
    assert len(actions) == n, actions
    await cog.warn.callback(cog, c, kai, reason="2 vierte")  # 3 -> 5 : Kick (schwerste erreichte)
    assert actions[-1][:2] == ("kick", 13), actions
    await gconf.ban_at.set(6)
    await cog.warn.callback(cog, c, kai, reason="5 fünfte")  # 5 -> 10 : Bann
    assert actions[-1][:2] == ("ban", 13), actions
    assert cog.crossed_action({"timeout_at": 2, "kick_at": 4, "ban_at": 6}, 0, 10) == "ban"
    assert cog.crossed_action({"timeout_at": 0, "kick_at": 0, "ban_at": 0}, 0, 10) is None
    print("Schwellen Timeout/Kick/Bann OK")
    # Hierarchie-Schutz der Maßnahmen: Mia bekommt Rolle über dem Bot
    high = H.Role(g, 1199, "Chef", 30); g.roles.append(high); mia.roles.append(high)
    n = len(actions)
    await cog.warn.callback(cog, co, mia, reason="5 hoch")   # Owner verwarnt, 3 -> 8: Bann-Schwelle, aber Mia > Bot
    assert len(actions) == n and "nicht ausgeführt" in co.last and "meine" in co.last, co.last
    mia.roles.remove(high)
    # Moderator-Hierarchie (Owner bypass vs. Mod): Actor-Mod ohne Rolle
    assert cog.action_block_reason(g, kai, types.SimpleNamespace(id=50, top_role=g.default_role), "kick") == "why_mod_hierarchy"
    # Admin -> kein Timeout
    kai.guild_permissions = discord.Permissions(administrator=True)
    assert cog.action_block_reason(g, kai, tom, "timeout") == "why_admin_timeout"
    kai.guild_permissions = discord.Permissions.none()
    # fehlendes Bot-Recht
    g.me.guild_permissions = discord.Permissions.none()
    why = cog.action_block_reason(g, kai, tom, "ban"); assert why == "why_bot_perms:perm_ban"
    from rc.warns.warns import why_text
    assert "Mitglieder bannen" in why_text("de", why)
    g.me.guild_permissions = discord.Permissions.all()
    # Bot-Owner / Server-Owner nie
    assert cog.action_block_reason(g, owner, owner, "kick") == "why_bot_owner"
    g.owner_id = 13; assert cog.action_block_reason(g, kai, owner, "kick") == "why_guild_owner"; g.owner_id = 1
    # Discord lehnt ab -> kein Crash, Grund im Log
    async def ban_fail(member, **kw): raise L.forbidden()
    g.ban = ban_fail
    await gconf.set_raw("ban_at", value=1); await gconf.set_raw("timeout_at", value=0); await gconf.set_raw("kick_at", value=0)
    await cog.config.member(lena).warnings.set([])
    await cog.warn.callback(cog, c, lena, reason="abgelehnt")
    assert "Discord hat die Aktion abgelehnt" in c.last, c.last
    lg = [m for m in logs._messages.values()][-1].embeds[0]
    assert any("nicht ausgeführt" in f.value for f in lg.fields), [f.value for f in lg.fields]
    g.ban = ban
    for k in ("timeout_at", "kick_at", "ban_at"):
        await gconf.set_raw(k, value=0)
    print("Maßnahmen-Schutz (Bot-/Mod-Hierarchie, Admin-Timeout, Rechte, Owner, Discord-Fehler) OK")

    # --- DM geschlossen / DM aus ---
    kai.dm_closed = True
    await cog.warn.callback(cog, c, kai, reason="dm zu"); assert "DM konnte nicht" in c.last
    kai.dm_closed = False
    await gconf.dm_enabled.set(False); n = len(W.SENT_DMS)
    await cog.warn.callback(cog, c, kai, reason="ohne dm"); assert len(W.SENT_DMS) == n
    await gconf.dm_enabled.set(True)
    await gconf.dm_text.set("Hey {name}: {reason} ({points}/{total}) #{id} von {moderator}, bis {expires} {foo} {0}")
    await cog.warn.callback(cog, c, kai, reason="Text")
    dm = W.SENT_DMS[-1][1]; assert dm.startswith("Hey Kai: Text (1/") and "von Tom, bis nie {foo} {0}" in dm, dm
    await gconf.dm_text.set("")
    print("DM (geschlossen, aus, eigener Text mit Platzhaltern) OK")

    # --- Verfall ---
    await gconf.expiry_days.set(1)
    await cog.config.member(mia).warnings.set([])
    await cog.warn.callback(cog, c, mia, reason="verfällt")
    e = (await cog.member_entries(g, 14))[-1]
    assert e["expires"] and 86000 < e["expires"] - e["ts"] <= 86400
    assert await cog.active_points(g, 14) == 1
    async with cog.config.member(mia).warnings() as es:
        es[-1]["expires"] = int(time.time()) - 5
    assert await cog.active_points(g, 14) == 0
    await gconf.expiry_days.set(0)
    print("Verfall OK")

    # --- IDs parallel eindeutig ---
    res = await asyncio.gather(*(cog.add_warning(g, kai, tom, f"p{i}", 1) for i in range(25)))
    ids = [r["id"] for r in res]; assert len(set(ids)) == 25, ids
    allids = [e["id"] for _, e in await cog.all_entries(g)]; assert len(allids) == len(set(allids))
    print("25 parallele Verwarnungen -> eindeutige IDs OK")

    # --- unwarn / warnings / clearwarns ---
    wid = ids[0]
    await cog.unwarn.callback(cog, c, wid); assert f"#{wid}**" in c.last and "aufgehoben" in c.last, c.last
    await cog.unwarn.callback(cog, c, wid); assert "bereits aufgehoben" in c.last
    await cog.unwarn.callback(cog, c, 99999); assert "nicht gefunden" in c.last
    tom_w = (await cog.member_entries(g, 12))[-1]["id"]
    await cog.unwarn.callback(cog, c, tom_w); assert "Eigene Verwarnungen" in c.last
    ck = Ctx(g, kai)
    await cog.warnings_cmd.callback(cog, ck, None); assert isinstance(ck.last, discord.Embed) and "Kai" in ck.last.title
    await cog.warnings_cmd.callback(cog, ck, tom); assert "nur Moderatoren" in ck.last
    await cog.warnings_cmd.callback(cog, c, kai); assert isinstance(c.last, discord.Embed) and c.last.footer.text
    n = await cog.clear(g, 14, owner); assert n >= 1 and await cog.member_entries(g, 14) == []
    # clearwarns braucht Admin (Red-Dekorator)
    from redbot.core.commands.requires import PrivilegeLevel
    assert cog.clearwarns.requires.privilege_level == PrivilegeLevel.ADMIN
    assert cog.clearwarns.requires.user_perms.administrator
    print("unwarn / warnings / clearwarns OK")

    # --- Einstellungs-Befehle ---
    ca = Ctx(g, owner)
    await cog.ws_action.callback(cog, ca, "timeout", 3, 120); assert "Timeout (2 Std.)" in ca.last, ca.last
    await cog.ws_action.callback(cog, ca, "nuke", 3, None); assert "Punkte 0" in ca.last
    await cog.ws_action.callback(cog, ca, "timeout", 0, None); assert "aus" in ca.last
    await cog.ws_expiry.callback(cog, ca, 30); assert "30 Tage" in ca.last
    await cog.ws_expiry.callback(cog, ca, 0)
    await cog.ws_settings.callback(cog, ca); assert isinstance(ca.last, discord.Embed)
    await cog.ws_language.callback(cog, ca, "en"); assert "Language set" in ca.last
    await cog.ws_language.callback(cog, ca, "de")
    print("warnset OK")

    # --- Datenlöschung ---
    await cog.add_warning(g, kai, tom, "vor Löschung", 1)
    await cog.red_delete_data_for_user(requester="user", user_id=12)   # Tom: als Verwarnter löschen, als Mod anonymisieren
    assert await cog.member_entries(g, 12) == []
    kai_e = await cog.member_entries(g, 13)
    assert kai_e and all(e["mod_id"] != 12 for e in kai_e) and any(e["mod_name"] == "Gelöschter Nutzer" for e in kai_e)
    assert all(e.get("revoked_by") != 12 for e in kai_e)
    print("red_delete_data_for_user OK")

    # --- Dashboard ---
    client = TestClient(TestServer(app)); await client.start_server()
    oh = {"X-Test-User": "1"}; lh = {"X-Test-User": "11"}; th = {"X-Test-User": "12"}; kh = {"X-Test-User": "13"}
    r = await client.get("/cogs/warnings?guild=1000", headers=oh); t = await r.text()
    assert r.status == 200 and "Aktive Verwarnungen" in t and "Aufheben" in t and "wl-members" in t
    for tab in ("Verlauf", "Mitglied verwarnen", "Automatische Maßnahmen", "Einstellungen"):
        assert f"data-title='{tab}'" in t, tab
    active_rows = t.count("<tr>")
    r = await client.get("/cogs/warnings?guild=1000&filter=all", headers=oh); t2 = await r.text()
    assert t2.count("<tr>") > active_rows and "aufgehoben" in t2
    tok = csrf(t)
    # Verwarnen per Formular (Lena, Bearbeiten) – Name mit ID-Vorschlag
    r = await client.get("/cogs/warnings?guild=1000", headers=lh); tl = await r.text(); tkl = csrf(tl)
    r = await client.post("/cogs/warnings", headers=lh, allow_redirects=False, data={
        "csrf_token": tkl, "form": "warn", "guild": "1000", "member": "Kai (13)", "reason": "<b>XSS</b> Dashboard", "points": "2"})
    loc = r.headers["Location"]; assert "ok=" in loc and "Verwarnung" in loc, loc
    e = (await cog.member_entries(g, 13))[-1]
    assert e["mod_id"] == 11 and e["mod_name"] == "Lena" and e["points"] == 2 and e["source"] == "dashboard", e
    # gleiche Prüfungen: Lena -> Tom (höhere Rolle), Lena -> sich selbst, Owner, unbekannt, mehrdeutig
    for member, needle in (("12", "h%C3%B6here+Rolle"), ("Lena", "nicht+selbst"), ("1", "Bot-Owner"),
                           ("Niemand", "nicht+gefunden"), ("", "Mitglied+angeben")):
        r = await client.post("/cogs/warnings", headers=lh, allow_redirects=False, data={
            "csrf_token": tkl, "form": "warn", "guild": "1000", "member": member, "reason": "x", "points": "1"})
        assert "err=" in r.headers["Location"] and needle in r.headers["Location"], (member, r.headers["Location"])
    r = await client.post("/cogs/warnings", headers=lh, allow_redirects=False, data={
        "csrf_token": tkl, "form": "warn", "guild": "1000", "member": "13", "reason": "", "points": "1"})
    assert "Grund" in r.headers["Location"]
    r = await client.post("/cogs/warnings", headers=lh, allow_redirects=False, data={
        "csrf_token": tkl, "form": "warn", "guild": "1000", "member": "13", "reason": "x", "points": "0"})
    assert "Punkte" in r.headers["Location"]
    # Mehrdeutiger Name
    g.members.append(H.Member(g, 15, "Kai", [])); W.patch_members(bot)
    r = await client.post("/cogs/warnings", headers=lh, allow_redirects=False, data={
        "csrf_token": tkl, "form": "warn", "guild": "1000", "member": "kai", "reason": "x", "points": "1"})
    assert "eindeutig" in r.headers["Location"], r.headers["Location"]
    g.members.pop()
    # Tom (Ansehen): kein Aufheben-Button, POST abgelehnt
    r = await client.get("/cogs/warnings?guild=1000", headers=th); tt = await r.text()
    assert r.status == 200 and "Aufheben</span>" not in tt and "nur <b>Ansehen</b>" in tt
    n0 = len(await cog.member_entries(g, 13))
    r = await client.post("/cogs/warnings", headers=th, allow_redirects=False, data={
        "csrf_token": csrf(tt), "form": "warn", "guild": "1000", "member": "13", "reason": "x", "points": "1"})
    assert "Keine+Bearbeitungsrechte" in r.headers["Location"] and len(await cog.member_entries(g, 13)) == n0
    # Kai: kein Zugriff
    r = await client.get("/cogs/warnings?guild=1000", headers=kh, allow_redirects=False); assert r.status in (302, 403)
    # Aufheben (Owner)
    r = await client.post("/cogs/warnings", headers=oh, allow_redirects=False, data={
        "csrf_token": tok, "form": "revoke", "guild": "1000", "id": str(e["id"])})
    assert "aufgehoben" in r.headers["Location"], r.headers["Location"]
    assert [x for x in await cog.member_entries(g, 13) if x["id"] == e["id"]][0]["revoked_by"] == 1
    # Maßnahmen + Einstellungen
    r = await client.post("/cogs/warnings", headers=oh, allow_redirects=False, data={
        "csrf_token": tok, "form": "actions", "guild": "1000", "timeout_at": "3", "timeout_minutes": "30", "kick_at": "5", "ban_at": "0"})
    assert "ok=" in r.headers["Location"]
    c3 = await gconf.all(); assert (c3["timeout_at"], c3["timeout_minutes"], c3["kick_at"], c3["ban_at"]) == (3, 30, 5, 0)
    r = await client.post("/cogs/warnings", headers=oh, allow_redirects=False, data={
        "csrf_token": tok, "form": "actions", "guild": "1000", "timeout_at": "3", "timeout_minutes": "99999", "kick_at": "5"})
    assert "err=" in r.headers["Location"]
    r = await client.post("/cogs/warnings", headers=oh, allow_redirects=False, data={
        "csrf_token": tok, "form": "settings", "guild": "1000", "log_channel": str(ann.id), "mod_roles": ["1101", "1102"],
        "expiry_days": "14", "default_points": "2", "dm_text": "Hallo {name}", "language": "de"})
    assert "ok=" in r.headers["Location"], r.headers["Location"]
    c3 = await gconf.all()
    assert c3["log_channel"] == ann.id and c3["mod_roles"] == [1101, 1102] and c3["expiry_days"] == 14 and not c3["dm_enabled"]
    for bad in ({"log_channel": "5"}, {"mod_roles": "77"}, {"expiry_days": "-1"}, {"default_points": "0"}, {"language": "xx"}):
        d = {"csrf_token": tok, "form": "settings", "guild": "1000", "expiry_days": "0", "default_points": "1", "language": "de"}
        d.update(bad)
        r = await client.post("/cogs/warnings", headers=oh, allow_redirects=False, data=d)
        assert "err=" in r.headers["Location"], (bad, r.headers["Location"])
    # XSS im Verlauf escaped
    r = await client.get("/cogs/warnings?guild=1000&filter=all", headers=oh); t = await r.text()
    assert "<b>XSS</b>" not in t and "&lt;b&gt;XSS&lt;/b&gt;" in t
    # Owner, der nicht auf dem Server ist (Server 2000 ohne Kai): Warn per Actor
    g2 = bot.guilds[1]
    g2.members = [m for m in g2.members if m.id != 1]
    r = await client.get("/cogs/warnings?guild=2000", headers=oh); tok2 = csrf(await r.text())
    r = await client.post("/cogs/warnings", headers=oh, allow_redirects=False, data={
        "csrf_token": tok2, "form": "warn", "guild": "2000", "member": "11", "reason": "Owner extern", "points": "1"})
    assert "ok=" in r.headers["Location"], r.headers["Location"]
    print("Dashboard (Verlauf/Filter, Verwarnen mit Prüfungen, Aufheben, Maßnahmen, Einstellungen, Rechte, XSS) OK")
    await client.close()
    print("ALLE WARNS-TESTS OK")

asyncio.run(main())
