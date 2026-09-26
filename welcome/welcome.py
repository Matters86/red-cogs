"""Welcome – Willkommens-/Abschiedsnachrichten, Willkommens-DM und Willkommensbild.

* Willkommen beim Beitritt, optional Abschied beim Verlassen (je eigener Kanal),
  jeweils als Text oder Embed (Titel, Text, Farbe, Bild-URL).
* Platzhalter ``{user}`` (Erwähnung), ``{name}``, ``{server}``, ``{count}``, ``{created}``.
* Optionales Willkommensbild (Pillow, ``card.py``): Banner mit rundem Avatar, Name,
  „Mitglied #N“, Hintergrundfarbe oder Bild-URL – gerendert per ``asyncio.to_thread``.
* Optionale DM an neue Mitglieder (geschlossene DMs werden still ignoriert).
* Bots ignorieren (Schalter), Pings nur für das neue Mitglied (``allowed_mentions``).
* Dashboard-Seite „Willkommen“ (``dashboard.py``) mit Live-Vorschau des Bildes.
"""

from __future__ import annotations

import asyncio
import collections
import io
import ipaddress
import logging
import re
import socket
import time
from datetime import datetime, timezone
from typing import Literal, Optional
from urllib.parse import urljoin, urlsplit

import aiohttp
import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from . import card as cardmod
from .dashboard import dashboard_handler
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.welcome")

KINDS = ("welcome", "leave", "dm")
MODES = ("text", "embed")
MAX_TEXT = 2000           # passt als normale Nachricht (Limit 2000) und als Embed-Beschreibung
MAX_TITLE = 256
MAX_URL = 500
MAX_HEADLINE = 40
CARD_FILENAME = "welcome.png"

AVATAR_TIMEOUT = 8        # Sekunden
AVATAR_MAX_BYTES = 4 * 1024 * 1024
AVATAR_CACHE = 64
AVATAR_TTL = 600
BG_TIMEOUT = 10
BG_TTL = 3600             # erfolgreich geladene Hintergründe 1 h zwischenspeichern
BG_ERR_TTL = 600          # Fehler 10 min merken (kein erneuter Download bei jedem Beitritt)
BG_CACHE = 16
BG_REDIRECTS = 3

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_PH_RE = re.compile(r"\{(user|name|server|count|created)\}")

DEFAULTS = {
    "welcome": {"color": "#3ddc97"},
    "leave": {"color": "#f0506e"},
    "dm": {"color": "#3ddc97"},
}


def valid_color(value) -> Optional[str]:
    v = str(value or "").strip()
    if v and not v.startswith("#"):
        v = "#" + v
    return v.lower() if HEX_RE.match(v) else None


def valid_url(value) -> Optional[str]:
    """``https://``-Adresse (max. ``MAX_URL`` Zeichen) oder ``None``."""
    v = str(value or "").strip()
    if not v or len(v) > MAX_URL or any(c.isspace() for c in v):
        return None
    parts = urlsplit(v)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return v


def fill_placeholders(text: str, values: dict) -> str:
    """Ersetzt NUR die bekannten Platzhalter – unbekannte ``{…}`` bleiben stehen (kein ``str.format``)."""
    return _PH_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), str(text or ""))


def account_age(created_at, lang: str, now: datetime | None = None) -> str:
    if created_at is None:
        return t(lang, "none")
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    secs = max(0, int((now - created_at).total_seconds()))
    days = secs // 86400
    for size, one, many in ((365, "age_year", "age_years"), (30, "age_month", "age_months"), (1, "age_day", "age_days")):
        n = days // size
        if n >= 1:
            return t(lang, one) if n == 1 else t(lang, many, n=n)
    hours = secs // 3600
    if hours >= 1:
        return t(lang, "age_hour") if hours == 1 else t(lang, "age_hours", n=hours)
    return t(lang, "age_new")


