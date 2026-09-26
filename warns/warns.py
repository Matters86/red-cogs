"""Warns – Verwarnsystem mit Punkten, Verfall und automatischen Maßnahmen.

* ``[p]warn @user [punkte] <grund>`` (kick_members oder Mod-Rolle), ``[p]warnings [@user]``,
  ``[p]unwarn <id>``, ``[p]clearwarns @user`` (Admin), ``[p]warnset …`` (Einstellungen).
* Punkte je Verwarnung (Standard 1), Verfall nach N Tagen (0 = nie; gilt ab Erstellung).
* Automatische Maßnahmen ab X aktiven Punkten (Timeout/Kick/Bann, Standard aus) – nie gegen
  Bot-Owner, Server-Owner oder Mitglieder mit gleich hoher/höherer Rolle als Bot bzw. Moderator.
* DM an Verwarnte (Schalter, Text mit Platzhaltern), Log-Kanal mit Embed.
* IDs fortlaufend je Server, vergeben unter einem Server-Lock (atomar).
* Dashboard-Seite „Verwarnungen“ (``dashboard.py``).

Der Ordner heißt bewusst **nicht** ``warnings``: Red lädt Fremd-Cogs unter ihrem nackten
Paketnamen – ein Paket ``warnings`` würde das Python-Standardmodul ``warnings`` im ganzen
Bot-Prozess ersetzen. Außerdem kollidierte die Klasse ``Warnings`` mit Reds eingebautem Cog.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.warns")

MAX_POINTS = 100
MAX_REASON = 500
MAX_DM_TEXT = 1500
MAX_EXPIRY_DAYS = 3650
MAX_TIMEOUT_MIN = 40320      # 28 Tage (Discord-Grenze)
ACTIONS = ("timeout", "kick", "ban")
SEVERITY = {"timeout": 1, "kick": 2, "ban": 3}
_PH_RE = re.compile(r"\{(user|name|server|reason|points|total|id|moderator|expires)\}")


def fill_placeholders(text: str, values: dict) -> str:
    """Ersetzt nur die bekannten Platzhalter (kein ``str.format`` auf Nutzertext)."""
    return _PH_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), str(text or ""))


def is_active(entry: dict, now: float | None = None) -> bool:
    if entry.get("revoked"):
        return False
    exp = entry.get("expires")
    return exp is None or exp > (now if now is not None else time.time())


def status_of(entry: dict, now: float | None = None) -> str:
    if entry.get("revoked"):
        return "revoked"
    return "active" if is_active(entry, now) else "expired"


def split_points(text: str) -> tuple[Optional[int], str]:
    """``"2 Spam im Chat"`` -> ``(2, "Spam im Chat")``; ohne führende Zahl -> ``(None, text)``."""
    text = str(text or "").strip()
    m = re.match(r"^(\d{1,4})\s+(\S.*)$", text, re.S)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, text


def fmt_duration(minutes: int, lang: str) -> str:
    minutes = int(minutes)
    if minutes % 1440 == 0:
        return t(lang, "days", n=minutes // 1440)
    if minutes % 60 == 0:
        return t(lang, "hours", n=minutes // 60)
    return t(lang, "minutes", n=minutes)


def action_label(action: str, conf: dict, lang: str) -> str:
    if action == "timeout":
        return t(lang, "act_timeout", duration=fmt_duration(conf.get("timeout_minutes", 60), lang))
    return t(lang, f"act_{action}")


def why_text(lang: str, why: str) -> str:
    """Text zu einem ``why_…``-Key (``why_bot_perms:<perm_key>`` nennt das fehlende Recht)."""
    if why.startswith("why_bot_perms:"):
        return t(lang, "why_bot_perms", perm=t(lang, why.split(":", 1)[1]))
    return t(lang, why)


class Actor:
    """Moderator ohne Member-Objekt (z. B. Bot-Owner im Dashboard, der nicht auf dem Server ist)."""

    def __init__(self, uid: int, name: str, *, owner: bool = False):
        self.id = int(uid)
        self.display_name = self.name = name
        self.mention = f"<@{uid}>"
        self.is_bot_owner = owner


class Warns(commands.Cog):
    """Verwarnsystem mit Punkten, Verfall, automatischen Maßnahmen, DM und Log."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=551902837146, force_registration=True)
        self.config.register_guild(
            language="de",
            next_id=1,               # nächste Verwarnungs-ID (fortlaufend je Server)
            default_points=1,
            expiry_days=0,           # 0 = Verwarnungen verfallen nie
            dm_enabled=True,
            dm_text="",              # leer = Standardtext
            log_channel=None,
            mod_roles=[],
            timeout_at=0,            # 0 = aus; sonst ab X aktiven Punkten
            timeout_minutes=60,
            kick_at=0,
            ban_at=0,
        )
        # Pro Mitglied: Liste von Verwarnungen (dicts, siehe add_warning).
        self.config.register_member(warnings=[])
        self._locks: dict[int, asyncio.Lock] = {}

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)

    async def cog_unload(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)
        self._locks.clear()

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        page = dict(owner=self, slug="warnings", name="Verwarnungen", icon="bi-exclamation-octagon",
                    handler=self.dashboard_page)
        try:
            # Tagesgeschäft für die Stufe „Bedienen“: Mitglied verwarnen, Verwarnung aufheben.
            webcore.register_page(**page, operate_forms={"warn", "revoke"})
        except TypeError:  # ältere WebCore-Versionen ohne Stufe „Bedienen“
            webcore.register_page(**page)

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Löscht Verwarnungen des Nutzers (als Verwarnter) und anonymisiert ihn als Moderator."""
        user_id = int(user_id)
        all_members = await self.config.all_members()
        for guild_id, members in all_members.items():
            async with self.lock(int(guild_id)):
                if user_id in members or str(user_id) in members:
                    await self.config.member_from_ids(int(guild_id), user_id).clear()
                for member_id in list(members):
                    if int(member_id) == user_id:
                        continue
                    async with self.config.member_from_ids(int(guild_id), int(member_id)).warnings() as entries:
                        for e in entries:
                            if e.get("mod_id") == user_id:
                                e["mod_id"] = 0
                                e["mod_name"] = t(DEFAULT_LANGUAGE, "deleted_user")
                            if e.get("revoked_by") == user_id:
                                e["revoked_by"] = 0
                                e["revoked_by_name"] = t(DEFAULT_LANGUAGE, "deleted_user")

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    def lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(int(guild_id), asyncio.Lock())

    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language() if guild else DEFAULT_LANGUAGE

    async def _say(self, ctx, key, **kwargs):
        await ctx.send(t(await self._lang(ctx.guild), key, **kwargs),
                       allowed_mentions=discord.AllowedMentions.none())

    def is_bot_owner(self, user) -> bool:
        if getattr(user, "is_bot_owner", False):
            return True
        return getattr(user, "id", None) in (self.bot.owner_ids or set())

    @staticmethod
    def is_guild_owner(guild, user) -> bool:
        return getattr(user, "id", None) is not None and user.id == getattr(guild, "owner_id", None)

    async def is_mod(self, member) -> bool:
        """Darf verwarnen: Bot-Owner, Server-Owner, Admin, „Mitglieder kicken“, Mod-Rolle (eigene oder Reds)."""
        if member is None:
            return False
        if self.is_bot_owner(member) or self.is_guild_owner(member.guild, member):
            return True
        perms = getattr(member, "guild_permissions", None)
        if perms is not None and (perms.administrator or perms.kick_members):
            return True
        mod_roles = {int(r) for r in await self.config.guild(member.guild).mod_roles()}
        if any(r.id in mod_roles for r in getattr(member, "roles", [])):
            return True
        checker = getattr(self.bot, "is_mod", None)
        if checker is not None:
            try:
                return bool(await checker(member))
            except Exception:  # noqa: BLE001
                return False
        return False

    def _outranks(self, guild, moderator, target) -> bool:
        """Steht ``moderator`` über ``target``? Bot-/Server-Owner immer."""
        if self.is_bot_owner(moderator) or self.is_guild_owner(guild, moderator):
            return True
        mod_top = getattr(moderator, "top_role", None)
        tgt_top = getattr(target, "top_role", None)
        if mod_top is None or tgt_top is None:
            return False
        return tgt_top < mod_top

    def check_target(self, guild, moderator, target) -> Optional[str]:
        """Dieselben Prüfungen für Befehl und Dashboard. ``None`` = erlaubt, sonst ein String-Key."""
        if getattr(target, "bot", False):
            return "err_bot"
        if target.id == moderator.id:
            return "err_self"
        if self.is_bot_owner(target):
            return "err_bot_owner"
        if self.is_guild_owner(guild, target):
            return "err_guild_owner"
        if not self._outranks(guild, moderator, target):
            return "err_hierarchy"
        return None

    async def member_entries(self, guild, user_id: int) -> list[dict]:
        return list(await self.config.member_from_ids(guild.id, int(user_id)).warnings())

    async def active_points(self, guild, user_id: int) -> int:
        now = time.time()
        return sum(int(e.get("points", 1)) for e in await self.member_entries(guild, user_id) if is_active(e, now))

    async def all_entries(self, guild) -> list[tuple[int, dict]]:
        """Alle Verwarnungen des Servers als ``[(user_id, eintrag)]``, neueste zuerst."""
        data = await self.config.all_members(guild)
        out = []
        for uid, mdata in data.items():
            for e in mdata.get("warnings", []):
                out.append((int(uid), e))
        out.sort(key=lambda x: (x[1].get("ts", 0), x[1].get("id", 0)), reverse=True)
        return out

    async def find_entry(self, guild, warn_id: int) -> tuple[Optional[int], Optional[dict]]:
        for uid, e in await self.all_entries(guild):
            if int(e.get("id", -1)) == int(warn_id):
                return uid, e
        return None, None

    # ----------------------------------------------------------------- #
    #  Kern: Verwarnen / Aufheben / Löschen
    # ----------------------------------------------------------------- #
    async def add_warning(self, guild, target, moderator, reason: str, points: int | None = None,
                          *, source: str = "command") -> dict:
        """Legt eine Verwarnung an und führt DM, automatische Maßnahme und Log aus.

        Prüfungen (``check_target``) macht der Aufrufer. Rückgabe: dict mit ``id``, ``total``,
        ``action`` (Label oder None), ``action_ok``, ``action_why``, ``dm_ok``.
        """
        gconf = self.config.guild(guild)
        conf = await gconf.all()
        lang = conf["language"]
        points = int(points if points is not None else conf["default_points"])
        points = max(1, min(MAX_POINTS, points))
        reason = str(reason or "").strip()[:MAX_REASON]
        now = time.time()
        async with self.lock(guild.id):
            wid = int(await gconf.next_id())
            await gconf.next_id.set(wid + 1)
            entry = {
                "id": wid,
                "reason": reason,
                "points": points,
                "mod_id": int(moderator.id),
                "mod_name": str(getattr(moderator, "display_name", None) or getattr(moderator, "name", "?"))[:100],
                "user_name": str(getattr(target, "display_name", None) or getattr(target, "name", "?"))[:100],
                "ts": int(now),
                "expires": int(now + conf["expiry_days"] * 86400) if conf["expiry_days"] else None,
                "revoked": False,
                "source": source,
            }
            async with self.config.member(target).warnings() as entries:
                before = sum(int(e.get("points", 1)) for e in entries if is_active(e, now))
                entries.append(entry)
            total = before + points

        action = self.crossed_action(conf, before, total)
        result = {"id": wid, "total": total, "points": points, "action": None, "action_ok": False,
                  "action_why": None, "dm_ok": None, "entry": entry}
        why = None
        if action:
            result["action"] = action_label(action, conf, lang)
            why = self.action_block_reason(guild, target, moderator, action)
        # DM zuerst – nach Kick/Bann erreicht sie das Mitglied nicht mehr.
        if conf["dm_enabled"]:
            result["dm_ok"] = await self._send_dm(guild, target, moderator, entry, total, conf,
                                                  result["action"] if action and why is None else None)
        if action:
            if why is None:
                why = await self._execute(guild, target, action, conf, reason=f"Verwarnung #{wid}: {reason}"[:400])
            result["action_ok"] = why is None
            result["action_why"] = why_text(lang, why) if why else None
            await self._store_action(guild, target.id, wid, action, result["action_ok"], result["action_why"])
            (log.info if result["action_ok"] else log.warning)(
                "Warns (%s): Maßnahme %s für %s: %s", guild.id, action, target.id,
                "ok" if result["action_ok"] else result["action_why"])
        await self._log_warn(guild, target, moderator, entry, total, conf, result)
        return result

    @staticmethod
    def crossed_action(conf: dict, before: int, after: int) -> Optional[str]:
        """Schwerste Maßnahme, deren Schwelle durch diese Verwarnung erreicht wurde (before < X ≤ after)."""
        best = None
        for action in ACTIONS:
            th = int(conf.get(f"{action}_at", 0) or 0)
            if th > 0 and before < th <= after:
                if best is None or SEVERITY[action] > SEVERITY[best]:
                    best = action
        return best

    def action_block_reason(self, guild, target, moderator, action: str) -> Optional[str]:
        """``None`` wenn die Maßnahme erlaubt ist, sonst ein String-Key (``why_…``)."""
        if self.is_bot_owner(target):
            return "why_bot_owner"
        if self.is_guild_owner(guild, target):
            return "why_guild_owner"
        me = guild.me
        tgt_top = getattr(target, "top_role", None)
        if me is None or tgt_top is None or tgt_top >= me.top_role:
            return "why_bot_hierarchy"
        if not self._outranks(guild, moderator, target):
            return "why_mod_hierarchy"
        perms = me.guild_permissions
        need = {"timeout": ("moderate_members", "perm_moderate"), "kick": ("kick_members", "perm_kick"),
                "ban": ("ban_members", "perm_ban")}[action]
        if not (getattr(perms, need[0], False) or getattr(perms, "administrator", False)):
            return f"why_bot_perms:{need[1]}"
        if action == "timeout" and getattr(getattr(target, "guild_permissions", None), "administrator", False):
            return "why_admin_timeout"
        return None

    async def _execute(self, guild, target, action: str, conf: dict, *, reason: str) -> Optional[str]:
        try:
            if action == "timeout":
                minutes = max(1, min(MAX_TIMEOUT_MIN, int(conf.get("timeout_minutes", 60))))
                await target.timeout(discord.utils.utcnow() + timedelta(minutes=minutes), reason=reason)
            elif action == "kick":
                await guild.kick(target, reason=reason)
            elif action == "ban":
                await guild.ban(target, reason=reason, delete_message_seconds=0)
        except discord.Forbidden:
            return "why_http"
        except discord.HTTPException:
            return "why_http"
        except Exception:  # noqa: BLE001
            log.exception("Warns (%s): Maßnahme %s fehlgeschlagen", guild.id, action)
            return "why_http"
        return None

    async def _store_action(self, guild, user_id, wid, action, ok, why):
        async with self.lock(guild.id):
            async with self.config.member_from_ids(guild.id, int(user_id)).warnings() as entries:
                for e in entries:
                    if e.get("id") == wid:
                        e["action"] = action
                        e["action_ok"] = bool(ok)
                        if why:
                            e["action_why"] = str(why)[:200]
                        break

    async def revoke(self, guild, warn_id: int, moderator) -> tuple[Optional[str], Optional[int], Optional[dict], int]:
        """Hebt eine Verwarnung auf. Rückgabe ``(fehler_key, user_id, eintrag, aktive_punkte)``."""
        async with self.lock(guild.id):
            uid, entry = await self.find_entry(guild, warn_id)
            if entry is None:
                return "err_not_found", None, None, 0
            if entry.get("revoked"):
                return "err_already_revoked", uid, entry, 0
            if uid == moderator.id and not (self.is_bot_owner(moderator) or self.is_guild_owner(guild, moderator)):
                return "err_own_warning", uid, entry, 0
            async with self.config.member_from_ids(guild.id, uid).warnings() as entries:
                for e in entries:
                    if e.get("id") == int(warn_id):
                        e["revoked"] = True
                        e["revoked_by"] = int(moderator.id)
                        e["revoked_by_name"] = str(getattr(moderator, "display_name", None)
                                                   or getattr(moderator, "name", "?"))[:100]
                        e["revoked_ts"] = int(time.time())
                        entry = dict(e)
                        break
        total = await self.active_points(guild, uid)
        await self._log_simple(guild, "log_revoke", uid, moderator, entry, total)
        return None, uid, entry, total

    async def clear(self, guild, user_id: int, moderator) -> int:
        async with self.lock(guild.id):
            mconf = self.config.member_from_ids(guild.id, int(user_id))
            n = len(await mconf.warnings())
            if n:
                await mconf.clear()
        if n:
            await self._log_simple(guild, "log_clear", user_id, moderator, None, 0, count=n)
        return n

    # ----------------------------------------------------------------- #
    #  DM & Log
    # ----------------------------------------------------------------- #
    def _fmt_expires(self, entry, lang) -> str:
        return f"<t:{entry['expires']}:R>" if entry.get("expires") else t(lang, "never")

    async def _send_dm(self, guild, target, moderator, entry, total, conf, action_label_) -> bool:
        lang = conf["language"]
        values = {
            "user": getattr(target, "mention", ""), "name": discord.utils.escape_markdown(entry["user_name"]),
            "server": discord.utils.escape_markdown(guild.name), "reason": entry["reason"] or "—",
            "points": entry["points"], "total": total, "id": entry["id"],
            "moderator": discord.utils.escape_markdown(entry["mod_name"]),
            "expires": self._fmt_expires(entry, lang),
        }
        text = fill_placeholders((conf.get("dm_text") or "").strip() or t(lang, "dm_default"), values)
        if action_label_:
            text += "\n" + t(lang, "dm_action_line", action=action_label_)
        try:
            await target.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())
            return True
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return False

    async def _log_channel(self, guild):
        cid = await self.config.guild(guild).log_channel()
        ch = guild.get_channel(int(cid)) if cid else None
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            return None
        me = guild.me
        if me is not None:
            perms = ch.permissions_for(me)
            if not (perms.send_messages and perms.embed_links):
                return None
        return ch

    async def _log_send(self, ch, emb):
        try:
            await ch.send(embed=emb, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("Warns: Log-Nachricht abgelehnt: %s", exc)

    async def _log_warn(self, guild, target, moderator, entry, total, conf, result):
        ch = await self._log_channel(guild)
        if ch is None:
            return
        lang = conf["language"]
        emb = discord.Embed(title=t(lang, "log_warn", id=entry["id"]), color=0xF5B94A,
                            timestamp=datetime.fromtimestamp(entry["ts"], timezone.utc))
        emb.add_field(name=t(lang, "log_member"), value=f"<@{target.id}> ({target.id})", inline=True)
        emb.add_field(name=t(lang, "log_moderator"), value=f"<@{moderator.id}>" if moderator.id else entry["mod_name"],
                      inline=True)
        emb.add_field(name=t(lang, "log_points"), value=f"+{entry['points']} → **{total}**", inline=True)
        emb.add_field(name=t(lang, "log_reason"), value=(entry["reason"] or "—")[:1024], inline=False)
        emb.add_field(name=t(lang, "log_expires"), value=self._fmt_expires(entry, lang), inline=True)
        emb.add_field(name=t(lang, "log_source"), value=t(lang, f"src_{entry.get('source', 'command')}"), inline=True)
        if result.get("action"):
            state = t(lang, "log_done") if result["action_ok"] else f"{t(lang, 'log_failed')}: {result['action_why']}"
            emb.add_field(name=t(lang, "log_action"), value=f"{result['action']} – {state}"[:1024], inline=False)
            if result["action_ok"]:
                emb.color = 0xF0506E
        await self._log_send(ch, emb)

    async def _log_simple(self, guild, key, user_id, moderator, entry, total, *, count=None):
        ch = await self._log_channel(guild)
        if ch is None:
            return
        lang = await self._lang(guild)
        emb = discord.Embed(title=t(lang, key, id=(entry or {}).get("id", "")), color=0x6CB6FF,
                            timestamp=discord.utils.utcnow())
        emb.add_field(name=t(lang, "log_member"), value=f"<@{user_id}> ({user_id})", inline=True)
        emb.add_field(name=t(lang, "log_moderator"), value=f"<@{moderator.id}>", inline=True)
        if count is not None:
            emb.add_field(name=t(lang, "log_count"), value=str(count), inline=True)
        else:
            emb.add_field(name=t(lang, "log_total"), value=str(total), inline=True)
            emb.add_field(name=t(lang, "log_reason"), value=(entry.get("reason") or "—")[:1024], inline=False)
        await self._log_send(ch, emb)

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    @commands.hybrid_command(name="warn")
    @commands.guild_only()
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        """Verwarnt ein Mitglied. Punkte optional als erste Zahl im Grund, z. B. `warn @user 2 Spam`."""
        guild = ctx.guild
        points, reason = split_points(reason)
        if not await self.is_mod(ctx.author):
            return await self._say(ctx, "err_not_mod")
        err = self.check_target(guild, ctx.author, member)
        if err:
            return await self._say(ctx, err, user=member.display_name)
        if points is not None and not 1 <= points <= MAX_POINTS:
            return await self._say(ctx, "err_points", max=MAX_POINTS)
        reason = (reason or "").strip()
        if not reason or len(reason) > MAX_REASON:
            return await self._say(ctx, "err_reason", max=MAX_REASON)
        lang = await self._lang(guild)
        res = await self.add_warning(guild, member, ctx.author, reason, points, source="command")
        lines = [t(lang, "warn_ok", id=res["id"], user=member.mention, reason=reason, points=res["points"],
                   total=res["total"])]
        if res["action"]:
            lines.append(t(lang, "warn_action_done", action=res["action"]) if res["action_ok"]
                         else t(lang, "warn_action_failed", action=res["action"], why=res["action_why"]))
        if res["dm_ok"] is False:
            lines.append(t(lang, "warn_dm_failed"))
        await ctx.send("\n".join(lines)[:2000], allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(name="warnings")
    @commands.guild_only()
    async def warnings_cmd(self, ctx: commands.Context, user: Optional[discord.User] = None):
        """Zeigt Verwarnungen (ohne Angabe: deine eigenen; andere nur für Moderatoren)."""
        guild = ctx.guild
        user = user or ctx.author
        if user.id != ctx.author.id and not await self.is_mod(ctx.author):
            return await self._say(ctx, "err_view_other")
        lang = await self._lang(guild)
        entries = sorted(await self.member_entries(guild, user.id), key=lambda e: e.get("ts", 0), reverse=True)
        name = getattr(user, "display_name", None) or user.name
        if not entries:
            return await self._say(ctx, "hist_empty", user=name)
        now = time.time()
        active = [e for e in entries if is_active(e, now)]
        emb = discord.Embed(title=t(lang, "hist_title", user=name)[:256], color=0xF5B94A,
                            description=t(lang, "hist_summary", total=sum(int(e.get("points", 1)) for e in active),
                                          active=len(active), count=len(entries)))
        shown = 0
        for e in entries[:10]:
            st = status_of(e, now)
            head = f"#{e['id']} · {t(lang, 'status_' + st)}"
            body = t(lang, "hist_line", id=e["id"], points=e.get("points", 1), when=f"<t:{e.get('ts', 0)}:d>",
                     mod=e.get("mod_name", "?"), reason=e.get("reason") or "—")
            emb.add_field(name=head[:256], value=body[:1024], inline=False)
            shown += 1
        if len(entries) > shown:
            emb.set_footer(text=t(lang, "hist_more", n=len(entries) - shown))
        await ctx.send(embed=emb, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(name="unwarn")
    @commands.guild_only()
    async def unwarn(self, ctx: commands.Context, warn_id: int):
        """Hebt eine Verwarnung über ihre ID auf."""
        if not await self.is_mod(ctx.author):
            return await self._say(ctx, "err_not_mod")
        err, uid, entry, total = await self.revoke(ctx.guild, warn_id, ctx.author)
        if err:
            return await self._say(ctx, err, id=warn_id)
        await self._say(ctx, "unwarn_ok", id=warn_id, user=f"<@{uid}>", total=total)

    @commands.hybrid_command(name="clearwarns")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def clearwarns(self, ctx: commands.Context, user: discord.User):
        """Löscht alle Verwarnungen eines Mitglieds endgültig (Admin)."""
        n = await self.clear(ctx.guild, user.id, ctx.author)
        name = getattr(user, "display_name", None) or user.name
        await self._say(ctx, "clear_ok" if n else "clear_none", n=n, user=name)

    # ---- Einstellungen ------------------------------------------------ #
    @commands.hybrid_group(name="warnset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def warnset(self, ctx: commands.Context):
        """Verwarnsystem einstellen."""

    @warnset.command(name="logchannel")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_log(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Log-Kanal setzen (ohne Kanal = entfernen)."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id if channel else None)
        if channel:
            await self._say(ctx, "set_log", channel=channel.mention)
        else:
            await self._say(ctx, "set_log_cleared")

    @warnset.command(name="dm")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_dm(self, ctx: commands.Context, state: bool):
        """DM an Verwarnte an/aus."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).dm_enabled.set(bool(state))
        await self._say(ctx, "set_dm", state=t(lang, "on" if state else "off"))

    @warnset.command(name="dmtext")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_dmtext(self, ctx: commands.Context, *, text: str = ""):
        """DM-Text (Platzhalter: {user} {name} {server} {reason} {points} {total} {id} {moderator} {expires})."""
        text = text.strip()
        if len(text) > MAX_DM_TEXT:
            return await self._say(ctx, "set_dmtext_long", max=MAX_DM_TEXT)
        await self.config.guild(ctx.guild).dm_text.set(text)
        await self._say(ctx, "set_dmtext" if text else "set_dmtext_reset")

    @warnset.command(name="modrole")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_modrole(self, ctx: commands.Context, role: discord.Role):
        """Mod-Rolle hinzufügen bzw. wieder entfernen (Umschalter)."""
        async with self.config.guild(ctx.guild).mod_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
                key = "set_modrole_removed"
            else:
                roles.append(role.id)
                key = "set_modrole_added"
        await self._say(ctx, key, role=role.name)

    @warnset.command(name="expiry")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_expiry(self, ctx: commands.Context, days: int):
        """Verfall neuer Verwarnungen in Tagen (0 = nie)."""
        if not 0 <= days <= MAX_EXPIRY_DAYS:
            return await self._say(ctx, "set_expiry_bad", max=MAX_EXPIRY_DAYS)
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).expiry_days.set(days)
        await self._say(ctx, "set_expiry", days=t(lang, "days", n=days) if days else t(lang, "never"))

    @warnset.command(name="points")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_points(self, ctx: commands.Context, points: int):
        """Standard-Punkte je Verwarnung (1–100)."""
        if not 1 <= points <= MAX_POINTS:
            return await self._say(ctx, "err_points", max=MAX_POINTS)
        await self.config.guild(ctx.guild).default_points.set(points)
        await self._say(ctx, "set_points", points=points)

    @warnset.command(name="action")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_action(self, ctx: commands.Context, action: str, points: int, minutes: Optional[int] = None):
        """Automatische Maßnahme: `timeout|kick|ban <punkte> [minuten]` – 0 Punkte = aus."""
        action = action.lower().strip()
        if action not in ACTIONS or not 0 <= points <= MAX_POINTS or (
                minutes is not None and not 1 <= minutes <= MAX_TIMEOUT_MIN):
            return await self._say(ctx, "set_action_bad", max=MAX_POINTS)
        gconf = self.config.guild(ctx.guild)
        await gconf.set_raw(f"{action}_at", value=points)
        if action == "timeout" and minutes is not None:
            await gconf.timeout_minutes.set(minutes)
        lang = await self._lang(ctx.guild)
        label = action_label(action, await gconf.all(), lang)
        if points:
            await self._say(ctx, "set_action", points=points, action=label)
        else:
            await self._say(ctx, "set_action_off", action=label)

    @warnset.command(name="language")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_language(self, ctx: commands.Context, code: str):
        """Sprache (de/en)."""
        code = code.lower().strip()
        if code not in LANGUAGES:
            return await self._say(ctx, "set_lang_unknown", code=code, langs=", ".join(LANGUAGES))
        await self.config.guild(ctx.guild).language.set(code)
        await self._say(ctx, "set_lang", language=LANGUAGES[code])

    @warnset.command(name="settings")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ws_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        conf = await self.config.guild(ctx.guild).all()
        lang = conf["language"]
        ch = ctx.guild.get_channel(int(conf["log_channel"])) if conf["log_channel"] else None
        roles = [ctx.guild.get_role(int(r)) for r in conf["mod_roles"]]
        acts = []
        for a in ACTIONS:
            if conf[f"{a}_at"]:
                acts.append(f"{action_label(a, conf, lang)}: ≥ {conf[f'{a}_at']}")
        emb = discord.Embed(title=t(lang, "settings_title"), color=0xF5B94A)
        emb.add_field(name=t(lang, "settings_log"), value=ch.mention if ch else t(lang, "none"))
        emb.add_field(name=t(lang, "settings_dm"), value=t(lang, "on" if conf["dm_enabled"] else "off"))
        emb.add_field(name=t(lang, "settings_expiry"),
                      value=t(lang, "days", n=conf["expiry_days"]) if conf["expiry_days"] else t(lang, "never"))
        emb.add_field(name=t(lang, "settings_points"), value=str(conf["default_points"]))
        emb.add_field(name=t(lang, "settings_lang"), value=LANGUAGES.get(lang, lang))
        emb.add_field(name=t(lang, "settings_modroles"),
                      value=(", ".join(r.mention for r in roles if r) or t(lang, "none"))[:1024])
        emb.add_field(name=t(lang, "settings_actions"), value=("\n".join(acts) or t(lang, "none"))[:1024], inline=False)
        await ctx.send(embed=emb, allowed_mentions=discord.AllowedMentions.none())
