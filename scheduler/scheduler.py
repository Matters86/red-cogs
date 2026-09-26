from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify

from . import timing
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.scheduler")

MAX_CONTENT = 1900          # Platz für den Rollen-Ping bis zum 2000er-Limit
MAX_EMBED_TITLE = 256
MAX_EMBED_DESC = 4000
MAX_NAME = 80
MAX_ENTRIES = 100           # je Server


class SendError(Exception):
    """Senden fehlgeschlagen – ``args[0]`` ist ein Text-Key aus strings.py, ``kwargs`` die Werte."""

    def __init__(self, key: str, **kwargs):
        super().__init__(key)
        self.key = key
        self.kwargs = kwargs


class Scheduler(commands.Cog):
    """Geplante Nachrichten: einmalig, täglich, wöchentlich, monatlich oder im Intervall – mit Dashboard."""

    TICK_SECONDS = 30

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=862057319448, force_registration=True)
        self.config.register_guild(
            language="de",
            timezone="Europe/Berlin",
            entries={},             # id -> Eintrag
            counter=0,
        )
        self._locks: dict[int, asyncio.Lock] = {}

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    def _now(self) -> float:
        return time.time()

    def _lock(self, guild_or_id) -> asyncio.Lock:
        gid = int(getattr(guild_or_id, "id", guild_or_id))
        return self._locks.setdefault(gid, asyncio.Lock())

    async def can_manage(self, member) -> bool:
        if member is None:
            return False
        if await self.bot.is_owner(member):
            return True
        perms = getattr(member, "guild_permissions", None)
        return bool(perms is not None and (perms.manage_guild or perms.administrator))

    @staticmethod
    def _channel(guild, cid):
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return None
        ch = guild.get_channel(cid)
        if ch is None and hasattr(guild, "get_thread"):
            ch = guild.get_thread(cid)
        return ch

    @staticmethod
    def next_for(entry: dict, tz_name: str, after: float) -> int | None:
        return timing.next_run(entry.get("schedule") or {}, tz_name, after, start_date=entry.get("start_date"),
                               end_date=entry.get("end_date"), anchor_ts=entry.get("anchor_ts"))

    # ----------------------------------------------------------------- #
    #  Red-Datenschutz-API
    # ----------------------------------------------------------------- #
    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Anonymisiert die Ersteller-/Bearbeiter-ID in allen Einträgen (-> 0)."""
        iid = int(user_id)
        try:
            all_guilds = await self.config.all_guilds()
        except Exception:  # noqa: BLE001
            return
        for gid in list(all_guilds):
            try:
                async with self._lock(gid):
                    async with self.config.guild_from_id(gid).entries() as entries:
                        for e in entries.values():
                            if not isinstance(e, dict):
                                continue
                            for key in ("creator_id", "updated_by"):
                                if e.get(key) == iid:
                                    e[key] = 0
            except Exception:  # noqa: BLE001
                log.exception("Datenlöschung in Guild %s fehlgeschlagen", gid)

    # ----------------------------------------------------------------- #
    #  Laden / Entladen / Dashboard
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._tick.start()

    async def cog_unload(self):
        self._tick.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(owner=self, slug="scheduler", name="Geplante Nachrichten", icon="bi-clock-history",
                              handler=self.dashboard_page)

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Einträge prüfen / anlegen / ändern
    # ----------------------------------------------------------------- #
    def normalize(self, guild, raw: dict, *, now=None) -> tuple[dict | None, tuple[str, dict] | None]:
        """Prüft Eingaben (Befehl/Dashboard) und liefert die speicherbaren Felder oder einen Fehler."""
        channel = self._channel(guild, raw.get("channel_id"))
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return None, ("err_channel", {})
        content = (raw.get("content") or "").strip()
        if len(content) > MAX_CONTENT:
            return None, ("err_content_len", {"max": MAX_CONTENT})
        emb = raw.get("embed") or {}
        title = (emb.get("title") or "").strip()
        desc = (emb.get("description") or "").strip()
        image = (emb.get("image_url") or "").strip()
        color = (emb.get("color") or "#5865f2").strip()
        if len(title) > MAX_EMBED_TITLE or len(desc) > MAX_EMBED_DESC:
            return None, ("err_embed_len", {})
        if image and not re.match(r"https?://\S+$", image):
            return None, ("err_image", {})
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return None, ("err_color", {})
        ping = raw.get("ping_role_id")
        ping_id = None
        if ping not in (None, "", 0, "0"):
            role = guild.get_role(int(ping)) if str(ping).isdigit() else None
            if role is None or role.is_default():
                return None, ("err_role", {})
            ping_id = role.id
        if not content and not (title or desc or image):
            return None, ("err_empty", {})
        schedule = raw.get("schedule") or {}
        err = timing.validate(schedule, start_date=raw.get("start_date"), end_date=raw.get("end_date"))
        if err:
            return None, (err, {})
        start = timing.parse_date(raw.get("start_date")) if raw.get("start_date") else None
        end = timing.parse_date(raw.get("end_date")) if raw.get("end_date") else None
        clean_sched = {"type": schedule["type"]}
        if schedule["type"] != "interval":
            h, m = timing.parse_hhmm(schedule.get("time"))
            clean_sched["time"] = f"{h:02d}:{m:02d}"
        elif timing.parse_hhmm(schedule.get("time")):
            h, m = timing.parse_hhmm(schedule.get("time"))
            clean_sched["time"] = f"{h:02d}:{m:02d}"
        if schedule["type"] == "once":
            clean_sched["date"] = str(timing.parse_date(schedule.get("date")))
        if schedule["type"] == "weekly":
            clean_sched["weekdays"] = sorted(set(int(d) for d in schedule.get("weekdays") or []))
        if schedule["type"] == "monthly":
            clean_sched["day"] = int(schedule.get("day"))
        if schedule["type"] == "interval":
            clean_sched["minutes"] = int(schedule.get("minutes"))
        name = (raw.get("name") or "").strip()[:MAX_NAME] or (content or title or desc or "Nachricht")[:40]
        return {
            "name": name, "channel_id": channel.id, "content": content,
            "embed": {"title": title, "description": desc, "image_url": image, "color": color.lower()},
            "ping_role_id": ping_id, "schedule": clean_sched,
            "start_date": str(start) if start else None, "end_date": str(end) if end else None,
            "delete_previous": bool(raw.get("delete_previous")),
        }, None

    async def add_entry(self, guild, raw: dict, *, creator_id: int = 0, paused: bool = False):
        """Neuen Eintrag anlegen. Rückgabe ``(eintrag, None)`` oder ``(None, (key, kwargs))``."""
        now = self._now()
        fields, err = self.normalize(guild, raw, now=now)
        if err:
            return None, err
        conf = await self.config.guild(guild).all()
        if len(conf.get("entries") or {}) >= MAX_ENTRIES:
            return None, ("err_too_many", {"max": MAX_ENTRIES})
        entry = {
            **fields, "paused": bool(paused), "auto_paused": False, "last_message_id": None,
            "last_run_ts": None, "last_skipped_ts": None, "fail_count": 0, "last_error": None,
            "run_count": 0, "creator_id": int(creator_id or 0), "updated_by": int(creator_id or 0),
            "created_ts": int(now), "updated_ts": int(now), "anchor_ts": int(now),
        }
        entry["next_run_ts"] = self.next_for(entry, conf.get("timezone"), now)
        if entry["next_run_ts"] is None:
            return None, ("err_past", {})
        async with self._lock(guild):
            counter = self.config.guild(guild).counter
            n = await counter() + 1
            await counter.set(n)
            entry["id"] = str(n)
            async with self.config.guild(guild).entries() as entries:
                entries[entry["id"]] = entry
        return dict(entry), None

    async def update_entry(self, guild, eid: str, raw: dict, *, editor_id: int = 0):
        now = self._now()
        fields, err = self.normalize(guild, raw, now=now)
        if err:
            return None, err
        tz = await self.config.guild(guild).timezone()
        async with self._lock(guild):
            async with self.config.guild(guild).entries() as entries:
                entry = entries.get(str(eid))
                if not isinstance(entry, dict):
                    return None, ("not_found", {"id": eid})
                sched_changed = entry.get("schedule") != fields["schedule"] or \
                    entry.get("start_date") != fields["start_date"]
                probe = {**entry, **fields, "anchor_ts": int(now) if sched_changed else entry.get("anchor_ts")}
                if self.next_for(probe, tz, now) is None:
                    return None, ("err_past", {})
                entry.update(fields)
                entry.update(updated_ts=int(now), updated_by=int(editor_id or 0), fail_count=0, auto_paused=False,
                             last_error=None)
                if sched_changed:
                    entry["anchor_ts"] = int(now)
                entry["next_run_ts"] = self.next_for(entry, tz, now)
                snapshot = dict(entry)
        return snapshot, None

    async def remove_entry(self, guild, eid) -> bool:
        async with self._lock(guild):
            async with self.config.guild(guild).entries() as entries:
                return entries.pop(str(eid).lstrip("#"), None) is not None

    async def set_paused(self, guild, eid, paused: bool) -> dict | None:
        """Pausieren/Fortsetzen. Fortsetzen setzt Fehlerzähler zurück und rechnet ab jetzt neu."""
        now = self._now()
        tz = await self.config.guild(guild).timezone()
        async with self._lock(guild):
            async with self.config.guild(guild).entries() as entries:
                entry = entries.get(str(eid).lstrip("#"))
                if not isinstance(entry, dict):
                    return None
                entry["paused"] = bool(paused)
                if not paused:
                    entry.update(auto_paused=False, fail_count=0, last_error=None)
                    entry["next_run_ts"] = self.next_for(entry, tz, now)
                return dict(entry)

    async def recompute_all(self, guild):
        """Nach Zeitzonen-Wechsel alle nächsten Termine neu berechnen."""
        now = self._now()
        tz = await self.config.guild(guild).timezone()
        async with self._lock(guild):
            async with self.config.guild(guild).entries() as entries:
                for e in entries.values():
                    if isinstance(e, dict):
                        e["next_run_ts"] = self.next_for(e, tz, now)

    # ----------------------------------------------------------------- #
    #  Senden
    # ----------------------------------------------------------------- #
    @staticmethod
    def build_message(entry: dict, *, ping: bool = True) -> dict:
        """Nachricht zum Senden: ``content``, ``embed``, ``allowed_mentions`` (nur die Ping-Rolle)."""
        text = entry.get("content") or ""
        rid = entry.get("ping_role_id")
        content = (f"<@&{int(rid)}>" + (f"\n{text}" if text else "")) if rid else text
        e = entry.get("embed") or {}
        embed = None
        if e.get("title") or e.get("description") or e.get("image_url"):
            try:
                color = int(str(e.get("color") or "#5865f2").lstrip("#"), 16)
            except ValueError:
                color = 0x5865F2
            embed = discord.Embed(title=e.get("title") or None, description=e.get("description") or None,
                                  color=color)
            if e.get("image_url"):
                embed.set_image(url=e["image_url"])
        allowed = discord.AllowedMentions(
            everyone=False, users=False, replied_user=False,
            roles=[discord.Object(id=int(rid))] if (rid and ping) else False,
        )
        return {"content": content or None, "embed": embed, "allowed_mentions": allowed}

    async def send_entry(self, guild, entry: dict, *, channel=None, ping: bool = True, delete_previous=None):
        """Sendet den Eintrag; wirft ``SendError`` mit Grund. Löscht optional die vorige Nachricht."""
        channel = channel or self._channel(guild, entry.get("channel_id"))
        if channel is None or not hasattr(channel, "send"):
            raise SendError("send_no_channel")
        msg_kwargs = self.build_message(entry, ping=ping)
        try:
            msg = await channel.send(**msg_kwargs)
        except discord.Forbidden:
            raise SendError("send_forbidden") from None
        except discord.HTTPException as exc:
            raise SendError("send_http", status=getattr(exc, "status", "?"), text=str(exc.text or exc)[:200]) from None
        if delete_previous and entry.get("last_message_id"):
            try:
                await channel.get_partial_message(int(entry["last_message_id"])).delete()
            except discord.HTTPException:
                log.debug("Vorherige Nachricht %s nicht löschbar", entry.get("last_message_id"))
        return msg

    async def test_entry(self, guild, eid, *, channel=None) -> tuple[bool, str | None]:
        """„Jetzt testen“: sendet einmal sofort (ohne Ping), ändert weder Zeitplan noch Fehlerzähler."""
        conf = await self.config.guild(guild).all()
        entry = (conf.get("entries") or {}).get(str(eid).lstrip("#"))
        if not isinstance(entry, dict):
            return False, t(conf.get("language"), "not_found", id=eid)
        try:
            await self.send_entry(guild, entry, channel=channel, ping=False, delete_previous=False)
            return True, None
        except SendError as err:
            return False, t(conf.get("language"), err.key, **err.kwargs)

    # ----------------------------------------------------------------- #
    #  Hintergrund-Schleife
    # ----------------------------------------------------------------- #
    async def process_due(self, now=None) -> int:
        """Alle fälligen Einträge aller Server ausführen. Fehler je Server/Eintrag werden abgefangen."""
        now = self._now() if now is None else now
        sent = 0
        for guild in list(self.bot.guilds):
            try:
                sent += await self.process_guild(guild, now)
            except Exception:  # noqa: BLE001
                log.exception("Geplante Nachrichten für Guild %s fehlgeschlagen", getattr(guild, "id", "?"))
        return sent

    async def process_guild(self, guild, now) -> int:
        conf = await self.config.guild(guild).all()
        tz = conf.get("timezone") or "Europe/Berlin"
        lang = conf.get("language", DEFAULT_LANGUAGE)
        sent = 0
        for eid, entry in list((conf.get("entries") or {}).items()):
            if not isinstance(entry, dict) or entry.get("paused"):
                continue
            nrt = entry.get("next_run_ts")
            if nrt is None or nrt > now:
                continue
            try:
                sent += await self._run_due(guild, eid, entry, tz, lang, now)
            except Exception:  # noqa: BLE001
                log.exception("Geplante Nachricht %s (Guild %s) fehlgeschlagen", eid, guild.id)
        return sent

    async def _run_due(self, guild, eid, entry, tz, lang, now) -> int:
        kw = {"start_date": entry.get("start_date"), "end_date": entry.get("end_date"),
              "anchor_ts": entry.get("anchor_ts")}
        due = timing.catch_up(entry.get("schedule") or {}, tz, int(entry["next_run_ts"]), now, **kw)
        ok, error, msg = False, None, None
        if due is not None:
            try:
                msg = await self.send_entry(guild, entry, delete_previous=entry.get("delete_previous"))
                ok = True
            except SendError as err:
                error = t(lang, err.key, **err.kwargs)
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"[:200]
                log.exception("Unerwarteter Fehler beim Senden von Eintrag %s", eid)
        async with self._lock(guild):
            async with self.config.guild(guild).entries() as entries:
                fresh = entries.get(eid)
                if not isinstance(fresh, dict):
                    return 0
                if due is None:
                    # Downtime: letzter Termin > 10 min her -> NICHT nachholen, nur weiterrechnen.
                    fresh["last_skipped_ts"] = int(entry["next_run_ts"])
                    log.info("Eintrag %s (Guild %s): verpassten Termin übersprungen", eid, guild.id)
                elif ok:
                    fresh.update(last_run_ts=int(now), last_message_id=getattr(msg, "id", None), fail_count=0,
                                 last_error=None, run_count=int(fresh.get("run_count") or 0) + 1)
                else:
                    fails = int(fresh.get("fail_count") or 0) + 1
                    fresh.update(fail_count=fails, last_error=error, last_error_ts=int(now))
                    if fails >= timing.MAX_FAILS:
                        fresh.update(paused=True, auto_paused=True)
                        log.warning("Eintrag %s (Guild %s) nach %d Fehlern automatisch pausiert: %s",
                                    eid, guild.id, fails, error)
                fresh["next_run_ts"] = self.next_for(fresh, tz, max(now, due or 0))
        return 1 if ok else 0

    @tasks.loop(seconds=TICK_SECONDS)
    async def _tick(self):
        try:
            await self.process_due()
        except Exception:  # noqa: BLE001 – die Schleife darf nie sterben
            log.exception("Fehler in der Scheduler-Schleife")

    @_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_red_ready()

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    async def _deny(self, ctx) -> bool:
        if await self.can_manage(ctx.author):
            return False
        await ctx.send(t(await self.config.guild(ctx.guild).language(), "no_permission"))
        return True

    @staticmethod
    def _when(ts) -> str:
        return f"<t:{int(ts)}:R> (<t:{int(ts)}:f>)"

    @commands.guild_only()
    @commands.hybrid_group(name="schedule", aliases=["zeitplan"])
    async def schedule(self, ctx: commands.Context):
        """Geplante Nachrichten verwalten (Server verwalten)."""

    @schedule.command(name="add")
    async def schedule_add(self, ctx: commands.Context, kanal: discord.TextChannel, zeitplan: str, *, text: str):
        """Nachricht planen, z. B. `[p]schedule add #news "täglich 09:00" Guten Morgen!`

        Zeitplan: `einmalig 2026-10-01 18:00`, `täglich 09:00`, `wöchentlich mo,mi,fr 18:00`,
        `monatlich 31 12:00`, `alle 2h`, `alle 90m` (min. 10 Minuten). Embed, Rollen-Ping,
        Start-/Enddatum und „vorherige löschen“ gibt es im Dashboard.
        """
        if await self._deny(ctx):
            return
        lang = await self.config.guild(ctx.guild).language()
        sched, err = timing.parse_spec(zeitplan)
        if err:
            return await ctx.send(t(lang, err))
        entry, err = await self.add_entry(ctx.guild, {"channel_id": kanal.id, "content": text, "schedule": sched},
                                          creator_id=ctx.author.id)
        if err:
            return await ctx.send(t(lang, err[0], **err[1]))
        desc = timing.describe(entry["schedule"], lang)
        if entry.get("next_run_ts"):
            await ctx.send(t(lang, "added", id=entry["id"], desc=desc, next=self._when(entry["next_run_ts"])))
        else:
            await ctx.send(t(lang, "added_none", id=entry["id"]))

    @schedule.command(name="list")
    async def schedule_list(self, ctx: commands.Context):
        """Alle geplanten Nachrichten mit nächster Ausführung."""
        if await self._deny(ctx):
            return
        conf = await self.config.guild(ctx.guild).all()
        lang = conf.get("language", DEFAULT_LANGUAGE)
        entries = conf.get("entries") or {}
        if not entries:
            return await ctx.send(t(lang, "list_empty"))
        rows = [t(lang, "list_header", tz=conf.get("timezone"))]
        for e in sorted(entries.values(), key=lambda x: (x.get("next_run_ts") is None, x.get("next_run_ts") or 0)):
            ch = self._channel(ctx.guild, e.get("channel_id"))
            if e.get("auto_paused"):
                state = t(lang, "state_auto_paused", fails=e.get("fail_count", 0))
            elif e.get("paused"):
                state = t(lang, "state_paused")
            elif e.get("next_run_ts"):
                state = t(lang, "state_next", next=self._when(e["next_run_ts"]))
            else:
                state = t(lang, "state_done")
            rows.append(t(lang, "list_row", id=e.get("id"), name=discord.utils.escape_markdown(e.get("name") or ""),
                          channel=ch.mention if ch is not None else "—",
                          desc=timing.describe(e.get("schedule") or {}, lang), state=state))
        for page in pagify("\n".join(rows), delims=["\n"], page_length=1900):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @schedule.command(name="remove", aliases=["delete"])
    async def schedule_remove(self, ctx: commands.Context, eintrag_id: str):
        """Geplante Nachricht löschen."""
        if await self._deny(ctx):
            return
        lang = await self.config.guild(ctx.guild).language()
        ok = await self.remove_entry(ctx.guild, eintrag_id)
        await ctx.send(t(lang, "removed" if ok else "not_found", id=eintrag_id))

    @schedule.command(name="pause")
    async def schedule_pause(self, ctx: commands.Context, eintrag_id: str):
        """Geplante Nachricht pausieren."""
        if await self._deny(ctx):
            return
        lang = await self.config.guild(ctx.guild).language()
        entry = await self.set_paused(ctx.guild, eintrag_id, True)
        await ctx.send(t(lang, "paused" if entry else "not_found", id=eintrag_id))

    @schedule.command(name="resume")
    async def schedule_resume(self, ctx: commands.Context, eintrag_id: str):
        """Pausierte (auch automatisch pausierte) Nachricht fortsetzen."""
        if await self._deny(ctx):
            return
        lang = await self.config.guild(ctx.guild).language()
        entry = await self.set_paused(ctx.guild, eintrag_id, False)
        if entry is None:
            return await ctx.send(t(lang, "not_found", id=eintrag_id))
        if entry.get("next_run_ts"):
            await ctx.send(t(lang, "resumed", id=eintrag_id, next=self._when(entry["next_run_ts"])))
        else:
            await ctx.send(t(lang, "resumed_none", id=eintrag_id))

    @schedule.command(name="test")
    async def schedule_test(self, ctx: commands.Context, eintrag_id: str):
        """Nachricht einmal sofort HIER posten (ohne Ping, Zeitplan bleibt unverändert)."""
        if await self._deny(ctx):
            return
        lang = await self.config.guild(ctx.guild).language()
        ok, err = await self.test_entry(ctx.guild, eintrag_id, channel=ctx.channel)
        if ok:
            await ctx.send(t(lang, "tested", id=eintrag_id))
        else:
            await ctx.send(t(lang, "test_failed", error=err))

    @schedule.command(name="timezone")
    async def schedule_timezone(self, ctx: commands.Context, zeitzone: Optional[str] = None):
        """Zeitzone anzeigen oder setzen (IANA, z. B. Europe/Berlin)."""
        if await self._deny(ctx):
            return
        lang = await self.config.guild(ctx.guild).language()
        if not zeitzone:
            tz = await self.config.guild(ctx.guild).timezone()
            now = datetime.fromtimestamp(self._now(), timing.get_tz(tz)).strftime("%d.%m.%Y %H:%M")
            return await ctx.send(t(lang, "tz_current", tz=tz, now=now))
        if not timing.valid_tz(zeitzone):
            return await ctx.send(t(lang, "tz_unknown", tz=zeitzone[:60]))
        await self.config.guild(ctx.guild).timezone.set(zeitzone)
        await self.recompute_all(ctx.guild)
        await ctx.send(t(lang, "tz_set", tz=zeitzone))

    @schedule.command(name="language")
    async def schedule_language(self, ctx: commands.Context, code: str):
        """Sprache der Bot-Antworten setzen (de, en)."""
        if await self._deny(ctx):
            return
        code = code.lower()
        if code not in LANGUAGES:
            return await ctx.send(t(await self.config.guild(ctx.guild).language(), "lang_unknown", code=code,
                                    langs=", ".join(LANGUAGES)))
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))
