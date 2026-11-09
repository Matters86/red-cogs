"""Discord-Kalender: dauerhafte Board-Buttons und frische, private Team-Aktionen.

Komponenten werden ausschließlich über ``handle_interaction`` ausgewertet.
Stabile IDs funktionieren nach einem Neustart ohne ``bot.add_view``; Formulare
verwenden Discords normale, kurzlebige Modal-Callbacks.
"""
from __future__ import annotations

import io
import time
from datetime import datetime, timedelta, timezone

import discord

from .models import CalendarError, calendar_ics, format_local, get_timezone
from .project_models import label_project

PREFIX = "teamcalendar:"
PAGE_SIZE = 25
CONFIRM_SECONDS = 120
STATUS = {"scheduled": "Geplant", "cancelled": "Abgesagt", "completed": "Erledigt"}
RSVP = {"yes": "Zusagen", "maybe": "Vielleicht", "no": "Absagen"}


def _now(cog):
    return int(cog._now()) if hasattr(cog, "_now") else int(time.time())


def _revision(event):
    return int(event.get("revision", 1))


def _name(guild, uid):
    try:
        member = guild.get_member(int(uid))
    except (ValueError, TypeError):
        member = None
    return discord.utils.escape_markdown(str(getattr(member, "display_name", None) or "Ehemaliges Mitglied")[:32])


def _participant_field(guild, participants, status):
    ids = [uid for uid, value in participants.items() if value == status]
    lines = []
    for uid in ids[:20]:
        candidate = "• " + _name(guild, uid)
        if len("\n".join([*lines, candidate])) > 960:
            break
        lines.append(candidate)
    remaining = len(ids) - len(lines)
    if remaining:
        lines.append(f"… und {remaining} weitere")
    return len(ids), "\n".join(lines) or "Noch niemand"


def event_embed(guild, event, conf):
    """Begrenzte Einzelansicht; keine Rollen-/User-Erwähnungen werden versendet."""
    tz = str(conf.get("timezone") or "Europe/Berlin")
    start, end = event.get("start_ts"), event.get("end_ts")
    embed = discord.Embed(title=str(event.get("title") or "Termin")[:100],
                          description=str(event.get("description") or "Keine Notizen.")[:2000],
                          color=0x3DDC97 if event.get("status", "scheduled") == "scheduled" else 0x95A5A6)
    when = f"{format_local(start, tz)} – {format_local(end, tz)}\nKalender-Zeitzone: {tz}"
    if isinstance(start, int):
        when += f"\nBei dir: <t:{start}:F> · <t:{start}:R>"
    embed.add_field(name="Wann?", value=when[:1024], inline=False)
    embed.add_field(name="Status", value=STATUS.get(event.get("status"), "Geplant"), inline=True)
    owner = event.get("owner_id")
    embed.add_field(name="Verantwortlich", value=_name(guild, owner) if owner else "Nicht zugewiesen", inline=True)
    if event.get("project_id") or event.get("project"):
        embed.add_field(name="Projekt", value=label_project(conf, event)[:200], inline=True)
    if event.get("location"):
        embed.add_field(name="Ort / Treffpunkt", value=str(event["location"])[:200], inline=False)
    participants = event.get("participants") or {}
    for status, label in RSVP.items():
        count, names = _participant_field(guild, participants, status)
        embed.add_field(name=f"{label} ({count})", value=names, inline=True)
    minutes = event.get("reminder_minutes") or []
    if minutes:
        embed.add_field(name="Erinnerungen", value=", ".join(f"{m} Min. vorher" for m in minutes[:3])[:1024], inline=False)
    embed.set_footer(text=f"Termin #{event.get('id', '?')} · Version {_revision(event)} · Änderungen gelten für das ganze Team"[:2048])
    return embed


def build_board_view():
    view = discord.ui.View(timeout=None)
    for label, action, style, emoji in (
        ("Termin erstellen", "new", discord.ButtonStyle.primary, "➕"),
        ("Termine ansehen", "list", discord.ButtonStyle.secondary, "📅"),
        ("Kalender exportieren", "export", discord.ButtonStyle.secondary, "📥"),
        ("Aufgabe erstellen", "pm:newtask", discord.ButtonStyle.primary, "➕"),
        ("Aufgaben ansehen", "pm:tasks", discord.ButtonStyle.secondary, "📋"),
    ):
        view.add_item(discord.ui.Button(label=label, custom_id=PREFIX + action, style=style, emoji=emoji))
    return view


