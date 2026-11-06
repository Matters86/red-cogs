"""Gemeinsamer Einrichtungsassistent: geprüfter Entwurf, explizite Übernahme.

Die Adapter schreiben ausschließlich deklarierte Config-Schlüssel. Kein Adapter
sendet Discord-Nachrichten, startet Jobs oder veröffentlicht Panels. Entwürfe
liegen kurzlebig im Bot-Prozess und sind an Nutzer, Sitzung und Server gebunden.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from aiohttp import web

from . import access as acl

log = logging.getLogger("red.red-cogs.webcore.setup")
TTL = 30 * 60
MAX_DRAFTS = 200
PATH = "/setup"


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"
    default: object = ""
    choices: tuple = ()
    help: str = ""
    advanced: bool = False
    grant: bool = False
    maximum: int = 2000


@dataclass(frozen=True)
class Adapter:
    slug: str
    cog: str
    name: str
    fields: tuple[Field, ...]
    summary: str
    container: str = ""


ADAPTERS = (
    Adapter("tickets", "Tickets", "Tickets", (
        Field("support_roles", "Support-Team", "roles", (), help="Diese Rollen können Tickets betreuen; es werden keine Rollen vergeben."),
        Field("ticket_type", "Ticket-Art", "choice", "category", (("category", "Eigener Kanal"), ("thread", "Privater Thread"), ("forum", "Forum-Beitrag"))),
        Field("category_open", "Kategorie für offene Tickets", "category", None),
        Field("thread_base", "Textkanal für private Ticket-Threads", "channel", None),
        Field("forum_channel", "Forum für Tickets", "forum", None),
        Field("log_channel", "Protokollkanal", "channel", None, advanced=True),
        Field("owner_role", "Automatische Rolle für Ticket-Ersteller", "role", None, advanced=True, grant=True),
        Field("max_open", "Offene Tickets je Mitglied", "number", 1, maximum=25, advanced=True),
    ), "Grundlagen für neue Tickets. Ein Ticket-Panel veröffentlichst du anschließend ausdrücklich in den Ticket-Einstellungen."),
    Adapter("welcome", "Welcome", "Begrüßung", (
        Field("welcome_enabled", "Begrüßung bei zukünftigen Beitritten aktiv", "bool", False),
        Field("welcome_channel", "Begrüßungskanal", "channel", None),
        Field("welcome_text", "Begrüßungstext", "textarea", "", help="Platzhalter: {user}, {name}, {server}, {count}, {created}. Leer verwendet den Standardtext."),
        Field("welcome_mode", "Darstellung", "choice", "text", (("text", "Text"), ("embed", "Embed")), advanced=True),
    ), "Gilt nach Übernahme für zukünftige Beitritte. Hier wird keine Testnachricht versendet."),
    Adapter("autorole", "Autorole", "Automatische Rollen", (
        Field("enabled", "Rollenvergabe bei zukünftigen Beitritten aktiv", "bool", True),
        Field("join_roles", "Rollen beim Beitritt", "roles", (), grant=True),
        Field("screening", "Mitgliedschaftsprüfung abwarten", "choice", "auto", (("auto", "Automatisch"), ("on", "Immer"), ("off", "Nicht abwarten"))),
        Field("delay", "Verzögerung in Sekunden", "number", 0, maximum=3600, advanced=True),
    ), "Gilt für zukünftige Beitritte. Bereits vorhandene Mitglieder erhalten durch die Übernahme keine Rollen."),
    Adapter("poll", "Poll", "Umfragen", (
        Field("allow_create", "Wer darf Umfragen erstellen?", "choice", "manager", (("manager", "Nur Umfrage-Verwalter"), ("everyone", "Alle Mitglieder"))),
        Field("manager_roles", "Umfrage-Verwalter", "roles", ()),
        Field("default_multiple", "Standard: Mehrfachauswahl", "bool", False, advanced=True),
        Field("default_anonymous", "Standard: Anonyme Abstimmung", "bool", False, advanced=True),
        Field("max_options", "Maximale Antwortmöglichkeiten", "number", 10, maximum=25, advanced=True),
    ), "Ändert die Vorgaben für neue Umfragen. Bestehende Umfragen behalten ihre Regeln."),
    Adapter("raidhelper", "RaidHelper", "Raid-Planung", (
        Field("signup_channel", "Kanal für neue Raids", "channel", None),
        Field("manager_roles", "Raid-Verwalter", "roles", ()),
        Field("default_game", "Standard-Spiel", "choice", "wow_retail", (("wow_retail", "WoW Retail"), ("wow_classic", "WoW Classic"), ("wow_wotlk", "WoW WotLK"))),
        Field("timezone", "Zeitzone", "timezone", "Europe/Berlin", advanced=True),
        Field("reminders", "Erinnerungen aktiv", "bool", True, advanced=True),
    ), "Ändert die Vorgaben. Es wird kein Raid erstellt und keine Erinnerung versendet."),
    Adapter("organigram", "Organigram", "Organigramm", (
        Field("name", "Name des neuen Entwurfs", "text", "Team", maximum=80),
        Field("roles", "Rollen im Organigramm", "roles", ()),
        Field("structure", "Struktur", "choice", "chain", (("chain", "Nach Rang untereinander"), ("flat", "Nebeneinander"))),
        Field("mode", "Darstellung", "choice", "embed", (("embed", "Embed"), ("image", "Bild")), advanced=True),
    ), "Erstellt einen neuen, unveröffentlichten Organigramm-Entwurf. Vorhandene Organigramme bleiben erhalten.", "charts"),
    Adapter("sticky", "Sticky", "Angeheftete Nachricht", (
        Field("channel", "Kanal für die neue Vorlage", "channel", None),
        Field("text", "Nachrichtentext", "textarea", ""),
    ), "Speichert eine deaktivierte Textvorlage. Aktiviere sie anschließend ausdrücklich in den Sticky-Einstellungen.", "stickies"),
    Adapter("giveaways", "Giveaways", "Gewinnspiele", (
        Field("manager_roles", "Gewinnspiel-Verwalter", "roles", ()),
        Field("timezone", "Zeitzone", "timezone", "Europe/Berlin"),
        Field("keep_days", "Abgeschlossene Gewinnspiele aufbewahren (Tage)", "number", 90, maximum=3650, advanced=True),
    ), "Ändert nur Grundeinstellungen. Es wird kein Gewinnspiel gestartet."),
    Adapter("scheduler", "Scheduler", "Geplante Nachrichten", (
        Field("timezone", "Zeitzone", "timezone", "Europe/Berlin"),
    ), "Ändert die Standard-Zeitzone. Vorhandene Termine bleiben erhalten; es wird keine Nachricht geplant."),
)
BY_SLUG = {a.slug: a for a in ADAPTERS}


class SetupError(ValueError):
    pass


class ScopedRequest:
    """Gleiche Sitzung, aber Rechte explizit für das jeweilige Cog prüfen."""
    def __init__(self, request, slug):
        self.request = request
        self.match_info = {**request.match_info, "slug": slug}

    def __getattr__(self, name):
        return getattr(self.request, name)

    def __getitem__(self, key):
        return self.request[key]

    def __setitem__(self, key, value):
        self.request[key] = value

    def __contains__(self, key):
        return key in self.request

    def get(self, key, default=None):
        return self.request.get(key, default)

    def pop(self, key, default=None):
        return self.request.pop(key, default)


def _loaded(wc, adapter):
    page = wc.pages.get(adapter.slug)
    cog = wc.bot.get_cog(adapter.cog)
    return cog if cog is not None and page is not None and page.owner is cog and hasattr(cog, "config") else None


async def setup_guilds(wc, request):
    """Für den globalen Server-Wechsler: Vereinigung tatsächlich bearbeitbarer Module."""
    guilds = {}
    for adapter in ADAPTERS:
        if _loaded(wc, adapter):
            for guild in await wc.visible_guilds(ScopedRequest(request, adapter.slug), min_level=acl.EDIT):
                guilds[guild.id] = guild
    return sorted(guilds.values(), key=lambda g: (g.name.casefold(), g.id))


async def _authorized(wc, request, guild, adapter, *, fresh=False):
    if fresh:
        invalidate = getattr(wc, "_invalidate_access_cache", None)
        if invalidate:
            invalidate(request)
    scoped = ScopedRequest(request, adapter.slug)
    return (_loaded(wc, adapter) is not None
            and guild.id in {g.id for g in await wc.visible_guilds(scoped, min_level=acl.EDIT)}
            and await wc.can_edit(scoped, guild))


def discard_user(wc, user_id):
    """Kurzlebige Entwürfe bei Reds Datenschutzanfrage vollständig entfernen."""
    for key in list(getattr(wc, "_setup_drafts", {})):
        if key[0] == int(user_id):
            del wc._setup_drafts[key]


async def _compatible(wc, guild, adapter):
    cog = _loaded(wc, adapter)
    if cog is None:
        return False
    conf = await cog.config.guild(guild).all()
    expected = {adapter.container} if adapter.container else {f.key for f in adapter.fields}
    return expected <= conf.keys()


def _url(guild=None, **query):
    if guild is not None:
        query["guild"] = guild.id
    return PATH + ("?" + urlencode(query) if query else "")


def _prune(wc):
    if not hasattr(wc, "_setup_drafts"):
        wc._setup_drafts = {}
        wc._setup_locks = {}
        wc._setup_flow_locks = {}
    now = time.monotonic()
    for key, draft in list(wc._setup_drafts.items()):
        if draft["expires"] <= now:
            del wc._setup_drafts[key]


def _new_draft(wc, key, selected):
    if key not in wc._setup_drafts and len(wc._setup_drafts) >= MAX_DRAFTS:
        oldest = min(wc._setup_drafts, key=lambda k: wc._setup_drafts[k]["expires"])
        del wc._setup_drafts[oldest]
    draft = {"id": secrets.token_urlsafe(20), "expires": time.monotonic() + TTL,
             "selected": selected, "values": {}, "review": None, "applied": False}
    wc._setup_drafts[key] = draft
    return draft


def _getlist(form, name):
    if hasattr(form, "getall"):
        return form.getall(name, [])
    value = form.get(name, [])
    return value if isinstance(value, list) else [value]


def _parse(field, form, name):
    raw = form.get(name, "")
    if field.kind == "bool":
        return name in form
    if field.kind == "roles":
        values = _getlist(form, name)
        if len(values) > 250 or any(not str(v).isdigit() for v in values):
            raise SetupError(f"{field.label}: Bitte gültige Server-Rollen auswählen.")
        return sorted(set(int(v) for v in values))
    if field.kind in {"role", "channel", "category", "forum"}:
        if not raw:
            return None
        if not str(raw).isdigit():
            raise SetupError(f"{field.label}: Bitte eine gültige Auswahl treffen.")
        return int(raw)
    if field.kind == "number":
        try:
            value = int(raw)
        except (ValueError, TypeError):
            raise SetupError(f"{field.label}: Bitte eine ganze Zahl eingeben.") from None
        minimum = 2 if field.key == "max_options" else 1 if field.key == "max_open" else 0
        if not minimum <= value <= field.maximum:
            raise SetupError(f"{field.label}: Erlaubt sind {minimum} bis {field.maximum}.")
        return value
    value = str(raw).strip()
    if field.kind == "choice" and value not in {str(v) for v, _ in field.choices}:
        raise SetupError(f"{field.label}: Unbekannte Auswahl.")
    if field.kind == "timezone":
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise SetupError(f"{field.label}: Unbekannte Zeitzone, zum Beispiel Europe/Berlin verwenden.") from None
    if len(value) > field.maximum:
        raise SetupError(f"{field.label}: Höchstens {field.maximum} Zeichen.")
    return value


async def _validate_fields(wc, request, guild, adapter, values):
    """Guild-Zugehörigkeit, Hierarchie und aktuell wirksame Bot-Rechte."""
    checks = []
    for field in adapter.fields:
        value = values[field.key]
        if field.kind in {"roles", "role"}:
            for rid in (value if field.kind == "roles" else [value]):
                if rid is None:
                    continue
                role = guild.get_role(rid)
                if role is None or role.is_default() or getattr(role.guild, "id", None) != guild.id:
                    raise SetupError(f"{adapter.name} · {field.label}: Rolle gehört nicht zu diesem Server oder ist @everyone.")
                if field.grant:
                    me = guild.me
                    if (getattr(role, "managed", False) or me is None
                            or not me.guild_permissions.manage_roles or role >= me.top_role):
                        raise SetupError(f"{adapter.name} · {field.label}: Der Bot kann diese Rolle nicht vergeben. Bot-Rolle darüber einsortieren und „Rollen verwalten“ erlauben.")
                    if not await wc.can_grant_role(ScopedRequest(request, adapter.slug), guild, role):
                        raise SetupError(f"{adapter.name} · {field.label}: Du darfst diese automatische Rolle nicht vergeben.")
                    checks.append(f"Rolle „{role.name}“: Bot und Bearbeiter dürfen sie vergeben.")
        if field.kind in {"channel", "category", "forum"} and value is not None:
            channel = guild.get_channel(value)
            cls = {"channel": discord.TextChannel, "category": discord.CategoryChannel, "forum": discord.ForumChannel}[field.kind]
            if (channel is None or not isinstance(channel, cls)
                    or getattr(getattr(channel, "guild", None), "id", None) != guild.id):
                raise SetupError(f"{adapter.name} · {field.label}: Bitte einen passenden Kanal auf diesem Server auswählen.")
            # Auch ausgewählte, momentan nicht verwendete Felder müssen echte,
            # erreichbare Ziele sein. So bleibt kein unsichtbarer Fremdwert übrig.
            _channel_permissions(guild, channel, ("view_channel",))
            checks.append(f"{field.label}: „{channel.name}“ ist für den Bot sichtbar.")
    return checks


PERM_NAMES = {
    "view_channel": "Kanal ansehen", "send_messages": "Nachrichten senden", "embed_links": "Links einbetten",
    "read_message_history": "Nachrichtenverlauf anzeigen", "manage_channels": "Kanäle verwalten",
    "manage_roles": "Rollen verwalten", "manage_threads": "Threads verwalten",
    "create_private_threads": "Private Threads erstellen", "create_public_threads": "Öffentliche Threads erstellen",
    "attach_files": "Dateien anhängen",
}


def _channel_permissions(guild, channel, names):
    if guild.me is None:
        raise SetupError("Der Bot ist auf diesem Server noch nicht bereit. Bitte später erneut versuchen.")
    perms = channel.permissions_for(guild.me)
    missing = [PERM_NAMES.get(p, p) for p in names if not getattr(perms, p, False)]
    if missing:
        raise SetupError(f"Kanal „{channel.name}“: Dem Bot fehlen „{'“, „'.join(missing)}“. Bitte in den Discord-Kanalrechten korrigieren und erneut prüfen.")
    return f"„{channel.name}“: " + ", ".join(PERM_NAMES.get(p, p) for p in names) + " erlaubt."


async def _plan(wc, request, guild, adapter, values, previous=None):
    cog = _loaded(wc, adapter)
    if not await _authorized(wc, request, guild, adapter):
        raise SetupError(f"Für „{adapter.name}“ fehlen dir inzwischen Bearbeiten-Rechte oder das Modul wurde entladen.")
    conf = await cog.config.guild(guild).all()
    expected = {adapter.container} if adapter.container else {f.key for f in adapter.fields}
    if not expected <= conf.keys():
        raise SetupError(f"„{adapter.name}“ hat eine andere Konfigurationsversion. Bitte die vollständigen Einstellungen verwenden.")
    checks = await _validate_fields(wc, request, guild, adapter, values)
    patch = dict(values) if not adapter.container else {}
    if adapter.slug == "tickets":
        if not values["support_roles"]:
            raise SetupError("Tickets: Bitte mindestens eine Support-Rolle auswählen.")
        kind = values["ticket_type"]
        target_key = {"category": "category_open", "thread": "thread_base", "forum": "forum_channel"}[kind]
        channel = guild.get_channel(values[target_key]) if values[target_key] else None
        if channel is None:
            raise SetupError("Tickets: Bitte das Ziel für die ausgewählte Ticket-Art festlegen.")
        required = ["view_channel", "manage_channels", "manage_roles"] if kind == "category" else [
            "view_channel", "send_messages", "read_message_history", "manage_threads",
            "create_private_threads" if kind == "thread" else "create_public_threads"]
        checks.append(_channel_permissions(guild, channel, required))
        if values["log_channel"]:
            checks.append(_channel_permissions(guild, guild.get_channel(values["log_channel"]), ["view_channel", "send_messages", "embed_links"]))
    elif adapter.slug == "welcome":
        if values["welcome_enabled"] and not values["welcome_channel"]:
            raise SetupError("Begrüßung: Für eine aktive Begrüßung bitte einen Kanal auswählen.")
        if values["welcome_channel"]:
            required = ["view_channel", "send_messages"] + (["embed_links"] if values["welcome_mode"] == "embed" else [])
            checks.append(_channel_permissions(guild, guild.get_channel(values["welcome_channel"]), required))
            if conf.get("card_enabled"):
                channel = guild.get_channel(values["welcome_channel"])
                checks.append("Vorhandenes Willkommensbild: " + ("Dateien anhängen erlaubt." if channel.permissions_for(guild.me).attach_files else "Der Bot darf keine Dateien anhängen; der vorhandene Cog sendet dann die Nachricht ohne Bild."))
    elif adapter.slug == "autorole":
        if values["enabled"] and not values["join_roles"]:
            raise SetupError("Automatische Rollen: Bitte mindestens eine Beitrittsrolle auswählen oder die Vergabe deaktivieren.")
    elif adapter.slug == "raidhelper":
        if not values["signup_channel"]:
            raise SetupError("Raid-Planung: Bitte einen Anmeldekanal auswählen.")
        checks.append(_channel_permissions(guild, guild.get_channel(values["signup_channel"]), ["view_channel", "send_messages", "embed_links", "read_message_history"]))
    elif adapter.slug == "organigram":
        if not values["name"] or not values["roles"]:
            raise SetupError("Organigramm: Bitte Namen und mindestens eine Rolle angeben.")
        charts = copy.deepcopy(conf["charts"])
        if any(c.get("name", "").casefold() == values["name"].casefold() for c in charts.values()):
            raise SetupError("Organigramm: Dieser Name wird schon verwendet. Bitte einen neuen Namen für den Entwurf wählen.")
        ident = previous["new_id"] if previous else secrets.token_hex(4)
        while not previous and ident in charts:
            ident = secrets.token_hex(4)
        nodes = {}
        parent = None
        roles = sorted((guild.get_role(rid) for rid in values["roles"]), key=lambda r: r.position, reverse=True)
        for index, role in enumerate(roles):
            nid = f"n{index}"
            nodes[nid] = {"role_id": role.id, "label": "", "parent": parent if values["structure"] == "chain" else None,
                          "order": index, "manual_names": [], "emoji": "", "color": ""}
            parent = nid
        charts[ident] = {"name": values["name"], "title": values["name"], "pattern": "baum", "mode": values["mode"],
                         "member_display": "highest", "accent": "#3ddc97", "show_avatars": True, "show_vacant": True,
                         "auto_update": True, "draft": True, "image_mode": "single", "page_size": 20,
                         "nodes": nodes, "posts": []}
        patch = {"charts": charts}
    elif adapter.slug == "sticky":
        if not values["channel"] or not values["text"]:
            raise SetupError("Angeheftete Nachricht: Bitte Kanal und Text für die Vorlage angeben.")
        stickies = copy.deepcopy(conf["stickies"])
        ident = str(values["channel"])
        if ident in stickies:
            raise SetupError("In diesem Kanal besteht bereits eine Sticky-Vorlage. Bitte einen anderen Kanal wählen oder die vorhandene Vorlage in den Einstellungen bearbeiten.")
        # Gleiche Schema-Vorlage wie der Cog; der Assistent deaktiviert sie ausdrücklich.
        stickies[ident] = {"enabled": False, "mode": "text", "text": values["text"], "embed_title": "", "embed_color": "#3ddc97",
                          "embed_image": "", "embed_footer": "", "webhook": False, "webhook_name": "", "webhook_avatar": "",
                          "message_id": None, "webhook_id": None}
        patch = {"stickies": stickies}
        checks.append(_channel_permissions(guild, guild.get_channel(values["channel"]), ["view_channel", "send_messages", "read_message_history"]))
    if _loaded(wc, adapter) is not cog:
        raise SetupError(f"„{adapter.name}“ wurde während der Prüfung neu geladen. Bitte erneut prüfen.")
    result = {"slug": adapter.slug, "owner": cog, "values": copy.deepcopy(values), "before": {k: copy.deepcopy(conf[k]) for k in patch},
              "after": patch, "checks": checks or ["Ausgewählte Einstellungen und Rollen sind gültig."], "new_id": None}
    if adapter.slug == "organigram":
        result["new_id"] = ident
    return result


async def _write_value(cog, guild, key, value):
    await cog.config.guild(guild).set_raw(key, value=copy.deepcopy(value))


async def _rollback(guild, completed):
    failed = []
    for cog, key, before, after in reversed(completed):
        try:
            async with cog.config.guild(guild).get_attr(key).get_lock():
                current = await cog.config.guild(guild).get_raw(key)
                if current == after:
                    await _write_value(cog, guild, key, before)
                elif current != before:
                    failed.append(key)
        except Exception:
            failed.append(key)
            log.exception("Einrichtungsassistent: Rücknahme für %s/%s fehlgeschlagen", guild.id, key)
    return failed


async def _apply(wc, request, guild, draft):
    """Alle Prüfungen zuerst; danach gezielte Schreibvorgänge mit Rücknahme."""
    plans = []
    for old in draft["review"]["plans"]:
        adapter = BY_SLUG[old["slug"]]
        if _loaded(wc, adapter) is not old["owner"]:
            raise SetupError(f"„{adapter.name}“ wurde seit der Vorschau neu geladen. Bitte erneut prüfen.")
        fresh = await _plan(wc, request, guild, adapter, old["values"], previous=old)
        if fresh["owner"] is not old["owner"] or old["before"] != fresh["before"] or old["after"] != fresh["after"]:
            raise SetupError(f"„{adapter.name}“ wurde seit der Vorschau geändert. Bitte erneut prüfen; es wurde nichts übernommen.")
        plans.append(fresh)
    completed = []
    try:
        for plan in plans:
            cog = plan["owner"]
            invalidate = getattr(wc, "_invalidate_access_cache", None)
            if invalidate:
                invalidate(request)
            # Erneut nach vorherigen Modul-Schreibvorgängen prüfen, bevor dieses
            # Modul verändert wird (Rollen/Kanäle können inzwischen geändert sein).
            fresh = await _plan(wc, request, guild, BY_SLUG[plan["slug"]], plan["values"], previous=plan)
            if fresh["owner"] is not cog or fresh["before"] != plan["before"]:
                raise SetupError("Die Einstellungen wurden während der Übernahme verändert. Bitte erneut prüfen.")
            for key, value in plan["after"].items():
                if plan["before"][key] == value:
                    continue
                # Während vorheriger await-Aufrufe könnte das Cog geändert worden sein.
                if not await _authorized(wc, request, guild, BY_SLUG[plan["slug"]], fresh=True):
                    raise SetupError("Bearbeiten-Rechte haben sich während der Übernahme geändert.")
                if _loaded(wc, BY_SLUG[plan["slug"]]) is not cog:
                    raise SetupError("Ein Modul wurde während der Übernahme neu geladen. Bitte erneut prüfen.")
                async with cog.config.guild(guild).get_attr(key).get_lock():
                    current = await cog.config.guild(guild).get_raw(key)
                    if current != plan["before"][key]:
                        raise SetupError("Die Einstellungen wurden während der Übernahme verändert. Bitte erneut prüfen.")
                    if _loaded(wc, BY_SLUG[plan["slug"]]) is not cog:
                        raise SetupError("Ein Modul wurde während der Übernahme neu geladen. Bitte erneut prüfen.")
                    # Auch ein Schreibfehler kann nach einer erfolgreichen Speicherung
                    # auftreten; deshalb den Rücknahme-Eintrag VOR dem await vormerken.
                    completed.append((cog, key, plan["before"][key], value))
                    await _write_value(cog, guild, key, value)
    except (Exception, asyncio.CancelledError) as exc:
        # Auch beim Abbruch eines Requests/Cog-Unloads vollständig zurücknehmen.
        # Die Rücknahme selbst darf ein erneutes cancel() nicht unterbrechen.
        rollback = asyncio.create_task(_rollback(guild, completed))
        cancelled = isinstance(exc, asyncio.CancelledError)
        while True:
            try:
                failed = await asyncio.shield(rollback)
                break
            except asyncio.CancelledError:
                cancelled = True
        if failed:
            log.error("Einrichtungsassistent: unvollständige Rücknahme für Server %s: %s", guild.id, failed)
            raise SetupError("Die Übernahme ist fehlgeschlagen. Einige Einstellungen konnten nicht zurückgesetzt werden. Bitte die betroffenen Module in den vollständigen Einstellungen prüfen und den Bot-Owner informieren.") from exc
        if cancelled:
            raise asyncio.CancelledError from exc
        log.warning("Einrichtungsassistent: Übernahme für Server %s zurückgenommen: %s", guild.id, type(exc).__name__)
        raise SetupError("Die Übernahme ist fehlgeschlagen. Bereits übernommene Änderungen wurden zurückgesetzt. Dein Entwurf bleibt erhalten; bitte erneut prüfen.") from exc
    draft["applied"] = True
    draft["test_token"] = secrets.token_urlsafe(24)
    return plans


def _field_html(ui, guild, adapter, field, value):
    name = adapter.slug + "." + field.key
    if field.kind == "bool":
        return ui.switch(name, field.label, value, desc=field.help or None)
    if field.kind in {"roles", "role"}:
        choices = [(r.id, f"{r.name} · {r.id}") for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                   if not r.is_default() and (not field.grant or not r.managed)]
        control = ui.select(name, choices, value, multiple=field.kind == "roles", none_label="Keine" if field.kind == "role" else None,
                            placeholder="Rollen suchen …")
    elif field.kind in {"channel", "category", "forum"}:
        cls = {"channel": discord.TextChannel, "category": discord.CategoryChannel, "forum": discord.ForumChannel}[field.kind]
        choices = [(c.id, f"{c.name} · {c.id}") for c in guild.channels if isinstance(c, cls)]
        control = ui.select(name, choices, value, none_label="Bitte auswählen …")
    elif field.kind == "choice":
        control = ui.select(name, field.choices, value)
    elif field.kind == "textarea":
        control = ui.textarea(name, value, rows=3)
    elif field.kind == "number":
        control = ui.number(name, value, min=2 if field.key == "max_options" else 1 if field.key == "max_open" else 0, max=field.maximum)
    else:
        control = ui.text_input(name, value, attrs={"maxlength": field.maximum})
    return ui.field(field.label, control, help=ui.esc(field.help) if field.help else None, wide=field.kind == "textarea")


def _display(ui, guild, field, value):
    if field.kind == "bool":
        return "Aktiv" if value else "Deaktiviert"
    if field.kind in {"roles", "role"}:
        ids = value if field.kind == "roles" else [value]
        return ", ".join(f"{getattr(guild.get_role(rid), 'name', 'Gelöschte Rolle')} · {rid}" for rid in ids if rid) or "Keine"
    if field.kind in {"channel", "category", "forum"}:
        return f"{getattr(guild.get_channel(value), 'name', 'Gelöschter Kanal')} · {value}" if value else "Keine"
    if field.kind == "choice":
        return dict(field.choices).get(value, str(value))
    return str(value) if value not in (None, "") else "Standard / leer"


def _configuration(ui, guild, draft, csrf):
    cards = []
    for slug in draft["selected"]:
        adapter = BY_SLUG[slug]
        values = draft["values"][slug]
        basic, advanced = [], []
        for field in adapter.fields:
            markup = _field_html(ui, guild, adapter, field, values.get(field.key, field.default))
            (advanced if field.advanced else basic).append(markup)
        body = ui.grid(*basic)
        if advanced:
            body += ui.disclosure("Weitere Einstellungen", ui.grid(*advanced))
        cards.append(ui.card(adapter.name, body, desc=ui.esc(adapter.summary), actions=ui.button("Vollständige Einstellungen",
                             href=f"/cogs/{adapter.slug}?guild={guild.id}", kind="ghost", small=True)))
    return ui.form(PATH, "".join(cards) + ui.actions(ui.button("Änderungen prüfen", icon="bi-search"),
                   ui.button("Modulauswahl ändern", href=_url(guild, step="modules"), kind="ghost")), csrf=csrf,
                   hidden={"action": "review", "guild": guild.id, "draft": draft["id"]}, savebar=True)


def _review_html(ui, guild, draft, csrf):
    cards = []
    for plan in draft["review"]["plans"]:
        adapter = BY_SLUG[plan["slug"]]
        rows = []
        for field in adapter.fields:
            after = _display(ui, guild, field, plan["values"][field.key])
            before = "Neuer Entwurf" if adapter.container else _display(ui, guild, field, plan["before"][field.key])
            changed = bool(adapter.container) or plan["before"][field.key] != plan["values"][field.key]
            rows.append("<tr><td>" + ui.esc(field.label) + "</td><td>" + ui.esc(before) + "</td><td>" + ui.esc(after)
                        + (" " + ui.badge("Änderung", "info") if changed else " " + ui.badge("Unverändert")) + "</td></tr>")
        body = ui.table(["Einstellung", "Bisher", "Nach Übernahme"], rows)
        if adapter.slug == "organigram":
            body += ui.callout("Neuer Entwurf: unveröffentlicht, automatische Aktualisierung erst nach ausdrücklicher Veröffentlichung. Bestehende Organigramme werden erhalten.")
        if adapter.slug == "sticky":
            body += ui.callout("Neue Vorlage: <b>Deaktiviert</b>. Es wird keine Nachricht veröffentlicht.")
        checks = "<ul>" + "".join("<li>" + ui.esc(check) + "</li>" for check in plan["checks"]) + "</ul>"
        body += ui.disclosure("Geprüfte Bot-Rechte und Bereitschaft", checks, expanded=True)
        body += ui.button("Vollständige Einstellungen", href=f"/cogs/{adapter.slug}?guild={guild.id}", kind="ghost", small=True)
        cards.append(ui.card(adapter.name, body, desc=ui.esc(adapter.summary)))
    return "".join(cards) + ui.form(PATH, ui.switch("confirm", "Diese geprüften Änderungen übernehmen", False,
                      desc="Aktive Begrüßung und Rollenvergabe gelten anschließend für zukünftige Beitritte.")
                      + ui.actions(ui.button("Jetzt übernehmen", icon="bi-check2-circle"),
                                   ui.button("Zurück zum Entwurf", href=_url(guild, step="configure"), kind="ghost")),
                      csrf=csrf, hidden={"action": "apply", "guild": guild.id, "draft": draft["id"], "review": draft["review"]["token"]})


async def handle_setup(wc, request):
    """Alle Entwurfsaktionen pro Server ordnen, auch doppelte Browser-Anfragen."""
    if request.method == "POST":
        _prune(wc)
        form = await request.post()
        raw = form.get("guild")
        guild = wc.bot.get_guild(int(raw)) if raw and str(raw).isdigit() else None
        if guild is not None:
            async with wc._setup_flow_locks.setdefault(guild.id, asyncio.Lock()):
                return await _handle_setup(wc, request)
    return await _handle_setup(wc, request)


async def _handle_setup(wc, request):
    """GET/POST /setup; Ergebnis vom normalen WebCore-Seitenrahmen rendern lassen."""
    user = await wc.current_user(request)
    if user is None:
        raise web.HTTPForbidden(text="Bitte zuerst anmelden.")
    csrf = await wc._csrf_token(request)
    request["webcore_csrf"] = csrf
    form = await request.post() if request.method == "POST" else None
    if form is not None and not secrets.compare_digest(str(form.get("csrf_token", "")), csrf):
        raise web.HTTPBadRequest(text="Ungültiges CSRF-Token. Bitte Seite neu laden.")
    _prune(wc)
    guilds = await setup_guilds(wc, request)
    allowed = {g.id: g for g in guilds}
    raw = (form.get("guild") if form is not None else request.query.get("guild"))
    guild = allowed.get(int(raw)) if raw and str(raw).isdigit() else None
    ui = wc.ui
    if guild is None:
        if raw or form is not None:
            raise web.HTTPForbidden(text="Für diesen Server hast du keine passenden Bearbeiten-Rechte.")
        choices = ui.select("guild", [(g.id, g.name) for g in guilds], none_label="Server auswählen …")
        body = ui.form(PATH, ui.field("Server", choices) + ui.actions(ui.button("Einrichtung beginnen")), csrf="", method="get") if guilds else ui.callout(
            "Es ist kein unterstütztes Modul mit Bearbeiten-Rechten verfügbar. Bitte ein Modul laden oder den Bot-Owner nach Zugriff fragen.", tone="warn")
        return {"title": "Gemeinsame Einrichtung", "content": ui.card("1 · Server auswählen", body)}
    key = (int(user["id"]), csrf, guild.id)
    wc._set_switcher(request, guilds, guild.id, PATH)
    draft = wc._setup_drafts.get(key)
    error = ""
    step = request.query.get("step", "")
    if form is not None:
        action = form.get("action")
        if action == "choose":
            slugs = list(dict.fromkeys(_getlist(form, "modules")))
            if not slugs or any(s not in BY_SLUG for s in slugs):
                raise web.HTTPBadRequest(text="Bitte mindestens ein unterstütztes Modul auswählen.")
            for slug in slugs:
                if not await _authorized(wc, request, guild, BY_SLUG[slug]):
                    raise web.HTTPForbidden(text="Für eines der ausgewählten Module fehlen Bearbeiten-Rechte.")
                if not await _compatible(wc, guild, BY_SLUG[slug]):
                    raise web.HTTPBadRequest(text="Ein ausgewähltes Modul hat eine inkompatible Konfigurationsversion. Bitte die vollständigen Einstellungen verwenden.")
            old = draft
            draft = _new_draft(wc, key, slugs)
            for slug in slugs:
                adapter = BY_SLUG[slug]
                conf = await _loaded(wc, adapter).config.guild(guild).all()
                draft["values"][slug] = copy.deepcopy(old["values"][slug]) if old and slug in old["values"] and not old["applied"] else {
                    field.key: copy.deepcopy(field.default if adapter.container else conf.get(field.key, field.default)) for field in adapter.fields}
            return {"redirect": _url(guild, step="configure")}
        if not draft or form.get("draft") != draft["id"]:
            raise web.HTTPBadRequest(text="Der Entwurf ist abgelaufen oder gehört zu einer anderen Sitzung. Bitte neu beginnen.")
        if action == "review":
            draft["review"] = None
            if draft["applied"]:
                raise web.HTTPBadRequest(text="Dieser Entwurf wurde bereits übernommen. Bitte eine neue Einrichtung beginnen.")
            try:
                parsed = {}
                for slug in draft["selected"]:
                    adapter = BY_SLUG[slug]
                    if not await _authorized(wc, request, guild, adapter):
                        raise web.HTTPForbidden(text="Für ein ausgewähltes Modul fehlen inzwischen Bearbeiten-Rechte.")
                    # Rohwerte zuerst merken, damit auch bei Validierungsfehlern
                    # kein zuvor eingegebener Text verloren geht.
                    for field in adapter.fields:
                        name = slug + "." + field.key
                        raw_value = _getlist(form, name) if field.kind == "roles" else form.get(name, "")
                        draft["values"][slug][field.key] = (name in form) if field.kind == "bool" else raw_value
                for slug in draft["selected"]:
                    parsed[slug] = {f.key: _parse(f, form, slug + "." + f.key) for f in BY_SLUG[slug].fields}
                plans = [await _plan(wc, request, guild, BY_SLUG[s], parsed[s]) for s in draft["selected"]]
                draft["values"] = parsed
                draft["review"] = {"token": secrets.token_urlsafe(24), "plans": plans}
                draft["expires"] = time.monotonic() + TTL
                return {"redirect": _url(guild, step="review")}
            except SetupError as exc:
                error = str(exc)
                step = "configure"
        elif action == "apply":
            if (not draft["review"] or not secrets.compare_digest(str(form.get("review", "")), draft["review"]["token"])
                    or form.get("confirm") != "on"):
                raise web.HTTPBadRequest(text="Bitte die aktuelle Vorschau prüfen und die Übernahme ausdrücklich bestätigen.")
            lock = wc._setup_locks.setdefault(guild.id, asyncio.Lock())
            async with lock:
                # Ein paralleler Request kann inzwischen einen neuen Entwurf
                # erstellt oder die Freigabe durch erneutes Prüfen ersetzt haben.
                if (wc._setup_drafts.get(key) is not draft or draft["expires"] <= time.monotonic()
                        or not draft["review"] or form.get("review") != draft["review"]["token"]):
                    raise web.HTTPBadRequest(text="Die Vorschau ist nicht mehr aktuell. Bitte erneut prüfen.")
                for slug in draft["selected"]:
                    if not await _authorized(wc, request, guild, BY_SLUG[slug]):
                        raise web.HTTPForbidden(text="Für ein ausgewähltes Modul fehlen inzwischen Bearbeiten-Rechte.")
                if not draft["applied"]:
                    try:
                        # Keine pro Request veralteten Dashboard-Rechte verwenden.
                        invalidate = getattr(wc, "_invalidate_access_cache", None)
                        if invalidate:
                            invalidate(request)
                        await _apply(wc, request, guild, draft)
                    except SetupError as exc:
                        draft["review"] = None
                        error = str(exc)
                        step = "configure"
                if draft["applied"]:
                    return {"redirect": _url(guild, step="done", ok="Einrichtung übernommen")}
        elif action == "test_welcome":
            if (not draft["applied"] or "welcome" not in draft["selected"] or not draft.get("test_token")
                    or not secrets.compare_digest(str(form.get("test", "")), draft["test_token"])):
                raise web.HTTPBadRequest(text="Bitte zuerst die Einrichtung übernehmen und den aktuellen Testknopf verwenden.")
            adapter = BY_SLUG["welcome"]
            if not await _authorized(wc, request, guild, adapter):
                raise web.HTTPForbidden(text="Für diesen Test fehlen Bearbeiten-Rechte für Begrüßung.")
            member = await wc._resolve_member(guild, int(user["id"]))
            if member is None:
                raise web.HTTPForbidden(text="Für diesen Test musst du Mitglied des ausgewählten Servers sein.")
            cog = _loaded(wc, adapter)
            conf = await cog.config.guild(guild).all()
            if conf != draft.get("test_conf"):
                raise web.HTTPBadRequest(text="Die Begrüßung wurde seit der Test-Vorschau verändert. Bitte die Abschlussseite neu laden.")
            channel = guild.get_channel(conf.get("welcome_channel")) if conf.get("welcome_channel") else None
            if not isinstance(channel, discord.TextChannel):
                return {"redirect": _url(guild, step="done", err="Bitte zuerst einen gültigen Begrüßungskanal einstellen")}
            try:
                _channel_permissions(guild, channel, ("view_channel", "send_messages"))
            except SetupError as exc:
                return {"redirect": _url(guild, step="done", err=str(exc))}
            # Ein Test ist eine eigene, ausdrücklich ausgelöste Aktion. Nur die
            # aktuell gespeicherte Konfiguration verwenden; keinerlei Form-Text.
            draft["test_token"] = None
            ok, _ = await cog.post(member, "welcome", conf, ping=False)
            return {"redirect": _url(guild, step="done", **({"ok": "Testnachricht gesendet"} if ok else {"err": "Testnachricht konnte nicht gesendet werden. Bitte die Begrüßungs-Einstellungen prüfen"}))}
        else:
            raise web.HTTPBadRequest(text="Unbekannter Einrichtungsschritt.")
    # Ein GET darf auch nach Rechteentzug keine alten Konfigurationsdaten zeigen.
    if draft:
        for slug in draft["selected"]:
            if not await _authorized(wc, request, guild, BY_SLUG[slug]):
                raise web.HTTPForbidden(text="Ein ausgewähltes Modul ist nicht mehr für dich bearbeitbar. Bitte eine neue Modulauswahl beginnen.")
    content = ui.hero("bi-magic", "", "Server auswählen → Module auswählen → Einstellungen prüfen → ausdrücklich übernehmen.")
    if error:
        content += ui.callout(ui.esc(error), tone="bad")
    if draft and draft["applied"] and step != "modules":
        links = ui.actions(*(ui.button(BY_SLUG[s].name, href=f"/cogs/{s}?guild={guild.id}", kind="ghost") for s in draft["selected"]))
        content += ui.card("Einrichtung übernommen", "<p>Die geprüften Einstellungen wurden gespeichert. Unveröffentlichte Vorlagen kannst du jetzt in den jeweiligen Einstellungen fertigstellen.</p>" + links
                           + ui.button("Weitere Einrichtung beginnen", href=_url(guild, step="modules"), kind="ghost"))
        testlinks = []
        for plan in draft["review"]["plans"]:
            slug = plan["slug"]
            query = {"guild": guild.id}
            if slug == "organigram":
                query["chart"] = plan["new_id"]
            labels = {"tickets": ("panels", "Ticket-Panel prüfen"), "welcome": ("willkommen", "Begrüßungs-Vorschau öffnen"),
                      "autorole": ("rollen", "Rollen prüfen"), "poll": ("neu", "Umfrage vorbereiten"),
                      "raidhelper": ("neu", "Raid vorbereiten"), "organigram": ("posten", "Organigramm-Vorschau öffnen"),
                      "sticky": ("stickies", "Deaktivierte Sticky-Vorlage prüfen"), "giveaways": ("neu", "Gewinnspiel vorbereiten"),
                      "scheduler": ("neu", "Nachrichten-Vorschau vorbereiten")}
            anchor, label = labels[slug]
            href = f"/cogs/{slug}?{urlencode(query)}#{anchor}"
            testlinks.append(ui.button(label, href=href, kind="ghost", small=True))
        tests = "<p>Prüfe die gespeicherten Einstellungen in der jeweiligen Vorschau. Panels, Organigramme und Sticky-Nachrichten werden erst dort ausdrücklich veröffentlicht.</p>" + ui.actions(*testlinks)
        if "welcome" in draft["selected"]:
            conf = await _loaded(wc, BY_SLUG["welcome"]).config.guild(guild).all()
            draft["test_token"] = secrets.token_urlsafe(24)
            draft["test_conf"] = copy.deepcopy(conf)
            channel = guild.get_channel(conf.get("welcome_channel")) if conf.get("welcome_channel") else None
            if isinstance(channel, discord.TextChannel):
                tests += ui.form(PATH, "<p>Ein Begrüßungstest sendet eine echte Nachricht nach <b>" + ui.esc(channel.name)
                                 + "</b>, mit dir als Beispiel und ohne Erwähnungen.</p>" + ui.actions(ui.button("Testnachricht senden", icon="bi-send", kind="ghost")),
                                 csrf=csrf, hidden={"action": "test_welcome", "guild": guild.id, "draft": draft["id"], "test": draft["test_token"]},
                                 confirm=f"Gespeicherte Begrüßung ohne Erwähnungen nach #{channel.name} senden?")
        content += ui.card("5 · Vorschau und Tests", tests)
    elif draft and step == "review" and draft["review"]:
        content += ui.card("4 · Vorschau vor der Übernahme", "<p>Prüfe Zielserver, Aktiv-Schalter und Änderungen. Beim Übernehmen werden Berechtigungen und Konfiguration erneut geprüft.</p>" + ui.badge(guild.name, "info"))
        content += _review_html(ui, guild, draft, csrf)
    elif draft and step != "modules":
        content += ui.callout("Dein Entwurf ist für 30 Minuten in dieser Sitzung gespeichert. Über den Assistenten kannst du ihn fortsetzen. Ein Bot-Neustart verwirft ihn.")
        content += ui.card("3 · Einstellungen für " + guild.name, "Wähle Rollen und Kanäle. Mit „Änderungen prüfen“ siehst du zuerst die genaue Vorschau.")
        content += _configuration(ui, guild, draft, csrf)
    else:
        modules = []
        for adapter in ADAPTERS:
            if await _authorized(wc, request, guild, adapter) and await _compatible(wc, guild, adapter):
                modules.append(ui.switch("modules", adapter.name, bool(draft and adapter.slug in draft["selected"]), value=adapter.slug, desc=adapter.summary))
        resume = ui.button("Gespeicherten Entwurf fortsetzen", href=_url(guild, step="configure"), kind="ghost") if draft and not draft["applied"] else ""
        content += ui.card("2 · Module für " + guild.name, ui.form(PATH, ui.switches(*modules) + ui.actions(ui.button("Einstellungen auswählen"), resume),
                            csrf=csrf, hidden={"action": "choose", "guild": guild.id}), desc="Nur geladene Module mit deinen Bearbeiten-Rechten werden angeboten.")
    # Auch nicht unterstützte Module bleiben über echte Einstellungsseiten erreichbar.
    more = []
    for slug, page in wc.pages.items():
        if slug not in BY_SLUG and guild.id in {g.id for g in await wc.visible_guilds(ScopedRequest(request, slug), min_level=acl.VIEW)}:
            more.append(ui.button(page.name, href=f"/cogs/{slug}?guild={guild.id}", kind="ghost", small=True))
    if more:
        content += ui.disclosure("Weitere geladene Module", ui.actions(*more))
    return {"title": "Gemeinsame Einrichtung", "content": content}
