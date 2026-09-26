"""WebCore-Dashboard für den Autorole-Cog.

Aufgaben:
* GET  -> Seite rendern (Übersicht, Beitrittsrollen, Einstellungen, Rollen-Panels)
* GET ?panel=<id> -> Editor für ein einzelnes Rollen-Panel
* POST -> Formular speichern bzw. Aktion ausführen, danach Redirect (Post/Redirect/Get)

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``) – kein
eigenes CSS. Die Oberfläche ist – wie im übrigen Repo – durchgängig deutsch.
"""

from __future__ import annotations

import html
from urllib.parse import quote_plus

from aiohttp import web

from .panels import MAX_ROLES, MODES, STYLES, new_panel
from .strings import LANGUAGES

_REASON_TEXT = {
    "reason_default": "@everyone",
    "reason_managed": "von Discord verwaltet",
    "reason_too_high": "steht über meiner höchsten Rolle",
}
_BTN_COLORS = (("secondary", "Grau"), ("primary", "Blau"), ("success", "Grün"), ("danger", "Rot"))
_SCREENING = (
    ("auto", "Automatisch – Verifizierung erkennen"),
    ("on", "Erst nach der Regel-Verifizierung"),
    ("off", "Sofort beim Beitritt"),
)


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _ids(values) -> list[int]:
    out = []
    for v in values:
        if v and str(v).isdigit():
            out.append(int(v))
    return out


def _color(role):
    return f"#{role.color.value:06x}" if getattr(role, "color", None) and role.color.value else None


def _role_items(cog, guild, *, only_assignable=False, exclude=()):
    """Rollen (ohne @everyone), höchste zuerst: [(id, label, farbe)].

    Nicht zuweisbare Rollen werden mit ⚠ markiert (bzw. mit ``only_assignable`` weggelassen).
    """
    out = []
    for r in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if r.is_default() or r.id in exclude:
            continue
        bad = cog._assignable_reason(guild, r) is not None
        if bad and only_assignable:
            continue
        out.append((r.id, ("⚠ " if bad else "") + r.name, _color(r)))
    return out


# --------------------------------------------------------------------------- #
#  Einstiegspunkt
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


def _selected_guild(guilds, request):
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
    guild = _selected_guild(guilds, request)
    if guild is None:
        return {"title": "Autorole", "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")

    # Einzelnes Panel bearbeiten? (eigene, fokussierte Ansicht)
    panels = conf.get("panels", {})
    pid = request.query.get("panel")
    if pid and pid in panels:
        return {
            "title": f"Autorole · {panels[pid].get('name', 'Panel')}",
            "content": _render_panel_editor(ui, cog, guild, panels[pid], csrf),
        }

    # Globaler Server-Wechsler von WebCore aktiv -> eigenes Dropdown ausblenden.
    guild_picker = ""
    if not request.get("wc_switcher"):
        guild_picker = ui.card(body=ui.form(
            "/cogs/autorole",
            ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
            csrf="", method="get",
        ))

    head = ui.hero(
        "bi-person-plus", "",
        "Vergibt neuen Mitgliedern und Bots automatisch Rollen, gibt <b>Sticky-Rollen</b> beim erneuten Beitritt "
        "zurück und stellt <b>Rollen-Panels</b> bereit, über die sich Mitglieder selbst Rollen nehmen.",
    ) + ui.stats([
        ("Status", "Aktiv" if conf["enabled"] else "Aus", "bi-power", None, "ok" if conf["enabled"] else "warn"),
        ("Mitglieder-Rollen", len(conf["join_roles"]), "bi-person-check", None, None),
        ("Bot-Rollen", len(conf["bot_roles"]), "bi-robot", None, None),
        ("Sticky-Rollen", len(conf["sticky_roles"]), "bi-pin-angle", None, None),
        ("Rollen-Panels", len(panels), "bi-ui-checks-grid", None, None),
    ])

    body = (
        ui.tab("uebersicht", "Übersicht", "bi-speedometer2", _render_overview(ui, cog, guild, conf, csrf))
        + _render_settings(ui, cog, guild, conf, csrf)
        + ui.tab("panels", "Rollen-Panels", "bi-ui-checks-grid", _render_panels(ui, guild, conf, csrf),
                 count=len(panels))
    )
    return {"title": "Autorole", "content": guild_picker + head + body}


