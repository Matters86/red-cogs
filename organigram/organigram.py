"""Organigram – postet Server-Organigramme nach Discord.

Mehrere benannte Organigramme pro Server, jeweils konfigurierbar über das
WebCore-Dashboard. Personen stammen hybrid aus Discord-Rollen **und** manuellen
Einträgen. Ausgabe wahlweise als Bild (acht Muster), Embed oder Text – pro Post
wählbar. Gepostete Beiträge aktualisieren sich automatisch, wenn sich passende
Rollen oder Mitglieder ändern.
"""

from __future__ import annotations

import asyncio
import io
import hashlib
import json
import logging
import re
import zipfile
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timezone
from typing import Literal, Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .render import (
    MAX_PEOPLE,
    ChartTooLarge,
    PATTERNS,
    RChart,
    RNode,
    RPerson,
    build_text_tree,
    render_chart_png,
)
from .pages import MAX_EXPORT_BYTES, PagesTooLarge, plan_pages, render_page

TOO_LARGE_HINT = ("Das Organigramm ist zu groß für ein Bild ({w}×{h} px). Nutze den Modus "
                  "„Embed“ oder „Text“, ein kompakteres Muster (z. B. „Abteilungen“) oder weniger Positionen.")

log = logging.getLogger("red.red-cogs.organigram")

IDENTIFIER = 471203958624

# Eingabe (DE) -> intern gespeicherter Modus
MODE_MAP = {"bild": "image", "image": "image", "embed": "embed", "text": "text"}
MODE_LABEL = {"image": "Bild", "embed": "Embed", "text": "Text"}

# Verzögerung fürs Zusammenfassen vieler Änderungs-Events (Sekunden).
REFRESH_DELAY = 4.0
# Avatar-Cache (Schlüssel = Avatar-Hash): Jede Rollen-/Namensänderung löst ein
# Neu-Rendern aus – ohne Cache wurden dabei jedes Mal ALLE Avatare neu geladen.
AVATAR_CACHE_MAX = 1000


def _color_int(hexstr: str | None) -> int:
    try:
        return int((hexstr or "#3ddc97").lstrip("#"), 16) & 0xFFFFFF
    except (ValueError, AttributeError):
        return 0x3DDC97


def resolve_node_people(guild: discord.Guild, chart: dict) -> dict:
    """Personenzuordnung für Bild, Embed, Text und Dashboard-Zählung.

    ``highest`` zeigt eine Discord-ID nur in ihrer höchsten Position: zuerst
    die geringste Tiefe im Organigramm, bei gleicher Tiefe die sichtbare
    Reihenfolge (Elternzweig, Reihenfolge, Bezeichnung). Freitext-Namen haben
    keine verlässliche Discord-Identität und bleiben unverändert.
    """
    nodes = chart.get("nodes", {})
    people = {}
    for nid, nd in nodes.items():
        role = guild.get_role(nd["role_id"]) if nd.get("role_id") else None
        entries = [(m.display_name, m) for m in sorted(
            role.members if role else [], key=lambda m: m.display_name.lower()
        )]
        entries.extend(((name or "").strip(), None) for name in nd.get("manual_names", [])
                       if (name or "").strip())
        people[nid] = entries
    if chart.get("member_display", "multiple") != "highest":
        return people

    def order_key(nid):
        nd = nodes[nid]
        return nd.get("order", 0), (nd.get("label") or "").lower()

    children = defaultdict(list)
    roots = []
    for nid, nd in nodes.items():
        parent = nd.get("parent")
        if parent in nodes and parent != nid:
            children[parent].append(nid)
        else:
            roots.append(nid)
    queue = deque(sorted(roots, key=order_key))
    visited, assigned = set(), set()
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        filtered = []
        for name, member in people[nid]:
            if member is None:
                filtered.append((name, member))
            elif member.id not in assigned:
                assigned.add(member.id)
                filtered.append((name, member))
        people[nid] = filtered
        queue.extend(sorted(children[nid], key=order_key))
    return people


