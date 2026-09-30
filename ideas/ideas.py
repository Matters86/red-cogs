from __future__ import annotations

import asyncio
import csv
import difflib
import io
import logging
import math
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify

from .strings import (CLOSED_STATUSES, DEFAULT_LANGUAGE, LANGUAGES, OPEN_STATUSES, STATUS_COLOR, STATUS_EMOJI,
                      STATUSES, normalize_status, status_label, t)
from .views import MAX_DESC, MAX_TITLE, CategoryView, IdeaModal, PanelView

log = logging.getLogger("red.red-cogs.ideas")

MAX_CATEGORIES = 10
MAX_CATEGORY_LEN = 20          # = Länge eines Forum-Tag-Namens
FORUM_TAG_LIMIT = 20           # Discord: max. Tags je Forum
MAX_APPLIED_TAGS = 5           # Discord: max. Tags je Beitrag
MAX_THREAD_NAME = 100
MAX_COMMENT = 1500
MAX_HISTORY = 60
SIMILARITY = 0.82              # Duplikat-Hinweis ab dieser Ähnlichkeit (difflib) der Titel
_UNSET = object()
_NONE = discord.AllowedMentions.none()

_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_duration(text):
    """Fallback, falls der Poll-Cog keine ``parse_duration`` hat (gleiches Format: 30m, 2h, 1d12h)."""
    matches = _DURATION_RE.findall((text or "").strip().lower())
    total = sum(int(n) * _DURATION_UNITS[u] for n, u in matches)
    return total or None


