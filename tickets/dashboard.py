"""WebCore-Dashboard für den Tickets-Cog.

Drei Aufgaben:
* GET  -> Einstellungs-Seite (Settings, Panels, Transcripts, Statistik) rendern
* POST -> Formular speichern, danach Redirect (Post/Redirect/Get)
* GET ?transcript=<num> -> gespeichertes Transcript als eigene Seite ausliefern

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``): Reiter
Übersicht · Panels · Einstellungen · Texte · Transcripts – kein eigenes CSS.

Rechte: Ticket-Aktionen brauchen WebCore „Bedienen“ und das zuständige Ticket-Team;
Einstellungen, Panels und die Team-Zuordnung je Grund brauchen „Bearbeiten“. WebCore
prüft die Seitenstufe zentral, dieser Handler prüft zusätzlich die einzelnen Ticket-Datensätze.
"""

from __future__ import annotations

import html
import secrets
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import quote_plus

import discord
from aiohttp import web

from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS, t
from .support import MAX_REPLY, support_due
from .naming import name_format, parse_name_settings, ticket_base_name


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _options(items, selected_ids, *, none_label: str | None = None) -> str:
    """``items``: Liste von (id, label). ``selected_ids``: Menge/Container von ids."""
    sel = {str(s) for s in (selected_ids or [])}
    out = []
    if none_label is not None:
        is_sel = " selected" if not sel else ""
        out.append(f"<option value=''{is_sel}>{_esc(none_label)}</option>")
    for ident, label in items:
        is_sel = " selected" if str(ident) in sel else ""
        out.append(f"<option value='{_esc(ident)}'{is_sel}>{_esc(label)}</option>")
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Einstiegspunkt
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    if request.query.get("transcript"):
        return await _serve_transcript(cog, request)
    return await _render(cog, request)


async def _visible_guilds(cog, request):
    """Nur die für den eingeloggten User sichtbaren Server (WebCore-Rechtemodell)."""
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
    if gid is not None:
        return None
    return guilds[0] if guilds else None


async def _dashboard_actor(cog, request, guild):
    webcore = request.app["webcore"]
    getter = getattr(webcore, "current_user", None) or webcore._get_user
    user = await getter(request) or {}
    uid = int(user.get("id") or 0)
    member = guild.get_member(uid) if uid else None
    if member is None and uid:
        try:
            member = await guild.fetch_member(uid)
        except Exception:
            member = None
    if member is None and uid in (getattr(cog.bot, "owner_ids", None) or set()):
        member = _DashboardCloser(uid, user.get("name") or "Bot-Owner")
    return member


def _can_read_transcript(cog, member, conf, transcript):
    record = cog._transcript_record(conf, transcript)
    return cog._is_admin(member, conf) if record is None else cog._can_view_record(member, conf, record)


def _scoped_conf(cog, member, conf):
    scoped = dict(conf)
    scoped["tickets"] = {cid: record for cid, record in (conf.get("tickets") or {}).items()
                         if cog._can_view_record(member, conf, record)}
    scoped["transcripts"] = [tr for tr in conf.get("transcripts", [])
                             if _can_read_transcript(cog, member, conf, tr)]
    opened, closed, claims, durations = set(), set(), {}, []
    for cid, record in scoped["tickets"].items():
        key = str(record.get("num") or f"channel-{cid}")
        opened.add(key)
        if record.get("status") == "closed":
            closed.add(key)
            try:
                start = datetime.fromisoformat(record["created_at"])
                end = datetime.fromisoformat(record["closed_at"])
                durations.append(max(0, int((end - start).total_seconds())))
            except (ValueError, TypeError, KeyError):
                pass
        if record.get("claimed_by"):
            uid = str(record["claimed_by"])
            claims[uid] = claims.get(uid, 0) + 1
    for tr in scoped["transcripts"]:
        key = str(tr.get("num"))
        opened.add(key)
        closed.add(key)
    scoped["stats"] = {"opened": len(opened), "closed": len(closed), "claims": claims,
                       "duration_sum": sum(durations), "duration_count": len(durations)}
    return scoped


_TYPE_LABEL = {"category": "Eigener Kanal", "thread": "Privater Thread", "forum": "Forum-Beitrag"}


