"""WebCore-Dashboard für den Organigram-Cog.

Aufbau:
* GET  -> Seite rendern: Organigramm-Liste (Reiter „Organigramme“ · „Neu anlegen“)
         bzw. Editor eines Organigramms (Reiter „Positionen“ · „Einstellungen“ ·
         „Vorschau & Posten“). Zusätzlich Bild-Endpunkte ``?preview=<id>`` und
         ``?download=<id>``, die direkt ein PNG zurückgeben (Live-Vorschau / Export).
* POST -> Formular verarbeiten, danach Redirect (Post/Redirect/Get).

Oberfläche über den UI-Baukasten von WebCore (``request.app["webcore"].ui``) –
kein eigenes CSS.
"""

from __future__ import annotations

import html
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from urllib.parse import quote_plus

import discord
from aiohttp import web

from .render import PATTERNS

log = logging.getLogger("red.red-cogs.organigram")

_PREVIEW_DIR = os.path.join(os.path.dirname(__file__), "assets", "previews")

# Eingabe (DE im Formular) -> intern gespeicherter Modus
MODE_MAP = {"bild": "image", "embed": "embed", "text": "text"}
MODE_LABEL = {"image": "Bild", "embed": "Embed", "text": "Text"}
# Auswahl im Formular: (Formularwert, Anzeige) – Formularwert wird per MODE_MAP umgesetzt.
_MODE_ITEMS = [("bild", "Bild (gerendertes PNG)"), ("embed", "Embed"), ("text", "Text")]
_MODE_FORM = {intern: val for val, intern in MODE_MAP.items()}

