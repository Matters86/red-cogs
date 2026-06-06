from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dashboard import dashboard_handler
from .embed import build_poll_embed, is_ended_or_closed, result_text, vote_counts
from .strings import DEFAULT_LANGUAGE, LANGUAGES, t
from .views import CID_VOTE, MAX_OPTION_BUTTONS, build_poll_view

log = logging.getLogger("red.red-cogs.poll")

# Obergrenze für Optionen (Buttons). Per Server zwischen 2 und diesem Wert einstellbar.
HARD_OPTION_LIMIT = MAX_OPTION_BUTTONS
# Maximale Längen, damit Embed-/Discord-Limits sicher eingehalten werden.
MAX_QUESTION_LEN = 256
MAX_OPTION_LEN = 100

_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str | None) -> int | None:
    """Wandelt z. B. '30m', '2h', '1d12h' in Sekunden um. Ungültig -> None."""
    if not text:
        return None
    matches = _DURATION_RE.findall(text.strip().lower())
    if not matches:
        return None
    total = sum(int(num) * _DURATION_UNITS[unit] for num, unit in matches)
    return total if total > 0 else None


class PollFlags(commands.FlagConverter, case_insensitive=True):
    """Flags für ``[p]poll create`` (werden als Slash-Felder dargestellt)."""

    frage: str = commands.flag(name="frage", description="Die Umfragefrage.")
    optionen: str = commands.flag(
        name="optionen", description="Antwortoptionen, getrennt mit | (z. B. A | B | C)."
    )
    dauer: Optional[str] = commands.flag(
        name="dauer", default=None, description="Optionale Laufzeit, z. B. 30m, 2h, 1d."
    )
    mehrfach: Optional[bool] = commands.flag(
        name="mehrfach", default=None, description="Mehrfachauswahl erlauben? (Standard: Server-Einstellung)"
    )
    anonym: Optional[bool] = commands.flag(
        name="anonym", default=None, description="Anonym abstimmen? (Standard: Server-Einstellung)"
    )


