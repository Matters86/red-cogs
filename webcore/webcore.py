import hashlib
import inspect
import logging
import secrets
import socket
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
from . import ui as _ui
from .admin_pages import render_access, render_audit

try:
    import psutil
except Exception:  # psutil ist optional
    psutil = None

log = logging.getLogger("red.red-cogs.webcore")

DISCORD_API = "https://discord.com/api/v10"
DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN = f"{DISCORD_API}/oauth2/token"
# Login-Sitzung läuft nach 7 Tagen ab (serverseitig geprüft, Fernet-TTL). Vorher galt
# das verschlüsselte Cookie unbegrenzt – ein einmal abgegriffenes Cookie für immer.
SESSION_MAX_AGE = 7 * 86400
# Cache-Buster für /static/webcore.css (bei Theme-Änderungen erhöhen).
ASSET_VERSION = "5"
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


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fmt(n: int) -> str:
    """Tausendertrennung im deutschen Format (24500 -> 24.500)."""
    return f"{n:,}".replace(",", ".")


class DashboardPage:
    """Eine vom Cog registrierte Dashboard-Seite."""

    def __init__(self, owner, slug, name, handler, icon="bi-grid"):
        self.owner = owner
        self.slug = slug
        self.name = name
        self.handler = handler
        self.icon = icon


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
        )
        self.pages: dict[str, DashboardPage] = {}
        # UI-Baukasten für Cog-Seiten: ``request.app["webcore"].ui`` (siehe ui.py)
        self.ui = _ui
        self.app: web.Application | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None

        self.recent: collections.deque = collections.deque(maxlen=12)
        self._loaded_at = datetime.now(timezone.utc)
        self._process = None
        # Kurzlebiger Cache für fetch_member-Fallback (admin-Modus ohne Member-Cache):
        # (guild_id, user_id) -> (ablauf_ts, member_or_none). Verhindert fetch-Stürme.
        self._member_cache: dict[tuple[int, int], tuple[float, object]] = {}

    # ----------------------------------------------------------------- #
    #  Öffentliche API für andere Cogs
    # ----------------------------------------------------------------- #
    def register_page(self, owner, slug: str, name: str, handler, icon: str = "bi-grid"):
        """Fügt eine Dashboard-Seite hinzu.

        owner   : der aufrufende Cog (für sauberes Entfernen beim Entladen)
        slug    : URL-Teil, erreichbar unter /cogs/<slug>
        name    : Anzeigename in der Navigation
        handler : async def handler(request) -> {"title": str, "content": html_str}
        icon    : Bootstrap-Icon-Klasse, z. B. "bi-stars"
        """
        self.pages[slug] = DashboardPage(owner, slug, name, handler, icon)
        log.info("Dashboard-Seite registriert: %s (von %s)", slug, owner.qualified_name)

    def unregister_owner(self, owner):
        """Entfernt alle Seiten eines Cogs (im cog_unload aufrufen)."""
        for slug in [s for s, p in self.pages.items() if p.owner is owner]:
            del self.pages[slug]

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
        await self._start_webserver()

    async def cog_unload(self):
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
                web.get("/api/overview", self.handle_overview_api),
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
        self._member_cache[key] = (now + 300, member)
        return member

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
          mindestens ``Ansehen`` hat – bei POST-Anfragen mindestens ``Bearbeiten``.
          Dadurch lehnen alle Cogs, die ihre Ziel-Guild gegen diese Liste prüfen,
          Speichern ohne Bearbeiten-Recht automatisch ab.
        """
        user = await self._get_user(request)
        amap = await self._access_map(user, request)
        if amap is None:
            return list(self.bot.guilds) if user is not None else []
        if not amap:
            return []
        slug = request.match_info.get("slug") if request.match_info else None
        if min_level is None:
            min_level = acl.EDIT if request.method == "POST" else acl.VIEW
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
        """Öffentlich für Cogs: Stufe (0/1/2) des Users für die aktuelle Seite in ``guild``."""
        user = await self._get_user(request)
        amap = await self._access_map(user, request)
        if amap is None:
            return acl.EDIT if user is not None else acl.NONE
        slug = request.match_info.get("slug") if request.match_info else None
        return (amap.get(guild.id) or {}).get(slug, acl.NONE)

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
        user = await self._get_user(request)
        amap = await self._access_map(user, request) if user else {}
        full = amap is None
        authorized = user is not None and (full or bool(amap))
        nav = []
        for p in sorted(self.pages.values(), key=lambda x: x.name.lower()):
            if full:
                nav.append({"slug": p.slug, "name": p.name, "icon": p.icon, "readonly": False})
                continue
            levels = [lv.get(p.slug, acl.NONE) for lv in (amap or {}).values()]
            best = max(levels) if levels else acl.NONE
            if best >= acl.VIEW:
                nav.append({"slug": p.slug, "name": p.name, "icon": p.icon, "readonly": best < acl.EDIT})
        label, cls = self._role_label(user, full, amap)
        return {
            "nav_pages": nav,
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
            "switcher_guild_name": "",
        }

    @staticmethod
    def _page_ctx(request, **extra) -> dict:
        ctx = {
            "switcher": request.get("wc_switcher"),
            "readonly": bool(request.get("webcore_readonly")),
            "switcher_guild_name": request.get("wc_guild_name", ""),
        }
        ctx.update(extra)
        return ctx

    async def _audit(self, request, user, *, page, guild_id, action, result, ok):
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
        try:
            async with self.config.audit() as entries:
                acl.append_audit(entries, entry)
        except Exception:  # noqa: BLE001 – Protokoll darf nie die Aktion scheitern lassen
            log.exception("Audit-Eintrag konnte nicht gespeichert werden")

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
    async def _deny(self, request, user):
        """Nicht angemeldet -> Login; angemeldet ohne Rechte -> "Kein Zugriff"."""
        if user is None:
            return self._login_response(request)
        return self._login_response(request, state="noaccess", status=403)

    @aiohttp_jinja2.template("index.html")
    async def handle_index(self, request):
        user = await self._get_user(request)
        if not await self._is_authorized(user, request):
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

    def _error_page(self, request, title, message, *, status, active=None, icon=None):
        return aiohttp_jinja2.render_template(
            "error.html", request,
            {"title": title, "message": message, "active_page": active, "icon": icon},
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
            # Zentrale Durchsetzung: Speichern nur mit "Bearbeiten" für den Ziel-Server.
            edit_ids = {g.id for g in await self.visible_guilds(request, min_level=acl.EDIT)}
            if not full and (not edit_ids or (gid is not None and gid not in edit_ids)):
                await self._audit(request, user, page=slug, guild_id=gid, action=action,
                                  result="Keine Bearbeitungsrechte", ok=False)
                back = f"/cogs/{slug}" + (f"?guild={gid}&" if gid else "?")
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
            request["webcore_readonly"] = level < acl.EDIT
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
            msg = "Gespeichert"
            async with self.config.role_perms() as role_perms:
                gperms = role_perms.setdefault(str(guild.id), {})
                if action == "add_role":
                    rid = form.get("role_id")
                    role = guild.get_role(int(rid)) if rid and rid.isdigit() else None
                    if role is None or role.is_default():
                        msg = "Rolle nicht gefunden"
                    else:
                        lvl = acl.parse_level(_int(form.get("default"), 1)) or acl.VIEW
                        gperms[str(role.id)] = {slug: acl.NAME_BY_LEVEL[lvl] for slug in self.pages}
                        msg = f"Rolle {role.name} hinzugefügt"
                elif action == "matrix":
                    remove = form.get("remove")
                    for rid in form.getall("roles", []):
                        if not str(rid).isdigit():
                            continue
                        if remove and rid == remove:
                            gperms.pop(rid, None)
                            continue
                        entry = {}
                        for slug in self.pages:
                            lvl = acl.parse_level(_int(form.get(f"p:{rid}:{slug}"), 0))
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
            await self._audit(request, user, page="access", guild_id=guild.id, action=action, result=msg,
                              ok=msg not in ("Rolle nicht gefunden",))
            from urllib.parse import quote_plus
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
        )
        return aiohttp_jinja2.render_template(
            "page.html", request,
            self._page_ctx(request, title="Zugriff & Rollen", content=content, active_page="access"),
        )

    async def handle_audit(self, request):
        user, denied = await self._require_owner_page(request)
        if denied is not None:
            return denied
        entries = await self.config.audit()
        page_names = {p.slug: p.name for p in self.pages.values()}
        page_names["access"] = "Zugriff & Rollen"
        guild_names = {}
        for e in entries:
            gid = e.get("guild_id")
            if gid:
                g = self.bot.get_guild(int(gid))
                guild_names[str(gid)] = g.name if g else (e.get("guild_name") or str(gid))
        content = render_audit(entries, page_names=page_names, guild_names=guild_names)
        return aiohttp_jinja2.render_template(
            "page.html", request, {"title": "Audit-Log", "content": content, "active_page": "audit"}
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
        """Dashboard-Recht einer Rolle setzen: <rolle> <seite|alle> <none|view|edit>.

        Beispiel: [p]webcore roleperm @Support tickets edit
        Seiten-Namen = Teil der URL (/cogs/<seite>), z. B. tickets, poll, guard.
        """
        level = acl.parse_level(stufe)
        if stufe.lower() not in ("none", "view", "edit"):
            return await ctx.send("Stufe muss `none`, `view` oder `edit` sein.")
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
        await ctx.send(
            f"{role.name}: {', '.join(slugs)} → **{acl.LEVEL_LABEL[level]}**.",
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
                f"`{ctx.clean_prefix}webcore roleperm <rolle> <seite|alle> <view|edit>`."
            )
        lines = []
        for rid, entry in gperms.items():
            role = ctx.guild.get_role(int(rid)) if str(rid).isdigit() else None
            name = role.name if role else f"gelöschte Rolle ({rid})"
            parts = [f"{slug}={'✏️' if acl.parse_level(v) == acl.EDIT else '👁'}" for slug, v in sorted(entry.items())]
            lines.append(f"{name}: {', '.join(parts) or '—'}")
        await ctx.send(box("\n".join(lines)[:1900], lang="yaml"))

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
            f"seiten: {', '.join(self.pages) or 'keine'}"
        )
        await ctx.send(box(text, lang="yaml"))
