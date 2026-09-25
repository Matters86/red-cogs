"""WebCore-Dashboard für den Guard-Cog.

Aufgaben (gleiches Muster wie poll/raidhelper):
* GET                 -> Seite mit Reitern (siehe unten)
* POST form=settings  -> Alle Einstellungen speichern (Post/Redirect/Get)
* POST form=lockdown  -> Notmodus an-/ausschalten

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``), kein
eigenes CSS: Reiter Übersicht (Einrichtung, Notmodus-Schalter, Verlauf) ·
Honeypot · Spamschutz · Eskalation · Raid & Notmodus · Allgemein & Ausnahmen.
Die Einstellungs-Reiter liegen in *einem* Formular – ein Speichern sendet alles.
Nutzereingaben werden mit ``html.escape`` abgesichert.
"""

from __future__ import annotations

import html
import time
from urllib.parse import quote

from aiohttp import web

from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

ACTIONS = (
    ("ban", "Bann"),
    ("softban", "Softban (Kick + Nachrichten weg)"),
    ("kick", "Kick"),
    ("timeout", "Timeout"),
)
JOIN_ACTIONS = (
    ("none", "Nichts tun"),
    ("kick", "Kicken"),
    ("timeout", "Timeout"),
)

# Checkbox-Felder (Anwesenheit im Formular = an).
BOOL_FIELDS = (
    "hp_enabled", "spam_enabled", "ignore_bots", "use_modlog",
    "s_rate", "s_repeat", "s_repeat_crosschannel", "s_mentions",
    "s_invites", "s_links", "s_walls", "s_newaccount",
    "delete_violations", "raid_enabled", "lockdown_pause_invites",
)

# Zahlenfelder: name -> (min, max).
INT_FIELDS = {
    "hp_delete_seconds": (0, 604800),
    "hp_timeout_minutes": (1, 40320),
    "s_rate_count": (1, 100),
    "s_rate_seconds": (1, 3600),
    "s_repeat_count": (1, 50),
    "s_repeat_seconds": (1, 3600),
    "s_mentions_max": (1, 100),
    "s_walls_attachments": (1, 100),
    "s_walls_emojis": (1, 200),
    "s_walls_newlines": (1, 500),
    "s_newaccount_hours": (1, 8760),
    "pts_rate": (0, 100), "pts_repeat": (0, 100), "pts_mentions": (0, 100),
    "pts_invite": (0, 100), "pts_link": (0, 100), "pts_wall": (0, 100),
    "pts_newaccount": (0, 100),
    "decay_seconds": (5, 86400),
    "warn_at": (1, 1000), "timeout_at": (1, 1000), "kick_at": (1, 1000), "ban_at": (1, 1000),
    "spam_timeout_minutes": (1, 40320),
    "raid_joins": (2, 1000),
    "raid_seconds": (1, 3600),
    "lockdown_slowmode": (0, 21600),
    "lockdown_auto_minutes": (0, 1440),
}

HISTORY_LIMIT = 50

_KIND_LABEL = {
    "honeypot": ("Honeypot", "bad"), "spam": ("Spam", "warn"), "raid": ("Raid/Notmodus", "bad"),
    "lockdown_join": ("Beitritt (Notmodus)", "info"), "lockdown_end": ("Notmodus beendet", "ok"),
}
_ACTION_LABEL = {"ban": "Bann", "softban": "Softban", "kick": "Kick", "timeout": "Timeout",
                 "warn": "Verwarnung", "delete": "gelöscht", "none": "—"}
_RULE_LABEL = {"honeypot": "Honeypot", "rate": "Rate", "repeat": "Wiederholung",
               "mentions": "Erwähnungen", "invite": "Einladung", "link": "Link",
               "wall": "Wall", "newaccount": "neues Konto", "lockdown_join": "Beitritt"}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _num(ui, conf, name, default, *, unit=None) -> str:
    """Zahlenfeld mit den Grenzen aus ``INT_FIELDS``."""
    lo, hi = INT_FIELDS[name]
    return ui.number(name, int(conf.get(name, default)), min=lo, max=hi, unit=unit)


def _switches(*items) -> str:
    return "<div class='wc-switches'>" + "".join(items) + "</div>"


