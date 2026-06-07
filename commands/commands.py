"""Commands-Cog (Anzeigename „Befehle").

Listet alle geladenen Cogs und ihre Befehle im WebCore-Dashboard – mit
Stufen-Spalten (Jeder/Mod/Admin/Owner), Detail-Metadaten, Suche/Filter, einer
exakten Mitglieds-Prüfung und Markdown-Export. Einzelne Cogs/Befehle lassen sich
ausblenden. In Discord gibt es zusätzlich ``[p]meinebefehle`` (zeigt jedem seine
nutzbaren Befehle) und die Owner-Gruppe ``[p]befehlsliste``.

Speichert keine personenbezogenen Endnutzerdaten: global nur die Namen
ausgeblendeter Cogs/Befehle, pro Server die Ausgabesprache.
"""

import logging

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from . import dashboard, inspector
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.commands")


class Commands(commands.Cog):
    """Übersicht aller Befehle aller Cogs – im Dashboard und in Discord."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=318472905613, force_registration=True)
        self.config.register_global(hidden_cogs=[], hidden_commands=[])
        self.config.register_guild(language=DEFAULT_LANGUAGE)

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (Muster aus example)
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
            slug="commands",
            name="Befehle",
            icon="bi-list-check",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard.render(self, request)

    # ----------------------------------------------------------------- #
    #  Sichtbarkeit (vom Dashboard und von [p]befehlsliste genutzt)
    # ----------------------------------------------------------------- #
    async def set_visibility(self, kind: str, value: str, hide: bool) -> bool:
        """Blendet einen Cog/Befehl aus bzw. ein. Gibt True zurück, wenn sich
        tatsächlich etwas geändert hat."""
        if kind == "cog":
            group = self.config.hidden_cogs
        elif kind == "command":
            group = self.config.hidden_commands
        else:
            return False
        async with group() as items:
            if hide:
                if value in items:
                    return False
                items.append(value)
                return True
            if value not in items:
                return False
            items.remove(value)
            return True

    # ----------------------------------------------------------------- #
    #  Hilfen
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        if guild is None:
            return DEFAULT_LANGUAGE
        return await self.config.guild(guild).language()

    async def _can_use(self, ctx, cmd, target, checking_other: bool) -> bool:
        if not checking_other:
            # Exakte Eigenprüfung über Reds can_run (inkl. Permissions-Cog-Regeln).
            try:
                return await cmd.can_run(ctx)
            except commands.CommandError:
                return False
            except Exception:  # noqa: BLE001 - defensiv, nie wegen eines Befehls crashen
                return False
        # Ziel-Mitglied: Privileg-/Rechte-Modell der Engine.
        info = inspector.build_command_info(cmd)
        priv = await inspector.member_privilege_level(self.bot, target)
        verdict, _ = inspector.evaluate_member(info, target, priv)
        return verdict

    def _join_names(self, names, lang: str) -> str:
        chunks = []
        length = 0
        ordered = sorted(names, key=str.lower)
        for index, name in enumerate(ordered):
            token = f"`{name}`"
            if length + len(token) + 3 > 980:  # Platz für den Mehr-Hinweis lassen
                chunks.append(t(lang, "more_suffix", count=len(ordered) - index))
                break
            chunks.append(token)
            length += len(token) + 3
        return " · ".join(chunks) if chunks else "—"

    def _build_embed(self, lang, usable, total, target, checking_other):
        count = sum(len(v) for v in usable.values())
        if checking_other:
            title = t(lang, "title_member", member=target.display_name)
            summary = t(lang, "summary_member", member=target.display_name, usable=count, total=total)
            empty = t(lang, "none_usable_member", member=target.display_name)
        else:
            title = t(lang, "title_my")
            summary = t(lang, "summary", usable=count, total=total)
            empty = t(lang, "none_usable")

        embed = discord.Embed(title=title, color=discord.Color(0x3DDC97))
        if count == 0:
            embed.description = empty
            return embed

        embed.description = summary
        other_label = t(lang, "field_other")
        shown = 0
        for cog_name in sorted(usable, key=lambda c: (c or "").lower()):
            if shown >= 24:  # 25-Felder-Limit von Embeds einhalten
                break
            embed.add_field(
                name=(cog_name or other_label),
                value=self._join_names(usable[cog_name], lang),
                inline=False,
            )
            shown += 1
        if len(usable) > shown:
            embed.add_field(
                name="…",
                value=t(lang, "more_suffix", count=len(usable) - shown),
                inline=False,
            )
        embed.set_footer(text=t(lang, "footer_self"))
        return embed

    # ----------------------------------------------------------------- #
    #  Öffentlicher Befehl
    # ----------------------------------------------------------------- #
    @commands.hybrid_command(name="meinebefehle")
    @commands.guild_only()
    async def meinebefehle(self, ctx: commands.Context, member: discord.Member = None, dm: bool = False):
        """Zeigt dir, welche Befehle du auf diesem Server nutzen kannst.

        Optional ein Mitglied angeben (nur Mod/Admin) und/oder `dm: true` für den
        Versand per Direktnachricht.
        """
        lang = await self._lang(ctx.guild)
        target = member or ctx.author
        checking_other = target.id != ctx.author.id

        if checking_other and not await inspector.member_is_mod_or_higher(self.bot, ctx.author):
            await ctx.send(t(lang, "no_permission_member"), ephemeral=True)
            return

        hidden_cogs = set(await self.config.hidden_cogs())
        hidden_cmds = set(await self.config.hidden_commands())

        usable: dict = {}
        total = 0
        for cmd in inspector.walk_all_commands(self.bot):
            if getattr(cmd, "hidden", False):
                continue
            if cmd.cog_name in hidden_cogs or cmd.qualified_name in hidden_cmds:
                continue
            total += 1
            if await self._can_use(ctx, cmd, target, checking_other):
                usable.setdefault(cmd.cog_name or "", []).append(cmd.qualified_name)

        embed = self._build_embed(lang, usable, total, target, checking_other)

        if dm:
            try:
                await ctx.author.send(embed=embed)
                await ctx.send(t(lang, "dm_sent"), ephemeral=True)
            except discord.HTTPException:
                await ctx.send(t(lang, "dm_failed"), ephemeral=True)
            return
        await ctx.send(embed=embed, ephemeral=True)

    # ----------------------------------------------------------------- #
    #  Owner-Verwaltung
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="befehlsliste")
    @commands.is_owner()
    async def befehlsliste(self, ctx: commands.Context):
        """Verwaltung der Befehls-Übersicht (nur Bot-Owner)."""

    @befehlsliste.command(name="verstecken")
    async def bl_hide(self, ctx: commands.Context, kind: str, *, name: str):
        """Blendet einen Cog oder Befehl aus. `kind` = `cog` oder `command`."""
        lang = await self._lang(ctx.guild)
        kind = kind.lower()
        if kind not in ("cog", "command"):
            await ctx.send(t(lang, "unknown_kind"))
            return
        name = name.strip()
        if not await self.set_visibility(kind, name, hide=True):
            await ctx.send(t(lang, "already_hidden"))
            return
        await ctx.send(t(lang, "hidden_cog" if kind == "cog" else "hidden_cmd", name=name))

    @befehlsliste.command(name="zeigen")
    async def bl_show(self, ctx: commands.Context, kind: str, *, name: str):
        """Zeigt einen ausgeblendeten Cog oder Befehl wieder. `kind` = `cog`/`command`."""
        lang = await self._lang(ctx.guild)
        kind = kind.lower()
        if kind not in ("cog", "command"):
            await ctx.send(t(lang, "unknown_kind"))
            return
        name = name.strip()
        if not await self.set_visibility(kind, name, hide=False):
            await ctx.send(t(lang, "not_hidden"))
            return
        await ctx.send(t(lang, "shown_cog" if kind == "cog" else "shown_cmd", name=name))

    @befehlsliste.command(name="status")
    async def bl_status(self, ctx: commands.Context):
        """Zeigt eine Kurzübersicht (Anzahl Cogs/Befehle, Ausgeblendetes, Dashboard)."""
        lang = await self._lang(ctx.guild)
        n_cogs = len(inspector.cog_names(self.bot))
        n_cmds = len(inspector.walk_all_commands(self.bot))
        hidden_cogs = await self.config.hidden_cogs()
        hidden_cmds = await self.config.hidden_commands()
        webcore = self.bot.get_cog("WebCore")
        dash = t(lang, "status_dashboard_on") if webcore is not None else t(lang, "status_dashboard_off")

        embed = discord.Embed(title=t(lang, "status_title"), color=discord.Color(0x3DDC97))
        embed.add_field(name=t(lang, "status_cogs"), value=str(n_cogs))
        embed.add_field(name=t(lang, "status_commands"), value=str(n_cmds))
        embed.add_field(name=t(lang, "status_hidden"), value=str(len(hidden_cogs) + len(hidden_cmds)))
        embed.add_field(name=t(lang, "status_language"), value=LANGUAGES.get(lang, lang))
        embed.add_field(name=t(lang, "status_dashboard"), value=dash, inline=False)
        if hidden_cogs or hidden_cmds:
            lines = [f"• Cog: {c}" for c in hidden_cogs] + [f"• Befehl: {c}" for c in hidden_cmds]
            embed.add_field(name="Ausgeblendet", value="\n".join(lines)[:1024], inline=False)
        await ctx.send(embed=embed, ephemeral=True)

    @befehlsliste.command(name="sprache")
    @commands.guild_only()
    async def bl_language(self, ctx: commands.Context, language: str):
        """Setzt die Sprache der Nutzer-Ausgabe für diesen Server (`de`/`en`)."""
        lang_now = await self._lang(ctx.guild)
        code = language.lower()
        if code not in LANGUAGES:
            await ctx.send(t(lang_now, "lang_unknown", langs=", ".join(LANGUAGES)))
            return
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))
