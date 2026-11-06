import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

from .dashboard import dashboard_handler
from .member import member_handler
from .strings import LANGUAGES, OVERRIDABLE_KEYS, t
from .transcript import build_transcript, redact_user
from .support import DEFAULT_REPLIES, MAX_REPLY, human_reply, render_reply, reset_response, set_waiting, support_due
from .replies import PriorityView, ReplyPicker
from .views import (
    CID_ASSIGN,
    CID_AUTOCLOSE,
    CID_CLAIM,
    CID_CLOSE,
    CID_LOCK,
    CID_KEEP_OPEN,
    CID_OPEN,
    CID_SELECT,
    CID_UNCLAIM,
    CID_UNLOCK,
    CID_WAIT_TEAM,
    CID_PRIORITY,
    CID_REPLY,
    CID_WAIT_USER,
    ConfirmView,
    AssignmentView,
    TicketModal,
    build_controls_view,
    build_panel_view,
    build_reminder_view,
)

log = logging.getLogger("red.red-cogs.tickets")

EMBED_COLOR = 0x3DDC97
INACTIVITY_TIMEOUT = timedelta(hours=24)

# Rollen-Pings müssen explizit erlaubt werden – Reds Standard blockt roles=False,
# sonst würden die Ping-Rollen beim Öffnen eines Tickets nicht benachrichtigt.
PING_ALLOWED = discord.AllowedMentions(everyone=False, roles=True, users=True)

# Kanalnamen: Umlaute lesbar umschreiben statt sie zu "-" zu machen (Störung -> stoerung).
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass
class OpenResult:
    """Ergebnis von ``Tickets.open_ticket`` (gemeinsam für Discord-Button und Website).

    ``status``: ``ok`` | ``max_open`` | ``failed``; ``max_open`` = aktuelles Limit.
    """
    status: str
    target: object = None
    max_open: int = 1


def _fill(template, **values) -> str:
    """Ersetzt nur bekannte ``{platzhalter}`` – bewusst kein ``str.format``.

    Frei eingegebene Vorlagen (Dashboard) mit unbekannten oder kaputten Klammern
    dürfen die Ticket-Erstellung nie abstürzen lassen; Unbekanntes bleibt stehen.
    """
    return _PLACEHOLDER.sub(
        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
        template or "",
    )


