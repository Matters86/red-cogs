"""WebCore-Dashboard für den FiveM-Admin-Cog (``fivemadmin``).

Das eigene Live-Panel (``panel.html``, eigener aiohttp-Server, Bridge-API) bleibt unverändert
für die Aktionen im Spiel. Diese Seite bündelt die **Verwaltung** im gemeinsamen Dashboard –
mit WebCore-Rollen-Rechten und WebCore-Audit-Log:

Reiter Übersicht (Kennzahlen, Live-Panel/Anmelden, Not-Aus, Einrichtung, letzte Aktionen) ·
Sperren · Panel-Rechte · Einstellungen.

Rechte (alles serverseitig):

* Server-Auswahl, Ansehen/Bearbeiten: ``webcore.visible_guilds`` (GET = Ansehen, POST = Bearbeiten).
* Zusätzlich je Aktion die fivemadmin-Rechte des Nutzers auf dem gewählten Server
  (``member_permissions``; Owner/Allowlist = alle Rechte) – gespiegelt von Befehl/Panel-Endpunkt:

  - Entbannen            → Panel-Recht ``ban``          (``[p]ap unban``, ``/api/panel/unban``)
  - Lockdown an/aus      → Discord-Administrator        (``[p]ap lockdown``)
  - Rollen/Personen      → Discord-Administrator        (``[p]ap roles``, ``/api/panel/roles|users``)
                            + kein Preset über den eigenen Rechten (Schutz vor Selbst-Hochstufung)
  - Einstellungen        → nur Owner/Allowlist, da botweit (``has_full_scope``)
  - Anmelden (SSO)       → beliebige Panel-Rechte des Discord-Mitglieds (wie ``[p]ap login``)

* Sichtbarkeit wie im Live-Panel: Sperrliste nur mit ``ban`` (``/api/panel/bans``), letzte Aktionen
  nur mit ``audit`` (``/api/panel/audit``), Rollen-/Personen-Zuordnungen nur für Discord-Administratoren
  (``/api/panel/roles``); sonst ein Hinweis statt Daten. Kennzahlen (Anzahlen) bleiben sichtbar.
"""

from __future__ import annotations

import asyncio
import datetime
import html
import json
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import discord

from . import db
from .adminpanel import (
    ALL_PERMS,
    DEFAULT_API_KEY,
    DEFAULT_ITEM_MAX,
    DEFAULT_MONEY_MAX,
    DEFAULT_PUBLIC_URL,
    DEFAULT_WEB_HOST,
    DEFAULT_WEB_PORT,
    PRESETS,
)

SLUG = "fivemadmin"
TITLE = "FiveM-Admin"
BASE = f"/cogs/{SLUG}"

# Presets in fester Reihenfolge mit deutscher Erklärung (Anzeige + Auswahl).
PRESET_INFO = {
    "support": ("Support", "Spielerliste, Teleport, Heilen, Wiederbeleben, Fahrzeug einparken, "
                           "Inventar ansehen, Nachrichten an Spieler"),
    "moderator": ("Moderator", "alles aus Support + Kick, Bannen/Entbannen, Ansagen, Protokoll, "
                               "Notizen/Verwarnungen, Job/Gang setzen"),
    "admin": ("Admin", "alles aus Moderator + Geld, Items, Statistiken, alle Fahrzeuge einparken, Audit"),
    "editor": ("Editor", "Server-Status und Statistiken – lässt sich mit den anderen Presets kombinieren"),
}
PRESET_ORDER = [p for p in PRESET_INFO if p in PRESETS] + [p for p in PRESETS if p not in PRESET_INFO]

