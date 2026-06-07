"""Organigram – postet Server-Organigramme nach Discord.

Mehrere benannte Organigramme pro Server, jeweils konfigurierbar über das
WebCore-Dashboard. Personen stammen hybrid aus Discord-Rollen **und** manuellen
Einträgen. Ausgabe wahlweise als Bild (fünf Muster), Embed oder Text – pro Post
wählbar. Gepostete Beiträge aktualisieren sich automatisch, wenn sich passende
Rollen oder Mitglieder ändern.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections import defaultdict
from typing import Literal, Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .render import (
    MAX_PEOPLE,
    PATTERNS,
    RChart,
    RNode,
    RPerson,
    build_text_tree,
    render_chart_png,
)

log = logging.getLogger("red.red-cogs.organigram")

IDENTIFIER = 471203958624

# Eingabe (DE) -> intern gespeicherter Modus
MODE_MAP = {"bild": "image", "image": "image", "embed": "embed", "text": "text"}
MODE_LABEL = {"image": "Bild", "embed": "Embed", "text": "Text"}

# Verzögerung fürs Zusammenfassen vieler Änderungs-Events (Sekunden).
REFRESH_DELAY = 4.0


def _color_int(hexstr: str | None) -> int:
    try:
        return int((hexstr or "#3ddc97").lstrip("#"), 16) & 0xFFFFFF
    except (ValueError, AttributeError):
        return 0x3DDC97


class Organigram(commands.Cog):
    """Erstellt und postet Organigramme für deinen Server."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=IDENTIFIER, force_registration=True)
        self.config.register_guild(charts={})
        # Auto-Update-Infrastruktur
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._pending: dict[tuple[int, str], asyncio.Task] = {}

    # ------------------------------------------------------------------ #
    #  Lebenszyklus / Dashboard
    # ------------------------------------------------------------------ #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore:
            self._register_dashboard(webcore)

    async def cog_unload(self):
        for task in list(self._pending.values()):
            task.cancel()
        self._pending.clear()
        webcore = self.bot.get_cog("WebCore")
        if webcore:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        try:
            webcore.register_page(
                owner=self,
                slug="organigram",
                name="Organigramm",
                handler=self.dashboard_page,
                icon="bi-diagram-3",
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

    def _schedule(self, gid: int, cid: str):
        key = (gid, cid)
        old = self._pending.get(key)
        if old and not old.done():
            old.cancel()
        self._pending[key] = asyncio.create_task(self._delayed(gid, cid))

    async def _delayed(self, gid: int, cid: str):
        try:
            await asyncio.sleep(REFRESH_DELAY)
            await self._refresh_chart(gid, cid)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Auto-Aktualisierung fehlgeschlagen (%s/%s)", gid, cid)
        finally:
            self._pending.pop((gid, cid), None)

    async def _schedule_affected(self, guild: discord.Guild, role_ids: set[int]):
        if not role_ids:
            return
        charts = await self.config.guild(guild).charts()
        for cid, chart in charts.items():
            if not chart.get("posts") or not chart.get("auto_update", True):
                continue
            nodes = chart.get("nodes", {})
            if any(nd.get("role_id") in role_ids for nd in nodes.values()):
                self._schedule(guild.id, cid)

    # ------------------------------------------------------------------ #
    #  Auflösung Config -> Render-Modell
    # ------------------------------------------------------------------ #
    async def _resolve(self, guild: discord.Guild, chart: dict) -> RChart:
        nodes_conf: dict = chart.get("nodes", {})
        show_av = chart.get("show_avatars", True)
        show_vac = chart.get("show_vacant", True)
        accent = chart.get("accent") or "#3ddc97"

        # 1) Personen je Knoten sammeln (Rollenmitglieder + manuelle Namen)
        node_people: dict[str, list[tuple[str, Optional[discord.Member]]]] = {}
        for nid, nd in nodes_conf.items():
            plist: list[tuple[str, Optional[discord.Member]]] = []
            role = guild.get_role(nd["role_id"]) if nd.get("role_id") else None
            if role:
                for m in sorted(role.members, key=lambda x: x.display_name.lower()):
                    plist.append((m.display_name, m))
            for nm in nd.get("manual_names", []):
                nm = (nm or "").strip()
                if nm:
                    plist.append((nm, None))
            node_people[nid] = plist

        # 2) Avatare laden – nur für tatsächlich sichtbare Mitglieder, einmal je Member
        avatars: dict[int, bytes] = {}
        if show_av:
            needed: dict[int, discord.Member] = {}
            for plist in node_people.values():
                for name, m in plist[:MAX_PEOPLE]:
                    if m is not None:
                        needed[m.id] = m

            async def _fetch(member: discord.Member):
                try:
                    return member.id, await member.display_avatar.read()
                except Exception:
                    return member.id, None

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
                people.append(RPerson(name=name, avatar_png=ap))
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

    async def _render_png(self, guild: discord.Guild, chart: dict) -> bytes:
        rchart = await self._resolve(guild, chart)
        return await self.bot.loop.run_in_executor(None, render_chart_png, rchart)

    def _build_embed(self, guild: discord.Guild, chart: dict, rchart: RChart) -> discord.Embed:
        emb = discord.Embed(
            title=rchart.title,
            color=discord.Color(_color_int(chart.get("accent"))),
        )
        count = 0

        def walk(node: RNode, depth: int):
            nonlocal count
            if count >= 24:
                return
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
            emb.add_field(name=name, value=value[:1024] or "—", inline=False)
            count += 1
            for c in node.children:
                walk(c, depth + 1)

        for r in rchart.roots:
            walk(r, 0)
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
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
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

    async def _post_chart(self, guild, chart_id, chart, channel, mode) -> tuple[bool, str | None]:
        posts: list = chart.setdefault("posts", [])
        existing = next((p for p in posts if p.get("channel_id") == channel.id), None)
        try:
            if mode == "image":
                png = await self._render_png(guild, chart)
                file = discord.File(io.BytesIO(png), filename="organigramm.png")
                msg = await self._send_or_edit(channel, existing, file=file)
            elif mode == "embed":
                rchart = await self._resolve(guild, chart)
                emb = self._build_embed(guild, chart, rchart)
                msg = await self._send_or_edit(channel, existing, embed=emb)
            else:
                rchart = await self._resolve(guild, chart)
                msg = await self._send_or_edit(channel, existing, content=self._text_block(rchart))
        except discord.Forbidden:
            return False, "Mir fehlen Rechte, in diesem Kanal zu posten/zu bearbeiten."
        except Exception as exc:
            log.exception("Posten fehlgeschlagen")
            return False, f"Unerwarteter Fehler: {exc}"

        entry = {"channel_id": channel.id, "message_id": msg.id, "mode": mode}
        if existing:
            posts[posts.index(existing)] = entry
        else:
            posts.append(entry)
        return True, None

    async def _post_and_save(self, guild, chart_id, channel, mode) -> tuple[bool, str | None]:
        async with self._lock(guild.id, chart_id):
            charts = await self.config.guild(guild).charts()
            chart = charts.get(chart_id)
            if not chart:
                return False, "Organigramm nicht gefunden."
            ok, err = await self._post_chart(guild, chart_id, chart, channel, mode)
            await self.config.guild(guild).charts.set(charts)
            return ok, err

    async def _refresh_chart(self, guild_id: int, chart_id: str):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        async with self._lock(guild_id, chart_id):
            charts = await self.config.guild(guild).charts()
            chart = charts.get(chart_id)
            if not chart:
                return
            posts = chart.get("posts", [])
            # tote Kanäle entfernen
            alive = [p for p in posts if guild.get_channel(p.get("channel_id")) is not None]
            chart["posts"] = alive
            for p in list(alive):
                channel = guild.get_channel(p["channel_id"])
                await self._post_chart(guild, chart_id, chart, channel, p.get("mode", "image"))
            await self.config.guild(guild).charts.set(charts)

    # ------------------------------------------------------------------ #
    #  Events -> Auto-Update
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        changed = {r.id for r in set(before.roles) ^ set(after.roles)}
        if before.display_name != after.display_name:
            changed |= {r.id for r in after.roles}
        await self._schedule_affected(after.guild, changed)

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
                if (ch := ctx.guild.get_channel(p.get("channel_id"))) is not None
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
            await self._refresh_chart(ctx.guild.id, cid)
        await ctx.send(f"„{chart['name']}” wurde aktualisiert.")

    @organigram.command(name="stop")
    @commands.admin_or_permissions(manage_guild=True)
    async def og_stop(
        self,
        ctx: commands.Context,
        name: str,
        kanal: Optional[discord.TextChannel] = None,
    ):
        """Beendet die Auto-Aktualisierung (die Nachricht selbst bleibt bestehen)."""
        async with self._lock(ctx.guild.id, "_"):
            charts = await self.config.guild(ctx.guild).charts()
            cid, chart = self._find(charts, name)
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
