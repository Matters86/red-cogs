"""Ein aktives Streamboard für Twitch und YouTube, mit gemeinsamem Titelfilter."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import discord
from redbot.core import Config, commands

from .providers import ProviderError, StreamAPI

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


def _image_url(value):
    value = str(value or "").replace("{width}", "1280").replace("{height}", "720")
    return value if urlsplit(value).scheme == "https" and len(value) <= 2000 else None


class Streamer(commands.Cog):
    """Zeigt ausschließlich aktive, zum Titelfilter passende Streams an."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=928461730552, force_registration=True)
        self.config.register_global(twitch_client_id="", twitch_client_secret="", youtube_api_key="", youtube_state={})
        self.config.register_guild(enabled=True, channel_id=None, title_filter="", sources={}, state={}, last_error="")
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

    async def configure(self, guild, *, channel_id=None, title_filter=None, enabled=None):
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
        async with self._lock(guild):
            conf = self.config.guild(guild)
            if channel_id is not None:
                await conf.channel_id.set(int(channel_id))
            if title_filter is not None:
                await conf.title_filter.set(str(title_filter).strip())
            if enabled is not None:
                await conf.enabled.set(bool(enabled))
        await self.cleanup_guild(guild)
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

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        if not self._unloading:
            self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        extra = {"operate_forms": {"check", "toggle"}} if hasattr(webcore, "OPERATE") else {}
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
                conf = await self.config.guild(guild).all()
                if not conf.get("enabled") or await self.bot.cog_disabled_in_guild(self, guild):
                    continue
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
        sources = conf["sources"]
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

        errors = []
        blocked_sources = set()
        for key, record in list(state.items()):
            source_key = record["source_key"]
            source = sources.get(source_key)
            explicit_remove = (not active or not source or not source.get("enabled", True)
                               or target is None or record.get("channel_id") != target.id
                               or not matches_title(record["stream"].get("title"), conf["title_filter"]))
            authoritative = snapshots.get(record["provider"]) is not None
            if explicit_remove or (authoritative and key not in desired):
                if await self._delete_message(guild, record):
                    state.pop(key, None)
                else:
                    errors.append(record["error"])
                    blocked_sources.add(source_key)
                await gc.state.set(state)

        for key, stream in desired.items():
            if stream["source_key"] in blocked_sources:
                continue
            record = state.get(key)
            fresh = record is None
            if fresh:
                record = {"source_key": stream["source_key"], "provider": stream["provider"],
                          "stream": dict(stream), "message_id": None, "channel_id": target.id,
                          "last_update": 0, "error": "", "pending": True, "pending_since": self._now()}
                state[key] = record
                # Eine Absicht vor dem Senden sichern; bei Abbruch kann die Meldung wiedergefunden werden.
                await gc.state.set(state)
            await self._ensure_message(guild, target, record, stream, fresh=fresh,
                                       persist=lambda: gc.state.set(state))
            if record.get("error"):
                errors.append(record["error"])
            await gc.state.set(state)
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
        image = _image_url(stream.get("thumbnail"))
        if image:
            embed.set_image(url=image)
        embed.set_footer(text=self._footer(record))
        return embed

    async def _ensure_message(self, guild, channel, record, stream, *, fresh=False, persist=None):
        now = self._now()
        if float(record.get("retry_at") or 0) > now:
            return
        attempted_send = False
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
            record["stream"] = dict(stream)
            embed = self._embed(stream, record)
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Zum Stream", style=discord.ButtonStyle.link, url=stream["url"]))
            if message is None:
                if not self.can_post(channel):
                    raise ValueError("Im Ankündigungskanal fehlen Sende-, Embed- oder Leserechte.")
                record["pending"] = True
                record["pending_since"] = record.get("pending_since") or now
                if persist is not None:
                    await persist()
                attempted_send = True
                message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                record["message_id"] = message.id
            else:
                await message.edit(content=None, embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            record.update(pending=False, error="", retry_at=0, last_update=now)
        except discord.HTTPException as exc:
            record["error"] = f"Ankündigung konnte nicht aktualisiert werden (Discord HTTP {exc.status}); wird erneut versucht."
            record["retry_at"] = now + RETRY_SECONDS
            if attempted_send and exc.status < 500 and not record.get("message_id"):
                record["pending"] = False
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