def _setup_checks(cog, guild, conf) -> list[tuple]:
    """Einrichtungs-Prüfung: [(tone, text[, reiter])] – mit Reiter gibt es einen Sprung-Button."""
    out = []
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        out.append(("bad", "Mir fehlt die Berechtigung <b>Rollen verwalten</b> – ohne sie kann ich keine Rollen vergeben."))

    bad, seen = [], set()
    for rid in list(conf["join_roles"]) + list(conf["bot_roles"]) + list(conf["sticky_roles"]):
        if rid in seen:
            continue
        seen.add(rid)
        r = guild.get_role(int(rid))
        if r is None:
            continue
        reason = cog._assignable_reason(guild, r)
        if reason is not None:
            bad.append(f"{_esc(r.name)} ({_REASON_TEXT.get(reason, _esc(reason))})")
    if bad:
        out.append((
            "warn",
            "Diese eingetragenen Rollen kann ich aktuell <b>nicht</b> vergeben (in der Auswahl mit ⚠ markiert): "
            + ", ".join(bad)
            + ". Verschiebe meine Bot-Rolle in den Servereinstellungen weiter nach oben oder wähle andere Rollen.",
            "rollen",
        ))
    if not conf["enabled"]:
        out.append(("info", "Die automatische Rollenvergabe ist <b>aus</b> – aktiviere sie im Reiter „Einstellungen“.",
                    "einstellungen"))
    if not conf["join_roles"]:
        out.append(("info", "Noch keine <b>Mitglieder-Rollen</b> – trage sie im Reiter „Beitrittsrollen“ ein.",
                    "rollen"))
    return out


def _render_overview(ui, cog, guild, conf, csrf) -> str:
    checks = _setup_checks(cog, guild, conf)
    if checks:
        check_html = "".join(_check_callout(ui, c) for c in checks)
    else:
        check_html = ui.callout("Alles eingerichtet – neue Mitglieder erhalten ihre Rollen automatisch.", tone="ok")
    screening = dict(_SCREENING).get(conf["screening"], conf["screening"])
    gate = "aktiv" if cog.gate_enabled(guild) else "nicht aktiv"
    setup = ui.card(
        "Einrichtung", check_html, icon="bi-clipboard-check",
        desc=f"Zeitpunkt: <b>{_esc(screening)}</b> · Regel-Verifizierung auf dem Server: <b>{gate}</b>",
    )
    return setup + _render_apply(ui, guild, conf, csrf, cog.apply_status.get(guild.id), cog.apply_running(guild.id))


_TAB_LABEL = {"rollen": "Zu den Beitrittsrollen", "einstellungen": "Zu den Einstellungen"}


def _check_callout(ui, check) -> str:
    tone, text = check[0], check[1]
    tab = check[2] if len(check) > 2 else None
    jump = f"<div class='wc-callout-act'>{ui.goto(_TAB_LABEL.get(tab, 'Öffnen'), tab)}</div>" if tab else ""
    return ui.callout(text + jump, tone=tone)


def _render_apply(ui, guild, conf, csrf, status=None, running=False) -> str:
    status_html = f"<div class='wc-help'>Letzter Lauf: {_esc(status)}</div>" if status else ""
    # Fehlt noch etwas, konkret sagen WAS – statt eines ausgegrauten Buttons (sieht sonst nach
    # „keine Berechtigung“ aus).
    missing = []
    if not conf["join_roles"]:
        missing.append(("Es sind noch keine <b>Mitglieder-Rollen</b> eingetragen – ohne sie gibt es nichts zu vergeben.",
                        ui.goto("Mitglieder-Rollen eintragen", "rollen", kind="accent")))
    if not conf["enabled"]:
        missing.append(("Die automatische Rollenvergabe ist <b>aus</b>.",
                        ui.goto("Zu den Einstellungen", "einstellungen", kind="accent")))
    if missing:
        body = "".join(ui.callout(f"{text}<div class='wc-callout-act'>{btn}</div>", tone="info")
                       for text, btn in missing) + status_html
    elif running:
        body = ui.callout("Läuft gerade – die Rollen werden im Hintergrund vergeben.", tone="info") + status_html
    else:
        body = ui.form(
            "/cogs/autorole", ui.actions(ui.button("Jetzt anwenden", icon="bi-people"), status_html),
            csrf=csrf, hidden={"form": "applyall", "guild": guild.id},
            confirm="Mitglieder-Rollen an alle bestehenden Mitglieder vergeben?",
        )
    return ui.card(
        "Auf bestehende Mitglieder anwenden",
        body,
        icon="bi-arrow-repeat",
        desc="Vergibt die eingetragenen <b>Mitglieder-Rollen</b> nachträglich an alle Menschen auf dem Server, "
             "die sie noch nicht haben. Auf großen Servern kann das einen Moment dauern.",
    )


