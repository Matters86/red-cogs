from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

from . import games
from .dashboard import dashboard_handler
from .embed import build_event_embed, signup_counts
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t
from .views import (
    CID_CLASS,
    CID_LEAVE,
    CID_SPEC,
    CID_STATUS,
    STATUS_BUTTONS,
    build_signup_view,
    build_spec_view,
)

log = logging.getLogger("red.red-cogs.raidhelper")

# Erinnerungen: Minuten vor Start, zu denen gepingt wird.
REMINDER_OFFSETS = [60, 15]
# Unterstützte Wiederholungen -> Zeitabstand bis zum nächsten Termin.
RECURRENCE_DELTA = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "biweekly": timedelta(days=14),
}


class RaidHelper(commands.Cog):
    """Mehrsprachiger Raid-Planer mit Anmeldung per Button, Roster, Erinnerungen und Dashboard."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=615238947104, force_registration=True)
        self.config.register_guild(
            language="de",
            default_game=games.DEFAULT_GAME,
            signup_channel=None,
            manager_roles=[],
            timezone="Europe/Berlin",
            reminders=True,
            ping_signed_up=False,   # bei Erinnerung zusätzlich angemeldete Nutzer per DM
            messages={},            # Text-Overrides (OVERRIDABLE_KEYS)
            events={},              # event_id -> Event-Datensatz
            counter=0,
            stats={"events": 0, "attended": {}},
        )
        # Gemerkte Spec je Nutzer und Spiel/Klasse (serverübergreifend).
        self.config.register_user(remember={})
        # Klassen-Icons gelten botweit (Application Emojis): class_id -> "<:rh_x:id>".
        self.config.register_global(class_emojis={})

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (1:1-Muster aus example/tickets)
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._reminder_tick.start()

    async def cog_unload(self):
        self._reminder_tick.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="raidhelper",
            name="Raidplaner",
            icon="bi-calendar-event",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    async def _overrides(self, guild) -> dict:
        return await self.config.guild(guild).messages()

    @staticmethod
    def _has_any_role(member: discord.Member, role_ids) -> bool:
        ids = {int(r) for r in (role_ids or [])}
        return any(r.id in ids for r in getattr(member, "roles", []))

    async def _is_manager(self, member: discord.Member) -> bool:
        if await self.bot.is_owner(member):
            return True
        perms = getattr(member, "guild_permissions", None)
        if perms and perms.manage_guild:
            return True
        roles = await self.config.guild(member.guild).manager_roles()
        return self._has_any_role(member, roles)

    async def _next_id(self, guild) -> str:
        n = await self.config.guild(guild).counter()
        n += 1
        await self.config.guild(guild).counter.set(n)
        return f"rh-{n:04d}"

    def _parse_dt(self, date_s: str, time_s: str, tz_name: str) -> int | None:
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("UTC")
        for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%d.%m.%y %H:%M"):
            try:
                dt = datetime.strptime(f"{date_s} {time_s}", fmt).replace(tzinfo=tz)
                return int(dt.timestamp())
            except ValueError:
                continue
        return None

    async def _remember_spec(self, user_id: int, game_id: str, class_id: str, spec_id: str):
        async with self.config.user_from_id(user_id).remember() as rem:
            rem[f"{game_id}:{class_id}"] = spec_id

    # ----------------------------------------------------------------- #
    #  Klassen-Icons (Application Emojis, botweit)
    # ----------------------------------------------------------------- #
    async def _class_emojis(self) -> dict:
        return await self.config.class_emojis()

    def _supports_app_emojis(self) -> bool:
        return hasattr(self.bot, "create_application_emoji") and hasattr(
            self.bot, "fetch_application_emojis"
        )

    @staticmethod
    def _emoji_name(class_id: str) -> str:
        # Application-Emoji-Name: a-z0-9_ , 2-32 Zeichen. Klassen-IDs sind bereits umlautfrei.
        return f"rh_{class_id}"

    async def _set_class_emoji_from_bytes(self, class_id: str, data: bytes) -> str:
        """Lädt ein Bild als Application Emoji hoch und speichert das Mapping. Ersetzt vorhandenes."""
        if not self._supports_app_emojis():
            raise RuntimeError("app_emojis_unsupported")
        name = self._emoji_name(class_id)
        try:
            for e in await self.bot.fetch_application_emojis():
                if e.name == name:
                    await self.bot.delete_application_emoji(e)
        except discord.HTTPException:
            pass
        emoji = await self.bot.create_application_emoji(name=name, image=data)
        async with self.config.class_emojis() as mapping:
            mapping[class_id] = str(emoji)
        return str(emoji)

    async def _set_class_emoji_str(self, class_id: str, emoji_str: str):
        async with self.config.class_emojis() as mapping:
            mapping[class_id] = emoji_str

    async def _delete_class_emoji(self, class_id: str):
        name = self._emoji_name(class_id)
        if self._supports_app_emojis():
            try:
                for e in await self.bot.fetch_application_emojis():
                    if e.name == name:
                        await self.bot.delete_application_emoji(e)
            except discord.HTTPException:
                pass
        async with self.config.class_emojis() as mapping:
            mapping.pop(class_id, None)

    @staticmethod
    def _known_class_ids() -> list[str]:
        """Vereinigung aller Klassen-IDs über alle Spiele (Retail ist die Obermenge)."""
        seen: list[str] = []
        for gid, _ in games.list_games():
            for cid in games.class_order(gid):
                if cid not in seen:
                    seen.append(cid)
        return seen


    # ----------------------------------------------------------------- #
    #  Event posten / aktualisieren
    # ----------------------------------------------------------------- #
    async def post_event(self, guild, event: dict) -> int | None:
        channel = guild.get_channel(event.get("channel_id")) if event.get("channel_id") else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None
        lang = await self._lang(guild)
        overrides = await self._overrides(guild)
        emojis = await self._class_emojis()
        try:
            msg = await channel.send(
                embed=build_event_embed(event, lang, overrides=overrides, emojis=emojis),
                view=build_signup_view(event, lang, emojis=emojis),
            )
            return msg.id
        except discord.HTTPException:
            log.exception("Event konnte nicht gepostet werden (Guild %s)", guild.id)
            return None

    async def refresh_event_message(self, guild, event: dict):
        if not event.get("channel_id") or not event.get("message_id"):
            return
        channel = guild.get_channel(event["channel_id"])
        if channel is None:
            return
        lang = await self._lang(guild)
        overrides = await self._overrides(guild)
        emojis = await self._class_emojis()
        try:
            msg = await channel.fetch_message(event["message_id"])
            await msg.edit(
                embed=build_event_embed(event, lang, overrides=overrides, emojis=emojis),
                view=build_signup_view(event, lang, emojis=emojis),
            )
        except discord.HTTPException:
            log.debug("Event-Nachricht nicht aktualisierbar (Event %s)", event.get("id"))

    async def create_event(self, guild, *, game, title, description, leader_id,
                           channel_id, start_ts, deadline_ts=None, color=None,
                           max_signups=None, role_limits=None, recurrence=None) -> dict:
        eid = await self._next_id(guild)
        event = {
            "id": eid,
            "game": game,
            "title": title,
            "description": description,
            "color": color,
            "leader_id": leader_id,
            "channel_id": channel_id,
            "message_id": None,
            "start_ts": int(start_ts),
            "deadline_ts": int(deadline_ts) if deadline_ts else int(start_ts),
            "max_signups": max_signups,
            "role_limits": role_limits or {},
            "recurrence": recurrence,
            "closed": False,
            "completed": False,
            "reminders_sent": [],
            "signups": {},
        }
        msg_id = await self.post_event(guild, event)
        event["message_id"] = msg_id
        async with self.config.guild(guild).events() as events:
            events[eid] = event
        return event

    # ----------------------------------------------------------------- #
    #  Interaktionen (Anmeldung) – persistent über custom_id
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        data = interaction.data or {}
        cid = data.get("custom_id", "")
        if not cid.startswith("rh:") or interaction.guild is None:
            return
        try:
            if cid.startswith(CID_CLASS):
                event_id = cid.split(":", 2)[2]
                class_id = (data.get("values") or [None])[0]
                await self._on_class(interaction, event_id, class_id)
            elif cid.startswith(CID_SPEC):
                _, _, event_id, class_id = cid.split(":", 3)
                spec_id = (data.get("values") or [None])[0]
                await self._apply_signup(interaction, event_id, class_id, spec_id, ephemeral_edit=True)
            elif cid.startswith(CID_STATUS):
                _, _, event_id, status = cid.split(":", 3)
                await self._apply_status(interaction, event_id, status)
            elif cid.startswith(CID_LEAVE):
                event_id = cid.split(":", 2)[2]
                await self._leave(interaction, event_id)
        except discord.HTTPException:
            log.exception("Fehler beim Verarbeiten einer Raid-Interaktion")

    async def _get_event(self, guild, event_id):
        events = await self.config.guild(guild).events()
        return events.get(event_id)

    def _signup_open(self, event) -> tuple[bool, str | None]:
        if event.get("closed"):
            return False, "signup_closed"
        now = int(datetime.now(tz=timezone.utc).timestamp())
        if event.get("deadline_ts") and now >= event["deadline_ts"]:
            return False, "deadline_passed"
        return True, None

    async def _on_class(self, interaction, event_id, class_id):
        guild = interaction.guild
        lang = await self._lang(guild)
        event = await self._get_event(guild, event_id)
        if event is None or class_id is None:
            await interaction.response.send_message(t(lang, "unknown_event"), ephemeral=True)
            return
        open_, reason = self._signup_open(event)
        if not open_:
            await interaction.response.send_message(t(lang, reason), ephemeral=True)
            return

        game_id = event["game"]
        specs = games.specs_of(game_id, class_id)
        if len(specs) <= 1:
            spec_id = specs[0][0] if specs else games.default_spec(game_id, class_id)
            await self._apply_signup(interaction, event_id, class_id, spec_id)
            return
        # Vorauswahl der gemerkten Spec? Trotzdem Auswahl anbieten (Wechsel möglich).
        emojis = await self._class_emojis()
        await interaction.response.send_message(
            t(lang, "pick_spec", cls=games.class_label(game_id, class_id)),
            view=build_spec_view(event_id, class_id, game_id, lang, emojis.get(class_id)),
            ephemeral=True,
        )

    def _count_role(self, event, role) -> int:
        return sum(
            1 for e in event["signups"].values()
            if e.get("status") == "signed" and e.get("role") == role
        )

    async def _apply_signup(self, interaction, event_id, class_id, spec_id, *, ephemeral_edit=False):
        guild = interaction.guild
        lang = await self._lang(guild)
        member = interaction.user
        uid = str(member.id)

        async with self.config.guild(guild).events() as events:
            event = events.get(event_id)
            if event is None:
                msg = t(lang, "unknown_event")
                return await self._respond(interaction, msg, ephemeral_edit)
            open_, reason = self._signup_open(event)
            if not open_:
                return await self._respond(interaction, t(lang, reason), ephemeral_edit)

            game_id = event["game"]
            role = games.spec_role(game_id, class_id, spec_id)
            prev = event["signups"].get(uid)
            was_in_roster = bool(prev and prev.get("status") == "signed")

            # Limits nur prüfen, wenn neu in diese Rolle (nicht beim reinen Spec-Wechsel innerhalb gleicher Rolle).
            entering = (not was_in_roster) or (prev and prev.get("role") != role)
            if entering:
                total, roster = signup_counts(event)
                cap = event.get("max_signups")
                if cap and not was_in_roster and roster >= int(cap):
                    return await self._respond(interaction, t(lang, "event_full", max=cap), ephemeral_edit)
                rlimit = (event.get("role_limits") or {}).get(role)
                if rlimit and self._count_role(event, role) >= int(rlimit):
                    label = games.role_meta(game_id, role).get("label", role)
                    return await self._respond(interaction, t(lang, "role_full", label=label, max=rlimit), ephemeral_edit)

            event["signups"][uid] = {
                "name": member.display_name,
                "class": class_id,
                "spec": spec_id,
                "role": role,
                "status": "signed",
                "at": (prev or {}).get("at") or int(datetime.now(tz=timezone.utc).timestamp()),
            }
            events[event_id] = event
            snapshot = dict(event)

        await self._remember_spec(member.id, game_id, class_id, spec_id)
        await self.refresh_event_message(guild, snapshot)

        cls_l = games.class_label(game_id, class_id)
        spec_l = games.spec_label(game_id, class_id, spec_id)
        role_l = games.role_meta(game_id, role).get("label", role)
        key = "spec_changed" if was_in_roster else "signed"
        await self._respond(interaction, t(lang, key, spec=spec_l, cls=cls_l, role=role_l), ephemeral_edit)

    async def _apply_status(self, interaction, event_id, status):
        guild = interaction.guild
        lang = await self._lang(guild)
        member = interaction.user
        uid = str(member.id)
        if status not in STATUS_BUTTONS:
            return await interaction.response.send_message(t(lang, "unknown_pick"), ephemeral=True)

        async with self.config.guild(guild).events() as events:
            event = events.get(event_id)
            if event is None:
                return await interaction.response.send_message(t(lang, "unknown_event"), ephemeral=True)
            open_, reason = self._signup_open(event)
            if not open_:
                return await interaction.response.send_message(t(lang, reason), ephemeral=True)
            prev = event["signups"].get(uid) or {}
            event["signups"][uid] = {
                "name": member.display_name,
                "class": prev.get("class"),
                "spec": prev.get("spec"),
                "role": prev.get("role"),
                "status": status,
                "at": prev.get("at") or int(datetime.now(tz=timezone.utc).timestamp()),
            }
            events[event_id] = event
            snapshot = dict(event)

        await self.refresh_event_message(guild, snapshot)
        await interaction.response.send_message(
            t(lang, "moved_status", status=t(lang, f"status_{status}")), ephemeral=True
        )

    async def _leave(self, interaction, event_id):
        guild = interaction.guild
        lang = await self._lang(guild)
        uid = str(interaction.user.id)
        async with self.config.guild(guild).events() as events:
            event = events.get(event_id)
            if event is None:
                return await interaction.response.send_message(t(lang, "unknown_event"), ephemeral=True)
            if uid not in event["signups"]:
                return await interaction.response.send_message(t(lang, "not_signed"), ephemeral=True)
            del event["signups"][uid]
            events[event_id] = event
            snapshot = dict(event)
        await self.refresh_event_message(guild, snapshot)
        await interaction.response.send_message(t(lang, "left"), ephemeral=True)

    async def _respond(self, interaction, text, ephemeral_edit):
        """Antwortet ephemer – bei Spec-Auswahl wird die Auswahl-Nachricht ersetzt."""
        if ephemeral_edit and not interaction.response.is_done():
            await interaction.response.edit_message(content=text, view=None)
        elif interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    # ----------------------------------------------------------------- #
    #  Hintergrund: Erinnerungen, Wiederholung, Statistik
    # ----------------------------------------------------------------- #
    @tasks.loop(seconds=60)
    async def _reminder_tick(self):
        now = int(datetime.now(tz=timezone.utc).timestamp())
        for guild in list(self.bot.guilds):
            try:
                conf = await self.config.guild(guild).all()
            except Exception:  # noqa: BLE001
                continue
            events = conf.get("events") or {}
            if not events:
                continue
            changed = False
            for eid, event in list(events.items()):
                start = event.get("start_ts") or 0
                # Erinnerungen
                if conf.get("reminders") and not event.get("completed"):
                    for off in REMINDER_OFFSETS:
                        due = start - off * 60
                        if due <= now < start and off not in event.get("reminders_sent", []):
                            await self._send_reminder(guild, event, off, conf)
                            event.setdefault("reminders_sent", []).append(off)
                            changed = True
                # Abschluss + Statistik + Wiederholung
                if not event.get("completed") and start and now >= start:
                    event["completed"] = True
                    event["closed"] = True
                    await self._count_attendance(guild, event)
                    await self.refresh_event_message(guild, event)
                    changed = True
                    if event.get("recurrence") in RECURRENCE_DELTA:
                        await self._spawn_next(guild, event)
            if changed:
                async with self.config.guild(guild).events() as stored:
                    for eid, event in events.items():
                        if eid in stored:
                            stored[eid] = event

    @_reminder_tick.before_loop
    async def _before_reminder(self):
        await self.bot.wait_until_red_ready()

    async def _send_reminder(self, guild, event, offset, conf):
        channel = guild.get_channel(event.get("channel_id"))
        lang = conf.get("language", DEFAULT_LANGUAGE)
        total, _ = signup_counts(event)
        rel = f"<t:{event['start_ts']}:R>"
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                await channel.send(t(lang, "reminder", title=event.get("title", ""), rel=rel, signups=total))
            except discord.HTTPException:
                pass
        if conf.get("ping_signed_up"):
            game_id = event.get("game")
            for uid, entry in event.get("signups", {}).items():
                if entry.get("status") not in ("signed", "late"):
                    continue
                member = guild.get_member(int(uid))
                if member is None:
                    continue
                cls_l = games.class_label(game_id, entry.get("class")) if entry.get("class") else "—"
                spec_l = games.spec_label(game_id, entry.get("class"), entry.get("spec")) if entry.get("spec") else ""
                try:
                    await member.send(t(lang, "reminder_dm", title=event.get("title", ""), rel=rel, spec=spec_l, cls=cls_l))
                except discord.HTTPException:
                    pass

    async def _count_attendance(self, guild, event):
        async with self.config.guild(guild).stats() as stats:
            stats["events"] = int(stats.get("events", 0)) + 1
            att = stats.setdefault("attended", {})
            for uid, entry in event.get("signups", {}).items():
                if entry.get("status") == "signed":
                    att[uid] = int(att.get(uid, 0)) + 1

    async def _spawn_next(self, guild, event):
        delta = RECURRENCE_DELTA.get(event.get("recurrence"))
        if not delta:
            return
        new_start = int((datetime.fromtimestamp(event["start_ts"], tz=timezone.utc) + delta).timestamp())
        shift = new_start - event["start_ts"]
        await self.create_event(
            guild,
            game=event["game"],
            title=event["title"],
            description=event.get("description"),
            leader_id=event.get("leader_id"),
            channel_id=event.get("channel_id"),
            start_ts=new_start,
            deadline_ts=(event.get("deadline_ts") + shift) if event.get("deadline_ts") else new_start,
            color=event.get("color"),
            max_signups=event.get("max_signups"),
            role_limits=event.get("role_limits"),
            recurrence=event.get("recurrence"),
        )

    # ----------------------------------------------------------------- #
    #  Befehle: Events
    # ----------------------------------------------------------------- #
    @commands.guild_only()
    @commands.hybrid_group(name="raid")
    async def raid(self, ctx: commands.Context):
        """Raid-Events verwalten."""

    @raid.command(name="create")
    async def raid_create(self, ctx, date: str, time: str, *, title: str):
        """Event anlegen.  Beispiel: [p]raid create 13.06.2026 20:00 Mythic Undermine"""
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(await self._lang(ctx.guild), "no_permission"))
        await self._create_flow(ctx, date, time, title, game=None, channel=None)

    @raid.command(name="quickcreate")
    async def raid_quickcreate(self, ctx, game: str, channel: discord.TextChannel,
                               date: str, time: str, *, title: str):
        """Event mit Spiel + Kanal direkt anlegen."""
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(await self._lang(ctx.guild), "no_permission"))
        await self._create_flow(ctx, date, time, title, game=game, channel=channel)

    async def _create_flow(self, ctx, date, time, title, game, channel):
        guild = ctx.guild
        lang = await self._lang(guild)
        conf = await self.config.guild(guild).all()
        game_id = game or conf["default_game"]
        if games.get_game(game_id) is None:
            avail = ", ".join(g for g, _ in games.list_games())
            return await ctx.send(t(lang, "create_bad_game", game=game_id, games=avail))
        ch = channel or (guild.get_channel(conf["signup_channel"]) if conf["signup_channel"] else None)
        if not isinstance(ch, discord.TextChannel):
            return await ctx.send(t(lang, "create_no_channel", p=ctx.clean_prefix))
        start_ts = self._parse_dt(date, time, conf["timezone"])
        if start_ts is None:
            return await ctx.send(t(lang, "create_bad_date"))
        if start_ts <= int(datetime.now(tz=timezone.utc).timestamp()):
            return await ctx.send(t(lang, "create_past"))
        event = await self.create_event(
            guild, game=game_id, title=title, description=None,
            leader_id=ctx.author.id, channel_id=ch.id, start_ts=start_ts,
        )
        link = f"https://discord.com/channels/{guild.id}/{ch.id}/{event['message_id']}" if event.get("message_id") else f"#{ch.name}"
        await ctx.send(t(lang, "created", link=link))

    @raid.command(name="list")
    async def raid_list(self, ctx):
        """Alle Events dieses Servers auflisten."""
        guild = ctx.guild
        lang = await self._lang(guild)
        events = await self.config.guild(guild).events()
        if not events:
            return await ctx.send(t(lang, "no_events"))
        rows = [t(lang, "list_header")]
        for e in sorted(events.values(), key=lambda x: x.get("start_ts", 0)):
            total, _ = signup_counts(e)
            status = t(lang, "status_closed" if e.get("closed") else "status_open")
            rows.append(t(lang, "list_row", id=e["id"], game=games.game_label(e["game"]),
                          time=f"<t:{e.get('start_ts',0)}:f>", signups=total, status=status))
        await ctx.send("\n".join(rows[:30]))

    @raid.command(name="close")
    async def raid_close(self, ctx, event_id: str):
        """Anmeldung schließen."""
        await self._set_closed(ctx, event_id, True)

    @raid.command(name="reopen")
    async def raid_reopen(self, ctx, event_id: str):
        """Anmeldung wieder öffnen."""
        await self._set_closed(ctx, event_id, False)

    async def _set_closed(self, ctx, event_id, closed):
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(guild).events() as events:
            event = events.get(event_id)
            if event is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            event["closed"] = closed
            events[event_id] = event
            snapshot = dict(event)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(t(lang, "closed" if closed else "reopened", id=event_id))

    @raid.command(name="delete")
    async def raid_delete(self, ctx, event_id: str):
        """Event löschen (inkl. Nachricht)."""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(guild).events() as events:
            event = events.pop(event_id, None)
        if event is None:
            return await ctx.send(t(lang, "not_found", id=event_id))
        if event.get("channel_id") and event.get("message_id"):
            channel = guild.get_channel(event["channel_id"])
            if channel is not None:
                try:
                    msg = await channel.fetch_message(event["message_id"])
                    await msg.delete()
                except discord.HTTPException:
                    pass
        await ctx.send(t(lang, "deleted", id=event_id))

    @raid.command(name="add")
    async def raid_add(self, ctx, event_id: str, member: discord.Member, class_id: str, spec_id: str):
        """Mitglied manuell eintragen."""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(guild).events() as events:
            event = events.get(event_id)
            if event is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            game_id = event["game"]
            if not games.is_valid(game_id, class_id, spec_id):
                return await ctx.send(t(lang, "unknown_pick"))
            role = games.spec_role(game_id, class_id, spec_id)
            event["signups"][str(member.id)] = {
                "name": member.display_name, "class": class_id, "spec": spec_id,
                "role": role, "status": "signed",
                "at": int(datetime.now(tz=timezone.utc).timestamp()),
            }
            events[event_id] = event
            snapshot = dict(event)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(t(lang, "added_manual", user=member.display_name,
                         spec=games.spec_label(game_id, class_id, spec_id),
                         cls=games.class_label(game_id, class_id)))

    @raid.command(name="remove")
    async def raid_remove(self, ctx, event_id: str, member: discord.Member):
        """Mitglied aus einem Event entfernen."""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(guild).events() as events:
            event = events.get(event_id)
            if event is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            event["signups"].pop(str(member.id), None)
            events[event_id] = event
            snapshot = dict(event)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(t(lang, "removed_manual", user=member.display_name))

    @raid.command(name="export")
    async def raid_export(self, ctx, event_id: str):
        """Anmeldungen als CSV exportieren."""
        guild = ctx.guild
        lang = await self._lang(guild)
        event = await self._get_event(guild, event_id)
        if event is None:
            return await ctx.send(t(lang, "not_found", id=event_id))
        game_id = event["game"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["name", "klasse", "spec", "rolle", "status", "zeitpunkt"])
        for uid, e in event["signups"].items():
            w.writerow([
                e.get("name", ""),
                games.class_label(game_id, e["class"]) if e.get("class") else "",
                games.spec_label(game_id, e["class"], e["spec"]) if e.get("spec") else "",
                e.get("role") or "",
                e.get("status") or "",
                datetime.fromtimestamp(e.get("at", 0), tz=timezone.utc).isoformat() if e.get("at") else "",
            ])
        buf.seek(0)
        file = discord.File(io.BytesIO(buf.getvalue().encode("utf-8")), filename=f"{event_id}.csv")
        await ctx.send(file=file)

    # ----------------------------------------------------------------- #
    #  Befehle: Einstellungen
    # ----------------------------------------------------------------- #
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.hybrid_group(name="raidset")
    async def raidset(self, ctx: commands.Context):
        """Einstellungen des Raid-Planers."""

    @raidset.command(name="language")
    async def raidset_language(self, ctx, code: str):
        """Sprache setzen (de, en)."""
        code = code.lower()
        if code not in LANGUAGES:
            return await ctx.send(t(await self._lang(ctx.guild), "lang_unknown",
                                    code=code, langs=", ".join(LANGUAGES)))
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))

    @raidset.command(name="game")
    async def raidset_game(self, ctx, game_id: str):
        """Standard-Spiel für neue Events setzen."""
        lang = await self._lang(ctx.guild)
        if games.get_game(game_id) is None:
            return await ctx.send(t(lang, "create_bad_game", game=game_id,
                                    games=", ".join(g for g, _ in games.list_games())))
        await self.config.guild(ctx.guild).default_game.set(game_id)
        await ctx.send(t(lang, "game_set", game=games.game_label(game_id)))

    @raidset.command(name="channel")
    async def raidset_channel(self, ctx, channel: discord.TextChannel):
        """Standard-Anmelde-Kanal setzen."""
        await self.config.guild(ctx.guild).signup_channel.set(channel.id)
        await ctx.send(t(await self._lang(ctx.guild), "channel_set", channel=channel.mention))

    @raidset.command(name="managerrole")
    async def raidset_managerrole(self, ctx, role: discord.Role):
        """Manager-Rolle hinzufügen/entfernen (Umschalter)."""
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).manager_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
                msg = t(lang, "mgr_removed", role=role.name)
            else:
                roles.append(role.id)
                msg = t(lang, "mgr_added", role=role.name)
        await ctx.send(msg)

    @raidset.command(name="timezone")
    async def raidset_timezone(self, ctx, tz: str):
        """Anzeige-Zeitzone setzen (z. B. Europe/Berlin)."""
        lang = await self._lang(ctx.guild)
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return await ctx.send(t(lang, "tz_unknown", tz=tz))
        await self.config.guild(ctx.guild).timezone.set(tz)
        await ctx.send(t(lang, "tz_set", tz=tz))

    @raidset.command(name="reminders")
    async def raidset_reminders(self, ctx, on_off: bool):
        """Erinnerungen an-/ausschalten."""
        await self.config.guild(ctx.guild).reminders.set(on_off)
        await ctx.send("✅")

    @raidset.command(name="settings")
    async def raidset_settings(self, ctx):
        """Aktuelle Einstellungen anzeigen."""
        d = await self.config.guild(ctx.guild).all()
        ch = ctx.guild.get_channel(d["signup_channel"]) if d["signup_channel"] else None
        roles = ", ".join(r.name for r in ctx.guild.roles if r.id in d["manager_roles"]) or "—"
        text = (
            f"Sprache: {d['language']}\n"
            f"Standard-Spiel: {games.game_label(d['default_game'])}\n"
            f"Anmelde-Kanal: {ch.mention if ch else '—'}\n"
            f"Manager-Rollen: {roles}\n"
            f"Zeitzone: {d['timezone']}\n"
            f"Erinnerungen: {'an' if d['reminders'] else 'aus'}\n"
            f"Events gespeichert: {len(d['events'])}"
        )
        await ctx.send(text)

    @raidset.command(name="dashboard")
    async def raidset_dashboard(self, ctx):
        """Hinweis zur Dashboard-Seite."""
        webcore = self.bot.get_cog("WebCore")
        if webcore is None:
            return await ctx.send("WebCore ist nicht geladen – Dashboard nicht verfügbar.")
        await ctx.send("Die Raidplaner-Seite findest du im WebCore-Dashboard unter `/cogs/raidhelper`.")

    # ----- Klassen-Icons ----------------------------------------------- #
    @raidset.command(name="icons")
    async def raidset_icons(self, ctx):
        """Zeigt, welche Klassen ein Icon haben (botweit)."""
        lang = await self._lang(ctx.guild)
        mapping = await self._class_emojis()
        lines = [t(lang, "icons_list_header")]
        for cid in self._known_class_ids():
            emoji = mapping.get(cid, "—")
            lines.append(f"{emoji} {games.class_label('wow_retail', cid)} (`{cid}`)")
        await ctx.send("\n".join(lines))

    @raidset.command(name="classicon")
    async def raidset_classicon(self, ctx, class_id: str, emoji: str):
        """Setzt das Icon einer Klasse manuell auf ein vorhandenes Emoji."""
        lang = await self._lang(ctx.guild)
        class_id = class_id.lower()
        if class_id not in self._known_class_ids():
            return await ctx.send(t(lang, "icon_unknown_class", cls=class_id,
                                    classes=", ".join(self._known_class_ids())))
        await self._set_class_emoji_str(class_id, emoji.strip())
        await ctx.send(t(lang, "icon_set", cls=games.class_label("wow_retail", class_id), emoji=emoji.strip()))

    @raidset.command(name="clearicon")
    async def raidset_clearicon(self, ctx, class_id: str):
        """Entfernt das Icon einer Klasse."""
        lang = await self._lang(ctx.guild)
        class_id = class_id.lower()
        await self._delete_class_emoji(class_id)
        await ctx.send(t(lang, "icon_removed", cls=games.class_label("wow_retail", class_id)))

    @raidset.command(name="uploadicons")
    async def raidset_uploadicons(self, ctx):
        """Lädt angehängte Bilddateien als Klassen-Icons hoch (Dateiname = Klassen-ID)."""
        lang = await self._lang(ctx.guild)
        if not self._supports_app_emojis():
            return await ctx.send(t(lang, "icons_unsupported"))
        attachments = getattr(ctx.message, "attachments", [])
        if not attachments:
            return await ctx.send(t(lang, "icons_no_files"))
        known = self._known_class_ids()
        ok, skipped = [], []
        for att in attachments:
            stem = att.filename.rsplit(".", 1)[0].lower()
            if stem not in known:
                skipped.append(att.filename)
                continue
            try:
                data = await att.read()
                if len(data) > 256 * 1024:
                    skipped.append(f"{att.filename} (>256 KB)")
                    continue
                await self._set_class_emoji_from_bytes(stem, data)
                ok.append(stem)
            except (discord.HTTPException, RuntimeError):
                skipped.append(att.filename)
        await ctx.send(t(lang, "icons_upload_result", ok=len(ok), skipped=len(skipped)))