ACTION_LABEL = {
    "teleport": "Teleport", "teleport_coords": "Teleport (Koordinaten)", "car_to_garage": "Einparken",
    "get_vehicles": "Fahrzeuge abfragen", "heal": "Heilen", "revive": "Wiederbeleben", "kick": "Kick",
    "announce": "Ansage", "money": "Geld", "give_item": "Item geben", "remove_item": "Item nehmen",
    "get_inventory": "Inventar abfragen", "get_stats": "Statistik", "search_player": "Spielersuche",
    "set_job": "Job setzen", "set_gang": "Gang setzen", "notify": "Nachricht", "park_all": "Alle einparken",
    "ban": "Ban", "diag": "Diagnose",
}
STATUS_BADGE = {"pending": ("offen", "info"), "done": ("erledigt", "ok"), "failed": ("fehlgeschlagen", "bad")}
BRIDGE_LIVE_SECONDS = 30  # die Bridge synchronisiert alle paar Sekunden


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _num(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def _fmt_ts(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def _fmt_age(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 5:
        return "gerade eben"
    if s < 90:
        return f"vor {s} s"
    if s < 90 * 60:
        return f"vor {s // 60} Min."
    if s < 36 * 3600:
        return f"vor {s // 3600} Std."
    return f"vor {s // 86400} Tagen"


def _redirect(guild, *, ok: str | None = None, err: str | None = None) -> dict:
    url = f"{BASE}?guild={guild.id}" if guild is not None else f"{BASE}?"
    if err:
        url += "&err=" + quote(err)
    elif ok:
        url += "&ok=" + quote(ok)
    return {"redirect": url}


def _may_assign(my_perms: set, *presets) -> bool:
    """Schutz vor Selbst-Hochstufung: jedes beteiligte Preset (alt und neu) darf nicht mehr
    Rechte haben als der Handelnde selbst."""
    return all(PRESETS.get(p, set()) <= my_perms for p in presets if p)


# --------------------------------------------------------------------------- #
#  Wer handelt?
# --------------------------------------------------------------------------- #
@dataclass
class Actor:
    user: dict | None
    member: object | None
    full: bool                      # Owner/Allowlist (volle Sicht)
    panel_perms: set = field(default_factory=set)   # echte Panel-Rechte des Discord-Mitglieds
    discord_admin: bool = False

    @property
    def perms(self) -> set:
        """Wirksame Rechte für Dashboard-Aktionen: Owner/Allowlist = alles."""
        return set(ALL_PERMS) if self.full else self.panel_perms

    @property
    def is_admin(self) -> bool:
        """Darf, was `has_permissions(administrator=True)`-Befehle dürfen (Owner inklusive)."""
        return self.full or self.discord_admin

    @property
    def name(self) -> str:
        if self.member is not None:
            return self.member.display_name
        return (self.user or {}).get("name") or "?"


async def _resolve_member(guild, uid: int):
    member = guild.get_member(uid)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(uid)
    except (discord.NotFound, discord.HTTPException):
        return None


async def _actor(cog, request, guild) -> Actor:
    webcore = request.app["webcore"]
    # WebCore hat (noch) keinen öffentlichen Helfer für den angemeldeten Nutzer –
    # `commands/dashboard.py` nutzt denselben Weg.
    user = await webcore._get_user(request)
    full = await webcore.has_full_scope(request)
    member = await _resolve_member(guild, int(user["id"])) if user else None
    perms = await cog.member_permissions(member) if member is not None else set()
    admin = full or await cog.is_panel_admin(member)
    return Actor(user=user, member=member, full=full, panel_perms=set(perms), discord_admin=admin)


async def _visible_guilds(request) -> list:
    webcore = request.app["webcore"]
    return sorted(await webcore.visible_guilds(request), key=lambda g: g.name.lower())


def _pick_guild(guilds, raw):
    if raw and str(raw).isdigit():
        for g in guilds:
            if g.id == int(raw):
                return g
    return None


async def _settings(cog) -> dict:
    """Wirksame globale Einstellungen (Config-Wert, sonst ENV/Standard) – ohne Secrets."""
    conf = await cog.config.all()
    api_key = conf.get("api_key") or DEFAULT_API_KEY
    return {
        "locked": bool(conf.get("locked")),
        "audit_channel": conf.get("audit_channel"),
        "alert_channel": conf.get("alert_channel"),
        "public_url": (conf.get("public_url") or DEFAULT_PUBLIC_URL or "").rstrip("/"),
        "public_url_raw": conf.get("public_url"),
        "money_max": int(conf.get("money_max") or DEFAULT_MONEY_MAX),
        "item_max": int(conf.get("item_max") or DEFAULT_ITEM_MAX),
        "api_key_set": bool(api_key) and api_key != "CHANGE_ME",
        "oauth_set": bool(conf.get("oauth_client_id") and conf.get("oauth_client_secret")),
        "web_port": getattr(cog, "web_port", None) or conf.get("web_port") or DEFAULT_WEB_PORT,
        "web_host": getattr(cog, "web_host", None) or conf.get("web_host") or DEFAULT_WEB_HOST,
    }


# --------------------------------------------------------------------------- #
#  Einstiegspunkt
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(request)
    guild = _pick_guild(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": TITLE, "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}

    csrf = request.get("webcore_csrf", "")
    readonly = bool(request.get("webcore_readonly"))
    actor = await _actor(cog, request, guild)
    st = await _settings(cog)
    gconf = await cog.config.guild(guild).all()
    state = await asyncio.to_thread(db.get_server_state)
    pending = await asyncio.to_thread(db.get_pending_actions)
    bans = await asyncio.to_thread(db.get_active_bans)
    actions = await asyncio.to_thread(db.get_actions_audit, 150)

    # Eigene Server-Auswahl nur ohne globalen Server-Wechsler von WebCore.
    bar = ""
    if not request.get("wc_switcher"):
        bar = ui.form(BASE, ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True),
                      csrf="", method="get", cls="wc-inline-form")
    live_btn = ""
    if st["public_url"]:
        live_btn = ui.button("Live-Panel öffnen", icon="bi-box-arrow-up-right", kind="ghost",
                             href=st["public_url"] + "/", attrs={"target": "_blank", "rel": "noopener"})

    head = ui.hero(
        "bi-controller", "",
        "Verwaltung deines <b>FiveM-Servers</b>: Not-Aus, Sperren, Panel-Rechte und Einstellungen. "
        "Aktionen im Spiel (Teleport, Heilen, Geld …) laufen weiterhin im <b>Live-Panel</b> – "
        "Anmeldung dort mit einem Klick unter „Übersicht“.",
        actions=bar + live_btn,
    ) + ui.stats(_stats(state, pending, bans, st))

    body = (
        ui.tab("uebersicht", "Übersicht", "bi-speedometer2",
               _render_overview(ui, cog, guild, actor, st, gconf, state, pending, actions, csrf, readonly))
        + ui.tab("sperren", "Sperren", "bi-slash-circle", _render_bans(ui, guild, actor, bans, csrf), count=len(bans))
        + ui.tab("rechte", "Panel-Rechte", "bi-person-badge", _render_rights(ui, guild, actor, gconf, csrf))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", _render_settings(ui, guild, actor, st, csrf))
    )
    return {"title": TITLE, "content": head + body}


def _stats(state, pending, bans, st):
    now = time.time()
    if not state:
        bridge = ("Bridge", "Nie verbunden", "bi-plug", "noch kein Sync", "bad")
        players = ("Spieler online", "—", "bi-people", None, None)
    else:
        age = now - float(state.get("synced_at") or 0)
        live = age <= BRIDGE_LIVE_SECONDS
        bridge = ("Bridge", "Verbunden" if live else "Getrennt", "bi-plug",
                  f"Letzter Sync {_fmt_age(age)}", "ok" if live else "warn")
        n = len(state.get("players") or [])
        slots = state.get("max_slots")
        players = ("Spieler online", f"{n}/{slots}" if slots else str(n), "bi-people",
                   str(state.get("server_name") or "")[:60] or None, "ok" if live and n else None)
    return [
        bridge,
        players,
        ("Offene Aufträge", len(pending), "bi-hourglass-split",
         "werden beim nächsten Sync ausgeführt" if pending else None, "info" if pending else None),
        ("Lockdown", "AN" if st["locked"] else "Aus", "bi-sign-stop",
         "alle Aktionen gesperrt" if st["locked"] else None, "bad" if st["locked"] else "ok"),
        ("Aktive Sperren", len(bans), "bi-slash-circle", None, None),
    ]


def _my_presets(member, gconf) -> list[str]:
    if member is None:
        return []
    role_map = gconf.get("role_map") or {}
    out = []
    for role in getattr(member, "roles", []):
        p = role_map.get(str(role.id))
        if p in PRESETS and p not in out:
            out.append(p)
    p = (gconf.get("user_map") or {}).get(str(member.id))
    if p in PRESETS and p not in out:
        out.append(p)
    return out


def _render_live_card(ui, guild, actor, st, gconf, csrf, readonly) -> str:
    # Eigene Panel-Rechte (echte Discord-Rechte – die zählen im Live-Panel)
    if actor.member is None:
        mine = ui.callout("Du bist auf diesem Server kein Mitglied – im Live-Panel hast du hier keine Rechte.",
                          tone="warn")
    elif actor.discord_admin:
        mine = f"<p class='wc-muted'>Deine Panel-Rechte: {ui.badge('Discord-Administrator – alle Rechte', 'ok')}</p>"
    elif actor.panel_perms:
        pills = " ".join(ui.badge(PRESET_INFO.get(p, (p,))[0], "ok") for p in _my_presets(actor.member, gconf))
        mine = f"<p class='wc-muted'>Deine Panel-Rechte: {pills}</p>"
    else:
        mine = ui.callout("Du hast auf diesem Server <b>keine Panel-Rechte</b>. Ein Discord-Administrator kann "
                          "dir im Reiter „Panel-Rechte“ ein Preset geben.", tone="info")

    if not st["public_url"]:
        action = ui.callout("Keine <b>Panel-URL</b> gesetzt – Live-Panel öffnen und Anmelden per Dashboard sind "
                            "erst danach möglich (Reiter „Einstellungen“). Bis dahin: <code>[p]ap login</code>.",
                            tone="warn")
    elif actor.member is None or not actor.panel_perms:
        action = ui.actions(ui.button("Live-Panel öffnen", icon="bi-box-arrow-up-right", kind="ghost",
                                      href=st["public_url"] + "/", attrs={"target": "_blank", "rel": "noopener"}))
    elif readonly:
        action = ui.callout("Anmelden per Dashboard braucht auf dieser Seite das Recht <b>Bearbeiten</b>. "
                            "Alternativ in Discord <code>[p]ap login</code> nutzen.", tone="info") + ui.actions(
            ui.button("Live-Panel öffnen", icon="bi-box-arrow-up-right", kind="ghost",
                      href=st["public_url"] + "/", attrs={"target": "_blank", "rel": "noopener"}))
    else:
        action = ui.form(
            BASE,
            ui.actions(
                ui.button("Im Live-Panel anmelden", icon="bi-box-arrow-in-right"),
                ui.button("Nur öffnen", icon="bi-box-arrow-up-right", kind="ghost",
                          href=st["public_url"] + "/", attrs={"target": "_blank", "rel": "noopener"}),
            ),
            csrf=csrf, hidden={"form": "sso", "guild": guild.id},
        )
    return ui.card(
        "Live-Panel", mine + action, icon="bi-box-arrow-in-right",
        desc="Spieler verwalten, Teleport, Heilen, Geld … Anmelden meldet dich mit deinem Discord-Konto an – "
             "wie ein Einmal-Link aus <code>[p]ap login</code> (5 Min. gültig).",
    )


def _render_lockdown_card(ui, guild, actor, st, pending, csrf) -> str:
    locked = st["locked"]
    status = (ui.badge("Lockdown AKTIV", "bad") if locked else ui.badge("Normalbetrieb", "ok"))
    text = (f"<p class='wc-muted'>Status: {status}</p>")
    if not actor.is_admin:
        ctrl = ui.callout("Nur <b>Discord-Administratoren</b> dieses Servers oder der Bot-Owner können den Not-Aus "
                          "schalten – wie bei <code>[p]ap lockdown</code>.", tone="info")
    elif locked:
        ctrl = ui.form(BASE, ui.actions(ui.button("Lockdown aufheben", icon="bi-unlock")),
                       csrf=csrf, hidden={"form": "lockdown", "state": "off", "guild": guild.id},
                       confirm="Lockdown aufheben? Panel-Aktionen und Befehle sind danach wieder möglich.")
    else:
        n = len(pending)
        ctrl = ui.form(BASE, ui.actions(ui.button("Lockdown aktivieren", icon="bi-sign-stop", kind="danger")),
                       csrf=csrf, hidden={"form": "lockdown", "state": "on", "guild": guild.id},
                       confirm=f"Not-Aus aktivieren? Alle Aktionen werden sofort gesperrt und {n} offene(r) "
                               f"Auftrag/Aufträge verworfen.")
    return ui.card(
        "Not-Aus", text + ctrl, icon="bi-sign-stop", tone="bad" if locked else None,
        desc="Sperrt sofort alle handelnden Aktionen im Live-Panel und per Discord-Befehl und verwirft offene "
             "Aufträge. Lesende Abfragen (Diagnose, Suche, Sperrliste) bleiben möglich. Gilt für den ganzen "
             "FiveM-Server.",
    )


def _setup_checks(cog, guild, st, gconf, state) -> list[tuple[str, str]]:
    out = []
    if st["locked"]:
        out.append(("bad", "<b>Lockdown ist aktiv</b> – alle handelnden Aktionen sind gesperrt."))
    if not st["api_key_set"]:
        out.append(("bad", "Kein <b>API-Key</b> gesetzt – die Bridge ist gesperrt (HTTP 503). "
                           "Per Discord erzeugen: <code>[p]ap config key</code>."))
    if getattr(cog, "runner", None) is None:
        out.append(("warn", f"Der <b>Webserver des Live-Panels</b> läuft nicht (Port {_esc(st['web_port'])}). "
                            "Bot-Log prüfen, ggf. <code>[p]reload fivemadmin</code>."))
    if not st["public_url"]:
        out.append(("warn", "Keine <b>Panel-URL</b> – Login-Links kommen nur als Token; „Live-Panel öffnen“ und "
                            "Anmelden per Dashboard sind aus. Im Reiter „Einstellungen“ setzen."))
    if not state:
        out.append(("warn", "Die <b>Bridge</b> hat sich noch nie gemeldet – läuft <code>ap_bridge</code> auf dem "
                            "FiveM-Server und stimmt der API-Key in der <code>server.cfg</code>?"))
    else:
        age = time.time() - float(state.get("synced_at") or 0)
        if age > 120:
            out.append(("warn", f"Letzter <b>Bridge-Sync</b> {_esc(_fmt_age(age))} – der FiveM-Server ist "
                                "offline oder erreicht das Panel nicht."))
    role_map = gconf.get("role_map") or {}
    if not role_map and not (gconf.get("user_map") or {}):
        out.append(("warn", "Keine <b>Rollen zugeordnet</b> – nur Discord-Administratoren haben Panel-Rechte. "
                            "Im Reiter „Panel-Rechte“ zuordnen."))
    stale = [rid for rid in role_map if not (str(rid).isdigit() and guild.get_role(int(rid)))]
    if stale:
        out.append(("info", f"{len(stale)} Rollen-Zuordnung(en) zeigen auf <b>gelöschte Rollen</b> – im Reiter "
                            "„Panel-Rechte“ entfernen."))
    if not st["audit_channel"]:
        out.append(("info", "Kein <b>Audit-Kanal</b> – heikle Aktionen (Geld, Items, Bans, Rechte-Änderungen) werden "
                            "nirgends in Discord protokolliert."))
    if not st["alert_channel"]:
        out.append(("info", "Kein <b>Alert-Kanal</b> – Missbrauchs-Warnungen der Bridge (Geld-/Item-Sprünge) gehen "
                            "nirgendwohin."))
    if not st["oauth_set"]:
        out.append(("info", "„Mit Discord anmelden“ im Live-Panel ist aus (<code>[p]ap config oauth</code>) – "
                            "Anmeldung per Dashboard oder <code>[p]ap login</code> funktioniert trotzdem."))
    return out


def _action_detail(a) -> str:
    try:
        p = json.loads(a.get("params") or "{}")
    except (ValueError, TypeError):
        p = {}
    if not isinstance(p, dict):
        return ""
    t = a.get("action_type")
    try:
        if t == "money":
            return f"{p.get('op', '?')} {_num(p.get('amount') or 0)} $ ({p.get('account', '?')})"
        if t in ("give_item", "remove_item"):
            return f"{p.get('item', '?')} ×{p.get('count', '?')}"
        if t in ("set_job", "set_gang"):
            return f"{p.get('job') or p.get('gang') or '?'} (Grad {p.get('grade', 0)})"
        if t == "ban":
            hrs = int(p.get("hours") or 0)
            return ("permanent" if hrs <= 0 else f"{hrs} Std.") + (f" · {p.get('reason')}" if p.get("reason") else "")
        if t in ("kick",):
            return str(p.get("reason") or "")
        if t in ("announce", "notify"):
            return str(p.get("message") or "")
    except (TypeError, ValueError):
        return ""
    return ""


def _who(created_by) -> str:
    s = str(created_by or "?")
    if s.startswith("web:"):
        return "Live-Panel · " + s[4:]
    if s.startswith("discord:"):
        return "Discord · " + s[8:]
    return s


def _render_overview(ui, cog, guild, actor, st, gconf, state, pending, actions, csrf, readonly) -> str:
    top = ui.columns(_render_live_card(ui, guild, actor, st, gconf, csrf, readonly),
                     _render_lockdown_card(ui, guild, actor, st, pending, csrf))

    checks = _setup_checks(cog, guild, st, gconf, state)
    check_html = ("".join(ui.callout(t, tone=tone) for tone, t in checks) if checks
                  else ui.callout("Alles eingerichtet – Bridge verbunden, Rechte vergeben.", tone="ok"))
    setup = ui.card("Einrichtung", check_html, icon="bi-clipboard-check",
                    desc="Was noch fehlt oder Aufmerksamkeit braucht.")

    if "audit" not in actor.perms:  # wie GET /api/panel/audit
        return top + setup + ui.card("Letzte Aktionen", _need_right(ui, "„Audit“", "Preset Admin"),
                                     icon="bi-clock-history")
    rows = []
    for a in actions:
        label, tone = STATUS_BADGE.get(a.get("status"), (a.get("status") or "?", "muted"))
        detail = _action_detail(a)
        target = a.get("target_name") or a.get("target")
        sub = _esc(a.get("result"))[:140] if a.get("status") == "failed" and a.get("result") else ""
        rows.append(ui.row(
            f"<span class='mono'>{_esc(_fmt_ts(a.get('created_at')))}</span>",
            f"<div class='wc-cell-title'>{_esc(ACTION_LABEL.get(a.get('action_type'), a.get('action_type')))}</div>"
            + (f"<div class='wc-cell-sub'>{_esc(detail[:120])}</div>" if detail else ""),
            f"<span class='mono'>{_esc(target)}</span>"
            + (f"<div class='wc-cell-sub'>{_esc(a.get('target'))}</div>" if a.get("target_name") else ""),
            ui.badge(label, tone) + (f"<div class='wc-cell-sub'>{sub}</div>" if sub else ""),
            _esc(_who(a.get("created_by"))),
        ))
    recent = ui.card(
        "Letzte Aktionen",
        ui.table(["Zeit", "Aktion", "Ziel", "Status", "Von"], rows, search=True, id="fa-actions",
                 search_placeholder="Aktion, Spieler, Team-Mitglied …",
                 empty_text="Noch keine Aktionen – sie erscheinen, sobald jemand im Live-Panel oder per Befehl handelt."),
        icon="bi-clock-history",
        desc="Die letzten 150 Aufträge aus Live-Panel und Discord-Befehlen (Audit der Action-Queue).",
    )
    return top + setup + recent


def _need_right(ui, right: str, presets: str) -> str:
    """Hinweis statt Daten, wenn das Live-Panel dem Nutzer diese Ansicht auch nicht zeigen würde."""
    return ui.callout(f"Dafür brauchst du im Live-Panel das Recht <b>{right}</b> ({presets}).", tone="info",
                      icon="bi-lock")


def _render_bans(ui, guild, actor, bans, csrf) -> str:
    # Wie GET /api/panel/bans (und Entbannen /api/panel/unban): Panel-Recht "ban".
    if "ban" not in actor.perms:
        return ui.card("Aktive Sperren", _need_right(ui, "„Bannen“", "Preset Moderator oder Admin"),
                       icon="bi-slash-circle")
    note = ui.callout(
        "Neue Sperren legst du im Live-Panel oder mit <code>[p]ap ban</code> an – sie werden beim nächsten Sync "
        "ausgeführt. Abgelaufene Sperren verschwinden automatisch.", tone="info")
    rows = []
    for b in bans:
        cid = b.get("citizenid")
        until = "permanent" if not b.get("expires_at") else f"bis {_fmt_ts(b.get('expires_at'))}"
        btn = ""
        if cid:
            btn = ui.form(
                BASE,
                ui.button("Entbannen", icon="bi-unlock", kind="danger", small=True),
                csrf=csrf, hidden={"form": "unban", "guild": guild.id, "cid": cid},
                confirm=f"Sperre für {b.get('name') or cid} ({cid}) aufheben? Der Spieler kann sofort wieder verbinden.",
            )
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(b.get('name') or '—')}</div>"
            f"<div class='wc-cell-sub mono'>{_esc(cid or b.get('license') or '—')}</div>",
            _esc(str(b.get("reason") or "")[:300]),
            ui.badge("permanent", "bad") if not b.get("expires_at") else _esc(until),
            f"{_esc(_who(b.get('banned_by')))}<div class='wc-cell-sub'>{_esc(_fmt_ts(b.get('created_at')))}</div>",
            ">" + (f"<div class='wc-row-actions'>{btn}</div>" if btn else ""),
        ))
    table = ui.table(["Spieler", "Grund", "Dauer", "Gesperrt von", ">"], rows, search=True, id="fa-bans",
                     search_placeholder="Name, CitizenID, Grund …", empty_text="Keine aktiven Sperren.")
    return note + ui.card("Aktive Sperren", table, icon="bi-slash-circle",
                          desc="Gilt für den ganzen FiveM-Server; die Bridge setzt Sperren beim Verbinden durch.")