def _render_settings(ui, cog, guild, conf, csrf) -> str:
    """Ein Formular über zwei Reiter (Beitrittsrollen + Einstellungen) – beide speichern alles."""
    help_ms = "Mit ⚠ markierte Rollen kann ich aktuell nicht vergeben."
    roles = ui.card("Beim Beitritt vergeben", ui.grid(
        ui.field("Rollen für neue Mitglieder",
                 ui.select("join_roles", _role_items(cog, guild), conf["join_roles"], multiple=True,
                           placeholder="Rollen suchen …"),
                 help="Bekommt jeder Mensch, der dem Server beitritt. " + help_ms, wide=True),
        ui.field("Rollen für neue Bots",
                 ui.select("bot_roles", _role_items(cog, guild), conf["bot_roles"], multiple=True,
                           placeholder="Rollen suchen …"),
                 help="Werden vergeben, sobald ein Bot dem Server hinzugefügt wird (ohne Verifizierung).", wide=True),
    ), icon="bi-person-plus", desc="Welche Rollen neue Mitglieder bzw. Bots automatisch erhalten.")

    sticky = ui.card("Sticky-Rollen", ui.grid(
        ui.field("Sticky-Rollen",
                 ui.select("sticky_roles", _role_items(cog, guild), conf["sticky_roles"], multiple=True,
                           placeholder="Rollen suchen …"),
                 help="<b>Keine</b> Mute-/Straf-Rolle hier eintragen.", wide=True),
    ), icon="bi-pin-angle",
        desc="Merkt sich der Bot beim Verlassen und vergibt sie beim erneuten Beitritt wieder.")

    general = ui.card("Allgemein", ui.switch(
        "enabled", "Automatische Rollenvergabe aktiv", conf["enabled"],
        desc="Aus = beim Beitritt werden keine Rollen vergeben (Rollen-Panels funktionieren weiter).",
    ) + "<div class='wc-divider'></div>" + ui.grid(
        ui.field("Sprache der Bot-Antworten", ui.select("language", list(LANGUAGES.items()), conf["language"])),
        ui.field("Vergabe-Zeitpunkt", ui.select("screening", _SCREENING, conf["screening"]),
                 help="„Erst nach der Regel-Verifizierung“ wirkt nur, wenn dieser Server Discords Screening nutzt."),
    ), icon="bi-gear")

    portal = ui.card("Mitglieder-Bereich", ui.switch(
        "member_page", "Im Mitglieder-Bereich anzeigen", conf.get("member_page", True),
        desc="Mitglieder können unter „Mein Bereich → Rollen“ dieselben Rollen wie über die geposteten "
             "Rollen-Panels wählen (gleiche Regeln wie die Buttons, nur Panels aus Kanälen, die sie sehen).",
    ) + ui.callout(
        "Den Mitglieder-Bereich selbst schaltet der Bot-Owner pro Server unter <b>Verwaltung → Zugriff &amp; Rollen</b> "
        "ein (oder mit <code>[p]webcore portal on</code>). Dieser Schalter blendet nur die Rollen-Seite aus.",
    ), icon="bi-person-badge", desc="Rollen im Web wählen – für Mitglieder ohne Team-Rechte.")

    protect = ui.card("Zeitpunkt & Schutz", ui.grid(
        ui.field("Verzögerung", ui.number("delay", int(conf["delay"]), min=0, max=3600, unit="Sekunden"),
                 help="Wartezeit nach dem Beitritt vor der Vergabe (0 = sofort)."),
        ui.field("Mindest-Kontoalter", ui.number("min_account_age", int(conf["min_account_age"]), min=0, unit="Stunden"),
                 help="Jüngere Konten erhalten keine Auto-Rollen (0 = aus). Schutz gegen Wegwerf-/Raid-Accounts."),
    ), icon="bi-shield-check")

    save = ui.save_row("Einstellungen speichern")
    return ui.form(
        "/cogs/autorole",
        ui.tab("rollen", "Beitrittsrollen", "bi-person-plus", roles + sticky + save,
               count=len(conf["join_roles"]) + len(conf["bot_roles"]))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", general + protect + portal + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


# --------------------------------------------------------------------------- #
#  Rollen-Panels (Übersicht + Editor)
# --------------------------------------------------------------------------- #
def _post_form(ui, guild, pid, csrf, label, *, small=False, kind="accent") -> str:
    return ui.form(
        "/cogs/autorole", ui.button(label, icon="bi-send", kind=kind, small=small),
        csrf=csrf, hidden={"form": "panel_post", "guild": guild.id, "panel": pid},
    )


def _render_panels(ui, guild, conf, csrf) -> str:
    panels = conf.get("panels", {})
    rows = []
    for pid, p in panels.items():
        ch = guild.get_channel(int(p["channel_id"])) if p.get("channel_id") else None
        style = "Buttons" if p.get("style") == "buttons" else "Dropdown"
        mode = "Toggle" if p.get("mode") == "toggle" else "Nur vergeben"
        if p.get("unique"):
            mode += " · nur eine"
        status = ui.badge("gepostet", "ok") if p.get("message_id") else ui.badge("nicht gepostet", "warn")
        edit = ui.button("Bearbeiten", icon="bi-pencil", kind="ghost", small=True,
                         href=f"/cogs/autorole?guild={guild.id}&panel={quote_plus(str(pid))}")
        post = _post_form(ui, guild, pid, csrf, "Posten", small=True, kind="ghost")
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(p['name'])}</div><div class='wc-cell-sub mono'>{_esc(pid)}</div>",
            _esc("#" + ch.name) if ch is not None else "<span class='wc-muted'>—</span>",
            style, _esc(mode), f"<span class='mono'>{len(p.get('roles', []))}</span>", status,
            f"><div class='wc-row-actions'>{edit}{post}</div>",
        ))
    if rows:
        listing = ui.table(["Panel", "Kanal", "Darstellung", "Verhalten", "Rollen", "Status", ">"], rows,
                           search=len(rows) > 5, search_placeholder="Panel suchen …", id="ar-panels")
    else:
        listing = ui.empty("bi-ui-checks-grid", "Noch keine Rollen-Panels.", "Lege unten dein erstes Panel an.")
    table = ui.card(
        "Deine Rollen-Panels", listing, icon="bi-ui-checks-grid",
        desc="Eine gepostete Nachricht mit Buttons oder einem Dropdown, über die sich Mitglieder selbst Rollen "
             "geben oder nehmen. Die Buttons funktionieren auch nach einem Neustart weiter.",
    )
    create = ui.card("Neues Panel", ui.form(
        "/cogs/autorole",
        ui.grid(ui.field("Name", ui.text_input("name", placeholder="z. B. Farb-Rollen",
                                               attrs={"maxlength": 100, "required": True}),
                         help="Interner Name (erscheint nicht in der Nachricht). Kanal, Aussehen und Rollen legst du danach fest.",
                         wide=True))
        + ui.actions(ui.button("Panel erstellen", icon="bi-plus-lg")),
        csrf=csrf, hidden={"form": "panel_create", "guild": guild.id},
    ), icon="bi-plus-square")
    return table + create