# --------------------------------------------------------------------------- #
#  Einstieg / Guild-Auswahl
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


async def _visible_guilds(cog, request):
    webcore = request.app.get("webcore")
    if webcore is not None:
        guilds = await webcore.visible_guilds(request)
    else:  # Fallback (sollte im Normalbetrieb nicht eintreten)
        guilds = list(cog.bot.guilds)
    return sorted(guilds, key=lambda g: g.name.lower())


def _pick_guild(guilds, request):
    gid = request.query.get("guild")
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                return g
    return guilds[0] if guilds else None


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(cog, request)
    guild = _pick_guild(guilds, request)
    if guild is None:
        return {"title": "Guard", "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")

    # Eigene Server-Auswahl nur ohne globalen Server-Wechsler von WebCore.
    bar = ""
    if not request.get("wc_switcher"):
        bar = ui.form("/cogs/guard", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True),
                      csrf="", method="get", cls="wc-inline-form")

    head = ui.hero(
        "bi-shield-lock", "",
        "Guard schützt den Server mit drei Bausteinen: einem <b>Honeypot</b>-Kanal als Falle für Spam-Bots, "
        "einem <b>Spamschutz</b> mit Punktesystem und einer <b>Raid-Erkennung</b>, die bei zu vielen Beitritten "
        "den <b>Notmodus</b> auslöst.",
        actions=bar,
    ) + _render_stats(ui, conf)

    body = (
        ui.tab("uebersicht", "Übersicht", "bi-speedometer2", _render_overview(ui, guild, conf, csrf))
        + _render_settings(ui, guild, conf, csrf)
    )
    return {"title": "Guard", "content": head + body}


