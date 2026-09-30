from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

from . import layout as L
from . import planner as P
from .executor import Job, Runner, err_text
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t

log = logging.getLogger("red.red-cogs.serverlayout")

MODE_WORDS = {"ergänzen": "merge", "ergaenzen": "merge", "merge": "merge", "add": "merge",
              "angleichen": "exact", "exakt": "exact", "exact": "exact", "sync": "exact"}
PART_WORDS = {"rollen": "roles", "rolle": "roles", "roles": "roles", "role": "roles",
              "kanäle": "channels", "kanaele": "channels", "kanal": "channels", "channels": "channels",
              "channel": "channels", "einstellungen": "settings", "settings": "settings", "server": "settings",
              "alle": "*", "alles": "*", "all": "*"}
SEC_LABEL = {"roles": "Rolle", "categories": "Kategorie", "channels": "Kanal", "settings": "Server", "order": "Reihenfolge"}
OP_ICON = {"create": "➕", "update": "✏️", "delete": "🗑️", "skip": "⏭️"}


class LoadError(Exception):
    """Laden nicht möglich – ``key`` ist ein Text-Key aus strings.py."""

    def __init__(self, key: str, **kwargs):
        super().__init__(key)
        self.key = key
        self.kwargs = kwargs


def parse_args(text: str, *, allow_mode: bool = True) -> tuple[str, str | None, list | None]:
    """``"Mein Layout angleichen rollen,kanäle"`` -> ("Mein Layout", "exact", ["roles", "channels"])."""
    text = (text or "").strip()
    name = None
    m = re.match(r'^["„“”](.+?)["“”]\s*(.*)$', text)
    if m:
        name, text = m.group(1).strip(), m.group(2)
    tokens = text.split()
    mode = None
    parts: set = set()
    while tokens:
        last = tokens[-1].lower()
        sub = [x for x in re.split(r"[,+/;]", last) if x]
        if allow_mode and mode is None and last in MODE_WORDS:
            mode = MODE_WORDS[last]
            tokens.pop()
            continue
        if sub and all(x in PART_WORDS for x in sub):
            for x in sub:
                parts |= set(L.PARTS) if PART_WORDS[x] == "*" else {PART_WORDS[x]}
            tokens.pop()
            continue
        break
    if name is None:
        name = " ".join(tokens).strip()
    return name, mode, ([p for p in L.PARTS if p in parts] or None)


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB".replace(".", ",")
    return f"{n / 1024 / 1024:.2f} MB".replace(".", ",")


def fmt_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return d.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    except (TypeError, ValueError):
        return iso or "—"


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return (s or "layout")[:60]


