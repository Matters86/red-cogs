import asyncio
import hashlib
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

try:
    import psutil
except Exception:  # psutil ist optional
    psutil = None

log = logging.getLogger("red.red-cogs.webcore")

DISCORD_API = "https://discord.com/api/v10"
DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN = f"{DISCORD_API}/oauth2/token"

try:
    import redbot
    RED_VERSION = getattr(redbot, "__version__", "?")
except Exception:
    RED_VERSION = "?"
DPY_VERSION = discord.__version__
PY_VERSION = platform.python_version()


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
        )
        self.pages: dict[str, DashboardPage] = {}
        self.app: web.Application | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None

        self.recent: collections.deque = collections.deque(maxlen=12)
        self._loaded_at = datetime.now(timezone.utc)
        self._process = None

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

    async def _start_webserver(self):
        data = await self.config.all()

        secret_key = data["secret_key"]
        if not secret_key:
            secret_key = secrets.token_hex(32)
            await self.config.secret_key.set(secret_key)
        fernet_key = hashlib.sha256(secret_key.encode()).digest()  # 32 Bytes

        app = web.Application()
        session_setup(app, EncryptedCookieStorage(fernet_key, cookie_name="WEBCORE_SESSION"))
        aiohttp_jinja2.setup(
            app,
            loader=jinja2.FileSystemLoader(str(Path(__file__).parent / "templates")),
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
                web.get("/api/overview", self.handle_overview_api),
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
        return {"id": int(uid), "name": session.get("user_name", "Unbekannt")}

    async def _is_authorized(self, user) -> bool:
        """Darf dieser User das Dashboard überhaupt betreten?"""
        if user is None:
            return False
        uid = user["id"]
        if uid in self.bot.owner_ids:
            return True
        data = await self.config.all()
        if uid in data["allowed_users"]:
            return True
        if data["access_mode"] == "admin":
            return any(
                (m := g.get_member(uid)) is not None and m.guild_permissions.administrator
                for g in self.bot.guilds
            )
        return False

    async def _has_full_scope(self, user) -> bool:
        """Volle Sicht (alle Server + Bot-Infrastruktur): nur Owner und Allowlist."""
        if user is None:
            return False
        if user["id"] in self.bot.owner_ids:
            return True
        return user["id"] in await self.config.allowed_users()

    def _admin_guilds(self, user) -> list:
        """Server, in denen der User Administrator ist (für eingeschränkte Sicht)."""
        if user is None:
            return []
        uid = user["id"]
        return [
            g for g in self.bot.guilds
            if (m := g.get_member(uid)) is not None and m.guild_permissions.administrator
        ]

    async def visible_guilds(self, request) -> list:
        """Öffentlich für Cogs: die Server, die der eingeloggte User sehen darf.

        Owner/Allowlist -> alle Server; Admin-Modus-User -> nur ihre eigenen.
        Cogs sollten ihre Server-Auswahl darauf beschränken.
        """
        user = await self._get_user(request)
        if not await self._is_authorized(user):
            return []
        if await self._has_full_scope(user):
            return list(self.bot.guilds)
        return self._admin_guilds(user)

    def _login_response(self, request):
        return aiohttp_jinja2.render_template(
            "login.html", request, {"title": "Anmeldung", "active_page": None}
        )

    async def _global_context(self, request):
        """Wird bei jedem Template-Render eingefügt (Navigation, User …)."""
        user = await self._get_user(request)
        return {
            "nav_pages": list(self.pages.values()),
            "current_user": user,
            "authorized": await self._is_authorized(user),
            "bot_name": self.bot.user.name if self.bot.user else "Red",
        }

    # ----------------------------------------------------------------- #
    #  Routen
    # ----------------------------------------------------------------- #
    @aiohttp_jinja2.template("index.html")
    async def handle_index(self, request):
        user = await self._get_user(request)
        if not await self._is_authorized(user):
            return self._login_response(request)
        ctx = await self._collect_overview(user)
        ctx["title"] = "Übersicht"
        ctx["active_page"] = "home"
        return ctx

    async def handle_overview_api(self, request):
        """Live-Kennzahlen als JSON (für die automatische Aktualisierung)."""
        user = await self._get_user(request)
        if not await self._is_authorized(user):
            return web.json_response({"error": "unauthorized"}, status=403)
        return web.json_response(await self._collect_overview(user))

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

    async def _collect_overview(self, user) -> dict:
        bot = self.bot
        full = await self._has_full_scope(user)
        guilds = list(bot.guilds) if full else self._admin_guilds(user)
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
        if not (data["client_id"] and data["client_secret"] and data["redirect_uri"]):
            return web.Response(
                text="OAuth2 ist noch nicht konfiguriert. Bot-Owner: bitte `[p]webcore oauth` ausführen.",
                content_type="text/plain",
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
        }
        raise web.HTTPFound(f"{DISCORD_AUTHORIZE}?{urlencode(params)}")

    async def handle_callback(self, request):
        data = await self.config.all()
        session = await get_session(request)
        code = request.query.get("code")
        state = request.query.get("state")
        if not code or state != session.get("oauth_state"):
            return web.Response(text="Ungültiger OAuth2-Callback (State stimmt nicht).", status=400)

        token_payload = {
            "client_id": str(data["client_id"]),
            "client_secret": data["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": data["redirect_uri"],
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with aiohttp.ClientSession() as cs:
            async with cs.post(DISCORD_TOKEN, data=token_payload, headers=headers) as resp:
                if resp.status != 200:
                    return web.Response(text="Token-Austausch fehlgeschlagen.", status=400)
                token = await resp.json()
            async with cs.get(
                f"{DISCORD_API}/users/@me",
                headers={"Authorization": f"Bearer {token['access_token']}"},
            ) as resp:
                if resp.status != 200:
                    return web.Response(text="Konnte Discord-Profil nicht laden.", status=400)
                me = await resp.json()

        session["user_id"] = str(me["id"])
        session["user_name"] = me.get("global_name") or me.get("username", "Unbekannt")
        raise web.HTTPFound("/")

    async def handle_logout(self, request):
        session = await get_session(request)
        session.invalidate()
        raise web.HTTPFound("/login")

    async def handle_cog_page(self, request):
        user = await self._get_user(request)
        if not await self._is_authorized(user):
            return self._login_response(request)

        slug = request.match_info["slug"]
        page = self.pages.get(slug)
        if page is None:
            return aiohttp_jinja2.render_template(
                "error.html",
                request,
                {"title": "Nicht gefunden", "message": f"Keine Seite für '{slug}'.", "active_page": None},
                status=404,
            )

        # CSRF-Token pro Sitzung sicherstellen und dem Handler bereitstellen.
        session = await get_session(request)
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token

        # Schreibende Anfragen (Formulare) zentral gegen CSRF absichern.
        if request.method == "POST":
            form = await request.post()
            if form.get("csrf_token") != token:
                return aiohttp_jinja2.render_template(
                    "error.html",
                    request,
                    {
                        "title": "Abgelehnt",
                        "message": "Ungültiges oder fehlendes CSRF-Token. Bitte Seite neu laden und erneut absenden.",
                        "active_page": slug,
                    },
                    status=400,
                )

        request["webcore_csrf"] = token

        try:
            result = await page.handler(request)
        except web.HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Fehler in Dashboard-Seite %s", slug)
            return aiohttp_jinja2.render_template(
                "error.html",
                request,
                {"title": "Fehler", "message": str(exc), "active_page": slug},
                status=500,
            )

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
            {
                "title": result.get("title", page.name),
                "content": result.get("content", ""),
                "active_page": slug,
            },
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
        await ctx.send("OAuth2-Daten gespeichert. Übernehmen mit `[p]reload webcore`.")

    @webcore.command(name="port")
    async def webcore_port(self, ctx: commands.Context, port: int):
        """Webserver-Port setzen (Standard 42100)."""
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
            "owner": "Nur Bot-Owner und Co-Owner.",
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
            f"seiten: {', '.join(self.pages) or 'keine'}"
        )
        await ctx.send(box(text, lang="yaml"))
