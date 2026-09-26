"""Levels – XP für Nachrichten und Voice, Level-Up-Meldungen, Rollen-Belohnungen, Rangkarte.

* XP pro Nachricht (Standard 15–25, Cooldown 60 s pro Mitglied), optional Voice-XP pro Minute
  (nicht allein im Kanal, nicht stumm/taub, nicht im AFK-Kanal).
* Levelkurve wie MEE6: von Level L nach L+1 braucht man ``5·L² + 50·L + 100`` XP.
* Ausgeschlossene Kanäle/Rollen, XP-Multiplikator-Rollen (es gilt der höchste Faktor).
* Level-Up-Meldung: aus / im selben Kanal / fester Kanal / DM; Platzhalter {user} {name} {level}
  {server}; gepingt wird höchstens das Mitglied selbst.
* Rollen-Belohnungen je Level (stapeln oder nur die höchste) mit Hierarchie-/Rechteprüfung.
* Rangkarte als Bild (Pillow, ``card.py`` per ``asyncio.to_thread``).

Datenhaltung: Config pro Mitglied (``xp``, ``level``, ``last_msg_ts``). Alle Mitgliedsdaten eines
Servers werden beim ersten Zugriff einmal mit ``Config.all_members`` geladen und im RAM gehalten;
Änderungen werden alle 60 s bzw. beim Entladen gebündelt unter einem Lock geschrieben.
"""

from __future__ import annotations

import asyncio
import collections
import io
import logging
import random
import re
import time
from typing import Literal, Optional, Union

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

from . import card as cardmod
from .dashboard import dashboard_handler
from .member import member_handler
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.levels")

FLUSH_SECONDS = 60
MAX_XP_PER_MESSAGE = 1000
MAX_COOLDOWN = 3600
MAX_VOICE_XP = 100
MIN_MULT, MAX_MULT = 0.1, 5.0
MAX_LEVEL = 500
MAX_XP_TOTAL = 10 ** 9
MAX_GIVE = 10 ** 7
MAX_ANNOUNCE = 1000
ANNOUNCE_MODES = ("off", "same", "channel", "dm")
CARD_FILENAME = "rang.png"

AVATAR_TIMEOUT = 8
AVATAR_MAX_BYTES = 4 * 1024 * 1024
AVATAR_CACHE = 64
AVATAR_TTL = 600

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_PH_RE = re.compile(r"\{(user|name|level|server)\}")

# Rechte, die als „Moderation/Verwaltung“ gelten – solche Rollen trägt per Befehl nur der
# Server-Inhaber bzw. Bot-Owner als Belohnung ein (gleicher Gedanke wie webcore.can_grant_role).
DANGEROUS_PERMS = ("administrator", "manage_guild", "manage_roles", "manage_channels", "ban_members",
                   "kick_members", "manage_messages", "moderate_members", "manage_webhooks",
                   "mention_everyone", "manage_nicknames", "manage_expressions")


# --------------------------------------------------------------------------- #
#  Levelkurve
# --------------------------------------------------------------------------- #
def xp_to_next(level: int) -> int:
    """XP, die man von ``level`` nach ``level + 1`` braucht (MEE6-Kurve)."""
    level = max(0, int(level))
    return 5 * level * level + 50 * level + 100


def total_xp_for_level(level: int) -> int:
    """Gesamt-XP, ab denen man ``level`` erreicht."""
    return sum(xp_to_next(i) for i in range(max(0, int(level))))


def level_from_xp(xp: int) -> int:
    xp = max(0, int(xp))
    level = 0
    while xp >= xp_to_next(level):
        xp -= xp_to_next(level)
        level += 1
    return level


def progress(xp: int) -> tuple[int, int, int]:
    """``(level, xp_im_level, xp_bis_zum_nächsten)``."""
    level = level_from_xp(xp)
    return level, max(0, int(xp)) - total_xp_for_level(level), xp_to_next(level)


def valid_color(value) -> Optional[str]:
    v = str(value or "").strip()
    if v and not v.startswith("#"):
        v = "#" + v
    return v.lower() if HEX_RE.match(v) else None


def fill_placeholders(text: str, values: dict) -> str:
    """Ersetzt NUR die bekannten Platzhalter – unbekannte ``{…}`` bleiben stehen (kein ``str.format``)."""
    return _PH_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), str(text or ""))


def fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", ".")


