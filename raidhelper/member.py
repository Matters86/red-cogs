"""Mitglieder-Seite „Raids“ (WebCore „Mein Bereich“, ``/me/raids``).

* GET                  -> kommende Events des gewählten Servers als Karten – nur Events in Kanälen,
                          die das Mitglied in Discord sehen darf (``view_channel``)
* GET ?event=<id>      -> Detailansicht mit Roster und allen Aktionen
* POST action=signup   -> anmelden / Spec wechseln   (``RaidHelper.set_signup``, validate=True)
* POST action=status   -> Bank/Spät/Vielleicht/Abwesend (``RaidHelper.set_signup(status=…)``)
* POST action=leave    -> abmelden                    (``RaidHelper.remove_signup``)

Alle Aktionen laufen über dieselben Funktionen wie die Discord-Buttons (gleiche Prüfungen,
gleiche Meldungstexte als Toast, die Event-Nachricht in Discord wird aktualisiert). Geändert
werden ausschließlich die Daten des angemeldeten Mitglieds (``request["wc_member"]``).
Aufbau nur mit dem WebCore-UI-Kit – kein eigenes CSS, kein JavaScript nötig.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote

from . import games
from .dashboard import _plain, _tz
from .embed import signup_counts
from .strings import role_name, t
from .views import STATUS_BUTTONS

SLUG = "raids"
DESC_SHORT = 180  # Zeichen der Beschreibung in der Kartenansicht

_WEEKDAYS = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]
_STATUS_LABEL = {"bench": "Bank", "late": "Spät", "tentative": "Vielleicht", "absence": "Abwesend"}
_STATUS_ICON = {"bench": "bi-hourglass-split", "late": "bi-clock-history",
                "tentative": "bi-question-circle", "absence": "bi-x-circle"}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _now() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


# --------------------------------------------------------------------------- #
#  Helfer
# --------------------------------------------------------------------------- #
def visible_channel(guild, member, event: dict):
    """Kanal des Events, wenn ``member`` ihn in Discord sehen darf – sonst ``None``."""
    cid = event.get("channel_id")
    if not cid:
        return None
    getter = getattr(guild, "get_channel_or_thread", None) or guild.get_channel
    channel = getter(cid)
    if channel is None or not hasattr(channel, "permissions_for"):
        return None
    try:
        perms = channel.permissions_for(member)
    except Exception:  # noqa: BLE001 – fehlende Cache-Daten o. Ä. -> lieber verbergen
        return None
    return channel if getattr(perms, "view_channel", False) else None


def _when(ts: int | None, tz_name: str) -> str:
    """„Sa., 27.09.2026, 20:00 Uhr“ in der Server-Zeitzone."""
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts, _tz(tz_name))
    return f"{_WEEKDAYS[dt.weekday()]}, {dt.strftime('%d.%m.%Y, %H:%M')} Uhr"


def relative(ts: int, now: int) -> str:
    """Deutsche Relativzeit: „in 3 Tagen“, „in 1 Stunde“, „vor 5 Minuten“, „gleich“."""
    diff = int(ts) - int(now)
    secs = abs(diff)
    if secs < 60:
        return "gleich" if diff >= 0 else "gerade eben"
    if secs < 3600:
        n, one, many = secs // 60, "Minute", "Minuten"
    elif secs < 86400:
        n, one, many = secs // 3600, "Stunde", "Stunden"
    else:
        n, one, many = secs // 86400, "Tag", "Tagen"
    unit = one if n == 1 else many
    return f"in {n} {unit}" if diff > 0 else f"vor {n} {unit}"


def _short(text, limit: int = DESC_SHORT) -> str:
    """Beschreibung für die Karte: Discord-Markdown entfernen, einzeilig, gekürzt."""
    text = " ".join(str(text or "").replace("**", "").replace("__", "").replace("`", "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _jump_url(guild, event: dict) -> str | None:
    if event.get("channel_id") and event.get("message_id"):
        return f"https://discord.com/channels/{guild.id}/{event['channel_id']}/{event['message_id']}"
    return None


def _state(cog, event: dict) -> tuple[str, str, str | None]:
    """(Label, Ton, Ablehnungs-Key|None) – dieselbe Prüfung wie die Buttons (``_signup_open``)."""
    open_, reason = cog._signup_open(event)
    if not open_:
        return ("geschlossen", "bad", reason) if reason == "signup_closed" else \
            ("Anmeldeschluss vorbei", "warn", reason)
    cap = event.get("max_signups")
    if cap and signup_counts(event)[1] >= int(cap):
        return "voll", "warn", None
    return "offen", "ok", None


def _own_line(game_id: str, entry: dict | None) -> tuple[str, str | None]:
    """Eigener Status als (HTML-Satz, Callout-Ton|None)."""
    if not entry:
        return "Du bist für dieses Event noch nicht angemeldet.", None
    cid, sid = entry.get("class"), entry.get("spec")
    pick = ""
    if cid:
        spec = games.spec_label(game_id, cid, sid) if sid else ""
        pick = f"{spec} {games.class_label(game_id, cid)}".strip()
    status = entry.get("status") or "signed"
    if status == "signed":
        role = entry.get("role") or games.spec_role(game_id, cid, sid)
        return (f"Du bist <b>angemeldet</b> als <b>{_esc(pick or '—')}</b>"
                f" ({_esc(role_name('de', role))}).", "ok")
    label = _STATUS_LABEL.get(status, status)
    extra = f" – gemerkte Auswahl: {_esc(pick)}" if pick else ""
    return f"Du stehst auf <b>{_esc(label)}</b>{extra}.", "info"


def _occupancy(ui, event: dict, game_id: str) -> str:
    """Belegung: Roster gesamt (Balken) + je Rolle + weitere Rückmeldungen."""
    total, roster = signup_counts(event)
    cap = event.get("max_signups")
    value = f"{roster} / {int(cap)}" if cap else f"{roster} (unbegrenzt)"
    # Balken nur mit Gesamt-Limit – ohne Limit wirkte ein voller Balken wie „ausgebucht“.
    bar = (f"<div class='bar'><span style='width:{min(100, round(roster * 100 / int(cap)))}%'></span></div>"
           if cap else "")
    meter = (
        "<div class='meter'><div class='mlabel'><span class='k'>Im Roster</span>"
        f"<span class='v'>{_esc(value)}</span></div>{bar}</div>"
    )
    signups = event.get("signups") or {}
    limits = event.get("role_limits") or {}
    pills = []
    for role in games.role_order(game_id):
        count = sum(1 for e in signups.values() if e.get("status") == "signed" and e.get("role") == role)
        limit = limits.get(role)
        emoji = games.role_meta(game_id, role).get("emoji", "")
        text = f"{emoji} {role_name('de', role)} {count}" + (f"/{int(limit)}" if limit else "")
        pills.append(ui.badge(text.strip(), "warn" if limit and count >= int(limit) else "muted"))
    for st in STATUS_BUTTONS:
        n = sum(1 for e in signups.values() if e.get("status") == st)
        if n:
            pills.append(ui.badge(f"{_STATUS_LABEL[st]} {n}", "info"))
    return (meter + "<div class='wc-form-actions' style='margin-top:10px;gap:6px'>" + "".join(pills)
            + "</div>")


def _pick_select(game_id: str, entry: dict | None, remembered: dict) -> str:
    """Eine Auswahl „Klasse & Spezialisierung“: Specs nach Klasse gruppiert (``<optgroup>``).

    So ist die Spec-Auswahl ohne JavaScript immer an die Klasse gebunden (keine ungültigen
    Kombinationen). Vorbelegt: aktuelle Anmeldung; gemerkte Specs (wie in Discord) sind markiert.
    """
    cur = f"{entry.get('class')}:{entry.get('spec')}" if entry and entry.get("class") and entry.get("spec") else ""
    groups = []
    for cid in games.class_order(game_id):
        opts = []
        last = remembered.get(f"{game_id}:{cid}")
        clabel = games.class_label(game_id, cid)
        for sid, slabel, role in games.specs_of(game_id, cid):
            value = f"{cid}:{sid}"
            # Klasse im Text, damit die zugeklappte Auswahl (Handy) eindeutig ist.
            label = f"{slabel} {clabel} – {role_name('de', role)}" + (" (zuletzt)" if sid == last else "")
            sel = " selected" if value == cur else ""
            opts.append(f"<option value='{_esc(value)}'{sel}>{_esc(label)}</option>")
        if opts:
            groups.append(f"<optgroup label='{_esc(games.class_label(game_id, cid))}'>{''.join(opts)}</optgroup>")
    none = f"<option value=''{'' if cur else ' selected'} disabled>— Klasse &amp; Spezialisierung wählen —</option>"
    return f"<select class='wc-input' name='pick' required>{none}{''.join(groups)}</select>"


def _url(guild, event_id: str | None = None) -> str:
    return f"/me/{SLUG}?guild={guild.id}" + (f"&event={quote(str(event_id))}" if event_id else "")


# --------------------------------------------------------------------------- #
#  Formulare
# --------------------------------------------------------------------------- #
def _signup_form(ui, guild, event, entry, remembered, csrf, *, back: str, disabled: bool) -> str:
    game_id = event.get("game") or games.DEFAULT_GAME
    if not games.get_game(game_id):
        return ""
    signed = bool(entry and entry.get("status") == "signed")
    label = "Spec wechseln" if signed else "Anmelden"
    help_ = ("Wie das Klassen-Menü in Discord: Die Rolle (Tank, Heiler, Nahkampf, Fernkampf) ergibt sich "
             "aus der Spezialisierung.")
    if entry and not signed:
        help_ += " Anmelden holt dich von „" + _esc(_STATUS_LABEL.get(entry.get("status"), "")) + "“ ins Roster."
    btn = ui.button(label, icon="bi-arrow-repeat" if signed else "bi-person-check",
                    attrs={"disabled": True} if disabled else None)
    body = ui.field("Klasse & Spezialisierung", _pick_select(game_id, entry, remembered), help=help_) \
        + ui.actions(btn)
    return ui.form(_url(guild), body, csrf=csrf,
                   hidden={"guild": guild.id, "event_id": event["id"], "action": "signup", "back": back})


def _status_form(ui, guild, event, entry, csrf, *, back: str, disabled: bool) -> str:
    current = (entry or {}).get("status")
    buttons = []
    for st in STATUS_BUTTONS:
        active = st == current
        attrs = {"aria-pressed": "true" if active else "false"}
        if disabled or active:
            attrs["disabled"] = True
        buttons.append(ui.button(_STATUS_LABEL[st], icon=_STATUS_ICON[st], kind="accent" if active else "ghost",
                                 name="status", value=st, attrs=attrs))
    return ui.form(_url(guild), ui.actions(*buttons), csrf=csrf,
                   hidden={"guild": guild.id, "event_id": event["id"], "action": "status", "back": back})


def _leave_form(ui, guild, event, csrf, *, back: str) -> str:
    title = event.get("title") or event["id"]
    return ui.form(_url(guild), ui.actions(ui.button("Abmelden", icon="bi-box-arrow-left", kind="danger")),
                   csrf=csrf, confirm=f"Vom Event „{title}“ abmelden?",
                   hidden={"guild": guild.id, "event_id": event["id"], "action": "leave", "back": back})


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def member_handler(cog, request):
    guild = request["wc_member_guild"]
    member = request["wc_member"]
    conf = await cog.config.guild(guild).all()
    if request.method == "POST":
        return await _post(cog, request, guild, member, conf)

    ui = request.app["webcore"].ui
    if not conf.get("member_page", True):
        return {"title": "Raids", "content": ui.card(body=ui.empty(
            "bi-calendar-x", "Raids sind hier nicht freigeschaltet",
            f"Das Team von <b>{_esc(guild.name)}</b> bietet die Raid-Anmeldung im Mitglieder-Bereich "
            "nicht an. Melde dich wie gewohnt über die Buttons unter dem Event in Discord an."))}

    csrf = request.get("webcore_csrf", "")
    remembered = await cog.config.user_from_id(member.id).remember()
    events = conf.get("events") or {}
    tz_name = conf.get("timezone") or "Europe/Berlin"
    now = _now()

    sel = request.query.get("event")
    if sel:
        event = events.get(sel)
        if not isinstance(event, dict) or visible_channel(guild, member, event) is None:
            return {"redirect": _url(guild) + "&err=" + quote(_plain(t(conf.get("language"), "unknown_event")))}
        return {"title": f"Raids · {event.get('title') or event['id']}",
                "content": _render_detail(cog, ui, guild, member, event, conf, remembered, csrf, now)}

    upcoming = []
    for event in events.values():
        if not isinstance(event, dict) or event.get("completed") or (event.get("start_ts") or 0) <= now:
            continue
        channel = visible_channel(guild, member, event)
        if channel is not None:
            upcoming.append((event, channel))
    upcoming.sort(key=lambda x: (x[0].get("start_ts") or 0, x[0].get("id", "")))
    return {"title": "Raids",
            "content": _render_list(cog, ui, guild, member, upcoming, tz_name, remembered, csrf, now)}


# --------------------------------------------------------------------------- #
#  Übersicht
# --------------------------------------------------------------------------- #
def _render_list(cog, ui, guild, member, upcoming, tz_name, remembered, csrf, now) -> str:
    uid = str(member.id)
    mine = sum(1 for e, _c in upcoming if (e.get("signups") or {}).get(uid, {}).get("status") == "signed")
    head = ui.hero(
        "bi-calendar-event", "",
        f"Kommende Raids auf <b>{_esc(guild.name)}</b> – du siehst die Events aus allen Kanälen, die du in "
        "Discord lesen kannst. Anmelden, Spec wechseln, Status setzen oder abmelden funktioniert hier genauso "
        f"wie mit den Buttons unter dem Event. Zeiten in <b>{_esc(tz_name)}</b>.",
    )
    if not upcoming:
        return head + ui.card(body=ui.empty(
            "bi-calendar-x", "Keine kommenden Raids",
            "Sobald das Team ein Event in einem Kanal anlegt, den du sehen kannst, erscheint es hier."))
    head += ui.stats([
        ("Kommende Raids", len(upcoming), "bi-calendar-event", None, None),
        ("Davon angemeldet", mine, "bi-person-check", "im Roster", "ok" if mine else None),
    ])
    cards = [_event_card(cog, ui, guild, member, e, ch, tz_name, remembered, csrf, now) for e, ch in upcoming]
    return head + "".join(cards)


def _event_card(cog, ui, guild, member, event, channel, tz_name, remembered, csrf, now) -> str:
    game_id = event.get("game") or games.DEFAULT_GAME
    entry = (event.get("signups") or {}).get(str(member.id))
    label, tone, reason = _state(cog, event)
    start = event.get("start_ts") or 0
    deadline = event.get("deadline_ts")

    rows = [("Termin", f"{_esc(_when(start, tz_name))}<div class='wc-cell-sub'>{_esc(relative(start, now))}</div>")]
    if deadline and deadline != start:
        rows.append(("Anmeldeschluss",
                     f"{_esc(_when(deadline, tz_name))}<div class='wc-cell-sub'>{_esc(relative(deadline, now))}</div>"))
    rows.append(("Kanal", f"#{_esc(getattr(channel, 'name', ''))}"))
    kv = "<dl class='wc-kv'>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"
    desc = event.get("description")
    desc_html = f"<p class='wc-help' style='margin:12px 0 0'>{_esc(_short(desc))}</p>" if desc else ""

    own, own_tone = _own_line(game_id, entry)
    own_html = ui.callout(own, tone=own_tone) if own_tone else f"<p class='wc-muted' style='margin:14px 0 12px'>{own}</p>"

    body = kv + desc_html + "<div style='height:14px'></div>" + _occupancy(ui, event, game_id) + own_html
    if reason:
        body += ui.callout(_esc(_plain(t("de", reason))), tone="warn")
    elif not entry:
        # Schnell-Anmeldung direkt auf der Karte; alles Weitere in der Detailansicht.
        body += _signup_form(ui, guild, event, entry, remembered, csrf, back="list", disabled=False)

    links = [ui.button("Details & Roster" if not entry or reason else "Ändern & Roster",
                       icon="bi-people", kind="ghost", href=_url(guild, event["id"]))]
    jump = _jump_url(guild, event)
    if jump:
        links.append(ui.button("In Discord öffnen", icon="bi-discord", kind="ghost", href=jump,
                               attrs={"target": "_blank", "rel": "noopener"}))
    body += ui.actions(*links)
    return ui.card(event.get("title") or event["id"], body, icon="bi-calendar-event",
                   desc=_esc(games.game_label(game_id)), actions=ui.badge(label, tone),
                   tone="ok" if entry and entry.get("status") == "signed" else None)


# --------------------------------------------------------------------------- #
#  Detailansicht
# --------------------------------------------------------------------------- #
def _render_detail(cog, ui, guild, member, event, conf, remembered, csrf, now) -> str:
    tz_name = conf.get("timezone") or "Europe/Berlin"
    game_id = event.get("game") or games.DEFAULT_GAME
    uid = str(member.id)
    entry = (event.get("signups") or {}).get(uid)
    label, tone, reason = _state(cog, event)
    start = event.get("start_ts") or 0
    deadline = event.get("deadline_ts")

    back = ui.button("Alle Raids", icon="bi-arrow-left", kind="ghost", small=True, href=_url(guild))
    head = ui.hero(
        "bi-calendar-event", event.get("title") or event["id"],
        f"{_esc(games.game_label(game_id))} · {_esc(_when(start, tz_name))} ({_esc(relative(start, now))}) · "
        f"{ui.badge(label, tone)}<br><br>{back}",
    )

    # ---- Deine Anmeldung
    own, own_tone = _own_line(game_id, entry)
    mine = ui.callout(own, tone=own_tone) if own_tone else f"<p class='wc-muted' style='margin:0 0 12px'>{own}</p>"
    if reason:
        # Wie in Discord: ohne offene Anmeldung kein Klassen-Menü, Status gesperrt, Abmelden bleibt.
        mine += ui.callout(_esc(_plain(t("de", reason)))
                           + (" Abmelden ist weiterhin möglich." if entry else ""), tone="warn")
    else:
        mine += _signup_form(ui, guild, event, entry, remembered, csrf, back="detail", disabled=False)
    mine += ("<div class='wc-divider'></div><label class='wc-label'>Status</label>"
             "<div class='wc-help' style='margin-bottom:6px'>Statt im Roster: Bank, Spät, Vielleicht oder "
             "Abwesend – deine Klasse bleibt gemerkt.</div>")
    mine += _status_form(ui, guild, event, entry, csrf, back="detail", disabled=bool(reason))
    if entry:
        mine += "<div class='wc-divider'></div>" + _leave_form(ui, guild, event, csrf, back="detail")
    own_card = ui.card("Deine Anmeldung", mine, icon="bi-person-check",
                       tone="ok" if entry and entry.get("status") == "signed" else None)

    # ---- Termin & Infos
    rows = [("Termin", f"{_esc(_when(start, tz_name))}<div class='wc-cell-sub'>{_esc(relative(start, now))} · "
                       f"{_esc(tz_name)}</div>")]
    if deadline and deadline != start:
        rows.append(("Anmeldeschluss", f"{_esc(_when(deadline, tz_name))}"
                                       f"<div class='wc-cell-sub'>{_esc(relative(deadline, now))}</div>"))
    channel = visible_channel(guild, member, event)
    rows.append(("Kanal", f"#{_esc(getattr(channel, 'name', ''))}"))
    leader = guild.get_member(int(event["leader_id"])) if str(event.get("leader_id") or "").isdigit() else None
    if leader is not None:
        rows.append(("Raidleitung", _esc(leader.display_name)))
    if event.get("recurrence"):
        rec = {"daily": "täglich", "weekly": "wöchentlich", "biweekly": "alle zwei Wochen"}
        rows.append(("Wiederholung", _esc(rec.get(event["recurrence"], event["recurrence"]))))
    info = "<dl class='wc-kv'>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"
    if event.get("description"):
        text = _esc(str(event["description"]).replace("**", "").replace("__", "").replace("`", ""))
        info += f"<p style='margin:14px 0 0;white-space:pre-line'>{text}</p>"
    info += "<div style='height:14px'></div>" + _occupancy(ui, event, game_id)
    jump = _jump_url(guild, event)
    if jump:
        info += ui.actions(ui.button("In Discord öffnen", icon="bi-discord", kind="ghost", href=jump,
                                     attrs={"target": "_blank", "rel": "noopener"}))
    info_card = ui.card("Termin & Infos", info, icon="bi-info-circle")

    return head + ui.columns(own_card, info_card, cols=2) + _render_roster(ui, event, game_id, uid)


def _render_roster(ui, event, game_id: str, uid: str) -> str:
    """Roster wie im Discord-Embed (nach Rolle, dann weitere Rückmeldungen); eigener Eintrag markiert."""
    ordered = sorted((event.get("signups") or {}).items(), key=lambda kv: (kv[1].get("at") or 0, kv[0]))
    by_role: dict = {r: [] for r in games.role_order(game_id)}
    by_status: dict = {s: [] for s in STATUS_BUTTONS}
    for n, (sid, e) in enumerate(ordered, 1):
        st = e.get("status") or "signed"
        spec = ""
        if e.get("class"):
            spec = f"{games.spec_label(game_id, e.get('class'), e.get('spec')) if e.get('spec') else ''} " \
                   f"{games.class_label(game_id, e.get('class'))}".strip()
        item = (n, e.get("name") or "?", spec, sid == uid)
        if st == "signed":
            role = e.get("role") or games.spec_role(game_id, e.get("class"), e.get("spec"))
            by_role.setdefault(role, []).append(item)
        elif st in by_status:
            by_status[st].append(item)

    def _list(items) -> str:
        if not items:
            return "<div class='wc-muted'>Noch niemand.</div>"
        lis = "".join(
            f"<li><span class='mono wc-muted'>{n}.</span><span>{_esc(name)}</span>"
            + (f"<span class='wc-muted'>{_esc(spec)}</span>" if spec else "")
            + (ui.badge("du", "ok") if me else "") + "</li>"
            for n, name, spec, me in items
        )
        return f"<ul class='wc-list'>{lis}</ul>"

    limits = event.get("role_limits") or {}
    role_cards = []
    for role in games.role_order(game_id):
        meta = games.role_meta(game_id, role)
        people = by_role.get(role, [])
        limit = limits.get(role)
        count = f"{len(people)}/{int(limit)}" if limit else str(len(people))
        role_cards.append(ui.card(f"{meta.get('emoji', '')} {role_name('de', role)} ({count})".strip(),
                                  _list(people)))
    out = "<h3 class='wc-sub'>Roster</h3>" + ui.columns(*role_cards, cols=2)
    status_cards = [ui.card(f"{_STATUS_LABEL[st]} ({len(by_status[st])})", _list(by_status[st]),
                            icon=_STATUS_ICON[st]) for st in STATUS_BUTTONS if by_status[st]]
    if status_cards:
        out += "<h3 class='wc-sub'>Weitere Rückmeldungen</h3>" + ui.columns(*status_cards, cols=2)
    return out


# --------------------------------------------------------------------------- #
#  Aktionen (POST) – CSRF, Rate-Limit und Server-Prüfung erledigt WebCore
# --------------------------------------------------------------------------- #
async def _post(cog, request, guild, member, conf):
    form = await request.post()
    lang = conf.get("language")
    event_id = str(form.get("event_id") or "")
    to_detail = form.get("back") == "detail" and bool(event_id)

    def done(ok: bool, text: str, *, detail: bool = to_detail):
        target = _url(guild, event_id if detail else None)
        return {"redirect": target + ("&ok=" if ok else "&err=") + quote(text)}

    if not conf.get("member_page", True):
        return done(False, "Die Raid-Anmeldung ist im Mitglieder-Bereich dieses Servers ausgeschaltet.",
                    detail=False)
    event = (conf.get("events") or {}).get(event_id)
    # Nur Events in Kanälen, die das Mitglied sehen darf – wie in Discord (dort gäbe es keinen Button).
    if not isinstance(event, dict) or visible_channel(guild, member, event) is None:
        return done(False, _plain(t(lang, "unknown_event")), detail=False)

    action = form.get("action")
    if action == "signup":
        class_id, _, spec_id = str(form.get("pick") or "").partition(":")
        ok, key, kwargs = await cog.set_signup(guild, event_id, member, class_id=class_id or None,
                                               spec_id=spec_id or None, validate=True)
    elif action == "status":
        status = str(form.get("status") or "")
        if status in STATUS_BUTTONS:  # "signed" ist kein Status-Button (-> set_signup-Anmeldepfad)
            ok, key, kwargs = await cog.set_signup(guild, event_id, member, status=status)
        else:
            ok, key, kwargs = False, "unknown_pick", {}
    elif action == "leave":
        ok, key, kwargs = await cog.remove_signup(guild, event_id, member)
    else:
        ok, key, kwargs = False, "unknown_pick", {}
    return done(ok, _plain(t(lang, key, **kwargs)))
