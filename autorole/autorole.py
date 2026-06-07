from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.autorole")

DELAY_MIN = 0
DELAY_MAX = 3600
SCREENING_MODES = ("auto", "on", "off")
# Guild-Feature-Flag, wenn die Regel-Verifizierung ("Membership Screening") aktiv ist.
GATE_FEATURE = "MEMBER_VERIFICATION_GATE_ENABLED"
# Sicherheitslimit, damit [p]autorole applyall auf riesigen Servern nicht entgleist.
APPLY_LIMIT = 5000


class Autorole(commands.Cog):
    """Vergibt neuen Mitgliedern (und Bots) automatisch Rollen.

    Mehrere Rollen für Menschen und Bots, optional erst nach Discords
    Regel-Verifizierung, mit Verzögerung, Mindest-Kontoalter (Raid-Schutz) und
    Sticky-Rollen (kommen beim erneuten Beitritt zurück). Mehrsprachig
    (Deutsch/Englisch) und vollständig über das WebCore-Dashboard konfigurierbar.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=905172634810, force_registration=True)
        self.config.register_guild(
            language="de",
            enabled=True,
            join_roles=[],        # Rollen-IDs für Menschen
            bot_roles=[],         # Rollen-IDs für Bots
            sticky_roles=[],      # Rollen-IDs, die beim erneuten Beitritt zurückkommen
            delay=0,              # Sekunden Wartezeit vor der Vergabe
            min_account_age=0,    # Stunden; 0 = aus
            screening="auto",     # auto | on | off
        )
        self.config.register_member(
            sticky=[],            # beim Verlassen gehaltene sticky-Rollen (Rollen-IDs)
        )

        # Laufzeit-Status (nicht persistent): geplante Vergaben pro (guild_id, member_id).
        self._pending: dict[tuple[int, int], asyncio.Task] = {}

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (1:1-Muster aus example/sticky)
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
            slug="autorole",
            name="Autorole",
            icon="bi-person-plus",
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
        await ctx.send(t(await self._lang(ctx.guild), key, **kwargs))

    @staticmethod
    def gate_enabled(guild: discord.Guild) -> bool:
        """Ob auf dem Server die Regel-Verifizierung (Membership Screening) aktiv ist."""
        return GATE_FEATURE in (guild.features or [])

    @classmethod
    def wait_for_screening(cls, guild: discord.Guild, mode: str) -> bool:
        """Soll die Vergabe auf den Abschluss der Regel-Verifizierung warten?

        ``off``       -> nie warten.
        ``on``/``auto`` -> nur warten, wenn der Server tatsächlich ein Gate hat.
        So „verhungert“ niemand, wenn ``on`` gesetzt ist, der Server aber gar kein
        Screening nutzt (dann wird sofort beim Beitritt vergeben).
        """
        if mode == "off":
            return False
        return cls.gate_enabled(guild)

    def _assignable_reason(self, guild: discord.Guild, role: discord.Role) -> str | None:
        """``None`` wenn die Rolle zuweisbar ist, sonst ein Grund-Key für ``t()``."""
        if role.is_default():
            return "reason_default"
        if role.managed:
            return "reason_managed"
        me = guild.me
        if me is not None and role >= me.top_role:
            return "reason_too_high"
        return None

    def _filter_roles(self, guild: discord.Guild, role_ids) -> list[discord.Role]:
        """Liefert die tatsächlich zuweisbaren Rollen zu einer Liste von IDs."""
        out = []
        for rid in role_ids:
            role = guild.get_role(int(rid))
            if role is not None and self._assignable_reason(guild, role) is None:
                out.append(role)
        return out

    async def _target_role_ids(self, member: discord.Member) -> set[int]:
        """Welche Rollen-IDs soll dieses Mitglied beim Beitritt erhalten?"""
        gconf = self.config.guild(member.guild)
        if member.bot:
            return set(await gconf.bot_roles())
        ids = set(await gconf.join_roles())
        sticky_now = set(await gconf.sticky_roles())
        if sticky_now:
            held = set(await self.config.member(member).sticky())
            ids |= (held & sticky_now)  # nur noch gültige sticky-Rollen zurückgeben
        return ids

    # ----------------------------------------------------------------- #
    #  Vergabe (verzögert / sofort)
    # ----------------------------------------------------------------- #
    def _schedule_apply(self, member: discord.Member, delay: int) -> None:
        key = (member.guild.id, member.id)
        existing = self._pending.get(key)
        if existing is not None and not existing.done():
            return  # für dieses Mitglied ist bereits eine Vergabe geplant
        self._pending[key] = asyncio.create_task(self._apply_after(member, delay))

    async def _apply_after(self, member: discord.Member, delay: int) -> None:
        key = (member.guild.id, member.id)
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._apply_now(member)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Autorole-Vergabe für %s in %s fehlgeschlagen.", member.id, member.guild.id)
        finally:
            self._pending.pop(key, None)

    async def _apply_now(self, member: discord.Member) -> int:
        """Vergibt die fälligen Rollen sofort. Gibt die Zahl neu vergebener Rollen zurück."""
        guild = member.guild
        fresh = guild.get_member(member.id)
        if fresh is None:
            return 0  # Mitglied ist inzwischen weg
        member = fresh

        gconf = self.config.guild(guild)
        if not await gconf.enabled():
            return 0
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return 0

        # Mindest-Kontoalter (Raid-/Wegwerf-Account-Schutz; nur für Menschen sinnvoll).
        min_age = int(await gconf.min_account_age())
        if min_age > 0 and not member.bot:
            created = member.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created < timedelta(hours=min_age):
                log.debug("Konto %s zu jung für Auto-Rollen in %s.", member.id, guild.id)
                await self.config.member(member).sticky.clear()
                return 0

        role_ids = await self._target_role_ids(member)
        if not role_ids:
            return 0
        to_add = [r for r in self._filter_roles(guild, role_ids) if r not in member.roles]
        if not to_add:
            await self.config.member(member).sticky.clear()
            return 0
        try:
            await member.add_roles(*to_add, reason="Autorole")
        except discord.Forbidden:
            log.warning("Keine Rechte, um Auto-Rollen in %s zu vergeben.", guild.id)
            return 0
        except discord.HTTPException:
            log.exception("Auto-Rollen-Vergabe in %s fehlgeschlagen.", guild.id)
            return 0
        await self.config.member(member).sticky.clear()  # sticky-Speicher konsumiert
        return len(to_add)

    async def apply_to_existing(self, guild: discord.Guild):
        """Vergibt die Mitglieder-Rollen an alle bestehenden Menschen.

        Rückgabe ``(added, members)`` oder ``None`` (deaktiviert / keine Rollen /
        keine Rechte).
        """
        gconf = self.config.guild(guild)
        if not await gconf.enabled():
            return None
        roles = self._filter_roles(guild, await gconf.join_roles())
        me = guild.me
        if not roles or me is None or not me.guild_permissions.manage_roles:
            return None
        added = touched = count = 0
        for member in guild.members:
            if member.bot:
                continue
            count += 1
            if count > APPLY_LIMIT:
                break
            missing = [r for r in roles if r not in member.roles]
            if not missing:
                continue
            try:
                await member.add_roles(*missing, reason="Autorole (applyall)")
            except discord.HTTPException:
                continue
            added += len(missing)
            touched += 1
        return added, touched

    # ----------------------------------------------------------------- #
    #  Listener
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        gconf = self.config.guild(guild)
        if not await gconf.enabled():
            return
        delay = int(await gconf.delay())
        if member.bot:
            # Bots durchlaufen keine Verifizierung -> direkt einplanen.
            self._schedule_apply(member, delay)
            return
        mode = await gconf.screening()
        if self.wait_for_screening(guild, mode) and member.pending:
            # Warten, bis das Mitglied die Regeln akzeptiert hat (on_member_update).
            return
        self._schedule_apply(member, delay)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Nur reagieren, wenn die Regel-Verifizierung gerade abgeschlossen wurde.
        if after.bot or not before.pending or after.pending:
            return
        guild = after.guild
        gconf = self.config.guild(guild)
        if not await gconf.enabled():
            return
        if not self.wait_for_screening(guild, await gconf.screening()):
            return
        self._schedule_apply(after, int(await gconf.delay()))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Eine evtl. noch geplante Vergabe verwerfen.
        task = self._pending.pop((member.guild.id, member.id), None)
        if task is not None and not task.done():
            task.cancel()
        if member.bot:
            return
        sticky_now = set(await self.config.guild(member.guild).sticky_roles())
        if not sticky_now:
            return
        held = [r.id for r in member.roles if r.id in sticky_now]
        if held:
            await self.config.member(member).sticky.set(held)
        else:
            await self.config.member(member).sticky.clear()

    # ----------------------------------------------------------------- #
    #  Befehle (hybrid = Text + Slash)
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="autorole")
    @commands.guild_only()
    async def autorole(self, ctx: commands.Context):
        """Automatische Rollenvergabe verwalten."""

    @autorole.command(name="toggle")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_toggle(self, ctx: commands.Context):
        """Schaltet die automatische Rollenvergabe an oder aus."""
        gconf = self.config.guild(ctx.guild)
        new_state = not await gconf.enabled()
        await gconf.enabled.set(new_state)
        await self._say(ctx, "system_on" if new_state else "system_off")

    @autorole.command(name="add")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_add(self, ctx: commands.Context, *, role: discord.Role):
        """Fügt eine Rolle hinzu, die neue Mitglieder automatisch erhalten."""
        reason = self._assignable_reason(ctx.guild, role)
        if reason is not None:
            lang = await self._lang(ctx.guild)
            return await ctx.send(t(lang, "add_unassignable", role=role.name, reason=t(lang, reason)))
        roles = await self.config.guild(ctx.guild).join_roles()
        if role.id in roles:
            return await self._say(ctx, "add_already", role=role.name)
        roles.append(role.id)
        await self.config.guild(ctx.guild).join_roles.set(roles)
        await self._say(ctx, "add_ok", role=role.name)

    @autorole.command(name="remove")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_remove(self, ctx: commands.Context, *, role: discord.Role):
        """Entfernt eine Rolle aus den Mitglieder-Rollen."""
        roles = await self.config.guild(ctx.guild).join_roles()
        if role.id not in roles:
            return await self._say(ctx, "remove_not_set", role=role.name)
        roles.remove(role.id)
        await self.config.guild(ctx.guild).join_roles.set(roles)
        await self._say(ctx, "remove_ok", role=role.name)

    @autorole.command(name="botadd")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_botadd(self, ctx: commands.Context, *, role: discord.Role):
        """Fügt eine Rolle hinzu, die neue Bots automatisch erhalten."""
        reason = self._assignable_reason(ctx.guild, role)
        if reason is not None:
            lang = await self._lang(ctx.guild)
            return await ctx.send(t(lang, "add_unassignable", role=role.name, reason=t(lang, reason)))
        roles = await self.config.guild(ctx.guild).bot_roles()
        if role.id in roles:
            return await self._say(ctx, "bot_add_already", role=role.name)
        roles.append(role.id)
        await self.config.guild(ctx.guild).bot_roles.set(roles)
        await self._say(ctx, "bot_add_ok", role=role.name)

    @autorole.command(name="botremove")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_botremove(self, ctx: commands.Context, *, role: discord.Role):
        """Entfernt eine Rolle aus den Bot-Rollen."""
        roles = await self.config.guild(ctx.guild).bot_roles()
        if role.id not in roles:
            return await self._say(ctx, "bot_remove_not_set", role=role.name)
        roles.remove(role.id)
        await self.config.guild(ctx.guild).bot_roles.set(roles)
        await self._say(ctx, "bot_remove_ok", role=role.name)

    @autorole.command(name="sticky")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_sticky(self, ctx: commands.Context, *, role: discord.Role):
        """Markiert eine Rolle als sticky (kommt beim erneuten Beitritt zurück) – erneut zum Entfernen."""
        roles = await self.config.guild(ctx.guild).sticky_roles()
        if role.id in roles:
            roles.remove(role.id)
            await self.config.guild(ctx.guild).sticky_roles.set(roles)
            return await self._say(ctx, "sticky_off", role=role.name)
        reason = self._assignable_reason(ctx.guild, role)
        if reason is not None:
            lang = await self._lang(ctx.guild)
            return await ctx.send(t(lang, "sticky_unassignable", role=role.name, reason=t(lang, reason)))
        roles.append(role.id)
        await self.config.guild(ctx.guild).sticky_roles.set(roles)
        await self._say(ctx, "sticky_on", role=role.name)

    @autorole.command(name="delay")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_delay(self, ctx: commands.Context, seconds: int):
        """Setzt die Wartezeit (Sekunden) nach dem Beitritt vor der Vergabe (0–3600)."""
        if seconds < DELAY_MIN or seconds > DELAY_MAX:
            return await self._say(ctx, "delay_bad")
        await self.config.guild(ctx.guild).delay.set(seconds)
        await self._say(ctx, "delay_set", sec=seconds)

    @autorole.command(name="age")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_age(self, ctx: commands.Context, hours: int):
        """Setzt das Mindest-Kontoalter in Stunden (0 = aus)."""
        if hours < 0:
            return await self._say(ctx, "age_bad")
        await self.config.guild(ctx.guild).min_account_age.set(hours)
        if hours == 0:
            await self._say(ctx, "age_off")
        else:
            await self._say(ctx, "age_set", hours=hours)

    @autorole.command(name="screening")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_screening(self, ctx: commands.Context, value: str):
        """Wann sollen Rollen vergeben werden: `auto`, `on` oder `off`."""
        value = value.lower()
        if value not in SCREENING_MODES:
            return await self._say(ctx, "screening_bad", value=value)
        await self.config.guild(ctx.guild).screening.set(value)
        lang = await self._lang(ctx.guild)
        await ctx.send(t(lang, "screening_set", mode=t(lang, f"screening_mode_{value}")))

    @autorole.command(name="language")
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_language(self, ctx: commands.Context, code: str):
        """Setzt die Sprache der Bot-Antworten (de/en)."""
        code = code.lower()
        if code not in LANGUAGES:
            langs = ", ".join(f"`{c}`" for c in LANGUAGES)
            return await self._say(ctx, "lang_unknown", code=code, langs=langs)
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))

    @autorole.command(name="applyall")
    @commands.admin_or_permissions(manage_guild=True)
    @commands.max_concurrency(1, commands.BucketType.guild)
    async def autorole_applyall(self, ctx: commands.Context):
        """Vergibt die Mitglieder-Rollen an alle bestehenden Mitglieder, die sie noch nicht haben."""
        gconf = self.config.guild(ctx.guild)
        if not await gconf.enabled():
            return await self._say(ctx, "apply_disabled", p=ctx.clean_prefix)
        if not await gconf.join_roles():
            return await self._say(ctx, "apply_none")
        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await self._say(ctx, "no_manage_roles")
        await self._say(ctx, "apply_running")
        result = await self.apply_to_existing(ctx.guild)
        if result is None:
            return await self._say(ctx, "apply_none")
        added, members = result
        await self._say(ctx, "apply_done", added=added, members=members)

    @autorole.command(name="settings", aliases=["list", "show"])
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_settings(self, ctx: commands.Context):
        """Zeigt die aktuellen Server-Einstellungen."""
        guild = ctx.guild
        conf = await self.config.guild(guild).all()
        lang = conf["language"]

        def names(ids):
            out = [r.name for rid in ids if (r := guild.get_role(int(rid))) is not None]
            return ", ".join(out) if out else t(lang, "none")

        state = t(lang, "state_on" if conf["enabled"] else "state_off")
        age = (
            t(lang, "age_hours", hours=conf["min_account_age"])
            if conf["min_account_age"]
            else t(lang, "age_off_short")
        )
        lines = [
            t(lang, "settings_header"),
            t(lang, "settings_state", state=state),
            t(lang, "settings_lang", lang=LANGUAGES.get(lang, lang)),
            t(lang, "settings_screening", mode=t(lang, f"screening_mode_{conf['screening']}")),
            t(lang, "settings_delay", sec=conf["delay"]),
            t(lang, "settings_age", age=age),
            t(lang, "settings_join", roles=names(conf["join_roles"])),
            t(lang, "settings_bot", roles=names(conf["bot_roles"])),
            t(lang, "settings_sticky", roles=names(conf["sticky_roles"])),
            t(lang, "settings_gate_on" if self.gate_enabled(guild) else "settings_gate_off"),
        ]
        await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())
