from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify

from .api import AuthError, NoCredentials, RateLimited, TwitchAPI, TwitchError
from .dashboard import dashboard_handler
from .embed import (
    LIMIT_TEMPLATE, LIMIT_TITLE, cap, ended_embed, link_view, live_embed, parse_ts, render_template, stream_url,
)
from .strings import DEFAULT_LANGUAGE, LANGUAGES, default_message, t

log = logging.getLogger("red.red-cogs.twitchlive")

POLL_DEFAULT = 60
POLL_MIN, POLL_MAX = 60, 600
UPDATE_INTERVAL = 600      # Live-Meldung alle ~10 min aktualisieren
GRACE = 300                # Offline-Aussetzer < 5 min zählen nicht als neuer Stream
MAX_BACKOFF = 900          # Backoff-Obergrenze (15 min)
USER_TTL = 6 * 3600        # Profilbild/Anzeigename so lange cachen
MAX_CHANNELS = 100         # beobachtete Kanäle pro Server
END_ACTIONS = ("edit", "delete")

_LOGIN_RE = re.compile(r"^[a-z0-9_]{3,25}$")
_URL_RE = re.compile(r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/", re.I)


def normalize_login(raw: str | None) -> str:
    """``https://twitch.tv/Name`` / ``@Name`` / ``Name`` -> ``name``."""
    value = _URL_RE.sub("", (raw or "").strip()).strip().lstrip("@").split("/")[0].split("?")[0]
    return value.lower()


def valid_login(login: str) -> bool:
    return bool(_LOGIN_RE.match(login or ""))


def _today(now: float) -> str:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Berlin")
    except Exception:  # noqa: BLE001 – tzdata fehlt (z. B. Windows) -> UTC
        tz = timezone.utc
    return datetime.fromtimestamp(now, tz=tz).strftime("%Y-%m-%d")


class TwitchLive(commands.Cog):
    """Twitch-Live-Meldungen mit Dashboard (eigene deutschsprachige Variante zu Reds „Streams“)."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=618305729164, force_registration=True)
        self.config.register_global(
            client_id="",
            client_secret="",
            poll_interval=POLL_DEFAULT,
        )
        self.config.register_guild(
            language=DEFAULT_LANGUAGE,
            default_channel=None,
            default_message="",        # leer = Standardtext der Sprache
            end_action="edit",         # "edit" | "delete"
            live_role=None,
            links={},                  # str(discord_user_id) -> twitch_login
            channels={},               # login -> {channel_id, ping_role, message, enabled, display_name, added}
            state={},                  # login -> laufende Live-Sitzung (Nachricht-ID, Stream-ID, live seit …)
            announced={},              # login -> zuletzt gemeldete Stream-ID (gegen Doppelmeldungen, auch nach Neustart)
            stats={"day": "", "today": 0, "total": 0},
        )
        self.api = TwitchAPI(self._credentials, clock=lambda: self._now())
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._locks: dict[int, asyncio.Lock] = {}
        self._users: dict[str, tuple[float, dict | None]] = {}
        self._failures = 0
        self.status: dict = {"state": "idle", "last_ok": None, "last_error": None, "error": "",
                             "failures": 0, "next_poll": None, "live": 0, "watched": 0}

    # ----------------------------------------------------------------- #
    #  Hilfen
    # ----------------------------------------------------------------- #
    def _now(self) -> float:
        return time.time()

    def _lock(self, gid: int) -> asyncio.Lock:
        lock = self._locks.get(gid)
        if lock is None:
            lock = self._locks[gid] = asyncio.Lock()
        return lock

    async def _credentials(self) -> tuple[str, str]:
        return (await self.config.client_id()) or "", (await self.config.client_secret()) or ""

    async def has_credentials(self) -> bool:
        cid, secret = await self._credentials()
        return bool(cid and secret)

    async def _interval(self) -> int:
        try:
            value = int(await self.config.poll_interval())
        except (TypeError, ValueError):
            value = POLL_DEFAULT
        return max(POLL_MIN, min(POLL_MAX, value))

    def _kick(self):
        """Hintergrund-Schleife sofort abfragen lassen (z. B. nach neuen Zugangsdaten)."""
        if self._wake is not None:
            self._wake.set()

    @staticmethod
    def can_post(channel) -> bool:
        guild = getattr(channel, "guild", None)
        me = getattr(guild, "me", None)
        if me is None:
            return False
        try:
            perms = channel.permissions_for(me)
        except Exception:  # noqa: BLE001
            return False
        return bool(perms.view_channel and perms.send_messages and perms.embed_links)

    @staticmethod
    def role_manageable(guild, role) -> bool:
        """Kann der Bot ``role`` vergeben (Recht + Hierarchie)?"""
        me = getattr(guild, "me", None)
        if role is None or me is None or role.is_default() or getattr(role, "managed", False):
            return False
        if not getattr(me.guild_permissions, "manage_roles", False):
            return False
        try:
            return role < me.top_role
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def target_channel(guild, conf: dict, entry: dict | None):
        cid = (entry or {}).get("channel_id") or conf.get("default_channel")
        ch = guild.get_channel(int(cid)) if cid else None
        return ch if isinstance(ch, (discord.TextChannel, discord.Thread)) else None

    def user_info(self, login: str) -> dict:
        cached = self._users.get(login)
        return (cached[1] if cached else None) or {}

    async def _refresh_users(self, logins, *, force: bool = False):
        now = self._now()
        need = [l for l in sorted(set(logins))
                if force or l not in self._users or now - self._users[l][0] > USER_TTL]
        if not need:
            return
        users = await self.api.users(need)
        for login in need:
            self._users[login] = (now, users.get(login))

    # ----------------------------------------------------------------- #
    #  Red-Datenschutz-API
    # ----------------------------------------------------------------- #
    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Entfernt die Discord↔Twitch-Verknüpfung dieses Nutzers (Live-Rolle) auf allen Servern."""
        uid = str(user_id)
        try:
            all_guilds = await self.config.all_guilds()
        except Exception:  # noqa: BLE001
            return
        for gid, data in all_guilds.items():
            try:
                if uid in (data.get("links") or {}):
                    async with self.config.guild_from_id(int(gid)).links() as links:
                        links.pop(uid, None)
                if any(uid in (s.get("role_members") or []) for s in (data.get("state") or {}).values()):
                    async with self._lock(int(gid)):
                        async with self.config.guild_from_id(int(gid)).state() as state:
                            for sess in state.values():
                                members = sess.get("role_members") or []
                                if uid in members:
                                    members.remove(uid)
            except Exception:  # noqa: BLE001
                continue

    # ----------------------------------------------------------------- #
    #  Lebenszyklus + Dashboard
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._runner())

    async def cog_unload(self):
        if self._task is not None:
            self._task.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)
        await self.api.close()

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="twitchlive",
            name="Twitch-Live",
            icon="bi-twitch",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Hintergrund: eine gemeinsame Abfrage für alle Server
    # ----------------------------------------------------------------- #
    async def _runner(self):
        try:
            await self.bot.wait_until_red_ready()
        except Exception:  # noqa: BLE001
            pass
        while True:
            try:
                delay = await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 – die Schleife darf nie sterben
                log.exception("TwitchLive: unerwarteter Fehler in der Abfrage")
                delay = 300
            self.status["next_poll"] = self._now() + delay
            if self._wake is None:
                self._wake = asyncio.Event()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def _backoff(self, interval: int, state: str, message: str, retry_after: float | None = None) -> float:
        self._failures += 1
        delay = min(MAX_BACKOFF, interval * (2 ** min(self._failures, 8)))
        if retry_after:
            delay = max(delay, retry_after)
        self.status.update(state=state, last_error=self._now(), error=message, failures=self._failures)
        log.warning("TwitchLive: %s – nächster Versuch in %d s", message, int(delay))
        return float(delay)

    async def poll_once(self) -> float:
        """Eine Abfrage-Runde. Gibt die Wartezeit bis zur nächsten Runde (Sekunden) zurück."""
        interval = await self._interval()
        if not await self.has_credentials():
            self.status.update(state="no_credentials", error="")
            return float(interval)

        all_guilds = await self.config.all_guilds()
        targets = []
        logins: set[str] = set()
        watched = 0
        for gid, data in all_guilds.items():
            guild = self.bot.get_guild(int(gid))
            chans = data.get("channels") or {}
            state = data.get("state") or {}
            if guild is None or (not chans and not state):
                continue
            try:
                if await self.bot.cog_disabled_in_guild(self, guild):
                    continue
            except Exception:  # noqa: BLE001
                pass
            targets.append(guild)
            enabled = {l for l, e in chans.items() if (e or {}).get("enabled", True)}
            watched += len(enabled)
            logins |= enabled | set(state)
        self.status["watched"] = watched
        if not logins:
            self._failures = 0
            self.status.update(state="ok", last_ok=self._now(), error="", failures=0, live=0)
            return float(interval)

        try:
            streams = await self.api.streams(sorted(logins))
        except RateLimited as exc:
            return self._backoff(interval, "rate_limited", "Twitch-Rate-Limit (429)", exc.retry_after)
        except (AuthError, NoCredentials):
            return self._backoff(interval, "auth_error", "Twitch lehnt die Zugangsdaten ab")
        except TwitchError as exc:
            return self._backoff(interval, "error", str(exc))

        try:
            # Profilbilder/Anzeigenamen: live Kanäle sofort, alle anderen nur nach Ablauf des Caches.
            await self._refresh_users(sorted(logins))
        except TwitchError as exc:
            log.debug("TwitchLive: Nutzerdaten nicht abrufbar (%s)", exc)

        self._failures = 0
        self.status.update(state="ok", last_ok=self._now(), error="", failures=0, live=len(streams))
        for guild in targets:
            try:
                await self._process_guild(guild, streams)
            except Exception:  # noqa: BLE001 – ein Server darf die anderen nicht blockieren
                log.exception("TwitchLive: Verarbeitung für Guild %s fehlgeschlagen", guild.id)
        return float(interval)

    async def _process_guild(self, guild, streams: dict):
        gconf = self.config.guild(guild)
        async with self._lock(guild.id):
            conf = await gconf.all()
            chans = conf.get("channels") or {}
            state = dict(conf.get("state") or {})
            announced = dict(conf.get("announced") or {})
            stats = dict(conf.get("stats") or {})
            lang = conf.get("language") or DEFAULT_LANGUAGE
            now = self._now()
            enabled = {l for l, e in chans.items() if (e or {}).get("enabled", True)}
            changed = False
            for login in sorted(set(state) | enabled):
                try:
                    stream = streams.get(login)
                    sess = state.get(login)
                    entry = chans.get(login)
                    if stream is not None:
                        if sess is not None:
                            same = (sess.get("stream_id") == stream.get("id")
                                    or now - float(sess.get("last_seen") or 0) < GRACE)
                            if same:
                                await self._continue_session(guild, conf, entry, login, sess, stream, lang, now)
                                if stream.get("id"):
                                    announced[login] = stream.get("id")
                                changed = True
                                continue
                            # Alte Sitzung ist lange vorbei (z. B. Bot war offline) -> sauber beenden.
                            await self._end_session(guild, conf, login, sess, lang)
                            state.pop(login, None)
                            changed = True
                        if login in enabled:
                            # Dieselbe Stream-ID wurde schon gemeldet (z. B. Twitch-Aussetzer > 5 min)
                            # -> Sitzung still fortsetzen, keine zweite Meldung.
                            silent = bool(stream.get("id")) and announced.get(login) == stream.get("id")
                            sess = await self._start_session(guild, conf, entry, login, stream, lang, now,
                                                             silent=silent)
                            state[login] = sess
                            if stream.get("id"):
                                announced[login] = stream.get("id")
                            if sess.get("message_id"):
                                stats = self._bump(stats, now)
                            changed = True
                    elif sess is not None and now - float(sess.get("last_seen") or 0) >= GRACE:
                        await self._end_session(guild, conf, login, sess, lang)
                        state.pop(login, None)
                        changed = True
                except Exception:  # noqa: BLE001 – pro Eintrag abfangen
                    log.exception("TwitchLive: Fehler bei %s (Guild %s)", login, guild.id)
            if changed:
                # Einträge entfernter Streamer nicht ewig mitschleppen.
                keep = set(chans) | set(state)
                announced = {k: v for k, v in announced.items() if k in keep}
                await gconf.state.set(state)
                await gconf.announced.set(announced)
                await gconf.stats.set(stats)

    @staticmethod
    def _bump(stats: dict, now: float) -> dict:
        day = _today(now)
        if stats.get("day") != day:
            stats = {"day": day, "today": 0, "total": int(stats.get("total") or 0)}
        stats["today"] = int(stats.get("today") or 0) + 1
        stats["total"] = int(stats.get("total") or 0) + 1
        return stats

    # ----------------------------------------------------------------- #
    #  Sitzungen
    # ----------------------------------------------------------------- #
    def _name_avatar(self, login: str, stream: dict | None, fallback: dict | None = None):
        user = self.user_info(login)
        name = (user.get("display_name") or (stream or {}).get("user_name")
                or (fallback or {}).get("name") or login)
        avatar = user.get("profile_image_url") or (fallback or {}).get("avatar") or None
        return str(name), avatar

    async def _start_session(self, guild, conf, entry, login, stream, lang, now, *, silent=False) -> dict:
        name, avatar = self._name_avatar(login, stream)
        started = parse_ts(stream.get("started_at")) or now
        sess = {
            "stream_id": stream.get("id"),
            "started_at": started,
            "announced_at": now,
            "last_seen": now,
            "last_update": now,
            "message_id": None,
            "channel_id": None,
            "title": cap(stream.get("title") or "", LIMIT_TITLE),
            "game": stream.get("game_name") or "",
            "games": [stream.get("game_name")] if stream.get("game_name") else [],
            "viewers": int(stream.get("viewer_count") or 0),
            "peak_viewers": int(stream.get("viewer_count") or 0),
            "thumbnail_url": str(stream.get("thumbnail_url") or "")[:300],
            "name": name,
            "avatar": avatar,
            "role_id": None,
            "role_members": [],
            "silent": bool(silent),   # True = schon gemeldet, nicht erneut posten
            "post_failed": False,
        }
        if not silent:
            await self._post(guild, conf, entry, login, sess, stream, lang, now)
        await self._grant_live_role(guild, conf, login, sess)
        return sess

    async def _post(self, guild, conf, entry, login, sess, stream, lang, now):
        channel = self.target_channel(guild, conf, entry)
        if channel is None:
            sess["post_failed"] = True
            return
        try:
            msg = await self.send_alert(channel, conf, entry, login, sess["name"], sess["avatar"], stream, lang, now)
        except discord.HTTPException as exc:
            sess["post_failed"] = True
            log.warning("TwitchLive: Meldung für %s in #%s fehlgeschlagen (HTTP %s)",
                        login, getattr(channel, "name", "?"), getattr(exc, "status", "?"))
            return
        sess["post_failed"] = False
        sess["message_id"] = msg.id
        sess["channel_id"] = channel.id

    async def send_alert(self, channel, conf, entry, login, name, avatar, stream, lang, now, *, test=False):
        guild = channel.guild
        rid = (entry or {}).get("ping_role")
        role = guild.get_role(int(rid)) if rid else None
        if role is not None and role.is_default():
            role = None
        template = (entry or {}).get("message") or conf.get("default_message") or default_message(lang)
        content = render_template(
            template,
            streamer=discord.utils.escape_markdown(name),
            title=cap(stream.get("title") or t(lang, "no_title"), LIMIT_TITLE),
            game=stream.get("game_name") or t(lang, "no_game"),
            url=stream_url(login),
            ping=role.mention if role is not None else "",
        )
        if test:
            content = cap(f"{t(lang, 'test_prefix')}\n{content}", 2000)
            allowed = discord.AllowedMentions.none()
        else:
            # Genau die gewählte Rolle – nie @everyone/@here oder Nutzer aus Titel/Vorlage.
            allowed = discord.AllowedMentions(everyone=False, users=False, replied_user=False,
                                              roles=[role] if role is not None else False)
        embed = live_embed(login=login, name=name, avatar=avatar, stream=stream, lang=lang, now=now, test=test)
        return await channel.send(content=content, embed=embed, view=link_view(login, lang),
                                  allowed_mentions=allowed)

    async def _continue_session(self, guild, conf, entry, login, sess, stream, lang, now):
        sess["stream_id"] = stream.get("id")
        sess["last_seen"] = now
        sess["title"] = cap(stream.get("title") or "", LIMIT_TITLE)
        game = stream.get("game_name") or ""
        sess["game"] = game
        if game and game not in (sess.get("games") or []):
            sess.setdefault("games", []).append(game)
            sess["games"] = sess["games"][-20:]
        viewers = int(stream.get("viewer_count") or 0)
        sess["viewers"] = viewers
        sess["thumbnail_url"] = str(stream.get("thumbnail_url") or "")[:300]
        sess["peak_viewers"] = max(int(sess.get("peak_viewers") or 0), viewers)
        name, avatar = self._name_avatar(login, stream, sess)
        sess["name"], sess["avatar"] = name, avatar
        if now - float(sess.get("last_update") or 0) < UPDATE_INTERVAL:
            return
        sess["last_update"] = now
        if not sess.get("message_id"):
            # Nur wenn das Posten fehlgeschlagen war (Rechte/Kanal) im Update-Takt erneut versuchen –
            # nie, wenn die Meldung gelöscht wurde oder der Stream schon gemeldet war (sonst doppelt).
            if (sess.get("post_failed") and not sess.get("deleted") and not sess.get("silent")
                    and entry is not None and entry.get("enabled", True)):
                await self._post(guild, conf, entry, login, sess, stream, lang, now)
            return
        msg = await self._fetch(guild, sess)
        if msg is None:
            return
        try:
            await msg.edit(embed=live_embed(login=login, name=name, avatar=avatar, stream=stream, lang=lang, now=now),
                           view=link_view(login, lang))
        except discord.NotFound:
            sess["message_id"] = None       # gelöscht -> nicht erneut posten (sonst doppelt)
            sess["deleted"] = True
        except discord.HTTPException as exc:
            log.debug("TwitchLive: Update für %s fehlgeschlagen (HTTP %s)", login, getattr(exc, "status", "?"))

    async def _fetch(self, guild, sess):
        ch = guild.get_channel(int(sess["channel_id"])) if sess.get("channel_id") else None
        if ch is None or not sess.get("message_id"):
            return None
        try:
            return await ch.fetch_message(int(sess["message_id"]))
        except discord.NotFound:
            sess["message_id"] = None
            sess["deleted"] = True
        except discord.HTTPException:
            pass
        return None

    async def _end_session(self, guild, conf, login, sess, lang):
        try:
            msg = await self._fetch(guild, sess)
            if msg is not None:
                if (conf.get("end_action") or "edit") == "delete":
                    await msg.delete()
                else:
                    name = sess.get("name") or login
                    await msg.edit(
                        content=t(lang, "ended_content", streamer=discord.utils.escape_markdown(name)),
                        embed=ended_embed(login=login, name=name, avatar=sess.get("avatar"), session=sess, lang=lang),
                        view=link_view(login, lang, ended=True),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
        except discord.HTTPException as exc:
            log.debug("TwitchLive: Ende-Bearbeitung für %s fehlgeschlagen (HTTP %s)", login, getattr(exc, "status", "?"))
        await self._revoke_live_role(guild, sess)

    # ----------------------------------------------------------------- #
    #  Live-Rolle
    # ----------------------------------------------------------------- #
    async def _grant_live_role(self, guild, conf, login, sess):
        rid = conf.get("live_role")
        role = guild.get_role(int(rid)) if rid else None
        if role is None or not self.role_manageable(guild, role):
            return
        given = []
        for uid, linked in (conf.get("links") or {}).items():
            if linked != login or not str(uid).isdigit():
                continue
            member = guild.get_member(int(uid))
            if member is None or role in member.roles:
                continue
            try:
                await member.add_roles(role, reason=f"TwitchLive: {login} ist live")
                given.append(str(uid))
            except discord.HTTPException:
                log.debug("TwitchLive: Live-Rolle für %s nicht vergeben", uid)
        sess["role_id"] = role.id
        sess["role_members"] = given

    async def _revoke_live_role(self, guild, sess):
        rid = sess.get("role_id")
        role = guild.get_role(int(rid)) if rid else None
        if role is None:
            return
        for uid in sess.get("role_members") or []:
            member = guild.get_member(int(uid)) if str(uid).isdigit() else None
            if member is None or role not in member.roles:
                continue
            try:
                await member.remove_roles(role, reason="TwitchLive: Stream beendet")
            except discord.HTTPException:
                log.debug("TwitchLive: Live-Rolle für %s nicht entfernt", uid)
        sess["role_members"] = []

    # ----------------------------------------------------------------- #
    #  Aktionen (von Befehlen und Dashboard gemeinsam genutzt)
    # ----------------------------------------------------------------- #
    async def lookup_user(self, login: str) -> tuple[bool | None, dict | None]:
        """(existiert?, user). ``None`` = nicht prüfbar (keine Zugangsdaten/API-Fehler)."""
        if not await self.has_credentials():
            return None, None
        try:
            await self._refresh_users([login], force=True)
        except TwitchError:
            return None, None
        user = self.user_info(login)
        return bool(user), user or None

    async def upsert_channel(self, guild, login: str, *, channel_id=None, ping_role=None, message=None,
                             enabled=None, verify: bool = True) -> tuple[bool, str | None]:
        """Legt einen Streamer an bzw. ändert ihn. -> (neu?, Fehler-Key|None).

        ``None`` = Feld unverändert lassen, ``0``/``""`` = zurücksetzen. ``verify`` prüft den Login
        bei Twitch (nur wenn Zugangsdaten gesetzt sind und Twitch erreichbar ist).
        """
        exists, user = await self.lookup_user(login) if verify else (None, None)
        if exists is False:
            return False, "unknown_login"
        async with self._lock(guild.id), self.config.guild(guild).channels() as chans:
            new = login not in chans
            if new and len(chans) >= MAX_CHANNELS:
                return False, "too_many"
            entry = chans.get(login) or {"channel_id": None, "ping_role": None, "message": "", "enabled": True,
                                         "display_name": "", "added": int(self._now())}
            if channel_id is not None:
                entry["channel_id"] = channel_id or None
            if ping_role is not None:
                entry["ping_role"] = ping_role or None
            if message is not None:
                entry["message"] = (message or "").strip()[:LIMIT_TEMPLATE]
            if enabled is not None:
                entry["enabled"] = bool(enabled)
            if user and user.get("display_name"):
                entry["display_name"] = str(user["display_name"])[:64]
            chans[login] = entry
        return new, None

    async def set_link(self, guild, user_id: int, login: str | None) -> bool:
        """Verknüpft ein Mitglied mit einem Twitch-Login (``None`` = entfernen). -> gab es vorher eine?"""
        async with self._lock(guild.id), self.config.guild(guild).links() as links:
            existed = str(user_id) in links
            if login:
                links[str(user_id)] = login
            else:
                links.pop(str(user_id), None)
        return existed

    async def may_grant(self, member, role) -> bool:
        """Darf ``member`` die Live-Rolle ``role`` automatisch vergeben lassen? (Schutz vor Selbst-Hochstufung)

        Bot-Owner, Server-Inhaber und Administratoren immer; sonst nur Rollen unter der eigenen
        höchsten Rolle ohne Verwaltungs-/Moderationsrechte.
        """
        if await self.bot.is_owner(member):
            return True
        guild = getattr(member, "guild", None)
        if guild is not None and member.id == getattr(guild, "owner_id", None):
            return True
        if getattr(member.guild_permissions, "administrator", False):
            return True
        p = role.permissions
        if any(getattr(p, name, False) for name in (
                "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_messages",
                "kick_members", "ban_members", "moderate_members", "manage_webhooks", "mention_everyone")):
            return False
        try:
            return role < member.top_role
        except Exception:  # noqa: BLE001
            return False

    async def remove_channel(self, guild, login: str) -> bool:
        async with self._lock(guild.id):
            async with self.config.guild(guild).channels() as chans:
                existed = chans.pop(login, None) is not None
            conf = await self.config.guild(guild).all()
            sess = (conf.get("state") or {}).get(login)
            if sess is not None:
                sess["last_seen"] = max(float(sess.get("last_seen") or 0), self._now())
                await self._end_session(guild, conf, login, sess, conf.get("language") or DEFAULT_LANGUAGE)
                async with self.config.guild(guild).state() as state:
                    state.pop(login, None)
            async with self.config.guild(guild).announced() as announced:
                announced.pop(login, None)
        return existed

    async def send_test(self, guild, login: str):
        """Testmeldung in den Zielkanal. -> (Nachricht|None, Kanal|None)."""
        conf = await self.config.guild(guild).all()
        entry = (conf.get("channels") or {}).get(login)
        lang = conf.get("language") or DEFAULT_LANGUAGE
        channel = self.target_channel(guild, conf, entry)
        if channel is None:
            return None, None
        now = self._now()
        stream = None
        if await self.has_credentials():
            try:
                await self._refresh_users([login])
                stream = (await self.api.streams([login])).get(login)
            except TwitchError:
                stream = None
        name, avatar = self._name_avatar(login, stream, {"name": (entry or {}).get("display_name")})
        if stream is None:
            stream = {"title": t(lang, "test_offline_title", streamer=name), "game_name": "Just Chatting",
                      "viewer_count": 0, "started_at": None, "thumbnail_url": ""}
        try:
            msg = await self.send_alert(channel, conf, entry, login, name, avatar, stream, lang, now, test=True)
        except discord.HTTPException:
            return None, channel
        return msg, channel

    async def set_credentials(self, client_id: str, client_secret: str) -> str:
        """Speichert die Zugangsdaten und prüft sie per Token-Abruf. -> ok|bad|error"""
        await self.config.client_id.set(client_id.strip())
        await self.config.client_secret.set(client_secret.strip())
        self.api.reset_token()
        self._failures = 0
        try:
            await self.api.get_token(force=True)
            result = "ok"
        except AuthError:
            result = "bad"
            self.status.update(state="auth_error", last_error=self._now(), error="Twitch lehnt die Zugangsdaten ab")
        except TwitchError:
            result = "error"
        self._kick()
        return result

    # ----------------------------------------------------------------- #
    #  Befehle – [p]twitch (Streamer verwalten)
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        if guild is None:
            return DEFAULT_LANGUAGE
        return await self.config.guild(guild).language()

    async def _watched_entry(self, ctx, raw_login: str):
        """-> (login, lang) wenn der Login auf diesem Server beobachtet wird, sonst Antwort + (None, lang)."""
        lang = await self._lang(ctx.guild)
        login = normalize_login(raw_login)
        chans = await self.config.guild(ctx.guild).channels()
        if login not in chans:
            await ctx.send(t(lang, "not_watched", login=discord.utils.escape_markdown(login[:40])),
                           allowed_mentions=discord.AllowedMentions.none())
            return None, lang
        return login, lang

    @commands.hybrid_group(name="twitch")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def twitch(self, ctx: commands.Context):
        """Twitch-Live-Meldungen: Streamer hinzufügen, entfernen, testen."""

    @twitch.command(name="add")
    async def tw_add(self, ctx: commands.Context, login: str, kanal: Optional[discord.TextChannel] = None,
                     ping: Optional[discord.Role] = None):
        """Streamer beobachten (oder Zielkanal/Ping-Rolle ändern).

        Ohne Kanal gilt der Standardkanal ([p]twitchset channel). Ping-Rolle optional.
        Beispiel: [p]twitch add matters86 #live @Streams
        """
        lang = await self._lang(ctx.guild)
        login = normalize_login(login)
        if not valid_login(login):
            return await ctx.send(t(lang, "bad_login", login=discord.utils.escape_markdown(login[:40])),
                                  allowed_mentions=discord.AllowedMentions.none())
        conf = await self.config.guild(ctx.guild).all()
        target = kanal or self.target_channel(ctx.guild, conf, (conf.get("channels") or {}).get(login))
        if target is None:
            return await ctx.send(t(lang, "no_channel", prefix=ctx.clean_prefix))
        if not self.can_post(target):
            return await ctx.send(t(lang, "bad_channel", channel=target.mention))
        if ping is not None and ping.is_default():
            ping = None
        async with ctx.typing():
            new, err = await self.upsert_channel(ctx.guild, login, channel_id=kanal.id if kanal else None,
                                                 ping_role=ping.id if ping else None)
        if err:
            return await ctx.send(t(lang, err, login=login, max=MAX_CHANNELS))
        entry = (await self.config.guild(ctx.guild).channels()).get(login) or {}
        role = ctx.guild.get_role(entry.get("ping_role") or 0)
        await ctx.send(
            t(lang, "added" if new else "updated", login=login, channel=target.mention,
              ping=role.mention if role else t(lang, "ping_none")),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self._kick()

    @twitch.command(name="remove", aliases=["delete", "del"])
    async def tw_remove(self, ctx: commands.Context, login: str):
        """Streamer nicht mehr beobachten (eine laufende Meldung wird beendet)."""
        lang = await self._lang(ctx.guild)
        login = normalize_login(login)
        if not await self.remove_channel(ctx.guild, login):
            return await ctx.send(t(lang, "not_watched", login=discord.utils.escape_markdown(login[:40])),
                                  allowed_mentions=discord.AllowedMentions.none())
        await ctx.send(t(lang, "removed", login=login))

    @twitch.command(name="list")
    async def tw_list(self, ctx: commands.Context):
        """Beobachtete Streamer auflisten (🔴 live · 🟢 aktiv · ⚪ pausiert)."""
        lang = await self._lang(ctx.guild)
        conf = await self.config.guild(ctx.guild).all()
        chans = conf.get("channels") or {}
        if not chans:
            return await ctx.send(t(lang, "list_empty"))
        rows = [t(lang, "list_header")]
        state = conf.get("state") or {}
        for login in sorted(chans):
            entry = chans[login]
            ch = self.target_channel(ctx.guild, conf, entry)
            role = ctx.guild.get_role(entry.get("ping_role") or 0)
            icon = "state_live" if login in state else ("state_on" if entry.get("enabled", True) else "state_off")
            rows.append(t(lang, "list_row", state=t(lang, icon), login=login,
                          channel=ch.mention if ch else "—",
                          ping=role.mention if role else t(lang, "ping_none"),
                          custom=t(lang, "list_custom") if entry.get("message") else ""))
        if not await self.has_credentials():
            rows.append("")
            rows.append(t(lang, "no_creds_hint", prefix=ctx.clean_prefix))
        for page in pagify("\n".join(rows), delims=["\n"], page_length=1900):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @twitch.command(name="test")
    async def tw_test(self, ctx: commands.Context, login: str):
        """Testmeldung in den Zielkanal posten (ohne echten Ping)."""
        lang = await self._lang(ctx.guild)
        login = normalize_login(login)
        if not valid_login(login):
            return await ctx.send(t(lang, "bad_login", login=discord.utils.escape_markdown(login[:40])),
                                  allowed_mentions=discord.AllowedMentions.none())
        async with ctx.typing():
            msg, channel = await self.send_test(ctx.guild, login)
        if channel is None:
            return await ctx.send(t(lang, "no_channel", prefix=ctx.clean_prefix))
        if msg is None:
            return await ctx.send(t(lang, "test_failed", channel=channel.mention))
        await ctx.send(t(lang, "test_sent", login=login, channel=channel.mention))

    @twitch.command(name="channel")
    async def tw_channel(self, ctx: commands.Context, login: str, kanal: Optional[discord.TextChannel] = None):
        """Zielkanal eines Streamers setzen (ohne Kanal: Standardkanal)."""
        login, lang = await self._watched_entry(ctx, login)
        if login is None:
            return
        if kanal is not None and not self.can_post(kanal):
            return await ctx.send(t(lang, "bad_channel", channel=kanal.mention))
        await self.upsert_channel(ctx.guild, login, channel_id=kanal.id if kanal else 0, verify=False)
        if kanal is not None:
            return await ctx.send(t(lang, "channel_set", login=login, channel=kanal.mention))
        conf = await self.config.guild(ctx.guild).all()
        default = self.target_channel(ctx.guild, conf, None)
        await ctx.send(t(lang, "channel_reset", login=login, channel=default.mention if default else "—"))

    @twitch.command(name="role")
    async def tw_role(self, ctx: commands.Context, login: str, rolle: Optional[discord.Role] = None):
        """Ping-Rolle eines Streamers setzen (ohne Rolle: kein Ping)."""
        login, lang = await self._watched_entry(ctx, login)
        if login is None:
            return
        if rolle is not None and rolle.is_default():
            rolle = None
        await self.upsert_channel(ctx.guild, login, ping_role=rolle.id if rolle else 0, verify=False)
        if rolle is None:
            return await ctx.send(t(lang, "role_cleared", login=login))
        await ctx.send(t(lang, "role_set", login=login, role=rolle.mention),
                       allowed_mentions=discord.AllowedMentions.none())

    @twitch.command(name="message", aliases=["text"])
    async def tw_message(self, ctx: commands.Context, login: str, *, text: Optional[str] = None):
        """Eigene Nachricht eines Streamers setzen (ohne Text: Standardtext).

        Platzhalter: {streamer} {title} {game} {url} {ping}
        """
        login, lang = await self._watched_entry(ctx, login)
        if login is None:
            return
        if text and len(text) > LIMIT_TEMPLATE:
            return await ctx.send(t(lang, "message_too_long", max=LIMIT_TEMPLATE))
        await self.upsert_channel(ctx.guild, login, message=(text or "").strip(), verify=False)
        await ctx.send(t(lang, "text_set" if text else "text_reset", login=login))

    @twitch.command(name="toggle")
    async def tw_toggle(self, ctx: commands.Context, login: str):
        """Meldungen eines Streamers pausieren/fortsetzen."""
        login, lang = await self._watched_entry(ctx, login)
        if login is None:
            return
        entry = (await self.config.guild(ctx.guild).channels()).get(login) or {}
        enabled = not entry.get("enabled", True)
        await self.upsert_channel(ctx.guild, login, enabled=enabled, verify=False)
        await ctx.send(t(lang, "toggled_on" if enabled else "toggled_off", login=login))

    @twitch.command(name="link")
    async def tw_link(self, ctx: commands.Context, mitglied: discord.Member, login: str):
        """Discord-Mitglied mit einem Twitch-Login verknüpfen (für die Live-Rolle)."""
        lang = await self._lang(ctx.guild)
        login = normalize_login(login)
        if not valid_login(login):
            return await ctx.send(t(lang, "bad_login", login=discord.utils.escape_markdown(login[:40])),
                                  allowed_mentions=discord.AllowedMentions.none())
        await self.set_link(ctx.guild, mitglied.id, login)
        await ctx.send(t(lang, "link_set", member=mitglied.mention, login=login),
                       allowed_mentions=discord.AllowedMentions.none())

    @twitch.command(name="unlink")
    async def tw_unlink(self, ctx: commands.Context, mitglied: discord.Member):
        """Verknüpfung eines Mitglieds entfernen."""
        lang = await self._lang(ctx.guild)
        existed = await self.set_link(ctx.guild, mitglied.id, None)
        await ctx.send(t(lang, "link_removed" if existed else "link_missing", member=mitglied.mention),
                       allowed_mentions=discord.AllowedMentions.none())

    # ----------------------------------------------------------------- #
    #  Befehle – [p]twitchset (Server-/Bot-Einstellungen)
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="twitchset")
    @commands.admin_or_permissions(manage_guild=True)
    async def twitchset(self, ctx: commands.Context):
        """Einstellungen für Twitch-Live-Meldungen."""

    @twitchset.command(name="channel")
    @commands.guild_only()
    async def ts_channel(self, ctx: commands.Context, kanal: Optional[discord.TextChannel] = None):
        """Standard-Zielkanal setzen (ohne Angabe: entfernen)."""
        lang = await self._lang(ctx.guild)
        if kanal is not None and not self.can_post(kanal):
            return await ctx.send(t(lang, "bad_channel", channel=kanal.mention))
        await self.config.guild(ctx.guild).default_channel.set(kanal.id if kanal else None)
        await ctx.send(t(lang, "default_channel_set", channel=kanal.mention) if kanal
                       else t(lang, "default_channel_cleared"))

    @twitchset.command(name="message")
    @commands.guild_only()
    async def ts_message(self, ctx: commands.Context, *, text: Optional[str] = None):
        """Standardtext setzen (ohne Text: zurücksetzen).

        Platzhalter: {streamer} {title} {game} {url} {ping}
        """
        lang = await self._lang(ctx.guild)
        if text and len(text) > LIMIT_TEMPLATE:
            return await ctx.send(t(lang, "message_too_long", max=LIMIT_TEMPLATE))
        await self.config.guild(ctx.guild).default_message.set((text or "").strip())
        await ctx.send(t(lang, "message_set" if text else "message_reset"))

    @twitchset.command(name="endaction")
    @commands.guild_only()
    async def ts_endaction(self, ctx: commands.Context, aktion: str):
        """Bei Stream-Ende: edit (Nachricht „war live · Dauer“) oder delete (löschen)."""
        lang = await self._lang(ctx.guild)
        aktion = aktion.lower().strip()
        if aktion not in END_ACTIONS:
            return await ctx.send(t(lang, "endaction_bad"))
        await self.config.guild(ctx.guild).end_action.set(aktion)
        await ctx.send(t(lang, "endaction_set", action=t(lang, f"endaction_{aktion}")))

    @twitchset.command(name="liverole")
    @commands.guild_only()
    async def ts_liverole(self, ctx: commands.Context, rolle: Optional[discord.Role] = None):
        """Live-Rolle für verknüpfte Mitglieder setzen (ohne Angabe: aus)."""
        lang = await self._lang(ctx.guild)
        if rolle is None:
            await self.config.guild(ctx.guild).live_role.set(None)
            return await ctx.send(t(lang, "liverole_cleared"))
        if not await self.may_grant(ctx.author, rolle):
            return await ctx.send(t(lang, "liverole_forbidden"))
        if not self.role_manageable(ctx.guild, rolle):
            return await ctx.send(t(lang, "liverole_hierarchy", role=rolle.mention),
                                  allowed_mentions=discord.AllowedMentions.none())
        await self.config.guild(ctx.guild).live_role.set(rolle.id)
        await ctx.send(t(lang, "liverole_set", role=rolle.mention), allowed_mentions=discord.AllowedMentions.none())

    @twitchset.command(name="language")
    @commands.guild_only()
    async def ts_language(self, ctx: commands.Context, code: str):
        """Sprache der Meldungen und Antworten (de, en)."""
        code = code.lower()
        if code not in LANGUAGES:
            return await ctx.send(t(await self._lang(ctx.guild), "lang_unknown", code=code[:10],
                                    langs=", ".join(LANGUAGES)))
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", language=LANGUAGES[code]))

    @twitchset.command(name="show", aliases=["settings"])
    @commands.guild_only()
    async def ts_show(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen (ohne Secret)."""
        lang = await self._lang(ctx.guild)
        conf = await self.config.guild(ctx.guild).all()
        ch = ctx.guild.get_channel(conf.get("default_channel") or 0)
        role = ctx.guild.get_role(conf.get("live_role") or 0)
        creds = await self.has_credentials()
        yes, no = t(lang, "yes"), t(lang, "no")
        if lang == "en":
            lines = [
                f"Language: {LANGUAGES.get(conf.get('language'), conf.get('language'))}",
                f"Default channel: {ch.mention if ch else '—'}",
                f"Default text: {'custom' if conf.get('default_message') else 'standard'}",
                f"On stream end: {t(lang, 'endaction_' + (conf.get('end_action') or 'edit'))}",
                f"Live role: {role.mention if role else '—'} · links: {len(conf.get('links') or {})}",
                f"Streamers: {len(conf.get('channels') or {})} · live now: {len(conf.get('state') or {})}",
                f"Twitch credentials set: {yes if creds else no} · interval: {await self._interval()} s",
            ]
        else:
            lines = [
                f"Sprache: {LANGUAGES.get(conf.get('language'), conf.get('language'))}",
                f"Standardkanal: {ch.mention if ch else '—'}",
                f"Standardtext: {'eigener' if conf.get('default_message') else 'Standard'}",
                f"Bei Stream-Ende: {t(lang, 'endaction_' + (conf.get('end_action') or 'edit'))}",
                f"Live-Rolle: {role.mention if role else '—'} · Verknüpfungen: {len(conf.get('links') or {})}",
                f"Streamer: {len(conf.get('channels') or {})} · gerade live: {len(conf.get('state') or {})}",
                f"Twitch-Zugangsdaten gesetzt: {yes if creds else no} · Intervall: {await self._interval()} s",
            ]
        text = t(lang, "settings_title") + "\n" + "\n".join(lines)
        if not creds:
            text += "\n" + t(lang, "no_creds_hint", prefix=ctx.clean_prefix)
        await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())

    @twitchset.command(name="creds", aliases=["credentials"], with_app_command=False)
    @commands.is_owner()
    async def ts_creds(self, ctx: commands.Context, client_id: str, client_secret: str):
        """Twitch-Client-ID und -Secret setzen (nur Bot-Owner, Nachricht wird gelöscht).

        App anlegen: https://dev.twitch.tv/console/apps – OAuth-Redirect http://localhost genügt,
        Kategorie „Chat Bot“ oder „Other“, Client-Typ „Confidential“.
        """
        deleted = True
        if ctx.guild is not None:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                deleted = False
        async with ctx.typing():
            result = await self.set_credentials(client_id, client_secret)
        lang = await self._lang(ctx.guild)
        key = {"ok": "creds_ok", "bad": "creds_bad"}.get(result, "creds_error")
        text = t(lang, "creds_set", result=t(lang, key))
        if not deleted:
            text += "\n" + t(lang, "creds_not_deleted")
        await ctx.send(text)

    @twitchset.command(name="clearcreds", with_app_command=False)
    @commands.is_owner()
    async def ts_clearcreds(self, ctx: commands.Context):
        """Twitch-Zugangsdaten löschen (nur Bot-Owner)."""
        await self.config.client_id.set("")
        await self.config.client_secret.set("")
        self.api.reset_token()
        self.status.update(state="no_credentials", error="")
        await ctx.send(t(await self._lang(ctx.guild), "creds_cleared"))

    @twitchset.command(name="interval")
    @commands.is_owner()
    async def ts_interval(self, ctx: commands.Context, sekunden: int):
        """Abfrage-Intervall botweit setzen (60–600 Sekunden, nur Bot-Owner)."""
        lang = await self._lang(ctx.guild)
        if not POLL_MIN <= sekunden <= POLL_MAX:
            return await ctx.send(t(lang, "interval_bad", min=POLL_MIN, max=POLL_MAX))
        await self.config.poll_interval.set(sekunden)
        self._kick()
        await ctx.send(t(lang, "interval_set", sec=sekunden))