def _cell(control: str) -> str:
    """Steuerelement in einer Tabellenzelle – auf dem Handy über die volle Kartenbreite."""
    return f"<div class='wc-row-actions'>{control}</div>"


def _preset_items():
    return [(p, PRESET_INFO.get(p, (p,))[0]) for p in PRESET_ORDER]


def _render_rights(ui, guild, actor, gconf, csrf) -> str:
    info = "".join(f"<dt>{ui.badge(PRESET_INFO.get(p, (p,))[0], 'info')}</dt>"
                   f"<dd>{_esc(PRESET_INFO.get(p, (p, ''))[1])}</dd>" for p in PRESET_ORDER)
    presets = ui.card(
        "Presets", f"<dl class='wc-kv'>{info}</dl>",
        icon="bi-info-circle",
        desc="Discord-Administratoren haben automatisch alle Rechte. Presets aus Rollen und Einzelpersonen "
             "addieren sich. Änderungen gelten sofort – das Live-Panel prüft bei jeder Anfrage neu.",
    )

    if not actor.is_admin:  # wie GET /api/panel/roles: nur Discord-Administratoren (Owner inklusive)
        return presets + ui.card("Zuordnungen", ui.callout(
            "Welche Rollen und Personen welches Preset haben, sehen und ändern nur <b>Discord-Administratoren</b> "
            "dieses Servers oder der Bot-Owner – wie im Live-Panel und bei <code>[p]ap roles</code>.",
            tone="info", icon="bi-lock"), icon="bi-people")

    role_map = gconf.get("role_map") or {}
    rows = []
    for r in sorted(guild.roles, key=lambda x: -x.position):
        if r.is_default() or getattr(r, "managed", False):
            continue
        color = f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None
        dot = f"<span class='wc-role-dot' style='background:{_esc(color)}'></span>" if color else "<span class='wc-role-dot'></span>"
        rows.append(ui.row(
            f"{dot}<b>{_esc(r.name)}</b><div class='wc-cell-sub'>{len(getattr(r, 'members', []) or [])} Mitglieder</div>",
            _cell(ui.select(f"role:{r.id}", _preset_items(), role_map.get(str(r.id)), none_label="— kein Zugriff")),
        ))
    for rid, preset in role_map.items():
        if str(rid).isdigit() and guild.get_role(int(rid)):
            continue
        rows.append(ui.row(
            f"<span class='wc-role-dot'></span><b>Gelöschte Rolle</b><div class='wc-cell-sub mono'>{_esc(rid)}</div>",
            _cell(ui.select(f"role:{rid}", [(preset, PRESET_INFO.get(preset, (preset,))[0])], preset,
                            none_label="— entfernen")),
        ))
    roles_card = ui.card(
        "Rollen", ui.table(["Rolle", "Preset"], rows, search=True, id="fa-roles", search_placeholder="Rolle suchen …",
                           empty_text="Keine Rollen auf diesem Server."),
        icon="bi-people", desc="Welches Preset bekommen alle Mitglieder einer Discord-Rolle? (wie <code>[p]ap roles set</code>)",
    )

    user_map = gconf.get("user_map") or {}
    urows = []
    for uid, preset in sorted(user_map.items(), key=lambda kv: kv[0]):
        m = guild.get_member(int(uid)) if str(uid).isdigit() else None
        name = (f"<b>{_esc(m.display_name)}</b>" + (" " + ui.badge("Discord-Admin – hat ohnehin alles", "muted")
                                                     if m.guild_permissions.administrator else "")
                if m else "<b>nicht mehr auf dem Server</b>")
        urows.append(ui.row(
            f"{name}<div class='wc-cell-sub mono'>{_esc(uid)}</div>",
            _cell(ui.select(f"user:{uid}", _preset_items(), preset, none_label="— entfernen")),
        ))
    add = ui.divider() + ui.grid(
        ui.field("Person hinzufügen", ui.text_input("add_user", "", placeholder="Nutzer-ID, @Erwähnung oder Name"),
                 help="Discord-ID (Rechtsklick → ID kopieren) oder exakter Anzeige-/Benutzername."),
        ui.field("Preset", ui.select("add_preset", _preset_items(), "support")),
    )
    users_card = ui.card(
        "Einzelpersonen", ui.table(["Person", "Preset"], urows, id="fa-users",
                                   empty_text="Keine Einzel-Zugriffe.") + add,
        icon="bi-person-plus", desc="Zusätzliches Preset für einzelne Mitglieder – unabhängig von ihren Rollen.",
    )

    note = ui.callout("Du kannst nur Presets vergeben oder entziehen, die <b>nicht mehr Rechte</b> haben als du selbst.",
                      tone="info")
    form = ui.form(BASE, roles_card + users_card + ui.save_row(), csrf=csrf,
                   hidden={"form": "rights", "guild": guild.id}, savebar=True)
    return presets + note + form


