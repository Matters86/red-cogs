"""WebCore-Dashboard für den Changelog-Cog.

Aufgaben (gleiches Muster wie poll/dashboard.py):
* GET                 -> Übersicht mit Reitern Einstellungen · Kategorien · Texte · Historie
* GET ?entry=<id>     -> Detailansicht eines Changelogs (read-only)
* POST form=settings  -> Einstellungen speichern (Post/Redirect/Get)
* POST form=action    -> Changelog löschen (optional inkl. Discord-Nachricht)

Oberfläche über den UI-Baukasten von WebCore (``request.app["webcore"].ui``) –
kein eigenes CSS. Nutzereingaben werden mit ``html.escape`` abgesichert. Die
Server-Auswahl ist auf die für den eingeloggten User sichtbaren Server beschränkt
(``visible_guilds``).
"""

from __future__ import annotations

import html
import json
from urllib.parse import quote, urlsplit

from aiohttp import web

from .public import build_payload
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

# Anzeige-Namen + Hilfetexte für die überschreibbaren Texte.
_OVERRIDE_LABELS = {
    "embed_title": ("Embed-Titel", "Platzhalter <code>{title}</code> = Titel aus dem Formular."),
    "footer": ("Fußzeile", "Platzhalter <code>{author}</code> = Name der postenden Person."),
}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _lines_html(raw: str) -> str:
    """Mehrzeiligen Rohtext als HTML-Liste (Bullets) darstellen."""
    lines = [ln.strip().lstrip("•-–*").strip() for ln in (raw or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    return "<ul class='mb-0'>" + "".join(f"<li>{_esc(ln)}</li>" for ln in lines) + "</ul>"


def _parse_color(text: str | None) -> int | None:
    if not text:
        return None
    value = str(text).strip().lstrip("#")
    if len(value) == 6:
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None


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


def _role_items(guild):
    return [
        (r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()
    ]


def _jump_url(guild, r: dict):
    channel = guild.get_channel(r.get("channel_id")) if r.get("channel_id") else None
    if channel is not None and r.get("message_id"):
        return channel, f"https://discord.com/channels/{guild.id}/{channel.id}/{r['message_id']}"
    return channel, None


# --------------------------------------------------------------------------- #
#  Einstieg
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
    guilds = await _visible_guilds(cog, request)
    guild = _pick_guild(guilds, request)
    if guild is None:
        return {"title": "Changelog", "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    entries = conf.get("entries") or {}

    # Eigene Server-Auswahl nur ohne globalen Server-Wechsler von WebCore.
    bar = ui.card(body=ui.form(
        "/cogs/changelog",
        ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
        csrf="", method="get",
    ))
    if request.get("wc_switcher"):
        bar = ""

    # Detailansicht eines Changelogs?
    sel = request.query.get("entry")
    if sel and sel in entries:
        return {"title": "Changelog · Eintrag", "content": bar + _render_detail(ui, guild, entries[sel])}

    channel = guild.get_channel(conf.get("channel_id")) if conf.get("channel_id") else None
    last_ts = max((r.get("created_ts", 0) for r in entries.values()), default=0)
    n_roles = len(conf.get("poster_roles") or [])
    head = ui.hero(
        "bi-megaphone", "",
        "Berechtigte Mitglieder posten Update-Notizen mit <code>/changelog</code> als einheitliches Embed. "
        "Hier legst du Ziel-Kanal, Rechte, Aussehen und Kategorien fest und siehst alle bisherigen Einträge.",
    ) + ui.stats([
        ("Changelogs", len(entries), "bi-journal-text", None, None),
        ("Ziel-Kanal", "Ja" if channel else "Nein", "bi-hash",
         f"#{channel.name}" if channel else "nicht festgelegt", "ok" if channel else "warn"),
        ("Poster-Rollen", n_roles, "bi-person-check", None if n_roles else "nur Admins/Verwalter", None),
        # Kurzer Wert (Tag.Monat.), Rest als Hinweis – lange Werte werden in der Kachel abgeschnitten.
        ("Letzter Eintrag", _fmt_ts(last_ts)[:6] if last_ts else "—", "bi-clock-history",
         f"{_fmt_ts(last_ts)[6:10]} · {_fmt_ts(last_ts)[11:]} Uhr (UTC)" if last_ts else None, None),
    ])

    base, public_host = await _public_base(request)
    body = (
        _render_settings(ui, cog, guild, conf, channel, csrf, base, public_host)
        + ui.tab("historie", "Historie", "bi-clock-history", _render_history(ui, guild, entries, csrf),
                 count=len(entries))
    )
    return {"title": "Changelog", "content": bar + head + body}


async def _public_base(request) -> tuple[str, bool]:
    """Basis-URL des Dashboards: aus der OAuth-``redirect_uri`` (öffentliche Adresse), sonst die
    aktuelle Anfrage. Zweiter Wert: ``True``, wenn die Adresse öffentlich per HTTPS aussieht."""
    webcore = request.app.get("webcore")
    redirect = ""
    try:
        redirect = str(await webcore.config.redirect_uri() or "") if webcore is not None else ""
    except Exception:  # noqa: BLE001
        redirect = ""
    parts = urlsplit(redirect)
    if parts.scheme in ("http", "https") and parts.netloc:
        host = parts.hostname or ""
        public = parts.scheme == "https" and host not in ("localhost", "127.0.0.1", "::1")
        return f"{parts.scheme}://{parts.netloc}", public
    return f"{request.scheme}://{request.host}", False


def _render_public(ui, guild, conf, base, public_host) -> str:
    """Karte „Für Launcher & Website freigeben“ (Schalter + URLs + Beispiel)."""
    json_url = f"{base}/api/public/changelog/{guild.id}"
    rss_url = json_url + "/rss"

    def copy_field(url):
        inp = ui.text_input("", url, attrs={"readonly": True, "onclick": "this.select()"})
        btn = ui.button("", icon="bi-clipboard", kind="ghost", type="button",
                        attrs={"title": "Kopieren", "onclick": "navigator.clipboard&&navigator.clipboard.writeText("
                               "this.previousElementSibling.value);this.querySelector('i').className='bi bi-check2'"})
        return f"<div class='wc-input-group'>{inp}{btn}</div>"

    example = build_payload(guild, conf, limit=1)
    if not example["entries"]:
        example["entries"] = [{
            "id": "cl1", "title": "Fahrzeug-Update",
            "category": {"emoji": "🚗", "label": "Fahrzeuge"},
            "sections": [{"key": "neu", "title": "Neu", "emoji": "🚗", "items": ["Neues Polizeiauto"]}],
            "note": None, "created_at": "2026-09-25T18:00:00Z", "author": "Matters86",
            "url": f"https://discord.com/channels/{guild.id}/123/456",
        }]
    example_json = json.dumps(example, ensure_ascii=False, indent=2)
    state = ui.badge("freigegeben", "ok") if conf.get("public_api") else ui.badge("aus", "muted")
    hint = ui.callout(
        "Damit ein Launcher oder eine Website die Daten abrufen kann, muss das Dashboard <b>öffentlich erreichbar</b> "
        "sein (Reverse-Proxy mit HTTPS, siehe WebCore-README). Ohne Freigabe – oder für unbekannte Server – antwortet "
        "die Adresse mit <code>404</code>. Ausgegeben werden nur Titel, Inhalte, Datum, Anzeigename des Autors und der "
        "Link zur Nachricht, keine Nutzer-IDs.",
        tone="info" if public_host else "warn",
    )
    if not public_host:
        hint += ui.callout(
            f"Die Adresse unten stammt von <code>{html.escape(base)}</code> – das sieht nicht nach einer öffentlichen "
            "HTTPS-Adresse aus. Trage in WebCore die öffentliche Redirect-URI ein, dann stimmen die Links.", tone="warn")
    body = (
        ui.switches(ui.switch("public_api", "Changelogs öffentlich abrufbar machen", conf.get("public_api"),
                              desc="JSON und RSS für diesen Server freigeben (Standard: aus)."))
        + ui.divider()
        + ui.grid(
            ui.field("JSON-Adresse", copy_field(json_url),
                     help="Parameter: <code>?limit=1–50</code> (Standard 10), <code>&amp;before=&lt;id&gt;</code> "
                          "für ältere Einträge (Wert aus <code>next_before</code>)."),
            ui.field("RSS-Feed", copy_field(rss_url), help="RSS 2.0 – z. B. für Feed-Reader oder Website-Widgets."),
        )
        + hint
        + ui.field("Beispiel-Antwort",
                   f"<textarea class='wc-input mono' rows='14' readonly>{html.escape(example_json)}</textarea>",
                   help="Neuester Eintrag dieses Servers (bzw. ein Beispiel, solange es noch keinen gibt).")
    )
    return ui.card("Für Launcher & Website freigeben", body, icon="bi-broadcast", actions=state,
                   desc="Öffentliche Schnittstelle, mit der z. B. dein Launcher die neuesten Changelogs anzeigt.")


def _render_settings(ui, cog, guild, conf, channel, csrf, base="", public_host=False) -> str:
    text_items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    role_items = _role_items(guild)
    color_hex = f"#{int(conf.get('color', 0x3DDC97)):06X}"

    setup = ""
    if channel is None:
        setup = ui.callout("Es ist noch <b>kein Ziel-Kanal</b> festgelegt – <code>/changelog</code> kann erst posten, "
                           "wenn einer ausgewählt ist.", tone="warn")

    post = ui.card("Kanal & Rechte", ui.grid(
        ui.field("Ziel-Kanal", ui.select("channel", text_items, conf.get("channel_id"), none_label="— kein Kanal —"),
                 help="Hier erscheinen alle Changelogs."),
        ui.field("Poster-Rollen", ui.select("poster_roles", role_items, conf.get("poster_roles") or [], multiple=True,
                                            placeholder="Rollen suchen …"),
                 help="Diese Rollen dürfen <code>/changelog</code> nutzen (Admins und Server-Verwalter dürfen immer)."),
    ), icon="bi-send", desc="Wohin gepostet wird und wer posten darf.")

    ping = ui.card("Benachrichtigung", ui.grid(
        ui.field("Ping-Rolle", ui.select("ping_role", [(i, n) for i, n, _c in role_items], conf.get("ping_role_id"),
                                         none_label="— keine —"),
                 help="Z. B. eine @Updates-Rolle, die Mitglieder selbst abonnieren."),
        ui.field("Ping", ui.switch("ping_enabled", "Ping-Rolle vor dem Embed anpingen", conf.get("ping_enabled"),
                                   desc="Die Rolle wird in der Nachricht über dem Embed erwähnt.")),
    ), icon="bi-bell")

    look = ui.card("Aussehen", ui.grid(
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf.get("language", "de")),
                 help="Sprache der Embed-Überschriften und des Eingabe-Formulars."),
        ui.field("Embed-Farbe", ui.text_input("color", color_hex, type="color",
                                              attrs={"style": "height:42px;padding:4px 6px;cursor:pointer"}),
                 help="Farbstreifen am linken Rand des Embeds."),
    ), icon="bi-palette")

    cats = cog._categories(conf)
    cats_text = "\n".join(f"{c.get('emoji', '')}|{c.get('label', '')}" for c in cats)
    categories = ui.card("Kategorien", ui.field(
        "Kategorien (eine pro Zeile)",
        ui.textarea("categories", cats_text, rows=8, mono=True, placeholder="🚗|Fahrzeuge\n🌾|Landwirtschaft"),
        help="Format: <code>Emoji|Bezeichnung</code>, max. 25. Die postende Person wählt beim Befehl "
             "<code>/changelog</code> eine Kategorie – ihr Emoji steht dann vor dem „Neu“-Bereich.",
    ), icon="bi-tags")

    overrides = conf.get("messages") or {}
    override_fields = []
    for key in OVERRIDABLE_KEYS:
        label, hint = _OVERRIDE_LABELS.get(key, (key, None))
        override_fields.append(ui.field(
            label, ui.text_input(f"ovr_{key}", overrides.get(key, ""), placeholder=STRINGS["de"].get(key, "")),
            help=hint,
        ))
    texts = ui.card("Eigene Texte", ui.grid(*override_fields), icon="bi-chat-left-text",
                    desc="Leer lassen = Standardtext der gewählten Sprache (als grauer Platzhalter sichtbar). "
                         "Platzhalter in geschweiften Klammern beibehalten.")

    save = ui.save_row("Einstellungen speichern")
    # Ein Formular über drei Reiter – jedes Speichern sendet alle Einstellungen.
    return ui.form(
        "/cogs/changelog",
        ui.tab("einstellungen", "Einstellungen", "bi-sliders", setup + post + ping + look + save)
        + ui.tab("kategorien", "Kategorien", "bi-tags", categories + save, count=len(cats))
        + ui.tab("texte", "Texte", "bi-chat-left-text", texts + save)
        + ui.tab("launcher", "Launcher & Website", "bi-broadcast",
                 _render_public(ui, guild, conf, base, public_host) + save),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )


def _render_history(ui, guild, entries, csrf) -> str:
    if not entries:
        return ui.card(body=ui.empty(
            "bi-journal-text", "Für diesen Server sind noch keine Changelogs gespeichert.",
            "Sobald jemand <code>/changelog</code> nutzt, erscheint der Eintrag hier."))
    rows = []
    for r in sorted(entries.values(), key=lambda x: x.get("created_ts", 0), reverse=True):
        eid = r.get("id")
        # Discord-Zeitstempel rendern im Web nicht – daher lesbares Datum bauen.
        when_txt = _fmt_ts(r.get("created_ts", 0))
        channel, url = _jump_url(guild, r)
        ch_name = f"#{channel.name}" if channel is not None else "—"
        detail_link = f"/cogs/changelog?guild={guild.id}&entry={_esc(eid)}"
        view = ui.button("", icon="bi-eye", kind="ghost", small=True, href=detail_link, attrs={"title": "Ansehen"})
        jump = ui.button("", icon="bi-discord", kind="ghost", small=True, href=url,
                         attrs={"title": "Zur Nachricht", "target": "_blank", "rel": "noopener"}) if url else ""
        delete = ui.form(
            "/cogs/changelog",
            ui.button("", icon="bi-trash", kind="danger", small=True, name="action", value="delete",
                      confirm=f"Changelog {eid} wirklich löschen? Die Nachricht in Discord wird ebenfalls entfernt.",
                      attrs={"title": "Löschen"}),
            csrf=csrf, hidden={"form": "action", "guild": guild.id, "entry_id": eid},
        )
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(r.get('category_emoji', ''))} "
            f"<a href='{detail_link}'>{_esc((r.get('title') or '(ohne Titel)')[:70])}</a></div>"
            f"<div class='wc-cell-sub'><span class='mono'>{_esc(eid)}</span> · {_esc(r.get('author_name', '?'))}"
            f" · {_esc(ch_name)}</div>",
            f"<span class='mono'>{_esc(when_txt)}</span>",
            f"><div class='wc-row-actions'>{view}{jump}{delete}</div>",
        ))
    return ui.card(
        "Historie",
        ui.table(["Changelog", "Datum (UTC)", ">"], rows, search=True,
                 search_placeholder="Nach Titel, ID, Autor oder Kanal suchen …", id="cl-history"),
        icon="bi-clock-history",
        desc="Alle gespeicherten Changelogs, neueste zuerst. Löschen entfernt auch die Discord-Nachricht.",
    )