class Welcome(commands.Cog):
    """Willkommens- und Abschiedsnachrichten, Willkommens-DM und Willkommensbild."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=730418295561, force_registration=True)
        self.config.register_guild(
            language="de",
            ignore_bots=True,
            ping_user=True,            # neues Mitglied bei der Willkommensnachricht anpingen
            # Willkommen
            welcome_enabled=False,
            welcome_channel=None,
            welcome_mode="text",       # text | embed
            welcome_text="",           # leer = Standardtext
            welcome_title="",
            welcome_color=DEFAULTS["welcome"]["color"],
            welcome_image="",
            # Abschied
            leave_enabled=False,
            leave_channel=None,
            leave_mode="text",
            leave_text="",
            leave_title="",
            leave_color=DEFAULTS["leave"]["color"],
            leave_image="",
            # DM
            dm_enabled=False,
            dm_mode="text",
            dm_text="",
            dm_title="",
            dm_color=DEFAULTS["dm"]["color"],
            dm_image="",
            # Willkommensbild
            card_enabled=False,
            card_bg_color="#1b2a4a",
            card_accent="#3ddc97",
            card_text_color="#ffffff",
            card_bg_url="",
            card_headline="",          # leer = „WILLKOMMEN“
        )
        self._session: aiohttp.ClientSession | None = None
        self._avatar_cache: collections.OrderedDict = collections.OrderedDict()   # key -> (ts, bytes)
        self._bg_cache: collections.OrderedDict = collections.OrderedDict()       # url -> (ts, bytes|None, err)
        self._bg_locks: dict[str, asyncio.Lock] = {}

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)

    async def cog_unload(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        self._avatar_cache.clear()
        self._bg_cache.clear()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Es werden keine Nutzerdaten gespeichert – nur kurzlebige Avatar-Zwischenspeicher im RAM."""
        for key in [k for k in self._avatar_cache if k[0] == user_id]:
            self._avatar_cache.pop(key, None)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="welcome",
            name="Willkommen",
            icon="bi-door-open",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Nachrichten bauen
    # ----------------------------------------------------------------- #
    def placeholder_values(self, member, lang: str, *, count: int | None = None) -> dict:
        guild = member.guild
        name = discord.utils.escape_markdown(getattr(member, "display_name", None) or getattr(member, "name", "?"))
        return {
            "user": getattr(member, "mention", name),
            "name": name,
            "server": discord.utils.escape_markdown(guild.name),
            "count": count if count is not None else (getattr(guild, "member_count", None) or len(guild.members)),
            "created": account_age(getattr(member, "created_at", None), lang),
        }

    def build_message(self, conf: dict, kind: str, member, *, with_card: bool = False, ping: bool | None = None) -> dict:
        """Sende-Argumente (``content``/``embed``/``allowed_mentions``) für ``kind``.

        ``with_card`` bindet das Bild (Datei ``welcome.png``) im Embed ein; die Datei selbst
        hängt der Aufrufer an. Pings: nur das neue Mitglied und nur, wenn ``ping`` wahr ist.
        """
        lang = conf.get("language") or DEFAULT_LANGUAGE
        values = self.placeholder_values(member, lang)
        raw = (conf.get(f"{kind}_text") or "").strip() or t(lang, f"default_{kind}")
        text = fill_placeholders(raw, values)
        mode = conf.get(f"{kind}_mode") if conf.get(f"{kind}_mode") in MODES else "text"
        if ping is None:
            ping = kind == "welcome" and bool(conf.get("ping_user", True))
        mentions = discord.AllowedMentions(everyone=False, roles=False, replied_user=False,
                                           users=[member] if ping else False)
        out: dict = {"allowed_mentions": mentions}
        if mode == "text":
            out["content"] = text[:MAX_TEXT]
            return out
        title = fill_placeholders((conf.get(f"{kind}_title") or "").strip() or t(lang, f"default_{kind}_title"), values)
        color = valid_color(conf.get(f"{kind}_color")) or DEFAULTS[kind]["color"]
        emb = discord.Embed(title=title[:MAX_TITLE], description=text[:4096], color=int(color[1:], 16))
        avatar = getattr(getattr(member, "display_avatar", None), "url", None)
        if kind != "dm" and avatar:
            emb.set_thumbnail(url=str(avatar))
        if with_card:
            emb.set_image(url=f"attachment://{CARD_FILENAME}")
        elif valid_url(conf.get(f"{kind}_image")):
            emb.set_image(url=conf[f"{kind}_image"])
        if kind == "welcome":
            emb.set_footer(text=t(lang, "embed_footer", count=values["count"]))
        out["embed"] = emb
        if ping and kind == "welcome":
            # Erwähnungen im Embed pingen nicht – für den Ping die Erwähnung als Inhalt mitsenden.
            out["content"] = getattr(member, "mention", None)
        return out

    # ----------------------------------------------------------------- #
    #  Willkommensbild
    # ----------------------------------------------------------------- #
    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=BG_TIMEOUT))
        return self._session

    async def avatar_bytes(self, member) -> bytes | None:
        """Avatar (PNG, 256 px) mit Timeout, Größenlimit und kleinem RAM-Cache; Fehler -> ``None``."""
        asset = getattr(member, "display_avatar", None)
        if asset is None:
            return None
        try:
            if hasattr(asset, "with_static_format"):
                asset = asset.with_static_format("png").with_size(256)
        except Exception:  # noqa: BLE001 – dann eben das Original
            pass
        key = (getattr(member, "id", 0), str(getattr(asset, "key", None) or getattr(asset, "url", "")))
        hit = self._avatar_cache.get(key)
        if hit and time.monotonic() - hit[0] < AVATAR_TTL:
            self._avatar_cache.move_to_end(key)
            return hit[1]
        try:
            data = await asyncio.wait_for(asset.read(), timeout=AVATAR_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 – Timeout, HTTP, kein Avatar …
            log.debug("Avatar von %s nicht geladen: %r", getattr(member, "id", "?"), exc)
            return None
        if not data or len(data) > AVATAR_MAX_BYTES:
            return None
        self._avatar_cache[key] = (time.monotonic(), data)
        while len(self._avatar_cache) > AVATAR_CACHE:
            self._avatar_cache.popitem(last=False)
        return data

    @staticmethod
    async def _check_host(host: str) -> None:
        """Nur öffentliche Adressen laden (kein Zugriff aufs Heimnetz/NAS über die Bild-URL)."""
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except (socket.gaierror, OSError):
            raise cardmod.BackgroundError("Der Server der Bild-URL ist nicht erreichbar.") from None
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                raise cardmod.BackgroundError("Ungültige Adresse.") from None
            if not ip.is_global:
                raise cardmod.BackgroundError("Die Bild-URL zeigt auf eine interne Adresse – nicht erlaubt.")

    async def _download(self, url: str) -> bytes:
        max_bytes = cardmod.MAX_BG_BYTES
        session = self._http()
        for _ in range(BG_REDIRECTS + 1):
            if not valid_url(url):
                raise cardmod.BackgroundError("Nur https://-Adressen sind erlaubt.")
            parts = urlsplit(url)
            if parts.port not in (None, 443):
                raise cardmod.BackgroundError("Nur der Standard-Port 443 ist erlaubt.")
            await self._check_host(parts.hostname)
            try:
                async with session.get(url, allow_redirects=False,
                                       headers={"User-Agent": "Red-Welcome/1.0"}) as resp:
                    if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                        url = urljoin(url, resp.headers["Location"])
                        continue
                    if resp.status != 200:
                        raise cardmod.BackgroundError(f"Der Server antwortete mit HTTP {resp.status}.")
                    if (resp.content_length or 0) > max_bytes:
                        raise cardmod.BackgroundError(f"Das Bild ist zu groß (max. {max_bytes // (1024 * 1024)} MB).")
                    buf = bytearray()
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        buf += chunk
                        if len(buf) > max_bytes:
                            raise cardmod.BackgroundError(
                                f"Das Bild ist zu groß (max. {max_bytes // (1024 * 1024)} MB).")
                    return bytes(buf)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                raise cardmod.BackgroundError("Das Bild konnte nicht geladen werden (Zeitüberschreitung/Verbindung).") from None
        raise cardmod.BackgroundError("Zu viele Weiterleitungen.")

    async def background_bytes(self, url: str) -> bytes:
        """Hintergrund aus der Bild-URL (geprüft, auf Kartengröße gebracht, zwischengespeichert).

        Wirft ``card.BackgroundError`` mit deutscher Begründung.
        """
        now = time.monotonic()
        hit = self._bg_cache.get(url)
        if hit and now - hit[0] < (BG_TTL if hit[1] else BG_ERR_TTL):
            if hit[1] is None:
                raise cardmod.BackgroundError(hit[2])
            return hit[1]
        lock = self._bg_locks.setdefault(url, asyncio.Lock())
        async with lock:
            hit = self._bg_cache.get(url)
            if hit and time.monotonic() - hit[0] < (BG_TTL if hit[1] else BG_ERR_TTL):
                if hit[1] is None:
                    raise cardmod.BackgroundError(hit[2])
                return hit[1]
            try:
                raw = await self._download(url)
                data = await asyncio.to_thread(cardmod.prepare_background, raw)
            except cardmod.BackgroundError as exc:
                self._remember_bg(url, None, str(exc))
                raise
            self._remember_bg(url, data, "")
            return data

    def _remember_bg(self, url, data, err):
        self._bg_cache[url] = (time.monotonic(), data, err)
        self._bg_cache.move_to_end(url)
        while len(self._bg_cache) > BG_CACHE:
            old, _ = self._bg_cache.popitem(last=False)
            self._bg_locks.pop(old, None)

    async def render_card(self, member, conf: dict, *, count: int | None = None) -> tuple[bytes, str | None]:
        """PNG-Bytes des Willkommensbildes + ggf. Hinweis, warum der Hintergrund fehlt."""
        lang = conf.get("language") or DEFAULT_LANGUAGE
        guild = member.guild
        if count is None:
            count = getattr(guild, "member_count", None) or len(guild.members)
        avatar = await self.avatar_bytes(member)
        background, bg_err = None, None
        url = valid_url(conf.get("card_bg_url"))
        if url:
            try:
                background = await self.background_bytes(url)
            except cardmod.BackgroundError as exc:
                bg_err = str(exc)
        headline = (conf.get("card_headline") or "").strip() or t(lang, "card_headline")
        png = await asyncio.to_thread(
            cardmod.render_card,
            name=getattr(member, "display_name", None) or getattr(member, "name", ""),
            member_line=t(lang, "card_member", count=count),
            server=guild.name,
            headline=headline[:MAX_HEADLINE],
            avatar=avatar,
            background=background,
            color1=valid_color(conf.get("card_bg_color")) or "#1b2a4a",
            color2=valid_color(conf.get("card_accent")) or "#3ddc97",
            text_color=valid_color(conf.get("card_text_color")) or "#ffffff",
            fallback_name=t(lang, "card_fallback_name"),
        )
        return png, bg_err

    # ----------------------------------------------------------------- #
    #  Senden
    # ----------------------------------------------------------------- #
    def _resolve_channel(self, guild, channel_id):
        if not channel_id:
            return None
        ch = guild.get_channel(int(channel_id))
        return ch if isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel)) else None

    async def post(self, member, kind: str, conf: dict | None = None, *, channel=None,
                   ping: bool | None = None) -> tuple[bool, str | None]:
        """Postet Willkommen/Abschied für ``member``. Rückgabe ``(ok, fehler_key)``.

        ``channel`` überschreibt den eingestellten Kanal (Test im aktuellen Kanal).
        """
        guild = member.guild
        if conf is None:
            conf = await self.config.guild(guild).all()
        if channel is None:
            if not conf.get(f"{kind}_channel"):
                return False, "err_no_channel"
            channel = self._resolve_channel(guild, conf[f"{kind}_channel"])
            if channel is None:
                return False, "err_channel_missing"
        me = guild.me
        perms = channel.permissions_for(me) if me is not None else None
        if perms is not None and not perms.send_messages:
            return False, "err_no_send"
        embed_mode = conf.get(f"{kind}_mode") == "embed"
        if embed_mode and perms is not None and not perms.embed_links:
            return False, "err_no_embed"
        file = None
        if kind == "welcome" and conf.get("card_enabled") and (perms is None or perms.attach_files):
            try:
                png, bg_err = await self.render_card(member, conf)
                if bg_err:
                    log.warning("Welcome (%s): Hintergrundbild nicht geladen: %s", guild.id, bg_err)
                file = discord.File(io.BytesIO(png), filename=CARD_FILENAME)
            except Exception:  # noqa: BLE001 – Bild ist optional, Nachricht trotzdem senden
                log.exception("Welcome (%s): Willkommensbild fehlgeschlagen", guild.id)
        kwargs = self.build_message(conf, kind, member, with_card=file is not None and embed_mode, ping=ping)
        if file is not None:
            kwargs["file"] = file
        try:
            await channel.send(**kwargs)
        except discord.Forbidden:
            return False, "err_no_send"
        except discord.HTTPException as exc:
            log.warning("Welcome (%s): %s-Nachricht abgelehnt: %s", guild.id, kind, exc)
            return False, "err_http"
        return True, None

    async def send_dm(self, member, conf: dict | None = None) -> bool:
        """Willkommens-DM; geschlossene DMs & Co. werden still ignoriert (``False``)."""
        if conf is None:
            conf = await self.config.guild(member.guild).all()
        kwargs = self.build_message(conf, "dm", member, ping=False)
        try:
            await member.send(**kwargs)
            return True
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return False

    # ----------------------------------------------------------------- #
    #  Listener
    # ----------------------------------------------------------------- #
    async def _active_conf(self, member) -> dict | None:
        guild = getattr(member, "guild", None)
        if guild is None:
            return None
        if self.bot.user is not None and member.id == self.bot.user.id:
            return None
        try:
            if await self.bot.cog_disabled_in_guild(self, guild):
                return None
        except Exception:  # noqa: BLE001
            pass
        conf = await self.config.guild(guild).all()
        if getattr(member, "bot", False) and conf["ignore_bots"]:
            return None
        return conf

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        conf = await self._active_conf(member)
        if conf is None:
            return
        try:
            if conf["welcome_enabled"] and conf["welcome_channel"]:
                ok, err = await self.post(member, "welcome", conf)
                if not ok:
                    log.info("Welcome (%s): Willkommen nicht gesendet: %s", member.guild.id, err)
            if conf["dm_enabled"] and not getattr(member, "bot", False):
                await self.send_dm(member, conf)
        except Exception:  # noqa: BLE001 – ein Fehler darf den Listener nicht sprengen
            log.exception("Welcome (%s): Fehler beim Beitritt von %s", member.guild.id, member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        conf = await self._active_conf(member)
        if conf is None:
            return
        try:
            if conf["leave_enabled"] and conf["leave_channel"]:
                ok, err = await self.post(member, "leave", conf)
                if not ok:
                    log.info("Welcome (%s): Abschied nicht gesendet: %s", member.guild.id, err)
        except Exception:  # noqa: BLE001
            log.exception("Welcome (%s): Fehler beim Verlassen von %s", member.guild.id, member.id)

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language() if guild else DEFAULT_LANGUAGE

    async def _say(self, ctx, key, **kwargs):
        await ctx.send(t(await self._lang(ctx.guild), key, **kwargs),
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_group(name="welcomeset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def welcomeset(self, ctx: commands.Context):
        """Willkommen, Abschied, DM und Willkommensbild einstellen."""

    @welcomeset.command(name="channel")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_channel(self, ctx: commands.Context, kind: Literal["welcome", "leave"],
                         channel: Optional[discord.TextChannel] = None):
        """Kanal für Willkommen bzw. Abschied setzen (ohne Kanal = entfernen)."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).set_raw(f"{kind}_channel", value=channel.id if channel else None)
        if channel:
            await self._say(ctx, "channel_set", kind=t(lang, f"kind_{kind}"), channel=channel.mention)
        else:
            await self._say(ctx, "channel_cleared", kind=t(lang, f"kind_{kind}"))

    @welcomeset.command(name="toggle")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_toggle(self, ctx: commands.Context, kind: Literal["welcome", "leave", "dm", "card"],
                        state: Optional[bool] = None):
        """Willkommen/Abschied/DM/Bild ein- oder ausschalten (ohne Wert = umschalten)."""
        lang = await self._lang(ctx.guild)
        gconf = self.config.guild(ctx.guild)
        key = f"{kind}_enabled"
        new = (not await gconf.get_raw(key)) if state is None else bool(state)
        await gconf.set_raw(key, value=new)
        label = t(lang, f"kind_{kind}")
        if new and kind in ("welcome", "leave") and not await gconf.get_raw(f"{kind}_channel"):
            return await self._say(ctx, "enabled_nochannel", kind=label, state=t(lang, "on"),
                                   prefix=ctx.clean_prefix, arg=kind)
        await self._say(ctx, "enabled_set", kind=label, state=t(lang, "on" if new else "off"))

    @welcomeset.command(name="message")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_message(self, ctx: commands.Context, kind: Literal["welcome", "leave", "dm"], *, text: str = ""):
        """Text setzen (Platzhalter: {user} {name} {server} {count} {created}); ohne Text = Standard."""
        lang = await self._lang(ctx.guild)
        text = text.strip()
        if len(text) > MAX_TEXT:
            return await self._say(ctx, "text_too_long", max=MAX_TEXT)
        await self.config.guild(ctx.guild).set_raw(f"{kind}_text", value=text)
        await self._say(ctx, "text_set" if text else "text_reset", kind=t(lang, f"kind_{kind}"))

    @welcomeset.command(name="mode")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_mode(self, ctx: commands.Context, kind: Literal["welcome", "leave", "dm"],
                      mode: Literal["text", "embed"]):
        """Darstellung: normaler Text oder Embed."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).set_raw(f"{kind}_mode", value=mode)
        await self._say(ctx, "mode_set", kind=t(lang, f"kind_{kind}"), mode=mode)

    @welcomeset.command(name="title")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_title(self, ctx: commands.Context, kind: Literal["welcome", "leave", "dm"], *, title: str = ""):
        """Embed-Titel setzen (ohne Text = Standard)."""
        lang = await self._lang(ctx.guild)
        title = title.strip()[:MAX_TITLE]
        await self.config.guild(ctx.guild).set_raw(f"{kind}_title", value=title)
        await self._say(ctx, "title_set" if title else "title_reset", kind=t(lang, f"kind_{kind}"))

    @welcomeset.command(name="color")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_color(self, ctx: commands.Context, kind: Literal["welcome", "leave", "dm"], color: str):
        """Embed-Farbe setzen, z. B. #3ddc97."""
        lang = await self._lang(ctx.guild)
        value = valid_color(color)
        if value is None:
            return await self._say(ctx, "color_bad")
        await self.config.guild(ctx.guild).set_raw(f"{kind}_color", value=value)
        await self._say(ctx, "color_set", kind=t(lang, f"kind_{kind}"), color=value)

    @welcomeset.command(name="image")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_image(self, ctx: commands.Context, kind: Literal["welcome", "leave", "dm"], url: str = ""):
        """Bild im Embed (https-Link); ohne Link = entfernen."""
        lang = await self._lang(ctx.guild)
        if url and valid_url(url) is None:
            return await self._say(ctx, "url_bad", max=MAX_URL)
        await self.config.guild(ctx.guild).set_raw(f"{kind}_image", value=url.strip())
        await self._say(ctx, "image_set" if url else "image_reset", kind=t(lang, f"kind_{kind}"))

    @welcomeset.command(name="ping")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_ping(self, ctx: commands.Context, state: bool):
        """Neues Mitglied in der Willkommensnachricht anpingen (an/aus)."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).ping_user.set(bool(state))
        await self._say(ctx, "ping_set", state=t(lang, "on" if state else "off"))

    @welcomeset.command(name="bots")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_bots(self, ctx: commands.Context, state: bool):
        """Bots ignorieren (an/aus)."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).ignore_bots.set(bool(state))
        await self._say(ctx, "bots_set", state=t(lang, "on" if state else "off"))

    @welcomeset.command(name="language")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_language(self, ctx: commands.Context, code: str):
        """Sprache der Standardtexte und Antworten (de/en)."""
        code = code.lower().strip()
        if code not in LANGUAGES:
            return await self._say(ctx, "lang_unknown", code=code, langs=", ".join(LANGUAGES))
        await self.config.guild(ctx.guild).language.set(code)
        await self._say(ctx, "lang_set", language=LANGUAGES[code])

    @welcomeset.command(name="cardcolors")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_cardcolors(self, ctx: commands.Context, background: str, accent: str, text: str = "#ffffff"):
        """Farben des Willkommensbildes: Hintergrund, Akzent (Verlauf) und Text."""
        c1, c2, c3 = valid_color(background), valid_color(accent), valid_color(text)
        if not (c1 and c2 and c3):
            return await self._say(ctx, "color_bad")
        gconf = self.config.guild(ctx.guild)
        await gconf.card_bg_color.set(c1)
        await gconf.card_accent.set(c2)
        await gconf.card_text_color.set(c3)
        await self._say(ctx, "card_colors_set", c1=c1, c2=c2, c3=c3)

    @welcomeset.command(name="cardbackground")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_cardbg(self, ctx: commands.Context, url: str = ""):
        """Hintergrundbild des Willkommensbildes (https-Link); ohne Link = Farbverlauf."""
        if url and valid_url(url) is None:
            return await self._say(ctx, "url_bad", max=MAX_URL)
        await self.config.guild(ctx.guild).card_bg_url.set(url.strip())
        await self._say(ctx, "card_bg_set" if url else "card_bg_removed")

    @welcomeset.command(name="cardheadline")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_cardheadline(self, ctx: commands.Context, *, text: str = ""):
        """Überschrift des Willkommensbildes (ohne Text = „WILLKOMMEN“)."""
        text = text.strip()[:MAX_HEADLINE]
        await self.config.guild(ctx.guild).card_headline.set(text)
        await self._say(ctx, "card_headline_set" if text else "card_headline_reset")

    @welcomeset.command(name="test")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_test(self, ctx: commands.Context, kind: Literal["welcome", "leave", "dm"] = "welcome"):
        """Zeigt die Nachricht mit dir als Beispiel (hier im Kanal bzw. als DM an dich)."""
        lang = await self._lang(ctx.guild)
        conf = await self.config.guild(ctx.guild).all()
        member = ctx.author
        if kind == "dm":
            ok = await self.send_dm(member, conf)
            return await self._say(ctx, "test_dm_sent" if ok else "test_dm_failed")
        async with ctx.typing():
            await ctx.send(t(lang, "test_intro", kind=t(lang, f"kind_{kind}")),
                           allowed_mentions=discord.AllowedMentions.none())
            ok, err = await self.post(member, kind, conf, channel=ctx.channel, ping=False)
        if not ok:
            await self._say(ctx, "test_failed", reason=t(lang, err or "err_http"))

    @welcomeset.command(name="settings")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        lang = await self._lang(ctx.guild)
        conf = await self.config.guild(ctx.guild).all()

        def onoff(v):
            return t(lang, "on" if v else "off")

        def chan(cid):
            ch = ctx.guild.get_channel(int(cid)) if cid else None
            return ch.mention if ch else t(lang, "none")

        emb = discord.Embed(title=t(lang, "settings_title"), color=0x3DDC97)
        for kind in KINDS:
            lines = [f"**{onoff(conf[f'{kind}_enabled'])}**"]
            if kind != "dm":
                lines.append(f"{t(lang, 'settings_channel')}: {chan(conf[f'{kind}_channel'])}")
            lines.append(f"{t(lang, 'settings_mode')}: {conf[f'{kind}_mode']}")
            lines.append(f"{t(lang, 'settings_text')}: "
                         + t(lang, "settings_custom" if conf[f"{kind}_text"] else "settings_default"))
            emb.add_field(name=t(lang, f"kind_{kind}"), value="\n".join(lines)[:1024], inline=True)
        card_lines = [f"**{onoff(conf['card_enabled'])}**",
                      f"{t(lang, 'settings_card_bg')}: `{conf['card_bg_color']}` → `{conf['card_accent']}`",
                      f"{t(lang, 'settings_card_url')}: {t(lang, 'on' if conf['card_bg_url'] else 'off')}"]
        emb.add_field(name=t(lang, "kind_card"), value="\n".join(card_lines)[:1024], inline=True)
        emb.add_field(name=t(lang, "settings_general"), value=(
            f"{t(lang, 'settings_ping')}: {onoff(conf['ping_user'])}\n"
            f"{t(lang, 'settings_bots')}: {onoff(conf['ignore_bots'])}\n"
            f"{t(lang, 'settings_lang')}: {LANGUAGES.get(conf['language'], conf['language'])}"), inline=True)
        await ctx.send(embed=emb)