def _role_items(guild):
    return [
        (r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()
    ]


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    webcore = request.app["webcore"]
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(cog, request)
    guild = _selected_guild(guilds, request)
    if guild is None:
        if request.query.get("guild") is not None:
            raise web.HTTPNotFound(text="Server nicht gefunden")
        return {"title": "Tickets", "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}

    conf = await cog.config.guild(guild).all()
    actor = await _dashboard_actor(cog, request, guild)
    denied_channels = {str(cid) for cid, record in conf.get("tickets", {}).items()
                       if not cog._can_view_record(actor, conf, record)}
    conf = _scoped_conf(cog, actor, conf)
    conf["panels"] = [panel for panel in conf.get("panels", []) if str(panel.get("channel_id")) not in denied_channels]
    csrf = request.get("webcore_csrf", "")
    role_items = _role_items(guild)
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels if str(c.id) not in denied_channels]
    cat_items = [(c.id, c.name) for c in guild.categories]
    forum_items = [(c.id, f"#{c.name}") for c in getattr(guild, "forums", [])]

    # Einzelnes Panel bearbeiten? (eigene, fokussierte Ansicht)
    pid = request.query.get("panel")
    if pid:
        panel = cog._find_panel(conf, pid)
        if panel is not None:
            return {
                "title": "Tickets · Panel bearbeiten",
                "content": _render_panel_editor(ui, guild, panel, text_items, role_items, cat_items, csrf),
            }
        raise web.HTTPNotFound(text="Panel nicht gefunden")

    stats = conf.get("stats") or {}
    tickets = conf.get("tickets") or {}
    open_now = sum(1 for r in tickets.values() if r.get("status") == "open")
    closed = int(stats.get("closed", 0))
    duration_count = stats.get("duration_count", closed)
    avg = int(stats.get("duration_sum", 0)) // duration_count if duration_count else 0
    panels = conf.get("panels", [])
    transcripts = conf.get("transcripts", [])

    head = ui.hero(
        "bi-life-preserver", "",
        "Mitglieder öffnen Tickets über <b>Panels</b> (Buttons oder Dropdown). Hier legst du fest, "
        "wer Tickets sieht und bearbeitet, wo sie entstehen und wie die Panels aussehen.",
    ) + ui.stats([
        ("Offen", open_now, "bi-envelope-open", None, "ok" if open_now else None),
        ("Erfasste Tickets", int(stats.get("opened", 0)), "bi-inbox", "Für dich sichtbare Tickets und Verläufe", None),
        ("Geschlossen", closed, "bi-archive", None, None),
        ("Ø Laufzeit", _fmt_duration(avg), "bi-stopwatch", None, None),
        ("Panels", len(panels), "bi-window-stack", None, None),
    ])

    getter = getattr(webcore, "current_user", None) or webcore._get_user
    viewer = await getter(request) or {}
    reply_preview = await _reply_preview_card(cog, request, ui, guild, int(viewer.get("id") or 0), csrf)
    body = (
        ui.tab("uebersicht", "Übersicht", "bi-speedometer2", reply_preview + await _render_overview(
            ui, cog, guild, conf, csrf, viewer_id=int(viewer.get("id") or 0), view=request.query.get("view", "all"), viewer_actor=actor))
        + ui.tab("panels", "Panels", "bi-window-stack", _render_panels(ui, guild, conf, text_items, csrf), count=len(panels))
        + _render_settings(ui, cog, guild, conf, role_items, text_items, cat_items, forum_items, csrf)
        + ui.tab("schnellantworten", "Schnellantworten", "bi-chat-left-text", _reply_settings(ui, guild, conf, csrf))
        + ui.tab("transcripts", "Transcripts", "bi-journal-text", _render_transcripts(ui, guild, conf), count=len(transcripts))
    )
    return {"title": "Tickets", "content": head + body}


def _setup_checks(guild, conf) -> list[tuple[str, str]]:
    """Kurze Einrichtungs-Prüfung: [(tone, text)]."""
    out = []
    ttype = conf.get("ticket_type", "category")
    if not conf.get("support_roles") and not conf.get("admin_roles"):
        out.append(("warn", "Es ist keine globale <b>Support- oder Admin-Rolle</b> eingetragen – Tickets ohne eigenes Team können nur Administratoren sowie Server- und Bot-Owner übernehmen."))
    if ttype == "thread" and not conf.get("thread_base"):
        out.append(("bad", "Ticket-Typ <b>Privater Thread</b>, aber kein <b>Basis-Kanal</b> gesetzt – Tickets können nicht erstellt werden."))
    if ttype == "forum" and not conf.get("forum_channel"):
        out.append(("bad", "Ticket-Typ <b>Forum-Beitrag</b>, aber kein <b>Forum-Kanal</b> gesetzt – Tickets können nicht erstellt werden."))
    if ttype == "category" and not conf.get("category_open"):
        out.append(("info", "Keine <b>Kategorie für offene Tickets</b> – neue Ticket-Kanäle erscheinen ganz oben ohne Kategorie."))
    if not conf.get("panels"):
        out.append(("info", "Noch kein <b>Panel</b> – lege im Reiter „Panels“ eins an, damit Mitglieder Tickets öffnen können."))
    if not conf.get("log_channel"):
        out.append(("info", "Kein <b>Log-Kanal</b> – Öffnen/Schließen und Transcripts werden nirgends protokolliert (optional)."))
    return out


async def _render_overview(ui, cog, guild, conf, csrf, *, viewer_id=0, view="all", viewer_actor=None) -> str:
    checks = _setup_checks(guild, conf)
    if checks:
        check_html = "".join(ui.callout(text, tone=tone) for tone, text in checks)
    else:
        check_html = ui.callout("Alles eingerichtet – Tickets können geöffnet werden.", tone="ok")
    setup = ui.card("Einrichtung", check_html, icon="bi-clipboard-check",
                    desc=f"Typ: <b>{_esc(_TYPE_LABEL.get(conf.get('ticket_type'), conf.get('ticket_type')))}</b> · "
                         f"max. {int(conf.get('max_open', 1))} offene(s) Ticket(s) pro Nutzer")

    claims = (conf.get("stats") or {}).get("claims") or {}
    rows = []
    for uid, count in sorted(claims.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        member = guild.get_member(int(uid)) if str(uid).isdigit() else None
        name = member.display_name if member else f"ID {uid}"
        rows.append(ui.row(_esc(name), f">{int(count)}"))
    claim_card = ui.card("Zugewiesene sichtbare Tickets", ui.table(["Mitglied", ">Tickets"], rows,
                         empty_text="Noch keine Übernahmen."), icon="bi-person-check")

    recent = list(reversed(conf.get("transcripts", [])))[:5]
    rrows = []
    for tr in recent:
        link = f"/cogs/tickets?guild={guild.id}&transcript={_esc(tr.get('num'))}"
        btn = ui.button("Öffnen", icon="bi-box-arrow-up-right", kind="ghost", small=True, href=link,
                        attrs={"target": "_blank"})
        rrows.append(ui.row(f"<span class='mono'>#{_esc(tr.get('num'))}</span>", _esc(tr.get("owner")),
                            _esc(tr.get("closed") or "—"), ">" + btn))
    recent_card = ui.card("Zuletzt geschlossen", ui.table(["#", "Inhaber", "Geschlossen", ">"], rrows,
                          empty_text="Noch keine geschlossenen Tickets."), icon="bi-clock-history")
    filters = ui.form("/cogs/tickets", ui.field("Tickets anzeigen", ui.select("view", [
        ("all", "Alle offenen Tickets"), ("mine", "Meine Tickets"), ("unassigned", "Nicht zugewiesen"),
        ("user", "Wartet auf Nutzer"), ("team", "Wartet auf Team"),
    ], view, autosubmit=True)), method="get", csrf="", hidden={"guild": guild.id})
    return setup + filters + _render_open_tickets(ui, cog, guild, conf, csrf, viewer_id=viewer_id,
                                                view=view, viewer_actor=viewer_actor) + ui.columns(claim_card, recent_card)


def _fmt_iso(value) -> str:
    """ISO-Zeitstempel (UTC) -> ``TT.MM.JJJJ HH:MM``."""
    try:
        return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return "—"


def _render_open_tickets(ui, cog, guild, conf, csrf, *, viewer_id=0, view="all", viewer_actor=None) -> str:
    """Offene Tickets mit Schließen und Timer-Steuerung (Tagesgeschäft)."""
    open_items = sorted(((cid, r) for cid, r in (conf.get("tickets") or {}).items() if r.get("status") == "open"),
                        key=lambda kv: kv[1].get("num") or 0)
    if view == "mine":
        open_items = [(cid, r) for cid, r in open_items if r.get("claimed_by") == viewer_id]
    elif view == "unassigned":
        open_items = [(cid, r) for cid, r in open_items if not r.get("claimed_by")]
    elif view in ("user", "team"):
        open_items = [(cid, r) for cid, r in open_items if r.get("waiting_for", "team") == view]
    rows = []
    for cid, rec in open_items[:100]:
        num = rec.get("num")
        ch = _ticket_channel(guild, cid)
        owner = guild.get_member(rec.get("owner_id")) if rec.get("owner_id") else None
        owner_name = owner.display_name if owner is not None else f"ID {rec.get('owner_id') or '—'}"
        claimer = guild.get_member(rec.get("claimed_by")) if rec.get("claimed_by") else None
        claimed = (ui.badge(claimer.display_name, "ok") if claimer is not None
                   else (ui.badge("übernommen", "ok") if rec.get("claimed_by") else ui.badge("frei", "warn")))
        where = f"#{ch.name}" if ch is not None else "Kanal derzeit nicht geladen"
        confirm = (f"Ticket #{num} schließen? Das Transcript wird gespeichert und "
                   + ("der Kanal gelöscht." if conf.get("delete_on_close") else "das Ticket archiviert.")
                   if ch is not None else
                   f"Ticket #{num} prüfen und schließen? Nur bei bestätigter Löschung wird der verwaiste Eintrag entfernt.")
        close = ui.form(
            "/cogs/tickets",
            ui.button("Schließen", icon="bi-lock", kind="danger", small=True),
            csrf=csrf, hidden={"form": "ticket_close", "guild": guild.id, "channel_id": cid},
            confirm=confirm, operate=True,
        )
        timer_active = bool(rec.get("auto_close_at"))
        timer_status = (f"<span class='mono'>{_esc(_fmt_iso(rec['auto_close_at']))}</span>"
                        if timer_active else ui.badge("Aus", "muted"))
        timer_action = ""
        assignment = ""
        priority = ui.badge("Dringend", "bad") if rec.get("priority") == "urgent" else ui.badge("Normal")
        due = support_due(rec, conf)
        due_status = (ui.badge("Antwort fällig", "bad") if due is not None and due <= datetime.now(timezone.utc) else
                      ("Antwort bis " + _esc(due.strftime("%d.%m. %H:%M UTC")) if due is not None else
                       (("Antwort erledigt" if not rec.get("response_cycle_open") else "Antwortzeit pausiert")
                        if conf.get("response_targets_enabled") and rec.get("waiting_for") == "user" else "")))
        if conf.get("response_targets_enabled") and rec.get("support_history_unconfirmed"):
            due_status = ui.badge("Verlauf noch nicht bestätigt", "warn")
        elif conf.get("response_targets_enabled") and rec.get("waiting_for", "team") == "team" and not rec.get("response_cycle_open"):
            due_status = "Antwortzeit startet mit dem nächsten bestätigten Anliegen"
        waiting = ui.badge("Wartet auf Nutzer" if rec.get("waiting_for") == "user" else "Wartet auf Team", "info")
        reply = ""
        can_manage = cog._is_staff(viewer_actor or guild.get_member(viewer_id) or (
            _DashboardCloser(viewer_id, "Bot-Owner") if viewer_id in getattr(cog.bot, "owner_ids", set()) else None), conf, rec)
        if not can_manage:
            close = ""
        if ch is not None and can_manage:
            priority += ui.form("/cogs/tickets", ui.select("priority", [("normal", "Normal"), ("urgent", "Dringend")], rec.get("priority", "normal"))
                + ui.button("Priorität setzen", small=True), csrf=csrf, hidden={"form": "ticket_priority", "guild": guild.id, "channel_id": cid}, operate=True)
            if conf.get("quick_replies"):
                reply = ui.form("/cogs/tickets", ui.select("reply_id", [(item["id"], item["label"]) for item in conf["quick_replies"]])
                    + ui.button("Entwurf öffnen", icon="bi-chat-left-text", small=True), csrf=csrf,
                    hidden={"form": "ticket_reply_preview", "guild": guild.id, "channel_id": cid}, operate=True)
            waiting += ui.form("/cogs/tickets", ui.select("waiting", [("team", "Team"), ("user", "Nutzer")],
                                                        rec.get("waiting_for", "team"))
                               + ui.button("Wartestatus setzen", small=True), csrf=csrf,
                               hidden={"form": "ticket_waiting", "guild": guild.id, "channel_id": cid}, operate=True)
            eligible = sorted(
                (member for member in guild.members if cog._can_assign_to(guild, ch, rec, conf, member)),
                key=lambda member: (member.display_name.casefold(), member.id),
            )
            items = [(member.id, f"{member.display_name} (@{member.name})") for member in eligible]
            assignment = ui.form(
                "/cogs/tickets",
                ui.select("member_id", items, rec.get("claimed_by"), none_label="Nicht zugewiesen")
                + ui.button("Zuweisen", icon="bi-person-check", small=True),
                csrf=csrf, hidden={"form": "ticket_assign", "guild": guild.id, "channel_id": cid},
                operate=True,
            )
            timer_action = ui.form(
                "/cogs/tickets",
                ui.button("Offen halten" if timer_active else "24h-Timer starten",
                          icon="bi-pause-circle" if timer_active else "bi-clock", small=True),
                csrf=csrf,
                hidden={"form": "ticket_keepopen" if timer_active else "ticket_autoclose",
                        "guild": guild.id, "channel_id": cid},
                operate=True,
            )
        rows.append(ui.row(
            f"<span class='mono'>#{_esc(num)}</span>",
            f"<div class='wc-cell-title'>{_esc(owner_name)}</div><div class='wc-cell-sub'>{_esc(where)}</div>",
            _esc(rec.get("reason_label") or "—"),
            f"<span class='mono'>{_esc(_fmt_iso(rec.get('created_at')))}</span>",
            claimed + assignment,
            waiting + f"<div class='wc-cell-sub'>{due_status}</div>" + priority,
            timer_status,
            f"><div class='wc-row-actions'>{reply}{timer_action}{close}</div>" if can_manage
            else "><span class='wc-muted'>Nur lesen für dieses Ticket</span>",
        ))
    more = ""
    if len(open_items) > 100:
        more = ui.callout(f"Es werden 100 von {len(open_items)} offenen Tickets gezeigt.", tone="info")
    return ui.card(
        "Offene Tickets",
        ui.table(["#", "Inhaber", "Grund", "Geöffnet (UTC)", "Zuständig", "Wartet auf", "Auto-Close (UTC)", ">"], rows,
                 empty_text="Keine offenen Tickets.", search=len(rows) > 8,
                 search_placeholder="Nummer, Inhaber, Grund …", id="tk-open") + more,
        icon="bi-envelope-open",
        desc="Schließen wirkt wie der Button im Ticket: Transcript, Log, Inhaber-Rolle entfernen, "
             "archivieren bzw. löschen. Der 24h-Timer wird pro Ticket gestartet; jede menschliche "
             "Nachricht setzt ihn zurück. „Offen halten“ stoppt ihn bis zum erneuten Start.",
    )


def _ticket_channel(guild, cid):
    if not str(cid).isdigit():
        return None
    getter = getattr(guild, "get_channel_or_thread", None) or guild.get_channel
    return getter(int(cid))


def _render_panels(ui, guild, conf, text_items, csrf) -> str:
    rows = []
    for p in conf.get("panels", []):
        ch = guild.get_channel(p.get("channel_id")) if p.get("channel_id") else None
        n_reasons = len(p.get("reasons") or [])
        n_q = len(p.get("modal_questions") or [])
        mode = "Dropdown" if p.get("mode") == "dropdown" else "Buttons"
        posted = ui.badge("gepostet", "ok") if p.get("message_id") else ui.badge("nicht gepostet", "warn")
        edit = ui.button("Bearbeiten", icon="bi-pencil", kind="ghost", small=True,
                         href=f"/cogs/tickets?guild={guild.id}&panel={_esc(p.get('id'))}")
        delete = ui.form(
            "/cogs/tickets",
            ui.button("", icon="bi-trash", kind="danger", small=True, attrs={"title": "Panel löschen"}),
            csrf=csrf, hidden={"form": "panel_delete", "guild": guild.id, "panel_id": p.get("id")},
            confirm="Das Panel und seine Nachricht werden gelöscht. Offene Tickets bleiben bestehen.",
        )
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(p.get('title') or '—')}</div>"
            f"<div class='wc-cell-sub'>{_esc('#' + ch.name if ch else 'Kanal fehlt')}</div>",
            mode, f"<span class='mono'>{n_reasons}</span>", f"<span class='mono'>{n_q}</span>", posted,
            f"><div class='wc-row-actions'>{edit}{delete}</div>",
        ))
    table = ui.card("Deine Panels", ui.table(["Panel", "Art", "Gründe", "Fragen", "Status", ">"], rows,
                    empty_text="Noch keine Panels."), icon="bi-window-stack",
                    desc="Ein Panel ist die Nachricht mit den Buttons bzw. dem Dropdown, über die Tickets geöffnet werden.")

    create = ui.card(
        "Neues Panel", ui.form(
            "/cogs/tickets",
            ui.grid(
                ui.field("Kanal", ui.select("channel_id", text_items), help="Hier wird das Panel gepostet."),
                ui.field("Darstellung", ui.select("mode", [("button", "Buttons"), ("dropdown", "Dropdown-Menü")])),
                ui.field("Titel", ui.text_input("title", "Support-Ticket")),
                ui.field("Beschreibung", ui.textarea("description", "Klicke unten, um ein Ticket zu öffnen.", rows=2)),
                ui.field("Gründe (optional, eine Zeile je Grund)",
                         ui.textarea("reasons", "", rows=4, mono=True,
                                     placeholder="Allgemein | 🎫 | Allgemeine Fragen\nBug melden | 🐞 |"),
                         help="Format: <code>Label | Emoji | Beschreibung</code>. Leer = ein einzelner „Ticket öffnen“-Button. "
                              "Jeder Grund bekommt später eine eigene Team-Zuordnung.", wide=True),
                ui.field("Fragen beim Öffnen (optional, max. 5)",
                         ui.textarea("questions", "", rows=3, mono=True,
                                     placeholder="Worum geht es? | Kurz beschreiben | ja | lang"),
                         help="Format: <code>Frage | Platzhalter | Pflicht (ja/nein) | lang (ja/nein)</code>.", wide=True),
            ) + ui.actions(ui.button("Panel erstellen & posten", icon="bi-send")),
            csrf=csrf, hidden={"form": "panel_create", "guild": guild.id},
        ), icon="bi-plus-square",
    )
    return table + create


