"""Changelog-Cog für Red-DiscordBot.

``/changelog`` öffnet ein Modal, aus dem der Bot ein einheitliches Update-Embed
im konfigurierten Kanal postet. Ziel-Kanal, berechtigte Rollen, optionale
Ping-Rolle, Farbe, Sprache und die wählbaren Kategorien werden **pro Server**
festgelegt – per Dashboard oder per ``[p]changelogset``. Gepostete Changelogs
werden gespeichert und sind im Dashboard einsehbar.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .embed import build_changelog_embed, has_any_section
from .modal import ChangelogModal
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.changelog")

# Standard-Kategorien (Emoji für den "Neu"-Bereich). Pro Server anpassbar;
# wird verwendet, solange der Server keine eigenen Kategorien gesetzt hat.
DEFAULT_CATEGORIES: list[dict] = [
    {"emoji": "🆕", "label": "Allgemein"},
    {"emoji": "🚗", "label": "Fahrzeuge"},
    {"emoji": "🌾", "label": "Landwirtschaft"},
    {"emoji": "⚙️", "label": "System"},
]

DEFAULT_COLOR = 0x3DDC97  # Emerald – passt zum WebCore-Theme
ENTRY_CAP = 200           # so viele Changelogs werden pro Server aufgehoben


def parse_color(text: str | None) -> int | None:
    """Wandelt ``#RRGGBB`` / ``RRGGBB`` in eine Farbzahl um (sonst None)."""
    if not text:
        return None
    value = text.strip().lstrip("#")
    if len(value) == 6:
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None