def _channel_items(guild, current):
    items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    if current and not any(c.id == int(current) for c in guild.text_channels):
        items.insert(0, (int(current), f"Kanal auf anderem Server ({current})"))
    return items


def _render_settings(ui, guild, actor, st, csrf) -> str:
    can = actor.full
    dis = None if can else {"disabled": True}

    channels = ui.card("Kanäle", ui.grid(
        ui.field("Audit-Kanal", ui.select("audit_channel", _channel_items(guild, st["audit_channel"]),
                                          st["audit_channel"], none_label="— aus", attrs=dis),
                 help="Heikle Aktionen (Geld, Items, Bans, Job/Gang, Rechte, Lockdown). Tipp: ein Kanal, in dem "
                      "die Admins selbst nichts löschen können."),
        ui.field("Alert-Kanal", ui.select("alert_channel", _channel_items(guild, st["alert_channel"]),
                                          st["alert_channel"], none_label="— aus", attrs=dis),
                 help="Missbrauchs-Warnungen der Bridge (Geld-/Item-Sprünge, Dupe-Muster)."),
    ), icon="bi-hash", desc="Wohin der Bot in Discord protokolliert.")

    limits = ui.card("Limits pro Aktion", ui.grid(
        ui.field("Geld", ui.number("money_max", st["money_max"], min=1, unit="$", attrs=dis),
                 help="Höchstbetrag je Geld-Aktion (Live-Panel und <code>[p]ap money</code>)."),
        ui.field("Items", ui.number("item_max", st["item_max"], min=1, unit="Stück", attrs=dis),
                 help="Höchstanzahl je Item-Aktion."),
    ), icon="bi-speedometer", desc="Schützt vor Vertippern und missbrauchten Sitzungen.")

    url = ui.card("Live-Panel", ui.grid(
        ui.field("Panel-URL", ui.text_input("public_url", st["public_url_raw"] or "",
                                            placeholder=DEFAULT_PUBLIC_URL or "https://panel.deinedomain.tld",
                                            type="url", attrs=dis),
                 help="Öffentliche Adresse des Live-Panels (für Login-Links und „Live-Panel öffnen“). "
                      "Leer = Vorgabe aus <code>ADMINPANEL_PUBLIC_URL</code>.", wide=True),
        cols=1,
    ), icon="bi-link-45deg")

    def state_badge(ok):
        return ui.badge("gesetzt", "ok") if ok else ui.badge("nicht gesetzt", "warn")

    cmd_rows = [
        ui.row("API-Key (Bridge)", state_badge(st["api_key_set"]), "<code>[p]ap config key</code>"),
        ui.row("Discord-Login (OAuth)", state_badge(st["oauth_set"]), "<code>[p]ap config oauth</code>"),
        ui.row("Web-Port", f"<span class='mono'>{_esc(st['web_port'])}</span>", "<code>[p]ap config port</code>"),
        ui.row("Bind-Adresse", f"<span class='mono'>{_esc(st['web_host'])}</span>", "<code>[p]ap config bind</code>"),
    ]
    cmd_card = ui.card(
        "Nur per Discord-Befehl", ui.table(["Einstellung", "Status", "Ändern mit"], cmd_rows),
        icon="bi-terminal",
        desc="Geheimnisse und Netzwerk-Einstellungen bleiben bewusst im Discord-Befehl (Nachrichten mit Secrets "
             "löscht der Bot sofort). Port und Bind-Adresse gelten nach <code>[p]reload fivemadmin</code>.",
    )

    if can:
        form = ui.form(BASE, channels + limits + url + ui.save_row(), csrf=csrf,
                       hidden={"form": "settings", "guild": guild.id}, savebar=True)
        return ui.callout("Diese Einstellungen gelten <b>botweit</b> – für den FiveM-Server und alle Discord-Server.",
                          tone="info") + form + cmd_card
    note = ui.callout("Diese Einstellungen gelten <b>botweit</b> – ändern kann sie nur der Bot-Owner.", tone="info")
    return note + channels + limits + url + cmd_card


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    guilds = await _visible_guilds(request)  # POST -> nur Server mit "Bearbeiten"
    guild = _pick_guild(guilds, data.get("guild"))
    if guild is None:
        return {"redirect": f"{BASE}?err=" + quote("Server nicht gefunden oder keine Bearbeitungsrechte")}
    actor = await _actor(cog, request, guild)
    handler = {
        "sso": _post_sso,
        "lockdown": _post_lockdown,
        "unban": _post_unban,
        "rights": _post_rights,
        "settings": _post_settings,
    }.get(data.get("form"))
    if handler is None:
        return _redirect(guild, err="Unbekannte Aktion")
    return await handler(cog, guild, actor, data)


