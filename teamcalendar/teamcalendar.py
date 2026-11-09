"""Gemeinsamer Projektkalender mit gleichen Verwaltungsrechten für das ganze Team."""
from __future__ import annotations

import asyncio
import copy
import logging
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import tasks
from redbot.core import Config, commands

from .models import CalendarError, MAX_EVENTS, format_local, normalize_event, parse_reminders
from .projects import ProjectMixin, prepare_event_project, register_project_config
from .project_models import parse_task_reminders, label_project

log = logging.getLogger("red.red-cogs.teamcalendar")


class TeamCalendar(ProjectMixin, commands.Cog):
    """Projekttermine anlegen, gemeinsam bearbeiten und zu- oder absagen."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=681340927516, force_registration=True)
        self.config.register_guild(
            timezone="Europe/Berlin", team_roles=[], manager_roles=[], team_can_manage=True,
            calendar_channel=None, reminder_channel=None, reminder_minutes=[1440, 60],
            board_message_id=None, board_error=None, events={}, counter=0, keep_days=180,
        )
        register_project_config(self)
        self._locks = {}
        self._unloading = False

    def _now(self):
        return int(time.time())

    def _lock(self, guild):
        return self._locks.setdefault(int(getattr(guild, "id", guild)), asyncio.Lock())

    def _lead(self, member, conf):
        if member is None:
            return False
        guild = getattr(member, "guild", None)
        return (member.id in (getattr(self.bot, "owner_ids", None) or set())
                or getattr(getattr(member, "guild_permissions", None), "administrator", False)
                or getattr(guild, "owner_id", None) == member.id
                or bool({role.id for role in getattr(member, "roles", [])} & set(conf.get("manager_roles") or [])))

    def can_configure(self, member, conf):
        return bool(self._lead(member, conf))

    def can_view(self, member, conf):
        return self._lead(member, conf) or member is not None and bool(
            {role.id for role in getattr(member, "roles", [])} & set(conf.get("team_roles") or []))

    def can_manage(self, member, conf):
        return self._lead(member, conf) or bool(conf.get("team_can_manage", True) and self.can_view(member, conf))

    def _actor(self, guild, actor):
        if getattr(actor, "id", None) in (getattr(self.bot, "owner_ids", None) or set()):
            return actor
        return guild.get_member(getattr(actor, "id", None))

    async def _authorize(self, guild, actor, conf, *, configure=False, view=False):
        if self._unloading or await self.bot.cog_disabled_in_guild(self, guild):
            raise CalendarError("Der Projektkalender ist auf diesem Server deaktiviert oder wird entladen.")
        actor = self._actor(guild, actor)
        predicate = self.can_configure if configure else self.can_view if view else self.can_manage
        if not predicate(actor, conf):
            raise CalendarError("Du gehörst nicht zum berechtigten Kalender-Team.")
        return actor

    @staticmethod
    def _event(conf, eid, revision=None):
        event = (conf.get("events") or {}).get(str(eid))
        if not isinstance(event, dict):
            raise CalendarError("Dieser Termin existiert nicht mehr.")
        if revision is not None:
            try:
                same = int(revision) == event.get("revision", 1)
            except (ValueError, TypeError):
                same = False
            if not same:
                raise CalendarError("Der Termin wurde inzwischen geändert. Bitte neu laden und erneut prüfen.")
        return event

    async def create_event(self, guild, actor, data):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._authorize(guild, actor, conf)
            if len(conf["events"]) >= MAX_EVENTS:
                raise CalendarError(f"Höchstens {MAX_EVENTS} Termine je Server. Bitte alte Termine entfernen.")
            now = self._now()
            values = prepare_event_project(conf, normalize_event(data, conf, now=now))
            owner = values.get("owner_id") or actor.id
            if owner != actor.id and guild.get_member(owner) is None:
                raise CalendarError("Die verantwortliche Person muss Mitglied dieses Servers sein.")
            ident = str(int(conf["counter"]) + 1)
            event = {**values, "id": ident, "owner_id": owner, "status": "scheduled", "participants": {},
                     "reminders_sent": {}, "created_by": actor.id, "updated_by": actor.id,
                     "created_at": now, "updated_at": now, "revision": 1}
            # Ein gemeinsamer Schreibvorgang: Zähler und Datensatz gehören zusammen.
            conf["counter"] = int(ident)
            conf["events"][ident] = event
            await self.config.guild(guild).set(conf)
            await self._refresh_board_locked(guild)
            return copy.deepcopy(event)

    async def update_event(self, guild, actor, eid, data, revision=None):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._authorize(guild, actor, conf)
            previous = self._event(conf, eid, revision)
            values = prepare_event_project(conf, normalize_event(data, conf, previous=previous, now=self._now()))
            owner = values.get("owner_id") or actor.id
            if owner != actor.id and guild.get_member(owner) is None:
                raise CalendarError("Die verantwortliche Person muss Mitglied dieses Servers sein.")
            event = {**previous, **values, "owner_id": owner, "updated_by": actor.id,
                     "updated_at": self._now(), "revision": previous.get("revision", 1) + 1}
            conf["events"][str(eid)] = event
            await self.config.guild(guild).set(conf)
            await self._refresh_board_locked(guild)
            return copy.deepcopy(event)

    async def event_action(self, guild, actor, eid, action, revision=None):
        if action not in {"cancel", "complete", "reopen", "delete"}:
            raise CalendarError("Unbekannte Termin-Aktion.")
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._authorize(guild, actor, conf)
            event = self._event(conf, eid, revision)
            if action == "delete":
                self._unlink_event_tasks(conf, eid, actor)
                del conf["events"][str(eid)]
                result = None
            else:
                event["status"] = {"cancel": "cancelled", "complete": "completed", "reopen": "scheduled"}[action]
                event.update(updated_by=actor.id, updated_at=self._now(), revision=event.get("revision", 1) + 1)
                result = copy.deepcopy(event)
            await self.config.guild(guild).set(conf)
            await self._refresh_board_locked(guild)
            if action == "delete":
                await self._refresh_task_board_locked(guild)
            return result

    async def set_rsvp(self, guild, actor, eid, status):
        if status not in {"yes", "maybe", "no", "remove"}:
            raise CalendarError("Bitte Zusage, Vielleicht oder Absage auswählen.")
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            actor = await self._authorize(guild, actor, conf, view=True)
            event = self._event(conf, eid)
            if event.get("status") != "scheduled" or event["end_ts"] <= self._now():
                raise CalendarError("Für diesen beendeten oder abgesagten Termin ist keine Anmeldung möglich.")
            participants = event.setdefault("participants", {})
            if status == "remove":
                participants.pop(str(actor.id), None)
            else:
                participants[str(actor.id)] = status
            # Zusagen ändern keine Formular-Version und lösen keine neuen Erinnerungen aus.
            await self.config.guild(guild).set(conf)
            await self._refresh_board_locked(guild)
            return copy.deepcopy(event)

    @staticmethod
    def _channel(guild, value):
        try:
            cid = int(value)
        except (ValueError, TypeError):
            return None
        return guild.get_channel(cid)

    def _valid_channel(self, guild, value):
        if value in (None, "", 0, "0"):
            return None
        channel = self._channel(guild, value)
        if not isinstance(channel, discord.TextChannel):
            raise CalendarError("Bitte einen Textkanal dieses Servers auswählen.")
        permissions = channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links and permissions.read_message_history):
            raise CalendarError("Dem Bot fehlen Kanal ansehen, Nachrichten senden, Links einbetten oder Nachrichtenverlauf anzeigen.")
        return channel

    async def save_settings(self, guild, actor, data):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            await self._authorize(guild, actor, conf, configure=True)
            patch = {}
            for key in ("team_roles", "manager_roles"):
                if key in data:
                    ids = data[key]
                    if not isinstance(ids, (list, tuple)) or len(ids) > 100:
                        raise CalendarError("Bitte gültige Team-Rollen auswählen.")
                    roles = []
                    for rid in ids:
                        role = guild.get_role(int(rid)) if str(rid).isdigit() else None
                        if role is None or role.is_default():
                            raise CalendarError("Eine ausgewählte Rolle gehört nicht zu diesem Server.")
                        roles.append(role.id)
                    patch[key] = sorted(set(roles))
            if "timezone" in data:
                try:
                    ZoneInfo(str(data["timezone"]))
                except (ZoneInfoNotFoundError, ValueError):
                    raise CalendarError("Unbekannte Zeitzone. Beispiel: Europe/Berlin.") from None
                patch["timezone"] = str(data["timezone"])
            for key in ("calendar_channel", "reminder_channel"):
                if key in data:
                    channel = self._valid_channel(guild, data[key])
                    patch[key] = channel.id if channel else None
            if "team_can_manage" in data:
                if not isinstance(data["team_can_manage"], bool):
                    raise CalendarError("Ungültige Team-Einstellung.")
                patch["team_can_manage"] = data["team_can_manage"]
            if "task_edit_mode" in data:
                if data["task_edit_mode"] not in {"team", "assigned"}:
                    raise CalendarError("Bitte gemeinsame Teamverwaltung oder zugewiesene Bearbeitung auswählen.")
                patch["task_edit_mode"] = data["task_edit_mode"]
            if "task_reminder_minutes" in data:
                patch["task_reminder_minutes"] = parse_task_reminders(data["task_reminder_minutes"])
            if "task_board_channel" in data:
                target = self._valid_channel(guild, data["task_board_channel"])
                patch["task_board_channel"] = target.id if target else None
                if patch["task_board_channel"] != conf.get("task_board_channel") and conf.get("task_board_message_id"):
                    raise CalendarError("Eine Aufgabenübersicht bitte ausdrücklich über „Aufgabenübersicht veröffentlichen“ verschieben.")
            if "reminder_minutes" in data:
                patch["reminder_minutes"] = parse_reminders(data["reminder_minutes"])
            if "keep_days" in data:
                try:
                    days = int(data["keep_days"])
                except (ValueError, TypeError):
                    days = -1
                if not 1 <= days <= 3650:
                    raise CalendarError("Aufbewahrung: 1 bis 3650 Tage.")
                patch["keep_days"] = days
            if patch.get("calendar_channel", conf["calendar_channel"]) != conf["calendar_channel"]:
                if conf.get("board_message_id"):
                    raise CalendarError("Eine veröffentlichte Übersicht bitte mit „Übersicht veröffentlichen“ in den neuen Kanal verschieben.")
            conf.update(patch)
            await self.config.guild(guild).set(conf)
            await self._refresh_board_locked(guild)
            await self._refresh_task_board_locked(guild)
            return conf

    def _board_embed(self, guild, conf):
        now = self._now()
        events = sorted((event for event in conf["events"].values()
                         if event.get("status") == "scheduled" and event.get("end_ts", 0) > now),
                        key=lambda event: (event["start_ts"], event["id"]))
        lines, previous_day = [], None
        for event in events[:15]:
            local = format_local(event["start_ts"], conf["timezone"])
            day = local.split(" ")[0]
            if day != previous_day:
                lines.append("\n**" + discord.utils.escape_markdown(day) + "**")
                previous_day = day
            title_raw = event["title"]
            project_raw = label_project(conf, event)
            title = discord.utils.escape_markdown(title_raw if len(title_raw) <= 60 else title_raw[:59] + "…")
            project = discord.utils.escape_markdown(project_raw if len(project_raw) <= 20 else project_raw[:19] + "…")
            yes = sum(value == "yes" for value in event.get("participants", {}).values())
            lines.append(f"`#{event['id']}` <t:{event['start_ts']}:t> · **{title}**" + (f" · {project}" if project else "") + f" · {yes} Zusagen")
        if len(events) > 15:
            lines.append(f"\nWeitere {len(events) - 15} Termine: Auswahl oder Dashboard öffnen.")
        return discord.Embed(title="Projektkalender · " + guild.name[:100],
            description=("\n".join(lines) or "Noch keine kommenden Termine. Das gesamte Team kann Termine anlegen.")[:4096],
            color=0x3DDC97).set_footer(text="Termine bearbeiten und Teilnahme über die Buttons · " + conf["timezone"])

    async def _board_view(self):
        from .views import build_board_view
        return build_board_view()

    async def _refresh_board_locked(self, guild):
        try:
            if self._unloading:
                return
            conf = await self.config.guild(guild).all()
            channel = self._channel(guild, conf.get("calendar_channel"))
            if channel is None and conf.get("calendar_channel"):
                await self.config.guild(guild).board_error.set("Der Kalenderkanal ist nicht erreichbar. Kanal und Bot-Rechte prüfen; gespeicherte Nachrichten-ID bleibt erhalten.")
                return
            if channel is None or not conf.get("board_message_id"):
                return
            try:
                message = await channel.fetch_message(conf["board_message_id"])
            except discord.NotFound:
                message = None
            if self._unloading:
                return
            kwargs = dict(embed=self._board_embed(guild, conf), view=await self._board_view(),
                          allowed_mentions=discord.AllowedMentions.none())
            if message is not None:
                if (not message.embeds or message.embeds[0].to_dict() != kwargs["embed"].to_dict()
                        or not getattr(message, "components", None)):
                    await message.edit(**kwargs)
            else:
                async def send_checkpoint():
                    if self._unloading:
                        return
                    message = await channel.send(**kwargs)
                    await self.config.guild(guild).board_message_id.set(message.id)
                transaction = asyncio.create_task(send_checkpoint())
                try:
                    await asyncio.shield(transaction)
                except asyncio.CancelledError:
                    await transaction
                    raise
            await self.config.guild(guild).board_error.set(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Kalenderübersicht für Server %s nicht aktualisiert", guild.id)
            try:
                await self.config.guild(guild).board_error.set("Übersicht konnte nicht aktualisiert werden. Kanalrechte prüfen und erneut versuchen.")
            except Exception:
                log.exception("Kalenderfehler für Server %s nicht speicherbar", guild.id)

    async def refresh_board(self, guild, *, actor=None):
        async with self._lock(guild):
            if self._unloading or await self.bot.cog_disabled_in_guild(self, guild):
                return
            if actor is not None:
                await self._authorize(guild, actor, await self.config.guild(guild).all())
            await self._refresh_board_locked(guild)

    async def post_board(self, guild, actor, channel=None):
        async with self._lock(guild):
            conf = await self.config.guild(guild).all()
            await self._authorize(guild, actor, conf, configure=channel is not None)
            target = self._valid_channel(guild, getattr(channel, "id", channel) if channel is not None else conf.get("calendar_channel"))
            if target is None:
                raise CalendarError("Bitte zuerst einen Kalenderkanal einstellen.")
            if target.id == conf.get("calendar_channel") and conf.get("board_message_id"):
                await self._refresh_board_locked(guild)
                return
            old_channel = self._channel(guild, conf.get("calendar_channel"))
            old_message = conf.get("board_message_id")
            async def send_checkpoint():
                if self._unloading:
                    raise CalendarError("Der Kalender wird gerade entladen. Bitte später erneut versuchen.")
                message = await target.send(embed=self._board_embed(guild, conf), view=await self._board_view(),
                                            allowed_mentions=discord.AllowedMentions.none())
                conf.update(calendar_channel=target.id, board_message_id=message.id, board_error=None)
                await self.config.guild(guild).set(conf)
                if old_channel is not None and old_message:
                    try:
                        await (await old_channel.fetch_message(old_message)).delete()
                    except discord.HTTPException:
                        await self.config.guild(guild).board_error.set("Neue Übersicht ist veröffentlicht; alte Nachricht bitte manuell entfernen.")
            transaction = asyncio.create_task(send_checkpoint())
            try:
                await asyncio.shield(transaction)
            except asyncio.CancelledError:
                await transaction
                raise
            except discord.HTTPException:
                raise CalendarError("Übersicht nicht veröffentlicht. Bitte die Kanalrechte prüfen.") from None

    async def _tick_once(self, now=None):
        if self._unloading:
            return
        now = self._now() if now is None else int(now)
        for guild in list(self.bot.guilds):
            try:
                if await self.bot.cog_disabled_in_guild(self, guild):
                    continue
                async with self._lock(guild):
                    if self._unloading:
                        return
                    conf = await self.config.guild(guild).all()
                    events = conf["events"]
                    cutoff = now - int(conf["keep_days"]) * 86400
                    removed = [eid for eid, event in events.items() if event.get("status") in {"completed", "cancelled"}
                               and event.get("end_ts", now) < cutoff]
                    for eid in removed:
                        self._unlink_event_tasks(conf, eid, guild.me)
                        del events[eid]
                    if removed:
                        await self.config.guild(guild).set(conf)
                    channel = self._channel(guild, conf.get("reminder_channel") or conf.get("calendar_channel"))
                    if channel is not None:
                        for event in events.values():
                            if event.get("status") != "scheduled" or event.get("start_ts", 0) <= now:
                                continue
                            sent = event.setdefault("reminders_sent", {})
                            occurrence = event["start_ts"]
                            due = []
                            for offset in event.get("reminder_minutes", conf["reminder_minutes"]):
                                key = f"{occurrence}:{offset}"
                                marker = sent.get(key) or {}
                                when = event["start_ts"] - int(offset) * 60
                                if now < when or now > when + 300 or marker.get("state") in {"reserved", "sent", "skipped"}:
                                    continue
                                if marker.get("attempts", 0) >= 3 or marker.get("retry_at", 0) > now:
                                    continue
                                due.append(int(offset))
                            if not due:
                                continue
                            offset = min(due)
                            for skipped in due:
                                if skipped != offset:
                                    sent[f"{occurrence}:{skipped}"] = {"state": "skipped", "at": now}
                            key = f"{occurrence}:{offset}"
                            attempts = (sent.get(key) or {}).get("attempts", 0) + 1
                            sent[key] = {"state": "reserved", "at": now, "attempts": attempts}
                            await self.config.guild(guild).events.set(events)
                            try:
                                await channel.send(embed=discord.Embed(title="Terminerinnerung", description=(
                                    f"**{discord.utils.escape_markdown(event['title'])}**\nBeginn <t:{event['start_ts']}:F> (<t:{event['start_ts']}:R>)"),
                                    color=0x3DDC97), allowed_mentions=discord.AllowedMentions.none())
                            except discord.HTTPException as exc:
                                # Serverfehler können trotz angenommener Nachricht auftreten.
                                # Ihre Reservierung bleibt bestehen; nur sichere 4xx erneut versuchen.
                                if 400 <= exc.status < 500:
                                    sent[key].update(state="failed", retry_at=now + 60 * attempts)
                            else:
                                sent[key]["state"] = "sent"
                            await self.config.guild(guild).events.set(events)
                    # Auch ohne Bearbeitung vergehen Termine; gelöschte Boards werden repariert.
                    await self._refresh_board_locked(guild)
                    await self._tick_projects_locked(guild, conf, now)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Kalenderprüfung für Server %s fehlgeschlagen", guild.id)

    @tasks.loop(seconds=60)
    async def _tick(self):
        await self._tick_once()

    @_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self._unloading = False
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._tick.start()

    async def cog_unload(self):
        self._unloading = True
        self._tick.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        if (interaction.guild is not None and interaction.type == discord.InteractionType.component
                and str((interaction.data or {}).get("custom_id", "")).startswith("teamcalendar:")):
            from .views import handle_interaction
            await handle_interaction(self, interaction)

    def _register_dashboard(self, webcore):
        webcore.register_page(owner=self, slug="teamcalendar", name="Projektmanagement", icon="bi-calendar3",
            handler=self.dashboard_page, operate_forms={"event_save", "event_action", "rsvp", "board_refresh",
                "project_save", "project_action", "task_save", "task_action", "task_assign", "task_check",
                "task_comment", "task_comment_delete", "task_board_refresh"})

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler
        return await dashboard_handler(self, request)

    async def red_delete_data_for_user(self, *, requester, user_id):
        uid = int(user_id)
        from .dashboard import discard_user
        discard_user(self, uid)
        for gid in await self.config.all_guilds():
            async with self._lock(gid):
                async with self.config.guild_from_id(gid).events() as events:
                    for event in events.values():
                        event.get("participants", {}).pop(str(uid), None)
                        if event.get("owner_id") == uid:
                            event["revision"] = event.get("revision", 1) + 1
                        for key in ("created_by", "updated_by", "owner_id"):
                            if event.get(key) == uid:
                                event[key] = 0
                conf = await self.config.guild_from_id(gid).all()
                self._scrub_projects_locked(conf, uid)
                await self.config.guild_from_id(gid).set(conf)
                guild = self.bot.get_guild(gid)
                if guild is not None:
                    await self._refresh_board_locked(guild)
                    await self._refresh_task_board_locked(guild)

    @commands.hybrid_group(name="termine", aliases=["kalender"])
    @commands.guild_only()
    async def calendar(self, ctx):
        """Gemeinsamer Projektkalender – das ganze Team darf Termine verwalten."""
        if getattr(ctx, "invoked_subcommand", None) is None:
            await self.calendar_list.callback(self, ctx)

    @calendar.command(name="liste")
    async def calendar_list(self, ctx, tage: int = 30):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._authorize(ctx.guild, ctx.author, conf, view=True)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        if not 1 <= tage <= 365:
            return await ctx.send("Bitte 1 bis 365 Tage auswählen.", ephemeral=True)
        conf["events"] = {eid: event for eid, event in conf["events"].items()
                          if event.get("start_ts", 0) <= self._now() + tage * 86400}
        await ctx.send(embed=self._board_embed(ctx.guild, conf), view=await self._board_view(), ephemeral=True,
                       allowed_mentions=discord.AllowedMentions.none())

    @calendar.command(name="neu")
    async def calendar_new(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._authorize(ctx.guild, ctx.author, conf)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Mit „Neuer Termin“ öffnest du das Formular. Alle Teammitglieder dürfen auch fremde Termine bearbeiten.",
                       view=await self._board_view(), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @calendar.command(name="details")
    async def calendar_details(self, ctx, termin: str):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._authorize(ctx.guild, ctx.author, conf, view=True)
            event = self._event(conf, termin)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        from .views import event_embed, build_event_view
        await ctx.send(embed=event_embed(ctx.guild, event, conf),
                       view=build_event_view(event, ctx.author.id,
                           can_manage=self.can_manage(self._actor(ctx.guild, ctx.author), conf), now=self._now()),
                       ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def _command_action(self, ctx, termin, action):
        await ctx.defer(ephemeral=True)
        try:
            await self.event_action(ctx.guild, ctx.author, termin, action)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Termin aktualisiert.", ephemeral=True)

    @calendar.command(name="absagen")
    async def calendar_cancel(self, ctx, termin: str):
        await self._command_action(ctx, termin, "cancel")

    @calendar.command(name="erledigt")
    async def calendar_complete(self, ctx, termin: str):
        await self._command_action(ctx, termin, "complete")

    @calendar.command(name="loeschen")
    async def calendar_delete(self, ctx, termin: str):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._authorize(ctx.guild, ctx.author, conf)
            event = self._event(conf, termin)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        view = discord.ui.View(timeout=60)
        button = discord.ui.Button(label="Termin endgültig löschen", style=discord.ButtonStyle.danger)
        async def confirmed(interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("Diese Bestätigung gehört einer anderen Person.", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            try:
                await self.event_action(ctx.guild, interaction.user, termin, "delete", revision=event["revision"])
            except CalendarError as exc:
                return await interaction.followup.send(str(exc), ephemeral=True)
            view.stop()
            button.disabled = True
            await interaction.followup.send("Termin gelöscht.", ephemeral=True)
        button.callback = confirmed
        view.add_item(button)
        await ctx.send("Diesen Termin samt Teilnahmen endgültig löschen?", view=view, ephemeral=True)

    @calendar.command(name="setup")
    async def calendar_setup(self, ctx, kanal: discord.TextChannel, teamrolle: discord.Role):
        await ctx.defer(ephemeral=True)
        try:
            conf = await self.config.guild(ctx.guild).all()
            roles = sorted(set(conf["team_roles"]) | {teamrolle.id})
            await self.save_settings(ctx.guild, ctx.author, {"team_roles": roles, "team_can_manage": True})
            await self.post_board(ctx.guild, ctx.author, kanal)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Projektkalender eingerichtet. Das gesamte ausgewählte Team darf Termine verwalten.", ephemeral=True)

    @calendar.command(name="board")
    async def calendar_board(self, ctx, channel: discord.TextChannel = None):
        await ctx.defer(ephemeral=True)
        try:
            await self.post_board(ctx.guild, ctx.author, channel)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Kalenderübersicht aktualisiert.", ephemeral=True)

    @calendar.command(name="teilnahme")
    async def calendar_rsvp(self, ctx, termin: str, antwort: str):
        await ctx.defer(ephemeral=True)
        choices = {"ja": "yes", "vielleicht": "maybe", "nein": "no", "entfernen": "remove"}
        try:
            await self.set_rsvp(ctx.guild, ctx.author, termin, choices.get(antwort.lower(), antwort.lower()))
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Deine Teilnahme wurde gespeichert.", ephemeral=True)

    @commands.hybrid_group(name="aufgaben")
    @commands.guild_only()
    async def work(self, ctx):
        """Projektaufgaben, Zuständigkeiten, Fristen und Checklisten."""
        if getattr(ctx, "invoked_subcommand", None) is None:
            await self.work_list.callback(self, ctx)

    @work.command(name="liste")
    async def work_list(self, ctx, nurmeine: bool = False):
        conf = await self.config.guild(ctx.guild).all()
        try:
            actor = await self._authorize(ctx.guild, ctx.author, conf, view=True)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        if nurmeine:
            conf["work_tasks"] = {tid: task for tid, task in conf["work_tasks"].items()
                                  if actor.id in (task.get("assignee_ids") or [])}
        from .task_views import build_task_board_view
        await ctx.send(embed=self._task_board_embed(ctx.guild, conf), view=build_task_board_view(),
                       ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @work.command(name="neu")
    async def work_new(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._project_actor(ctx.guild, ctx.author, conf)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        from .task_views import build_task_board_view
        await ctx.send("Mit „Neue Aufgabe“ öffnest du das Aufgabenformular.", view=build_task_board_view(), ephemeral=True)

    @work.command(name="details")
    async def work_details(self, ctx, nummer: str):
        conf = await self.config.guild(ctx.guild).all()
        try:
            actor = await self._authorize(ctx.guild, ctx.author, conf, view=True)
            task = self._record(conf, "work_tasks", nummer)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        from .task_views import task_embed, build_task_view
        await ctx.send(embed=task_embed(ctx.guild, task, conf),
            view=build_task_view(task, actor.id, can_edit=self.can_edit_task(actor, conf, task), can_work=self.can_work_task(actor, conf, task)),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @work.command(name="status")
    async def work_status(self, ctx, nummer: str, status: str):
        mapping = {"offen": "todo", "arbeit": "in_progress", "blockiert": "blocked", "erledigt": "done"}
        action = mapping.get(status.lower(), status.lower())
        if action not in {"todo", "in_progress", "blocked", "done"}:
            return await ctx.send("Status: offen, arbeit, blockiert oder erledigt.", ephemeral=True)
        await ctx.defer(ephemeral=True)
        try:
            await self.task_action(ctx.guild, ctx.author, nummer, action)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Aufgabenstatus gespeichert.", ephemeral=True)

    @work.command(name="zuweisen")
    async def work_assign(self, ctx, nummer: str, mitglied: discord.Member = None):
        await ctx.defer(ephemeral=True)
        try:
            await self.assign_task(ctx.guild, ctx.author, nummer, [mitglied.id] if mitglied else [])
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Zuständigkeit gespeichert.", ephemeral=True)

    @work.command(name="kommentar")
    async def work_comment(self, ctx, nummer: str, *, text: str):
        await ctx.defer(ephemeral=True)
        try:
            await self.add_task_comment(ctx.guild, ctx.author, nummer, text)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Kommentar gespeichert.", ephemeral=True)

    @work.command(name="board")
    async def work_board(self, ctx, kanal: discord.TextChannel = None):
        await ctx.defer(ephemeral=True)
        try:
            await self.post_task_board(ctx.guild, ctx.author, kanal)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        error = await self.config.guild(ctx.guild).task_board_error()
        await ctx.send(error or "Aufgabenübersicht aktualisiert.", ephemeral=True)

    @commands.hybrid_group(name="projekte")
    @commands.guild_only()
    async def projects(self, ctx):
        """Gemeinsame Projekte und ihre Aufgaben."""
        if getattr(ctx, "invoked_subcommand", None) is None:
            await self.projects_list.callback(self, ctx)

    @projects.command(name="liste")
    async def projects_list(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._authorize(ctx.guild, ctx.author, conf, view=True)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        from .task_views import build_task_board_view
        lines = [f"`#{project['id']}` {discord.utils.escape_markdown(project['name'])} · "
                 + {"active": "Aktiv", "paused": "Pausiert", "completed": "Abgeschlossen", "archived": "Archiviert"}.get(project.get("status"), "Aktiv")
                 for project in conf["projects"].values()]
        await ctx.send(embed=discord.Embed(title="Projekte", description=("\n".join(lines[:15]) or "Noch keine Projekte.")
            + (f"\nWeitere {len(lines) - 15} Projekte in der Auswahl." if len(lines) > 15 else ""), color=0x3DDC97),
            view=build_task_board_view(), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @projects.command(name="neu")
    async def projects_new(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._project_actor(ctx.guild, ctx.author, conf, projects=True)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        from .task_views import build_task_board_view
        await ctx.send("Über „Projekte“ öffnest du die Projektliste und das Formular für ein neues Projekt.",
                       view=build_task_board_view(), ephemeral=True)

    @projects.command(name="details")
    async def projects_details(self, ctx, nummer: str):
        conf = await self.config.guild(ctx.guild).all()
        try:
            await self._authorize(ctx.guild, ctx.author, conf, view=True)
            project = self._record(conf, "projects", nummer)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        from .task_views import project_embed, build_task_board_view
        await ctx.send(embed=project_embed(ctx.guild, project, conf), view=build_task_board_view(),
                       ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @projects.command(name="status")
    async def projects_status(self, ctx, nummer: str, status: str):
        mapping = {"aktiv": "activate", "pause": "pause", "abgeschlossen": "complete", "archiv": "archive"}
        action = mapping.get(status.lower(), status.lower())
        if action not in {"activate", "pause", "complete", "archive"}:
            return await ctx.send("Status: aktiv, pause, abgeschlossen oder archiv.", ephemeral=True)
        await ctx.defer(ephemeral=True)
        try:
            await self.project_action(ctx.guild, ctx.author, nummer, action)
        except CalendarError as exc:
            return await ctx.send(str(exc), ephemeral=True)
        await ctx.send("Projektstatus gespeichert.", ephemeral=True)
