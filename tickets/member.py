"""„Meine Tickets“ – Mitglieder-Seite im WebCore-Bereich „Mein Bereich“ (``/me/tickets``).

* GET                           -> offene Tickets, Verlauf (geschlossen) und „Neues Ticket“
* GET ?transcript=<num>         -> Transcript eines EIGENEN geschlossenen Tickets (sonst 404)
* GET ?new=<panel>&reason=<id>  -> Formular mit den Fragen des Panels
* POST form=open                -> Ticket über dieselbe Logik wie der Discord-Button öffnen

Sicherheit: Es wird ausschließlich über ``request["wc_member"].id`` gefiltert. IDs aus URL oder
Formular wählen nur innerhalb der eigenen Tickets bzw. der Panels aus, die das Mitglied in
Discord sehen kann – fremde oder erfundene IDs ergeben „nicht gefunden“.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote

from aiohttp import web

from .strings import t
from .views import modal_fields

SLUG = "tickets"


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _url(guild, **params) -> str:
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items() if v not in (None, ""))
    return f"/me/{SLUG}?guild={guild.id}" + (f"&{query}" if query else "")


def _redirect(guild, *, ok: str | None = None, err: str | None = None, **params) -> dict:
    return {"redirect": _url(guild, **params, ok=ok, err=err)}


def is_mine(record: dict, member_id: int) -> bool:
    """Ersteller – oder per ``[p]ticket add`` hinzugefügt (seit dieser Version gespeichert)."""
    return record.get("owner_id") == member_id or member_id in (record.get("members") or [])


def _parse_iso(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt_dt(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M") if dt else "—"


def _ago(dt: datetime | None) -> str:
    if dt is None:
        return ""
    secs = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if secs < 60:
        return "gerade eben"
    if secs < 3600:
        return f"vor {secs // 60} Min."
    if secs < 86400:
        return f"vor {secs // 3600} Std."
    days = secs // 86400
    return "vor 1 Tag" if days == 1 else f"vor {days} Tagen"


def _closed_text(raw) -> str:
    """``2026-09-25 14:03:11`` (Transcript-Metadaten) -> ``25.09.2026 14:03``."""
    dt = _parse_iso(str(raw or "").replace(" ", "T"))
    return _fmt_dt(dt) if dt else (_esc(raw) or "—")


def _channel_url(guild, channel_id) -> str:
    return f"https://discord.com/channels/{guild.id}/{int(channel_id)}"


def _unicode_emoji(value) -> str | None:
    """Nur echte Unicode-Emojis anzeigen (eigene Server-Emojis ``<:x:id>`` wären im Web nur Text)."""
    value = (value or "").strip()
    if not value or value.startswith("<") or len(value) > 16 or any(c.isascii() and c.isalnum() for c in value):
        return None
    return value


# --------------------------------------------------------------------------- #
#  Panels, die das Mitglied in Discord benutzen kann
# --------------------------------------------------------------------------- #
def usable_panels(guild, member, conf) -> list[dict]:
    """Nur gepostete Panels in Kanälen, die das Mitglied sehen kann (dort liegt der Button)."""
    out = []
    for panel in conf.get("panels") or []:
        if not panel.get("id") or not panel.get("message_id") or not panel.get("channel_id"):
            continue
        channel = guild.get_channel(panel["channel_id"])
        if channel is None:
            continue
        try:
            if not channel.permissions_for(member).view_channel:
                continue
        except Exception:  # noqa: BLE001 – im Zweifel nicht anzeigen
            continue
        out.append(panel)
    return out


def _choices(conf, panel) -> list[tuple[str, str, str | None, str | None]]:
    """Wie die Buttons/Optionen des Panels in Discord: [(reason_id, label, emoji, beschreibung)]."""
    reasons = panel.get("reasons") or []
    if reasons:
        return [(r["id"], (r.get("label") or "Ticket")[:80], _unicode_emoji(r.get("emoji")),
                 (r.get("description") or None)) for r in reasons[:25] if r.get("id")]
    label = (conf.get("messages") or {}).get("btn_open") or panel.get("button_label") or "🎟️ Ticket"
    return [("_", label[:80], None, None)]


def _resolve_choice(cog, guild, member, conf, panel_id, reason_id):
    """(panel, reason) für eine Auswahl – oder (None, None), wenn sie für dieses Mitglied ungültig ist."""
    panel = next((p for p in usable_panels(guild, member, conf) if p.get("id") == panel_id), None)
    if panel is None:
        return None, None
    if panel.get("reasons"):
        reason = cog._find_reason(panel, reason_id)
        return (panel, reason) if reason is not None else (None, None)
    return (panel, None) if reason_id in ("_", "", None) else (None, None)


def _panel_title(cog, conf, panel) -> str:
    lang = panel.get("lang") or conf["language"]
    return panel.get("title") or cog._text(conf, lang, "panel_default_title")


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def member_handler(cog, request):
    ui = request.app["webcore"].ui
    guild = request["wc_member_guild"]
    member = request["wc_member"]
    conf = await cog.config.guild(guild).all()

    if not conf.get("portal_enabled", True):
        if request.method == "POST":
            return _redirect(guild, err="Tickets sind im Mitglieder-Bereich ausgeschaltet.")
        if request.query.get("transcript"):
            return web.Response(text="Transcript nicht gefunden.", status=404)
        return {"title": "Meine Tickets", "content": ui.card(body=ui.empty(
            "bi-slash-circle", "Auf diesem Server nicht verfügbar",
            "Das Team hat die Ticket-Übersicht für den Mitglieder-Bereich ausgeschaltet. "
            "Tickets öffnest du wie gewohnt über das Panel in Discord."))}

    if request.method == "POST":
        return await _handle_post(cog, request, guild, member, conf)
    if request.query.get("transcript"):
        return await _serve_transcript(cog, request, conf, member)
    if request.query.get("new"):
        return _render_new_form(cog, request, ui, guild, member, conf)
    return _render_overview(cog, request, ui, guild, member, conf)


# --------------------------------------------------------------------------- #
#  Übersicht (GET)
# --------------------------------------------------------------------------- #
def _status_badge(ui, record) -> str:
    if record.get("locked"):
        return ui.badge("Gesperrt", "warn")
    if record.get("claimed_by"):
        return ui.badge("In Bearbeitung", "ok")
    return ui.badge("Wartet auf das Team", "info")


def _render_overview(cog, request, ui, guild, member, conf) -> dict:
    uid = member.id
    tickets = conf.get("tickets") or {}
    mine_open = sorted(
        ((cid, r) for cid, r in tickets.items() if r.get("status") == "open" and is_mine(r, uid)),
        key=lambda kv: int(kv[1].get("num") or 0), reverse=True,
    )
    mine_closed = [tr for tr in reversed(conf.get("transcripts") or []) if is_mine(tr, uid)]
    allow_create = bool(conf.get("portal_create", True))

    head = ui.hero(
        "bi-life-preserver", "",
        f"Deine Tickets auf <b>{_esc(guild.name)}</b>: offene Anliegen, frühere Verläufe"
        + (" – und hier kannst du auch direkt ein neues Ticket öffnen." if allow_create else "."),
    )

    created = request.query.get("created", "")
    notice = ""
    if created.isdigit() and created in dict(mine_open):
        rec = tickets[created]
        notice = ui.callout(
            f"Dein Ticket <b>#{_esc(rec.get('num'))}</b> wurde erstellt. Das Team wurde benachrichtigt – "
            "schreib dein Anliegen gern direkt im Ticket-Kanal weiter."
            + ui.actions(ui.button("Zum Ticket in Discord", icon="bi-discord", href=_channel_url(guild, created),
                                   attrs={"target": "_blank", "rel": "noopener"})),
            tone="ok",
        )

    # --- Offen --------------------------------------------------------------- #
    cards = []
    for cid, r in mine_open:
        opened = _parse_iso(r.get("created_at"))
        role = "Ersteller" if r.get("owner_id") == uid else "Hinzugefügt"
        body = ui.grid(
            ui.field("Grund", f"<div>{_esc(r.get('reason_label') or t('de', 'no_reason'))}</div>"),
            ui.field("Status", _status_badge(ui, r)),
            ui.field("Geöffnet", f"<div class='mono'>{_fmt_dt(opened)}</div>"
                                 f"<div class='wc-help'>{_esc(_ago(opened))}</div>"),
            ui.field("Deine Rolle", f"<div>{role}</div>"),
        ) + ui.actions(ui.button("In Discord öffnen", icon="bi-discord", href=_channel_url(guild, cid),
                                 attrs={"target": "_blank", "rel": "noopener"}))
        cards.append(ui.card(f"Ticket #{r.get('num')}", body, icon="bi-ticket-perforated"))
    if not cards:
        action = ui.goto("Neues Ticket öffnen", "neu", icon="bi-plus-circle", kind="accent", small=False) \
            if allow_create else ""
        cards.append(ui.card(body=ui.empty(
            "bi-emoji-smile", "Du hast gerade keine offenen Tickets.",
            "Brauchst du Hilfe? Öffne ein Ticket – über das Panel in Discord"
            + (" oder direkt hier." if allow_create else "."), action=action)))
    open_tab = ui.tab("offen", "Offen", "bi-envelope-open", "".join(cards), count=len(mine_open))

    # --- Verlauf -------------------------------------------------------------- #
    rows = []
    for tr in mine_closed:
        link = _url(guild, transcript=tr.get("num"))
        rows.append(ui.row(
            f"<div class='wc-cell-title'>Ticket #{_esc(tr.get('num'))}</div>"
            f"<div class='wc-cell-sub'>{_esc(tr.get('reason') or t('de', 'no_reason'))}</div>",
            f"<span class='mono'>{_closed_text(tr.get('closed'))}</span>",
            ">" + ui.button("Verlauf ansehen", icon="bi-journal-text", kind="ghost", small=True, href=link,
                            attrs={"target": "_blank", "rel": "noopener"}),
        ))
    history = ui.card(
        "Geschlossene Tickets",
        ui.table(["Ticket", "Geschlossen (UTC)", ">"], rows, empty_text="Noch keine geschlossenen Tickets.",
                 search=len(rows) > 8, search_placeholder="Nach Nummer oder Grund suchen …", id="tk-me-history"),
        icon="bi-journal-text",
        desc="Der komplette Verlauf jedes geschlossenen Tickets öffnet sich als eigene Seite.",
    )
    history_tab = ui.tab("verlauf", "Verlauf", "bi-clock-history", history, count=len(mine_closed))

    new_tab = ""
    if allow_create:
        new_tab = ui.tab("neu", "Neues Ticket", "bi-plus-circle", _render_new_list(cog, ui, guild, member, conf))
    return {"title": "Meine Tickets", "content": head + notice + open_tab + history_tab + new_tab}


def _blocked_callout(cog, ui, conf, member) -> str:
    if cog.open_blocked(conf, member.id) == "max_open":
        return ui.callout(
            f"{_esc(t('de', 'max_open_reached', max=int(conf['max_open'])))} "
            "Sobald ein Ticket geschlossen ist, kannst du ein neues öffnen.", tone="warn")
    return ""


def _render_new_list(cog, ui, guild, member, conf) -> str:
    blocked = _blocked_callout(cog, ui, conf, member)
    if blocked:
        return ui.card(body=blocked)
    panels = usable_panels(guild, member, conf)
    if not panels:
        return ui.card(body=ui.empty(
            "bi-inbox", "Gerade kein Ticket-Panel verfügbar.",
            "Auf diesem Server gibt es im Moment kein Panel, das du nutzen kannst."))
    out = []
    for panel in panels:
        lang = panel.get("lang") or conf["language"]
        desc = panel.get("description") or cog._text(conf, lang, "panel_default_description")
        tiles = []
        for rid, label, emoji, rdesc in _choices(conf, panel):
            icon = (f"<span class='ti'>{_esc(emoji)}</span>" if emoji
                    else "<span class='ti'><i class='bi bi-ticket-perforated'></i></span>")
            tiles.append(
                f"<a class='tile' href='{_esc(_url(guild, new=panel['id'], reason=rid))}'>{icon}"
                f"<span style='min-width:0'><div class='tn'>{_esc(label)}</div>"
                + (f"<div class='td'>{_esc(rdesc)}</div>" if rdesc else "")
                + "</span></a>"
            )
        body = (f"<p class='wc-help' style='margin-top:0'>{_esc(desc)}</p>" if desc else "") \
            + f"<div class='tiles'>{''.join(tiles)}</div>"
        out.append(ui.card(_panel_title(cog, conf, panel), body, icon="bi-window-stack"))
    return "".join(out)


def _render_new_form(cog, request, ui, guild, member, conf) -> dict:
    if not conf.get("portal_create", True):
        return _redirect(guild, err="Tickets können hier nicht über die Website geöffnet werden.")
    panel, reason = _resolve_choice(cog, guild, member, conf, request.query.get("new"),
                                    request.query.get("reason", "_"))
    if panel is None:
        return _redirect(guild, err="Dieses Panel ist nicht (mehr) verfügbar.")
    back = _url(guild) + "#neu"
    title = _panel_title(cog, conf, panel)
    what = (reason or {}).get("label")
    head = ui.hero(
        "bi-plus-circle", "",
        f"Neues Ticket über <b>{_esc(title)}</b>" + (f" – Grund: <b>{_esc(what)}</b>" if what else "") + ".",
        actions=ui.button("Zurück", icon="bi-arrow-left", kind="ghost", href=back),
    )
    blocked = _blocked_callout(cog, ui, conf, member)
    if blocked:
        return {"title": "Neues Ticket", "content": head + ui.card(body=blocked)}

    fields = modal_fields(panel.get("modal_questions"))
    controls = []
    for i, f in enumerate(fields):
        label = f["label"] + ("" if f["required"] else " (optional)")
        if f["long"]:
            ctrl = (f"<textarea class='wc-input' name='q{i}' rows='5' maxlength='{f['max_length']}'"
                    f" placeholder='{_esc(f['placeholder'] or '')}'{' required' if f['required'] else ''}></textarea>")
        else:
            ctrl = ui.text_input(f"q{i}", "", placeholder=f["placeholder"] or "",
                                 attrs={"maxlength": f["max_length"], "required": f["required"]})
        controls.append(ui.field(label, ctrl, wide=True))
    if controls:
        body = ui.grid(*controls, cols=1)
    else:
        body = ui.callout("Für dieses Panel sind keine Fragen hinterlegt – dein Ticket wird direkt erstellt.",
                          tone="info")
    body += ui.actions(ui.button("Ticket öffnen", icon="bi-send"),
                       ui.button("Abbrechen", kind="ghost", href=back))
    form = ui.form(
        _url(guild), body, csrf=request["webcore_csrf"],
        hidden={"form": "open", "guild": guild.id, "panel": panel["id"], "reason": (reason or {}).get("id") or "_"},
    )
    card = ui.card("Deine Angaben" if controls else "Ticket öffnen", form, icon="bi-pencil-square",
                   desc="Das Team sieht deine Antworten im neuen Ticket-Kanal.")
    return {"title": "Neues Ticket", "content": head + card}


# --------------------------------------------------------------------------- #
#  Transcript (nur eigene Tickets)
# --------------------------------------------------------------------------- #
async def _serve_transcript(cog, request, conf, member):
    num = request.query.get("transcript", "")
    record = next((tr for tr in conf.get("transcripts") or []
                   if str(tr.get("num")) == num and is_mine(tr, member.id)), None)
    text = await cog.read_transcript(record) if record else None
    if text is None:  # fremd, unbekannt oder Datei fehlt -> immer dieselbe Antwort
        return web.Response(text="Transcript nicht gefunden.", status=404)
    return web.Response(text=text, content_type="text/html")


# --------------------------------------------------------------------------- #
#  Ticket öffnen (POST) – dieselbe Logik wie der Discord-Button
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request, guild, member, conf):
    data = await request.post()
    if data.get("form") != "open":
        return _redirect(guild, err="Unbekannte Aktion.")
    if not conf.get("portal_create", True):
        return _redirect(guild, err="Tickets können hier nicht über die Website geöffnet werden.")
    panel_id, reason_id = str(data.get("panel") or ""), str(data.get("reason") or "_")
    panel, reason = _resolve_choice(cog, guild, member, conf, panel_id, reason_id)
    if panel is None:
        return _redirect(guild, err="Dieses Panel ist nicht (mehr) verfügbar.")
    back = {"new": panel_id, "reason": reason_id}

    # Antworten exakt wie das Discord-Modal: gleiche Fragen, Pflichtfelder, max. Länge, Schlüssel = Label.
    answers = {}
    for i, f in enumerate(modal_fields(panel.get("modal_questions"))):
        value = str(data.get(f"q{i}") or "").replace("\r\n", "\n").replace("\r", "\n")
        if not f["long"]:
            value = " ".join(value.split("\n"))  # Kurzfeld ist in Discord einzeilig
        if len(value) > f["max_length"]:
            return _redirect(guild, err=f"Die Antwort auf „{f['label']}“ ist zu lang (max. {f['max_length']} Zeichen).",
                             **back)
        if f["required"] and not value.strip():
            return _redirect(guild, err=f"Bitte beantworte die Pflichtfrage „{f['label']}“.", **back)
        answers[f["label"]] = value

    if cog.open_blocked(conf, member.id) == "max_open":  # Vorprüfung wie beim Button
        return _redirect(guild, err=t("de", "max_open_reached", max=int(conf["max_open"])))
    result = await cog.open_ticket(guild, member, panel, reason, answers)
    if result.status == "max_open":
        return _redirect(guild, err=t("de", "max_open_reached", max=result.max_open))
    if result.target is None:
        return _redirect(guild, err="Das Ticket konnte nicht erstellt werden – bitte informiere das Team.", **back)
    record = (await cog.config.guild(guild).tickets()).get(str(result.target.id)) or {}
    num = record.get("num")
    return _redirect(guild, ok=f"Ticket #{num} erstellt" if num else "Ticket erstellt", created=result.target.id)