async def _post_sso(cog, guild, actor, data):
    st = await _settings(cog)
    if not st["public_url"]:
        return _redirect(guild, err="Keine Panel-URL gesetzt – Anmelden per Dashboard ist erst danach möglich")
    if actor.member is None:
        return _redirect(guild, err="Du bist auf diesem Server kein Mitglied")
    # Gleiche Prüfung wie `[p]ap login`: echte Panel-Rechte des Discord-Mitglieds.
    perms = await cog.member_permissions(actor.member)
    if not perms:
        return _redirect(guild, err="Du hast auf diesem Server keine Panel-Rechte")
    token = await asyncio.to_thread(
        db.create_login_token, str(actor.member.id), str(guild.id), actor.member.display_name
    )
    return {"redirect": f"{st['public_url']}/?login={quote(token)}"}


async def _post_lockdown(cog, guild, actor, data):
    if not actor.is_admin:
        return _redirect(guild, err="Den Not-Aus dürfen nur Discord-Administratoren oder der Bot-Owner schalten")
    state = data.get("state")
    by = f"{actor.name} (Dashboard)"
    if state == "on":
        dropped = await cog.set_lockdown(True, by)
        return _redirect(guild, ok=f"Lockdown aktiv – {dropped} offene Aufträge verworfen")
    if state == "off":
        await cog.set_lockdown(False, by)
        return _redirect(guild, ok="Lockdown aufgehoben")
    return _redirect(guild, err="Ungültiger Zustand")


