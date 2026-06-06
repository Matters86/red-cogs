from __future__ import annotations

import asyncio
import logging
import time

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.sticky")

# Name des vom Bot erzeugten Webhooks (Webhook-Modus). Pro Kanal genau einer.
WEBHOOK_NAME = "Sticky"
# Standardfarbe für Embeds (Theme-Akzent).
DEFAULT_COLOR = 0x3DDC97
# Grenzen für den Cooldown (Sekunden).
COOLDOWN_MIN = 0
COOLDOWN_MAX = 3600

# Vorlage eines Sticky-Datensatzes (pro Kanal in Config gespeichert).
STICKY_DEFAULT = {
    "enabled": True,
    "mode": "text",           # "text" | "embed"
    "text": "",               # Text-Inhalt bzw. Embed-Beschreibung
    "embed_title": "",
    "embed_color": "#3ddc97",
    "embed_image": "",
    "embed_footer": "",
    "webhook": False,         # via Webhook posten (eigener Name/Avatar)?
    "webhook_name": "",
    "webhook_avatar": "",
    "message_id": None,       # ID der zuletzt geposteten Nachricht
    "webhook_id": None,       # ID des genutzten Webhooks (Webhook-Modus)
}


class Sticky(commands.Cog):
    """Hält eine Nachricht am unteren Ende eines Kanals fest.

    Sobald jemand im Kanal schreibt, löscht der Bot seine alte Sticky und postet
    sie unten neu. Text- oder Embed-Modus, optionaler Webhook (eigener Name/
    Avatar), Platzhalter, Cooldown gegen Spam – mehrsprachig und über das
    WebCore-Dashboard konfigurierbar.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=592384710265, force_registration=True)
        self.config.register_guild(
            language="de",
            cooldown=5,          # Sekunden: frühestens so oft wird neu gepostet
            ignore_bots=True,    # Nachrichten anderer Bots lösen kein Neu-Posten aus
            stickies={},         # channel_id (str) -> Sticky-Datensatz
        )

        # Laufzeit-Status (nicht persistent).
        self._locks: dict[int, asyncio.Lock] = {}
        self._last_post: dict[int, float] = {}
        self._pending: dict[int, asyncio.Task] = {}
        self._webhook_cache: dict[int, discord.Webhook] = {}

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (1:1-Muster aus example/tickets)
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)

    async def cog_unload(self):
        for task in list(self._pending.values()):
            task.cancel()
        self._pending.clear()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="sticky",
            name="Sticky",
            icon="bi-pin-angle",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        if guild is None:
            return DEFAULT_LANGUAGE
        return await self.config.guild(guild).language()

    async def _say(self, ctx: commands.Context, key: str, **kwargs):
        lang = await self._lang(ctx.guild)
        await ctx.send(t(lang, key, **kwargs))

    def _lock_for(self, channel_id: int) -> asyncio.Lock:
        lock = self._locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[channel_id] = lock
        return lock

    @staticmethod
    def _parse_color(value) -> discord.Color:
        try:
            raw = (value or "").strip().lstrip("#")
            if not raw:
                return discord.Color(DEFAULT_COLOR)
            return discord.Color(int(raw, 16))
        except (ValueError, TypeError):
            return discord.Color(DEFAULT_COLOR)

    @staticmethod
    def _apply_placeholders(text: str, channel) -> str:
        if not text:
            return text
        guild = channel.guild
        replacements = {
            "{membercount}": str(guild.member_count or 0),
            "{servername}": guild.name,
            "{server}": guild.name,
            "{channel}": channel.mention,
            "{channelname}": channel.name,
        }
        for key, value in replacements.items():
            text = text.replace(key, value)
        return text

    def _render_sticky(self, channel, s: dict):
        """Baut (content, embed) aus einem Sticky-Datensatz."""
        text = self._apply_placeholders(s.get("text", ""), channel)
        if s.get("mode") == "embed":
            embed = discord.Embed(
                description=text or None,
                color=self._parse_color(s.get("embed_color")),
            )
            title = self._apply_placeholders(s.get("embed_title", ""), channel)
            if title:
                embed.title = title[:256]
            image = (s.get("embed_image") or "").strip()
            if image:
                embed.set_image(url=image)
            footer = self._apply_placeholders(s.get("embed_footer", ""), channel)
            if footer:
                embed.set_footer(text=footer[:2048])
            return None, embed
        return text, None

    # ----------------------------------------------------------------- #
    #  Webhook-Modus
    # ----------------------------------------------------------------- #
    async def _get_or_create_webhook(self, channel) -> discord.Webhook | None:
        """Liefert den (gecachten) Sticky-Webhook des Bots im Kanal oder legt ihn an."""
        if not isinstance(channel, discord.TextChannel):
            return None  # Threads/Voice unterstützen keine eigenen Webhooks -> Fallback
        cached = self._webhook_cache.get(channel.id)
        if cached is not None:
            return cached
        me = channel.guild.me
        if me is None or not channel.permissions_for(me).manage_webhooks:
            return None
        try:
            hooks = await channel.webhooks()
        except discord.HTTPException:
            return None
        webhook = None
        for h in hooks:
            if (
                h.user is not None
                and self.bot.user is not None
                and h.user.id == self.bot.user.id
                and h.name == WEBHOOK_NAME
            ):
                webhook = h
                break
        if webhook is None:
            try:
                webhook = await channel.create_webhook(name=WEBHOOK_NAME)
            except discord.HTTPException:
                return None
        self._webhook_cache[channel.id] = webhook
        return webhook

    # ----------------------------------------------------------------- #
    #  Posten / Neu-Posten
    # ----------------------------------------------------------------- #
    async def _repost(self, channel) -> bool:
        """Löscht die alte Sticky und postet sie unten neu. Gibt Erfolg zurück."""
        guild = channel.guild
        data = await self.config.guild(guild).stickies()
        s = data.get(str(channel.id))
        if not s or not s.get("enabled"):
            return False

        content, embed = self._render_sticky(channel, s)
        if not content and embed is None:
            return False  # nichts zu posten (sollte durch Validierung verhindert sein)

        use_webhook = bool(s.get("webhook"))
        old_message_id = s.get("message_id")
        old_webhook_id = s.get("webhook_id")
        new_message_id = None
        new_webhook_id = None

        try:
            posted_via_webhook = False
            if use_webhook:
                webhook = await self._get_or_create_webhook(channel)
                if webhook is not None:
                    new_webhook_id = webhook.id
                    # Webhook-ID früh sichern, damit on_message die gleich gepostete
                    # Sticky zuverlässig ignoriert (auch bei ignore_bots = False).
                    if str(old_webhook_id) != str(new_webhook_id):
                        async with self.config.guild(guild).stickies() as st:
                            cur = st.get(str(channel.id))
                            if cur is not None:
                                cur["webhook_id"] = str(new_webhook_id)
                    if old_message_id:
                        try:
                            await webhook.delete_message(int(old_message_id))
                        except discord.NotFound:
                            pass
                        except discord.HTTPException:
                            self._webhook_cache.pop(channel.id, None)
                    msg = await webhook.send(
                        content=content or None,
                        embed=embed,
                        username=(s.get("webhook_name") or None),
                        avatar_url=(s.get("webhook_avatar") or None),
                        wait=True,
                    )
                    new_message_id = msg.id
                    posted_via_webhook = True

            if not posted_via_webhook:
                if old_message_id:
                    try:
                        await channel.get_partial_message(int(old_message_id)).delete()
                    except discord.NotFound:
                        pass
                    except discord.HTTPException:
                        pass
                msg = await channel.send(content=content or None, embed=embed)
                new_message_id = msg.id
                new_webhook_id = None
        except discord.Forbidden:
            log.warning("Keine Rechte zum Posten der Sticky in Kanal %s.", channel.id)
            return False
        except discord.HTTPException:
            log.exception("Sticky-Repost in Kanal %s fehlgeschlagen.", channel.id)
            return False

        async with self.config.guild(guild).stickies() as stickies:
            cur = stickies.get(str(channel.id))
            if cur is not None:
                cur["message_id"] = str(new_message_id) if new_message_id else None
                cur["webhook_id"] = str(new_webhook_id) if new_webhook_id else None
        return True

    async def post_now(self, channel) -> bool:
        """Sofortiges Neu-Posten (ohne Cooldown). Vom Dashboard/Befehl genutzt."""
        async with self._lock_for(channel.id):
            ok = await self._repost(channel)
            self._last_post[channel.id] = time.monotonic()
        return ok

    async def delete_current(self, channel) -> None:
        """Löscht die aktuell gepostete Sticky-Nachricht (best effort)."""
        data = await self.config.guild(channel.guild).stickies()
        s = data.get(str(channel.id))
        if not s:
            return
        mid = s.get("message_id")
        if mid:
            try:
                if s.get("webhook") and s.get("webhook_id"):
                    webhook = await self._get_or_create_webhook(channel)
                    if webhook is not None:
                        await webhook.delete_message(int(mid))
                else:
                    await channel.get_partial_message(int(mid)).delete()
            except discord.HTTPException:
                pass
        async with self.config.guild(channel.guild).stickies() as stickies:
            cur = stickies.get(str(channel.id))
            if cur is not None:
                cur["message_id"] = None

    # ----------------------------------------------------------------- #
    #  Cooldown-gesteuertes Neu-Posten (Trailing-Debounce)
    # ----------------------------------------------------------------- #
    def _schedule_repost(self, channel, cooldown: int) -> None:
        existing = self._pending.get(channel.id)
        if existing is not None and not existing.done():
            return  # ein Neu-Posten ist bereits geplant
        now = time.monotonic()
        last = self._last_post.get(channel.id, 0.0)
        delay = max(0.0, (last + cooldown) - now)
        self._pending[channel.id] = asyncio.create_task(self._delayed_repost(channel, delay))

    async def _delayed_repost(self, channel, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            async with self._lock_for(channel.id):
                await self._repost(channel)
                self._last_post[channel.id] = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Geplantes Sticky-Neu-Posten in Kanal %s fehlgeschlagen.", channel.id)
        finally:
            self._pending.pop(channel.id, None)

    # ----------------------------------------------------------------- #
    #  Listener
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or self.bot.user is None:
            return
        # Eigene Nachrichten nie verarbeiten.
        if message.author.id == self.bot.user.id:
            return

        guild_conf = await self.config.guild(message.guild).all()
        stickies = guild_conf.get("stickies", {})
        s = stickies.get(str(message.channel.id))
        if not s or not s.get("enabled"):
            return

        # Eigenen Sticky-Webhook ignorieren (verhindert Endlosschleife).
        if message.webhook_id is not None and str(message.webhook_id) == str(s.get("webhook_id")):
            return
        # Genau die zuletzt geposteten Sticky-Nachricht ignorieren.
        if str(message.id) == str(s.get("message_id")):
            return
        # Andere Bots optional ignorieren.
        if message.author.bot and guild_conf.get("ignore_bots", True):
            return

        self._schedule_repost(message.channel, int(guild_conf.get("cooldown", 5)))

    # ----------------------------------------------------------------- #
    #  Befehle (hybrid = Text + Slash)
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="sticky")
    @commands.guild_only()
    async def sticky(self, ctx: commands.Context):
        """Sticky-Nachrichten verwalten."""

    @sticky.command(name="set")
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky_set(self, ctx: commands.Context, channel: discord.TextChannel, *, text: str):
        """Setzt eine Text-Sticky für einen Kanal."""
        text = text.strip()
        if not text:
            return await self._say(ctx, "no_text")
        async with self.config.guild(ctx.guild).stickies() as stickies:
            entry = dict(STICKY_DEFAULT)
            entry.update(stickies.get(str(channel.id), {}))
            entry.update({"enabled": True, "mode": "text", "text": text})
            stickies[str(channel.id)] = entry
        await self.post_now(channel)
        lang = await self._lang(ctx.guild)
        await ctx.send(t(lang, "set_ok", channel=channel.mention, mode=t(lang, "mode_text")))

    @sticky.command(name="embed")
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky_embed(self, ctx: commands.Context, channel: discord.TextChannel, *, text: str):
        """Setzt eine Embed-Sticky (Beschreibung). Titel/Farbe/Bild im Dashboard."""
        text = text.strip()
        if not text:
            return await self._say(ctx, "no_text")
        async with self.config.guild(ctx.guild).stickies() as stickies:
            entry = dict(STICKY_DEFAULT)
            entry.update(stickies.get(str(channel.id), {}))
            entry.update({"enabled": True, "mode": "embed", "text": text})
            stickies[str(channel.id)] = entry
        await self.post_now(channel)
        lang = await self._lang(ctx.guild)
        await ctx.send(t(lang, "set_ok", channel=channel.mention, mode=t(lang, "mode_embed")))

    @sticky.command(name="remove")
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky_remove(self, ctx: commands.Context, channel: discord.TextChannel):
        """Entfernt die Sticky eines Kanals."""
        s = (await self.config.guild(ctx.guild).stickies()).get(str(channel.id))
        if not s:
            return await self._say(ctx, "not_set", channel=channel.mention)
        await self.delete_current(channel)
        async with self.config.guild(ctx.guild).stickies() as stickies:
            stickies.pop(str(channel.id), None)
        await self._say(ctx, "removed", channel=channel.mention)

    @sticky.command(name="toggle")
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky_toggle(self, ctx: commands.Context, channel: discord.TextChannel):
        """Schaltet die Sticky eines Kanals an oder aus (ohne sie zu löschen)."""
        s = (await self.config.guild(ctx.guild).stickies()).get(str(channel.id))
        if not s:
            return await self._say(ctx, "not_set", channel=channel.mention)
        new_state = not s.get("enabled")
        async with self.config.guild(ctx.guild).stickies() as stickies:
            stickies[str(channel.id)]["enabled"] = new_state
        if new_state:
            await self.post_now(channel)
            await self._say(ctx, "toggled_on", channel=channel.mention)
        else:
            await self.delete_current(channel)
            await self._say(ctx, "toggled_off", channel=channel.mention)

    @sticky.command(name="refresh")
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky_refresh(self, ctx: commands.Context, channel: discord.TextChannel):
        """Postet die Sticky eines Kanals sofort neu (umgeht den Cooldown)."""
        s = (await self.config.guild(ctx.guild).stickies()).get(str(channel.id))
        if not s:
            return await self._say(ctx, "not_set", channel=channel.mention)
        if not s.get("enabled"):
            lang = await self._lang(ctx.guild)
            return await ctx.send(t(lang, "is_disabled", channel=channel.mention, p=ctx.clean_prefix))
        ok = await self.post_now(channel)
        if ok:
            await self._say(ctx, "refreshed", channel=channel.mention)
        else:
            await self._say(ctx, "no_perm", channel=channel.mention)

    @sticky.command(name="show")
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky_show(self, ctx: commands.Context, channel: discord.TextChannel):
        """Zeigt die Sticky-Konfiguration eines Kanals."""
        s = (await self.config.guild(ctx.guild).stickies()).get(str(channel.id))
        if not s:
            return await self._say(ctx, "not_set", channel=channel.mention)
        lang = await self._lang(ctx.guild)
        mode = t(lang, "mode_embed" if s.get("mode") == "embed" else "mode_text")
        state = t(lang, "state_on" if s.get("enabled") else "state_off")
        via = t(lang, "webhook_on" if s.get("webhook") else "webhook_off")
        lines = [
            t(lang, "show_header", channel=channel.mention),
            t(lang, "show_mode", mode=mode),
            t(lang, "show_state", state=state),
            t(lang, "show_webhook", via=via),
            t(lang, "show_text", text=(s.get("text") or "—")),
        ]
        await ctx.send("\n".join(lines))

    @sticky.command(name="list")
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky_list(self, ctx: commands.Context):
        """Listet alle Stickies dieses Servers auf."""
        stickies = await self.config.guild(ctx.guild).stickies()
        lang = await self._lang(ctx.guild)
        if not stickies:
            return await ctx.send(t(lang, "list_empty"))
        rows = [t(lang, "list_header")]
        for cid, s in stickies.items():
            ch = ctx.guild.get_channel(int(cid)) if str(cid).isdigit() else None
            ch_name = ch.mention if ch else f"`{cid}` (gelöscht)"
            mode = t(lang, "mode_embed" if s.get("mode") == "embed" else "mode_text")
            state = t(lang, "state_on" if s.get("enabled") else "state_off")
            via = t(lang, "webhook_on" if s.get("webhook") else "webhook_off")
            rows.append(t(lang, "list_row", channel=ch_name, mode=mode, state=state, via=via))
        await ctx.send("\n".join(rows))

    # ---- Einstellungen (Admin) ---- #
    @sticky.command(name="cooldown")
    @commands.admin_or_permissions(manage_guild=True)
    async def sticky_cooldown(self, ctx: commands.Context, seconds: int):
        """Setzt den Cooldown (Sek.), frühestens so oft wird neu gepostet."""
        if seconds < COOLDOWN_MIN or seconds > COOLDOWN_MAX:
            return await self._say(ctx, "cooldown_bad")
        await self.config.guild(ctx.guild).cooldown.set(seconds)
        await self._say(ctx, "cooldown_set", sec=seconds)

    @sticky.command(name="ignorebots")
    @commands.admin_or_permissions(manage_guild=True)
    async def sticky_ignorebots(self, ctx: commands.Context, value: bool):
        """Sollen Nachrichten anderer Bots ein Neu-Posten auslösen?"""
        await self.config.guild(ctx.guild).ignore_bots.set(value)
        await self._say(ctx, "ignorebots_on" if value else "ignorebots_off")

    @sticky.command(name="language")
    @commands.admin_or_permissions(manage_guild=True)
    async def sticky_language(self, ctx: commands.Context, code: str):
        """Setzt die Sprache der Bot-Antworten (de/en)."""
        code = code.lower()
        if code not in LANGUAGES:
            langs = ", ".join(f"`{c}`" for c in LANGUAGES)
            return await self._say(ctx, "lang_unknown", code=code, langs=langs)
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))

    @sticky.command(name="settings")
    @commands.admin_or_permissions(manage_guild=True)
    async def sticky_settings(self, ctx: commands.Context):
        """Zeigt die aktuellen Server-Einstellungen."""
        conf = await self.config.guild(ctx.guild).all()
        lang = conf["language"]
        state = t(lang, "yes" if conf["ignore_bots"] else "no")
        lines = [
            t(lang, "settings_header"),
            t(lang, "settings_lang", lang=LANGUAGES.get(lang, lang)),
            t(lang, "settings_cooldown", sec=conf["cooldown"]),
            t(lang, "settings_ignorebots", state=state),
        ]
        await ctx.send("\n".join(lines))