# Muster-Vorschau: Bild unter der Muster-Auswahl beim Wechsel austauschen.
_MUSTER_SCRIPT = """
<script>
  document.querySelectorAll("select[name=pattern]").forEach(function (sel) {
    sel.addEventListener("change", function () {
      var box = document.getElementById(sel.form.id + "-muster");
      if (!box) { return; }
      var img = box.querySelector("img");
      var cap = box.querySelector(".wc-help");
      if (img) { img.src = img.getAttribute("data-base") + encodeURIComponent(sel.value); }
      if (cap) { cap.textContent = sel.options[sel.selectedIndex].text; }
    });
  });
</script>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "organigramm").lower()).strip("-")
    return s or "organigramm"


def _descendants(nodes: dict, root_id: str) -> set[str]:
    children = defaultdict(list)
    for nid, nd in nodes.items():
        p = nd.get("parent")
        if p:
            children[p].append(nid)
    out: set[str] = set()
    stack = list(children.get(root_id, []))
    while stack:
        c = stack.pop()
        if c in out:
            continue
        out.add(c)
        stack.extend(children.get(c, []))
    return out


def _label_of(guild, nodes: dict, nid) -> str:
    nd = nodes.get(nid, {})
    if nd.get("label"):
        return nd["label"]
    if nd.get("role_id"):
        r = guild.get_role(nd["role_id"])
        if r:
            return r.name
    return "(ohne Titel)"


def _people_count(guild, nd: dict) -> int:
    role = guild.get_role(nd["role_id"]) if nd.get("role_id") else None
    manual = len([m for m in nd.get("manual_names", []) if (m or "").strip()])
    return (len(role.members) if role else 0) + manual


def _posted_channels(guild, chart: dict) -> list[str]:
    return [
        f"#{ch.name}" for p in chart.get("posts", [])
        if (ch := guild.get_channel_or_thread(p.get("channel_id"))) is not None
    ]


def _accent(value) -> str:
    accent = (value or "#3ddc97").strip()
    return accent if accent.startswith("#") else "#" + accent


def _color_input(ui, name: str, value: str) -> str:
    # Farbwähler im Kit-Stil; nur Höhe/Innenabstand an das native Farbfeld angepasst.
    return ui.text_input(name, value, type="color", attrs={"style": "height:42px;padding:4px 6px;cursor:pointer"})


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
    # Statische Muster-Vorschau (guild-unabhängig, lange cachebar).
    muster = request.query.get("muster")
    if muster:
        if muster not in PATTERNS:
            raise web.HTTPNotFound(text="Unbekanntes Muster")
        path = os.path.join(_PREVIEW_DIR, f"{muster}.png")
        if not os.path.isfile(path):
            raise web.HTTPNotFound(text="Vorschau nicht gefunden")
        with open(path, "rb") as fh:
            data = fh.read()
        return web.Response(body=data, content_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(cog, request)
    guild = _pick_guild(guilds, request)
    if guild is None:
        return {"title": "Organigramm",
                "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}

    charts = await cog.config.guild(guild).charts()

    # --- Bild-Endpunkte (Vorschau / Download) ----------------------------- #
    img_id = request.query.get("preview") or request.query.get("download")
    if img_id:
        chart = charts.get(img_id)
        if not chart:
            raise web.HTTPNotFound(text="Organigramm nicht gefunden")
        try:
            png = await cog._render_png(guild, chart)
        except Exception:
            log.exception("Vorschau-Rendering fehlgeschlagen")
            raise web.HTTPInternalServerError(text="Rendering fehlgeschlagen")
        headers = {"Cache-Control": "no-store"}
        if request.query.get("download"):
            headers["Content-Disposition"] = (
                f'attachment; filename="{_slug(chart.get("name"))}.png"'
            )
        return web.Response(body=png, content_type="image/png", headers=headers)

    csrf = request.get("webcore_csrf", "")

    # Eigene Server-Auswahl nur ohne globalen Server-Wechsler von WebCore.
    guild_picker = ui.card(body=ui.form(
        "/cogs/organigram",
        ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
        csrf="", method="get",
    ))
    if request.get("wc_switcher"):
        guild_picker = ""

    sel_cid = request.query.get("chart")
    selected = charts.get(sel_cid) if sel_cid else None

    if selected:
        body = _render_editor(ui, guild, sel_cid, selected, csrf, request)
        title = "Organigramm · bearbeiten"
    else:
        body = _render_overview(ui, guild, charts, csrf)
        title = "Organigramm"

    return {"title": title, "content": guild_picker + body + _MUSTER_SCRIPT}


# --------------------------------------------------------------------------- #
#  Übersicht: Liste + Neu anlegen
# --------------------------------------------------------------------------- #
def _render_overview(ui, guild, charts, csrf) -> str:
    n_nodes = sum(len(c.get("nodes", {})) for c in charts.values())
    n_posts = sum(len(c.get("posts", [])) for c in charts.values())
    n_auto = sum(1 for c in charts.values() if c.get("auto_update", True))
    head = ui.hero(
        "bi-diagram-3", "",
        "Zeigt die Struktur eures Teams als <b>Bild</b>, <b>Embed</b> oder <b>Text</b>. Positionen können mit "
        "Discord-Rollen verknüpft werden – gepostete Organigramme aktualisieren sich dann automatisch.",
    ) + ui.stats([
        ("Organigramme", len(charts), "bi-diagram-3", None, None),
        ("Positionen", n_nodes, "bi-person-badge", None, None),
        ("Gepostet", n_posts, "bi-send", "Beiträge in Kanälen", "ok" if n_posts else None),
        ("Auto-Update", n_auto, "bi-arrow-repeat", "Organigramme mit automatischer Aktualisierung", None),
    ])
    return (
        head
        + ui.tab("organigramme", "Organigramme", "bi-diagram-3", _render_list(ui, guild, charts, csrf), count=len(charts))
        + ui.tab("neu", "Neu anlegen", "bi-plus-square", _render_new(ui, guild, csrf))
    )


def _render_list(ui, guild, charts, csrf) -> str:
    if not charts:
        return ui.card(body=ui.empty(
            "bi-diagram-3", "Noch keine Organigramme.",
            "Lege im Reiter „Neu anlegen“ dein erstes Organigramm an.",
            action=ui.button("Organigramm anlegen", icon="bi-plus-lg", href="#neu",
                             attrs={"onclick": "if (window.wcActivateTab) { wcActivateTab('neu', true); return false; }"}),
        ))
    rows = []
    for cid, c in charts.items():
        n = len(c.get("nodes", {}))
        where = _posted_channels(guild, c)
        pat = PATTERNS.get(c.get("pattern", "baum"), c.get("pattern", "baum"))
        edit_link = f"/cogs/organigram?guild={guild.id}&chart={_esc(cid)}"
        edit = ui.button("Bearbeiten", icon="bi-pencil", kind="ghost", small=True, href=edit_link)
        delete = ui.form(
            "/cogs/organigram",
            ui.button("", icon="bi-trash", kind="danger", small=True, attrs={"title": "Organigramm löschen"}),
            csrf=csrf, hidden={"form": "chart_delete", "guild": guild.id, "chart": cid},
            confirm=f"Organigramm „{c.get('name', '?')}“ wirklich löschen? Bereits gepostete Nachrichten bleiben bestehen.",
        )
        posted = ", ".join(where) if where else ""
        rows.append(ui.row(
            f"<div class='wc-cell-title'><a href='{edit_link}'>{_esc(c.get('name', '?'))}</a></div>"
            + (f"<div class='wc-cell-sub'>{_esc(c.get('title'))}</div>" if c.get("title") else ""),
            _esc(pat),
            ui.badge(MODE_LABEL.get(c.get("mode", "image"), "Bild"), "info"),
            f"<span class='mono'>{n}</span>",
            (ui.badge(posted, "ok") if posted else ui.badge("nicht gepostet", "muted"))
            + ("" if c.get("auto_update", True) else " " + ui.badge("Auto-Update aus", "warn")),
            f"><div class='wc-row-actions'>{edit}{delete}</div>",
        ))
    return ui.card(
        "Deine Organigramme",
        ui.table(["Name", "Muster", "Ausgabe", "Positionen", "Gepostet in", ">"], rows,
                 search=len(rows) > 6, search_placeholder="Organigramm suchen …", id="og-charts"),
        icon="bi-diagram-3",
        desc="Klicke auf einen Namen, um Positionen zu pflegen, das Aussehen anzupassen oder das Organigramm zu posten.",
    )


def _muster_preview(form_id: str, selected: str) -> str:
    base = "/cogs/organigram?muster="
    return (
        f"<div id='{_esc(form_id)}-muster' class='text-center'>"
        f"<img class='img-fluid rounded' style='max-height:220px' alt='Muster-Vorschau' loading='lazy' "
        f"data-base='{base}' src='{base}{_esc(selected)}'>"
        f"<div class='wc-help'>{_esc(PATTERNS.get(selected, selected))}</div>"
        "</div>"
    )


def _chart_cards(ui, chart: dict, form_id: str) -> str:
    """Gemeinsame Felder für „Neu anlegen“ und „Einstellungen“ (gleiche Feldnamen)."""
    pattern = chart.get("pattern", "baum")
    general = ui.card("Allgemein", ui.grid(
        ui.field("Name", ui.text_input("name", chart.get("name", ""), placeholder="Leitung", attrs={"required": True}),
                 help="Kurzer, eindeutiger Name – wird auch in Befehlen verwendet, z. B. "
                      "<code>/organigram show Leitung</code>."),
        ui.field("Titel im Bild", ui.text_input("title", chart.get("title", ""), placeholder="= Name"),
                 help="Überschrift über dem Organigramm. Leer lassen = Name."),
    ), icon="bi-card-heading")
    look = ui.card("Darstellung", ui.grid(
        ui.field("Muster (Bild-Ausgabe)", ui.select("pattern", list(PATTERNS.items()), pattern)
                 + _muster_preview(form_id, pattern),
                 help="Anordnung der Positionen im gerenderten Bild."),
        ui.field("Standard-Ausgabe", ui.select("mode", _MODE_ITEMS, _MODE_FORM.get(chart.get("mode", "image"), "bild")),
                 help="Wird beim Posten vorausgewählt. <b>Bild</b> = gerendertes PNG, <b>Embed</b>/<b>Text</b> = "
                      "Discord-Nachricht mit den Namen."),
        ui.field("Akzentfarbe", _color_input(ui, "accent", _accent(chart.get("accent"))),
                 help="Farbe für Linien und Hervorhebungen im Bild."),
        cols=3,
    ), icon="bi-palette")
    opts = ui.card("Optionen", "<div class='wc-switches'>"
        + ui.switch("show_avatars", "Avatare im Bild anzeigen", chart.get("show_avatars", True),
                    desc="Profilbilder der Rollenmitglieder neben den Namen.")
        + ui.switch("show_vacant", "Leere Positionen zeigen", chart.get("show_vacant", True),
                    desc="Positionen ohne Personen erscheinen als „unbesetzt“.")
        + ui.switch("auto_update", "Automatisch aktualisieren", chart.get("auto_update", True),
                    desc="Gepostete Beiträge werden bei Rollen-Änderungen neu erstellt.")
        + "</div>", icon="bi-toggles")
    return general + look + opts


def _render_new(ui, guild, csrf) -> str:
    return ui.form(
        "/cogs/organigram",
        _chart_cards(ui, {}, "og-new") + ui.actions(ui.button("Organigramm anlegen", icon="bi-plus-lg")),
        csrf=csrf, hidden={"form": "chart_new", "guild": guild.id}, id="og-new",
    )


# --------------------------------------------------------------------------- #
#  Editor eines Organigramms
# --------------------------------------------------------------------------- #
def _render_editor(ui, guild, cid, chart, csrf, request) -> str:
    nodes = chart.get("nodes", {})
    where = _posted_channels(guild, chart)
    n_people = sum(_people_count(guild, nd) for nd in nodes.values())

    back = ui.button("Alle Organigramme", icon="bi-arrow-left", kind="ghost",
                     href=f"/cogs/organigram?guild={guild.id}#organigramme")
    # Zurück-Button als eigene Leiste (Hero-Aktionen brechen auf dem Handy nicht um).
    head = f"<div class='wc-toolbar'>{back}</div>" + ui.hero(
        "bi-diagram-3", chart.get("name", "?"),
        "Lege Positionen an, passe das Aussehen an und poste das Organigramm in einen Kanal.",
    ) + ui.stats([
        ("Positionen", len(nodes), "bi-person-badge", None, None),
        ("Personen", n_people, "bi-people", "Rollenmitglieder + zusätzliche Namen", None),
        ("Gepostet in", len(where), "bi-send", ", ".join(where) or "noch nirgends", "ok" if where else None),
        ("Ausgabe", MODE_LABEL.get(chart.get("mode", "image"), "Bild"), "bi-image",
         PATTERNS.get(chart.get("pattern", "baum"), None), None),
    ])

    settings = ui.form(
        "/cogs/organigram",
        _chart_cards(ui, chart, "og-settings") + ui.save_row("Einstellungen speichern"),
        csrf=csrf, hidden={"form": "chart_settings", "guild": guild.id, "chart": cid},
        savebar=True, id="og-settings",
    )

    return (
        head
        + ui.tab("positionen", "Positionen", "bi-diagram-2",
                 _render_positions(ui, guild, cid, nodes, csrf, request), count=len(nodes))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", settings)
        + ui.tab("posten", "Vorschau & Posten", "bi-send", _render_preview_post(ui, guild, cid, chart, where, csrf))
    )


def _render_positions(ui, guild, cid, nodes, csrf, request) -> str:
    prows = []
    for nid, nd in sorted(nodes.items(), key=lambda kv: (kv[1].get("order", 0), _label_of(guild, nodes, kv[0]).lower())):
        role = guild.get_role(nd["role_id"]) if nd.get("role_id") else None
        role_name = f"@{role.name}" if role else ("@gelöscht" if nd.get("role_id") else "—")
        parent_lbl = f"unter {_label_of(guild, nodes, nd['parent'])}" if nd.get("parent") in nodes else "oberste Ebene"
        manual = len([m for m in nd.get("manual_names", []) if (m or "").strip()])
        edit_link = f"/cogs/organigram?guild={guild.id}&chart={_esc(cid)}&node={_esc(nid)}#positionen"
        edit = ui.button("Bearbeiten", icon="bi-pencil", kind="ghost", small=True, href=edit_link)
        delete = ui.form(
            "/cogs/organigram",
            ui.button("", icon="bi-trash", kind="danger", small=True, attrs={"title": "Position löschen"}),
            csrf=csrf, hidden={"form": "node_delete", "guild": guild.id, "chart": cid, "node": nid},
            confirm="Position wirklich löschen? Untergeordnete Positionen rücken eine Ebene nach oben.",
        )
        sub = f"{parent_lbl} · Reihenfolge {int(nd.get('order', 0) or 0)}" + (f" · {manual} zusätzl. Name(n)" if manual else "")
        prows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(nd.get('emoji') or '')} "
            f"<a href='{edit_link}'>{_esc(_label_of(guild, nodes, nid))}</a></div>"
            f"<div class='wc-cell-sub'>{_esc(sub)}</div>",
            ui.badge(role_name, "bad" if role_name == "@gelöscht" else "muted") if role_name != "—"
            else "<span class='wc-muted'>—</span>",
            f"><span class='mono'>{_people_count(guild, nd)}</span>",
            f"><div class='wc-row-actions'>{edit}{delete}</div>",
        ))
    if prows:
        table = ui.card(
            "Positionen", ui.table(["Position", "Rolle", ">Personen", ">"], prows,
                                   search=len(prows) > 8, search_placeholder="Position oder Rolle suchen …",
                                   id="og-nodes"),
            icon="bi-diagram-2",
            desc="Jede Position kann eine Rolle (Mitglieder erscheinen automatisch) und/oder feste Namen haben.",
        )
    else:
        table = ui.card(body=ui.empty(
            "bi-diagram-2", "Noch keine Positionen.",
            "Lege unten die oberste Position an (z. B. „Leitung“) und ordne weitere darunter an."))

    editor = _render_node_editor(ui, guild, cid, nodes, csrf, request)
    # Beim Bearbeiten steht der Editor oben, damit er nach dem Klick sofort sichtbar ist.
    return editor + table if request.query.get("node") in nodes else table + editor


def _render_node_editor(ui, guild, cid, nodes, csrf, request) -> str:
    sel_nid = request.query.get("node")
    nd = nodes.get(sel_nid) if sel_nid else None
    nd = nd or {}
    is_edit = bool(nd)

    color = (nd.get("color") or "").strip()
    color_val = ("#" + color.lstrip("#")) if color else "#3ddc97"
    has_color = bool(color)

    # Rollen (ohne @everyone), nach Position absteigend
    roles = [r for r in guild.roles if not r.is_default()]
    roles.sort(key=lambda r: r.position, reverse=True)
    role_items = [(r.id, r.name) for r in roles]

    # Übergeordnete Position: alle außer sich selbst und eigenen Nachfahren
    forbidden = {sel_nid} | (_descendants(nodes, sel_nid) if sel_nid else set())
    parent_items = [(nid, _label_of(guild, nodes, nid)) for nid in nodes if nid not in forbidden]

    manual_text = "\n".join(nd.get("manual_names", []) or [])
    hidden = {"form": "node_save", "guild": guild.id, "chart": cid}
    if sel_nid:
        hidden["node"] = sel_nid

    fields = ui.grid(
        ui.field("Bezeichnung", ui.text_input("label", nd.get("label", ""), placeholder="z. B. Administration"),
                 help="Leer lassen, um den Namen der verknüpften Rolle zu verwenden."),
        ui.field("Übergeordnete Position", ui.select("parent", parent_items, nd.get("parent"),
                                                      none_label="— (oberste Ebene)"),
                 help="Unter welcher Position diese im Organigramm hängt."),
        ui.field("Verknüpfte Rolle", ui.select("role_id", role_items, nd.get("role_id"), none_label="— keine Rolle —"),
                 help="Alle Mitglieder dieser Rolle erscheinen automatisch."),
        ui.field("Reihenfolge", ui.number("order", int(nd.get("order", 0) or 0)),
                 help="Kleinere Zahl = weiter links bzw. oben."),
        ui.field("Zusätzliche Namen", ui.textarea("manual_names", manual_text, rows=3,
                                                   placeholder="Max Mustermann\nErika Beispiel"),
                 help="Eine Person pro Zeile – für Personen ohne passende Discord-Rolle. "
                      "Werden zusätzlich zu den Rollenmitgliedern angezeigt.", wide=True),
        ui.field("Emoji", ui.text_input("emoji", nd.get("emoji", ""), placeholder="👑"),
                 help="Nur in der Embed- und Text-Ausgabe."),
        ui.field("Farbe", ui.switch("use_color", "Eigene Farbe statt Rollenfarbe", has_color)
                 + _color_input(ui, "color", color_val),
                 help="Ohne eigene Farbe wird die Farbe der verknüpften Rolle genutzt."),
    )
    buttons = [ui.button("Position speichern" if is_edit else "Position anlegen", icon="bi-check2")]
    if is_edit:
        buttons.append(ui.button("Abbrechen", icon="bi-x-lg", kind="ghost",
                                 href=f"/cogs/organigram?guild={guild.id}&chart={_esc(cid)}#positionen"))
    title = f"Position bearbeiten: {_label_of(guild, nodes, sel_nid)}" if is_edit else "Neue Position"
    return ui.card(
        title,
        ui.form("/cogs/organigram", fields + ui.actions(*buttons), csrf=csrf, hidden=hidden, savebar=is_edit),
        icon="bi-pencil-square" if is_edit else "bi-plus-square",
        desc="Bezeichnung oder Rolle ist Pflicht." if not is_edit else None,
    )


def _render_preview_post(ui, guild, cid, chart, where, csrf) -> str:
    cache_bust = int(time.time())
    preview_src = f"/cogs/organigram?guild={guild.id}&preview={_esc(cid)}&t={cache_bust}"
    download_src = f"/cogs/organigram?guild={guild.id}&download={_esc(cid)}"
    preview = ui.card(
        "Vorschau",
        f"<div class='text-center'><img class='img-fluid rounded' src='{preview_src}' alt='Vorschau' loading='lazy'></div>",
        icon="bi-image", desc="So sieht die Bild-Ausgabe mit den aktuellen Einstellungen aus.",
        actions=ui.button("PNG herunterladen", icon="bi-download", kind="ghost", small=True, href=download_src),
    )
    chan_items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    # Pflichtauswahl: ohne Kanal meldet der Browser das Feld direkt.
    chan_select = ui.select("channel", chan_items, None, none_label="— Kanal wählen —").replace(
        "<select ", "<select required ", 1)
    current = (
        "".join(ui.badge(w, "ok") + " " for w in where) if where else ui.badge("noch nicht gepostet", "muted")
    )
    post = ui.card(
        "Posten",
        ui.form(
            "/cogs/organigram",
            ui.grid(
                ui.field("Kanal", chan_select),
                ui.field("Ausgabe", ui.select("mode", _MODE_ITEMS, _MODE_FORM.get(chart.get("mode", "image"), "bild"))),
                cols=1,
            )
            + ui.callout("Ein bereits geposteter Beitrag im selben Kanal wird aktualisiert statt neu erstellt. "
                         "Mit aktiviertem Auto-Update bleibt er danach automatisch aktuell.", tone="info")
            + ui.actions(ui.button("Posten / Aktualisieren", icon="bi-send")),
            csrf=csrf, hidden={"form": "post", "guild": guild.id, "chart": cid},
        )
        + f"<div class='wc-sub'>Aktuell gepostet in</div><div>{current}</div>",
        icon="bi-send",
    )
    return ui.columns(preview, post)


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
def _redirect(path: str):
    raise web.HTTPFound(path)


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
        raise web.HTTPFound("/cogs/organigram?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)
    base = f"/cogs/organigram?guild={guild.id}"

    # ---- neues Organigramm ---------------------------------------------- #
    if form == "chart_new":
        name = (data.get("name") or "").strip()
        if not name:
            raise web.HTTPFound(f"{base}&ok=Bitte+einen+Namen+angeben")
        async with gconf.charts() as charts:
            if any(c.get("name", "").lower() == name.lower() for c in charts.values()):
                raise web.HTTPFound(f"{base}&ok=Name+bereits+vergeben")
            new_id = secrets.token_hex(3)
            while new_id in charts:
                new_id = secrets.token_hex(3)
            charts[new_id] = {
                "name": name,
                "title": (data.get("title") or "").strip(),
                "pattern": data.get("pattern") if data.get("pattern") in PATTERNS else "baum",
                "mode": MODE_MAP.get(data.get("mode"), "image"),
                "accent": (data.get("accent") or "#3ddc97").strip(),
                "show_avatars": "show_avatars" in data,
                "show_vacant": "show_vacant" in data,
                "auto_update": "auto_update" in data,
                "nodes": {},
                "posts": [],
            }
        raise web.HTTPFound(f"{base}&chart={new_id}&ok=Organigramm+angelegt")

    # ---- Einstellungen speichern ---------------------------------------- #
    if form == "chart_settings":
        cid = data.get("chart")
        name = (data.get("name") or "").strip()
        async with gconf.charts() as charts:
            chart = charts.get(cid)
            if not chart:
                raise web.HTTPFound(f"{base}&ok=Organigramm+nicht+gefunden")
            if name and any(
                c.get("name", "").lower() == name.lower() and k != cid
                for k, c in charts.items()
            ):
                raise web.HTTPFound(f"{base}&chart={cid}&ok=Name+bereits+vergeben")
            if name:
                chart["name"] = name
            chart["title"] = (data.get("title") or "").strip()
            if data.get("pattern") in PATTERNS:
                chart["pattern"] = data.get("pattern")
            chart["mode"] = MODE_MAP.get(data.get("mode"), chart.get("mode", "image"))
            chart["accent"] = (data.get("accent") or "#3ddc97").strip()
            chart["show_avatars"] = "show_avatars" in data
            chart["show_vacant"] = "show_vacant" in data
            chart["auto_update"] = "auto_update" in data
            refresh = bool(chart.get("posts")) and chart["auto_update"]
        if refresh:  # gepostete Beiträge direkt nachziehen (vorher erst bei Rollen-Änderungen)
            cog._schedule(guild.id, cid)
        raise web.HTTPFound(f"{base}&chart={cid}&ok=Einstellungen+gespeichert")

    # ---- Organigramm löschen -------------------------------------------- #
    if form == "chart_delete":
        cid = data.get("chart")
        async with gconf.charts() as charts:
            charts.pop(cid, None)
        raise web.HTTPFound(f"{base}&ok=Organigramm+gel%C3%B6scht")

    # ---- Position speichern --------------------------------------------- #
    if form == "node_save":
        cid = data.get("chart")
        nid = data.get("node") or None
        label = (data.get("label") or "").strip()
        role_raw = data.get("role_id")
        role_id = int(role_raw) if role_raw and role_raw.isdigit() else None
        if not label and role_id is None:
            dest = f"{base}&chart={cid}" + (f"&node={nid}" if nid else "")
            raise web.HTTPFound(f"{dest}&ok=Bitte+Bezeichnung+oder+Rolle+angeben")

        manual = [ln.strip() for ln in (data.get("manual_names") or "").splitlines() if ln.strip()]
        try:
            order = int(data.get("order", 0))
        except (TypeError, ValueError):
            order = 0
        parent = data.get("parent") or None
        color = (data.get("color") or "#3ddc97").strip() if "use_color" in data else ""

        async with gconf.charts() as charts:
            chart = charts.get(cid)
            if not chart:
                raise web.HTTPFound(f"{base}&ok=Organigramm+nicht+gefunden")
            nodes = chart.setdefault("nodes", {})
            # Zyklus-Schutz: Elternteil darf nicht der Knoten selbst oder ein Nachfahre sein.
            if nid:
                forbidden = {nid} | _descendants(nodes, nid)
                if parent in forbidden:
                    parent = None
            if parent is not None and parent not in nodes:
                parent = None
            if not nid:
                nid = secrets.token_hex(3)
                while nid in nodes:
                    nid = secrets.token_hex(3)
            nodes[nid] = {
                "label": label,
                "parent": parent,
                "role_id": role_id,
                "manual_names": manual,
                "emoji": (data.get("emoji") or "").strip(),
                "color": color,
                "order": order,
            }
            refresh = bool(chart.get("posts")) and chart.get("auto_update", True)
        if refresh:
            cog._schedule(guild.id, cid)
        raise web.HTTPFound(f"{base}&chart={cid}&ok=Position+gespeichert")

    # ---- Position löschen (Kinder hochziehen) --------------------------- #
    if form == "node_delete":
        cid = data.get("chart")
        nid = data.get("node")
        refresh = False
        async with gconf.charts() as charts:
            chart = charts.get(cid)
            if chart:
                nodes = chart.get("nodes", {})
                victim = nodes.pop(nid, None)
                if victim is not None:
                    new_parent = victim.get("parent")
                    for nd in nodes.values():
                        if nd.get("parent") == nid:
                            nd["parent"] = new_parent
                refresh = bool(chart.get("posts")) and chart.get("auto_update", True)
        if refresh:
            cog._schedule(guild.id, cid)
        raise web.HTTPFound(f"{base}&chart={cid}&ok=Position+gel%C3%B6scht")

    # ---- Posten --------------------------------------------------------- #
    if form == "post":
        cid = data.get("chart")
        ch_raw = data.get("channel")
        channel = guild.get_channel(int(ch_raw)) if ch_raw and ch_raw.isdigit() else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise web.HTTPFound(f"{base}&chart={cid}&ok=Ung%C3%BCltiger+Kanal")
        charts = await gconf.charts()
        if cid not in charts:
            raise web.HTTPFound(f"{base}&ok=Organigramm+nicht+gefunden")
        mode = MODE_MAP.get(data.get("mode"), charts[cid].get("mode", "image"))
        ok, err = await cog._post_and_save(guild, cid, channel, mode)
        msg = "Gepostet" if ok else quote_plus(f"Fehler: {err or ''}")
        raise web.HTTPFound(f"{base}&chart={cid}&ok={msg}")

    raise web.HTTPFound(base)