async def _post_unban(cog, guild, actor, data):
    # Wie `/api/panel/unban` und `[p]ap unban`: Panel-Recht "ban" (im Lockdown erlaubt).
    if "ban" not in actor.perms:
        return _redirect(guild, err="Zum Entbannen fehlt dir das Panel-Recht „Bannen“ (Moderator/Admin)")
    cid = str(data.get("cid") or "").strip()[:100]
    if not cid:
        return _redirect(guild, err="CitizenID fehlt")
    removed = await asyncio.to_thread(db.remove_ban, cid)
    if not removed:
        return _redirect(guild, err=f"Keine aktive Sperre für {cid}")
    await cog._audit(f"🔓 **Unban** · `{cid.replace('`', '')}` · von {actor.name} (Dashboard)")
    return _redirect(guild, ok=f"Sperre für {cid} aufgehoben")


def _find_member(guild, query: str):
    q = (query or "").strip()
    if q.startswith("<@") and q.endswith(">"):
        q = q.strip("<@!>")
    if q.isdigit():
        return guild.get_member(int(q)), int(q)
    q = q.lstrip("@").casefold()
    if not q:
        return None, None
    hits = [m for m in guild.members if q in (m.display_name.casefold(), m.name.casefold())]
    return (hits[0], hits[0].id) if len(hits) == 1 else (None, None)


