"""
AdminPanel Cog
--------------
Discord-Commands + eingebettetes Webpanel mit Discord-Rollen-Login.

Login-Flow:
  1) Nutzer tippt auf dem Server: !ap login
  2) Bot schickt per DM einen Einmal-Link (5 Min gültig)
  3) Panel tauscht den Token gegen eine Session (12 h)
  4) Berechtigungen werden bei JEDEM Request live aus den aktuellen
     Discord-Rollen berechnet -> Rolle entzogen = sofort wirksam.

Berechtigungs-Presets (Rollen-Mapping per `!ap roles set <preset> @Rolle`):
  support:   Spielerliste, Teleport, Heal, Revive, Fahrzeug einparken
  moderator: support + Kick, Ansage
  admin:     moderator + Geld
  editor:    Server-Status-Dashboard (additiv kombinierbar)

Discord-Administratoren haben automatisch alle Rechte.

ENV:
  ADMINPANEL_API_KEY     Key für die FiveM-Bridge (Maschine-zu-Maschine)
  ADMINPANEL_WEB_PORT    Port des Webpanels (Default 8099)
  ADMINPANEL_PUBLIC_URL  Öffentliche Panel-URL für die Login-Links,
                         z. B. https://panel.deinedomain.tld
"""

import json
import os
import logging
import hmac
import time
import secrets
import urllib.parse

import aiohttp
import discord
from aiohttp import web
from redbot.core import commands, Config

from . import db

log = logging.getLogger("red.adminpanel")

# ENV dienen nur noch als DEFAULTS. Zur Laufzeit überschreiben die per
# Discord-Befehl gesetzten Config-Werte diese (self.api_key usw.).
DEFAULT_API_KEY = os.environ.get("ADMINPANEL_API_KEY", "CHANGE_ME")
DEFAULT_WEB_PORT = int(os.environ.get("ADMINPANEL_WEB_PORT", "8099"))
DEFAULT_PUBLIC_URL = os.environ.get("ADMINPANEL_PUBLIC_URL", "").rstrip("/")
DEFAULT_MONEY_MAX = int(os.environ.get("ADMINPANEL_MONEY_MAX", "50000"))
DEFAULT_ITEM_MAX = int(os.environ.get("ADMINPANEL_ITEM_MAX", "100"))

# Aktionen, die immer zusätzlich in den Audit-Channel geloggt werden
# (die "damit könnte man Schaden anrichten"-Menge).
SENSITIVE_ACTIONS = {
    "money", "give_item", "remove_item", "park_all",
    "set_job", "set_gang", "ban",
}

# ------------------------------------------------------------------
# Berechtigungen
# ------------------------------------------------------------------

_SUPPORT = {"view_players", "teleport", "heal", "revive", "car_to_garage", "view_inventory", "message"}
_MODERATOR = _SUPPORT | {"kick", "ban", "announce", "view_logs", "notes", "setjob"}
_ADMIN = _MODERATOR | {"money", "items", "view_stats", "park_all", "audit"}

PRESETS = {
    "support": _SUPPORT,
    "moderator": _MODERATOR,
    "admin": _ADMIN,
    "editor": {"server_status", "view_stats"},
}

# Welche Berechtigung braucht welcher Action-Type?
ACTION_PERMISSION = {
    "teleport": "teleport",
    "teleport_coords": "teleport",
    "car_to_garage": "car_to_garage",
    "get_vehicles": "car_to_garage",
    "heal": "heal",
    "revive": "revive",
    "kick": "kick",
    "announce": "announce",
    "money": "money",
    "give_item": "items",
    "remove_item": "items",
    "get_inventory": "view_inventory",
    "get_stats": "view_stats",
    "search_player": "view_players",
    "set_job": "setjob",
    "set_gang": "setjob",
    "notify": "message",
    "park_all": "park_all",
    "ban": "ban",
    "diag": "server_status",
}