class ServerLayout(commands.Cog):
    """Server-Layout speichern und auf einen anderen (oder denselben) Server laden."""

    OP_PAUSE = 0.25            # Pause zwischen Discord-Aufrufen bei vielen Schritten (zusätzlich zu discord.py)
    PAUSE_THRESHOLD = 25
    MAX_AUTO_BACKUPS = 10      # automatische Sicherungen je Server
    MAX_REPORTS = 10

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=639281740517, force_registration=True)
        self.config.register_global(layouts={})        # id -> Metadaten (Dateien liegen im Cog-Datenordner)
        self.config.register_guild(language="de", reports=[], applied_images={})
        self._jobs: dict[int, Job] = {}
        self._index_lock = asyncio.Lock()
        self._dir: Path | None = None

    # ----------------------------------------------------------------- #
    #  Laden / Entladen / Dashboard
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)

    async def cog_unload(self):
        for job in list(self._jobs.values()):
            if job.running and job.task is not None:
                job.cancel_requested = True
                job.task.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        # Kein Tagesgeschäft (operate_forms): Layouts laden/löschen/hochladen ist Owner-Sache, alles andere
        # verlangt ebenfalls volle Sicht (siehe dashboard.py).
        webcore.register_page(owner=self, slug="serverlayout", name="Server-Layout", icon="bi-diagram-3",
                              handler=self.dashboard_page)

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Red-Datenschutz-API
    # ----------------------------------------------------------------- #
    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Anonymisiert Ersteller-IDs (Index + Dateien) und Nutzer in Berichten (-> 0) und entfernt
        mitgeschriebene Mitglieder-Überschreibungen dieser Person aus allen Layout-Dateien."""
        uid = int(user_id)
        try:
            async with self._index_lock:
                async with self.config.layouts() as idx:
                    for m in idx.values():
                        if m.get("creator_id") == uid:
                            m["creator_id"] = 0
                    ids = list(idx)
            for lid in ids:
                await asyncio.to_thread(self._anonymize_file, lid, uid)
        except Exception:  # noqa: BLE001
            log.exception("Datenlöschung (Layouts) fehlgeschlagen")
        try:
            for gid, data in (await self.config.all_guilds()).items():
                if not any(r.get("user_id") == uid for r in data.get("reports") or []):
                    continue
                async with self.config.guild_from_id(gid).reports() as reports:
                    for r in reports:
                        if r.get("user_id") == uid:
                            r["user_id"] = 0
                            r["user_name"] = "gelöscht"
        except Exception:  # noqa: BLE001
            log.exception("Datenlöschung (Berichte) fehlgeschlagen")
        for job in self._jobs.values():
            if job.user_id == uid:
                job.user_id, job.user_name = 0, "gelöscht"

    def _anonymize_file(self, lid: str, uid: int):
        path = self._path(lid)
        if not path.exists():
            return
        import json
        data = json.loads(path.read_bytes().decode("utf-8"))
        changed = False
        if data.get("creator_id") == uid:
            data["creator_id"] = 0
            changed = True
        for entry in (data.get("categories") or []) + (data.get("channels") or []):
            ows = entry.get("overwrites") or []
            keep = [o for o in ows if not (o.get("type") == "member" and o.get("id") == uid)]
            if len(keep) != len(ows):
                entry["overwrites"] = keep
                changed = True
        if changed:
            self._write(lid, L.dump(data))

    # ----------------------------------------------------------------- #
    #  Dateien & Index
    # ----------------------------------------------------------------- #
    @property
    def layout_dir(self) -> Path:
        if self._dir is None:
            self._dir = cog_data_path(self) / "layouts"
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def _path(self, lid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", str(lid)):
            raise ValueError("ungültige Layout-ID")
        return self.layout_dir / f"{lid}.json"

    def _write(self, lid: str, raw: bytes):
        path = self._path(lid)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, path)

    async def layouts(self) -> list[dict]:
        idx = await self.config.layouts()
        out = []
        for lid, meta in idx.items():
            try:
                if self._path(lid).exists():
                    out.append(dict(meta, id=lid))
            except ValueError:
                continue
        out.sort(key=lambda m: m.get("created") or "", reverse=True)
        return out

    async def find(self, query: str) -> dict | None:
        q = (query or "").strip()
        if not q:
            return None
        items = await self.layouts()
        for m in items:
            if m["id"] == q:
                return m
        for m in items:
            if m["name"].casefold() == q.casefold():
                return m
        return None

    @staticmethod
    def valid_name(name: str) -> str | None:
        name = (name or "").strip()
        if not 1 <= len(name) <= L.MAX_LAYOUT_NAME or any(ord(c) < 32 for c in name):
            return None
        return name

    async def unique_name(self, name: str, exclude: str | None = None) -> str:
        taken = {m["name"].casefold() for m in await self.layouts() if m["id"] != exclude}
        if name.casefold() not in taken:
            return name
        for i in range(2, 1000):
            cand = f"{name[:L.MAX_LAYOUT_NAME - 6]} ({i})"
            if cand.casefold() not in taken:
                return cand
        return f"{name[:40]} {secrets.token_hex(3)}"

    async def store(self, data: dict, *, auto: bool = False, exclude_prune: str | None = None) -> dict:
        lid = secrets.token_hex(6)
        raw = L.dump(data)
        L.parse_bytes(raw)          # muss sich später wieder laden lassen (LayoutError sonst)
        await asyncio.to_thread(self._write, lid, raw)
        meta = {"name": data["name"], "source_name": data["source"]["guild_name"], "source_id": data["source"]["guild_id"],
                "created": data.get("created") or L._now_iso(), "creator_id": int(data.get("creator_id") or 0),
                "parts": list(data["parts"]), "size": len(raw), "auto": bool(auto), "counts": L.counts(data)}
        async with self._index_lock:
            async with self.config.layouts() as idx:
                idx[lid] = meta
        if auto:
            await self._prune_auto(meta["source_id"], exclude=exclude_prune)
        return dict(meta, id=lid)

    async def _prune_auto(self, source_id: int, exclude: str | None = None):
        autos = [m for m in await self.layouts() if m.get("auto") and m.get("source_id") == source_id and m["id"] != exclude]
        for m in autos[self.MAX_AUTO_BACKUPS:]:
            await self.delete_layout(m["id"])

    async def read(self, lid: str) -> dict:
        raw = await asyncio.to_thread(self._path(lid).read_bytes)
        return L.parse_bytes(raw)

    async def save_layout(self, guild, name: str, parts, *, creator_id: int, auto: bool = False,
                          exclude_prune: str | None = None) -> tuple[dict, list]:
        clean = self.valid_name(name)
        if clean is None:
            raise LoadError("name_invalid")
        if auto:
            clean = await self.unique_name(clean)
        elif clean.casefold() in {m["name"].casefold() for m in await self.layouts()}:
            raise LoadError("name_taken", name=clean)
        data, notes = await L.export_guild(guild, parts or L.PARTS, name=clean, creator_id=creator_id)
        meta = await self.store(data, auto=auto, exclude_prune=exclude_prune)
        return meta, notes

    async def import_bytes(self, raw: bytes, *, creator_id: int, name: str | None = None) -> dict:
        data = L.parse_bytes(raw)
        base = self.valid_name(name or "") or self.valid_name(data["name"][:L.MAX_LAYOUT_NAME]) or "Import"
        data["name"] = await self.unique_name(base)
        data["creator_id"] = int(creator_id)
        return await self.store(data)

    async def delete_layout(self, lid: str) -> bool:
        async with self._index_lock:
            async with self.config.layouts() as idx:
                existed = idx.pop(lid, None) is not None
        try:
            await asyncio.to_thread(self._path(lid).unlink, True)
        except (OSError, ValueError):
            pass
        return existed

    async def rename_layout(self, lid: str, new_name: str) -> dict:
        clean = self.valid_name(new_name)
        if clean is None:
            raise LoadError("name_invalid")
        if clean.casefold() in {m["name"].casefold() for m in await self.layouts() if m["id"] != lid}:
            raise LoadError("name_taken", name=clean)
        data = await self.read(lid)
        data["name"] = clean
        raw = L.dump(data)
        await asyncio.to_thread(self._write, lid, raw)
        async with self._index_lock:
            async with self.config.layouts() as idx:
                if lid in idx:
                    idx[lid]["name"] = clean
                    idx[lid]["size"] = len(raw)
        return dict((await self.config.layouts()).get(lid) or {}, id=lid)

    async def export_bytes(self, lid: str) -> tuple[str, bytes]:
        meta = next((m for m in await self.layouts() if m["id"] == lid), None)
        raw = await asyncio.to_thread(self._path(lid).read_bytes)
        return f"serverlayout-{slug(meta['name'] if meta else lid)}.json", raw

    # ----------------------------------------------------------------- #
    #  Vorschau / Laden
    # ----------------------------------------------------------------- #
    def job(self, guild_id: int) -> Job | None:
        return self._jobs.get(int(guild_id))

    def running(self, guild_id: int) -> bool:
        j = self._jobs.get(int(guild_id))
        return bool(j and j.running)

    async def preview(self, guild, lid: str, mode: str = "merge", parts=None, protect_channel_id=None):
        layout = await self.read(lid)
        plan = P.build_plan(layout, guild, mode=mode, parts=parts, protect_channel_id=protect_channel_id,
                            image_state=await self.config.guild(guild).applied_images())
        return layout, plan

    async def start_load(self, guild, lid: str, *, mode: str, parts, user, expected_hash: str | None = None,
                         notify=None, protect_channel_id: int | None = None) -> Job:
        """Startet den Hintergrund-Task. Wirft ``LoadError`` (busy/blocked/changed/nothing/not_found)."""
        if self.running(guild.id):
            raise LoadError("busy")
        meta = next((m for m in await self.layouts() if m["id"] == lid), None)
        if meta is None:
            raise LoadError("not_found", name=lid)
        layout, plan = await self.preview(guild, lid, mode, parts, protect_channel_id)
        if plan["blockers"]:
            raise LoadError("blocked", reasons=" ".join(plan["blockers"]))
        if expected_hash and plan["hash"] != expected_hash:
            raise LoadError("changed")
        if not plan["actionable"]:
            raise LoadError("preview_nothing")
        if self.running(guild.id):          # erneut prüfen (nach den awaits) – kein paralleles Laden
            raise LoadError("busy")
        job = Job(guild.id, lid, meta["name"], plan["mode"], plan["parts"], getattr(user, "id", 0),
                  getattr(user, "display_name", None) or getattr(user, "name", "?"))
        self._jobs[guild.id] = job
        job.task = asyncio.create_task(self._run_job(job, guild, layout, plan, notify))
        return job

    async def _run_job(self, job: Job, guild, layout: dict, plan: dict, notify):
        try:
            job.step = "Automatische Sicherung …"
            try:
                stamp = datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M:%S")
                meta, _notes = await self.save_layout(guild, f"Automatisch vor dem Laden – {stamp}"[:L.MAX_LAYOUT_NAME],
                                                      L.PARTS, creator_id=job.user_id, auto=True,
                                                      exclude_prune=job.layout_id)
                job.backup_id, job.backup_name = meta["id"], meta["name"]
                job.add("info", f"Sicherung angelegt: {meta['name']}")
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"
                job.error = f"Automatische Sicherung fehlgeschlagen – nichts geändert: {err_text(exc)}"
                log.warning("Server-Layout: Sicherung vor dem Laden fehlgeschlagen (Guild %s)", guild.id, exc_info=exc)
                return
            if job.cancel_requested:
                job.status = "cancelled"
                job.add("info", "Abgebrochen vor dem ersten Schritt – nichts geändert.")
                return
            reason = f"Server-Layout ‚{layout['name']}‘ geladen von {job.user_name}"
            runner = Runner(guild, layout, plan, job, reason=reason, pause=self.OP_PAUSE,
                            pause_threshold=self.PAUSE_THRESHOLD)
            try:
                await runner.run()
            finally:
                if runner.image_state:
                    async with self.config.guild(guild).applied_images() as st:
                        st.update(runner.image_state)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.add("info", "Abgebrochen (Cog entladen).")
            raise
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = err_text(exc)
            log.exception("Server-Layout: Laden auf Guild %s fehlgeschlagen", guild.id)
        finally:
            job.finished = time.time()
            job.step = {"done": "Fertig", "cancelled": "Abgebrochen"}.get(job.status, "Fehlgeschlagen")
            try:
                await self._store_report(guild.id, job)
                await self._notify(guild, job, notify)
            except Exception:  # noqa: BLE001
                log.exception("Server-Layout: Bericht konnte nicht gespeichert/gesendet werden")

    async def _store_report(self, guild_id: int, job: Job):
        async with self.config.guild_from_id(guild_id).reports() as reports:
            reports.insert(0, job.to_report())
            del reports[self.MAX_REPORTS:]

    def summary(self, lang, counts: dict) -> str:
        return t(lang, "summary", **{k: counts.get(k, 0) for k in ("created", "updated", "deleted", "skipped", "errors")})

    def report_text(self, lang, rep: dict) -> str:
        if rep.get("status") == "failed":
            return t(lang, "report_failed", name=rep["layout_name"], error=rep.get("error") or "?")[:1900]
        key = "report_done" if rep.get("status") == "done" else "report_cancelled"
        text = t(lang, key, name=rep["layout_name"], summary=self.summary(lang, rep["counts"]),
                 backup=rep.get("backup_name") or "—")
        errs = [x["msg"] for x in rep.get("log", []) if x["lvl"] == "err"][:5]
        if errs:
            text += "\n" + t(lang, "report_errors", lines="\n".join(f"• {e[:180]}" for e in errs))
        return text[:1990]

    async def _notify(self, guild, job: Job, channel):
        if channel is None:
            return
        lang = await self.config.guild(guild).language()
        try:
            await channel.send(self.report_text(lang, job.to_report()),
                               allowed_mentions=discord.AllowedMentions.none())
        except (discord.HTTPException, AttributeError):
            pass    # Kanal gelöscht (z. B. beim Angleichen) oder keine Rechte – Bericht steht im Dashboard

    def cancel(self, guild_id: int) -> bool:
        job = self._jobs.get(int(guild_id))
        if not job or not job.running:
            return False
        job.cancel_requested = True
        return True

    async def reports(self, guild) -> list:
        return await self.config.guild(guild).reports()

    # ----------------------------------------------------------------- #
    #  Befehle
    # ----------------------------------------------------------------- #
    async def _lang(self, ctx) -> str:
        return await self.config.guild(ctx.guild).language() if ctx.guild else DEFAULT_LANGUAGE

    async def _is_owner(self, ctx) -> bool:
        return await self.bot.is_owner(ctx.author)

    def _parts_text(self, lang, parts) -> str:
        return ", ".join(t(lang, f"part_{p}") for p in parts)

    async def _visible(self, ctx, meta) -> bool:
        return await self._is_owner(ctx) or meta.get("source_id") == ctx.guild.id

    async def _find_or_reply(self, ctx, name: str, lang: str) -> dict | None:
        meta = await self.find(name)
        if meta is None or not await self._visible(ctx, meta):
            await ctx.send(t(lang, "not_found", name=name[:80], prefix=ctx.clean_prefix),
                           allowed_mentions=discord.AllowedMentions.none())
            return None
        return meta

    @commands.hybrid_group(name="layout")
    @commands.guild_only()
    async def layout_group(self, ctx: commands.Context):
        """Server-Layout speichern und laden · Save and load server layouts"""

    @layout_group.command(name="save")
    @commands.admin_or_permissions(administrator=True)
    async def layout_save(self, ctx: commands.Context, *, args: str):
        """Layout dieses Servers speichern · Save this server's layout

        `<name> [rollen,kanäle,einstellungen]` – ohne Teile werden alle gespeichert.
        """
        lang = await self._lang(ctx)
        name, _mode, parts = parse_args(args, allow_mode=False)
        if not name:
            return await ctx.send(t(lang, "name_missing", prefix=ctx.clean_prefix))
        async with ctx.typing():
            try:
                meta, notes = await self.save_layout(ctx.guild, name, parts or L.PARTS, creator_id=ctx.author.id)
            except LoadError as exc:
                return await ctx.send(t(lang, exc.key, **exc.kwargs), allowed_mentions=discord.AllowedMentions.none())
            except L.LayoutError as exc:
                return await ctx.send(t(lang, "import_invalid", error=str(exc)))
        text = t(lang, "saved", name=meta["name"], parts=self._parts_text(lang, meta["parts"]), size=fmt_size(meta["size"]),
                 **meta["counts"])
        if notes:
            text += "\n" + t(lang, "notes", notes="\n".join(f"• {n}" for n in notes))
        await ctx.send(text[:1990], allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="list")
    @commands.admin_or_permissions(administrator=True)
    async def layout_list(self, ctx: commands.Context):
        """Gespeicherte Layouts anzeigen · List saved layouts"""
        lang = await self._lang(ctx)
        owner = await self._is_owner(ctx)
        items = [m for m in await self.layouts() if owner or m.get("source_id") == ctx.guild.id]
        if not items:
            return await ctx.send(t(lang, "list_empty"))
        lines = [t(lang, "list_header")]
        for m in items:
            lines.append(t(lang, "list_row", name=m["name"], source=m.get("source_name") or "?",
                           date=fmt_date(m.get("created")), parts=self._parts_text(lang, m.get("parts") or []),
                           size=fmt_size(m.get("size") or 0), auto=t(lang, "auto") if m.get("auto") else ""))
        from redbot.core.utils.chat_formatting import pagify
        for page in pagify("\n".join(lines), page_length=1900):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="info")
    @commands.admin_or_permissions(administrator=True)
    async def layout_info(self, ctx: commands.Context, *, name: str):
        """Details zu einem Layout · Details of a layout"""
        lang = await self._lang(ctx)
        meta = await self._find_or_reply(ctx, name, lang)
        if meta is None:
            return
        creator = f"<@{meta['creator_id']}>" if meta.get("creator_id") else "—"
        emb = discord.Embed(title=t(lang, "info_title", name=meta["name"])[:256], colour=discord.Colour.blurple(),
                            description=t(lang, "info_body", source=meta.get("source_name") or "?",
                                          source_id=meta.get("source_id") or 0, date=fmt_date(meta.get("created")),
                                          creator=creator, parts=self._parts_text(lang, meta.get("parts") or []),
                                          size=fmt_size(meta.get("size") or 0), **(meta.get("counts") or
                                          {"roles": 0, "categories": 0, "channels": 0}))[:4000])
        await ctx.send(embed=emb, allowed_mentions=discord.AllowedMentions.none())

    def preview_embed(self, lang, meta, guild, plan) -> discord.Embed:
        c = plan["counts"]
        emb = discord.Embed(
            title=t(lang, "preview_title", name=meta["name"], guild=guild.name)[:256],
            description=t(lang, "preview_desc", mode=t(lang, f"mode_{plan['mode']}"),
                          parts=self._parts_text(lang, plan["parts"]), **{k: c[k] for k in ("create", "update", "delete", "skip")}),
            colour=discord.Colour.red() if plan["blockers"] else (discord.Colour.orange() if plan["mode"] == "exact"
                                                                  else discord.Colour.green()))
        lines = []
        for it in plan["items"]:
            if it["op"] == "skip":
                continue
            det = "; ".join(it["details"])
            lines.append(f"{OP_ICON[it['op']]} {SEC_LABEL.get(it['sec'], '')} **{discord.utils.escape_markdown(it['label'])}**"
                         + (f" – {det[:120]}" if det else ""))
        emb.add_field(name=t(lang, "preview_items"), value=self._fit(lines, lang) or t(lang, "preview_nothing"), inline=False)
        skips = [f"⏭️ {discord.utils.escape_markdown(it['label'])} – {it['reason']}" for it in plan["items"] if it["op"] == "skip"]
        if skips:
            emb.add_field(name="⏭️", value=self._fit(skips, lang), inline=False)
        if plan["warnings"]:
            emb.add_field(name=t(lang, "preview_warnings"), value=self._fit([f"• {w}" for w in plan["warnings"]], lang),
                          inline=False)
        if plan["blockers"]:
            emb.add_field(name=t(lang, "preview_blockers"), value=self._fit([f"• {b}" for b in plan["blockers"]], lang),
                          inline=False)
        return emb

    @staticmethod
    def _fit(lines: list, lang, limit: int = 1000) -> str:
        out, used = [], 0
        for i, line in enumerate(lines):
            line = line[:300]
            if used + len(line) + 1 > limit - 60:
                out.append(t(lang, "preview_more", n=len(lines) - i))
                break
            out.append(line)
            used += len(line) + 1
        return "\n".join(out)[:1024]

    @layout_group.command(name="preview")
    @commands.is_owner()
    async def layout_preview(self, ctx: commands.Context, *, args: str):
        """Vorschau: was würde sich ändern? · Preview the changes

        `<name> [ergänzen|angleichen] [rollen,kanäle,einstellungen]`
        """
        lang = await self._lang(ctx)
        name, mode, parts = parse_args(args)
        meta = await self._find_or_reply(ctx, name, lang)
        if meta is None:
            return
        _layout, plan = await self.preview(ctx.guild, meta["id"], mode or "merge", parts, ctx.channel.id)
        await ctx.send(embed=self.preview_embed(lang, meta, ctx.guild, plan), allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="load", with_app_command=False)
    @commands.is_owner()
    async def layout_load(self, ctx: commands.Context, *, args: str):
        """Layout auf diesen Server laden (mit Vorschau + Bestätigung) · Load a layout onto this server

        `<name> [ergänzen|angleichen] [rollen,kanäle,einstellungen]`
        """
        from .views import ConfirmView
        lang = await self._lang(ctx)
        name, mode, parts = parse_args(args)
        mode = mode or "merge"
        meta = await self._find_or_reply(ctx, name, lang)
        if meta is None:
            return
        if self.running(ctx.guild.id):
            return await ctx.send(t(lang, "busy", prefix=ctx.clean_prefix))
        _layout, plan = await self.preview(ctx.guild, meta["id"], mode, parts, ctx.channel.id)
        emb = self.preview_embed(lang, meta, ctx.guild, plan)
        if plan["blockers"] or not plan["actionable"]:
            return await ctx.send(embed=emb, allowed_mentions=discord.AllowedMentions.none())
        view = ConfirmView(self, ctx, lang, meta, plan)
        view.message = await ctx.send(t(lang, f"confirm_{plan['mode']}"), embed=emb, view=view,
                                      allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="delete")
    @commands.is_owner()
    async def layout_delete(self, ctx: commands.Context, *, name: str):
        """Layout löschen · Delete a layout"""
        lang = await self._lang(ctx)
        meta = await self._find_or_reply(ctx, name, lang)
        if meta is None:
            return
        await self.delete_layout(meta["id"])
        await ctx.send(t(lang, "deleted", name=meta["name"]), allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="rename")
    @commands.is_owner()
    async def layout_rename(self, ctx: commands.Context, name: str, *, new_name: str):
        """Layout umbenennen (alter Name in Anführungszeichen) · Rename a layout"""
        lang = await self._lang(ctx)
        meta = await self._find_or_reply(ctx, name, lang)
        if meta is None:
            return
        try:
            new = await self.rename_layout(meta["id"], new_name)
        except LoadError as exc:
            return await ctx.send(t(lang, exc.key, **exc.kwargs), allowed_mentions=discord.AllowedMentions.none())
        await ctx.send(t(lang, "renamed", old=meta["name"], new=new["name"]), allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="export")
    @commands.admin_or_permissions(administrator=True)
    async def layout_export(self, ctx: commands.Context, *, name: str):
        """Layout als Datei senden · Send a layout as file"""
        lang = await self._lang(ctx)
        meta = await self._find_or_reply(ctx, name, lang)
        if meta is None:
            return
        filename, raw = await self.export_bytes(meta["id"])
        limit = int(getattr(ctx.guild, "filesize_limit", 8 * 1024 * 1024) or 8 * 1024 * 1024)
        if len(raw) > limit:
            return await ctx.send(t(lang, "export_too_big", size=fmt_size(len(raw))))
        await ctx.send(t(lang, "export_ok", name=meta["name"]), file=discord.File(io.BytesIO(raw), filename=filename),
                       allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="import", with_app_command=False)
    @commands.is_owner()
    async def layout_import(self, ctx: commands.Context, *, name: str = ""):
        """Layout-Datei (Anhang) importieren · Import a layout file (attachment)"""
        lang = await self._lang(ctx)
        atts = list(getattr(ctx.message, "attachments", None) or [])
        if not atts:
            return await ctx.send(t(lang, "import_no_file"))
        att = atts[0]
        if int(getattr(att, "size", 0) or 0) > L.MAX_FILE_BYTES:
            return await ctx.send(t(lang, "import_too_big", max=fmt_size(L.MAX_FILE_BYTES)))
        try:
            raw = await att.read()
            meta = await self.import_bytes(raw, creator_id=ctx.author.id, name=name or None)
        except L.LayoutError as exc:
            return await ctx.send(t(lang, "import_invalid", error=str(exc))[:1990], allowed_mentions=discord.AllowedMentions.none())
        await ctx.send(t(lang, "imported", name=meta["name"], parts=self._parts_text(lang, meta["parts"]), **meta["counts"]),
                       allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="status")
    @commands.admin_or_permissions(administrator=True)
    async def layout_status(self, ctx: commands.Context):
        """Fortschritt bzw. letzter Bericht · Progress or last report"""
        lang = await self._lang(ctx)
        job = self.job(ctx.guild.id)
        if job and job.running:
            return await ctx.send(t(lang, "status_running", name=job.layout_name, mode=t(lang, f"mode_{job.mode}"),
                                    done=job.done, total=job.total, percent=job.percent, step=job.step)[:1990],
                                  allowed_mentions=discord.AllowedMentions.none())
        reports = await self.reports(ctx.guild)
        if not reports:
            return await ctx.send(t(lang, "status_none"))
        r = reports[0]
        await ctx.send(t(lang, "status_last", name=r["layout_name"], mode=t(lang, f"mode_{r['mode']}"),
                         status=t(lang, f"st_{r['status']}"), date=f"<t:{int(r['finished'])}:f>",
                         summary=self.summary(lang, r["counts"]))[:1990], allowed_mentions=discord.AllowedMentions.none())

    @layout_group.command(name="cancel")
    @commands.is_owner()
    async def layout_cancel(self, ctx: commands.Context):
        """Laufenden Ladevorgang abbrechen · Cancel the running load"""
        lang = await self._lang(ctx)
        await ctx.send(t(lang, "cancel_ok" if self.cancel(ctx.guild.id) else "cancel_none"))

    @layout_group.command(name="language")
    @commands.admin_or_permissions(administrator=True)
    async def layout_language(self, ctx: commands.Context, code: str):
        """Sprache der Bot-Antworten (de/en) · Language of bot replies"""
        code = code.lower().strip()
        if code not in LANGUAGES:
            return await ctx.send(t(await self._lang(ctx), "lang_unknown", code=code[:10], langs=", ".join(LANGUAGES)))
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", name=LANGUAGES[code]))