async def _post_rights(cog, guild, actor, data):
    # Wie `[p]ap roles …` und die Panel-Endpunkte: nur Discord-Administratoren (Owner inklusive).
    if not actor.is_admin:
        return _redirect(guild, err="Panel-Rechte ändern dürfen nur Discord-Administratoren oder der Bot-Owner")
    my = actor.perms
    gconf = cog.config.guild(guild)
    role_map = dict(await gconf.role_map())
    user_map = dict(await gconf.user_map())
    audits, denied, invalid = [], [], []

    for key in {k for k in data.keys() if k.startswith("role:")}:
        rid = key[5:]
        new = data.get(key) or None
        old = role_map.get(rid)
        if new == old:
            continue
        if new is not None and new not in PRESETS:
            invalid.append(rid)
            continue
        role = guild.get_role(int(rid)) if rid.isdigit() else None
        if role is None:
            if new is not None or old is None:  # gelöschte Rolle: nur Entfernen erlaubt
                invalid.append(rid)
                continue
            label = f"gelöschte Rolle ({rid})"
        elif role.is_default() or getattr(role, "managed", False):
            invalid.append(role.name)
            continue
        else:
            label = f"@{role.name}"
        if not _may_assign(my, old, new):
            denied.append(label)
            continue
        if new:
            role_map[rid] = new
        else:
            role_map.pop(rid, None)
        audits.append(f"🔧 **Rollen-Mapping** · {label} → {new or '— entfernt'} · von {actor.name} (Dashboard)")

    changes_user = []
    for key in {k for k in data.keys() if k.startswith("user:")}:
        changes_user.append((key[5:], data.get(key) or None))
    add_q = str(data.get("add_user") or "").strip()
    if add_q:
        member, uid = _find_member(guild, add_q)
        if uid is None:
            return _redirect(guild, err="Person nicht gefunden – Discord-ID oder exakten Namen angeben")
        if member is None:
            member = await _resolve_member(guild, uid)
            if member is None:
                return _redirect(guild, err="Diese Person ist nicht auf dem Server")
        changes_user.append((str(uid), data.get("add_preset") or None))

    for uid, new in changes_user:
        old = user_map.get(uid)
        if new == old or not uid.isdigit():
            continue
        if new is not None and new not in PRESETS:
            invalid.append(uid)
            continue
        target = guild.get_member(int(uid))
        if target is None and new is not None:
            target = await _resolve_member(guild, int(uid))
            if target is None:  # beim Entfernen darf die Person den Server schon verlassen haben
                invalid.append(uid)
                continue
        if target is not None and getattr(target, "bot", False):
            invalid.append(target.display_name)
            continue
        label = f"{target.display_name} (`{uid}`)" if target is not None else f"`{uid}`"
        if not _may_assign(my, old, new):
            denied.append(label)
            continue
        if new:
            user_map[uid] = new
        else:
            user_map.pop(uid, None)
        audits.append(f"🔧 **Einzel-Zugriff** · {label} → {new or '— entfernt'} · von {actor.name} (Dashboard)")

    if audits:
        await gconf.role_map.set(role_map)
        await gconf.user_map.set(user_map)
        for line in audits:
            await cog._audit(line)
    if denied:
        return _redirect(guild, err=f"Nicht erlaubt (Preset über deinen eigenen Rechten): {', '.join(denied)[:200]}"
                                    + (f" – {len(audits)} andere Änderung(en) gespeichert" if audits else ""))
    if invalid:
        return _redirect(guild, err=f"Ungültige Einträge übersprungen: {', '.join(map(str, invalid))[:200]}"
                                    + (f" – {len(audits)} Änderung(en) gespeichert" if audits else ""))
    if not audits:
        return _redirect(guild, ok="Keine Änderungen")
    return _redirect(guild, ok=f"Panel-Rechte gespeichert ({len(audits)} Änderung{'en' if len(audits) != 1 else ''})")


