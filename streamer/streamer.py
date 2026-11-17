"""Ein aktives Streamboard für Twitch und YouTube, mit gemeinsamem Titelfilter."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import discord
from redbot.core import Config, commands

from .providers import ProviderError, StreamAPI
from .presence import parse_activity, source_from_stream
from .presence_refresh import PresenceRefresh
from .notifications import reconcile as reconcile_notifications

log = logging.getLogger("red.red-cogs.streamer")
PROVIDERS = ("twitch", "youtube")
MAX_SOURCES = 100
POLL_SECONDS = 60
RETRY_SECONDS = 60


def matches_title(title, title_filter):
    return not str(title_filter or "").strip() or str(title_filter).strip().casefold() in str(title or "").casefold()


def _cap(value, limit):
    return str(value or "")[:limit]


def _timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _image_url(value, now=None):
    value = str(value or "").replace("{width}", "1280").replace("{height}", "720")
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or len(value) > 2000:
            return None
        if now is not None and parsed.hostname == "static-cdn.jtvnw.net" and parsed.path.startswith("/previews-ttv/"):
            query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "streamer_preview"]
            query.append(("streamer_preview", str(int(now // 300))))
            return urlunsplit(parsed._replace(query=urlencode(query)))
        return value
    except ValueError:
        return None


class Streamer(commands.Cog):
    """Zeigt ausschließlich aktive, zum Titelfilter passende Streams an."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=928461730552, force_registration=True)
        self.config.register_global(twitch_client_id="", twitch_client_secret="", youtube_api_key="", youtube_state={})
        self.config.register_guild(enabled=True, channel_id=None, title_filter="", watched_role_id=None,
                                   presence_refresh_enabled=False, mention_everyone=False, notification_state={},
                                   sources={}, state={}, last_error="")
        self.api = StreamAPI(self._credentials, clock=lambda: self._now(),
                             youtube_state_get=self.config.youtube_state,
                             youtube_state_set=self.config.youtube_state.set)
        self.status = {p: {"state": "idle", "error": "", "last_ok": None} for p in PROVIDERS}
        self._poll_lock = asyncio.Lock()
        self._locks = {}
        self._wake = asyncio.Event()
        self._task = None
        self._poll_tasks = set()
        self._unloading = False
        self._presence_connected = True
        self._disconnected_shards = set()
        self.presence_refresh = PresenceRefresh(bot, clock=lambda: self._now())

    def _now(self):
        return time.time()

    def _lock(self, guild):
        return self._locks.setdefault(guild.id, asyncio.Lock())

    async def _credentials(self):
        return {key: await getattr(self.config, key)() for key in
                ("twitch_client_id", "twitch_client_secret", "youtube_api_key")}

    async def set_credentials(self, **values):
        keys = {"twitch_client_id", "twitch_client_secret", "youtube_api_key"}
        if set(values) - keys:
            raise ValueError("Unbekannte Zugangseinstellung.")
        cleaned = {k: str(v).strip() for k, v in values.items() if v is not None}
        if any(len(v) > 512 or any(c.isspace() for c in v) for v in cleaned.values()):
            raise ValueError("Zugangsdaten sind ungültig. Bitte ohne Leerzeichen eintragen.")
        async with self._poll_lock:
            for key, value in cleaned.items():
                await getattr(self.config, key).set(value)
            self.api.reset_credentials()
        self._wake.set()

    @staticmethod
    def can_post(channel):
        if not isinstance(channel, discord.TextChannel):
            return False
        me = getattr(channel.guild, "me", None)
        if me is None:
            return False
        perms = channel.permissions_for(me)
        return bool(perms.view_channel and perms.send_messages and perms.embed_links and perms.read_message_history)

    def _target(self, guild, conf):
        cid = conf.get("channel_id")
        channel = guild.get_channel(int(cid)) if cid else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def configure(self, guild, *, channel_id=None, title_filter=None, enabled=None, watched_role_id=None,
                        mention_everyone=None):
        if title_filter is not None and len(str(title_filter).strip()) > 100:
            raise ValueError("Der Titelfilter darf höchstens 100 Zeichen enthalten.")
        if channel_id is not None:
            try:
                channel = guild.get_channel_or_thread(int(channel_id))
            except (TypeError, ValueError):
                channel = None
            if not self.can_post(channel):
                raise ValueError("Bitte einen Kanal dieses Servers wählen, in dem der Bot ansehen, senden, "
                                 "Links einbetten und den Nachrichtenverlauf lesen darf.")
        role_id = None
        if watched_role_id is not None:
            try:
                role_id = int(watched_role_id)
            except (TypeError, ValueError):
                raise ValueError("Bitte eine gültige Rolle dieses Servers auswählen.") from None
            if role_id:
                role = guild.get_role(role_id)
                if role is None or role.is_default():
                    raise ValueError("Bitte eine Rolle dieses Servers wählen; @everyone kann nicht beobachtet werden.")
        async with self._lock(guild):
            conf = self.config.guild(guild)
            current = await conf.all()
            effective_mention = current.get("mention_everyone", False) if mention_everyone is None else bool(mention_everyone)
            if effective_mention:
                target = guild.get_channel(int(channel_id or current.get("channel_id") or 0))
                if (not self.can_post(target)
                        or not target.permissions_for(guild.me).mention_everyone):
                    raise ValueError("Für @everyone muss der Bot im Zielkanal das Recht „@everyone, @here und alle Rollen erwähnen“ haben.")
            if channel_id is not None:
                await conf.channel_id.set(int(channel_id))
            if title_filter is not None:
                await conf.title_filter.set(str(title_filter).strip())
            if enabled is not None:
                await conf.enabled.set(bool(enabled))
            if mention_everyone is not None:
                await conf.mention_everyone.set(bool(mention_everyone))
            if watched_role_id is not None:
                changed = await conf.watched_role_id() != (role_id or None)
                await conf.watched_role_id.set(role_id or None)
                if changed:
                    self.presence_refresh.invalidate(guild)
        await self.cleanup_guild(guild)
        self._wake.set()

    def role_watch_status(self, guild, conf=None):
        """Gateway-Daten nur lesen; keine Discord-Mitgliederdaten dauerhaft speichern."""
        conf = conf or {}
        role_id = conf.get("watched_role_id")
        status = {"role_id": role_id, "role_name": "", "members": 0, "live": 0,
                  "ready": True, "warning": "", "sources": {}, "streams": {}}
        if not role_id:
            return status
        role = guild.get_role(int(role_id))
        if role is None:
            status["warning"] = "Die beobachtete Rolle existiert nicht mehr. Bitte eine andere Rolle auswählen."
            return status
        status["role_name"] = role.name
        members = [m for m in role.members if not getattr(m, "bot", False)]
        status["members"] = len(members)
        intents = getattr(self.bot, "intents", None)
        if not getattr(intents, "presences", False) or not getattr(intents, "members", False):
            status.update(ready=False, warning="Die Rollenbeobachtung benötigt Presence Intent und Server Members Intent. "
                          "Beide im Discord Developer Portal und beim Bot-Start aktivieren; danach den Bot neu starten.")
            return status
        if (not self._presence_connected or not getattr(self.bot, "is_ready", lambda: True)()
                or getattr(guild, "shard_id", None) in self._disconnected_shards
                or getattr(guild, "unavailable", False)):
            status.update(ready=False, warning="Discord ist noch nicht verbunden. Vorhandene Rollen-Ankündigungen bleiben bis zur nächsten sicheren Prüfung erhalten.")
            return status
        if not getattr(guild, "chunked", True):
            status.update(ready=False, warning="Die Mitgliederliste wird noch geladen. Rollenstreams werden geprüft, sobald sie vollständig verfügbar ist.")
            return status
        warning = self.presence_refresh.status(guild)
        if conf.get("presence_refresh_enabled") and not self.presence_refresh.enabled(guild):
            warning = "Der Discord-Status wird beim nächsten Prüflauf neu geladen. Vorhandene Meldungen bleiben bis dahin erhalten."
        if warning:
            status.update(ready=False, warning=warning)
            return status
        for member in members:
            for activity in self.presence_refresh.activities(member):
                stream = parse_activity(activity)
                if stream is None:
                    continue
                key = stream["source_key"]
                previous = status["streams"].get(key)
                if previous and (matches_title(previous[0]["title"], conf.get("title_filter"))
                                 or not matches_title(stream["title"], conf.get("title_filter"))):
                    continue
                status["sources"][key] = source_from_stream(stream)
                status["streams"][key] = [stream]
        status["live"] = len(status["sources"])
        return status

    def member_diagnostics(self, guild, member, conf, *, watch_status=None):
        """Nur aktuelle Diagnosewerte erzeugen; keine Mitgliederdaten in Config/Logs schreiben."""
        data = {"member_name": _cap(getattr(member, "display_name", "Nicht im Mitgliedercache"), 100),
                "has_role": False, "activity_types": [], "streaming": 0, "accepted": 0,
                "filter_matches": 0, "title": "", "url": "", "reason": "", "hint": ""}
        role_id = conf.get("watched_role_id")
        if member is None or getattr(getattr(member, "guild", None), "id", None) != guild.id:
            data.update(reason="Mitglied nicht auf diesem Server gefunden.", hint="Ein Mitglied dieses Servers auswählen.")
            return data
        data["has_role"] = any(r.id == role_id for r in member.roles)
        labels = {discord.ActivityType.playing: "Spielt", discord.ActivityType.streaming: "Streamt",
                  discord.ActivityType.listening: "Hört zu", discord.ActivityType.watching: "Schaut",
                  discord.ActivityType.custom: "Benutzerstatus", discord.ActivityType.competing: "Wettbewerb"}
        activities = self.presence_refresh.activities(member)
        accepted = []
        for activity in activities:
            kind = getattr(activity, "type", None)
            label = labels.get(kind, "Unbekannte Aktivität")
            if label not in data["activity_types"]:
                data["activity_types"].append(label)
            if kind == discord.ActivityType.streaming:
                data["streaming"] += 1
                # Keine beliebigen Aktivitätsinhalte oder ungeprüften URLs anzeigen.
                if isinstance(activity, discord.Streaming):
                    data["title"] = _cap(activity.name, 200)
            stream = parse_activity(activity)
            if stream is not None:
                accepted.append(stream)
        data["accepted"] = len(accepted)
        data["filter_matches"] = sum(matches_title(s["title"], conf.get("title_filter")) for s in accepted)
        if accepted:
            selected = next((s for s in accepted if matches_title(s["title"], conf.get("title_filter"))), accepted[0])
            data.update(title=_cap(selected["title"], 200), url=selected["url"])
        if not role_id:
            data.update(reason="Keine beobachtete Rolle eingestellt.", hint="Unter Einstellungen eine Streamer-Rolle auswählen.")
        elif not data["has_role"]:
            data.update(reason="Mitglied hat die beobachtete Rolle nicht.", hint="Die gespeicherte Rolle und ihre Mitgliedschaft prüfen.")
        elif getattr(member, "bot", False):
            data.update(reason="Bot-Mitglieder werden nicht angekündigt.")
        else:
            status = self.role_watch_status(guild, conf) if watch_status is None else watch_status
            if not status["ready"]:
                data.update(reason="Discord-Daten noch nicht sicher verfügbar.", hint=status["warning"])
            elif not activities:
                data.update(reason="Keine Aktivität empfangen.", hint="Discord-Status neu laden. Bleibt dies leer, übermittelt Discord dem Bot keine öffentliche Aktivität dieses Mitglieds.")
            elif not data["streaming"]:
                data.update(reason="Keine Streamingaktivität empfangen.", hint="Discord meldet dem Bot nur die genannten Aktivitätstypen. Für diesen Modus ist „Streamt …“ mit öffentlichem Stream-Link nötig.")
            elif not accepted:
                data.update(reason="Streamingaktivität ohne unterstützten Stream-Link.", hint="Discord muss einen öffentlichen Twitch- oder YouTube-Stream-Link mitsenden. Beliebige oder fehlende URLs werden nicht angekündigt.")
            elif not data["filter_matches"]:
                data.update(reason="Der empfangene Titel passt nicht zum Titelfilter.", hint="Maßgeblich ist der hier empfangene Discord-Titel, nicht allein der Titel auf der Streaming-Webseite.")
            elif not conf.get("enabled"):
                data.update(reason="Stream-Ankündigungen sind ausgeschaltet.", hint="Unter Einstellungen aktivieren.")
            elif not self.can_post(self._target(guild, conf)):
                data.update(reason="Zielkanal fehlt oder Bot-Rechte reichen nicht aus.", hint="Zielkanal, Senderecht, Links einbetten und Nachrichtenverlauf lesen prüfen.")
            else:
                data.update(reason="Passender Stream empfangen.", hint="„Jetzt prüfen“ aktualisiert die Ankündigung. Eventuelle Discord-Sendefehler stehen über der Übersicht.")
        return data

    async def refresh_role_presences(self, guild):
        """Aktivitätsdaten über das Discord-Gateway gezielt neu anfordern."""
        if self._unloading:
            return {"ok": False, "message": "Streamer wird gerade neu geladen."}
        task = asyncio.current_task()
        self._poll_tasks.add(task)
        try:
            ticket = self.presence_refresh.checkpoint(guild)
            conf = await self.config.guild(guild).all()
            role = guild.get_role(int(conf.get("watched_role_id") or 0))
            if role is None:
                return {"ok": False, "message": "Bitte zuerst eine gültige Streamer-Rolle einstellen."}
            if (not self._presence_connected or getattr(guild, "shard_id", None) in self._disconnected_shards
                    or await self.bot.cog_disabled_in_guild(self, guild)):
                return {"ok": False, "message": "Die Discord-Verbindung ist nicht bereit oder der Cog ist auf diesem Server deaktiviert."}
            if self._unloading:
                return {"ok": False, "message": "Streamer wird gerade neu geladen."}
            # Nur die Betriebsart sichern, niemals Mitgliederdaten oder Aktivitäten.
            await self.config.guild(guild).presence_refresh_enabled.set(True)
            if self._unloading:
                return {"ok": False, "message": "Streamer wird gerade neu geladen."}
            result = await self.presence_refresh.refresh(guild, role, force=True, checkpoint=ticket)
            if result["ok"]:
                self._wake.set()
            return result
        finally:
            self._poll_tasks.discard(task)

    @staticmethod
    def _streaming_signature(member, activities=None):
        return sorted((str(a.name or ""), str(a.url or "")) for a in
                      (getattr(member, "activities", ()) if activities is None else activities)
                      if isinstance(a, discord.Streaming))

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if self._unloading:
            return
        before_signature = self._streaming_signature(before, self.presence_refresh.activities(before))
        self.presence_refresh.observe(after)
        if before_signature == self._streaming_signature(after):
            return
        role_id = await self.config.guild(after.guild).watched_role_id()
        if role_id and any(r.id == role_id for m in (before, after) for r in m.roles):
            self._wake.set()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        role_id = await self.config.guild(after.guild).watched_role_id()
        if role_id and ({r.id for r in before.roles} ^ {r.id for r in after.roles}) & {role_id}:
            if not any(r.id == role_id for r in after.roles):
                self.presence_refresh.remove(after)
            self._wake.set()

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        self.presence_refresh.remove(member)
        role_id = await self.config.guild(member.guild).watched_role_id()
        if role_id and any(r.id == role_id for r in member.roles):
            self._wake.set()

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        if await self.config.guild(role.guild).watched_role_id() == role.id:
            self.presence_refresh.invalidate(role.guild)
            self._wake.set()

    @commands.Cog.listener()
    async def on_disconnect(self):
        self._presence_connected = False

    @commands.Cog.listener()
    async def on_resumed(self):
        self._presence_connected = True
        self._wake.set()

    @commands.Cog.listener()
    async def on_ready(self):
        self._presence_connected = True
        self._disconnected_shards.clear()
        self._wake.set()

    @commands.Cog.listener()
    async def on_shard_disconnect(self, shard_id):
        self._disconnected_shards.add(shard_id)

    @commands.Cog.listener()
    async def on_shard_resumed(self, shard_id):
        self._disconnected_shards.discard(shard_id)
        self._presence_connected = True
        self._wake.set()

    @commands.Cog.listener()
    async def on_shard_ready(self, shard_id):
        self._disconnected_shards.discard(shard_id)
        self._wake.set()

    async def add_source(self, guild, provider, raw):
        provider = str(provider).lower().strip()
        if provider not in PROVIDERS:
            raise ValueError("Bitte twitch oder youtube als Plattform wählen.")
        if len(str(raw)) > 300:
            raise ValueError("Die Kanaladresse ist zu lang.")
        # Netzwerkauflösung außerhalb des Guild-Locks; danach das Quellenlimit frisch prüfen.
        source = dict(await self.api.resolve(provider, str(raw).strip()))
        source["enabled"] = True
        async with self._lock(guild):
            async with self.config.guild(guild).sources() as sources:
                if source["key"] not in sources and len(sources) >= MAX_SOURCES:
                    raise ValueError(f"Es können höchstens {MAX_SOURCES} Kanäle beobachtet werden.")
                sources[source["key"]] = source
        self._wake.set()
        return source

    async def remove_source(self, guild, key):
        async with self._lock(guild):
            async with self.config.guild(guild).sources() as sources:
                if key not in sources:
                    raise ValueError("Dieser Kanal wird nicht beobachtet.")
                del sources[key]
        await self.cleanup_guild(guild)
        self._wake.set()

    async def toggle_source(self, guild, key):
        async with self._lock(guild):
            async with self.config.guild(guild).sources() as sources:
                if key not in sources:
                    raise ValueError("Dieser Kanal wird nicht beobachtet.")
                sources[key]["enabled"] = not sources[key].get("enabled", True)
        await self.cleanup_guild(guild)
        self._wake.set()

    async def cog_load(self):
        self._unloading = False
        wc = self.bot.get_cog("WebCore")
        if wc is not None:
            self._register_dashboard(wc)
        self._task = asyncio.create_task(self._runner())

    async def cog_unload(self):
        self._unloading = True
        running = set(self._poll_tasks)
        if self._task is not None:
            running.add(self._task)
        running.discard(asyncio.current_task())
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        wc = self.bot.get_cog("WebCore")
        if wc is not None:
            wc.unregister_owner(self)
        await self.api.close()
        self.presence_refresh.clear()

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        if not self._unloading:
            self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        extra = {"operate_forms": {"check", "toggle", "presence_refresh"}} if hasattr(webcore, "OPERATE") else {}
        webcore.register_page(owner=self, slug="streamer", name="Streamer", icon="bi-broadcast",
                              handler=self.dashboard_page, **extra)

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler
        return await dashboard_handler(self, request)

    async def _runner(self):
        await self.bot.wait_until_red_ready()
        while not self._unloading:
            self._wake.clear()
            try:
                await self.poll_once()
            except Exception as exc:  # Ein Serverfehler darf die Überwachung nicht beenden.
                log.warning("Stream-Abfrage fehlgeschlagen (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(self._wake.wait(), POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def poll_once(self):
        task = asyncio.current_task()
        self._poll_tasks.add(task)
        try:
            await self._poll_once()
        finally:
            self._poll_tasks.discard(task)

    async def _poll_once(self):
        """Nur erfolgreiche vollständige Provider-Snapshots dürfen Offline-Löschungen auslösen."""
        async with self._poll_lock:
            if self._unloading:
                return
            watched = {p: {} for p in PROVIDERS}
            known = {p: {} for p in PROVIDERS}
            for guild in list(self.bot.guilds):
                presence_ticket = self.presence_refresh.checkpoint(guild)
                conf = await self.config.guild(guild).all()
                if not conf.get("enabled") or await self.bot.cog_disabled_in_guild(self, guild):
                    continue
                if (conf.get("watched_role_id") and conf.get("presence_refresh_enabled")
                        and self._presence_connected and getattr(guild, "shard_id", None) not in self._disconnected_shards):
                    role = guild.get_role(int(conf["watched_role_id"]))
                    if role is not None:
                        await self.presence_refresh.refresh(guild, role, force=not self.presence_refresh.enabled(guild),
                                                            checkpoint=presence_ticket)
                for key, source in conf["sources"].items():
                    provider = source.get("provider")
                    if provider in watched and source.get("enabled", True):
                        watched[provider][key] = source
                for state_key, record in conf["state"].items():
                    key = record.get("source_key") or state_key.rsplit("/", 1)[0]
                    provider = record.get("provider")
                    if provider in known and key in watched[provider]:
                        stream_id = (record.get("stream") or {}).get("id")
                        if stream_id:
                            known[provider].setdefault(key, []).append(stream_id)

            async def fetch(provider):
                if not watched[provider]:
                    self.status[provider].update(state="idle", error="")
                    return provider, {}
                try:
                    snapshot = await self.api.streams(provider, watched[provider], known=known[provider])
                    if not isinstance(snapshot, dict) or set(watched[provider]) - set(snapshot):
                        raise ProviderError("Die Plattform hat einen unvollständigen Status geliefert.")
                    for key, streams in snapshot.items():
                        if key not in watched[provider] or not isinstance(streams, list):
                            raise ProviderError("Die Plattform hat einen ungültigen Status geliefert.")
                        for stream in streams:
                            if (not isinstance(stream, dict) or not stream.get("id")
                                    or stream.get("source_key") != key or stream.get("provider") != provider):
                                raise ProviderError("Die Plattform hat ungültige Streamdaten geliefert.")
                    self.status[provider].update(state="ok", error="", last_ok=self._now())
                    return provider, snapshot
                except ProviderError as exc:
                    self.status[provider].update(state="error", error=str(exc))
                except Exception as exc:
                    self.status[provider].update(state="error", error="Streamstatus vorübergehend nicht erreichbar.")
                    log.warning("%s-Abfrage fehlgeschlagen (%s)", provider, type(exc).__name__)
                return provider, None

            snapshots = dict(await asyncio.gather(*(fetch(p) for p in PROVIDERS)))
            if self._unloading:
                return
            for guild in list(self.bot.guilds):
                try:
                    async with self._lock(guild):
                        await self._sync_guild(guild, snapshots)
                except Exception as exc:
                    log.warning("Streamer für Server %s fehlgeschlagen (%s)", guild.id, type(exc).__name__)
                    await self.config.guild(guild).last_error.set("Die Streamübersicht konnte nicht vollständig aktualisiert werden.")

    async def cleanup_guild(self, guild):
        """Explizite Einstellungen sofort anwenden; API-Ausfälle niemals als Offline deuten."""
        async with self._lock(guild):
            await self._sync_guild(guild, {p: None for p in PROVIDERS})

    async def _sync_guild(self, guild, snapshots):
        if self._unloading:
            return
        gc = self.config.guild(guild)
        conf = await gc.all()
        state = conf["state"]
        # WebCore entfernt beim Export Felder mit Namen wie *_key. Die Quelle
        # ist zusätzlich im stabilen Dictionary-Schlüssel enthalten.
        for key, record in state.items():
            record.setdefault("source_key", key.rsplit("/", 1)[0])
            record["stream"].setdefault("source_key", record["source_key"])
        sources = dict(conf["sources"])
        role_status = self.role_watch_status(guild, conf)
        sources.update(role_status["sources"])
        snapshots = dict(snapshots, discord=role_status["streams"] if role_status["ready"] else None)
        notices = reconcile_notifications(conf, snapshots, role_status, self._now())
        await gc.notification_state.set(notices)

        async def persist():
            # Reservierungen vor dem HTTP-Post sichern: unklare Antworten dürfen keinen zweiten Ping auslösen.
            await gc.notification_state.set(notices)
            await gc.state.set(state)
        # Unbekannte Gateway-Daten behalten, solange dieselbe Rolle eingerichtet ist.
        for record in state.values():
            if (record["source_key"].startswith("discord:") and not role_status["ready"]
                    and record.get("watch_role_id") == conf.get("watched_role_id")):
                sources.setdefault(record["source_key"], {"enabled": True})
        active = bool(conf["enabled"]) and not await self.bot.cog_disabled_in_guild(self, guild)
        target = self._target(guild, conf)
        desired = {}
        for provider, snapshot in snapshots.items():
            if snapshot is None or not active or target is None:
                continue
            for source_key, streams in snapshot.items():
                source = sources.get(source_key)
                if not source or not source.get("enabled", True):
                    continue
                for stream in streams:
                    if matches_title(stream.get("title"), conf["title_filter"]):
                        desired[f"{source_key}/{stream['id']}"] = stream

        # Dieselbe öffentliche Stream-URL nur einmal ankündigen: bestehende Meldungen
        # bevorzugen, unabhängig davon, ob sie über Rolle oder Plattform-API gefunden wurden.
        def origin(record):
            return "discord" if record["source_key"].startswith("discord:") else record["provider"]

        def api_source_for(stream):
            key = stream["source_key"]
            if key.startswith("discord:youtube:"):
                identifier = key[len("discord:youtube:"):]
                canonical = "youtube:" + identifier
                if canonical in conf["sources"]:
                    return canonical
                if identifier.startswith("@"):
                    for api_key, source in conf["sources"].items():
                        if source.get("provider") == "youtube" and identifier in (source.get("handles") or []):
                            return api_key
            return key

        unknown_records = [r for r in state.values()
                           if snapshots.get(origin(r)) is None and r["source_key"] in sources
                           and sources[r["source_key"]].get("enabled", True)
                           and active and target is not None and r.get("channel_id") == target.id
                           and matches_title(r["stream"].get("title"), conf["title_filter"])]
        unknown_urls = {r["stream"].get("url") for r in unknown_records}
        api_active = {s["source_key"] for s in desired.values() if not s["source_key"].startswith("discord:")}
        api_active.update(r["source_key"] for r in unknown_records if origin(r) != "discord")
        desired = {key: stream for key, stream in desired.items()
                   if not (stream["source_key"].startswith("discord:")
                           and api_source_for(stream) in api_active)}
        by_url = {}
        for key, stream in desired.items():
            url = stream["url"]
            if url in unknown_urls and key not in state:
                continue
            previous = by_url.get(url)
            if previous is None or (key in state and state[key].get("message_id")
                                     and not state.get(previous, {}).get("message_id")):
                by_url[url] = key
        desired = {key: desired[key] for key in by_url.values()}

        errors = []
        blocked_sources = set()
        blocked_urls = set()
        for key, record in list(state.items()):
            source_key = record["source_key"]
            source = sources.get(source_key)
            explicit_remove = (not active or not source or not source.get("enabled", True)
                               or target is None or record.get("channel_id") != target.id
                               or not matches_title(record["stream"].get("title"), conf["title_filter"])
                               or (source_key.startswith("discord:")
                                   and record.get("watch_role_id") != conf.get("watched_role_id")))
            authoritative = snapshots.get(origin(record)) is not None
            if explicit_remove or (authoritative and key not in desired):
                if await self._delete_message(guild, record):
                    state.pop(key, None)
                else:
                    errors.append(record["error"])
                    blocked_sources.add(source_key)
                    blocked_sources.add(api_source_for(record["stream"]))
                    blocked_urls.add(record["stream"].get("url"))
                await gc.state.set(state)

        for key, stream in desired.items():
            if (stream["source_key"] in blocked_sources or api_source_for(stream) in blocked_sources
                    or stream["url"] in blocked_urls):
                continue
            record = state.get(key)
            fresh = record is None
            notice = notices[stream["url"]]
            if stream["source_key"].startswith("discord:"):
                stream = dict(stream, started_at=datetime.fromtimestamp(notice["first_seen"], timezone.utc).isoformat())
            if fresh:
                record = {"source_key": stream["source_key"], "provider": stream["provider"],
                          "stream": dict(stream), "message_id": None, "channel_id": target.id,
                          "last_update": 0, "error": "", "pending": True, "pending_since": self._now(),
                          "first_seen": notice["first_seen"]}
                state[key] = record
                # Eine Absicht vor dem Senden sichern; bei Abbruch kann die Meldung wiedergefunden werden.
                await gc.state.set(state)
            if stream["source_key"].startswith("discord:"):
                record["watch_role_id"] = conf.get("watched_role_id")
            await self._ensure_message(guild, target, record, stream, fresh=fresh,
                                       persist=persist, notice=notice, mention_everyone=conf.get("mention_everyone", False))
            if record.get("error"):
                errors.append(record["error"])
            await persist()
        # Auch Fehler bei weiter unbekanntem Plattformstatus sichtbar halten.
        errors.extend(r["error"] for r in state.values() if r.get("error") and r["error"] not in errors)
        await gc.last_error.set(" · ".join(dict.fromkeys(errors))[:1000])

    @staticmethod
    def _footer(record):
        return "Streamer · " + ("Twitch" if record["provider"] == "twitch" else "YouTube")

    def _owned(self, guild, message, record):
        bot_id = getattr(self.bot.user, "id", None)
        if getattr(getattr(message, "author", None), "id", None) != bot_id:
            return False
        return any(e.url == record["stream"].get("url") and e.footer.text == self._footer(record)
                   for e in message.embeds)

    async def _recover(self, guild, channel, record):
        """Eine eventuell trotz Timeout gesendete eigene Meldung zuerst übernehmen."""
        after = datetime.fromtimestamp(float(record.get("pending_since") or self._now()) - 30, timezone.utc)
        count = 0
        async for message in channel.history(limit=200, after=after, oldest_first=True):
            count += 1
            if self._owned(guild, message, record):
                expected = _timestamp(record["stream"].get("started_at"))
                if expected is None or any(e.timestamp == expected for e in message.embeds):
                    return message
        if count >= 200:
            raise ValueError("Nachrichtenverlauf zu groß; eine möglicherweise gesendete Meldung konnte nicht sicher zugeordnet werden.")
        return None

    async def _delete_message(self, guild, record):
        channel = guild.get_channel_or_thread(int(record["channel_id"]))
        if channel is None:
            return True  # Der gespeicherte Kanal existiert nicht mehr.
        try:
            if record.get("message_id"):
                message = await channel.fetch_message(int(record["message_id"]))
                if not self._owned(guild, message, record):
                    # Eine fremde Nachricht niemals bearbeiten/löschen, auch bei beschädigter Config.
                    return True
            elif record.get("pending"):
                message = await self._recover(guild, channel, record)
                if message is None:
                    return True
                record["message_id"] = message.id
            else:
                return True
            await message.delete()
            return True
        except discord.NotFound as exc:
            if exc.code in (10003, 10008):
                return True
            record["error"] = "Die alte Ankündigung konnte nicht sicher gefunden werden."
        except discord.HTTPException as exc:
            record["error"] = f"Ankündigung konnte nicht gelöscht werden (Discord HTTP {exc.status}); wird erneut versucht."
        except ValueError as exc:
            record["error"] = str(exc)
        return False

    def _embed(self, stream, record):
        title = _cap(stream.get("title") or "Live-Stream", 256)
        embed = discord.Embed(title=title, url=stream["url"], color=0x9146FF if record["provider"] == "twitch" else 0xFF0000,
                              timestamp=_timestamp(stream.get("started_at")))
        embed.set_author(name=_cap(stream.get("name") or "Streamer", 256))
        if stream.get("game"):
            embed.add_field(name="Spiel", value=discord.utils.escape_markdown(_cap(stream["game"], 1000)))
        if stream.get("viewers") is not None:
            embed.add_field(name="Zuschauer", value=str(max(0, int(stream["viewers"]))))
        image = _image_url(stream.get("thumbnail"), self._now())
        if image:
            embed.set_image(url=image)
        embed.set_footer(text=self._footer(record))
        return embed

    async def _ensure_message(self, guild, channel, record, stream, *, fresh=False, persist=None,
                              notice=None, mention_everyone=False):
        now = self._now()
        if float(record.get("retry_at") or 0) > now:
            return
        attempted_send = False
        notice = notice if notice is not None else {"announced": True}
        previous_record = bool(record.get("announced") or record.get("message_id"))
        previous_notice = bool(notice.get("announced"))
        record["announced"] = previous_record
        try:
            message = None
            if record.get("message_id"):
                try:
                    message = await channel.fetch_message(int(record["message_id"]))
                    if not self._owned(guild, message, record):
                        message = None
                        record["message_id"] = None
                        record["pending"] = False
                except discord.NotFound as exc:
                    if exc.code != 10008:
                        raise
                    record["message_id"] = None
                    record["pending"] = False
            elif record.get("pending") and not fresh:
                message = await self._recover(guild, channel, record)
                if message is not None:
                    record["message_id"] = message.id
                    record["announced"] = True
            record["stream"] = dict(stream)
            embed = self._embed(stream, record)
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Zum Stream", style=discord.ButtonStyle.link, url=stream["url"]))
            if message is None:
                if not self.can_post(channel):
                    raise ValueError("Im Ankündigungskanal fehlen Sende-, Embed- oder Leserechte.")
                record["pending"] = True
                record["pending_since"] = record.get("pending_since") or now
                can_mention = bool(channel.permissions_for(guild.me).mention_everyone)
                ping = bool(mention_everyone and can_mention and not record["announced"] and not notice.get("announced"))
                record["message_mention"] = bool(record.get("message_mention") or ping)
                record["mention_skipped"] = bool(mention_everyone and not can_mention and not record["announced"])
                record["announced"] = True
                notice["announced"] = True
                if persist is not None:
                    await persist()
                attempted_send = True
                allowed = (discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False)
                           if ping else discord.AllowedMentions.none())
                message = await channel.send(content="@everyone" if record["message_mention"] else None,
                                             embed=embed, view=view, allowed_mentions=allowed)
                record["message_id"] = message.id
            else:
                notice["announced"] = True
                record["announced"] = True
                await message.edit(content="@everyone" if record.get("message_mention") else None,
                                   embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            warning = ("Die Ankündigung wurde ohne Ping gesendet: Dem Bot fehlt das Recht für @everyone im Zielkanal."
                       if record.get("mention_skipped") and mention_everyone
                       and not channel.permissions_for(guild.me).mention_everyone else "")
            record.update(pending=False, error=warning, retry_at=0, last_update=now)
        except discord.HTTPException as exc:
            record["error"] = f"Ankündigung konnte nicht aktualisiert werden (Discord HTTP {exc.status}); wird erneut versucht."
            record["retry_at"] = now + RETRY_SECONDS
            if attempted_send and exc.status < 500 and not record.get("message_id"):
                record["pending"] = False
                record["announced"] = previous_record
                notice["announced"] = previous_notice
                record["message_mention"] = False
        except ValueError as exc:
            record["error"] = str(exc)
            record["retry_at"] = now + RETRY_SECONDS

    async def red_delete_data_for_user(self, *, requester, user_id):
        # Der Cog speichert keine Zuordnung von Discord-Nutzern zu Stream-Kanälen.
        return

    @commands.hybrid_group(name="streamer", invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def streamer(self, ctx):
        """Aktive Streams einrichten und verwalten."""
        await ctx.send_help()

    @streamer.command(name="setup")
    async def streamer_setup(self, ctx, kanal: discord.TextChannel):
        """Den Kanal für aktive Stream-Ankündigungen festlegen."""
        try:
            await self.configure(ctx.guild, channel_id=kanal.id)
        except ValueError as exc:
            return await ctx.send(str(exc))
        await ctx.send(f"Aktive Streams werden in {kanal.mention} angezeigt. Twitch/YouTube-Zugang im WebCore unter Streamer einrichten.",
                       allowed_mentions=discord.AllowedMentions.none())

    @streamer.command(name="add")
    async def streamer_add(self, ctx, plattform: str, *, kanal: str):
        """Twitch-Namen oder YouTube-Handle/Kanaladresse hinzufügen."""
        try:
            source = await self.add_source(ctx.guild, plattform, kanal)
        except (ValueError, ProviderError) as exc:
            return await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
        await ctx.send(f"Kanal hinzugefügt: **{discord.utils.escape_markdown(source['name'])}** (`{source['key']}`).",
                       allowed_mentions=discord.AllowedMentions.none())

    @streamer.command(name="role")
    async def streamer_role(self, ctx, rolle: discord.Role = None):
        """Mitglieder dieser Rolle über ihren Discord-Streamingstatus beobachten; ohne Rolle ausschalten."""
        try:
            await self.configure(ctx.guild, watched_role_id=rolle.id if rolle else 0)
        except ValueError as exc:
            return await ctx.send(str(exc))
        if rolle is None:
            message = "Rollenbeobachtung ausgeschaltet. Manuell eingetragene Kanäle bleiben aktiv."
        else:
            conf = await self.config.guild(ctx.guild).all()
            status = self.role_watch_status(ctx.guild, conf)
            message = (f"Rollenbeobachtung für {rolle.mention} aktiviert. Mitglieder werden bei Discord-Status „Streamt …“ "
                       "angekündigt; der Titelfilter gilt auch hier.")
            if status["warning"]:
                message += "\n" + status["warning"]
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())

    @streamer.command(name="remove")
    async def streamer_remove(self, ctx, *, kennung: str):
        """Einen Kanal anhand seiner Kennung aus streamer list entfernen."""
        try:
            await self.remove_source(ctx.guild, kennung.strip())
        except ValueError as exc:
            return await ctx.send(str(exc))
        await ctx.send("Kanal entfernt. Seine Ankündigungen werden gelöscht; bei Discord-Fehlern wird dies wiederholt.")

    @streamer.command(name="filter")
    async def streamer_filter(self, ctx, *, text: str = ""):
        """Nur Titel mit diesem Text anzeigen; ohne Text den Filter ausschalten."""
        try:
            await self.configure(ctx.guild, title_filter=text)
        except ValueError as exc:
            return await ctx.send(str(exc))
        await ctx.send(f"Titelfilter: **{discord.utils.escape_markdown(text.strip())}**." if text.strip()
                       else "Titelfilter ausgeschaltet. Alle aktiven Streams der eingetragenen Kanäle werden angezeigt.",
                       allowed_mentions=discord.AllowedMentions.none())

    @streamer.command(name="everyone")
    async def streamer_everyone(self, ctx, schalter: str):
        """Optionalen @everyone-Ping bei neuen Live-Ankündigungen ein- oder ausschalten."""
        value = schalter.casefold().strip()
        if value not in {"an", "aus", "on", "off", "true", "false"}:
            return await ctx.send("Bitte an oder aus angeben.")
        enabled = value in {"an", "on", "true"}
        try:
            await self.configure(ctx.guild, mention_everyone=enabled)
        except ValueError as exc:
            return await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
        await ctx.send("@everyone bei neuen Live-Ankündigungen " + ("eingeschaltet." if enabled else "ausgeschaltet."),
                       allowed_mentions=discord.AllowedMentions.none())

    @streamer.command(name="list")
    async def streamer_list(self, ctx):
        """Eingetragene Kanäle und ihren Status anzeigen."""
        from redbot.core.utils.chat_formatting import pagify
        sources = await self.config.guild(ctx.guild).sources()
        text = "\n".join(f"`{key}` · {'aktiv' if s.get('enabled', True) else 'pausiert'}" for key, s in sorted(sources.items()))
        for page in pagify(text or "Noch keine Stream-Kanäle eingerichtet.", page_length=1900):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @streamer.command(name="check")
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def streamer_check(self, ctx):
        """Aktuelle Streams prüfen (YouTube-Suchintervalle bleiben bestehen)."""
        await ctx.defer()
        await self.poll_once()
        error = await self.config.guild(ctx.guild).last_error()
        platform_errors = [s["error"] for s in self.status.values() if s.get("error")]
        await ctx.send(error or " · ".join(platform_errors) or "Streamübersicht aktualisiert.",
                       allowed_mentions=discord.AllowedMentions.none())

    @streamer.command(name="diagnose")
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def streamer_diagnose(self, ctx, mitglied: discord.Member = None):
        """Discord-Streamingstatus für dich oder ein Mitglied prüfen und gezielt neu laden."""
        private = getattr(ctx, "interaction", None) is not None
        if private:
            await ctx.defer(ephemeral=True)
        member = ctx.guild.get_member((mitglied or ctx.author).id)
        conf = await self.config.guild(ctx.guild).all()
        current = self.member_diagnostics(ctx.guild, member, conf)
        result = {"ok": False, "message": ""}
        if current["has_role"]:
            result = await self.refresh_role_presences(ctx.guild)
        conf = await self.config.guild(ctx.guild).all()
        data = self.member_diagnostics(ctx.guild, member, conf)
        safe = discord.utils.escape_markdown
        lines = [f"**Streamer-Diagnose: {safe(data['member_name'])}**",
                 "Beobachtete Rolle vorhanden: " + ("Ja" if data["has_role"] else "Nein"),
                 "Empfangene Aktivitäten: " + (", ".join(data["activity_types"]) or "Keine"),
                 f"Streamingaktivitäten: {data['streaming']} · Unterstützte Links: {data['accepted']}",
                 "**Ergebnis:** " + safe(data["reason"])]
        if data["title"]:
            lines.append("Empfangener Titel: " + safe(data["title"]))
        if data["url"]:
            lines.append("Stream-Link: <" + data["url"] + ">")
        if data["hint"]:
            lines.append(safe(data["hint"]))
        if result.get("message"):
            lines.append(safe(result["message"]))
        text = "\n".join(lines)[:1900]
        if private:
            await ctx.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            try:
                await ctx.author.send(text, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                await ctx.send("Die Diagnose konnte dir nicht per Direktnachricht gesendet werden. "
                               "Bitte Direktnachrichten für den Bot erlauben oder den Slash-Befehl /streamer diagnose verwenden.")
            else:
                await ctx.send("Die Streamer-Diagnose wurde dir per Direktnachricht geschickt.")

    @commands.group(name="streamerset", invoke_without_command=True)
    @commands.is_owner()
    async def streamerset(self, ctx):
        """Botweiten Plattformzugang setzen; Zugangsdaten ausschließlich per Direktnachricht."""
        await ctx.send_help()

    @streamerset.command(name="twitch")
    @commands.dm_only()
    async def streamerset_twitch(self, ctx, client_id: str, client_secret: str):
        try:
            await self.set_credentials(twitch_client_id=client_id, twitch_client_secret=client_secret)
        except ValueError as exc:
            return await ctx.send(str(exc))
        await ctx.send("Twitch-Zugang gespeichert.")

    @streamerset.command(name="youtube")
    @commands.dm_only()
    async def streamerset_youtube(self, ctx, api_key: str):
        try:
            await self.set_credentials(youtube_api_key=api_key)
        except ValueError as exc:
            return await ctx.send(str(exc))
        await ctx.send("YouTube-Zugang gespeichert.")
