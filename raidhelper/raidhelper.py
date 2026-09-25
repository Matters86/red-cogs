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
from redbot.core.utils.chat_formatting import pagify

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
# Aufräumen alter Events: höchstens so oft je Server (Sekunden).
CLEANUP_INTERVAL = 3600


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
            cleanup_days=30,        # abgeschlossene Events nach N Tagen löschen (0 = aus)
        )
        # Gemerkte Spec je Nutzer und Spiel/Klasse (serverübergreifend).
        self.config.register_user(remember={})
        # Spec-Icons gelten botweit (Application Emojis): "<class>:<spec>" -> "<:rh_x:id>".
        self.config.register_global(spec_emojis={})
        # Aufräumen alter Events höchstens stündlich je Server (nur im RAM).
        self._last_cleanup: dict[int, float] = {}

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
    #  Datenschutz (Red-API)
    # ----------------------------------------------------------------- #
    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Entfernt alle personenbezogenen Daten eines Nutzers.

        - Anmeldungen/Status des Nutzers aus allen Events aller Guilds
        - Teilnahme-Zähler (``stats.attended``) des Nutzers
        - gemerkte Specs in der Nutzer-Config
        """
        uid = str(user_id)
        for guild_id in await self.config.all_guilds():
            gconf = self.config.guild_from_id(guild_id)
            async with gconf.events() as events:
                for event in events.values():
                    if isinstance(event, dict) and isinstance(event.get("signups"), dict):
                        event["signups"].pop(uid, None)
            async with gconf.stats() as stats:
                attended = stats.get("attended")
                if isinstance(attended, dict):
                    attended.pop(uid, None)
        await self.config.user_from_id(user_id).clear()

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
        # Unter dem Value-Lock: gleichzeitiges Anlegen (Befehl + Dashboard oder zwei
        # Wiederholungen) bekam sonst dieselbe ID und überschrieb ein Event.
        counter = self.config.guild(guild).counter
        async with counter.get_lock():
            n = int(await counter()) + 1
            await counter.set(n)
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
    #  Spec-Icons (Application Emojis, botweit) – Schlüssel "<class>:<spec>"
    # ----------------------------------------------------------------- #
    async def _spec_emojis(self) -> dict:
        return await self.config.spec_emojis()

    def _supports_app_emojis(self) -> bool:
        return hasattr(self.bot, "create_application_emoji") and hasattr(
            self.bot, "fetch_application_emojis"
        )

    @staticmethod
    def _emoji_name(class_id: str, spec_id: str) -> str:
        # Application-Emoji-Name: a-z0-9_ , 2-32 Zeichen. IDs sind bereits umlautfrei.
        return f"rh_{class_id}_{spec_id}"[:32]

    async def _set_spec_emoji_from_bytes(self, class_id: str, spec_id: str, data: bytes) -> str:
        """Lädt ein Bild als Application Emoji hoch und speichert das Mapping. Ersetzt vorhandenes."""
        if not self._supports_app_emojis():
            raise RuntimeError("app_emojis_unsupported")
        name = self._emoji_name(class_id, spec_id)
        try:
            for e in await self.bot.fetch_application_emojis():
                if e.name == name:
                    await self.bot.delete_application_emoji(e)
        except discord.HTTPException:
            pass
        emoji = await self.bot.create_application_emoji(name=name, image=data)
        async with self.config.spec_emojis() as mapping:
            mapping[f"{class_id}:{spec_id}"] = str(emoji)
        return str(emoji)

    async def _set_spec_emoji_str(self, class_id: str, spec_id: str, emoji_str: str):
        async with self.config.spec_emojis() as mapping:
            mapping[f"{class_id}:{spec_id}"] = emoji_str

    async def _delete_spec_emoji(self, class_id: str, spec_id: str):
        name = self._emoji_name(class_id, spec_id)
        if self._supports_app_emojis():
            try:
                for e in await self.bot.fetch_application_emojis():
                    if e.name == name:
                        await self.bot.delete_application_emoji(e)
            except discord.HTTPException:
                pass
        async with self.config.spec_emojis() as mapping:
            mapping.pop(f"{class_id}:{spec_id}", None)

    @staticmethod
    def _known_spec_structure() -> list[tuple[str, str, list[tuple[str, str]]]]:
        """[(class_id, class_label, [(spec_id, spec_label), …]), …] – Vereinigung über alle Spiele."""
        order: list[str] = []
        index: dict[str, dict] = {}
        for gid, _ in games.list_games():
            for cid in games.class_order(gid):
                if cid not in index:
                    index[cid] = {"label": games.class_label(gid, cid), "specs": [], "seen": set()}
                    order.append(cid)
                entry = index[cid]
                for sid, slabel, _role in games.specs_of(gid, cid):
                    if sid not in entry["seen"]:
                        entry["seen"].add(sid)
                        entry["specs"].append((sid, slabel))
        return [(cid, index[cid]["label"], index[cid]["specs"]) for cid in order]

    @classmethod
    def _known_pair_set(cls) -> set[tuple[str, str]]:
        return {(cid, sid) for cid, _lbl, specs in cls._known_spec_structure() for sid, _sl in specs}


    # ----------------------------------------------------------------- #
    #  Event posten / aktualisieren
    # ----------------------------------------------------------------- #
    async def post_event(self, guild, event: dict) -> int | None:
        channel = guild.get_channel(event.get("channel_id")) if event.get("channel_id") else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None
        lang = await self._lang(guild)
        overrides = await self._overrides(guild)
        emojis = await self._spec_emojis()
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
        emojis = await self._spec_emojis()
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
                           max_signups=None, role_limits=None, recurrence=None, series=None) -> dict:
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
            "series": series,
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
        emojis = await self._spec_emojis()
        remembered = await self.config.user_from_id(interaction.user.id).remember()
        default_spec = remembered.get(f"{game_id}:{class_id}")
        if default_spec not in {sid for sid, _label, _role in specs}:
            default_spec = None
        await interaction.response.send_message(
            t(lang, "pick_spec", cls=games.class_label(game_id, class_id)),
            view=build_spec_view(event_id, class_id, game_id, lang, emojis, default_spec=default_spec),
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

        # Erst antworten, dann die Event-Nachricht aktualisieren: Discord verlangt eine
        # Antwort binnen 3 s – fetch+edit davor ließ die Interaktion unter Last scheitern.
        cls_l = games.class_label(game_id, class_id)
        spec_l = games.spec_label(game_id, class_id, spec_id)
        role_l = games.role_meta(game_id, role).get("label", role)
        key = "spec_changed" if was_in_roster else "signed"
        await self._respond(interaction, t(lang, key, spec=spec_l, cls=cls_l, role=role_l), ephemeral_edit)
        await self._remember_spec(member.id, game_id, class_id, spec_id)
        await self.refresh_event_message(guild, snapshot)

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

        await interaction.response.send_message(
            t(lang, "moved_status", status=t(lang, f"status_{status}")), ephemeral=True
        )
        await self.refresh_event_message(guild, snapshot)

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
        await interaction.response.send_message(t(lang, "left"), ephemeral=True)
        await self.refresh_event_message(guild, snapshot)

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
            for eid, event in list(events.items()):
                # Ein fehlerhaftes Event darf die Schleife nicht beenden – eine
                # unbehandelte Exception stoppt tasks.loop dauerhaft (keine
                # Erinnerungen/Abschlüsse mehr auf ALLEN Servern bis zum Reload).
                try:
                    await self._tick_event(guild, conf, eid, event, now)
                except Exception:  # noqa: BLE001
                    log.exception("Raid-Tick für Event %s (Guild %s) fehlgeschlagen", eid, guild.id)
            # Aufräumen alter Events – eigener Fehlerabfang pro Server, höchstens stündlich.
            if now - self._last_cleanup.get(guild.id, 0) >= CLEANUP_INTERVAL:
                self._last_cleanup[guild.id] = now
                try:
                    removed = await self.cleanup_old_events(guild, now=now)
                    if removed:
                        log.info("Raid-Aufräumen: %s alte Events gelöscht (Guild %s)", len(removed), guild.id)
                except Exception:  # noqa: BLE001
                    log.exception("Raid-Aufräumen fehlgeschlagen (Guild %s)", guild.id)

    @staticmethod
    def _same_series(a_id: str, a: dict, b_id: str, b: dict) -> bool:
        """Gehören zwei Events zur selben Wiederholungsserie?

        Neue Folgetermine tragen ``series`` (= ID des ersten Termins). Altbestand ohne
        dieses Feld wird über Titel, Spiel und Kanal zugeordnet.
        """
        if a.get("series") or b.get("series"):
            return (a.get("series") or a_id) == (b.get("series") or b_id)
        return all(a.get(k) == b.get(k) for k in ("title", "game", "channel_id"))

    def _cleanup_candidates(self, events: dict, days: int, now: int) -> list[str]:
        """IDs der Events, die gelöscht werden dürfen.

        Nur abgeschlossene Events, deren Termin länger als ``days`` Tage vorbei ist.
        Ein Event mit Wiederholung wird nur gelöscht, wenn es in seiner Serie bereits
        einen späteren Termin gibt – so bleibt das jeweils letzte Glied einer Serie
        immer erhalten (auch wenn das Anlegen des Folgetermins einmal fehlschlug).
        """
        if days <= 0:
            return []
        cutoff = now - days * 86400
        valid = {eid: e for eid, e in events.items() if isinstance(e, dict)}
        out = []
        for eid, ev in valid.items():
            start = ev.get("start_ts") or 0
            if not ev.get("completed") or not start or start >= cutoff:
                continue
            if ev.get("recurrence") in RECURRENCE_DELTA:
                has_later = any(
                    oid != eid and (o.get("start_ts") or 0) > start and self._same_series(eid, ev, oid, o)
                    for oid, o in valid.items()
                )
                if not has_later:
                    continue
            out.append(eid)
        return out

    async def cleanup_old_events(self, guild, *, now: int | None = None, days: int | None = None) -> list[str]:
        """Löscht alte, abgeschlossene Events (nur Daten, keine Discord-Nachrichten)."""
        if now is None:
            now = int(datetime.now(tz=timezone.utc).timestamp())
        gconf = self.config.guild(guild)
        if days is None:
            days = int(await gconf.cleanup_days() or 0)
        if days <= 0:
            return []
        async with gconf.events() as events:
            victims = self._cleanup_candidates(events, days, now)
            for eid in victims:
                events.pop(eid, None)
        return victims

    async def _tick_event(self, guild, conf, eid, event, now):
        if not isinstance(event, dict):
            return
        start = event.get("start_ts") or 0
        # Erinnerungen: sind mehrere gleichzeitig fällig (Bot war offline),
        # nur die nächstliegende senden und alle fälligen als erledigt markieren.
        sent_now: list[int] = []
        if conf.get("reminders") and not event.get("completed"):
            already = event.get("reminders_sent", [])
            due_offs = [off for off in REMINDER_OFFSETS
                        if start - off * 60 <= now < start and off not in already]
            if due_offs:
                await self._send_reminder(guild, event, min(due_offs), conf)
                sent_now.extend(due_offs)
        # Nur das Flag der tatsächlich gesendeten Erinnerungen auf dem
        # FRISCH gelesenen Eintrag setzen – niemals den veralteten
        # Snapshot komplett zurückschreiben (sonst gehen parallele
        # Anmeldungen verloren). Reminder bleiben so genau einmalig.
        if sent_now:
            async with self.config.guild(guild).events() as stored:
                cur = stored.get(eid)
                if isinstance(cur, dict):
                    rs = cur.setdefault("reminders_sent", [])
                    for off in sent_now:
                        if off not in rs:
                            rs.append(off)
        # Abschluss + Statistik + Wiederholung
        if not event.get("completed") and start and now >= start:
            # Abschluss atomar auf dem frischen Eintrag beanspruchen,
            # damit genau einmal abgeschlossen/gezählt wird und die
            # aktuellen Anmeldungen erhalten bleiben.
            snapshot = None
            async with self.config.guild(guild).events() as stored:
                cur = stored.get(eid)
                if isinstance(cur, dict) and not cur.get("completed"):
                    cur["completed"] = True
                    cur["closed"] = True
                    snapshot = dict(cur)
            if snapshot is not None:
                await self._count_attendance(guild, snapshot)
                await self.refresh_event_message(guild, snapshot)
                if snapshot.get("recurrence") in RECURRENCE_DELTA:
                    await self._spawn_next(guild, snapshot)

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
        # In der Guild-Zeitzone rechnen: das Intervall als Kalenderarithmetik auf
        # die lokale Zeit addieren, damit die Uhrzeit über DST-Wechsel stabil
        # bleibt (fixe UTC-Addition würde nach Zeitumstellung um 1 h driften).
        tz_name = await self.config.guild(guild).timezone()
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
        local_start = datetime.fromtimestamp(event["start_ts"], tz=tz)
        # War der Bot länger offline, bis zum nächsten Termin in der Zukunft
        # weiterspringen – sonst entstünde eine Kette sofort abgelaufener Events.
        now = datetime.now(tz=tz)
        nxt = local_start + delta
        while nxt <= now:
            nxt += delta
        new_start = int(nxt.timestamp())
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
            series=event.get("series") or event.get("id"),
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
        for page in pagify("\n".join(rows), delims=["\n"], page_length=1900):
            await ctx.send(page)

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
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
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

    # ----- Event nachträglich konfigurieren --------------------------- #
    @raid.command(name="description")
    async def raid_description(self, ctx, event_id: str, *, text: str = ""):
        """Beschreibung eines Events setzen (leer lassen = entfernen)."""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        event = await self._get_event(guild, event_id)
        if event is None:
            return await ctx.send(t(lang, "not_found", id=event_id))
        new_desc = text.strip() or None
        async with self.config.guild(guild).events() as events:
            cur = events.get(event_id)
            if cur is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            cur["description"] = new_desc
            events[event_id] = cur
            snapshot = dict(cur)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(t(lang, "description_set" if new_desc else "description_cleared", id=event_id))

    @raid.command(name="deadline")
    async def raid_deadline(self, ctx, event_id: str, date: str, time: str):
        """Anmeldeschluss setzen.  Beispiel: [p]raid deadline rh-0001 13.06.2026 19:30"""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        event = await self._get_event(guild, event_id)
        if event is None:
            return await ctx.send(t(lang, "not_found", id=event_id))
        tz_name = await self.config.guild(guild).timezone()
        deadline_ts = self._parse_dt(date, time, tz_name)
        if deadline_ts is None:
            return await ctx.send(t(lang, "create_bad_date"))
        async with self.config.guild(guild).events() as events:
            cur = events.get(event_id)
            if cur is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            cur["deadline_ts"] = deadline_ts
            events[event_id] = cur
            snapshot = dict(cur)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(t(lang, "deadline_set", id=event_id, time=f"<t:{deadline_ts}:f>"))

    @raid.command(name="recurrence")
    async def raid_recurrence(self, ctx, event_id: str, value: str):
        """Wiederholung setzen: none, daily, weekly, biweekly."""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        event = await self._get_event(guild, event_id)
        if event is None:
            return await ctx.send(t(lang, "not_found", id=event_id))
        value = value.lower()
        if value in ("none", "off", "aus"):
            new_rec = None
        elif value in RECURRENCE_DELTA:
            new_rec = value
        else:
            allowed = ", ".join(["none", *RECURRENCE_DELTA])
            return await ctx.send(t(lang, "recurrence_bad", value=value, allowed=allowed))
        async with self.config.guild(guild).events() as events:
            cur = events.get(event_id)
            if cur is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            cur["recurrence"] = new_rec
            events[event_id] = cur
            snapshot = dict(cur)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(
            t(lang, "recurrence_set", id=event_id, value=new_rec)
            if new_rec else t(lang, "recurrence_cleared", id=event_id)
        )

    @raid.command(name="maxsignups")
    async def raid_maxsignups(self, ctx, event_id: str, count: int):
        """Maximale Anmeldungen setzen (0 oder weniger = unbegrenzt)."""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        event = await self._get_event(guild, event_id)
        if event is None:
            return await ctx.send(t(lang, "not_found", id=event_id))
        new_max = count if count > 0 else None
        async with self.config.guild(guild).events() as events:
            cur = events.get(event_id)
            if cur is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            cur["max_signups"] = new_max
            events[event_id] = cur
            snapshot = dict(cur)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(
            t(lang, "maxsignups_set", id=event_id, max=new_max)
            if new_max else t(lang, "maxsignups_cleared", id=event_id)
        )

    @raid.command(name="rolelimit")
    async def raid_rolelimit(self, ctx, event_id: str, role: str, count: int):
        """Rollen-Limit setzen (0 oder weniger = Limit entfernen)."""
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._is_manager(ctx.author):
            return await ctx.send(t(lang, "no_permission"))
        event = await self._get_event(guild, event_id)
        if event is None:
            return await ctx.send(t(lang, "not_found", id=event_id))
        game_id = event["game"]
        role = role.lower()
        valid_roles = games.role_order(game_id)
        if role not in valid_roles:
            return await ctx.send(t(lang, "rolelimit_bad_role", role=role, roles=", ".join(valid_roles)))
        label = games.role_meta(game_id, role).get("label", role)
        async with self.config.guild(guild).events() as events:
            cur = events.get(event_id)
            if cur is None:
                return await ctx.send(t(lang, "not_found", id=event_id))
            limits = cur.setdefault("role_limits", {})
            if count > 0:
                limits[role] = count
            else:
                limits.pop(role, None)
            events[event_id] = cur
            snapshot = dict(cur)
        await self.refresh_event_message(guild, snapshot)
        await ctx.send(
            t(lang, "rolelimit_set", id=event_id, label=label, max=count)
            if count > 0 else t(lang, "rolelimit_cleared", id=event_id, label=label)
        )

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

    @raidset.command(name="cleanup")
    async def raidset_cleanup(self, ctx, days: int):
        """Abgeschlossene Events nach N Tagen löschen (0 = aus, Standard 30).

        Gelöscht werden nur gespeicherte Daten – Discord-Nachrichten bleiben stehen.
        Wiederholungsserien bleiben erhalten.
        """
        lang = await self._lang(ctx.guild)
        if not 0 <= days <= 3650:
            return await ctx.send(t(lang, "cleanup_bad"))
        await self.config.guild(ctx.guild).cleanup_days.set(days)
        if days == 0:
            return await ctx.send(t(lang, "cleanup_off"))
        removed = await self.cleanup_old_events(ctx.guild)
        await ctx.send(t(lang, "cleanup_set", days=days, removed=len(removed)))

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
            f"Alte Events löschen nach: {str(d['cleanup_days']) + ' Tagen' if d['cleanup_days'] else 'aus'}\n"
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

    # ----- Spec-Icons -------------------------------------------------- #
    @raidset.command(name="icons")
    async def raidset_icons(self, ctx):
        """Zeigt, welche Spezialisierungen ein Icon haben (botweit)."""
        lang = await self._lang(ctx.guild)
        mapping = await self._spec_emojis()
        lines = [t(lang, "icons_list_header")]
        for cid, clabel, specs in self._known_spec_structure():
            parts = []
            for sid, slabel in specs:
                emoji = mapping.get(f"{cid}:{sid}", "—")
                parts.append(f"{emoji} {slabel}")
            lines.append(f"**{clabel}**: " + " · ".join(parts))
        # Discord-Nachrichtenlimit beachten
        text = "\n".join(lines)
        await ctx.send(text[:1990])

    @raidset.command(name="specicon")
    @commands.is_owner()  # Application Emojis gelten botweit – nicht von Server-Admins änderbar
    async def raidset_specicon(self, ctx, class_id: str, spec_id: str, emoji: str):
        """Setzt das Icon einer Spezialisierung manuell auf ein vorhandenes Emoji."""
        lang = await self._lang(ctx.guild)
        class_id, spec_id = class_id.lower(), spec_id.lower()
        if (class_id, spec_id) not in self._known_pair_set():
            return await ctx.send(t(lang, "icon_unknown_pair", cls=class_id, spec=spec_id))
        await self._set_spec_emoji_str(class_id, spec_id, emoji.strip())
        await ctx.send(t(lang, "icon_set",
                         cls=games.class_label("wow_retail", class_id),
                         spec=spec_id, emoji=emoji.strip()))

    @raidset.command(name="clearspecicon")
    @commands.is_owner()
    async def raidset_clearspecicon(self, ctx, class_id: str, spec_id: str):
        """Entfernt das Icon einer Spezialisierung."""
        lang = await self._lang(ctx.guild)
        class_id, spec_id = class_id.lower(), spec_id.lower()
        await self._delete_spec_emoji(class_id, spec_id)
        await ctx.send(t(lang, "icon_removed",
                         cls=games.class_label("wow_retail", class_id), spec=spec_id))

    @raidset.command(name="uploadicons")
    @commands.is_owner()
    async def raidset_uploadicons(self, ctx):
        """Lädt angehängte Bilddateien als Spec-Icons hoch (Dateiname = klasse_spec, z. B. krieger_furor.png)."""
        lang = await self._lang(ctx.guild)
        if not self._supports_app_emojis():
            return await ctx.send(t(lang, "icons_unsupported"))
        attachments = getattr(ctx.message, "attachments", [])
        if not attachments:
            return await ctx.send(t(lang, "icons_no_files"))
        pairs = self._known_pair_set()
        # Dateiname klasse_spec -> (class, spec): am ersten "_" trennen (IDs sind unterstrichfrei).
        ok, skipped = 0, 0
        for att in attachments:
            stem = att.filename.rsplit(".", 1)[0].lower()
            cls_spec = stem.split("_", 1)
            if len(cls_spec) != 2 or tuple(cls_spec) not in pairs:
                skipped += 1
                continue
            cid, sid = cls_spec
            try:
                data = await att.read()
                if len(data) > 256 * 1024:
                    skipped += 1
                    continue
                await self._set_spec_emoji_from_bytes(cid, sid, data)
                ok += 1
            except (discord.HTTPException, RuntimeError):
                skipped += 1
        await ctx.send(t(lang, "icons_upload_result", ok=ok, skipped=skipped))