def _render_panel_editor(ui, cog, guild, panel, csrf) -> str:
    pid = panel["id"]
    back = ui.button("Zurück zu den Panels", icon="bi-arrow-left", kind="ghost",
                     href=f"/cogs/autorole?guild={guild.id}#panels")
    head = ui.hero("bi-ui-checks-grid", panel.get("name") or "Panel",
                   "Einstellungen und Rollen dieses Panels. Ist es gepostet, werden Änderungen automatisch "
                   "in die Nachricht übernommen.")

    # Nachricht: Status + Posten/Löschen – über den Reitern, damit immer sichtbar.
    posted = bool(panel.get("message_id"))
    delete = ui.form(
        "/cogs/autorole", ui.button("Panel löschen", icon="bi-trash", kind="danger"),
        csrf=csrf, hidden={"form": "panel_delete", "guild": guild.id, "panel": pid},
        confirm="Panel wirklich löschen? Die gepostete Nachricht wird ebenfalls entfernt.",
    )
    message = ui.card(
        "Nachricht im Kanal",
        ui.actions(_post_form(ui, guild, pid, csrf, "Nachricht aktualisieren" if posted else "Jetzt posten"), delete),
        icon="bi-send", tone="ok" if posted else "warn",
        desc="Gepostet – Änderungen an Eigenschaften und Rollen werden automatisch in die Nachricht übernommen."
        if posted else
        "Noch nicht gepostet. Wähle einen Kanal, speichere die Eigenschaften und klicke dann „Jetzt posten“.",
    )

    props = ui.form(
        "/cogs/autorole",
        ui.card("Grunddaten", ui.grid(
            ui.field("Name", ui.text_input("name", panel.get("name"), attrs={"maxlength": 100}),
                     help="Interner Name – erscheint nicht in der Nachricht."),
            ui.field("Kanal", ui.select("channel_id", [(c.id, f"#{c.name}") for c in sorted(
                getattr(guild, "text_channels", []), key=lambda c: getattr(c, "position", 0))],
                panel.get("channel_id"), none_label="— Kanal wählen —"),
                help="Hier wird das Panel gepostet."),
            ui.field("Darstellung", ui.select("style", [("buttons", "Buttons"), ("select", "Dropdown (Select-Menü)")],
                                               panel.get("style"))),
            ui.field("Klick-Verhalten", ui.select("mode", [("toggle", "Toggle – Klick gibt/entfernt"),
                                                            ("add", "Nur vergeben (kein Entfernen)")],
                                                   panel.get("mode"))),
        ) + "<div class='wc-switches'>" + ui.switch(
            "unique", "Nur eine Rolle gleichzeitig", panel.get("unique"),
            desc="Wählt jemand eine neue Rolle, wird die bisherige aus diesem Panel entfernt (z. B. Farb-Rollen).",
        ) + "</div>", icon="bi-sliders")
        + ui.card("Aussehen der Nachricht", ui.switch(
            "use_embed", "Als Embed posten", panel.get("use_embed"),
            desc="Mit Titel und farbigem Rand. Aus = einfache Textnachricht.",
        ) + "<div class='wc-divider'></div>" + ui.grid(
            ui.field("Titel", ui.text_input("title", panel.get("title"), attrs={"maxlength": 256})),
            ui.field("Embed-Farbe", ui.text_input("color", panel.get("color"), placeholder="#3ddc97",
                                                  attrs={"maxlength": 7}),
                     help="Hex-Wert, z. B. <code>#3ddc97</code>. Leer = Standardfarbe."),
            ui.field("Text", ui.textarea("text", panel.get("text"), rows=3), wide=True),
        ), icon="bi-card-heading")
        + ui.save_row("Eigenschaften speichern"),
        csrf=csrf, hidden={"form": "panel_save", "guild": guild.id, "panel": pid}, savebar=True,
    )

    roles = panel.get("roles", [])
    return (
        f"<div class='wc-toolbar'>{back}</div>" + head + message
        + ui.tab("eigenschaften", "Eigenschaften", "bi-sliders", props)
        + ui.tab("rollen", "Rollen", "bi-person-badge", _render_panel_roles(ui, cog, guild, panel, csrf),
                 count=len(roles))
    )


