"""Harness für die fivemadmin-WebCore-Seite: Standard-Harness (wc_harness.make_app) + AdminPanel.

Der eigene Webserver und der Backup-Task des Cogs werden NICHT gestartet; die SQLite-DB liegt in
einem Temp-Ordner (db.set_data_dir über gepatchtes cog_data_path). Testdaten: Bans, Aktionen
(inkl. offener Aufträge), Server-State, role_map/user_map, Secrets (API-Key/OAuth) zum Leck-Test.
Start: python tests/fivem_harness.py [port]
"""
import asyncio, json, time, types
import bootstrap
import wc_harness as H

SECRET_API_KEY = "TESTAPIKEY-SECRET-9f8e7d6c5b4a"
SECRET_OAUTH = "OAUTH-CLIENT-SECRET-zyx987"
PUBLIC_URL = "https://panel.example.test"


async def make_app():
    wc, bot, app = await H.make_app()
    bot.loop = asyncio.get_running_loop()
    bot.sent = []  # (channel_id, text) – alles, was der Cog in Discord-Kanäle schreibt

    def _mk_send(ch):
        async def send(content=None, **kw):
            bot.sent.append((ch.id, content))
        return send
    for g in bot.guilds:
        for ch in g.text_channels:
            ch.send = _mk_send(ch)
    bot.get_channel = lambda cid: next((c for g in bot.guilds for c in g.text_channels if c.id == cid), None)

    import rc.fivemadmin.adminpanel as ap
    tmp = bootstrap.tmpdir("fivem_db_")
    ap.cog_data_path = lambda cog: tmp

    async def _noop(self):
        return None
    ap.AdminPanel._start_webserver = _noop
    ap.AdminPanel._backup_loop = _noop
    cog = ap.AdminPanel(bot)
    bot._cogs["AdminPanel"] = cog
    await cog.cog_load()                       # registriert die Seite bei WebCore
    cog.runner = types.SimpleNamespace()       # „Webserver läuft“ simulieren
    await seed(cog, bot)
    await cog._resolve_settings()
    # WebCore-Rollen-Rechte: Support (Lena) = Bearbeiten, Moderator (Tom) = Ansehen
    await wc.config.role_perms.set({"1000": {"1101": {"fivemadmin": "edit"}, "1102": {"fivemadmin": "view"}},
                                    "2000": {"2101": {"fivemadmin": "view"}}})
    return wc, bot, app, cog


async def seed(cog, bot):
    from rc.fivemadmin import db
    await cog.config.api_key.set(SECRET_API_KEY)
    await cog.config.oauth_client_id.set("123456789012345678")
    await cog.config.oauth_client_secret.set(SECRET_OAUTH)
    await cog.config.public_url.set(PUBLIC_URL)
    await cog.config.audit_channel.set(1004)   # #logs auf „Matters Community“
    await cog.config.guild_from_id(1000).role_map.set({"1101": "support", "1102": "moderator", "1999": "admin"})
    await cog.config.guild_from_id(1000).user_map.set({"14": "editor"})
    await cog.config.guild_from_id(2000).role_map.set({"2101": "support"})
    now = time.time()
    db.add_ban("ABC12345", "license:aa11", "555", "Kevin Krawall", "Cheating (Aimbot)", "web:Matters86", None)
    db.add_ban("XYZ98765", "license:bb22", None, "Lisa Lärm", "RDM im Stadtpark", "discord:Tom", now + 48 * 3600)
    db.add_ban("QWE55555", None, None, "Otto <script>alert(1)</script>", "Beleidigung & Spam", "web:Tom", now + 5 * 3600)
    db.add_ban("MNO11111", "license:dd44", None, "Dieter Dupe", "Item-Dupe", "web:Matters86", now + 20 * 24 * 3600)
    def act(t, target, params, by, status=None, result=None):
        aid = db.add_action(t, target, json.dumps(params) if params is not None else None, by)
        if status:
            db.mark_action_result(aid, status, result)
        return aid
    act("teleport", "ABC12345", {"to_spieler": "XYZ98765"}, "web:Lena", "done", "ok")
    act("money", "XYZ98765", {"op": "add", "amount": 25000, "account": "bank"}, "discord:Matters86", "done", "ok")
    act("give_item", "MNO11111", {"item": "water", "count": 5}, "web:Tom", "failed", "Spieler offline")
    act("ban", "ABC12345", {"hours": 0, "reason": "Cheating (Aimbot)"}, "web:Matters86", "done", "{}")
    act("heal", "LMN22222", None, "web:Lena", "done", "ok")
    act("kick", "QWE55555", {"reason": "Spam"}, "discord:Tom")        # offen
    act("announce", "*", {"message": "Restart in 10 Minuten"}, "web:Matters86")  # offen
    act("revive", "RST33333", None, "web:Lena")                         # offen
    db.save_server_state({"server_name": "Matters RP | Whitelist", "max_slots": 64, "uptime": 7200,
                          "players": [{"id": i, "name": f"Spieler {i}", "citizenid": f"CID{i:05d}"} for i in range(1, 24)]})


if __name__ == "__main__":
    H.main(make_app)