def _render_settings(ui, cog, guild, conf, role_items, text_items, cat_items, forum_items, csrf) -> str:
    lang_items = list(LANGUAGES.items())
    ttype = conf.get("ticket_type", "category")

    general = ui.card("Allgemein", ui.grid(
        ui.field("Sprache", ui.select("language", lang_items, conf["language"])),
        ui.field("Ticket-Typ", ui.select("ticket_type", [
            ("category", "Eigener Kanal (in einer Kategorie)"),
            ("thread", "Privater Thread"),
            ("forum", "Forum-Beitrag"),
        ], ttype), help="Wo ein neues Ticket entsteht."),
        ui.field("Max. offene Tickets pro Nutzer", ui.number("max_open", int(conf["max_open"]), min=1, max=25)),
        ui.field("Ticketnamen", ui.select("name_format", [
            ("legacy", "Bisheriges Verhalten · Grund–Nummer"),
            ("reason_user_num", "Grund–Nutzer–Nummer · bewerbung-max-12"),
            ("user_reason_num", "Nutzer–Grund–Nummer · max-bewerbung-12"),
            ("ticket_num", "Ticket–Nummer · ticket-12"),
            ("custom", "Eigene Vorlage"),
        ], name_format(conf)), help="Gilt für neue Ticket-Kanäle, private Threads und Forum-Beiträge. Bestehende Namen bleiben erhalten."),
        ui.conditional("name_format", ["custom"], ui.field("Eigene Namensvorlage",
            ui.text_input("name_template", conf["name_template"], attrs={"maxlength": 90}),
            help="Erlaubt: <code>{reason}</code> Grund, <code>{user}</code> Nutzername, "
                 "<code>{display}</code> Anzeigename, <code>{num}</code> Ticketnummer und <code>{id}</code> Nutzer-ID. "
                 "<code>{num}</code> muss enthalten sein. Höchstens 90 Zeichen.")),
        ui.field("Beispiel für das gespeicherte Format", "<code>" + _esc(cog._channel_name(ticket_base_name(
            conf, {"label": "Bewerbung"}, 12, SimpleNamespace(name="max", display_name="Max Mustermann", id=123456)))) + "</code>",
            help="Grund Bewerbung, Nutzer max, Ticket 12. Auswahl und Vorlage werden beim Speichern übernommen."),
    ), icon="bi-gear", desc="Grundverhalten des Ticketsystems.")

    team = ui.card("Team & Rollen", ui.grid(
        ui.field("Support-Rollen", ui.select("support_roles", role_items, conf["support_roles"], multiple=True,
                 placeholder="Rollen suchen …"), help="Standard-Team für Tickets ohne eigene Team-Zuordnung. Ein eigenes Team je Grund ersetzt diese Rollen für das betreffende Ticket."),
        ui.field("Admin-Rollen", ui.select("admin_roles", role_items, conf["admin_roles"], multiple=True,
                 placeholder="Rollen suchen …"), help="Wie Support, zusätzlich Tickets endgültig löschen. Sehen auch Tickets mit eigenem Team."),
        ui.field("Nur-Lesen-Rollen", ui.select("view_roles", role_items, conf["view_roles"], multiple=True,
                 placeholder="Rollen suchen …"), help="Dürfen alle zuordenbaren Tickets und Verläufe im Team-Dashboard lesen, aber nicht bedienen. Discord-Leserechte gelten vor allem im Typ „Eigener Kanal“."),
        ui.field("Ping-Rollen", ui.select("ping_roles", role_items, conf["ping_roles"], multiple=True,
                 placeholder="Rollen suchen …"), help="Werden beim Öffnen erwähnt, außer in privaten Threads: Dort wird das zuständige Team ohne Rollen-Ping eingeladen."),
        ui.field("Inhaber-Rolle", ui.select("owner_role", [(i, n) for i, n, _c in role_items],
                 conf["owner_role"], none_label="— keine —"),
                 help="Bekommt der Ersteller, solange sein Ticket offen ist.", wide=True),
    ), icon="bi-people", desc="Pro Grund kannst du im Panel-Editor zusätzlich ein eigenes Team festlegen.") + ui.callout(
        "Für strikt getrennten Discord-Zugriff je Grund verwende <b>Eigener Kanal</b>. "
        "Forum-Beiträge übernehmen die Sichtbarkeit des gesamten Forums; „Threads verwalten“ kann auch private Threads sichtbar machen. "
        "Bot-Aktionen prüfen bei allen Ticket-Typen das zuständige Team.", tone="info")

    place = ui.card("Speicherort & Protokoll", ui.grid(
        ui.field("Kategorie für offene Tickets", ui.select("category_open", cat_items, conf["category_open"], none_label="— keine —"),
                 help="Nur für Typ „Eigener Kanal“."),
        ui.field("Kategorie für geschlossene Tickets", ui.select("category_close", cat_items, conf["category_close"], none_label="— keine —"),
                 help="Geschlossene Tickets werden hierhin verschoben (Archiv)."),
        ui.field("Basis-Kanal", ui.select("thread_base", text_items, conf["thread_base"], none_label="— keiner —"),
                 help="Nur für Typ „Privater Thread“: in diesem Kanal entstehen die Threads."),
        ui.field("Forum-Kanal", ui.select("forum_channel", forum_items, conf["forum_channel"], none_label="— keiner —"),
                 help="Nur für Typ „Forum-Beitrag“."),
        ui.field("Log-Kanal", ui.select("log_channel", text_items, conf["log_channel"], none_label="— keiner —"),
                 help="Öffnen, Übernehmen, Schließen und das Transcript als Datei.", wide=True),
    ), icon="bi-folder2-open")

    behaviour = ui.card("Verhalten", "<div class='wc-switches'>"
        + ui.switch("close_confirmation", "Vor dem Schließen bestätigen", conf["close_confirmation"],
                    desc="Fragt nach, bevor ein Ticket geschlossen wird.")
        + ui.switch("user_can_close", "Ersteller darf schließen", conf["user_can_close"],
                    desc="Der Ersteller kann sein eigenes Ticket schließen.")
        + ui.switch("delete_on_close", "Beim Schließen löschen", conf["delete_on_close"],
                    desc="Kanal wird gelöscht statt archiviert (Transcript bleibt erhalten).")
        + "</div>", icon="bi-toggles")

    portal = ui.card("Mitglieder-Bereich", "<div class='wc-switches'>"
        + ui.switch("portal_enabled", "Im Mitglieder-Bereich anzeigen", conf.get("portal_enabled", True),
                    desc="Mitglieder sehen unter „Mein Bereich → Meine Tickets“ ihre eigenen offenen Tickets "
                         "und die Verläufe ihrer geschlossenen Tickets.")
        + ui.switch("portal_create", "Tickets über die Website öffnen erlauben", conf.get("portal_create", True),
                    desc="Mitglieder können dort über die Panels, die sie in Discord sehen, ein Ticket öffnen – "
                         "mit denselben Fragen und Limits wie beim Button.")
        + "</div>", icon="bi-person-badge",
        desc="Wirkt nur, wenn der Bot-Owner „Mein Bereich“ für diesen Server eingeschaltet hat.")

    overrides = conf.get("messages") or {}
    override_fields = []
    labels = {
        "panel_default_title": ("Panel-Titel (Standard)", "Wenn ein Panel keinen eigenen Titel hat."),
        "panel_default_description": ("Panel-Text (Standard)", "Wenn ein Panel keine eigene Beschreibung hat."),
        "btn_open": ("Button „Ticket öffnen“", "Beschriftung des Einzel-Buttons."),
        "opened_title": ("Titel im neuen Ticket", "Platzhalter: <code>{num}</code>, <code>{user}</code>."),
        "opened_body": ("Begrüßung im neuen Ticket", "Platzhalter: <code>{num}</code>, <code>{user}</code> (Erwähnung)."),
    }
    for key in OVERRIDABLE_KEYS:
        label, hint = labels.get(key, (key, None))
        default = STRINGS["de"].get(key, "")
        ctrl = (ui.textarea(f"ovr_{key}", overrides.get(key, ""), rows=3, placeholder=default)
                if key in ("opened_body", "panel_default_description")
                else ui.text_input(f"ovr_{key}", overrides.get(key, ""), placeholder=default))
        override_fields.append(ui.field(label, ctrl, help=hint, wide=key in ("opened_body", "panel_default_description")))
    texts = ui.card("Eigene Texte", ui.grid(*override_fields),
                    icon="bi-chat-left-text",
                    desc="Leer lassen = Standardtext der gewählten Sprache (als grauer Platzhalter sichtbar).")

    save = ui.save_row("Einstellungen speichern")
    advanced = ui.disclosure("Erweitert: Priorität und Antwortzeiten", ui.switches(ui.switch(
        "response_targets_enabled", "Antwortzeiten anzeigen", conf.get("response_targets_enabled", False),
        desc="Standard aus. Zählt nur, während das Team antworten muss; Nutzer-Wartezeit pausiert dieselbe Uhr."))
        + ui.grid(ui.field("Normal", ui.number("response_target_hours", conf.get("response_target_hours", 24), min=1, max=720, unit="Stunden")),
                  ui.field("Dringend", ui.number("response_urgent_hours", conf.get("response_urgent_hours", 4), min=1, max=720, unit="Stunden"))),
        expanded=conf.get("response_targets_enabled", False))
    # Ein Formular über zwei Reiter (Einstellungen + Texte) – beide speichern alles.
    return ui.form(
        "/cogs/tickets",
        ui.tab("einstellungen", "Einstellungen", "bi-sliders", general + team + place + behaviour + portal + advanced + save)
        + ui.tab("texte", "Texte", "bi-chat-left-text", texts + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _reply_settings(ui, guild, conf, csrf):
    cards = []
    for item in conf.get("quick_replies", []):
        save = ui.form("/cogs/tickets", ui.field("Name", ui.text_input("label", item["label"], attrs={"maxlength": 80, "required": True}))
            + ui.field("Text", ui.textarea("text", item["text"], rows=4), help="{user}, {ticket}, {staff}, {signature}; unbekannte Platzhalter bleiben wörtlich.")
            + ui.button("Vorlage speichern"), csrf=csrf,
            hidden={"form": "quick_reply_save", "guild": guild.id, "reply_id": item["id"]})
        delete = ui.form("/cogs/tickets", ui.button("Entfernen", kind="danger", small=True), csrf=csrf,
            hidden={"form": "quick_reply_delete", "guild": guild.id, "reply_id": item["id"]}, confirm="Diese Schnellantwort entfernen?")
        cards.append(ui.card(item["label"], save, actions=delete))
    create = ui.form("/cogs/tickets", ui.field("Name", ui.text_input("label", attrs={"maxlength": 80, "required": True}))
        + ui.field("Text", ui.textarea("text", rows=4)) + ui.button("Schnellantwort hinzufügen"), csrf=csrf,
        hidden={"form": "quick_reply_save", "guild": guild.id})
    signature = ui.form("/cogs/tickets", ui.field("Signatur", ui.textarea("signature", conf.get("quick_reply_signature", ""), rows=2),
        help="Optional, höchstens 200 Zeichen. Nur über {signature} eingefügt; keine automatischen Erwähnungen.")
        + ui.button("Signatur speichern"), csrf=csrf, hidden={"form": "quick_reply_signature", "guild": guild.id})
    return ui.callout("Vorlagen bearbeiten braucht Bearbeiten. Teammitglieder wählen einen Entwurf, bearbeiten ihn und senden erst nach ausdrücklicher Bestätigung. Kein automatisches Posten.") + ui.disclosure(
        "Erweitert: Vorlagen und Signatur verwalten", "".join(cards) + ui.card("Neue Vorlage (max. 25)", create) + ui.card("Signatur", signature))


def _reply_draft(cog, request, guild, cid, uid):
    drafts = cog.__dict__.setdefault("_quick_reply_drafts", {})
    now = time.monotonic()
    for key, draft in list(drafts.items()):
        if draft["expires"] < now:
            drafts.pop(key, None)
    return drafts, (request.get("webcore_csrf", ""), guild.id, str(cid), uid)


async def _reply_preview_card(cog, request, ui, guild, uid, csrf):
    cid = str(request.query.get("reply") or "")
    drafts, key = _reply_draft(cog, request, guild, cid, uid)
    draft = drafts.get(key)
    if not draft:
        return ""
    channel = _ticket_channel(guild, cid)
    actor = await _dashboard_actor(cog, request, guild)
    if actor is None or actor.id != uid:
        return ""
    error = await cog._reply_access(guild, channel, actor) if channel is not None else "Ticket nicht gefunden."
    if error:
        return ui.callout(_esc(error), tone="warn")
    form = ui.form("/cogs/tickets", ui.field("Antwort bearbeiten", ui.textarea("text", draft["text"], rows=5),
            help="Noch nicht gesendet. Keine Erwähnung löst einen Ping aus; höchstens 2000 Zeichen.")
        + ui.button("Antwort jetzt senden", icon="bi-send"), csrf=csrf, operate=True,
        hidden={"form": "ticket_reply_send", "guild": guild.id, "channel_id": cid, "token": draft["token"]},
        confirm="Diese Antwort jetzt im Ticket veröffentlichen?")
    return ui.card("Schnellantwort – Vorschau, noch nicht gesendet", form, icon="bi-eye")


def _reasons_to_text(reasons) -> str:
    """Gründe-Liste zurück in das ``Label | Emoji | Beschreibung``-Textformat."""
    lines = []
    for r in reasons or []:
        parts = [r.get("label") or "", r.get("emoji") or "", r.get("description") or ""]
        while len(parts) > 1 and not parts[-1]:
            parts.pop()
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _questions_to_text(questions) -> str:
    """Modal-Fragen zurück in das ``Label | Platzhalter | pflicht | lang``-Textformat."""
    lines = []
    for q in questions or []:
        req = "ja" if q.get("required", True) else "nein"
        style = "lang" if q.get("style") == "long" else "kurz"
        lines.append(" | ".join([q.get("label") or "", q.get("placeholder") or "", req, style]))
    return "\n".join(lines)


def _render_panel_editor(ui, guild, panel, text_items, role_items, cat_items, csrf) -> str:
    """Editor für ein bestehendes Panel (Titel, Text, Modus, Kanal, Gründe, Fragen) + Team-Zuordnung."""
    pid = panel.get("id")
    back = ui.button("Zurück zu den Panels", icon="bi-arrow-left", kind="ghost",
                     href=f"/cogs/tickets?guild={guild.id}#panels")
    head = ui.hero("bi-window-stack", panel.get("title") or "Panel",
                   "Änderungen aktualisieren die bereits gepostete Panel-Nachricht direkt.", actions=back)

    edit = ui.form(
        "/cogs/tickets",
        ui.card("Inhalt & Darstellung", ui.grid(
            ui.field("Kanal", ui.select("channel_id", text_items, panel.get("channel_id")),
                     help="Bei einem Wechsel wird die alte Nachricht gelöscht und neu gepostet."),
            ui.field("Darstellung", ui.select("mode", [("button", "Buttons"), ("dropdown", "Dropdown-Menü")],
                                               panel.get("mode", "button"))),
            ui.field("Titel", ui.text_input("title", panel.get("title") or "")),
            ui.field("Beschreibung", ui.textarea("description", panel.get("description") or "", rows=2)),
        ), icon="bi-card-heading")
        + ui.card("Gründe & Fragen", ui.grid(
            ui.field("Gründe (eine Zeile je Grund)", ui.textarea("reasons", _reasons_to_text(panel.get("reasons") or []), rows=5, mono=True),
                     help="Format: <code>Label | Emoji | Beschreibung</code>. Leer = ein einzelner „Ticket öffnen“-Button. "
                          "Das Format für neue Ticketnamen wählst du unter Einstellungen → Ticketnamen.", wide=True),
            ui.field("Fragen beim Öffnen (max. 5)", ui.textarea("questions", _questions_to_text(panel.get("modal_questions") or []), rows=4, mono=True),
                     help="Format: <code>Frage | Platzhalter | Pflicht (ja/nein) | lang (ja/nein)</code>.", wide=True),
        ), icon="bi-list-ul")
        + ui.save_row("Speichern & Nachricht aktualisieren"),
        csrf=csrf, hidden={"form": "panel_save", "guild": guild.id, "panel_id": pid}, savebar=True,
    )
    reasons = panel.get("reasons") or []
    return (
        head
        + ui.tab("inhalt", "Inhalt", "bi-card-heading", edit)
        + ui.tab("teams", "Team je Grund", "bi-diagram-3",
                 _render_reason_routing(ui, guild, panel, role_items, cat_items, csrf), count=len(reasons))
    )


def _render_reason_routing(ui, guild, panel, role_items, cat_items, csrf) -> str:
    """Team-Zuordnung je Grund: eigene Team-Rollen, Ping-Rollen und Kategorie."""
    reasons = panel.get("reasons") or []
    if not reasons:
        return ui.card(body=ui.empty(
            "bi-diagram-3", "Dieses Panel hat noch keine Gründe.",
            "Lege im Reiter „Inhalt“ Gründe an und speichere – dann kannst du hier jedem Grund ein eigenes Team geben."))
    blocks = []
    for r in reasons:
        rid = r.get("id")
        title = f"{r.get('emoji') or ''} {r.get('label') or '—'}".strip()
        blocks.append(ui.card(title, ui.grid(
            ui.field("Team-Rollen", ui.select(f"r_{rid}_support", role_items, r.get("support_roles") or [], multiple=True,
                     placeholder="leer = globale Support-Rollen"),
                     help="Dieses Team ersetzt die globalen Support-Rollen für Tickets dieses Grundes. Admins behalten Zugriff."),
            ui.field("Ping-Rollen", ui.select(f"r_{rid}_ping", role_items, r.get("ping_roles") or [], multiple=True,
                     placeholder="leer = globale Ping-Rollen")),
            ui.field("Kategorie", ui.select(f"r_{rid}_cat", cat_items, r.get("category_id"), none_label="— globale Kategorie —"),
                     wide=True),
        ), icon="bi-tag"))
    return (
        ui.callout("<b>Gilt für neue Tickets.</b> Bereits offene Tickets behalten ihr bisheriges Team. "
                   "Leer gelassene Felder nutzen die globalen Einstellungen. Ein eigenes Team ersetzt die globalen Support-Rollen; "
                   "Admins und ausdrücklich konfigurierte Nur-Lesen-Rollen behalten ihren Zugriff. "
                   "Für getrennte Discord-Sichtbarkeit verwende den Ticket-Typ <b>Eigener Kanal</b>.", tone="info")
        + ui.form("/cogs/tickets", "".join(blocks) + ui.save_row("Team-Zuordnung speichern"),
                  csrf=csrf, hidden={"form": "panel_routing", "guild": guild.id, "panel_id": panel.get("id")}, savebar=True)
    )


def _render_transcripts(ui, guild, conf) -> str:
    items = list(reversed(conf.get("transcripts", [])))[:200]
    rows = []
    for tr in items:
        link = f"/cogs/tickets?guild={guild.id}&transcript={_esc(tr.get('num'))}"
        rows.append(ui.row(
            f"<span class='mono'>#{_esc(tr.get('num'))}</span>",
            _esc(tr.get("channel_name")), _esc(tr.get("owner")), _esc(tr.get("reason") or "—"),
            f"<span class='mono'>{_esc(tr.get('closed') or '—')}</span>",
            f">{ui.button('Öffnen', icon='bi-box-arrow-up-right', kind='ghost', small=True, href=link, attrs={'target': '_blank'})}",
        ))
    return ui.card("Transcripts", ui.table(["#", "Kanal", "Inhaber", "Grund", "Geschlossen", ">"], rows,
                   empty_text="Noch keine Transcripts.", search=True, search_placeholder="Nach Nummer, Name oder Grund suchen …",
                   id="tk-transcripts"),
                   icon="bi-journal-text", desc="Der komplette Verlauf jedes geschlossenen Tickets als eigene Seite (die letzten 200).")


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
def _ids(values) -> list[int]:
    out = []
    for v in values:
        if v and str(v).isdigit():
            out.append(int(v))
    return out


def _one_id(value):
    return int(value) if value and str(value).isdigit() else None


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
        raise web.HTTPFound("/cogs/tickets?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    ticket_forms = {"ticket_close", "ticket_assign", "ticket_waiting", "ticket_priority",
                    "ticket_reply_preview", "ticket_reply_send", "ticket_autoclose", "ticket_keepopen"}
    if form in ticket_forms:
        conf = await gconf.all()
        record = (conf.get("tickets") or {}).get(str(data.get("channel_id") or ""))
        actor = await _dashboard_actor(cog, request, guild)
        if not record or not cog._is_staff(actor, conf, record):
            raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&err=Ticket+nicht+gefunden")

    if form == "ticket_close":
        return await _close_from_dashboard(cog, request, guild, data.get("channel_id"))

    if form == "ticket_assign":
        return await _assign_from_dashboard(cog, request, guild, data.get("channel_id"), data.get("member_id"))

    if form == "ticket_waiting":
        back = f"/cogs/tickets?guild={guild.id}"
        channel = _ticket_channel(guild, data.get("channel_id"))
        if channel is None:
            raise web.HTTPFound(back + "&err=Ticket+nicht+gefunden")
        error = await cog._set_waiting(guild, channel, data.get("waiting"), actor, check_actor=True)
        raise web.HTTPFound(back + ("&err=" + quote_plus(error) if error else "&ok=Wartestatus+aktualisiert"))

    if form in {"ticket_priority", "ticket_reply_preview", "ticket_reply_send"}:
        back = f"/cogs/tickets?guild={guild.id}"
        cid = str(data.get("channel_id") or "")
        channel = _ticket_channel(guild, cid)
        if channel is None:
            raise web.HTTPFound(back + "&err=Ticket+nicht+gefunden")
        actor = await _dashboard_actor(cog, request, guild)
        uid = getattr(actor, "id", 0)
        if form == "ticket_priority":
            error = await cog._set_priority(guild, channel, data.get("priority"), actor)
            raise web.HTTPFound(back + ("&err=" + quote_plus(error) if error else "&ok=Priorität+aktualisiert"))
        drafts, key = _reply_draft(cog, request, guild, cid, uid)
        if form == "ticket_reply_preview":
            error, text = await cog._prepare_reply(guild, channel, actor, data.get("reply_id"))
            if error:
                raise web.HTTPFound(back + "&err=" + quote_plus(error))
            while len(drafts) >= 200:
                drafts.pop(next(iter(drafts)))
            record = await cog._get_record(guild, channel.id)
            drafts[key] = {"token": secrets.token_urlsafe(24), "expires": time.monotonic() + 600,
                           "text": text, "owner_id": (record or {}).get("owner_id")}
            raise web.HTTPFound(back + "&reply=" + cid + "#uebersicht")
        draft = drafts.get(key)
        if not draft or not secrets.compare_digest(str(data.get("token") or ""), draft["token"]):
            raise web.HTTPFound(back + "&err=Vorschau+abgelaufen+oder+bereits+gesendet")
        drafts.pop(key, None)
        edited = str(data.get("text") or "").strip()
        if 0 < len(edited) <= MAX_REPLY:
            draft["text"] = edited
        error = await cog._send_support_reply(guild, channel, actor, data.get("text"))
        if error:
            drafts.setdefault(key, draft)
            raise web.HTTPFound(back + "&reply=" + cid + "&err=" + quote_plus(error))
        raise web.HTTPFound(back + "&ok=Antwort+gesendet")

    if form in {"quick_reply_save", "quick_reply_delete", "quick_reply_signature"}:
        back = f"/cogs/tickets?guild={guild.id}"
        if form == "quick_reply_signature":
            signature = str(data.get("signature") or "").strip()
            if len(signature) > 200 or "\x00" in signature:
                raise web.HTTPFound(back + "&err=Signatur+höchstens+200+Zeichen")
            await gconf.quick_reply_signature.set(signature)
        else:
            reply_id = str(data.get("reply_id") or "")
            if form == "quick_reply_save":
                label, text = str(data.get("label") or "").strip(), str(data.get("text") or "").strip()
                if not 1 <= len(label) <= 80 or not 1 <= len(text) <= MAX_REPLY or "\x00" in text or "\x00" in label:
                    raise web.HTTPFound(back + "&err=Name+1–80+und+Text+1–2000+Zeichen+angeben")
            async with gconf.quick_replies() as replies:
                if form == "quick_reply_delete":
                    replies[:] = [item for item in replies if item["id"] != reply_id]
                else:
                    entry = next((item for item in replies if item["id"] == reply_id), None)
                    if entry is None:
                        if len(replies) >= 25:
                            raise web.HTTPFound(back + "&err=Höchstens+25+Schnellantworten")
                        entry = {"id": uuid.uuid4().hex[:8]}
                        replies.append(entry)
                    entry.update(label=label, text=text)
        raise web.HTTPFound(back + "&ok=Schnellantworten+gespeichert#schnellantworten")

    if form in {"ticket_autoclose", "ticket_keepopen"}:
        return await _autoclose_from_dashboard(
            cog, request, guild, data.get("channel_id"), enabled=form == "ticket_autoclose"
        )

    if form == "settings":
        try:
            naming_mode, naming_template = parse_name_settings(data, await gconf.all())
        except ValueError as exc:
            raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&err=" + quote_plus(str(exc))) from None
        try:
            normal = int(data.get("response_target_hours", 24))
            urgent = int(data.get("response_urgent_hours", 4))
            if not 1 <= normal <= 720 or not 1 <= urgent <= 720 or urgent > normal:
                raise ValueError()
        except (TypeError, ValueError):
            raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&err=" + quote_plus("Antwortzeiten: 1–720 Stunden; Dringend darf nicht länger als Normal sein"))
        was_enabled = await gconf.response_targets_enabled()
        await gconf.response_target_hours.set(normal)
        await gconf.response_urgent_hours.set(urgent)
        await gconf.response_targets_enabled.set("response_targets_enabled" in data)
        if not was_enabled and "response_targets_enabled" in data:
            await cog._mark_support_history_pending()
        lang = data.get("language") or "de"
        await gconf.language.set(lang if lang in LANGUAGES else "de")
        ttype = data.get("ticket_type") or "category"
        await gconf.ticket_type.set(ttype if ttype in ("category", "thread", "forum") else "category")
        await gconf.support_roles.set(_ids(data.getall("support_roles", [])))
        await gconf.admin_roles.set(_ids(data.getall("admin_roles", [])))
        await gconf.view_roles.set(_ids(data.getall("view_roles", [])))
        await gconf.ping_roles.set(_ids(data.getall("ping_roles", [])))
        # Die Inhaber-Rolle bekommt jeder Ticket-Ersteller automatisch -> neue Rolle nur,
        # wenn der User sie vergeben darf (sonst Selbst-Hochstufung über ein Ticket).
        new_owner = _one_id(data.get("owner_role"))
        cur_owner = await gconf.owner_role()
        webcore = request.app.get("webcore")
        if (new_owner and new_owner != cur_owner and webcore is not None and hasattr(webcore, "can_grant_role")
                and not await webcore.can_grant_role(request, guild, guild.get_role(new_owner))):
            new_owner = cur_owner
        await gconf.owner_role.set(new_owner)
        await gconf.category_open.set(_one_id(data.get("category_open")))
        await gconf.category_close.set(_one_id(data.get("category_close")))
        await gconf.thread_base.set(_one_id(data.get("thread_base")))
        await gconf.forum_channel.set(_one_id(data.get("forum_channel")))
        await gconf.log_channel.set(_one_id(data.get("log_channel")))
        try:
            await gconf.max_open.set(max(1, int(data.get("max_open", 1))))
        except (TypeError, ValueError):
            await gconf.max_open.set(1)
        await gconf.name_template_mode.set(naming_mode)
        await gconf.name_template.set(naming_template)
        await gconf.close_confirmation.set("close_confirmation" in data)
        await gconf.user_can_close.set("user_can_close" in data)
        await gconf.delete_on_close.set("delete_on_close" in data)
        await gconf.portal_enabled.set("portal_enabled" in data)
        await gconf.portal_create.set("portal_create" in data)

        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)
        raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok=Einstellungen+gespeichert")

    if form == "panel_create":
        panel = {
            "id": uuid.uuid4().hex[:8],
            "channel_id": _one_id(data.get("channel_id")),
            "message_id": None,
            "title": (data.get("title") or "Support-Ticket").strip(),
            "description": (data.get("description") or "").strip(),
            "mode": "dropdown" if data.get("mode") == "dropdown" else "button",
            "button_label": "🎟️ Ticket",
            "placeholder": "Grund auswählen …",
            "reasons": _parse_reasons(data.get("reasons", "")),
            "modal_questions": _parse_questions(data.get("questions", "")),
            "lang": None,
        }
        msg_id = await cog.post_panel(guild, panel)
        panel["message_id"] = msg_id
        async with gconf.panels() as panels:
            panels.append(panel)
        ok = "Panel+erstellt" if msg_id else "Panel+gespeichert+(Posten+fehlgeschlagen)"
        raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok={ok}")

    if form == "panel_save":
        pid = data.get("panel_id")
        new_channel_id = _one_id(data.get("channel_id"))
        old_channel_id = None
        panel_copy = None
        # 1) Felder im gespeicherten Panel aktualisieren
        async with gconf.panels() as panels:
            for p in panels:
                if p.get("id") == pid:
                    old_channel_id = p.get("channel_id")
                    p["title"] = (data.get("title") or "Support-Ticket").strip()
                    p["description"] = (data.get("description") or "").strip()
                    p["mode"] = "dropdown" if data.get("mode") == "dropdown" else "button"
                    p["channel_id"] = new_channel_id
                    # Gründe neu parsen, aber IDs + Team-Zuordnung anhand des Labels erhalten,
                    # damit die Zuordnung beim Bearbeiten des Grund-Textes nicht verloren geht.
                    p["reasons"] = _merge_reason_routing(p.get("reasons"), _parse_reasons(data.get("reasons", "")))
                    p["modal_questions"] = _parse_questions(data.get("questions", ""))
                    panel_copy = dict(p)
                    break
        if panel_copy is None:
            raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok=Panel+nicht+gefunden")
        # 2) Kanalwechsel: alte Nachricht entfernen und neu posten
        if old_channel_id and old_channel_id != new_channel_id and panel_copy.get("message_id"):
            await cog.delete_panel_message(
                guild, {"channel_id": old_channel_id, "message_id": panel_copy["message_id"]}
            )
            panel_copy["message_id"] = None
        # 3) Nachricht aktualisieren (edit an Ort und Stelle bzw. neu posten)
        new_msg_id = await cog.update_panel_message(guild, panel_copy)
        async with gconf.panels() as panels:
            for p in panels:
                if p.get("id") == pid:
                    p["message_id"] = new_msg_id
                    break
        ok = "Panel+aktualisiert" if new_msg_id else "Panel+gespeichert+(Nachricht+nicht+aktualisiert)"
        raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok={ok}")

    if form == "panel_routing":
        pid = data.get("panel_id")
        async with gconf.panels() as panels:
            for p in panels:
                if p.get("id") != pid:
                    continue
                for r in (p.get("reasons") or []):
                    rid = r.get("id")
                    r["support_roles"] = _ids(data.getall(f"r_{rid}_support", []))
                    r["ping_roles"] = _ids(data.getall(f"r_{rid}_ping", []))
                    r["category_id"] = _one_id(data.get(f"r_{rid}_cat"))
                break
        raise web.HTTPFound(
            f"/cogs/tickets?guild={guild.id}&panel={pid}&ok=Team-Zuordnung+gespeichert"
        )

    if form == "panel_delete":
        pid = data.get("panel_id")
        removed = None
        async with gconf.panels() as panels:
            for i, p in enumerate(panels):
                if p.get("id") == pid:
                    removed = panels.pop(i)
                    break
        if removed:
            await cog.delete_panel_message(guild, removed)
        raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}&ok=Panel+gelöscht")

    raise web.HTTPFound(f"/cogs/tickets?guild={guild.id}")