class Tickets(commands.Cog):
    """Mehrsprachiges Ticketsystem mit Panels, Transcripts und Dashboard-Verwaltung."""

    support_due = staticmethod(support_due)

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=846215097433, force_registration=True)
        self.config.register_guild(
            language="de",
            support_roles=[],
            admin_roles=[],
            view_roles=[],
            ping_roles=[],
            owner_role=None,
            ticket_type="category",  # category | thread | forum
            category_open=None,
            category_close=None,
            thread_base=None,
            forum_channel=None,
            log_channel=None,
            max_open=1,
            close_confirmation=True,
            user_can_close=True,
            delete_on_close=False,
            name_template="ticket-{num}",
            messages={},
            panels=[],
            counter=0,
            tickets={},
            transcripts=[],
            stats={"opened": 0, "closed": 0, "claims": {}, "duration_sum": 0},
            portal_enabled=True,   # „Meine Tickets“ im Mitglieder-Bereich (WebCore /me/tickets)
            portal_create=True,    # Tickets über die Website öffnen erlauben
            response_targets_enabled=False,
            response_target_hours=24,
            response_urgent_hours=4,
            quick_replies=DEFAULT_REPLIES,
            quick_reply_signature="",
        )
        self.transcripts_dir = cog_data_path(self) / "transcripts"
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        # Serialisiert Öffnen (pro Nutzer) und Schließen (pro Kanal) gegen Doppelklicks.
        self._locks: dict[tuple, asyncio.Lock] = {}
        self._active_timer_channels: set[int] = set()
        # Gateway-Aktivität sofort merken, auch wenn die Ablaufprüfung gerade auf Discord wartet.
        self._latest_activity: dict[int, datetime] = {}
        self._controls_restored = False
        self._pending_control_refresh: set[tuple[int, int]] = set()

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (1:1-Muster aus example)
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        await self._mark_support_history_pending()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._autoclose_loop.start()

    async def cog_unload(self):
        self._autoclose_loop.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    # ----------------------------------------------------------------- #
    #  Datenlöschung (Red: [p]mydata / Owner / Discord-Löschanfrage)
    # ----------------------------------------------------------------- #
    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Entfernt bzw. anonymisiert alle Daten eines Nutzers (alle Server).

        - **Transcripts, deren Ersteller er ist, werden gelöscht** (Datei + Metadaten). Ein
          Transcript ist der Verlauf *seines* Anliegens: Name, Fragen/Antworten und Inhalte
          identifizieren ihn auch nach Schwärzen des Namens, und Nachrichten anderer darin sind
          Antworten auf sein Anliegen – Anonymisieren wäre unvollständig, Löschen ist sauber.
        - In Transcripts **fremder** Tickets werden nur seine Nachrichten, sein Name im Kopf
          („Geschlossen von“) und Erwähnungen durch „Gelöschter Nutzer“ ersetzt – der Rest gehört
          zum Anliegen des anderen Mitglieds und bleibt. (Transcripts älterer Versionen ohne
          Nutzer-IDs: nur Erwähnungen, Anzeigenamen sind nicht eindeutig zuzuordnen.)
        - Geschlossene Tickets: Inhaber-ID → 0, aus „hinzugefügt“ entfernt, Übernahme gelöscht,
          Modal-Antworten gelöscht; Übernahme-Statistik des Nutzers gelöscht.
        - **Offene** Tickets sind Betriebsdaten (Rechte, Limit, Schließen): bei ``user`` bleiben sie
          unverändert, bei ``owner``/``user_strict`` bleiben nur die IDs (Antworten werden gelöscht),
          bei ``discord_deleted_user`` (Konto gelöscht, ID ungültig) wird auch die ID entfernt.
        """
        uid = int(user_id)
        for key, draft in list(getattr(self, "_quick_reply_drafts", {}).items()):
            if key[-1] == uid or draft.get("owner_id") == uid:
                self._quick_reply_drafts.pop(key, None)
        drop_open_ids = requester == "discord_deleted_user"
        keep_open_answers = requester == "user"
        langs: dict[int, str] = {}
        creator_files: set[str] = set()
        try:
            all_guilds = await self.config.all_guilds()
        except Exception:  # noqa: BLE001
            log.exception("Datenlöschung: Config nicht lesbar")
            return
        for gid, gdata in all_guilds.items():
            langs[int(gid)] = (gdata or {}).get("language") or "de"
            gconf = self.config.guild_from_id(int(gid))
            try:
                async with gconf.tickets() as tickets:
                    for rec in tickets.values():
                        if not isinstance(rec, dict):
                            continue
                        is_open = rec.get("status") == "open"
                        involved = (rec.get("owner_id") == uid or rec.get("claimed_by") == uid
                                    or uid in (rec.get("members") or []))
                        if not involved:
                            continue
                        if is_open and not drop_open_ids:
                            if not keep_open_answers and rec.get("owner_id") == uid:
                                rec["answers"] = {}
                            continue
                        if rec.get("owner_id") == uid:
                            rec["owner_id"] = 0
                            rec["answers"] = {}
                        if rec.get("claimed_by") == uid:
                            rec["claimed_by"] = None
                        if uid in (rec.get("members") or []):
                            rec["members"] = [m for m in rec["members"] if m != uid]
                async with gconf.transcripts() as transcripts:
                    kept = []
                    for tr in transcripts:
                        if isinstance(tr, dict) and tr.get("owner_id") == uid:
                            if tr.get("file"):
                                creator_files.add(str(tr["file"]))
                            continue
                        if isinstance(tr, dict) and uid in (tr.get("members") or []):
                            tr["members"] = [m for m in tr["members"] if m != uid]
                        kept.append(tr)
                    transcripts[:] = kept
                async with gconf.stats() as stats:
                    claims = stats.get("claims")
                    if isinstance(claims, dict):
                        claims.pop(str(uid), None)
            except Exception:  # noqa: BLE001 – ein kaputter Server darf die anderen nicht blockieren
                log.exception("Datenlöschung für Guild %s fehlgeschlagen", gid)
        await asyncio.to_thread(self._scrub_transcript_files, uid, creator_files, langs)

    def _scrub_transcript_files(self, uid: int, creator_files: set, langs: dict) -> None:
        """Löscht Transcript-Dateien des Erstellers, schwärzt ihn in allen übrigen (blockierend).

        Geht über alle Dateien im Ordner – auch über solche, deren Metadaten schon aus der
        500er-Liste gefallen sind (Ersteller dann über ``Inhaber: <span data-uid=…>`` erkannt).
        """
        marker = str(uid)
        creator_head = f"Inhaber: <span data-uid='{uid}'>"
        for path in sorted(self.transcripts_dir.glob("*.html")):
            try:
                doc = path.read_text(encoding="utf-8")
                if path.name in creator_files or creator_head in doc:
                    path.unlink()
                    continue
                if marker not in doc:
                    continue
                gid = path.name.split("-", 1)[0]
                lang = langs.get(int(gid), "de") if gid.isdigit() else "de"
                new_doc, n = redact_user(doc, uid, t(lang, "deleted_user"))
                if n:
                    path.write_text(new_doc, encoding="utf-8")
            except OSError:
                log.exception("Transcript %s: Datenlöschung fehlgeschlagen", path.name)

    def _register_dashboard(self, webcore):
        page = dict(owner=self, slug="tickets", name="Tickets", icon="bi-life-preserver", handler=self.dashboard_page)
        try:
            # Tagesgeschäft für die Stufe „Bedienen“: einzelne Tickets schließen.
            webcore.register_page(**page, operate_forms={"ticket_close", "ticket_autoclose", "ticket_keepopen", "ticket_assign", "ticket_waiting", "ticket_priority", "ticket_reply_preview", "ticket_reply_send"})
        except TypeError:  # ältere WebCore-Versionen ohne Stufe „Bedienen“
            webcore.register_page(**page)
        if hasattr(webcore, "register_member_page"):  # ältere WebCore-Versionen ohne „Mein Bereich“
            webcore.register_member_page(
                owner=self,
                visible=lambda g: self.config.guild(g).portal_enabled(),
                slug="tickets",
                name="Meine Tickets",
                handler=self.member_page,
                icon="bi-life-preserver",
                description="Deine Tickets und Verläufe",
            )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    async def member_page(self, request):
        return await member_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    def _lock(self, *key) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    @staticmethod
    def _text(conf, lang, key, **values) -> str:
        """Wie ``t()``, berücksichtigt aber die pro-Server-Overrides aus dem Dashboard."""
        if key in OVERRIDABLE_KEYS:
            override = (conf.get("messages") or {}).get(key)
            if override:
                return _fill(override, **values)
        return t(lang, key, **values)

    @staticmethod
    def _open_count(conf, member_id) -> int:
        return sum(
            1 for r in (conf.get("tickets") or {}).values()
            if r.get("owner_id") == member_id and r.get("status") == "open"
        )

    def open_blocked(self, conf, member_id) -> str | None:
        """Warum ``member_id`` gerade kein Ticket öffnen darf (``"max_open"``) – sonst ``None``.

        Einzige Stelle für Öffnen-Sperren: Discord-Button (Vorprüfung + Prüfung unter dem Lock)
        und Website nutzen genau diese Funktion.
        """
        if self._open_count(conf, member_id) >= int(conf["max_open"]):
            return "max_open"
        return None

    @staticmethod
    def _channel_name(raw: str) -> str:
        s = (raw or "").lower().translate(_TRANSLIT).strip()
        s = re.sub(r"[^a-z0-9\-_]+", "-", s)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        return s[:90] or "ticket"

    @staticmethod
    def _has_any_role(member: discord.Member, role_ids) -> bool:
        ids = {int(r) for r in (role_ids or [])}
        return any(r.id in ids for r in getattr(member, "roles", []))

    def _is_bot_owner(self, member) -> bool:
        """Bot-Owner (inkl. Co-Owner) hat immer alle Rechte."""
        return getattr(member, "id", None) in (getattr(self.bot, "owner_ids", None) or set())

    def _is_admin(self, member: discord.Member, conf: dict) -> bool:
        if self._is_bot_owner(member) or member.guild_permissions.manage_guild:
            return True
        return self._has_any_role(member, conf.get("admin_roles"))

    def _is_staff(self, member: discord.Member, conf: dict, record: dict | None = None) -> bool:
        """Admin, globale Support-Rolle – oder das für DIESES Ticket zuständige Team
        (Team-Zuordnung je Grund). Ohne ``record`` zählen nur die globalen Rollen."""
        if self._is_admin(member, conf) or self._has_any_role(member, conf.get("support_roles")):
            return True
        return bool(record) and self._has_any_role(member, record.get("support_roles"))

    def _resolve_roles(self, guild, ids):
        out = []
        for rid in ids or []:
            role = guild.get_role(int(rid))
            if role is not None:
                out.append(role)
        return out

    def _overwrites(self, guild, member, conf, support_ids=None):
        # support_ids: die für dieses Ticket zuständigen Support-Rollen (typ-abhängig).
        # None -> globale Support-Rollen. Admin-Rollen haben immer Zugriff.
        if support_ids is None:
            support_ids = conf.get("support_roles")
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_channels=True, manage_messages=True,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True,
            ),
        }
        for role in self._resolve_roles(guild, support_ids) + self._resolve_roles(guild, conf.get("admin_roles")):
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        for role in self._resolve_roles(guild, conf.get("view_roles")):
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
        return ow

    def _closed_overwrites(self, guild, conf, support_ids=None):
        if support_ids is None:
            support_ids = conf.get("support_roles")
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
            ),
        }
        for role in self._resolve_roles(guild, support_ids) + self._resolve_roles(guild, conf.get("admin_roles")):
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        for role in self._resolve_roles(guild, conf.get("view_roles")):
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
        return ow

    def _find_panel(self, conf, panel_id):
        for p in conf.get("panels", []):
            if p.get("id") == panel_id:
                return p
        return None

    @staticmethod
    def _find_reason(panel, reason_id):
        if not reason_id or reason_id == "_":
            return None
        for r in panel.get("reasons") or []:
            if r.get("id") == reason_id:
                return r
        return None

    # --- Typ-abhängige Zuständigkeit (Team/Ping/Kategorie/Name) --------- #
    @staticmethod
    def _effective_support_ids(conf, reason):
        """Support-Rollen für dieses Ticket: die des Grundes, sonst die globalen."""
        if reason and reason.get("support_roles"):
            return list(reason["support_roles"])
        return conf.get("support_roles")

    @staticmethod
    def _effective_ping_ids(conf, reason):
        if reason and reason.get("ping_roles"):
            return list(reason["ping_roles"])
        return conf.get("ping_roles")

    @staticmethod
    def _effective_category_id(conf, reason):
        if reason and reason.get("category_id"):
            return reason["category_id"]
        return conf.get("category_open")

    def _ticket_base_name(self, conf, reason, num, member):
        """Kanalname: automatisch nach Typ (<grund>-<num>), sonst globale Vorlage."""
        label = (reason or {}).get("label") if reason else None
        if label:
            return f"{label}-{num}"
        return _fill(conf.get("name_template") or "ticket-{num}", num=num, user=member.name)

    # ----------------------------------------------------------------- #
    #  Panels posten / entfernen (vom Dashboard aufgerufen)
    # ----------------------------------------------------------------- #
    async def _panel_payload(self, guild, panel, *, emojis: bool = True):
        """Embed + View eines Panels (Overrides aus dem Dashboard berücksichtigt)."""
        conf = await self.config.guild(guild).all()
        lang = panel.get("lang") or conf["language"]
        title = panel.get("title") or self._text(conf, lang, "panel_default_title")
        desc = panel.get("description") or self._text(conf, lang, "panel_default_description")
        embed = discord.Embed(title=title[:256], description=desc[:4096], color=EMBED_COLOR)
        # Override "btn_open" gewinnt; sonst bleibt die bisherige Panel-Beschriftung.
        open_label = (conf.get("messages") or {}).get("btn_open")
        view = build_panel_view(panel, open_label=open_label, emojis=emojis)
        return embed, view

    async def _send_or_edit_panel(self, guild, panel, send):
        """Führt ``send(embed, view)`` aus. Lehnt Discord ein ungültiges Emoji ab
        (400), wird einmal ohne Emojis erneut versucht, statt das Panel zu verlieren."""
        embed, view = await self._panel_payload(guild, panel)
        try:
            return await send(embed, view)
        except discord.HTTPException as e:
            if e.status != 400:
                raise
            log.warning("Panel %s: Discord lehnt die Komponenten ab (%s) – ohne Emojis erneut.",
                        panel.get("id"), e.text)
        embed, view = await self._panel_payload(guild, panel, emojis=False)
        return await send(embed, view)

    async def post_panel(self, guild, panel) -> int | None:
        channel = guild.get_channel(panel.get("channel_id")) if panel.get("channel_id") else None
        if not isinstance(channel, discord.TextChannel):
            return None
        try:
            msg = await self._send_or_edit_panel(
                guild, panel, lambda e, v: channel.send(embed=e, view=v)
            )
            return msg.id
        except discord.HTTPException:
            log.exception("Panel konnte nicht gepostet werden (Guild %s)", guild.id)
            return None

    async def delete_panel_message(self, guild, panel):
        channel = guild.get_channel(panel.get("channel_id")) if panel.get("channel_id") else None
        if channel is None or not panel.get("message_id"):
            return
        try:
            msg = await channel.fetch_message(panel["message_id"])
            await msg.delete()
        except discord.HTTPException:
            pass

    async def update_panel_message(self, guild, panel) -> int | None:
        """Aktualisiert eine bereits gepostete Panel-Nachricht (Embed + Buttons).

        Existiert die Nachricht noch, wird sie an Ort und Stelle bearbeitet;
        andernfalls (oder bei fehlender ``message_id``) wird neu gepostet.
        """
        channel = guild.get_channel(panel.get("channel_id")) if panel.get("channel_id") else None
        if isinstance(channel, discord.TextChannel) and panel.get("message_id"):
            try:
                msg = await channel.fetch_message(panel["message_id"])
            except discord.HTTPException:
                msg = None
            if msg is not None:
                try:
                    await self._send_or_edit_panel(
                        guild, panel, lambda e, v: msg.edit(embed=e, view=v)
                    )
                    return msg.id
                except discord.HTTPException:
                    log.exception("Panel konnte nicht aktualisiert werden (Guild %s)", guild.id)
                    return msg.id  # alte Nachricht bleibt bestehen – nicht doppelt posten
        # Nachricht weg oder Kanal gewechselt -> neu posten
        return await self.post_panel(guild, panel)

    # ----------------------------------------------------------------- #
    #  Interaktionen (persistente Buttons / Dropdowns)
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        data = interaction.data or {}
        cid = data.get("custom_id", "")
        if not cid.startswith("tickets:") or interaction.guild is None:
            return

        try:
            if cid.startswith(CID_OPEN):
                _, _, panel_id, reason_id = cid.split(":", 3)
                await self._handle_open(interaction, panel_id, reason_id)
            elif cid.startswith(CID_SELECT):
                panel_id = cid.split(":", 2)[2]
                reason_id = (data.get("values") or ["_"])[0]
                await self._handle_open(interaction, panel_id, reason_id)
            elif cid == CID_CLOSE:
                await self._control_close(interaction)
            elif cid == CID_AUTOCLOSE:
                await self._control_autoclose(interaction, enabled=True)
            elif cid == CID_KEEP_OPEN:
                await self._control_autoclose(interaction, enabled=False)
            elif cid == CID_ASSIGN:
                await self._control_assign(interaction)
            elif cid in (CID_PRIORITY, CID_REPLY):
                await self._control_support(interaction, priority=cid == CID_PRIORITY)
            elif cid in (CID_WAIT_USER, CID_WAIT_TEAM):
                await interaction.response.defer(ephemeral=True)
                error = await self._set_waiting(
                    interaction.guild, interaction.channel, "user" if cid == CID_WAIT_USER else "team", interaction.user,
                )
                await interaction.followup.send(error or t(await self._lang(interaction.guild), "waiting_changed"),
                                                ephemeral=True)
            elif cid == CID_CLAIM:
                await self._control_claim(interaction, claim=True)
            elif cid == CID_UNCLAIM:
                await self._control_claim(interaction, claim=False)
            elif cid == CID_LOCK:
                await self._control_lock(interaction, lock=True)
            elif cid == CID_UNLOCK:
                await self._control_lock(interaction, lock=False)
        except discord.HTTPException:
            log.exception("Fehler beim Verarbeiten einer Ticket-Interaktion")

    async def _handle_open(self, interaction, panel_id, reason_id):
        guild = interaction.guild
        member = interaction.user
        conf = await self.config.guild(guild).all()
        panel = self._find_panel(conf, panel_id)
        lang = (panel or {}).get("lang") or conf["language"]
        if panel is None:
            await interaction.response.send_message(t(lang, "not_a_ticket"), ephemeral=True)
            return

        if self.open_blocked(conf, member.id):
            await interaction.response.send_message(
                t(lang, "max_open_reached", max=conf["max_open"]), ephemeral=True
            )
            return

        if panel.get("modal_questions"):
            await interaction.response.send_modal(
                TicketModal(self, panel_id, reason_id, panel["modal_questions"], lang)
            )
        else:
            await self.create_ticket_from_interaction(interaction, panel_id, reason_id, {})

    async def create_ticket_from_interaction(self, interaction, panel_id, reason_id, answers):
        guild = interaction.guild
        member = interaction.user
        conf = await self.config.guild(guild).all()
        panel = self._find_panel(conf, panel_id) or {}
        lang = panel.get("lang") or conf["language"]
        reason = self._find_reason(panel, reason_id)

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        result = await self.open_ticket(guild, member, panel, reason, answers)
        if result.status == "max_open":
            await interaction.followup.send(
                t(lang, "max_open_reached", max=result.max_open), ephemeral=True
            )
            return
        if result.target is None:
            await interaction.followup.send(t(lang, "create_failed"), ephemeral=True)
            return
        await interaction.followup.send(
            t(lang, "created_ephemeral", channel=result.target.mention), ephemeral=True
        )

    async def open_ticket(self, guild, member, panel, reason, answers) -> OpenResult:
        """Legt ein Ticket an – gemeinsamer Kern für den Discord-Button/-Modal und die Website.

        Pro Nutzer serialisiert + Limit frisch geprüft: ein Doppelklick (oder zwei offene
        Modals, zwei Browser-Tabs) erzeugt sonst zwei Tickets trotz "max. 1 offen".
        """
        async with self._lock("open", guild.id, member.id):
            conf = await self.config.guild(guild).all()
            if self.open_blocked(conf, member.id):
                return OpenResult("max_open", None, int(conf["max_open"]))
            try:
                target = await self._create_ticket(guild, member, conf, panel, reason, answers)
            except Exception:  # noqa: BLE001 – Nutzer darf nie im "denkt nach…" hängen bleiben
                log.exception("Unerwarteter Fehler bei der Ticket-Erstellung (Guild %s)", guild.id)
                target = None
        return OpenResult("ok" if target is not None else "failed", target, int(conf["max_open"]))

    async def read_transcript(self, record: dict) -> str | None:
        """HTML eines gespeicherten Transcripts (Dateiname aus den Metadaten) oder ``None``."""
        name = str(record.get("file") or "")
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        path = self.transcripts_dir / name

        def _read():
            try:
                return path.read_text(encoding="utf-8") if path.is_file() else None
            except OSError:
                log.exception("Transcript %s konnte nicht gelesen werden", name)
                return None
        return await asyncio.to_thread(_read)

    async def _create_ticket(self, guild, member, conf, panel, reason, answers):
        lang = panel.get("lang") or conf["language"]
        reason_label = (reason or {}).get("label") if reason else None

        async with self.config.guild(guild).counter.get_lock():
            num = await self.config.guild(guild).counter() + 1
            await self.config.guild(guild).counter.set(num)

        # Overrides unterstützen jetzt {num}/{user} in Titel UND Text (vorher blieb
        # "{num}" im eigenen Titel wörtlich stehen, kaputte Klammern im Text crashten).
        title = self._text(conf, lang, "opened_title", num=num, user=member.display_name)
        body = self._text(conf, lang, "opened_body", num=num, user=member.mention)
        embed = discord.Embed(title=title[:256], description=body[:4096], color=EMBED_COLOR)
        embed.set_footer(text=t(lang, "waiting_footer", user=t(lang, "unassigned"), status=t(lang, "waiting_team")))
        if reason_label:
            embed.add_field(name="​", value=t(lang, "opened_reason", reason=reason_label), inline=False)
        for q, a in (answers or {}).items():
            embed.add_field(name=q[:256], value=(a or "—")[:1024], inline=False)

        # Typ-abh\u00e4ngige Zust\u00e4ndigkeit: eigenes Team/Ping/Kategorie des Grundes,
        # sonst die globalen Einstellungen.
        eff_support = self._effective_support_ids(conf, reason)
        eff_ping = self._effective_ping_ids(conf, reason)
        eff_category = self._effective_category_id(conf, reason)
        ping_roles = self._resolve_roles(guild, eff_ping)
        support_roles = self._resolve_roles(guild, eff_support)
        base_name = self._ticket_base_name(conf, reason, num, member)
        controls = build_controls_view(lang)

        ttype = conf.get("ticket_type", "category")
        target = None
        opening_msg = None
        ping_content = " ".join(r.mention for r in ping_roles) or None

        try:
            if ttype == "forum":
                forum = guild.get_channel(conf.get("forum_channel")) if conf.get("forum_channel") else None
                if not isinstance(forum, discord.ForumChannel):
                    return None
                mentions = " ".join(r.mention for r in (ping_roles + support_roles)) or None
                created = await forum.create_thread(
                    name=(self._channel_name(base_name).replace("-", " "))[:100] or f"ticket {num}",
                    content=mentions or "\u200b",
                    embed=embed,
                    view=controls,
                    allowed_mentions=PING_ALLOWED,
                )
                target = created.thread
                opening_msg = created.message
                try:
                    await target.add_user(member)
                except discord.HTTPException:
                    pass

            elif ttype == "thread":
                base = guild.get_channel(conf.get("thread_base")) if conf.get("thread_base") else None
                if not isinstance(base, discord.TextChannel):
                    return None
                target = await base.create_thread(
                    name=base_name[:100] or f"ticket-{num}",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    reason=f"Ticket #{num} ({member})",
                )
                try:
                    await target.add_user(member)
                except discord.HTTPException:
                    pass
                mentions = " ".join(r.mention for r in (ping_roles + support_roles)) or None
                opening_msg = await target.send(
                    content=mentions, embed=embed, view=controls, allowed_mentions=PING_ALLOWED
                )

            else:  # category
                name = self._channel_name(base_name)
                category = guild.get_channel(eff_category) if eff_category else None
                target = await guild.create_text_channel(
                    name,
                    category=category if isinstance(category, discord.CategoryChannel) else None,
                    overwrites=self._overwrites(guild, member, conf, support_ids=eff_support),
                    reason=f"Ticket #{num} ({member})",
                )
                opening_msg = await target.send(
                    content=ping_content, embed=embed, view=controls, allowed_mentions=PING_ALLOWED
                )
        except discord.Forbidden:
            log.warning("Fehlende Rechte beim Erstellen eines Tickets (Guild %s)", guild.id)
            return None
        except discord.HTTPException:
            log.exception("Ticket-Erstellung fehlgeschlagen (Guild %s)", guild.id)
            return None

        # Inhaber-Rolle vergeben
        owner_role = guild.get_role(conf["owner_role"]) if conf.get("owner_role") else None
        if owner_role is not None:
            try:
                await member.add_roles(owner_role, reason=f"Ticket #{num}")
            except discord.HTTPException:
                pass

        record = {
            "num": num,
            "owner_id": member.id,
            "panel_id": panel.get("id"),
            "reason_id": (reason or {}).get("id"),
            "reason_label": reason_label,
            "support_roles": eff_support,      # zuständiges Team (für Schließen/Wiederöffnen)
            "category_id": eff_category,       # Kategorie dieses Typs (offen)
            "status": "open",
            "claimed_by": None,
            "waiting_for": "team",
            "priority": "normal",
            "locked": False,
            "type": ttype,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "auto_close_at": None,
            "auto_close_started_at": None,
            "message_id": opening_msg.id if opening_msg else None,
            "answers": answers or {},
        }
        reset_response(record, self._timer_time(record["created_at"]))
        record["support_synced_at"] = record["created_at"]
        async with self.config.guild(guild).tickets() as tickets:
            tickets[str(target.id)] = record
        async with self.config.guild(guild).stats() as stats:
            stats["opened"] = stats.get("opened", 0) + 1

        await self._log(guild, conf, t(lang, "log_opened", num=num, user=str(member), reason=reason_label or t(lang, "no_reason")))
        return target

    # ----------------------------------------------------------------- #
    #  Steuer-Aktionen
    # ----------------------------------------------------------------- #
    async def _get_record(self, guild, channel_id):
        tickets = await self.config.guild(guild).tickets()
        return tickets.get(str(channel_id))

    async def _refresh_controls(self, guild, channel, record, lang):
        # Auch Refreshes außerhalb der Aktionssperre müssen in fester Reihenfolge schreiben.
        async with self._lock("controls", channel.id):
            record = await self._get_record(guild, channel.id)
            if not record or not record.get("message_id"):
                return
            try:
                msg = await channel.fetch_message(record["message_id"])
                record = await self._get_record(guild, channel.id)
                if not record:
                    return
                payload = {}
                if msg.embeds:
                    embed = discord.Embed.from_dict(msg.embeds[0].to_dict())
                    assignee = guild.get_member(record.get("claimed_by")) if record.get("claimed_by") else None
                    name = (assignee.display_name if assignee is not None else (
                        f"ID {record['claimed_by']}" if record.get("claimed_by") else t(lang, "unassigned")))
                    embed.set_footer(text=t(lang, "waiting_footer", user=name,
                                            status=t(lang, "waiting_user" if record.get("waiting_for") == "user"
                                                     else "waiting_team")))
                    conf = await self.config.guild(guild).all()
                    due = support_due(record, conf)
                    extra = " · Dringend" if record.get("priority") == "urgent" else ""
                    if due is not None:
                        extra += " · " + ("Antwort fällig" if due <= datetime.now(timezone.utc) else "Antwort bis " + due.strftime("%d.%m. %H:%M UTC"))
                    embed.set_footer(text=embed.footer.text + extra)
                    payload["embed"] = embed
                await msg.edit(**payload, view=build_controls_view(
                    lang, claimed=bool(record.get("claimed_by")), locked=bool(record.get("locked")),
                    auto_close=bool(record.get("auto_close_at")),
                    waiting_for=record.get("waiting_for", "team"),
                    priority=record.get("priority", "normal"),
                ) if record.get("status") == "open" else None)
            except discord.HTTPException:
                pass

    @staticmethod
    def _timer_time(value) -> datetime | None:
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _human_message(message) -> bool:
        return (
            not getattr(message.author, "bot", False)
            and not getattr(message, "webhook_id", None)
            and getattr(message, "type", discord.MessageType.default)
            in (discord.MessageType.default, discord.MessageType.reply)
        )

    async def _control_autoclose(self, interaction, enabled: bool):
        guild, channel, member = interaction.guild, interaction.channel, interaction.user
        conf = await self.config.guild(guild).all()
        lang = conf["language"]
        record = conf["tickets"].get(str(channel.id))
        if not record:
            return await interaction.response.send_message(t(lang, "not_a_ticket"), ephemeral=True)
        is_owner = record.get("owner_id") == member.id
        # Der Ersteller darf einen Timer auch dann stoppen, wenn nur das Team schließen darf.
        if not (self._is_staff(member, conf, record)
                or (is_owner and (not enabled or conf["user_can_close"]))):
            return await interaction.response.send_message(t(lang, "no_permission"), ephemeral=True)
        if record.get("status") != "open":
            return await interaction.response.send_message(t(lang, "already_closed"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        changed = await self._set_ticket_autoclose(guild, channel, enabled, member, conf)
        key = ("autoclose_ack" if enabled else "keep_open_ack") if changed else "already_closed"
        await interaction.followup.send(t(lang, key), ephemeral=True)

    async def _set_ticket_autoclose(self, guild, channel, enabled, actor, conf) -> bool:
        """Start/Abbruch aus Discord und Dashboard, mit derselben Sperre wie Schließen."""
        async with self._lock("close", channel.id):
            now = datetime.now(timezone.utc)
            async with self.config.guild(guild).tickets() as tickets:
                record = tickets.get(str(channel.id))
                if not record or record.get("status") != "open":
                    return False
                record["auto_close_at"] = (now + INACTIVITY_TIMEOUT).isoformat() if enabled else None
                record["auto_close_started_at"] = now.isoformat() if enabled else None
                record["auto_close_reminded_for"] = None
                record = dict(record)
            self._latest_activity.pop(channel.id, None)
            if enabled:
                self._active_timer_channels.add(channel.id)
            else:
                self._active_timer_channels.discard(channel.id)
            lang = conf["language"]
            try:
                await channel.send(
                    t(lang, "autoclose_started" if enabled else "autoclose_cancelled", user=actor.mention),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                log.warning("Timer-Hinweis für Ticket %s nicht sendbar", channel.id)
            await self._refresh_controls(guild, channel, record, lang)
            return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or not self._human_message(message):
            return
        cid = message.channel.id
        stamp = message.created_at.astimezone(timezone.utc)
        if cid in self._active_timer_channels:
            self._latest_activity[cid] = max(stamp, self._latest_activity.get(cid, stamp))
        record = await self._get_record(message.guild, cid)
        if not record or record.get("status") != "open":
            return
        if record.get("auto_close_at"):
            self._latest_activity[cid] = max(stamp, self._latest_activity.get(cid, stamp))
        conf = await self.config.guild(message.guild).all()
        if record.get("support_history_unconfirmed"):
            await self._sync_support_history(message.guild, message.channel, conf)
        is_staff = self._is_staff(message.author, conf, record) and message.author.id != record.get("owner_id")
        async with self._lock("close", cid):
            async with self.config.guild(message.guild).tickets() as tickets:
                current = tickets.get(str(cid))
                if not current or current.get("status") != "open":
                    return
                if human_reply(current, is_staff, stamp):
                    self._pending_control_refresh.add((message.guild.id, cid))
                deadline = self._timer_time(current.get("auto_close_at"))
                if deadline is not None:
                    current["auto_close_at"] = max(deadline, stamp + INACTIVITY_TIMEOUT).isoformat()
                    if current["auto_close_at"] != deadline.isoformat():
                        current["auto_close_reminded_for"] = None

    async def _set_waiting(self, guild, channel, status, actor, *, check_actor=True):
        async with self._lock("close", channel.id):
            conf = await self.config.guild(guild).all()
            lang = conf["language"]
            record = conf["tickets"].get(str(channel.id))
            if not record:
                return t(lang, "not_a_ticket")
            if check_actor and not self._is_staff(actor, conf, record):
                return t(lang, "no_permission")
            if record.get("status") != "open":
                return t(lang, "already_closed")
            if status not in ("user", "team"):
                return t(lang, "no_permission")
            async with self.config.guild(guild).tickets() as tickets:
                set_waiting(tickets[str(channel.id)], status)
            await self._refresh_controls(guild, channel, record, lang)
            return None

    async def _reply_access(self, guild, channel, actor):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return "Das Ticketsystem ist auf diesem Server deaktiviert."
        conf = await self.config.guild(guild).all()
        record = conf["tickets"].get(str(channel.id))
        if not record:
            return "Das ist kein Ticket."
        if record.get("status") != "open":
            return "Dieses Ticket ist bereits geschlossen."
        if actor is None or not self._is_staff(actor, conf, record):
            return "Dafür brauchst du die Support-Rechte dieses Tickets."
        if not self._is_bot_owner(actor):
            permissions = channel.permissions_for(actor)
            if not (permissions.view_channel and permissions.read_message_history
                    and (permissions.send_messages_in_threads if isinstance(channel, discord.Thread) else permissions.send_messages)):
                return "Du musst dieses Ticket lesen und darin schreiben dürfen."
        return None

    async def _prepare_reply(self, guild, channel, actor, reply_id):
        error = await self._reply_access(guild, channel, actor)
        if error:
            return error, None
        conf = await self.config.guild(guild).all()
        record = conf["tickets"].get(str(channel.id))
        if not record or record.get("status") != "open":
            return "Dieses Ticket ist bereits geschlossen.", None
        template = next((item for item in conf["quick_replies"] if item["id"] == reply_id), None)
        if template is None:
            return "Diese Schnellantwort existiert nicht mehr.", None
        try:
            return None, render_reply(template["text"], record, actor, guild.get_member(record["owner_id"]), conf["quick_reply_signature"])
        except ValueError as exc:
            return str(exc), None

    async def _send_support_reply(self, guild, channel, actor, text):
        text = str(text or "").strip()
        if not text or len(text) > MAX_REPLY or "\x00" in text:
            return "Die Antwort muss 1 bis 2000 Zeichen lang sein."
        async with self._lock("close", channel.id):
            error = await self._reply_access(guild, channel, actor)
            if error:
                return error
            permissions = channel.permissions_for(guild.me)
            if not permissions.view_channel or not (permissions.send_messages_in_threads if isinstance(channel, discord.Thread) else permissions.send_messages):
                return "Dem Bot fehlen Leserechte oder Schreibrechte im Ticket."
            try:
                if isinstance(channel, discord.Thread) and channel.archived:
                    await channel.edit(archived=False)
                await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                return "Antwort nicht gesendet – Discord-Kanalrechte prüfen und erneut versuchen."
            now = datetime.now(timezone.utc)
            async with self.config.guild(guild).tickets() as tickets:
                record = tickets[str(channel.id)]
                human_reply(record, actor.id != record.get("owner_id"), now)
                if record.get("auto_close_at"):
                    record["auto_close_at"] = (now + INACTIVITY_TIMEOUT).isoformat()
                    record["auto_close_reminded_for"] = None
            self._pending_control_refresh.add((guild.id, channel.id))
            return None

    async def _set_priority(self, guild, channel, priority, actor, *, check_actor=True):
        async with self._lock("close", channel.id):
            conf = await self.config.guild(guild).all()
            record = conf["tickets"].get(str(channel.id))
            if not record or record.get("status") != "open":
                return "Offenes Ticket nicht gefunden."
            if check_actor:
                error = await self._reply_access(guild, channel, actor)
                if error:
                    return error
            if priority not in ("normal", "urgent"):
                return "Priorität: normal oder urgent."
            async with self.config.guild(guild).tickets() as tickets:
                tickets[str(channel.id)]["priority"] = priority
            await self._refresh_controls(guild, channel, record, conf["language"])
            return None

    async def _control_support(self, interaction, *, priority):
        error = await self._reply_access(interaction.guild, interaction.channel, interaction.user)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        conf = await self.config.guild(interaction.guild).all()
        record = conf["tickets"].get(str(interaction.channel.id))
        if not priority and not conf["quick_replies"]:
            return await interaction.response.send_message("Noch keine Schnellantworten eingerichtet.", ephemeral=True)
        view = PriorityView(self, interaction.user.id, record.get("priority", "normal")) if priority else ReplyPicker(self, interaction.user.id, conf["quick_replies"])
        await interaction.response.send_message("Priorität wählen:" if priority else "Antwort wählen – vor dem Senden kannst du sie bearbeiten:", view=view, ephemeral=True)

    async def _mark_support_history_pending(self):
        for gid, conf in (await self.config.all_guilds()).items():
            if not conf.get("response_targets_enabled"):
                continue
            async with self.config.guild_from_id(int(gid)).tickets() as records:
                for record in records.values():
                    if record.get("status") == "open":
                        record["support_history_unconfirmed"] = True

    @commands.Cog.listener()
    async def on_resumed(self):
        await self._mark_support_history_pending()
        self._controls_restored = False

    @commands.Cog.listener()
    async def on_ready(self):
        # Auch ein vollständiger Gateway-Neuaufbau (nicht nur RESUMED) kann Antworten verpasst haben.
        await self.on_resumed()

    async def _sync_support_history(self, guild, channel, conf):
        if not conf.get("response_targets_enabled"):
            return
        async with self._lock("close", channel.id):
            record = await self._get_record(guild, channel.id)
            if not record or record.get("status") != "open":
                return
            after = self._timer_time(record.get("support_synced_at") or record.get("created_at"))
            now = datetime.now(timezone.utc)
            try:
                events = [message async for message in channel.history(limit=None, after=after, oldest_first=True)
                          if self._human_message(message)]
            except discord.HTTPException:
                async with self.config.guild(guild).tickets() as tickets:
                    tickets[str(channel.id)]["support_history_unconfirmed"] = True
                return
            async with self.config.guild(guild).tickets() as tickets:
                current = tickets.get(str(channel.id))
                if current is None or current.get("status") != "open":
                    return
                for message in events:
                    member = guild.get_member(message.author.id)
                    staff = member is not None and member.id != current.get("owner_id") and self._is_staff(member, conf, current)
                    human_reply(current, staff, message.created_at)
                current["support_synced_at"] = now.isoformat()
                current["support_history_unconfirmed"] = False

    @tasks.loop(seconds=60)
    async def _autoclose_loop(self):
        if not self._controls_restored:
            try:
                await self._restore_ticket_controls()
                self._controls_restored = True
            except Exception:  # noqa: BLE001 – beim nächsten Durchlauf erneut versuchen
                log.exception("Ticket-Steuerleisten konnten nicht wiederhergestellt werden")
        try:
            await self._retry_support_history()
            await self._check_autoclose()
            for gid, cid in list(self._pending_control_refresh):
                self._pending_control_refresh.discard((gid, cid))
                guild = self.bot.get_guild(gid)
                if guild is not None:
                    channel = guild.get_channel_or_thread(cid)
                    if channel is not None:
                        await self._refresh_controls(guild, channel, None, await self._lang(guild))
        except Exception:  # noqa: BLE001 – temporäre Config-Fehler dürfen den Timer nicht beenden
            log.exception("Ticket-Timer-Prüfung fehlgeschlagen")

    @_autoclose_loop.before_loop
    async def _before_autoclose_loop(self):
        await self.bot.wait_until_red_ready()

    async def _retry_support_history(self):
        for gid, conf in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(int(gid))
            if guild is None or not conf.get("response_targets_enabled") or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            for cid, record in conf["tickets"].items():
                if record.get("status") != "open" or not record.get("support_history_unconfirmed"):
                    continue
                try:
                    channel = guild.get_channel_or_thread(int(cid)) or await guild.fetch_channel(int(cid))
                    await self._sync_support_history(guild, channel, conf)
                except discord.HTTPException:
                    pass

    async def _restore_ticket_controls(self):
        for gid, conf in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(int(gid))
            if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            for cid, record in conf.get("tickets", {}).items():
                if record.get("status") != "open":
                    continue
                if record.get("auto_close_at"):
                    self._active_timer_channels.add(int(cid))
                # Auch bestehende Tickets bekommen die neuen persistenten Buttons.
                try:
                    channel = guild.get_channel_or_thread(int(cid))
                    if channel is None:
                        channel = await guild.fetch_channel(int(cid))
                    await self._sync_support_history(guild, channel, conf)
                    await self._refresh_controls(guild, channel, record, conf["language"])
                except discord.HTTPException:
                    log.warning("Steuerleiste für Ticket %s (Guild %s) nicht erreichbar", cid, gid)

    async def _check_autoclose(self):
        now = datetime.now(timezone.utc)
        for gid, conf in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(int(gid))
            if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            for cid, record in conf.get("tickets", {}).items():
                deadline = self._timer_time(record.get("auto_close_at"))
                if record.get("status") != "open" or deadline is None or deadline > now + timedelta(hours=1):
                    continue
                try:
                    channel = guild.get_channel_or_thread(int(cid))
                    if channel is None:
                        channel = await guild.fetch_channel(int(cid))
                    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                        continue
                    if deadline > now:
                        await self._remind_autoclose(guild, channel, conf)
                    else:
                        await self._close_ticket(guild, channel, record, guild.me, conf, inactivity=True)
                except Exception:  # noqa: BLE001 – ein Ticket darf andere Timer nicht blockieren
                    log.exception("Auto-Close für Ticket %s (Guild %s) fehlgeschlagen", cid, gid)

    async def _remind_autoclose(self, guild, channel, conf):
        async with self._lock("close", channel.id):
            record = await self._get_record(guild, channel.id)
            now = datetime.now(timezone.utc)
            deadline = self._timer_time((record or {}).get("auto_close_at"))
            if not record or record.get("status") != "open" or deadline is None:
                return
            if not now < deadline <= now + timedelta(hours=1) or record.get("auto_close_reminded_for") == deadline.isoformat():
                return
            deadline, _deferred = await self._deadline_after_history(guild, channel, record, deadline, now)
            pending = self._latest_activity.get(channel.id)
            if pending is not None:
                deadline = max(deadline, pending + INACTIVITY_TIMEOUT)
            if not now < deadline <= now + timedelta(hours=1):
                return
            owner_id = record.get("owner_id")
            await channel.send(t(conf["language"], "close_reminder", user=f"<@{owner_id}>" if owner_id else "",
                                 deadline=int(deadline.timestamp())), view=build_reminder_view(conf["language"]),
                               allowed_mentions=discord.AllowedMentions(everyone=False, roles=False,
                                                                         users=[discord.Object(owner_id)] if owner_id else False))
            async with self.config.guild(guild).tickets() as tickets:
                tickets[str(channel.id)]["auto_close_reminded_for"] = deadline.isoformat()

    async def _control_close(self, interaction):
        guild = interaction.guild
        channel = interaction.channel
        conf = await self.config.guild(guild).all()
        lang = conf["language"]
        record = conf["tickets"].get(str(channel.id))
        if not record:
            await interaction.response.send_message(t(lang, "not_a_ticket"), ephemeral=True)
            return
        member = interaction.user
        is_owner = record.get("owner_id") == member.id
        if not (self._is_staff(member, conf, record) or (is_owner and conf["user_can_close"])):
            await interaction.response.send_message(t(lang, "no_permission"), ephemeral=True)
            return
        if record.get("status") == "closed":
            await interaction.response.send_message(t(lang, "already_closed"), ephemeral=True)
            return

        if conf["close_confirmation"]:
            async def _confirmed(inter):
                await inter.response.edit_message(content="…", view=None)
                await self._close_ticket(guild, channel, record, member, conf)
            await interaction.response.send_message(
                t(lang, "confirm_close"), view=ConfirmView(_confirmed, lang), ephemeral=True
            )
        else:
            await interaction.response.defer()
            await self._close_ticket(guild, channel, record, member, conf)

    def _can_assign_to(self, guild, channel, record, conf, member) -> bool:
        if (member is None or getattr(member, "guild", None) != guild
                or getattr(member, "bot", False) or member.id == record.get("owner_id")
                or not self._is_staff(member, conf, record)):
            return False
        perms = channel.permissions_for(member)
        return (perms.view_channel and perms.read_message_history
                and (perms.send_messages_in_threads if isinstance(channel, discord.Thread) else perms.send_messages))

    async def _assign_ticket(self, guild, channel, member, actor, *, replace=True, check_actor=True):
        """Gemeinsame Zuständigkeit für Buttons, Befehle und das autorisierte Dashboard.

        ``None`` = erfolgreich; sonst eine übersetzte, sichtbare Fehlermeldung.
        Derselbe Kanal-Lock verhindert Rennen mit Übernehmen, Freigeben und Schließen.
        """
        async with self._lock("close", channel.id):
            conf = await self.config.guild(guild).all()
            lang = conf["language"]
            record = conf["tickets"].get(str(channel.id))
            if not record:
                return t(lang, "not_a_ticket")
            if check_actor and not self._is_staff(actor, conf, record):
                return t(lang, "no_permission")
            if record.get("status") != "open":
                return t(lang, "already_closed")
            if member is not None and not self._can_assign_to(guild, channel, record, conf, member):
                return t(lang, "assignment_invalid")
            previous = record.get("claimed_by")
            target_id = member.id if member is not None else None
            if not replace and previous and previous != target_id:
                return t(lang, "already_claimed", user=f"<@{previous}>")
            if previous == target_id:
                return t(lang, "assignment_unchanged")
            if member is not None and isinstance(channel, discord.Thread):
                try:
                    if channel.archived:
                        await channel.edit(archived=False)
                    await channel.add_user(member)
                except discord.HTTPException:
                    return t(lang, "assignment_access_failed")
            async with self.config.guild(guild).tickets() as tickets:
                tickets[str(channel.id)]["claimed_by"] = target_id
            record["claimed_by"] = target_id
            if member is not None:
                async with self.config.guild(guild).stats() as stats:
                    claims = stats.setdefault("claims", {})
                    claims[str(target_id)] = claims.get(str(target_id), 0) + 1
                notice = (t(lang, "claimed_by", user=member.mention) if member.id == actor.id
                          else t(lang, "assigned_by", user=member.mention, actor=actor.mention))
            else:
                notice = t(lang, "unclaimed_by", user=actor.mention)
            try:
                await channel.send(notice, allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=[member] if member is not None else False,
                ))
            except discord.HTTPException:
                log.warning("Zuweisungshinweis für Ticket %s nicht sendbar", channel.id)
            await self._log(guild, conf, t(lang, "log_assigned", num=record["num"],
                                          actor=str(actor), user=str(member) if member else t(lang, "unassigned")))
            await self._refresh_controls(guild, channel, record, lang)
            return None

    async def _control_assign(self, interaction):
        conf = await self.config.guild(interaction.guild).all()
        lang = conf["language"]
        record = conf["tickets"].get(str(interaction.channel.id))
        if not record:
            error = "not_a_ticket"
        elif not self._is_staff(interaction.user, conf, record):
            error = "no_permission"
        elif record.get("status") != "open":
            error = "already_closed"
        else:
            return await interaction.response.send_message(
                t(lang, "assign_prompt"), view=AssignmentView(self, interaction.user.id, lang), ephemeral=True,
            )
        await interaction.response.send_message(t(lang, error), ephemeral=True)

    async def _assign_from_interaction(self, interaction, member_id):
        await interaction.response.defer(ephemeral=True)
        lang = await self._lang(interaction.guild)
        member = interaction.guild.get_member(member_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(member_id)
            except discord.HTTPException:
                await interaction.followup.send(t(lang, "assignment_invalid"), ephemeral=True)
                return False
        error = await self._assign_ticket(interaction.guild, interaction.channel, member, interaction.user)
        if error:
            await interaction.followup.send(error, ephemeral=True)
        return error is None

    async def _control_claim(self, interaction, claim: bool):
        await interaction.response.defer(ephemeral=True)
        error = await self._assign_ticket(
            interaction.guild, interaction.channel, interaction.user if claim else None,
            interaction.user, replace=not claim,
        )
        lang = await self._lang(interaction.guild)
        await interaction.followup.send(error or t(lang, "assignment_done"), ephemeral=True)

    async def _control_lock(self, interaction, lock: bool):
        guild = interaction.guild
        channel = interaction.channel
        conf = await self.config.guild(guild).all()
        lang = conf["language"]
        record = conf["tickets"].get(str(channel.id))
        if not record:
            await interaction.response.send_message(t(lang, "not_a_ticket"), ephemeral=True)
            return
        member = interaction.user
        if not self._is_staff(member, conf, record):
            await interaction.response.send_message(t(lang, "no_permission"), ephemeral=True)
            return
        await interaction.response.defer()
        await self._set_locked(guild, channel, record, conf, lock)
        await channel.send(t(lang, "locked_by" if lock else "unlocked_by", user=member.mention))
        async with self.config.guild(guild).tickets() as tickets:
            if str(channel.id) in tickets:
                tickets[str(channel.id)]["locked"] = lock
        record["locked"] = lock
        await self._refresh_controls(guild, channel, record, lang)

    async def _set_locked(self, guild, channel, record, conf, lock: bool):
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(locked=lock)
            else:
                owner = guild.get_member(record["owner_id"])
                if owner is not None:
                    ow = channel.overwrites_for(owner)
                    ow.send_messages = not lock
                    await channel.set_permissions(owner, overwrite=ow)
        except discord.HTTPException:
            pass

    async def _deadline_after_history(self, guild, channel, record, deadline, now):
        """Unter der Kanalsperre: Offline-Antworten und laufende Gateway-Nachrichten prüfen."""
        started = self._timer_time(record.get("auto_close_started_at"))
        after = max(started or now - INACTIVITY_TIMEOUT, now - INACTIVITY_TIMEOUT)
        latest = self._latest_activity.get(channel.id)
        async for message in channel.history(limit=None, after=after, oldest_first=False):
            if self._human_message(message):
                stamp = message.created_at.astimezone(timezone.utc)
                latest = max(latest, stamp) if latest is not None else stamp
                break
        pending = self._latest_activity.get(channel.id)
        if pending is not None:
            latest = max(latest, pending) if latest is not None else pending
        if latest is not None:
            deadline = max(deadline, latest + INACTIVITY_TIMEOUT)
        deferred = deadline > datetime.now(timezone.utc)
        if deferred:
            async with self.config.guild(guild).tickets() as tickets:
                tickets[str(channel.id)]["auto_close_at"] = deadline.isoformat()
        # Ein überfälliger Pfad hat ab der letzten Aktivitätsprüfung kein weiteres await.
        return deadline, deferred

    async def _close_ticket(self, guild, channel, record, closer, conf, *, inactivity=False) -> bool:
        """Schließt (bzw. löscht) ein Ticket. Pro Kanal serialisiert; ein bereits
        geschlossenes Ticket wird nicht erneut gezählt/transkribiert."""
        async with self._lock("close", channel.id):
            current = await self._get_record(guild, channel.id)
            if current is None:
                return False
            if inactivity:
                now = datetime.now(timezone.utc)
                deadline = self._timer_time(current.get("auto_close_at"))
                if current.get("status") != "open" or deadline is None or deadline > now:
                    return False
                deadline, deferred = await self._deadline_after_history(guild, channel, current, deadline, now)
                if deferred:
                    return False
                current["auto_closed"] = True
            if current.get("status") == "closed":
                if conf["delete_on_close"]:  # z. B. [p]ticket delete auf archiviertem Ticket
                    async with self.config.guild(guild).tickets() as tickets:
                        tickets.pop(str(channel.id), None)
                    try:
                        await channel.delete(reason=f"Ticket #{record['num']} gelöscht")
                    except discord.HTTPException:
                        pass
                return False
            await self._close_ticket_locked(guild, channel, current, closer, conf)
            self._active_timer_channels.discard(channel.id)
            self._latest_activity.pop(channel.id, None)
            await self._refresh_controls(guild, channel, current, conf["language"])
            return True

    async def _close_ticket_locked(self, guild, channel, record, closer, conf):
        lang = conf["language"]
        record["status"] = "closed"
        record["closed_at"] = datetime.now(timezone.utc).isoformat()

        # Laufzeit
        try:
            opened = datetime.fromisoformat(record["created_at"])
            duration = int((datetime.now(timezone.utc) - opened).total_seconds())
        except (KeyError, ValueError):
            duration = 0

        # Transcript
        owner = guild.get_member(record["owner_id"])
        meta = {
            "num": record["num"],
            "channel_name": getattr(channel, "name", "ticket"),
            "owner": str(owner) if owner else record["owner_id"],
            "reason": record.get("reason_label"),
            "opened": record.get("created_at", "")[:19].replace("T", " "),
            "closed": record["closed_at"][:19].replace("T", " "),
            "closed_by": str(closer) + (" · " + t(lang, "auto_closed") if record.get("auto_closed") else ""),
            "owner_id": record.get("owner_id"),       # nur als data-uid (Datenlöschung)
            "closed_by_id": getattr(closer, "id", None),
        }
        filename = f"{guild.id}-{record['num']}.html"
        try:
            html_doc = await build_transcript(channel, meta)
            (self.transcripts_dir / filename).write_text(html_doc, encoding="utf-8")
            async with self.config.guild(guild).transcripts() as transcripts:
                transcripts.append({
                    "num": record["num"],
                    "channel_name": meta["channel_name"],
                    "owner": meta["owner"],
                    "owner_id": record["owner_id"],
                    "members": list(record.get("members") or []),  # per [p]ticket add hinzugefügt
                    "reason": record.get("reason_label"),
                    "closed": meta["closed"],
                    "file": filename,
                })
                del transcripts[:-500]  # nur die letzten 500 Metadaten behalten
        except OSError:
            log.exception("Transcript konnte nicht gespeichert werden")

        # Statistik
        async with self.config.guild(guild).stats() as stats:
            stats["closed"] = stats.get("closed", 0) + 1
            stats["duration_sum"] = stats.get("duration_sum", 0) + duration

        # Log
        await self._log(
            guild, conf,
            t(lang, "log_closed", num=record["num"], user=str(closer),
              duration=self._fmt_dur(duration))
            + (" " + t(lang, "auto_closed") if record.get("auto_closed") else ""),
            transcript_file=self.transcripts_dir / filename,
        )

        # Inhaber-Rolle entfernen
        owner_role = guild.get_role(conf["owner_role"]) if conf.get("owner_role") else None
        if owner_role is not None and owner is not None:
            try:
                await owner.remove_roles(owner_role, reason=f"Ticket #{record['num']} geschlossen")
            except discord.HTTPException:
                pass

        if conf["delete_on_close"]:
            async with self.config.guild(guild).tickets() as tickets:
                tickets.pop(str(channel.id), None)
            try:
                await channel.delete(reason=f"Ticket #{record['num']} geschlossen")
            except discord.HTTPException:
                pass
            return

        # Archivieren statt löschen
        try:
            await channel.send(t(lang, "auto_closed") if record.get("auto_closed")
                               else t(lang, "closed_by", user=closer.mention))
        except discord.HTTPException:
            pass
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(archived=True, locked=True)
            else:
                closed_cat = guild.get_channel(conf.get("category_close")) if conf.get("category_close") else None
                await channel.edit(
                    category=closed_cat if isinstance(closed_cat, discord.CategoryChannel) else channel.category,
                    overwrites=self._closed_overwrites(guild, conf, support_ids=record.get("support_roles")),
                    reason=f"Ticket #{record['num']} geschlossen",
                )
        except discord.HTTPException:
            pass

        async with self.config.guild(guild).tickets() as tickets:
            if str(channel.id) in tickets:
                tickets[str(channel.id)]["status"] = "closed"
                set_waiting(tickets[str(channel.id)], "user")
                tickets[str(channel.id)]["closed_at"] = record["closed_at"]
                tickets[str(channel.id)]["auto_close_at"] = None
                tickets[str(channel.id)]["auto_close_started_at"] = None

    async def _reopen_ticket(self, guild, channel, record, conf):
        owner = guild.get_member(record["owner_id"])
        owner_role = guild.get_role(conf["owner_role"]) if conf.get("owner_role") else None
        if owner_role is not None and owner is not None:
            try:
                await owner.add_roles(owner_role, reason=f"Ticket #{record['num']} wieder geöffnet")
            except discord.HTTPException:
                pass
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(archived=False, locked=False)
            else:
                cat_id = record.get("category_id") or conf.get("category_open")
                open_cat = guild.get_channel(cat_id) if cat_id else None
                await channel.edit(
                    category=open_cat if isinstance(open_cat, discord.CategoryChannel) else channel.category,
                    overwrites=self._overwrites(guild, owner or guild.me, conf, support_ids=record.get("support_roles")),
                )
        except discord.HTTPException:
            pass
        async with self.config.guild(guild).tickets() as tickets:
            if str(channel.id) in tickets:
                tickets[str(channel.id)]["status"] = "open"
                reset_response(tickets[str(channel.id)])
                tickets[str(channel.id)]["waiting_for"] = "team"
                tickets[str(channel.id)]["support_synced_at"] = datetime.now(timezone.utc).isoformat()
                tickets[str(channel.id)]["auto_close_at"] = None
                tickets[str(channel.id)]["auto_close_started_at"] = None
        self._active_timer_channels.discard(channel.id)
        self._latest_activity.pop(channel.id, None)
        record = await self._get_record(guild, channel.id)
        if record is not None:
            await self._refresh_controls(guild, channel, record, conf["language"])

    async def _log(self, guild, conf, text, transcript_file=None):
        chan = guild.get_channel(conf.get("log_channel")) if conf.get("log_channel") else None
        if not isinstance(chan, (discord.TextChannel, discord.Thread)):
            return
        embed = discord.Embed(description=text, color=EMBED_COLOR, timestamp=datetime.now(timezone.utc))
        try:
            file = discord.File(str(transcript_file), filename=transcript_file.name) if transcript_file and transcript_file.exists() else None
            await chan.send(embed=embed, file=file)
        except discord.HTTPException:
            pass

    @staticmethod
    def _fmt_dur(seconds: int) -> str:
        if seconds <= 0:
            return "0m"
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h}h {m}m" if h else f"{m}m"

    # ----------------------------------------------------------------- #
    #  Befehle – im Ticket
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="ticket")
    @commands.guild_only()
    async def ticket(self, ctx):
        """Befehle innerhalb eines Tickets."""

    async def _ctx_record(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        record = conf["tickets"].get(str(ctx.channel.id))
        return conf, record

    @ticket.command(name="close")
    async def ticket_close(self, ctx, *, reason: str = None):
        """Schließt das aktuelle Ticket."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        is_owner = record.get("owner_id") == ctx.author.id
        if not (self._is_staff(ctx.author, conf, record) or (is_owner and conf["user_can_close"])):
            return await ctx.send(t(lang, "no_permission"))
        if record.get("status") == "closed":
            return await ctx.send(t(lang, "already_closed"))
        await ctx.send("🔒")
        await self._close_ticket(ctx.guild, ctx.channel, record, ctx.author, conf)

    @ticket.command(name="autoclose")
    async def ticket_autoclose(self, ctx):
        """Startet den 24-Stunden-Timer; neue Nachrichten setzen ihn zurück."""
        await self._ctx_autoclose(ctx, enabled=True)

    @ticket.command(name="keepopen")
    async def ticket_keepopen(self, ctx):
        """Stoppt den Timer dauerhaft, bis er erneut gestartet wird."""
        await self._ctx_autoclose(ctx, enabled=False)

    async def _ctx_autoclose(self, ctx, enabled):
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        is_owner = record.get("owner_id") == ctx.author.id
        if not (self._is_staff(ctx.author, conf, record)
                or (is_owner and (not enabled or conf["user_can_close"]))):
            return await ctx.send(t(lang, "no_permission"))
        await ctx.defer(ephemeral=True)
        changed = await self._set_ticket_autoclose(ctx.guild, ctx.channel, enabled, ctx.author, conf)
        key = ("autoclose_ack" if enabled else "keep_open_ack") if changed else "already_closed"
        await ctx.send(t(lang, key), ephemeral=True)

    @ticket.command(name="open")
    async def ticket_open(self, ctx):
        """Öffnet ein geschlossenes (archiviertes) Ticket wieder."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf, record):
            return await ctx.send(t(lang, "no_permission"))
        if record.get("status") != "closed":
            return await ctx.send(t(lang, "not_closed"))
        await self._reopen_ticket(ctx.guild, ctx.channel, record, conf)
        await ctx.send(t(lang, "reopened_by", user=ctx.author.mention))

    @ticket.command(name="waiting")
    async def ticket_waiting(self, ctx, status: Literal["user", "team"]):
        """Setzt Wartet auf Nutzer (user) oder Team (team)."""
        await ctx.defer(ephemeral=True)
        error = await self._set_waiting(ctx.guild, ctx.channel, status, ctx.author)
        await ctx.send(error or t(await self._lang(ctx.guild), "waiting_changed"), ephemeral=True)

    @ticket.command(name="priority")
    async def ticket_priority(self, ctx, priority: Literal["normal", "urgent"]):
        """Setzt die Priorität, ohne die bereits gewartete Teamzeit zurückzusetzen."""
        await ctx.defer(ephemeral=True)
        error = await self._set_priority(ctx.guild, ctx.channel, priority, ctx.author)
        await ctx.send(error or "Priorität aktualisiert.", ephemeral=True)

    @ticket.command(name="claim")
    async def ticket_claim(self, ctx):
        """Übernimmt das aktuelle Ticket."""
        await self._ctx_assign(ctx, ctx.author, replace=False)

    @ticket.command(name="assign")
    async def ticket_assign(self, ctx, member: discord.Member):
        """Weist das aktuelle Ticket einem Teammitglied zu (auch Übergabe)."""
        await self._ctx_assign(ctx, member)

    @ticket.command(name="unclaim")
    async def ticket_unclaim(self, ctx):
        """Gibt das aktuelle Ticket wieder frei."""
        await self._ctx_assign(ctx, None)

    async def _ctx_assign(self, ctx, member, *, replace=True):
        await ctx.defer(ephemeral=True)
        error = await self._assign_ticket(ctx.guild, ctx.channel, member, ctx.author, replace=replace)
        lang = await self._lang(ctx.guild)
        await ctx.send(error or t(lang, "assignment_done"), ephemeral=True)

    @ticket.command(name="add")
    async def ticket_add(self, ctx, member: discord.Member):
        """Fügt ein Mitglied zum Ticket hinzu."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf, record):
            return await ctx.send(t(lang, "no_permission"))
        try:
            if isinstance(ctx.channel, discord.Thread):
                await ctx.channel.add_user(member)
            else:
                await ctx.channel.set_permissions(
                    member, overwrite=discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
                )
        except discord.HTTPException:
            pass
        async with self.config.guild(ctx.guild).tickets() as tickets:
            rec = tickets.get(str(ctx.channel.id))
            if rec is not None and member.id not in (rec.get("members") or []):
                rec.setdefault("members", []).append(member.id)
        await ctx.send(t(lang, "member_added", user=member.mention))

    @ticket.command(name="remove")
    async def ticket_remove(self, ctx, member: discord.Member):
        """Entfernt ein Mitglied aus dem Ticket."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf, record):
            return await ctx.send(t(lang, "no_permission"))
        try:
            if isinstance(ctx.channel, discord.Thread):
                await ctx.channel.remove_user(member)
            else:
                await ctx.channel.set_permissions(member, overwrite=None)
        except discord.HTTPException:
            pass
        async with self.config.guild(ctx.guild).tickets() as tickets:
            rec = tickets.get(str(ctx.channel.id))
            if rec is not None and member.id in (rec.get("members") or []):
                rec["members"] = [m for m in rec["members"] if m != member.id]
        await ctx.send(t(lang, "member_removed", user=member.mention))

    @ticket.command(name="rename")
    async def ticket_rename(self, ctx, *, name: str):
        """Benennt das Ticket um."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf, record):
            return await ctx.send(t(lang, "no_permission"))
        new_name = name[:100] if isinstance(ctx.channel, discord.Thread) else self._channel_name(name)
        try:
            await ctx.channel.edit(name=new_name)
        except discord.HTTPException:
            pass
        await ctx.send(t(lang, "renamed_to", name=new_name))

    @ticket.command(name="owner")
    async def ticket_owner(self, ctx, member: discord.Member):
        """Ändert den Inhaber des Tickets."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf, record):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(ctx.guild).tickets() as tickets:
            rec = tickets.get(str(ctx.channel.id))
            if rec:
                rec["owner_id"] = member.id
        if isinstance(ctx.channel, discord.Thread):
            try:
                await ctx.channel.add_user(member)
            except discord.HTTPException:
                pass
        else:
            try:
                await ctx.channel.set_permissions(
                    member, overwrite=discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True, attach_files=True
                    )
                )
            except discord.HTTPException:
                pass
        await ctx.send(t(lang, "owner_changed", user=member.mention))

    @ticket.command(name="delete")
    async def ticket_delete(self, ctx):
        """Löscht das Ticket endgültig (nur Admin)."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_admin(ctx.author, conf):
            return await ctx.send(t(lang, "no_permission"))
        # Transcript trotzdem sichern
        conf_force = dict(conf)
        conf_force["delete_on_close"] = True
        await self._close_ticket(ctx.guild, ctx.channel, record, ctx.author, conf_force)

    @ticket.command(name="list")
    async def ticket_list(self, ctx, status: str = "open"):
        """Listet Tickets (open/closed/all)."""
        conf, _ = await self._ctx_record(ctx)
        # Globales Team/Admins sehen alles; ein Team eines Grundes nur "seine" Tickets.
        full = self._is_staff(ctx.author, conf)
        visible = {
            cid: rec for cid, rec in conf["tickets"].items()
            if full or self._is_staff(ctx.author, conf, rec)
        }
        if not full and not visible:
            return await ctx.send(t(conf["language"], "no_permission"))
        status = status.lower()
        lines = []
        for cid, rec in visible.items():
            if status in ("open", "closed") and rec.get("status") != status:
                continue
            owner = ctx.guild.get_member(rec.get("owner_id"))
            who = owner.mention if owner else (rec.get("owner_id") or t(conf["language"], "deleted_user"))
            lines.append(f"#{rec.get('num')} · <#{cid}> · {who} · {rec.get('status')}")
        if not lines:
            return await ctx.send(embed=discord.Embed(title="Tickets", description="—", color=EMBED_COLOR))
        # Zeilenweise auf mehrere Embeds verteilen statt mitten in einer Zeile abzuschneiden.
        pages, cur = [], ""
        for line in lines:
            if len(cur) + len(line) + 1 > 4000:
                pages.append(cur)
                cur = ""
            cur += line + "\n"
        pages.append(cur)
        for i, page in enumerate(pages[:5], 1):
            title = "Tickets" if len(pages) == 1 else f"Tickets ({i}/{len(pages)})"
            await ctx.send(embed=discord.Embed(title=title, description=page, color=EMBED_COLOR))

    # ----------------------------------------------------------------- #
    #  Befehle – Konfiguration (das Meiste läuft übers Dashboard)
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="ticketset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def ticketset(self, ctx):
        """Konfiguration des Ticketsystems (Feineinstellungen im Dashboard)."""

    @ticketset.command(name="language")
    async def ticketset_language(self, ctx, code: str):
        """Sprache setzen (z. B. de, en)."""
        code = code.lower()
        if code not in LANGUAGES:
            return await ctx.send(f"Verfügbare Sprachen: {', '.join(LANGUAGES)}")
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(f"Sprache: **{LANGUAGES[code]}**.")

    @ticketset.command(name="type")
    async def ticketset_type(self, ctx, kind: str):
        """Ticket-Typ: category | thread | forum."""
        kind = kind.lower()
        if kind not in ("category", "thread", "forum"):
            return await ctx.send("Erlaubt: category, thread, forum.")
        await self.config.guild(ctx.guild).ticket_type.set(kind)
        await ctx.send(f"Ticket-Typ: **{kind}**.")

    async def _toggle_role(self, ctx, key, role):
        async with self.config.guild(ctx.guild).get_attr(key)() as ids:
            if role.id in ids:
                ids.remove(role.id)
                action = "entfernt"
            else:
                ids.append(role.id)
                action = "hinzugefügt"
        await ctx.send(f"Rolle {role.mention} {action}.")

    @ticketset.command(name="support")
    async def ticketset_support(self, ctx, role: discord.Role):
        """Support-Rolle an-/abschalten."""
        await self._toggle_role(ctx, "support_roles", role)

    @ticketset.command(name="admin")
    async def ticketset_admin(self, ctx, role: discord.Role):
        """Admin-Rolle an-/abschalten."""
        await self._toggle_role(ctx, "admin_roles", role)

    @ticketset.command(name="view")
    async def ticketset_view(self, ctx, role: discord.Role):
        """View-Rolle (nur lesen) an-/abschalten."""
        await self._toggle_role(ctx, "view_roles", role)

    @ticketset.command(name="ping")
    async def ticketset_ping(self, ctx, role: discord.Role):
        """Ping-Rolle an-/abschalten."""
        await self._toggle_role(ctx, "ping_roles", role)

    @ticketset.command(name="ownerrole")
    async def ticketset_ownerrole(self, ctx, role: discord.Role = None):
        """Inhaber-Rolle setzen (ohne Argument: entfernen)."""
        await self.config.guild(ctx.guild).owner_role.set(role.id if role else None)
        await ctx.send("Inhaber-Rolle gesetzt." if role else "Inhaber-Rolle entfernt.")

    @ticketset.command(name="category")
    async def ticketset_category(self, ctx, open_cat: discord.CategoryChannel, closed_cat: discord.CategoryChannel = None):
        """Kategorien für offene (und optional geschlossene) Tickets."""
        await self.config.guild(ctx.guild).category_open.set(open_cat.id)
        if closed_cat:
            await self.config.guild(ctx.guild).category_close.set(closed_cat.id)
        await ctx.send("Kategorien gesetzt.")

    @ticketset.command(name="threadbase")
    async def ticketset_threadbase(self, ctx, channel: discord.TextChannel):
        """Basis-Kanal für den Thread-Modus."""
        await self.config.guild(ctx.guild).thread_base.set(channel.id)
        await ctx.send(f"Basis-Kanal: {channel.mention}.")

    @ticketset.command(name="forum")
    async def ticketset_forum(self, ctx, channel: discord.ForumChannel):
        """Forum-Kanal für den Forum-Modus."""
        await self.config.guild(ctx.guild).forum_channel.set(channel.id)
        await ctx.send(f"Forum-Kanal: {channel.mention}.")

    @ticketset.command(name="logchannel")
    async def ticketset_logchannel(self, ctx, channel: discord.TextChannel):
        """Log-Kanal setzen."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Log-Kanal: {channel.mention}.")

    @ticketset.command(name="maxopen")
    async def ticketset_maxopen(self, ctx, count: int):
        """Maximale offene Tickets pro Nutzer."""
        await self.config.guild(ctx.guild).max_open.set(max(1, count))
        await ctx.send(f"Maximal offene Tickets pro Nutzer: **{max(1, count)}**.")

    @ticketset.command(name="panel")
    async def ticketset_panel(self, ctx, channel: discord.TextChannel, *, title: str = "Support-Ticket"):
        """Schnell ein einfaches Ein-Button-Panel posten (Details im Dashboard)."""
        import uuid
        panel = {
            "id": uuid.uuid4().hex[:8],
            "channel_id": channel.id,
            "message_id": None,
            "title": title,
            "description": t(await self._lang(ctx.guild), "panel_default_description"),
            "mode": "button",
            "button_label": "🎟️ Ticket",
            "placeholder": "Grund auswählen …",
            "reasons": [],
            "modal_questions": [],
            "lang": None,
        }
        panel["message_id"] = await self.post_panel(ctx.guild, panel)
        async with self.config.guild(ctx.guild).panels() as panels:
            panels.append(panel)
        await ctx.send("Panel gepostet." if panel["message_id"] else "Panel gespeichert, Posten fehlgeschlagen (Rechte?).")

    @ticketset.command(name="settings")
    async def ticketset_settings(self, ctx):
        """Aktuelle Einstellungen anzeigen."""
        c = await self.config.guild(ctx.guild).all()
        def names(ids):
            return ", ".join(r.name for r in self._resolve_roles(ctx.guild, ids)) or "—"
        e = discord.Embed(title="Tickets – Einstellungen", color=EMBED_COLOR)
        e.add_field(name="Sprache", value=LANGUAGES.get(c["language"], c["language"]), inline=True)
        e.add_field(name="Typ", value=c["ticket_type"], inline=True)
        e.add_field(name="Max. offen", value=str(c["max_open"]), inline=True)
        e.add_field(name="Support", value=names(c["support_roles"]), inline=False)
        e.add_field(name="Admin", value=names(c["admin_roles"]), inline=False)
        e.add_field(name="View", value=names(c["view_roles"]), inline=False)
        e.add_field(name="Panels", value=str(len(c["panels"])), inline=True)
        e.add_field(name="Offen/Geschlossen", value=f"{sum(1 for r in c['tickets'].values() if r.get('status')=='open')} / {c['stats'].get('closed',0)}", inline=True)
        await ctx.send(embed=e)

    @ticketset.command(name="dashboard")
    async def ticketset_dashboard(self, ctx):
        """Hinweis zum Dashboard."""
        await ctx.send("Alle Einstellungen, Panels, Transcripts und die Statistik findest du im WebCore-Dashboard unter **Tickets**.")
