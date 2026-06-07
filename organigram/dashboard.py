"""WebCore-Dashboard für den Organigram-Cog.

Aufbau:
* GET  -> Seite rendern: Server-Auswahl, Organigramm-Liste, Editor.
         Zusätzlich Bild-Endpunkte ``?preview=<id>`` und ``?download=<id>``,
         die direkt ein PNG zurückgeben (Live-Vorschau / Export).
* POST -> Formular verarbeiten, danach Redirect (Post/Redirect/Get).

Es werden nur die Theme-Klassen (card-x, table, btn-accent …) sowie die ohnehin
geladenen Bootstrap-Formularklassen genutzt – kein eigenes Design.
"""

from __future__ import annotations

import html
import logging
import os
import re
import secrets
import time
from collections import defaultdict

import discord
from aiohttp import web

from .render import PATTERNS

log = logging.getLogger("red.red-cogs.organigram")

_PREVIEW_DIR = os.path.join(os.path.dirname(__file__), "assets", "previews")

# Eingabe (DE im Formular) -> intern gespeicherter Modus
MODE_MAP = {"bild": "image", "embed": "embed", "text": "text"}
MODE_LABEL = {"image": "Bild", "embed": "Embed", "text": "Text"}

_FORM_STYLE = """
<style>
  .og-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .og-form input,.og-form select,.og-form textarea{width:100%;
    background:var(--panel-2);color:var(--text);border:1px solid var(--border);
    border-radius:9px;padding:9px 11px;font-family:inherit;font-size:.92rem}
  .og-form textarea{min-height:80px;resize:vertical;font-family:"IBM Plex Mono",monospace}
  .og-form input[type=color]{height:42px;padding:4px;cursor:pointer}
  .og-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .og-form .row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
  .og-form .hint{color:var(--muted);font-size:.78rem;margin-top:4px}
  .og-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .og-check input{width:auto}
  .og-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .og-section-title{font-family:"Archivo",sans-serif;font-weight:700;
    font-size:1.15rem;margin:0 0 14px}
  .og-spacer{height:26px}
  .og-actions{display:flex;gap:8px;flex-wrap:wrap}
  .og-actions form{margin:0}
  .og-btn-sm{padding:5px 12px}
  .og-preview-wrap{background:var(--panel-2);border:1px solid var(--border);
    border-radius:12px;padding:14px;text-align:center}
  .og-preview-wrap img{max-width:100%;height:auto;border-radius:8px}
  .og-grid2{display:grid;grid-template-columns:1.1fr .9fr;gap:20px;align-items:start}
  @media (max-width:860px){.og-grid2{grid-template-columns:1fr}}
  .og-muster{margin-top:10px;background:var(--panel-2);border:1px solid var(--border);
    border-radius:10px;padding:10px;text-align:center}
  .og-muster img{max-width:100%;max-height:240px;height:auto;border-radius:7px;
    display:block;margin:0 auto}
  .og-muster-cap{display:block;color:var(--muted);font-size:.78rem;margin-top:7px}
</style>
<script>
  function ogMuster(sel){
    var box = sel.parentNode.querySelector('.og-muster');
    if(!box){ return; }
    var img = box.querySelector('img');
    var cap = box.querySelector('.og-muster-cap');
    if(img){ img.src = img.getAttribute('data-base') + encodeURIComponent(sel.value); }
    if(cap){ cap.textContent = sel.options[sel.selectedIndex].text; }
  }
</script>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "organigramm").lower()).strip("-")
    return s or "organigramm"


def _options(items, selected_ids, *, none_label: str | None = None) -> str:
    sel = {str(s) for s in (selected_ids or [])}
    out = []
    if none_label is not None:
        is_sel = " selected" if not sel else ""
        out.append(f"<option value=''{is_sel}>{_esc(none_label)}</option>")
    for ident, label in items:
        is_sel = " selected" if str(ident) in sel else ""
        out.append(f"<option value='{_esc(ident)}'{is_sel}>{_esc(label)}</option>")
    return "".join(out)


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


# --------------------------------------------------------------------------- #
#  Einstiegspunkt
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


def _selected_guild(cog, request):
    gid = request.query.get("guild")
    if gid and gid.isdigit():
        g = cog.bot.get_guild(int(gid))
        if g is not None:
            return g
    guilds = sorted(cog.bot.guilds, key=lambda g: g.name.lower())
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

    guild = _selected_guild(cog, request)
    if guild is None:
        return {"title": "Organigramm",
                "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

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

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='og-flash'>{_esc(request.query.get('ok'))}</div>"

    guild_opts = _options(
        [(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())],
        [guild.id],
    )
    guild_picker = f"""
    <div class='card-x' style='margin-bottom:20px'>
      <form method='get' action='/cogs/organigram' class='og-form' style='margin:0'>
        <label style='margin-top:0'>Server</label>
        <select name='guild' onchange='this.form.submit()'>{guild_opts}</select>
      </form>
    </div>
    """

    sel_cid = request.query.get("chart")
    selected = charts.get(sel_cid) if sel_cid else None

    if selected:
        body = _render_editor(cog, guild, sel_cid, selected, csrf, request)
    else:
        body = _render_list(guild, charts, csrf) + "<div class='og-spacer'></div>" + _render_new(guild, csrf)

    content = _FORM_STYLE + flash + guild_picker + body
    return {"title": "Organigramm", "content": content}


def _render_list(guild, charts, csrf) -> str:
    rows = []
    for cid, c in charts.items():
        n = len(c.get("nodes", {}))
        posts = c.get("posts", [])
        where = ", ".join(
            f"#{ch.name}" for p in posts
            if (ch := guild.get_channel(p.get("channel_id"))) is not None
        ) or "—"
        pat = PATTERNS.get(c.get("pattern", "baum"), c.get("pattern", "baum"))
        edit_link = f"/cogs/organigram?guild={guild.id}&chart={_esc(cid)}"
        rows.append(
            "<tr>"
            f"<td><strong>{_esc(c.get('name', '?'))}</strong></td>"
            f"<td>{_esc(pat)}</td>"
            f"<td>{_esc(MODE_LABEL.get(c.get('mode', 'image'), 'Bild'))}</td>"
            f"<td>{n}</td>"
            f"<td style='color:var(--muted)'>{_esc(where)}</td>"
            "<td><div class='og-actions'>"
            f"<a class='btn-accent og-btn-sm' href='{edit_link}'>Bearbeiten</a>"
            f"<form method='post' action='/cogs/organigram' onsubmit=\"return confirm('Organigramm wirklich löschen?')\">"
            f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
            f"<input type='hidden' name='form' value='chart_delete'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='chart' value='{_esc(cid)}'>"
            "<button class='btn-accent og-btn-sm'>Löschen</button></form>"
            "</div></td>"
            "</tr>"
        )
    table = (
        "<table class='table'><thead><tr>"
        "<th>Name</th><th>Muster</th><th>Standard-Modus</th><th>Positionen</th>"
        "<th>Gepostet in</th><th></th>"
        "</tr></thead><tbody>"
        + ("".join(rows)
           or "<tr><td colspan='6' style='color:var(--muted)'>Noch keine Organigramme – lege unten eines an.</td></tr>")
        + "</tbody></table>"
    )
    return f"<div class='card-x'><div class='og-section-title'>Organigramme</div>{table}</div>"


def _pattern_options(selected: str) -> str:
    return "".join(
        f"<option value='{key}'{' selected' if selected == key else ''}>{_esc(label)}</option>"
        for key, label in PATTERNS.items()
    )


def _muster_preview(selected: str) -> str:
    base = "/cogs/organigram?muster="
    label = PATTERNS.get(selected, selected)
    return (
        "<div class='og-muster'>"
        f"<img alt='Muster-Vorschau' loading='lazy' data-base='{base}' "
        f"src='{base}{_esc(selected)}'>"
        f"<span class='og-muster-cap'>{_esc(label)}</span>"
        "</div>"
    )


def _mode_options(internal_selected: str) -> str:
    # internal_selected ist "image"/"embed"/"text"
    pairs = [("bild", "Bild", "image"), ("embed", "Embed", "embed"), ("text", "Text", "text")]
    return "".join(
        f"<option value='{val}'{' selected' if internal_selected == intern else ''}>{label}</option>"
        for val, label, intern in pairs
    )


def _render_new(guild, csrf) -> str:
    return f"""
    <div class='card-x'>
      <div class='og-section-title'>Neues Organigramm</div>
      <form class='og-form' method='post' action='/cogs/organigram'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='chart_new'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <div class='row2'>
          <div>
            <label>Name (für Befehle, z.&nbsp;B. „Leitung“)</label>
            <input name='name' required placeholder='Leitung'>
          </div>
          <div>
            <label>Muster (für Bild-Modus)</label>
            <select name='pattern' onchange='ogMuster(this)'>{_pattern_options('baum')}</select>
            {_muster_preview('baum')}
          </div>
        </div>
        <div class='row3'>
          <div>
            <label>Standard-Ausgabe</label>
            <select name='mode'>{_mode_options('image')}</select>
          </div>
          <div>
            <label>Akzentfarbe</label>
            <input type='color' name='accent' value='#3ddc97'>
          </div>
          <div>
            <label>Titel (optional)</label>
            <input name='title' placeholder='= Name'>
          </div>
        </div>
        <div class='og-check'><input type='checkbox' name='show_avatars' checked>
          <span>Avatare im Bild anzeigen</span></div>
        <div class='og-check'><input type='checkbox' name='show_vacant' checked>
          <span>Leere Positionen als „unbesetzt“ zeigen</span></div>
        <div class='og-check'><input type='checkbox' name='auto_update' checked>
          <span>Geposteten Beitrag automatisch aktualisieren</span></div>
        <div class='og-spacer'></div>
        <button class='btn-accent' type='submit'>Anlegen</button>
      </form>
    </div>
    """


def _render_editor(cog, guild, cid, chart, csrf, request) -> str:
    nodes = chart.get("nodes", {})
    accent = (chart.get("accent") or "#3ddc97").strip()
    if not accent.startswith("#"):
        accent = "#" + accent

    back = f"/cogs/organigram?guild={guild.id}"

    # --- Einstellungen ---------------------------------------------------- #
    settings = f"""
    <div class='card-x'>
      <div class='og-section-title'>Einstellungen · {_esc(chart.get('name', '?'))}</div>
      <form class='og-form' method='post' action='/cogs/organigram'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='chart_settings'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <input type='hidden' name='chart' value='{_esc(cid)}'>
        <div class='row2'>
          <div><label>Name</label><input name='name' required value='{_esc(chart.get('name', ''))}'></div>
          <div><label>Titel im Bild</label>
            <input name='title' value='{_esc(chart.get('title', ''))}' placeholder='= Name'></div>
        </div>
        <div class='row3'>
          <div><label>Muster (Bild)</label>
            <select name='pattern' onchange='ogMuster(this)'>{_pattern_options(chart.get('pattern', 'baum'))}</select>
            {_muster_preview(chart.get('pattern', 'baum'))}</div>
          <div><label>Standard-Ausgabe</label>
            <select name='mode'>{_mode_options(chart.get('mode', 'image'))}</select></div>
          <div><label>Akzentfarbe</label>
            <input type='color' name='accent' value='{_esc(accent)}'></div>
        </div>
        <div class='og-check'><input type='checkbox' name='show_avatars' {'checked' if chart.get('show_avatars', True) else ''}>
          <span>Avatare im Bild anzeigen</span></div>
        <div class='og-check'><input type='checkbox' name='show_vacant' {'checked' if chart.get('show_vacant', True) else ''}>
          <span>Leere Positionen als „unbesetzt“ zeigen</span></div>
        <div class='og-check'><input type='checkbox' name='auto_update' {'checked' if chart.get('auto_update', True) else ''}>
          <span>Geposteten Beitrag automatisch aktualisieren</span></div>
        <div class='og-spacer'></div>
        <button class='btn-accent' type='submit'>Einstellungen speichern</button>
      </form>
    </div>
    """

    # --- Vorschau + Posten ------------------------------------------------ #
    cache_bust = int(time.time())
    preview_src = f"/cogs/organigram?guild={guild.id}&preview={_esc(cid)}&t={cache_bust}"
    download_src = f"/cogs/organigram?guild={guild.id}&download={_esc(cid)}"
    chan_opts = _options([(c.id, f"#{c.name}") for c in guild.text_channels],
                         [], none_label="— Kanal wählen —")
    preview_post = f"""
    <div class='card-x'>
      <div class='og-section-title'>Vorschau &amp; Posten</div>
      <div class='og-preview-wrap'>
        <img src='{preview_src}' alt='Vorschau' loading='lazy'>
      </div>
      <div class='og-actions' style='margin-top:12px'>
        <a class='btn-accent og-btn-sm' href='{download_src}'>PNG herunterladen</a>
      </div>
      <div class='og-spacer'></div>
      <form class='og-form' method='post' action='/cogs/organigram'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='post'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <input type='hidden' name='chart' value='{_esc(cid)}'>
        <div class='row2'>
          <div><label>Kanal</label><select name='channel' required>{chan_opts}</select></div>
          <div><label>Modus</label><select name='mode'>{_mode_options(chart.get('mode', 'image'))}</select></div>
        </div>
        <div class='hint'>Postet das Organigramm und hält es automatisch aktuell. Ein bereits
          geposteter Beitrag im selben Kanal wird aktualisiert statt neu erstellt.</div>
        <div class='og-spacer'></div>
        <button class='btn-accent' type='submit'>Posten / Aktualisieren</button>
      </form>
    </div>
    """

    # --- Positionen-Tabelle ---------------------------------------------- #
    def label_of(nid):
        nd = nodes.get(nid, {})
        if nd.get("label"):
            return nd["label"]
        if nd.get("role_id"):
            r = guild.get_role(nd["role_id"])
            if r:
                return r.name
        return "(ohne Titel)"

    prows = []
    for nid, nd in sorted(nodes.items(), key=lambda kv: (kv[1].get("order", 0), label_of(kv[0]).lower())):
        role = guild.get_role(nd["role_id"]) if nd.get("role_id") else None
        role_name = f"@{role.name}" if role else ("@gelöscht" if nd.get("role_id") else "—")
        parent_lbl = label_of(nd["parent"]) if nd.get("parent") in nodes else "— (oberste Ebene)"
        manual = len([m for m in nd.get("manual_names", []) if (m or "").strip()])
        n_people = (len(role.members) if role else 0) + manual
        edit_link = f"/cogs/organigram?guild={guild.id}&chart={_esc(cid)}&node={_esc(nid)}"
        prows.append(
            "<tr>"
            f"<td><strong>{_esc(label_of(nid))}</strong></td>"
            f"<td style='color:var(--muted)'>{_esc(role_name)}</td>"
            f"<td style='color:var(--muted)'>{_esc(parent_lbl)}</td>"
            f"<td>{n_people}</td>"
            "<td><div class='og-actions'>"
            f"<a class='btn-accent og-btn-sm' href='{edit_link}'>Bearbeiten</a>"
            f"<form method='post' action='/cogs/organigram' onsubmit=\"return confirm('Position löschen?')\">"
            f"<input type='hidden' name='csrf_token' value='{_esc(csrf)}'>"
            f"<input type='hidden' name='form' value='node_delete'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input type='hidden' name='chart' value='{_esc(cid)}'>"
            f"<input type='hidden' name='node' value='{_esc(nid)}'>"
            "<button class='btn-accent og-btn-sm'>Löschen</button></form>"
            "</div></td>"
            "</tr>"
        )
    ptable = (
        "<table class='table'><thead><tr>"
        "<th>Position</th><th>Rolle</th><th>Übergeordnet</th><th>Personen</th><th></th>"
        "</tr></thead><tbody>"
        + ("".join(prows)
           or "<tr><td colspan='5' style='color:var(--muted)'>Noch keine Positionen.</td></tr>")
        + "</tbody></table>"
    )
    positions = f"<div class='card-x'><div class='og-section-title'>Positionen</div>{ptable}</div>"

    # --- Knoten-Editor --------------------------------------------------- #
    node_editor = _render_node_editor(guild, cid, nodes, csrf, request)

    head = (
        f"<div style='margin-bottom:14px'><a class='btn-accent og-btn-sm' href='{back}'>"
        "← Alle Organigramme</a></div>"
    )
    grid = f"<div class='og-grid2'>{settings}{preview_post}</div>"
    return (head + grid + "<div class='og-spacer'></div>" + positions
            + "<div class='og-spacer'></div>" + node_editor)


def _render_node_editor(guild, cid, nodes, csrf, request) -> str:
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
    role_opts = _options([(r.id, r.name) for r in roles],
                         [nd.get("role_id")] if nd.get("role_id") else [],
                         none_label="— keine Rolle —")

    # Übergeordnete Position: alle außer sich selbst und eigenen Nachfahren
    forbidden = {sel_nid} | (_descendants(nodes, sel_nid) if sel_nid else set())

    def label_of(nid):
        n = nodes.get(nid, {})
        if n.get("label"):
            return n["label"]
        if n.get("role_id"):
            r = guild.get_role(n["role_id"])
            if r:
                return r.name
        return "(ohne Titel)"

    parent_items = [(nid, label_of(nid)) for nid in nodes if nid not in forbidden]
    parent_opts = _options(parent_items,
                           [nd.get("parent")] if nd.get("parent") else [],
                           none_label="— (oberste Ebene)")

    manual_text = "\n".join(nd.get("manual_names", []) or [])
    title = "Position bearbeiten" if is_edit else "Neue Position"
    node_hidden = f"<input type='hidden' name='node' value='{_esc(sel_nid)}'>" if sel_nid else ""

    return f"""
    <div class='card-x'>
      <div class='og-section-title'>{_esc(title)}</div>
      <form class='og-form' method='post' action='/cogs/organigram'>
        <input type='hidden' name='csrf_token' value='{_esc(csrf)}'>
        <input type='hidden' name='form' value='node_save'>
        <input type='hidden' name='guild' value='{guild.id}'>
        <input type='hidden' name='chart' value='{_esc(cid)}'>
        {node_hidden}
        <div class='row2'>
          <div><label>Bezeichnung der Position</label>
            <input name='label' value='{_esc(nd.get('label', ''))}' placeholder='z.&nbsp;B. Administration'>
            <div class='hint'>Leer lassen, um den Rollennamen zu verwenden.</div></div>
          <div><label>Übergeordnete Position</label>
            <select name='parent'>{parent_opts}</select></div>
        </div>
        <div class='row2'>
          <div><label>Verknüpfte Rolle (Mitglieder automatisch)</label>
            <select name='role_id'>{role_opts}</select></div>
          <div><label>Reihenfolge</label>
            <input type='number' name='order' value='{int(nd.get('order', 0) or 0)}'>
            <div class='hint'>Kleinere Zahl = weiter links/oben.</div></div>
        </div>
        <label>Zusätzliche Namen (eine Person pro Zeile)</label>
        <textarea name='manual_names' placeholder='Max Mustermann&#10;Erika Beispiel'>{_esc(manual_text)}</textarea>
        <div class='hint'>Für Personen ohne passende Discord-Rolle. Werden zusätzlich zu den
          Rollenmitgliedern angezeigt.</div>
        <div class='row2'>
          <div><label>Emoji (nur Embed-/Text-Modus)</label>
            <input name='emoji' value='{_esc(nd.get('emoji', ''))}' placeholder='👑'></div>
          <div>
            <div class='og-check' style='margin-top:32px'>
              <input type='checkbox' name='use_color' {'checked' if has_color else ''}>
              <span>Eigene Farbe statt Rollenfarbe</span></div>
            <input type='color' name='color' value='{_esc(color_val)}'></div>
        </div>
        <div class='og-spacer'></div>
        <div class='og-actions'>
          <button class='btn-accent' type='submit'>Position speichern</button>
          <a class='btn-accent og-btn-sm' href='/cogs/organigram?guild={guild.id}&chart={_esc(cid)}'
             style='display:inline-flex;align-items:center'>Abbrechen / Neu</a>
        </div>
      </form>
    </div>
    """


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
def _redirect(path: str):
    raise web.HTTPFound(path)


async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    gid = data.get("guild")
    guild = cog.bot.get_guild(int(gid)) if gid and gid.isdigit() else None
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
        raise web.HTTPFound(f"{base}&chart={cid}&ok=Position+gespeichert")

    # ---- Position löschen (Kinder hochziehen) --------------------------- #
    if form == "node_delete":
        cid = data.get("chart")
        nid = data.get("node")
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
        msg = "Gepostet" if ok else f"Fehler:+{(err or '').replace(' ', '+')}"
        raise web.HTTPFound(f"{base}&chart={cid}&ok={msg}")

    raise web.HTTPFound(base)