def build_event_view(event, requester_id, *, can_manage=False, now=None):
    """Private Details; sichtbare Buttons ersetzen keine serverseitige Prüfung."""
    view = discord.ui.View(timeout=None)
    eid, revision = str(event["id"]), _revision(event)
    now = int(time.time()) if now is None else int(now)
    active = event.get("status", "scheduled") == "scheduled" and int(event.get("end_ts") or 0) > now
    if active:
        for status, label, style in (
            ("yes", "Zusagen", discord.ButtonStyle.success),
            ("maybe", "Vielleicht", discord.ButtonStyle.secondary),
            ("no", "Absagen", discord.ButtonStyle.secondary),
            ("remove", "Antwort zurücknehmen", discord.ButtonStyle.secondary),
        ):
            view.add_item(discord.ui.Button(label=label, style=style,
                          custom_id=f"{PREFIX}rsvp:{requester_id}:{eid}:{status}", row=0))
    if can_manage:
        actions = [("Bearbeiten", "edit", discord.ButtonStyle.primary)]
        if event.get("status", "scheduled") == "scheduled":
            actions += [("Als erledigt markieren", "complete", discord.ButtonStyle.secondary),
                        ("Termin absagen", "cancel", discord.ButtonStyle.secondary)]
        else:
            actions.append(("Wieder öffnen", "reopen", discord.ButtonStyle.secondary))
        actions.append(("Löschen", "delete", discord.ButtonStyle.danger))
        for label, action, style in actions:
            view.add_item(discord.ui.Button(label=label, style=style,
                          custom_id=f"{PREFIX}{action}:{requester_id}:{eid}:{revision}", row=1))
    view.add_item(discord.ui.Button(label="Zur Terminliste", style=discord.ButtonStyle.secondary,
                  custom_id=f"{PREFIX}list:{requester_id}:0", row=2))
    return view


async def _context(cog, interaction, *, manage=False):
    guild = interaction.guild
    if guild is None:
        raise CalendarError("Bitte den Projektkalender auf dem Discord-Server öffnen.")
    actor = guild.get_member(interaction.user.id)
    if interaction.user.id in (getattr(cog.bot, "owner_ids", None) or set()):
        actor = actor or interaction.user
    conf = await cog.config.guild(guild).all()
    if await cog.bot.cog_disabled_in_guild(cog, guild):
        raise CalendarError("Der Projektkalender ist auf diesem Server deaktiviert.")
    if not (cog.can_manage(actor, conf) if manage else cog.can_view(actor, conf)):
        raise CalendarError("Du gehörst nicht zum berechtigten Kalender-Team.")
    return guild, actor, conf


def _event(conf, eid, revision=None):
    event = (conf.get("events") or {}).get(str(eid))
    if not isinstance(event, dict):
        raise CalendarError("Dieser Termin existiert nicht mehr. Bitte die Terminliste neu öffnen.")
    if revision is not None and str(_revision(event)) != str(revision):
        raise CalendarError("Der Termin wurde inzwischen geändert. Bitte die Terminliste neu öffnen und erneut prüfen.")
    return event