class Levels(commands.Cog):
    """XP für Nachrichten und Voice, Level-Up-Meldungen, Rollen-Belohnungen und Rangkarte."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=427610958372, force_registration=True)
        self.config.register_guild(
            enabled=True,
            language="de",
            xp_min=15,
            xp_max=25,
            cooldown=60,              # Sekunden pro Mitglied
            voice_enabled=False,
            voice_xp=5,               # XP pro Minute in Voice
            excluded_channels=[],
            excluded_roles=[],
            multipliers={},           # "rollen_id" -> Faktor (es gilt der höchste)
            announce_mode="same",     # off | same | channel | dm
            announce_channel=None,
            announce_text="",         # leer = Standardtext
            rewards={},               # "level" -> rollen_id
            stack_rewards=True,       # True: alle erreichten Rollen, False: nur die höchste
            card_color="#3ddc97",
            member_page=True,         # Seite „Mein Level“ im Mitglieder-Bereich
        )
        self.config.register_member(xp=0, level=0, last_msg_ts=0)
        self._lock = asyncio.Lock()
        self._load_locks: dict[int, asyncio.Lock] = {}
        self._data: dict[int, dict[int, dict]] = {}      # guild_id -> member_id -> {xp, level, last_msg_ts}
        self._dirty: dict[int, set[int]] = {}
        self._version: dict[int, int] = {}
        self._ranking: dict[int, tuple[int, list]] = {}
        self._avatar_cache: collections.OrderedDict = collections.OrderedDict()
        self._clock = time.time        # für Tests austauschbar
        self._random = random.randint  # für Tests austauschbar

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
            await self.flush()
        except Exception:  # noqa: BLE001
            log.exception("Levels: Speichern beim Entladen fehlgeschlagen")
        self._avatar_cache.clear()

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(owner=self, slug="levels", name="Level", icon="bi-trophy", handler=self.dashboard_page)
        if hasattr(webcore, "register_member_page"):  # ältere WebCore-Versionen ohne „Mein Bereich“
            webcore.register_member_page(
                owner=self,
                visible=lambda g: self.config.guild(g).member_page(),
                slug="level",
                name="Mein Level",
                icon="bi-trophy",
                handler=self.member_page,
                description="Dein Rang, dein Fortschritt und die Top 10",
            )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    async def member_page(self, request):
        return await member_handler(self, request)

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Löscht XP, Level und Cooldown-Zeit des Nutzers auf allen Servern."""
        async with self._lock:
            all_members = await self.config.all_members()
            for gid, members in all_members.items():
                if user_id in members or str(user_id) in members:
                    await self.config.member_from_ids(int(gid), user_id).clear()
            for gid, data in self._data.items():
                if data.pop(user_id, None) is not None:
                    self._bump(gid)
                self._dirty.get(gid, set()).discard(user_id)
        for key in [k for k in self._avatar_cache if k[0] == user_id]:
            self._avatar_cache.pop(key, None)

    # ----------------------------------------------------------------- #
    #  Datenhaltung (RAM + gebündeltes Schreiben)
    # ----------------------------------------------------------------- #
    async def guild_data(self, guild_id: int) -> dict[int, dict]:
        data = self._data.get(guild_id)
        if data is not None:
            return data
        lock = self._load_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            if guild_id not in self._data:
                raw = await self.config.all_members(discord.Object(id=guild_id))
                self._data[guild_id] = {
                    int(uid): {"xp": int(v.get("xp", 0)), "level": int(v.get("level", 0)),
                               "last_msg_ts": float(v.get("last_msg_ts", 0) or 0)}
                    for uid, v in raw.items()
                }
            return self._data[guild_id]

    def _bump(self, guild_id: int):
        self._version[guild_id] = self._version.get(guild_id, 0) + 1

    def _mark(self, guild_id: int, member_id: int):
        self._dirty.setdefault(guild_id, set()).add(member_id)
        self._bump(guild_id)

    async def flush(self) -> int:
        """Geänderte Mitglieder gebündelt schreiben. Rückgabe: Anzahl geschriebener Datensätze."""
        written = 0
        async with self._lock:
            dirty, self._dirty = self._dirty, {}
            for gid, uids in dirty.items():
                data = self._data.get(gid, {})
                for uid in uids:
                    rec = data.get(uid)
                    try:
                        if rec is None:
                            await self.config.member_from_ids(gid, uid).clear()
                        else:
                            await self.config.member_from_ids(gid, uid).set(
                                {"xp": int(rec["xp"]), "level": int(rec["level"]),
                                 "last_msg_ts": float(rec["last_msg_ts"])})
                        written += 1
                    except Exception:  # noqa: BLE001 – beim nächsten Durchlauf erneut versuchen
                        log.exception("Levels: Schreiben %s/%s fehlgeschlagen", gid, uid)
                        self._dirty.setdefault(gid, set()).add(uid)
        return written

    @tasks.loop(seconds=FLUSH_SECONDS)
    async def _loop(self):
        try:
            await self.voice_tick()
        except Exception:  # noqa: BLE001 – der Loop darf nie sterben
            log.exception("Levels: Voice-XP fehlgeschlagen")
        try:
            await self.flush()
        except Exception:  # noqa: BLE001
            log.exception("Levels: Flush fehlgeschlagen")

    @_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_red_ready()

    # ----------------------------------------------------------------- #
    #  Rangliste
    # ----------------------------------------------------------------- #
    async def ranking(self, guild) -> list[tuple[int, dict]]:
        """Mitglieder mit XP, die noch auf dem Server sind – sortiert (XP absteigend). Gecacht bis zur nächsten Änderung."""
        data = await self.guild_data(guild.id)
        ver = self._version.get(guild.id, 0)
        hit = self._ranking.get(guild.id)
        if hit and hit[0] == ver:
            return hit[1]
        rows = [(uid, rec) for uid, rec in data.items() if rec["xp"] > 0 and guild.get_member(uid) is not None]
        rows.sort(key=lambda r: (-r[1]["xp"], r[0]))
        self._ranking[guild.id] = (ver, rows)
        return rows

    async def rank_of(self, guild, member_id: int) -> tuple[Optional[int], int]:
        rows = await self.ranking(guild)
        for i, (uid, _) in enumerate(rows, 1):
            if uid == member_id:
                return i, len(rows)
        return None, len(rows)

    async def member_record(self, guild, member_id: int) -> dict:
        data = await self.guild_data(guild.id)
        rec = data.get(member_id) or {"xp": 0, "level": 0, "last_msg_ts": 0}
        return dict(rec)

    # ----------------------------------------------------------------- #
    #  XP
    # ----------------------------------------------------------------- #
    @staticmethod
    def multiplier(member, conf: dict) -> float:
        mults = conf.get("multipliers") or {}
        best = None
        for r in getattr(member, "roles", []):
            f = mults.get(str(r.id))
            if f is not None:
                best = float(f) if best is None else max(best, float(f))
        return 1.0 if best is None else best

    @staticmethod
    def is_excluded(member, conf: dict) -> bool:
        ex = {int(r) for r in conf.get("excluded_roles") or []}
        return any(r.id in ex for r in getattr(member, "roles", []))

    async def set_xp(self, member, xp: int, *, channel=None, announce: bool = True, conf: dict | None = None):
        """Setzt die XP eines Mitglieds (0 … MAX_XP_TOTAL). Rückgabe ``(alt_level, neu_level)``."""
        guild = member.guild
        data = await self.guild_data(guild.id)
        rec = data.setdefault(member.id, {"xp": 0, "level": 0, "last_msg_ts": 0})
        rec["xp"] = max(0, min(MAX_XP_TOTAL, int(xp)))
        old, new = rec["level"], level_from_xp(rec["xp"])
        rec["level"] = new
        self._mark(guild.id, member.id)
        if new != old:
            await self._level_changed(member, old, new, channel=channel, announce=announce, conf=conf)
        return old, new

    async def add_xp(self, member, amount: int, **kwargs):
        rec = await self.member_record(member.guild, member.id)
        return await self.set_xp(member, rec["xp"] + int(amount), **kwargs)

    async def reset_member(self, member):
        """Setzt XP/Level/Cooldown zurück (Datensatz wird gelöscht) und gleicht Belohnungen ab."""
        data = await self.guild_data(member.guild.id)
        had = data.pop(member.id, None)
        self._mark(member.guild.id, member.id)
        if had and had.get("level"):
            await self.sync_rewards(member, 0)
        return had

    async def _level_changed(self, member, old: int, new: int, *, channel=None, announce: bool = True,
                             conf: dict | None = None):
        conf = conf or await self.config.guild(member.guild).all()
        try:
            await self.sync_rewards(member, new, conf)
        except Exception:  # noqa: BLE001
            log.exception("Levels (%s): Belohnungen für %s fehlgeschlagen", member.guild.id, member.id)
        if new > old and announce:
            try:
                await self.announce(member, new, channel, conf)
            except Exception:  # noqa: BLE001
                log.exception("Levels (%s): Level-Up-Meldung fehlgeschlagen", member.guild.id)

    async def handle_message(self, message) -> int:
        """XP für eine Nachricht vergeben (mit allen Regeln). Rückgabe: vergebene XP (0 = keine)."""
        guild = message.guild
        author = message.author
        if guild is None or getattr(author, "bot", False) or getattr(message, "webhook_id", None):
            return 0
        if not isinstance(author, discord.Member) and not hasattr(author, "roles"):
            return 0
        try:
            if await self.bot.cog_disabled_in_guild(self, guild):
                return 0
        except Exception:  # noqa: BLE001
            pass
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return 0
        ch = message.channel
        cid = ch.parent_id if isinstance(ch, discord.Thread) else getattr(ch, "id", None)
        excluded = {int(c) for c in conf["excluded_channels"]}
        if cid in excluded or getattr(ch, "id", None) in excluded or self.is_excluded(author, conf):
            return 0
        data = await self.guild_data(guild.id)
        rec = data.setdefault(author.id, {"xp": 0, "level": 0, "last_msg_ts": 0})
        now = self._clock()
        if now - float(rec.get("last_msg_ts") or 0) < int(conf["cooldown"]):
            return 0
        rec["last_msg_ts"] = now          # sofort setzen (kein await dazwischen) -> kein Doppel-XP
        lo, hi = sorted((int(conf["xp_min"]), int(conf["xp_max"])))
        amount = max(1, int(round(self._random(lo, hi) * self.multiplier(author, conf))))
        await self.set_xp(author, rec["xp"] + amount, channel=ch, conf=conf)
        return amount

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            await self.handle_message(message)
        except Exception:  # noqa: BLE001
            log.exception("Levels: Fehler bei Nachricht %s", getattr(message, "id", "?"))

    @staticmethod
    def voice_eligible(member, channel, conf: dict) -> bool:
        """Voice-XP-Regeln: kein Bot, nicht stumm/taub, nicht AFK, nicht ausgeschlossen, nicht allein."""
        if channel is None or getattr(member, "bot", False):
            return False
        guild = member.guild
        afk = getattr(guild, "afk_channel", None)
        if afk is not None and afk.id == channel.id:
            return False
        if channel.id in {int(c) for c in conf.get("excluded_channels") or []}:
            return False
        vs = getattr(member, "voice", None)
        if vs is None or vs.self_mute or vs.mute or vs.self_deaf or vs.deaf:
            return False
        if Levels.is_excluded(member, conf):
            return False
        humans = [m for m in getattr(channel, "members", []) if not getattr(m, "bot", False)]
        return len(humans) >= 2

    async def voice_tick(self) -> int:
        """Einmal pro Minute: Voice-XP an alle berechtigten Mitglieder. Rückgabe: Anzahl belohnt."""
        count = 0
        for guild in list(self.bot.guilds):
            try:
                conf = await self.config.guild(guild).all()
                if not (conf["enabled"] and conf["voice_enabled"]):
                    continue
                try:
                    if await self.bot.cog_disabled_in_guild(self, guild):
                        continue
                except Exception:  # noqa: BLE001
                    pass
                channels = list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", []) or [])
                for ch in channels:
                    for m in list(getattr(ch, "members", []) or []):
                        if self.voice_eligible(m, ch, conf):
                            amount = max(1, int(round(int(conf["voice_xp"]) * self.multiplier(m, conf))))
                            await self.add_xp(m, amount, channel=None, conf=conf)
                            count += 1
            except Exception:  # noqa: BLE001 – ein Server darf die anderen nicht blockieren
                log.exception("Levels: Voice-XP für Server %s fehlgeschlagen", getattr(guild, "id", "?"))
        return count

    # ----------------------------------------------------------------- #
    #  Belohnungen
    # ----------------------------------------------------------------- #
    @staticmethod
    def bot_can_manage(guild, role) -> bool:
        me = guild.me
        if role is None or me is None or role.is_default() or getattr(role, "managed", False):
            return False
        perms = getattr(me, "guild_permissions", None)
        if perms is not None and not (perms.manage_roles or perms.administrator):
            return False
        return role < me.top_role

    @staticmethod
    def has_dangerous_perms(role) -> bool:
        p = getattr(role, "permissions", None)
        return any(bool(getattr(p, name, False)) for name in DANGEROUS_PERMS)

    async def user_can_grant(self, member, role) -> bool:
        """Darf ``member`` (per Befehl) ``role`` als Belohnung eintragen? Owner/Server-Inhaber immer."""
        if await self.bot.is_owner(member) or getattr(member.guild, "owner_id", None) == member.id:
            return True
        if self.has_dangerous_perms(role):
            return False
        return role < member.top_role

    async def sync_rewards(self, member, level: int, conf: dict | None = None) -> tuple[list, list]:
        """Rollen-Belohnungen passend zu ``level`` vergeben/entfernen. Rückgabe ``(vergeben, entfernt)``."""
        guild = member.guild
        conf = conf or await self.config.guild(guild).all()
        rewards = []
        for lvl, rid in (conf.get("rewards") or {}).items():
            role = guild.get_role(int(rid)) if str(rid).isdigit() else None
            if role is not None and str(lvl).isdigit():
                rewards.append((int(lvl), role))
        if not rewards:
            return [], []
        reached = [(lvl, r) for lvl, r in rewards if lvl <= level]
        if conf.get("stack_rewards", True):
            want = {r.id for _, r in reached}
        else:
            want = {max(reached, key=lambda x: x[0])[1].id} if reached else set()
        have = {r.id for r in getattr(member, "roles", [])}
        add = [r for _, r in rewards if r.id in want and r.id not in have and self.bot_can_manage(guild, r)]
        remove = [r for _, r in rewards if r.id not in want and r.id in have and self.bot_can_manage(guild, r)]
        # dieselbe Rolle für mehrere Level: nicht doppelt
        add = list({r.id: r for r in add}.values())
        remove = [r for r in {r.id: r for r in remove}.values() if r.id not in want]
        try:
            if add:
                await member.add_roles(*add, reason=f"Level {level} erreicht")
            if remove:
                await member.remove_roles(*remove, reason=f"Level {level} – Belohnung angepasst")
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("Levels (%s): Rollen für %s nicht geändert: %s", guild.id, member.id, exc)
            return [], []
        return add, remove

    async def sync_all(self, guild) -> tuple[int, int]:
        added = removed = 0
        conf = await self.config.guild(guild).all()
        for uid, rec in list((await self.guild_data(guild.id)).items()):
            m = guild.get_member(uid)
            if m is None:
                continue
            a, r = await self.sync_rewards(m, rec["level"], conf)
            added += len(a)
            removed += len(r)
        return added, removed

    # ----------------------------------------------------------------- #
    #  Level-Up-Meldung
    # ----------------------------------------------------------------- #
    def announce_text(self, member, level: int, conf: dict) -> str:
        lang = conf.get("language") or DEFAULT_LANGUAGE
        raw = (conf.get("announce_text") or "").strip() or t(lang, "levelup_default")
        name = discord.utils.escape_markdown(getattr(member, "display_name", None) or getattr(member, "name", "?"))
        values = {"user": getattr(member, "mention", name), "name": name, "level": level,
                  "server": discord.utils.escape_markdown(member.guild.name)}
        return fill_placeholders(raw, values)[:2000]

    async def announce(self, member, level: int, channel=None, conf: dict | None = None) -> bool:
        """Postet die Level-Up-Meldung laut Einstellung. Rückgabe: gesendet?"""
        guild = member.guild
        conf = conf or await self.config.guild(guild).all()
        mode = conf.get("announce_mode") or "same"
        if mode == "off":
            return False
        text = self.announce_text(member, level, conf)
        mentions = discord.AllowedMentions(everyone=False, roles=False, replied_user=False, users=[member])
        if mode == "dm":
            try:
                await member.send(text, allowed_mentions=discord.AllowedMentions.none())
                return True
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                return False
        target = channel if mode == "same" else None
        if mode == "channel" and conf.get("announce_channel"):
            target = guild.get_channel(int(conf["announce_channel"]))
        if target is None or not hasattr(target, "send"):
            return False
        me = guild.me
        if me is not None and hasattr(target, "permissions_for") and not target.permissions_for(me).send_messages:
            return False
        try:
            await target.send(text, allowed_mentions=mentions)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    # ----------------------------------------------------------------- #
    #  Rangkarte
    # ----------------------------------------------------------------- #
    async def avatar_bytes(self, member) -> bytes | None:
        """Avatar (PNG, 256 px) mit Timeout, Größenlimit und kleinem RAM-Cache; Fehler -> ``None``."""
        asset = getattr(member, "display_avatar", None)
        if asset is None:
            return None
        try:
            if hasattr(asset, "with_static_format"):
                asset = asset.with_static_format("png").with_size(256)
        except Exception:  # noqa: BLE001
            pass
        key = (getattr(member, "id", 0), str(getattr(asset, "key", None) or getattr(asset, "url", "")))
        hit = self._avatar_cache.get(key)
        if hit and time.monotonic() - hit[0] < AVATAR_TTL:
            self._avatar_cache.move_to_end(key)
            return hit[1]
        try:
            data = await asyncio.wait_for(asset.read(), timeout=AVATAR_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 – Timeout, HTTP, kein Avatar …
            log.debug("Avatar von %s nicht geladen: %r", getattr(member, "id", "?"), exc)
            return None
        if not data or len(data) > AVATAR_MAX_BYTES:
            return None
        self._avatar_cache[key] = (time.monotonic(), data)
        while len(self._avatar_cache) > AVATAR_CACHE:
            self._avatar_cache.popitem(last=False)
        return data

    async def render_card(self, member, conf: dict | None = None) -> bytes:
        guild = member.guild
        conf = conf or await self.config.guild(guild).all()
        lang = conf.get("language") or DEFAULT_LANGUAGE
        rec = await self.member_record(guild, member.id)
        level, into, needed = progress(rec["xp"])
        rank, _ = await self.rank_of(guild, member.id)
        avatar = await self.avatar_bytes(member)
        return await asyncio.to_thread(
            cardmod.render_rank_card,
            name=getattr(member, "display_name", None) or getattr(member, "name", ""),
            level=level, rank=rank, xp_into=into, xp_needed=needed, total_xp=rec["xp"],
            server=guild.name, avatar=avatar, accent=valid_color(conf.get("card_color")) or "#3ddc97",
            labels={"level": t(lang, "card_level"), "rank": t(lang, "card_rank"),
                    "xp": t(lang, "card_xp"), "total": t(lang, "card_total")},
        )

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language() if guild else DEFAULT_LANGUAGE

    async def _say(self, ctx, key, **kwargs):
        await ctx.send(t(await self._lang(ctx.guild), key, **kwargs), allowed_mentions=discord.AllowedMentions.none())

    async def rank_embed(self, member, conf: dict) -> discord.Embed:
        lang = conf.get("language") or DEFAULT_LANGUAGE
        rec = await self.member_record(member.guild, member.id)
        level, into, needed = progress(rec["xp"])
        rank, _ = await self.rank_of(member.guild, member.id)
        name = discord.utils.escape_markdown(member.display_name)
        emb = discord.Embed(title=t(lang, "rank_title", name=name)[:256], color=int(
            (valid_color(conf.get("card_color")) or "#3ddc97")[1:], 16))
        emb.description = t(lang, "rank_line", rank=rank or "–", level=level, xp=fmt_int(rec["xp"]),
                            left=fmt_int(needed - into), next=level + 1)
        return emb

    @commands.hybrid_command(name="rank")
    @commands.guild_only()
    async def rank(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Zeigt deine Rangkarte (oder die eines anderen Mitglieds)."""
        member = member or ctx.author
        conf = await self.config.guild(ctx.guild).all()
        if not conf["enabled"]:
            return await self._say(ctx, "disabled")
        if member.bot:
            return await self._say(ctx, "rank_bot")
        perms = ctx.channel.permissions_for(ctx.guild.me) if ctx.guild.me is not None else None
        if perms is None or perms.attach_files:
            try:
                async with ctx.typing():
                    png = await self.render_card(member, conf)
                return await ctx.send(file=discord.File(io.BytesIO(png), filename=CARD_FILENAME),
                                      allowed_mentions=discord.AllowedMentions.none())
            except Exception:  # noqa: BLE001 – Bild ist Beiwerk: Embed als Ersatz
                log.exception("Levels: Rangkarte fehlgeschlagen")
        await ctx.send(embed=await self.rank_embed(member, conf))

    @commands.hybrid_command(name="leaderboard", aliases=["top"])
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context, page: Optional[int] = 1):
        """Rangliste des Servers (10 pro Seite)."""
        conf = await self.config.guild(ctx.guild).all()
        lang = conf["language"]
        if not conf["enabled"]:
            return await self._say(ctx, "disabled")
        rows = await self.ranking(ctx.guild)
        pages = max(1, (len(rows) + 9) // 10)
        page = int(page or 1)
        if not 1 <= page <= pages:
            return await self._say(ctx, "lb_page_bad", pages=pages)
        emb = discord.Embed(title=t(lang, "lb_title", server=ctx.guild.name)[:256], color=0x3DDC97)
        lines = []
        for i, (uid, rec) in enumerate(rows[(page - 1) * 10: page * 10], (page - 1) * 10 + 1):
            m = ctx.guild.get_member(uid)
            name = discord.utils.escape_markdown(m.display_name if m else str(uid))[:40]
            lines.append(t(lang, "lb_line", rank=i, name=name, level=rec["level"], xp=fmt_int(rec["xp"])))
        emb.description = ("\n".join(lines) or t(lang, "lb_empty"))[:4096]
        mine, _ = await self.rank_of(ctx.guild, ctx.author.id)
        emb.set_footer(text=t(lang, "lb_footer", page=page, pages=pages,
                              rank=f"#{mine}" if mine else t(lang, "rank_unranked")))
        await ctx.send(embed=emb, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_group(name="levelset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def levelset(self, ctx: commands.Context):
        """Levelsystem einstellen."""

    @levelset.command(name="xp")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_xp(self, ctx: commands.Context, action: Literal["give", "take", "set", "reset"],
                    member: discord.Member, amount: Optional[int] = None):
        """XP geben, nehmen, setzen oder zurücksetzen (ohne Level-Up-Meldung)."""
        lang = await self._lang(ctx.guild)
        if member.bot:
            return await self._say(ctx, "xp_bot")
        if action == "reset":
            await self.reset_member(member)
        else:
            limit = MAX_XP_TOTAL if action == "set" else MAX_GIVE
            lowest = 0 if action == "set" else 1
            if amount is None or not lowest <= amount <= limit:
                return await self._say(ctx, "xp_amount_bad", max=fmt_int(limit))
            rec = await self.member_record(ctx.guild, member.id)
            new = {"give": rec["xp"] + amount, "take": rec["xp"] - amount, "set": amount}[action]
            await self.set_xp(member, new, announce=False)
        rec = await self.member_record(ctx.guild, member.id)
        await ctx.send(t(lang, "xp_done", name=discord.utils.escape_markdown(member.display_name),
                         xp=fmt_int(rec["xp"]), level=rec["level"]), allowed_mentions=discord.AllowedMentions.none())

    @levelset.command(name="toggle")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_toggle(self, ctx: commands.Context, state: Optional[bool] = None):
        """Levelsystem ein- oder ausschalten (ohne Wert = umschalten)."""
        lang = await self._lang(ctx.guild)
        new = (not await self.config.guild(ctx.guild).enabled()) if state is None else bool(state)
        await self.config.guild(ctx.guild).enabled.set(new)
        await self._say(ctx, "toggle_set", state=t(lang, "on" if new else "off"))

    @levelset.command(name="xprange")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_xprange(self, ctx: commands.Context, minimum: int, maximum: int):
        """XP pro Nachricht (zufällig zwischen min und max, Standard 15–25)."""
        if not (1 <= minimum <= maximum <= MAX_XP_PER_MESSAGE):
            return await self._say(ctx, "range_bad", max=MAX_XP_PER_MESSAGE)
        await self.config.guild(ctx.guild).xp_min.set(minimum)
        await self.config.guild(ctx.guild).xp_max.set(maximum)
        await self._say(ctx, "range_set", min=minimum, max=maximum)

    @levelset.command(name="cooldown")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_cooldown(self, ctx: commands.Context, seconds: int):
        """Cooldown zwischen zwei XP-Nachrichten pro Mitglied (Standard 60 s)."""
        if not 0 <= seconds <= MAX_COOLDOWN:
            return await self._say(ctx, "cooldown_bad", max=MAX_COOLDOWN)
        await self.config.guild(ctx.guild).cooldown.set(seconds)
        await self._say(ctx, "cooldown_set", sec=seconds)

    @levelset.command(name="voice")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_voice(self, ctx: commands.Context, state: bool, xp_per_minute: Optional[int] = None):
        """Voice-XP an/aus, optional mit XP pro Minute."""
        lang = await self._lang(ctx.guild)
        gconf = self.config.guild(ctx.guild)
        if xp_per_minute is not None:
            if not 1 <= xp_per_minute <= MAX_VOICE_XP:
                return await self._say(ctx, "voice_bad", max=MAX_VOICE_XP)
            await gconf.voice_xp.set(xp_per_minute)
        await gconf.voice_enabled.set(bool(state))
        await self._say(ctx, "voice_set", state=t(lang, "on" if state else "off"), xp=await gconf.voice_xp())

    @levelset.command(name="excludechannel")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_excludechannel(self, ctx: commands.Context,
                                channel: Union[discord.TextChannel, discord.VoiceChannel]):
        """Kanal von XP ausschließen – erneut ausführen, um ihn wieder zuzulassen."""
        async with self.config.guild(ctx.guild).excluded_channels() as ids:
            if channel.id in ids:
                ids.remove(channel.id)
                key = "exclude_channel_off"
            else:
                ids.append(channel.id)
                key = "exclude_channel_on"
        await self._say(ctx, key, channel=channel.mention)

    @levelset.command(name="excluderole")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_excluderole(self, ctx: commands.Context, role: discord.Role):
        """Rolle von XP ausschließen – erneut ausführen, um sie wieder zuzulassen."""
        async with self.config.guild(ctx.guild).excluded_roles() as ids:
            if role.id in ids:
                ids.remove(role.id)
                key = "exclude_role_off"
            else:
                ids.append(role.id)
                key = "exclude_role_on"
        await self._say(ctx, key, role=role.mention)

    @levelset.command(name="multiplier")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_multiplier(self, ctx: commands.Context, role: discord.Role, factor: float):
        """XP-Multiplikator für eine Rolle (0.1–5; 1 = entfernen). Es gilt der höchste Faktor."""
        if factor != 1 and not MIN_MULT <= factor <= MAX_MULT:
            return await self._say(ctx, "mult_bad", min=MIN_MULT, max=MAX_MULT)
        async with self.config.guild(ctx.guild).multipliers() as mults:
            if factor == 1:
                mults.pop(str(role.id), None)
            else:
                mults[str(role.id)] = round(float(factor), 2)
        if factor == 1:
            return await self._say(ctx, "mult_removed", role=role.mention)
        await self._say(ctx, "mult_set", role=role.mention, factor=round(float(factor), 2))

    @levelset.command(name="reward")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_reward(self, ctx: commands.Context, level: int, role: Optional[discord.Role] = None):
        """Rolle als Belohnung für ein Level (ohne Rolle = Belohnung entfernen)."""
        if not 1 <= level <= MAX_LEVEL:
            return await self._say(ctx, "reward_level_bad", max=MAX_LEVEL)
        gconf = self.config.guild(ctx.guild)
        if role is None:
            async with gconf.rewards() as rewards:
                had = rewards.pop(str(level), None)
            return await self._say(ctx, "reward_removed" if had else "reward_none", level=level)
        if role.is_default() or role.managed:
            return await self._say(ctx, "reward_role_bad")
        if not self.bot_can_manage(ctx.guild, role):
            return await self._say(ctx, "reward_bot_hierarchy", role=role.mention)
        if not await self.user_can_grant(ctx.author, role):
            return await self._say(ctx, "reward_user_hierarchy", role=role.mention)
        async with gconf.rewards() as rewards:
            rewards[str(level)] = role.id
        await self._say(ctx, "reward_set", level=level, role=role.mention)

    @levelset.command(name="stack")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_stack(self, ctx: commands.Context, state: bool):
        """Belohnungen stapeln (an) oder nur die höchste erreichte Rolle behalten (aus)."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).stack_rewards.set(bool(state))
        await self._say(ctx, "stack_set", mode=t(lang, "stack_on" if state else "stack_off"))

    @levelset.command(name="syncrewards")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_syncrewards(self, ctx: commands.Context):
        """Belohnungsrollen aller Mitglieder mit ihrem Level abgleichen."""
        async with ctx.typing():
            added, removed = await self.sync_all(ctx.guild)
        await self._say(ctx, "sync_done", added=added, removed=removed)

    @levelset.command(name="announce")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_announce(self, ctx: commands.Context, mode: Literal["off", "same", "channel", "dm"],
                          channel: Optional[discord.TextChannel] = None):
        """Level-Up-Meldung: off, same (selber Kanal), channel (fester Kanal) oder dm."""
        lang = await self._lang(ctx.guild)
        gconf = self.config.guild(ctx.guild)
        if mode == "channel":
            if channel is None:
                return await self._say(ctx, "announce_needs_channel")
            await gconf.announce_channel.set(channel.id)
        await gconf.announce_mode.set(mode)
        label = t(lang, f"mode_{mode}") + (f" ({channel.mention})" if mode == "channel" else "")
        await self._say(ctx, "announce_set", mode=label)

    @levelset.command(name="message")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_message(self, ctx: commands.Context, *, text: str = ""):
        """Text der Level-Up-Meldung (Platzhalter {user} {name} {level} {server}); ohne Text = Standard."""
        text = text.strip()
        if len(text) > MAX_ANNOUNCE:
            return await self._say(ctx, "message_bad", max=MAX_ANNOUNCE)
        await self.config.guild(ctx.guild).announce_text.set(text)
        await self._say(ctx, "message_set" if text else "message_reset")

    @levelset.command(name="language")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_language(self, ctx: commands.Context, code: str):
        """Sprache der Meldungen und Antworten (de/en)."""
        code = code.lower().strip()
        if code not in LANGUAGES:
            return await self._say(ctx, "lang_unknown", code=code, langs=", ".join(LANGUAGES))
        await self.config.guild(ctx.guild).language.set(code)
        await self._say(ctx, "lang_set", language=LANGUAGES[code])

    @levelset.command(name="settings")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ls_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        conf = await self.config.guild(ctx.guild).all()
        lang = conf["language"]
        g = ctx.guild

        def onoff(v):
            return t(lang, "on" if v else "off")

        emb = discord.Embed(title=t(lang, "settings_title"), color=0x3DDC97)
        emb.add_field(name=t(lang, "settings_general"), value=f"{onoff(conf['enabled'])} · {LANGUAGES.get(lang, lang)}")
        emb.add_field(name=t(lang, "settings_xp"), value=f"{conf['xp_min']}–{conf['xp_max']}")
        emb.add_field(name=t(lang, "settings_cooldown"), value=f"{conf['cooldown']} s")
        emb.add_field(name=t(lang, "settings_voice"), value=f"{onoff(conf['voice_enabled'])} · {conf['voice_xp']} XP/min")
        ch = g.get_channel(int(conf["announce_channel"])) if conf["announce_channel"] else None
        mode = t(lang, f"mode_{conf['announce_mode']}") + (f" ({ch.mention})" if conf["announce_mode"] == "channel" and ch else "")
        emb.add_field(name=t(lang, "settings_announce"), value=mode)
        rewards = sorted(((int(lv), g.get_role(int(rid))) for lv, rid in conf["rewards"].items()), key=lambda x: x[0])
        rtxt = "\n".join(f"{lv}: {r.mention if r else '—'}" for lv, r in rewards) or t(lang, "none")
        emb.add_field(name=t(lang, "settings_rewards") + f" ({t(lang, 'stack_on' if conf['stack_rewards'] else 'stack_off')})",
                      value=rtxt[:1024], inline=False)
        ex = [g.get_channel(int(c)) for c in conf["excluded_channels"]] + [g.get_role(int(r)) for r in conf["excluded_roles"]]
        emb.add_field(name=t(lang, "settings_excluded"), value=(", ".join(x.mention for x in ex if x) or t(lang, "none"))[:1024],
                      inline=False)
        mults = [(g.get_role(int(r)), f) for r, f in conf["multipliers"].items()]
        emb.add_field(name=t(lang, "settings_mult"),
                      value=(", ".join(f"{r.mention} ×{f}" for r, f in mults if r) or t(lang, "none"))[:1024], inline=False)
        await ctx.send(embed=emb, allowed_mentions=discord.AllowedMentions.none())
