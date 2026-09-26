"""ServerStats – Server-Statistik ohne personenbezogene Daten.

Erfasst pro Server und **Kalendertag in der Zeitzone des Servers** (Guild-Config ``timezone``,
IANA-Name, Standard ``Europe/Berlin``; Sommerzeit inklusive):

* Beitritte, Abgänge, Mitgliederzahl (Tagesendstand = letzter Stand des Tages),
* Nachrichten je Kanal (nur Zählung, keine Inhalte; Bots/Webhooks ausgenommen; Threads zählen
  zu ihrem Elternkanal),
* Voice-Zeit je Kanal in Sekunden (ohne AFK-Kanal, ohne Bots), an lokaler Mitternacht auf die Tage
  aufgeteilt (auch an Sommerzeit-Tagen mit 23 bzw. 25 Stunden).

Ältere Versionen haben in UTC-Tagen gezählt; diese Tage werden unverändert weiterverwendet (Versatz
höchstens ein paar Stunden). Ein Zeitzonen-Wechsel gilt ab dann, bisherige Tage bleiben, wie sie sind.

Datenschutz: Dauerhaft gespeichert werden nur Tages-Summen je Kanal. Laufende Voice-Sitzungen
(Mitglied → Kanal, Startzeit) liegen ausschließlich im Arbeitsspeicher.

Schreiblast: Zähler werden im RAM gepuffert und alle 60 s (sowie beim Entladen) gebündelt und
unter einem Lock in die Config geschrieben. Ein Hintergrund-Loop entfernt stündlich Tage, die
älter als die Aufbewahrung (Standard 90 Tage) sind.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.serverstats")

FLUSH_SECONDS = 60
CLEANUP_EVERY = 60          # jede 60. Runde (≈ stündlich) alte Tage entfernen
DEFAULT_RETENTION = 90
MIN_RETENTION, MAX_RETENTION = 7, 730
RANGES = (7, 30, 90)
DEFAULT_TZ = "Europe/Berlin"

# Vorschläge für das Dashboard (Freitext bleibt möglich – jeder IANA-Name ist erlaubt).
COMMON_TIMEZONES = (
    "Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/Amsterdam", "Europe/Brussels", "Europe/Luxembourg",
    "Europe/Paris", "Europe/London", "Europe/Dublin", "Europe/Lisbon", "Europe/Madrid", "Europe/Rome",
    "Europe/Warsaw", "Europe/Prague", "Europe/Stockholm", "Europe/Helsinki", "Europe/Athens", "Europe/Istanbul",
    "Europe/Moscow", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Sao_Paulo", "Asia/Dubai", "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney", "UTC",
)


def valid_tz(name) -> bool:
    """``True``, wenn ``name`` ein gültiger IANA-Zeitzonen-Name ist (wie im Cog ``scheduler``)."""
    if not isinstance(name, str) or not name.strip() or len(name) > 64 or name != name.strip():
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def get_tz(name) -> ZoneInfo:
    """Zeitzone zum Namen; ungültig/leer -> Standard ``Europe/Berlin`` (notfalls UTC)."""
    for candidate in (name, DEFAULT_TZ):
        if valid_tz(candidate):
            return ZoneInfo(candidate)
    return ZoneInfo("UTC")


def local_date(ts: float, tz=None) -> date:
    """Kalenderdatum eines Zeitstempels in ``tz`` (``None`` = UTC)."""
    return datetime.fromtimestamp(ts, tz or timezone.utc).date()


def day_of(ts: float, tz=None) -> str:
    """Datum ``YYYY-MM-DD`` eines Zeitstempels in der Zeitzone ``tz`` (``None`` = UTC)."""
    return local_date(ts, tz).isoformat()


def next_midnight(ts: float, tz) -> float:
    """Zeitstempel der nächsten lokalen Mitternacht nach ``ts`` (berücksichtigt Sommerzeit: Tage mit 23/25 h)."""
    d = local_date(ts, tz) + timedelta(days=1)
    nxt = datetime(d.year, d.month, d.day, tzinfo=tz).timestamp()
    # Zonen, in denen Mitternacht in einer Zeitumstellungs-Lücke liegt: nie rückwärts laufen.
    return nxt if nxt > ts else ts + 3600


def empty_day() -> dict:
    return {"joins": 0, "leaves": 0, "members": None, "messages": {}, "voice_sec": {}}


def merge_day(target: dict, rec: dict) -> dict:
    """Addiert einen Puffer-Eintrag ``rec`` in den gespeicherten Tag ``target`` (in place)."""
    for key in ("joins", "leaves"):
        target[key] = int(target.get(key) or 0) + int(rec.get(key) or 0)
    if rec.get("members") is not None:
        target["members"] = int(rec["members"])
    target.setdefault("members", None)
    for key in ("messages", "voice_sec"):
        dst = target.setdefault(key, {})
        for cid, n in (rec.get(key) or {}).items():
            dst[str(cid)] = int(round(float(dst.get(str(cid)) or 0) + float(n)))
    return target


class ServerStats(commands.Cog):
    """Server-Statistik: Beitritte, Abgänge, Mitglieder, Nachrichten und Voice-Zeit – nur Zählungen."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=683920147265, force_registration=True)
        self.config.register_guild(
            language="de",
            retention_days=DEFAULT_RETENTION,
            timezone=DEFAULT_TZ,     # IANA-Zeitzone, nach deren Kalendertagen gezählt wird
            ignored_channels=[],     # Kanal-IDs, die nicht gezählt werden (Text und Voice)
            days={},                 # "YYYY-MM-DD" -> {joins, leaves, members, messages{cid:n}, voice_sec{cid:s}}
        )
        self._lock = asyncio.Lock()
        self._pending: dict[int, dict[str, dict]] = {}      # Puffer: guild_id -> Tag -> Zähler
        self._voice: dict[tuple[int, int], list] = {}       # (guild_id, member_id) -> [channel_id, start_ts] – nur RAM
        self._members_written: dict[int, tuple[str, int]] = {}
        self._ignored: dict[int, set[int]] = {}
        self._tz: dict[int, ZoneInfo] = {}
        self._ticks = 0
        self._clock = time.time      # für Tests austauschbar

    # ----------------------------------------------------------------- #
    #  Lebenszyklus & Dashboard
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._loop.start()

    async def cog_unload(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)
        self._loop.cancel()
        try:
            await self.flush()           # Puffer + laufende Voice-Zeit sichern
        except Exception:  # noqa: BLE001
            log.exception("ServerStats: Speichern beim Entladen fehlgeschlagen")
        self._voice.clear()
        self._pending.clear()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Nichts zu löschen: gespeichert werden nur anonyme Tages-Summen je Kanal.

        Die einzige nutzerbezogene Information – eine laufende Voice-Sitzung (wer sitzt seit wann
        in welchem Kanal) – liegt nur im Arbeitsspeicher und wird hier trotzdem verworfen.
        """
        for key in [k for k in self._voice if k[1] == user_id]:
            self._voice.pop(key, None)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        # Bewusst ohne operate_forms: nur Einstellungen und „Zurücksetzen“ (Massenaktion) – die WebCore-Stufe
        # „Bedienen“ wirkt auf dieser Seite wie „Ansehen“.
        webcore.register_page(owner=self, slug="serverstats", name="Statistik", icon="bi-graph-up",
                              handler=self.dashboard_page)

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Puffer
    # ----------------------------------------------------------------- #
    def _bucket(self, guild_id: int, day: str) -> dict:
        return self._pending.setdefault(guild_id, {}).setdefault(
            day, {"joins": 0, "leaves": 0, "messages": {}, "voice_sec": {}})

    def _count(self, guild_id: int, key: str, tz, *, channel_id: int | None = None, amount: float = 1,
               ts: float | None = None):
        rec = self._bucket(guild_id, day_of(self._clock() if ts is None else ts, tz))
        if channel_id is None:
            rec[key] = rec.get(key, 0) + amount
        else:
            sub = rec[key]
            sub[str(channel_id)] = sub.get(str(channel_id), 0) + amount

    def _credit_voice(self, guild_id: int, channel_id: int, start: float, end: float, tz):
        """Voice-Zeit ``start``–``end`` gutschreiben, an lokaler Mitternacht (Zeitzone ``tz``) auf Tage aufgeteilt."""
        while start < end:
            seg_end = min(end, next_midnight(start, tz))
            self._count(guild_id, "voice_sec", tz, channel_id=channel_id, amount=seg_end - start, ts=start)
            start = seg_end

    async def guild_tz(self, guild) -> ZoneInfo:
        """Zeitzone eines Servers (``guild`` oder ID), zwischengespeichert bis ``invalidate``."""
        gid = guild if isinstance(guild, int) else guild.id
        cached = self._tz.get(gid)
        if cached is None:
            cached = get_tz(await self.config.guild_from_id(gid).timezone())
            self._tz[gid] = cached
        return cached

    async def ignored_channels(self, guild) -> set[int]:
        cached = self._ignored.get(guild.id)
        if cached is None:
            cached = {int(c) for c in await self.config.guild(guild).ignored_channels()}
            self._ignored[guild.id] = cached
        return cached

    def invalidate(self, guild_id: int):
        self._ignored.pop(guild_id, None)
        self._tz.pop(guild_id, None)

    async def _active(self, guild) -> bool:
        if guild is None:
            return False
        try:
            return not await self.bot.cog_disabled_in_guild(self, guild)
        except Exception:  # noqa: BLE001
            return True

    async def flush(self) -> int:
        """Puffer gebündelt in die Config schreiben. Rückgabe: Anzahl geschriebener Server."""
        async with self._lock:
            now = self._clock()
            # Laufende Voice-Sitzungen bis jetzt anrechnen (Sitzung läuft ab jetzt weiter).
            tzs: dict[int, ZoneInfo] = {}
            for (gid, _uid), sess in list(self._voice.items()):
                if now > sess[1]:
                    try:
                        tz = tzs[gid] = tzs.get(gid) or await self.guild_tz(gid)
                    except Exception:  # noqa: BLE001 – Sitzung läuft weiter, nächste Runde erneut
                        log.exception("ServerStats: Zeitzone für Server %s nicht lesbar", gid)
                        continue
                    self._credit_voice(gid, sess[0], sess[1], now, tz)
                    sess[1] = now
            pending, self._pending = self._pending, {}
            members: dict[int, int] = {}
            today: dict[int, str] = {}
            for guild in list(getattr(self.bot, "guilds", []) or []):
                count = getattr(guild, "member_count", None)
                if count is None:
                    continue
                try:
                    tz = tzs[guild.id] = tzs.get(guild.id) or await self.guild_tz(guild.id)
                except Exception:  # noqa: BLE001
                    log.exception("ServerStats: Zeitzone für Server %s nicht lesbar", guild.id)
                    continue
                today[guild.id] = day_of(now, tz)
                if self._members_written.get(guild.id) != (today[guild.id], int(count)) or guild.id in pending:
                    members[guild.id] = int(count)
            written = 0
            for gid in set(pending) | set(members):
                try:
                    async with self.config.guild_from_id(gid).days() as days:
                        for day, rec in pending.get(gid, {}).items():
                            merge_day(days.setdefault(day, empty_day()), rec)
                        if gid in members:
                            days.setdefault(today[gid], empty_day())["members"] = members[gid]
                    if gid in members:
                        self._members_written[gid] = (today[gid], members[gid])
                    written += 1
                except Exception:  # noqa: BLE001 – ein Server darf die anderen nicht blockieren
                    log.exception("ServerStats: Schreiben für Server %s fehlgeschlagen", gid)
                    for day, rec in pending.get(gid, {}).items():   # zurück in den Puffer
                        merge_day(self._bucket(gid, day), rec)
            return written

    async def cleanup(self) -> int:
        """Tage entfernen, die älter als die Aufbewahrung sind. Rückgabe: Anzahl entfernter Tage."""
        removed = 0
        async with self._lock:
            now = self._clock()
            all_guilds = await self.config.all_guilds()
            for gid, conf in all_guilds.items():
                try:
                    keep = max(MIN_RETENTION, min(MAX_RETENTION, int(conf.get("retention_days") or DEFAULT_RETENTION)))
                    tz = get_tz(conf.get("timezone"))
                    cutoff = (local_date(now, tz) - timedelta(days=keep - 1)).isoformat()
                    old = [d for d in (conf.get("days") or {}) if d < cutoff]
                    if not old:
                        continue
                    async with self.config.guild_from_id(gid).days() as days:
                        for d in old:
                            days.pop(d, None)
                    removed += len(old)
                except Exception:  # noqa: BLE001
                    log.exception("ServerStats: Aufräumen für Server %s fehlgeschlagen", gid)
        return removed

    @tasks.loop(seconds=FLUSH_SECONDS)
    async def _loop(self):
        try:
            await self.flush()
        except Exception:  # noqa: BLE001 – der Loop darf nie sterben
            log.exception("ServerStats: Flush fehlgeschlagen")
        if self._ticks % CLEANUP_EVERY == 0:
            try:
                await self.cleanup()
            except Exception:  # noqa: BLE001
                log.exception("ServerStats: Aufräumen fehlgeschlagen")
        self._ticks += 1

    @_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_red_ready()
        await self.start_voice_sessions()

    async def start_voice_sessions(self):
        """Nach dem Start: wer schon in Voice sitzt, wird ab jetzt gezählt."""
        now = self._clock()
        for guild in list(self.bot.guilds):
            try:
                if not await self._active(guild):
                    continue
                for ch in list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", []) or []):
                    for m in list(getattr(ch, "members", []) or []):
                        if await self._counts_voice(m, ch):
                            self._voice.setdefault((guild.id, m.id), [ch.id, now])
            except Exception:  # noqa: BLE001
                log.exception("ServerStats: Voice-Start für Server %s fehlgeschlagen", getattr(guild, "id", "?"))

    # ----------------------------------------------------------------- #
    #  Listener
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if await self._active(getattr(member, "guild", None)):
            self._count(member.guild.id, "joins", await self.guild_tz(member.guild))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = getattr(member, "guild", None)
        self._voice.pop((getattr(guild, "id", 0), member.id), None)
        if await self._active(guild):
            self._count(guild.id, "leaves", await self.guild_tz(guild))

    @staticmethod
    def _message_channel_id(channel) -> int | None:
        if isinstance(channel, discord.Thread):
            return channel.parent_id
        return getattr(channel, "id", None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        guild = message.guild
        if guild is None or getattr(message.author, "bot", False) or getattr(message, "webhook_id", None):
            return
        cid = self._message_channel_id(message.channel)
        if cid is None or not await self._active(guild):
            return
        if cid in await self.ignored_channels(guild):
            return
        self._count(guild.id, "messages", await self.guild_tz(guild), channel_id=cid)

    async def _counts_voice(self, member, channel) -> bool:
        if channel is None or getattr(member, "bot", False):
            return False
        guild = member.guild
        afk = getattr(guild, "afk_channel", None)
        if afk is not None and afk.id == channel.id:
            return False
        return channel.id not in await self.ignored_channels(guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        guild = getattr(member, "guild", None)
        if guild is None:
            return
        b, a = getattr(before, "channel", None), getattr(after, "channel", None)
        if (b.id if b else None) == (a.id if a else None):
            return   # nur Stummschalten o. Ä.
        now = self._clock()
        key = (guild.id, member.id)
        sess = self._voice.pop(key, None)
        if sess is not None and now > sess[1]:
            self._credit_voice(guild.id, sess[0], sess[1], now, await self.guild_tz(guild))
        if a is not None and await self._active(guild) and await self._counts_voice(member, a):
            self._voice[key] = [a.id, now]

    # ----------------------------------------------------------------- #
    #  Auswertung
    # ----------------------------------------------------------------- #
    async def get_days(self, guild, n: int) -> list[tuple[str, dict]]:
        """Die letzten ``n`` Kalendertage in der Zeitzone des Servers (inkl. heute) – gespeicherte Werte
        + noch nicht geschriebener Puffer. Fehlende Tage werden mit 0 aufgefüllt; ``members`` wird
        vorwärts fortgeschrieben (``None`` vor dem ersten bekannten Wert), heute = aktuelle Mitgliederzahl."""
        stored = await self.config.guild(guild).days()
        today = local_date(self._clock(), await self.guild_tz(guild))
        keys = [(today - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]
        out = []
        last_members = None
        for d in sorted(stored):
            if d < keys[0] and stored[d].get("members") is not None:
                last_members = stored[d]["members"]
        pend = self._pending.get(guild.id, {})
        for d in keys:
            rec = merge_day(empty_day(), stored.get(d) or {})
            if d in pend:
                merge_day(rec, pend[d])
            if rec.get("members") is not None:
                last_members = rec["members"]
            rec["members"] = last_members
            out.append((d, rec))
        count = getattr(guild, "member_count", None)
        if count is not None and out:
            out[-1][1]["members"] = int(count)
        return out

    @staticmethod
    def summarize(days: list[tuple[str, dict]]) -> dict:
        joins = sum(r["joins"] for _, r in days)
        leaves = sum(r["leaves"] for _, r in days)
        msgs: dict[str, int] = {}
        voice: dict[str, float] = {}
        for _, r in days:
            for cid, v in r["messages"].items():
                msgs[cid] = msgs.get(cid, 0) + int(v)
            for cid, v in r["voice_sec"].items():
                voice[cid] = voice.get(cid, 0) + float(v)
        return {
            "joins": joins, "leaves": leaves, "net": joins - leaves,
            "messages": sum(msgs.values()), "voice_hours": sum(voice.values()) / 3600,
            "by_channel_messages": msgs, "by_channel_voice": voice,
            "members": days[-1][1]["members"] if days else None,
        }

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language() if guild else DEFAULT_LANGUAGE

    async def _say(self, ctx, key, **kwargs):
        await ctx.send(t(await self._lang(ctx.guild), key, **kwargs), allowed_mentions=discord.AllowedMentions.none())

    @staticmethod
    def channel_name(guild, cid) -> str:
        ch = guild.get_channel(int(cid)) if str(cid).isdigit() else None
        return ch.name if ch is not None else f"gelöscht ({cid})"

    async def build_embed(self, guild, days: int = 7) -> discord.Embed:
        lang = await self._lang(guild)
        retention = await self.config.guild(guild).retention_days()
        data = await self.get_days(guild, days)
        s = self.summarize(data)
        from .charts import fmt_num
        tz_name = (await self.guild_tz(guild)).key
        emb = discord.Embed(title=t(lang, "stats_title", server=guild.name)[:256],
                            description=t(lang, "stats_desc", days=days, tz=tz_name), color=0x3DDC97)
        emb.add_field(name=t(lang, "members"), value=fmt_num(s["members"]), inline=True)
        emb.add_field(name=t(lang, "growth"), value=t(lang, "growth_value", net=s["net"], joins=s["joins"],
                                                       leaves=s["leaves"]), inline=True)
        emb.add_field(name=t(lang, "messages"), value=fmt_num(s["messages"]), inline=True)
        emb.add_field(name=t(lang, "voice"), value=fmt_num(round(s["voice_hours"], 1)), inline=True)
        top = sorted(s["by_channel_messages"].items(), key=lambda kv: -kv[1])[:5]
        if top:
            lines = [f"`{fmt_num(n):>6}` #{discord.utils.escape_markdown(self.channel_name(guild, cid))}"
                     for cid, n in top]
            emb.add_field(name=t(lang, "top_channels"), value="\n".join(lines)[:1024], inline=False)
        elif not (s["joins"] or s["leaves"] or s["voice_hours"]):
            emb.add_field(name="​", value=t(lang, "no_data"), inline=False)
        emb.set_footer(text=t(lang, "footer", retention=retention))
        return emb

    @commands.hybrid_command(name="stats")
    @commands.guild_only()
    async def stats(self, ctx: commands.Context, days: Optional[int] = 7):
        """Kurzübersicht der Server-Statistik (Standard: letzte 7 Tage, max. 90)."""
        days = max(1, min(90, int(days or 7)))
        await ctx.send(embed=await self.build_embed(ctx.guild, days))

    @commands.hybrid_group(name="statsset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def statsset(self, ctx: commands.Context):
        """Statistik einstellen."""

    @statsset.command(name="retention")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def statsset_retention(self, ctx: commands.Context, days: int):
        """Wie viele Tage Statistik aufbewahrt wird (7–730, Standard 90)."""
        if not MIN_RETENTION <= days <= MAX_RETENTION:
            return await self._say(ctx, "retention_bad", min=MIN_RETENTION, max=MAX_RETENTION)
        await self.config.guild(ctx.guild).retention_days.set(int(days))
        await self._say(ctx, "retention_set", days=days)

    @statsset.command(name="ignore")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def statsset_ignore(self, ctx: commands.Context,
                              channel: Union[discord.TextChannel, discord.VoiceChannel]):
        """Kanal nicht mehr zählen – erneut ausführen, um ihn wieder zu zählen."""
        async with self.config.guild(ctx.guild).ignored_channels() as ids:
            if channel.id in ids:
                ids.remove(channel.id)
                key = "ignore_off"
            else:
                ids.append(channel.id)
                key = "ignore_on"
        self.invalidate(ctx.guild.id)
        if key == "ignore_on":
            for k in [k for k, s in self._voice.items() if k[0] == ctx.guild.id and s[0] == channel.id]:
                self._voice.pop(k, None)
        await self._say(ctx, key, channel=channel.mention)

    @statsset.command(name="timezone")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def statsset_timezone(self, ctx: commands.Context, zone: Optional[str] = None):
        """Zeitzone anzeigen oder setzen (IANA, z. B. Europe/Berlin) – danach richten sich die Tage."""
        if not zone:
            tz = await self.guild_tz(ctx.guild)
            now = datetime.fromtimestamp(self._clock(), tz).strftime("%d.%m.%Y %H:%M")
            return await self._say(ctx, "tz_current", tz=tz.key, now=now)
        zone = zone.strip()
        if not valid_tz(zone):
            return await self._say(ctx, "tz_unknown", tz=zone[:60].replace("`", "'"))
        await self.config.guild(ctx.guild).timezone.set(zone)
        self.invalidate(ctx.guild.id)
        await self._say(ctx, "tz_set", tz=zone)

    @statsset.command(name="language")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def statsset_language(self, ctx: commands.Context, code: str):
        """Sprache der Antworten (de/en)."""
        code = code.lower().strip()
        if code not in LANGUAGES:
            return await self._say(ctx, "lang_unknown", code=code, langs=", ".join(LANGUAGES))
        await self.config.guild(ctx.guild).language.set(code)
        await self._say(ctx, "lang_set", language=LANGUAGES[code])

    @statsset.command(name="settings")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def statsset_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        conf = await self.config.guild(ctx.guild).all()
        lang = conf["language"]
        ign = [ctx.guild.get_channel(int(c)) for c in conf["ignored_channels"]]
        emb = discord.Embed(title=t(lang, "settings_title"), color=0x3DDC97)
        emb.add_field(name=t(lang, "settings_retention"), value=t(lang, "days_unit", n=conf["retention_days"]))
        emb.add_field(name=t(lang, "settings_ignored"),
                      value=(", ".join(c.mention for c in ign if c) or t(lang, "none"))[:1024])
        emb.add_field(name=t(lang, "settings_lang"), value=LANGUAGES.get(lang, lang))
        emb.add_field(name=t(lang, "settings_tz"), value=(await self.guild_tz(ctx.guild)).key)
        await ctx.send(embed=emb)
