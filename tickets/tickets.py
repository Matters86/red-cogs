import logging
import re
from datetime import datetime, timezone

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

from .dashboard import dashboard_handler
from .strings import LANGUAGES, t
from .transcript import build_transcript
from .views import (
    CID_CLAIM,
    CID_CLOSE,
    CID_LOCK,
    CID_OPEN,
    CID_SELECT,
    CID_UNCLAIM,
    CID_UNLOCK,
    ConfirmView,
    TicketModal,
    build_controls_view,
    build_panel_view,
)

log = logging.getLogger("red.red-cogs.tickets")

EMBED_COLOR = 0x3DDC97


class Tickets(commands.Cog):
    """Mehrsprachiges Ticketsystem mit Panels, Transcripts und Dashboard-Verwaltung."""

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
        )
        self.transcripts_dir = cog_data_path(self) / "transcripts"
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (1:1-Muster aus example)
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)

    async def cog_unload(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="tickets",
            name="Tickets",
            icon="bi-life-preserver",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    @staticmethod
    def _channel_name(raw: str) -> str:
        s = (raw or "").lower().strip()
        s = re.sub(r"[^a-z0-9\-_]+", "-", s)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        return s[:90] or "ticket"

    @staticmethod
    def _has_any_role(member: discord.Member, role_ids) -> bool:
        ids = {int(r) for r in (role_ids or [])}
        return any(r.id in ids for r in getattr(member, "roles", []))

    def _is_admin(self, member: discord.Member, conf: dict) -> bool:
        if member.guild_permissions.manage_guild:
            return True
        return self._has_any_role(member, conf.get("admin_roles"))

    def _is_staff(self, member: discord.Member, conf: dict) -> bool:
        return self._is_admin(member, conf) or self._has_any_role(member, conf.get("support_roles"))

    def _resolve_roles(self, guild, ids):
        out = []
        for rid in ids or []:
            role = guild.get_role(int(rid))
            if role is not None:
                out.append(role)
        return out

    def _overwrites(self, guild, member, conf):
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
        for role in self._resolve_roles(guild, conf.get("support_roles")) + self._resolve_roles(guild, conf.get("admin_roles")):
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        for role in self._resolve_roles(guild, conf.get("view_roles")):
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
        return ow

    def _closed_overwrites(self, guild, conf):
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
            ),
        }
        for role in self._resolve_roles(guild, conf.get("support_roles")) + self._resolve_roles(guild, conf.get("admin_roles")):
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

    # ----------------------------------------------------------------- #
    #  Panels posten / entfernen (vom Dashboard aufgerufen)
    # ----------------------------------------------------------------- #
    async def post_panel(self, guild, panel) -> int | None:
        channel = guild.get_channel(panel.get("channel_id")) if panel.get("channel_id") else None
        if not isinstance(channel, discord.TextChannel):
            return None
        lang = panel.get("lang") or await self._lang(guild)
        title = panel.get("title") or t(lang, "panel_default_title")
        desc = panel.get("description") or t(lang, "panel_default_description")
        embed = discord.Embed(title=title, description=desc, color=EMBED_COLOR)
        try:
            msg = await channel.send(embed=embed, view=build_panel_view(panel))
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

        open_count = sum(
            1 for r in conf["tickets"].values()
            if r.get("owner_id") == member.id and r.get("status") == "open"
        )
        if open_count >= int(conf["max_open"]):
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

        target = await self._create_ticket(guild, member, conf, panel, reason, answers)
        if target is None:
            await interaction.followup.send(
                "Ticket konnte nicht erstellt werden – Konfiguration prüfen (Kategorie/Forum/Basis-Kanal).",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            t(lang, "created_ephemeral", channel=target.mention), ephemeral=True
        )

    async def _create_ticket(self, guild, member, conf, panel, reason, answers):
        lang = panel.get("lang") or conf["language"]
        reason_label = (reason or {}).get("label") if reason else None

        async with self.config.guild(guild).counter.get_lock():
            num = await self.config.guild(guild).counter() + 1
            await self.config.guild(guild).counter.set(num)

        overrides = conf.get("messages") or {}
        title = overrides.get("opened_title") or t(lang, "opened_title", num=num)
        body = overrides.get("opened_body")
        body = body.format(user=member.mention) if body else t(lang, "opened_body", user=member.mention)
        embed = discord.Embed(title=title, description=body, color=EMBED_COLOR)
        if reason_label:
            embed.add_field(name="​", value=t(lang, "opened_reason", reason=reason_label), inline=False)
        for q, a in (answers or {}).items():
            embed.add_field(name=q[:256], value=(a or "—")[:1024], inline=False)

        ping_roles = self._resolve_roles(guild, conf.get("ping_roles"))
        support_roles = self._resolve_roles(guild, conf.get("support_roles"))
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
                    name=(self._channel_name(conf["name_template"].format(num=num, user=member.name)).replace("-", " "))[:100] or f"ticket {num}",
                    content=mentions or "\u200b",
                    embed=embed,
                    view=controls,
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
                    name=(conf["name_template"].format(num=num, user=member.name))[:100] or f"ticket-{num}",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    reason=f"Ticket #{num} ({member})",
                )
                try:
                    await target.add_user(member)
                except discord.HTTPException:
                    pass
                mentions = " ".join(r.mention for r in (ping_roles + support_roles)) or None
                opening_msg = await target.send(content=mentions, embed=embed, view=controls)

            else:  # category
                name = self._channel_name(conf["name_template"].format(num=num, user=member.name))
                category = guild.get_channel(conf.get("category_open")) if conf.get("category_open") else None
                target = await guild.create_text_channel(
                    name,
                    category=category if isinstance(category, discord.CategoryChannel) else None,
                    overwrites=self._overwrites(guild, member, conf),
                    reason=f"Ticket #{num} ({member})",
                )
                opening_msg = await target.send(content=ping_content, embed=embed, view=controls)
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
            "status": "open",
            "claimed_by": None,
            "locked": False,
            "type": ttype,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message_id": opening_msg.id if opening_msg else None,
            "answers": answers or {},
        }
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
        if not record.get("message_id"):
            return
        try:
            msg = await channel.fetch_message(record["message_id"])
            await msg.edit(view=build_controls_view(
                lang, claimed=bool(record.get("claimed_by")), locked=bool(record.get("locked"))
            ))
        except discord.HTTPException:
            pass

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
        if not (self._is_staff(member, conf) or (is_owner and conf["user_can_close"])):
            await interaction.response.send_message(t(lang, "no_permission"), ephemeral=True)
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

    async def _control_claim(self, interaction, claim: bool):
        guild = interaction.guild
        channel = interaction.channel
        conf = await self.config.guild(guild).all()
        lang = conf["language"]
        record = conf["tickets"].get(str(channel.id))
        if not record:
            await interaction.response.send_message(t(lang, "not_a_ticket"), ephemeral=True)
            return
        member = interaction.user
        if not self._is_staff(member, conf):
            await interaction.response.send_message(t(lang, "no_permission"), ephemeral=True)
            return

        await interaction.response.defer()
        if claim:
            if record.get("claimed_by") and record["claimed_by"] != member.id:
                other = guild.get_member(record["claimed_by"])
                await channel.send(t(lang, "already_claimed", user=other.mention if other else "?"))
                return
            record["claimed_by"] = member.id
            async with self.config.guild(guild).stats() as stats:
                claims = stats.setdefault("claims", {})
                claims[str(member.id)] = claims.get(str(member.id), 0) + 1
            await channel.send(t(lang, "claimed_by", user=member.mention))
            await self._log(guild, conf, t(lang, "log_claimed", num=record["num"], user=str(member)))
        else:
            record["claimed_by"] = None
            await channel.send(t(lang, "unclaimed_by", user=member.mention))

        async with self.config.guild(guild).tickets() as tickets:
            if str(channel.id) in tickets:
                tickets[str(channel.id)]["claimed_by"] = record["claimed_by"]
        await self._refresh_controls(guild, channel, record, lang)

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
        if not self._is_staff(member, conf):
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

    async def _close_ticket(self, guild, channel, record, closer, conf):
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
            "closed_by": str(closer),
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
              duration=self._fmt_dur(duration)),
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
            await channel.send(t(lang, "closed_by", user=closer.mention))
        except discord.HTTPException:
            pass
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(archived=True, locked=True)
            else:
                closed_cat = guild.get_channel(conf.get("category_close")) if conf.get("category_close") else None
                await channel.edit(
                    category=closed_cat if isinstance(closed_cat, discord.CategoryChannel) else channel.category,
                    overwrites=self._closed_overwrites(guild, conf),
                    reason=f"Ticket #{record['num']} geschlossen",
                )
        except discord.HTTPException:
            pass

        async with self.config.guild(guild).tickets() as tickets:
            if str(channel.id) in tickets:
                tickets[str(channel.id)]["status"] = "closed"
                tickets[str(channel.id)]["closed_at"] = record["closed_at"]

    async def _reopen_ticket(self, guild, channel, record, conf):
        lang = conf["language"]
        owner = guild.get_member(record["owner_id"])
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(archived=False, locked=False)
            else:
                open_cat = guild.get_channel(conf.get("category_open")) if conf.get("category_open") else None
                await channel.edit(
                    category=open_cat if isinstance(open_cat, discord.CategoryChannel) else channel.category,
                    overwrites=self._overwrites(guild, owner or guild.me, conf),
                )
        except discord.HTTPException:
            pass
        async with self.config.guild(guild).tickets() as tickets:
            if str(channel.id) in tickets:
                tickets[str(channel.id)]["status"] = "open"

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
        if not (self._is_staff(ctx.author, conf) or (is_owner and conf["user_can_close"])):
            return await ctx.send(t(lang, "no_permission"))
        await ctx.send("🔒")
        await self._close_ticket(ctx.guild, ctx.channel, record, ctx.author, conf)

    @ticket.command(name="open")
    async def ticket_open(self, ctx):
        """Öffnet ein geschlossenes (archiviertes) Ticket wieder."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf):
            return await ctx.send(t(lang, "no_permission"))
        await self._reopen_ticket(ctx.guild, ctx.channel, record, conf)
        await ctx.send(t(lang, "reopened_by", user=ctx.author.mention))

    @ticket.command(name="claim")
    async def ticket_claim(self, ctx):
        """Übernimmt das aktuelle Ticket."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(ctx.guild).tickets() as tickets:
            rec = tickets.get(str(ctx.channel.id))
            if rec:
                rec["claimed_by"] = ctx.author.id
        async with self.config.guild(ctx.guild).stats() as stats:
            claims = stats.setdefault("claims", {})
            claims[str(ctx.author.id)] = claims.get(str(ctx.author.id), 0) + 1
        record["claimed_by"] = ctx.author.id
        await self._refresh_controls(ctx.guild, ctx.channel, record, lang)
        await ctx.send(t(lang, "claimed_by", user=ctx.author.mention))

    @ticket.command(name="unclaim")
    async def ticket_unclaim(self, ctx):
        """Gibt das aktuelle Ticket wieder frei."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(ctx.guild).tickets() as tickets:
            rec = tickets.get(str(ctx.channel.id))
            if rec:
                rec["claimed_by"] = None
        record["claimed_by"] = None
        await self._refresh_controls(ctx.guild, ctx.channel, record, lang)
        await ctx.send(t(lang, "unclaimed_by", user=ctx.author.mention))

    @ticket.command(name="add")
    async def ticket_add(self, ctx, member: discord.Member):
        """Fügt ein Mitglied zum Ticket hinzu."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf):
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
        await ctx.send(t(lang, "member_added", user=member.mention))

    @ticket.command(name="remove")
    async def ticket_remove(self, ctx, member: discord.Member):
        """Entfernt ein Mitglied aus dem Ticket."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf):
            return await ctx.send(t(lang, "no_permission"))
        try:
            if isinstance(ctx.channel, discord.Thread):
                await ctx.channel.remove_user(member)
            else:
                await ctx.channel.set_permissions(member, overwrite=None)
        except discord.HTTPException:
            pass
        await ctx.send(t(lang, "member_removed", user=member.mention))

    @ticket.command(name="rename")
    async def ticket_rename(self, ctx, *, name: str):
        """Benennt das Ticket um."""
        conf, record = await self._ctx_record(ctx)
        lang = conf["language"]
        if not record:
            return await ctx.send(t(lang, "not_a_ticket"))
        if not self._is_staff(ctx.author, conf):
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
        if not self._is_staff(ctx.author, conf):
            return await ctx.send(t(lang, "no_permission"))
        async with self.config.guild(ctx.guild).tickets() as tickets:
            rec = tickets.get(str(ctx.channel.id))
            if rec:
                rec["owner_id"] = member.id
        if not isinstance(ctx.channel, discord.Thread):
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
        if not self._is_staff(ctx.author, conf):
            return await ctx.send(t(conf["language"], "no_permission"))
        status = status.lower()
        lines = []
        for cid, rec in conf["tickets"].items():
            if status in ("open", "closed") and rec.get("status") != status:
                continue
            owner = ctx.guild.get_member(rec.get("owner_id"))
            lines.append(f"#{rec.get('num')} · <#{cid}> · {owner.mention if owner else rec.get('owner_id')} · {rec.get('status')}")
        text = "\n".join(lines) or "—"
        await ctx.send(embed=discord.Embed(title="Tickets", description=text[:4000], color=EMBED_COLOR))

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
