import asyncio
import html
import inspect
import logging
import time
from typing import Optional, Union

import discord

from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.red-cogs.autoroom")

DEFAULT_TEMPLATE = "🔊 {user}"
VIS_LABELS = {"public": "Öffentlich", "locked": "Gesperrt", "private": "Privat"}
VIS_CHOICES = ("public", "locked", "private")


def _source_defaults() -> dict:
    """Standardwerte für eine neue Quelle."""
    return {
        "dest_category": None,        # None = gleiche Kategorie wie die Quelle
        "name_template": DEFAULT_TEMPLATE,
        "user_limit": 0,              # 0 = unbegrenzt
        "bitrate_kbps": None,         # None = Server-Standard
        "default_visibility": "public",
        "text_channel": False,        # zusätzlicher Textkanal pro Raum
    }


class AutoRoom(commands.Cog):
    """Automatische Voicechannels (Autovoiceroom).

    Joint jemand einen festgelegten Quell-Channel, erstellt der Bot einen
    eigenen Voicechannel und verschiebt die Person hinein. Sobald der Raum
    leer ist, wird er automatisch wieder gelöscht. Eingerichtet wird alles
    bequem über das WebCore-Dashboard oder per Befehl.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736014928503, force_registration=True)
        self.config.register_guild(
            sources={},        # { "<source_channel_id>": {<einstellungen>} }
            active_rooms={},   # { "<room_channel_id>": {owner_id, source_id, text_id, created_at} }
            admin_access=True, # dürfen Admin-Rollen private/gesperrte Räume sehen?
            mod_access=False,  # dürfen Mod-Rollen private/gesperrte Räume sehen?
        )
        self._locks: dict[int, asyncio.Lock] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (Muster aus `example`)
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._cleanup_task = asyncio.create_task(self._initial_cleanup())

    async def cog_unload(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="autoroom",
            name="Autovoiceroom",
            icon="bi-mic",
            handler=self.dashboard_page,
        )

    # ----------------------------------------------------------------- #
    #  Hilfsfunktionen
    # ----------------------------------------------------------------- #
    def _lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    def _render_name(self, template: str, member: discord.Member, category) -> str:
        """Platzhalter ersetzen: {user}, {game}, {num}. Ohne externe Abhängigkeiten."""
        game = ""
        for act in getattr(member, "activities", []) or []:
            if getattr(act, "type", None) == discord.ActivityType.playing and getattr(act, "name", None):
                game = act.name
                break

        def render(num: int) -> str:
            out = template or DEFAULT_TEMPLATE
            out = out.replace("{user}", member.display_name)
            out = out.replace("{game}", game)
            out = out.replace("{num}", str(num))
            out = out.strip()[:100]
            return out or member.display_name[:100]

        if "{num}" not in (template or ""):
            return render(1)

        if isinstance(category, discord.CategoryChannel):
            existing = {c.name for c in category.voice_channels}
        else:
            existing = {c.name for c in member.guild.voice_channels}
        for n in range(1, 100):
            cand = render(n)
            if cand not in existing:
                return cand
        return render(1)

    async def _staff_role_ids(self, guild: discord.Guild, *, mod: bool = False) -> set[int]:
        """Admin- bzw. Mod-Rollen ermitteln (Red-Helfer, sonst Berechtigungs-Fallback)."""
        ids: set[int] = set()
        getter = getattr(self.bot, "get_mod_role_ids" if mod else "get_admin_role_ids", None)
        if getter is not None:
            try:
                res = getter(guild.id)
                if inspect.isawaitable(res):
                    res = await res
                ids.update(res or [])
                return ids
            except Exception:  # noqa: BLE001
                pass
        for role in guild.roles:
            if not mod and role.permissions.administrator:
                ids.add(role.id)
            elif mod and (role.permissions.manage_guild or role.permissions.manage_channels):
                ids.add(role.id)
        return ids

    async def _build_overwrites(self, guild, owner, visibility):
        everyone = guild.default_role
        me = guild.me
        ow = {
            me: discord.PermissionOverwrite(
                view_channel=True, connect=True, manage_channels=True, move_members=True
            )
        }
        if visibility == "private":
            ow[everyone] = discord.PermissionOverwrite(view_channel=False, connect=False)
        elif visibility == "locked":
            ow[everyone] = discord.PermissionOverwrite(view_channel=True, connect=False)
        else:
            ow[everyone] = discord.PermissionOverwrite(view_channel=True, connect=True)
        ow[owner] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)

        if visibility in ("private", "locked"):
            data = await self.config.guild(guild).all()
            role_ids: set[int] = set()
            if data.get("admin_access", True):
                role_ids |= await self._staff_role_ids(guild, mod=False)
            if data.get("mod_access", False):
                role_ids |= await self._staff_role_ids(guild, mod=True)
            for rid in role_ids:
                role = guild.get_role(rid)
                if role is not None and role != everyone:
                    ow[role] = discord.PermissionOverwrite(view_channel=True, connect=True)
        return ow

    async def _require_owned(self, ctx):
        """Gibt (channel, record) zurück, wenn ctx.author Besitzer seines AutoRooms ist."""
        vc = ctx.author.voice.channel if ctx.author.voice else None
        if vc is None:
            await ctx.send("Du bist in keinem Voicechannel.")
            return None
        rooms = await self.config.guild(ctx.guild).active_rooms()
        rec = rooms.get(str(vc.id))
        if rec is None:
            await ctx.send("Dein aktueller Channel ist kein AutoRoom.")
            return None
        # Bot-Owner darf jeden Raum verwalten.
        if rec.get("owner_id") != ctx.author.id and not await self.bot.is_owner(ctx.author):
            await ctx.send(
                "Das ist nicht dein AutoRoom. Falls der Besitzer weg ist, "
                f"kannst du ihn mit `{ctx.clean_prefix}autoroom claim` übernehmen."
            )
            return None
        return vc, rec

    # ----------------------------------------------------------------- #
    #  Kern: Voice-Events, Erstellen, Aufräumen
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or member.guild is None:
            return
        if before.channel and before.channel != after.channel:
            await self._sync_text_access(member, before.channel, joined=False)
            await self._maybe_cleanup_room(before.channel)
        if after.channel and after.channel != before.channel:
            sources = await self.config.guild(member.guild).sources()
            cfg = sources.get(str(after.channel.id))
            if cfg is not None and await self.bot.cog_disabled_in_guild(self, member.guild):
                cfg = None  # Cog im Server deaktiviert: keine neuen Räume (Aufräumen läuft weiter)
            if cfg is not None:
                await self._create_room_for(member, after.channel, cfg)
            else:
                # Beitritt zu einem bestehenden AutoRoom -> Zugriff auf dessen Textkanal
                await self._sync_text_access(member, after.channel, joined=True)

    async def _create_room_for(self, member, source, cfg):
        guild = member.guild
        me = guild.me
        if not (me.guild_permissions.manage_channels and me.guild_permissions.move_members):
            log.warning(
                "AutoRoom: fehlende Rechte in %s (Manage Channels / Move Members).", guild.id
            )
            return

        async with self._lock(guild.id):
            category = None
            if cfg.get("dest_category"):
                category = guild.get_channel(int(cfg["dest_category"]))
            if not isinstance(category, discord.CategoryChannel):
                category = source.category

            visibility = cfg.get("default_visibility", "public")
            name = self._render_name(cfg.get("name_template", DEFAULT_TEMPLATE), member, category)
            overwrites = await self._build_overwrites(guild, member, visibility)

            kwargs = {
                "category": category,
                "overwrites": overwrites,
                "reason": f"AutoRoom für {member}",
            }
            limit = int(cfg.get("user_limit", 0) or 0)
            if limit > 0:
                kwargs["user_limit"] = min(max(limit, 0), 99)
            bitrate = cfg.get("bitrate_kbps")
            if bitrate:
                kwargs["bitrate"] = min(int(bitrate) * 1000, int(guild.bitrate_limit))

            try:
                channel = await guild.create_voice_channel(name, **kwargs)
            except discord.HTTPException:
                log.exception("AutoRoom-Channel konnte nicht erstellt werden.")
                return

            try:
                await member.move_to(channel, reason="AutoRoom")
            except discord.HTTPException:
                try:
                    await channel.delete(reason="AutoRoom: Nutzer war nicht mehr im Voice.")
                except discord.HTTPException:
                    pass
                return

            text_id = None
            if cfg.get("text_channel"):
                try:
                    t_over = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        member: discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, read_message_history=True
                        ),
                        me: discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, manage_channels=True
                        ),
                    }
                    # Staff-Rollen (wie beim Voice-Raum) dürfen den Textkanal immer sehen.
                    data = await self.config.guild(guild).all()
                    staff_ids: set[int] = set()
                    if data.get("admin_access", True):
                        staff_ids |= await self._staff_role_ids(guild, mod=False)
                    if data.get("mod_access", False):
                        staff_ids |= await self._staff_role_ids(guild, mod=True)
                    for rid in staff_ids:
                        role = guild.get_role(rid)
                        if role is not None and role != guild.default_role:
                            t_over[role] = discord.PermissionOverwrite(
                                view_channel=True, send_messages=True, read_message_history=True
                            )
                    tch = await guild.create_text_channel(
                        name, category=category, overwrites=t_over, reason="AutoRoom-Textkanal"
                    )
                    text_id = tch.id
                except discord.HTTPException:
                    text_id = None

            rooms = await self.config.guild(guild).active_rooms()
            rooms[str(channel.id)] = {
                "owner_id": member.id,
                "source_id": source.id,
                "text_id": text_id,
                "created_at": time.time(),
            }
            await self.config.guild(guild).active_rooms.set(rooms)

    async def _sync_text_access(self, member, channel, *, joined: bool):
        """Gibt/entzieht dem Mitglied Zugriff auf den Textkanal seines AutoRooms.

        Wer dem Voice-Raum beitritt, kann den zugehörigen Textkanal nutzen;
        beim Verlassen wird der Zugriff wieder entfernt. Der Besitzer behält
        seinen Zugriff (er kommt evtl. gleich zurück; leert sich der Raum,
        wird er ohnehin gelöscht).
        """
        if not isinstance(channel, discord.VoiceChannel):
            return
        guild = channel.guild
        rooms = await self.config.guild(guild).active_rooms()
        rec = rooms.get(str(channel.id))
        if not rec or not rec.get("text_id"):
            return
        tch = guild.get_channel(int(rec["text_id"]))
        if not isinstance(tch, discord.TextChannel):
            return
        try:
            if joined:
                await tch.set_permissions(
                    member,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    ),
                    reason="AutoRoom: Voice beigetreten",
                )
            elif member.id != rec.get("owner_id"):
                await tch.set_permissions(
                    member, overwrite=None, reason="AutoRoom: Voice verlassen"
                )
        except discord.HTTPException:
            pass

    async def _maybe_cleanup_room(self, channel):
        if not isinstance(channel, discord.VoiceChannel):
            return
        guild = channel.guild
        async with self._lock(guild.id):
            rooms = await self.config.guild(guild).active_rooms()
            rec = rooms.get(str(channel.id))
            if rec is None:
                return
            if any(not m.bot for m in channel.members):
                return
            await self._delete_room(guild, channel, rec, "AutoRoom leer")
            rooms.pop(str(channel.id), None)
            await self.config.guild(guild).active_rooms.set(rooms)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Raum von Hand gelöscht -> Datensatz + zugehörigen Textkanal sofort aufräumen.

        Vorher blieb der Textkanal eines manuell gelöschten Raums für immer liegen.
        """
        if not isinstance(channel, discord.VoiceChannel):
            return
        guild = channel.guild
        async with self._lock(guild.id):
            rooms = await self.config.guild(guild).active_rooms()
            rec = rooms.pop(str(channel.id), None)
            if rec is None:
                return
            await self._delete_room(guild, None, rec, "AutoRoom gelöscht")
            await self.config.guild(guild).active_rooms.set(rooms)

    async def _delete_room(self, guild, channel, rec, reason):
        text_id = rec.get("text_id")
        if text_id:
            tch = guild.get_channel(int(text_id))
            if tch is not None:
                try:
                    await tch.delete(reason=reason)
                except discord.HTTPException:
                    pass
        if channel is not None:
            try:
                await channel.delete(reason=reason)
            except discord.HTTPException:
                pass

    async def _initial_cleanup(self):
        try:
            await self.bot.wait_until_red_ready()
        except Exception:  # noqa: BLE001
            return
        for guild in self.bot.guilds:
            try:
                await self._sweep_guild(guild)
            except Exception:  # noqa: BLE001
                log.exception("AutoRoom-Cleanup fehlgeschlagen in %s.", guild.id)

    async def _sweep_guild(self, guild) -> int:
        removed = 0
        async with self._lock(guild.id):
            rooms = await self.config.guild(guild).active_rooms()
            changed = False
            for cid, rec in list(rooms.items()):
                ch = guild.get_channel(int(cid))
                if ch is None:
                    # Voice-Raum weg -> auch den evtl. verwaisten Textkanal entfernen.
                    await self._delete_room(guild, None, rec, "AutoRoom-Cleanup")
                    rooms.pop(cid, None)
                    changed = True
                    continue
                if not any(not m.bot for m in ch.members):
                    await self._delete_room(guild, ch, rec, "AutoRoom-Cleanup")
                    rooms.pop(cid, None)
                    changed = True
                    removed += 1
            if changed:
                await self.config.guild(guild).active_rooms.set(rooms)
        return removed

    # ----------------------------------------------------------------- #
    #  Nutzer-Befehle: eigenen Raum verwalten  (hybrid = Text + Slash)
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="autoroom", invoke_without_command=True)
    @commands.guild_only()
    async def autoroom(self, ctx: commands.Context):
        """Verwalte deinen eigenen AutoRoom."""
        await ctx.send_help()

    @autoroom.command(name="settings")
    async def ar_settings(self, ctx: commands.Context):
        """Zeigt die Einstellungen deines aktuellen AutoRooms."""
        vc = ctx.author.voice.channel if ctx.author.voice else None
        if vc is None:
            await ctx.send("Du bist in keinem Voicechannel.")
            return
        rooms = await self.config.guild(ctx.guild).active_rooms()
        rec = rooms.get(str(vc.id))
        if rec is None:
            await ctx.send("Dein aktueller Channel ist kein AutoRoom.")
            return
        ow = vc.overwrites_for(ctx.guild.default_role)
        if ow.view_channel is False:
            vis = "Privat"
        elif ow.connect is False:
            vis = "Gesperrt"
        else:
            vis = "Öffentlich"
        owner = ctx.guild.get_member(rec.get("owner_id"))
        limit = vc.user_limit or "unbegrenzt"
        embed = discord.Embed(title=f"AutoRoom: {vc.name}", color=await ctx.embed_color())
        embed.add_field(name="Besitzer", value=owner.mention if owner else "—")
        embed.add_field(name="Sichtbarkeit", value=vis)
        embed.add_field(name="Limit", value=str(limit))
        embed.add_field(name="Mitglieder", value=str(len([m for m in vc.members if not m.bot])))
        await ctx.send(embed=embed)

    async def _set_visibility(self, ctx, vc, visibility):
        everyone = ctx.guild.default_role
        if visibility == "private":
            ow = discord.PermissionOverwrite(view_channel=False, connect=False)
        elif visibility == "locked":
            ow = discord.PermissionOverwrite(view_channel=True, connect=False)
        else:
            ow = discord.PermissionOverwrite(view_channel=True, connect=True)
        try:
            await vc.set_permissions(everyone, overwrite=ow, reason=f"AutoRoom: {visibility}")
        except discord.HTTPException:
            await ctx.send("Konnte die Berechtigungen nicht ändern (fehlende Rechte?).")
            return False
        return True

    @autoroom.command(name="public")
    async def ar_public(self, ctx: commands.Context):
        """Macht deinen Raum öffentlich (jeder sieht und joint)."""
        owned = await self._require_owned(ctx)
        if owned and await self._set_visibility(ctx, owned[0], "public"):
            await ctx.send("Raum ist jetzt **öffentlich**.")

    @autoroom.command(name="locked")
    async def ar_locked(self, ctx: commands.Context):
        """Sperrt deinen Raum (sichtbar, aber niemand kann joinen)."""
        owned = await self._require_owned(ctx)
        if owned and await self._set_visibility(ctx, owned[0], "locked"):
            await ctx.send("Raum ist jetzt **gesperrt**.")

    @autoroom.command(name="private")
    async def ar_private(self, ctx: commands.Context):
        """Macht deinen Raum privat (unsichtbar, niemand joint)."""
        owned = await self._require_owned(ctx)
        if owned and await self._set_visibility(ctx, owned[0], "private"):
            await ctx.send("Raum ist jetzt **privat**.")

    @autoroom.command(name="name")
    async def ar_name(self, ctx: commands.Context, *, name: str):
        """Benennt deinen Raum um."""
        owned = await self._require_owned(ctx)
        if not owned:
            return
        try:
            await owned[0].edit(name=name[:100], reason="AutoRoom umbenannt")
            await ctx.send(f"Raum heißt jetzt **{name[:100]}**.")
        except discord.HTTPException:
            await ctx.send(
                "Umbenennen fehlgeschlagen. Discord erlaubt nur wenige Umbenennungen "
                "in kurzer Zeit – bitte gleich nochmal versuchen."
            )

    @autoroom.command(name="limit")
    async def ar_limit(self, ctx: commands.Context, limit: int):
        """Setzt das Nutzerlimit (0 = unbegrenzt)."""
        owned = await self._require_owned(ctx)
        if not owned:
            return
        limit = min(max(limit, 0), 99)
        try:
            await owned[0].edit(user_limit=limit, reason="AutoRoom-Limit")
            await ctx.send(f"Limit auf **{limit or 'unbegrenzt'}** gesetzt.")
        except discord.HTTPException:
            await ctx.send("Limit konnte nicht gesetzt werden.")

    @autoroom.command(name="bitrate")
    async def ar_bitrate(self, ctx: commands.Context, kbps: int):
        """Setzt die Bitrate in kbps."""
        owned = await self._require_owned(ctx)
        if not owned:
            return
        value = min(max(kbps, 8) * 1000, int(ctx.guild.bitrate_limit))
        try:
            await owned[0].edit(bitrate=value, reason="AutoRoom-Bitrate")
            await ctx.send(f"Bitrate auf **{value // 1000} kbps** gesetzt.")
        except discord.HTTPException:
            await ctx.send("Bitrate konnte nicht gesetzt werden.")

    @autoroom.command(name="allow")
    async def ar_allow(self, ctx: commands.Context, target: Union[discord.Member, discord.Role]):
        """Erlaubt einem Nutzer oder einer Rolle den Zutritt."""
        owned = await self._require_owned(ctx)
        if not owned:
            return
        try:
            await owned[0].set_permissions(
                target, overwrite=discord.PermissionOverwrite(view_channel=True, connect=True)
            )
            await ctx.send(f"{getattr(target, 'mention', target)} darf jetzt rein.")
        except discord.HTTPException:
            await ctx.send("Konnte die Berechtigung nicht setzen.")

    @autoroom.command(name="deny")
    async def ar_deny(self, ctx: commands.Context, target: Union[discord.Member, discord.Role]):
        """Verweigert einem Nutzer/einer Rolle den Zutritt (und wirft anwesende raus)."""
        owned = await self._require_owned(ctx)
        if not owned:
            return
        vc = owned[0]
        try:
            await vc.set_permissions(
                target, overwrite=discord.PermissionOverwrite(view_channel=False, connect=False)
            )
        except discord.HTTPException:
            await ctx.send("Konnte die Berechtigung nicht setzen.")
            return
        if isinstance(target, discord.Member) and target.voice and target.voice.channel == vc:
            try:
                await target.move_to(None, reason="AutoRoom: deny")
            except discord.HTTPException:
                pass
        await ctx.send(f"{getattr(target, 'mention', target)} ist jetzt ausgesperrt.")

    @autoroom.command(name="claim")
    async def ar_claim(self, ctx: commands.Context):
        """Übernimmt einen AutoRoom, dessen Besitzer nicht mehr drin ist."""
        vc = ctx.author.voice.channel if ctx.author.voice else None
        if vc is None:
            await ctx.send("Du bist in keinem Voicechannel.")
            return
        # Unter dem Guild-Lock frisch lesen und nur den betroffenen Key ändern,
        # damit es keinen Race mit dem Cleanup gibt (verlorene Updates).
        async with self._lock(ctx.guild.id):
            rooms = await self.config.guild(ctx.guild).active_rooms()
            rec = rooms.get(str(vc.id))
            if rec is None:
                await ctx.send("Dein aktueller Channel ist kein AutoRoom.")
                return
            owner = ctx.guild.get_member(rec.get("owner_id"))
            if owner is not None and owner in vc.members:
                await ctx.send("Der Besitzer ist noch im Raum – Übernahme nicht möglich.")
                return
            rec["owner_id"] = ctx.author.id
            rooms[str(vc.id)] = rec
            await self.config.guild(ctx.guild).active_rooms.set(rooms)
        try:
            await vc.set_permissions(
                ctx.author, overwrite=discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
            )
        except discord.HTTPException:
            pass
        await ctx.send("Du bist jetzt der Besitzer dieses AutoRooms.")

    @autoroom.command(name="transfer")
    async def ar_transfer(self, ctx: commands.Context, member: discord.Member):
        """Übergibt den Raum an ein anderes Mitglied im Raum."""
        owned = await self._require_owned(ctx)
        if not owned:
            return
        vc, _rec = owned
        if member not in vc.members:
            await ctx.send("Diese Person ist nicht in deinem Raum.")
            return
        # Unter dem Guild-Lock frisch lesen (Existenz erneut prüfen) und nur den
        # betroffenen Key ändern – kein Race mit dem Cleanup.
        async with self._lock(ctx.guild.id):
            rooms = await self.config.guild(ctx.guild).active_rooms()
            rec = rooms.get(str(vc.id))
            if rec is None:
                await ctx.send("Dein aktueller Channel ist kein AutoRoom.")
                return
            rec["owner_id"] = member.id
            rooms[str(vc.id)] = rec
            await self.config.guild(ctx.guild).active_rooms.set(rooms)
        try:
            await vc.set_permissions(
                member, overwrite=discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
            )
        except discord.HTTPException:
            pass
        await ctx.send(f"{member.mention} ist jetzt der Besitzer.")

    # ----------------------------------------------------------------- #
    #  Admin-Befehle: Quellen einrichten
    # ----------------------------------------------------------------- #
    @commands.group(name="autoroomset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def autoroomset(self, ctx: commands.Context):
        """Einrichtung der AutoRoom-Quellen (auch bequem im Dashboard)."""

    async def _update_source(self, guild, voice_id: int, **changes) -> bool:
        sources = await self.config.guild(guild).sources()
        cfg = sources.get(str(voice_id))
        if cfg is None:
            return False
        cfg.update(changes)
        sources[str(voice_id)] = cfg
        await self.config.guild(guild).sources.set(sources)
        return True

    @autoroomset.command(name="addsource")
    async def arset_addsource(
        self,
        ctx: commands.Context,
        source: discord.VoiceChannel,
        category: Optional[discord.CategoryChannel] = None,
    ):
        """Legt eine Quelle an. Neue Räume entstehen in <category> (sonst Quell-Kategorie)."""
        sources = await self.config.guild(ctx.guild).sources()
        if str(source.id) in sources:
            await ctx.send("Dieser Channel ist bereits eine Quelle.")
            return
        cfg = _source_defaults()
        if category is not None:
            cfg["dest_category"] = category.id
        sources[str(source.id)] = cfg
        await self.config.guild(ctx.guild).sources.set(sources)
        await ctx.send(
            f"Quelle **{source.name}** angelegt. Weitere Optionen über `[p]autoroomset` "
            f"oder im Dashboard."
        )

    @autoroomset.command(name="removesource")
    async def arset_removesource(self, ctx: commands.Context, source: discord.VoiceChannel):
        """Entfernt eine Quelle (bestehende Räume bleiben erhalten)."""
        sources = await self.config.guild(ctx.guild).sources()
        if sources.pop(str(source.id), None) is None:
            await ctx.send("Dieser Channel ist keine Quelle.")
            return
        await self.config.guild(ctx.guild).sources.set(sources)
        await ctx.send(f"Quelle **{source.name}** entfernt.")

    @autoroomset.command(name="name")
    async def arset_name(self, ctx: commands.Context, source: discord.VoiceChannel, *, template: str):
        """Setzt die Namensvorlage. Platzhalter: {user}, {game}, {num}."""
        if await self._update_source(ctx.guild, source.id, name_template=template[:100]):
            await ctx.send(f"Vorlage für **{source.name}**: `{template[:100]}`")
        else:
            await ctx.send("Dieser Channel ist keine Quelle.")

    @autoroomset.command(name="limit")
    async def arset_limit(self, ctx: commands.Context, source: discord.VoiceChannel, limit: int):
        """Standard-Nutzerlimit für Räume dieser Quelle (0 = unbegrenzt)."""
        if await self._update_source(ctx.guild, source.id, user_limit=min(max(limit, 0), 99)):
            await ctx.send(f"Limit für **{source.name}**: {min(max(limit, 0), 99) or 'unbegrenzt'}")
        else:
            await ctx.send("Dieser Channel ist keine Quelle.")

    @autoroomset.command(name="bitrate")
    async def arset_bitrate(self, ctx: commands.Context, source: discord.VoiceChannel, kbps: int):
        """Standard-Bitrate in kbps (0 = Server-Standard)."""
        value = None if kbps <= 0 else min(max(kbps, 8), int(ctx.guild.bitrate_limit) // 1000)
        if await self._update_source(ctx.guild, source.id, bitrate_kbps=value):
            await ctx.send(f"Bitrate für **{source.name}**: {value or 'Server-Standard'}")
        else:
            await ctx.send("Dieser Channel ist keine Quelle.")

    @autoroomset.command(name="visibility")
    async def arset_visibility(self, ctx: commands.Context, source: discord.VoiceChannel, modus: str):
        """Standard-Sichtbarkeit: public / locked / private."""
        modus = modus.lower()
        if modus not in VIS_CHOICES:
            await ctx.send("Bitte `public`, `locked` oder `private` angeben.")
            return
        if await self._update_source(ctx.guild, source.id, default_visibility=modus):
            await ctx.send(f"Sichtbarkeit für **{source.name}**: {VIS_LABELS[modus]}")
        else:
            await ctx.send("Dieser Channel ist keine Quelle.")

    @autoroomset.command(name="textchannel")
    async def arset_textchannel(self, ctx: commands.Context, source: discord.VoiceChannel, an: bool):
        """Zusätzlichen Textkanal pro Raum an-/ausschalten (true/false)."""
        if await self._update_source(ctx.guild, source.id, text_channel=an):
            await ctx.send(f"Textkanal für **{source.name}**: {'an' if an else 'aus'}")
        else:
            await ctx.send("Dieser Channel ist keine Quelle.")

    @autoroomset.command(name="access")
    async def arset_access(self, ctx: commands.Context, gruppe: str, an: bool):
        """Dürfen Admin-/Mod-Rollen private Räume sehen? gruppe: admin / mod."""
        gruppe = gruppe.lower()
        if gruppe == "admin":
            await self.config.guild(ctx.guild).admin_access.set(an)
        elif gruppe == "mod":
            await self.config.guild(ctx.guild).mod_access.set(an)
        else:
            await ctx.send("Bitte `admin` oder `mod` angeben.")
            return
        await ctx.send(f"Zugriff für {gruppe}-Rollen: {'an' if an else 'aus'} (gilt für neue Räume).")

    @autoroomset.command(name="cleanup")
    async def arset_cleanup(self, ctx: commands.Context):
        """Räumt verwaiste, leere AutoRooms in diesem Server auf."""
        removed = await self._sweep_guild(ctx.guild)
        await ctx.send(f"{removed} verwaiste(r) Raum/Räume aufgeräumt.")

    @autoroomset.command(name="settings", aliases=["list"])
    async def arset_settings(self, ctx: commands.Context):
        """Zeigt alle Quellen und Einstellungen dieses Servers."""
        data = await self.config.guild(ctx.guild).all()
        sources = data.get("sources", {})
        if not sources:
            await ctx.send("Noch keine Quellen angelegt. Mit `[p]autoroomset addsource` starten.")
            return
        lines = []
        for cid, cfg in sources.items():
            ch = ctx.guild.get_channel(int(cid))
            cat = ctx.guild.get_channel(int(cfg["dest_category"])) if cfg.get("dest_category") else None
            lines.append(
                f"**{ch.name if ch else 'unbekannt'}** → Kategorie: "
                f"{cat.name if cat else 'wie Quelle'} · Vorlage: `{cfg.get('name_template')}` · "
                f"Limit: {cfg.get('user_limit') or '∞'} · Sicht: {VIS_LABELS.get(cfg.get('default_visibility'), '?')} · "
                f"Text: {'an' if cfg.get('text_channel') else 'aus'}"
            )
        lines.append(
            f"\nZugriff private Räume — Admin: {'an' if data.get('admin_access') else 'aus'}, "
            f"Mod: {'an' if data.get('mod_access') else 'aus'}"
        )
        await ctx.send("\n".join(lines))

    # ----------------------------------------------------------------- #
    #  Dashboard-Seite (Anzeige + Einstellungen per Formular)
    #  Aufbau mit dem WebCore-UI-Kit: Reiter Quellen · Aktive Räume · Zugriff
    # ----------------------------------------------------------------- #
    _SOURCE_HELP = (
        "<b>Platzhalter</b> in Namensvorlagen: <code>{user}</code> Name des Erstellers, "
        "<code>{game}</code> aktuelles Spiel, <code>{num}</code> fortlaufende Nummer.<br>"
        "<b>Sichtbarkeit</b>: <b>Öffentlich</b> = alle sehen und betreten den Raum · "
        "<b>Gesperrt</b> = sichtbar, betreten nur mit Freigabe · <b>Privat</b> = unsichtbar ohne Freigabe."
    )

    async def _visible_guilds(self, request):
        webcore = request.app.get("webcore")
        if webcore is not None:
            guilds = await webcore.visible_guilds(request)
        else:  # Fallback (sollte im Normalbetrieb nicht eintreten)
            guilds = list(self.bot.guilds)
        return sorted(guilds, key=lambda g: g.name.lower())

    def _source_fields(self, ui, guild, cfg, *, bitrate: bool, lead: str = "") -> str:
        """Gemeinsame Felder für „Quelle bearbeiten“ und „Neue Quelle“ (gleiche Feldnamen wie bisher)."""
        cat_items = [(c.id, c.name) for c in guild.categories]
        vis_items = [(k, VIS_LABELS[k]) for k in VIS_CHOICES]
        fields = [lead] if lead else []
        fields += [
            ui.field("Ziel-Kategorie", ui.select("category_id", cat_items, cfg.get("dest_category"),
                                                 none_label="wie Quell-Channel"),
                     help="Hier entstehen die neuen Räume."),
            ui.field("Sichtbarkeit", ui.select("visibility", vis_items, cfg.get("default_visibility", "public")),
                     help="Standard für neue Räume – der Besitzer kann sie per Befehl ändern."),
            ui.field("Namensvorlage", ui.text_input("template", cfg.get("name_template", ""), placeholder="{user}"),
                     help="z. B. <code>🔊 {user}</code> oder <code>{game} #{num}</code>."),
            ui.field("Personenlimit", ui.number("limit", int(cfg.get("user_limit") or 0), min=0, max=99, unit="Personen"),
                     help="0 = unbegrenzt."),
        ]
        if bitrate:
            fields.append(ui.field(
                "Bitrate", ui.number("bitrate", cfg.get("bitrate_kbps") or "", min=8, unit="kbps"),
                help=f"Leer = Server-Standard (max. {int(guild.bitrate_limit) // 1000} kbps auf diesem Server).",
            ))
        return ui.grid(*fields, cols=3 if bitrate else 2) + "<div class='wc-switches'>" + ui.switch(
            "textchannel", "Textkanal pro Raum", cfg.get("text_channel"),
            desc="Legt zu jedem Raum einen Textkanal an, den nur die Personen im Raum sehen.",
        ) + "</div>"

    def _render_sources(self, ui, guild, data, csrf) -> str:
        sources = data.get("sources", {})
        blocks = []
        for cid, cfg in sources.items():
            ch = guild.get_channel(int(cid))
            cat = guild.get_channel(int(cfg["dest_category"])) if cfg.get("dest_category") else None
            vis = cfg.get("default_visibility", "public")
            tone = {"public": "ok", "locked": "warn", "private": "info"}.get(vis, "muted")
            desc = (
                f"Räume in <b>{html.escape(cat.name) if cat else 'gleicher Kategorie'}</b> · "
                f"{ui.badge(VIS_LABELS.get(vis, '?'), tone)}"
                + (f" {ui.badge('Textkanal', 'info')}" if cfg.get("text_channel") else "")
            )
            remove = ui.form(
                "/cogs/autoroom",
                ui.button("Entfernen", icon="bi-trash", kind="danger", small=True),
                csrf=csrf, hidden={"action": "remove", "guild_id": guild.id, "channel_id": cid},
                confirm=f"Quelle „{ch.name if ch else cid}“ entfernen? Bereits bestehende Räume bleiben erhalten.",
            )
            warn = "" if ch else ui.callout(
                f"Der Quell-Channel (ID <span class='mono'>{html.escape(str(cid))}</span>) existiert nicht mehr. "
                "Entferne die Quelle oder lege sie neu an.", tone="warn")
            edit = ui.form(
                "/cogs/autoroom",
                warn + self._source_fields(ui, guild, cfg, bitrate=True) + ui.save_row("Quelle speichern"),
                csrf=csrf, hidden={"action": "edit", "guild_id": guild.id, "channel_id": cid}, savebar=True,
            )
            title = ch.name if ch else "Gelöschter Channel"
            blocks.append(ui.card(title, edit, icon="bi-mic", desc=desc, actions=remove,
                                  tone=None if ch else "warn"))
        if not blocks:
            blocks.append(ui.card(body=ui.empty(
                "bi-mic", "Noch keine Quellen.",
                "Lege unten einen Quell-Channel an – wer ihn betritt, bekommt sofort einen eigenen Raum.")))

        excluded = set(sources.keys()) | set(data.get("active_rooms", {}).keys())
        voice_items = [(c.id, c.name) for c in guild.voice_channels if str(c.id) not in excluded]
        hint = "" if voice_items else ui.callout(
            "Alle Voicechannels sind bereits Quellen oder aktive AutoRooms. Lege in Discord einen neuen "
            "Voicechannel an (z. B. „➕ Raum erstellen“).", tone="info")
        add = ui.card(
            "Neue Quelle", ui.form(
                "/cogs/autoroom",
                hint
                + self._source_fields(
                    ui, guild, {"name_template": DEFAULT_TEMPLATE}, bitrate=True,
                    lead=ui.field("Quell-Channel", ui.select("channel_id", voice_items),
                                  help="Wer diesen Voicechannel betritt, bekommt einen eigenen Raum.", wide=True),
                )
                + ui.actions(ui.button("Quelle hinzufügen", icon="bi-plus-lg")),
                csrf=csrf, hidden={"action": "add", "guild_id": guild.id},
            ), icon="bi-plus-square",
            desc="Alle Werte lassen sich später in der Quelle ändern.",
        )
        return ui.callout(self._SOURCE_HELP, tone="info") + "".join(blocks) + add

    def _render_rooms(self, ui, guild, data) -> tuple[str, int, int]:
        sources = data.get("sources", {})
        rows, people = [], 0
        for cid, rec in data.get("active_rooms", {}).items():
            ch = guild.get_channel(int(cid))
            if ch is None:
                continue
            owner = guild.get_member(rec.get("owner_id"))
            count = len([m for m in ch.members if not m.bot])
            people += count
            src = guild.get_channel(int(rec["source_id"])) if str(rec.get("source_id") or "").isdigit() else None
            text = (" " + ui.badge("Textkanal", "info")) if rec.get("text_id") else ""
            rows.append(ui.row(
                f"<div class='wc-cell-title'>{html.escape(ch.name)}{text}</div>"
                + (f"<div class='wc-cell-sub'>über {html.escape(src.name)}</div>" if src
                   else ("<div class='wc-cell-sub'>Quelle entfernt</div>" if str(rec.get("source_id") or "") not in sources else "")),
                html.escape(owner.display_name) if owner else "—",
                f"><span class='mono'>{count}</span>",
            ))
        if rows:
            table = ui.table(["Raum", "Besitzer", ">Personen"], rows, search=len(rows) > 5,
                             search_placeholder="Raum oder Besitzer suchen …", id="ar-rooms")
        else:
            table = ui.empty("bi-mic-mute", "Gerade ist kein AutoRoom aktiv.",
                             "Räume erscheinen hier, sobald jemand einen Quell-Channel betritt.")
        rooms_card = ui.card("Aktive Räume", table, icon="bi-broadcast",
                             desc="Leere Räume (und ihr Textkanal) werden automatisch gelöscht.")
        cmds = [
            ("public · locked · private", "Sichtbarkeit des eigenen Raums ändern"),
            ("name &lt;Name&gt;", "Raum umbenennen"),
            ("limit &lt;Zahl&gt;", "Personenlimit (0 = unbegrenzt)"),
            ("bitrate &lt;kbps&gt;", "Tonqualität ändern"),
            ("allow · deny &lt;@Person/Rolle&gt;", "Zutritt erlauben bzw. entziehen"),
            ("claim", "Raum übernehmen, wenn der Besitzer weg ist"),
            ("transfer &lt;@Person&gt;", "Raum an jemand anderen übergeben"),
        ]
        help_rows = [ui.row(f"<code>autoroom {c}</code>", d) for c, d in cmds]
        help_card = ui.card("Befehle für Raumbesitzer", ui.table(["Befehl", "Wirkung"], help_rows),
                            icon="bi-terminal",
                            desc="Als Slash-Befehl <code>/autoroom …</code> oder mit Präfix – nur im eigenen Raum.")
        return rooms_card + help_card, len(rows), people

    def _render_access(self, ui, guild, data, csrf) -> str:
        return ui.form(
            "/cogs/autoroom",
            ui.card("Zugriff auf private & gesperrte Räume", "<div class='wc-switches'>"
                    + ui.switch("admin_access", "Admin-Rollen", data.get("admin_access", True),
                                desc="Admin-Rollen sehen und betreten private und gesperrte Räume.")
                    + ui.switch("mod_access", "Mod-Rollen", data.get("mod_access", False),
                                desc="Mod-Rollen sehen und betreten private und gesperrte Räume.")
                    + "</div>" + ui.save_row("Übernehmen"),
                    icon="bi-shield-lock",
                    desc="Gilt für neu erstellte Räume und deren Textkanal. Bestehende Räume bleiben unverändert."),
            csrf=csrf, hidden={"action": "access", "guild_id": guild.id}, savebar=True,
        )

    async def _render_dashboard(self, request) -> dict:
        ui = request.app["webcore"].ui
        csrf = request.get("webcore_csrf", "")

        guilds = await self._visible_guilds(request)
        if not guilds:
            return {"title": "Autovoiceroom",
                    "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}

        gid = request.query.get("guild")
        guild = self.bot.get_guild(int(gid)) if (gid and gid.isdigit()) else None
        if guild is None or guild not in guilds:
            guild = guilds[0]

        # Rückmeldung nach dem Speichern: WebCore zeigt ?ok=1 / ?err=1 als Toast und blendet
        # „*-flash“-Elemente dann aus – der Hinweis hier ist nur der Fallback ohne JavaScript.
        flash = ""
        if request.query.get("ok"):
            flash = f"<div class='ar-flash'>{ui.callout('Gespeichert.', tone='ok')}</div>"
        elif request.query.get("err"):
            flash = f"<div class='ar-flash'>{ui.callout('Eingabe ungültig – bitte prüfen.', tone='bad')}</div>"

        # Eigenes Dropdown nur, wenn WebCore (noch) keinen globalen Server-Wechsler hat.
        guild_picker = ""
        if len(guilds) > 1 and not request.get("wc_switcher"):
            guild_picker = ui.card(body=ui.form(
                "/cogs/autoroom",
                ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
                csrf="", method="get",
            ))

        data = await self.config.guild(guild).all()
        sources = data.get("sources", {})
        rooms_html, n_rooms, people = self._render_rooms(ui, guild, data)
        access = [n for n, on in (("Admins", data.get("admin_access", True)),
                                  ("Mods", data.get("mod_access", False))) if on]

        head = ui.hero(
            "bi-mic", "",
            "Wer einen <b>Quell-Channel</b> betritt, bekommt automatisch einen eigenen Voicechannel und wird "
            "hineinverschoben. Ist der Raum leer, wird er wieder gelöscht.",
        ) + ui.stats([
            ("Quellen", len(sources), "bi-mic", None, None if sources else "warn"),
            ("Aktive Räume", n_rooms, "bi-broadcast", None, "ok" if n_rooms else None),
            ("Personen in Räumen", people, "bi-people", None, None),
            ("Privat sichtbar für", " + ".join(access) or "niemand", "bi-shield-lock", None, None),
        ])

        body = (
            ui.tab("quellen", "Quellen", "bi-mic", self._render_sources(ui, guild, data, csrf), count=len(sources))
            + ui.tab("raeume", "Aktive Räume", "bi-broadcast", rooms_html, count=n_rooms)
            + ui.tab("zugriff", "Zugriff", "bi-shield-lock", self._render_access(ui, guild, data, csrf))
        )
        return {"title": "Autovoiceroom", "content": flash + guild_picker + head + body}

    async def _handle_dashboard_post(self, request) -> dict:
        form = await request.post()
        action = form.get("action")
        guilds = await self._visible_guilds(request)
        try:
            guild = self.bot.get_guild(int(form.get("guild_id")))
        except (TypeError, ValueError):
            guild = None
        if guild is None or guild not in guilds:
            return {"redirect": "/cogs/autoroom?err=1"}

        if action == "access":
            await self.config.guild(guild).admin_access.set(form.get("admin_access") == "on")
            await self.config.guild(guild).mod_access.set(form.get("mod_access") == "on")
            return {"redirect": f"/cogs/autoroom?guild={guild.id}&ok=1"}

        if action == "remove":
            sources = await self.config.guild(guild).sources()
            if sources.pop(str(form.get("channel_id")), None) is not None:
                await self.config.guild(guild).sources.set(sources)
            return {"redirect": f"/cogs/autoroom?guild={guild.id}&ok=1"}

        if action in ("add", "edit"):
            channel = guild.get_channel(int(form.get("channel_id"))) if str(form.get("channel_id") or "").isdigit() else None
            if not isinstance(channel, discord.VoiceChannel):
                return {"redirect": f"/cogs/autoroom?guild={guild.id}&err=1"}
            if str(channel.id) in (await self.config.guild(guild).active_rooms()):
                # Ein temporärer AutoRoom darf keine Quelle werden (würde sich endlos vermehren).
                return {"redirect": f"/cogs/autoroom?guild={guild.id}&err=1"}

            cat_id = form.get("category_id") or ""
            dest_category = int(cat_id) if cat_id.isdigit() else None
            if dest_category is not None and not isinstance(guild.get_channel(dest_category), discord.CategoryChannel):
                dest_category = None

            template = (form.get("template") or DEFAULT_TEMPLATE).strip()[:100] or DEFAULT_TEMPLATE
            try:
                limit = min(max(int(form.get("limit") or 0), 0), 99)
            except ValueError:
                limit = 0
            bitrate_raw = (form.get("bitrate") or "").strip()
            bitrate = None
            if bitrate_raw.isdigit() and int(bitrate_raw) > 0:
                bitrate = min(max(int(bitrate_raw), 8), int(guild.bitrate_limit) // 1000)
            visibility = form.get("visibility")
            if visibility not in VIS_CHOICES:
                visibility = "public"

            cfg = _source_defaults()
            cfg.update(
                {
                    "dest_category": dest_category,
                    "name_template": template,
                    "user_limit": limit,
                    "bitrate_kbps": bitrate,
                    "default_visibility": visibility,
                    "text_channel": form.get("textchannel") == "on",
                }
            )
            sources = await self.config.guild(guild).sources()
            sources[str(channel.id)] = cfg
            await self.config.guild(guild).sources.set(sources)
            return {"redirect": f"/cogs/autoroom?guild={guild.id}&ok=1"}

        return {"redirect": f"/cogs/autoroom?guild={guild.id}&err=1"}

    async def dashboard_page(self, request):
        if request.method == "POST":
            return await self._handle_dashboard_post(request)
        return await self._render_dashboard(request)
