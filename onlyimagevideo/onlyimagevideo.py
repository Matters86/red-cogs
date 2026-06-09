from __future__ import annotations

import logging
from typing import Union

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .detect import filename_is_media, text_has_media_link
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.onlyimagevideo")

# Kanaltypen, die als Nur-Medien-Kanal markiert werden können.
_ALLOWED_CHANNEL_TYPES = (discord.TextChannel, discord.VoiceChannel, discord.ForumChannel)
ChannelArg = Union[discord.TextChannel, discord.VoiceChannel, discord.ForumChannel]

# Nachrichtentypen, die überhaupt geprüft werden (alles andere = System/Beitritt/Pin …).
_CHECKED_TYPES = (discord.MessageType.default, discord.MessageType.reply)

NOTIFY_MIN = 2
NOTIFY_MAX = 60


class OnlyImageVideo(commands.Cog):
    """Erzwingt in ausgewählten Kanälen Beiträge mit Bild, Video oder GIF.

    Reine Textnachrichten werden gelöscht; ein kurzer, selbstlöschender Hinweis
    erklärt die Regel. Threads in einem Nur-Medien-Kanal erben die Regel.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=472619305847, force_registration=True)
        self.config.register_guild(
            language="de",
            channels=[],            # IDs der Nur-Medien-Kanäle (Threads erben)
            exempt_roles=[],         # Rollen, die von der Regel ausgenommen sind
            allow_links=True,        # Links zu Mediendateien zählen als Medium
            allow_hosts=True,        # Tenor/Giphy/… zählen als Medium
            allow_stickers=True,     # Sticker zählen als Bild
            ignore_bots=True,        # Bots/Webhooks ausnehmen
            notify=True,             # Hinweis beim Löschen senden
            notify_delete_after=6,   # Sekunden bis der Hinweis verschwindet
            messages={},             # Text-Overrides (OVERRIDABLE_KEYS)
            deleted_total=0,         # Zähler für das Dashboard
        )

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

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="onlyimagevideo",
            name="Nur Medien",
            icon="bi-card-image",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    @staticmethod
    def _is_monitored(message: discord.Message, channel_ids) -> bool:
        ids = {int(c) for c in (channel_ids or [])}
        if not ids:
            return False
        ch = message.channel
        if isinstance(ch, discord.Thread):
            return ch.parent_id in ids
        return getattr(ch, "id", None) in ids

    @staticmethod
    def _embed_has_media(message: discord.Message) -> bool:
        for e in message.embeds:
            if e.type in ("image", "gifv", "video"):
                return True
            for media in (e.image, e.thumbnail, e.video):
                if media is not None and getattr(media, "url", None):
                    return True
        return False

    def _is_allowed(self, message: discord.Message, conf: dict) -> bool:
        # Anhänge: Bild/Video über content_type, sonst über Dateiendung.
        for att in message.attachments:
            ctype = (att.content_type or "").lower()
            if ctype.startswith("image/") or ctype.startswith("video/"):
                return True
            if filename_is_media(att.filename):
                return True
        # Sticker zählen als Bild (falls aktiviert).
        if conf.get("allow_stickers") and message.stickers:
            return True
        # Bereits vorhandene Medien-Embeds (z. B. weitergeleitete Inhalte).
        if self._embed_has_media(message):
            return True
        # Medien-Links im Text.
        if text_has_media_link(
            message.content,
            allow_links=conf.get("allow_links", True),
            allow_hosts=conf.get("allow_hosts", True),
        ):
            return True
        return False

    # ----------------------------------------------------------------- #
    #  Durchsetzung
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._check(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # Nur prüfen, wenn sich der Text wirklich geändert hat – verhindert eine
        # Reaktion auf das nachträgliche Einfügen von Link-Vorschauen durch Discord.
        if before.content == after.content:
            return
        await self._check(after)

    async def _check(self, message: discord.Message):
        if message.guild is None:
            return
        if message.author.id == self.bot.user.id:
            return
        if message.type not in _CHECKED_TYPES:
            return

        conf = await self.config.guild(message.guild).all()
        channels = conf.get("channels") or []
        if not channels or not self._is_monitored(message, channels):
            return
        if conf.get("ignore_bots", True) and (message.author.bot or message.webhook_id is not None):
            return
        member = message.author
        if isinstance(member, discord.Member):
            exempt = {int(r) for r in (conf.get("exempt_roles") or [])}
            if exempt and any(r.id in exempt for r in member.roles):
                return
        if self._is_allowed(message, conf):
            return

        # Verstoß: löschen (sofern möglich), dann Hinweis + Zähler.
        try:
            await message.delete()
        except discord.Forbidden:
            log.warning(
                "Fehlende Berechtigung 'Nachrichten verwalten' in Kanal %s (Guild %s).",
                getattr(message.channel, "id", "?"), message.guild.id,
            )
            return
        except discord.NotFound:
            return
        except discord.HTTPException:
            log.exception("Nachricht konnte nicht gelöscht werden.")
            return

        await self.config.guild(message.guild).deleted_total.set(int(conf.get("deleted_total", 0)) + 1)

        if conf.get("notify", True):
            lang = conf.get("language", DEFAULT_LANGUAGE)
            overrides = conf.get("messages") or {}
            text = overrides.get("notice") or t(lang, "notice", user=message.author.mention)
            if "{user}" in text:
                text = text.format(user=message.author.mention)
            delay = int(conf.get("notify_delete_after", 6))
            try:
                await message.channel.send(
                    text,
                    delete_after=delay,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
                )
            except discord.HTTPException:
                pass

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.hybrid_group(name="oiv", aliases=["onlyimagevideo"])
    async def oiv(self, ctx: commands.Context):
        """Nur-Medien-Kanäle verwalten."""

    @oiv.command(name="add")
    async def oiv_add(self, ctx: commands.Context, channel: ChannelArg):
        """Einen Kanal als Nur-Medien-Kanal markieren."""
        lang = await self._lang(ctx.guild)
        if not isinstance(channel, _ALLOWED_CHANNEL_TYPES):
            return await ctx.send(t(lang, "channel_bad"))
        async with self.config.guild(ctx.guild).channels() as chans:
            if channel.id in chans:
                return await ctx.send(t(lang, "channel_already", channel=channel.mention))
            chans.append(channel.id)
        await ctx.send(t(lang, "channel_added", channel=channel.mention))

    @oiv.command(name="remove")
    async def oiv_remove(self, ctx: commands.Context, channel: ChannelArg):
        """Einen Kanal aus der Nur-Medien-Liste entfernen."""
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).channels() as chans:
            if channel.id not in chans:
                return await ctx.send(t(lang, "channel_not_listed", channel=channel.mention))
            chans.remove(channel.id)
        await ctx.send(t(lang, "channel_removed", channel=channel.mention))

    @oiv.command(name="list")
    async def oiv_list(self, ctx: commands.Context):
        """Alle Nur-Medien-Kanäle anzeigen."""
        lang = await self._lang(ctx.guild)
        chans = await self.config.guild(ctx.guild).channels()
        if not chans:
            return await ctx.send(t(lang, "list_empty"))
        lines = [t(lang, "list_header")]
        for cid in chans:
            ch = ctx.guild.get_channel(cid)
            label = ch.mention if ch is not None else f"`{cid}` (gelöscht?)"
            lines.append(t(lang, "list_row", channel=label))
        lines.append("")
        lines.append(t(lang, "list_note"))
        await ctx.send("\n".join(lines))

    @oiv.command(name="exemptrole")
    async def oiv_exemptrole(self, ctx: commands.Context, role: discord.Role):
        """Ausnahme-Rolle hinzufügen/entfernen (Umschalter)."""
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).exempt_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
                msg = t(lang, "role_removed", role=role.name)
            else:
                roles.append(role.id)
                msg = t(lang, "role_added", role=role.name)
        await ctx.send(msg)

    async def _toggle(self, ctx, field, key):
        lang = await self._lang(ctx.guild)
        cur = await getattr(self.config.guild(ctx.guild), field)()
        new = not cur
        await getattr(self.config.guild(ctx.guild), field).set(new)
        state = t(lang, "state_on" if new else "state_off")
        await ctx.send(t(lang, key, state=state))

    @oiv.command(name="links")
    async def oiv_links(self, ctx: commands.Context):
        """Links zu Mediendateien als Medium zählen (Umschalter)."""
        await self._toggle(ctx, "allow_links", "set_links")

    @oiv.command(name="gifhosts")
    async def oiv_gifhosts(self, ctx: commands.Context):
        """GIF-/Medien-Dienste (Tenor, Giphy …) als Medium zählen (Umschalter)."""
        await self._toggle(ctx, "allow_hosts", "set_hosts")

    @oiv.command(name="stickers")
    async def oiv_stickers(self, ctx: commands.Context):
        """Sticker als Bild zählen (Umschalter)."""
        await self._toggle(ctx, "allow_stickers", "set_stickers")

    @oiv.command(name="ignorebots")
    async def oiv_ignorebots(self, ctx: commands.Context):
        """Bots/Webhooks von der Regel ausnehmen (Umschalter)."""
        await self._toggle(ctx, "ignore_bots", "set_ignorebots")

    @oiv.command(name="notify")
    async def oiv_notify(self, ctx: commands.Context):
        """Hinweis beim Löschen senden (Umschalter)."""
        await self._toggle(ctx, "notify", "set_notify")

    @oiv.command(name="language")
    async def oiv_language(self, ctx: commands.Context, code: str):
        """Sprache setzen (de, en)."""
        code = code.lower()
        if code not in LANGUAGES:
            return await ctx.send(
                t(await self._lang(ctx.guild), "lang_unknown", code=code, langs=", ".join(LANGUAGES))
            )
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))

    @oiv.command(name="settings")
    async def oiv_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        d = await self.config.guild(ctx.guild).all()
        chan_names = []
        for cid in d["channels"]:
            ch = ctx.guild.get_channel(cid)
            chan_names.append(ch.name if ch is not None else str(cid))
        roles = ", ".join(r.name for r in ctx.guild.roles if r.id in d["exempt_roles"]) or "—"
        onoff = lambda b: "an" if b else "aus"  # noqa: E731
        text = (
            f"Sprache: {d['language']}\n"
            f"Nur-Medien-Kanäle ({len(chan_names)}): {', '.join(chan_names) or '—'}\n"
            f"Ausnahme-Rollen: {roles}\n"
            f"Medien-Links zählen: {onoff(d['allow_links'])}\n"
            f"GIF-/Medien-Dienste zählen: {onoff(d['allow_hosts'])}\n"
            f"Sticker zählen: {onoff(d['allow_stickers'])}\n"
            f"Bots/Webhooks ausgenommen: {onoff(d['ignore_bots'])}\n"
            f"Hinweis beim Löschen: {onoff(d['notify'])} ({d['notify_delete_after']}s)\n"
            f"Gelöschte Nachrichten gesamt: {d['deleted_total']}"
        )
        await ctx.send(text)

    @oiv.command(name="dashboard")
    async def oiv_dashboard(self, ctx: commands.Context):
        """Hinweis zur Dashboard-Seite."""
        lang = await self._lang(ctx.guild)
        webcore = self.bot.get_cog("WebCore")
        if webcore is None:
            return await ctx.send(t(lang, "dashboard_missing"))
        await ctx.send(t(lang, "dashboard_hint"))