class Poll(commands.Cog):
    """Mehrsprachige Umfragen mit Abstimmung per Button, Live-Ergebnis und Dashboard."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=529184637025, force_registration=True)
        self.config.register_guild(
            language="de",
            allow_create="manager",     # "everyone" | "manager"
            manager_roles=[],
            default_multiple=False,
            default_anonymous=False,
            max_options=10,
            messages={},                # Text-Overrides (OVERRIDABLE_KEYS)
            polls={},                   # poll_id -> Umfrage-Datensatz
            counter=0,
        )

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung (1:1-Muster aus example/raidhelper)
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)
        self._poll_tick.start()

    async def cog_unload(self):
        self._poll_tick.cancel()
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="poll",
            name="Umfragen",
            icon="bi-bar-chart-line",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return await dashboard_handler(self, request)

    # ----------------------------------------------------------------- #
    #  Helfer
    # ----------------------------------------------------------------- #
    async def _lang(self, guild) -> str:
        return await self.config.guild(guild).language()

    async def _overrides(self, guild) -> dict:
        return await self.config.guild(guild).messages()

    @staticmethod
    def _has_any_role(member: discord.Member, role_ids) -> bool:
        ids = {int(r) for r in (role_ids or [])}
        return any(r.id in ids for r in getattr(member, "roles", []))

    async def _is_manager(self, member: discord.Member) -> bool:
        if await self.bot.is_owner(member):
            return True
        perms = getattr(member, "guild_permissions", None)
        if perms and perms.manage_guild:
            return True
        roles = await self.config.guild(member.guild).manager_roles()
        return self._has_any_role(member, roles)

    async def _can_create(self, member: discord.Member) -> bool:
        mode = await self.config.guild(member.guild).allow_create()
        if mode == "everyone":
            return True
        return await self._is_manager(member)

    async def _can_manage_poll(self, member: discord.Member, poll: dict) -> bool:
        if poll.get("author_id") == member.id:
            return True
        return await self._is_manager(member)

    async def _next_id(self, guild) -> str:
        n = await self.config.guild(guild).counter()
        n += 1
        await self.config.guild(guild).counter.set(n)
        return f"p-{n:04d}"

    # ----------------------------------------------------------------- #
    #  Umfrage posten / aktualisieren / anlegen
    # ----------------------------------------------------------------- #
    async def post_poll(self, guild, poll: dict) -> int | None:
        channel = guild.get_channel(poll.get("channel_id")) if poll.get("channel_id") else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None
        lang = await self._lang(guild)
        overrides = await self._overrides(guild)
        try:
            msg = await channel.send(
                embed=build_poll_embed(poll, lang, overrides=overrides),
                view=build_poll_view(poll),
            )
            return msg.id
        except discord.HTTPException:
            log.exception("Umfrage konnte nicht gepostet werden (Guild %s)", guild.id)
            return None

    async def refresh_poll_message(self, guild, poll: dict):
        if not poll.get("channel_id") or not poll.get("message_id"):
            return
        channel = guild.get_channel(poll["channel_id"])
        if channel is None:
            return
        lang = await self._lang(guild)
        overrides = await self._overrides(guild)
        try:
            msg = await channel.fetch_message(poll["message_id"])
            await msg.edit(
                embed=build_poll_embed(poll, lang, overrides=overrides),
                view=build_poll_view(poll),
            )
        except discord.HTTPException:
            log.debug("Umfrage-Nachricht nicht aktualisierbar (Umfrage %s)", poll.get("id"))

    async def create_poll(self, guild, *, question, options, channel_id, author_id,
                          end_ts=None, multiple=False, anonymous=False) -> dict:
        pid = await self._next_id(guild)
        poll = {
            "id": pid,
            "question": question[:MAX_QUESTION_LEN],
            "options": [o[:MAX_OPTION_LEN] for o in options][:HARD_OPTION_LIMIT],
            "channel_id": channel_id,
            "message_id": None,
            "author_id": author_id,
            "created_ts": int(datetime.now(tz=timezone.utc).timestamp()),
            "end_ts": int(end_ts) if end_ts else None,
            "multiple": bool(multiple),
            "anonymous": bool(anonymous),
            "closed": False,
            "ended": False,
            "announced": False,
            "votes": {},
        }
        msg_id = await self.post_poll(guild, poll)
        poll["message_id"] = msg_id
        async with self.config.guild(guild).polls() as polls:
            polls[pid] = poll
        return poll

    # ----------------------------------------------------------------- #
    #  Interaktionen (Abstimmen) – persistent über custom_id
    # ----------------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        data = interaction.data or {}
        cid = data.get("custom_id", "")
        if not cid.startswith("poll:") or interaction.guild is None:
            return
        try:
            if cid.startswith(CID_VOTE):
                _, _, poll_id, idx = cid.split(":", 3)
                await self._apply_vote(interaction, poll_id, int(idx))
        except (ValueError, discord.HTTPException):
            log.exception("Fehler beim Verarbeiten einer Umfrage-Interaktion")

    async def _get_poll(self, guild, poll_id):
        polls = await self.config.guild(guild).polls()
        return polls.get(poll_id)

    async def _apply_vote(self, interaction: discord.Interaction, poll_id: str, idx: int):
        guild = interaction.guild
        lang = await self._lang(guild)
        member = interaction.user
        uid = str(member.id)

        async with self.config.guild(guild).polls() as polls:
            poll = polls.get(poll_id)
            if poll is None:
                return await interaction.response.send_message(t(lang, "unknown_poll"), ephemeral=True)
            if poll.get("closed") or poll.get("ended"):
                key = "vote_ended" if poll.get("ended") else "vote_closed"
                return await interaction.response.send_message(t(lang, key), ephemeral=True)
            options = poll.get("options") or []
            if idx < 0 or idx >= len(options):
                return await interaction.response.send_message(t(lang, "unknown_option"), ephemeral=True)

            entry = poll["votes"].get(uid) or {"name": member.display_name, "choices": []}
            entry["name"] = member.display_name
            choices = list(entry.get("choices") or [])

            if poll.get("multiple"):
                if idx in choices:
                    choices.remove(idx)
                    action = "removed"
                else:
                    choices.append(idx)
                    action = "added"
            else:
                if choices == [idx]:
                    choices = []
                    action = "removed"
                else:
                    action = "changed" if choices else "added"
                    choices = [idx]

            if choices:
                entry["choices"] = sorted(choices)
                poll["votes"][uid] = entry
            else:
                poll["votes"].pop(uid, None)
            polls[poll_id] = poll
            snapshot = dict(poll)

        await self.refresh_poll_message(guild, snapshot)
        key = {"added": "vote_added", "removed": "vote_removed", "changed": "vote_changed"}[action]
        await interaction.response.send_message(
            t(lang, key, option=options[idx]), ephemeral=True
        )

    # ----------------------------------------------------------------- #
    #  Hintergrund: Auto-Ende + Ergebnis-Ansage
    # ----------------------------------------------------------------- #
    @tasks.loop(seconds=30)
    async def _poll_tick(self):
        now = int(datetime.now(tz=timezone.utc).timestamp())
        for guild in list(self.bot.guilds):
            try:
                conf = await self.config.guild(guild).all()
            except Exception:  # noqa: BLE001
                continue
            polls = conf.get("polls") or {}
            if not polls:
                continue
            lang = conf.get("language", DEFAULT_LANGUAGE)
            changed = False
            for pid, poll in list(polls.items()):
                end_ts = poll.get("end_ts")
                if poll.get("closed") or poll.get("ended") or not end_ts:
                    continue
                if now >= end_ts:
                    poll["ended"] = True
                    poll["closed"] = True
                    await self.refresh_poll_message(guild, poll)
                    if not poll.get("announced"):
                        await self._announce_result(guild, poll, lang)
                        poll["announced"] = True
                    changed = True
            if changed:
                async with self.config.guild(guild).polls() as stored:
                    for pid, poll in polls.items():
                        if pid in stored:
                            stored[pid] = poll

    @_poll_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_red_ready()

    async def _announce_result(self, guild, poll, lang):
        channel = guild.get_channel(poll.get("channel_id"))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        text = t(lang, "ended_announcement", question=poll.get("question", ""),
                 result=result_text(poll, lang))
        reference = None
        if poll.get("message_id"):
            reference = discord.MessageReference(
                message_id=poll["message_id"], channel_id=channel.id, guild_id=guild.id,
                fail_if_not_exists=False,
            )
        try:
            await channel.send(text, reference=reference)
        except discord.HTTPException:
            pass

    # ----------------------------------------------------------------- #
    #  Befehle: Umfragen
    # ----------------------------------------------------------------- #
    @commands.guild_only()
    @commands.hybrid_group(name="poll")
    async def poll(self, ctx: commands.Context):
        """Umfragen erstellen und verwalten."""

    @poll.command(name="create")
    async def poll_create(self, ctx: commands.Context, *, flags: PollFlags):
        """Umfrage mit allen Optionen anlegen.

        Beispiel (Text): [p]poll create frage: Beste Pizza? optionen: Margherita | Salami | Hawaii dauer: 2h
        """
        await self._do_create(
            ctx, flags.frage, flags.optionen,
            duration=flags.dauer, multiple=flags.mehrfach, anonymous=flags.anonym,
        )

    @poll.command(name="quick")
    async def poll_quick(self, ctx: commands.Context, *, text: str):
        """Schnelle Umfrage mit Server-Standards.

        Frage und Optionen mit | trennen, z. B.: [p]poll quick Beste Pizza? | Margherita | Salami | Hawaii
        """
        parts = [p.strip() for p in text.split("|")]
        question = parts[0] if parts else ""
        options = parts[1:]
        await self._do_create(ctx, question, "|".join(options),
                               duration=None, multiple=None, anonymous=None)

    async def _do_create(self, ctx, question, options_raw, *, duration, multiple, anonymous):
        guild = ctx.guild
        lang = await self._lang(guild)
        if not await self._can_create(ctx.author):
            return await ctx.send(t(lang, "no_permission_create"))

        question = (question or "").strip()
        options = [o.strip() for o in (options_raw or "").split("|") if o.strip()]
        if not question or len(options) < 2:
            return await ctx.send(t(lang, "create_few_options"))
        max_opts = await self.config.guild(guild).max_options()
        if len(options) > max_opts:
            return await ctx.send(t(lang, "create_too_many", max=max_opts))

        channel = ctx.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await ctx.send(t(lang, "create_bad_channel"))

        end_ts = None
        if duration:
            secs = parse_duration(duration)
            if secs is None:
                return await ctx.send(t(lang, "create_bad_duration"))
            end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + secs

        gconf = self.config.guild(guild)
        multiple = await gconf.default_multiple() if multiple is None else multiple
        anonymous = await gconf.default_anonymous() if anonymous is None else anonymous

        poll = await self.create_poll(
            guild, question=question, options=options, channel_id=channel.id,
            author_id=ctx.author.id, end_ts=end_ts, multiple=multiple, anonymous=anonymous,
        )
        if poll.get("message_id"):
            link = f"https://discord.com/channels/{guild.id}/{channel.id}/{poll['message_id']}"
        else:
            link = f"#{getattr(channel, 'name', '')}"
        await ctx.send(t(lang, "created", link=link))

    @poll.command(name="list")
    async def poll_list(self, ctx: commands.Context):
        """Alle Umfragen dieses Servers auflisten."""
        guild = ctx.guild
        lang = await self._lang(guild)
        polls = await self.config.guild(guild).polls()
        if not polls:
            return await ctx.send(t(lang, "no_polls"))
        rows = [t(lang, "list_header")]
        for p in sorted(polls.values(), key=lambda x: x.get("created_ts", 0), reverse=True):
            _, total, _ = vote_counts(p)
            status = self._status_word(lang, p)
            q = (p.get("question") or "")[:60]
            rows.append(t(lang, "list_row", id=p["id"], question=q, votes=total, status=status))
        await ctx.send("\n".join(rows[:30]))

    @staticmethod
    def _status_word(lang, poll):
        if poll.get("ended"):
            return t(lang, "status_ended")
        if poll.get("closed"):
            return t(lang, "status_closed")
        return t(lang, "status_open")

    @poll.command(name="close")
    async def poll_close(self, ctx: commands.Context, poll_id: str):
        """Umfrage schließen (zeigt das Endergebnis)."""
        await self._set_closed(ctx, poll_id, True)

    @poll.command(name="reopen")
    async def poll_reopen(self, ctx: commands.Context, poll_id: str):
        """Geschlossene Umfrage wieder öffnen (entfernt ein Zeitlimit)."""
        await self._set_closed(ctx, poll_id, False)

    async def _set_closed(self, ctx, poll_id, closed):
        guild = ctx.guild
        lang = await self._lang(guild)
        async with self.config.guild(guild).polls() as polls:
            poll = polls.get(poll_id)
            if poll is None:
                return await ctx.send(t(lang, "not_found", id=poll_id))
            if not await self._can_manage_poll(ctx.author, poll):
                return await ctx.send(t(lang, "no_permission_manage"))
            poll["closed"] = closed
            if not closed:
                # Wieder öffnen: Auto-Ende-Marker und Zeitlimit zurücksetzen.
                poll["ended"] = False
                poll["announced"] = False
                poll["end_ts"] = None
            polls[poll_id] = poll
            snapshot = dict(poll)
        await self.refresh_poll_message(guild, snapshot)
        await ctx.send(t(lang, "closed" if closed else "reopened", id=poll_id))

    @poll.command(name="delete")
    async def poll_delete(self, ctx: commands.Context, poll_id: str):
        """Umfrage löschen (inkl. Nachricht)."""
        guild = ctx.guild
        lang = await self._lang(guild)
        async with self.config.guild(guild).polls() as polls:
            poll = polls.get(poll_id)
            if poll is None:
                return await ctx.send(t(lang, "not_found", id=poll_id))
            if not await self._can_manage_poll(ctx.author, poll):
                return await ctx.send(t(lang, "no_permission_manage"))
            poll = polls.pop(poll_id, None)
        if poll and poll.get("channel_id") and poll.get("message_id"):
            channel = guild.get_channel(poll["channel_id"])
            if channel is not None:
                try:
                    msg = await channel.fetch_message(poll["message_id"])
                    await msg.delete()
                except discord.HTTPException:
                    pass
        await ctx.send(t(lang, "deleted", id=poll_id))

    @poll.command(name="results")
    async def poll_results(self, ctx: commands.Context, poll_id: str):
        """Aktuellen Ergebnis-Stand einer Umfrage posten."""
        guild = ctx.guild
        lang = await self._lang(guild)
        poll = await self._get_poll(guild, poll_id)
        if poll is None:
            return await ctx.send(t(lang, "not_found", id=poll_id))
        overrides = await self._overrides(guild)
        await ctx.send(embed=build_poll_embed(poll, lang, overrides=overrides))

    @poll.command(name="export")
    async def poll_export(self, ctx: commands.Context, poll_id: str):
        """Ergebnisse als CSV exportieren (bei anonymen Umfragen nur Zähler)."""
        guild = ctx.guild
        lang = await self._lang(guild)
        poll = await self._get_poll(guild, poll_id)
        if poll is None:
            return await ctx.send(t(lang, "not_found", id=poll_id))
        if not await self._can_manage_poll(ctx.author, poll):
            return await ctx.send(t(lang, "no_permission_manage"))

        buf = io.StringIO()
        w = csv.writer(buf)
        options = poll.get("options") or []
        if poll.get("anonymous"):
            counts, _, _ = vote_counts(poll)
            w.writerow(["option", "stimmen"])
            for i, opt in enumerate(options):
                w.writerow([opt, counts[i] if i < len(counts) else 0])
        else:
            w.writerow(["nutzer", "stimmen_fuer"])
            for entry in poll.get("votes", {}).values():
                chosen = "; ".join(options[i] for i in (entry.get("choices") or []) if 0 <= i < len(options))
                w.writerow([entry.get("name", ""), chosen])
        buf.seek(0)
        file = discord.File(io.BytesIO(buf.getvalue().encode("utf-8")), filename=f"{poll_id}.csv")
        await ctx.send(file=file)

    # ----------------------------------------------------------------- #
    #  Befehle: Einstellungen
    # ----------------------------------------------------------------- #
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.hybrid_group(name="pollset")
    async def pollset(self, ctx: commands.Context):
        """Einstellungen für Umfragen."""

    @pollset.command(name="language")
    async def pollset_language(self, ctx: commands.Context, code: str):
        """Sprache setzen (de, en)."""
        code = code.lower()
        if code not in LANGUAGES:
            return await ctx.send(t(await self._lang(ctx.guild), "lang_unknown",
                                    code=code, langs=", ".join(LANGUAGES)))
        await self.config.guild(ctx.guild).language.set(code)
        await ctx.send(t(code, "lang_set", lang=LANGUAGES[code]))

    @pollset.command(name="allowcreate")
    async def pollset_allowcreate(self, ctx: commands.Context, mode: str):
        """Wer Umfragen erstellen darf: everyone oder manager."""
        lang = await self._lang(ctx.guild)
        mode = mode.lower()
        if mode not in ("everyone", "manager"):
            return await ctx.send(t(lang, "allowcreate_unknown"))
        await self.config.guild(ctx.guild).allow_create.set(mode)
        who = t(lang, "who_everyone" if mode == "everyone" else "who_manager")
        await ctx.send(t(lang, "allowcreate_set", who=who))

    @pollset.command(name="managerrole")
    async def pollset_managerrole(self, ctx: commands.Context, role: discord.Role):
        """Manager-Rolle hinzufügen/entfernen (Umschalter)."""
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).manager_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
                msg = t(lang, "mgr_removed", role=role.name)
            else:
                roles.append(role.id)
                msg = t(lang, "mgr_added", role=role.name)
        await ctx.send(msg)

    @pollset.command(name="multiple")
    async def pollset_multiple(self, ctx: commands.Context, on_off: bool):
        """Standard-Mehrfachauswahl für neue Umfragen an-/ausschalten."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).default_multiple.set(on_off)
        state = t(lang, "state_multiple_on" if on_off else "state_multiple_off")
        await ctx.send(t(lang, "set_multiple", state=state))

    @pollset.command(name="anonymous")
    async def pollset_anonymous(self, ctx: commands.Context, on_off: bool):
        """Standard-Sichtbarkeit neuer Umfragen: an = anonym, aus = öffentlich."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).default_anonymous.set(on_off)
        state = t(lang, "state_anon_on" if on_off else "state_anon_off")
        await ctx.send(t(lang, "set_anonymous", state=state))

    @pollset.command(name="maxoptions")
    async def pollset_maxoptions(self, ctx: commands.Context, anzahl: int):
        """Maximale Optionen pro Umfrage setzen (2–25)."""
        lang = await self._lang(ctx.guild)
        if anzahl < 2 or anzahl > HARD_OPTION_LIMIT:
            return await ctx.send(t(lang, "maxoptions_bad"))
        await self.config.guild(ctx.guild).max_options.set(anzahl)
        await ctx.send(t(lang, "maxoptions_set", n=anzahl))

    @pollset.command(name="settings")
    async def pollset_settings(self, ctx: commands.Context):
        """Aktuelle Einstellungen anzeigen."""
        d = await self.config.guild(ctx.guild).all()
        roles = ", ".join(r.name for r in ctx.guild.roles if r.id in d["manager_roles"]) or "—"
        text = (
            f"Sprache: {d['language']}\n"
            f"Erstellen erlaubt: {d['allow_create']}\n"
            f"Manager-Rollen: {roles}\n"
            f"Standard Mehrfachauswahl: {'an' if d['default_multiple'] else 'aus'}\n"
            f"Standard anonym: {'ja' if d['default_anonymous'] else 'nein'}\n"
            f"Max. Optionen: {d['max_options']}\n"
            f"Umfragen gespeichert: {len(d['polls'])}"
        )
        await ctx.send(text)

    @pollset.command(name="dashboard")
    async def pollset_dashboard(self, ctx: commands.Context):
        """Hinweis zur Dashboard-Seite."""
        lang = await self._lang(ctx.guild)
        webcore = self.bot.get_cog("WebCore")
        if webcore is None:
            return await ctx.send(t(lang, "dashboard_missing"))
        await ctx.send(t(lang, "dashboard_hint"))
