"""WebCore-Dashboard für TwitchLive.

* GET  -> Seite rendern (Reiter Streamer · Hinzufügen/Bearbeiten · Vorschau · Einstellungen ·
  Live-Rolle · Twitch-Zugang)
* POST -> Aktion ausführen, danach Redirect mit ``?ok=``/``?err=`` (Toast)

Nur UI-Kit (``request.app["webcore"].ui``), kein eigenes CSS. Rechte: Server ausschließlich über
``webcore.visible_guilds`` (GET = Ansehen, POST = Bearbeiten), Live-Rolle zusätzlich über
``webcore.can_grant_role``, botweite Werte (Intervall, „Jetzt abfragen“) nur mit ``has_full_scope``.
Zugangsdaten werden nie angezeigt – nur „gesetzt/nicht gesetzt“.
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote

import discord
from aiohttp import web

from .embed import (
    LIMIT_TEMPLATE, TWITCH_COLOR, cap, fmt_duration, render_template, stream_url, thumbnail,
)
from .strings import LANGUAGES, default_message, t

SLUG = "twitchlive"
BASE = f"/cogs/{SLUG}"
TITLE = "Twitch-Live"
MEMBER_SELECT_MAX = 300   # darüber: Freitextfeld statt Auswahlliste


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _ago(ts, now) -> str:
    if not ts:
        return "—"
    sec = max(0, int(now - float(ts)))
    if sec < 90:
        return f"vor {sec} s"
    if sec < 5400:
        return f"vor {sec // 60} min"
    return f"vor {sec // 3600} Std."


def _in(ts, now) -> str:
    if not ts:
        return "—"
    sec = int(float(ts) - now)
    return "gleich" if sec <= 1 else f"in {sec} s"


def _redirect(guild_id, *, ok: str | None = None, err: str | None = None, extra: str = "") -> web.HTTPFound:
    q = f"?guild={guild_id}" if guild_id else "?"
    if extra:
        q += "&" + extra
    if ok:
        q += "&ok=" + quote(ok)
    if err:
        q += "&err=" + quote(err)
    return web.HTTPFound(BASE + q)


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


async def _guilds(request):
    webcore = request.app["webcore"]
    guilds = await webcore.visible_guilds(request)
    return sorted(guilds, key=lambda g: g.name.lower())


def _pick(guilds, raw):
    raw = str(raw or "")
    if raw.isdigit():
        for g in guilds:
            if g.id == int(raw):
                return g
    return None


# --------------------------------------------------------------------------- #
#  API-Status
# --------------------------------------------------------------------------- #
def api_state(cog, creds: bool, now: float):
    """-> (Label, Ton, Hinweis) für Kennzahl/Status-Karte. Enthält nie Secrets."""
    st = cog.status or {}
    state = st.get("state")
    if not creds:
        return "Fehlt", "warn", "Zugangsdaten fehlen – [p]twitchset creds"
    if state == "ok":
        return "Verbunden", "ok", f"letzte Abfrage {_ago(st.get('last_ok'), now)}"
    if state == "rate_limited":
        return "Rate-Limit", "warn", "Twitch bremst – Abfrage pausiert kurz"
    if state == "auth_error":
        return "Ungültig", "bad", "Zugangsdaten ungültig – Client-ID/Secret prüfen"
    if state == "error":
        return "Störung", "bad", cap(st.get("error") or "Twitch nicht erreichbar", 80)
    return "Startet …", "info", "erste Abfrage läuft gleich"


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    webcore = request.app["webcore"]
    ui = webcore.ui
    guilds = await _guilds(request)
    guild = _pick(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": TITLE, "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}

    csrf = request.get("webcore_csrf", "")
    conf = await cog.config.guild(guild).all()
    chans = conf.get("channels") or {}
    state = conf.get("state") or {}
    creds = await cog.has_credentials()
    full = await webcore.has_full_scope(request)
    now = cog._now()

    guild_picker = ""
    if not request.get("wc_switcher"):
        guild_picker = ui.card(body=ui.form(
            BASE, ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
            csrf="", method="get",
        ))

    live_now = [l for l in state if l in chans]
    enabled = sum(1 for e in chans.values() if (e or {}).get("enabled", True))
    api_label, api_tone, api_hint = api_state(cog, creds, now)
    stats = conf.get("stats") or {}
    today = int(stats.get("today") or 0) if stats.get("day") == _today(cog, now) else 0
    head = ui.hero(
        "bi-twitch", "",
        "Sobald ein Streamer auf <b>Twitch</b> live geht, postet der Bot eine Meldung mit Titel, Spiel, "
        "Vorschaubild und Button „Zum Stream“ – genau einmal pro Stream, optional mit Rollen-Ping.",
    ) + ui.stats([
        ("Streamer", len(chans), "bi-person-video3", f"{enabled} aktiv" if chans else None, None),
        ("Gerade live", len(live_now), "bi-broadcast",
         cap(", ".join(sorted(live_now)), 60) if live_now else None, "bad" if live_now else None),
        ("Twitch-API", api_label, "bi-plug", api_hint, api_tone),
        ("Meldungen heute", today, "bi-send", f"{int(stats.get('total') or 0)} insgesamt", None),
    ])
    if not creds:
        head += ui.callout(
            "<b>Zugangsdaten fehlen:</b> Ohne Twitch-Client-ID und -Secret fragt der Bot Twitch nicht ab und "
            "postet keine Meldungen. Die Anleitung steht im Reiter <b>Twitch-Zugang</b>. "
            + ui.goto("Zur Anleitung", "zugang"),
            tone="warn",
        )

    edit_login = (request.query.get("edit") or "").strip().lower()
    editing = edit_login if edit_login in chans else None
    body = (
        ui.tab("streamer", "Streamer", "bi-person-video3", _tab_streamers(cog, ui, guild, conf, csrf, now),
               count=len(chans))
        + ui.tab("editor", f"Bearbeiten: {editing}" if editing else "Hinzufügen",
                 "bi-pencil-square" if editing else "bi-plus-square",
                 _tab_editor(cog, ui, guild, conf, csrf, editing))
        + ui.tab("vorschau", "Vorschau", "bi-eye", _tab_preview(cog, ui, guild, conf, csrf, request, now))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", _tab_settings(ui, guild, conf, csrf))
        + ui.tab("liverole", "Live-Rolle", "bi-person-badge", _tab_liverole(cog, ui, guild, conf, csrf))
        + ui.tab("zugang", "Twitch-Zugang", "bi-key", await _tab_access(cog, ui, guild, csrf, creds, full, now))
    )
    return {"title": TITLE, "content": head + guild_picker + body}


def _today(cog, now):
    from .twitchlive import _today as today
    return today(now)


def _avatar(cog, login: str, size: int = 32) -> str:
    url = (cog.user_info(login) or {}).get("profile_image_url") or ""
    if url.startswith("https://"):
        return (f"<img src='{_esc(url)}' alt='' loading='lazy' referrerpolicy='no-referrer' "
                f"style='width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;flex-shrink:0'>")
    return (f"<span style='width:{size}px;height:{size}px;border-radius:50%;display:inline-grid;place-items:center;"
            f"flex-shrink:0;background:var(--panel-3);color:#9146ff'><i class='bi bi-twitch'></i></span>")


def _channel_label(guild, cid, default_cid=None) -> str:
    if cid:
        ch = guild.get_channel(int(cid))
        return f"#{ch.name}" if ch else f"{cid} (gelöscht)"
    ch = guild.get_channel(int(default_cid)) if default_cid else None
    return f"Standard (#{ch.name})" if ch else "— kein Kanal —"


def _tab_streamers(cog, ui, guild, conf, csrf, now) -> str:
    chans = conf.get("channels") or {}
    state = conf.get("state") or {}
    default_cid = conf.get("default_channel")
    rows = []
    no_target = []
    for login in sorted(chans, key=lambda l: (l not in state, l)):   # live zuerst
        e = chans[login] or {}
        sess = state.get(login)
        name = (cog.user_info(login) or {}).get("display_name") or e.get("display_name") or login
        target = cog.target_channel(guild, conf, e)
        if target is None:
            no_target.append(login)
        role = guild.get_role(int(e["ping_role"])) if e.get("ping_role") else None
        if sess is not None:
            started = sess.get("started_at")
            dur = fmt_duration(now - float(started)) if started else ""
            status = ui.badge(f"live · {int(sess.get('viewers') or 0)} Zuschauer", "bad")
            sub = cap(" · ".join(x for x in (sess.get("game") or "", dur) if x), 80)
        elif not e.get("enabled", True):
            status, sub = ui.badge("pausiert", "warn"), ""
        else:
            status, sub = ui.badge("offline", "muted"), ""
        tags = " " + ui.badge("eigener Text", "info") if e.get("message") else ""
        ident = (
            "<div style='display:flex;align-items:center;gap:10px'>" + _avatar(cog, login)
            + f"<div><div class='wc-cell-title'>{_esc(name)}{tags}</div>"
            f"<div class='wc-cell-sub'><a href='{_esc(stream_url(login))}' target='_blank' rel='noopener'>"
            f"twitch.tv/{_esc(login)}</a>" + (f" · {_esc(sub)}" if sub else "") + "</div></div></div>"
        )
        hidden = {"guild": guild.id, "login": login}
        edit = ui.button("", icon="bi-pencil", kind="ghost", small=True, attrs={"title": "Bearbeiten"},
                         href=f"{BASE}?guild={guild.id}&edit={quote(login)}#editor")
        test = ui.form(BASE, ui.button("", icon="bi-send", kind="ghost", small=True,
                                       attrs={"title": "Testmeldung posten (ohne Ping)"}),
                       csrf=csrf, hidden={"action": "test", **hidden})
        enabled = e.get("enabled", True)
        toggle = ui.form(BASE, ui.button("", icon="bi-pause-fill" if enabled else "bi-play-fill", kind="ghost",
                                         small=True, attrs={"title": "Pausieren" if enabled else "Fortsetzen"}),
                         csrf=csrf, hidden={"action": "toggle", **hidden})
        delete = ui.form(BASE, ui.button("", icon="bi-trash", kind="danger", small=True,
                                         attrs={"title": "Entfernen"}),
                         csrf=csrf, hidden={"action": "delete", **hidden},
                         confirm=f"{name} wirklich entfernen? Eine laufende Live-Meldung wird beendet.")
        rows.append(ui.row(
            ident,
            _esc(_channel_label(guild, e.get("channel_id"), default_cid)),
            _esc(f"@{role.name}") if role else "<span class='wc-muted'>—</span>",
            status,
            f"><div class='wc-row-actions'>{edit}{test}{toggle}{delete}</div>",
        ))
    if not rows:
        return ui.card(body=ui.empty(
            "bi-twitch", "Noch keine Streamer.",
            "Füge den ersten Twitch-Kanal hinzu – z. B. deinen eigenen.",
            action=ui.goto("Streamer hinzufügen", "editor", icon="bi-plus-lg", kind="accent", small=False),
        ))
    warn = ""
    if no_target:
        warn = ui.callout(
            "Ohne Zielkanal (kein eigener und kein Standardkanal): <b>" + _esc(", ".join(no_target))
            + "</b> – setze einen Standardkanal unter <b>Einstellungen</b>.", tone="warn")
    table = ui.table(["Streamer", "Kanal", "Ping", "Status", ">"], rows, search=len(rows) > 6,
                     search_placeholder="Streamer suchen …", id="tw-list")
    return warn + ui.card(
        "Beobachtete Streamer", table, icon="bi-person-video3",
        desc="Status aus der letzten Abfrage. <i class='bi bi-send'></i> postet eine Testmeldung ohne Ping.",
        actions=ui.goto("Hinzufügen", "editor", icon="bi-plus-lg", kind="ghost"),
    )


def _channel_items(guild):
    return [(c.id, f"#{c.name}") for c in guild.text_channels]


def _role_items(guild):
    roles = [r for r in guild.roles if not r.is_default() and not getattr(r, "managed", False)]
    roles.sort(key=lambda r: getattr(r, "position", 0), reverse=True)
    return [(r.id, f"@{r.name}") for r in roles]


def _placeholder_help() -> str:
    return ("Platzhalter: <code>{streamer}</code> <code>{title}</code> <code>{game}</code> <code>{url}</code> "
            "<code>{ping}</code> (Ping-Rolle; fehlt er, wird der Ping vorangestellt). "
            f"Max. {LIMIT_TEMPLATE} Zeichen, die fertige Nachricht wird auf 2000 gekürzt.")


def _tab_editor(cog, ui, guild, conf, csrf, editing) -> str:
    chans = conf.get("channels") or {}
    e = chans.get(editing) or {} if editing else {}
    lang = conf.get("language") or "de"
    default_cid = conf.get("default_channel")
    default_ch = guild.get_channel(int(default_cid)) if default_cid else None
    none_label = f"— Standardkanal (#{default_ch.name}) —" if default_ch else "— Standardkanal (nicht gesetzt) —"
    if editing:
        login_field = ui.field(
            "Twitch-Login", ui.text_input("login_show", editing, attrs={"disabled": True}),
            help=f"<a href='{_esc(stream_url(editing))}' target='_blank' rel='noopener'>twitch.tv/{_esc(editing)}</a>"
                 " – der Login lässt sich nicht ändern (entfernen und neu anlegen).")
    else:
        login_field = ui.field(
            "Twitch-Login", ui.text_input("login", "", placeholder="z. B. matters86 oder https://twitch.tv/matters86",
                                          attrs={"required": True, "maxlength": 80, "autocomplete": "off"}),
            help="Der Kanalname aus der Twitch-Adresse. Mit Zugangsdaten wird er bei Twitch geprüft.")
    grid = ui.grid(
        login_field,
        ui.field("Zielkanal", ui.select("channel", _channel_items(guild), e.get("channel_id"), none_label=none_label),
                 help="Hier erscheint die Live-Meldung. Der Bot braucht dort „Nachrichten senden“ und "
                      "„Links einbetten“."),
        ui.field("Ping-Rolle", ui.select("ping_role", _role_items(guild), e.get("ping_role"),
                                         none_label="— kein Ping —"),
                 help="Wird nur bei echten Live-Meldungen erwähnt – nie @everyone/@here. Nicht erwähnbare Rollen "
                      "pingen nur, wenn der Bot „@everyone erwähnen“ darf."),
        ui.field("Status", ui.switches(ui.switch("enabled", "Meldungen aktiv", e.get("enabled", True) if editing else True,
                                                 desc="Aus = pausiert, der Streamer bleibt in der Liste."))),
        ui.field("Eigene Nachricht (optional)",
                 ui.textarea("message", e.get("message") or "", rows=3,
                             placeholder=conf.get("default_message") or default_message(lang)),
                 help="Leer = Standardtext aus den Einstellungen. " + _placeholder_help(), wide=True),
    )
    actions = ""
    if editing:
        actions = ui.button("Neuer Streamer", icon="bi-plus-lg", kind="ghost", small=True,
                            href=f"{BASE}?guild={guild.id}#editor")
    hidden = {"action": "save" if editing else "add", "guild": guild.id}
    if editing:
        hidden["login"] = editing
    form = ui.form(
        BASE,
        ui.card(f"Streamer bearbeiten: {editing}" if editing else "Streamer hinzufügen", grid,
                icon="bi-pencil-square" if editing else "bi-plus-square", actions=actions,
                desc="Pro Server beliebig viele Streamer (max. 100), jeweils mit eigenem Kanal, Ping und Text.")
        + ui.save_row("Speichern" if editing else "Hinzufügen"),
        csrf=csrf, hidden=hidden, savebar=bool(editing),
    )
    return form


# --------------------------------------------------------------------------- #
#  Vorschau
# --------------------------------------------------------------------------- #
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ROLE_MENTION = re.compile(r"&lt;@&amp;(\d+)&gt;")


def _discord_text(guild, text: str) -> str:
    """Nachrichtentext grob wie Discord darstellen (escaped; **fett**, Rollen-Erwähnungen)."""
    out = _esc(text)

    def role(m):
        r = guild.get_role(int(m.group(1))) if guild is not None else None
        name = r.name if r else "gelöschte Rolle"
        return (f"<span style='background:rgba(88,101,242,.3);color:#c9cdfb;border-radius:4px;padding:0 3px'>"
                f"@{_esc(name)}</span>")
    out = _ROLE_MENTION.sub(role, out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    return out.replace("\n", "<br>")


def _embed_mock(cog, *, login, name, stream, lang, now, ended=None) -> str:
    color = "#%06x" % (0x6C6C75 if ended else TWITCH_COLOR)
    avatar = _avatar(cog, login, 22)
    title = _esc(cap((stream.get("title") or "").strip() or t(lang, "no_title"), 256))
    if ended:
        fields = [(t(lang, "field_games"), ended["games"]), (t(lang, "field_duration"), ended["duration"])]
        desc = f"<div style='margin:6px 0'>{_discord_text(None, t(lang, 'ended_desc', streamer=name, duration=ended['duration']))}</div>"
        img = ""
        footer = t(lang, "footer_ended")
    else:
        fields = [(t(lang, "field_game"), stream.get("game_name") or t(lang, "no_game")),
                  (t(lang, "field_viewers"), f"{int(stream.get('viewer_count') or 0):,}".replace(",", "."))]
        desc = ""
        url = thumbnail(stream, now)
        if url:
            img = (f"<img src='{_esc(url)}' alt='Vorschaubild' loading='lazy' referrerpolicy='no-referrer' "
                   "style='width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:6px;margin-top:10px;"
                   "background:var(--panel-3)'>")
        else:
            img = ("<div style='aspect-ratio:16/9;border-radius:6px;margin-top:10px;background:var(--panel-3);"
                   "display:grid;place-items:center;color:var(--muted);text-align:center;font-size:.8rem'>"
                   "<div><i class='bi bi-image' style='font-size:1.6rem'></i><br>Vorschaubild des Streams "
                   "(1280×720, wird bei jeder Meldung frisch geladen)</div></div>")
        footer = t(lang, "footer_live") + " · " + ("heute" if lang == "de" else "today")
    cells = "".join(
        f"<div><div style='font-weight:700;font-size:.8rem'>{_esc(k)}</div>"
        f"<div style='font-size:.85rem'>{_esc(v)}</div></div>" for k, v in fields)
    button = (f"<div style='margin-top:8px'><span class='btn-ghost btn-sm' style='pointer-events:none'>"
              f"<i class='bi bi-box-arrow-up-right'></i><span>"
              f"{_esc(t(lang, 'button_channel' if ended else 'button_watch'))}</span></span></div>")
    return (
        f"<div style='border-left:4px solid {color};background:var(--panel-3);border-radius:6px;padding:10px 14px;"
        "max-width:520px;margin-top:6px'>"
        f"<div style='display:flex;align-items:center;gap:8px;font-size:.82rem;font-weight:600'>{avatar}"
        f"{_esc(name)}</div>"
        f"<div style='font-weight:700;margin-top:6px;color:#00a8fc'>{title}</div>{desc}"
        f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-top:8px'>"
        f"{cells}</div>{img}"
        f"<div style='font-size:.72rem;color:var(--muted);margin-top:8px'>{_esc(footer)}</div></div>{button}"
    )


def _message_mock(inner: str) -> str:
    return (
        "<div style='display:flex;gap:12px;align-items:flex-start'>"
        "<span style='width:40px;height:40px;border-radius:50%;flex-shrink:0;display:grid;place-items:center;"
        "background:var(--accent-soft);color:var(--accent)'><i class='bi bi-robot'></i></span>"
        f"<div style='min-width:0;flex:1'>{inner}</div></div>"
    )


def _tab_preview(cog, ui, guild, conf, csrf, request, now) -> str:
    chans = conf.get("channels") or {}
    state = conf.get("state") or {}
    lang = conf.get("language") or "de"
    sel = (request.query.get("preview") or "").strip().lower()
    if sel not in chans:
        # Standard: ein gerade live Streamer, sonst der erste aktive, sonst der erste.
        order = sorted(chans, key=lambda l: (l not in state, not (chans[l] or {}).get("enabled", True), l))
        sel = order[0] if order else None
    login = sel or "deinkanal"
    entry = chans.get(sel) or {}
    name = ((cog.user_info(login) or {}).get("display_name") or entry.get("display_name") or login)
    sess = state.get(sel) if sel else None
    if sess is not None:
        stream = {"title": sess.get("title"), "game_name": sess.get("game"), "viewer_count": sess.get("viewers"),
                  "thumbnail_url": sess.get("thumbnail_url") or ""}
        source = "Aktuelle Daten des laufenden Streams."
    else:
        stream = {"title": "Ranked-Grind bis Diamant – !discord", "game_name": "Just Chatting", "viewer_count": 128,
                  "thumbnail_url": ""}
        source = "Beispieldaten – der Streamer ist gerade offline."
    role = guild.get_role(int(entry["ping_role"])) if entry.get("ping_role") else None
    template = entry.get("message") or conf.get("default_message") or default_message(lang)
    content = render_template(
        template, streamer=discord.utils.escape_markdown(name),
        title=cap(stream.get("title") or t(lang, "no_title"), 256),
        game=stream.get("game_name") or t(lang, "no_game"), url=stream_url(login),
        ping=role.mention if role is not None else "",
    )
    target = cog.target_channel(guild, conf, entry) if sel else None

    picker = ""
    if chans:
        picker = ui.form(BASE, ui.grid(ui.field(
            "Streamer", ui.select("preview", [(l, (chans[l] or {}).get("display_name") or l) for l in sorted(chans)],
                                  sel, autosubmit=True),
            help=_esc(source))), csrf="", method="get", hidden={"guild": guild.id})
    else:
        picker = ui.callout("Noch kein Streamer angelegt – die Vorschau zeigt Beispielwerte.", tone="info")

    live = ui.card(
        "Live-Meldung", picker + _message_mock(
            f"<div style='font-size:.92rem'>{_discord_text(guild, content)}</div>"
            + _embed_mock(cog, login=login, name=name, stream=stream, lang=lang, now=now)),
        icon="bi-broadcast",
        desc=("Zielkanal: <b>" + _esc(f"#{target.name}" if target else "— keiner —") + "</b>"
              + (" · Ping: <b>" + _esc(f"@{role.name}") + "</b>" if role else " · kein Ping")),
    )
    started = now - 3 * 3600 - 17 * 60
    if (conf.get("end_action") or "edit") == "delete":
        end_body = ui.callout("Nach dem Stream wird die Meldung <b>gelöscht</b>.", tone="info", icon="bi-trash")
    else:
        dur = fmt_duration(now - (float(sess["started_at"]) if sess and sess.get("started_at") else started), lang)
        games = ", ".join((sess or {}).get("games") or [stream.get("game_name") or t(lang, "no_game")])
        end_body = _message_mock(
            f"<div style='font-size:.92rem'>{_discord_text(guild, t(lang, 'ended_content', streamer=name))}</div>"
            + _embed_mock(cog, login=login, name=name, stream=stream, lang=lang, now=now,
                          ended={"games": games, "duration": dur}))
    ended = ui.card("Nach Stream-Ende", end_body, icon="bi-stop-circle",
                    desc="So sieht die Meldung aus, wenn der Stream vorbei ist (Einstellung „Bei Stream-Ende“).")
    test = ""
    if sel:
        test = ui.form(BASE, ui.actions(ui.button("Testmeldung posten", icon="bi-send", kind="ghost")),
                       csrf=csrf, hidden={"action": "test", "guild": guild.id, "login": sel})
        test = ui.card("Im Discord ausprobieren", "<p class='wc-muted' style='margin-top:0'>Postet die Meldung "
                       "mit Hinweis „Testmeldung“ in den Zielkanal – ohne echten Ping.</p>" + test, icon="bi-send")
    return ui.columns(live, ended + test)


# --------------------------------------------------------------------------- #
#  Einstellungen · Live-Rolle · Zugang
# --------------------------------------------------------------------------- #
def _tab_settings(ui, guild, conf, csrf) -> str:
    lang = conf.get("language") or "de"
    grid = ui.grid(
        ui.field("Standard-Zielkanal", ui.select("default_channel", _channel_items(guild), conf.get("default_channel"),
                                                 none_label="— keiner —"),
                 help="Gilt für alle Streamer ohne eigenen Kanal."),
        ui.field("Bei Stream-Ende", ui.select("end_action", [
            ("edit", "Nachricht bearbeiten („war live · Dauer“)"), ("delete", "Nachricht löschen")],
            conf.get("end_action") or "edit"),
            help="Bearbeiten zeigt Dauer, gespielte Spiele und max. Zuschauer; der Ping wird dabei nicht wiederholt."),
        ui.field("Sprache der Meldungen", ui.select("language", list(LANGUAGES.items()), lang),
                 help="Embed-Texte, Button und Antworten der Befehle."),
        ui.field("Standardtext", ui.textarea("default_message", conf.get("default_message") or "", rows=3,
                                             placeholder=default_message(lang)),
                 help="Leer = eingebauter Text der Sprache. " + _placeholder_help(), wide=True),
    )
    return ui.form(
        BASE, ui.card("Meldungen", grid, icon="bi-sliders", desc="Gilt für alle Streamer auf diesem Server.")
        + ui.save_row("Einstellungen speichern"),
        csrf=csrf, hidden={"action": "settings", "guild": guild.id}, savebar=True,
    )


def _tab_liverole(cog, ui, guild, conf, csrf) -> str:
    links = conf.get("links") or {}
    rid = conf.get("live_role")
    role = guild.get_role(int(rid)) if rid else None
    warn = ""
    if role is not None and not cog.role_manageable(guild, role):
        warn = ui.callout("Der Bot kann diese Rolle nicht vergeben (Recht „Rollen verwalten“ fehlt oder die Rolle "
                          "liegt über der Bot-Rolle).", tone="warn")
    settings = ui.form(
        BASE,
        ui.card("Live-Rolle", warn + ui.grid(ui.field(
            "Rolle während des Streams", ui.select("live_role", _role_items(guild), rid, none_label="— aus —"),
            help="Verknüpfte Mitglieder bekommen diese Rolle, solange ihr Twitch-Kanal live ist, und verlieren "
                 "sie nach dem Stream wieder. Nur Rollen ohne Verwaltungsrechte unter deiner höchsten Rolle."))
            + ui.save_row("Live-Rolle speichern"),
            icon="bi-person-badge", desc="Optional – z. B. um Live-Mitglieder in der Mitgliederliste hervorzuheben."),
        csrf=csrf, hidden={"action": "liverole", "guild": guild.id}, savebar=True,
    )
    rows = []
    for uid, login in sorted(links.items(), key=lambda kv: kv[1]):
        member = guild.get_member(int(uid)) if str(uid).isdigit() else None
        who = member.display_name if member else f"{uid} (nicht auf dem Server)"
        rm = ui.form(BASE, ui.button("", icon="bi-x-lg", kind="danger", small=True, attrs={"title": "Verknüpfung lösen"}),
                     csrf=csrf, hidden={"action": "unlink", "guild": guild.id, "user": uid},
                     confirm=f"Verknüpfung {who} ↔ {login} lösen?")
        rows.append(ui.row(f"<div class='wc-cell-title'>{_esc(who)}</div>",
                           f"<a href='{_esc(stream_url(login))}' target='_blank' rel='noopener'>{_esc(login)}</a>",
                           f"><div class='wc-row-actions'>{rm}</div>"))
    members = [m for m in guild.members if not getattr(m, "bot", False)]
    if len(members) <= MEMBER_SELECT_MAX:
        member_ctl = ui.select("user", [(m.id, m.display_name) for m in sorted(members, key=lambda m: m.display_name.lower())],
                               None, none_label="— Mitglied wählen —")
    else:
        member_ctl = ui.text_input("user", "", placeholder="Nutzer-ID oder exakter Name")
    add = ui.form(BASE, ui.grid(
        ui.field("Mitglied", member_ctl),
        ui.field("Twitch-Login", ui.text_input("login", "", placeholder="z. B. matters86", attrs={"maxlength": 80})),
    ) + ui.save_row("Verknüpfen"), csrf=csrf, hidden={"action": "link", "guild": guild.id})
    table = ui.table(["Mitglied", "Twitch", ">"], rows, empty_text="Noch keine Verknüpfungen.")
    links_card = ui.card("Verknüpfungen Discord ↔ Twitch", table + ui.divider() + add, icon="bi-link-45deg",
                         desc="Welches Mitglied streamt auf welchem Kanal? Der Kanal muss zusätzlich im Reiter "
                              "„Streamer“ eingetragen sein.")
    return settings + links_card


async def _tab_access(cog, ui, guild, csrf, creds, full, now) -> str:
    st = cog.status or {}
    label, tone, hint = api_state(cog, creds, now)
    kv = [
        ("Zugangsdaten", ui.badge("gesetzt", "ok") if creds else ui.badge("nicht gesetzt", "warn")),
        ("API-Status", ui.badge(label, tone) + (f" <span class='wc-muted'>{_esc(hint)}</span>" if hint else "")),
        ("Letzte erfolgreiche Abfrage", _esc(_ago(st.get("last_ok"), now))),
        ("Nächste Abfrage", _esc(_in(st.get("next_poll"), now))),
        ("Intervall", _esc(f"{await cog._interval()} s")),
    ]
    if full:   # serverübergreifende Zahl nur für Owner/Allowlist
        kv.append(("Beobachtet (alle Server)", _esc(st.get("watched", 0))))
    if st.get("error") and st.get("state") in ("error", "rate_limited", "auth_error"):
        kv.append(("Letzter Fehler", f"{_esc(cap(st.get('error'), 120))} · {_esc(_ago(st.get('last_error'), now))}"))
    info = "<dl class='wc-kv'>" + "".join(f"<dt>{_esc(k)}</dt><dd>{v}</dd>" for k, v in kv) + "</dl>"
    owner_tools = ""
    if full:
        owner_tools = ui.divider() + ui.form(
            BASE, ui.grid(ui.field("Abfrage-Intervall", ui.number("interval", await cog._interval(), min=60, max=600,
                                                                  unit="Sekunden"),
                                   help="Botweit für alle Server (60–600). Twitch erlaubt großzügig viele "
                                        "Anfragen; 60 s ist ein guter Wert."))
            + ui.save_row("Intervall speichern"),
            csrf=csrf, hidden={"action": "interval", "guild": guild.id},
        ) + ui.form(BASE, ui.actions(ui.button("Jetzt abfragen", icon="bi-arrow-repeat", kind="ghost")),
                      csrf=csrf, hidden={"action": "poll", "guild": guild.id})
    status = ui.card("Verbindung zu Twitch", info + owner_tools, icon="bi-plug",
                     desc="Die Zugangsdaten werden nie angezeigt – nur, ob sie gesetzt sind.")
    steps = (
        "<ol style='margin:0;padding-left:20px;line-height:1.7'>"
        "<li>Auf <a href='https://dev.twitch.tv/console/apps' target='_blank' rel='noopener'>dev.twitch.tv/console"
        "</a> mit einem Twitch-Konto anmelden (Zwei-Faktor-Authentifizierung muss aktiv sein).</li>"
        "<li><b>Register Your Application</b>: Name frei wählbar (z. B. „Matters Discord Bot“), "
        "<b>OAuth Redirect URL</b> <code>http://localhost</code> (wird nicht benutzt), <b>Kategorie</b> "
        "„Chat Bot“ oder „Other“, <b>Client-Typ</b> „Confidential“.</li>"
        "<li>Die Application öffnen (<b>Manage</b>), die <b>Client-ID</b> kopieren und mit <b>New Secret</b> ein "
        "<b>Client-Secret</b> erzeugen.</li>"
        "<li>Im Discord (am besten per DM an den Bot) als Bot-Owner ausführen:<br>"
        "<code>[p]twitchset creds &lt;client_id&gt; &lt;client_secret&gt;</code><br>"
        "<span class='wc-muted'>Die Nachricht wird sofort gelöscht, der Bot prüft die Daten und meldet das "
        "Ergebnis.</span></li>"
        "<li>Fertig – Streamer im Reiter <b>Streamer</b> hinzufügen. Neue Streams werden innerhalb von etwa "
        "einer Minute gemeldet.</li></ol>"
    )
    guide = ui.card("Anleitung: Twitch-Zugang einrichten", steps, icon="bi-journal-check",
                    desc="Einmalig nötig, gilt für alle Server des Bots. Es werden nur öffentliche Daten gelesen "
                         "(App-Token, kein Login eines Streamers nötig).")
    return ui.columns(status, guide)


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
def _int(value):
    value = str(value or "").strip()
    return int(value) if value.isdigit() else None


async def _handle_post(cog, request):
    from .twitchlive import MAX_CHANNELS, normalize_login, valid_login

    webcore = request.app["webcore"]
    data = await request.post()
    action = data.get("action") or ""
    guild = _pick(await _guilds(request), data.get("guild"))   # POST -> nur Server mit „Bearbeiten“
    if guild is None:
        raise _redirect(None, err="Server nicht gefunden oder keine Bearbeiten-Rechte")
    gid = guild.id

    if action in ("add", "save"):
        login = normalize_login(data.get("login"))
        if not valid_login(login):
            raise _redirect(gid, err="Ungültiger Twitch-Login (3–25 Zeichen: Buchstaben, Ziffern, _)")
        chans = await cog.config.guild(guild).channels()
        if action == "save" and login not in chans:
            raise _redirect(gid, err="Streamer nicht gefunden")
        cid = _int(data.get("channel"))
        channel = guild.get_channel(cid) if cid else None
        if cid and channel is None:
            raise _redirect(gid, err="Kanal nicht gefunden")
        if channel is not None and not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise _redirect(gid, err="Bitte einen Textkanal wählen")
        if channel is not None and not cog.can_post(channel):
            raise _redirect(gid, err=f"Der Bot darf in #{channel.name} keine Embeds senden (Rechte prüfen)")
        conf = await cog.config.guild(guild).all()
        if channel is None and cog.target_channel(guild, conf, None) is None:
            raise _redirect(gid, err="Kein Zielkanal: Kanal wählen oder unter Einstellungen einen Standardkanal setzen")
        rid = _int(data.get("ping_role"))
        role = guild.get_role(rid) if rid else None
        if rid and (role is None or role.is_default()):
            raise _redirect(gid, err="Ping-Rolle nicht gefunden")
        message = (data.get("message") or "").strip()
        if len(message) > LIMIT_TEMPLATE:
            raise _redirect(gid, err=f"Nachricht zu lang (max. {LIMIT_TEMPLATE} Zeichen)")
        new, err = await cog.upsert_channel(
            guild, login, channel_id=cid or 0, ping_role=rid or 0, message=message,
            enabled=bool(data.get("enabled")), verify=(action == "add"),
        )
        if err == "unknown_login":
            raise _redirect(gid, err=f"Twitch kennt keinen Kanal „{login}“")
        if err == "too_many":
            raise _redirect(gid, err=f"Maximal {MAX_CHANNELS} Streamer pro Server")
        cog._kick()
        if action == "add" and not new:
            raise _redirect(gid, ok=f"{login} war schon eingetragen – Einstellungen aktualisiert")
        raise _redirect(gid, ok=f"{login} hinzugefügt" if new else f"{login} gespeichert")

    if action in ("delete", "toggle", "test"):
        login = normalize_login(data.get("login"))
        chans = await cog.config.guild(guild).channels()
        if login not in chans:
            raise _redirect(gid, err="Streamer nicht gefunden")
        if action == "delete":
            await cog.remove_channel(guild, login)
            raise _redirect(gid, ok=f"{login} entfernt")
        if action == "toggle":
            enabled = not (chans[login] or {}).get("enabled", True)
            await cog.upsert_channel(guild, login, enabled=enabled, verify=False)
            raise _redirect(gid, ok=f"{login} " + ("fortgesetzt" if enabled else "pausiert"))
        msg, channel = await cog.send_test(guild, login)
        if channel is None:
            raise _redirect(gid, err="Kein Zielkanal gesetzt")
        if msg is None:
            raise _redirect(gid, err=f"Testmeldung in #{channel.name} fehlgeschlagen (Rechte prüfen)")
        raise _redirect(gid, ok=f"Testmeldung in #{channel.name} gepostet")

    if action == "settings":
        cid = _int(data.get("default_channel"))
        channel = guild.get_channel(cid) if cid else None
        if cid and not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise _redirect(gid, err="Standardkanal nicht gefunden")
        if channel is not None and not cog.can_post(channel):
            raise _redirect(gid, err=f"Der Bot darf in #{channel.name} keine Embeds senden (Rechte prüfen)")
        end_action = data.get("end_action") if data.get("end_action") in ("edit", "delete") else "edit"
        language = data.get("language") if data.get("language") in LANGUAGES else "de"
        message = (data.get("default_message") or "").strip()
        if len(message) > LIMIT_TEMPLATE:
            raise _redirect(gid, err=f"Standardtext zu lang (max. {LIMIT_TEMPLATE} Zeichen)")
        gconf = cog.config.guild(guild)
        await gconf.default_channel.set(channel.id if channel else None)
        await gconf.end_action.set(end_action)
        await gconf.language.set(language)
        await gconf.default_message.set(message)
        raise _redirect(gid, ok="Einstellungen gespeichert")

    if action == "liverole":
        rid = _int(data.get("live_role"))
        if not rid:
            await cog.config.guild(guild).live_role.set(None)
            raise _redirect(gid, ok="Live-Rolle ausgeschaltet")
        role = guild.get_role(rid)
        if role is None or role.is_default():
            raise _redirect(gid, err="Rolle nicht gefunden")
        if not await webcore.can_grant_role(request, guild, role):
            raise _redirect(gid, err=f"@{role.name} darfst du nicht automatisch vergeben lassen "
                                     "(über deiner höchsten Rolle oder mit Verwaltungsrechten)")
        if not cog.role_manageable(guild, role):
            raise _redirect(gid, err=f"Der Bot kann @{role.name} nicht vergeben (Rechte/Rollen-Reihenfolge)")
        await cog.config.guild(guild).live_role.set(role.id)
        raise _redirect(gid, ok=f"Live-Rolle: @{role.name}")

    if action == "link":
        raw = (data.get("user") or "").strip()
        member = None
        uid = _int(raw.strip("<@!>"))
        if uid:
            member = guild.get_member(uid)
        elif raw:
            low = raw.lower()
            member = next((m for m in guild.members
                           if m.display_name.lower() == low or getattr(m, "name", "").lower() == low), None)
        if member is None or getattr(member, "bot", False):
            raise _redirect(gid, err="Mitglied nicht gefunden")
        login = normalize_login(data.get("login"))
        if not valid_login(login):
            raise _redirect(gid, err="Ungültiger Twitch-Login")
        await cog.set_link(guild, member.id, login)
        raise _redirect(gid, ok=f"{member.display_name} ↔ {login} verknüpft")

    if action == "unlink":
        uid = _int(data.get("user"))
        if not uid or not await cog.set_link(guild, uid, None):
            raise _redirect(gid, err="Verknüpfung nicht gefunden")
        raise _redirect(gid, ok="Verknüpfung gelöst")

    if action in ("interval", "poll"):
        if not await webcore.has_full_scope(request):
            raise _redirect(gid, err="Nur der Bot-Owner darf botweite Einstellungen ändern")
        if action == "poll":
            cog._kick()
            raise _redirect(gid, ok="Abfrage angestoßen")
        try:
            sec = int(data.get("interval") or 0)
        except ValueError:
            sec = 0
        if not 60 <= sec <= 600:
            raise _redirect(gid, err="Intervall: 60–600 Sekunden")
        await cog.config.poll_interval.set(sec)
        cog._kick()
        raise _redirect(gid, ok=f"Intervall: {sec} s")

    raise _redirect(gid, err="Unbekannte Aktion")
