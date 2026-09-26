from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify

from . import core
from .core import (MAX_BONUS_PER_ROLE, MAX_BONUS_ROLES, MAX_DESC_LEN, MAX_MEMBER_DAYS, MAX_PRIZE_LEN,
                   MAX_ROLE_LIST, MAX_WINNERS, eligibility, is_running, parse_duration, role_ids,
                   tickets_for, weighted_sample)
from .embed import JoinView, LeaveConfirmView, build_embed
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.giveaways")


class Giveaways(commands.Cog):
    """Gewinnspiele mit Teilnahme-Button, Voraussetzungen, Bonus-Losen, fairer Auslosung und Dashboard."""

    REFRESH_THROTTLE = 10.0     # Sekunden: Teilnehmerzahl im Embed höchstens so oft aktualisieren
    TICK_SECONDS = 20           # Takt der Auslosungs-Schleife

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=739164825013, force_registration=True)
        self.config.register_guild(
            language="de",
            timezone="Europe/Berlin",   # für Datum/Uhrzeit im Dashboard
            manager_roles=[],           # dürfen Gewinnspiele starten/beenden/neu auslosen/abbrechen
            color="#f5b94a",            # Embed-Farbe laufender Gewinnspiele
            member_page=True,           # „Mein Bereich → Gewinnspiele“ anzeigen
            keep_days=90,               # beendete/abgebrochene Gewinnspiele so lange behalten
            giveaways={},               # id -> Datensatz
            counter=0,
        )
        self._locks: dict[int, asyncio.Lock] = {}
        self._refresh_tasks: dict[tuple, asyncio.Task] = {}
        self._last_refresh: dict[tuple, float] = {}
        self._views: list[discord.ui.View] = []

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    def _now(self) -> float:
        return time.time()

    def _lock(self, guild_or_id) -> asyncio.Lock:
        gid = int(getattr(guild_or_id, "id", guild_or_id))
        return self._locks.setdefault(gid, asyncio.Lock())

    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    @staticmethod
    def _channel(guild, cid):
        if not cid:
            return None
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return None
        ch = guild.get_channel(cid)
        if ch is None and hasattr(guild, "get_thread"):
            ch = guild.get_thread(cid)
        return ch

    async def is_manager(self, member) -> bool:
        """Owner, „Server verwalten“/Admin oder eine der Manager-Rollen."""
        if member is None:
            return False
        if await self.bot.is_owner(member):
            return True
        perms = getattr(member, "guild_permissions", None)
        if perms is not None and (perms.manage_guild or perms.administrator):
            return True
        roles = await self.config.guild(member.guild).manager_roles()
        return bool(role_ids(member) & {int(r) for r in roles})

    async def _is_admin(self, member) -> bool:
        if await self.bot.is_owner(member):
            return True
        perms = getattr(member, "guild_permissions", None)
        return bool(perms is not None and (perms.manage_guild or perms.administrator))

    def text(self, guild, lang, key, kwargs=None, *, web: bool = False) -> str:
        """Übersetzter Text; Rollen-Listen werden in Discord als Erwähnung, im Web als Name gezeigt."""
        kwargs = dict(kwargs or {})
        if "roles" in kwargs and not isinstance(kwargs["roles"], str):
            ids = list(kwargs["roles"])[:MAX_ROLE_LIST]
            if web:
                names = [getattr(guild.get_role(int(r)), "name", None) for r in ids]
                kwargs["roles"] = ", ".join(n for n in names if n) or "—"
            else:
                kwargs["roles"] = ", ".join(f"<@&{int(r)}>" for r in ids)
        return t(lang, key, **kwargs)

    # ----------------------------------------------------------------- #
    #  Red-Datenschutz-API
    # ----------------------------------------------------------------- #
    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Entfernt Teilnahmen und Gewinner-Einträge des Nutzers; Veranstalter-ID wird auf 0 gesetzt."""
        uid, iid = str(user_id), int(user_id)
        try:
            all_guilds = await self.config.all_guilds()
        except Exception:  # noqa: BLE001
            return
        for gid in list(all_guilds):
            try:
                async with self._lock(gid):
                    async with self.config.guild_from_id(gid).giveaways() as gws:
                        for gw in gws.values():
                            if not isinstance(gw, dict):
                                continue
                            (gw.get("entrants") or {}).pop(uid, None)
                            gw["winner_ids"] = [w for w in gw.get("winner_ids") or [] if int(w) != iid]
                            gw["rerolled_out"] = [w for w in gw.get("rerolled_out") or [] if int(w) != iid]
                            if gw.get("host_id") == iid:
                                gw["host_id"] = 0
            except Exception:  # noqa: BLE001
                log.exception("Datenlöschung in Guild %s fehlgeschlagen", gid)

    # ----------------------------------------------------------------- #
    #  Laden / Entladen / Dashboard
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        try:
            await self._restore_views()
        except Exception:  # noqa: BLE001
            log.exception("Persistente Gewinnspiel-Buttons konnten nicht registriert werden")
        self._tick.start()

    async def cog_unload(self):
        self._tick.cancel()
        for task in list(self._refresh_tasks.values()):
            task.cancel()
        self._refresh_tasks.clear()
        for view in self._views:
            view.stop()
        self._views.clear()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        # Tagesgeschäft („Bedienen“): Gewinnspiel starten sowie beenden/neu auslosen/abbrechen/Eintrag entfernen.
        # Einstellungen, Manager-Rollen und der Mitglieder-Bereich-Schalter brauchen „Bearbeiten“.
        extra = {"operate_forms": {"create", "action"}} if hasattr(webcore, "OPERATE") else {}
        webcore.register_page(owner=self, slug="giveaways", name="Gewinnspiele", icon="bi-gift",
                              handler=self.dashboard_page, **extra)
        if hasattr(webcore, "register_member_page"):
            webcore.register_member_page(
                owner=self, slug="gewinnspiele", name="Gewinnspiele", icon="bi-gift",
                description="An laufenden Gewinnspielen teilnehmen und eigene Gewinne sehen",
                handler=self.member_page, visible=lambda g: self.config.guild(g).member_page(),
            )

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler
        return await dashboard_handler(self, request)

    async def member_page(self, request):
        from .member import member_page_handler
        return await member_page_handler(self, request)

    def _register_view(self, view, message_id):
        add = getattr(self.bot, "add_view", None)
        if add is None:
            return
        try:
            add(view, message_id=int(message_id) if message_id else None)
            self._views.append(view)
        except Exception:  # noqa: BLE001
            log.exception("add_view fehlgeschlagen")

    async def _restore_views(self):
        """Nach (Neu-)Start: für jedes laufende Gewinnspiel die persistente View registrieren."""
        for gid, data in (await self.config.all_guilds()).items():
            lang = data.get("language", DEFAULT_LANGUAGE)
            for gw in (data.get("giveaways") or {}).values():
                if isinstance(gw, dict) and gw.get("status") == "running" and gw.get("message_id"):
                    self._register_view(JoinView(gid, gw, lang), gw["message_id"])

    # ----------------------------------------------------------------- #
    #  Anlegen
    # ----------------------------------------------------------------- #
    def validate(self, guild, *, prize, end_ts, winner_count, description="", required_roles=(),
                 excluded_roles=(), min_member_days=0, bonus_roles=None, now=None):
        """Prüft und normalisiert Eingaben. Rückgabe ``(werte, None)`` oder ``(None, (key, kwargs))``."""
        now = self._now() if now is None else now
        prize = (prize or "").strip()
        if not prize or len(prize) > MAX_PRIZE_LEN:
            return None, ("bad_prize", {"max": MAX_PRIZE_LEN})
        try:
            winner_count = int(winner_count)
        except (TypeError, ValueError):
            winner_count = 0
        if not 1 <= winner_count <= MAX_WINNERS:
            return None, ("bad_winners", {"max": MAX_WINNERS})
        try:
            end_ts = int(end_ts)
        except (TypeError, ValueError):
            end_ts = 0
        if end_ts - now < core.MIN_DURATION - 1 or end_ts - now > core.MAX_DURATION_DAYS * 86400:
            return None, ("bad_duration", {"max_days": core.MAX_DURATION_DAYS})

        def roles(values):
            out = []
            for v in values or []:
                try:
                    r = guild.get_role(int(v))
                except (TypeError, ValueError):
                    r = None
                if r is not None and not r.is_default() and r.id not in out:
                    out.append(r.id)
            return out[:MAX_ROLE_LIST]

        bonus = {}
        for rid, n in (bonus_roles or {}).items():
            try:
                r = guild.get_role(int(rid))
                n = int(n)
            except (TypeError, ValueError):
                continue
            if r is not None and n > 0 and len(bonus) < MAX_BONUS_ROLES:
                bonus[str(r.id)] = min(MAX_BONUS_PER_ROLE, n)
        try:
            days = max(0, min(MAX_MEMBER_DAYS, int(min_member_days or 0)))
        except (TypeError, ValueError):
            days = 0
        return {
            "prize": prize, "description": (description or "").strip()[:MAX_DESC_LEN], "end_ts": end_ts,
            "winner_count": winner_count, "required_roles": roles(required_roles),
            "excluded_roles": roles(excluded_roles), "min_member_days": days, "bonus_roles": bonus,
        }, None

    async def create_giveaway(self, guild, channel, *, host_id, **fields):
        """Legt ein Gewinnspiel an und postet es. Rückgabe ``(datensatz, None)`` oder ``(None, (key, kwargs))``."""
        values, err = self.validate(guild, **fields)
        if err:
            return None, err
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None, ("bad_channel", {})
        counter = self.config.guild(guild).counter
        async with counter.get_lock():
            n = await counter() + 1
            await counter.set(n)
        gw = {
            "id": str(n), "channel_id": channel.id, "message_id": None, "host_id": int(host_id or 0),
            "created_ts": int(self._now()), "entrants": {}, "status": "running", "winner_ids": [],
            "rerolled_out": [], "ended_ts": None, "ended_by": None, "rerolls": 0, **values,
        }
        conf = await self.config.guild(guild).all()
        lang = conf.get("language", DEFAULT_LANGUAGE)
        view = JoinView(guild.id, gw, lang)
        try:
            msg = await channel.send(embed=build_embed(gw, lang, color=conf.get("color")), view=view)
        except discord.HTTPException:
            log.warning("Gewinnspiel konnte nicht gepostet werden (Guild %s, Kanal %s)", guild.id, channel.id)
            return None, ("post_failed", {})
        gw["message_id"] = msg.id
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                gws[gw["id"]] = gw
        self._register_view(view, msg.id)
        return dict(gw), None

    # ----------------------------------------------------------------- #
    #  Teilnehmen / Austreten (gemeinsam für Button und Mitgliederseite)
    # ----------------------------------------------------------------- #
    async def join(self, guild, member, gw_id) -> tuple[str, dict, bool]:
        """Teilnahme eintragen. Rückgabe ``(text_key, kwargs, geändert)``; ``already`` = nimmt schon teil."""
        now = self._now()
        gw_id = str(gw_id)
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                gw = gws.get(gw_id)
                if not isinstance(gw, dict):
                    return "err_unknown", {}, False
                uid = str(member.id)
                if not is_running(gw, now):
                    return "err_ended", {}, False
                if uid in (gw.get("entrants") or {}):
                    return "already", {"tickets": tickets_for(member, gw)}, False
                err = eligibility(member, gw, now)
                if err is not None:
                    return err[0], err[1], False
                gw.setdefault("entrants", {})[uid] = {"name": str(member.display_name)[:64], "ts": int(now)}
                tickets = tickets_for(member, gw)
        self._schedule_refresh(guild, gw_id)
        return "joined", {"tickets": tickets}, True

    async def leave(self, guild, member, gw_id) -> tuple[str, dict, bool]:
        now = self._now()
        gw_id = str(gw_id)
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                gw = gws.get(gw_id)
                if not isinstance(gw, dict):
                    return "err_unknown", {}, False
                if not is_running(gw, now):
                    return "err_ended", {}, False
                if (gw.get("entrants") or {}).pop(str(member.id), None) is None:
                    return "not_entered", {}, False
        self._schedule_refresh(guild, gw_id)
        return "left", {}, True

    async def handle_join_click(self, interaction: discord.Interaction, gw_id: str):
        guild = interaction.guild
        if guild is None:
            return
        lang = await self._lang(guild)
        try:
            key, kwargs, _changed = await self.join(guild, interaction.user, gw_id)
            text = self.text(guild, lang, key, kwargs)
            if key == "already":
                await interaction.response.send_message(text, view=LeaveConfirmView(gw_id, lang), ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            log.exception("Antwort auf Gewinnspiel-Klick fehlgeschlagen")

    async def handle_leave_click(self, interaction: discord.Interaction, gw_id: str):
        guild = interaction.guild
        if guild is None:
            return
        lang = await self._lang(guild)
        try:
            key, kwargs, _changed = await self.leave(guild, interaction.user, gw_id)
            await interaction.response.edit_message(content=self.text(guild, lang, key, kwargs), view=None)
        except discord.HTTPException:
            log.exception("Antwort auf Austreten-Klick fehlgeschlagen")

    # ----------------------------------------------------------------- #
    #  Nachricht aktualisieren (gedrosselt)
    # ----------------------------------------------------------------- #
    def _schedule_refresh(self, guild, gw_id):
        """Embed/Button-Zähler aktualisieren – höchstens alle ``REFRESH_THROTTLE`` Sekunden je Gewinnspiel.
        Klicks in der Wartezeit werden im nächsten Update mitgezählt (liest immer den frischen Stand)."""
        key = (guild.id, str(gw_id))
        task = self._refresh_tasks.get(key)
        if task is not None and not task.done():
            return
        delay = max(0.0, self._last_refresh.get(key, 0.0) + self.REFRESH_THROTTLE - time.monotonic())
        try:
            self._refresh_tasks[key] = asyncio.get_running_loop().create_task(
                self._delayed_refresh(guild, str(gw_id), delay))
        except RuntimeError:
            pass

    async def _delayed_refresh(self, guild, gw_id, delay):
        key = (guild.id, gw_id)
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            self._refresh_tasks.pop(key, None)   # Klicks ab jetzt planen ein neues Update
            self._last_refresh[key] = time.monotonic()
            await self.refresh_message(guild, gw_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Gewinnspiel-Nachricht %s konnte nicht aktualisiert werden", gw_id)

    async def refresh_message(self, guild, gw_id) -> bool:
        conf = await self.config.guild(guild).all()
        gw = (conf.get("giveaways") or {}).get(str(gw_id))
        if not isinstance(gw, dict) or not gw.get("message_id"):
            return False
        channel = self._channel(guild, gw.get("channel_id"))
        if channel is None:
            return False
        lang = conf.get("language", DEFAULT_LANGUAGE)
        try:
            msg = await channel.fetch_message(int(gw["message_id"]))
            await msg.edit(embed=build_embed(gw, lang, color=conf.get("color")), view=JoinView(guild.id, gw, lang))
            return True
        except discord.HTTPException:
            log.debug("Gewinnspiel-Nachricht %s nicht aktualisierbar", gw_id)
            return False

    # ----------------------------------------------------------------- #
    #  Auslosen / Beenden / Neu auslosen / Abbrechen
    # ----------------------------------------------------------------- #
    async def _draw_pool(self, guild, gw, now, exclude) -> list[tuple[int, int]]:
        """Gültige Teilnahmen zum Zeitpunkt der Auslosung: Mitglied noch auf dem Server und
        erfüllt die Voraussetzungen weiterhin; Lose nach den aktuellen Rollen."""
        pool = []
        for uid in list(gw.get("entrants") or {}):
            iid = int(uid)
            if iid in exclude:
                continue
            member = guild.get_member(iid)
            if member is None and hasattr(guild, "fetch_member"):
                try:
                    member = await guild.fetch_member(iid)
                except (discord.NotFound, discord.HTTPException):
                    member = None
            if member is None or eligibility(member, gw, now, check_running=False) is not None:
                continue
            pool.append((iid, tickets_for(member, gw)))
        return pool

    async def end_giveaway(self, guild, gw_id, *, by: str = "auto") -> tuple[str, dict]:
        now = self._now()
        gw_id = str(gw_id).lstrip("#")
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                gw = gws.get(gw_id)
                if not isinstance(gw, dict):
                    return "not_found", {"id": gw_id}
                if gw.get("status") != "running":
                    return "not_running", {"id": gw_id}
                pool = await self._draw_pool(guild, gw, now, set())
                winners = weighted_sample(pool, int(gw.get("winner_count") or 1))
                gw.update(status="ended", winner_ids=winners, ended_ts=int(now), ended_by=by)
                snapshot = dict(gw)
        log.info("Gewinnspiel %s (Guild %s) ausgelost: %d Gewinner aus %d gültigen Teilnahmen",
                 gw_id, guild.id, len(winners), len(pool))
        await self.refresh_message(guild, gw_id)
        await self._announce(guild, snapshot, winners, reroll=False)
        return "ended_ok", {"id": gw_id}

    async def reroll(self, guild, gw_id, user_id=None) -> tuple[str, dict, list[int]]:
        """Neu auslosen: ``user_id`` = nur diesen Gewinner ersetzen, sonst alle. Wer einmal
        „weggelost“ wurde, kann bei diesem Gewinnspiel nicht erneut gezogen werden."""
        now = self._now()
        gw_id = str(gw_id).lstrip("#")
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                gw = gws.get(gw_id)
                if not isinstance(gw, dict):
                    return "not_found", {"id": gw_id}, []
                if gw.get("status") != "ended":
                    return "not_ended", {"id": gw_id}, []
                current = [int(w) for w in gw.get("winner_ids") or []]
                out = {int(w) for w in gw.get("rerolled_out") or []}
                if user_id is not None:
                    user_id = int(user_id)
                    if user_id not in current:
                        return "not_winner", {"id": gw_id, "user": f"<@{user_id}>"}, []
                    pool = await self._draw_pool(guild, gw, now, set(current) | out)
                    picks = weighted_sample(pool, 1)
                    if not picks:
                        return "no_candidates", {}, []
                    new = [picks[0] if w == user_id else w for w in current]
                    out.add(user_id)
                else:
                    pool = await self._draw_pool(guild, gw, now, set(current) | out)
                    picks = weighted_sample(pool, int(gw.get("winner_count") or 1))
                    if not picks:
                        return "no_candidates", {}, []
                    new = picks
                    out |= set(current)
                gw.update(winner_ids=new, rerolled_out=sorted(out), rerolls=int(gw.get("rerolls") or 0) + 1)
                snapshot = dict(gw)
        await self.refresh_message(guild, gw_id)
        await self._announce(guild, snapshot, picks, reroll=True)
        return "rerolled_ok", {"mentions": " ".join(f"<@{p}>" for p in picks)}, picks

    async def cancel_giveaway(self, guild, gw_id) -> tuple[str, dict]:
        gw_id = str(gw_id).lstrip("#")
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                gw = gws.get(gw_id)
                if not isinstance(gw, dict):
                    return "not_found", {"id": gw_id}
                if gw.get("status") != "running":
                    return "not_running", {"id": gw_id}
                gw.update(status="cancelled", ended_ts=int(self._now()), ended_by="cancel")
        await self.refresh_message(guild, gw_id)
        return "cancelled_ok", {"id": gw_id}

    async def delete_giveaway(self, guild, gw_id) -> bool:
        """Entfernt einen beendeten/abgebrochenen Datensatz (laufende erst beenden oder abbrechen)."""
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                gw = gws.get(str(gw_id))
                if not isinstance(gw, dict) or gw.get("status") == "running":
                    return False
                gws.pop(str(gw_id), None)
        return True

    async def _announce(self, guild, gw, winners, *, reroll: bool) -> bool:
        """Ansage im Gewinnspiel-Kanal – Ping ausschließlich für die Gewinner."""
        channel = self._channel(guild, gw.get("channel_id"))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False
        lang = await self._lang(guild)
        prize = discord.utils.escape_mentions(gw.get("prize") or "")
        if winners:
            mentions = " ".join(f"<@{int(w)}>" for w in winners)
            if reroll:
                text = t(lang, "announce_reroll", prize=prize, mentions=mentions)
            else:
                verb = t(lang, "verb_one" if len(winners) == 1 else "verb_many")
                text = t(lang, "announce_winners", prize=prize, mentions=mentions, verb=verb)
        else:
            text = t(lang, "announce_none", prize=prize)
        reference = None
        if gw.get("message_id"):
            reference = discord.MessageReference(message_id=int(gw["message_id"]), channel_id=channel.id,
                                                 guild_id=guild.id, fail_if_not_exists=False)
        allowed = discord.AllowedMentions(everyone=False, roles=False, replied_user=False,
                                          users=[discord.Object(id=int(w)) for w in winners])
        try:
            await channel.send(text[:2000], reference=reference, allowed_mentions=allowed)
            return True
        except discord.HTTPException:
            log.warning("Gewinner-Ansage für Gewinnspiel %s (Guild %s) fehlgeschlagen", gw.get("id"), guild.id)
            return False

    # ----------------------------------------------------------------- #
    #  Hintergrund: fällige Gewinnspiele auslosen (holt nach Downtime nach)
    # ----------------------------------------------------------------- #
    async def process_due(self, now=None) -> int:
        """Lost alle fälligen Gewinnspiele aus – auch solche, deren Ende während einer
        Bot-Downtime lag – und räumt alte beendete Einträge auf. Fehler je Server/Gewinnspiel
        werden geloggt und stoppen die Schleife nie."""
        now = self._now() if now is None else now
        done = 0
        for guild in list(self.bot.guilds):
            try:
                conf = await self.config.guild(guild).all()
            except Exception:  # noqa: BLE001
                log.exception("Config für Guild %s nicht lesbar", getattr(guild, "id", "?"))
                continue
            gws = conf.get("giveaways") or {}
            for gw_id, gw in list(gws.items()):
                if not isinstance(gw, dict) or gw.get("status") != "running":
                    continue
                if float(gw.get("end_ts") or 0) > now:
                    continue
                try:
                    key, _ = await self.end_giveaway(guild, gw_id, by="auto")
                    done += key == "ended_ok"
                except Exception:  # noqa: BLE001
                    log.exception("Auslosung von Gewinnspiel %s (Guild %s) fehlgeschlagen", gw_id, guild.id)
            try:
                await self._prune(guild, conf, now)
            except Exception:  # noqa: BLE001
                log.exception("Aufräumen alter Gewinnspiele (Guild %s) fehlgeschlagen", guild.id)
        return done

    async def _prune(self, guild, conf, now):
        keep = int(conf.get("keep_days") or 0)
        if keep <= 0:
            return
        cutoff = now - keep * 86400
        old = [k for k, g in (conf.get("giveaways") or {}).items()
               if isinstance(g, dict) and g.get("status") in ("ended", "cancelled")
               and (g.get("ended_ts") or g.get("end_ts") or 0) < cutoff]
        if not old:
            return
        async with self._lock(guild):
            async with self.config.guild(guild).giveaways() as gws:
                for k in old:
                    gws.pop(k, None)

    @tasks.loop(seconds=TICK_SECONDS)
    async def _tick(self):
        try:
            await self.process_due()
        except Exception:  # noqa: BLE001 – tasks.loop darf nie an einer Exception sterben
            log.exception("Fehler in der Gewinnspiel-Schleife")

    @_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_red_ready()

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    async def _deny(self, ctx, admin=False) -> bool:
        ok = await (self._is_admin(ctx.author) if admin else self.is_manager(ctx.author))
        if not ok:
            await ctx.send(t(await self._lang(ctx.guild), "no_permission_admin" if admin else "no_permission"))
        return not ok

    @commands.guild_only()
    @commands.hybrid_group(name="giveaway", aliases=["gewinnspiel"])
    async def giveaway(self, ctx: commands.Context):
        """Gewinnspiele starten und verwalten (Server verwalten oder Manager-Rolle)."""

    @giveaway.command(name="start")
    async def giveaway_start(self, ctx: commands.Context, dauer: str, gewinner: int, *, preis: str):
        """Gewinnspiel in diesem Kanal starten, z. B. `[p]giveaway start 1d 2 Discord Nitro`.

        Rollen-Voraussetzungen, Bonus-Lose und Endzeit per Datum gibt es im Dashboard.
        """
        if await self._deny(ctx):
            return
        lang = await self._lang(ctx.guild)
        secs = parse_duration(dauer)
        if secs is None:
            return await ctx.send(t(lang, "bad_duration", max_days=core.MAX_DURATION_DAYS))
        gw, err = await self.create_giveaway(
            ctx.guild, ctx.channel, host_id=ctx.author.id, prize=preis,
            end_ts=int(self._now()) + secs, winner_count=gewinner,
        )
        if err:
            return await ctx.send(t(lang, err[0], **err[1]))
        link = f"https://discord.com/channels/{ctx.guild.id}/{gw['channel_id']}/{gw['message_id']}"
        await ctx.send(t(lang, "started", id=gw["id"], link=link))

    @giveaway.command(name="end")
    async def giveaway_end(self, ctx: commands.Context, giveaway_id: str):
        """Gewinnspiel vorzeitig beenden und sofort auslosen."""
        if await self._deny(ctx):
            return
        key, kw = await self.end_giveaway(ctx.guild, giveaway_id, by="manual")
        await ctx.send(t(await self._lang(ctx.guild), key, **kw))

    @giveaway.command(name="reroll")
    async def giveaway_reroll(self, ctx: commands.Context, giveaway_id: str, nutzer: Optional[discord.User] = None):
        """Neu auslosen: alle Gewinner oder nur `nutzer` ersetzen."""
        if await self._deny(ctx):
            return
        key, kw, _ = await self.reroll(ctx.guild, giveaway_id, nutzer.id if nutzer else None)
        await ctx.send(t(await self._lang(ctx.guild), key, **kw),
                       allowed_mentions=discord.AllowedMentions.none())

    @giveaway.command(name="cancel")
    async def giveaway_cancel(self, ctx: commands.Context, giveaway_id: str):
        """Gewinnspiel abbrechen (ohne Auslosung)."""
        if await self._deny(ctx):
            return
        key, kw = await self.cancel_giveaway(ctx.guild, giveaway_id)
        await ctx.send(t(await self._lang(ctx.guild), key, **kw))

    @giveaway.command(name="list")
    async def giveaway_list(self, ctx: commands.Context):
        """Alle Gewinnspiele dieses Servers auflisten."""
        if await self._deny(ctx):
            return
        lang = await self._lang(ctx.guild)
        gws = await self.config.guild(ctx.guild).giveaways()
        if not gws:
            return await ctx.send(t(lang, "list_empty"))
        rows = [t(lang, "list_header")]
        order = sorted(gws.values(), key=lambda g: (g.get("status") != "running", -int(g.get("end_ts") or 0)))
        for gw in order:
            status = gw.get("status", "running")
            ts = int(gw.get("end_ts") if status == "running" else (gw.get("ended_ts") or gw.get("end_ts") or 0))
            rows.append(t(lang, "list_row", id=gw.get("id"), prize=discord.utils.escape_markdown(
                (gw.get("prize") or "")[:60]), status=t(lang, f"status_{status}"),
                entries=len(gw.get("entrants") or {}), when=f"<t:{ts}:R>"))
        for page in pagify("\n".join(rows), delims=["\n"], page_length=1900):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @giveaway.command(name="managerrole")
    async def giveaway_managerrole(self, ctx: commands.Context, rolle: discord.Role):
        """Manager-Rolle hinzufügen/entfernen (Umschalter, nur „Server verwalten“)."""
        if await self._deny(ctx, admin=True):
            return
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).manager_roles() as roles:
            if rolle.id in roles:
                roles.remove(rolle.id)
                msg = t(lang, "mgr_removed", role=rolle.name)
            else:
                roles.append(rolle.id)
                msg = t(lang, "mgr_added", role=rolle.name)
        await ctx.send(msg, allowed_mentions=discord.AllowedMentions.none())

    @giveaway.command(name="language")
    async def giveaway_language(self, ctx: commands.Context, code: str):
        """Sprache der Gewinnspiel-Nachrichten setzen (de, en)."""
        if await self._deny(ctx, admin=True):
            return
        code = code.lower()
        if code not in LANGUAGES:
            return await ctx.send(t(await self._lang(ctx.guild), "lang_unknown", code=code,
                                    langs=", ".join(LANGUAGES)))
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))
