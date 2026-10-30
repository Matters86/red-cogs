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

import asyncio
import errno
import json
import math
import os
import logging
import time
import secrets
import hashlib
import urllib.parse
import re
import unicodedata

import aiohttp
import discord
from aiohttp import web
from redbot.core import commands, Config
from redbot.core.data_manager import cog_data_path

from . import db
from .serverprofiles import Profiles, PROFILE_ID, ENV_NAME, ALLOWED_PROFILES

log = logging.getLogger("red.adminpanel")

# This identifies the loaded Python module independently of a later source copy.
PANEL_BUILD = "2026-10-29-support-v2.2.2"
try:
    with open(__file__, "rb") as _module_source:
        LOADED_MODULE_SHA256 = hashlib.sha256(_module_source.read()).hexdigest()
except OSError:
    LOADED_MODULE_SHA256 = None


def _frontend_payload():
    """Read only this installed cog's HTML; never config, database or network."""
    with open(os.path.join(os.path.dirname(__file__), "panel.html"), "rb") as source:
        return source.read()


def _frontend_version():
    try:
        payload = _frontend_payload()
    except OSError:
        digest = None
    else:
        digest = hashlib.sha256(payload).hexdigest()
    return {"build": PANEL_BUILD, "loaded_module_sha256": LOADED_MODULE_SHA256,
            "html_sha256": digest, "frontend": "panel.html"}


# ENV dienen nur noch als DEFAULTS. Zur Laufzeit überschreiben die per
# Discord-Befehl gesetzten Config-Werte diese (self.api_key usw.).
DEFAULT_API_KEY = os.environ.get("ADMINPANEL_API_KEY", "CHANGE_ME")
DEFAULT_WEB_PORT = int(os.environ.get("ADMINPANEL_WEB_PORT", "8099"))
# Bind-Adresse: Standard bleibt 0.0.0.0 (alle Schnittstellen). Läuft das Panel nur
# hinter einem Reverse-Proxy auf demselben Host, ist 127.0.0.1 sicherer.
DEFAULT_WEB_HOST = os.environ.get("ADMINPANEL_WEB_HOST", "0.0.0.0")
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

_SUPPORT = {"view_players", "teleport", "heal", "revive", "car_to_garage", "view_inventory", "message",
            "support_cases", "support_vehicles", "support_diagnostics"}
_MODERATOR = _SUPPORT | {"kick", "ban", "announce", "view_logs", "notes", "setjob"}
_ADMIN = _MODERATOR | {"money", "items", "view_stats", "park_all", "audit"}

PRESETS = {
    "support": _SUPPORT,
    "moderator": _MODERATOR,
    "admin": _ADMIN,
    "editor": {"server_status", "view_stats"},
}

# Alle Rechte (Discord-Administratoren; im Dashboard auch Owner/Allowlist).
ALL_PERMS = _ADMIN | PRESETS["editor"]

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
    "support_vehicle_search": "support_vehicles",
    "support_vehicle_case": "support_vehicles",
    "support_diagnose": "support_diagnostics",
}
READ_ACTIONS = {"diag", "get_stats", "get_inventory", "get_vehicles", "search_player",
                "support_vehicle_search", "support_vehicle_case", "support_diagnose"}


def project_actions(actions, permissions):
    """Keine Aktion/Ergebnisdaten ohne das konkrete Recht für diese Aktion."""
    fields = (
        "id", "action_type", "target", "target_name", "params", "status", "result",
        "created_by", "created_at", "completed_at", "result_review_required",
        "result_review_reason", "audit_delivery", "audit_claimed_at", "audit_completed_at",
        "profile_queue_hold",
    )
    projected = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        permission = ACTION_PERMISSION.get(action.get("action_type"))
        if permission is not None and permission in permissions:
            projected.append({key: action[key] for key in fields if key in action})
    return projected


def _player_search_query(value):
    if not isinstance(value, str):
        raise ValueError('Suchbegriff muss Text sein.')
    value = unicodedata.normalize('NFC', ' '.join(value.split()))
    if not 2 <= len(value) <= 80 or any(unicodedata.category(c) in ('Cc', 'Cs') for c in value):
        raise ValueError('Bitte 2 bis 80 gültige Zeichen eingeben.')
    return value


def _player_search_fold(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(value).casefold())
                            if not unicodedata.combining(c)).split())


def _player_search_discord_id(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value) is not None and int(value) <= 18446744073709551615


def _health_number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > 10 ** 12 or not math.isfinite(value):
        return None
    if integer and value != int(value):
        return None
    return int(value) if integer else value


def project_bridge_health(state):
    """Whitelist des tatsächlichen ap_bridge-1.1-Zustands, kein erfundenes Ready.

    Transport (synced_at), Ausführungsbereitschaft und DB-Probe sind getrennte
    Beobachtungen. Fehlende Werte alter Bridge-Versionen bleiben unbestätigt.
    """
    bridge = state.get("bridge")
    bridge = bridge if isinstance(bridge, dict) else {}
    version = bridge.get("version")
    readiness = bridge.get("mutation_queue_ready")
    resources = state.get("resources_not_running")
    safe_resources = [] if isinstance(resources, list) else None
    if isinstance(resources, list):
        for resource in resources[:30]:
            if not isinstance(resource, dict):
                continue
            name, resource_state = resource.get("name"), resource.get("state")
            if isinstance(name, str) and isinstance(resource_state, str):
                safe_resources.append({"name": name[:128], "state": resource_state[:32]})
    return {
        "uptime": _health_number(state.get("uptime")),
        "resources_total": _health_number(state.get("resources_total"), integer=True),
        "resources_not_running": safe_resources,
        "db_ping_ms": _health_number(state.get("db_ping_ms")),
        "db_ping_sample_age_ms": _health_number(state.get("db_ping_sample_age_ms")),
        "bridge": {
            "version": version[:64] if isinstance(version, str) and version else None,
            "active_actions": _health_number(bridge.get("active_actions"), integer=True),
            "mutation_queue_ready": readiness if isinstance(readiness, bool) else None,
            "queued_events": _health_number(bridge.get("queued_events"), integer=True),
            "dropped_events": _health_number(bridge.get("dropped_events"), integer=True),
        },
    }


def support_action_params(action_type, params, profile_id):
    def vehicle_id():
        value = params.get("vehicle_id")
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2147483647:
            raise ValueError("vehicle_id_invalid")
        return value

    def text(name, maximum, *, required=False):
        value = params.get(name)
        if value is None and not required:
            return None
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise ValueError(name + "_invalid")
        return value.strip()

    clean = {"server_id": profile_id, "profile": profile_id, "schema_version": 1}
    if action_type == "support_vehicle_search":
        if "kind" in params:
            raise ValueError("use_kinds_array")
        clean["query"] = text("query", 50, required=True)
        query_kind = params.get("query_kind")
        if query_kind is not None and query_kind not in ("vehicleId", "plate", "citizenid"):
            raise ValueError("query_kind_invalid")
        query = clean["query"]
        numeric_id = query.isascii() and query.isdigit() and query == str(int(query)) and 1 <= int(query) <= 2147483647
        if query_kind == "vehicleId" and not numeric_id:
            raise ValueError("vehicle_id_invalid")
        if query_kind == "citizenid" and (not query.isascii() or not query.replace("_", "").replace("-", "").isalnum()):
            raise ValueError("citizenid_invalid")
        if query_kind == "plate" and (not query.isascii() or not 2 <= len(query) <= 15 or not query.replace(" ", "").isalnum()):
            raise ValueError("plate_invalid")
        if len(query) < 2 and not numeric_id and query_kind != "citizenid":
            raise ValueError("query_invalid")
        if query_kind is not None:
            clean["query_kind"] = query_kind
        limit = params.get("limit", 20)
        cursor = params.get("cursor", 0)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit_invalid")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or not 0 <= cursor <= 2147483647:
            raise ValueError("cursor_invalid")
        clean.update(limit=limit, cursor=cursor)
        kinds = params.get("kinds")
        if kinds is not None:
            if (not isinstance(kinds, list) or not kinds or len(kinds) > 3
                    or any(kind not in ("private", "faction", "lease") for kind in kinds)):
                raise ValueError("kinds_invalid")
            if len(set(kinds)) != len(kinds):
                raise ValueError("kinds_invalid")
            clean["kinds"] = list(kinds)
    elif action_type == "support_vehicle_case":
        clean["vehicle_id"] = vehicle_id()
        for name, maximum in (("expected_plate", 15), ("citizenid", 50)):
            value = text(name, maximum)
            if value is not None:
                clean[name] = value
    elif action_type == "support_diagnose":
        topic = params.get("topic")
        if topic not in ("keys", "trunk", "fuel", "civil_jobs"):
            raise ValueError("topic_invalid")
        clean["topic"] = topic
        if topic == "civil_jobs":
            clean["citizenid"] = text("citizenid", 50, required=True)
        else:
            clean["vehicle_id"] = vehicle_id()
    else:
        raise ValueError("unsupported_action")
    return clean


