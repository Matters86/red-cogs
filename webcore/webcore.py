import asyncio
import hashlib
import inspect
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
import aiohttp_jinja2
import jinja2
from aiohttp import web
from aiohttp_session import get_session
from aiohttp_session import setup as session_setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage

from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

import collections
import platform
from datetime import datetime, timezone

import discord

from . import access as acl
from . import backup as bk
from . import errorlog
from . import ui as _ui
from .admin_pages import (
    render_access, render_audit, render_audit_channel, render_backup, render_backup_preview, render_errors,
    render_member_home, render_portal_card, render_status,
)

try:
    import psutil
except Exception:  # psutil ist optional
    psutil = None

try:
    import resource  # nur Unix – Fallback für RAM/CPU ohne psutil
except Exception:  # pragma: no cover – Windows
    resource = None

log = logging.getLogger("red.red-cogs.webcore")

DISCORD_API = "https://discord.com/api/v10"
DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN = f"{DISCORD_API}/oauth2/token"
# Login-Sitzung läuft nach 7 Tagen ab (serverseitig geprüft, Fernet-TTL). Vorher galt
# das verschlüsselte Cookie unbegrenzt – ein einmal abgegriffenes Cookie für immer.
SESSION_MAX_AGE = 7 * 86400
# Cache-Buster für /static/webcore.css (bei Theme-Änderungen erhöhen).
ASSET_VERSION = "10"
# Rollen mit diesen Rechten darf nur vergeben (per Autorole/Ticket-Inhaberrolle …),
# wer Owner/Allowlist oder Discord-Administrator ist – sonst könnte sich ein
# Team-Mitglied mit Dashboard-Rechten selbst hochstufen.
DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
    "ban_members", "kick_members", "moderate_members", "manage_messages", "mention_everyone",
    "manage_nicknames", "manage_expressions", "manage_events", "manage_threads", "view_audit_log",
)

try:
    import redbot
    RED_VERSION = getattr(redbot, "__version__", "?")
except Exception:
    RED_VERSION = "?"
DPY_VERSION = discord.__version__
PY_VERSION = platform.python_version()

# Mitglieder-Bereich: POSTs pro Nutzer und Minute; öffentliche API: Anfragen pro IP und Minute.
MEMBER_POST_LIMIT = 30
PUBLIC_LIMIT = 60
RATE_WINDOW = 60.0
# Abgelehnte Zugriffe desselben Nutzers mit demselben Grund höchstens so oft ins Audit-Log (Sekunden).
AUDIT_DENY_THROTTLE = 60.0
# Höchstens so viele Audit-Nachrichten gleichzeitig unterwegs nach Discord (Rest wird verworfen).
AUDIT_POST_MAX_PENDING = 50
_PUBLIC_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# Sichern & Wiederherstellen: Vorschau gilt so lange (Sekunden); so viele „Rückgängig“-Stände je Server.
IMPORT_PREVIEW_TTL = 30 * 60
IMPORT_UNDO_KEEP = 5
# Namen der Owner-Seiten (Audit-Log, Discord-Embed)
OWNER_PAGE_LABELS = {
    "access": "Zugriff & Rollen", "audit": "Audit-Log", "status": "Bot-Status",
    "errors": "Fehlerprotokoll", "backup": "Sichern & Wiederherstellen",
}


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fmt(n: int) -> str:
    """Tausendertrennung im deutschen Format (24500 -> 24.500)."""
    return f"{n:,}".replace(",", ".")


class DashboardPage:
    """Eine vom Cog registrierte Dashboard-Seite (Team-Seite oder Mitgliederseite)."""

    def __init__(self, owner, slug, name, handler, icon="bi-grid", description="", visible=None, operate_forms=()):
        self.owner = owner
        self.visible = visible  # optional: async (guild) -> bool (nur Mitgliederseiten)
        self.slug = slug
        self.name = name
        self.handler = handler
        self.icon = icon
        self.description = description
        # Tagesgeschäft (Stufe „Bedienen“): Menge von form/action-Werten oder Callable (data) -> bool.
        if callable(operate_forms):
            self.operate_forms = operate_forms
        elif isinstance(operate_forms, str):
            self.operate_forms = frozenset({operate_forms}) if operate_forms else frozenset()
        else:
            self.operate_forms = frozenset(str(v) for v in (operate_forms or ()) if str(v))

    @property
    def supports_operate(self) -> bool:
        """Hat die Seite überhaupt Tagesgeschäft? Sonst wirkt „Bedienen“ wie „Ansehen“."""
        return bool(self.operate_forms)

    @property
    def operate_list(self) -> list:
        """Formular-Werte für ``data-operate-forms`` (leer bei Callable)."""
        return [] if callable(self.operate_forms) else sorted(self.operate_forms)


class PublicApi:
    """Ein öffentlicher Lese-Endpunkt unter ``/api/public/<slug>[/<tail>]``."""

    def __init__(self, owner, slug, handler):
        self.owner = owner
        self.slug = slug
        self.handler = handler


class _RateLimiter:
    """Gleitendes Fenster: höchstens ``limit`` Treffer pro ``window`` Sekunden je Schlüssel."""

    def __init__(self, limit: int, window: float = RATE_WINDOW):
        self.limit = limit
        self.window = window
        self._hits: dict = {}

    def hit(self, key) -> tuple[bool, int]:
        """(erlaubt?, Sekunden bis zum nächsten erlaubten Versuch)."""
        now = time.monotonic()
        dq = self._hits.get(key)
        if dq is None:
            if len(self._hits) > 5000:
                self._prune(now)
            dq = self._hits[key] = collections.deque()
        while dq and dq[0] <= now - self.window:
            dq.popleft()
        if len(dq) >= self.limit:
            return False, max(1, int(dq[0] + self.window - now) + 1)
        dq.append(now)
        return True, 0

    def _prune(self, now: float) -> None:
        for key in [k for k, dq in self._hits.items() if not dq or dq[-1] <= now - self.window]:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


def _parse_ip(value: str):
    value = (value or "").strip().strip('"')
    if value.startswith("[") and "]" in value:          # [IPv6]:port
        value = value[1:value.index("]")]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        if value.count(":") == 1:                         # IPv4:port
            try:
                return ipaddress.ip_address(value.split(":", 1)[0])
            except ValueError:
                return None
        return None


def _is_trusted_proxy(ip) -> bool:
    return ip is not None and (ip.is_loopback or ip.is_private)


def client_ip(request) -> str:
    """IP des Aufrufers für Rate-Limits.

    ``X-Forwarded-For`` wird nur ausgewertet, wenn die direkte Gegenstelle ein Reverse-Proxy im
    eigenen Netz ist (127.0.0.1/::1 oder privates Netz). Von rechts gelesen: vertrauenswürdige
    Proxy-Hops werden übersprungen, der erste öffentliche Eintrag ist der Client (vorne
    eingeschmuggelte Einträge des Clients zählen damit nicht).
    """
    peer = request.remote or ""
    if _is_trusted_proxy(_parse_ip(peer)):
        hops = [h for h in request.headers.get("X-Forwarded-For", "").split(",") if h.strip()]
        candidate = None
        for hop in reversed(hops):
            ip = _parse_ip(hop)
            if ip is None:
                break
            candidate = str(ip)
            if not _is_trusted_proxy(ip):
                break
        if candidate:
            return candidate
    return peer or "?"