def _parse_channel(guild, raw, current):
    """'' -> None; sonst Kanal dieses Servers oder der bisherige Wert (unverändert)."""
    raw = str(raw or "").strip()
    if not raw:
        return True, None
    if not raw.isdigit():
        return False, None
    cid = int(raw)
    if cid == current or any(c.id == cid for c in guild.text_channels):
        return True, cid
    return False, None


async def _post_settings(cog, guild, actor, data):
    # Botweite Werte (gelten für alle Server) -> nur Owner/Allowlist.
    if not actor.full:
        return _redirect(guild, err="Diese Einstellungen gelten botweit – nur der Bot-Owner kann sie ändern")
    st = await _settings(cog)
    ok_a, audit_ch = _parse_channel(guild, data.get("audit_channel"), st["audit_channel"])
    ok_b, alert_ch = _parse_channel(guild, data.get("alert_channel"), st["alert_channel"])
    if not (ok_a and ok_b):
        return _redirect(guild, err="Ungültiger Kanal")
    try:
        money_max = int(str(data.get("money_max", st["money_max"])).strip())
        item_max = int(str(data.get("item_max", st["item_max"])).strip())
    except ValueError:
        return _redirect(guild, err="Limits müssen ganze Zahlen sein")
    if money_max < 1 or item_max < 1:
        return _redirect(guild, err="Limits müssen mindestens 1 sein")
    url = str(data.get("public_url") or "").strip().rstrip("/")
    if url:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or any(ch in url for ch in " \"'<>"):
            return _redirect(guild, err="Die Panel-URL muss mit http:// oder https:// beginnen")

    changes = []
    if audit_ch != st["audit_channel"]:
        changes.append(("audit_channel", audit_ch, f"Audit-Kanal → {f'<#{audit_ch}>' if audit_ch else 'aus'}"))
    if alert_ch != st["alert_channel"]:
        changes.append(("alert_channel", alert_ch, f"Alert-Kanal → {f'<#{alert_ch}>' if alert_ch else 'aus'}"))
    if money_max != st["money_max"]:
        changes.append(("money_max", money_max, f"Geld-Limit → {_num(money_max)} $"))
    if item_max != st["item_max"]:
        changes.append(("item_max", item_max, f"Item-Limit → {item_max} Stück"))
    if (url or None) != (st["public_url_raw"] or None):
        changes.append(("public_url", url or None, f"Panel-URL → {url or 'Vorgabe'}"))
    if not changes:
        return _redirect(guild, ok="Keine Änderungen")

    text = f"⚙️ **Einstellungen** · {' · '.join(c[2] for c in changes)} · von {actor.name} (Dashboard)"
    # Erst in den bisherigen Audit-Kanal (falls er gerade abgeschaltet/verlegt wird) …
    await cog._audit(text)
    for key, value, _ in changes:
        await getattr(cog.config, key).set(value)
    # … und in einen neuen Audit-Kanal ebenfalls.
    if any(c[0] == "audit_channel" and c[1] for c in changes):
        await cog._audit(text)
    # Laufzeitwerte wie die Befehle sofort übernehmen.
    cog.money_max = money_max
    cog.item_max = item_max
    cog.public_url = (url or DEFAULT_PUBLIC_URL or "").rstrip("/")
    return _redirect(guild, ok="Einstellungen gespeichert")