def parking_action_params(target, params):
    """Validate the existing parking contract; final identity/garage checks are server-owned."""
    def plate(value):
        return isinstance(value, str) and 1 <= len(value.strip()) <= 15 and value.strip().isascii() and value.replace(" ", "").isalnum()
    if not plate(target) or not isinstance(params, dict) or set(params) - {"garage", "vehicle_id", "expected_plate"}:
        raise ValueError("parking_target_invalid")
    garage = params.get("garage", "")
    expected = params.get("expected_plate", target)
    if not isinstance(garage, str) or len(garage.strip()) > 100 or any(ord(c) < 32 for c in garage) or not plate(expected):
        raise ValueError("parking_params_invalid")
    if expected.upper().replace(" ", "") != target.upper().replace(" ", ""):
        raise ValueError("parking_plate_mismatch")
    clean = {"garage": garage.strip(), "expected_plate": expected.strip()}
    if "vehicle_id" in params:
        value = params["vehicle_id"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2147483647:
            raise ValueError("parking_vehicle_id_invalid")
        clean["vehicle_id"] = value
    return clean


class AdminPanel(commands.Cog):
    """FiveM-Server-Verwaltung per Discord und Webbrowser."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA0D141)
        self.config.register_guild(
            role_map={},   # {role_id(str): preset_name}
            user_map={},   # {user_id(str): preset_name} – Einzelpersonen-Zugriffe
            profile_selection={},  # Discord-Befehle: explizite Auswahl pro Nutzer/Guild
        )
        self.config.register_global(
            alert_channel=None,
            audit_channel=None,
            locked=False,
            api_key=None,      # None => ENV/Default
            web_port=None,
            web_host=None,     # None => ENV/Default (0.0.0.0)
            public_url=None,
            money_max=None,
            item_max=None,
            oauth_client_id=None,
            oauth_client_secret=None,
            server_profiles={},  # trusted Guild-Bindung + Key-ENV je Profil; nie Browserwerte
        )
        # OAuth-CSRF-States (state -> Ablaufzeit), kurzlebig, nur im RAM
        self._oauth_states: dict = {}
        # Laufzeit-Settings (werden in _start_webserver aus Config+ENV aufgelöst)
        self.api_key = DEFAULT_API_KEY
        self.web_port = DEFAULT_WEB_PORT
        self.web_host = DEFAULT_WEB_HOST
        self.public_url = DEFAULT_PUBLIC_URL
        self.money_max = DEFAULT_MONEY_MAX
        self.item_max = DEFAULT_ITEM_MAX
        self.profiles = Profiles(legacy_key=self.api_key)
        self._profile_config_lock = asyncio.Lock()
        self._settings_ready = asyncio.Event()
        try:
            path = db.set_data_dir(cog_data_path(self))
            log.info("AdminPanel-DB: %s", path)
        except Exception:
            log.exception("AdminPanel: Datenverzeichnis nicht verfügbar; Start abgebrochen")
            raise
        db.init_db(auth=True)
        db.configure_profiles({"legacy": db.DB_PATH})
        self.runner: web.AppRunner | None = None
        self._closing = False
        self._web_task = None
        self._backup_task = None

    async def _resolve_settings(self):
        """Effektive Settings = Config-Wert, sonst ENV/Default."""
        self.api_key = await self.config.api_key() or DEFAULT_API_KEY
        self.web_port = await self.config.web_port() or DEFAULT_WEB_PORT
        self.web_host = await self.config.web_host() or DEFAULT_WEB_HOST
        self.public_url = (await self.config.public_url() or DEFAULT_PUBLIC_URL).rstrip("/")
        self.money_max = await self.config.money_max() or DEFAULT_MONEY_MAX
        self.item_max = await self.config.item_max() or DEFAULT_ITEM_MAX
        await self._refresh_profiles()
        self._settings_ready.set()

    async def _refresh_profiles(self):
        configured = await self.config.server_profiles()
        self.profiles = Profiles(configured, self.api_key)
        paths = {"legacy": db.DB_PATH}
        for profile in self.profiles.items.values():
            if profile.id != "legacy" and profile.guild_id is not None:
                path = db.DB_PATH.parent / "profiles" / profile.id / "adminpanel.sqlite3"
                path.parent.mkdir(parents=True, exist_ok=True)
                paths[profile.id] = path
        db.configure_profiles(paths)
        for profile_id in paths:
            with db.profile_scope(profile_id):
                db.init_db()

    async def profile_setting(self, name):
        profile_id = db.current_profile()
        if profile_id is None:
            raise RuntimeError("server_profile_scope_required")
        record = self.profiles.raw.get(profile_id, {})
        if name in record:
            return record[name]
        if profile_id == "legacy":
            return await getattr(self.config, name)()
        return False if name == "locked" else None

    async def profile_locked(self):
        return (await self.profile_setting("locked")) is True

    async def set_profile_setting(self, name, value):
        profile_id = db.current_profile()
        if profile_id is None:
            raise RuntimeError("server_profile_scope_required")
        async with self._profile_config_lock:
            records = await self.config.server_profiles()
            records = dict(records) if isinstance(records, dict) else {}
            record = dict(records.get(profile_id) or {})
            record[name] = value
            records[profile_id] = record
            await self.config.server_profiles.set(records)
            await self._refresh_profiles()

    def profile_channel(self, channel_id):
        profile = self.profiles.items.get(db.current_profile())
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        if not profile or not profile.guild_id or not channel:
            return None
        return channel if str(getattr(getattr(channel, "guild", None), "id", "")) == profile.guild_id else None

    def _key_ok(self, provided: str) -> bool:
        """Kompatibler Helfer: nur ein eindeutig zugeordnetes Profil akzeptieren."""
        return self.profiles.for_bridge(provided) is not None

    # --------------------------------------------------------------
    # WebCore-Dashboard (Verwaltungsseite; das Live-Panel bleibt eigenständig)
    # --------------------------------------------------------------

    async def cog_load(self):
        if self._closing:
            return
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        # A failed add_cog/registration must not leave an unowned web task.
        if self._web_task is None:
            self._web_task = self.bot.loop.create_task(self._start_webserver())
        if self._backup_task is None:
            self._backup_task = self.bot.loop.create_task(self._backup_loop())

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        if not self._closing:
            self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        page = dict(owner=self, slug="fivemadmin", name="FiveM-Admin", icon="bi-controller",
                    handler=self.dashboard_page)
        try:
            # Tagesgeschäft für die Stufe „Bedienen“: Im Live-Panel anmelden, Not-Aus, Entbannen –
            # die eigenen Prüfungen (Panel-Recht „ban“, Discord-Admin für den Not-Aus) gelten zusätzlich.
            webcore.register_page(**page, operate_forms={"sso", "lockdown", "unban"})
        except TypeError:  # ältere WebCore-Versionen ohne Stufe „Bedienen“
            webcore.register_page(**page)

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler
        return await dashboard_handler(self, request)

    async def cog_unload(self):
        self._closing = True
        try:
            webcore = self.bot.get_cog("WebCore")
            if webcore is not None:
                webcore.unregister_owner(self)
        except Exception as exc:
            log.warning("AdminPanel Dashboard-Abmeldung fehlgeschlagen (%s).", type(exc).__name__)
        tasks = [task for task in (self._web_task, self._backup_task)
                 if task is not None and task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._web_task = self._backup_task = None
        runner, self.runner = self.runner, None
        if runner is not None:
            try:
                await runner.cleanup()
            except Exception as exc:
                log.warning("AdminPanel Webserver-Cleanup fehlgeschlagen (%s).", type(exc).__name__)

    async def _backup_loop(self):
        """Sichert die DB alle 24h automatisch."""
        # Stündlich prüfen, ob das jüngste Backup älter als 24 h ist. Vorher wurde
        # erst 24 h NACH jedem Laden gesichert – bei häufigem [p]reload also nie.
        await self.bot.wait_until_ready()
        await self._settings_ready.wait()
        while True:
            try:
                for profile_id in self.profiles.items:
                    if profile_id != "legacy" and self.profiles.items[profile_id].guild_id is None:
                        continue
                    with db.profile_scope(profile_id):
                        age = await asyncio.to_thread(db.newest_backup_age)
                        if age is None or age >= 24 * 3600:
                            path, count = await asyncio.to_thread(db.backup_db)
                            log.info("AdminPanel DB-Backup Profil %s erstellt (%s Backups)", profile_id, count)
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"DB-Backup fehlgeschlagen: {e}")
                await asyncio.sleep(3600)

    # --------------------------------------------------------------
    # Berechtigungs-Auflösung (live aus Discord-Rollen)
    # --------------------------------------------------------------

    def _is_panel_admin_sync(self, member) -> bool:
        """Wie ``is_panel_admin``, ohne await (für Listen/innere Funktionen)."""
        if member is None:
            return False
        if member.id in (getattr(self.bot, "owner_ids", None) or set()):
            return True
        return bool(getattr(member, "guild_permissions", None) and member.guild_permissions.administrator)

    async def is_panel_admin(self, member) -> bool:
        """Discord-Administrator des Servers oder Bot-Owner (Owner hat immer alle Rechte)."""
        if member is None:
            return False
        if await self.bot.is_owner(member):
            return True
        return bool(getattr(member, "guild_permissions", None) and member.guild_permissions.administrator)

    async def member_permissions(self, member: discord.Member) -> set:
        perms: set = set()
        if await self.is_panel_admin(member):
            return set(ALL_PERMS)
        role_map = await self.config.guild(member.guild).role_map()
        for role in member.roles:
            preset = role_map.get(str(role.id))
            if preset in PRESETS:
                perms |= PRESETS[preset]
        # Einzelpersonen-Zugriff: addiert sich zu evtl. Rollen-Presets
        user_map = await self.config.guild(member.guild).user_map()
        preset = user_map.get(str(member.id))
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
        runner = None
        published = False
        try:
            await self.bot.wait_until_ready()
            if self._closing:
                return
            await self._resolve_settings()
            if self._closing:
                return
            app = web.Application(middlewares=[self._security_headers, self._auth_middleware])
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
            app.router.add_get("/api/panel/profiles", self.http_panel_profiles)
            app.router.add_get("/api/panel/catalog", self.http_panel_catalog)
            app.router.add_get("/api/panel/player_history", self.http_player_history)
            app.router.add_post("/api/panel/notes", self.http_add_note)
            app.router.add_post("/api/panel/notes/delete", self.http_delete_note)
            app.router.add_get("/api/panel/bans", self.http_get_bans)
            app.router.add_post("/api/panel/unban", self.http_unban)
            app.router.add_get("/api/panel/audit", self.http_audit)
            app.router.add_get("/api/panel/roles", self.http_get_role_map)
            app.router.add_post("/api/panel/roles", self.http_set_role_map)
            app.router.add_post("/api/panel/users", self.http_set_user_map)
            app.router.add_get("/api/panel/user_search", self.http_user_search)
            app.router.add_post("/api/panel/action", self.http_panel_action)
            # Bridge (FiveM-Server)
            app.router.add_post("/api/bridge/sync", self.http_bridge_sync)
            app.router.add_post("/api/bridge/catalog", self.http_bridge_catalog)
            app.router.add_post("/api/actions/result", self.http_bridge_result)
            from . import support
            support.register_routes(self, app)

            runner = web.AppRunner(app)
            await runner.setup()
            for attempt in range(3):
                # aiohttp registers a site before binding its socket. A failed
                # site must be stopped; never start the same instance twice.
                site = web.TCPSite(runner, self.web_host, self.web_port)
                try:
                    await site.start()
                except OSError as exc:
                    try:
                        await site.stop()
                    except Exception as cleanup_error:
                        log.warning("AdminPanel Start-Site-Cleanup fehlgeschlagen (%s).", type(cleanup_error).__name__)
                    if exc.errno != errno.EADDRINUSE or attempt == 2:
                        log.error("AdminPanel Webserver konnte Port %s nicht binden: %s", self.web_port, exc)
                        return
                    log.warning("Port %s noch belegt (%s) – neuer Versuch in 2s…", self.web_port, exc)
                    await asyncio.sleep(2)
                    continue
                if self._closing:
                    return
                self.runner = runner
                published = True
                log.info("AdminPanel Webserver läuft auf %s:%s", self.web_host, self.web_port)
                if not any(profile.enabled and profile.key for profile in self.profiles.items.values()):
                    log.warning("Kein gültiger Profil-Key konfiguriert; Bridge-Zugriffe bleiben gesperrt. "
                                "Profil an die Ziel-Guild binden und vorhandene Key-Umgebungsvariable zuordnen.")
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("AdminPanel Webserver-Start fehlgeschlagen (%s).", type(exc).__name__)
        finally:
            if runner is not None and not published:
                try:
                    await runner.cleanup()
                except Exception as exc:
                    log.warning("AdminPanel Start-Runner-Cleanup fehlgeschlagen (%s).", type(exc).__name__)

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        path = request.path
        if path.startswith("/api/bridge/") or path.startswith("/api/actions/"):
            if not any(profile.enabled and profile.key for profile in self.profiles.items.values()):
                return web.json_response(
                    {"error": "bridge disabled: no API key configured"}, status=503)
            profile = self.profiles.for_bridge(request.headers.get("X-API-Key"),
                                                request.headers.get("X-Server-Profile"))
            if profile is None:
                return web.json_response({"error": "unauthorized"}, status=401)
            request["profile"] = profile.public(internal=True)
            with db.profile_scope(profile.id):
                return await handler(request)
        elif path.startswith("/api/panel/"):
            session = await asyncio.to_thread(db.get_session, request.headers.get("X-Session", ""))
            if not session:
                return web.json_response({"error": "unauthorized"}, status=401)
            member, perms = await self.session_permissions(session)
            if member is None or not perms:
                return web.json_response({"error": "unauthorized"}, status=401)
            request["session"] = session
            request["member"] = member
            request["perms"] = perms
            if path == "/api/panel/profiles":
                return await handler(request)
            profile_id = request.headers.get("X-Server-Profile")
            if not profile_id:
                return web.json_response({"error": "server_selection_required"}, status=409)
            profile = self.profiles.select(profile_id, member.guild.id)
            if profile is None:
                return web.json_response({"error": "server_profile_forbidden"}, status=403)
            request["profile"] = profile.public(internal=True)
            with db.profile_scope(profile.id):
                return await handler(request)
        return await handler(request)

    @web.middleware
    async def _security_headers(self, request: web.Request, handler):
        """Defensive HTTP-Header auf allen Antworten (Clickjacking / MIME-Sniffing)."""
        def _apply(resp):
            resp.headers.setdefault("X-Frame-Options", "DENY")
            resp.headers.setdefault("X-Content-Type-Options", "nosniff")
            resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
            if request.path == "/" or request.path.startswith("/api/"):
                resp.headers["Cache-Control"] = "no-store"
            elif request.path in ("/sw.js", "/manifest.json"):
                resp.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
            return resp
        try:
            return _apply(await handler(request))
        except web.HTTPException as exc:
            _apply(exc)
            raise

    async def _read_json(self, request: web.Request):
        """Liest den JSON-Body oder bricht mit HTTP 400 ab (statt 500 bei kaputtem JSON)."""
        try:
            return await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "ungültiges JSON"}),
                content_type="application/json",
            )

    # ---------------- Browser-Endpoints ----------------

    async def http_index(self, request: web.Request):
        payload = _frontend_payload()
        return web.Response(body=payload, content_type="text/html", charset="utf-8", headers={
            "X-DNP-Panel-Build": PANEL_BUILD,
            "X-DNP-Panel-HTML-SHA256": hashlib.sha256(payload).hexdigest(),
        })

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

        # Bevorzuge berechtigte Guilds mit aktiv gebundenen Serverprofilen.
        # Eine noch unkonfigurierte Guild bleibt nur als Setup-Fallback erhalten.
        fallback = None
        for guild in self.bot.guilds:
            member = guild.get_member(int(user_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(user_id))
                except (discord.NotFound, discord.HTTPException):
                    continue
            perms = await self.member_permissions(member)
            if not perms:
                continue
            if self.profiles.for_guild(guild.id):
                token = await asyncio.to_thread(db.create_login_token, str(user_id), str(guild.id), member.display_name)
                return web.HTTPFound(f"/?login={token}")
            if fallback is None:
                fallback = (guild, member)

        if fallback is not None:
            guild, member = fallback
            token = await asyncio.to_thread(db.create_login_token, str(user_id), str(guild.id), member.display_name)
            return web.HTTPFound(f"/?login={token}")

        return web.HTTPFound("/?oauth=noperm")

    async def http_login(self, request: web.Request):
        data = await self._read_json(request)
        session = await asyncio.to_thread(db.redeem_login_token, str(data.get("token", "")))
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

    async def http_panel_profiles(self, request: web.Request):
        return web.json_response({
            "profiles": [profile.public() for profile in self.profiles.for_guild(request["member"].guild.id)],
            "selected": None,
        })

    async def http_panel_state(self, request: web.Request):
        perms = request["perms"]
        state = await asyncio.to_thread(db.get_server_state)
        recent_actions = await asyncio.to_thread(db.get_recent_actions)
        payload = {
            "permissions": sorted(perms),
            "actorId": str(request["member"].id),
            "name": request["session"]["display_name"],
            "actions": project_actions(recent_actions, perms),
            "server": None,
            "limits": {"money": self.money_max, "item": self.item_max},
            "locked": await self.profile_locked(),
            "profile": {key: request["profile"][key] for key in ("id", "label", "environment")},
            "is_admin": await self.is_panel_admin(request["member"]),
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
                            p["discord_username"] = m.name
                            p["discord_global_name"] = getattr(m, "global_name", None)
                    enriched.append(p)
                server["players"] = enriched
            if "server_status" in perms:
                server.update(project_bridge_health(state))
            payload["server"] = server
        if "view_logs" in perms:
            payload["events"] = await asyncio.to_thread(db.get_recent_events, 60)
        return web.json_response(payload)

    async def _player_search_current(self, request, profile):
        """Recheck the same live session, bound profile and role after async lookup."""
        if self._closing or profile is None:
            return False
        original = request['session']
        session = await asyncio.to_thread(db.get_session, original['token'])
        if (not session or str(session.get('user_id')) != str(original.get('user_id'))
                or str(session.get('guild_id')) != str(original.get('guild_id'))):
            return False
        member, permissions = await self.session_permissions(session)
        if (member is None or 'view_players' not in permissions or self._closing
                or str(member.guild.id) != str(original['guild_id'])
                or self.profiles.select(profile.id, member.guild.id) is not profile
                or db.current_profile() != profile.id):
            return False
        request['member'] = member
        return True

    async def _player_search_params(self, request, query, supplied):
        if set(supplied) - {'query_kind'}:
            raise ValueError('Nur die Suchart darf vom Browser gesetzt werden.')
        kind = supplied.get('query_kind', 'character')
        if kind not in ('character', 'discord'):
            raise ValueError('Unbekannte Suchart.')
        profile = self.profiles.select(request['profile']['id'], request['member'].guild.id)
        if profile is None:
            raise ValueError('Serverprofil ist nicht mehr freigegeben.')
        key = (profile.id, str(request['member'].guild.id), str(request['member'].id))
        gate = getattr(self, '_player_search_gate', None)
        if gate is None:
            gate = self._player_search_gate = {}
        now = time.monotonic()
        for old_key, state in list(gate.items()):
            if not state['busy'] and now - state['at'] > 60:
                gate.pop(old_key, None)
        old = gate.get(key)
        if old and (old['busy'] or now - old['at'] < 1):
            raise ValueError('Suche läuft bereits oder wurde gerade gestartet. Bitte kurz warten.')
        if old is None and len(gate) >= 256:
            raise ValueError('Zu viele laufende Suchanfragen. Bitte kurz warten.')
        state = {'at': now, 'busy': True}
        gate[key] = state
        try:
            params = {'search_schema': 2, 'query_kind': kind}
            if kind == 'discord':
                guild = request['member'].guild
                matches, seen = [], set()
                needle = _player_search_fold(query.removeprefix('@'))
                if len(needle) < 2:
                    raise ValueError('Discord-Namen brauchen mindestens zwei Zeichen ohne @.')
                cached = list(guild.members)
                total = getattr(guild, 'member_count', None)
                incomplete = not isinstance(total, int) or len(cached) < total

                def push(member):
                    identifier = str(getattr(member, 'id', ''))
                    if (len(matches) >= 10 or not _player_search_discord_id(identifier)
                            or identifier in seen or str(getattr(getattr(member, 'guild', None), 'id', '')) != str(guild.id)):
                        return
                    fields = {name: str(getattr(member, name, '') or '')[:100]
                              for name in ('name', 'display_name', 'global_name')}
                    seen.add(identifier)
                    matches.append({'id': identifier, 'username': fields['name'],
                                    'display_name': fields['display_name'], 'global_name': fields['global_name']})

                raw_id = query.removeprefix('discord:').strip()
                if _player_search_discord_id(raw_id):
                    member = guild.get_member(int(raw_id))
                    if member is None:
                        try:
                            member = await asyncio.wait_for(guild.fetch_member(int(raw_id)), timeout=4)
                        except discord.NotFound:
                            member = None
                        except (discord.HTTPException, asyncio.TimeoutError):
                            member, incomplete = None, True
                    if member is not None:
                        push(member)
                    # An exact resolved ID is complete even if the guild cache is partial.
                    incomplete = member is None and incomplete
                else:
                    for member in cached:
                        if any(needle in _player_search_fold(getattr(member, field, '') or '')
                               for field in ('name', 'display_name', 'global_name')):
                            push(member)
                            if len(matches) == 10:
                                incomplete = True
                                break
                    # No full-guild chunk: one bounded gateway query only when cache coverage is partial.
                    if incomplete and len(matches) < 10:
                        try:
                            found = await asyncio.wait_for(guild.query_members(query=query.removeprefix('@'), limit=10), timeout=4)
                            for member in found:
                                if any(needle in _player_search_fold(getattr(member, field, '') or '')
                                       for field in ('name', 'display_name', 'global_name')):
                                    push(member)
                        except (discord.HTTPException, discord.ClientException, asyncio.TimeoutError):
                            pass
                params.update(discord_ids=[member['id'] for member in matches], discord_matches=matches,
                              lookup_incomplete=incomplete)
            if not await self._player_search_current(request, profile):
                raise ValueError('Sitzung, Serverprofil oder Spielerleserecht hat sich geändert. Bitte erneut anmelden.')
            return params
        finally:
            state['busy'] = False

    async def http_panel_action(self, request: web.Request):
        data = await self._read_json(request)
        action_type = data.get("action_type")
        target = str(data.get("target", "")).strip()
        params = data.get("params") or {}
        if not isinstance(params, dict):
            return web.json_response({"error": "params muss ein Objekt sein"}, status=400)

        needed = ACTION_PERMISSION.get(action_type)
        if not needed:
            return web.json_response({"error": "ungültiger action_type"}, status=400)
        if needed not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        if not target:
            return web.json_response({"error": "target fehlt"}, status=400)

        if action_type == "search_player":
            try:
                target = _player_search_query(data.get("target"))
                params = await self._player_search_params(request, target, params)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)

        if action_type in {"support_vehicle_search", "support_vehicle_case", "support_diagnose"}:
            if target != "*":
                return web.json_response({"error": "support_target_must_be_star"}, status=400)
            try:
                params = support_action_params(action_type, params, request["profile"]["id"])
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)

        if action_type == "car_to_garage":
            try:
                params = parking_action_params(target, params)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)

        # Lockdown: nur noch Diagnose erlaubt, alle handelnden Aktionen blockiert
        if action_type not in READ_ACTIONS and await self.profile_locked():
            return web.json_response({"error": "🔒 Panel im Lockdown – Aktionen gesperrt"}, status=423)

        # Wert-Validierung + Sicherheits-Limits – analog zu den Discord-Befehlen.
        # Schützt vor kompromittierten Sessions / manipulierten Requests / Vertippern.
        if action_type == "money":
            try:
                amount = int(params.get("amount"))
            except (TypeError, ValueError):
                return web.json_response({"error": "amount muss eine Zahl sein"}, status=400)
            if params.get("op") not in ("add", "remove"):
                return web.json_response({"error": "op muss add oder remove sein"}, status=400)
            if params.get("account") not in ("cash", "bank"):
                return web.json_response({"error": "account muss cash oder bank sein"}, status=400)
            if amount <= 0:
                return web.json_response({"error": "amount muss größer als 0 sein"}, status=400)
            if amount > self.money_max:
                return web.json_response(
                    {"error": f"Limit überschritten: max. {self.money_max:,} $ pro Aktion".replace(",", ".")},
                    status=400)
        if action_type == "ban":
            try:
                hours = int(params.get("hours", 0))
            except (TypeError, ValueError):
                return web.json_response({"error": "hours muss eine Zahl sein"}, status=400)
            if hours < 0:
                return web.json_response({"error": "hours darf nicht negativ sein (0 = permanent)"}, status=400)
            params["hours"] = hours
            params["reason"] = str(params.get("reason") or "").strip()[:500]
        if action_type in ("set_job", "set_gang"):
            try:
                params["grade"] = int(params.get("grade", 0))
            except (TypeError, ValueError):
                return web.json_response({"error": "grade muss eine Zahl sein"}, status=400)
        if action_type in ("give_item", "remove_item"):
            try:
                count = int(params.get("count"))
            except (TypeError, ValueError):
                return web.json_response({"error": "count muss eine Zahl sein"}, status=400)
            if count < 1:
                return web.json_response({"error": "count muss mindestens 1 sein"}, status=400)
            if count > self.item_max:
                return web.json_response(
                    {"error": f"Limit überschritten: max. {self.item_max} Stück pro Aktion"},
                    status=400)

        member = request["member"]
        action_id = await asyncio.to_thread(
            db.add_action,
            action_type, target, json.dumps(params),
            f"web:{member.display_name}",
        )
        return web.json_response({"ok": True, "id": action_id})

    # ---------------- Bridge-Endpoints (FiveM) ----------------

    async def http_bridge_sync(self, request: web.Request):
        """Ein Roundtrip: FiveM liefert Server-State + Events, bekommt offene Actions + Ban-Liste."""
        data = await self._read_json(request)
        state = data.get("state")
        if isinstance(state, dict):
            await asyncio.to_thread(db.save_server_state, state)
        events = data.get("events")
        if isinstance(events, list) and events:
            await asyncio.to_thread(db.add_events, events[:100])
            await self._dispatch_alerts(events[:100])
        # Bans an die Bridge, damit sie beim Connect enforced werden können
        active_bans = await asyncio.to_thread(db.get_active_bans)
        bans = [
            {"license": b.get("license"), "discord": b.get("discord"),
             "citizenid": b.get("citizenid"), "reason": b.get("reason"),
             "expires_at": b.get("expires_at")}
            for b in active_bans
        ]
        # Im Lockdown werden keine offenen Aktionen ausgeliefert (Not-Aus).
        actions = await asyncio.to_thread(db.get_pending_actions)
        if await self.profile_locked():
            actions = [action for action in actions if action["action_type"] in READ_ACTIONS]
        return web.json_response({"actions": actions, "bans": bans})

    async def _dispatch_alerts(self, events: list):
        """Postet alert-/warn-Events sofort in den konfigurierten Discord-Channel."""
        channel_id = await self.profile_setting("alert_channel")
        if not channel_id:
            return
        channel = self.profile_channel(channel_id)
        if not channel:
            return
        colors = {"alert": discord.Color.red(), "warn": discord.Color.orange()}
        embeds = []
        for e in events:
            if not isinstance(e, dict):
                continue
            sev = e.get("severity")
            if sev not in colors:
                continue
            who = str(e.get("name") or "?")[:100]
            if e.get("citizenid"):
                who += f" (`{str(e['citizenid'])[:50]}`)"
            embeds.append(discord.Embed(
                title=(("🚨 " if sev == "alert" else "⚠️ ") + str(e.get("type", "event")))[:256],
                description=f"**{who}**\n{str(e.get('message', ''))[:1500]}",
                color=colors[sev],
            ))
        # Bis zu 10 Embeds pro Nachricht statt einer Nachricht je Event (Rate-Limits).
        for i in range(0, len(embeds), 10):
            try:
                await channel.send(embeds=embeds[i:i + 10])
            except discord.HTTPException:
                log.warning("Alert konnte nicht in den Channel gesendet werden.")

    async def http_player_history(self, request: web.Request):
        # Akte (Aktionen, Notizen, Verwarnungen, Ban) nur für Rollen mit Spieler-/Moderationsbezug –
        # vorher reichte JEDE Session (z. B. reines "editor"-Preset für den Server-Status).
        if not ({"view_players", "notes", "ban"} & request["perms"]):
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        cid = (request.query.get("cid") or "").strip()
        if not cid:
            return web.json_response({"error": "cid fehlt"}, status=400)
        actions = await asyncio.to_thread(db.get_actions_for, cid)
        notes = await asyncio.to_thread(db.get_notes, cid)
        ban = await asyncio.to_thread(db.get_ban, cid)
        payload = {
            "actions": project_actions(actions, request["perms"]),
            "events": [],
            "notes": notes,
            "can_note": "notes" in request["perms"],
            "can_ban": "ban" in request["perms"],
            "ban": ban,
        }
        if "view_logs" in request["perms"]:
            payload["events"] = await asyncio.to_thread(db.get_events_for, cid)
        return web.json_response(payload)

    async def http_add_note(self, request: web.Request):
        if "notes" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        data = await self._read_json(request)
        cid = str(data.get("cid", "")).strip()
        kind = data.get("kind")
        text = str(data.get("text", "")).strip()
        if not cid or kind not in ("note", "warn") or not text:
            return web.json_response({"error": "cid/kind/text fehlt"}, status=400)
        note_id = await asyncio.to_thread(db.add_note, cid, kind, text[:1000], f"web:{request['member'].display_name}")
        return web.json_response({"ok": True, "id": note_id})

    async def http_delete_note(self, request: web.Request):
        if "notes" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        data = await self._read_json(request)
        note_id = data.get("id")
        if not isinstance(note_id, int):
            return web.json_response({"error": "id fehlt"}, status=400)
        ok = await asyncio.to_thread(db.delete_note, note_id)
        return web.json_response({"ok": ok})

    async def http_get_bans(self, request: web.Request):
        if "ban" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        bans = await asyncio.to_thread(db.get_active_bans)
        return web.json_response({"bans": bans})

    async def http_unban(self, request: web.Request):
        if "ban" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        data = await self._read_json(request)
        cid = str(data.get("cid", "")).strip()
        if not cid:
            return web.json_response({"error": "cid fehlt"}, status=400)
        removed = await asyncio.to_thread(db.remove_ban, cid)
        if removed:
            await self._audit(f"🔓 **Unban** · `{cid}` · von {request['member'].display_name}")
        return web.json_response({"ok": removed})

    async def http_audit(self, request: web.Request):
        if "audit" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        audit_actions = await asyncio.to_thread(db.get_actions_audit)
        bans = await asyncio.to_thread(db.get_active_bans)
        return web.json_response({
            "actions": project_actions(audit_actions, request["perms"]),
            "bans": bans,
        })

    # -------- Rollen-Verwaltung (NUR Discord-Administratoren) --------

    async def http_get_role_map(self, request: web.Request):
        member = request["member"]
        if not await self.is_panel_admin(member):
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
        # Einzelpersonen-Zugriffe (Namen live auflösen; weg vom Server = kennzeichnen)
        user_map = await self.config.guild(guild).user_map()
        users = []
        for uid, preset in user_map.items():
            m = guild.get_member(int(uid)) if uid.isdigit() else None
            users.append({
                "id": uid,
                "name": m.display_name if m else f"nicht mehr auf dem Server ({uid})",
                "on_guild": m is not None,
                "is_admin": self._is_panel_admin_sync(m),
                "preset": preset,
            })
        users.sort(key=lambda u: u["name"].lower())
        return web.json_response({"roles": roles, "users": users, "presets": sorted(PRESETS.keys())})

    async def http_user_search(self, request: web.Request):
        """Mitglieder-Suche für Einzelpersonen-Zugriffe (nur Discord-Admins)."""
        member = request["member"]
        if not await self.is_panel_admin(member):
            return web.json_response({"error": "Nur Discord-Administratoren"}, status=403)
        q = (request.query.get("q") or "").strip()
        if len(q) < 2:
            return web.json_response({"results": []})
        guild = member.guild
        results, seen = [], set()

        def push(m):
            if m.bot or m.id in seen:
                return
            seen.add(m.id)
            results.append({
                "id": str(m.id),
                "name": m.display_name,
                "username": m.name,
                "is_admin": self._is_panel_admin_sync(m),
            })

        needle = q.lower()
        # 1) lokaler Member-Cache (deckt die meisten Fälle sofort ab)
        for m in guild.members:
            if needle in m.display_name.lower() or needle in m.name.lower():
                push(m)
                if len(results) >= 10:
                    break
        # 2) Gateway-Suche als Ergänzung (findet auch nicht gecachte Mitglieder)
        if len(results) < 10:
            try:
                for m in await guild.query_members(query=q, limit=10):
                    push(m)
            except (discord.HTTPException, asyncio.TimeoutError):
                pass
        return web.json_response({"results": results[:10]})

    async def http_set_user_map(self, request: web.Request):
        """Einzelperson ein Preset geben/entziehen (nur Discord-Admins)."""
        member = request["member"]
        if not await self.is_panel_admin(member):
            return web.json_response({"error": "Nur Discord-Administratoren"}, status=403)
        data = await self._read_json(request)
        user_id = str(data.get("user_id", "")).strip()
        preset = data.get("preset") or None
        if not user_id.isdigit():
            return web.json_response({"error": "Ungültige Nutzer-ID"}, status=400)
        if preset is not None and preset not in PRESETS:
            return web.json_response({"error": "Unbekanntes Preset"}, status=400)
        guild = member.guild
        target = guild.get_member(int(user_id))
        if target is None and preset is not None:
            # Beim ENTFERNEN darf der Nutzer den Server bereits verlassen haben
            try:
                target = await guild.fetch_member(int(user_id))
            except (discord.NotFound, discord.HTTPException):
                return web.json_response({"error": "Nutzer nicht auf diesem Server"}, status=400)
        if target is not None and target.bot:
            return web.json_response({"error": "Bots bekommen keinen Panel-Zugriff"}, status=400)
        async with self.config.guild(guild).user_map() as user_map:
            if preset:
                user_map[user_id] = preset
            else:
                user_map.pop(user_id, None)
        label = target.display_name if target else user_id
        await self._audit(f"🔧 **Einzel-Zugriff** · {label} (`{user_id}`) → {preset or '— entfernt'} · von {member.display_name} (Panel)")
        return web.json_response({"ok": True})

    async def http_set_role_map(self, request: web.Request):
        member = request["member"]
        if not await self.is_panel_admin(member):
            return web.json_response({"error": "Nur Discord-Administratoren"}, status=403)
        data = await self._read_json(request)
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
        data = await self._read_json(request)
        items = data.get("items")
        garages = data.get("garages")
        if isinstance(items, list):
            await asyncio.to_thread(db.save_catalog, {
                "items": items[:5000],
                "garages": garages[:100] if isinstance(garages, list) else [],
            })
        return web.json_response({"ok": True})

    async def http_panel_catalog(self, request: web.Request):
        if "items" not in request["perms"] and "view_inventory" not in request["perms"]:
            return web.json_response({"error": "keine Berechtigung"}, status=403)
        catalog = await asyncio.to_thread(db.get_catalog)
        return web.json_response(catalog or {"items": []})

    async def http_bridge_result(self, request: web.Request):
        data = await self._read_json(request)
        if not isinstance(data, dict):
            return web.json_response({"error": "invalid_payload"}, status=400)
        action_id = data.get("id")
        if not isinstance(action_id, str) or not action_id or len(action_id) > 128:
            return web.json_response({"error": "invalid_id"}, status=400)
        status = data.get("status")
        result = data.get("result", "")
        previous = await asyncio.to_thread(db.get_action, action_id)
        if previous is None:
            return web.json_response({"error": "action_not_found"}, status=404)
        try:
            saved = await asyncio.to_thread(
                db.mark_action_result, action_id, status, result,
                resolved_target=data.get("resolved_target"), resolved_name=data.get("resolved_name"),
                audit_required=previous["action_type"] in SENSITIVE_ACTIONS,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        action = saved["action"]
        if saved["outcome"] == "not_found":
            return web.json_response({"error": "action_not_found"}, status=404)
        if saved["outcome"] == "conflict":
            # Die Bridge darf nur ihr gespeichertes Ergebnis erneut melden; eine
            # Abweichung ist kein Auftrag zur erneuten Ausführung oder Freigabe.
            log.warning("Widersprüchlicher terminaler Bridge-Callback für Aktion %s", action_id)
            return web.json_response({"error": "terminal_callback_conflict", "review_required": True}, status=409)
        review_required = (bool(action.get("result_review_required"))
                           or action.get("audit_delivery") in ("claimed", "uncertain"))
        if await asyncio.to_thread(db.claim_result_audit, action_id):
            delivery = "uncertain"
            try:
                sent = await self._audit_action(action)
                delivery = "sent" if sent is True else "not_configured" if sent is False else "uncertain"
            except Exception:
                # Nach Versandfehler/Prozessabbruch keine doppelte Nachricht riskieren.
                # Die reservierte Zustellung bleibt in der DB nachvollziehbar.
                log.exception("Audit-Zustellung für Aktion %s nicht bestätigt", action_id)
            finally:
                await asyncio.to_thread(db.finish_result_audit, action_id, delivery)
            review_required = review_required or delivery == "uncertain"
        return web.json_response({
            "ok": True, "replayed": saved["outcome"] == "replayed",
            "review_required": review_required,
        })

    async def set_lockdown(self, enabled: bool, by: str) -> int:
        """Not-Aus schalten (gemeinsam für `[p]ap lockdown` und das Dashboard).

        Aktivieren verwirft alle offenen Aufträge – sonst würden sie nach dem Aufheben doch
        noch ausgeführt (genau die Aufträge, wegen derer man evtl. den Not-Aus zieht).
        Rückgabe: Anzahl verworfener Aufträge (beim Aufheben 0).
        """
        if enabled:
            await self.set_profile_setting("locked", True)
            dropped = await asyncio.to_thread(db.cancel_pending_actions, f"Verworfen durch Lockdown ({by})")
            await self._audit(f"🔒 **LOCKDOWN AKTIVIERT** von {by} · {dropped} offene Aufträge verworfen")
            return dropped
        await self.set_profile_setting("locked", False)
        await self._audit(f"🔓 Lockdown aufgehoben von {by}")
        return 0

    async def _audit(self, text: str):
        channel_id = await self.profile_setting("audit_channel")
        if not channel_id:
            return False
        channel = self.profile_channel(channel_id)
        if channel:
            try:
                await channel.send(text)
                return True
            except discord.HTTPException:
                return None
        return None

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
            try:
                hrs = int(params.get("hours") or 0)
            except (TypeError, ValueError):
                hrs = 0
            detail = ("permanent" if hrs <= 0 else f"{hrs}h") + f" · {params.get('reason', '')}"
        status_icon = "✅" if action["status"] == "done" else "❌"
        return await self._audit(
            f"[{db.current_profile()}] {icons.get(action['action_type'], '•')} **{action['action_type']}** {status_icon}\n"
            f"Ziel: `{action['target']}` · {detail}\nDurch: {who}"
        )

    # --------------------------------------------------------------
    # Discord-Commands
    # --------------------------------------------------------------

    async def cog_before_invoke(self, ctx):
        command = getattr(getattr(ctx, "command", None), "qualified_name", "")
        if command == "ap version":
            if not await self.bot.is_owner(ctx.author):
                raise commands.CheckFailure("Die Versionsdiagnose ist nur für Bot-Owner.")
            return
        if command == "ap" or command in ("ap server", "ap login", "ap profile") or command.startswith(("ap profile ", "ap roles")):
            return
        if command == "ap config" or command.startswith("ap config "):
            if not await self.bot.is_owner(ctx.author):
                raise commands.CheckFailure("Botweite Einstellungen dürfen nur Bot-Owner ändern.")
            return
        if ctx.guild is None:
            raise commands.CheckFailure("Serverprofil nur innerhalb der zugeordneten Discord-Guild auswählen.")
        selected = await self.config.guild(ctx.guild).profile_selection()
        profile = self.profiles.select(selected.get(str(ctx.author.id)), ctx.guild.id)
        if profile is None or not await self.member_permissions(ctx.author):
            raise commands.CheckFailure("Zuerst mit ap server <Profil> ein erlaubtes Serverprofil auswählen.")
        manager = db.profile_scope(profile.id)
        manager.__enter__()
        ctx._adminpanel_profile_scope = manager
        ctx.adminpanel_profile = profile.public(internal=True)

    async def cog_after_invoke(self, ctx):
        manager = getattr(ctx, "_adminpanel_profile_scope", None)
        if manager is not None:
            del ctx._adminpanel_profile_scope
            manager.__exit__(None, None, None)

    async def _require(self, ctx: commands.Context, permission: str, *, acting: bool = True) -> bool:
        """Rechte-Check für Discord-Befehle. ``acting=True``: Befehl legt eine Aktion
        im Spiel an und ist im Lockdown gesperrt (wie im Webpanel)."""
        if ctx.guild is None:
            await ctx.send("Bitte auf dem Server nutzen, nicht per DM.")
            return False
        perms = await self.member_permissions(ctx.author)
        if permission not in perms:
            await ctx.send("❌ Dafür fehlt dir die Berechtigung.")
            return False
        if acting and await self.profile_locked():
            await ctx.send("🔒 Panel im Lockdown – Aktionen sind gesperrt.")
            return False
        return True

    @commands.group(name="ap")
    async def ap(self, ctx: commands.Context):
        """Adminpanel-Befehle."""

    @ap.command(name="version")
    @commands.is_owner()
    async def ap_version(self, ctx: commands.Context):
        """Geladenen Cog und ausgelieferte HTML-Datei rein lesend unterscheiden."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("Die Versionsdiagnose ist nur für Bot-Owner.")
        info = _frontend_version()
        await ctx.send(
            "DNP Admin Zentrale · " + info["build"]
            + "\nCog-Quelldatei beim Laden SHA-256: `" + (info["loaded_module_sha256"] or "nicht bestätigt") + "`"
            + "\nHTML SHA-256: `" + (info["html_sha256"] or "nicht lesbar") + "`"
            + "\nFrontend: panel.html; unabhängig von der FiveM-Bridge."
            + "\nReine Versionsleseprüfung – keine Serveraktion, kein Reload, keine Datenänderung."
        )

    @ap.command(name="server")
    @commands.guild_only()
    async def ap_server(self, ctx: commands.Context, profile_id: str = None):
        """Explizites Serverprofil für nachfolgende Discord-Befehle auswählen."""
        if ctx.guild is None or not await self.member_permissions(ctx.author):
            return await ctx.send("Keine Panel-Berechtigung in dieser Discord-Guild.")
        available = self.profiles.for_guild(ctx.guild.id)
        if profile_id is None:
            text = ", ".join(f"{profile.id}: {profile.label}" for profile in available) or "keine gebundenen Profile"
            return await ctx.send("Serverprofile: " + text + ". Auswahl: ap server <Profil>.")
        profile = self.profiles.select(profile_id, ctx.guild.id)
        if profile is None:
            return await ctx.send("Dieses Serverprofil ist dieser Discord-Guild nicht freigegeben.")
        value = await self.config.guild(ctx.guild).profile_selection()
        value[str(ctx.author.id)] = profile.id
        await self.config.guild(ctx.guild).profile_selection.set(value)
        await ctx.send(f"Serverprofil ausgewählt: {profile.label} ({profile.id}).")

    @ap.group(name="profile")
    @commands.guild_only()
    async def ap_profile(self, ctx: commands.Context):
        """Owner-Konfiguration: bind / keyenv. Keine Secrets im Chat."""

    @ap_profile.command(name="bind")
    async def ap_profile_bind(self, ctx: commands.Context, profile_id: str, *, label: str = ""):
        if ctx.guild is None or not await self.bot.is_owner(ctx.author):
            return await ctx.send("Profilbindungen dürfen nur Bot-Owner in der Ziel-Guild festlegen.")
        if profile_id not in ALLOWED_PROFILES:
            return await ctx.send("Ungültige Profilkennung.")
        async with self._profile_config_lock:
            records = await self.config.server_profiles()
            records = dict(records) if isinstance(records, dict) else {}
            record = dict(records.get(profile_id) or {})
            if record.get("guild_id") and str(record["guild_id"]) != str(ctx.guild.id):
                return await ctx.send("Bereits an eine andere Guild gebunden; keine automatische Umbindung.")
            record.update(guild_id=str(ctx.guild.id), label=(label.strip() or profile_id)[:64])
            record.setdefault("enabled", True)
            if profile_id != "legacy":
                record.setdefault("key_env", "ADMINPANEL_" + profile_id.upper().replace("-", "_") + "_KEY")
            records[profile_id] = record
            await self.config.server_profiles.set(records)
            await self._refresh_profiles()
        await ctx.send(f"Profil {profile_id} explizit an diese Guild gebunden. Daten/Queues wurden nicht verschoben.")

    @ap_profile.command(name="keyenv")
    async def ap_profile_keyenv(self, ctx: commands.Context, profile_id: str, variable: str):
        if ctx.guild is None or not await self.bot.is_owner(ctx.author):
            return await ctx.send("Schlüsselzuordnungen dürfen nur Bot-Owner festlegen.")
        if not PROFILE_ID.fullmatch(profile_id) or not ENV_NAME.fullmatch(variable):
            return await ctx.send("Nur Profilkennung und Name einer vorhandenen Umgebungsvariable angeben; keine Schlüsselwerte.")
        async with self._profile_config_lock:
            records = await self.config.server_profiles()
            record = dict(records.get(profile_id) or {}) if isinstance(records, dict) else {}
            if str(record.get("guild_id", "")) != str(ctx.guild.id):
                return await ctx.send("Profil zuerst explizit an diese Guild binden.")
            record["key_env"] = variable
            records = dict(records)
            records[profile_id] = record
            await self.config.server_profiles.set(records)
            await self._refresh_profiles()
        await ctx.send("Umgebungsvariable dem Profil zugeordnet. Kein Schlüsselwert wird angezeigt oder erzeugt.")

    # ---- Login ----

    @ap.command(name="login")
    @commands.guild_only()
    async def ap_login(self, ctx: commands.Context):
        """Schickt dir per DM einen Einmal-Link für das Webpanel (5 Min gültig)."""
        perms = await self.member_permissions(ctx.author)
        if not perms:
            return await ctx.send("❌ Du hast keine Panel-Berechtigung. "
                                  "Ein Admin kann deine Rolle mit `!ap roles set` freischalten.")
        token = await asyncio.to_thread(
            db.create_login_token,
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
        await asyncio.to_thread(db.add_action, "teleport", spieler,
                                json.dumps({"to_spieler": target_spieler}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Teleport `{spieler}` → `{target_spieler}` angelegt.")

    @ap.command(name="heal")
    async def ap_heal(self, ctx: commands.Context, spieler: str):
        """Heilt einen Spieler vollständig."""
        if not await self._require(ctx, "heal"):
            return
        await asyncio.to_thread(db.add_action, "heal", spieler, None, f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Heal für `{spieler}` angelegt.")

    @ap.command(name="revive")
    async def ap_revive(self, ctx: commands.Context, spieler: str):
        """Belebt einen Spieler wieder."""
        if not await self._require(ctx, "revive"):
            return
        await asyncio.to_thread(db.add_action, "revive", spieler, None, f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Revive für `{spieler}` angelegt.")

    @ap.command(name="kick")
    async def ap_kick(self, ctx: commands.Context, spieler: str, *, reason: str = "Vom Support gekickt"):
        """Kickt einen Spieler. Beispiel: !ap kick ABC123 Beleidigung"""
        if not await self._require(ctx, "kick"):
            return
        await asyncio.to_thread(db.add_action, "kick", spieler, json.dumps({"reason": reason}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Kick für `{spieler}` angelegt. Grund: {reason}")

    @ap.command(name="announce")
    async def ap_announce(self, ctx: commands.Context, *, message: str):
        """Sendet eine Server-Ansage an alle Spieler."""
        if not await self._require(ctx, "announce"):
            return
        await asyncio.to_thread(db.add_action, "announce", "*", json.dumps({"message": message}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send("✅ Ansage angelegt.")

    @ap.command(name="car2garage")
    async def ap_car2garage(self, ctx: commands.Context, plate: str, garage: str = ""):
        """Packt ein Fahrzeug per Kennzeichen in eine Garage."""
        if not await self._require(ctx, "car_to_garage"):
            return
        try:
            params = parking_action_params(plate, {"garage": garage})
        except ValueError:
            return await ctx.send("Kennzeichen oder Garage ist ungültig. Es wurde kein Auftrag angelegt.")
        await asyncio.to_thread(db.add_action, "car_to_garage", plate, json.dumps(params),
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
        await asyncio.to_thread(db.add_action, "money", spieler,
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
        await asyncio.to_thread(db.add_action, "give_item", spieler,
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
        await asyncio.to_thread(db.add_action, "remove_item", spieler,
                                json.dumps({"item": item, "count": count}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Entfernen von `{item}` ×{count} bei `{spieler}` angelegt.")

    @ap.command(name="inv")
    async def ap_inv(self, ctx: commands.Context, spieler: str):
        """Zeigt das Inventar eines Spielers. Beispiel: !ap inv ABC123"""
        if not await self._require(ctx, "view_inventory", acting=False):
            return
        action_id = await asyncio.to_thread(db.add_action, "get_inventory", spieler, None,
                                            f"discord:{ctx.author.display_name}")
        msg = await ctx.send(f"⏳ Frage Inventar von `{spieler}` ab…")

        for _ in range(12):  # max. ~12 Sekunden auf die Bridge warten
            await asyncio.sleep(1)
            action = await asyncio.to_thread(db.get_action, action_id)
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
        await asyncio.to_thread(db.add_action, "teleport_coords", spieler,
                                json.dumps({"x": x, "y": y, "z": z}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Teleport `{spieler}` → `{x}, {y}, {z}` angelegt.")

    @ap.command(name="cars")
    async def ap_cars(self, ctx: commands.Context, spieler: str):
        """Zeigt die Fahrzeuge eines Spielers (auch offline). Beispiel: !ap cars ABC123"""
        if not await self._require(ctx, "car_to_garage", acting=False):
            return
        action_id = await asyncio.to_thread(db.add_action, "get_vehicles", spieler, None,
                                            f"discord:{ctx.author.display_name}")
        msg = await ctx.send(f"⏳ Frage Fahrzeuge von `{spieler}` ab…")

        for _ in range(12):
            await asyncio.sleep(1)
            action = await asyncio.to_thread(db.get_action, action_id)
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
            await self.set_profile_setting("alert_channel", None)
            return await ctx.send("🔕 Alert-Channel deaktiviert.")
        if str(channel.guild.id) != self.profiles.items[db.current_profile()].guild_id:
            return await ctx.send("Kanal gehört nicht zur freigegebenen Profil-Guild.")
        await self.set_profile_setting("alert_channel", channel.id)
        await ctx.send(f"🚨 Alerts (Geld-/Item-Sprünge, Dupe-Muster) gehen jetzt nach {channel.mention}.")

    @ap.command(name="find")
    async def ap_find(self, ctx: commands.Context, *, query: str):
        """Sucht Spieler in der DB (Name oder CID, auch offline). Beispiel: !ap find Kevin"""
        if not await self._require(ctx, "view_players", acting=False):
            return
        action_id = await asyncio.to_thread(db.add_action, "search_player", query, None,
                                            f"discord:{ctx.author.display_name}")
        msg = await ctx.send(f"⏳ Suche nach `{query}`…")
        for _ in range(12):
            await asyncio.sleep(1)
            action = await asyncio.to_thread(db.get_action, action_id)
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
                try:
                    bank = f"{int(r.get('bank') or 0):,}".replace(",", ".")
                except (TypeError, ValueError):
                    bank = str(r.get("bank"))
                lines.append(f"**{r.get('charname', '?')}** · `{r.get('citizenid')}` · "
                             f"{r.get('job') or 'kein Job'} · Bank: {bank}$")
            embed.description = "\n".join(lines)
            return await msg.edit(content=None, embed=embed)
        await msg.edit(content="❌ Keine Antwort von der FiveM-Bridge – läuft der Server?")

    @ap.command(name="setjob")
    async def ap_setjob(self, ctx: commands.Context, spieler: str, job: str, grade: int = 0):
        """Setzt den Job eines Online-Spielers. Beispiel: !ap setjob Kevin police 2"""
        if not await self._require(ctx, "setjob"):
            return
        await asyncio.to_thread(db.add_action, "set_job", spieler, json.dumps({"job": job, "grade": grade}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Job `{job}` (Grade {grade}) für `{spieler}` angelegt.")

    @ap.command(name="setgang")
    async def ap_setgang(self, ctx: commands.Context, spieler: str, gang: str, grade: int = 0):
        """Setzt die Gang eines Online-Spielers. Beispiel: !ap setgang Kevin ballas 1"""
        if not await self._require(ctx, "setjob"):
            return
        await asyncio.to_thread(db.add_action, "set_gang", spieler, json.dumps({"gang": gang, "grade": grade}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Gang `{gang}` (Grade {grade}) für `{spieler}` angelegt.")

    @ap.command(name="msg")
    async def ap_msg(self, ctx: commands.Context, spieler: str, *, message: str):
        """Schickt einem Spieler eine private Support-Nachricht. Beispiel: !ap msg Kevin Bitte melde dich im Support"""
        if not await self._require(ctx, "message"):
            return
        await asyncio.to_thread(db.add_action, "notify", spieler, json.dumps({"message": message}),
                                f"discord:{ctx.author.display_name}")
        await ctx.send(f"✅ Nachricht an `{spieler}` angelegt.")

    @ap.command(name="note")
    async def ap_note(self, ctx: commands.Context, citizenid: str, *, text: str):
        """Legt eine Team-Notiz zu einem Spieler an."""
        if not await self._require(ctx, "notes", acting=False):
            return
        await asyncio.to_thread(db.add_note, citizenid, "note", text[:1000], f"discord:{ctx.author.display_name}")
        await ctx.send(f"📝 Notiz für `{citizenid}` gespeichert.")

    @ap.command(name="warn")
    async def ap_warn(self, ctx: commands.Context, citizenid: str, *, text: str):
        """Spricht eine Verwarnung aus (Team-weit sichtbar in der Akte)."""
        if not await self._require(ctx, "notes", acting=False):
            return
        await asyncio.to_thread(db.add_note, citizenid, "warn", text[:1000], f"discord:{ctx.author.display_name}")
        notes = await asyncio.to_thread(db.get_notes, citizenid)
        warns = len([n for n in notes if n["kind"] == "warn"])
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
                hours = -1
            if hours < 0:  # vorher wurde "-5" stillschweigend zu einem PERMANENTEN Ban
                return await ctx.send("Dauer muss eine positive Stundenzahl oder `perm` sein.")
        await asyncio.to_thread(db.add_action, "ban", spieler, json.dumps({"hours": hours, "reason": reason}),
                                f"discord:{ctx.author.display_name}")
        dur_txt = "permanent" if hours == 0 else f"{hours} Stunden"
        await ctx.send(f"🔨 Ban für `{spieler}` ({dur_txt}) angelegt – wird beim nächsten Sync ausgeführt.")

    @ap.command(name="unban")
    async def ap_unban(self, ctx: commands.Context, citizenid: str):
        """Hebt einen Ban auf. Beispiel: !ap unban ABC123"""
        if not await self._require(ctx, "ban", acting=False):
            return
        if await asyncio.to_thread(db.remove_ban, citizenid):
            await self._audit(f"🔓 **Unban** · `{citizenid}` · von {ctx.author.display_name}")
            await ctx.send(f"🔓 Ban für `{citizenid}` aufgehoben.")
        else:
            await ctx.send(f"Kein aktiver Ban für `{citizenid}` gefunden.")

    @ap.command(name="bans")
    async def ap_bans(self, ctx: commands.Context):
        """Zeigt alle aktiven Bans."""
        if not await self._require(ctx, "ban", acting=False):
            return
        bans = await asyncio.to_thread(db.get_active_bans)
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
                name=f"{b.get('name') or '?'} · {b['citizenid']}"[:256],
                value=f"{str(b['reason'])[:200]}\nBis: {exp} · von {b['banned_by']}"[:1024],
                inline=False,
            )
        if len(bans) > 20:
            embed.set_footer(text=f"… und {len(bans) - 20} weitere (vollständig im Webpanel)")
        await ctx.send(embed=embed)

    @ap.command(name="auditchannel")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def ap_auditchannel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Setzt den Channel für das Admin-Audit-Log (Geld, Items, Bans …). Ohne Angabe: aus."""
        if channel is None:
            await self.set_profile_setting("audit_channel", None)
            return await ctx.send("🔕 Audit-Log deaktiviert.")
        if str(channel.guild.id) != self.profiles.items[db.current_profile()].guild_id:
            return await ctx.send("Kanal gehört nicht zur freigegebenen Profil-Guild.")
        await self.set_profile_setting("audit_channel", channel.id)
        await ctx.send(f"📋 Admin-Aktionen (Geld, Items, Bans, Job/Gang) werden jetzt nach {channel.mention} geloggt. "
                       f"Tipp: einen Channel wählen, auf den die Admins selbst **keinen** Schreib-/Löschzugriff haben.")

    @ap.command(name="parkall")
    async def ap_parkall(self, ctx: commands.Context, fallback_garage: str = ""):
        """Parkt ALLE gespawnten Spieler-Fahrzeuge in die nächste Garage ein. Besetzte Fahrzeuge bleiben stehen."""
        if not await self._require(ctx, "park_all"):
            return
        await asyncio.to_thread(db.add_action, "park_all", "*", json.dumps({"garage": fallback_garage}),
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
        key_disp = "❌ nicht gesetzt" if not key or key == "CHANGE_ME" else "✓ Legacy-Key gesetzt (verdeckt)"
        url = self.public_url or "— (Login nur per Token)"
        embed = discord.Embed(title="AdminPanel – Einstellungen")
        embed.add_field(name="API-Key (Bridge)", value=key_disp, inline=False)
        embed.add_field(name="Web-Port", value=str(self.web_port), inline=True)
        embed.add_field(name="Bind-Adresse", value=f"`{self.web_host}`", inline=True)
        embed.add_field(name="Public-URL", value=url, inline=False)
        embed.add_field(name="Geld-Limit / Aktion", value=f"{self.money_max:,} $".replace(",", "."), inline=True)
        embed.add_field(name="Item-Limit / Aktion", value=str(self.item_max), inline=True)
        embed.set_footer(text="Ändern: !ap config key | url | port | bind | moneymax | itemmax")
        await ctx.send(embed=embed)

    @ap_config.command(name="key")
    async def ap_config_key(self, ctx: commands.Context, custom_key: str = None):
        """Keine Schlüsselwerte im Chat/DM; Profile nutzen vorhandene Key-ENVs."""
        if custom_key:
            # Eigener Key stand im Befehl -> Nachricht sofort löschen (Secret nicht im Chat lassen)
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
        await ctx.send("Der vorhandene Legacy-Key bleibt erhalten. Für ein Serverprofil eine sichere "
                       "Umgebungsvariable außerhalb Discords konfigurieren und ap profile keyenv "
                       "<Profil> <Variablenname> verwenden. Hier wird kein Key erzeugt oder angezeigt.")

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
        """Setzt den Web-Port (wird nach `[p]reload fivemadmin` aktiv)."""
        if not (1 <= port <= 65535):
            return await ctx.send("Ungültiger Port.")
        await self.config.web_port.set(port)
        await ctx.send(f"✅ Web-Port auf {port} gesetzt. Wird nach `[p]reload fivemadmin` aktiv "
                       f"(der Server bindet den Port beim Start). Reverse-Proxy ggf. anpassen.")

    @ap_config.command(name="bind")
    async def ap_config_bind(self, ctx: commands.Context, host: str):
        """Bind-Adresse des Webservers: `127.0.0.1` (nur lokal/Reverse-Proxy) oder `0.0.0.0` (alle)."""
        import ipaddress
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return await ctx.send("Bitte eine IP-Adresse angeben, z. B. `127.0.0.1` oder `0.0.0.0`.")
        await self.config.web_host.set(host)
        await ctx.send(
            f"✅ Bind-Adresse `{host}` gespeichert. Wird nach `[p]reload fivemadmin` aktiv.\n"
            "⚠️ Mit `127.0.0.1` ist das Panel nur noch über einen Reverse-Proxy auf demselben Rechner "
            "erreichbar (bei Docker: nur, wenn der Proxy im selben Container/Host-Netz läuft)."
        )

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
        if not await self._require(ctx, "server_status", acting=False):
            return
        action_id = await asyncio.to_thread(db.add_action, "diag", "*", None, f"discord:{ctx.author.display_name}")
        msg = await ctx.send("⏳ Diagnose läuft…")
        for _ in range(12):
            await asyncio.sleep(1)
            action = await asyncio.to_thread(db.get_action, action_id)
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
            path, count = await asyncio.to_thread(db.backup_db)
            await ctx.send(f"💾 Backup erstellt: `{path}`\n({count} Backups vorhanden, ältere werden automatisch gelöscht). "
                           f"Tipp: den `backups/`-Ordner ins Synology-Backup aufnehmen.")
        except Exception as e:
            await ctx.send(f"❌ Backup fehlgeschlagen: {e}")

    @ap.command(name="lockdown")
    @commands.has_permissions(administrator=True)
    async def ap_lockdown(self, ctx: commands.Context, state: str = None):
        """NOT-AUS: sperrt sofort alle Panel-Aktionen. `!ap lockdown on` / `off`"""
        if state is None:
            current = await self.profile_locked()
            return await ctx.send(f"Lockdown ist aktuell **{'AN 🔒' if current else 'aus'}**. "
                                  f"Umschalten mit `!ap lockdown on` / `off`.")
        if state.lower() in ("on", "an", "1", "true"):
            dropped = await self.set_lockdown(True, ctx.author.display_name)
            await ctx.send(f"🔒 **Lockdown aktiv.** Alle Panel-Aktionen sind gesperrt, **{dropped}** offene Aufträge wurden verworfen. "
                           "Nur Diagnose läuft noch. Aufheben mit `!ap lockdown off`.")
        elif state.lower() in ("off", "aus", "0", "false"):
            await self.set_lockdown(False, ctx.author.display_name)
            await ctx.send("🔓 Lockdown aufgehoben – Panel wieder normal nutzbar.")
        else:
            await ctx.send("Nutzung: `!ap lockdown on` / `off`")

    @ap.command(name="status")
    async def ap_status(self, ctx: commands.Context):
        """Zeigt die letzten 10 Aktionen."""
        perms = await self.member_permissions(ctx.author) if ctx.guild is not None else set()
        if not perms:
            return await ctx.send("❌ Keine Berechtigung.")
        actions = await asyncio.to_thread(db.get_recent_actions, 10)
        actions = project_actions(actions, perms)
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