def _trunc(text, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


@web.middleware
async def _security_headers(request, handler):
    """Sicherheits-Header für jede Antwort (wichtig, sobald das Dashboard öffentlich erreichbar ist).

    HSTS setzt bewusst der Reverse-Proxy (z. B. Synology), weil es für den ganzen Hostnamen gilt.
    """
    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        _apply_security_headers(exc)
        raise
    _apply_security_headers(resp)
    return resp


def _apply_security_headers(resp) -> None:
    h = resp.headers
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    h.setdefault("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
    ctype = h.get("Content-Type", "")
    if ctype.startswith("text/html"):
        # Seiten mit Sitzungsdaten nicht in fremden/geteilten Caches ablegen.
        h.setdefault("Cache-Control", "no-store")


class WebCore(commands.Cog):
    """Zentrales Web-Dashboard für eigene Cogs.

    Andere Cogs klinken sich ein, indem sie auf das Event ``on_webcore_ready``
    hören (bzw. in ihrem ``cog_load`` ``bot.get_cog("WebCore")`` prüfen) und
    dann ``register_page(...)`` aufrufen.
    """

    # Rechte-Stufen für Cogs (``webcore.OPERATE`` …) – nie feste Zahlen verwenden.
    NONE, VIEW, OPERATE, EDIT = acl.NONE, acl.VIEW, acl.OPERATE, acl.EDIT

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8472013561, force_registration=True)
        self.config.register_global(
            host="0.0.0.0",
            port=42100,
            client_id=None,
            client_secret=None,
            redirect_uri=None,
            secret_key=None,
            access_mode="owner",   # owner | admin | allowlist
            allowed_users=[],
            # Rollen-Rechte je Server/Seite (siehe access.py) – nur vom Owner änderbar.
            role_perms={},
            # Audit-Log aller speichernden Dashboard-Aktionen (neueste zuerst, gekappt).
            audit=[],
            # Mitglieder-Bereich („Mein Bereich“, /me) je Server: {guild_id(str): True}. Standard: überall aus.
            member_portal={},
            # Audit-Log zusätzlich als Embed in einen Discord-Kanal: {guild_id(str): channel_id}.
            audit_channels={},
        )
        self.pages: dict[str, DashboardPage] = {}
        self.member_pages: dict[str, DashboardPage] = {}
        self.public_apis: dict[str, PublicApi] = {}
        self._member_limiter = _RateLimiter(MEMBER_POST_LIMIT)
        self._public_limiter = _RateLimiter(PUBLIC_LIMIT)
        # (user_id, grund) -> Zeitpunkt des letzten protokollierten abgelehnten Zugriffs
        self._deny_logged: dict[tuple, float] = {}
        self._bg_tasks: set = set()
        # UI-Baukasten für Cog-Seiten: ``request.app["webcore"].ui`` (siehe ui.py)
        self.ui = _ui
        self.app: web.Application | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None

        self.recent: collections.deque = collections.deque(maxlen=12)
        self._loaded_at = datetime.now(timezone.utc)
        self._process = None
        # Fehlerprotokoll (logging.Handler am Logger ``red``) und bekannte Secrets zum Maskieren.
        self._errorlog = None
        self._known_secrets: set = set()
        # Sichern & Wiederherstellen: offene Vorschauen und „Rückgängig“-Stände (nur im RAM).
        self._import_pending: dict = {}
        self._import_undo: dict = {}
        self._backup_lock = asyncio.Lock()
        # Kurzlebiger Cache für fetch_member-Fallback (admin-Modus ohne Member-Cache):
        # (guild_id, user_id) -> (ablauf_ts, member_or_none). Verhindert fetch-Stürme.
        self._member_cache: dict[tuple[int, int], tuple[float, object]] = {}

    # ----------------------------------------------------------------- #
    #  Öffentliche API für andere Cogs
    # ----------------------------------------------------------------- #
    def register_page(self, owner, slug: str, name: str, handler, icon: str = "bi-grid", operate_forms=()):
        """Fügt eine Dashboard-Seite hinzu.

        owner         : der aufrufende Cog (für sauberes Entfernen beim Entladen)
        slug          : URL-Teil, erreichbar unter /cogs/<slug>
        name          : Anzeigename in der Navigation
        handler       : async def handler(request) -> {"title": str, "content": html_str}
        icon          : Bootstrap-Icon-Klasse, z. B. "bi-stars"
        operate_forms : Tagesgeschäft für die Stufe „Bedienen“ – Werte des POST-Feldes ``form`` (falls
                        vorhanden, sonst ``action``), z. B. ``{"event_action", "repost"}``, oder ein
                        Callable ``(data: MultiDict) -> bool``. Leer = die Seite hat kein Tagesgeschäft,
                        „Bedienen“ wirkt dort wie „Ansehen“. Nie Einstellungen/Rollen/Rechte!
        """
        self.pages[slug] = DashboardPage(owner, slug, name, handler, icon, operate_forms=operate_forms)
        log.info("Dashboard-Seite registriert: %s (von %s)", slug, owner.qualified_name)

    def register_member_page(self, owner, slug: str, name: str, handler, icon: str = "bi-grid",
                             description: str = "", visible=None):
        """Fügt eine Seite für normale Server-Mitglieder hinzu („Mein Bereich“).

        owner       : der aufrufende Cog (für ``unregister_owner``)
        slug        : URL-Teil, erreichbar unter ``/me/<slug>`` (GET + POST)
        name        : Anzeigename (Navigation + Kachel auf ``/me``)
        handler     : ``async def handler(request) -> {"title": str, "content": html}`` oder
                      ``{"redirect": url}`` (oder eine fertige ``web.Response``)
        icon        : Bootstrap-Icon-Klasse
        description : ein Satz für die Kachel auf der Übersicht ``/me``
        visible     : optional ``async def visible(guild) -> bool`` – blendet Kachel und Navigation
                      für Server aus, auf denen der Cog die Seite abgeschaltet hat

        Vor dem Aufruf setzt WebCore ``request["wc_member_guild"]`` (discord.Guild),
        ``request["wc_member"]`` (discord.Member des angemeldeten Users auf diesem Server) und
        ``request["webcore_csrf"]``; POSTs sind bereits CSRF-geprüft und rate-limitiert.
        """
        if not _PUBLIC_NAME_RE.match(str(slug)):
            raise ValueError("Ungültiger slug (erlaubt: A-Z a-z 0-9 _ . -).")
        self.member_pages[slug] = DashboardPage(owner, slug, name, handler, icon, description, visible)
        log.info("Mitglieder-Seite registriert: /me/%s (von %s)", slug, getattr(owner, "qualified_name", owner))

    async def _visible_member_pages(self, guild) -> list:
        """Mitgliederseiten, die auf ``guild`` angezeigt werden sollen (sortiert)."""
        out = []
        for p in sorted(self.member_pages.values(), key=lambda x: x.name.lower()):
            if guild is not None and p.visible is not None:
                try:
                    if not await p.visible(guild):
                        continue
                except Exception:  # noqa: BLE001 – im Zweifel anzeigen, die Seite prüft selbst
                    log.exception("visible()-Prüfung der Mitgliederseite %s fehlgeschlagen", p.slug)
            out.append(p)
        return out

    async def _member_nav_for(self, request) -> list:
        """Navigation „Mein Bereich“ für den gewählten Server (Kontext-Prozessoren laufen VOR dem
        Handler und kennen den Server noch nicht – daher hier nachberechnet)."""
        return [
            {"slug": p.slug, "name": p.name, "icon": p.icon, "description": p.description}
            for p in await self._visible_member_pages(request.get("wc_member_guild"))
        ]

    def register_public_api(self, owner, slug: str, handler):
        """Öffentliche Lese-API ``GET /api/public/<slug>`` und ``GET /api/public/<slug>/<tail>``.

        Ohne Login und ohne Sitzung (für Launcher/Websites). ``handler(request)`` liest den Rest
        des Pfads über ``request.match_info.get("tail", "")`` und gibt eine ``web.Response``
        (z. B. ``web.json_response(...)``) zurück. WebCore setzt CORS ``*`` (GET/OPTIONS),
        ``Cache-Control: public, max-age=60`` (falls der Handler nichts anderes setzt), ein
        Rate-Limit von 60 Anfragen pro IP und Minute (429) und fängt Fehler ab (500-JSON).
        Nur öffentliche Daten ausliefern – es gibt keinen angemeldeten Nutzer.
        """
        if not _PUBLIC_NAME_RE.match(str(slug)):
            raise ValueError("Ungültiger slug für die öffentliche API (erlaubt: A-Z a-z 0-9 _ . -).")
        self.public_apis[slug] = PublicApi(owner, slug, handler)
        log.info("Öffentliche API registriert: /api/public/%s (von %s)", slug,
                 getattr(owner, "qualified_name", owner))

    def unregister_owner(self, owner):
        """Entfernt alle Seiten, Mitglieder-Seiten und öffentlichen APIs eines Cogs (im cog_unload)."""
        for slug in [s for s, p in self.pages.items() if p.owner is owner]:
            del self.pages[slug]
        for slug in [s for s, p in self.member_pages.items() if p.owner is owner]:
            del self.member_pages[slug]
        for slug in [n for n, r in self.public_apis.items() if r.owner is owner]:
            del self.public_apis[slug]

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Anonymisiert den Nutzer im Audit-Log und entfernt ihn aus der Allowlist."""
        async with self.config.audit() as entries:
            for e in entries:
                if str(e.get("user_id")) == str(user_id):
                    e["user_id"] = 0
                    e["user_name"] = "—"
        async with self.config.allowed_users() as users:
            if user_id in users:
                users.remove(user_id)

    # ----------------------------------------------------------------- #
    #  Lifecycle
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        if psutil is not None:
            try:
                self._process = psutil.Process()
                self._process.cpu_percent(None)  # CPU-Messung initialisieren
            except Exception:
                self._process = None
        self._install_error_log()
        try:
            await self._refresh_known_secrets()
        except Exception:  # noqa: BLE001
            log.debug("Secrets für das Fehlerprotokoll nicht ermittelbar", exc_info=True)
        try:
            await self._start_webserver()
        except BaseException:
            # Red ruft cog_unload nach einem fehlgeschlagenen cog_load nicht auf -> Handler selbst entfernen.
            self._remove_error_log()
            raise

    def _install_error_log(self):
        """Fehlerprotokoll-Handler am Logger ``red`` anbringen (ersetzt einen vorhandenen, nie doppelt)."""
        self._errorlog = errorlog.install(secrets_provider=lambda: self._known_secrets)
        return self._errorlog

    def _remove_error_log(self):
        errorlog.remove(self._errorlog)
        self._errorlog = None

    async def _refresh_known_secrets(self) -> None:
        """Werte, die im Fehlerprotokoll nie im Klartext erscheinen dürfen (Bot-Token, OAuth-Secret,
        API-Keys aus ``[p]set api`` und Secret-Schlüssel der Cog-Konfigurationen)."""
        found = set()

        def walk(value, secret_name=False):
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(v, secret_name or bk.is_secret_key(k))
            elif isinstance(value, list):
                for v in value:
                    walk(v, secret_name)
            elif secret_name and isinstance(value, (str, int)) and len(str(value)) >= 6:
                found.add(str(value))

        data = await self.config.all()
        walk({"client_secret": data.get("client_secret"), "secret_key": data.get("secret_key")})
        token = getattr(getattr(self.bot, "http", None), "token", None)
        if token:
            found.add(str(token))
        getter = getattr(self.bot, "get_shared_api_tokens", None)
        if getter is not None:
            try:
                tokens = await getter()
                for service in (tokens or {}).values():
                    if isinstance(service, dict):
                        found.update(str(v) for v in service.values() if v and len(str(v)) >= 6)
            except Exception:  # noqa: BLE001
                pass
        for cog in bk.backup_cogs(self).values():
            try:
                walk(await cog.config.all())
            except Exception:  # noqa: BLE001
                pass
        self._known_secrets = found

    async def cog_unload(self):
        self._remove_error_log()
        self._import_pending.clear()
        self._import_undo.clear()
        for task in list(self._bg_tasks):
            task.cancel()
        if self.site is not None:
            await self.site.stop()
        if self.runner is not None:
            await self.runner.cleanup()
        log.info("WebCore-Dashboard gestoppt.")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        """Hält die zuletzt genutzten Befehle für die Übersicht fest (nur im Speicher)."""
        self.recent.appendleft(
            {
                "command": ctx.command.qualified_name if ctx.command else "?",
                "where": (
                    f"{ctx.guild.name} · {ctx.author.display_name}"
                    if ctx.guild
                    else f"DM · {ctx.author.display_name}"
                ),
                "guild_id": ctx.guild.id if ctx.guild else None,
                "ts": datetime.now(timezone.utc),
            }
        )

    async def handle_health(self, request):
        """Einfacher Gesundheitscheck (z. B. für Docker/Uptime-Monitor), ohne Login und ohne Daten."""
        return web.Response(text="ok", headers={"Cache-Control": "no-store"})

    async def _start_webserver(self):
        data = await self.config.all()

        secret_key = data["secret_key"]
        if not secret_key:
            secret_key = secrets.token_hex(32)
            await self.config.secret_key.set(secret_key)
        fernet_key = hashlib.sha256(secret_key.encode()).digest()  # 32 Bytes

        app = web.Application(middlewares=[_security_headers])
        storage_kwargs = {"cookie_name": "WEBCORE_SESSION", "max_age": SESSION_MAX_AGE, "httponly": True}
        # Öffentlich per HTTPS erreichbar (redirect_uri https://…) → Cookie nur noch über HTTPS senden.
        if str(data.get("redirect_uri") or "").lower().startswith("https://"):
            storage_kwargs["secure"] = True
        # samesite erst ab neueren aiohttp_session-Versionen – nur setzen, wenn unterstützt.
        if "samesite" in inspect.signature(EncryptedCookieStorage.__init__).parameters:
            storage_kwargs["samesite"] = "Lax"
        session_setup(app, EncryptedCookieStorage(fernet_key, **storage_kwargs))
        aiohttp_jinja2.setup(
            app,
            loader=jinja2.FileSystemLoader(str(Path(__file__).parent / "templates")),
            # Autoescape an: {{ ... }} wird HTML-escaped (schützt vor XSS über Server-/
            # Nutzernamen in der Übersicht). Cog-HTML kommt bewusst über {{ content | safe }}.
            autoescape=jinja2.select_autoescape(["html", "xml"]),
            context_processors=[self._global_context],
        )
        app["webcore"] = self
        app.add_routes(
            [
                web.get("/", self.handle_index),
                web.get("/login", self.handle_login),
                web.get("/callback", self.handle_callback),
                web.get("/logout", self.handle_logout),
                web.get("/cogs/{slug}", self.handle_cog_page),
                web.post("/cogs/{slug}", self.handle_cog_page),
                web.get("/access", self.handle_access),
                web.post("/access", self.handle_access),
                web.get("/audit", self.handle_audit),
                web.post("/audit", self.handle_audit),
                web.get("/status", self.handle_status),
                web.get("/errors", self.handle_errors),
                web.post("/errors", self.handle_errors),
                web.get("/backup", self.handle_backup),
                web.post("/backup", self.handle_backup),
                web.get("/api/overview", self.handle_overview_api),
                # Mitglieder-Bereich und öffentliche API: je EINE feste Route, die zu den
                # registrierten Handlern verteilt (der aiohttp-Router ist nach dem Start
                # eingefroren). web.get registriert HEAD automatisch mit.
                web.get("/me", self.handle_member_home),
                web.get("/me/{slug}", self.handle_member_page),
                web.post("/me/{slug}", self.handle_member_page),
                web.get("/api/public/{slug}", self.handle_public),
                web.get("/api/public/{slug}/{tail:.*}", self.handle_public),
                web.route("OPTIONS", "/api/public/{slug}", self.handle_public),
                web.route("OPTIONS", "/api/public/{slug}/{tail:.*}", self.handle_public),
                web.get("/healthz", self.handle_health),
                web.static("/static", str(Path(__file__).parent / "static")),
            ]
        )

        self.app = app
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        host = data["host"]
        self.site = web.TCPSite(self.runner, host, data["port"])
        try:
            await self.site.start()
        except OSError as exc:
            # z. B. socket.gaierror, wenn der Host nicht auflösbar/bindbar ist.
            if host != "0.0.0.0":
                log.warning("Konnte nicht an Host %r binden (%s) – Fallback auf 0.0.0.0.", host, exc)
                self.site = web.TCPSite(self.runner, "0.0.0.0", data["port"])
                await self.site.start()
                host = "0.0.0.0"
            else:
                raise
        log.info("WebCore-Dashboard läuft auf %s:%s", host, data["port"])

        # Bereits geladene Cogs registrieren lassen.
        self.bot.dispatch("webcore_ready", self)

    # ----------------------------------------------------------------- #
    #  Auth-Helfer
    # ----------------------------------------------------------------- #
    async def _get_user(self, request):
        session = await get_session(request)
        uid = session.get("user_id")
        if uid is None:
            return None
        uid = int(uid)
        return {
            "id": uid,
            "name": session.get("user_name", "Unbekannt"),
            "avatar": acl.avatar_url(uid, session.get("user_avatar")),
        }

    async def _resolve_member(self, guild, uid):
        """Mitglied auflösen: erst Cache, sonst ein bewusster REST-Fallback.

        Rollen-Rechte und der Zugriffsmodus ``admin`` hängen an ``get_member``.
        Ist das Members-Intent aus oder das Mitglied nicht gecacht, liefert
        ``get_member`` ``None`` und würde legitime Nutzer aussperren. Der
        ``fetch_member``-Fallback fängt das ab; das Ergebnis wird 5 Minuten
        gecacht, damit wiederholte Requests keine API-Stürme auslösen.
        """
        member = guild.get_member(uid)
        if member is not None:
            return member
        key = (guild.id, uid)
        now = datetime.now(timezone.utc).timestamp()
        cached = self._member_cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            member = await guild.fetch_member(uid)
        except (discord.HTTPException, discord.Forbidden):
            member = None
        if len(self._member_cache) > 5000:
            # Mit dem Mitglieder-Bereich melden sich viele Nutzer an – abgelaufene Einträge aufräumen.
            for k in [k for k, v in self._member_cache.items() if v[0] <= now]:
                del self._member_cache[k]
        self._member_cache[key] = (now + 300, member)
        return member

    async def _portal_scope(self, user, request=None) -> list:
        """Server, auf denen ``user`` „Mein Bereich“ nutzen darf (pro Request gecacht).

        * Normale Nutzer: Server mit aktivem Mitglieder-Bereich, auf denen sie Mitglied sind.
        * Team (Rollen-Rechte/Server-Admin): zusätzlich die Server, auf denen sie Team-Zugriff
          haben – auch bei ausgeschaltetem Mitglieder-Bereich (Vorschau zum Testen).
        * Owner/Allowlist: alle Server, auf denen sie Mitglied sind.
        Mitgliedschaft wird live geprüft (Member-Cache, sonst fetch-Fallback). Ohne
        ``discord.Member`` gibt es keinen Zugang (der Handler bekommt immer ein Member-Objekt).
        """
        if user is None:
            return []
        if request is not None and "_wc_portal" in request:
            return request["_wc_portal"]
        portal = await self.config.member_portal() or {}
        amap = await self._access_map(user, request)
        full = amap is None
        result, members, preview = [], {}, set()
        for g in self.bot.guilds:
            enabled = bool(portal.get(str(g.id)))
            team_here = full or g.id in (amap or {})
            if not enabled and not team_here:
                continue
            member = await self._resolve_member(g, user["id"])
            if member is None:
                continue
            result.append(g)
            members[g.id] = member
            if not enabled:
                preview.add(g.id)
        result.sort(key=lambda g: g.name.lower())
        if request is not None:
            request["_wc_portal"] = result
            request["_wc_portal_members"] = members
            request["_wc_portal_preview"] = preview
        return result

    async def portal_guilds(self, request) -> list:
        """Öffentlich für Cogs: Server, die der angemeldete User in „Mein Bereich“ wählen darf.

        Für Mitglieder-Seiten statt ``visible_guilds`` verwenden (Liste von ``discord.Guild``).
        """
        return list(await self._portal_scope(await self._get_user(request), request))

    async def member_context(self, request):
        """Öffentlich für Cogs: ``(guild, member)`` des angemeldeten Users im Mitglieder-Bereich.

        Auf ``/me/<slug>`` die von WebCore gesetzte Auswahl, sonst der Server aus ``?guild=``
        (nur wenn erlaubt; bei genau einem erlaubten Server dieser). ``None``, wenn kein Zugriff.
        """
        guild, member = request.get("wc_member_guild"), request.get("wc_member")
        if guild is not None and member is not None:
            return guild, member
        scope = await self._portal_scope(await self._get_user(request), request)
        if not scope:
            return None
        raw = request.query.get("guild", "")
        guild = next((g for g in scope if raw.isdigit() and g.id == int(raw)), None)
        if guild is None and not raw and len(scope) == 1:
            guild = scope[0]
        if guild is None:
            return None
        member = request.get("_wc_portal_members", {}).get(guild.id)
        return (guild, member) if member is not None else None

    async def current_user(self, request):
        """Öffentlich für Cogs: ``{"id", "name", "avatar"}`` des eingeloggten Users oder ``None``."""
        user = await self._get_user(request)
        return dict(user) if user else None

    async def _has_full_scope(self, user) -> bool:
        """Volle Sicht (alle Server, alle Seiten, Bot-Infrastruktur): Owner und Allowlist."""
        if user is None:
            return False
        if user["id"] in self.bot.owner_ids:
            return True
        return user["id"] in await self.config.allowed_users()

    async def _access_map(self, user, request=None):
        """Rechte eines Nutzers.

        ``None``  = volle Sicht (Owner/Allowlist: alle Server, überall Bearbeiten).
        ``dict``  = {guild_id: {slug: Stufe}} – nur Server/Seiten mit Zugriff.
        Pro Request gecacht (Cogs rufen visible_guilds mehrfach auf).
        """
        if user is None:
            return {}
        if request is not None and "_wc_access" in request:
            return request["_wc_access"]
        if await self._has_full_scope(user):
            result = None
        else:
            data = await self.config.all()
            role_perms = data.get("role_perms") or {}
            configured = acl.configured_guild_ids(role_perms)
            admin_mode = data.get("access_mode") == "admin"
            slugs = list(self.pages)
            result = {}
            for g in self.bot.guilds:
                if not admin_mode and g.id not in configured:
                    continue
                member = await self._resolve_member(g, user["id"])
                if member is None:
                    continue
                if admin_mode and member.guild_permissions.administrator:
                    # Zugriffsmodus "admin": Server-Admins bearbeiten ihren Server komplett.
                    result[g.id] = {slug: acl.EDIT for slug in slugs}
                    continue
                if g.id in configured:
                    levels = acl.levels_from_roles(
                        [r.id for r in member.roles if not r.is_default()],
                        acl.guild_role_perms(role_perms, g.id),
                        slugs,
                    )
                    if levels:
                        result[g.id] = levels
        if request is not None:
            request["_wc_access"] = result
        return result

    @staticmethod
    def _invalidate_access_cache(request=None) -> None:
        """Rechte-Cache verwerfen, nachdem Rollen-Rechte/Mitglieder-Bereich geändert wurden.

        ``_access_map`` und ``_portal_scope`` cachen nur pro Request (``request["_wc_access"]`` bzw.
        ``_wc_portal*``) – jeder neue Request rechnet frisch aus der Config. Innerhalb des laufenden
        Requests werden die Einträge hier verworfen, damit auch er schon die neuen Rechte sieht.
        """
        if request is None:
            return
        for key in ("_wc_access", "_wc_portal", "_wc_portal_members", "_wc_portal_preview"):
            request.pop(key, None)

    async def _is_authorized(self, user, request=None) -> bool:
        """Darf dieser User das Dashboard überhaupt betreten?"""
        if user is None:
            return False
        amap = await self._access_map(user, request)
        return amap is None or bool(amap)

    async def _admin_guilds(self, user, request=None) -> list:
        """Server mit irgendeinem Zugriff (für die eingeschränkte Übersicht)."""
        amap = await self._access_map(user, request)
        if amap is None:
            return list(self.bot.guilds)
        return [g for g in self.bot.guilds if g.id in amap]

    def _role_label(self, user, full: bool, amap) -> tuple[str, str]:
        if user is None:
            return "", ""
        if user["id"] in self.bot.owner_ids:
            return "Owner", "owner"
        if full:
            return "Voller Zugriff", "owner"
        if amap and all(all(v == acl.EDIT for v in lv.values()) and len(lv) >= len(self.pages)
                        for lv in amap.values()):
            return "Server-Admin", "admin"
        return "Team", "team"

    async def visible_guilds(self, request, *, min_level: int | None = None) -> list:
        """Öffentlich für Cogs: die Server, die der eingeloggte User auf DIESER Seite sehen darf.

        * Owner/Allowlist -> alle Server.
        * Sonst nur Server, in denen der User für die aktuelle Seite (``/cogs/<slug>``)
          mindestens ``Ansehen`` hat – bei POST-Anfragen mindestens ``Bearbeiten``, bzw.
          ``Bedienen``, wenn WebCore den POST als Tagesgeschäft eingestuft hat
          (``request["wc_operate"]``, siehe ``register_page(operate_forms=…)``).
          Dadurch lehnen alle Cogs, die ihre Ziel-Guild gegen diese Liste prüfen,
          Speichern ohne passendes Recht automatisch ab.
        """
        user = await self._get_user(request)
        amap = await self._access_map(user, request)
        if amap is None:
            return list(self.bot.guilds) if user is not None else []
        if not amap or request.get("wc_area") == "member":
            # Rollen-Rechte gelten nur für /cogs/* – Mitglieder-Seiten nutzen portal_guilds.
            return []
        slug = request.match_info.get("slug") if request.match_info else None
        if min_level is None:
            if request.method == "POST":
                min_level = acl.OPERATE if request.get("wc_operate") else acl.EDIT
            else:
                min_level = acl.VIEW
        out = []
        for g in self.bot.guilds:
            levels = amap.get(g.id)
            if not levels:
                continue
            level = levels.get(slug, acl.NONE) if slug else max(levels.values())
            if level >= min_level:
                out.append(g)
        return out

    async def page_level(self, request, guild) -> int:
        """Öffentlich für Cogs: Stufe des Users für die aktuelle Seite in ``guild``.

        ``acl.NONE`` (0), ``acl.VIEW`` (1), ``acl.OPERATE`` (2), ``acl.EDIT`` (3) – im Cog nie mit
        festen Zahlen vergleichen, sondern ``can_operate``/``can_edit`` benutzen.
        """
        user = await self._get_user(request)
        amap = await self._access_map(user, request)
        if amap is None:
            return acl.EDIT if user is not None else acl.NONE
        if request.get("wc_area") == "member":
            return acl.NONE
        slug = request.match_info.get("slug") if request.match_info else None
        return (amap.get(guild.id) or {}).get(slug, acl.NONE)

    async def can_operate(self, request, guild) -> bool:
        """Öffentlich für Cogs: darf der User auf der aktuellen Seite in ``guild`` das Tagesgeschäft
        ausführen (Stufe ≥ Bedienen)? Owner/Allowlist/Server-Admin (Modus ``admin``) immer."""
        return guild is not None and await self.page_level(request, guild) >= acl.OPERATE

    async def can_edit(self, request, guild) -> bool:
        """Öffentlich für Cogs: darf der User auf der aktuellen Seite in ``guild`` Einstellungen
        ändern (Stufe Bearbeiten)?"""
        return guild is not None and await self.page_level(request, guild) >= acl.EDIT

    async def can_grant_role(self, request, guild, role) -> bool:
        """Öffentlich für Cogs: darf der eingeloggte User ``role`` automatisch vergeben lassen?

        Owner/Allowlist und Discord-Administratoren immer. Team-Mitglieder mit
        Rollen-Rechten nur Rollen, die UNTER ihrer höchsten Rolle liegen und keine
        Moderations-/Verwaltungsrechte haben (Schutz vor Selbst-Hochstufung).
        """
        if role is None:
            return False
        user = await self._get_user(request)
        amap = await self._access_map(user, request)
        if amap is None:
            return user is not None
        member = await self._resolve_member(guild, user["id"])
        if member is None:
            return False
        if member.guild_permissions.administrator:
            return True
        top = max((r.position for r in member.roles), default=0)
        if role.position >= top:
            return False
        perms = role.permissions
        return not any(getattr(perms, p, False) for p in DANGEROUS_PERMS)

    async def has_full_scope(self, request) -> bool:
        """Öffentlich für Cogs: ist der eingeloggte User Owner/Allowlist (volle Sicht)?

        Für botweite Einstellungen (z. B. Application Emojis), die ein Server-Admin
        oder ein Team-Mitglied mit Rollen-Rechten nicht ändern darf.
        """
        return await self._has_full_scope(await self._get_user(request))

    def _login_response(self, request, *, state=None, error=None, status=200):
        return aiohttp_jinja2.render_template(
            "login.html", request,
            {"title": "Anmeldung", "active_page": None, "state": state, "error": error},
            status=status,
        )

    async def _global_context(self, request):
        """Wird bei jedem Template-Render eingefügt (Navigation, User, Server-Wechsler …)."""
        if request.path.startswith(("/api/public/", "/healthz", "/static/")):
            return {}  # öffentliche Endpunkte: keine Sitzung lesen, keine Rechte berechnen
        user = await self._get_user(request)
        amap = await self._access_map(user, request) if user else {}
        full = amap is None
        authorized = user is not None and (full or bool(amap))
        nav = []
        for p in sorted(self.pages.values(), key=lambda x: x.name.lower()):
            if full:
                nav.append({"slug": p.slug, "name": p.name, "icon": p.icon, "readonly": False, "operate": False})
                continue
            levels = [lv.get(p.slug, acl.NONE) for lv in (amap or {}).values()]
            best = max(levels) if levels else acl.NONE
            if best >= acl.VIEW:
                # „Bedienen“ auf einer Seite ohne Tagesgeschäft wirkt wie „Ansehen“.
                operate = best == acl.OPERATE and p.supports_operate
                nav.append({"slug": p.slug, "name": p.name, "icon": p.icon,
                            "readonly": best < acl.EDIT and not operate, "operate": operate})
        label, cls = self._role_label(user, full, amap)
        pguilds = await self._portal_scope(user, request) if user else []
        member_only = user is not None and not authorized and bool(pguilds)
        if member_only:
            label, cls = "Mitglied", "member"
        # Team/Owner: Abschnitt „Mein Bereich“ nur, wenn Seiten registriert sind und der
        # Mitglieder-Bereich auf mindestens einem ihrer Server wirklich aktiv ist.
        preview = request.get("_wc_portal_preview") or set()
        portal_live = any(g.id not in preview for g in pguilds)
        show_member_nav = member_only or (bool(self.member_pages) and portal_live)
        member_nav = [
            {"slug": p.slug, "name": p.name, "icon": p.icon, "description": p.description}
            for p in await self._visible_member_pages(request.get("wc_member_guild"))
        ] if show_member_nav else []
        return {
            "nav_pages": nav,
            "member_nav": member_nav,
            "show_member_nav": show_member_nav,
            "member_only": member_only,
            "home_href": "/me" if member_only else "/",
            "home_label": "Zu „Mein Bereich“" if member_only else "Zurück zur Übersicht",
            "current_user": user,
            "authorized": authorized,
            "is_full": bool(user) and full,
            "role_label": label,
            "role_class": cls,
            "bot_name": self.bot.user.name if self.bot.user else "Red",
            "bot_avatar": str(self.bot.user.display_avatar.url) if self.bot.user else None,
            "red_version": RED_VERSION,
            "asset_version": ASSET_VERSION,
            # Werden pro Seite gesetzt (Context-Prozessoren laufen VOR dem Handler,
            # daher überschreibt _page_ctx() diese Werte beim Rendern).
            "switcher": None,
            "readonly": False,
            "operate": False,
            "operate_forms": "",
            "switcher_guild_name": "",
            "toast_err": None,
            "member_preview": False,
        }

    @staticmethod
    def _page_ctx(request, **extra) -> dict:
        ctx = {
            "switcher": request.get("wc_switcher"),
            "readonly": bool(request.get("webcore_readonly")),
            "operate": bool(request.get("webcore_operate")),
            "operate_forms": ",".join(request.get("wc_operate_forms") or ()),
            "switcher_guild_name": request.get("wc_guild_name", ""),
            "member_preview": bool(request.get("wc_member_preview")),
        }
        ctx.update(extra)
        return ctx

    async def _audit(self, request, user, *, page, guild_id, action, result, ok, area=None):
        """Audit-Eintrag speichern und (falls eingerichtet) als Embed in den Log-Kanal posten.

        ``request`` darf ``None`` sein (Befehle). ``user``: {"id", "name"[, "avatar"]}.
        """
        guild = self.bot.get_guild(guild_id) if guild_id else None
        entry = {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "user_id": user["id"] if user else 0,
            "user_name": user["name"] if user else "?",
            "page": page,
            "guild_id": guild_id,
            "guild_name": guild.name if guild else None,
            "action": (str(action)[:60] if action else None),
            "result": (str(result)[:160] if result else None),
            "ok": bool(ok),
        }
        if area:
            entry["area"] = area
        try:
            async with self.config.audit() as entries:
                acl.append_audit(entries, entry, member_cap=acl.MEMBER_AUDIT_MAX)
        except Exception:  # noqa: BLE001 – Protokoll darf nie die Aktion scheitern lassen
            log.exception("Audit-Eintrag konnte nicht gespeichert werden")
        self._schedule_audit_post(entry, (user or {}).get("avatar"))

    async def _audit_denied(self, request, user, *, page, guild_id, action, result, area="member"):
        """Abgelehnten Zugriff protokollieren – pro Nutzer und Grund höchstens einmal pro Minute."""
        if user is None:
            return
        key = (user["id"], page, result)
        now = time.monotonic()
        if now - self._deny_logged.get(key, -AUDIT_DENY_THROTTLE) < AUDIT_DENY_THROTTLE:
            return
        if len(self._deny_logged) > 5000:
            self._deny_logged = {k: t for k, t in self._deny_logged.items() if now - t < AUDIT_DENY_THROTTLE}
        self._deny_logged[key] = now
        await self._audit(request, user, page=page, guild_id=guild_id, action=action,
                          result=result, ok=False, area=area)

    # ----------------------------------------------------------------- #
    #  Audit-Log nach Discord
    # ----------------------------------------------------------------- #
    def _page_label(self, slug) -> str:
        if slug in OWNER_PAGE_LABELS:
            return OWNER_PAGE_LABELS[slug]
        if slug and str(slug).startswith("me:"):
            p = self.member_pages.get(slug[3:])
            return f"Mein Bereich: {p.name if p else slug[3:]}"
        p = self.pages.get(slug)
        return p.name if p else (slug or "—")

    def _schedule_audit_post(self, entry: dict, avatar) -> None:
        """Fire-and-forget: Audit-Eintrag in den Log-Kanal posten (Fehler werden nur geloggt)."""
        if not entry.get("guild_id"):
            return
        if len(self._bg_tasks) >= AUDIT_POST_MAX_PENDING:
            log.warning("Audit-Log nach Discord: zu viele ausstehende Nachrichten – Eintrag verworfen.")
            return
        try:
            task = asyncio.get_running_loop().create_task(self._post_audit(entry, avatar))
        except RuntimeError:
            return
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _audit_embed(self, entry: dict, avatar) -> discord.Embed:
        ok = entry.get("ok", True)
        esc = discord.utils.escape_markdown
        ts = int(entry.get("ts") or 0)
        uid = int(entry.get("user_id") or 0)
        uname = esc(str(entry.get("user_name") or "?"))
        result = entry.get("result") or ("OK" if ok else "abgelehnt")
        embed = discord.Embed(
            title=("✅ Dashboard-Aktion" if ok else "⛔ Abgelehnter Zugriff"),
            color=0x3DDC97 if ok else 0xFF6B6B,
            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        )
        embed.add_field(name="Zeit", value=f"<t:{ts}:f>", inline=True)
        embed.add_field(name="Nutzer", value=_trunc(f"<@{uid}> ({uname})" if uid else uname, 1024), inline=True)
        embed.add_field(name="Seite", value=_trunc(esc(self._page_label(entry.get("page"))), 1024), inline=True)
        action = str(entry.get("action") or "—").replace("`", "")
        embed.add_field(name="Aktion", value=_trunc(f"`{action}`" if entry.get("action") else "—", 1024), inline=True)
        embed.add_field(name="Ergebnis", value=_trunc(("OK" if ok else "abgelehnt") + f" · {esc(str(result))}", 1024),
                        inline=False)
        if avatar:
            embed.set_thumbnail(url=avatar)
        area = "Mein Bereich" if entry.get("area") == "member" else "Dashboard"
        embed.set_footer(text=f"WebCore-Audit · {area}")
        return embed

    async def _post_audit(self, entry: dict, avatar) -> None:
        try:
            gid = entry.get("guild_id")
            cid = (await self.config.audit_channels() or {}).get(str(gid))
            guild = self.bot.get_guild(int(gid)) if gid else None
            if not cid or guild is None:
                return
            channel = guild.get_channel(int(cid))
            if channel is None or not hasattr(channel, "send"):
                return
            await channel.send(embed=self._audit_embed(entry, avatar),
                               allowed_mentions=discord.AllowedMentions.none())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 – das Dashboard darf daran nie scheitern
            log.warning("Audit-Eintrag konnte nicht nach Discord gepostet werden: %r", exc)

    @staticmethod
    def _redirect_message(location: str | None) -> tuple[str | None, bool]:
        """Meldung (ok/err) aus einer PRG-Weiterleitung lesen."""
        if not location:
            return None, True
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(str(location)).query)
        if "err" in q:
            msg = q["err"][0]
            return ("Eingabe ungültig" if msg == "1" else msg), False
        if "ok" in q:
            msg = q["ok"][0]
            if msg == "1":
                return "Gespeichert", True
            bad = any(w in msg.lower() for w in ("nicht gefunden", "fehlgeschlagen", "ungültig", "fehler"))
            return msg, not bad
        return None, True

    # ----------------------------------------------------------------- #
    #  Routen
    # ----------------------------------------------------------------- #
    async def _post_guild_id(self, request):
        """Ziel-Server eines POSTs (Feld ``guild``/``guild_id`` oder ``?guild=``) – nur für Protokolle."""
        try:
            form = await request.post()
        except Exception:  # noqa: BLE001
            form = {}
        raw = str(form.get("guild") or form.get("guild_id") or request.query.get("guild") or "")
        gid = int(raw) if raw.isdigit() else None
        return gid if gid is not None and self.bot.get_guild(gid) is not None else None

    async def _deny(self, request, user):
        """Nicht angemeldet -> Login; angemeldet ohne Rechte -> "Kein Zugriff".

        Reine Mitglieder (nur „Mein Bereich“) bekommen eine 403-Seite mit Link zu /me.
        """
        if user is None:
            return self._login_response(request)
        if request.method == "POST":
            gid = await self._post_guild_id(request)
            await self._audit_denied(request, user, page=request.match_info.get("slug") or request.path.strip("/"),
                                     guild_id=gid, action="POST", result="Kein Zugriff (Team-Bereich)", area=None)
        if await self._portal_scope(user, request):
            return self._error_page(
                request, "Kein Zugriff",
                "Dieser Bereich ist dem Team vorbehalten. Deine Seiten findest du unter „Mein Bereich“.",
                status=403, icon="bi-shield-lock",
            )
        return self._login_response(request, state="noaccess", status=403)

    @aiohttp_jinja2.template("index.html")
    async def handle_index(self, request):
        user = await self._get_user(request)
        if not await self._is_authorized(user, request):
            if user is not None and await self._portal_scope(user, request):
                # Mitglied ohne Team-Rechte -> direkt in „Mein Bereich“.
                raise web.HTTPFound("/me")
            return await self._deny(request, user)
        ctx = await self._collect_overview(user, request)
        ctx["title"] = "Übersicht"
        ctx["active_page"] = "home"
        return ctx

    async def handle_overview_api(self, request):
        """Live-Kennzahlen als JSON (für die automatische Aktualisierung)."""
        user = await self._get_user(request)
        if not await self._is_authorized(user, request):
            return web.json_response({"error": "unauthorized"}, status=403)
        return web.json_response(await self._collect_overview(user, request))

    # ----------------------------------------------------------------- #
    #  Übersicht: Datensammlung
    # ----------------------------------------------------------------- #
    @staticmethod
    def _aware(dt):
        if dt is None:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _humanize(delta) -> str:
        secs = int(delta.total_seconds())
        if secs < 60:
            return "<1m"
        days, secs = divmod(secs, 86400)
        hours, secs = divmod(secs, 3600)
        mins, _ = divmod(secs, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if mins or not parts:
            parts.append(f"{mins}m")
        return " ".join(parts)

    def _ago(self, ts, now=None) -> str:
        now = now or datetime.now(timezone.utc)
        secs = int((now - self._aware(ts)).total_seconds())
        if secs < 10:
            return "gerade eben"
        if secs < 60:
            return f"vor {secs}s"
        if secs < 3600:
            return f"vor {secs // 60}m"
        return f"vor {secs // 3600}h {(secs % 3600) // 60}m"

    async def _collect_overview(self, user, request=None) -> dict:
        bot = self.bot
        full = await self._has_full_scope(user)
        guilds = list(bot.guilds) if full else await self._admin_guilds(user, request)
        member_total = sum((g.member_count or 0) for g in guilds)
        channel_count = sum(len(g.channels) for g in guilds)
        emoji_count = sum(len(g.emojis) for g in guilds)
        lat = bot.latency
        latency = round(lat * 1000) if lat == lat else 0  # NaN != NaN

        started = getattr(bot, "uptime", None) or self._loaded_at
        uptime = self._humanize(datetime.now(timezone.utc) - self._aware(started))

        largest = max((g.member_count or 0) for g in guilds) if guilds else 0
        top = sorted(guilds, key=lambda g: (g.member_count or 0), reverse=True)[:5]
        top_guilds = [
            {
                "name": g.name,
                "members": _fmt(g.member_count or 0),
                "pct": round((g.member_count or 0) / largest * 100) if largest else 0,
            }
            for g in top
        ]

        # Bot-weite Infrastruktur nur bei voller Sicht (Owner/Allowlist).
        user_count = command_count = cog_count = None
        mem_mb = mem_pct = cpu_pct = None
        if full:
            user_count = _fmt(len(bot.users))
            try:
                command_count = _fmt(sum(1 for _ in bot.walk_commands()))
            except Exception:
                command_count = _fmt(len(bot.commands))
            cog_count = _fmt(len(bot.cogs))
            if self._process is not None:
                try:
                    mem_mb = round(self._process.memory_info().rss / 1048576)
                    mem_pct = round(self._process.memory_percent())
                    cpu_pct = round(self._process.cpu_percent())
                except Exception:
                    pass

        now = datetime.now(timezone.utc)
        if full:
            entries = list(self.recent)
        else:
            visible_ids = {g.id for g in guilds}
            entries = [a for a in self.recent if a.get("guild_id") in visible_ids]
        activity = [
            {"ago": self._ago(a["ts"], now), "command": a["command"], "where": a["where"]}
            for a in entries
        ]

        return {
            "full_access": full,
            "guild_count": _fmt(len(guilds)),
            "member_total": _fmt(member_total),
            "user_count": user_count,
            "channel_count": _fmt(channel_count),
            "emoji_count": _fmt(emoji_count),
            "command_count": command_count,
            "cog_count": cog_count,
            "latency": latency,
            "uptime": uptime,
            "shard_count": bot.shard_count or 1,
            "red_version": RED_VERSION,
            "dpy_version": DPY_VERSION,
            "py_version": PY_VERSION,
            "mem_mb": mem_mb,
            "mem_pct": mem_pct,
            "cpu_pct": cpu_pct,
            "top_guilds": top_guilds,
            "activity": activity,
            "now": now.strftime("%H:%M:%S"),
            "bot_avatar": str(bot.user.display_avatar.url) if bot.user else None,
        }

    async def handle_login(self, request):
        data = await self.config.all()
        configured = bool(data["client_id"] and data["client_secret"] and data["redirect_uri"])
        if request.query.get("go") != "1" or not configured:
            # Erst die Login-Seite zeigen; ?go=1 startet den Discord-Login.
            return aiohttp_jinja2.render_template(
                "login.html", request,
                {"title": "Anmeldung", "not_configured": not configured, "state": None},
            )
        session = await get_session(request)
        state = secrets.token_urlsafe(16)
        session["oauth_state"] = state
        params = {
            "client_id": data["client_id"],
            "redirect_uri": data["redirect_uri"],
            "response_type": "code",
            "scope": "identify",
            "state": state,
            "prompt": "none",
        }
        raise web.HTTPFound(f"{DISCORD_AUTHORIZE}?{urlencode(params)}")

    async def handle_callback(self, request):
        data = await self.config.all()
        session = await get_session(request)
        if request.query.get("error"):
            return self._login_response(request, error="Anmeldung bei Discord abgebrochen.", status=400)
        code = request.query.get("code")
        state = request.query.get("state")
        # State einmalig verbrauchen und strikt vergleichen (verhindert Login-CSRF,
        # wenn die Session noch gar keinen State gesetzt hat -> None == None).
        stored_state = session.pop("oauth_state", None)
        if not code or not stored_state or state != stored_state:
            return self._login_response(
                request, error="Die Anmeldung ist abgelaufen oder ungültig – bitte erneut versuchen.", status=400
            )

        token_payload = {
            "client_id": str(data["client_id"]),
            "client_secret": data["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": data["redirect_uri"],
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        timeout = aiohttp.ClientTimeout(total=15)
        failed = "Discord hat die Anmeldung nicht bestätigt – bitte erneut versuchen."
        try:
            async with aiohttp.ClientSession(timeout=timeout) as cs:
                async with cs.post(DISCORD_TOKEN, data=token_payload, headers=headers) as resp:
                    if resp.status != 200:
                        return self._login_response(request, error=failed, status=400)
                    token = await resp.json()
                access_token = token.get("access_token")
                if not access_token:
                    return self._login_response(request, error=failed, status=400)
                async with cs.get(
                    f"{DISCORD_API}/users/@me",
                    headers={"Authorization": f"Bearer {access_token}"},
                ) as resp:
                    if resp.status != 200:
                        return self._login_response(request, error=failed, status=400)
                    me = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            # Discord nicht erreichbar / keine JSON-Antwort -> saubere Meldung statt HTTP 500.
            return self._login_response(
                request, error="Discord ist gerade nicht erreichbar – bitte gleich erneut versuchen.", status=502
            )

        if not me.get("id"):
            return self._login_response(request, error=failed, status=400)
        # Neue Sitzung (kein Übernehmen alter Werte, frisches CSRF-Token)
        session.clear()
        session["user_id"] = str(me["id"])
        session["user_name"] = me.get("global_name") or me.get("username", "Unbekannt")
        session["user_avatar"] = me.get("avatar")
        raise web.HTTPFound("/")

    async def handle_logout(self, request):
        session = await get_session(request)
        session.invalidate()
        raise web.HTTPFound("/login")

    def _error_page(self, request, title, message, *, status, active=None, icon=None, toast=None):
        return aiohttp_jinja2.render_template(
            "error.html", request,
            {"title": title, "message": message, "active_page": active, "icon": icon, "toast_err": toast},
            status=status,
        )

    async def _csrf_token(self, request) -> str:
        session = await get_session(request)
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def _set_switcher(self, request, guilds, selected_id, path):
        ordered = sorted(guilds, key=lambda g: g.name.lower())
        request["wc_switcher"] = {
            "path": path,
            "selected": selected_id,
            "guilds": [{"id": g.id, "name": g.name} for g in ordered],
        }
        sel = next((g for g in ordered if g.id == selected_id), None)
        request["wc_guild_name"] = sel.name if sel else ""

    async def _select_guild(self, request, guilds, path):
        """Globaler Server-Wechsler: ``?guild=`` erzwingen (aus Sitzung oder erster Server).

        Alle Cog-Seiten lesen ``?guild=``. Fehlt es (oder ist es für diese Seite nicht
        erlaubt), wird auf den zuletzt gewählten Server umgeleitet – dadurch bleibt die
        Auswahl beim Wechsel zwischen den Seiten erhalten.
        """
        session = await get_session(request)
        ids = {g.id for g in guilds}
        raw = request.query.get("guild")
        if raw and raw.isdigit() and int(raw) in ids:
            if session.get("wc_guild") != raw:
                session["wc_guild"] = raw
            return int(raw)
        pref = session.get("wc_guild")
        if pref and str(pref).isdigit() and int(pref) in ids:
            target = int(pref)
        else:
            target = sorted(guilds, key=lambda g: g.name.lower())[0].id
        raise web.HTTPFound(str(request.rel_url.update_query({"guild": str(target)})))

    async def handle_cog_page(self, request):
        user = await self._get_user(request)
        if not await self._is_authorized(user, request):
            return await self._deny(request, user)

        slug = request.match_info["slug"]
        page = self.pages.get(slug)
        if page is None:
            return self._error_page(request, "Nicht gefunden", f"Keine Seite für '{slug}'.",
                                    status=404, icon="bi-question-circle")

        view_guilds = await self.visible_guilds(request, min_level=acl.VIEW)
        if not view_guilds:
            return self._error_page(
                request, "Kein Zugriff",
                f"Deine Rollen haben keinen Zugriff auf „{page.name}“. Wende dich an den Bot-Owner.",
                status=403, active=slug, icon="bi-shield-lock",
            )
        amap = await self._access_map(user, request)
        full = amap is None

        # CSRF-Token pro Sitzung sicherstellen und dem Handler bereitstellen.
        token = await self._csrf_token(request)

        if request.method == "POST":
            form = await request.post()
            raw_gid = form.get("guild") or form.get("guild_id")
            gid = int(raw_gid) if raw_gid and str(raw_gid).isdigit() else None
            action = form.get("form") or form.get("action")
            if form.get("csrf_token") != token:
                return self._error_page(
                    request, "Abgelehnt",
                    "Ungültiges oder fehlendes CSRF-Token. Bitte Seite neu laden und erneut absenden.",
                    status=400, active=slug,
                )
            # Zentrale Durchsetzung: Tagesgeschäft (operate_forms) braucht mindestens „Bedienen“,
            # alles andere „Bearbeiten“ – jeweils für den Ziel-Server.
            is_operate = acl.is_operate_post(page.operate_forms, form)
            request["wc_operate"] = is_operate
            needed = acl.OPERATE if is_operate else acl.EDIT
            allowed_ids = {g.id for g in await self.visible_guilds(request, min_level=needed)}
            if not full and (not allowed_ids or (gid is not None and gid not in allowed_ids)):
                levels = [lv.get(slug, acl.NONE) for g_id, lv in (amap or {}).items()
                          if gid is None or g_id == gid]
                have = max(levels) if levels else acl.NONE
                back = f"/cogs/{slug}" + (f"?guild={gid}&" if gid else "?")
                if have == acl.OPERATE and needed == acl.EDIT:
                    await self._audit(request, user, page=slug, guild_id=gid, action=action,
                                      result="Abgelehnt: Stufe Bedienen, Bearbeiten nötig", ok=False)
                    raise web.HTTPFound(back + "err=" + "Daf%C3%BCr+brauchst+du+das+Recht+Bearbeiten")
                await self._audit(request, user, page=slug, guild_id=gid, action=action,
                                  result=f"Keine Bearbeitungsrechte (Stufe {acl.LEVEL_LABEL[have]})", ok=False)
                raise web.HTTPFound(back + "ok=" + "Keine+Bearbeitungsrechte+f%C3%BCr+diesen+Server")
            request["webcore_csrf"] = token
            try:
                result = await page.handler(request)
            except web.HTTPFound as exc:
                msg, ok = self._redirect_message(exc.location)
                await self._audit(request, user, page=slug, guild_id=gid, action=action, result=msg, ok=ok)
                raise
            except web.HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("Fehler in Dashboard-Seite %s (POST)", slug)
                await self._audit(request, user, page=slug, guild_id=gid, action=action,
                                  result=f"Fehler: {exc}", ok=False)
                return self._error_page(request, "Fehler", str(exc), status=500, active=slug)
            if isinstance(result, dict) and result.get("redirect"):
                msg, ok = self._redirect_message(result["redirect"])
                await self._audit(request, user, page=slug, guild_id=gid, action=action, result=msg, ok=ok)
                raise web.HTTPFound(result["redirect"])
            await self._audit(request, user, page=slug, guild_id=gid, action=action, result=None, ok=True)
        else:
            selected = await self._select_guild(request, view_guilds, f"/cogs/{slug}")
            self._set_switcher(request, view_guilds, selected, f"/cogs/{slug}")
            level = acl.EDIT if full else (amap.get(selected) or {}).get(slug, acl.NONE)
            # „Bedienen“ ohne Tagesgeschäft auf dieser Seite wirkt wie „Ansehen“.
            operate = level == acl.OPERATE and page.supports_operate
            request["webcore_readonly"] = level < acl.EDIT and not operate
            request["webcore_operate"] = operate
            if operate:
                request["wc_operate_forms"] = page.operate_list
            request["webcore_csrf"] = token
            try:
                result = await page.handler(request)
            except web.HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("Fehler in Dashboard-Seite %s", slug)
                return self._error_page(request, "Fehler", str(exc), status=500, active=slug)

        # Handler darf eine fertige Response direkt zurückgeben
        # (z. B. Transcript-Seite, Datei-Download). web.Response erbt von StreamResponse.
        if isinstance(result, web.StreamResponse):
            return result

        # Handler darf nach einem POST per {"redirect": "/..."} umleiten (PRG-Muster).
        if isinstance(result, dict) and result.get("redirect"):
            raise web.HTTPFound(result["redirect"])

        return aiohttp_jinja2.render_template(
            "page.html",
            request,
            self._page_ctx(
                request,
                title=result.get("title", page.name),
                content=result.get("content", ""),
                active_page=slug,
            ),
        )

    # ----------------------------------------------------------------- #
    #  Mitglieder-Bereich (/me)
    # ----------------------------------------------------------------- #
    async def _member_denied(self, request, user):
        """Kein Server mit Mitglieder-Bereich: Login bzw. „Kein Zugriff“."""
        if user is None:
            return self._login_response(request)
        if await self._is_authorized(user, request):
            # Team ohne Mitgliedschaft auf einem passenden Server: Fehlerseite mit normaler Navigation.
            return self._error_page(
                request, "Mein Bereich",
                "„Mein Bereich“ ist für dich auf keinem Server verfügbar. Der Bot-Owner schaltet ihn unter "
                "„Zugriff & Rollen“ bzw. mit [p]webcore portal on ein.",
                status=403, icon="bi-person-badge",
            )
        return self._login_response(request, state="noaccess", status=403)

    async def _member_guild_from_query(self, request, user, guilds, path, audit_page):
        """``?guild=`` für den Mitglieder-Bereich auflösen; fremde Server werden abgelehnt + protokolliert."""
        raw = request.query.get("guild")
        if raw and not (raw.isdigit() and int(raw) in {g.id for g in guilds}):
            await self._audit_denied(request, user, page=audit_page, guild_id=int(raw) if raw.isdigit() else None,
                                     action="guild", result="Kein Mitglieder-Zugriff auf diesen Server")
            first = sorted(guilds, key=lambda g: g.name.lower())[0]
            raise web.HTTPFound(f"{path}?guild={first.id}&err=" + "Kein+Zugriff+auf+diesen+Server")
        selected = await self._select_guild(request, guilds, path)
        self._set_switcher(request, guilds, selected, path)
        return selected

    def _set_member_request(self, request, guild_id):
        members = request.get("_wc_portal_members") or {}
        request["wc_member_guild"] = self.bot.get_guild(guild_id)
        request["wc_member"] = members.get(guild_id)
        request["wc_member_preview"] = guild_id in (request.get("_wc_portal_preview") or set())

    async def handle_member_home(self, request):
        """„Mein Bereich“: Kacheln aller registrierten Mitglieder-Seiten für den gewählten Server."""
        request["wc_area"] = "member"
        user = await self._get_user(request)
        guilds = await self._portal_scope(user, request)
        if not guilds:
            return await self._member_denied(request, user)
        selected = await self._member_guild_from_query(request, user, guilds, "/me", "me")
        self._set_member_request(request, selected)
        pages = [(p.slug, p.name, p.icon, p.description)
                 for p in await self._visible_member_pages(request["wc_member_guild"])]
        content = render_member_home(
            guild=request["wc_member_guild"], member=request["wc_member"], pages=pages,
        )
        return aiohttp_jinja2.render_template(
            "page.html", request,
            self._page_ctx(request, title="Mein Bereich", content=content, active_page="me",
                           member_nav=await self._member_nav_for(request)),
        )

    def _member_limited(self, request, retry: int) -> web.Response:
        msg = "Zu viele Anfragen – bitte warte kurz und versuche es dann erneut."
        if "application/json" in request.headers.get("Accept", ""):
            resp = web.json_response({"error": "rate_limited", "message": msg}, status=429)
        else:
            resp = self._error_page(request, "Zu viele Anfragen", msg, status=429,
                                    icon="bi-hourglass-split", toast=msg)
        resp.headers["Retry-After"] = str(max(1, int(retry)))
        return resp

    async def handle_member_page(self, request):
        """``/me/<slug>``: verteilt an die registrierte Mitglieder-Seite (GET + POST)."""
        request["wc_area"] = "member"
        user = await self._get_user(request)
        guilds = await self._portal_scope(user, request)
        if not guilds:
            return await self._member_denied(request, user)
        slug = request.match_info["slug"]
        active = f"me:{slug}"
        page = self.member_pages.get(slug)
        if page is None:
            return self._error_page(request, "Nicht gefunden", f"Keine Seite „{slug}“ in „Mein Bereich“.",
                                    status=404, icon="bi-question-circle")
        token = await self._csrf_token(request)
        ids = {g.id for g in guilds}

        if request.method == "POST":
            allowed, retry = self._member_limiter.hit(user["id"])
            if not allowed:
                await self._audit_denied(request, user, page=active, guild_id=None, action="POST",
                                         result="Zu viele Anfragen (Rate-Limit)")
                return self._member_limited(request, retry)
            form = await request.post()
            if form.get("csrf_token") != token:
                await self._audit_denied(request, user, page=active, guild_id=await self._post_guild_id(request),
                                         action="POST", result="Ungültiges CSRF-Token")
                return self._error_page(
                    request, "Abgelehnt",
                    "Ungültiges oder fehlendes Sicherheits-Token. Bitte Seite neu laden und erneut absenden.",
                    status=400, active=active,
                )
            raw = str(form.get("guild") or form.get("guild_id") or request.query.get("guild") or "")
            if not raw:
                session = await get_session(request)
                pref = str(session.get("wc_guild") or "")
                raw = pref if pref.isdigit() and int(pref) in ids else (str(guilds[0].id) if len(guilds) == 1 else "")
            gid = int(raw) if raw.isdigit() else None
            if gid not in ids:
                await self._audit_denied(request, user, page=active, guild_id=gid,
                                         action=form.get("form") or form.get("action") or "POST",
                                         result="Kein Mitglieder-Zugriff auf diesen Server")
                raise web.HTTPFound(f"/me/{slug}?err=" + "Kein+Zugriff+auf+diesen+Server")
            self._set_member_request(request, gid)
        else:
            selected = await self._member_guild_from_query(request, user, guilds, f"/me/{slug}", active)
            self._set_member_request(request, selected)
        request["webcore_readonly"] = False
        request["webcore_csrf"] = token
        # Mitglieder-Aktionen landen bewusst NICHT im Admin-Audit-Log (nur abgelehnte Zugriffe).
        try:
            result = await page.handler(request)
        except web.HTTPException:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Fehler in Mitglieder-Seite %s (%s)", slug, request.method)
            # Mitgliedern keine internen Fehlertexte zeigen.
            return self._error_page(request, "Fehler", "Da ist etwas schiefgelaufen. Bitte später erneut versuchen.",
                                    status=500, active=active)

        if isinstance(result, web.StreamResponse):
            return result
        if isinstance(result, dict) and result.get("redirect"):
            raise web.HTTPFound(result["redirect"])
        result = result or {}
        return aiohttp_jinja2.render_template(
            "page.html", request,
            self._page_ctx(request, title=result.get("title", page.name),
                           content=result.get("content", ""), active_page=active,
                           member_nav=await self._member_nav_for(request)),
        )

    # ----------------------------------------------------------------- #
    #  Öffentliche API (/api/public/<slug>[/<tail>])
    # ----------------------------------------------------------------- #
    _CORS = {"Access-Control-Allow-Origin": "*"}

    def _public_error(self, status: int, error: str, **extra) -> web.Response:
        headers = {**self._CORS, "Cache-Control": "no-store", **extra}
        return web.json_response({"error": error}, status=status, headers=headers)

    async def handle_public(self, request):
        """Ohne Login und ohne Sitzung (es wird nie ein Cookie gelesen oder gesetzt)."""
        if request.method == "OPTIONS":
            return web.Response(status=204, headers={
                **self._CORS,
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            })
        allowed, retry = self._public_limiter.hit(client_ip(request))
        if not allowed:
            return self._public_error(429, "rate_limited", **{"Retry-After": str(retry)})
        api = self.public_apis.get(request.match_info.get("slug", ""))
        if api is None:
            return self._public_error(404, "not_found")
        try:
            result = await api.handler(request)
            if result is None:
                return self._public_error(404, "not_found")
            resp = result if isinstance(result, web.StreamResponse) else web.json_response(result)
        except web.HTTPException as exc:
            if exc.status < 400:
                raise
            return self._public_error(exc.status, (exc.reason or "error").lower().replace(" ", "_"))
        except Exception:  # noqa: BLE001 – nie einen Stacktrace ausliefern
            log.exception("Fehler in der öffentlichen API %s", api.slug)
            return self._public_error(500, "internal_error")
        for key, val in self._CORS.items():
            resp.headers.setdefault(key, val)
        resp.headers.setdefault("Cache-Control", "public, max-age=60")
        return resp

    # ----------------------------------------------------------------- #
    #  Owner-Seiten: Zugriff & Rollen, Audit-Log
    # ----------------------------------------------------------------- #
    async def _require_owner_page(self, request):
        user = await self._get_user(request)
        if not await self._is_authorized(user, request):
            return user, await self._deny(request, user)
        if not await self._has_full_scope(user):
            return user, self._error_page(request, "Kein Zugriff",
                                          "Diese Seite ist dem Bot-Owner vorbehalten.",
                                          status=403, icon="bi-shield-lock")
        return user, None

    async def handle_access(self, request):
        user, denied = await self._require_owner_page(request)
        if denied is not None:
            return denied
        if user["id"] not in self.bot.owner_ids:
            # Allowlist hat volle Sicht, Rechte vergeben darf aber nur der Owner.
            return self._error_page(request, "Kein Zugriff", "Rollen-Rechte vergibt nur der Bot-Owner.",
                                    status=403, icon="bi-shield-lock")
        guilds = list(self.bot.guilds)
        if not guilds:
            return self._error_page(request, "Zugriff & Rollen", "Der Bot ist auf keinem Server.", status=200)
        token = await self._csrf_token(request)

        if request.method == "POST":
            form = await request.post()
            if form.get("csrf_token") != token:
                return self._error_page(request, "Abgelehnt", "Ungültiges CSRF-Token. Bitte neu laden.", status=400)
            raw = form.get("guild")
            guild = self.bot.get_guild(int(raw)) if raw and raw.isdigit() else None
            if guild is None:
                raise web.HTTPFound("/access?ok=Server+nicht+gefunden")
            action = form.get("form")
            from urllib.parse import quote_plus
            if action == "portal":
                enabled = bool(form.get("portal"))
                await self._set_portal(guild.id, enabled)
                msg = f"Mein Bereich {'eingeschaltet' if enabled else 'ausgeschaltet'}"
                await self._audit(request, user, page="access", guild_id=guild.id, action="portal", result=msg, ok=True)
                raise web.HTTPFound(f"/access?guild={guild.id}&ok=" + quote_plus(msg))
            msg = "Gespeichert"
            async with self.config.role_perms() as role_perms:
                gperms = role_perms.setdefault(str(guild.id), {})
                if action in ("add_role", "apply_template"):
                    rid = form.get("role_id")
                    role = guild.get_role(int(rid)) if rid and rid.isdigit() else None
                    # Vorlage (neu) bzw. „Startwert“ älterer Formulare (1 = Ansehen, 2 = Bearbeiten).
                    tkey = acl.resolve_template(form.get("template") or "")
                    if tkey is None and action == "add_role" and "template" not in form:
                        tkey = {"2": "edit"}.get(str(form.get("default") or ""), "view")
                    if role is None or role.is_default():
                        msg = "Rolle nicht gefunden"
                    elif tkey is None:
                        msg = "Vorlage nicht gefunden"
                    elif action == "add_role" and str(role.id) in gperms:
                        msg = f"Rolle {role.name} ist bereits eingetragen"
                    else:
                        entry = acl.apply_template(gperms.get(str(role.id)), tkey, self.pages)
                        label = acl.ROLE_TEMPLATES[tkey]["label"]
                        if entry:
                            gperms[str(role.id)] = entry
                        else:
                            gperms.pop(str(role.id), None)
                        if action == "add_role":
                            msg = (f"Rolle {role.name} hinzugefügt (Vorlage {label})" if entry else
                                   f"Vorlage {label} ergibt keine Rechte für die geladenen Seiten – "
                                   f"Rolle {role.name} nicht hinzugefügt")
                        else:
                            msg = f"Vorlage {label} auf {role.name} angewendet"
                elif action == "matrix":
                    remove = form.get("remove")
                    bad = [k for k, v in form.items() if str(k).startswith("p:") and not acl.is_level_name(v)]
                    if bad:
                        # z. B. eine alte, noch offene Seite mit Zahlen-Werten – lieber nichts speichern.
                        raise web.HTTPFound(f"/access?guild={guild.id}&err="
                                            + quote_plus("Ungültige Stufe – bitte Seite neu laden"))
                    for rid in form.getall("roles", []):
                        if not str(rid).isdigit():
                            continue
                        if remove and rid == remove:
                            gperms.pop(rid, None)
                            continue
                        entry = {}
                        for slug in self.pages:
                            lvl = acl.parse_level(form.get(f"p:{rid}:{slug}") or "none")
                            if lvl > acl.NONE:
                                entry[slug] = acl.NAME_BY_LEVEL[lvl]
                        # Rechte für aktuell nicht geladene Cogs beibehalten
                        for slug, val in (gperms.get(rid) or {}).items():
                            if slug not in self.pages:
                                entry[slug] = val
                        if entry:
                            gperms[rid] = entry
                        else:
                            gperms.pop(rid, None)
                    msg = "Rolle entfernt" if remove else "Rechte gespeichert"
                elif action == "cleanup":
                    for rid in list(gperms):
                        if not str(rid).isdigit() or guild.get_role(int(rid)) is None:
                            gperms.pop(rid, None)
                    msg = "Aufgeräumt"
                if not gperms:
                    role_perms.pop(str(guild.id), None)
            failed = msg in ("Rolle nicht gefunden", "Vorlage nicht gefunden") or "nicht hinzugefügt" in msg \
                or "bereits eingetragen" in msg
            await self._audit(request, user, page="access", guild_id=guild.id, action=action, result=msg,
                              ok=not failed)
            if failed:
                raise web.HTTPFound(f"/access?guild={guild.id}&err=" + quote_plus(msg))
            raise web.HTTPFound(f"/access?guild={guild.id}&ok=" + quote_plus(msg))

        selected = await self._select_guild(request, guilds, "/access")
        guild = self.bot.get_guild(selected)
        self._set_switcher(request, guilds, selected, "/access")
        roles = [
            (r.id, r.name, f"#{r.color.value:06x}" if r.color.value else None, len(r.members), r.position)
            for r in guild.roles if not r.is_default() and not r.managed
        ]
        pages = [(p.slug, p.name, p.icon) for p in sorted(self.pages.values(), key=lambda x: x.name.lower())]
        role_perms = await self.config.role_perms()
        content = render_access(
            guild=guild, roles=roles, pages=pages,
            guild_perms=acl.guild_role_perms(role_perms, guild.id),
            csrf=token, access_mode=await self.config.access_mode(),
            operate_pages={p.slug for p in self.pages.values() if p.supports_operate},
        )
        portal = await self.config.member_portal() or {}
        content += render_portal_card(
            guild=guild, enabled=bool(portal.get(str(guild.id))), csrf=token,
            member_pages=[(p.name, p.icon, p.description)
                          for p in sorted(self.member_pages.values(), key=lambda x: x.name.lower())],
        )
        return aiohttp_jinja2.render_template(
            "page.html", request,
            self._page_ctx(request, title="Zugriff & Rollen", content=content, active_page="access"),
        )

    async def _set_portal(self, guild_id: int, enabled: bool) -> None:
        async with self.config.member_portal() as portal:
            if enabled:
                portal[str(guild_id)] = True
            else:
                portal.pop(str(guild_id), None)

    async def _set_audit_channel(self, guild_id: int, channel_id) -> None:
        async with self.config.audit_channels() as chans:
            if channel_id:
                chans[str(guild_id)] = int(channel_id)
            else:
                chans.pop(str(guild_id), None)

    async def handle_audit(self, request):
        user, denied = await self._require_owner_page(request)
        if denied is not None:
            return denied
        is_owner = user["id"] in self.bot.owner_ids
        token = await self._csrf_token(request)
        guilds = list(self.bot.guilds)

        if request.method == "POST":
            form = await request.post()
            if form.get("csrf_token") != token:
                return self._error_page(request, "Abgelehnt", "Ungültiges CSRF-Token. Bitte neu laden.", status=400)
            if not is_owner:
                return self._error_page(request, "Kein Zugriff", "Den Log-Kanal legt nur der Bot-Owner fest.",
                                        status=403, icon="bi-shield-lock")
            raw = str(form.get("guild") or "")
            guild = self.bot.get_guild(int(raw)) if raw.isdigit() else None
            if guild is None:
                raise web.HTTPFound("/audit?err=Server+nicht+gefunden")
            raw_ch = str(form.get("channel") or "")
            channel = None
            if raw_ch:
                channel = next((c for c in guild.text_channels if str(c.id) == raw_ch), None)
                if channel is None:
                    raise web.HTTPFound(f"/audit?guild={guild.id}&err=Kanal+nicht+gefunden")
            await self._set_audit_channel(guild.id, channel.id if channel else None)
            msg = f"Log-Kanal: #{channel.name}" if channel else "Log-Kanal ausgeschaltet"
            await self._audit(request, user, page="audit", guild_id=guild.id, action="auditchannel",
                              result=msg, ok=True)
            from urllib.parse import quote_plus
            raise web.HTTPFound(f"/audit?guild={guild.id}&ok=" + quote_plus(msg))

        channel_card = ""
        if is_owner and guilds:
            selected = await self._select_guild(request, guilds, "/audit")
            self._set_switcher(request, guilds, selected, "/audit")
            guild = self.bot.get_guild(selected)
            chans = await self.config.audit_channels() or {}
            active = []
            for gid, cid in chans.items():
                g = self.bot.get_guild(int(gid)) if str(gid).isdigit() else None
                ch = g.get_channel(int(cid)) if g is not None else None
                if g is not None:
                    active.append((g.name, f"#{ch.name}" if ch is not None else f"gelöschter Kanal ({cid})"))
            channel_card = render_audit_channel(
                guild=guild, channels=[(c.id, c.name) for c in guild.text_channels],
                current=chans.get(str(guild.id)), csrf=token, active=sorted(active),
            )
        entries = await self.config.audit()
        page_names = {p.slug: p.name for p in self.pages.values()}
        page_names.update({f"me:{p.slug}": f"Mein Bereich: {p.name}" for p in self.member_pages.values()})
        page_names.update(OWNER_PAGE_LABELS)
        page_names["me"] = "Mein Bereich"
        guild_names = {}
        for e in entries:
            gid = e.get("guild_id")
            if gid:
                g = self.bot.get_guild(int(gid))
                guild_names[str(gid)] = g.name if g else (e.get("guild_name") or str(gid))
        content = channel_card + render_audit(entries, page_names=page_names, guild_names=guild_names)
        return aiohttp_jinja2.render_template(
            "page.html", request,
            self._page_ctx(request, title="Audit-Log", content=content, active_page="audit"),
        )

    # ----------------------------------------------------------------- #
    #  Owner-Seiten: Bot-Status, Fehlerprotokoll
    # ----------------------------------------------------------------- #
    def _process_info(self) -> dict:
        """RAM/CPU des Bot-Prozesses: psutil (in Red enthalten), sonst ``resource`` (nur Spitzenwerte)."""
        proc = self._process
        if proc is None and psutil is not None:
            try:
                proc = self._process = psutil.Process()
                proc.cpu_percent(None)
            except Exception:  # noqa: BLE001
                proc = None
        if proc is not None:
            try:
                with proc.oneshot():
                    return {
                        "source": "psutil",
                        "rss_mb": round(proc.memory_info().rss / 1048576),
                        "mem_pct": round(proc.memory_percent(), 1),
                        "cpu_pct": round(proc.cpu_percent(None), 1),
                        "threads": proc.num_threads(),
                        "pid": proc.pid,
                        "cpu_count": psutil.cpu_count() or None,
                    }
            except Exception:  # noqa: BLE001
                pass
        if resource is not None:
            try:
                ru = resource.getrusage(resource.RUSAGE_SELF)
                # Linux: KiB, macOS: Bytes
                peak = ru.ru_maxrss / (1048576 if sys.platform == "darwin" else 1024)
                cpu = int(ru.ru_utime + ru.ru_stime)
                return {
                    "source": "resource",
                    "rss_mb": round(peak),
                    "cpu_time": f"{cpu // 3600}h {(cpu % 3600) // 60}m {cpu % 60}s",
                    "threads": threading.active_count(),
                    "pid": os.getpid(),
                }
            except Exception:  # noqa: BLE001
                pass
        return {"source": None}

    def _cog_rows(self) -> list:
        """Geladene Cogs mit ihren WebCore-Registrierungen (Seiten, Mitglieder-Seiten, öffentliche APIs)."""
        cogs = {}
        for name, cog in dict(getattr(self.bot, "cogs", None) or {}).items():
            cogs[str(name)] = cog
        for reg in list(self.pages.values()) + list(self.member_pages.values()) + list(self.public_apis.values()):
            name = getattr(reg.owner, "qualified_name", None) or str(reg.owner)
            cogs.setdefault(str(name), reg.owner)
        rows = []
        for name, cog in sorted(cogs.items(), key=lambda kv: kv[0].lower()):
            module = type(cog).__module__ or ""
            try:
                n_cmds = sum(1 for _ in cog.walk_commands()) if hasattr(cog, "walk_commands") else None
            except Exception:  # noqa: BLE001
                n_cmds = None
            rows.append({
                "name": name,
                "core": module.startswith("redbot."),
                "package": module.split(".")[0] if module and module not in ("types", "builtins") else "",
                "commands": n_cmds,
                "pages": [(p.slug, p.name) for p in sorted(self.pages.values(), key=lambda x: x.name.lower())
                          if p.owner is cog],
                "member_pages": [(p.slug, p.name) for p in sorted(self.member_pages.values(), key=lambda x: x.name.lower())
                                 if p.owner is cog],
                "apis": [(a.slug, f"/api/public/{a.slug}") for a in sorted(self.public_apis.values(), key=lambda x: x.slug)
                         if a.owner is cog],
            })
        return rows

    def _error_records(self) -> list:
        """Einträge des Fehlerprotokolls (neueste zuerst), zur Anzeige erneut maskiert."""
        if self._errorlog is None:
            return []
        known = tuple(self._known_secrets)
        out = []
        for r in self._errorlog.snapshot():
            r = dict(r)
            r["message"] = errorlog.mask_secrets(r.get("message"), known)
            r["traceback"] = errorlog.mask_secrets(r.get("traceback"), known)
            r["time"] = errorlog.fmt_time(r.get("ts"))
            out.append(r)
        return out

    async def _collect_status(self) -> dict:
        bot = self.bot
        started = self._aware(getattr(bot, "uptime", None) or self._loaded_at)
        lat = getattr(bot, "latency", None)
        latency = round(lat * 1000) if isinstance(lat, (int, float)) and lat == lat and lat != float("inf") else None
        guilds = list(bot.guilds)
        records = self._error_records()
        cogs = self._cog_rows()
        return {
            "uptime": self._humanize(datetime.now(timezone.utc) - started),
            "started": started.astimezone().strftime("%d.%m.%Y %H:%M"),
            "latency": latency,
            "guild_count": _fmt(len(guilds)),
            "member_total": _fmt(sum((g.member_count or 0) for g in guilds)),
            "user_count": _fmt(len(getattr(bot, "users", []) or [])),
            "cog_count": _fmt(len(cogs)),
            "page_count": len(self.pages),
            "process": self._process_info(),
            "versions": [
                ("Python", PY_VERSION), ("Red-DiscordBot", RED_VERSION), ("discord.py", DPY_VERSION),
                ("aiohttp", aiohttp.__version__), ("System", f"{platform.system()} {platform.release()}".strip()),
                ("Shards", str(getattr(bot, "shard_count", None) or 1)),
            ],
            "cogs": cogs,
            "errors": {
                "warning": sum(1 for r in records if r["levelno"] < logging.ERROR),
                "error": sum(1 for r in records if r["levelno"] >= logging.ERROR),
                "recent": records[:5],
            },
        }

    async def handle_status(self, request):
        user, denied = await self._require_owner_page(request)
        if denied is not None:
            return denied
        try:
            await self._refresh_known_secrets()
        except Exception:  # noqa: BLE001
            pass
        content = render_status(await self._collect_status())
        return aiohttp_jinja2.render_template(
            "page.html", request, self._page_ctx(request, title="Bot-Status", content=content, active_page="status"),
        )

    async def handle_errors(self, request):
        user, denied = await self._require_owner_page(request)
        if denied is not None:
            return denied
        token = await self._csrf_token(request)
        if request.method == "POST":
            form = await request.post()
            if form.get("csrf_token") != token:
                return self._error_page(request, "Abgelehnt", "Ungültiges CSRF-Token. Bitte neu laden.", status=400,
                                        active="errors")
            if form.get("form") != "clear":
                raise web.HTTPFound("/errors?err=Unbekannte+Aktion")
            n = len(self._errorlog.records) if self._errorlog is not None else 0
            if self._errorlog is not None:
                self._errorlog.clear()
            await self._audit(request, user, page="errors", guild_id=None, action="clear",
                              result=f"{n} Einträge gelöscht", ok=True)
            raise web.HTTPFound("/errors?ok=Fehlerprotokoll+geleert")
        try:
            await self._refresh_known_secrets()
        except Exception:  # noqa: BLE001
            pass
        records = self._error_records()
        sources = sorted({r["source"] for r in records}, key=str.lower)
        level = request.query.get("level", "").upper()
        min_no = logging.getLevelName(level) if level in ("WARNING", "ERROR", "CRITICAL") else None
        level = level if min_no is not None else ""
        source = request.query.get("source", "")
        query = request.query.get("q", "").strip()[:200]
        shown = [
            r for r in records
            if (min_no is None or r["levelno"] >= min_no)
            and (not source or r["source"] == source)
            and (not query or query.lower() in f"{r['message']}\n{r['traceback']}\n{r['logger']}".lower())
        ]
        content = render_errors(shown, total=len(records), sources=sources, level=level, source=source, query=query,
                                csrf=token, active=self._errorlog is not None, capacity=errorlog.MAX_RECORDS)
        return aiohttp_jinja2.render_template(
            "page.html", request,
            self._page_ctx(request, title="Fehlerprotokoll", content=content, active_page="errors"),
        )

    # ----------------------------------------------------------------- #
    #  Owner-Seite: Sichern & Wiederherstellen
    # ----------------------------------------------------------------- #
    def _prune_pending(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._import_pending.items() if now - v["created"] > IMPORT_PREVIEW_TTL]:
            del self._import_pending[key]
        while len(self._import_pending) > 20:
            oldest = min(self._import_pending, key=lambda k: self._import_pending[k]["created"])
            del self._import_pending[oldest]

    def _get_pending(self, token, user, guild_id):
        self._prune_pending()
        pending = self._import_pending.get(str(token or ""))
        if pending is None or pending["user_id"] != user["id"] or pending["guild_id"] != guild_id:
            return None
        return pending

    @staticmethod
    def _backup_filename(guild) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", guild.name).strip("-").lower()[:40] or "server"
        return f"backup-{slug}-{guild.id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"

    async def handle_backup(self, request):
        user, denied = await self._require_owner_page(request)
        if denied is not None:
            return denied
        guilds = list(self.bot.guilds)
        if not guilds:
            return self._error_page(request, "Sichern & Wiederherstellen", "Der Bot ist auf keinem Server.", status=200,
                                    active="backup")
        token = await self._csrf_token(request)
        from urllib.parse import quote_plus

        if request.method == "POST":
            back_gid = request.query.get("guild", "")
            back = f"/backup?guild={back_gid}&" if back_gid.isdigit() else "/backup?"
            too_big = back + "err=" + quote_plus("Datei zu groß (höchstens 2 MB).")
            if (request.content_length or 0) > bk.MAX_BYTES + 256 * 1024:
                raise web.HTTPFound(too_big)
            try:
                # Upload bis 2 MB (+ Formular-Overhead) – das App-weite Limit bleibt bei 1 MiB.
                form = await request.clone(client_max_size=bk.MAX_BYTES + 256 * 1024).post()
            except web.HTTPRequestEntityTooLarge:
                raise web.HTTPFound(too_big) from None
            if form.get("csrf_token") != token:
                return self._error_page(request, "Abgelehnt", "Ungültiges CSRF-Token. Bitte neu laden.", status=400,
                                        active="backup")
            raw = str(form.get("guild") or "")
            guild = self.bot.get_guild(int(raw)) if raw.isdigit() else None
            if guild is None:
                raise web.HTTPFound("/backup?err=Server+nicht+gefunden")
            base = f"/backup?guild={guild.id}"
            action = form.get("form")

            is_owner = user["id"] in self.bot.owner_ids
            if action == "export":
                include_global = bool(form.get("include_global"))
                # Dashboard-Einstellungen (Rollen-Rechte …) nur für den Bot-Owner – wie „Zugriff & Rollen“.
                data = await bk.build_export(self, guild, include_global=include_global, include_webcore=is_owner)
                await self._audit(request, user, page="backup", guild_id=guild.id, action="export",
                                  result=f"{len(data['cogs'])} Cogs exportiert" + (" (inkl. botweit)" if include_global else "")
                                  + (" + Dashboard-Einstellungen" if "webcore" in data else ""),
                                  ok=True)
                return web.Response(
                    body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                    content_type="application/json", charset="utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{self._backup_filename(guild)}"',
                             "Cache-Control": "no-store"},
                )

            if action == "preview":
                upload = form.get("backup")
                if not hasattr(upload, "file"):
                    raise web.HTTPFound(f"{base}&err=" + quote_plus("Bitte eine Sicherungsdatei auswählen."))
                raw_bytes = await asyncio.to_thread(upload.file.read, bk.MAX_BYTES + 1)
                try:
                    data = bk.parse_backup(raw_bytes)
                except ValueError as exc:
                    raise web.HTTPFound(f"{base}&err=" + quote_plus(str(exc))) from None
                self._prune_pending()
                pid = secrets.token_urlsafe(16)
                self._import_pending[pid] = {
                    "user_id": user["id"], "guild_id": guild.id, "data": data,
                    "filename": str(getattr(upload, "filename", "") or "")[:120], "created": time.monotonic(),
                }
                raise web.HTTPFound(f"{base}&preview={pid}")

            if action == "cancel":
                self._import_pending.pop(str(form.get("preview") or ""), None)
                raise web.HTTPFound(f"{base}&ok=" + quote_plus("Import abgebrochen"))

            if action == "confirm":
                pending = self._get_pending(form.get("preview"), user, guild.id)
                if pending is None:
                    raise web.HTTPFound(f"{base}&err=" + quote_plus(
                        "Die Vorschau ist abgelaufen – bitte die Datei erneut hochladen."))
                async with self._backup_lock:
                    plan = await bk.plan_import(self, guild, pending["data"])
                    include_global = bool(form.get("include_global")) and plan["has_global"]
                    wplan = plan.get("webcore")
                    # Rechte-Vergabe ist sicherheitsrelevant: nur Bot-Owner und nur mit eigenem Häkchen.
                    include_webcore = bool(form.get("include_webcore")) and is_owner and wplan is not None
                    totals = bk.plan_totals(plan, include_global=include_global)
                    snapshot = await bk.apply_import(self, guild, plan, include_global=include_global)
                    wc_snap = await bk.apply_webcore(self, guild, wplan) if include_webcore else {}
                if wc_snap:
                    self._invalidate_access_cache(request)
                self._import_pending.pop(str(form.get("preview")), None)
                ignored = totals["unknown"] + totals["type_errors"]
                if not snapshot and not wc_snap:
                    msg = "Keine Änderungen – die Einstellungen waren schon so"
                else:
                    src = pending["data"]
                    undo = self._import_undo.setdefault(guild.id, [])
                    undo.insert(0, {
                        "id": secrets.token_urlsafe(10), "ts": time.time(), "user": user["name"],
                        "source": f"{src.get('guild_name') or '?'} ({src.get('guild_id')})",
                        "cogs": sorted(snapshot) + (["Dashboard-Einstellungen"] if wc_snap else []),
                        "snapshot": snapshot, "webcore": wc_snap or None,
                        "keys": sum(len(s.get("guild", {})) + len(s.get("global", {})) for s in snapshot.values())
                        + int(wc_snap.get("changes", 0) if wc_snap else 0),
                    })
                    del undo[IMPORT_UNDO_KEEP:]
                    done = []
                    if snapshot:
                        done.append(f"{totals['changed']} Einstellung(en) in {totals['cogs']} Cog(s)")
                    if wc_snap:
                        done.append(f"Dashboard-Rechte/-Einstellungen ({int(wc_snap.get('changes', 0))} Änderung(en))")
                    msg = "Import: " + " und ".join(done) + " übernommen"
                if ignored:
                    msg += f", {ignored} ignoriert (unbekannt/falscher Typ)"
                if include_webcore and bk.webcore_problems(wplan):
                    msg += f", {bk.webcore_problems(wplan)} Dashboard-Einträge übersprungen"
                extras = (["botweit"] if include_global else []) + (["Dashboard-Rechte"] if wc_snap else [])
                action_label = "import" + (f" (inkl. {', '.join(extras)})" if extras else "")
                await self._audit(request, user, page="backup", guild_id=guild.id,
                                  action=action_label, result=msg, ok=True)
                raise web.HTTPFound(f"{base}&ok=" + quote_plus(msg))

            if action == "undo":
                uid = str(form.get("undo") or "")
                entries = self._import_undo.get(guild.id) or []
                entry = next((e for e in entries if e["id"] == uid), None)
                if entry is None:
                    raise web.HTTPFound(f"{base}&err=" + quote_plus("Dieser Stand ist nicht mehr verfügbar."))
                if entry.get("webcore") and not is_owner:
                    raise web.HTTPFound(f"{base}&err=" + quote_plus(
                        "Dieser Import enthält Dashboard-Rechte – rückgängig machen kann ihn nur der Bot-Owner."))
                async with self._backup_lock:
                    count, missing = await bk.restore_snapshot(self, guild, entry["snapshot"])
                    wc_count = await bk.restore_webcore(self, guild, entry["webcore"]) if entry.get("webcore") else 0
                if wc_count:
                    self._invalidate_access_cache(request)
                entries.remove(entry)
                msg = f"Rückgängig: {count} Einstellung(en) wiederhergestellt"
                if wc_count:
                    msg += ", Dashboard-Rechte/-Einstellungen zurückgesetzt"
                if missing:
                    msg += " (nicht geladen: " + ", ".join(missing) + ")"
                await self._audit(request, user, page="backup", guild_id=guild.id, action="undo", result=msg,
                                  ok=not missing)
                raise web.HTTPFound(f"{base}&ok=" + quote_plus(msg))

            raise web.HTTPFound(f"{base}&err=Unbekannte+Aktion")

        selected = await self._select_guild(request, guilds, "/backup")
        self._set_switcher(request, guilds, selected, "/backup")
        guild = self.bot.get_guild(selected)
        preview_html = ""
        pid = request.query.get("preview", "")
        if pid:
            pending = self._get_pending(pid, user, guild.id)
            if pending is None:
                request["wc_toast_err"] = "Die Vorschau ist abgelaufen oder gehört zu einem anderen Server."
            else:
                plan = await bk.plan_import(self, guild, pending["data"])
                page_names = {p.slug: p.name for p in self.pages.values()}
                preview_html = render_backup_preview(guild=guild, data=pending["data"], plan=plan, token=pid,
                                                     csrf=token, filename=pending["filename"], page_names=page_names,
                                                     can_webcore=user["id"] in self.bot.owner_ids)
        cogs = [(name, len(bk.guild_defaults(cog.config)), len(bk.global_defaults(cog.config)))
                for name, cog in bk.backup_cogs(self).items()
                if bk.guild_defaults(cog.config) or bk.global_defaults(cog.config)]
        undo = [
            {"id": e["id"], "time": errorlog.fmt_time(e["ts"]), "user": e["user"], "source": e["source"],
             "cogs": e["cogs"], "keys": e["keys"]}
            for e in self._import_undo.get(guild.id) or []
        ]
        content = render_backup(guild=guild, cogs=cogs, csrf=token, undo=undo, preview=preview_html,
                                webcore_export=user["id"] in self.bot.owner_ids)
        return aiohttp_jinja2.render_template(
            "page.html", request,
            self._page_ctx(request, title="Sichern & Wiederherstellen", content=content, active_page="backup",
                           toast_err=request.get("wc_toast_err")),
        )

    # ----------------------------------------------------------------- #
    #  Owner-Befehle
    # ----------------------------------------------------------------- #
    @commands.group()
    @commands.is_owner()
    async def webcore(self, ctx: commands.Context):
        """Einstellungen für das Web-Dashboard."""

    @webcore.command(name="oauth")
    async def webcore_oauth(self, ctx: commands.Context, client_id: str, client_secret: str, redirect_uri: str):
        """OAuth2-Daten setzen.

        redirect_uri MUSS exakt dem Eintrag im Discord-Developer-Portal entsprechen,
        z. B. https://dashboard.deinedomain.de/callback
        """
        await self.config.client_id.set(client_id)
        await self.config.client_secret.set(client_secret)
        await self.config.redirect_uri.set(redirect_uri)
        try:
            await ctx.message.delete()
        except Exception:
            pass
        msg = "OAuth2-Daten gespeichert. Übernehmen mit `[p]reload webcore`."
        low = redirect_uri.lower()
        if not low.endswith("/callback"):
            msg += "\n⚠️ Die redirect_uri muss auf `/callback` enden."
        if low.startswith("http://") and not any(x in low for x in ("localhost", "127.0.0.1", "192.168.", "10.", "172.")):
            msg += ("\n⚠️ Öffentliche Adresse ohne HTTPS: Sitzungscookies würden unverschlüsselt übertragen. "
                    "Nutze einen Reverse-Proxy mit Zertifikat und eine `https://`-Adresse.")
        elif low.startswith("https://"):
            msg += "\nHTTPS erkannt: Das Sitzungscookie wird nach dem Reload nur noch über HTTPS gesendet."
        await ctx.send(msg)

    @webcore.command(name="port")
    async def webcore_port(self, ctx: commands.Context, port: int):
        """Webserver-Port setzen (Standard 42100)."""
        if not 1 <= port <= 65535:
            await ctx.send("Ungültiger Port (1–65535).")
            return
        await self.config.port.set(port)
        await ctx.send(f"Port auf {port} gesetzt. Übernehmen mit `[p]reload webcore`.")

    @webcore.command(name="host")
    async def webcore_host(self, ctx: commands.Context, host: str):
        """Bind-Host setzen (Standard 0.0.0.0).

        Muss eine lokale Bind-Adresse sein (0.0.0.0, 127.0.0.1 oder eine interne IP),
        nicht die öffentliche Domain – die gehört in die redirect_uri.
        """
        try:
            socket.getaddrinfo(host, None)
        except OSError:
            await ctx.send(
                f"`{host}` lässt sich nicht auflösen. Nimm eine lokale Bind-Adresse wie "
                f"`0.0.0.0` (alle Interfaces) oder `127.0.0.1`. Die öffentliche Domain "
                f"gehört in die redirect_uri, nicht in den Host."
            )
            return
        await self.config.host.set(host)
        await ctx.send(f"Host auf {host} gesetzt. Übernehmen mit `[p]reload webcore`.")

    @webcore.command(name="access")
    async def webcore_access(self, ctx: commands.Context, mode: str):
        """Zugriffsmodus setzen: owner | admin | allowlist."""
        mode = mode.lower()
        if mode not in ("owner", "admin", "allowlist"):
            await ctx.send("Modus muss `owner`, `admin` oder `allowlist` sein.")
            return
        await self.config.access_mode.set(mode)
        hint = {
            "owner": "Nur Bot-Owner und Co-Owner (plus Rollen mit Dashboard-Rechten).",
            "admin": (
                "Owner plus Discord-Admins (in mind. einem gemeinsamen Server) – "
                "jeweils nur auf ihre eigenen Server beschränkt. Erfordert das Members-Intent."
            ),
            "allowlist": "Owner plus die per `[p]webcore allow` freigegebenen User (volle Sicht).",
        }[mode]
        await ctx.send(f"Zugriffsmodus: **{mode}**. {hint}")

    @webcore.command(name="allow")
    async def webcore_allow(self, ctx: commands.Context, user: discord.User):
        """User für das Dashboard freigeben (volle Sicht)."""
        async with self.config.allowed_users() as users:
            if user.id not in users:
                users.append(user.id)
        await ctx.send(f"{user} darf das Dashboard jetzt mit voller Sicht nutzen.")

    @webcore.command(name="deny")
    async def webcore_deny(self, ctx: commands.Context, user: discord.User):
        """Freigabe für einen User entfernen."""
        async with self.config.allowed_users() as users:
            if user.id in users:
                users.remove(user.id)
        await ctx.send(f"{user} wurde aus der Freigabeliste entfernt.")

    @webcore.command(name="roleperm")
    @commands.guild_only()
    async def webcore_roleperm(self, ctx: commands.Context, role: discord.Role, seite: str, stufe: str):
        """Dashboard-Recht einer Rolle setzen: <rolle> <seite|alle> <none|view|operate|edit>.

        Stufen: none (kein Zugriff), view/ansehen, operate/bedienen (Tagesgeschäft, keine
        Einstellungen), edit/bearbeiten (alles).
        Beispiel: [p]webcore roleperm @Support tickets bedienen
        Seiten-Namen = Teil der URL (/cogs/<seite>), z. B. tickets, poll, guard.
        """
        if not acl.is_level_name(stufe):
            return await ctx.send("Stufe muss `none`, `view`, `operate` oder `edit` sein "
                                  "(deutsch: `ansehen`, `bedienen`, `bearbeiten`).")
        level = acl.parse_level(stufe)
        if role.is_default():
            return await ctx.send("@everyone kann keine Dashboard-Rechte bekommen.")
        seite = seite.lower()
        slugs = list(self.pages) if seite in ("alle", "all", "*") else [seite]
        unknown = [s for s in slugs if s not in self.pages]
        if unknown:
            return await ctx.send(
                f"Unbekannte Seite `{unknown[0]}`. Verfügbar: {', '.join(sorted(self.pages)) or '—'}"
            )
        async with self.config.role_perms() as role_perms:
            for slug in slugs:
                acl.set_role_level(role_perms, ctx.guild.id, role.id, slug, level)
        msg = f"{role.name}: {', '.join(slugs)} → {acl.LEVEL_LABEL[level]}"
        await self._audit(None, self._cmd_user(ctx), page="access", guild_id=ctx.guild.id,
                          action="roleperm (Befehl)", result=msg, ok=True)
        hint = ""
        if level == acl.OPERATE:
            no_op = [s for s in slugs if not self.pages[s].supports_operate]
            if no_op:
                hint = (f"\nHinweis: {', '.join(no_op)} hat kein Tagesgeschäft – „Bedienen“ wirkt dort wie "
                        "„Ansehen“.")
        await ctx.send(
            f"{role.name}: {', '.join(slugs)} → **{acl.LEVEL_LABEL[level]}**.{hint}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @webcore.command(name="roletemplate")
    @commands.guild_only()
    async def webcore_roletemplate(self, ctx: commands.Context, role: discord.Role, *, vorlage: str):
        """Rollen-Vorlage auf eine Rolle anwenden: <rolle> <vorlage>.

        Vorlagen: Nur ansehen, Bedienen, Bearbeiten, Support, Moderator, Eventleitung, Admin.
        Setzt die Stufen aller geladenen Seiten laut Vorlage (andere Einträge bleiben).
        Beispiel: [p]webcore roletemplate @Support support
        """
        tkey = acl.resolve_template(vorlage)
        if tkey is None:
            names = ", ".join(f"`{t['label']}`" for t in acl.ROLE_TEMPLATES.values())
            return await ctx.send(f"Unbekannte Vorlage. Verfügbar: {names}.")
        if role.is_default():
            return await ctx.send("@everyone kann keine Dashboard-Rechte bekommen.")
        if not self.pages:
            return await ctx.send("Es sind keine Dashboard-Seiten geladen.")
        async with self.config.role_perms() as role_perms:
            gperms = role_perms.setdefault(str(ctx.guild.id), {})
            entry = acl.apply_template(gperms.get(str(role.id)), tkey, self.pages)
            if entry:
                gperms[str(role.id)] = entry
            else:
                gperms.pop(str(role.id), None)
            if not gperms:
                role_perms.pop(str(ctx.guild.id), None)
        label = acl.ROLE_TEMPLATES[tkey]["label"]
        await self._audit(None, self._cmd_user(ctx), page="access", guild_id=ctx.guild.id,
                          action="roletemplate (Befehl)", result=f"Vorlage {label} auf {role.name}", ok=True)
        parts = [f"{slug}={acl.LEVEL_LABEL[acl.parse_level(v)].lower()}"
                 for slug, v in sorted(entry.items()) if slug in self.pages]
        await ctx.send(
            f"Vorlage **{label}** auf {role.name} angewendet: {', '.join(parts) or 'keine Rechte'}."[:1990],
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @webcore.command(name="roles")
    @commands.guild_only()
    async def webcore_roles(self, ctx: commands.Context):
        """Zeigt die Dashboard-Rechte der Rollen dieses Servers."""
        gperms = acl.guild_role_perms(await self.config.role_perms(), ctx.guild.id)
        if not gperms:
            return await ctx.send(
                "Auf diesem Server haben noch keine Rollen Dashboard-Rechte. "
                "Einrichten im Dashboard unter **Zugriff & Rollen** oder mit "
                f"`{ctx.clean_prefix}webcore roleperm <rolle> <seite|alle> <view|operate|edit>` bzw. "
                f"`{ctx.clean_prefix}webcore roletemplate <rolle> <vorlage>`."
            )
        lines = []
        for rid, entry in gperms.items():
            role = ctx.guild.get_role(int(rid)) if str(rid).isdigit() else None
            name = role.name if role else f"gelöschte Rolle ({rid})"
            parts = [f"{slug}={acl.LEVEL_LABEL[acl.parse_level(v)].lower()}" for slug, v in sorted(entry.items())]
            lines.append(f"{name}: {', '.join(parts) or '—'}")
        await ctx.send(box("\n".join(lines)[:1900], lang="yaml"))

    @staticmethod
    def _cmd_user(ctx) -> dict:
        a = ctx.author
        avatar = getattr(getattr(a, "display_avatar", None), "url", None)
        return {"id": a.id, "name": getattr(a, "display_name", None) or str(a),
                "avatar": str(avatar) if avatar else None}

    @webcore.command(name="portal")
    @commands.guild_only()
    async def webcore_portal(self, ctx: commands.Context, schalter: str):
        """„Mein Bereich“ (Mitglieder-Bereich) für diesen Server ein-/ausschalten: on | off.

        Ist er an, dürfen sich alle Mitglieder dieses Servers im Dashboard anmelden und sehen
        ausschließlich die Mitglieder-Seiten („Mein Bereich“) – keine Team-Seiten.
        """
        schalter = schalter.lower()
        if schalter not in ("on", "off", "an", "aus"):
            return await ctx.send("Bitte `on` oder `off` angeben.")
        enabled = schalter in ("on", "an")
        await self._set_portal(ctx.guild.id, enabled)
        msg = f"Mein Bereich {'eingeschaltet' if enabled else 'ausgeschaltet'}"
        await self._audit(None, self._cmd_user(ctx), page="access", guild_id=ctx.guild.id,
                          action="portal (Befehl)", result=msg, ok=True)
        if enabled:
            names = ", ".join(sorted(p.name for p in self.member_pages.values())) or "noch keine – Module können welche anbieten"
            await ctx.send(
                f"✅ **Mein Bereich** ist auf diesem Server an. Alle Mitglieder können sich jetzt im Dashboard "
                f"anmelden und sehen nur ihre Mitglieder-Seiten (aktuell: {names}).",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await ctx.send("**Mein Bereich** ist auf diesem Server aus. Reine Mitglieder haben keinen Dashboard-Zugang mehr.")

    @webcore.command(name="auditchannel")
    @commands.guild_only()
    async def webcore_auditchannel(self, ctx: commands.Context, kanal: discord.TextChannel = None):
        """Audit-Log dieses Servers zusätzlich als Embed in einen Kanal posten (ohne Kanal = aus)."""
        channel = kanal
        if channel is not None and ctx.guild.get_channel(channel.id) is None:
            return await ctx.send("Der Kanal muss auf diesem Server liegen.")
        await self._set_audit_channel(ctx.guild.id, channel.id if channel else None)
        msg = f"Log-Kanal: #{channel.name}" if channel else "Log-Kanal ausgeschaltet"
        await self._audit(None, self._cmd_user(ctx), page="audit", guild_id=ctx.guild.id,
                          action="auditchannel (Befehl)", result=msg, ok=True)
        if channel:
            await ctx.send(f"Dashboard-Änderungen und abgelehnte Zugriffe dieses Servers werden jetzt in "
                           f"{channel.mention} gepostet.")
        else:
            await ctx.send("Audit-Log wird nicht mehr in einen Kanal gepostet (im Dashboard bleibt es erhalten).")

    @webcore.command(name="settings")
    async def webcore_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen (ohne Secret)."""
        d = await self.config.all()
        text = (
            f"host: {d['host']}\n"
            f"port: {d['port']}\n"
            f"client_id: {d['client_id']}\n"
            f"redirect_uri: {d['redirect_uri']}\n"
            f"client_secret: {'gesetzt' if d['client_secret'] else 'nicht gesetzt'}\n"
            f"access_mode: {d['access_mode']}\n"
            f"allowlist: {len(d['allowed_users'])} User\n"
            f"rollen-rechte: {sum(len(v) for v in (d.get('role_perms') or {}).values())} Rolle(n) auf "
            f"{len(d.get('role_perms') or {})} Server(n)\n"
            f"audit-log: {len(d.get('audit') or [])} Einträge\n"
            f"audit-kanäle: {len(d.get('audit_channels') or {})} Server\n"
            f"mein-bereich: an auf {len(d.get('member_portal') or {})} Server(n)\n"
            f"seiten: {', '.join(self.pages) or 'keine'}\n"
            f"mitglieder-seiten: {', '.join(self.member_pages) or 'keine'}\n"
            f"öffentliche api: {', '.join(self.public_apis) or 'keine'}"
        )
        await ctx.send(box(text, lang="yaml"))
