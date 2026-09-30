"""Server-Layout: Ausführung eines Plans (Hintergrund-Task) mit Fortschritt, Protokoll und Abbrechen.

Reihenfolge: Rollen -> Rollen-Reihenfolge (edit_role_positions in Blöcken) -> Kategorien -> Kanäle (inkl.
Überschreibungen) -> Kanal-Reihenfolge -> Server-Einstellungen -> Löschungen (Kanäle, Kategorien, Rollen).
Jeder Schritt fängt seine Fehler selbst ab und protokolliert sie – ein Fehler bricht den Lauf nicht ab.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time

import discord

from . import layout as L
from . import planner as P

log = logging.getLogger("red.red-cogs.serverlayout")

BLOCK = 100            # Rollen/Kanäle je Positions-Anfrage
MAX_LOG = 400          # Protokollzeilen je Bericht

PHASE = {"role_create": 1, "role_update": 1, "everyone": 1, "role_order": 2, "cat_create": 3, "cat_update": 3,
         "chan_create": 4, "chan_update": 4, "chan_order": 5, "settings": 6, "image": 6,
         "chan_delete": 7, "cat_delete": 8, "role_delete": 9}
PHASE_LABEL = {1: "Rollen", 2: "Rollen-Reihenfolge", 3: "Kategorien", 4: "Kanäle", 5: "Kanal-Reihenfolge",
               6: "Server-Einstellungen", 7: "Kanäle löschen", 8: "Kategorien löschen", 9: "Rollen löschen"}


class Job:
    """Ein Ladevorgang auf einem Server (höchstens einer gleichzeitig pro Server)."""

    def __init__(self, guild_id: int, layout_id: str, layout_name: str, mode: str, parts: list,
                 user_id: int, user_name: str):
        self.id = secrets.token_hex(4)
        self.guild_id = int(guild_id)
        self.layout_id = layout_id
        self.layout_name = layout_name
        self.mode = mode
        self.parts = list(parts)
        self.user_id = int(user_id)
        self.user_name = str(user_name)
        self.started = time.time()
        self.finished: float | None = None
        self.status = "running"          # running / done / cancelled / failed
        self.step = "Wird vorbereitet …"
        self.total = 0
        self.done = 0
        self.log: list[dict] = []
        self.counts = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0, "errors": 0}
        self.cancel_requested = False
        self.backup_id: str | None = None
        self.backup_name: str | None = None
        self.error: str | None = None
        self.task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.status == "running"

    @property
    def percent(self) -> int:
        if not self.total:
            return 0 if self.running else 100
        return max(0, min(100, int(self.done * 100 / self.total)))

    def add(self, lvl: str, text: str, sec: str = ""):
        self.log.append({"t": round(time.time(), 1), "lvl": lvl, "sec": sec, "msg": str(text)[:500]})

    def status_json(self) -> dict:
        return {"running": self.running, "status": self.status, "done": self.done, "total": self.total,
                "percent": self.percent, "step": self.step, "counts": dict(self.counts)}

    def to_report(self) -> dict:
        lines = self.log
        if len(lines) > MAX_LOG:
            errs = [x for x in lines if x["lvl"] == "err"][:MAX_LOG // 2]
            rest = [x for x in lines if x["lvl"] != "err"][:MAX_LOG - len(errs)]
            lines = sorted(errs + rest, key=lambda x: x["t"]) + [
                {"t": 0, "lvl": "info", "sec": "", "msg": f"… {len(self.log) - MAX_LOG} weitere Zeilen gekürzt"}]
        return {"id": self.id, "layout_id": self.layout_id, "layout_name": self.layout_name, "mode": self.mode,
                "parts": self.parts, "user_id": self.user_id, "user_name": self.user_name,
                "started": int(self.started), "finished": int(self.finished or time.time()), "status": self.status,
                "total": self.total, "done": self.done, "counts": dict(self.counts), "backup_id": self.backup_id,
                "backup_name": self.backup_name, "error": self.error, "log": lines}


def err_text(exc: BaseException) -> str:
    if isinstance(exc, discord.Forbidden):
        return "Keine Rechte (Discord 403)"
    if isinstance(exc, discord.HTTPException):
        return f"Discord-Fehler {getattr(exc, 'status', '?')}: {str(getattr(exc, 'text', '') or exc)[:200]}"
    return f"{type(exc).__name__}: {exc}"[:300]


def _enum(cls, value, default=None):
    try:
        return cls(value)
    except (ValueError, TypeError):
        return default


class Runner:
    def __init__(self, guild, layout: dict, plan: dict, job: Job, *, reason: str, pause: float = 0.25,
                 pause_threshold: int = 25):
        self.guild = guild
        self.layout = layout
        self.plan = plan
        self.job = job
        self.reason = reason[:500]
        self.pause = pause
        self.pause_threshold = pause_threshold
        self.new_roles: dict[int, object] = {}
        self.new_cats: dict[int, object] = {}
        self.new_chans: dict[int, object] = {}
        self.image_state: dict[str, dict] = {}     # gesetzte Bilder: {"icon": {"sha", "key"}}

    # --------------------------------------------------------------- #
    async def run(self):
        job = self.job
        items = self.plan["items"]
        for it in items:
            if it["op"] == "skip":
                job.counts["skipped"] += 1
                job.add("skip", f"{it['label']}: übersprungen – {it['reason']}", it["sec"])
        work = [it for it in items if it["op"] in ("create", "update", "delete") and it["do"].get("a")]
        work.sort(key=lambda it: PHASE.get(it["do"]["a"], 10))
        job.total = len(work)
        pause = self.pause if len(work) > self.pause_threshold else 0
        for it in work:
            if job.cancel_requested:
                job.status = "cancelled"
                job.add("info", f"Abgebrochen – {job.done} von {job.total} Schritten ausgeführt.")
                return
            phase = PHASE.get(it["do"]["a"], 10)
            job.step = f"{PHASE_LABEL.get(phase, '')}: {it['label']}"
            try:
                msg = await self.do(it)
                if msg is not False:
                    key = {"create": "created", "update": "updated", "delete": "deleted"}[it["op"]]
                    job.counts[key] += 1
                    verb = {"create": "angelegt", "update": "geändert", "delete": "gelöscht"}[it["op"]]
                    job.add("ok", f"{it['label']}: {verb}" + (f" – {msg}" if msg else ""), it["sec"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 – je Schritt abfangen, weitermachen
                job.counts["errors"] += 1
                job.add("err", f"{it['label']}: {err_text(exc)}", it["sec"])
                if not isinstance(exc, discord.HTTPException):
                    log.warning("Server-Layout: Schritt %s fehlgeschlagen", it["do"].get("a"), exc_info=exc)
            job.done += 1
            if pause:
                await asyncio.sleep(pause)
        job.status = "done"

    # --------------------------------------------------------------- #
    async def do(self, it):
        a = it["do"]["a"]
        return await getattr(self, f"_{a}")(it["do"])

    def _role(self, ref):
        kind, rid = ref[0], ref[1]
        if kind == "new":
            return self.new_roles.get(int(rid))
        if int(rid) == self.guild.id:
            return self.guild.default_role
        return self.guild.get_role(int(rid))

    def _overwrites(self, ow_list) -> dict:
        out = {}
        for kind, oid, allow, deny in ow_list or []:
            if kind == "member":
                target = (self.guild.get_member(int(oid)) if hasattr(self.guild, "get_member") else None) \
                    or discord.Object(id=int(oid))
            else:
                target = self._role((kind, oid))
            if target is None:
                name = self.layout["roles"][int(oid)]["name"] if kind == "new" else str(oid)
                self.job.add("skip", f"Überschreibung für „{name}“ übersprungen – Rolle wurde nicht angelegt")
                continue
            out[target] = discord.PermissionOverwrite.from_pair(discord.Permissions(int(allow)), discord.Permissions(int(deny)))
        return out

    # --- Rollen ---------------------------------------------------------
    async def _role_create(self, d):
        role = await self.guild.create_role(name=d["name"], permissions=discord.Permissions(int(d["permissions"])),
                                            colour=discord.Colour(int(d["color"])), hoist=bool(d["hoist"]),
                                            mentionable=bool(d["mentionable"]), reason=self.reason)
        self.new_roles[int(d["idx"])] = role
        return ""

    async def _role_update(self, d):
        role = self.guild.get_role(int(d["id"]))
        if role is None:
            raise RuntimeError("Rolle nicht mehr vorhanden")
        f = d["fields"]
        kw = {}
        if "color" in f:
            kw["colour"] = discord.Colour(int(f["color"]))
        if "permissions" in f:
            kw["permissions"] = discord.Permissions(int(f["permissions"]))
        for k in ("hoist", "mentionable"):
            if k in f:
                kw[k] = bool(f[k])
        await role.edit(reason=self.reason, **kw)
        return ""

    async def _everyone(self, d):
        await self.guild.default_role.edit(permissions=discord.Permissions(int(d["permissions"])), reason=self.reason)
        return ""

    async def _fresh_roles(self):
        try:
            return await self.guild.fetch_roles()
        except Exception:  # noqa: BLE001
            return list(self.guild.roles)

    async def _role_order(self, d):
        wanted = []
        for key in (L.role_key(*k) for k in L.dup_keys(r["name"] for r in self.layout.get("roles") or [])):
            ref = self.plan["rolemap"].get(key)
            role = self._role(ref) if ref else None
            if role is not None:
                wanted.append(role.id)
        me = self.guild.me
        total = 0
        for _round in range(2):          # Blöcke + eine Kontrollrunde
            roles = await self._fresh_roles()
            top_id = me.top_role.id
            top = next((r.position for r in roles if r.id == top_id), me.top_role.position)
            current = [(r.id, r.position) for r in roles if r.id != self.guild.id]
            changes = P.role_order(current, wanted, top, {r.id for r in self.new_roles.values()})
            if not changes:
                break
            ids = sorted(changes, key=lambda rid: changes[rid])
            for i in range(0, len(ids), BLOCK):
                block = {discord.Object(id=rid): changes[rid] for rid in ids[i:i + BLOCK]}
                await self.guild.edit_role_positions(block, reason=self.reason)
            total += len(changes)
            if len(ids) <= BLOCK:
                break
        if not total:
            self.job.add("info", "Rollen-Reihenfolge passte bereits", "order")
            return False
        return f"{total} Rolle(n) verschoben"

    # --- Kategorien -----------------------------------------------------
    async def _cat_create(self, d):
        cat = await self.guild.create_category(d["name"], overwrites=self._overwrites(d["ow"]), reason=self.reason)
        self.new_cats[int(d["idx"])] = cat
        return ""

    async def _cat_update(self, d):
        cat = self.guild.get_channel(int(d["id"]))
        if cat is None:
            raise RuntimeError("Kategorie nicht mehr vorhanden")
        await cat.edit(overwrites=self._overwrites(d["ow"]), reason=self.reason)
        return ""

    def _category(self, idx):
        if idx is None:
            return None, True
        idx = int(idx)
        if idx in self.new_cats:
            return self.new_cats[idx], True
        cid = (self.plan.get("catmap") or {}).get(idx)
        if cid:
            cat = self.guild.get_channel(int(cid))
            return cat, cat is not None
        return None, False

    # --- Kanäle ---------------------------------------------------------
    async def _chan_create(self, d):
        e = self.layout["channels"][int(d["idx"])]
        cat, ok = self._category(d.get("cat"))
        if not ok:
            raise RuntimeError("Kategorie konnte nicht angelegt werden – Kanal übersprungen")
        kind = d["kind"]
        ow = self._overwrites(d["ow"])
        limit = int(getattr(self.guild, "bitrate_limit", 96000) or 96000)
        g = self.guild
        if kind in ("text", "news"):
            kw = dict(category=cat, news=(kind == "news"), slowmode_delay=e.get("slowmode", 0), nsfw=e["nsfw"],
                      overwrites=ow, reason=self.reason, default_auto_archive_duration=e.get("default_auto_archive", 1440),
                      default_thread_slowmode_delay=e.get("default_thread_slowmode", 0))
            if e.get("topic"):
                kw["topic"] = e["topic"]
            ch = await g.create_text_channel(e["name"], **kw)
        elif kind in ("voice", "stage"):
            kw = dict(category=cat, bitrate=min(int(e.get("bitrate", 64000)), limit),
                      user_limit=int(e.get("user_limit", 0)) if kind == "stage" else min(int(e.get("user_limit", 0)), 99),
                      overwrites=ow, reason=self.reason, rtc_region=e.get("rtc_region"),
                      video_quality_mode=_enum(discord.VideoQualityMode, e.get("video_quality", 1), discord.VideoQualityMode.auto))
            if kind == "voice":
                ch = await g.create_voice_channel(e["name"], nsfw=e["nsfw"], **kw)
            else:
                ch = await g.create_stage_channel(e["name"], **kw)
        else:
            kw = dict(category=cat, slowmode_delay=e.get("slowmode", 0), nsfw=e["nsfw"], overwrites=ow, reason=self.reason,
                      default_auto_archive_duration=e.get("default_auto_archive", 1440),
                      default_thread_slowmode_delay=e.get("default_thread_slowmode", 0),
                      default_layout=_enum(discord.ForumLayoutType, e.get("default_layout", 0), discord.ForumLayoutType.not_set),
                      available_tags=[discord.ForumTag(name=t["name"], emoji=t["emoji"], moderated=t["moderated"])
                                      for t in e.get("tags", [])])
            if e.get("topic"):
                kw["topic"] = e["topic"]
            if e.get("default_sort_order") is not None:
                kw["default_sort_order"] = _enum(discord.ForumOrderType, e["default_sort_order"])
            if e.get("default_reaction"):
                kw["default_reaction_emoji"] = e["default_reaction"]
            if e.get("media"):
                kw["media"] = True
            ch = await g.create_forum(e["name"], **kw)
        self.new_chans[int(d["idx"])] = ch
        return "" if kind == e["type"] else f"als {P.KIND_LABELS[kind]} (Community fehlt)"

    async def _chan_update(self, d):
        ch = self.guild.get_channel(int(d["id"]))
        if ch is None:
            raise RuntimeError("Kanal nicht mehr vorhanden")
        f = dict(d["fields"])
        kw = {}
        if "type" in f:
            kw["type"] = discord.ChannelType.news if f.pop("type") == "news" else discord.ChannelType.text
        if "video_quality_mode" in f:
            kw["video_quality_mode"] = _enum(discord.VideoQualityMode, f.pop("video_quality_mode"), discord.VideoQualityMode.auto)
        if "default_layout" in f:
            kw["default_layout"] = _enum(discord.ForumLayoutType, f.pop("default_layout"), discord.ForumLayoutType.not_set)
        if "default_sort_order" in f:
            kw["default_sort_order"] = _enum(discord.ForumOrderType, f.pop("default_sort_order"))
        if "tags" in f:
            tags = []
            for t in f.pop("tags"):
                tag = discord.ForumTag(name=t["name"], emoji=t.get("emoji"), moderated=bool(t.get("moderated")))
                if t.get("id"):
                    tag.id = int(t["id"])     # vorhandenen Tag behalten (Beiträge verlieren ihn nicht)
                tags.append(tag)
            kw["available_tags"] = tags
        kw.update(f)
        if d.get("ow") is not None:
            kw["overwrites"] = self._overwrites(d["ow"])
        await ch.edit(reason=self.reason, **kw)
        return ""

    async def _chan_order(self, d):
        g = self.guild
        cmap = self.plan.get("catmap") or {}
        chmap = self.plan.get("chanmap") or {}
        wanted = []
        for i in range(len(self.layout.get("categories") or [])):
            obj = self.new_cats.get(i)
            cid = obj.id if obj is not None else cmap.get(i)
            if cid:
                wanted.append(int(cid))
        for i in range(len(self.layout.get("channels") or [])):
            obj = self.new_chans.get(i)
            cid = obj.id if obj is not None else chmap.get(i)
            if cid:
                wanted.append(int(cid))
        changes = P.channel_order(P.channel_groups(g), wanted)
        if not changes:
            self.job.add("info", "Kanal-Reihenfolge passte bereits", "order")
            return False
        payload = [{"id": cid, "position": pos} for cid, pos in changes.items()]
        http = getattr(getattr(g, "_state", None), "http", None)
        if http is not None and hasattr(http, "bulk_channel_update"):
            for i in range(0, len(payload), BLOCK):
                await http.bulk_channel_update(g.id, payload[i:i + BLOCK], reason=self.reason)
        else:
            for p in payload:
                ch = g.get_channel(p["id"])
                if ch is not None:
                    await ch.edit(position=p["position"], reason=self.reason)
        return f"{len(payload)} Kanäle/Kategorien verschoben"

    # --- Server-Einstellungen ---------------------------------------------
    def _resolve_ref(self, ref):
        if ref is None:
            return None
        want = L.ref_tuple(ref)
        for key, ch in L.target_channel_keys(self.guild):
            if key == want:
                return ch
        raise LookupError(f"Kanal „{ref['name']}“ nicht gefunden")

    async def _settings(self, d):
        kw = {}
        notes = []
        for key, value in d["fields"].items():
            try:
                if key in ("afk_channel", "system_channel", "rules_channel", "public_updates_channel"):
                    kw[key] = self._resolve_ref(value)
                elif key == "verification_level":
                    kw[key] = discord.VerificationLevel(int(value))
                elif key == "explicit_content_filter":
                    kw[key] = discord.ContentFilter(int(value))
                elif key == "default_notifications":
                    kw[key] = discord.NotificationLevel(int(value))
                elif key == "system_channel_flags":
                    kw[key] = discord.SystemChannelFlags._from_value(int(value))
                else:
                    kw[key] = value
            except (LookupError, ValueError) as exc:
                notes.append(f"{key}: {exc}")
        if kw:
            try:
                await self.guild.edit(reason=self.reason, **kw)
            except discord.HTTPException as exc:
                # Einzeln nachversuchen, damit ein Feld (z. B. Community-Kanal) nicht alles blockiert
                if len(kw) == 1:
                    raise
                ok = 0
                for key, value in kw.items():
                    try:
                        await self.guild.edit(reason=self.reason, **{key: value})
                        ok += 1
                    except discord.HTTPException as exc2:
                        notes.append(f"{key}: {err_text(exc2)}")
                if not ok:
                    raise exc
        for n in notes:
            self.job.counts["errors"] += 1
            self.job.add("err", f"Server-Einstellungen: {n}", "settings")
        return ""

    async def _image(self, d):
        key = d["key"]
        raw = L.image_bytes((self.layout.get("settings") or {}).get(key))
        if not raw:
            raise RuntimeError("Bild fehlt im Layout")
        res = await self.guild.edit(reason=self.reason, **{key: raw})
        asset = getattr(res if res is not None else self.guild, key, None)
        if asset is not None and getattr(asset, "key", None):
            self.image_state[key] = {"sha": L.image_sha((self.layout.get("settings") or {}).get(key)),
                                     "key": str(asset.key)}
        return ""

    # --- Löschen -----------------------------------------------------------
    async def _chan_delete(self, d):
        ch = self.guild.get_channel(int(d["id"]))
        if ch is None:
            self.job.add("skip", f"Kanal {d['id']} war bereits gelöscht")
            return False
        await ch.delete(reason=self.reason)
        return ""

    _cat_delete = _chan_delete

    async def _role_delete(self, d):
        role = self.guild.get_role(int(d["id"]))
        if role is None:
            self.job.add("skip", f"Rolle {d['id']} war bereits gelöscht")
            return False
        await role.delete(reason=self.reason)
        return ""
