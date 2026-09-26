"""„Mein Bereich → Rollen“: Rollen aus den Rollen-Panels selbst wählen (für normale Mitglieder).

* GET  -> alle geposteten Rollen-Panels, deren Kanal das Mitglied in Discord sehen kann – als Karten
          mit denselben Bedienelementen wie in Discord (Buttons bzw. Auswahl).
* POST form=btn -> wie ein Klick auf einen Panel-Button    (Feld ``role``)
* POST form=sel -> wie eine Auswahl im Panel-Dropdown      (Felder ``roles``)

Die eigentliche Arbeit (Bot-Rechte, Hierarchie, Modus/„nur eine“, Vergeben/Entfernen) macht
``Autorole.panel_interact`` – dieselbe Funktion wie beim Discord-Button. Hier wird zusätzlich
alles abgelehnt, was es in Discord nicht geben kann: fremde/ungepostete/unsichtbare Panels,
Rollen-IDs, die nicht im Panel stehen, mehrere Rollen bei „nur eine“, falsche Bedienart.
Die Panel-Nachricht zeigt keine Zähler, muss also nicht aktualisiert werden.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from .strings import t

MODE_HINTS = {
    # (mode, unique) -> Erklärung für Mitglieder
    ("toggle", False): "Tippe eine Rolle an, um sie zu bekommen – erneutes Antippen gibt sie wieder ab.",
    ("toggle", True): "Aus dieser Gruppe kannst du nur <b>eine</b> Rolle haben: eine andere wählen tauscht sie aus, "
                      "erneutes Antippen gibt sie ab.",
    ("add", False): "Rollen werden hier nur <b>vergeben</b> – abgeben ist über dieses Panel nicht möglich.",
    ("add", True): "Aus dieser Gruppe kannst du nur <b>eine</b> Rolle haben: eine andere wählen tauscht sie aus.",
}
SELECT_HINTS = {
    ("toggle", False): "Deine Auswahl ist dein neuer Stand in dieser Gruppe – abgewählte Rollen werden entfernt.",
    ("toggle", True): "Nur <b>eine</b> Rolle möglich. „Keine“ gibt deine Rolle aus dieser Gruppe ab.",
    ("add", False): "Angehakte Rollen werden vergeben – abwählen entfernt hier keine Rollen.",
    ("add", True): "Nur <b>eine</b> Rolle möglich. „Keine“ gibt deine Rolle aus dieser Gruppe ab.",
}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _plain(text: str) -> str:
    """Discord-Markdown aus Bot-Antworten entfernen (Toast zeigt reinen Text)."""
    return (text or "").replace("**", "").replace("`", "")


def can_view(channel, member) -> bool:
    """Darf ``member`` den Kanal in Discord sehen?"""
    if channel is None or member is None:
        return False
    try:
        return bool(channel.permissions_for(member).view_channel)
    except Exception:  # noqa: BLE001 – unbekannter Kanaltyp -> lieber verbergen
        return False


def panel_visible(guild, member, panel) -> bool:
    """Gepostet, mit Rollen und im Kanal für das Mitglied sichtbar (sonst in Discord nicht klickbar)."""
    if not isinstance(panel, dict) or not panel.get("message_id") or not panel.get("channel_id"):
        return False
    if not panel.get("roles"):
        return False
    try:
        channel = guild.get_channel(int(panel["channel_id"]))
    except (TypeError, ValueError):
        return False
    return can_view(channel, member)


def _is_select(panel) -> bool:
    return panel.get("style") == "select"


def _panel_role_ids(panel) -> list[int]:
    return [int(r["role_id"]) for r in panel.get("roles", [])]


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def member_page_handler(cog, request):
    guild = request["wc_member_guild"]
    member = request["wc_member"]
    conf = await cog.config.guild(guild).all()
    base = f"/me/rollen?guild={guild.id}"
    if request.method == "POST":
        return await _handle_post(cog, request, guild, member, conf, base)
    return _render(cog, request, guild, member, conf)


async def _handle_post(cog, request, guild, member, conf, base):
    data = await request.post()
    lang = conf.get("language", "de")

    def err(text, anchor=""):
        return {"redirect": base + "&err=" + quote(_plain(text)) + anchor}

    if not conf.get("member_page", True):
        return err("Rollen sind im Mitglieder-Bereich ausgeschaltet")
    form = data.get("form")
    if form not in ("btn", "sel"):
        return err("Unbekannte Aktion")
    pid = str(data.get("panel") or "")
    panel = (conf.get("panels") or {}).get(pid)
    # Fremde, ungepostete oder unsichtbare Panels verhalten sich wie gelöschte.
    if not pid or panel is None or not panel_visible(guild, member, panel):
        return err(t(lang, "panel_gone"))
    anchor = "#ar-" + quote(pid)
    # Bedienart muss zum Panel passen (Buttons-Panel hat kein Dropdown und umgekehrt).
    if (form == "sel") != _is_select(panel):
        return err("Unbekannte Aktion", anchor)
    panel_ids = set(_panel_role_ids(panel))

    if form == "btn":
        raw = str(data.get("role") or "")
        if not raw.isdigit() or int(raw) not in panel_ids:
            return err("Diese Rolle gehört nicht zu diesem Panel – bitte Seite neu laden", anchor)
        status, text = await cog.panel_interact(guild, member, panel, "btn", target=int(raw), lang=lang)
    else:
        raw_values = [str(v) for v in data.getall("roles", []) if str(v) != ""]
        if any(not v.isdigit() or int(v) not in panel_ids for v in raw_values):
            return err("Diese Rolle gehört nicht zu diesem Panel – bitte Seite neu laden", anchor)
        chosen = {int(v) for v in raw_values}
        if panel.get("unique") and len(chosen) > 1:
            return err("Bei diesem Panel ist nur eine Rolle möglich", anchor)
        status, text = await cog.panel_interact(guild, member, panel, "sel", chosen=chosen, lang=lang)

    if status == "error":
        return err(text, anchor)
    return {"redirect": base + "&ok=" + quote(_plain(text)) + anchor}


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
def _render(cog, request, guild, member, conf):
    ui = request.app["webcore"].ui
    csrf = request.get("webcore_csrf", "")
    if not conf.get("member_page", True):
        return {"title": "Rollen", "content": ui.card(body=ui.empty(
            "bi-eye-slash", "Rollen sind auf diesem Server im Mitglieder-Bereich ausgeschaltet.",
            "Wähle deine Rollen direkt in Discord über die Rollen-Panels."))}

    panels = [p for p in (conf.get("panels") or {}).values() if panel_visible(guild, member, p)]
    head = ui.hero(
        "bi-person-badge", "",
        "Nimm dir hier dieselben Rollen wie über die Rollen-Panels in Discord. Rollen, die du schon hast, "
        "sind hervorgehoben. Du siehst nur Panels aus Kanälen, die du lesen kannst.",
    )
    if not panels:
        return {"title": "Rollen", "content": head + ui.card(body=ui.empty(
            "bi-person-badge", "Hier gibt es gerade keine Rollen zum Auswählen.",
            "Sobald das Team ein Rollen-Panel postet, erscheint es hier."))}
    me = guild.me
    warn = ""
    if me is None or not me.guild_permissions.manage_roles:
        warn = ui.callout("Der Bot darf gerade keine Rollen vergeben – Änderungen schlagen fehl. "
                          "Bitte sag dem Team Bescheid.", tone="warn")
    cards = "".join(_panel_card(ui, cog, guild, member, p, csrf) for p in panels)
    return {"title": "Rollen", "content": head + warn + cards}


def _role_label(guild, entry) -> str:
    role = guild.get_role(int(entry["role_id"]))
    label = (entry.get("label") or "").strip() or (role.name if role is not None else "Rolle")
    emoji = (entry.get("emoji") or "").strip()
    if emoji and not emoji.startswith("<"):   # Unicode-Emoji zeigen, eigene Server-Emojis nicht
        label = f"{emoji} {label}"
    return label


def _panel_card(ui, cog, guild, member, panel, csrf) -> str:
    pid = str(panel.get("id", ""))
    held = {r.id for r in member.roles}
    mode = panel.get("mode", "toggle")
    if mode not in ("toggle", "add"):
        mode = "toggle"
    unique = bool(panel.get("unique"))
    channel = guild.get_channel(int(panel["channel_id"]))
    entries = [e for e in panel.get("roles", []) if guild.get_role(int(e["role_id"])) is not None]

    meta = [f"<span><i class='bi bi-hash'></i>{_esc(channel.name)}</span>"] if channel is not None else []
    meta.append(ui.badge("nur eine Rolle" if unique else "mehrere möglich", "info"))
    meta.append(ui.badge("nur vergeben" if mode == "add" else "an- und abwählbar", "muted"))
    mine = [e for e in entries if int(e["role_id"]) in held]
    status = (f"Du hast: <b>{', '.join(_esc(_role_label(guild, e)) for e in mine)}</b>"
              if mine else "Du hast noch keine Rolle aus diesem Panel.")
    text = (panel.get("text") or "").strip()
    body = f"<div class='wc-muted'>{' &nbsp;'.join(meta)}</div>"
    if text:
        body += f"<p style='margin:10px 0 0'>{_esc(text).replace(chr(10), '<br>')}</p>"
    body += f"<div class='wc-divider'></div><div class='wc-help'>{status}</div>"

    hidden = {"guild": guild.id, "panel": pid}
    if _is_select(panel):
        hint = SELECT_HINTS[(mode, unique)]
        if unique:
            current = next((int(e["role_id"]) for e in mine), None)
            control = ui.field("Deine Rolle", ui.select(
                "roles", [(int(e["role_id"]), _role_label(guild, e)) for e in entries], current,
                none_label="— keine —"), help=hint)
        else:
            control = ui.switches(*[
                ui.switch("roles", _role_label(guild, e), int(e["role_id"]) in held, value=str(e["role_id"]),
                          desc=_esc((e.get("description") or "").strip()) or None)
                for e in entries
            ]) + f"<div class='wc-help' style='margin-top:8px'>{hint}</div>"
        body += "<div style='margin-top:14px'>" + ui.form(
            f"/me/rollen?guild={guild.id}",
            control + ui.actions(ui.button("Auswahl übernehmen", icon="bi-check2")),
            csrf=csrf, hidden={"form": "sel", **hidden},
        ) + "</div>"
    else:
        buttons = []
        for e in entries:
            rid = int(e["role_id"])
            has = rid in held
            title = ("Abgeben" if mode == "toggle" else "Hast du bereits") if has else "Nehmen"
            buttons.append(ui.button(
                _role_label(guild, e), icon="bi-check2-circle" if has else "bi-plus-circle",
                kind="accent" if has else "ghost", name="role", value=str(rid),
                attrs={"title": title, "aria-pressed": "true" if has else "false"}))
        body += ui.form(
            f"/me/rollen?guild={guild.id}",
            ui.actions(*buttons) + f"<div class='wc-help' style='margin-top:8px'>{MODE_HINTS[(mode, unique)]}</div>",
            csrf=csrf, hidden={"form": "btn", **hidden},
        )

    title = (panel.get("title") or "").strip() if panel.get("use_embed", True) else ""
    return (f"<div id='ar-{_esc(pid)}'>"
            + ui.card(title or panel.get("name") or "Rollen", body, icon="bi-person-badge")
            + "</div>")