class Organigram(commands.Cog):
    """Erstellt und postet Organigramme für deinen Server."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=IDENTIFIER, force_registration=True)
        self.config.register_guild(charts={})
        # Auto-Update-Infrastruktur
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._pending: dict[tuple[int, str], asyncio.Task] = {}
        self._running: set[asyncio.Task] = set()
        self._active_keys: set[tuple[int, str]] = set()
        self._again: set[tuple[int, str]] = set()
        self._verify_requests: dict[tuple[int, str], set[int]] = {}
        self._unloading = False
        self._avatar_cache: OrderedDict[str, bytes] = OrderedDict()
        self._startup_task = None

    # ------------------------------------------------------------------ #
    #  Lebenszyklus / Dashboard
    # ------------------------------------------------------------------ #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore:
            self._register_dashboard(webcore)
        self._startup_task = asyncio.create_task(self._reconcile_on_ready())

    async def cog_unload(self):
        self._unloading = True
        if self._startup_task is not None:
            self._startup_task.cancel()
        for task in list(self._pending.values()) + list(self._running):
            task.cancel()
        self._pending.clear()
        self._running.clear()
        webcore = self.bot.get_cog("WebCore")
        if webcore:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        try:
            # Tagesgeschäft („Bedienen“): nur Posten/Aktualisieren (form=post). Organigramme, Positionen und
            # Einstellungen anlegen/ändern/löschen brauchen „Bearbeiten“ (Positionen = Rollen-Zuordnung).
            extra = {"operate_forms": {"post", "retry"}} if hasattr(webcore, "OPERATE") else {}
            webcore.register_page(
                owner=self,
                slug="organigram",
                name="Organigramm",
                handler=self.dashboard_page,
                icon="bi-diagram-3",
                **extra,
            )
        except Exception:
            log.exception("Dashboard-Seite konnte nicht registriert werden.")

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler

        return await dashboard_handler(self, request)

    # ------------------------------------------------------------------ #
    #  Locks / Scheduler
    # ------------------------------------------------------------------ #
    def _lock(self, gid: int, cid: str) -> asyncio.Lock:
        return self._locks.setdefault((gid, cid), asyncio.Lock())

    def _schedule(self, gid: int, cid: str, *, verify_ids=()):
        key = (gid, cid)
        if self._unloading:
            return
        if verify_ids:
            self._verify_requests.setdefault(key, set()).update(verify_ids)
        if key in self._active_keys:
            self._again.add(key)
            return
        old = self._pending.get(key)
        if old and not old.done():
            old.cancel()
        self._pending[key] = asyncio.create_task(self._delayed(gid, cid))

    async def _delayed(self, gid: int, cid: str):
        try:
            await asyncio.sleep(REFRESH_DELAY)
            # Sobald ein Update beginnt, darf ein neues Ereignis es nicht mitten
            # zwischen Discord-Senden und Speichern der Nachrichten-ID abbrechen.
            key = (gid, cid)
            if self._pending.get(key) is asyncio.current_task():
                del self._pending[key]
            self._running.add(asyncio.current_task())
            self._active_keys.add(key)
            chart = (await self.config.guild_from_id(gid).charts()).get(cid)
            guild = self.bot.get_guild(gid)
            if (guild is not None and chart and chart.get("auto_update", True)
                    and not await self.bot.cog_disabled_in_guild(self, guild)):
                verify_ids = self._verify_requests.pop(key, set())
                await self._refresh_chart(gid, cid, force=False, verify_ids=verify_ids)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Auto-Aktualisierung fehlgeschlagen (%s/%s)", gid, cid)
        finally:
            was_running = asyncio.current_task() in self._running
            self._running.discard(asyncio.current_task())
            if was_running:
                self._active_keys.discard((gid, cid))
            # Nur den EIGENEN Task entfernen. Beim Debounce ersetzt _schedule den
            # Eintrag unter demselben Key durch einen neuen Task – ohne diese
            # Identitätsprüfung würde das finally des alten (gecancelten) Tasks den
            # neuen aus _pending poppen.
            key = (gid, cid)
            if self._pending.get(key) is asyncio.current_task():
                del self._pending[key]
            if was_running and key in self._again:
                self._again.discard(key)
                self._schedule(gid, cid)

    async def _schedule_affected(self, guild: discord.Guild, role_ids: set[int]):
        if not role_ids:
            return
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        charts = await self.config.guild(guild).charts()
        for cid, chart in charts.items():
            if not chart.get("posts") or not chart.get("auto_update", True):
                continue
            nodes = chart.get("nodes", {})
            if any(nd.get("role_id") in role_ids for nd in nodes.values()):
                self._schedule(guild.id, cid)

    async def _reconcile_on_ready(self):
        await self.bot.wait_until_red_ready()
        for attempt in range(3):
            try:
                for gid, conf in (await self.config.all_guilds()).items():
                    guild = self.bot.get_guild(int(gid))
                    if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                        continue
                    for cid, chart in conf.get("charts", {}).items():
                        if chart.get("posts") and chart.get("auto_update", True):
                            await self._verify_after_downtime(guild, cid, chart)
                            self._schedule(guild.id, cid)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Organigramm-Abgleich nach Neustart fehlgeschlagen")
                if attempt < 2:
                    await asyncio.sleep(10)

    async def _verify_after_downtime(self, guild, chart_id, chart):
        """Einmaliger Startabgleich in 20er-Gruppen; normale Updates bleiben ohne Fetch."""
        missing = set()
        for entry in chart.get("posts", []):
            ids = entry.get("page_message_ids") or ([entry["message_id"]] if entry.get("message_id") else [])
            try:
                channel = guild.get_channel_or_thread(entry["channel_id"])
                if channel is None:
                    channel = await guild.fetch_channel(entry["channel_id"])
                for offset in range(0, len(ids), 20):
                    for mid in ids[offset:offset + 20]:
                        try:
                            await channel.fetch_message(mid)
                        except discord.NotFound:
                            missing.add(mid)
                    await asyncio.sleep(0)
            except discord.HTTPException:
                # Fehlende Rechte sind keine Löschung. Der normale Abgleich speichert Fehler.
                continue
        if missing:
            self._schedule(guild.id, chart_id, verify_ids=missing)

    async def _repair_deleted_pages(self, guild_id, message_ids):
        guild = self.bot.get_guild(guild_id)
        if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
            return
        for chart_id, chart in (await self.config.guild(guild).charts()).items():
            if not chart.get("auto_update", True):
                continue
            active = {mid for entry in chart.get("posts", []) for mid in (
                entry.get("page_message_ids") or ([entry["message_id"]] if entry.get("message_id") else []))}
            affected = active.intersection(message_ids)
            if affected:
                self._schedule(guild.id, chart_id, verify_ids=affected)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id is not None:
            await self._repair_deleted_pages(payload.guild_id, {payload.message_id})

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if payload.guild_id is not None:
            await self._repair_deleted_pages(payload.guild_id, set(payload.message_ids))

    # ------------------------------------------------------------------ #
    #  Auflösung Config -> Render-Modell
    # ------------------------------------------------------------------ #
    async def _resolve(self, guild: discord.Guild, chart: dict, *, load_avatars=True) -> RChart:
        nodes_conf: dict = chart.get("nodes", {})
        show_av = chart.get("show_avatars", True)
        show_vac = chart.get("show_vacant", True)
        accent = chart.get("accent") or "#3ddc97"

        # 1) Einheitliche Personenzuordnung für alle Ausgabemodi.
        node_people = resolve_node_people(guild, chart)

        # 2) Avatare laden – nur für tatsächlich sichtbare Mitglieder, einmal je Member
        avatars: dict[int, bytes] = {}
        if show_av and load_avatars:
            needed: dict[int, discord.Member] = {}
            for plist in node_people.values():
                for name, m in plist[:MAX_PEOPLE]:
                    if m is not None:
                        needed[m.id] = m

            sem = asyncio.Semaphore(8)  # CDN nicht mit hunderten Parallel-Requests fluten

            async def _fetch(member: discord.Member):
                asset = member.display_avatar
                key = f"{asset.key}:{member.id}"
                cached = self._avatar_cache.get(key)
                if cached is not None:
                    self._avatar_cache.move_to_end(key)
                    return member.id, cached
                try:
                    async with sem:
                        data = await asset.read()
                except Exception:
                    return member.id, None
                self._avatar_cache[key] = data
                while len(self._avatar_cache) > AVATAR_CACHE_MAX:
                    self._avatar_cache.popitem(last=False)
                return member.id, data

            if needed:
                for mid, data in await asyncio.gather(*(_fetch(m) for m in needed.values())):
                    if data:
                        avatars[mid] = data

        # 3) RNodes bauen
        rnodes: dict[str, RNode] = {}
        for nid, nd in nodes_conf.items():
            role = guild.get_role(nd["role_id"]) if nd.get("role_id") else None
            label = nd.get("label") or (role.name if role else "—")
            color = nd.get("color")
            if not color:
                if role is not None and role.color.value:
                    color = f"#{role.color.value:06x}"
                else:
                    color = accent
            people: list[RPerson] = []
            for name, m in node_people[nid]:
                ap = avatars.get(m.id) if (m is not None and show_av) else None
                people.append(RPerson(name=name, avatar_png=ap, member_id=m.id if m is not None else None))
            if not people and show_vac:
                people.append(RPerson(name="unbesetzt", vacant=True))
            rnodes[nid] = RNode(
                id=nid, label=label, color=color,
                emoji=nd.get("emoji", "") or "", people=people,
            )

        # 4) Baum verknüpfen (mit Zyklus-Schutz)
        children_of: dict[str, list[str]] = defaultdict(list)
        roots: list[str] = []
        for nid, nd in nodes_conf.items():
            parent = nd.get("parent")
            if parent and parent in rnodes and parent != nid:
                children_of[parent].append(nid)
            else:
                roots.append(nid)

        def order_key(nid: str):
            nd = nodes_conf[nid]
            return (nd.get("order", 0), (nd.get("label") or "").lower())

        def attach(nid: str, seen: set[str]) -> RNode:
            node = rnodes[nid]
            node.children = []
            for cid in sorted(children_of.get(nid, []), key=order_key):
                if cid in seen:
                    continue
                seen.add(cid)
                node.children.append(attach(cid, seen))
            return node

        seen = set(roots)
        root_nodes = [attach(nid, seen) for nid in sorted(roots, key=order_key)]
        if not root_nodes:
            root_nodes = [RNode(
                id="_empty", label="(leer)", color=accent,
                people=[RPerson("Noch keine Positionen", vacant=True)],
            )]

        return RChart(
            title=chart.get("title") or chart.get("name") or "Organigramm",
            pattern=chart.get("pattern", "baum"),
            accent=accent,
            show_avatars=show_av,
            roots=root_nodes,
            footer=guild.name,
        )

    async def _image_manifest(self, guild, chart):
        if chart.get("image_mode", "single") != "pages":
            return [chart.get("title") or chart.get("name") or "Organigramm"]
        model = await self._resolve(guild, chart, load_avatars=False)
        return [page.title for page in plan_pages(model, chart.get("page_size", 20))]

    async def _render_images(self, guild, chart):
        model = await self._resolve(guild, chart)
        if chart.get("image_mode", "single") != "pages":
            png = await asyncio.to_thread(render_chart_png, model)
            return [(model.title, png)]
        specs = plan_pages(model, chart.get("page_size", 20))
        result, total_bytes = [], 0
        for index, page in enumerate(specs):
            png = await asyncio.to_thread(render_page, model, page, index, len(specs))
            total_bytes += len(png)
            if total_bytes > MAX_EXPORT_BYTES:
                raise PagesTooLarge("Die Seiten überschreiten zusammen 64 MiB. Bitte teile das Organigramm auf.")
            result.append((page.title, png))
        return result

    async def _export_images_zip(self, guild, chart):
        images = await self._render_images(guild, chart)
        name = re.sub(r"[^a-zA-Z0-9_-]+", "-", chart.get("name") or "organigramm").strip("-")[:60] or "organigramm"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for index, (_, png) in enumerate(images):
                archive.writestr(f"{name}-{index + 1:03d}.png", png)
        if output.tell() > MAX_EXPORT_BYTES:
            raise PagesTooLarge("Der ZIP-Export überschreitet 64 MiB. Bitte teile das Organigramm auf.")
        return output.getvalue()

    async def _render_png(self, guild: discord.Guild, chart: dict, page=0) -> bytes:
        rchart = await self._resolve(guild, chart)
        if chart.get("image_mode", "single") == "pages":
            specs = plan_pages(rchart, chart.get("page_size", 20))
            if not 0 <= page < len(specs):
                raise IndexError("Seite nicht gefunden")
            return await asyncio.to_thread(render_page, rchart, specs[page], page, len(specs))
        if page != 0:
            raise IndexError("Seite nicht gefunden")
        return await asyncio.get_running_loop().run_in_executor(None, render_chart_png, rchart)

    def _build_embed(self, guild: discord.Guild, chart: dict, rchart: RChart) -> discord.Embed:
        emb = discord.Embed(
            # Discord-Limit 256 – ein langer Titel aus dem Dashboard ließ das Posten
            # im Embed-Modus sonst mit HTTP 400 scheitern.
            title=(rchart.title or "")[:256] or None,
            color=discord.Color(_color_int(chart.get("accent"))),
        )
        # Discord-Limit: max. 25 Felder UND max. 6000 Zeichen je Embed.
        # Gesamtlaenge (inkl. Titel/Footer) mitzaehlen und mit etwas Puffer
        # fuer den Hinweis "+N weitere Positionen" kappen, sonst HTTP 400.
        LIMIT = 5800
        count = 0
        omitted = 0
        stop = False
        total = len((rchart.title or "")[:256]) + len(guild.name or "")

        def walk(node: RNode, depth: int):
            nonlocal count, omitted, stop, total
            indent = "\u3000" * depth  # geviertbreites Leerzeichen für Einrückung
            arrow = "" if depth == 0 else "↳ "
            emoji = (node.emoji + " ") if node.emoji else ""
            name = f"{indent}{arrow}{emoji}{node.label}"[:256] or "—"
            if node.people:
                shown = node.people[:MAX_PEOPLE]
                value = "\n".join(
                    "• " + (f"*{p.name}*" if p.vacant else p.name) for p in shown
                )
                extra = len(node.people) - MAX_PEOPLE
                if extra > 0:
                    value += f"\n• +{extra} weitere"
            else:
                value = "—"
            value = value[:1024] or "—"
            field_len = len(name) + len(value)
            if stop or count >= 24 or total + field_len > LIMIT:
                stop = True
                omitted += 1
            else:
                emb.add_field(name=name, value=value, inline=False)
                total += field_len
                count += 1
            for c in node.children:
                walk(c, depth + 1)

        for r in rchart.roots:
            walk(r, 0)
        if omitted > 0:
            emb.add_field(name="…", value=f"+{omitted} weitere Positionen", inline=False)
        emb.set_footer(text=guild.name)
        emb.timestamp = discord.utils.utcnow()
        return emb

    def _text_block(self, rchart: RChart) -> str:
        tree = build_text_tree(rchart)
        if len(tree) > 1900:
            tree = tree[:1890] + "\n… (gekürzt)"
        return f"```\n{tree}\n```"

    # ------------------------------------------------------------------ #
    #  Posten / Aktualisieren
    # ------------------------------------------------------------------ #
    async def _safe_fetch(self, channel: discord.abc.Messageable, message_id: int | None):
        if not message_id:
            return None
        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound:
            return None

    async def _send_or_edit(self, channel, existing, *, file=None, embed=None, content=None):
        msg = await self._safe_fetch(channel, existing.get("message_id")) if existing else None
        if msg is not None:
            await msg.edit(
                content=content,
                embed=embed,
                attachments=[file] if file else [],
            )
            return msg
        if file is not None:
            return await channel.send(content=content, embed=embed, file=file)
        return await channel.send(content=content, embed=embed)

    async def _persist_publication(self, guild, chart_id, entry):
        """Neu gesendete IDs sofort sichern, bevor die nächste Seite gesendet wird."""
        async with self.config.guild(guild).charts() as charts:
            if chart_id not in charts:
                raise RuntimeError("Organigramm wurde während der Veröffentlichung entfernt")
            posts = charts[chart_id].setdefault("posts", [])
            old = next((p for p in posts if p.get("channel_id") == entry["channel_id"]), None)
            if old is None:
                posts.append(dict(entry))
            else:
                posts[posts.index(old)] = dict(entry)

    async def _post_chart(self, guild, chart_id, chart, channel, mode, *, force=True, verify_ids=()) -> tuple[bool, str | None]:
        posts = chart.setdefault("posts", [])
        existing = next((p for p in posts if p.get("channel_id") == channel.id), None)
        entry = dict(existing or {"channel_id": channel.id, "message_id": None})
        slots = list(entry.get("page_message_ids") or ([entry["message_id"]] if entry.get("message_id") else []))
        tracked = list(dict.fromkeys(entry.get("message_ids") or slots))
        old_hashes = list(entry.get("page_hashes", []))
        had_error = bool(entry.get("last_error"))
        entry.update(mode=mode, attempted_mode=mode, channel_name=getattr(channel, "name", ""),
                     last_attempt_at=datetime.now(timezone.utc).isoformat(), publishing=True,
                     last_error="Veröffentlichung noch nicht abgeschlossen; bitte bei Bedarf erneut versuchen.",
                     error_at=datetime.now(timezone.utc).isoformat())

        def attach():
            old = next((p for p in posts if p.get("channel_id") == channel.id), None)
            if old is None:
                posts.append(entry)
            else:
                posts[posts.index(old)] = entry

        async def checkpoint():
            entry.update(page_message_ids=list(slots), message_ids=list(tracked),
                         message_id=slots[0] if slots else None)
            attach()
            await self._persist_publication(guild, chart_id, entry)

        async def failed(message):
            entry.update(last_error=message, error_at=datetime.now(timezone.utc).isoformat(), publishing=False)
            await checkpoint()
            return False, message

        try:
            await checkpoint()
            payloads = []
            if mode == "image":
                images = await self._render_images(guild, chart)
                file_limit = getattr(guild, "filesize_limit", 8 * 1024 * 1024)
                if any(len(png) > file_limit for _, png in images):
                    raise PagesTooLarge("Eine Bildseite überschreitet das Discord-Dateilimit. Reduziere die Seitengröße.")
                for index, (title, png) in enumerate(images):
                    caption = (f"{chart.get('name') or 'Organigramm'} · Seite {index + 1}/{len(images)} · {title}"
                               if chart.get("image_mode") == "pages" else None)
                    payloads.append({"png": png, "content": discord.utils.escape_markdown(caption)[:1900] if caption else None})
            else:
                model = await self._resolve(guild, chart)
                payloads.append({"embed": self._build_embed(guild, chart, model)} if mode == "embed"
                                else {"content": self._text_block(model)})
            hashes = []
            for payload in payloads:
                content = dict(payload)
                png = content.pop("png", b"")
                if content.get("embed") is not None:
                    content["embed"] = content["embed"].to_dict()
                    content["embed"].pop("timestamp", None)
                hashes.append(hashlib.sha256(png + json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest())
            # Unveränderte automatische Seiten verursachen weder Fetch noch Edit.
            matching = {index for index, digest in enumerate(hashes)
                         if not had_error and index < len(slots)
                         and index < len(old_hashes) and old_hashes[index] == digest}
            check = {index for index in range(len(payloads)) if force or index not in matching
                     or (index < len(slots) and slots[index] in verify_ids)}
            messages = [await self._safe_fetch(channel, slots[index])
                        if index in check and index < len(slots) else None
                        for index in range(len(payloads))]
            unchanged = {index for index in matching if index not in check or messages[index] is not None}
            for batch in range(0, len(payloads), 10):
                for index in range(batch, min(batch + 10, len(payloads))):
                    if index in unchanged:
                        continue
                    payload = payloads[index]
                    file = (discord.File(io.BytesIO(payload["png"]), filename=f"organigramm-{index + 1:03d}.png")
                            if "png" in payload else None)
                    msg = messages[index]
                    if msg is not None:
                        await msg.edit(content=payload.get("content"), embed=payload.get("embed"),
                                       attachments=[file] if file else [], allowed_mentions=discord.AllowedMentions.none())
                    else:
                        async def send_and_track(index=index, payload=payload, file=file):
                            msg = await channel.send(content=payload.get("content"), embed=payload.get("embed"),
                                                     **({"file": file} if file else {}),
                                                     allowed_mentions=discord.AllowedMentions.none())
                            if index < len(slots):
                                slots[index] = msg.id
                            else:
                                slots.append(msg.id)
                            if msg.id not in tracked:
                                tracked.append(msg.id)
                            await checkpoint()
                            return msg
                        # Auch beim Cog-Entladen die ID einer schon gesendeten Seite sichern.
                        transaction = asyncio.create_task(send_and_track())
                        try:
                            await asyncio.shield(transaction)
                        except asyncio.CancelledError:
                            await transaction
                            raise
            desired = slots[:len(payloads)]
            obsolete = [mid for mid in dict.fromkeys(tracked + list(entry.get("retired_message_ids", [])))
                        if mid not in desired]
            # Stale Seiten erst entfernen, nachdem JEDE Ersatzseite erfolgreich geschrieben wurde.
            entry["retired_message_ids"] = list(obsolete)
            slots[:] = desired
            await checkpoint()
            failed_cleanup = []
            for message_id in obsolete:
                try:
                    old = await self._safe_fetch(channel, message_id)
                    if old is not None:
                        await old.delete()
                except discord.HTTPException:
                    failed_cleanup.append(message_id)
            tracked[:] = desired + failed_cleanup
            entry["retired_message_ids"] = failed_cleanup
            entry["page_count"] = len(payloads)
            entry["page_hashes"] = hashes
            if failed_cleanup:
                return await failed("Neue Seiten sind veröffentlicht; alte Seiten konnten noch nicht entfernt werden. Bitte erneut versuchen.")
            entry.update(last_success_at=datetime.now(timezone.utc).isoformat(), last_error=None, error_at=None,
                         publishing=False)
            await checkpoint()
            return True, None
        except discord.Forbidden:
            return await failed("Mir fehlen Rechte zum Lesen, Posten oder Bearbeiten in diesem Kanal.")
        except ChartTooLarge as exc:
            return await failed(TOO_LARGE_HINT.format(w=exc.width, h=exc.height))
        except (PagesTooLarge, ValueError) as exc:
            return await failed(str(exc))
        except Exception as exc:
            log.exception("Posten fehlgeschlagen")
            return await failed(f"Discord-Beitrag konnte nicht aktualisiert werden: {exc}")

    async def _post_and_save(self, guild, chart_id, channel, mode) -> tuple[bool, str | None]:
        async with self._lock(guild.id, chart_id):
            charts = await self.config.guild(guild).charts()
            chart = charts.get(chart_id)
            if not chart:
                return False, "Organigramm nicht gefunden."
            ok, err = await self._post_chart(guild, chart_id, chart, channel, mode)
            # Lost-Update vermeiden: nur den 'posts'-Eintrag dieses Charts frisch
            # zurückschreiben, nicht den kompletten (evtl. veralteten) Snapshot.
            async with self.config.guild(guild).charts() as stored:
                if chart_id in stored:
                    stored[chart_id]["posts"] = chart.get("posts", [])
                    if ok:
                        stored[chart_id]["draft"] = False
            return ok, err

    async def _refresh_chart(self, guild_id: int, chart_id: str, *, channel_id=None, force=True, verify_ids=()):
        result = {"updated": 0, "failed": 0, "removed": 0}
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return result
        async with self._lock(guild_id, chart_id):
            charts = await self.config.guild(guild).charts()
            chart = charts.get(chart_id)
            if not chart:
                return result
            posts = list(chart.get("posts", []))
            alive = []
            chart["posts"] = alive
            for p in posts:
                if channel_id is not None and p.get("channel_id") != channel_id:
                    alive.append(p)
                    continue
                channel = guild.get_channel_or_thread(p["channel_id"])
                if channel is None:
                    try:
                        # Archivierte Threads fehlen oft nur im lokalen Cache.
                        channel = await guild.fetch_channel(p["channel_id"])
                    except discord.NotFound:
                        result["removed"] += 1
                        continue  # Nur eine bestätigte Löschung entfernt die Zuordnung.
                    except discord.HTTPException as exc:
                        error_time = datetime.now(timezone.utc).isoformat()
                        alive.append(dict(p, last_attempt_at=error_time, error_at=error_time,
                                          attempted_mode=p.get("mode", "image"),
                                          last_error=f"Kanal nicht erreichbar: {exc}"))
                        result["failed"] += 1
                        log.warning("Organigramm-Kanal %s vorübergehend nicht erreichbar; Zuordnung bleibt erhalten",
                                    p["channel_id"])
                        continue
                alive.append(p)
                ok, _ = await self._post_chart(guild, chart_id, chart, channel, p.get("mode", "image"),
                                               force=force, verify_ids=verify_ids)
                result["updated" if ok else "failed"] += 1
            # Lost-Update vermeiden: nur den 'posts'-Eintrag dieses Charts gezielt
            # zurückschreiben, nicht den kompletten (evtl. veralteten) Snapshot.
            async with self.config.guild(guild).charts() as stored:
                if chart_id in stored:
                    stored[chart_id]["posts"] = chart.get("posts", [])
        return result

    # ------------------------------------------------------------------ #
    #  Events -> Auto-Update
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        changed = {r.id for r in set(before.roles) ^ set(after.roles)}
        if (before.display_name != after.display_name
                or getattr(before, "display_avatar", None) != getattr(after, "display_avatar", None)):
            changed |= {r.id for r in after.roles}
        await self._schedule_affected(after.guild, changed)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if (before.name, getattr(before, "global_name", None), before.display_avatar) == (
                after.name, getattr(after, "global_name", None), after.display_avatar):
            return
        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member is not None:
                await self._schedule_affected(guild, {role.id for role in member.roles})

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._schedule_affected(member.guild, {role.id for role in member.roles})

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._schedule_affected(member.guild, {r.id for r in member.roles})

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if before.name != after.name or before.color != after.color:
            await self._schedule_affected(after.guild, {after.id})

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._schedule_affected(role.guild, {role.id})

    # ------------------------------------------------------------------ #
    #  Befehle
    # ------------------------------------------------------------------ #
    def _find(self, charts: dict, name: str) -> tuple[Optional[str], Optional[dict]]:
        nl = (name or "").strip().lower()
        for cid, c in charts.items():
            if c.get("name", "").lower() == nl:
                return cid, c
        return None, None

    @commands.hybrid_group(name="organigram", aliases=["org"])
    @commands.guild_only()
    async def organigram(self, ctx: commands.Context):
        """Organigramme anzeigen und posten."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @organigram.command(name="list")
    async def og_list(self, ctx: commands.Context):
        """Listet alle Organigramme dieses Servers."""
        charts = await self.config.guild(ctx.guild).charts()
        if not charts:
            return await ctx.send(
                "Es gibt noch keine Organigramme. Lege eines im Dashboard an "
                "(Seite **Organigramm**)."
            )
        lines = []
        for c in charts.values():
            n = len(c.get("nodes", {}))
            posts = c.get("posts", [])
            where = ", ".join(
                f"#{ch.name}"
                for p in posts
                if (ch := ctx.guild.get_channel_or_thread(p.get("channel_id"))) is not None
            ) or "—"
            pat = PATTERNS.get(c.get("pattern", "baum"), c.get("pattern", "baum"))
            lines.append(
                f"**{c.get('name','?')}** · {pat} · Standard: "
                f"{MODE_LABEL.get(c.get('mode','image'),'Bild')} · {n} Positionen · "
                f"gepostet: {where}"
            )
        await ctx.send("\n".join(lines)[:1990])

    @organigram.command(name="show")
    @commands.admin_or_permissions(manage_guild=True)
    async def og_show(
        self,
        ctx: commands.Context,
        name: str,
        modus: Optional[Literal["bild", "embed", "text"]] = None,
    ):
        """Zeigt ein Organigramm einmalig hier an (ohne Auto-Aktualisierung)."""
        charts = await self.config.guild(ctx.guild).charts()
        cid, chart = self._find(charts, name)
        if not chart:
            return await ctx.send(
                f"Kein Organigramm namens „{name}”. `{ctx.clean_prefix}organigram list` zeigt alle."
            )
        mode = MODE_MAP.get(modus) if modus else chart.get("mode", "image")
        async with ctx.typing():
            try:
                if mode == "image":
                    if chart.get("image_mode", "single") == "pages":
                        archive = await self._export_images_zip(ctx.guild, chart)
                        if len(archive) > getattr(ctx.guild, "filesize_limit", 8 * 1024 * 1024):
                            return await ctx.send("Der vollständige ZIP-Export überschreitet das Discord-Dateilimit. "
                                                  "Bitte im Dashboard herunterladen oder mit organigram post veröffentlichen.")
                        await ctx.send(file=discord.File(io.BytesIO(archive), filename="organigramm-seiten.zip"))
                    else:
                        png = await self._render_png(ctx.guild, chart)
                        await ctx.send(file=discord.File(io.BytesIO(png), filename="organigramm.png"))
                elif mode == "embed":
                    rchart = await self._resolve(ctx.guild, chart)
                    await ctx.send(embed=self._build_embed(ctx.guild, chart, rchart))
                else:
                    rchart = await self._resolve(ctx.guild, chart)
                    await ctx.send(self._text_block(rchart))
            except discord.Forbidden:
                await ctx.send("Mir fehlen Rechte, hier zu posten.")
            except ChartTooLarge as exc:
                await ctx.send(TOO_LARGE_HINT.format(w=exc.width, h=exc.height))
            except PagesTooLarge as exc:
                await ctx.send(str(exc))
            except discord.HTTPException as exc:
                log.exception("Anzeigen fehlgeschlagen")
                await ctx.send(f"Konnte das Organigramm nicht senden: {exc}")

    @organigram.command(name="post")
    @commands.admin_or_permissions(manage_guild=True)
    async def og_post(
        self,
        ctx: commands.Context,
        name: str,
        modus: Optional[Literal["bild", "embed", "text"]] = None,
        kanal: Optional[discord.TextChannel] = None,
    ):
        """Postet ein Organigramm (aktualisiert sich danach automatisch)."""
        charts = await self.config.guild(ctx.guild).charts()
        cid, chart = self._find(charts, name)
        if not chart:
            return await ctx.send(
                f"Kein Organigramm namens „{name}”. `{ctx.clean_prefix}organigram list` zeigt alle."
            )
        channel = kanal or ctx.channel
        mode = MODE_MAP.get(modus) if modus else chart.get("mode", "image")
        async with ctx.typing():
            ok, err = await self._post_and_save(ctx.guild, cid, channel, mode)
        if ok:
            await ctx.send(
                f"„{chart['name']}” in {channel.mention} gepostet ({MODE_LABEL[mode]}). "
                "Der Beitrag aktualisiert sich automatisch bei Änderungen."
            )
        else:
            await ctx.send(f"Konnte nicht posten: {err}")

    @organigram.command(name="refresh")
    @commands.admin_or_permissions(manage_guild=True)
    async def og_refresh(self, ctx: commands.Context, name: str):
        """Aktualisiert alle geposteten Beiträge eines Organigramms sofort."""
        charts = await self.config.guild(ctx.guild).charts()
        cid, chart = self._find(charts, name)
        if not chart:
            return await ctx.send(f"Kein Organigramm namens „{name}”.")
        if not chart.get("posts"):
            return await ctx.send("Dieses Organigramm ist aktuell nirgends gepostet.")
        async with ctx.typing():
            result = await self._refresh_chart(ctx.guild.id, cid)
        await ctx.send(f"„{chart['name']}”: {result['updated']} aktualisiert, "
                       f"{result['failed']} fehlgeschlagen, {result['removed']} gelöschte Kanäle entfernt.")

    @organigram.command(name="stop")
    @commands.admin_or_permissions(manage_guild=True)
    async def og_stop(
        self,
        ctx: commands.Context,
        name: str,
        kanal: Optional[discord.TextChannel] = None,
    ):
        """Beendet die Auto-Aktualisierung (die Nachricht selbst bleibt bestehen)."""
        charts = await self.config.guild(ctx.guild).charts()
        cid, chart = self._find(charts, name)
        if not chart:
            return await ctx.send(f"Kein Organigramm namens „{name}”.")
        # Chart VOR dem Lock auflösen, damit wir denselben (guild_id, cid)-Lock
        # wie ein laufender Refresh nehmen und uns mit ihm ausschließen.
        async with self._lock(ctx.guild.id, cid):
            charts = await self.config.guild(ctx.guild).charts()
            chart = charts.get(cid)
            if not chart:
                return await ctx.send(f"Kein Organigramm namens „{name}”.")
            before = len(chart.get("posts", []))
            if kanal:
                chart["posts"] = [
                    p for p in chart.get("posts", []) if p.get("channel_id") != kanal.id
                ]
            else:
                chart["posts"] = []
            removed = before - len(chart["posts"])
            await self.config.guild(ctx.guild).charts.set(charts)
        await ctx.send(
            f"Auto-Aktualisierung gestoppt – {removed} Beitrag/Beiträge werden nicht mehr "
            "verfolgt. Die bereits geposteten Nachrichten bleiben unverändert stehen."
        )

    @organigram.command(name="members")
    @commands.admin_or_permissions(manage_guild=True)
    async def og_members(self, ctx: commands.Context, name: str,
                         anzeige: Literal["multiple", "highest"]):
        """Mitglieder mehrfach (multiple) oder nur in höchster Position (highest) anzeigen."""
        charts = await self.config.guild(ctx.guild).charts()
        cid, chart = self._find(charts, name)
        if chart is None:
            return await ctx.send(f"Kein Organigramm namens „{name}”.")
        async with self._lock(ctx.guild.id, cid):
            async with self.config.guild(ctx.guild).charts() as stored:
                chart = stored.get(cid)
                if chart is None:
                    return await ctx.send(f"Kein Organigramm namens „{name}”.")
                chart["member_display"] = anzeige
                refresh = bool(chart.get("posts")) and chart.get("auto_update", True)
        if refresh:
            self._schedule(ctx.guild.id, cid)
        description = ("in jeder passenden Position" if anzeige == "multiple"
                       else "nur einmal in ihrer höchsten Position")
        await ctx.send(f"Mitglieder werden in „{chart['name']}” {description} angezeigt.")