def _norm_title(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", (text or "").casefold()).split())


def thread_name(nr: int, title: str) -> str:
    return f"#{nr} · {title}"[:MAX_THREAD_NAME]


def thread_url(guild_id, thread_id) -> str | None:
    return f"https://discord.com/channels/{guild_id}/{thread_id}" if thread_id else None


class Ideas(commands.Cog):
    """Ideen-Sammler: eigenes Forum, Einreichen per Formular, Status-Workflow fürs Team, Umfragen aus Ideen."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=417305926681, force_registration=True)
        self.config.register_guild(
            language="de",
            forum_id=None,              # Ideen-Forum (discord.ForumChannel)
            panel_thread_id=None,       # angepinnter Beitrag „💡 Idee einreichen“
            panel_message_id=None,
            categories=[],              # optionale Kategorien (max. 10, je max. 20 Zeichen)
            category_tags=True,         # Kategorien zusätzlich als Forum-Tags
            anonymous=False,            # Einreicher im Beitrag nicht nennen
            follow_submitter=True,      # Einreicher dem Beitrag hinzufügen (bekommt Antworten mit)
            dm_status=True,             # DM an den Einreicher bei Statuswechsel
            archive_closed=True,        # Umgesetzt/Abgelehnt -> Beitrag schließen + archivieren
            cooldown_minutes=10,        # Wartezeit je Mitglied zwischen zwei Ideen
            max_open=5,                 # max. offene Ideen je Mitglied (0 = unbegrenzt)
            team_roles=[],              # dürfen Status setzen usw. (zusätzlich „Server verwalten“)
            manual_posts=True,          # manuell erstellte Forum-Beiträge als Idee übernehmen
            poll_review=True,           # Umfrage aus Ideen: „Neu“ -> „In Prüfung“
            member_page=True,           # „Mein Bereich → Ideen“ anzeigen
            blocked=[],                 # gesperrte Mitglieder (IDs)
            tag_ids={},                 # Status -> Forum-Tag-ID
            category_tag_ids={},        # Kategorie -> Forum-Tag-ID
            ideas={},                   # "nr" -> Datensatz
            counter=0,
        )
        self.config.register_member(last_submit=0)
        self._locks: dict[int, asyncio.Lock] = {}
        self._fresh_tags: dict[int, dict[int, discord.ForumTag]] = {}
        self._views: list[discord.ui.View] = []

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    def _now(self) -> float:
        return time.time()

    def _lock(self, guild_or_id) -> asyncio.Lock:
        gid = int(getattr(guild_or_id, "id", guild_or_id))
        return self._locks.setdefault(gid, asyncio.Lock())

    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    @staticmethod
    def forum_of(guild, data) -> Optional[discord.ForumChannel]:
        fid = data.get("forum_id")
        if not fid:
            return None
        ch = guild.get_channel(int(fid))
        return ch if isinstance(ch, discord.ForumChannel) else None

    async def get_forum(self, guild):
        return self.forum_of(guild, {"forum_id": await self.config.guild(guild).forum_id()})

    async def _thread(self, guild, thread_id):
        """Thread aus dem Cache – archivierte Beiträge sind dort oft nicht, dann per API."""
        if not thread_id:
            return None
        tid = int(thread_id)
        th = None
        for getter in ("get_thread", "get_channel_or_thread"):
            fn = getattr(guild, getter, None)
            if fn is not None:
                th = fn(tid)
                if th is not None:
                    break
        if th is None:
            try:
                th = await self.bot.fetch_channel(tid)
            except (discord.HTTPException, AttributeError):
                th = None
        return th if isinstance(th, discord.Thread) else None

    async def is_team(self, member) -> bool:
        """Owner, „Server verwalten“/Administrator oder eine der Team-Rollen."""
        if member is None:
            return False
        if await self.bot.is_owner(member):
            return True
        perms = getattr(member, "guild_permissions", None)
        if perms is not None and (perms.manage_guild or perms.administrator):
            return True
        guild = getattr(member, "guild", None)
        if guild is None:
            return False
        roles = {int(r) for r in await self.config.guild(guild).team_roles()}
        return any(r.id in roles for r in getattr(member, "roles", []))

    @staticmethod
    def resolve_category(categories, value):
        """(Kategorie in Originalschreibweise | None, gültig?) – leer = ohne Kategorie."""
        value = (value or "").strip()
        if not value or value == "__none__":
            return None, True
        for c in categories or []:
            if c.casefold() == value.casefold():
                return c, True
        return None, False

    @staticmethod
    def similar_ideas(ideas: dict, title: str, exclude: int | None = None) -> list[dict]:
        """Sehr ähnliche offene/abgeschlossene Ideen (einfacher Titel-Vergleich, max. 3)."""
        n = _norm_title(title)
        if len(n) < 3:
            return []
        hits = []
        for idea in (ideas or {}).values():
            if not isinstance(idea, dict) or idea.get("deleted") or idea.get("status") == "merged":
                continue
            if exclude is not None and idea.get("nr") == exclude:
                continue
            o = _norm_title(idea.get("title", ""))
            if not o:
                continue
            ratio = difflib.SequenceMatcher(None, n, o).ratio()
            if ratio >= SIMILARITY or (min(len(n), len(o)) >= 8 and (n in o or o in n)):
                hits.append((ratio, idea))
        hits.sort(key=lambda x: (-x[0], x[1].get("nr", 0)))
        return [i for _, i in hits[:3]]

    def idea_link(self, guild, idea) -> str | None:
        return thread_url(guild.id, idea.get("thread_id"))

    @staticmethod
    def open_count(ideas, uid) -> int:
        return sum(1 for i in (ideas or {}).values()
                   if isinstance(i, dict) and i.get("author_id") == uid and i.get("status") in OPEN_STATUSES
                   and not i.get("deleted"))

    # ----------------------------------------------------------------- #
    #  Red-Datenschutz-API
    # ----------------------------------------------------------------- #
    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Anonymisiert statt zu löschen: Ideen sind Beiträge im Community-Forum (die Discord-Nachrichten
        gehören nicht dem Cog). Entfernt werden die Einreicher-ID und der gespeicherte Name, die IDs/Namen
        der Person in Verlauf/Umfrage-Verknüpfungen (Team-Aktionen), der Sperrlisten-Eintrag und der
        Cooldown-Zeitstempel. Titel/Beschreibung bleiben, damit Nummern, Verlauf und Zusammenführungen
        für die Community nachvollziehbar bleiben."""
        uid = int(user_id)
        try:
            all_guilds = await self.config.all_guilds()
        except Exception:  # noqa: BLE001
            return
        for gid in list(all_guilds):
            try:
                async with self._lock(gid):
                    gconf = self.config.guild_from_id(gid)
                    async with gconf.ideas() as ideas:
                        for idea in ideas.values():
                            if not isinstance(idea, dict):
                                continue
                            if idea.get("author_id") == uid:
                                idea["author_id"] = 0
                                idea["author_name"] = ""
                            for h in idea.get("history") or []:
                                if isinstance(h, dict) and h.get("by") == uid:
                                    h["by"] = 0
                                    h["by_name"] = ""
                            for p in idea.get("polls") or []:
                                if isinstance(p, dict) and p.get("by") == uid:
                                    p["by"] = 0
                    async with gconf.blocked() as blocked:
                        blocked[:] = [b for b in blocked if int(b) != uid]
                    await self.config.member_from_ids(gid, uid).clear()
            except Exception:  # noqa: BLE001
                log.exception("Datenlöschung in Guild %s fehlgeschlagen", gid)

    # ----------------------------------------------------------------- #
    #  Laden / Entladen / Dashboard
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        add = getattr(self.bot, "add_view", None)
        if add is not None:
            try:
                view = PanelView(self, DEFAULT_LANGUAGE)
                add(view)                    # eine persistente View für alle Server (custom_id fest)
                self._views.append(view)
            except Exception:  # noqa: BLE001
                log.exception("Persistenter Ideen-Button konnte nicht registriert werden")

    async def cog_unload(self):
        for view in self._views:
            view.stop()
        self._views.clear()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        # Tagesgeschäft („Bedienen“): Status setzen, kommentieren, zusammenführen, bearbeiten und löschen
        # einzelner Ideen, Status für eine Auswahl, Umfrage aus Ideen. Einstellungen, Team-Rollen, Panel,
        # Forum anlegen, Tags und Sperren brauchen „Bearbeiten“.
        from .dashboard import OPERATE_FORMS
        extra = {"operate_forms": set(OPERATE_FORMS)} if hasattr(webcore, "OPERATE") else {}
        webcore.register_page(owner=self, slug="ideas", name="Ideen", icon="bi-lightbulb",
                              handler=self.dashboard_page, **extra)
        if hasattr(webcore, "register_member_page"):
            webcore.register_member_page(
                owner=self, slug="ideen", name="Ideen", icon="bi-lightbulb",
                description="Ideen einreichen und den Status deiner Ideen verfolgen",
                handler=self.member_page, visible=lambda g: self.config.guild(g).member_page(),
            )

    async def dashboard_page(self, request):
        from .dashboard import dashboard_handler
        return await dashboard_handler(self, request)

    async def member_page(self, request):
        from .member import member_page_handler
        return await member_page_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Forum-Tags
    # ----------------------------------------------------------------- #
    async def ensure_tags(self, guild, forum=None) -> list[str]:
        """Status-Tags (und ggf. Kategorie-Tags) im Forum sicherstellen. Gibt Warnungen zurück.

        Vorhandene Tags werden per ID oder Namen (jede Sprache) wiedererkannt, fehlende in EINEM
        ``forum.edit(available_tags=…)`` angelegt (``create_tag`` einzeln würde mit veraltetem Cache
        eben angelegte Tags wieder überschreiben). Rechte und das Limit von 20 Tags werden geprüft.
        """
        gconf = self.config.guild(guild)
        data = await gconf.all()
        lang = data.get("language", DEFAULT_LANGUAGE)
        forum = forum or self.forum_of(guild, data)
        if forum is None:
            return []
        tags = list(forum.available_tags)
        by_id = {tg.id: tg for tg in tags}
        by_name = {tg.name.casefold(): tg for tg in tags}
        tag_ids = {k: v for k, v in (data.get("tag_ids") or {}).items()}
        cat_ids = {k: v for k, v in (data.get("category_tag_ids") or {}).items()}
        cats = list(data.get("categories") or []) if data.get("category_tags") else []
        wanted = [(tag_ids, s, [status_label(lang, s)] + [status_label(lg, s) for lg in LANGUAGES],
                   status_label(lang, s), STATUS_EMOJI[s], True) for s in STATUSES]
        wanted += [(cat_ids, c, [c], c[:MAX_CATEGORY_LEN], None, False) for c in cats]
        missing = []
        for store, key, names, cname, emoji, moderated in wanted:
            tid = store.get(key)
            if tid and int(tid) in by_id:
                continue
            tag = next((by_name[n.casefold()] for n in names if n.casefold() in by_name), None)
            if tag is not None:
                store[key] = tag.id
                continue
            missing.append((store, key, cname, emoji, moderated))
        warnings = []
        if missing:
            me = getattr(guild, "me", None)
            perms = forum.permissions_for(me) if me is not None else None
            if perms is None or not perms.manage_channels:
                warnings.append(t(lang, "tag_warn_perm", tags=", ".join(m[2] for m in missing)))
            else:
                room = max(0, FORUM_TAG_LIMIT - len(tags))
                create, skipped = missing[:room], missing[room:]
                if skipped:
                    warnings.append(t(lang, "tag_warn_limit", tags=", ".join(m[2] for m in skipped)))
                if create:
                    new, seen = [], set()
                    for _, _, c, e, m in create:        # gleicher Name (z. B. Kategorie „Neu“) nur einmal anlegen
                        if c.casefold() not in seen:
                            seen.add(c.casefold())
                            new.append(discord.ForumTag(name=c, emoji=e, moderated=m))
                    fresh = []
                    try:
                        result = await forum.edit(available_tags=tags + new, reason="Ideen: Status-/Kategorie-Tags")
                        fresh = list(getattr(result, "available_tags", None) or [])
                    except discord.HTTPException:
                        log.warning("Forum-Tags konnten nicht angelegt werden (Guild %s)", guild.id, exc_info=True)
                    fresh_by_name = {tg.name.casefold(): tg for tg in fresh if getattr(tg, "id", 0)}
                    failed = []
                    for store, key, cname, _, _ in create:
                        tg = fresh_by_name.get(cname.casefold())
                        if tg is None:
                            failed.append(cname)
                            continue
                        store[key] = tg.id
                        self._fresh_tags.setdefault(guild.id, {})[tg.id] = tg
                    if failed:
                        warnings.append(t(lang, "tag_warn_fail", tags=", ".join(failed)))
        cat_ids = {k: v for k, v in cat_ids.items() if k in cats}
        await gconf.tag_ids.set(tag_ids)
        await gconf.category_tag_ids.set(cat_ids)
        return warnings

    def _tag_objs(self, guild, forum, data, idea) -> list:
        """Tag-Objekte für einen Beitrag: Status + ggf. Kategorie (nur Tags, die es im Forum gibt)."""
        ids = []
        sid = (data.get("tag_ids") or {}).get(idea.get("status", "new"))
        if sid:
            ids.append(int(sid))
        if data.get("category_tags") and idea.get("category"):
            cid = (data.get("category_tag_ids") or {}).get(idea["category"])
            if cid:
                ids.append(int(cid))
        fresh = self._fresh_tags.get(guild.id, {})
        out = []
        for i in ids:
            tag = forum.get_tag(i) or fresh.get(i)
            if tag is not None:
                out.append(tag)
        return out[:MAX_APPLIED_TAGS]

    def _needs_tags(self, forum, data, idea) -> bool:
        ids = {tg.id for tg in forum.available_tags} | set(self._fresh_tags.get(forum.guild.id, {}))
        sid = (data.get("tag_ids") or {}).get(idea.get("status", "new"))
        if not sid or int(sid) not in ids:
            return True
        if data.get("category_tags") and idea.get("category"):
            cid = (data.get("category_tag_ids") or {}).get(idea["category"])
            return not cid or int(cid) not in ids
        return False

    # ----------------------------------------------------------------- #
    #  Embed
    # ----------------------------------------------------------------- #
    def build_embed(self, guild, idea: dict, data: dict) -> discord.Embed:
        lang = data.get("language", DEFAULT_LANGUAGE)
        status = idea.get("status", "new")
        nr = idea.get("nr")
        emb = discord.Embed(
            title=f"#{nr} · {idea.get('title', '')}"[:256],
            description=(idea.get("description") or t(lang, "embed_no_desc"))[:4000],
            color=STATUS_COLOR.get(status, 0x6CB6FF),
        )
        emb.add_field(name=t(lang, "embed_status"), value=f"{STATUS_EMOJI.get(status, '')} {status_label(lang, status)}")
        if idea.get("category"):
            emb.add_field(name=t(lang, "embed_category"), value=str(idea["category"])[:1024])
        if idea.get("anonymous"):
            who = t(lang, "embed_anonymous")
        elif idea.get("author_id"):
            who = f"<@{int(idea['author_id'])}>"
        else:
            who = "—"
        emb.add_field(name=t(lang, "embed_author"), value=who)
        target = (data.get("ideas") or {}).get(str(idea.get("merged_into"))) if idea.get("merged_into") else None
        if target:
            link = thread_url(guild.id, target.get("thread_id"))
            text = f"#{target['nr']} · {target.get('title', '')}"[:200]
            emb.add_field(name=t(lang, "embed_merged_into"), value=(f"[{text}]({link})" if link else text)[:1024],
                          inline=False)
        polls = [p for p in (idea.get("polls") or []) if isinstance(p, dict) and p.get("message_id")]
        if polls:
            lines = [f"🗳️ https://discord.com/channels/{guild.id}/{p['channel_id']}/{p['message_id']}"
                     for p in polls[-3:]]
            emb.add_field(name=t(lang, "embed_polls"), value="\n".join(lines)[:1024], inline=False)
        emb.set_footer(text=t(lang, "embed_footer", nr=nr))
        if idea.get("created_ts"):
            emb.timestamp = datetime.fromtimestamp(int(idea["created_ts"]), tz=timezone.utc)
        return emb

    # ----------------------------------------------------------------- #
    #  Einreichen (Modal, Webseite) – eine gemeinsame Funktion
    # ----------------------------------------------------------------- #
    @staticmethod
    def _err(key, **kw):
        return {"ok": False, "key": key, "kw": kw, "idea": None, "similar": []}

    async def _check_member(self, guild, member, data, privileged):
        if getattr(member, "bot", False):
            return self._err("err_bot")
        if privileged:
            return None
        if int(member.id) in {int(b) for b in data.get("blocked") or []}:
            return self._err("err_blocked")
        cooldown = int(data.get("cooldown_minutes") or 0) * 60
        if cooldown > 0:
            last = await self.config.member(member).last_submit()
            remaining = (last or 0) + cooldown - self._now()
            if remaining > 0:
                return self._err("err_cooldown", minutes=max(1, math.ceil(remaining / 60)))
        max_open = int(data.get("max_open") or 0)
        if max_open > 0 and self.open_count(data.get("ideas"), member.id) >= max_open:
            return self._err("err_limit", max=max_open)
        return None

    async def precheck(self, guild, member):
        """Prüfung vor dem Öffnen des Formulars (Button/Webseite) – gleiche Regeln wie ``submit``."""
        data = await self.config.guild(guild).all()
        if self.forum_of(guild, data) is None:
            return self._err("err_no_forum")
        return await self._check_member(guild, member, data, await self.bot.is_owner(member))

    async def submit(self, guild, member, *, title, description="", category=None, source="form") -> dict:
        """Idee prüfen, Forum-Beitrag anlegen, speichern. Rückgabe: {"ok", "key", "kw", "idea", "similar"}.

        Nummern werden unter einem Server-Lock vergeben; der Zähler steigt erst nach erfolgreichem
        Posten (keine Lücken, keine doppelten Nummern). Limits/Cooldown werden unter dem Lock erneut
        geprüft, damit parallele Klicks sie nicht umgehen.
        """
        gconf = self.config.guild(guild)
        data = await gconf.all()
        forum = self.forum_of(guild, data)
        title = " ".join((title or "").split())
        description = (description or "").strip()
        if getattr(member, "bot", False):
            return self._err("err_bot")
        if forum is None:
            return self._err("err_no_forum")
        if not title:
            return self._err("err_title_empty")
        if len(title) > MAX_TITLE:
            return self._err("err_title_long", max=MAX_TITLE)
        if len(description) > MAX_DESC:
            return self._err("err_desc_long", max=MAX_DESC)
        cat, ok = self.resolve_category(data.get("categories"), category)
        if not ok:
            return self._err("err_category", cats=", ".join(data.get("categories") or []) or "—")
        privileged = await self.bot.is_owner(member)
        pre = await self._check_member(guild, member, data, privileged)
        if pre:
            return pre
        async with self._lock(guild):
            data = await gconf.all()
            pre = await self._check_member(guild, member, data, privileged)
            if pre:
                return pre
            nr = int(data.get("counter") or 0) + 1
            now = int(self._now())
            idea = {
                "nr": nr, "title": title, "description": description, "category": cat,
                "author_id": int(member.id), "author_name": getattr(member, "display_name", "") or "",
                "anonymous": bool(data.get("anonymous")), "status": "new", "source": source,
                "created_ts": now, "updated_ts": now, "thread_id": None, "message_id": None,
                "history": [{"ts": now, "status": "new", "old": None, "by": int(member.id),
                             "by_name": getattr(member, "display_name", "") or "", "comment": None}],
                "merged_into": None, "merged_from": [], "polls": [], "deleted": False,
            }
            similar = self.similar_ideas(data.get("ideas"), title)
            if self._needs_tags(forum, data, idea):
                await self.ensure_tags(guild, forum)
                data = await gconf.all()
            try:
                res = await forum.create_thread(
                    name=thread_name(nr, title), embed=self.build_embed(guild, idea, data),
                    applied_tags=self._tag_objs(guild, forum, data, idea), allowed_mentions=_NONE,
                    reason=f"Idee #{nr}",
                )
            except discord.HTTPException:
                log.warning("Idee konnte nicht gepostet werden (Guild %s)", guild.id, exc_info=True)
                return self._err("err_post_failed")
            thread, message = res.thread, res.message
            idea["thread_id"] = thread.id
            idea["message_id"] = message.id
            async with gconf.ideas() as ideas:
                ideas[str(nr)] = idea
            await gconf.counter.set(nr)
            await self.config.member(member).last_submit.set(now)
        lang = data.get("language", DEFAULT_LANGUAGE)
        if data.get("follow_submitter") and not idea["anonymous"]:
            try:
                await thread.add_user(member)
            except (discord.HTTPException, AttributeError):
                log.debug("Einreicher konnte nicht hinzugefügt werden (Idee %s)", nr)
        if similar:
            try:
                await thread.send(t(lang, "thread_dup_note", links=self._links_md(guild, similar)),
                                  allowed_mentions=_NONE)
            except discord.HTTPException:
                pass
        return {"ok": True, "key": "submitted", "kw": {"nr": nr, "link": thread_url(guild.id, thread.id)},
                "idea": idea, "similar": similar}

    def _links_md(self, guild, ideas) -> str:
        out = []
        for i in ideas:
            text = f"#{i['nr']} · {i.get('title', '')}"[:80]
            link = self.idea_link(guild, i)
            out.append(f"[{text}]({link})" if link else text)
        return ", ".join(out)

    def result_text(self, guild, lang, res, *, web=False) -> str:
        """Antworttext für Modal (Markdown mit Links) bzw. Webseite (Klartext für den Toast)."""
        if not res.get("ok"):
            return t(lang, res["key"], **res.get("kw", {}))
        if web:
            text = t(lang, "submitted", nr=res["kw"]["nr"], link="").replace("**", "").rstrip(": ").rstrip()
            if res.get("similar"):
                text += " " + t(lang, "dup_hint", links=", ".join(
                    f"#{i['nr']} {i.get('title', '')}"[:80] for i in res["similar"]))
            return text
        text = t(lang, res["key"], **res["kw"])
        if res.get("similar"):
            text += "\n" + t(lang, "dup_hint", links=self._links_md(guild, res["similar"]))
        return text[:2000]

    # --- Discord-Oberfläche -------------------------------------------------
    async def _reply(self, interaction, text, **kw):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text[:2000], ephemeral=True, **kw)
            else:
                await interaction.response.send_message(text[:2000], ephemeral=True, **kw)
        except discord.HTTPException:
            log.debug("Antwort auf Interaktion fehlgeschlagen", exc_info=True)

    async def open_submit(self, interaction: discord.Interaction):
        """Panel-Button: Vorabprüfung, dann Kategorie-Auswahl (falls Kategorien) oder direkt das Formular."""
        guild, member = interaction.guild, interaction.user
        if guild is None:
            return
        data = await self.config.guild(guild).all()
        lang = data.get("language", DEFAULT_LANGUAGE)
        pre = await self.precheck(guild, member)
        if pre:
            return await self._reply(interaction, t(lang, pre["key"], **pre["kw"]))
        cats = list(data.get("categories") or [])
        if cats:
            await interaction.response.send_message(t(lang, "cat_prompt"), view=CategoryView(self, cats, lang),
                                                    ephemeral=True)
        else:
            await interaction.response.send_modal(IdeaModal(self, lang, None))

    async def submit_from_modal(self, interaction, title, description, category):
        guild, member = interaction.guild, interaction.user
        if guild is None:
            return
        lang = await self._lang(guild)
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.HTTPException:
            pass
        res = await self.submit(guild, member, title=title, description=description, category=category,
                                source="form")
        await self._reply(interaction, self.result_text(guild, lang, res))

    # ----------------------------------------------------------------- #
    #  Manuelle Beiträge / gelöschte Beiträge
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        try:
            await self.register_manual(thread)
        except Exception:  # noqa: BLE001
            log.exception("Manueller Beitrag konnte nicht übernommen werden")

    async def register_manual(self, thread) -> dict | None:
        """Von einem Mitglied direkt im Ideen-Forum erstellter Beitrag -> als Idee übernehmen."""
        guild = getattr(thread, "guild", None)
        if guild is None:
            return None
        if await self.bot.cog_disabled_in_guild(self, guild):
            return None
        gconf = self.config.guild(guild)
        data = await gconf.all()
        forum = self.forum_of(guild, data)
        if forum is None or thread.parent_id != forum.id or not data.get("manual_posts", True):
            return None
        bot_id = getattr(getattr(self.bot, "user", None), "id", None)
        if thread.owner_id == bot_id or thread.id == data.get("panel_thread_id"):
            return None
        author = guild.get_member(thread.owner_id) if thread.owner_id else None
        if author is None and thread.owner_id:
            try:        # ohne Members-Intent ist das Mitglied evtl. nicht im Cache
                author = await guild.fetch_member(thread.owner_id)
            except (discord.HTTPException, AttributeError):
                author = None
        if author is None or getattr(author, "bot", False):
            return None
        if int(author.id) in {int(b) for b in data.get("blocked") or []}:
            return None
        if any(i.get("thread_id") == thread.id for i in (data.get("ideas") or {}).values() if isinstance(i, dict)):
            return None
        starter = None
        for attempt in range(2):
            try:
                starter = await thread.fetch_message(thread.id)
                break
            except discord.NotFound:
                if attempt == 0:
                    await asyncio.sleep(1.5)     # Startnachricht kommt manchmal kurz nach dem Event
            except discord.HTTPException:
                break
        description = (getattr(starter, "content", "") or "").strip()[:MAX_DESC]
        title = " ".join((thread.name or "").split())[:MAX_TITLE] or "—"
        # vom Mitglied gewählter Tag, der einer Kategorie entspricht -> Kategorie übernehmen
        cat = None
        cat_ids = {int(v): k for k, v in (data.get("category_tag_ids") or {}).items()}
        for tag in getattr(thread, "applied_tags", []) or []:
            if tag.id in cat_ids and cat_ids[tag.id] in (data.get("categories") or []):
                cat = cat_ids[tag.id]
                break
        async with self._lock(guild):
            data = await gconf.all()
            nr = int(data.get("counter") or 0) + 1
            now = int(self._now())
            idea = {
                "nr": nr, "title": title, "description": description, "category": cat,
                "author_id": int(author.id), "author_name": getattr(author, "display_name", "") or "",
                "anonymous": False, "status": "new", "source": "manual",
                "created_ts": now, "updated_ts": now, "thread_id": thread.id, "message_id": None,
                "history": [{"ts": now, "status": "new", "old": None, "by": int(author.id),
                             "by_name": getattr(author, "display_name", "") or "", "comment": None}],
                "merged_into": None, "merged_from": [], "polls": [], "deleted": False,
            }
            async with gconf.ideas() as ideas:
                ideas[str(nr)] = idea
            await gconf.counter.set(nr)
        lang = data.get("language", DEFAULT_LANGUAGE)
        if self._needs_tags(forum, data, idea):
            await self.ensure_tags(guild, forum)
            data = await gconf.all()
        try:   # Info-Embed als Bot-Antwort (die Startnachricht gehört dem Mitglied und ist nicht editierbar)
            msg = await thread.send(t(lang, "manual_registered", nr=nr, status=status_label(lang, "new")),
                                    embed=self.build_embed(guild, idea, data), allowed_mentions=_NONE)
            async with gconf.ideas() as ideas:
                if str(nr) in ideas:
                    ideas[str(nr)]["message_id"] = msg.id
        except discord.HTTPException:
            log.warning("Info zu Idee #%s konnte nicht gepostet werden", nr, exc_info=True)
        try:
            kw = {"name": thread_name(nr, title)}
            tags = self._tag_objs(guild, forum, data, idea)
            if tags:
                kw["applied_tags"] = tags
            await thread.edit(**kw)
        except discord.HTTPException:
            log.warning("Beitrag zu Idee #%s konnte nicht umbenannt/getaggt werden", nr, exc_info=True)
        return idea

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload):
        guild_id = getattr(payload, "guild_id", None)
        thread_id = getattr(payload, "thread_id", None)
        if not guild_id or not thread_id:
            return
        gconf = self.config.guild_from_id(int(guild_id))
        try:
            if await gconf.panel_thread_id() == thread_id:
                await gconf.panel_thread_id.set(None)
                await gconf.panel_message_id.set(None)
                return
            async with self._lock(guild_id):
                async with gconf.ideas() as ideas:
                    for idea in ideas.values():
                        if isinstance(idea, dict) and idea.get("thread_id") == thread_id and not idea.get("deleted"):
                            idea["deleted"] = True
                            idea["deleted_ts"] = int(self._now())
        except Exception:  # noqa: BLE001
            log.exception("Gelöschter Beitrag konnte nicht verarbeitet werden")

    # ----------------------------------------------------------------- #
    #  Team-Workflow
    # ----------------------------------------------------------------- #
    async def _sync_thread(self, guild, nr, *, notes=()):
        """Beitrag an den gespeicherten Stand angleichen: ggf. wieder öffnen, Hinweise posten, Embed,
        Name und Tags aktualisieren, bei Umgesetzt/Abgelehnt (Schalter) bzw. Zusammengeführt schließen."""
        data = await self.config.guild(guild).all()
        idea = (data.get("ideas") or {}).get(str(nr))
        if not idea or idea.get("deleted"):
            return
        thread = await self._thread(guild, idea.get("thread_id"))
        if thread is None:
            return
        forum = self.forum_of(guild, data)
        status = idea.get("status", "new")
        closing = status == "merged" or (status in CLOSED_STATUSES and data.get("archive_closed", True))
        try:
            if getattr(thread, "archived", False) or getattr(thread, "locked", False):
                thread = await thread.edit(archived=False, locked=False) or thread
        except discord.HTTPException:
            log.warning("Beitrag zu Idee #%s konnte nicht geöffnet werden", nr, exc_info=True)
        for text in notes:
            try:
                await thread.send(str(text)[:2000], allowed_mentions=_NONE)
            except discord.HTTPException:
                log.warning("Hinweis in Idee #%s konnte nicht gepostet werden", nr, exc_info=True)
        if idea.get("message_id"):
            try:
                msg = await thread.fetch_message(int(idea["message_id"]))
                await msg.edit(embed=self.build_embed(guild, idea, data))
            except discord.HTTPException:
                log.debug("Embed zu Idee #%s nicht aktualisierbar", nr)
        changes = {}
        name = thread_name(idea["nr"], idea.get("title", ""))
        if thread.name != name:
            changes["name"] = name
        if forum is not None and thread.parent_id == forum.id:
            if self._needs_tags(forum, data, idea):
                await self.ensure_tags(guild, forum)
                data = await self.config.guild(guild).all()
            tags = self._tag_objs(guild, forum, data, idea)
            if tags and sorted(tg.id for tg in tags) != sorted(tg.id for tg in thread.applied_tags):
                changes["applied_tags"] = tags
        if closing:
            changes["archived"] = True
            changes["locked"] = True
        if changes:
            try:
                await thread.edit(**changes)
            except discord.HTTPException:
                log.warning("Beitrag zu Idee #%s konnte nicht aktualisiert werden", nr, exc_info=True)

    async def _dm(self, guild, idea, status, comment=None):
        uid = idea.get("author_id")
        member = guild.get_member(int(uid)) if uid else None
        if member is None or getattr(member, "bot", False):
            return
        lang = await self._lang(guild)
        text = t(lang, "dm_status", nr=idea["nr"], title=idea.get("title", ""), guild=guild.name,
                 status=status_label(lang, status))
        if comment:
            text += "\n" + t(lang, "dm_comment", text=comment)
        link = self.idea_link(guild, idea)
        if link:
            text += "\n" + link
        try:
            await member.send(text[:2000], allowed_mentions=_NONE)
        except (discord.HTTPException, AttributeError):
            log.debug("DM an %s nicht möglich", uid)

    def _entry(self, by, status, old, comment=None, **extra):
        return {"ts": int(self._now()), "status": status, "old": old, "by": int(getattr(by, "id", 0) or 0),
                "by_name": getattr(by, "display_name", None) or getattr(by, "name", "") or "",
                "comment": comment, **extra}

    @staticmethod
    def _trim(idea):
        if len(idea.get("history") or []) > MAX_HISTORY:
            idea["history"] = idea["history"][-MAX_HISTORY:]

    async def set_status(self, guild, nr, status, *, by=None, comment=None, notify=True, post_note=True,
                         extra_notes=()):
        """Status setzen (+ Kommentar). Rückgabe (Text-Key, kwargs)."""
        status = normalize_status(status) if status not in STATUSES else status
        lang = await self._lang(guild)
        if status not in STATUSES:
            return "bad_status", {"valid": ", ".join(status_label(lang, s) for s in STATUSES)}
        comment = (comment or "").strip()[:MAX_COMMENT] or None
        async with self._lock(guild):
            async with self.config.guild(guild).ideas() as ideas:
                idea = ideas.get(str(nr))
                if not isinstance(idea, dict) or idea.get("deleted"):
                    return "not_found", {"nr": nr}
                old = idea.get("status", "new")
                if old == status and not comment:
                    return "status_same", {"nr": nr, "status": status_label(lang, status)}
                if status == "merged" and not idea.get("merged_into"):
                    return "bad_status", {"valid": ", ".join(status_label(lang, s) for s in STATUSES
                                                             if s != "merged")}
                idea["status"] = status
                if status != "merged":
                    idea["merged_into"] = None
                idea["updated_ts"] = int(self._now())
                idea.setdefault("history", []).append(
                    self._entry(by, status if old != status else None, old, comment))
                self._trim(idea)
                snapshot = dict(idea)
        notes = list(extra_notes)
        if post_note and old != status:
            notes.append(t(lang, "status_note", old=status_label(lang, old), new=status_label(lang, status)))
        if comment:
            notes.append(t(lang, "comment_note", text=comment))
        await self._sync_thread(guild, nr, notes=notes)
        if notify and old != status and await self.config.guild(guild).dm_status():
            await self._dm(guild, snapshot, status, comment)
        return "status_set", {"nr": nr, "status": status_label(lang, status)}

    async def add_comment(self, guild, nr, text, *, by=None):
        text = (text or "").strip()[:MAX_COMMENT]
        if not text:
            return "comment_empty", {}
        lang = await self._lang(guild)
        async with self._lock(guild):
            async with self.config.guild(guild).ideas() as ideas:
                idea = ideas.get(str(nr))
                if not isinstance(idea, dict) or idea.get("deleted"):
                    return "not_found", {"nr": nr}
                idea.setdefault("history", []).append(self._entry(by, None, idea.get("status"), text))
                idea["updated_ts"] = int(self._now())
                self._trim(idea)
        await self._sync_thread(guild, nr, notes=[t(lang, "comment_note", text=text)])
        return "comment_ok", {"nr": nr}

    async def merge(self, guild, dup_nr, target_nr, *, by=None):
        """Duplikat -> Ziel: Status „Zusammengeführt“, Hinweis mit Link, Beitrag archivieren."""
        dup_nr, target_nr = int(dup_nr), int(target_nr)
        lang = await self._lang(guild)
        if dup_nr == target_nr:
            return "merge_same", {}
        async with self._lock(guild):
            async with self.config.guild(guild).ideas() as ideas:
                dup, target = ideas.get(str(dup_nr)), ideas.get(str(target_nr))
                if not isinstance(dup, dict) or dup.get("deleted"):
                    return "not_found", {"nr": dup_nr}
                if not isinstance(target, dict) or target.get("deleted"):
                    return "not_found", {"nr": target_nr}
                if dup.get("status") == "merged":
                    return "merge_already", {"nr": dup_nr}
                if target.get("status") == "merged":
                    return "merge_bad_target", {"nr": target_nr}
                old = dup.get("status", "new")
                dup["status"] = "merged"
                dup["merged_into"] = target_nr
                dup["updated_ts"] = int(self._now())
                dup.setdefault("history", []).append(self._entry(by, "merged", old, None, merged_into=target_nr))
                self._trim(dup)
                target.setdefault("merged_from", [])
                if dup_nr not in target["merged_from"]:
                    target["merged_from"].append(dup_nr)
                target.setdefault("history", []).append(self._entry(by, None, target.get("status"), None,
                                                                    merged_from=dup_nr))
                self._trim(target)
                dup_snap, target_snap = dict(dup), dict(target)
        await self._sync_thread(guild, dup_nr, notes=[t(lang, "merged_note", nr=target_nr,
                                                        title=target_snap.get("title", ""),
                                                        link=self.idea_link(guild, target_snap) or "—")])
        await self._sync_thread(guild, target_nr, notes=[t(lang, "merged_target_note", nr=dup_nr,
                                                           title=dup_snap.get("title", ""))])
        if await self.config.guild(guild).dm_status():
            await self._dm(guild, dup_snap, "merged")
        return "merged_ok", {"dup": dup_nr, "target": target_nr}

    async def edit_idea(self, guild, nr, *, title=_UNSET, description=_UNSET, category=_UNSET, by=None):
        data = await self.config.guild(guild).all()
        if title is not _UNSET:
            title = " ".join((title or "").split())
            if not title:
                return "err_title_empty", {}
            if len(title) > MAX_TITLE:
                return "err_title_long", {"max": MAX_TITLE}
        if description is not _UNSET:
            description = (description or "").strip()
            if len(description) > MAX_DESC:
                return "err_desc_long", {"max": MAX_DESC}
        if category is not _UNSET:
            category, ok = self.resolve_category(data.get("categories"), category)
            if not ok:
                return "err_category", {"cats": ", ".join(data.get("categories") or []) or "—"}
        async with self._lock(guild):
            async with self.config.guild(guild).ideas() as ideas:
                idea = ideas.get(str(nr))
                if not isinstance(idea, dict) or idea.get("deleted"):
                    return "not_found", {"nr": nr}
                changed = []
                for key, val in (("title", title), ("description", description), ("category", category)):
                    if val is not _UNSET and idea.get(key) != val:
                        idea[key] = val
                        changed.append(key)
                if changed:
                    idea["updated_ts"] = int(self._now())
                    idea.setdefault("history", []).append(self._entry(by, None, idea.get("status"), None,
                                                                      edited=changed))
                    self._trim(idea)
        if changed:
            await self._sync_thread(guild, nr)
        return "edited_ok", {"nr": nr}

    async def delete_idea(self, guild, nr):
        async with self._lock(guild):
            async with self.config.guild(guild).ideas() as ideas:
                idea = ideas.pop(str(nr), None)
        if not isinstance(idea, dict):
            return "not_found", {"nr": nr}
        if not idea.get("deleted"):
            thread = await self._thread(guild, idea.get("thread_id"))
            if thread is not None:
                try:
                    await thread.delete(reason=f"Idee #{nr} gelöscht")
                except discord.HTTPException:
                    log.warning("Beitrag zu Idee #%s konnte nicht gelöscht werden", nr, exc_info=True)
        return "deleted_ok", {"nr": nr}

    async def set_blocked(self, guild, user_id: int, blocked: bool):
        async with self.config.guild(guild).blocked() as lst:
            ids = [int(x) for x in lst]
            if blocked and int(user_id) not in ids:
                ids.append(int(user_id))
            if not blocked:
                ids = [x for x in ids if x != int(user_id)]
            lst[:] = ids

    # ----------------------------------------------------------------- #
    #  Umfrage aus Ideen (über den Poll-Cog)
    # ----------------------------------------------------------------- #
    def poll_cog(self):
        return self.bot.get_cog("Poll")

    async def poll_limits(self, guild) -> int:
        pc = self.poll_cog()
        mod = sys.modules.get(type(pc).__module__) if pc is not None else None
        hard = int(getattr(mod, "HARD_OPTION_LIMIT", 25) or 25)
        try:
            mx = int(await pc.config.guild(guild).max_options())
        except Exception:  # noqa: BLE001
            mx = 10
        return max(2, min(mx, hard))

    async def start_poll(self, guild, nrs, *, question=None, channel=None, duration=None, multiple=None,
                         anonymous=None, set_review=None, by=None):
        """Umfrage mit „#12 Titel“-Optionen über ``Poll.create_poll`` anlegen und posten, Ideen verknüpfen.

        Rückgabe: (ok, Text, Umfrage-Dict | None)."""
        lang = await self._lang(guild)
        pc = self.poll_cog()
        if pc is None:
            return False, t(lang, "poll_missing"), None
        if not callable(getattr(pc, "create_poll", None)):
            return False, t(lang, "poll_old"), None
        mod = sys.modules.get(type(pc).__module__)
        seen, order = set(), []
        for n in nrs:
            try:
                n = int(str(n).lstrip("#"))
            except (TypeError, ValueError):
                continue
            if n not in seen:
                seen.add(n)
                order.append(n)
        max_opts = await self.poll_limits(guild)
        if len(order) < 2:
            return False, t(lang, "poll_few"), None
        if len(order) > max_opts:
            return False, t(lang, "poll_many", max=max_opts), None
        data = await self.config.guild(guild).all()
        ideas = data.get("ideas") or {}
        unknown = [n for n in order if not isinstance(ideas.get(str(n)), dict) or ideas[str(n)].get("deleted")]
        if unknown:
            return False, t(lang, "poll_unknown", nrs=", ".join(f"#{n}" for n in unknown)), None
        closed = [n for n in order if ideas[str(n)].get("status") not in OPEN_STATUSES]
        if closed:
            return False, t(lang, "poll_not_open", nrs=", ".join(f"#{n}" for n in closed)), None
        max_q = int(getattr(mod, "MAX_QUESTION_LEN", 256) or 256)
        question = " ".join((question or "").split()) or t(lang, "poll_default_question")
        if len(question) > max_q:
            return False, t(lang, "poll_bad_question", max=max_q), None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False, t(lang, "poll_bad_channel"), None
        end_ts = None
        if duration:
            parse = getattr(mod, "parse_duration", None) or _parse_duration
            secs = parse(str(duration))
            if not secs:
                return False, t(lang, "poll_bad_duration"), None
            end_ts = int(self._now()) + int(secs)
        try:
            pconf = pc.config.guild(guild)
            multiple = await pconf.default_multiple() if multiple is None else multiple
            anonymous = await pconf.default_anonymous() if anonymous is None else anonymous
        except Exception:  # noqa: BLE001
            multiple, anonymous = bool(multiple), bool(anonymous)
        opt_len = int(getattr(mod, "MAX_OPTION_LEN", 100) or 100)
        options = []
        for n in order:
            text = f"#{n} {ideas[str(n)].get('title', '')}"
            options.append(text if len(text) <= opt_len else text[:opt_len - 1] + "…")
        poll = await pc.create_poll(guild, question=question, options=options, channel_id=channel.id,
                                    author_id=int(getattr(by, "id", 0) or getattr(self.bot.user, "id", 0)),
                                    end_ts=end_ts, multiple=bool(multiple), anonymous=bool(anonymous))
        if not poll.get("message_id"):
            return False, t(lang, "poll_post_failed"), poll
        link = f"https://discord.com/channels/{guild.id}/{channel.id}/{poll['message_id']}"
        entry = {"id": poll.get("id"), "channel_id": channel.id, "message_id": poll["message_id"],
                 "ts": int(self._now()), "by": int(getattr(by, "id", 0) or 0)}
        async with self._lock(guild):
            async with self.config.guild(guild).ideas() as stored:
                for n in order:
                    if str(n) in stored:
                        stored[str(n)].setdefault("polls", []).append(dict(entry))
                        stored[str(n)]["polls"] = stored[str(n)]["polls"][-10:]
        review = data.get("poll_review", True) if set_review is None else set_review
        note = t(lang, "poll_note", link=link)
        for n in order:
            if review and ideas[str(n)].get("status") == "new":
                await self.set_status(guild, n, "review", by=by, extra_notes=[note])
            else:
                await self._sync_thread(guild, n, notes=[note])
        return True, t(lang, "poll_ok", n=len(order), link=link), poll

    # ----------------------------------------------------------------- #
    #  Panel / Forum anlegen / Export
    # ----------------------------------------------------------------- #
    def panel_embed(self, data) -> discord.Embed:
        lang = data.get("language", DEFAULT_LANGUAGE)
        emb = discord.Embed(title=t(lang, "panel_title"), description=t(lang, "panel_text"), color=0xF5B94A)
        emb.set_footer(text=t(lang, "panel_limits", max_open=data.get("max_open") or "∞",
                              cooldown=data.get("cooldown_minutes") or 0)[:2048])
        if data.get("categories"):
            emb.add_field(name=t(lang, "embed_category"), value=", ".join(data["categories"])[:1024])
        return emb

    async def post_panel(self, guild):
        """Panel-Beitrag posten bzw. erneuern. Rückgabe (ok, Text, Warnungen)."""
        gconf = self.config.guild(guild)
        data = await gconf.all()
        lang = data.get("language", DEFAULT_LANGUAGE)
        forum = self.forum_of(guild, data)
        if forum is None:
            return False, t(lang, "err_no_forum"), []
        warnings = await self.ensure_tags(guild, forum)
        embed, view = self.panel_embed(data), PanelView(self, lang)
        thread = await self._thread(guild, data.get("panel_thread_id"))
        if thread is not None and thread.parent_id == forum.id:
            try:
                if thread.archived:
                    thread = await thread.edit(archived=False) or thread
                msg = await thread.fetch_message(int(data.get("panel_message_id") or thread.id))
                await msg.edit(embed=embed, view=view)
                await thread.edit(pinned=True, locked=True)
                return True, t(lang, "panel_ok", link=thread_url(guild.id, thread.id)), warnings
            except discord.HTTPException:
                log.info("Panel wird neu gepostet (Guild %s)", guild.id)
        try:
            res = await forum.create_thread(name=t(lang, "panel_thread"), embed=embed, view=view,
                                            allowed_mentions=_NONE, reason="Ideen: Panel")
        except discord.HTTPException:
            log.warning("Panel konnte nicht gepostet werden (Guild %s)", guild.id, exc_info=True)
            return False, t(lang, "panel_fail"), warnings
        await gconf.panel_thread_id.set(res.thread.id)
        await gconf.panel_message_id.set(res.message.id)
        try:
            await res.thread.edit(pinned=True, locked=True)
        except discord.HTTPException:
            log.warning("Panel konnte nicht angepinnt werden (Guild %s)", guild.id, exc_info=True)
        return True, t(lang, "panel_ok", link=thread_url(guild.id, res.thread.id)), warnings

    async def create_forum(self, guild, name="ideen", category=None):
        """Forum mit Status-/Kategorie-Tags und passenden Rechten anlegen, einstellen und Panel posten.

        Rechte: @everyone darf antworten, aber keine eigenen Beiträge erstellen (Einreichen nur über das
        Formular); der Bot darf posten, Beiträge verwalten und Tags setzen; Team-Rollen dürfen Beiträge
        verwalten. Rückgabe (ok, Text, Warnungen)."""
        gconf = self.config.guild(guild)
        data = await gconf.all()
        lang = data.get("language", DEFAULT_LANGUAGE)
        name = (name or "ideen").strip()[:100] or "ideen"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                send_messages=False, send_messages_in_threads=True, create_public_threads=False,
                create_private_threads=False),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, send_messages_in_threads=True, manage_threads=True,
                embed_links=True, read_message_history=True)
        for rid in data.get("team_roles") or []:
            role = guild.get_role(int(rid))
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(manage_threads=True, send_messages_in_threads=True)
        tags = [discord.ForumTag(name=status_label(lang, s), emoji=STATUS_EMOJI[s], moderated=True) for s in STATUSES]
        if data.get("category_tags"):
            names = {tg.name.casefold() for tg in tags}
            tags += [discord.ForumTag(name=c[:MAX_CATEGORY_LEN], moderated=False)
                     for c in (data.get("categories") or [])
                     if c[:MAX_CATEGORY_LEN].casefold() not in names][:FORUM_TAG_LIMIT - len(tags)]
        try:
            forum = await guild.create_forum(name, topic=t(lang, "forum_topic"), category=category,
                                             overwrites=overwrites, available_tags=tags,
                                             reason="Ideen: Forum anlegen")
        except (discord.HTTPException, AttributeError):
            log.warning("Forum konnte nicht angelegt werden (Guild %s)", guild.id, exc_info=True)
            return False, t(lang, "forum_create_fail"), []
        await gconf.forum_id.set(forum.id)
        await gconf.tag_ids.set({})
        await gconf.category_tag_ids.set({})
        await gconf.panel_thread_id.set(None)
        await gconf.panel_message_id.set(None)
        ok, text, warnings = await self.post_panel(guild)
        msg = t(lang, "forum_created", forum=forum.mention)
        if not ok:
            msg += " " + text
        return True, msg, warnings

    async def set_forum(self, guild, forum):
        """Forum setzen + Tags prüfen/anlegen. Rückgabe Warnungen."""
        gconf = self.config.guild(guild)
        if forum is None:
            await gconf.forum_id.set(None)
            return []
        if await gconf.forum_id() != forum.id:
            await gconf.forum_id.set(forum.id)
            await gconf.tag_ids.set({})
            await gconf.category_tag_ids.set({})
            await gconf.panel_thread_id.set(None)
            await gconf.panel_message_id.set(None)
        return await self.ensure_tags(guild, forum)

    async def export_csv(self, guild) -> bytes:
        data = await self.config.guild(guild).all()
        lang = data.get("language", DEFAULT_LANGUAGE)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Nr", "Titel", "Beschreibung", "Kategorie", "Status", "Einreicher-ID", "Einreicher",
                    "Anonym", "Quelle", "Erstellt (UTC)", "Aktualisiert (UTC)", "Beitrag", "Zusammengeführt mit",
                    "Umfragen", "Gelöscht"])

        def cell(v):
            s = "" if v is None else str(v)
            return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s   # CSV-Injection verhindern

        def iso(ts):
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else ""

        for idea in sorted((i for i in (data.get("ideas") or {}).values() if isinstance(i, dict)),
                           key=lambda i: i.get("nr", 0)):
            w.writerow([cell(x) for x in (
                idea.get("nr"), idea.get("title"), idea.get("description"), idea.get("category") or "",
                status_label(lang, idea.get("status", "new")), idea.get("author_id") or "",
                idea.get("author_name") or "", "ja" if idea.get("anonymous") else "nein", idea.get("source", ""),
                iso(idea.get("created_ts")), iso(idea.get("updated_ts")), self.idea_link(guild, idea) or "",
                f"#{idea['merged_into']}" if idea.get("merged_into") else "",
                " ".join(str(p.get("id")) for p in idea.get("polls") or [] if isinstance(p, dict)),
                "ja" if idea.get("deleted") else "nein")])
        return ("﻿" + buf.getvalue()).encode("utf-8")

    # ----------------------------------------------------------------- #
    #  Befehle: Team
    # ----------------------------------------------------------------- #
    async def _deny(self, ctx) -> bool:
        ok = await self.is_team(ctx.author)
        if not ok:
            await ctx.send(t(await self._lang(ctx.guild), "no_permission"))
        return not ok

    async def _say(self, ctx, key, kw):
        await ctx.send(t(await self._lang(ctx.guild), key, **kw)[:2000], allowed_mentions=_NONE)

    @commands.guild_only()
    @commands.hybrid_group(name="ideas", aliases=["ideen"])
    async def ideas(self, ctx: commands.Context):
        """Ideen verwalten (Team: Server verwalten oder Ideen-Team-Rolle)."""

    @ideas.command(name="status")
    async def ideas_status(self, ctx: commands.Context, nr: int, status: str, *, kommentar: Optional[str] = None):
        """Status setzen: neu, prüfung, geplant, umgesetzt, abgelehnt – optional mit Kommentar."""
        if await self._deny(ctx):
            return
        key, kw = await self.set_status(ctx.guild, nr, status, by=ctx.author, comment=kommentar)
        await self._say(ctx, key, kw)

    @ideas.command(name="comment", aliases=["kommentar"])
    async def ideas_comment(self, ctx: commands.Context, nr: int, *, text: str):
        """Kommentar des Teams im Beitrag der Idee posten."""
        if await self._deny(ctx):
            return
        key, kw = await self.add_comment(ctx.guild, nr, text, by=ctx.author)
        await self._say(ctx, key, kw)

    @ideas.command(name="merge")
    async def ideas_merge(self, ctx: commands.Context, duplikat: int, ziel: int):
        """Duplikat mit einer anderen Idee zusammenführen (Beitrag wird archiviert)."""
        if await self._deny(ctx):
            return
        key, kw = await self.merge(ctx.guild, duplikat, ziel, by=ctx.author)
        await self._say(ctx, key, kw)

    @ideas.command(name="edit")
    async def ideas_edit(self, ctx: commands.Context, nr: int, feld: str, *, wert: str = ""):
        """Titel, Beschreibung oder Kategorie ändern: `[p]ideas edit 12 titel Neuer Titel`."""
        if await self._deny(ctx):
            return
        field = {"titel": "title", "title": "title", "beschreibung": "description", "description": "description",
                 "kategorie": "category", "category": "category"}.get(feld.casefold())
        if field is None:
            return await self._say(ctx, "bad_field", {})
        key, kw = await self.edit_idea(ctx.guild, nr, by=ctx.author, **{field: wert})
        await self._say(ctx, key, kw)

    @ideas.command(name="delete")
    async def ideas_delete(self, ctx: commands.Context, nr: int, bestaetigen: Optional[str] = None):
        """Idee samt Forum-Beitrag löschen – zur Bestätigung `ja` anhängen."""
        if await self._deny(ctx):
            return
        if (bestaetigen or "").casefold() not in ("ja", "yes", "j", "y"):
            idea = (await self.config.guild(ctx.guild).ideas()).get(str(nr))
            if not idea:
                return await self._say(ctx, "not_found", {"nr": nr})
            return await self._say(ctx, "delete_confirm", {"nr": nr, "cmd": f"{ctx.clean_prefix}ideas delete {nr} ja"})
        key, kw = await self.delete_idea(ctx.guild, nr)
        await self._say(ctx, key, kw)

    @ideas.command(name="block")
    async def ideas_block(self, ctx: commands.Context, mitglied: discord.Member):
        """Mitglied für das Einreichen sperren."""
        if await self._deny(ctx):
            return
        if await self.is_team(mitglied):
            return await self._say(ctx, "block_team", {})
        await self.set_blocked(ctx.guild, mitglied.id, True)
        await self._say(ctx, "blocked_ok", {"user": mitglied.mention})

    @ideas.command(name="unblock")
    async def ideas_unblock(self, ctx: commands.Context, mitglied: discord.Member):
        """Sperre aufheben."""
        if await self._deny(ctx):
            return
        await self.set_blocked(ctx.guild, mitglied.id, False)
        await self._say(ctx, "unblocked_ok", {"user": mitglied.mention})

    @ideas.command(name="list")
    async def ideas_list(self, ctx: commands.Context, status: Optional[str] = None):
        """Ideen auflisten, optional nach Status gefiltert (z. B. `offen`, `geplant`)."""
        if await self._deny(ctx):
            return
        lang = await self._lang(ctx.guild)
        ideas = await self.config.guild(ctx.guild).ideas()
        wanted = None
        if status:
            if status.casefold() in ("offen", "open"):
                wanted = set(OPEN_STATUSES)
            else:
                key = normalize_status(status)
                if key is None:
                    return await self._say(ctx, "bad_status", {"valid": ", ".join(status_label(lang, s) for s in STATUSES)})
                wanted = {key}
        rows = []
        for idea in sorted((i for i in ideas.values() if isinstance(i, dict) and not i.get("deleted")),
                           key=lambda i: -i.get("nr", 0)):
            if wanted and idea.get("status") not in wanted:
                continue
            st = idea.get("status", "new")
            rows.append(t(lang, "list_row", nr=idea["nr"], emoji=STATUS_EMOJI.get(st, ""),
                          title=idea.get("title", "")[:80], status=status_label(lang, st),
                          cat=f" · {idea['category']}" if idea.get("category") else ""))
        if not rows:
            return await self._say(ctx, "list_empty", {})
        text = t(lang, "list_header") + "\n" + "\n".join(rows)
        for page in pagify(text, delims=["\n"], page_length=1900):
            await ctx.send(page, allowed_mentions=_NONE)

    @ideas.command(name="export")
    async def ideas_export(self, ctx: commands.Context):
        """Alle Ideen als CSV-Datei."""
        if await self._deny(ctx):
            return
        if not await self.config.guild(ctx.guild).ideas():
            return await self._say(ctx, "export_empty", {})
        data = await self.export_csv(ctx.guild)
        await ctx.send(t(await self._lang(ctx.guild), "export_ok"),
                       file=discord.File(io.BytesIO(data), filename=f"ideen-{ctx.guild.id}.csv"))

    @ideas.command(name="poll", aliases=["umfrage"])
    async def ideas_poll(self, ctx: commands.Context, *, text: str):
        """Umfrage aus Ideen in diesem Kanal: `[p]ideas poll 12 15 18 | Welche zuerst?`"""
        if await self._deny(ctx):
            return
        left, _, question = text.partition("|")
        nrs = [p for p in re.split(r"[\s,;]+", left.strip()) if p]
        ok, msg, _ = await self.start_poll(ctx.guild, nrs, question=question.strip() or None, channel=ctx.channel,
                                           by=ctx.author)
        await ctx.send(msg[:2000], allowed_mentions=_NONE)

    # ----------------------------------------------------------------- #
    #  Befehle: Einstellungen (Server verwalten)
    # ----------------------------------------------------------------- #
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.hybrid_group(name="ideaset")
    async def ideaset(self, ctx: commands.Context):
        """Einstellungen des Ideen-Sammlers (Server verwalten)."""

    @ideaset.command(name="forum")
    async def ideaset_forum(self, ctx: commands.Context, forum: discord.ForumChannel):
        """Ideen-Forum festlegen (Status-Tags werden angelegt, falls sie fehlen)."""
        lang = await self._lang(ctx.guild)
        if not isinstance(forum, discord.ForumChannel):
            return await ctx.send(t(lang, "set_forum_bad"))
        warnings = await self.set_forum(ctx.guild, forum)
        lines = [t(lang, "set_forum", forum=forum.mention)] + [t(lang, "set_tag_warn", warn=w) for w in warnings]
        await ctx.send("\n".join(lines)[:2000], allowed_mentions=_NONE)

    @ideaset.command(name="createforum", aliases=["forumanlegen"])
    async def ideaset_createforum(self, ctx: commands.Context, *, name: str = "ideen"):
        """Neues Ideen-Forum mit Tags, Rechten und Panel anlegen."""
        ok, msg, warnings = await self.create_forum(ctx.guild, name)
        lang = await self._lang(ctx.guild)
        await ctx.send("\n".join([msg] + [t(lang, "set_tag_warn", warn=w) for w in warnings])[:2000],
                       allowed_mentions=_NONE)

    @ideaset.command(name="panel")
    async def ideaset_panel(self, ctx: commands.Context):
        """Panel „💡 Idee einreichen“ im Forum posten bzw. erneuern."""
        ok, msg, warnings = await self.post_panel(ctx.guild)
        lang = await self._lang(ctx.guild)
        await ctx.send("\n".join([msg] + [t(lang, "set_tag_warn", warn=w) for w in warnings])[:2000],
                       allowed_mentions=_NONE)

    @ideaset.command(name="categories", aliases=["kategorien"])
    async def ideaset_categories(self, ctx: commands.Context, *, kategorien: str = ""):
        """Kategorien setzen, getrennt mit | (leer = keine): `[p]ideaset categories Events | Discord | Spiele`"""
        lang = await self._lang(ctx.guild)
        cats = clean_categories(kategorien.split("|"))
        if cats is None:
            return await ctx.send(t(lang, "categories_bad", max=MAX_CATEGORIES, len=MAX_CATEGORY_LEN))
        await self.config.guild(ctx.guild).categories.set(cats)
        warnings = await self.ensure_tags(ctx.guild)
        await ctx.send("\n".join([t(lang, "categories_set", cats=", ".join(cats) or "—")]
                                 + [t(lang, "set_tag_warn", warn=w) for w in warnings])[:2000],
                       allowed_mentions=_NONE)

    @ideaset.command(name="teamrole")
    async def ideaset_teamrole(self, ctx: commands.Context, rolle: discord.Role):
        """Team-Rolle hinzufügen/entfernen (Umschalter)."""
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).team_roles() as roles:
            if rolle.id in roles:
                roles.remove(rolle.id)
                key = "teamrole_removed"
            else:
                roles.append(rolle.id)
                key = "teamrole_added"
        await ctx.send(t(lang, key, role=rolle.mention), allowed_mentions=_NONE)

    async def _toggle(self, ctx, attr, value):
        await getattr(self.config.guild(ctx.guild), attr).set(bool(value))
        await ctx.send(t(await self._lang(ctx.guild), "set_ok"))

    @ideaset.command(name="anonymous", aliases=["anonym"])
    async def ideaset_anonymous(self, ctx: commands.Context, an: bool):
        """Einreicher im Beitrag nicht nennen (das Team sieht ihn im Dashboard weiterhin)."""
        await self._toggle(ctx, "anonymous", an)

    @ideaset.command(name="dm")
    async def ideaset_dm(self, ctx: commands.Context, an: bool):
        """DM an den Einreicher bei Statuswechsel."""
        await self._toggle(ctx, "dm_status", an)

    @ideaset.command(name="archive", aliases=["archivieren"])
    async def ideaset_archive(self, ctx: commands.Context, an: bool):
        """Beitrag bei Umgesetzt/Abgelehnt schließen und archivieren."""
        await self._toggle(ctx, "archive_closed", an)

    @ideaset.command(name="manual", aliases=["manuell"])
    async def ideaset_manual(self, ctx: commands.Context, an: bool):
        """Manuell erstellte Forum-Beiträge als Idee übernehmen."""
        await self._toggle(ctx, "manual_posts", an)

    @ideaset.command(name="cooldown")
    async def ideaset_cooldown(self, ctx: commands.Context, minuten: int):
        """Wartezeit je Mitglied zwischen zwei Ideen (0–1440 Minuten)."""
        await self.config.guild(ctx.guild).cooldown_minutes.set(max(0, min(1440, minuten)))
        await ctx.send(t(await self._lang(ctx.guild), "set_ok"))

    @ideaset.command(name="maxopen")
    async def ideaset_maxopen(self, ctx: commands.Context, anzahl: int):
        """Max. offene Ideen je Mitglied (0 = unbegrenzt, höchstens 100)."""
        await self.config.guild(ctx.guild).max_open.set(max(0, min(100, anzahl)))
        await ctx.send(t(await self._lang(ctx.guild), "set_ok"))

    @ideaset.command(name="language", aliases=["sprache"])
    async def ideaset_language(self, ctx: commands.Context, code: str):
        """Sprache der Discord-Texte: de oder en."""
        code = code.lower()
        lang = await self._lang(ctx.guild)
        if code not in LANGUAGES:
            return await ctx.send(t(lang, "lang_bad", langs=", ".join(LANGUAGES)))
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))

    @ideaset.command(name="settings")
    async def ideaset_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        data = await self.config.guild(ctx.guild).all()
        forum = self.forum_of(ctx.guild, data)
        roles = [f"<@&{r}>" for r in data.get("team_roles") or []]
        yes = {True: "an", False: "aus"}
        lines = [
            f"**Ideen-Forum:** {forum.mention if forum else '—'}",
            f"**Kategorien:** {', '.join(data.get('categories') or []) or '—'} (Tags: {yes[bool(data.get('category_tags'))]})",
            f"**Cooldown:** {data.get('cooldown_minutes')} Min. · **Max. offen:** {data.get('max_open') or '∞'}",
            f"**Anonym:** {yes[bool(data.get('anonymous'))]} · **DM bei Status:** {yes[bool(data.get('dm_status'))]}"
            f" · **Archivieren:** {yes[bool(data.get('archive_closed'))]} · **Manuelle Beiträge:** "
            f"{yes[bool(data.get('manual_posts'))]}",
            f"**Team-Rollen:** {', '.join(roles) or '—'} · **Gesperrt:** {len(data.get('blocked') or [])}",
            f"**Sprache:** {LANGUAGES.get(data.get('language'), data.get('language'))} · "
            f"**Ideen:** {len(data.get('ideas') or {})}",
        ]
        await ctx.send("\n".join(lines)[:2000], allowed_mentions=_NONE)


def clean_categories(items):
    """Kategorien bereinigen: leer raus, Duplikate (ohne Groß/klein) raus. None = zu viele/zu lang."""
    out, seen = [], set()
    for c in items or []:
        c = " ".join(str(c).split())
        if not c or c.casefold() in seen:
            continue
        if len(c) > MAX_CATEGORY_LEN or c == "__none__":
            return None
        seen.add(c.casefold())
        out.append(c)
    if len(out) > MAX_CATEGORIES:
        return None
    return out