def _render_panel_roles(ui, cog, guild, panel, csrf) -> str:
    """Je Rolle eine Karte (Anzeige bearbeiten / entfernen) plus „Rolle hinzufügen“."""
    pid = panel["id"]
    blocks = []
    for r in panel.get("roles", []):
        role = guild.get_role(int(r["role_id"]))
        hidden = {"guild": guild.id, "panel": pid, "role_id": r["role_id"]}
        if role is None:
            title, tone, desc = f"Unbekannte Rolle ({r['role_id']})", "bad", "Die Rolle existiert nicht mehr – entferne sie."
        elif cog._assignable_reason(guild, role) is not None:
            title, tone, desc = role.name, "warn", ui.badge("⚠ kann ich aktuell nicht vergeben", "warn")
        else:
            title, tone, desc = role.name, None, None
        remove = ui.form(
            "/cogs/autorole",
            ui.button("Entfernen", icon="bi-x-lg", kind="danger", small=True),
            csrf=csrf, hidden={"form": "panel_role_remove", **hidden},
            confirm="Rolle aus dem Panel entfernen?",
        )
        update = ui.form(
            "/cogs/autorole",
            ui.grid(
                ui.field("Label", ui.text_input("label", r.get("label"), placeholder="Label", attrs={"maxlength": 80})),
                ui.field("Emoji", ui.text_input("emoji", r.get("emoji"), placeholder="🎮 oder <:name:id>",
                                                attrs={"maxlength": 64})),
                ui.field("Button-Farbe", ui.select("style", _BTN_COLORS, r.get("style"))),
                ui.field("Beschreibung", ui.text_input("description", r.get("description"),
                                                       placeholder="nur im Dropdown sichtbar",
                                                       attrs={"maxlength": 100})),
                cols=4,
            ) + ui.actions(ui.button("Speichern", icon="bi-check2", small=True)),
            csrf=csrf, hidden={"form": "panel_role_update", **hidden}, savebar=True,
        )
        blocks.append(ui.card(title, update, icon="bi-tag", tone=tone, desc=desc, actions=remove))

    if not blocks:
        blocks.append(ui.card(body=ui.empty("bi-person-badge", "Noch keine Rollen in diesem Panel.",
                                            "Füge unten die erste Rolle hinzu.")))

    existing_ids = {int(r["role_id"]) for r in panel.get("roles", [])}
    add = ui.card("Rolle hinzufügen", ui.form(
        "/cogs/autorole",
        ui.grid(
            ui.field("Rolle", ui.select("role_id", _role_items(cog, guild, only_assignable=True, exclude=existing_ids),
                                        none_label="— Rolle wählen —"),
                     help="Nur Rollen, die ich vergeben kann."),
            ui.field("Label (optional)", ui.text_input("label", placeholder="Standard: Rollenname",
                                                       attrs={"maxlength": 80})),
            ui.field("Emoji (optional)", ui.text_input("emoji", placeholder="🎮 oder <:name:id>",
                                                       attrs={"maxlength": 64})),
            ui.field("Button-Farbe", ui.select("style", _BTN_COLORS, "secondary")),
        ) + ui.actions(ui.button("Rolle hinzufügen", icon="bi-plus-lg")),
        csrf=csrf, hidden={"form": "panel_role_add", "guild": guild.id, "panel": pid},
    ), icon="bi-plus-square", desc=f"Max. {MAX_ROLES} Rollen pro Panel.")
    return "".join(blocks) + add


