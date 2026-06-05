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
        if rec.get("owner_id") != ctx.author.id:
            await ctx.send(
                "Das ist nicht dein AutoRoom. Falls der Besitzer weg ist, "
                "kannst du ihn mit `[p]autoroom claim` übernehmen."
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
            await self._maybe_cleanup_room(before.channel)
        if after.channel and after.channel != before.channel:
            sources = await self.config.guild(member.guild).sources()
            cfg = sources.get(str(after.channel.id))
            if cfg is not None:
                await self._create_room_for(member, after.channel, cfg)

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
                        member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                        me: discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, manage_channels=True
                        ),
                    }
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
        vc, rec = owned
        if member not in vc.members:
            await ctx.send("Diese Person ist nicht in deinem Raum.")
            return
        rec["owner_id"] = member.id
        rooms = await self.config.guild(ctx.guild).active_rooms()
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
    # ----------------------------------------------------------------- #
    def _voice_select(self, guild, field, selected=None, exclude=None, blank=None):
        opts = []
        if blank is not None:
            sel = " selected" if not selected else ""
            opts.append(f"<option value=''{sel}>{html.escape(blank)}</option>")
        for ch in guild.voice_channels:
            if exclude and str(ch.id) in exclude:
                continue
            sel = " selected" if selected and ch.id == selected else ""
            opts.append(f"<option value='{ch.id}'{sel}>{html.escape(ch.name)}</option>")
        return f"<select name='{field}' class='form-select form-select-sm'>{''.join(opts)}</select>"

    def _category_select(self, guild, field, selected=None):
        opts = [f"<option value=''>{'wie Quelle'}</option>"]
        for cat in guild.categories:
            sel = " selected" if selected and cat.id == selected else ""
            opts.append(f"<option value='{cat.id}'{sel}>{html.escape(cat.name)}</option>")
        return f"<select name='{field}' class='form-select form-select-sm'>{''.join(opts)}</select>"

    def _vis_select(self, field, selected="public"):
        opts = []
        for key in VIS_CHOICES:
            sel = " selected" if selected == key else ""
            opts.append(f"<option value='{key}'{sel}>{VIS_LABELS[key]}</option>")
        return f"<select name='{field}' class='form-select form-select-sm'>{''.join(opts)}</select>"

    async def _render_dashboard(self, request) -> dict:
        csrf = request.get("webcore_csrf", "")
        flash = ""
        if request.query.get("ok"):
            flash = "<div class='card-x' style='border-color:var(--accent);margin-bottom:16px'>Gespeichert.</div>"
        elif request.query.get("err"):
            flash = "<div class='card-x' style='border-color:var(--danger);margin-bottom:16px'>Eingabe ungültig – bitte prüfen.</div>"

        # Aktive Räume (über alle Server)
        room_rows = []
        for guild in self.bot.guilds:
            rooms = await self.config.guild(guild).active_rooms()
            for cid, rec in rooms.items():
                ch = guild.get_channel(int(cid))
                if ch is None:
                    continue
                owner = guild.get_member(rec.get("owner_id"))
                count = len([m for m in ch.members if not m.bot])
                room_rows.append(
                    "<tr>"
                    f"<td>{html.escape(guild.name)}</td>"
                    f"<td>{html.escape(ch.name)}</td>"
                    f"<td>{html.escape(owner.display_name) if owner else '—'}</td>"
                    f"<td class='mono'>{count}</td>"
                    "</tr>"
                )
        rooms_body = "".join(room_rows) or "<tr><td colspan='4' style='color:var(--muted)'>Aktuell keine aktiven Räume.</td></tr>"
        active_card = (
            "<div class='card-x' style='margin-bottom:18px'>"
            "<div class='stat-label'>Aktive Räume</div>"
            "<table class='table' style='margin-top:10px'>"
            "<thead><tr><th>Server</th><th>Raum</th><th>Besitzer</th><th>Drin</th></tr></thead>"
            f"<tbody>{rooms_body}</tbody></table></div>"
        )

        # Pro Server: Quellen + Formulare
        guild_blocks = []
        for guild in sorted(self.bot.guilds, key=lambda g: g.name.lower()):
            data = await self.config.guild(guild).all()
            sources = data.get("sources", {})
            source_ids = set(sources.keys())

            # Tabelle bestehender Quellen mit Bearbeiten/Entfernen
            src_rows = []
            for cid, cfg in sources.items():
                ch = guild.get_channel(int(cid))
                ch_name = html.escape(ch.name) if ch else f"(gelöscht: {cid})"
                edit_form = (
                    "<details><summary style='cursor:pointer;color:var(--accent)'>bearbeiten</summary>"
                    "<form method='post' action='/cogs/autoroom' style='margin-top:10px;display:grid;gap:8px;max-width:520px'>"
                    f"<input type='hidden' name='csrf_token' value='{csrf}'>"
                    "<input type='hidden' name='action' value='edit'>"
                    f"<input type='hidden' name='guild_id' value='{guild.id}'>"
                    f"<input type='hidden' name='channel_id' value='{cid}'>"
                    f"<label class='stat-label'>Kategorie</label>{self._category_select(guild, 'category_id', cfg.get('dest_category'))}"
                    f"<label class='stat-label'>Namensvorlage</label><input name='template' class='form-control form-control-sm' value='{html.escape(cfg.get('name_template', ''))}'>"
                    f"<label class='stat-label'>Limit (0 = unbegrenzt)</label><input name='limit' type='number' min='0' max='99' class='form-control form-control-sm' value='{int(cfg.get('user_limit') or 0)}'>"
                    f"<label class='stat-label'>Bitrate kbps (leer = Standard)</label><input name='bitrate' type='number' min='8' class='form-control form-control-sm' value='{cfg.get('bitrate_kbps') or ''}'>"
                    f"<label class='stat-label'>Sichtbarkeit</label>{self._vis_select('visibility', cfg.get('default_visibility', 'public'))}"
                    f"<label class='form-check'><input class='form-check-input' type='checkbox' name='textchannel'{' checked' if cfg.get('text_channel') else ''}> Textkanal pro Raum</label>"
                    "<button class='btn-accent' type='submit'>Speichern</button>"
                    "</form></details>"
                )
                remove_form = (
                    "<form method='post' action='/cogs/autoroom' onsubmit=\"return confirm('Quelle entfernen?')\">"
                    f"<input type='hidden' name='csrf_token' value='{csrf}'>"
                    "<input type='hidden' name='action' value='remove'>"
                    f"<input type='hidden' name='guild_id' value='{guild.id}'>"
                    f"<input type='hidden' name='channel_id' value='{cid}'>"
                    "<button type='submit' style='background:none;border:0;color:var(--danger);cursor:pointer'>entfernen</button>"
                    "</form>"
                )
                cat = guild.get_channel(int(cfg["dest_category"])) if cfg.get("dest_category") else None
                cat_cell = html.escape(cat.name) if cat else "<span style='color:var(--muted)'>wie Quelle</span>"
                src_rows.append(
                    "<tr>"
                    f"<td>{ch_name}</td>"
                    f"<td>{cat_cell}</td>"
                    f"<td class='mono'>{html.escape(cfg.get('name_template', ''))}</td>"
                    f"<td class='mono'>{int(cfg.get('user_limit') or 0) or '∞'}</td>"
                    f"<td>{VIS_LABELS.get(cfg.get('default_visibility'), '?')}</td>"
                    f"<td>{edit_form}</td>"
                    f"<td>{remove_form}</td>"
                    "</tr>"
                )
            src_body = "".join(src_rows) or "<tr><td colspan='7' style='color:var(--muted)'>Noch keine Quellen.</td></tr>"

            add_form = (
                "<form method='post' action='/cogs/autoroom' style='display:grid;gap:8px;max-width:520px;margin-top:14px'>"
                f"<input type='hidden' name='csrf_token' value='{csrf}'>"
                "<input type='hidden' name='action' value='add'>"
                f"<input type='hidden' name='guild_id' value='{guild.id}'>"
                f"<label class='stat-label'>Quell-Channel</label>{self._voice_select(guild, 'channel_id', exclude=source_ids)}"
                f"<label class='stat-label'>Ziel-Kategorie</label>{self._category_select(guild, 'category_id')}"
                "<label class='stat-label'>Namensvorlage</label>"
                f"<input name='template' class='form-control form-control-sm' value='{html.escape(DEFAULT_TEMPLATE)}' placeholder='{{user}}'>"
                "<label class='stat-label'>Limit (0 = unbegrenzt)</label>"
                "<input name='limit' type='number' min='0' max='99' class='form-control form-control-sm' value='0'>"
                "<label class='stat-label'>Sichtbarkeit</label>"
                f"{self._vis_select('visibility')}"
                "<label class='form-check'><input class='form-check-input' type='checkbox' name='textchannel'> Textkanal pro Raum</label>"
                "<button class='btn-accent' type='submit'>Quelle hinzufügen</button>"
                "</form>"
            )

            access_form = (
                "<form method='post' action='/cogs/autoroom' style='display:flex;gap:18px;align-items:center;margin-top:14px;flex-wrap:wrap'>"
                f"<input type='hidden' name='csrf_token' value='{csrf}'>"
                "<input type='hidden' name='action' value='access'>"
                f"<input type='hidden' name='guild_id' value='{guild.id}'>"
                f"<label class='form-check'><input class='form-check-input' type='checkbox' name='admin_access'{' checked' if data.get('admin_access', True) else ''}> Admin-Rollen sehen private Räume</label>"
                f"<label class='form-check'><input class='form-check-input' type='checkbox' name='mod_access'{' checked' if data.get('mod_access', False) else ''}> Mod-Rollen sehen private Räume</label>"
                "<button class='btn-accent' type='submit'>Übernehmen</button>"
                "</form>"
            )

            guild_blocks.append(
                "<div class='card-x' style='margin-bottom:18px'>"
                f"<h2 style='font-family:Archivo,sans-serif;font-size:1.1rem;margin:0 0 12px'>{html.escape(guild.name)}</h2>"
                "<table class='table'>"
                "<thead><tr><th>Quelle</th><th>Kategorie</th><th>Vorlage</th><th>Limit</th><th>Sicht</th><th></th><th></th></tr></thead>"
                f"<tbody>{src_body}</tbody></table>"
                f"{add_form}{access_form}</div>"
            )

        intro = (
            "<p style='color:var(--muted);margin-top:0'>Lege Quell-Channels fest: Wer einen Quell-Channel "
            "betritt, bekommt automatisch einen eigenen Voicechannel. Platzhalter in Vorlagen: "
            "<code>{user}</code>, <code>{game}</code>, <code>{num}</code>.</p>"
        )
        content = flash + intro + active_card + "".join(guild_blocks)
        return {"title": "Autovoiceroom", "content": content}

    async def _handle_dashboard_post(self, request) -> dict:
        form = await request.post()
        action = form.get("action")
        try:
            guild = self.bot.get_guild(int(form.get("guild_id")))
        except (TypeError, ValueError):
            guild = None
        if guild is None:
            return {"redirect": "/cogs/autoroom?err=1"}

        if action == "access":
            await self.config.guild(guild).admin_access.set(form.get("admin_access") == "on")
            await self.config.guild(guild).mod_access.set(form.get("mod_access") == "on")
            return {"redirect": "/cogs/autoroom?ok=1"}

        if action == "remove":
            sources = await self.config.guild(guild).sources()
            if sources.pop(str(form.get("channel_id")), None) is not None:
                await self.config.guild(guild).sources.set(sources)
            return {"redirect": "/cogs/autoroom?ok=1"}

        if action in ("add", "edit"):
            channel = guild.get_channel(int(form.get("channel_id"))) if str(form.get("channel_id") or "").isdigit() else None
            if not isinstance(channel, discord.VoiceChannel):
                return {"redirect": "/cogs/autoroom?err=1"}

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
            return {"redirect": "/cogs/autoroom?ok=1"}

        return {"redirect": "/cogs/autoroom?err=1"}

    async def dashboard_page(self, request):
        if request.method == "POST":
            return await self._handle_dashboard_post(request)
        return await self._render_dashboard(request)