def _lockdown_text(conf) -> str:
    until = conf.get("lockdown_until")
    # (Früher stand hier Discord-Markdown "<t:…:R>" – im Browser ein unsichtbares Tag.)
    if until and until > 0:
        mins = max(0, int((until - time.time()) // 60))
        return f"endet automatisch in ca. {mins} Min."
    return "bis zur manuellen Aufhebung"


def _lockdown_short(conf) -> str:
    until = conf.get("lockdown_until")
    if until and until > 0:
        return f"noch ca. {max(0, int((until - time.time()) // 60))} Min."
    return "bis manuell beendet"


def _render_stats(ui, conf) -> str:
    today = sum(1 for r in (conf.get("history") or []) if time.time() - r.get("ts", 0) <= 86400)
    ld_active = bool(conf.get("lockdown_until"))
    return ui.stats([
        ("Auslösungen gesamt", int(conf.get("stats_total", 0)), "bi-lightning", None, None),
        ("Letzte 24 h", today, "bi-clock-history", None, "warn" if today else None),
        ("Honeypot", "an" if conf.get("hp_enabled") else "aus", "bi-bug", None, "ok" if conf.get("hp_enabled") else None),
        ("Spamschutz", "an" if conf.get("spam_enabled") else "aus", "bi-shield-check", None,
         "ok" if conf.get("spam_enabled") else None),
        ("Notmodus", "aktiv" if ld_active else "aus", "bi-lock", _lockdown_short(conf) if ld_active else None,
         "bad" if ld_active else None),
    ])


def _setup_checks(guild, conf) -> list[tuple[str, str]]:
    """Kurze Einrichtungs-Prüfung: [(tone, text)]."""
    out = []
    hp_chan = conf.get("hp_channel")
    if conf.get("hp_enabled") and not hp_chan:
        out.append(("bad", "Der <b>Honeypot</b> ist an, aber es ist kein <b>Honeypot-Kanal</b> gewählt – er greift nicht."))
    elif hp_chan and guild.get_channel(int(hp_chan)) is None:
        out.append(("warn", "Der gewählte <b>Honeypot-Kanal</b> existiert nicht mehr – wähle im Reiter „Honeypot“ einen neuen."))
    if not conf.get("hp_enabled") and not conf.get("spam_enabled"):
        out.append(("warn", "<b>Honeypot</b> und <b>Spamschutz</b> sind beide aus – Guard reagiert derzeit nur auf Raids."))
    if not conf.get("raid_enabled", True):
        out.append(("info", "Die <b>Raid-Erkennung</b> ist aus – der Notmodus startet nur noch manuell."))
    if not conf.get("log_channel"):
        out.append(("info", "Kein <b>Log-Kanal</b> gesetzt – Aktionen erscheinen nur im Verlauf unten. Festlegen unter „Allgemein &amp; Ausnahmen“."))
    return out


def _render_overview(ui, guild, conf, csrf) -> str:
    checks = _setup_checks(guild, conf)
    if checks:
        check_html = "".join(ui.callout(text, tone=tone) for tone, text in checks)
    else:
        check_html = ui.callout("Alles eingerichtet – Guard ist aktiv.", tone="ok")
    setup = ui.card("Einrichtung", check_html, icon="bi-clipboard-check")
    # Karten in eigenen <div>s behalten ihren Abstand nach unten (wc-cols setzt ihn sonst auf 0).
    top = ui.columns(f"<div>{_render_lockdown(ui, guild, conf, csrf)}</div>", f"<div>{setup}</div>")
    return top + _render_history(ui, conf)


def _render_lockdown(ui, guild, conf, csrf) -> str:
    active = bool(conf.get("lockdown_until"))
    if active:
        text = ui.callout(f"<b>Der Notmodus ist aktiv</b> – {_esc(_lockdown_text(conf))}", tone="bad", icon="bi-lock-fill")
        btn = ui.button("Notmodus beenden", icon="bi-unlock", name="state", value="off")
    else:
        text = ("<p class='wc-help'>Setzt Slowmode in allen Textkanälen, pausiert (falls möglich) Einladungen "
                "und behandelt neue Beitritte gemäß Reiter „Raid &amp; Notmodus“.</p>")
        btn = ui.button("Notmodus jetzt aktivieren", icon="bi-lock", kind="danger", name="state", value="on",
                        confirm="Der Notmodus setzt sofort Slowmode in allen Textkanälen und pausiert ggf. Einladungen.")
    form = ui.form("/cogs/guard", text + ui.actions(btn), csrf=csrf,
                   hidden={"form": "lockdown", "guild": guild.id})
    return ui.card("Notmodus (Lockdown)", form, icon="bi-lock", tone="bad" if active else None,
                   desc="Manuell ein- und ausschalten – unabhängig von der Raid-Erkennung.")


def _render_history(ui, conf) -> str:
    hist = conf.get("history") or []
    if not hist:
        return ui.card("Verlauf", ui.empty("bi-clock-history", "Noch keine Aktionen protokolliert.",
                                           "Hier erscheinen Honeypot-, Spam- und Raid-Auslösungen."),
                       icon="bi-clock-history")
    rows = []
    for r in hist[:HISTORY_LIMIT]:
        rules = ", ".join(_RULE_LABEL.get(x, x) for x in (r.get("rules") or [])) or "—"
        chan = f"#{r['channel']}" if r.get("channel") else "—"
        pts = r.get("points")
        kind, tone = _KIND_LABEL.get(r.get("kind"), (r.get("kind"), "muted"))
        rows.append(ui.row(
            f"<span class='mono'>{_esc(_ago(r.get('ts', 0))).replace(' ', '&nbsp;')}</span>",
            ui.badge(kind or "—", tone),
            _esc(r.get("user") or "—"),
            _esc(rules),
            _esc(_ACTION_LABEL.get(r.get("action"), r.get("action"))),
            _esc(chan),
            f"><span class='mono'>{_esc('—' if pts is None else pts)}</span>",
        ))
    return ui.card(
        "Verlauf", ui.table(["Wann", "Auslöser", "Nutzer", "Regel(n)", "Aktion", "Kanal", ">Punkte"], rows,
                            search=True, search_placeholder="Nach Nutzer, Regel oder Kanal suchen …", id="gd-history"),
        icon="bi-clock-history", desc=f"Die letzten {HISTORY_LIMIT} Aktionen, neueste zuerst.",
    )


def _render_settings(ui, guild, conf, csrf) -> str:
    text_channels = [(c.id, f"#{c.name}") for c in guild.text_channels]
    roles = [
        (r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()
    ]
    save = ui.save_row("Einstellungen speichern")

    # ---- Honeypot
    honeypot = ui.card("Honeypot", _switches(
        ui.switch("hp_enabled", "Honeypot aktiv", conf.get("hp_enabled"),
                  desc="Wer im Honeypot-Kanal schreibt, wird sofort bestraft."),
    ) + ui.grid(
        ui.field("Honeypot-Kanal", ui.select("hp_channel", text_channels, conf.get("hp_channel"), none_label="— keiner —"),
                 help="Bestehenden Kanal markieren. Neuen anlegen: <code>[p]guardset honeypot create</code>"),
        ui.field("Aktion bei Auslösung", ui.select("hp_action", ACTIONS, conf.get("hp_action", "softban"))),
        ui.field("Nachrichten löschen", _num(ui, conf, "hp_delete_seconds", 86400, unit="Sek."),
                 help="Nur bei Bann/Softban: Nachrichten der letzten X Sekunden entfernen (0–604800, max. 7 Tage)."),
        ui.field("Timeout-Dauer", _num(ui, conf, "hp_timeout_minutes", 60, unit="Min."),
                 help="Nur wenn die Aktion „Timeout“ ist."),
    ), icon="bi-bug",
        desc="Ein Kanal, in dem kein Mensch schreiben soll – Spam-Bots posten dort trotzdem und verraten sich.")

    overrides = conf.get("messages") or {}
    text_labels = {"hp_warning": ("Warntext im Honeypot-Kanal",
                                  "Steht als Nachricht im Honeypot-Kanal. Beim Speichern wird die vorhandene Warnnachricht "
                                  "des Bots dort bearbeitet (fehlt sie, wird sie neu gepostet); ein Kanalthema mit dem "
                                  "alten Text wird mit angepasst. Per Befehl: <code>[p]guardset honeypot warning &lt;Text&gt;</code>.")}
    text_fields = []
    for key in OVERRIDABLE_KEYS:
        label, hint = text_labels.get(key, (key, None))
        text_fields.append(ui.field(label, ui.textarea(f"ovr_{key}", overrides.get(key, ""), rows=3,
                                                       placeholder=STRINGS["de"].get(key, "")), help=hint, wide=True))
    texts = ui.card("Eigene Texte", ui.grid(*text_fields, cols=1), icon="bi-chat-left-text",
                    desc="Leer lassen = Standardtext der gewählten Sprache (als grauer Platzhalter sichtbar).")

    # ---- Spamschutz
    spam_main = ui.card("Spamschutz", _switches(
        ui.switch("spam_enabled", "Spamschutz aktiv", conf.get("spam_enabled"),
                  desc="Hauptschalter – ohne ihn greift keine der Regeln unten."),
    ), icon="bi-shield-check",
        desc="Jede Regel, die anschlägt, gibt Punkte. Erreicht ein Mitglied eine Schwelle aus dem Reiter "
             "„Eskalation“, folgt die passende Maßnahme.")
    pts = "Punkte"
    rate = ui.card("Nachrichten-Rate", _switches(
        ui.switch("s_rate", "Regel aktiv", conf.get("s_rate", True), desc="Zu viele Nachrichten in kurzer Zeit."),
    ) + ui.grid(
        ui.field("Max. Nachrichten", _num(ui, conf, "s_rate_count", 6)),
        ui.field("im Zeitfenster", _num(ui, conf, "s_rate_seconds", 5, unit="Sek.")),
        ui.field(pts, _num(ui, conf, "pts_rate", 3, unit="Pkt.")),
        cols=3), icon="bi-speedometer")
    repeat = ui.card("Wiederholungen", _switches(
        ui.switch("s_repeat", "Regel aktiv", conf.get("s_repeat", True), desc="Dieselbe Nachricht mehrfach."),
        ui.switch("s_repeat_crosschannel", "Kanalübergreifend zählen", conf.get("s_repeat_crosschannel", True),
                  desc="Auch in verschiedenen Kanälen gepostet."),
    ) + ui.grid(
        ui.field("Gleiche Nachr. ab", _num(ui, conf, "s_repeat_count", 4)),
        ui.field("im Zeitfenster", _num(ui, conf, "s_repeat_seconds", 20, unit="Sek.")),
        ui.field(pts, _num(ui, conf, "pts_repeat", 3, unit="Pkt.")),
        cols=3), icon="bi-files")
    mentions = ui.card("Massen-Erwähnungen", _switches(
        ui.switch("s_mentions", "Regel aktiv", conf.get("s_mentions", True), desc="Viele @Erwähnungen in einer Nachricht."),
    ) + ui.grid(
        ui.field("Max. Erwähnungen je Nachricht", _num(ui, conf, "s_mentions_max", 5)),
        ui.field(pts, _num(ui, conf, "pts_mentions", 4, unit="Pkt.")),
    ), icon="bi-at")
    links = ui.card("Einladungen & Links", _switches(
        ui.switch("s_invites", "Einladungslinks erkennen", conf.get("s_invites", True), desc="discord.gg/… und Ähnliches."),
        ui.switch("s_links", "Alle externen Links erkennen", conf.get("s_links", False), desc="Streng – jeder Link zählt."),
    ) + ui.grid(
        ui.field("Punkte je Einladung", _num(ui, conf, "pts_invite", 5, unit="Pkt.")),
        ui.field("Punkte je Link", _num(ui, conf, "pts_link", 2, unit="Pkt.")),
    ), icon="bi-link-45deg")
    walls = ui.card("Anhang-, Emoji- & Zeilen-Walls", _switches(
        ui.switch("s_walls", "Regel aktiv", conf.get("s_walls", True), desc="Überlange oder überladene Nachrichten."),
    ) + ui.grid(
        ui.field("Max. Anhänge", _num(ui, conf, "s_walls_attachments", 6)),
        ui.field("Max. Custom-Emojis", _num(ui, conf, "s_walls_emojis", 12)),
        ui.field("Max. Zeilenumbrüche", _num(ui, conf, "s_walls_newlines", 12)),
        ui.field(pts, _num(ui, conf, "pts_wall", 2, unit="Pkt.")),
    ), icon="bi-bricks")
    newacc = ui.card("Neue Konten", _switches(
        ui.switch("s_newaccount", "Neue Konten strenger behandeln", conf.get("s_newaccount", True),
                  desc="Verstärkt andere Treffer: sehr junge Konten bekommen Zusatzpunkte."),
    ) + ui.grid(
        ui.field("Konto jünger als", _num(ui, conf, "s_newaccount_hours", 24, unit="Std.")),
        ui.field("Zusatzpunkte", _num(ui, conf, "pts_newaccount", 2, unit="Pkt.")),
    ), icon="bi-person-plus")
    spam = spam_main + ui.columns(rate, repeat, mentions, links, walls, newacc)

    # ---- Eskalation
    escalation = ui.card("Schwellen", ui.grid(
        ui.field("Verwarnen ab", _num(ui, conf, "warn_at", 3, unit="Pkt.")),
        ui.field("Timeout ab", _num(ui, conf, "timeout_at", 6, unit="Pkt.")),
        ui.field("Kick ab", _num(ui, conf, "kick_at", 9, unit="Pkt.")),
        ui.field("Bann ab", _num(ui, conf, "ban_at", 12, unit="Pkt.")),
        cols=4), icon="bi-bar-chart-steps",
        desc="Die Punkte eines Mitglieds werden zusammengezählt; die höchste erreichte Stufe wird ausgeführt.")
    escalation += ui.card("Punkte & Maßnahmen", ui.grid(
        ui.field("Punkte verfallen nach", _num(ui, conf, "decay_seconds", 60, unit="Sek."),
                 help="Nur Treffer innerhalb dieses Zeitfensters zählen zusammen."),
        ui.field("Timeout-Dauer (Spam)", _num(ui, conf, "spam_timeout_minutes", 10, unit="Min."),
                 help="Dauer des Timeouts, wenn die Stufe „Timeout“ erreicht wird."),
    ) + _switches(
        ui.switch("delete_violations", "Auslösende Nachricht löschen", conf.get("delete_violations", True),
                  desc="Die Nachricht, die eine Regel ausgelöst hat, wird entfernt."),
    ), icon="bi-hourglass-split")

    # ---- Raid / Notmodus
    raid = ui.card("Raid-Erkennung", _switches(
        ui.switch("raid_enabled", "Raid-Erkennung aktiv", conf.get("raid_enabled", True),
                  desc="Zu viele Beitritte in kurzer Zeit schalten den Notmodus automatisch ein."),
    ) + ui.grid(
        ui.field("Beitritte ab", _num(ui, conf, "raid_joins", 8)),
        ui.field("im Zeitfenster", _num(ui, conf, "raid_seconds", 20, unit="Sek.")),
    ), icon="bi-people")
    raid += ui.card("Verhalten im Notmodus", ui.grid(
        ui.field("Slowmode", _num(ui, conf, "lockdown_slowmode", 10, unit="Sek."),
                 help="Wird in allen Textkanälen gesetzt (0 = kein Slowmode)."),
        ui.field("Automatisch beenden nach", _num(ui, conf, "lockdown_auto_minutes", 10, unit="Min."),
                 help="0 = nur manuell beenden."),
        ui.field("Neue Beitritte", ui.select("lockdown_action_joins", JOIN_ACTIONS, conf.get("lockdown_action_joins", "none")),
                 help="Was mit Mitgliedern passiert, die während des Notmodus beitreten.", wide=True),
    ) + _switches(
        ui.switch("lockdown_pause_invites", "Einladungen pausieren", conf.get("lockdown_pause_invites", True),
                  desc="Falls von Discord unterstützt."),
    ), icon="bi-lock", desc="Manuell ein- und ausschalten kannst du den Notmodus im Reiter „Übersicht“.")

    # ---- Allgemein & Ausnahmen
    general = ui.card("Allgemein", ui.grid(
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf.get("language", "de")),
                 help="Sprache der Bot-Meldungen."),
        ui.field("Log-Kanal", ui.select("log_channel", text_channels, conf.get("log_channel"), none_label="— keiner —"),
                 help="Hier protokolliert Guard jede Aktion."),
    ) + _switches(
        ui.switch("ignore_bots", "Andere Bots ignorieren", conf.get("ignore_bots", True),
                  desc="Nachrichten anderer Bots lösen nichts aus."),
        ui.switch("use_modlog", "In Reds Modlog spiegeln", conf.get("use_modlog", True),
                  desc="Aktionen zusätzlich als Modlog-Fall eintragen."),
    ), icon="bi-gear")
    wl_users = " ".join(str(u) for u in (conf.get("whitelist_users") or []))
    exemptions = ui.card("Ausnahmen", ui.grid(
        ui.field("Rollen ausnehmen", ui.select("whitelist_roles", roles, conf.get("whitelist_roles") or [],
                                               multiple=True, placeholder="Rollen suchen …"),
                 help="Mitglieder mit diesen Rollen lösen nichts aus."),
        ui.field("Kanäle ausnehmen", ui.select("whitelist_channels", text_channels, conf.get("whitelist_channels") or [],
                                               multiple=True, placeholder="Kanäle suchen …"),
                 help="Gilt nur für den Spamschutz – der Honeypot bleibt aktiv."),
        ui.field("Nutzer ausnehmen", ui.text_input("whitelist_users", wl_users,
                                                   placeholder="z. B. 123456789012345678 987654321098765432"),
                 help="Nutzer-IDs, mit Leerzeichen getrennt.", wide=True),
    ), icon="bi-person-check",
        desc="Owner, Admins/„Server verwalten“, der Bot selbst und Reds Immunität (<code>[p]immune</code>) "
             "sind ohnehin immer ausgenommen.")

    # Ein Formular über alle Einstellungs-Reiter – ein Speichern sendet alles.
    return ui.form(
        "/cogs/guard",
        ui.tab("honeypot", "Honeypot", "bi-bug", honeypot + texts + save)
        + ui.tab("spamschutz", "Spamschutz", "bi-shield-check", spam + save)
        + ui.tab("eskalation", "Eskalation", "bi-bar-chart-steps", escalation + save)
        + ui.tab("raid", "Raid & Notmodus", "bi-lock", raid + save)
        + ui.tab("allgemein", "Allgemein & Ausnahmen", "bi-gear", general + exemptions + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _ago(ts: int) -> str:
    if not ts:
        return "—"
    secs = int(time.time() - ts)
    if secs < 60:
        return f"vor {secs}s"
    if secs < 3600:
        return f"vor {secs // 60}min"
    if secs < 86400:
        return f"vor {secs // 3600}h"
    return f"vor {secs // 86400}d"


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    # Server-Auswahl serverseitig gegen die sichtbaren Server prüfen.
    guilds = await _visible_guilds(cog, request)
    guild = None
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                guild = g
                break
    if guild is None:
        raise web.HTTPFound("/cogs/guard?err=" + quote("Server nicht gefunden"))

    gconf = cog.config.guild(guild)

    if form == "lockdown":
        state = data.get("state")
        if state == "on":
            await cog._start_lockdown(guild, reason_kind="manual")
            raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&ok=" + quote("Notmodus aktiviert"))
        if state == "off":
            await cog._end_lockdown(guild)
            raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&ok=" + quote("Notmodus beendet"))
        raise web.HTTPFound(f"/cogs/guard?guild={guild.id}")

    if form == "settings":
        # Effektiver Warntext vorher – ändert er sich (Text oder Sprache), wird die
        # bestehende Warnnachricht im Honeypot-Kanal nachgezogen.
        old_warning = await cog._text(guild, "hp_warning")
        # Booleans (Checkbox-Anwesenheit)
        for field in BOOL_FIELDS:
            await gconf.set_raw(field, value=(field in data))

        # Zahlen mit Grenzen
        for field, (lo, hi) in INT_FIELDS.items():
            raw = data.get(field)
            if raw is None:
                continue
            try:
                val = int(raw)
            except (TypeError, ValueError):
                continue
            await gconf.set_raw(field, value=max(lo, min(hi, val)))

        # Sprache
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)

        # Selects: Aktionen
        hp_action = (data.get("hp_action") or "softban").lower()
        if hp_action in {a for a, _ in ACTIONS}:
            await gconf.hp_action.set(hp_action)
        join_action = (data.get("lockdown_action_joins") or "none").lower()
        if join_action in {a for a, _ in JOIN_ACTIONS}:
            await gconf.lockdown_action_joins.set(join_action)

        # Kanäle (gegen echte Guild-Objekte prüfen)
        def _valid_channel(value):
            if value and str(value).isdigit():
                ch = guild.get_channel(int(value))
                if ch is not None:
                    return ch.id
            return None

        await gconf.log_channel.set(_valid_channel(data.get("log_channel")))
        await gconf.hp_channel.set(_valid_channel(data.get("hp_channel")))

        # Multiselect: Rollen / Kanäle
        valid_role_ids = {r.id for r in guild.roles}
        roles = [int(r) for r in data.getall("whitelist_roles", []) if str(r).isdigit() and int(r) in valid_role_ids]
        await gconf.whitelist_roles.set(roles)
        valid_chan_ids = {c.id for c in guild.channels}
        chans = [int(c) for c in data.getall("whitelist_channels", []) if str(c).isdigit() and int(c) in valid_chan_ids]
        await gconf.whitelist_channels.set(chans)

        # Nutzer-IDs (Freitext)
        users = []
        for token in (data.get("whitelist_users") or "").replace(",", " ").split():
            if token.isdigit():
                users.append(int(token))
        await gconf.whitelist_users.set(users)

        # Text-Overrides
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)

        if await gconf.hp_channel() and await cog._text(guild, "hp_warning") != old_warning:
            status, _channel = await cog.sync_hp_warning(guild, old_text=old_warning)
            if status in ("edited", "posted"):
                raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&ok=" + quote(
                    "Gespeichert – Warnnachricht im Honeypot-Kanal "
                    + ("aktualisiert" if status == "edited" else "neu gepostet")))
            reason = {
                "no_channel": "der Honeypot-Kanal existiert nicht mehr",
                "forbidden": "dem Bot fehlen dort Rechte (Nachrichten senden / Verlauf lesen)",
            }.get(status, "Discord hat die Änderung abgelehnt")
            raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&err=" + quote(
                f"Gespeichert, aber die Warnnachricht im Honeypot-Kanal wurde nicht aktualisiert: {reason}"))

        raise web.HTTPFound(f"/cogs/guard?guild={guild.id}&ok=" + quote("Gespeichert"))

    raise web.HTTPFound(f"/cogs/guard?guild={guild.id}")