# --------------------------------------------------------------------------- #
#  Speichern / Aktion (POST)
# --------------------------------------------------------------------------- #
def _panel_redirect(guild_id, pid=None, ok=""):
    url = f"/cogs/autorole?guild={guild_id}"
    if pid:
        url += f"&panel={quote_plus(str(pid))}"
    if ok:
        url += f"&ok={quote_plus(ok)}"
    return web.HTTPFound(url)


_POST_MSG = {
    "panel_posted": "Panel gepostet bzw. aktualisiert",
    "panel_posted_noemoji": "Panel gepostet – Discord hat ein Emoji abgelehnt, daher ohne Emojis. Bitte Emojis prüfen",
    "panel_post_no_channel": "Kein gültiger Kanal gesetzt",
    "panel_post_no_roles": "Das Panel hat noch keine Rollen",
    "panel_post_no_send": "Mir fehlen Senderechte im Zielkanal",
    "panel_post_failed": "Posten fehlgeschlagen",
}


async def _may_grant(request, guild, role_id) -> bool:
    """WebCore-Prüfung, ob der eingeloggte User diese Rolle vergeben lassen darf."""
    webcore = request.app.get("webcore")
    if webcore is None or not hasattr(webcore, "can_grant_role"):
        return True
    return await webcore.can_grant_role(request, guild, guild.get_role(int(role_id)))