class AdminPanel(commands.Cog):
    """FiveM-Server-Verwaltung per Discord und Webbrowser."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA0D141)
        self.config.register_guild(role_map={})  # {role_id(str): preset_name}
        self.config.register_global(
            alert_channel=None,
            audit_channel=None,
            locked=False,
            api_key=None,      # None => ENV/Default
            web_port=None,
            public_url=None,
            money_max=None,
            item_max=None,
            oauth_client_id=None,
            oauth_client_secret=None,
        )
        # OAuth-CSRF-States (state -> Ablaufzeit), kurzlebig, nur im RAM
        self._oauth_states: dict = {}
        # Laufzeit-Settings (werden in _start_webserver aus Config+ENV aufgelöst)
        self.api_key = DEFAULT_API_KEY
        self.web_port = DEFAULT_WEB_PORT
        self.public_url = DEFAULT_PUBLIC_URL
        self.money_max = DEFAULT_MONEY_MAX
        self.item_max = DEFAULT_ITEM_MAX
        db.init_db()
        self.runner: web.AppRunner | None = None
        self._web_task = self.bot.loop.create_task(self._start_webserver())
        self._backup_task = self.bot.loop.create_task(self._backup_loop())

    async def _resolve_settings(self):
        """Effektive Settings = Config-Wert, sonst ENV/Default."""
        self.api_key = await self.config.api_key() or DEFAULT_API_KEY
        self.web_port = await self.config.web_port() or DEFAULT_WEB_PORT
        self.public_url = (await self.config.public_url() or DEFAULT_PUBLIC_URL).rstrip("/")
        self.money_max = await self.config.money_max() or DEFAULT_MONEY_MAX
        self.item_max = await self.config.item_max() or DEFAULT_ITEM_MAX

    def _key_ok(self, provided: str) -> bool:
        """Konstanter-Zeit-Vergleich gegen Timing-Angriffe."""
        return hmac.compare_digest(str(provided or ""), self.api_key)

    def cog_unload(self):
        if self._web_task:
            self._web_task.cancel()
        if getattr(self, "_backup_task", None):
            self._backup_task.cancel()
        if self.runner:
            self.bot.loop.create_task(self.runner.cleanup())

    async def _backup_loop(self):
        """Sichert die DB alle 24h automatisch."""
        import asyncio
        await self.bot.wait_until_ready()
        while True:
            try:
                await asyncio.sleep(24 * 3600)
                path, count = db.backup_db()
                log.info(f"AdminPanel DB-Backup erstellt: {path} ({count} Backups vorhanden)")
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"DB-Backup fehlgeschlagen: {e}")

    # --------------------------------------------------------------
    # Berechtigungs-Auflösung (live aus Discord-Rollen)
    # --------------------------------------------------------------

    async def member_permissions(self, member: discord.Member) -> set:
        perms: set = set()
        if member.guild_permissions.administrator:
            return _ADMIN | PRESETS["editor"]
        role_map = await self.config.guild(member.guild).role_map()
        for role in member.roles:
            preset = role_map.get(str(role.id))
            if preset in PRESETS:
                perms |= PRESETS[preset]
        return perms

    async def session_permissions(self, session: dict):
        """Session -> (member, permissions). Live-Check gegen Discord."""
        guild = self.bot.get_guild(int(session["guild_id"]))
        if not guild:
            return None, set()
        member = guild.get_member(int(session["user_id"]))
        if member is None:
            try:
                member = await guild.fetch_member(int(session["user_id"]))
            except (discord.NotFound, discord.HTTPException):
                return None, set()
        return member, await self.member_permissions(member)

    # --------------------------------------------------------------
    # Webserver
    # --------------------------------------------------------------

    async def _start_webserver(self):
        await self.bot.wait_until_ready()
        await self._resolve_settings()
        app = web.Application(middlewares=[self._auth_middleware])
        # Panel (Browser)
        app.router.add_get("/", self.http_index)
        # PWA (Handy-App)
        pwa_dir = os.path.join(os.path.dirname(__file__), "pwa")
        app.router.add_get("/manifest.json",
                           lambda r: web.FileResponse(os.path.join(pwa_dir, "manifest.json")))
        app.router.add_get("/sw.js",
                           lambda r: web.FileResponse(os.path.join(pwa_dir, "sw.js")))
        app.router.add_static("/icons/", os.path.join(pwa_dir, "icons"))
        app.router.add_post("/api/auth/login", self.http_login)
        app.router.add_get("/api/auth/discord", self.http_oauth_start)
        app.router.add_get("/api/auth/callback", self.http_oauth_callback)
        app.router.add_get("/api/panel/state", self.http_panel_state)
        app.router.add_get("/api/panel/catalog", self.http_panel_catalog)
        app.router.add_get("/api/panel/player_history", self.http_player_history)
        app.router.add_post("/api/panel/notes", self.http_add_note)
        app.router.add_post("/api/panel/notes/delete", self.http_delete_note)
        app.router.add_get("/api/panel/bans", self.http_get_bans)
        app.router.add_post("/api/panel/unban", self.http_unban)
        app.router.add_get("/api/panel/audit", self.http_audit)
        app.router.add_get("/api/panel/roles", self.http_get_role_map)
        app.router.add_post("/api/panel/roles", self.http_set_role_map)
        app.router.add_post("/api/panel/action", self.http_panel_action)
        # Bridge (FiveM-Server)
        app.router.add_post("/api/bridge/sync", self.http_bridge_sync)
        app.router.add_post("/api/bridge/catalog", self.http_bridge_catalog)
        app.router.add_post("/api/actions/result", self.http_bridge_result)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.web_port)
        await site.start()
        log.info(f"AdminPanel Webserver läuft auf Port {self.web_port}")
        if self.api_key == "CHANGE_ME":
            log.warning(
                "⚠️ Kein API-Key gesetzt (Default 'CHANGE_ME')! Der Kanal zur FiveM-Bridge ist ungeschützt. "
                "Setze ihn per Discord: `!ap config key` (generiert einen und schickt ihn dir per DM)."
            )

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        path = request.path
        if path.startswith("/api/bridge/") or path.startswith("/api/actions/"):
            if not self._key_ok(request.headers.get("X-API-Key")):
                return web.json_response({"error": "unauthorized"}, status=401)
        elif path.startswith("/api/panel/"):
            session = db.get_session(request.headers.get("X-Session", ""))
            if not session:
                return web.json_response({"error": "unauthorized"}, status=401)
            member, perms = await self.session_permissions(session)
            if member is None or not perms:
                return web.json_response({"error": "unauthorized"}, status=401)
            request["session"] = session
            request["member"] = member
            request["perms"] = perms
        return await handler(request)

    # ---------------- Browser-Endpoints ----------------

    async def http_index(self, request: web.Request):
        html_path = os.path.join(os.path.dirname(__file__), "panel.html")
        with open(html_path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")

    # ---------------- Discord OAuth2 ("Mit Discord anmelden") ----------------

    async def _oauth_creds(self):
        cid = await self.config.oauth_client_id()
        secret = await self.config.oauth_client_secret()
        return (str(cid), secret) if cid and secret else (None, None)

    def _oauth_redirect_uri(self) -> str:
        return f"{self.public_url}/api/auth/callback"

    async def http_oauth_start(self, request: web.Request):
        """Leitet zu Discords Autorisierungsseite weiter."""
        cid, secret = await self._oauth_creds()
        if not cid or not secret or not self.public_url:
            return web.HTTPFound("/?oauth=missing")
        # CSRF-Schutz: zufälliger State, 10 Minuten gültig
        now = time.time()
        self._oauth_states = {s: exp for s, exp in self._oauth_states.items() if exp > now}
        state = secrets.token_urlsafe(24)
        self._oauth_states[state] = now + 600
        params = urllib.parse.urlencode({
            "client_id": cid,
            "redirect_uri": self._oauth_redirect_uri(),
            "response_type": "code",
            "scope": "identify",
            "state": state,
        })
        return web.HTTPFound(f"https://discord.com/oauth2/authorize?{params}")

    async def http_oauth_callback(self, request: web.Request):
        """Discord-Rücksprung: Code gegen User tauschen, Rechte prüfen, einloggen."""
        if request.query.get("error"):
            return web.HTTPFound("/?oauth=denied")
        state = request.query.get("state", "")
        if self._oauth_states.pop(state, 0) < time.time():
            return web.HTTPFound("/?oauth=state")
        code = request.query.get("code", "")
        cid, secret = await self._oauth_creds()
        if not code or not cid:
            return web.HTTPFound("/?oauth=missing")

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    "https://discord.com/api/oauth2/token",
                    data={
                        "client_id": cid,
                        "client_secret": secret,
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self._oauth_redirect_uri(),
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as resp:
                    tok = await resp.json()
                access = tok.get("access_token")
                if not access:
                    log.warning(f"OAuth-Token-Tausch fehlgeschlagen: {tok.get('error_description') or tok}")
                    return web.HTTPFound("/?oauth=exchange")
                async with http.get(
                    "https://discord.com/api/users/@me",
                    headers={"Authorization": f"Bearer {access}"},
                ) as resp:
                    me = await resp.json()
        except aiohttp.ClientError:
            return web.HTTPFound("/?oauth=exchange")

        user_id = me.get("id")
        if not user_id:
            return web.HTTPFound("/?oauth=exchange")

        # Auf welchem Server hat dieser User Panel-Rechte? (Bot-seitig, kein extra Scope nötig)
        for guild in self.bot.guilds:
            member = guild.get_member(int(user_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(user_id))
                except (discord.NotFound, discord.HTTPException):
                    continue
            perms = await self.member_permissions(member)
            if perms:
                token = db.create_login_token(str(user_id), str(guild.id), member.display_name)
                return web.HTTPFound(f"/?login={token}")

        return web.HTTPFound("/?oauth=noperm")

    async def http_login(self, request: web.Request):
        data = await request.json()
        session = db.redeem_login_token(str(data.get("token", "")))
        if not session:
            return web.json_response({"error": "invalid_token"}, status=401)
        member, perms = await self.session_permissions(session)
        if member is None or not perms:
            return web.json_response({"error": "no_permissions"}, status=403)
        return web.json_response({
            "session": session["token"],
            "name": session["display_name"],
            "permissions": sorted(perms),
        })

    async def http_panel_state(self, request: web.Request):
        perms = request["perms"]
        state = db.get_server_state()
        payload = {
            "permissions": sorted(perms),
            "name": request["session"]["display_name"],
            "actions": db.get_recent_actions(),
            "server": None,
            "limits": {"money": self.money_max, "item": self.item_max},
            "locked": await self.config.locked(),
            "is_admin": request["member"].guild_permissions.administrator,
        }
        if state:
            server = {
                "synced_at": state.get("synced_at"),
                "player_count": len(state.get("players", [])),
                "max_slots": state.get("max_slots"),
                "server_name": state.get("server_name"),
            }
            if "view_players" in perms:
                guild = request["member"].guild
                enriched = []
                for p in state.get("players", []):
                    p = dict(p)
                    did = p.get("discord")
                    if did and str(did).isdigit():
                        m = guild.get_member(int(did))
                        if m:
                            p["discord_name"] = m.display_name
                    enriched.append(p)
                server["players"] = enriched
            if "server_status" in perms:
                server["uptime"] = state.get("uptime")
                server["resources_total"] = state.get("resources_total")
                server["resources_not_running"] = state.get("resources_not_running", [])
            payload["server"] = server
        if "view_logs" in perms:
            payload["events"] = db.get_recent_events(60)
        return web.json_response(payload)

    async def http_panel_action(self, request: web.Request):
        data = await request.json()
        action_type = data.get("action_type")
        target = str(data.get("target", "")).strip()
        params = data.get("params") or {}

        needed = ACTION_PERMISSION.get(action_type)
        if not needed:
            return web.json_response({"error": "ungültiger action_type"}, status=400)
        if needed not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        if not target:
            return web.json_response({"error": "target fehlt"}, status=400)

        # Lockdown: nur noch Diagnose erlaubt, alle handelnden Aktionen blockiert
        if action_type != "diag" and await self.config.locked():
            return web.json_response({"error": "🔒 Panel im Lockdown – Aktionen gesperrt"}, status=423)

        # Sicherheits-Limits: schützen vor kompromittierten Sessions / Vertippern
        if action_type == "money":
            amount = int(params.get("amount") or 0)
            if amount > self.money_max:
                return web.json_response(
                    {"error": f"Limit überschritten: max. {self.money_max:,} $ pro Aktion".replace(",", ".")},
                    status=400)
        if action_type in ("give_item", "remove_item"):
            count = int(params.get("count") or 0)
            if count > self.item_max:
                return web.json_response(
                    {"error": f"Limit überschritten: max. {self.item_max} Stück pro Aktion"},
                    status=400)

        member = request["member"]
        action_id = db.add_action(
            action_type, target, json.dumps(params),
            f"web:{member.display_name}",
        )
        return web.json_response({"ok": True, "id": action_id})

    # ---------------- Bridge-Endpoints (FiveM) ----------------

    async def http_bridge_sync(self, request: web.Request):
        """Ein Roundtrip: FiveM liefert Server-State + Events, bekommt offene Actions + Ban-Liste."""
        data = await request.json()
        state = data.get("state")
        if isinstance(state, dict):
            db.save_server_state(state)
        events = data.get("events")
        if isinstance(events, list) and events:
            db.add_events(events[:100])
            await self._dispatch_alerts(events[:100])
        # Bans an die Bridge, damit sie beim Connect enforced werden können
        bans = [
            {"license": b.get("license"), "discord": b.get("discord"),
             "citizenid": b.get("citizenid"), "reason": b.get("reason"),
             "expires_at": b.get("expires_at")}
            for b in db.get_active_bans()
        ]
        # Im Lockdown werden keine offenen Aktionen ausgeliefert (Not-Aus).
        actions = [] if await self.config.locked() else db.get_pending_actions()
        return web.json_response({"actions": actions, "bans": bans})

    async def _dispatch_alerts(self, events: list):
        """Postet alert-/warn-Events sofort in den konfigurierten Discord-Channel."""
        channel_id = await self.config.alert_channel()
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            return
        colors = {"alert": discord.Color.red(), "warn": discord.Color.orange()}
        for e in events:
            sev = e.get("severity")
            if sev not in colors:
                continue
            who = e.get("name") or "?"
            if e.get("citizenid"):
                who += f" (`{e['citizenid']}`)"
            embed = discord.Embed(
                title=("🚨 " if sev == "alert" else "⚠️ ") + str(e.get("type", "event")),
                description=f"**{who}**\n{e.get('message', '')}",
                color=colors[sev],
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                log.warning("Alert konnte nicht in den Channel gesendet werden.")

    async def http_player_history(self, request: web.Request):
        cid = (request.query.get("cid") or "").strip()
        if not cid:
            return web.json_response({"error": "cid fehlt"}, status=400)
        payload = {
            "actions": db.get_actions_for(cid),
            "events": [],
            "notes": db.get_notes(cid),
            "can_note": "notes" in request["perms"],
            "can_ban": "ban" in request["perms"],
            "ban": db.get_ban(cid),
        }
        if "view_logs" in request["perms"]:
            payload["events"] = db.get_events_for(cid)
        return web.json_response(payload)

    async def http_add_note(self, request: web.Request):
        if "notes" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        data = await request.json()
        cid = str(data.get("cid", "")).strip()
        kind = data.get("kind")
        text = str(data.get("text", "")).strip()
        if not cid or kind not in ("note", "warn") or not text:
            return web.json_response({"error": "cid/kind/text fehlt"}, status=400)
        note_id = db.add_note(cid, kind, text[:1000], f"web:{request['member'].display_name}")
        return web.json_response({"ok": True, "id": note_id})

    async def http_delete_note(self, request: web.Request):
        if "notes" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        data = await request.json()
        note_id = data.get("id")
        if not isinstance(note_id, int):
            return web.json_response({"error": "id fehlt"}, status=400)
        return web.json_response({"ok": db.delete_note(note_id)})

    async def http_get_bans(self, request: web.Request):
        if "ban" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        return web.json_response({"bans": db.get_active_bans()})

    async def http_unban(self, request: web.Request):
        if "ban" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        data = await request.json()
        cid = str(data.get("cid", "")).strip()
        if not cid:
            return web.json_response({"error": "cid fehlt"}, status=400)
        removed = db.remove_ban(cid)
        if removed:
            await self._audit(f"🔓 **Unban** · `{cid}` · von {request['member'].display_name}")
        return web.json_response({"ok": removed})

    async def http_audit(self, request: web.Request):
        if "audit" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        return web.json_response({
            "actions": db.get_actions_audit(),
            "bans": db.get_active_bans(),
        })

    # -------- Rollen-Verwaltung (NUR Discord-Administratoren) --------

    async def http_get_role_map(self, request: web.Request):
        member = request["member"]
        if not member.guild_permissions.administrator:
            return web.json_response({"error": "Nur Discord-Administratoren"}, status=403)
        guild = member.guild
        role_map = await self.config.guild(guild).role_map()
        roles = []
        for r in sorted(guild.roles, key=lambda x: -x.position):
            if r.is_default() or r.managed:   # @everyone und Bot-Rollen ausblenden
                continue
            roles.append({
                "id": str(r.id),
                "name": r.name,
                "color": f"#{r.color.value:06x}" if r.color.value else None,
                "members": len(r.members),
                "preset": role_map.get(str(r.id)),
            })
        return web.json_response({"roles": roles, "presets": sorted(PRESETS.keys())})

    async def http_set_role_map(self, request: web.Request):
        member = request["member"]
        if not member.guild_permissions.administrator:
            return web.json_response({"error": "Nur Discord-Administratoren"}, status=403)
        data = await request.json()
        role_id = str(data.get("role_id", "")).strip()
        preset = data.get("preset") or None
        if preset is not None and preset not in PRESETS:
            return web.json_response({"error": "Unbekanntes Preset"}, status=400)
        guild = member.guild
        role = guild.get_role(int(role_id)) if role_id.isdigit() else None
        if role is None:
            return web.json_response({"error": "Rolle nicht gefunden"}, status=400)
        async with self.config.guild(guild).role_map() as role_map:
            if preset:
                role_map[role_id] = preset
            else:
                role_map.pop(role_id, None)
        await self._audit(f"🔧 **Rollen-Mapping** · @{role.name} → {preset or '— entfernt'} · von {member.display_name} (Panel)")
        return web.json_response({"ok": True})

    async def http_bridge_catalog(self, request: web.Request):
        data = await request.json()
        items = data.get("items")
        if isinstance(items, list):
            db.save_catalog({"items": items[:5000]})
        return web.json_response({"ok": True})

    async def http_panel_catalog(self, request: web.Request):
        if "items" not in request["perms"] and "view_inventory" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        return web.json_response(db.get_catalog() or {"items": []})

    async def http_bridge_result(self, request: web.Request):
        data = await request.json()
        action_id = data.get("id")
        if not action_id:
            return web.json_response({"error": "id fehlt"}, status=400)
        status = data.get("status", "failed")
        result = data.get("result", "")
        db.mark_action_result(action_id, status, result)

        # Name -> CID: aufgelöstes Target übernehmen (wichtig für Akte, Audit und Bans)
        resolved = data.get("resolved_target")
        if resolved:
            db.update_action_target(action_id, str(resolved))

        action = db.get_action(action_id)
        if action:
            if action["action_type"] == "ban" and status == "done":
                self._finalize_ban(action, result)
            if action["action_type"] in SENSITIVE_ACTIONS:
                await self._audit_action(action)
        return web.json_response({"ok": True})

    def _finalize_ban(self, action, result):
        try:
            info = json.loads(result or "{}")
        except (ValueError, TypeError):
            info = {}
        try:
            params = json.loads(action.get("params") or "{}")
        except (ValueError, TypeError):
            params = {}
        hours = params.get("hours")
        expires_at = None
        if hours and int(hours) > 0:
            expires_at = time.time() + int(hours) * 3600
        db.add_ban(
            citizenid=action["target"],
            license=info.get("license"),
            discord=info.get("discord"),
            name=info.get("name"),
            reason=params.get("reason") or "Kein Grund angegeben",
            banned_by=action.get("created_by") or "unbekannt",
            expires_at=expires_at,
        )

    async def _audit(self, text: str):
        channel_id = await self.config.audit_channel()
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass

    async def _audit_action(self, action):
        try:
            params = json.loads(action.get("params") or "{}")
        except (ValueError, TypeError):
            params = {}
        who = (action.get("created_by") or "?").replace("web:", "🖥 ").replace("discord:", "💬 ")
        icons = {"money": "💰", "give_item": "📦", "remove_item": "📦", "park_all": "🅿️",
                 "set_job": "👔", "set_gang": "🔫", "ban": "🔨"}
        detail = ""
        if action["action_type"] == "money":
            detail = f"{params.get('op', '?')} {params.get('amount', '?')}$ ({params.get('account', '?')})"
        elif action["action_type"] in ("give_item", "remove_item"):
            detail = f"{params.get('item', '?')} ×{params.get('count', '?')}"
        elif action["action_type"] in ("set_job", "set_gang"):
            detail = f"{params.get('job') or params.get('gang', '?')} (Grade {params.get('grade', 0)})"
        elif action["action_type"] == "ban":
            hrs = params.get("hours")
            detail = ("permanent" if not hrs or int(hrs) == 0 else f"{hrs}h") + f" · {params.get('reason', '')}"
        status_icon = "✅" if action["status"] == "done" else "❌"
        await self._audit(
            f"{icons.get(action['action_type'], '•')} **{action['action_type']}** {status_icon}\n"
            f"Ziel: `{action['target']}` · {detail}\nDurch: {who}"
        )

    # --------------------------------------------------------------
    # Discord-Commands
    # --------------------------------------------------------------

    async def _require(self, ctx: commands.Context, permission: str) -> bool:
        if ctx.guild is None:
            await ctx.send("Bitte auf dem Server nutzen, nicht per DM.")
            return False
        perms = await self.member_permissions(ctx.author)
        if permission not in perms:
            await ctx.send("❌ Dafür fehlt dir die Berechtigung.")
            return False
        return True

    @commands.group(name="ap")
    async def ap(self, ctx: commands.Context):
        """Adminpanel-Befehle."""

    # ---- Login ----

    @ap.command(name="login")
    @commands.guild_only()
    async def ap_login(self, ctx: commands.Context):
        """Schickt dir per DM einen Einmal-Link für das Webpanel (5 Min gültig)."""
        perms = await self.member_permissions(ctx.author)
        if not perms:
            return await ctx.send("❌ Du hast keine Panel-Berechtigung. "
                                  "Ein Admin kann deine Rolle mit `!ap roles set` freischalten.")
        token = db.create_login_token(
            str(ctx.author.id), str(ctx.guild.id), ctx.author.display_name
        )
        if self.public_url:
            text = (f"🔑 Dein Login-Link (5 Min gültig, einmalig):\n"
                    f"{self.public_url}/?login={token}")
        else:
            text = (f"🔑 Dein Login-Token (5 Min gültig, einmalig):\n`{token}`\n"
                    f"Im Panel unter „Anmelden“ einfügen.")
        try:
            await ctx.author.send(text)
            await ctx.send("📬 Login-Link ist in deinen DMs.")
        except discord.Forbidden:
            await ctx.send("❌ Ich kann dir keine DM schicken – bitte DMs für diesen Server erlauben.")

    # ---- Rollen-Verwaltung ----

    @ap.group(name="roles")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def ap_roles(self, ctx: commands.Context):
        """Rollen-Berechtigungen verwalten (nur Discord-Admins)."""

    @ap_roles.command(name="set")
    async def ap_roles_set(self, ctx: commands.Context, preset: str, role: discord.Role):
        """Preset einer Rolle zuweisen. Presets: support, moderator, admin, editor"""
        preset = preset.lower()
        if preset not in PRESETS:
            return await ctx.send(f"Unbekanntes Preset. Verfügbar: {', '.join(PRESETS)}")
        async with self.config.guild(ctx.guild).role_map() as role_map:
            role_map[str(role.id)] = preset
        await ctx.send(f"✅ {role.mention} → **{preset}** "
                       f"({', '.join(sorted(PRESETS[preset]))})")

    @ap_roles.command(name="remove")
    async def ap_roles_remove(self, ctx: commands.Context, role: discord.Role):
        """Berechtigung einer Rolle entfernen."""
        async with self.config.guild(ctx.guild).role_map() as role_map:
            removed = role_map.pop(str(role.id), None)
        await ctx.send("✅ Entfernt." if removed else "Diese Rolle hatte kein Preset.")

    @ap_roles.command(name="list")
    async def ap_roles_list(self, ctx: commands.Context):
        """Zeigt alle Rollen-Zuweisungen."""
        role_map = await self.config.guild(ctx.guild).role_map()
        if not role_map:
            return await ctx.send("Keine Rollen zugewiesen. `!ap roles set support @Rolle`")
        lines = []
        for role_id, preset in role_map.items():
            role = ctx.guild.get_role(int(role_id))
            lines.append(f"• {role.mention if role else f'gelöschte Rolle ({role_id})'} → **{preset}**")
        await ctx.send("\n".join(lines))

    # ---- Support-Aktionen ----

    @ap.command(name="tp")
    async def ap_tp(self, ctx: commands.Context, spieler: str, target_spieler: str):
        """Teleportiert Spieler A zu Spieler B. Beispiel: !ap tp ABC123 XYZ789"""
        if not await self._require(ctx, "teleport"):
            return
        db.add_action("teleport", spieler,
                      json.dumps({"to_spieler": target_spieler}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Teleport `{spieler}` → `{target_spieler}` angelegt.")

    @ap.command(name="heal")
    async def ap_heal(self, ctx: commands.Context, spieler: str):
        """Heilt einen Spieler vollständig."""
        if not await self._require(ctx, "heal"):
            return
        db.add_action("heal", spieler, None, f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Heal für `{spieler}` angelegt.")

    @ap.command(name="revive")
    async def ap_revive(self, ctx: commands.Context, spieler: str):
        """Belebt einen Spieler wieder."""
        if not await self._require(ctx, "revive"):
            return
        db.add_action("revive", spieler, None, f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Revive für `{spieler}` angelegt.")

    @ap.command(name="kick")
    async def ap_kick(self, ctx: commands.Context, spieler: str, *, reason: str = "Vom Support gekickt"):
        """Kickt einen Spieler. Beispiel: !ap kick ABC123 Beleidigung"""
        if not await self._require(ctx, "kick"):
            return
        db.add_action("kick", spieler, json.dumps({"reason": reason}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Kick für `{spieler}` angelegt. Grund: {reason}")

    @ap.command(name="announce")
    async def ap_announce(self, ctx: commands.Context, *, message: str):
        """Sendet eine Server-Ansage an alle Spieler."""
        if not await self._require(ctx, "announce"):
            return
        db.add_action("announce", "*", json.dumps({"message": message}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send("✅ Ansage angelegt.")

    @ap.command(name="car2garage")
    async def ap_car2garage(self, ctx: commands.Context, plate: str, garage: str = "downtown"):
        """Packt ein Fahrzeug per Kennzeichen in eine Garage."""
        if not await self._require(ctx, "car_to_garage"):
            return
        db.add_action("car_to_garage", plate, json.dumps({"garage": garage}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ `{plate}` → Garage `{garage}` angelegt.")

    @ap.command(name="money")
    async def ap_money(self, ctx: commands.Context, spieler: str, op: str,
                       amount: int, account: str = "cash"):
        """Geld geben/nehmen. Beispiel: !ap money ABC123 add 500 bank"""
        if not await self._require(ctx, "money"):
            return
        op = op.lower()
        if op not in ("add", "remove") or amount <= 0 or account not in ("cash", "bank"):
            return await ctx.send("Nutzung: `!ap money <spieler> <add|remove> <betrag> [cash|bank]`")
        if amount > self.money_max:
            return await ctx.send(f"❌ Limit: max. {self.money_max:,} $ pro Aktion.".replace(",", "."))
        db.add_action("money", spieler,
                      json.dumps({"op": op, "amount": amount, "account": account}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ {op} {amount}$ ({account}) für `{spieler}` angelegt.")

    @ap.command(name="giveitem")
    async def ap_giveitem(self, ctx: commands.Context, spieler: str, item: str, count: int = 1):
        """Gibt einem Spieler ein Item. Beispiel: !ap giveitem ABC123 water 5"""
        if not await self._require(ctx, "items"):
            return
        if count < 1:
            return await ctx.send("Anzahl muss mindestens 1 sein.")
        if count > self.item_max:
            return await ctx.send(f"❌ Limit: max. {self.item_max} Stück pro Aktion.")
        db.add_action("give_item", spieler,
                      json.dumps({"item": item, "count": count}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ `{item}` ×{count} für `{spieler}` angelegt.")

    @ap.command(name="removeitem")
    async def ap_removeitem(self, ctx: commands.Context, spieler: str, item: str, count: int = 1):
        """Nimmt einem Spieler ein Item weg. Beispiel: !ap removeitem ABC123 water 5"""
        if not await self._require(ctx, "items"):
            return
        if count < 1:
            return await ctx.send("Anzahl muss mindestens 1 sein.")
        if count > self.item_max:
            return await ctx.send(f"❌ Limit: max. {self.item_max} Stück pro Aktion.")
        db.add_action("remove_item", spieler,
                      json.dumps({"item": item, "count": count}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Entfernen von `{item}` ×{count} bei `{spieler}` angelegt.")

    @ap.command(name="inv")
    async def ap_inv(self, ctx: commands.Context, spieler: str):
        """Zeigt das Inventar eines Spielers. Beispiel: !ap inv ABC123"""
        if not await self._require(ctx, "view_inventory"):
            return
        action_id = db.add_action("get_inventory", spieler, None,
                                  f"discord:{ctx.author.display_name}")
        msg = await ctx.send(f"⏳ Frage Inventar von `{spieler}` ab…")

        import asyncio
        for _ in range(12):  # max. ~12 Sekunden auf die Bridge warten
            await asyncio.sleep(1)
            action = db.get_action(action_id)
            if not action or action["status"] == "pending":
                continue
            if action["status"] == "failed":
                return await msg.edit(content=f"❌ {action['result'] or 'Abfrage fehlgeschlagen.'}")
            try:
                items = json.loads(action["result"] or "{}").get("items", [])
            except (ValueError, TypeError):
                items = []
            if not items:
                return await msg.edit(content=f"📦 Inventar von `{spieler}` ist leer.")
            embed = discord.Embed(title=f"Inventar von {spieler}")
            lines = [f"`{i.get('name')}` ×{i.get('count', 1)} (Slot {i.get('slot', '?')})"
                     for i in items[:25]]
            if len(items) > 25:
                lines.append(f"… und {len(items) - 25} weitere")
            embed.description = "\n".join(lines)
            return await msg.edit(content=None, embed=embed)
        await msg.edit(content="❌ Keine Antwort von der FiveM-Bridge – läuft der Server?")

    @ap.command(name="tpc")
    async def ap_tpc(self, ctx: commands.Context, spieler: str, x: float, y: float, z: float):
        """Teleportiert einen Spieler zu Koordinaten. Beispiel: !ap tpc ABC123 298.6 -584.5 43.3"""
        if not await self._require(ctx, "teleport"):
            return
        db.add_action("teleport_coords", spieler,
                      json.dumps({"x": x, "y": y, "z": z}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Teleport `{spieler}` → `{x}, {y}, {z}` angelegt.")

    @ap.command(name="cars")
    async def ap_cars(self, ctx: commands.Context, spieler: str):
        """Zeigt die Fahrzeuge eines Spielers (auch offline). Beispiel: !ap cars ABC123"""
        if not await self._require(ctx, "car_to_garage"):
            return
        action_id = db.add_action("get_vehicles", spieler, None,
                                  f"discord:{ctx.author.display_name}")
        msg = await ctx.send(f"⏳ Frage Fahrzeuge von `{spieler}` ab…")

        import asyncio
        for _ in range(12):
            await asyncio.sleep(1)
            action = db.get_action(action_id)
            if not action or action["status"] == "pending":
                continue
            if action["status"] == "failed":
                return await msg.edit(content=f"❌ {action['result'] or 'Abfrage fehlgeschlagen.'}")
            try:
                vehicles = json.loads(action["result"] or "{}").get("vehicles", [])
            except (ValueError, TypeError):
                vehicles = []
            if not vehicles:
                return await msg.edit(content=f"🚗 `{spieler}` besitzt keine Fahrzeuge.")
            state_names = {0: "Draußen", 1: "Garage", 2: "Beschlagnahmt"}
            embed = discord.Embed(title=f"Fahrzeuge von {spieler}")
            lines = []
            for v in vehicles[:25]:
                st = state_names.get(v.get("state"), "?")
                if v.get("state") == 1 and v.get("garage"):
                    st += f": {v['garage']}"
                lines.append(f"**{v.get('vehicle', '?')}** · `{v.get('plate', '?')}` · {st}")
            if len(vehicles) > 25:
                lines.append(f"… und {len(vehicles) - 25} weitere")
            embed.description = "\n".join(lines)
            return await msg.edit(content=None, embed=embed)
        await msg.edit(content="❌ Keine Antwort von der FiveM-Bridge – läuft der Server?")

    @ap.command(name="logchannel")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def ap_logchannel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Setzt den Channel für Missbrauchs-Alerts. Ohne Angabe: ausschalten."""
        if channel is None:
            await self.config.alert_channel.set(None)
            return await ctx.send("🔕 Alert-Channel deaktiviert.")
        await self.config.alert_channel.set(channel.id)
        await ctx.send(f"🚨 Alerts (Geld-/Item-Sprünge, Dupe-Muster) gehen jetzt nach {channel.mention}.")

    @ap.command(name="find")
    async def ap_find(self, ctx: commands.Context, *, query: str):
        """Sucht Spieler in der DB (Name oder CID, auch offline). Beispiel: !ap find Kevin"""
        if not await self._require(ctx, "view_players"):
            return
        action_id = db.add_action("search_player", query, None,
                                  f"discord:{ctx.author.display_name}")
        msg = await ctx.send(f"⏳ Suche nach `{query}`…")
        import asyncio
        for _ in range(12):
            await asyncio.sleep(1)
            action = db.get_action(action_id)
            if not action or action["status"] == "pending":
                continue
            if action["status"] == "failed":
                return await msg.edit(content=f"❌ {action['result'] or 'Suche fehlgeschlagen.'}")
            try:
                results = json.loads(action["result"] or "{}").get("results", [])
            except (ValueError, TypeError):
                results = []
            if not results:
                return await msg.edit(content=f"🔍 Keine Treffer für `{query}`.")
            embed = discord.Embed(title=f"Suche: {query}")
            lines = []
            for r in results[:15]:
                lines.append(f"**{r.get('charname', '?')}** · `{r.get('citizenid')}` · "
                             f"{r.get('job') or 'kein Job'} · Bank: {r.get('bank', 0):,}$".replace(",", "."))
            embed.description = "\n".join(lines)
            return await msg.edit(content=None, embed=embed)
        await msg.edit(content="❌ Keine Antwort von der FiveM-Bridge – läuft der Server?")

    @ap.command(name="setjob")
    async def ap_setjob(self, ctx: commands.Context, spieler: str, job: str, grade: int = 0):
        """Setzt den Job eines Online-Spielers. Beispiel: !ap setjob Kevin police 2"""
        if not await self._require(ctx, "setjob"):
            return
        db.add_action("set_job", spieler, json.dumps({"job": job, "grade": grade}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Job `{job}` (Grade {grade}) für `{spieler}` angelegt.")

    @ap.command(name="setgang")
    async def ap_setgang(self, ctx: commands.Context, spieler: str, gang: str, grade: int = 0):
        """Setzt die Gang eines Online-Spielers. Beispiel: !ap setgang Kevin ballas 1"""
        if not await self._require(ctx, "setjob"):
            return
        db.add_action("set_gang", spieler, json.dumps({"gang": gang, "grade": grade}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Gang `{gang}` (Grade {grade}) für `{spieler}` angelegt.")

    @ap.command(name="msg")
    async def ap_msg(self, ctx: commands.Context, spieler: str, *, message: str):
        """Schickt einem Spieler eine private Support-Nachricht. Beispiel: !ap msg Kevin Bitte melde dich im Support"""
        if not await self._require(ctx, "message"):
            return
        db.add_action("notify", spieler, json.dumps({"message": message}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Nachricht an `{spieler}` angelegt.")

    @ap.command(name="note")
    async def ap_note(self, ctx: commands.Context, citizenid: str, *, text: str):
        """Legt eine Team-Notiz zu einem Spieler an."""
        if not await self._require(ctx, "notes"):
            return
        db.add_note(citizenid, "note", text[:1000], f"discord:{ctx.author.display_name}")
        await ctx.send(f"📝 Notiz für `{citizenid}` gespeichert.")

    @ap.command(name="warn")
    async def ap_warn(self, ctx: commands.Context, citizenid: str, *, text: str):
        """Spricht eine Verwarnung aus (Team-weit sichtbar in der Akte)."""
        if not await self._require(ctx, "notes"):
            return
        db.add_note(citizenid, "warn", text[:1000], f"discord:{ctx.author.display_name}")
        warns = len([n for n in db.get_notes(citizenid) if n["kind"] == "warn"])
        await ctx.send(f"⚠️ Verwarnung für `{citizenid}` gespeichert – das ist Verwarnung **Nr. {warns}**.")

    @ap.command(name="ban")
    async def ap_ban(self, ctx: commands.Context, spieler: str, duration: str, *, reason: str):
        """Bannt einen Spieler. Dauer: Stunden-Zahl oder 'perm'. Beispiel: !ap ban Kevin 24 Cheating / !ap ban ABC123 perm RDM"""
        if not await self._require(ctx, "ban"):
            return
        if duration.lower() in ("perm", "permanent", "0"):
            hours = 0
        else:
            try:
                hours = int(duration)
            except ValueError:
                return await ctx.send("Dauer muss eine Stundenzahl oder `perm` sein.")
        db.add_action("ban", spieler, json.dumps({"hours": hours, "reason": reason}),
                      f"discord:{ctx.author.display_name}")
        dur_txt = "permanent" if hours == 0 else f"{hours} Stunden"
        await ctx.send(f"🔨 Ban für `{spieler}` ({dur_txt}) angelegt – wird beim nächsten Sync ausgeführt.")

    @ap.command(name="unban")
    async def ap_unban(self, ctx: commands.Context, citizenid: str):
        """Hebt einen Ban auf. Beispiel: !ap unban ABC123"""
        if not await self._require(ctx, "ban"):
            return
        if db.remove_ban(citizenid):
            await self._audit(f"🔓 **Unban** · `{citizenid}` · von {ctx.author.display_name}")
            await ctx.send(f"🔓 Ban für `{citizenid}` aufgehoben.")
        else:
            await ctx.send(f"Kein aktiver Ban für `{citizenid}` gefunden.")

    @ap.command(name="bans")
    async def ap_bans(self, ctx: commands.Context):
        """Zeigt alle aktiven Bans."""
        if not await self._require(ctx, "ban"):
            return
        bans = db.get_active_bans()
        if not bans:
            return await ctx.send("Keine aktiven Bans.")
        import datetime
        embed = discord.Embed(title=f"Aktive Bans ({len(bans)})")
        for b in bans[:20]:
            if b["expires_at"]:
                exp = datetime.datetime.fromtimestamp(b["expires_at"]).strftime("%d.%m.%Y %H:%M")
            else:
                exp = "permanent"
            embed.add_field(
                name=f"{b.get('name') or '?'} · {b['citizenid']}",
                value=f"{b['reason']}\nBis: {exp} · von {b['banned_by']}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @ap.command(name="auditchannel")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def ap_auditchannel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Setzt den Channel für das Admin-Audit-Log (Geld, Items, Bans …). Ohne Angabe: aus."""
        if channel is None:
            await self.config.audit_channel.set(None)
            return await ctx.send("🔕 Audit-Log deaktiviert.")
        await self.config.audit_channel.set(channel.id)
        await ctx.send(f"📋 Admin-Aktionen (Geld, Items, Bans, Job/Gang) werden jetzt nach {channel.mention} geloggt. "
                       f"Tipp: einen Channel wählen, auf den die Admins selbst **keinen** Schreib-/Löschzugriff haben.")

    @ap.command(name="parkall")
    async def ap_parkall(self, ctx: commands.Context, fallback_garage: str = "downtown"):
        """Parkt ALLE gespawnten Spieler-Fahrzeuge in die nächste Garage ein. Besetzte Fahrzeuge bleiben stehen."""
        if not await self._require(ctx, "park_all"):
            return
        db.add_action("park_all", "*", json.dumps({"garage": fallback_garage}),
                      f"discord:{ctx.author.display_name}")
        await ctx.send("🅿️ Massen-Einparken angelegt – Ergebnis kommt gleich ins Protokoll "
                       "(`!ap status`). Besetzte und NPC-Fahrzeuge werden übersprungen.")

    @ap.group(name="config")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def ap_config(self, ctx: commands.Context):
        """Panel-Einstellungen per Befehl (kein Datei-Editieren nötig)."""

    @ap_config.command(name="show")
    async def ap_config_show(self, ctx: commands.Context):
        """Zeigt die aktuellen Einstellungen."""
        key = self.api_key
        key_disp = "❌ nicht gesetzt (CHANGE_ME)" if key == "CHANGE_ME" else f"✓ gesetzt (…{key[-4:]})"
        url = self.public_url or "— (Login nur per Token)"
        embed = discord.Embed(title="AdminPanel – Einstellungen")
        embed.add_field(name="API-Key (Bridge)", value=key_disp, inline=False)
        embed.add_field(name="Web-Port", value=str(self.web_port), inline=True)
        embed.add_field(name="Public-URL", value=url, inline=False)
        embed.add_field(name="Geld-Limit / Aktion", value=f"{self.money_max:,} $".replace(",", "."), inline=True)
        embed.add_field(name="Item-Limit / Aktion", value=str(self.item_max), inline=True)
        embed.set_footer(text="Ändern: !ap config key | url | port | moneymax | itemmax")
        await ctx.send(embed=embed)

    @ap_config.command(name="key")
    async def ap_config_key(self, ctx: commands.Context, custom_key: str = None):
        """Generiert einen neuen API-Key (oder setzt einen eigenen) und schickt ihn per DM."""
        import secrets
        key = custom_key or secrets.token_hex(32)
        await self.config.api_key.set(key)
        self.api_key = key
        try:
            await ctx.author.send(
                f"🔑 **Neuer AdminPanel API-Key:**\n```{key}```\n"
                f"Trage ihn in deine `server.cfg` ein:\n"
                f"```set adminpanel_key \"{key}\"```\n"
                f"Danach die Resource neu starten: `restart ap_bridge` (oder Server-Neustart). "
                f"Bis dahin kann sich die FiveM-Bridge nicht mehr verbinden."
            )
            note = "🔑 Neuer API-Key generiert und dir per DM geschickt."
        except discord.Forbidden:
            note = ("🔑 Key gesetzt, aber ich kann dir keine DM schicken. "
                    "Aktiviere DMs und nutze `!ap config key` erneut, oder hol ihn dir sicher aus der Bot-Config.")
        await ctx.send(note + " ⚠️ Vergiss nicht, `server.cfg` anzupassen und `ap_bridge` neu zu starten.")

    @ap_config.command(name="url")
    async def ap_config_url(self, ctx: commands.Context, url: str):
        """Setzt die öffentliche Panel-URL für die Login-Links. Beispiel: !ap config url https://panel.example.com"""
        url = url.rstrip("/")
        if not url.startswith("http"):
            return await ctx.send("Die URL muss mit http:// oder https:// beginnen.")
        await self.config.public_url.set(url)
        self.public_url = url
        await ctx.send(f"✅ Public-URL gesetzt: {url}\nLogin-Links kommen jetzt als anklickbarer Link.")

    @ap_config.command(name="port")
    async def ap_config_port(self, ctx: commands.Context, port: int):
        """Setzt den Web-Port (wird nach `[p]reload adminpanel` aktiv)."""
        if not (1 <= port <= 65535):
            return await ctx.send("Ungültiger Port.")
        await self.config.web_port.set(port)
        await ctx.send(f"✅ Web-Port auf {port} gesetzt. Wird nach `[p]reload adminpanel` aktiv "
                       f"(der Server bindet den Port beim Start). Reverse-Proxy ggf. anpassen.")

    @ap_config.command(name="moneymax")
    async def ap_config_moneymax(self, ctx: commands.Context, amount: int):
        """Setzt das Geld-Limit pro Aktion. Beispiel: !ap config moneymax 100000"""
        if amount < 1:
            return await ctx.send("Muss mindestens 1 sein.")
        await self.config.money_max.set(amount)
        self.money_max = amount
        await ctx.send(f"✅ Geld-Limit: max. {amount:,} $ pro Aktion.".replace(",", "."))

    @ap_config.command(name="itemmax")
    async def ap_config_itemmax(self, ctx: commands.Context, count: int):
        """Setzt das Item-Limit pro Aktion. Beispiel: !ap config itemmax 250"""
        if count < 1:
            return await ctx.send("Muss mindestens 1 sein.")
        await self.config.item_max.set(count)
        self.item_max = count
        await ctx.send(f"✅ Item-Limit: max. {count} Stück pro Aktion.")

    @ap_config.command(name="oauth")
    async def ap_config_oauth(self, ctx: commands.Context, client_id: str, client_secret: str):
        """Aktiviert 'Mit Discord anmelden'. Client-ID + Secret aus dem Developer Portal."""
        # Nachricht sofort löschen – das Secret soll nicht im Chat stehen bleiben
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass
        if not client_id.isdigit():
            return await ctx.send("Die Client-ID ist die lange Zahl deiner Bot-Application (Developer Portal → General Information → Application ID).")
        await self.config.oauth_client_id.set(client_id)
        await self.config.oauth_client_secret.set(client_secret)
        redirect = self._oauth_redirect_uri() if self.public_url else "⚠️ Erst `!ap config url …` setzen!"
        await ctx.send(
            "✅ **Discord-Login aktiviert.** (Deine Nachricht mit dem Secret habe ich gelöscht.)\n\n"
            "Letzter Schritt im **Developer Portal** (discord.com/developers) → deine Application → **OAuth2** → **Redirects** → hinzufügen:\n"
            f"```{redirect}```\n"
            "Speichern – danach erscheint der Login sofort im Panel. Muss exakt übereinstimmen (inkl. Port)."
        )

    @ap.command(name="diag")
    async def ap_diag(self, ctx: commands.Context):
        """Prüft das Setup (DB, Exports, Tabellen, Society-System)."""
        if not await self._require(ctx, "server_status"):
            return
        action_id = db.add_action("diag", "*", None, f"discord:{ctx.author.display_name}")
        msg = await ctx.send("⏳ Diagnose läuft…")
        import asyncio
        for _ in range(12):
            await asyncio.sleep(1)
            action = db.get_action(action_id)
            if not action or action["status"] == "pending":
                continue
            if action["status"] == "failed":
                return await msg.edit(content=f"❌ {action['result'] or 'Diagnose fehlgeschlagen.'}")
            try:
                checks = json.loads(action["result"] or "{}").get("checks", [])
            except (ValueError, TypeError):
                checks = []
            icons = {"ok": "✅", "warn": "⚠️", "fail": "❌", "info": "ℹ️"}
            lines = [f"{icons.get(c['status'], '•')} **{c['label']}** — {c['detail']}" for c in checks]
            fails = sum(1 for c in checks if c["status"] == "fail")
            embed = discord.Embed(
                title="Setup-Diagnose",
                description="\n".join(lines) or "Keine Ergebnisse",
                color=discord.Color.red() if fails else discord.Color.green(),
            )
            return await msg.edit(content=None, embed=embed)
        await msg.edit(content="❌ Keine Antwort von der FiveM-Bridge – läuft der Server?")

    @ap.command(name="backup")
    @commands.has_permissions(administrator=True)
    async def ap_backup(self, ctx: commands.Context):
        """Erstellt sofort ein DB-Backup (Bans, Notizen, Log)."""
        try:
            path, count = db.backup_db()
            await ctx.send(f"💾 Backup erstellt: `{path}`\n({count} Backups vorhanden, ältere werden automatisch gelöscht). "
                           f"Tipp: den `backups/`-Ordner ins Synology-Backup aufnehmen.")
        except Exception as e:
            await ctx.send(f"❌ Backup fehlgeschlagen: {e}")

    @ap.command(name="lockdown")
    @commands.has_permissions(administrator=True)
    async def ap_lockdown(self, ctx: commands.Context, state: str = None):
        """NOT-AUS: sperrt sofort alle Panel-Aktionen. `!ap lockdown on` / `off`"""
        if state is None:
            current = await self.config.locked()
            return await ctx.send(f"Lockdown ist aktuell **{'AN 🔒' if current else 'aus'}**. "
                                  f"Umschalten mit `!ap lockdown on` / `off`.")
        if state.lower() in ("on", "an", "1", "true"):
            await self.config.locked.set(True)
            await self._audit(f"🔒 **LOCKDOWN AKTIVIERT** von {ctx.author.display_name}")
            await ctx.send("🔒 **Lockdown aktiv.** Alle Panel-Aktionen sind gesperrt, offene Aufträge werden nicht mehr ausgeführt. "
                           "Nur Diagnose läuft noch. Aufheben mit `!ap lockdown off`.")
        elif state.lower() in ("off", "aus", "0", "false"):
            await self.config.locked.set(False)
            await self._audit(f"🔓 Lockdown aufgehoben von {ctx.author.display_name}")
            await ctx.send("🔓 Lockdown aufgehoben – Panel wieder normal nutzbar.")
        else:
            await ctx.send("Nutzung: `!ap lockdown on` / `off`")

    @ap.command(name="status")
    async def ap_status(self, ctx: commands.Context):
        """Zeigt die letzten 10 Aktionen."""
        if ctx.guild is None or not await self.member_permissions(ctx.author):
            return await ctx.send("❌ Keine Berechtigung.")
        actions = db.get_recent_actions(10)
        if not actions:
            return await ctx.send("Keine Aktionen vorhanden.")
        embed = discord.Embed(title="Letzte Adminpanel-Aktionen")
        for a in actions:
            embed.add_field(
                name=f"{a['action_type']} → {a['target']}",
                value=f"Status: **{a['status']}** | von {a['created_by']}",
                inline=False,
            )
        await ctx.send(embed=embed)