class _DashboardCloser:
    """Schließende Person, wenn der Dashboard-User (z. B. Bot-Owner) kein Mitglied des Servers ist."""

    def __init__(self, uid: int, name: str):
        self.id = uid
        self.name = name
        self.display_name = name
        self.mention = f"<@{uid}>"

    def __str__(self):
        return self.name


async def _close_from_dashboard(cog, request, guild, raw_cid):
    """Einzelnes Ticket schließen (Tagesgeschäft) – dieselbe Logik wie der „Schließen“-Button."""
    back = f"/cogs/tickets?guild={guild.id}"
    cid = str(raw_cid or "").strip()
    if not cid.isdigit():
        raise web.HTTPFound(back + "&err=" + quote_plus("Ticket nicht gefunden"))
    gconf = cog.config.guild(guild)
    conf = await gconf.all()
    record = (conf.get("tickets") or {}).get(cid)
    actor = await _dashboard_actor(cog, request, guild)
    if not record or not cog._is_staff(actor, conf, record):
        raise web.HTTPFound(back + "&err=" + quote_plus("Ticket nicht gefunden"))
    num = record.get("num")
    if record.get("status") != "open":
        raise web.HTTPFound(back + "&err=" + quote_plus(f"Ticket #{num} ist bereits geschlossen"))
    channel = _ticket_channel(guild, cid)
    if channel is None:
        # Threads können nach einem Neustart/Archivieren im Cache fehlen. Nur ein
        # bestätigtes Discord-404 erlaubt das Entfernen des gespeicherten Tickets.
        try:
            channel = await guild.fetch_channel(int(cid))
        except discord.NotFound:
            channel = None
        except (discord.HTTPException, AttributeError):
            raise web.HTTPFound(back + "&err=" + quote_plus("Ticket-Kanal derzeit nicht erreichbar – bitte erneut versuchen")) from None
        else:
            if channel is None or getattr(getattr(channel, "guild", None), "id", None) != guild.id:
                raise web.HTTPFound(back + "&err=" + quote_plus("Ticket-Kanal derzeit nicht erreichbar – bitte erneut versuchen"))
    if channel is None:
        async with cog._lock("close", int(cid)):
            current_conf = await gconf.all()
            current = current_conf["tickets"].get(cid)
            actor = await _dashboard_actor(cog, request, guild)
            if not current or not cog._is_staff(actor, current_conf, current):
                raise web.HTTPFound(back + "&err=Ticket+nicht+gefunden")
            if current.get("status") != "open":
                raise web.HTTPFound(back + "&err=" + quote_plus(f"Ticket #{num} ist bereits geschlossen"))
            async with gconf.tickets() as tickets:
                tickets.pop(cid, None)
        raise web.HTTPFound(back + "&ok=" + quote_plus(f"Ticket #{num}: Kanal existiert nicht mehr – Eintrag entfernt"))
    closed = await cog._close_ticket(guild, channel, record, actor, conf, check_actor=True)
    if not closed:
        raise web.HTTPFound(back + "&err=" + quote_plus(f"Ticket #{num} ist bereits geschlossen"))
    raise web.HTTPFound(back + "&ok=" + quote_plus(f"Ticket #{num} geschlossen"))