async def _say(interaction, text=None, **kwargs):
    kwargs.update(ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await sender(text, **kwargs)


def _ordered_events(conf, now):
    def sort_key(event):
        start = int(event.get("start_ts") or 0)
        upcoming = event.get("status", "scheduled") == "scheduled" and int(event.get("end_ts") or 0) > now
        return (0 if upcoming else 1, start if upcoming else -start, str(event.get("id", "")))
    return sorted((conf.get("events") or {}).values(), key=sort_key)


async def _list(cog, interaction, conf, actor, page):
    events = _ordered_events(conf, _now(cog))
    pages = max(1, (len(events) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    view = discord.ui.View(timeout=None)
    options = []
    for event in events[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        label = f"{format_local(event.get('start_ts'), conf.get('timezone'))} · {event.get('title') or 'Termin'}"
        desc = f"{STATUS.get(event.get('status'), 'Geplant')} · {event.get('project') or 'Ohne Projekt'} · #{event['id']}"
        options.append(discord.SelectOption(label=label[:100], value=str(event["id"]), description=desc[:100]))
    if options:
        view.add_item(discord.ui.Select(custom_id=f"{PREFIX}select:{actor.id}", options=options,
                      placeholder="Termin auswählen …", min_values=1, max_values=1, row=0))
    if pages > 1:
        view.add_item(discord.ui.Button(label="Zurück", style=discord.ButtonStyle.secondary,
                      custom_id=f"{PREFIX}list:{actor.id}:{page - 1}", disabled=page == 0, row=1))
        view.add_item(discord.ui.Button(label="Weiter", style=discord.ButtonStyle.secondary,
                      custom_id=f"{PREFIX}list:{actor.id}:{page + 1}", disabled=page == pages - 1, row=1))
    if cog.can_manage(actor, conf):
        view.add_item(discord.ui.Button(label="Termin erstellen", style=discord.ButtonStyle.primary, custom_id=PREFIX + "new", row=2))
    text = (f"**Termine · Seite {page + 1}/{pages}**\n{len(events)} Termine · Zeitzone {conf.get('timezone') or 'Europe/Berlin'}. "
            "Bevorstehende Termine stehen zuerst; erledigte und abgesagte danach.") if events else "Noch keine Termine. Das Team kann den ersten Termin erstellen."
    await _say(interaction, text, view=view)


class NewEventModal(discord.ui.Modal):
    """Fünf kurze Felder; Teamrolle und Version werden erst beim Absenden gewertet."""
    def __init__(self, cog, requester_id, conf, event=None, *, guild_id=None):
        super().__init__(title="Termin bearbeiten" if event else "Termin erstellen", timeout=300)
        self.cog, self.requester_id, self.guild_id = cog, int(requester_id), guild_id
        self.event_id = str(event["id"]) if event else None
        self.revision = _revision(event) if event else None
        self.submitted = False
        tz = str(conf.get("timezone") or "Europe/Berlin")
        local = datetime.now(timezone.utc).astimezone(get_timezone(tz)).replace(second=0, microsecond=0) + timedelta(hours=1)
        def date_input(stamp):
            return datetime.fromtimestamp(stamp, get_timezone(tz)).isoformat(timespec="minutes")
        self.title_field = discord.ui.TextInput(label="Titel", default=str((event or {}).get("title") or "")[:100], max_length=100)
        self.start_field = discord.ui.TextInput(label=f"Beginn ({tz})"[:45], max_length=64,
            default=date_input(event["start_ts"]) if event else local.isoformat(timespec="minutes"),
            placeholder="TT.MM.JJJJ HH:MM, z. B. 10.11.2026 18:00")
        self.end_field = discord.ui.TextInput(label=f"Ende ({tz})"[:45], max_length=64,
            default=date_input(event["end_ts"]) if event else (local + timedelta(hours=1)).isoformat(timespec="minutes"),
            placeholder="TT.MM.JJJJ HH:MM")
        self.location_field = discord.ui.TextInput(label="Ort / Treffpunkt (optional)", required=False, max_length=200,
            default=str((event or {}).get("location") or "")[:200])
        self.description_field = discord.ui.TextInput(label="Notizen (optional)", required=False, max_length=2000,
            style=discord.TextStyle.paragraph, default=str((event or {}).get("description") or "")[:2000])
        for field in (self.title_field, self.start_field, self.end_field, self.location_field, self.description_field):
            self.add_item(field)

    async def on_submit(self, interaction):
        try:
            if interaction.user.id != self.requester_id or self.guild_id is not None and getattr(interaction.guild, "id", None) != self.guild_id:
                raise CalendarError("Dieses Formular gehört zu einer anderen Person oder einem anderen Server.")
            if self.submitted:
                raise CalendarError("Dieses Formular wurde bereits abgesendet. Bitte den Termin über den Kalender öffnen.")
            self.submitted = True
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild, actor, conf = await _context(self.cog, interaction, manage=True)
            values = {"title": self.title_field.value, "start": self.start_field.value, "end": self.end_field.value,
                      "location": self.location_field.value, "description": self.description_field.value}
            if self.event_id is None:
                event = await self.cog.create_event(guild, actor, values)
            else:
                _event(conf, self.event_id, self.revision)
                event = await self.cog.update_event(guild, actor, self.event_id, values, revision=self.revision)
            current = await self.cog.config.guild(guild).all()
            await _say(interaction, "Termin gespeichert.", embed=event_embed(guild, event, current),
                       view=build_event_view(event, actor.id, can_manage=self.cog.can_manage(actor, current), now=_now(self.cog)))
        except CalendarError as exc:
            await _say(interaction, str(exc))


async def handle_interaction(cog, interaction):
    """Nur bekannte Kalender-Komponenten; alle Antworten bleiben ephemer."""
    if getattr(interaction, "type", None) != discord.InteractionType.component:
        return
    cid = str((interaction.data or {}).get("custom_id") or "")
    if not cid.startswith(PREFIX):
        return
    if cid.startswith(PREFIX + "pm:"):
        from .task_views import handle_interaction as handle_tasks
        return await handle_tasks(cog, interaction)
    parts = cid[len(PREFIX):].split(":")
    action = parts[0]
    lengths = {"new": (1,), "list": (1, 3), "export": (1,), "select": (2,), "rsvp": (4,),
               "edit": (4,), "cancel": (4,), "delete": (4,), "complete": (4,), "reopen": (4,), "confirm": (6,)}
    if action not in lengths or len(parts) not in lengths[action]:
        return
    try:
        if len(parts) > 1 and (not parts[1].isdigit() or int(parts[1]) != interaction.user.id):
            raise CalendarError("Diese Auswahl gehört zu einer anderen Person. Bitte den Kalender erneut öffnen.")
        manage = action in {"new", "edit", "cancel", "delete", "complete", "reopen", "confirm"}
        guild, actor, conf = await _context(cog, interaction, manage=manage)
        if action == "new":
            return await interaction.response.send_modal(NewEventModal(cog, actor.id, conf, guild_id=guild.id))
        if action == "list":
            if len(parts) == 3 and not parts[2].lstrip("-").isdigit():
                raise CalendarError("Ungültige Kalenderseite. Bitte die Terminliste neu öffnen.")
            return await _list(cog, interaction, conf, actor, int(parts[2]) if len(parts) == 3 else 0)
        if action == "export":
            await interaction.response.defer(ephemeral=True, thinking=True)
            data = calendar_ics(list((conf.get("events") or {}).values()), guild.id, guild.name)
            return await _say(interaction, "Kalenderdatei für deine Kalender-App.",
                              file=discord.File(io.BytesIO(data), filename=f"projektkalender-{guild.id}.ics"))
        if action == "select":
            selected = (interaction.data or {}).get("values") or []
            if len(selected) != 1:
                raise CalendarError("Bitte genau einen Termin auswählen.")
            event = _event(conf, selected[0])
            return await _say(interaction, embed=event_embed(guild, event, conf),
                view=build_event_view(event, actor.id, can_manage=cog.can_manage(actor, conf), now=_now(cog)))
        eid = parts[2]
        if action == "rsvp":
            await interaction.response.defer(ephemeral=True, thinking=True)
            event = await cog.set_rsvp(guild, actor, eid, parts[3])
            conf = await cog.config.guild(guild).all()
            return await _say(interaction, "Deine Antwort wurde gespeichert.", embed=event_embed(guild, event, conf),
                view=build_event_view(event, actor.id, can_manage=cog.can_manage(actor, conf), now=_now(cog)))
        event = _event(conf, eid, parts[3])
        if action == "edit":
            return await interaction.response.send_modal(NewEventModal(cog, actor.id, conf, event, guild_id=guild.id))
        if action in {"cancel", "delete"}:
            verb = "endgültig löschen" if action == "delete" else "absagen"
            view = discord.ui.View(timeout=None)
            deadline = _now(cog) + CONFIRM_SECONDS
            view.add_item(discord.ui.Button(label="Endgültig löschen" if action == "delete" else "Absage bestätigen",
                style=discord.ButtonStyle.danger, custom_id=f"{PREFIX}confirm:{actor.id}:{eid}:{parts[3]}:{action}:{deadline}"))
            view.add_item(discord.ui.Button(label="Abbrechen / Termin ansehen", style=discord.ButtonStyle.secondary,
                custom_id=f"{PREFIX}list:{actor.id}:0"))
            text = f"Termin **{discord.utils.escape_markdown(str(event.get('title') or 'Termin')[:100])}** wirklich {verb}?"
            text += " Zusagen und Termin werden entfernt." if action == "delete" else " Der Termin bleibt als abgesagt im Kalender erhalten."
            return await _say(interaction, text + " Die Bestätigung gilt zwei Minuten.", view=view)
        if action == "confirm":
            if parts[4] not in {"cancel", "delete"} or not parts[5].isdigit() or int(parts[5]) <= _now(cog):
                raise CalendarError("Die Bestätigung ist abgelaufen. Bitte den Termin neu öffnen.")
            action = parts[4]
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await cog.event_action(guild, actor, eid, action, revision=int(parts[3]))
        if result is None:
            return await _say(interaction, "Termin gelöscht.", view=build_board_view())
        current = await cog.config.guild(guild).all()
        await _say(interaction, "Termin aktualisiert.", embed=event_embed(guild, result, current),
            view=build_event_view(result, actor.id, can_manage=cog.can_manage(actor, current), now=_now(cog)))
    except CalendarError as exc:
        await _say(interaction, str(exc))