def _render_detail(ui, guild, r: dict) -> str:
    channel, url = _jump_url(guild, r)
    ch_name = f"#{channel.name}" if channel is not None else "—"
    actions = [ui.button("Zurück zur Historie", icon="bi-arrow-left", kind="ghost",
                         href=f"/cogs/changelog?guild={guild.id}#historie")]
    if url:
        actions.append(ui.button("Zur Nachricht", icon="bi-discord", kind="ghost", href=url,
                                 attrs={"target": "_blank", "rel": "noopener"}))
    head = f"<div class='wc-toolbar'>{''.join(actions)}</div>" + ui.hero(
        "bi-megaphone", r.get("title", "(ohne Titel)"),
        f"{_esc(_fmt_ts(r.get('created_ts', 0)))} UTC · {_esc(ch_name)} · {_esc(r.get('author_name', '?'))} · "
        f"<span class='mono'>{_esc(r.get('id'))}</span>",
    )

    sections = []
    new_html = _lines_html(r.get("neu", ""))
    if new_html:
        sections.append(f"<div class='wc-sub'>{_esc(r.get('category_emoji', ''))} Neu</div>{new_html}")
    changed_html = _lines_html(r.get("geaendert", ""))
    if changed_html:
        sections.append(f"<div class='wc-sub'>🔧 Geändert</div>{changed_html}")
    fixes_html = _lines_html(r.get("fixes", ""))
    if fixes_html:
        sections.append(f"<div class='wc-sub'>🐛 Fixes</div>{fixes_html}")
    body = "".join(sections) or ui.empty("bi-journal", "Kein Inhalt.")
    note = (r.get("hinweis") or "").strip()
    if note:
        body += "<div class='wc-divider'></div>" + ui.callout(f"<b>{_esc(note)}</b>", tone="warn")
    return head + ui.card("Inhalt", body, icon="bi-journal-text")