async def _assign_from_dashboard(cog, request, guild, raw_cid, raw_member_id):
    """WebCore prüft Bedienen und Serverzugriff; das Ziel prüft die gemeinsame Ticketlogik."""
    back = f"/cogs/tickets?guild={guild.id}"
    cid, member_id = str(raw_cid or "").strip(), str(raw_member_id or "").strip()
    conf = await cog.config.guild(guild).all()
    lang = conf["language"]
    actor = await _dashboard_actor(cog, request, guild)
    record = conf["tickets"].get(cid)
    if not record or not cog._is_staff(actor, conf, record):
        raise web.HTTPFound(back + "&err=Ticket+nicht+gefunden")
    if not cid.isdigit() or (member_id and not member_id.isdigit()):
        raise web.HTTPFound(back + "&err=" + quote_plus(t(lang, "assignment_invalid")))
    channel = _ticket_channel(guild, cid)
    if channel is None or cid not in conf["tickets"]:
        raise web.HTTPFound(back + "&err=" + quote_plus(t(lang, "not_a_ticket")))
    member = guild.get_member(int(member_id)) if member_id else None
    if member_id and member is None:
        raise web.HTTPFound(back + "&err=" + quote_plus(t(lang, "assignment_invalid")))
    error = await cog._assign_ticket(guild, channel, member, actor, check_actor=True)
    raise web.HTTPFound(back + ("&err=" + quote_plus(error) if error
                               else "&ok=" + quote_plus(t(lang, "assignment_done"))))


