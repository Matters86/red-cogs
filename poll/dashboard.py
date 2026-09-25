"""WebCore-Dashboard für den Poll-Cog.

Aufgaben (gleiches Muster wie tickets/dashboard.py):
* GET                  -> Seite mit Reitern: Umfragen · Neue Umfrage · Einstellungen · Texte
* GET ?poll=<id>       -> Ergebnis-Detail einer Umfrage (read-only)
* POST form=settings   -> Einstellungen speichern (Post/Redirect/Get)
* POST form=create     -> Neue Umfrage anlegen und posten
* POST form=action     -> Umfrage schließen/öffnen/löschen

Aufbau mit dem UI-Baukasten von WebCore (``request.app["webcore"].ui``) – kein
eigenes CSS. Nutzereingaben werden mit ``html.escape`` abgesichert.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote

import discord
from aiohttp import web

from .embed import vote_counts
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

HARD_OPTION_LIMIT = 25

# Beschriftung + Hilfe der überschreibbaren Texte (Schlüssel aus strings.OVERRIDABLE_KEYS)
_OVERRIDE_LABELS = {
    "embed_no_votes": ("Noch keine Stimmen", "Steht in der Umfrage, solange noch niemand abgestimmt hat."),
}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _one_id(value):
    return int(value) if value and str(value).isdigit() else None


def _status_word(poll: dict) -> str:
    if poll.get("ended"):
        return "beendet"
    if poll.get("closed"):
        return "geschlossen"
    return "offen"


_STATUS_TONE = {"offen": "ok", "geschlossen": "warn", "beendet": "muted"}


def _role_items(guild):
    return [
        (r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()
    ]


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
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
    return guilds[0] if guilds else None


def _guild_bar(ui, guilds, guild, request) -> str:
    """Cog-eigene Server-Auswahl – nur ohne globalen WebCore-Server-Wechsler."""
    if request.get("wc_switcher"):
        return ""
    return ui.form(
        "/cogs/poll",
        ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
        csrf="", method="get",
    )


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(cog, request)
    guild = _selected_guild(guilds, request)
    if guild is None:
        return {"title": "Umfragen",
                "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    polls = conf.get("polls") or {}
    bar = _guild_bar(ui, guilds, guild, request)

    # Ergebnis-Detailansicht?
    sel = request.query.get("poll")
    if sel and sel in polls:
        return {"title": "Umfragen · Ergebnis", "content": bar + _render_results(ui, guild, polls[sel])}

    active = sum(1 for p in polls.values() if not (p.get("closed") or p.get("ended")))
    total_votes = sum(vote_counts(p)[1] for p in polls.values())
    head = ui.hero(
        "bi-bar-chart", "",
        "Mitglieder stimmen per Button direkt in Discord ab. Hier startest du neue Umfragen, siehst die "
        "Ergebnisse und legst fest, wer Umfragen erstellen darf.",
    ) + ui.stats([
        ("Aktive Umfragen", active, "bi-broadcast", None, "ok" if active else None),
        ("Umfragen gesamt", len(polls), "bi-collection", None, None),
        ("Stimmen gesamt", total_votes, "bi-check2-square", None, None),
        ("Stimmabgabe", "anonym" if conf.get("default_anonymous") else "sichtbar", "bi-eye",
         "Standard für neue Umfragen", None),
    ])

    body = (
        ui.tab("umfragen", "Umfragen", "bi-list-check", _render_polls_table(ui, guild, polls, csrf), count=len(polls))
        + ui.tab("neu", "Neue Umfrage", "bi-plus-square", _render_create_form(ui, guild, conf, csrf))
        + _render_settings(ui, guild, conf, csrf)
    )
    return {"title": "Umfragen", "content": bar + head + body}


def _render_settings(ui, guild, conf, csrf) -> str:
    access = ui.card("Allgemein & Rechte", ui.grid(
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf.get("language", "de")),
                 help="Sprache der Umfrage-Nachrichten und Buttons."),
        ui.field("Erstellen erlaubt für", ui.select(
            "allow_create", [("manager", "Nur Mods/Manager"), ("everyone", "Alle Mitglieder")],
            conf.get("allow_create", "manager")),
            help="Wer in Discord mit <code>[p]poll create</code> Umfragen starten darf."),
        ui.field("Manager-Rollen", ui.select("manager_roles", _role_items(guild), conf.get("manager_roles") or [],
                                             multiple=True, placeholder="Rollen suchen …"),
                 help="Dürfen Umfragen erstellen und fremde Umfragen schließen/löschen. "
                      "Server-Verwalter dürfen das immer.", wide=True),
        ui.field("Max. Optionen", ui.number("max_options", int(conf.get("max_options", 10)), min=2,
                                            max=HARD_OPTION_LIMIT, unit="Optionen"),
                 help=f"Obergrenze je Umfrage (2–{HARD_OPTION_LIMIT})."),
    ), icon="bi-shield-check", desc="Wer Umfragen erstellen und verwalten darf.")

    defaults = ui.card("Standardwerte", "<div class='wc-switches'>"
        + ui.switch("default_multiple", "Mehrfachauswahl erlauben", conf.get("default_multiple"),
                    desc="Mitglieder dürfen mehrere Optionen wählen.")
        + ui.switch("default_anonymous", "Anonym abstimmen", conf.get("default_anonymous"),
                    desc="Nur Zähler sichtbar, keine Namen.")
        + "</div>", icon="bi-toggles",
        desc="Vorbelegung für neue Umfragen – lässt sich pro Umfrage ändern.")

    overrides = conf.get("messages") or {}
    fields = []
    for key in OVERRIDABLE_KEYS:
        label, hint = _OVERRIDE_LABELS.get(key, (key, None))
        fields.append(ui.field(label, ui.text_input(f"ovr_{key}", overrides.get(key, ""),
                                                    placeholder=STRINGS["de"].get(key, "")),
                               help=hint, wide=True))
    texts = ui.card("Eigene Texte", ui.grid(*fields), icon="bi-chat-left-text",
                    desc="Leer lassen = Standardtext der gewählten Sprache (als grauer Platzhalter sichtbar).")

    save = ui.save_row("Einstellungen speichern")
    # Ein Formular über zwei Reiter (Einstellungen + Texte) – beide speichern alles.
    return ui.form(
        "/cogs/poll",
        ui.tab("einstellungen", "Einstellungen", "bi-sliders", access + defaults + save)
        + ui.tab("texte", "Texte", "bi-chat-left-text", texts + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _render_create_form(ui, guild, conf, csrf) -> str:
    max_opts = int(conf.get("max_options", 10))
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    form = ui.form(
        "/cogs/poll",
        ui.grid(
            ui.field("Frage", ui.text_input("question", "", placeholder="Beste Pizza?", attrs={"maxlength": 256}),
                     wide=True),
            ui.field(f"Optionen (eine pro Zeile, 2–{max_opts})",
                     ui.textarea("options", "", rows=5, placeholder="Margherita\nSalami\nHawaii"),
                     help="Jede Zeile wird ein Button. Die Obergrenze stellst du unter „Einstellungen“ ein.", wide=True),
            ui.field("Kanal", ui.select("channel", text_items), help="Hier wird die Umfrage gepostet."),
            ui.field("Laufzeit (optional)", ui.text_input("duration", "", placeholder="z. B. 2h, 30m, 1d"),
                     help="Leer = läuft, bis sie geschlossen wird."),
        )
        + "<div class='wc-switches'>"
        + ui.switch("multiple", "Mehrfachauswahl erlauben", conf.get("default_multiple"),
                    desc="Mitglieder dürfen mehrere Optionen wählen.")
        + ui.switch("anonymous", "Anonym abstimmen", conf.get("default_anonymous"),
                    desc="Nur Zähler sichtbar, keine Namen.")
        + "</div>"
        + ui.actions(ui.button("Umfrage posten", icon="bi-send")),
        csrf=csrf, hidden={"form": "create", "guild": guild.id},
    )
    return ui.card("Neue Umfrage", form, icon="bi-plus-square",
                   desc="Die Umfrage wird sofort im gewählten Kanal gepostet (als Bot).")


def _render_polls_table(ui, guild, polls, csrf) -> str:
    if not polls:
        return ui.card(body=ui.empty(
            "bi-bar-chart", "Für diesen Server sind keine Umfragen gespeichert.",
            "Starte eine im Reiter „Neue Umfrage“ oder in Discord mit <code>[p]poll create</code>."))
    rows = []
    for p in sorted(polls.values(), key=lambda x: x.get("created_ts", 0), reverse=True):
        _, total, voters = vote_counts(p)
        status = _status_word(p)
        pid = p["id"]
        channel = guild.get_channel(p.get("channel_id")) if p.get("channel_id") else None
        ch_name = f"#{channel.name}" if channel is not None else "—"
        is_closed = bool(p.get("closed") or p.get("ended"))
        hidden = {"form": "action", "guild": guild.id, "poll_id": pid}
        results = ui.button("Ergebnis", icon="bi-bar-chart", kind="ghost", small=True,
                            href=f"/cogs/poll?guild={guild.id}&poll={quote(str(pid))}")
        toggle = ui.form(
            "/cogs/poll",
            ui.button("Öffnen" if is_closed else "Schließen", icon="bi-unlock" if is_closed else "bi-lock",
                      kind="ghost", small=True,
                      attrs={"title": "Abstimmung wieder öffnen" if is_closed else "Abstimmung beenden"}),
            csrf=csrf, hidden={**hidden, "action": "reopen" if is_closed else "close"},
        )
        delete = ui.form(
            "/cogs/poll",
            ui.button("", icon="bi-trash", kind="danger", small=True, attrs={"title": "Umfrage löschen"}),
            csrf=csrf, hidden={**hidden, "action": "delete"},
            confirm="Die Umfrage, alle Stimmen und ihre Discord-Nachricht werden gelöscht.",
        )
        tags = ["Mehrfachauswahl" if p.get("multiple") else "eine Stimme", "anonym" if p.get("anonymous") else "öffentlich"]
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc((p.get('question') or '')[:70])}</div>"
            f"<div class='wc-cell-sub'><span class='mono'>{_esc(pid)}</span> · {_esc(' · '.join(tags))}</div>",
            _esc(ch_name),
            f"<span class='mono'>{total}</span>"
            f"<div class='wc-cell-sub'>{voters} Teilnehmer</div>",
            ui.badge(status, _STATUS_TONE.get(status, "muted")),
            f"><div class='wc-row-actions'>{results}{toggle}{delete}</div>",
        ))
    return ui.card(
        "Umfragen", ui.table(["Frage", "Kanal", "Stimmen", "Status", ">"], rows,
                             search=True, search_placeholder="Nach Frage, ID oder Kanal suchen …", id="pl-polls"),
        icon="bi-list-check",
        desc="Neueste zuerst. „Öffnen“ setzt auch eine abgelaufene Laufzeit zurück.",
    )


def _render_results(ui, guild, poll: dict) -> str:
    counts, total, voters = vote_counts(poll)
    options = poll.get("options") or []
    anonymous = bool(poll.get("anonymous"))
    winning = max(counts) if counts else 0
    finished = bool(poll.get("closed") or poll.get("ended"))

    blocks = []
    for idx, opt in enumerate(options):
        c = counts[idx] if idx < len(counts) else 0
        pct = int(round((c / total) * 100)) if total else 0
        trophy = " 🏆" if finished and c == winning and c > 0 else ""
        voters_line = ""
        if not anonymous:
            names = [
                _esc(v.get("name", "?"))
                for v in (poll.get("votes") or {}).values()
                if idx in (v.get("choices") or [])
            ]
            if names:
                voters_line = f"<div class='wc-help'>{', '.join(names)}</div>"
        blocks.append(
            "<div class='meter'>"
            f"<div class='mlabel'><span>{idx + 1}. {_esc(opt)}{trophy}</span>"
            f"<span class='v'>{c} · {pct}%</span></div>"
            f"<div class='bar'><span style='width:{pct}%'></span></div>"
            f"{voters_line}</div>"
        )

    status = _status_word(poll)
    back = ui.button("Zurück zu den Umfragen", icon="bi-arrow-left", kind="ghost", small=True,
                     href=f"/cogs/poll?guild={guild.id}#umfragen")
    meta = [
        f"<span class='mono'>{_esc(poll.get('id'))}</span>",
        "Mehrfachauswahl" if poll.get("multiple") else "Eine Stimme",
        "anonym" if anonymous else "öffentlich",
        ui.badge(status, _STATUS_TONE.get(status, "muted")),
    ]
    # Zurück-Button im Kopftext (ui.hero(actions=…) bricht auf dem Handy nicht um).
    head = ui.hero("bi-bar-chart", poll.get("question") or "Umfrage",
                   " · ".join(meta) + f"<br><br>{back}") + ui.stats([
        ("Stimmen", total, "bi-check2-square", None, None),
        ("Teilnehmer", voters, "bi-people", None, None),
    ])
    body = (f"<div class='kv'>{''.join(blocks)}</div>" if blocks
            else ui.empty("bi-bar-chart", "Diese Umfrage hat keine Optionen."))
    note = "" if not anonymous else ui.callout("Anonyme Umfrage – es werden nur Zähler angezeigt, keine Namen.")
    return head + ui.card("Ergebnis", note + body, icon="bi-bar-chart",
                          desc="Anteil an allen abgegebenen Stimmen." + (" 🏆 = meiste Stimmen." if finished else ""))


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
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
        raise web.HTTPFound("/cogs/poll?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    if form == "settings":
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)
        mode = (data.get("allow_create") or "manager").lower()
        if mode in ("everyone", "manager"):
            await gconf.allow_create.set(mode)
        try:
            mx = int(data.get("max_options") or 10)
            await gconf.max_options.set(max(2, min(HARD_OPTION_LIMIT, mx)))
        except (TypeError, ValueError):
            pass
        roles = []
        for rid in data.getall("manager_roles", []):
            # Nur real existierende Rollen speichern (verhindert tote/gefälschte IDs).
            if str(rid).isdigit() and guild.get_role(int(rid)) is not None:
                roles.append(int(rid))
        await gconf.manager_roles.set(roles)
        await gconf.default_multiple.set("default_multiple" in data)
        await gconf.default_anonymous.set("default_anonymous" in data)
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)
        raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=Gespeichert")

    if form == "create":
        from .poll import parse_duration  # zur Laufzeit (vermeidet Import-Zyklus)

        question = (data.get("question") or "").strip()
        options = [o.strip() for o in (data.get("options") or "").splitlines() if o.strip()]
        max_opts = await gconf.max_options()
        if not question or len(options) < 2:
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&err=" + quote("Bitte Frage und mind. 2 Optionen angeben"))
        if len(options) > max_opts:
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&err=" + quote(f"Zu viele Optionen (max. {max_opts})"))
        channel = guild.get_channel(_one_id(data.get("channel")) or 0)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            # Nur Text-/Thread-Kanäle: sonst entstünde eine Umfrage ohne Nachricht (Leiche).
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&err=" + quote("Bitte einen Textkanal wählen"))
        end_ts = None
        dur = (data.get("duration") or "").strip()
        if dur:
            secs = parse_duration(dur)
            if secs is None:
                raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&err=" + quote("Dauer nicht erkannt (z. B. 2h, 30m, 1d)"))
            end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + secs
        poll = await cog.create_poll(
            guild, question=question, options=options, channel_id=channel.id,
            author_id=cog.bot.user.id, end_ts=end_ts,
            multiple="multiple" in data, anonymous="anonymous" in data,
        )
        if not poll.get("message_id"):
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&err=" + quote(
                "Umfrage gespeichert, aber das Posten ist fehlgeschlagen (Rechte im Kanal prüfen)"))
        raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote("Umfrage erstellt"))

    if form == "action":
        poll_id = data.get("poll_id")
        action = data.get("action")
        async with gconf.polls() as polls:
            poll = polls.get(poll_id)
            if poll is None:
                raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=Umfrage+nicht+gefunden")
            if action == "close":
                poll["closed"] = True
                polls[poll_id] = poll
                snapshot = dict(poll)
            elif action == "reopen":
                poll["closed"] = False
                poll["ended"] = False
                poll["announced"] = False
                poll["end_ts"] = None
                polls[poll_id] = poll
                snapshot = dict(poll)
            elif action == "delete":
                snapshot = polls.pop(poll_id, None)
            else:
                snapshot = None
        if action in ("close", "reopen") and snapshot:
            await cog.refresh_poll_message(guild, snapshot)
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=Aktualisiert")
        if action == "delete" and snapshot:
            if snapshot.get("channel_id") and snapshot.get("message_id"):
                channel = guild.get_channel(snapshot["channel_id"])
                if channel is not None:
                    try:
                        msg = await channel.fetch_message(snapshot["message_id"])
                        await msg.delete()
                    except Exception:  # noqa: BLE001
                        pass
            raise web.HTTPFound(f"/cogs/poll?guild={guild.id}&ok=" + quote("Gelöscht"))

    raise web.HTTPFound(f"/cogs/poll?guild={guild.id}")