async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guilds = await _visible_guilds(cog, request)
    guild = None
    if gid and gid.isdigit():
        for g in guilds:
            if g.id == int(gid):
                guild = g
                break
    if guild is None:
        raise web.HTTPFound("/cogs/autorole?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        current = await gconf.all()
        blocked = 0

        async def _allowed(key):
            # Neu hinzugefügte Rollen nur, wenn der User sie vergeben darf (WebCore-Rollenrechte);
            # bereits eingetragene bleiben unverändert, Entfernen ist immer erlaubt.
            nonlocal blocked
            keep = []
            before = {int(r) for r in (current.get(key) or [])}
            for rid in _ids(data.getall(key, [])):
                if rid in before or await _may_grant(request, guild, rid):
                    keep.append(rid)
                else:
                    blocked += 1
            return keep

        lang = data.get("language") or "de"
        await gconf.language.set(lang if lang in LANGUAGES else "de")
        scr = data.get("screening") or "auto"
        await gconf.screening.set(scr if scr in ("auto", "on", "off") else "auto")
        await gconf.enabled.set("enabled" in data)
        await gconf.member_page.set("member_page" in data)
        try:
            delay = int(data.get("delay", 0))
        except (TypeError, ValueError):
            delay = 0
        await gconf.delay.set(max(0, min(3600, delay)))
        try:
            age = int(data.get("min_account_age", 0))
        except (TypeError, ValueError):
            age = 0
        await gconf.min_account_age.set(max(0, age))
        await gconf.join_roles.set(await _allowed("join_roles"))
        await gconf.bot_roles.set(await _allowed("bot_roles"))
        await gconf.sticky_roles.set(await _allowed("sticky_roles"))
        if blocked:
            raise web.HTTPFound(
                f"/cogs/autorole?guild={guild.id}&ok="
                + quote_plus(f"Gespeichert – {blocked} Rolle(n) nicht übernommen: über deiner Rolle oder mit Moderationsrechten")
            )
        raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}&ok=Einstellungen+gespeichert")

    if form == "applyall":
        # Im Hintergrund: auf großen Servern dauert das Minuten (Rate-Limits) – der
        # Request würde sonst hängen/timeouten und ein zweiter Klick liefe parallel.
        if cog.start_apply_job(guild) is None:
            raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}&ok=" + quote_plus("Läuft bereits – bitte warten"))
        raise web.HTTPFound(
            f"/cogs/autorole?guild={guild.id}&ok="
            + quote_plus("Anwendung gestartet – Ergebnis erscheint unten, Seite ggf. neu laden")
        )

    # ---- Rollen-Panels ----
    if form == "panel_create":
        name = (data.get("name") or "").strip()[:100] or "Panel"
        panel = new_panel(name)
        async with gconf.panels() as panels:
            panels[panel["id"]] = panel
        raise _panel_redirect(guild.id, panel["id"], "Panel erstellt")

    if form == "panel_save":
        pid = data.get("panel")
        panels = await gconf.panels()
        if not pid or pid not in panels:
            raise _panel_redirect(guild.id, ok="Panel nicht gefunden")
        style = data.get("style")
        mode = data.get("mode")
        ch = data.get("channel_id")
        moved = None
        async with gconf.panels() as panels:
            p = panels[pid]
            p["name"] = (data.get("name") or p["name"]).strip()[:100] or "Panel"
            new_ch = int(ch) if ch and ch.isdigit() else None
            if p.get("message_id") and p.get("channel_id") and p.get("channel_id") != new_ch:
                # Kanal gewechselt: alte Nachricht entfernen, sonst bliebe ein zweites,
                # weiter funktionierendes Panel im alten Kanal stehen.
                moved = {"channel_id": p["channel_id"], "message_id": p["message_id"]}
                p["message_id"] = None
            p["channel_id"] = new_ch
            p["style"] = style if style in STYLES else "buttons"
            p["mode"] = mode if mode in MODES else "toggle"
            p["unique"] = "unique" in data
            p["use_embed"] = "use_embed" in data
            p["title"] = (data.get("title") or "")[:256]
            p["color"] = (data.get("color") or "").strip()[:7]
            p["text"] = (data.get("text") or "")[:2000]
        if moved:
            await cog._panel_delete_message(guild, moved)
            if new_ch:
                ok, key = await cog._panel_post(guild, await cog._get_panel(guild, pid))
                if not ok:
                    raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}&panel={quote_plus(str(pid))}&err="
                                        + quote_plus("Gespeichert, alte Nachricht entfernt – " + _POST_MSG.get(key, "Posten fehlgeschlagen")))
        else:
            await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid, "Eigenschaften gespeichert")

    if form == "panel_role_add":
        pid = data.get("panel")
        rid = data.get("role_id")
        panels = await gconf.panels()
        if not pid or pid not in panels:
            raise _panel_redirect(guild.id, ok="Panel nicht gefunden")
        role = guild.get_role(int(rid)) if rid and rid.isdigit() else None
        if role is None:
            raise _panel_redirect(guild.id, pid, "Rolle nicht gefunden")
        if cog._assignable_reason(guild, role) is not None:
            raise _panel_redirect(guild.id, pid, "Diese Rolle kann ich nicht vergeben")
        if not await _may_grant(request, guild, role.id):
            raise _panel_redirect(guild.id, pid, "Diese Rolle darfst du nicht vergeben (über deiner Rolle oder mit Moderationsrechten)")
        existing = panels[pid].get("roles", [])
        if any(int(r["role_id"]) == role.id for r in existing):
            raise _panel_redirect(guild.id, pid, "Rolle ist bereits im Panel")
        if len(existing) >= MAX_ROLES:
            raise _panel_redirect(guild.id, pid, f"Panel voll (max. {MAX_ROLES})")
        label = (data.get("label") or role.name).strip()[:80] or role.name[:80]
        emoji = (data.get("emoji") or "").strip()[:64]
        bstyle = data.get("style")
        bstyle = bstyle if bstyle in ("primary", "secondary", "success", "danger") else "secondary"
        async with gconf.panels() as panels:
            panels[pid]["roles"].append(
                {"role_id": role.id, "label": label, "emoji": emoji, "style": bstyle, "description": ""}
            )
        await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid, "Rolle hinzugefügt")

    if form == "panel_role_update":
        pid = data.get("panel")
        rid = data.get("role_id")
        panels = await gconf.panels()
        if not pid or pid not in panels or not (rid and rid.isdigit()):
            raise _panel_redirect(guild.id, pid or None, "Nicht gefunden")
        bstyle = data.get("style")
        bstyle = bstyle if bstyle in ("primary", "secondary", "success", "danger") else "secondary"
        async with gconf.panels() as panels:
            for r in panels[pid]["roles"]:
                if int(r["role_id"]) == int(rid):
                    r["label"] = (data.get("label") or "").strip()[:80]
                    r["emoji"] = (data.get("emoji") or "").strip()[:64]
                    r["style"] = bstyle
                    r["description"] = (data.get("description") or "").strip()[:100]
                    break
        await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid, "Rolle aktualisiert")

    if form == "panel_role_remove":
        pid = data.get("panel")
        rid = data.get("role_id")
        panels = await gconf.panels()
        if pid and pid in panels and rid and rid.isdigit():
            async with gconf.panels() as panels:
                panels[pid]["roles"] = [
                    r for r in panels[pid]["roles"] if int(r["role_id"]) != int(rid)
                ]
            await cog._panel_refresh(guild, pid)
        raise _panel_redirect(guild.id, pid or None, "Rolle entfernt")

    if form == "panel_post":
        pid = data.get("panel")
        panel = await cog._get_panel(guild, pid) if pid else None
        if panel is None:
            raise _panel_redirect(guild.id, ok="Panel nicht gefunden")
        ok, key = await cog._panel_post(guild, panel)
        if not ok:
            raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}&panel={quote_plus(str(pid))}&err="
                                + quote_plus(_POST_MSG.get(key, "Posten fehlgeschlagen")))
        raise _panel_redirect(guild.id, pid, _POST_MSG.get(key, "OK"))

    if form == "panel_delete":
        pid = data.get("panel")
        panel = await cog._get_panel(guild, pid) if pid else None
        if panel is not None:
            await cog._panel_delete_message(guild, panel)
            async with gconf.panels() as panels:
                panels.pop(pid, None)
        raise _panel_redirect(guild.id, ok="Panel gelöscht")

    raise web.HTTPFound(f"/cogs/autorole?guild={guild.id}")