async def _autoclose_from_dashboard(cog, request, guild, raw_cid, *, enabled):
    """Timer über dieselbe Logik wie die persistenten Discord-Buttons steuern."""
    back = f"/cogs/tickets?guild={guild.id}"
    cid = str(raw_cid or "").strip()
    if not cid.isdigit():
        raise web.HTTPFound(back + "&err=" + quote_plus("Ticket nicht gefunden"))
    conf = await cog.config.guild(guild).all()
    record = (conf.get("tickets") or {}).get(cid)
    actor = await _dashboard_actor(cog, request, guild)
    if not record or not cog._is_staff(actor, conf, record):
        raise web.HTTPFound(back + "&err=" + quote_plus("Ticket nicht gefunden"))
    num = record.get("num")
    if record.get("status") != "open":
        raise web.HTTPFound(back + "&err=" + quote_plus(f"Ticket #{num} ist bereits geschlossen"))
    channel = _ticket_channel(guild, cid)
    if channel is None:
        raise web.HTTPFound(back + "&err=" + quote_plus(f"Ticket #{num}: Kanal nicht gefunden"))
    changed = await cog._set_ticket_autoclose(guild, channel, enabled, actor, conf, check_actor=True)
    if not changed:
        raise web.HTTPFound(back + "&err=" + quote_plus(f"Ticket #{num} ist bereits geschlossen"))
    result = "24h-Timer gestartet" if enabled else "Timer gestoppt – bleibt offen"
    raise web.HTTPFound(back + "&ok=" + quote_plus(f"Ticket #{num}: {result}"))


