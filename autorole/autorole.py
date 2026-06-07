from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .panels import (
    MAX_ROLES,
    build_view,
    compute_button,
    compute_select,
    message_kwargs,
    new_panel,
    parse_custom_id,
)
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
            panels={},            # Rollen-Panels: {panel_id: {...}} (Buttons/Dropdown)
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
    #  Rollen-Panels: Helfer (Config + Nachricht posten)
    # ----------------------------------------------------------------- #
    async def _get_panel(self, guild: discord.Guild, pid: str):
        panels = await self.config.guild(guild).panels()
        return panels.get(pid)

    async def _panel_post(self, guild: discord.Guild, panel: dict) -> tuple[bool, str]:
        """Postet bzw. aktualisiert die Panel-Nachricht. Rückgabe ``(ok, string_key)``."""
        ch = guild.get_channel(int(panel["channel_id"])) if panel.get("channel_id") else None
        if not isinstance(ch, discord.TextChannel):
            return False, "panel_post_no_channel"
        if not panel.get("roles"):
            return False, "panel_post_no_roles"
        me = guild.me
        perms = ch.permissions_for(me) if me is not None else None
        if perms is None or not perms.send_messages or (panel.get("use_embed") and not perms.embed_links):
            return False, "panel_post_no_send"
        view = build_view(panel)
        kwargs = message_kwargs(panel)
        msg_id = panel.get("message_id")
        if msg_id:
            try:
                old = await ch.fetch_message(int(msg_id))
                await old.edit(view=view, **kwargs)
                return True, "panel_posted"
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass  # alte Nachricht weg/gesperrt -> neu posten
        try:
            sent = await ch.send(view=view, **kwargs)
        except discord.HTTPException:
            return False, "panel_post_failed"
        async with self.config.guild(guild).panels() as panels:
            if panel["id"] in panels:
                panels[panel["id"]]["message_id"] = sent.id
                panels[panel["id"]]["channel_id"] = ch.id
        return True, "panel_posted"

    async def _panel_refresh(self, guild: discord.Guild, pid: str) -> None:
        """Aktualisiert die Nachricht eines bereits geposteten Panels (sonst nichts)."""
        panel = await self._get_panel(guild, pid)
        if panel and panel.get("message_id"):
            try:
                await self._panel_post(guild, panel)
            except Exception:  # noqa: BLE001
                log.exception("Panel-Refresh für %s in %s fehlgeschlagen.", pid, guild.id)

    async def _panel_delete_message(self, guild: discord.Guild, panel: dict) -> None:
        ch = guild.get_channel(int(panel["channel_id"])) if panel.get("channel_id") else None
        msg_id = panel.get("message_id")
        if isinstance(ch, discord.TextChannel) and msg_id:
            try:
                msg = await ch.fetch_message(int(msg_id))
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

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
    #  Rollen-Panels: Interaktion (Button-/Dropdown-Klicks)
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # Nur unsere eigenen Panel-Komponenten verarbeiten (Präfix "arp:").
        try:
            if interaction.type != discord.InteractionType.component:
                return
            data = interaction.data or {}
            parsed = parse_custom_id(data.get("custom_id", ""))
            if parsed is None:
                return
            guild = interaction.guild
            if guild is None:
                return
            kind, pid, role_id = parsed
            await interaction.response.defer(ephemeral=True, thinking=True)
            lang = await self._lang(guild)
            panel = await self._get_panel(guild, pid)
            if panel is None:
                return await self._pf(interaction, t(lang, "panel_gone"))
            me = guild.me
            if me is None or not me.guild_permissions.manage_roles:
                return await self._pf(interaction, t(lang, "panel_bot_no_perm"))
            member = interaction.user
            if not isinstance(member, discord.Member):
                member = guild.get_member(getattr(interaction.user, "id", 0))
            if member is None:
                return await self._pf(interaction, t(lang, "panel_failed"))
            panel_ids = [int(r["role_id"]) for r in panel.get("roles", [])]
            member_ids = {r.id for r in member.roles}
            mode = panel.get("mode", "toggle")
            unique = bool(panel.get("unique"))
            if kind == "btn":
                await self._panel_button(interaction, lang, guild, member, member_ids, role_id, panel_ids, mode, unique)
            else:
                values = {int(v) for v in (data.get("values") or []) if str(v).isdigit()}
                await self._panel_select(interaction, lang, guild, member, member_ids, values, panel_ids, mode, unique)
        except Exception:  # noqa: BLE001
            log.exception("Fehler bei einer Panel-Interaktion.")
            try:
                await self._pf(interaction, "⚠️")
            except Exception:  # noqa: BLE001
                pass

    async def _pf(self, interaction: discord.Interaction, text: str) -> None:
        """Ephemerale Antwort an die klickende Person (auch nach defer)."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass

    async def _panel_apply(self, member: discord.Member, add_roles, remove_roles) -> bool:
        try:
            if add_roles:
                await member.add_roles(*add_roles, reason="Autorole-Panel")
            if remove_roles:
                await member.remove_roles(*remove_roles, reason="Autorole-Panel")
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _panel_button(self, interaction, lang, guild, member, member_ids,
                            target, panel_ids, mode, unique) -> None:
        if target not in panel_ids:
            return await self._pf(interaction, t(lang, "panel_gone"))
        role = guild.get_role(target)
        if role is None or self._assignable_reason(guild, role) is not None:
            return await self._pf(interaction, t(lang, "panel_role_unavailable"))
        add_ids, rem_ids = compute_button(member_ids, target, panel_ids, mode, unique)
        add_roles = self._filter_roles(guild, add_ids)
        rem_roles = self._filter_roles(guild, rem_ids)
        if not add_roles and not rem_roles:
            key = "panel_have" if (mode == "add" and target in member_ids) else "panel_none"
            return await self._pf(interaction, t(lang, key, role=role.name))
        if not await self._panel_apply(member, add_roles, rem_roles):
            return await self._pf(interaction, t(lang, "panel_failed"))
        added_target = any(r.id == target for r in add_roles)
        removed_target = any(r.id == target for r in rem_roles)
        also_removed = [r for r in rem_roles if r.id != target]
        if added_target and also_removed:
            msg = t(lang, "panel_set", role=role.name)
        elif added_target:
            msg = t(lang, "panel_got", role=role.name)
        elif removed_target:
            msg = t(lang, "panel_removed", role=role.name)
        else:
            msg = t(lang, "panel_updated")
        await self._pf(interaction, msg)

    async def _panel_select(self, interaction, lang, guild, member, member_ids,
                            chosen, panel_ids, mode, unique) -> None:
        add_ids, rem_ids = compute_select(member_ids, chosen, panel_ids, mode, unique)
        add_roles = self._filter_roles(guild, add_ids)
        rem_roles = self._filter_roles(guild, rem_ids)
        if not add_roles and not rem_roles:
            return await self._pf(interaction, t(lang, "panel_none"))
        if not await self._panel_apply(member, add_roles, rem_roles):
            return await self._pf(interaction, t(lang, "panel_failed"))
        parts = []
        if add_roles:
            parts.append(t(lang, "panel_part_added", roles=", ".join(r.name for r in add_roles)))
        if rem_roles:
            parts.append(t(lang, "panel_part_removed", roles=", ".join(r.name for r in rem_roles)))
        await self._pf(interaction, " • ".join(parts) if parts else t(lang, "panel_none"))

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

    # ----------------------------------------------------------------- #
    #  Befehle: Rollen-Panels (Text; Feinkonfiguration im Dashboard)
    # ----------------------------------------------------------------- #
    @autorole.group(name="panel", with_app_command=False, invoke_without_command=True)
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_panel(self, ctx: commands.Context):
        """Rollen-Panels (Buttons/Dropdown) verwalten – Details im Dashboard."""
        await ctx.send_help()

    @autorole_panel.command(name="list", with_app_command=False)
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_panel_list(self, ctx: commands.Context):
        """Listet alle Rollen-Panels des Servers."""
        panels = await self.config.guild(ctx.guild).panels()
        lang = await self._lang(ctx.guild)
        if not panels:
            return await self._say(ctx, "panel_list_empty", p=ctx.clean_prefix)
        lines = [t(lang, "panel_list_header")]
        for pid, p in panels.items():
            ch = ctx.guild.get_channel(int(p["channel_id"])) if p.get("channel_id") else None
            chname = ch.mention if isinstance(ch, discord.TextChannel) else t(lang, "panel_no_channel_short")
            status = t(lang, "panel_status_posted" if p.get("message_id") else "panel_status_unposted")
            uniq = " • unique" if p.get("unique") else ""
            lines.append(
                f"`{pid}` • **{p['name']}** • {chname} • {p.get('style')}/{p.get('mode')}{uniq}"
                f" • {len(p.get('roles', []))} Rollen • {status}"
            )
        await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())

    @autorole_panel.command(name="create", with_app_command=False)
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_panel_create(self, ctx: commands.Context, *, name: str):
        """Erstellt ein neues (leeres) Panel mit einem Namen."""
        panel = new_panel(name)
        async with self.config.guild(ctx.guild).panels() as panels:
            panels[panel["id"]] = panel
        await self._say(ctx, "panel_created", name=panel["name"], id=panel["id"], p=ctx.clean_prefix)

    @autorole_panel.command(name="addrole", with_app_command=False)
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_panel_addrole(self, ctx: commands.Context, panel_id: str, *, role: discord.Role):
        """Fügt eine Rolle zu einem Panel hinzu (Label = Rollenname)."""
        panel = await self._get_panel(ctx.guild, panel_id)
        if panel is None:
            return await self._say(ctx, "panel_not_found", id=panel_id)
        reason = self._assignable_reason(ctx.guild, role)
        if reason is not None:
            lang = await self._lang(ctx.guild)
            return await ctx.send(t(lang, "add_unassignable", role=role.name, reason=t(lang, reason)))
        if any(int(r["role_id"]) == role.id for r in panel.get("roles", [])):
            return await self._say(ctx, "panel_role_exists", role=role.name, name=panel["name"])
        if len(panel.get("roles", [])) >= MAX_ROLES:
            return await self._say(ctx, "panel_role_full", max=MAX_ROLES)
        async with self.config.guild(ctx.guild).panels() as panels:
            panels[panel_id]["roles"].append(
                {"role_id": role.id, "label": role.name[:80], "emoji": "", "style": "secondary", "description": ""}
            )
        await self._panel_refresh(ctx.guild, panel_id)
        await self._say(ctx, "panel_role_added", role=role.name, name=panel["name"])

    @autorole_panel.command(name="removerole", with_app_command=False)
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_panel_removerole(self, ctx: commands.Context, panel_id: str, *, role: discord.Role):
        """Entfernt eine Rolle aus einem Panel."""
        panel = await self._get_panel(ctx.guild, panel_id)
        if panel is None:
            return await self._say(ctx, "panel_not_found", id=panel_id)
        if not any(int(r["role_id"]) == role.id for r in panel.get("roles", [])):
            return await self._say(ctx, "panel_role_not_in", role=role.name, name=panel["name"])
        async with self.config.guild(ctx.guild).panels() as panels:
            panels[panel_id]["roles"] = [
                r for r in panels[panel_id]["roles"] if int(r["role_id"]) != role.id
            ]
        await self._panel_refresh(ctx.guild, panel_id)
        await self._say(ctx, "panel_role_removed", role=role.name, name=panel["name"])

    @autorole_panel.command(name="post", with_app_command=False)
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_panel_post(self, ctx: commands.Context, panel_id: str,
                                  channel: discord.TextChannel = None):
        """Postet bzw. aktualisiert ein Panel (optional in einem anderen Kanal)."""
        panel = await self._get_panel(ctx.guild, panel_id)
        if panel is None:
            return await self._say(ctx, "panel_not_found", id=panel_id)
        if channel is not None:
            async with self.config.guild(ctx.guild).panels() as panels:
                panels[panel_id]["channel_id"] = channel.id
            panel = await self._get_panel(ctx.guild, panel_id)
        ok, key = await self._panel_post(ctx.guild, panel)
        lang = await self._lang(ctx.guild)
        if ok:
            reloaded = await self._get_panel(ctx.guild, panel_id)
            ch = ctx.guild.get_channel(int(reloaded["channel_id"])) if reloaded.get("channel_id") else None
            chname = ch.mention if isinstance(ch, discord.TextChannel) else "?"
            await ctx.send(t(lang, "panel_posted", name=panel["name"], channel=chname),
                           allowed_mentions=discord.AllowedMentions.none())
        else:
            await ctx.send(t(lang, key, name=panel["name"], id=panel_id, p=ctx.clean_prefix),
                           allowed_mentions=discord.AllowedMentions.none())

    @autorole_panel.command(name="delete", with_app_command=False)
    @commands.admin_or_permissions(manage_roles=True)
    async def autorole_panel_delete(self, ctx: commands.Context, panel_id: str):
        """Löscht ein Panel (und seine bereits gepostete Nachricht)."""
        panel = await self._get_panel(ctx.guild, panel_id)
        if panel is None:
            return await self._say(ctx, "panel_not_found", id=panel_id)
        await self._panel_delete_message(ctx.guild, panel)
        async with self.config.guild(ctx.guild).panels() as panels:
            panels.pop(panel_id, None)
        await self._say(ctx, "panel_deleted", name=panel["name"])