def _fmt_ts(ts) -> str:
    """Unix-Sekunden -> lesbares UTC-Datum (im Web, wo Discord-Tags nicht greifen)."""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


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
        raise web.HTTPFound("/cogs/changelog?ok=" + quote("Server nicht gefunden"))

    gconf = cog.config.guild(guild)

    if form == "settings":
        # Ziel-Kanal
        ch = data.get("channel")
        if ch and ch.isdigit() and guild.get_channel(int(ch)) is not None:
            await gconf.channel_id.set(int(ch))
        else:
            await gconf.channel_id.set(None)

        # Sprache
        lang = (data.get("language") or "de").lower()
        if lang in LANGUAGES:
            await gconf.language.set(lang)

        # Poster-Rollen
        roles = [int(r) for r in data.getall("poster_roles", []) if str(r).isdigit()]
        await gconf.poster_roles.set(roles)

        # Ping-Rolle + Schalter
        pr = data.get("ping_role")
        if pr and pr.isdigit() and guild.get_role(int(pr)) is not None:
            await gconf.ping_role_id.set(int(pr))
        else:
            await gconf.ping_role_id.set(None)
        await gconf.ping_enabled.set("ping_enabled" in data)

        # Farbe
        color = _parse_color(data.get("color"))
        if color is not None:
            await gconf.color.set(color)

        # Kategorien (Emoji|Bezeichnung pro Zeile)
        cats = []
        for line in (data.get("categories") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                emoji, label = line.split("|", 1)
            else:
                parts = line.split(None, 1)
                emoji, label = (parts[0], parts[1] if len(parts) > 1 else "")
            emoji = emoji.strip()[:16]
            label = label.strip()[:80]
            if emoji:
                cats.append({"emoji": emoji, "label": label or emoji})
            if len(cats) >= 25:
                break
        await gconf.categories.set(cats)

        # Text-Overrides
        overrides = {}
        for key in OVERRIDABLE_KEYS:
            val = (data.get(f"ovr_{key}") or "").strip()
            if val:
                overrides[key] = val
        await gconf.messages.set(overrides)

        # Öffentliche API (Launcher & Website)
        await gconf.public_api.set("public_api" in data)

        raise web.HTTPFound(f"/cogs/changelog?guild={guild.id}&ok=" + quote("Gespeichert"))

    if form == "action" and data.get("action") == "delete":
        entry_id = data.get("entry_id")
        snapshot = None
        async with gconf.entries() as entries:
            snapshot = entries.pop(entry_id, None)
        if snapshot and snapshot.get("channel_id") and snapshot.get("message_id"):
            channel = guild.get_channel(snapshot["channel_id"])
            if channel is not None:
                try:
                    msg = await channel.fetch_message(snapshot["message_id"])
                    await msg.delete()
                except Exception:  # noqa: BLE001
                    pass
        raise web.HTTPFound(f"/cogs/changelog?guild={guild.id}&ok=" + quote("Gelöscht"))

    raise web.HTTPFound(f"/cogs/changelog?guild={guild.id}")