def _parse_reasons(raw: str) -> list[dict]:
    reasons = []
    seen = set()
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0]
        # Doppelte Labels überspringen: sie bekämen beim Bearbeiten dieselbe ID
        # (_merge_reason_routing) -> doppelte custom_ids -> Discord lehnt das Panel ab.
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        reasons.append(
            {
                "id": uuid.uuid4().hex[:6],
                "label": label[:80],
                "emoji": (parts[1] if len(parts) > 1 and parts[1] else None),
                "description": (parts[2][:100] if len(parts) > 2 and parts[2] else None),
            }
        )
    return reasons[:25]


def _merge_reason_routing(old_reasons, new_reasons):
    """Übernimmt ID und Team-Zuordnung (support/ping/category) eines Grundes anhand
    des Labels, damit die Zuordnung beim Bearbeiten des Grund-Textes erhalten bleibt.
    """
    by_label = {}
    for r in old_reasons or []:
        if r.get("label"):
            by_label[r["label"]] = r
    for r in new_reasons:
        old = by_label.get(r.get("label"))
        if not old:
            continue
        if old.get("id"):
            r["id"] = old["id"]
        for key in ("support_roles", "ping_roles", "category_id"):
            if old.get(key):
                r[key] = old[key]
    return new_reasons


def _parse_questions(raw: str) -> list[dict]:
    out = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0]
        if not label:
            continue
        required = True
        if len(parts) > 2 and parts[2].lower() in ("nein", "no", "false", "0"):
            required = False
        style = "long" if len(parts) > 3 and parts[3].lower() in ("lang", "long", "ja", "yes", "1") else "short"
        out.append(
            {
                "label": label[:45],
                "placeholder": (parts[1] if len(parts) > 1 and parts[1] else None),
                "required": required,
                "style": style,
            }
        )
    return out[:5]


# --------------------------------------------------------------------------- #
#  Transcript ausliefern
# --------------------------------------------------------------------------- #
async def _serve_transcript(cog, request):
    guilds = await _visible_guilds(cog, request)
    guild = _selected_guild(guilds, request)
    num = request.query.get("transcript")
    if guild is None or not num:
        return web.Response(text="Nicht gefunden.", status=404)
    conf = await cog.config.guild(guild).all()
    record = next((r for r in conf.get("transcripts", []) if str(r.get("num")) == str(num)), None)
    actor = await _dashboard_actor(cog, request, guild)
    if not record or not _can_read_transcript(cog, actor, conf, record):
        return web.Response(text="Transcript nicht gefunden.", status=404)
    text = await cog.read_transcript(record)  # gemeinsam mit „Meine Tickets“ (asyncio.to_thread)
    if text is None:
        return web.Response(text="Transcript-Datei fehlt.", status=404)
    return web.Response(text=text, content_type="text/html")