class Changelog(commands.Cog):
    """Server-Updates (Changelogs) per Modal posten – mehrsprachig, mit Dashboard."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=274069153822, force_registration=True)
        self.config.register_guild(
            language="de",
            channel_id=None,        # Ziel-Kanal
            poster_roles=[],        # Rollen, die posten dürfen
            ping_role_id=None,      # optionale @Updates-Rolle
            ping_enabled=False,     # Ping vor dem Embed?
            color=DEFAULT_COLOR,
            categories=[],          # leer -> DEFAULT_CATEGORIES
            messages={},            # Text-Overrides (OVERRIDABLE_KEYS)
            entries={},             # id -> Changelog-Datensatz
            counter=0,
        )

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (1:1-Muster aus example/poll)
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
            slug="changelog",
            name="Changelog",
            icon="bi-megaphone",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Hilfsfunktionen
    # ----------------------------------------------------------------- #
    def _categories(self, conf: dict) -> list[dict]:
        cats = conf.get("categories") or []
        return cats if cats else DEFAULT_CATEGORIES

    def _resolve_category(self, conf: dict, choice: str | None) -> tuple[str, str]:
        """Wandelt den (optionalen) Autocomplete-Wert in (emoji, label) um."""
        cats = self._categories(conf)
        if not cats:  # theoretisch nie – DEFAULT_CATEGORIES ist nicht leer
            return ("🆕", "Allgemein")
        if choice:
            if choice.isdigit():
                idx = int(choice)
                if 0 <= idx < len(cats):
                    c = cats[idx]
                    return (c["emoji"], c["label"])
            low = choice.lower()
            for c in cats:
                if c["emoji"] == choice or (c.get("label", "").lower() == low):
                    return (c["emoji"], c["label"])
        first = cats[0]
        return (first["emoji"], first["label"])

    async def _can_post(self, member: discord.Member | None, conf: dict) -> bool:
        if member is None:
            return False
        if await self.bot.is_owner(member):
            return True
        perms = getattr(member, "guild_permissions", None)
        if perms is not None and (perms.administrator or perms.manage_guild):
            return True
        role_ids = {r.id for r in getattr(member, "roles", [])}
        return any(rid in role_ids for rid in (conf.get("poster_roles") or []))

    async def _prefix(self, guild: discord.Guild | None) -> str:
        try:
            for p in await self.bot.get_valid_prefixes(guild):
                if not p.startswith("<@"):
                    return p
        except Exception:  # noqa: BLE001
            pass
        return "[p]"

    async def _store_entry(self, guild: discord.Guild, record: dict) -> None:
        async with self.config.guild(guild).entries() as entries:
            entries[record["id"]] = record
            if len(entries) > ENTRY_CAP:
                oldest = sorted(entries.values(), key=lambda r: r.get("created_ts", 0))
                for old in oldest[: len(entries) - ENTRY_CAP]:
                    entries.pop(old["id"], None)

    # ----------------------------------------------------------------- #
    #  /changelog  (reiner Slash-Command – ein Modal braucht eine Interaction)
    # ----------------------------------------------------------------- #
    async def category_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            conf = await self.config.guild(interaction.guild).all()
        except Exception:  # noqa: BLE001
            return []
        cats = self._categories(conf)
        cur = (current or "").lower()
        choices: list[app_commands.Choice[str]] = []
        for idx, c in enumerate(cats[:25]):
            name = f"{c['emoji']} {c.get('label', '')}".strip()
            if cur and cur not in name.lower():
                continue
            choices.append(app_commands.Choice(name=name[:100], value=str(idx)))
        return choices[:25]

    @app_commands.command(
        name="changelog",
        description="Postet ein Server-Update (Changelog) im konfigurierten Kanal.",
    )
    @app_commands.guild_only()
    @app_commands.describe(kategorie="Kategorie/Emoji für den 'Neu'-Bereich (optional).")
    @app_commands.autocomplete(kategorie=category_autocomplete)
    async def changelog_slash(
        self, interaction: discord.Interaction, kategorie: str | None = None
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                t(DEFAULT_LANGUAGE, "err_guild_only"), ephemeral=True
            )
            return

        conf = await self.config.guild(guild).all()
        lang = conf.get("language", DEFAULT_LANGUAGE)

        if not await self._can_post(interaction.user, conf):
            await interaction.response.send_message(t(lang, "err_no_perm"), ephemeral=True)
            return

        channel = guild.get_channel(conf["channel_id"]) if conf.get("channel_id") else None
        if channel is None:
            prefix = await self._prefix(guild)
            await interaction.response.send_message(
                t(lang, "err_no_channel", prefix=prefix), ephemeral=True
            )
            return

        emoji, label = self._resolve_category(conf, kategorie)
        modal = ChangelogModal(self, lang=lang, category_emoji=emoji, category_label=label)
        await interaction.response.send_modal(modal)

    # ----------------------------------------------------------------- #
    #  Modal-Auswertung: validieren, Embed bauen, posten, speichern
    # ----------------------------------------------------------------- #
    async def handle_modal_submit(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        neu: str,
        geaendert: str,
        fixes: str,
        hinweis: str,
        category_emoji: str,
        category_label: str,
        lang: str,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(t(lang, "err_guild_only"), ephemeral=True)
            return

        conf = await self.config.guild(guild).all()

        if not has_any_section(neu, geaendert, fixes):
            await interaction.response.send_message(t(lang, "err_need_section"), ephemeral=True)
            return

        channel = guild.get_channel(conf["channel_id"]) if conf.get("channel_id") else None
        if channel is None:
            await interaction.response.send_message(t(lang, "err_channel_gone"), ephemeral=True)
            return

        me = guild.me
        perms = channel.permissions_for(me) if me is not None else None
        if perms is None or not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(t(lang, "err_cant_send"), ephemeral=True)
            return

        # Ab hier posten wir – kann kurz dauern, daher ephemer aufschieben.
        await interaction.response.defer(ephemeral=True)

        # Optionaler Ping als separate Nachricht vor dem Embed.
        if conf.get("ping_enabled") and conf.get("ping_role_id"):
            role = guild.get_role(conf["ping_role_id"])
            if role is not None:
                try:
                    await channel.send(
                        role.mention,
                        allowed_mentions=discord.AllowedMentions(roles=[role]),
                    )
                except discord.HTTPException:
                    pass

        now = datetime.now(tz=timezone.utc)
        author = interaction.user
        embed = build_changelog_embed(
            title=title,
            neu=neu,
            geaendert=geaendert,
            fixes=fixes,
            hinweis=hinweis,
            category_emoji=category_emoji,
            author_name=author.display_name,
            author_icon=str(author.display_avatar.url) if author else None,
            color=int(conf.get("color", DEFAULT_COLOR)),
            lang=lang,
            messages=conf.get("messages") or {},
            when=now,
        )

        try:
            message = await channel.send(embed=embed)
        except discord.HTTPException:
            await interaction.followup.send(t(lang, "err_cant_send"), ephemeral=True)
            return

        cid = int(conf.get("counter", 0)) + 1
        await self.config.guild(guild).counter.set(cid)
        record = {
            "id": f"cl{cid}",
            "title": title.strip()[:230],
            "category_emoji": category_emoji,
            "category_label": category_label,
            "neu": (neu or "").strip(),
            "geaendert": (geaendert or "").strip(),
            "fixes": (fixes or "").strip(),
            "hinweis": (hinweis or "").strip(),
            "author_id": author.id,
            "author_name": author.display_name,
            "channel_id": channel.id,
            "message_id": message.id,
            "created_ts": int(now.timestamp()),
        }
        await self._store_entry(guild, record)

        await interaction.followup.send(t(lang, "posted_ok"), ephemeral=True)

    # ----------------------------------------------------------------- #
    #  Admin-Befehle:  [p]changelogset …   (hybrid = Text + Slash)
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="changelogset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def changelogset(self, ctx: commands.Context):
        """Einstellungen für den Changelog-Cog."""

    @changelogset.command(name="channel")
    async def cl_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Ziel-Kanal für Changelogs festlegen."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Ziel-Kanal ist jetzt {channel.mention}.")

    @changelogset.command(name="roleadd")
    async def cl_roleadd(self, ctx: commands.Context, role: discord.Role):
        """Eine Rolle hinzufügen, die Changelogs posten darf."""
        async with self.config.guild(ctx.guild).poster_roles() as roles:
            if role.id in roles:
                await ctx.send(f"{role.name} darf bereits posten.")
                return
            roles.append(role.id)
        await ctx.send(f"{role.name} darf jetzt Changelogs posten.")

    @changelogset.command(name="roleremove")
    async def cl_roleremove(self, ctx: commands.Context, role: discord.Role):
        """Eine Poster-Rolle wieder entfernen."""
        async with self.config.guild(ctx.guild).poster_roles() as roles:
            if role.id not in roles:
                await ctx.send(f"{role.name} war nicht freigegeben.")
                return
            roles.remove(role.id)
        await ctx.send(f"{role.name} darf keine Changelogs mehr posten.")

    @changelogset.command(name="pingrole")
    async def cl_pingrole(self, ctx: commands.Context, role: discord.Role):
        """Rolle festlegen, die vor dem Embed gepingt wird."""
        await self.config.guild(ctx.guild).ping_role_id.set(role.id)
        await ctx.send(
            f"Ping-Rolle ist jetzt {role.name}. Aktivieren mit "
            f"`{ctx.clean_prefix}changelogset ping on`."
        )

    @changelogset.command(name="ping")
    async def cl_ping(self, ctx: commands.Context, aktiv: bool):
        """Ping vor dem Embed an- oder ausschalten (on/off)."""
        await self.config.guild(ctx.guild).ping_enabled.set(aktiv)
        state = "aktiviert" if aktiv else "deaktiviert"
        await ctx.send(f"Ping vor dem Embed {state}.")

    @changelogset.command(name="color")
    async def cl_color(self, ctx: commands.Context, hexfarbe: str):
        """Embed-Farbe setzen (z. B. #3DDC97)."""
        value = parse_color(hexfarbe)
        if value is None:
            await ctx.send("Bitte eine Hex-Farbe wie `#3DDC97` angeben.")
            return
        await self.config.guild(ctx.guild).color.set(value)
        await ctx.send(f"Embed-Farbe gesetzt: #{value:06X}.")

    @changelogset.command(name="language")
    async def cl_language(self, ctx: commands.Context, sprache: str):
        """Sprache für Changelogs setzen (de/en)."""
        code = sprache.lower()
        if code not in LANGUAGES:
            await ctx.send(f"Verfügbare Sprachen: {', '.join(LANGUAGES)}.")
            return
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(f"Sprache: {LANGUAGES[code]}.")

    @changelogset.command(name="catadd")
    async def cl_catadd(self, ctx: commands.Context, emoji: str, *, label: str):
        """Wählbare Kategorie hinzufügen (Emoji + Bezeichnung)."""
        async with self.config.guild(ctx.guild).categories() as cats:
            if not cats:
                cats.extend(DEFAULT_CATEGORIES)
            if len(cats) >= 25:
                await ctx.send("Maximal 25 Kategorien möglich.")
                return
            cats.append({"emoji": emoji.strip()[:16], "label": label.strip()[:80]})
        await ctx.send(f"Kategorie hinzugefügt: {emoji} {label}")

    @changelogset.command(name="catremove")
    async def cl_catremove(self, ctx: commands.Context, index: int):
        """Kategorie per Nummer entfernen (siehe `changelogset cats`)."""
        async with self.config.guild(ctx.guild).categories() as cats:
            if not cats:
                cats.extend(DEFAULT_CATEGORIES)
            if index < 1 or index > len(cats):
                await ctx.send(f"Nummer zwischen 1 und {len(cats)} angeben.")
                return
            removed = cats.pop(index - 1)
        await ctx.send(f"Entfernt: {removed.get('emoji', '')} {removed.get('label', '')}")

    @changelogset.command(name="cats")
    async def cl_cats(self, ctx: commands.Context):
        """Aktuell wählbare Kategorien anzeigen."""
        conf = await self.config.guild(ctx.guild).all()
        cats = self._categories(conf)
        lines = [f"{i + 1}. {c['emoji']} {c.get('label', '')}" for i, c in enumerate(cats)]
        await ctx.send("**Kategorien:**\n" + "\n".join(lines))

    @changelogset.command(name="show")
    async def cl_show(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        conf = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(conf["channel_id"]) if conf.get("channel_id") else None
        roles = [ctx.guild.get_role(r) for r in (conf.get("poster_roles") or [])]
        role_names = ", ".join(r.name for r in roles if r) or "—"
        ping_role = ctx.guild.get_role(conf["ping_role_id"]) if conf.get("ping_role_id") else None
        ping_state = "an" if conf.get("ping_enabled") else "aus"
        lang = conf.get("language", DEFAULT_LANGUAGE)
        embed = discord.Embed(title="Changelog – Einstellungen", color=int(conf.get("color", DEFAULT_COLOR)))
        embed.add_field(name="Ziel-Kanal", value=(channel.mention if channel else "—"), inline=False)
        embed.add_field(name="Poster-Rollen", value=role_names, inline=False)
        embed.add_field(
            name="Ping",
            value=f"{ping_state}" + (f" · {ping_role.name}" if ping_role else ""),
            inline=False,
        )
        embed.add_field(name="Sprache", value=LANGUAGES.get(lang, lang), inline=True)
        embed.add_field(name="Farbe", value=f"#{int(conf.get('color', DEFAULT_COLOR)):06X}", inline=True)
        embed.add_field(name="Kategorien", value=str(len(self._categories(conf))), inline=True)
        embed.add_field(name="Gespeicherte Changelogs", value=str(len(conf.get("entries") or {})), inline=True)
        await ctx.send(embed=embed)

    @changelogset.command(name="history")
    async def cl_history(self, ctx: commands.Context, anzahl: int = 5):
        """Die letzten Changelogs auflisten (Standard: 5)."""
        anzahl = max(1, min(20, anzahl))
        conf = await self.config.guild(ctx.guild).all()
        entries = list((conf.get("entries") or {}).values())
        if not entries:
            await ctx.send("Für diesen Server sind noch keine Changelogs gespeichert.")
            return
        entries.sort(key=lambda r: r.get("created_ts", 0), reverse=True)
        lines = []
        for r in entries[:anzahl]:
            ts = r.get("created_ts", 0)
            when = f"<t:{ts}:d>" if ts else "—"
            lines.append(
                f"`{r.get('id', '?')}` · {when} · {r.get('category_emoji', '')} "
                f"**{r.get('title', '(ohne Titel)')}** · {r.get('author_name', '?')}"
            )
        await ctx.send("\n".join(lines))
