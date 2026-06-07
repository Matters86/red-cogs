"""Guard – Spamschutz, Honeypot und Raid-Notmodus für Red-DiscordBot.

Zwei pro Server unabhängig schaltbare Module:

* **Honeypot** – ein Köder-Kanal, in dem reguläre Mitglieder nie schreiben.
  Wer dort postet, wird automatisch entfernt (Aktion einstellbar).
* **Spamschutz** – mehrere Heuristiken (Rate, Wiederholungen, Erwähnungen,
  Einladungs-/Linkfilter, Anhang-/Emoji-/Zeilen-Walls, sehr neue Konten) füttern
  ein Punktesystem; Schwellen lösen eine Eskalationsleiter aus
  (verwarnen -> Timeout -> Kick -> Bann). Wiederholt sich nichts, verfallen die
  Punkte nach einer einstellbaren Zeit.

Dazu ein **Raid-Notmodus**: zu viele Beitritte in kurzer Zeit (oder ein Befehl)
versetzen den Server in einen Lockdown (Slowmode, optional Einladungen
pausieren, neue Beitritte automatisch behandeln). Der Notmodus übersteht
Bot-Neustarts und wird nach einer Frist automatisch beendet.

Aktionen werden – ohne DM an Ausgelöste – in einen Log-Kanal geschrieben,
optional zusätzlich in Reds ``modlog`` gespiegelt, und persistent als
Verlauf fürs Dashboard gespeichert. Ohne externe pip-Abhängigkeiten.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord.ext import tasks
from redbot.core import Config, commands, modlog
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.guard")

# Discord-Einladungslinks und allgemeine URLs / Custom-Emojis.
INVITE_RE = re.compile(r"(?:discord(?:app)?\.com/invite|discord\.gg|discord\.me)/\S+", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")

ACTIONS = ("ban", "softban", "kick", "timeout")
HISTORY_MAX = 50

# Eskalationsstufen nach Schwere (für den Vergleich „schon gehandelt?\").
STAGE_RANK = {"none": 0, "warn": 1, "timeout": 2, "kick": 3, "ban": 4}

# modlog-Falltypen, die dieser Cog (best effort) registriert.
CASETYPES = [
    {"name": "guard_honeypot", "default_setting": True, "image": "\N{HONEY POT}",
     "case_str": "Guard – Honeypot"},
    {"name": "guard_spam", "default_setting": True, "image": "\N{NO ENTRY SIGN}",
     "case_str": "Guard – Spam"},
    {"name": "guard_raid", "default_setting": True, "image": "\N{LOCK}",
     "case_str": "Guard – Raid/Notmodus"},
]


class Guard(commands.Cog):
    """Spamschutz, Honeypot und Raid-Notmodus – mehrsprachig und per Dashboard steuerbar."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=384207516930, force_registration=True)
        self.config.register_guild(
            language="de",
            # Ausnahmen / allgemeine Optionen
            whitelist_roles=[],
            whitelist_users=[],
            whitelist_channels=[],     # nur Spamschutz – Honeypot bleibt aktiv
            ignore_bots=True,
            use_modlog=True,
            log_channel=None,
            # Honeypot
            hp_enabled=False,
            hp_channel=None,
            hp_action="softban",       # ban | softban | kick | timeout
            hp_delete_seconds=86400,   # Nachrichten-Löschfenster bei ban/softban (0..604800)
            hp_timeout_minutes=60,
            # Spamschutz – Schalter & Schwellen
            spam_enabled=False,
            s_rate=True, s_rate_count=6, s_rate_seconds=5,
            s_repeat=True, s_repeat_count=4, s_repeat_seconds=20, s_repeat_crosschannel=True,
            s_mentions=True, s_mentions_max=5,
            s_invites=True,
            s_links=False,
            s_walls=True, s_walls_attachments=6, s_walls_emojis=12, s_walls_newlines=12,
            s_newaccount=True, s_newaccount_hours=24,
            # Eskalation (Punkte)
            pts_rate=3, pts_repeat=3, pts_mentions=4, pts_invite=5, pts_link=2,
            pts_wall=2, pts_newaccount=2,
            decay_seconds=60,
            warn_at=3, timeout_at=6, kick_at=9, ban_at=12,
            spam_timeout_minutes=10,
            delete_violations=True,
            # Raid / Notmodus
            raid_enabled=True, raid_joins=8, raid_seconds=20,
            lockdown_slowmode=10,
            lockdown_pause_invites=True,
            lockdown_action_joins="none",   # none | kick | timeout
            lockdown_auto_minutes=10,        # 0 = nur manuell beenden
            lockdown_until=0,                # 0 = aus, -1 = aktiv (manuell), >0 = Ende-Zeitstempel
            lockdown_prev={},                # channel_id -> ursprünglicher Slowmode
            lockdown_invites_paused=False,
            # Texte / Verlauf / Statistik
            messages={},
            history=[],
            stats_total=0,
        )

        # Laufzeitzustand (nur Speicher).
        self._msgtimes: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=60))
        self._lastmsgs: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=20))
        self._points: dict[tuple, list] = defaultdict(list)   # (gid,uid) -> [(ts, pts), ...]
        self._acted: dict[tuple, int] = {}                    # (gid,uid) -> zuletzt ausgeführter Rang
        self._joins: dict[int, deque] = defaultdict(lambda: deque(maxlen=200))

    # ----------------------------------------------------------------- #
    #  Lifecycle / Dashboard
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        try:
            await modlog.register_casetypes(CASETYPES)
        except Exception:  # noqa: BLE001 – Falltypen evtl. schon vorhanden
            pass
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._lockdown_tick.start()

    async def cog_unload(self):
        self._lockdown_tick.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="guard",
            name="Guard",
            icon="bi-shield-shaded",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Hintergrund: Notmodus automatisch beenden
    # ----------------------------------------------------------------- #
    @tasks.loop(seconds=20)
    async def _lockdown_tick(self):
        now = int(time.time())
        for guild in list(self.bot.guilds):
            try:
                until = await self.config.guild(guild).lockdown_until()
            except Exception:  # noqa: BLE001
                continue
            if until and until > 0 and now >= until:
                await self._end_lockdown(guild)

    @_lockdown_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_red_ready()

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    async def _say(self, ctx, key, **kwargs):
        lang = await self._lang(ctx.guild) if ctx.guild else DEFAULT_LANGUAGE
        await ctx.send(t(lang, key, **kwargs))

    async def _text(self, guild, key, **kwargs) -> str:
        lang = await self._lang(guild)
        overrides = await self.config.guild(guild).messages()
        if key in overrides and overrides[key]:
            template = overrides[key]
            try:
                return template.format(**kwargs) if kwargs else template
            except (KeyError, IndexError, ValueError):
                return template
        return t(lang, key, **kwargs)

    async def _is_exempt(self, member, *, channel=None, honeypot=False) -> bool:
        """True, wenn das Mitglied von automatischen Aktionen ausgenommen ist."""
        if member is None or not isinstance(member, discord.Member):
            return True
        if self.bot.user is not None and member.id == self.bot.user.id:
            return True

        conf = await self.config.guild(member.guild).all()
        if member.bot and conf.get("ignore_bots", True):
            return True
        # Owner und Server-Verwalter nie automatisch bestrafen.
        try:
            if await self.bot.is_owner(member):
                return True
        except Exception:  # noqa: BLE001
            pass
        perms = getattr(member, "guild_permissions", None)
        if perms and (perms.administrator or perms.manage_guild):
            return True
        # Reds eingebaute Immunität ([p]immune) respektieren.
        try:
            if await self.bot.is_automod_immune(member):
                return True
        except Exception:  # noqa: BLE001
            pass
        if member.id in {int(u) for u in conf.get("whitelist_users", [])}:
            return True
        wl_roles = {int(r) for r in conf.get("whitelist_roles", [])}
        if any(r.id in wl_roles for r in getattr(member, "roles", [])):
            return True
        # Kanal-Whitelist gilt nur für den Spamschutz, nicht für den Honeypot.
        if not honeypot and channel is not None:
            if channel.id in {int(c) for c in conf.get("whitelist_channels", [])}:
                return True
        return False

    # ---- Discord-Aktionen (alle abgesichert) ------------------------- #
    async def _do_ban(self, guild, user, reason, delete_seconds) -> bool:
        secs = max(0, min(int(delete_seconds), 604800))
        try:
            await guild.ban(user, reason=reason, delete_message_seconds=secs)
            return True
        except TypeError:
            try:
                await guild.ban(user, reason=reason, delete_message_days=max(0, min(secs // 86400, 7)))
                return True
            except Exception:  # noqa: BLE001
                return False
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _do_softban(self, guild, user, reason, delete_seconds) -> bool:
        if not await self._do_ban(guild, user, reason, delete_seconds):
            return False
        try:
            await guild.unban(user, reason=reason)
        except Exception:  # noqa: BLE001
            pass
        return True

    async def _do_kick(self, guild, member, reason) -> bool:
        try:
            await guild.kick(member, reason=reason)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _do_timeout(self, member, minutes, reason) -> bool:
        try:
            until = discord.utils.utcnow() + timedelta(minutes=max(1, int(minutes)))
            await member.timeout(until, reason=reason)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _execute(self, guild, member, action, reason, *, delete_seconds, timeout_minutes) -> str:
        """Führt ``action`` aus und gibt die tatsächlich erfolgte Aktion zurück."""
        ok = False
        if action == "ban":
            ok = await self._do_ban(guild, member, reason, delete_seconds)
        elif action == "softban":
            ok = await self._do_softban(guild, member, reason, delete_seconds)
        elif action == "kick":
            ok = await self._do_kick(guild, member, reason)
        elif action == "timeout":
            ok = await self._do_timeout(member, timeout_minutes, reason)
        elif action == "warn":
            ok = True
        return action if ok else "none"

    @staticmethod
    async def _delete_message(message):
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass

    # ---- Logging / Verlauf ------------------------------------------- #
    async def _log_action(self, guild, *, kind, member, action, rules, channel=None, points=None):
        lang = await self._lang(guild)
        conf = await self.config.guild(guild).all()
        title_key = {
            "honeypot": "log_title_honeypot",
            "spam": "log_title_spam",
            "raid": "log_title_raid",
            "lockdown_join": "log_title_spam",
            "lockdown_end": "log_title_lockdown_end",
        }.get(kind, "log_title_spam")

        rule_text = ", ".join(t(lang, "rule_" + r) for r in rules) if rules else "—"
        action_text = t(lang, "act_" + action)

        # Verlauf (persistent, gekappt) + Statistik.
        record = {
            "ts": int(time.time()),
            "kind": kind,
            "user_id": getattr(member, "id", 0),
            "user": str(member) if member is not None else "—",
            "action": action,
            "rules": list(rules) if rules else [],
            "channel": getattr(channel, "name", None),
            "points": points,
        }
        async with self.config.guild(guild).history() as hist:
            hist.insert(0, record)
            del hist[HISTORY_MAX:]
        if kind != "lockdown_end":
            await self.config.guild(guild).stats_total.set(int(conf.get("stats_total", 0)) + 1)

        # Log-Kanal.
        chan_id = conf.get("log_channel")
        if chan_id:
            log_channel = guild.get_channel(int(chan_id))
            if isinstance(log_channel, discord.TextChannel):
                colour = {
                    "honeypot": discord.Colour.orange(),
                    "spam": discord.Colour.red(),
                    "raid": discord.Colour.dark_red(),
                    "lockdown_join": discord.Colour.red(),
                    "lockdown_end": discord.Colour.green(),
                }.get(kind, discord.Colour.red())
                embed = discord.Embed(title=t(lang, title_key), colour=colour,
                                      timestamp=discord.utils.utcnow())
                if member is not None:
                    embed.add_field(name=t(lang, "log_user"),
                                    value=f"{member.mention} (`{member.id}`)", inline=False)
                    created = getattr(member, "created_at", None)
                    if created is not None:
                        embed.add_field(name=t(lang, "log_account_age"),
                                        value=f"<t:{int(created.timestamp())}:R>", inline=True)
                if kind != "lockdown_end":
                    embed.add_field(name=t(lang, "log_action"), value=action_text, inline=True)
                if rules:
                    embed.add_field(name=t(lang, "log_rule"), value=rule_text, inline=False)
                if channel is not None:
                    embed.add_field(name=t(lang, "log_channel"),
                                    value=getattr(channel, "mention", f"#{channel}"), inline=True)
                if points is not None:
                    label = t(lang, "log_joins") if kind == "raid" else t(lang, "log_points")
                    embed.add_field(name=label, value=str(points), inline=True)
                try:
                    await log_channel.send(embed=embed)
                except Exception:  # noqa: BLE001
                    pass

        # Optional zusätzlich in Reds modlog.
        if conf.get("use_modlog", True) and member is not None and action in ("ban", "softban", "kick", "timeout"):
            casetype = "guard_honeypot" if kind == "honeypot" else ("guard_raid" if kind in ("raid", "lockdown_join") else "guard_spam")
            try:
                await modlog.create_case(
                    self.bot, guild, discord.utils.utcnow(), casetype,
                    member, moderator=guild.me, reason=action_text + " · " + rule_text,
                )
            except Exception:  # noqa: BLE001
                pass

    # ---- Lockdown ---------------------------------------------------- #
    async def _lockdown_active(self, guild) -> bool:
        return bool(await self.config.guild(guild).lockdown_until())

    async def _start_lockdown(self, guild, *, reason_kind="raid", joins=None) -> bool:
        gconf = self.config.guild(guild)
        if await self._lockdown_active(guild):
            return False
        conf = await gconf.all()
        now = int(time.time())
        auto = int(conf.get("lockdown_auto_minutes", 10))
        until = now + auto * 60 if auto > 0 else -1
        await gconf.lockdown_until.set(until)

        # Slowmode setzen, alte Werte sichern.
        slow = int(conf.get("lockdown_slowmode", 10))
        prev = {}
        if slow > 0 and guild.me and guild.me.guild_permissions.manage_channels:
            for ch in guild.text_channels:
                try:
                    if ch.slowmode_delay != slow:
                        prev[str(ch.id)] = ch.slowmode_delay
                        await ch.edit(slowmode_delay=slow, reason="Guard: Notmodus")
                except Exception:  # noqa: BLE001
                    continue
        await gconf.lockdown_prev.set(prev)

        # Einladungen pausieren (sofern unterstützt).
        paused = False
        if conf.get("lockdown_pause_invites", True):
            try:
                await guild.edit(invites_disabled=True, reason="Guard: Notmodus")
                paused = True
            except Exception:  # noqa: BLE001
                paused = False
        await gconf.lockdown_invites_paused.set(paused)

        await self._log_action(guild, kind="raid", member=None, action="none",
                               rules=[], points=joins)
        log.info("Guard-Notmodus aktiviert auf %s (%s).", guild.id, reason_kind)
        return True

    async def _end_lockdown(self, guild) -> bool:
        gconf = self.config.guild(guild)
        if not await self._lockdown_active(guild):
            return False
        conf = await gconf.all()
        prev = conf.get("lockdown_prev", {}) or {}
        for cid, old in prev.items():
            ch = guild.get_channel(int(cid))
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.edit(slowmode_delay=int(old), reason="Guard: Notmodus beendet")
                except Exception:  # noqa: BLE001
                    continue
        if conf.get("lockdown_invites_paused"):
            try:
                await guild.edit(invites_disabled=False, reason="Guard: Notmodus beendet")
            except Exception:  # noqa: BLE001
                pass
        await gconf.lockdown_prev.set({})
        await gconf.lockdown_invites_paused.set(False)
        await gconf.lockdown_until.set(0)
        await self._log_action(guild, kind="lockdown_end", member=None, action="none", rules=[])
        log.info("Guard-Notmodus beendet auf %s.", guild.id)
        return True

    # ----------------------------------------------------------------- #
    #  Listener: Beitritte (Raid-Erkennung + Notmodus-Behandlung)
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild is None:
            return
        guild = member.guild
        conf = await self.config.guild(guild).all()

        # Während aktivem Notmodus neue Beitritte ggf. behandeln.
        if await self._lockdown_active(guild):
            action = conf.get("lockdown_action_joins", "none")
            if action in ("kick", "timeout") and not await self._is_exempt(member):
                reason = await self._text(guild, "reason_lockdown_join")
                done = await self._execute(guild, member, action, reason,
                                           delete_seconds=0,
                                           timeout_minutes=conf.get("spam_timeout_minutes", 10))
                await self._log_action(guild, kind="lockdown_join", member=member,
                                       action=done, rules=["lockdown_join"])

        # Raid-Erkennung: zu viele Beitritte in kurzer Zeit.
        if conf.get("raid_enabled", True):
            now = time.time()
            dq = self._joins[guild.id]
            dq.append(now)
            window = conf.get("raid_seconds", 20)
            recent = sum(1 for ts in dq if now - ts <= window)
            if recent >= conf.get("raid_joins", 8) and not await self._lockdown_active(guild):
                await self._start_lockdown(guild, reason_kind="raid", joins=recent)

    # ----------------------------------------------------------------- #
    #  Listener: Nachrichten (Honeypot + Spamschutz)
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or self.bot.user is None:
            return
        if message.author.id == self.bot.user.id:
            return
        if message.webhook_id is not None and not isinstance(message.author, discord.Member):
            return

        guild = message.guild
        conf = await self.config.guild(guild).all()
        member = message.author if isinstance(message.author, discord.Member) else guild.get_member(message.author.id)

        # --- Honeypot zuerst ---
        if conf.get("hp_enabled") and conf.get("hp_channel") and message.channel.id == int(conf["hp_channel"]):
            if member is not None and not await self._is_exempt(member, honeypot=True):
                reason = await self._text(guild, "reason_honeypot")
                await self._delete_message(message)
                done = await self._execute(
                    guild, member, conf.get("hp_action", "softban"), reason,
                    delete_seconds=conf.get("hp_delete_seconds", 86400),
                    timeout_minutes=conf.get("hp_timeout_minutes", 60),
                )
                await self._log_action(guild, kind="honeypot", member=member, action=done,
                                       rules=["honeypot"], channel=message.channel)
            return

        # --- Spamschutz ---
        if not conf.get("spam_enabled"):
            return
        if member is None or await self._is_exempt(member, channel=message.channel):
            return

        violations = self._scan_spam(message, conf)
        if not violations:
            return

        key = (guild.id, member.id)
        now = time.time()
        gained = sum(p for _, p in violations)
        ledger = self._points[key]
        ledger.append((now, gained))
        decay = conf.get("decay_seconds", 60)
        ledger[:] = [(ts, p) for ts, p in ledger if now - ts <= decay]
        total = sum(p for _, p in ledger)
        if total <= 0:
            self._acted.pop(key, None)

        if conf.get("delete_violations", True):
            await self._delete_message(message)

        # Eskalationsstufe bestimmen (höchste erreichte zuerst).
        stage = "none"
        for threshold, name in ((conf.get("ban_at", 12), "ban"),
                                (conf.get("kick_at", 9), "kick"),
                                (conf.get("timeout_at", 6), "timeout"),
                                (conf.get("warn_at", 3), "warn")):
            if total >= threshold:
                stage = name
                break
        if stage == "none":
            return

        last_rank = self._acted.get(key, 0)
        if STAGE_RANK[stage] <= last_rank:
            return  # diese (oder eine härtere) Stufe wurde schon ausgeführt
        self._acted[key] = STAGE_RANK[stage]

        rules = [r for r, _ in violations]
        rule_names = ", ".join(rules)
        reason = await self._text(guild, "reason_spam", rules=rule_names)
        done = await self._execute(
            guild, member, stage, reason,
            delete_seconds=conf.get("hp_delete_seconds", 86400),
            timeout_minutes=conf.get("spam_timeout_minutes", 10),
        )
        await self._log_action(guild, kind="spam", member=member, action=done,
                               rules=rules, channel=message.channel, points=int(total))

    def _scan_spam(self, message: discord.Message, conf: dict) -> list:
        """Prüft alle aktiven Heuristiken. Gibt [(regel, punkte), ...] zurück."""
        out = []
        key = (message.guild.id, message.author.id)
        now = time.time()
        content = (message.content or "").strip()

        # Nachrichten-Rate
        if conf.get("s_rate", True):
            dq = self._msgtimes[key]
            dq.append(now)
            window = conf.get("s_rate_seconds", 5)
            count = sum(1 for ts in dq if now - ts <= window)
            if count > conf.get("s_rate_count", 6):
                out.append(("rate", conf.get("pts_rate", 3)))

        # Wiederholungen
        if conf.get("s_repeat", True) and content:
            dq = self._lastmsgs[key]
            norm = content.lower()
            dq.append((norm, message.channel.id, now))
            window = conf.get("s_repeat_seconds", 20)
            cross = conf.get("s_repeat_crosschannel", True)
            same = sum(
                1 for c, ch, ts in dq
                if c == norm and now - ts <= window and (cross or ch == message.channel.id)
            )
            if same >= conf.get("s_repeat_count", 4):
                out.append(("repeat", conf.get("pts_repeat", 3)))

        # Massen-Erwähnungen
        if conf.get("s_mentions", True):
            mentions = len(message.mentions) + len(message.role_mentions)
            if message.mention_everyone or mentions > conf.get("s_mentions_max", 5):
                out.append(("mentions", conf.get("pts_mentions", 4)))

        # Einladungslinks
        if conf.get("s_invites", True) and content and INVITE_RE.search(content):
            out.append(("invite", conf.get("pts_invite", 5)))

        # Externe Links
        if conf.get("s_links", False) and content and URL_RE.search(content):
            out.append(("link", conf.get("pts_link", 2)))

        # Anhang-/Emoji-/Zeilen-Walls (Zeilen am Rohtext zählen, damit auch
        # reine Leerzeilen-Walls erkannt werden – content ist oben gestrippt).
        if conf.get("s_walls", True):
            emojis = len(CUSTOM_EMOJI_RE.findall(content))
            newlines = (message.content or "").count("\n")
            if (len(message.attachments) > conf.get("s_walls_attachments", 6)
                    or emojis > conf.get("s_walls_emojis", 12)
                    or newlines > conf.get("s_walls_newlines", 12)):
                out.append(("wall", conf.get("pts_wall", 2)))

        # Sehr neues Konto – nur, wenn ohnehin etwas auffällig war (Verstärker).
        if conf.get("s_newaccount", True) and out:
            created = getattr(message.author, "created_at", None)
            if created is not None:
                age_h = (discord.utils.utcnow() - created).total_seconds() / 3600.0
                if age_h < conf.get("s_newaccount_hours", 24):
                    out.append(("newaccount", conf.get("pts_newaccount", 2)))

        return out

    # ----------------------------------------------------------------- #
    #  Befehle – Einstellungen (Admin / „Server verwalten\")
    # ----------------------------------------------------------------- #
    @commands.group(name="guardset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def guardset(self, ctx: commands.Context):
        """Guard einrichten: Module, Honeypot, Whitelist, Log, Sprache."""

    @guardset.command(name="module")
    async def guardset_module(self, ctx: commands.Context, module: str, state: bool):
        """Schaltet ein Modul: `honeypot` oder `spam`, jeweils on/off."""
        module = module.lower()
        if module not in ("honeypot", "spam"):
            return await self._say(ctx, "module_unknown")
        await self.config.guild(ctx.guild).set_raw(
            "hp_enabled" if module == "honeypot" else "spam_enabled", value=state
        )
        await self._say(ctx, "module_on" if state else "module_off", module=module)

    @guardset.group(name="honeypot")
    async def guardset_honeypot(self, ctx: commands.Context):
        """Honeypot-Kanal einrichten."""

    @guardset_honeypot.command(name="create")
    @commands.bot_has_permissions(manage_channels=True)
    async def hp_create(self, ctx: commands.Context, *, name: str = "honeypot"):
        """Legt einen neuen Honeypot-Kanal an und aktiviert ihn."""
        try:
            warning = await self._text(ctx.guild, "hp_warning")
            channel = await ctx.guild.create_text_channel(
                name=name[:90], topic=warning[:1024], reason="Guard: Honeypot"
            )
            try:
                await channel.send(warning)
            except Exception:  # noqa: BLE001
                pass
        except discord.Forbidden:
            return await self._say(ctx, "hp_create_failed")
        except discord.HTTPException:
            return await self._say(ctx, "hp_create_failed")
        await self.config.guild(ctx.guild).hp_channel.set(channel.id)
        await self.config.guild(ctx.guild).hp_enabled.set(True)
        await self._say(ctx, "hp_created", channel=channel.mention)

    @guardset_honeypot.command(name="set")
    async def hp_set(self, ctx: commands.Context, channel: discord.TextChannel):
        """Markiert einen bestehenden Kanal als Honeypot und aktiviert ihn."""
        await self.config.guild(ctx.guild).hp_channel.set(channel.id)
        await self.config.guild(ctx.guild).hp_enabled.set(True)
        await self._say(ctx, "hp_set", channel=channel.mention)

    @guardset_honeypot.command(name="disable")
    async def hp_disable(self, ctx: commands.Context):
        """Deaktiviert den Honeypot."""
        await self.config.guild(ctx.guild).hp_enabled.set(False)
        await self._say(ctx, "hp_disabled")

    @guardset_honeypot.command(name="action")
    async def hp_action(self, ctx: commands.Context, action: str):
        """Aktion bei Auslösung: `ban`, `softban`, `kick` oder `timeout`."""
        action = action.lower()
        if action not in ACTIONS:
            return await self._say(ctx, "hp_action_unknown")
        await self.config.guild(ctx.guild).hp_action.set(action)
        await self._say(ctx, "hp_action_set", action=action)

    @guardset.command(name="logchannel")
    async def guardset_logchannel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Setzt den Log-Kanal (ohne Angabe: Log-Kanal entfernen)."""
        if channel is None:
            await self.config.guild(ctx.guild).log_channel.set(None)
            return await self._say(ctx, "log_cleared")
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await self._say(ctx, "log_set", channel=channel.mention)

    @guardset.command(name="whitelistrole")
    async def guardset_wl_role(self, ctx: commands.Context, role: discord.Role):
        """Schaltet eine Rolle in der Ausnahmeliste an/aus."""
        async with self.config.guild(ctx.guild).whitelist_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
                key = "wl_role_removed"
            else:
                roles.append(role.id)
                key = "wl_role_added"
        await self._say(ctx, key, name=role.name)

    @guardset.command(name="whitelistuser")
    async def guardset_wl_user(self, ctx: commands.Context, user: discord.Member):
        """Schaltet einen Nutzer in der Ausnahmeliste an/aus."""
        async with self.config.guild(ctx.guild).whitelist_users() as users:
            if user.id in users:
                users.remove(user.id)
                key = "wl_user_removed"
            else:
                users.append(user.id)
                key = "wl_user_added"
        await self._say(ctx, key, name=str(user))

    @guardset.command(name="whitelistchannel")
    async def guardset_wl_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Nimmt einen Kanal vom Spamschutz aus (an/aus)."""
        async with self.config.guild(ctx.guild).whitelist_channels() as chans:
            if channel.id in chans:
                chans.remove(channel.id)
                key = "wl_channel_removed"
            else:
                chans.append(channel.id)
                key = "wl_channel_added"
        await self._say(ctx, key, name=channel.mention)

    @guardset.command(name="language")
    async def guardset_language(self, ctx: commands.Context, code: str):
        """Sprache setzen (`de` oder `en`)."""
        code = code.lower()
        if code not in LANGUAGES:
            langs = ", ".join(f"`{c}`" for c in LANGUAGES)
            return await self._say(ctx, "lang_unknown", code=code, langs=langs)
        await self.config.guild(ctx.guild).language.set(code)
        await self._say(ctx, "lang_set", lang=LANGUAGES[code])

    @guardset.command(name="settings")
    async def guardset_settings(self, ctx: commands.Context):
        """Zeigt die wichtigsten Einstellungen und den Dashboard-Link."""
        conf = await self.config.guild(ctx.guild).all()
        lang = conf.get("language", "de")
        on = t(lang, "state_on")
        off = t(lang, "state_off")
        hp = on if conf.get("hp_enabled") else off
        spam = on if conf.get("spam_enabled") else off
        ld = on if conf.get("lockdown_until") else off
        log_ch = ctx.guild.get_channel(conf["log_channel"]) if conf.get("log_channel") else None
        lines = [
            t(lang, "settings_header", guild=ctx.guild.name),
            f"• Honeypot: **{hp}** · {t(lang, 'log_action')}: `{conf.get('hp_action')}`",
            f"• Spamschutz: **{spam}** · Decay {conf.get('decay_seconds')}s · "
            f"warn/timeout/kick/ban = {conf.get('warn_at')}/{conf.get('timeout_at')}/"
            f"{conf.get('kick_at')}/{conf.get('ban_at')}",
            f"• Notmodus: **{ld}** · Raid {conf.get('raid_joins')}/{conf.get('raid_seconds')}s",
            f"• Log: {log_ch.mention if log_ch else '—'} · modlog: "
            f"{'an' if conf.get('use_modlog') else 'aus'}",
            t(lang, "dashboard_hint"),
        ]
        await ctx.send("\n".join(lines))

    # ----------------------------------------------------------------- #
    #  Befehle – Notmodus (manuell)
    # ----------------------------------------------------------------- #
    @commands.command(name="lockdown")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def lockdown_cmd(self, ctx: commands.Context, state: str):
        """Notmodus manuell schalten: `on` oder `off`."""
        state = state.lower()
        if state in ("on", "an", "true"):
            if await self._start_lockdown(ctx.guild, reason_kind="manual"):
                await self._say(ctx, "lockdown_started")
            else:
                await self._say(ctx, "lockdown_already")
        elif state in ("off", "aus", "false"):
            if await self._end_lockdown(ctx.guild):
                await self._say(ctx, "lockdown_ended")
            else:
                await self._say(ctx, "lockdown_not_active")
        else:
            await self._say(ctx, "lockdown_bad_state")
