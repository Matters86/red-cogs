"""WebCore-Dashboard „Server-Layout“ (``/cogs/serverlayout``) – nur für den Bot-Owner (volle Sicht).

* GET                              -> Reiter Layouts · Speichern · Hochladen · Laden · Verlauf
* GET ?tab=laden&layout=…&preview=1 -> Vorschau (wird angelegt / geändert / gelöscht / übersprungen, Warnungen)
* GET ?download=<id>               -> Layout-Datei (JSON)
* GET ?status=json                 -> Fortschritt des laufenden Vorgangs (für die kleine JS-Abfrage)
* POST form=save|upload|rename|delete|apply|cancel

Rechte: Alles verlangt ``has_full_scope`` (Owner/Allowlist). Andere Nutzer mit Seiten-Recht sehen nur einen
Hinweis, jeder POST wird serverseitig abgelehnt. Kein Tagesgeschäft (``operate_forms`` nicht gesetzt).
Ziel-Server = globaler Server-Wechsler, Quelle = gespeichertes Layout.
"""

from __future__ import annotations

import html
import types
from urllib.parse import quote_plus

from aiohttp import web

from . import layout as L
from . import planner as P
from .strings import t

SLUG = "serverlayout"
TITLE = "Server-Layout"
BASE = f"/cogs/{SLUG}"
SEC_TITLES = [("roles", "Rollen", "bi-person-badge"), ("order", "Reihenfolge", "bi-sort-down"),
              ("categories", "Kategorien", "bi-folder2"), ("channels", "Kanäle", "bi-hash"),
              ("settings", "Server-Einstellungen", "bi-gear")]
OP_BADGE = {"create": ("anlegen", "ok"), "update": ("ändern", "info"), "delete": ("löschen", "bad"),
            "skip": ("übersprungen", "muted")}
STATUS_BADGE = {"done": ("fertig", "ok"), "cancelled": ("abgebrochen", "warn"), "failed": ("fehlgeschlagen", "bad"),
                "running": ("läuft", "info")}
LVL_BADGE = {"ok": ("ok", "ok"), "err": ("Fehler", "bad"), "skip": ("übersprungen", "muted"), "info": ("Info", "info")}


def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _plain(text: str) -> str:
    return (text or "").replace("**", "").replace("`", "")


def _go(gid, tab: str | None = None, *, ok: str | None = None, err: str | None = None, extra: str = "") -> dict:
    url = BASE + (f"?guild={gid}" if gid else "?")
    if tab:
        url += f"&tab={tab}"
    if extra:
        url += "&" + extra
    if ok:
        url += "&ok=" + quote_plus(ok[:300])
    if err:
        url += "&err=" + quote_plus(err[:300])
    return {"redirect": url.replace("?&", "?")}


def _upload_limit(request) -> int:
    """WebCore liest POST-Daten vorab mit dem App-Limit (Standard 1 MiB) – Uploads darüber lehnt aiohttp ab."""
    app_limit = int(getattr(request.app, "_client_max_size", 1024 ** 2) or 1024 ** 2)
    return max(64 * 1024, min(L.MAX_FILE_BYTES, app_limit - 16 * 1024))


def _parts_label(parts) -> str:
    return ", ".join(L.PART_LABELS[p] for p in parts) or "—"


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    wc = request.app["webcore"]
    ui = wc.ui
    full = await wc.has_full_scope(request)
    guilds = await wc.visible_guilds(request)
    by_id = {g.id: g for g in guilds}

    if request.method == "POST":
        form = await request.post()
        raw = str(form.get("guild") or "")
        guild = by_id.get(int(raw)) if raw.isdigit() else None
        if not full:
            return _go(guild.id if guild else None,
                       err="Server-Layouts verwaltet nur der Bot-Owner – Aktion abgelehnt.")
        return await _post(cog, request, wc, form, guild)

    raw = request.query.get("guild") or ""
    guild = by_id.get(int(raw)) if raw.isdigit() else (guilds[0] if guilds else None)
    if not full:
        return {"title": TITLE, "content": ui.hero("bi-diagram-3", "", "Server-Layouts speichern und laden.") + ui.card(
            "Nur für den Bot-Owner", ui.callout(
                "Layouts laden, hochladen und löschen darf nur der <b>Bot-Owner</b> – ein Layout kann ganze Server "
                "umbauen. Server-Administratoren können das Layout <i>ihres</i> Servers per Befehl "
                "<code>[p]layout save &lt;name&gt;</code> speichern.", tone="warn"), icon="bi-shield-lock")}
    if request.query.get("status") == "json":
        job = cog.job(guild.id) if guild else None
        data = job.status_json() if job else {"running": False, "status": "none", "done": 0, "total": 0,
                                              "percent": 0, "step": "", "counts": {}}
        return web.json_response(data, headers={"Cache-Control": "no-store"})
    dl = request.query.get("download")
    if dl:
        meta = next((m for m in await cog.layouts() if m["id"] == dl), None)
        if meta is None:
            return _go(guild.id if guild else None, "layouts", err="Layout nicht gefunden.")
        filename, raw_bytes = await cog.export_bytes(dl)
        return web.Response(body=raw_bytes, content_type="application/json", charset="utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                     "Cache-Control": "no-store"})
    if guild is None:
        return {"title": TITLE, "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    return {"title": TITLE, "content": await _page(cog, request, wc, ui, guild)}


# --------------------------------------------------------------------------- #
#  POST
# --------------------------------------------------------------------------- #
async def _post(cog, request, wc, form, guild):
    from .serverlayout import LoadError
    action = str(form.get("form") or "")
    gid = guild.id if guild else None
    if action == "upload":
        field = form.get("file")
        if field is None or not hasattr(field, "file"):
            return _go(gid, "hochladen", err="Bitte eine Layout-Datei (.json) auswählen.")
        raw = field.file.read(L.MAX_FILE_BYTES + 1)
        if len(raw) > L.MAX_FILE_BYTES:
            return _go(gid, "hochladen", err="Datei zu groß (höchstens 8 MB).")
        user = await wc.current_user(request) or {}
        try:
            meta = await cog.import_bytes(raw, creator_id=int(user.get("id") or 0),
                                          name=str(form.get("name") or "").strip() or None)
        except L.LayoutError as exc:
            return _go(gid, "hochladen", err=f"Datei abgelehnt: {exc}")
        return _go(gid, "layouts", ok=f"Layout „{meta['name']}“ hochgeladen.")
    if action == "rename":
        lid = str(form.get("layout") or "")
        try:
            meta = await cog.rename_layout(lid, str(form.get("new_name") or ""))
        except LoadError as exc:
            return _go(gid, "layouts", err=_plain(t("de", exc.key, **exc.kwargs)))
        except (ValueError, OSError):
            return _go(gid, "layouts", err="Layout nicht gefunden.")
        return _go(gid, "layouts", ok=f"Umbenannt in „{meta['name']}“.")
    if action == "delete":
        lid = str(form.get("layout") or "")
        meta = next((m for m in await cog.layouts() if m["id"] == lid), None)
        if meta is None:
            return _go(gid, "layouts", err="Layout nicht gefunden.")
        if any(j.running and j.layout_id == lid for j in cog._jobs.values()):
            return _go(gid, "layouts", err="Dieses Layout wird gerade geladen.")
        await cog.delete_layout(lid)
        return _go(gid, "layouts", ok=f"Layout „{meta['name']}“ gelöscht.")
    if guild is None:
        return _go(None, err="Server nicht gefunden.")
    if action == "save":
        parts = [p for p in L.PARTS if form.get(p)]
        if not parts:
            return _go(gid, "speichern", err="Bitte mindestens einen Teil wählen.")
        user = await wc.current_user(request) or {}
        try:
            meta, notes = await cog.save_layout(guild, str(form.get("name") or ""), parts,
                                                creator_id=int(user.get("id") or 0))
        except LoadError as exc:
            return _go(gid, "speichern", err=_plain(t("de", exc.key, **exc.kwargs)))
        except L.LayoutError as exc:
            return _go(gid, "speichern", err=str(exc))
        msg = f"Layout „{meta['name']}“ gespeichert."
        if notes:
            msg += " Hinweis: " + " ".join(notes)
        return _go(gid, "layouts", ok=msg)
    if action == "cancel":
        if cog.cancel(guild.id):
            return _go(gid, "verlauf", ok="Abbruch angefordert – der laufende Schritt wird noch beendet.")
        return _go(gid, "verlauf", err="Es läuft kein Ladevorgang.")
    if action == "apply":
        lid = str(form.get("layout") or "")
        mode = str(form.get("mode") or "merge")
        mode = mode if mode in P.MODES else "merge"
        parts = [p for p in str(form.get("parts") or "").split(",") if p in L.PARTS]
        back = f"layout={quote_plus(lid)}&mode={mode}&preview=1&" + "&".join(f"{p}=1" for p in parts)
        if mode == "exact" and str(form.get("confirm_name") or "").strip() != guild.name.strip():
            return _go(gid, "laden", extra=back, err="Server-Name falsch eingetippt – nichts geändert.")
        user = await wc.current_user(request) or {}
        who = types.SimpleNamespace(id=int(user.get("id") or 0), display_name=str(user.get("name") or "Dashboard"))
        try:
            await cog.start_load(guild, lid, mode=mode, parts=parts, user=who,
                                 expected_hash=str(form.get("hash") or "") or None)
        except LoadError as exc:
            return _go(gid, "laden", extra=back, err=_plain(t("de", exc.key, prefix="[p]", **exc.kwargs)))
        return _go(gid, "verlauf", ok="Laden gestartet – vorher wurde automatisch eine Sicherung angelegt.")
    return _go(gid, err="Unbekannte Aktion.")


# --------------------------------------------------------------------------- #
#  GET
# --------------------------------------------------------------------------- #
async def _page(cog, request, wc, ui, guild) -> str:
    csrf = request.get("webcore_csrf", "")
    metas = await cog.layouts()
    job = cog.job(guild.id)
    caps = P.bot_caps(guild)
    perms_ok = caps["manage_roles"] and caps["manage_channels"] and caps["manage_guild"]
    head = ui.hero("bi-diagram-3", "",
                   "Rollen, Kanäle und Server-Einstellungen als <b>Layout</b> speichern und auf einen anderen (oder "
                   f"denselben) Server laden. Ziel-Server: <b>{_esc(guild.name)}</b> – oben rechts wählen.")
    stats = ui.stats([
        ("Layouts", len(metas), "bi-collection", f"{sum(1 for m in metas if m.get('auto'))} automatisch", None),
        ("Ziel-Server", guild.name, "bi-hdd-network", f"{len(guild.roles)} Rollen · {len(guild.channels)} Kanäle", None),
        ("Bot-Rechte", "ok" if perms_ok else "fehlen", "bi-shield-check", None, "ok" if perms_ok else "bad"),
        ("Vorgang", "läuft" if job and job.running else "—", "bi-activity",
         f"{job.percent} %" if job and job.running else None, "info" if job and job.running else None),
    ])
    body = head + stats
    if job and job.running:
        body += ui.callout(f"Auf diesem Server wird gerade <b>{_esc(job.layout_name)}</b> geladen – Fortschritt im Reiter "
                           "„Verlauf“.", tone="info")
    body += ui.tab("layouts", "Layouts", "bi-collection", _tab_layouts(ui, csrf, guild, metas), count=len(metas))
    body += ui.tab("speichern", "Speichern", "bi-save", _tab_save(ui, csrf, guild))
    body += ui.tab("hochladen", "Hochladen", "bi-upload", _tab_upload(ui, csrf, guild, _upload_limit(request)))
    body += ui.tab("laden", "Laden", "bi-box-arrow-in-down", await _tab_load(cog, request, ui, csrf, guild, metas, perms_ok))
    reports = await cog.reports(guild)
    body += ui.tab("verlauf", "Verlauf", "bi-clock-history", _tab_history(ui, csrf, guild, job, reports),
                   count=len(reports) or None)
    return body


def _tab_layouts(ui, csrf, guild, metas) -> str:
    if not metas:
        return ui.card(body=ui.empty("bi-collection", "Noch keine Layouts",
                                     "Im Reiter „Speichern“ den aktuellen Server sichern oder eine Datei hochladen.",
                                     action=ui.goto("Server speichern", "speichern", icon="bi-save", kind="accent")))
    rows = []
    for m in metas:
        c = m.get("counts") or {}
        name = f"<b>{_esc(m['name'])}</b>" + (" " + ui.badge("automatisch", "muted") if m.get("auto") else "")
        acts = ui.actions(
            ui.button("Vorschau/Laden", icon="bi-eye", kind="ghost", small=True,
                      href=f"{BASE}?guild={guild.id}&tab=laden&layout={m['id']}"),
            ui.button("", icon="bi-download", kind="ghost", small=True, href=f"{BASE}?guild={guild.id}&download={m['id']}",
                      attrs={"title": "Herunterladen", "aria-label": "Herunterladen"}),
            ui.form(BASE, ui.button("", icon="bi-trash", kind="danger", small=True,
                                    attrs={"title": "Löschen", "aria-label": "Löschen"}),
                    csrf=csrf, hidden={"form": "delete", "layout": m["id"], "guild": guild.id}, cls="d-inline",
                    confirm=f"Layout „{m['name']}“ endgültig löschen?"),
        )
        rows.append(ui.row(
            name,
            f"{_esc(m.get('source_name') or '?')}<br><small class='text-muted mono'>{_esc(m.get('source_id') or '')}</small>",
            _esc(_fmt_date(m.get("created"))),
            _esc(_parts_label(m.get("parts") or [])) + f"<br><small class='text-muted'>{c.get('roles', 0)} Rollen · "
            f"{c.get('categories', 0)} Kat. · {c.get('channels', 0)} Kanäle</small>",
            ">" + _esc(_fmt_size(m.get("size") or 0)),
            acts,
        ))
    table = ui.table(["Name", "Quelle", "Datum", "Teile", ">Größe", "Aktionen"], rows, search=len(rows) > 6,
                     search_placeholder="Layouts durchsuchen …", id="sl-layouts")
    rename = ui.form(BASE, ui.grid(
        ui.field("Layout", ui.select("layout", [(m["id"], m["name"]) for m in metas])),
        ui.field("Neuer Name", ui.text_input("new_name", "", placeholder="z. B. Grundgerüst Community",
                                             attrs={"maxlength": L.MAX_LAYOUT_NAME, "required": True})),
    ) + ui.actions(ui.button("Umbenennen", icon="bi-pencil")), csrf=csrf, hidden={"form": "rename", "guild": guild.id})
    return (ui.card("Gespeicherte Layouts", table, icon="bi-collection",
                    desc="Layouts gelten botweit – jedes lässt sich auf jeden Server laden. Automatische Sicherungen "
                         "entstehen vor jedem Laden (die letzten 10 je Server bleiben).")
            + ui.card("Umbenennen", rename, icon="bi-pencil"))


def _fmt_size(n: int) -> str:
    from .serverlayout import fmt_size
    return fmt_size(n)


def _fmt_date(iso: str) -> str:
    from .serverlayout import fmt_date
    return fmt_date(iso)


def _part_switches(ui, selected, available=L.PARTS) -> str:
    desc = {"roles": "Name, Farbe, Rechte, Reihenfolge, @everyone – ohne Mitglieder",
            "channels": "Kategorien und Kanäle inkl. Berechtigungen für Rollen",
            "settings": "Name, Icon, Banner, Verifizierung, AFK/System-/Regel-Kanal …"}
    return ui.switches(*[ui.switch(p, L.PART_LABELS[p], p in selected, desc=desc[p], value="1")
                         for p in L.PARTS if p in available])


def _tab_save(ui, csrf, guild) -> str:
    form = ui.form(BASE, ui.grid(
        ui.field("Name", ui.text_input("name", f"{guild.name}"[:L.MAX_LAYOUT_NAME],
                                       attrs={"maxlength": L.MAX_LAYOUT_NAME, "required": True}),
                 help="1–64 Zeichen, eindeutig."),
        ui.field("Teile", _part_switches(ui, L.PARTS)),
    ) + ui.actions(ui.button("Layout speichern", icon="bi-save")),
        csrf=csrf, hidden={"form": "save", "guild": guild.id})
    info = ui.callout("Nicht gespeichert werden: Nachrichten, Mitglieder und ihre Rollen, Emojis/Sticker, Bans, Webhooks, "
                      "Einladungen. Überschreibungen für einzelne Mitglieder stehen nur zur Info in der Datei.", tone="info")
    return ui.card(f"„{guild.name}“ speichern", form + info, icon="bi-save",
                   desc="Speichert den oben rechts gewählten Server als neues Layout.")


def _tab_upload(ui, csrf, guild, limit: int) -> str:
    size = _fmt_size(limit)
    control = (f"<input class='wc-input' type='file' name='file' accept='.json,application/json' required "
               f"data-max='{limit}' data-max-label='{_esc(size)}'>")
    form = ui.form(BASE, ui.grid(
        ui.field("Layout-Datei", control, help=f"JSON-Datei aus „Herunterladen“ oder <code>[p]layout export</code> – "
                                               f"über das Dashboard höchstens <b>{_esc(size)}</b>, größere Dateien (bis 8 MB) "
                                               "per <code>[p]layout import</code> als Anhang."),
        ui.field("Name (optional)", ui.text_input("name", "", placeholder="Name aus der Datei",
                                                  attrs={"maxlength": L.MAX_LAYOUT_NAME})),
    ) + ui.actions(ui.button("Hochladen", icon="bi-upload")), csrf=csrf, hidden={"form": "upload", "guild": guild.id},
        enctype="multipart/form-data", id="sl-upload")
    js = ("<script>(function(){var f=document.getElementById('sl-upload');if(!f)return;f.addEventListener('submit',"
          "function(e){var i=f.querySelector('input[type=file]');var max=+i.getAttribute('data-max');"
          "if(i.files&&i.files[0]&&i.files[0].size>max){e.preventDefault();e.stopImmediatePropagation();"
          "var m='Datei zu groß für das Dashboard (höchstens '+i.getAttribute('data-max-label')+'). Bitte per "
          "[p]layout import hochladen.';if(window.wcToast)wcToast(m,true);else alert(m);}},true);})();</script>")
    note = ui.callout("Die Datei wird streng geprüft (Format <code>red-serverlayout</code>, Version 1, Limits von Discord); "
                      "unbekannte Felder werden ignoriert. Hochladen ändert noch nichts am Server.", tone="info")
    return ui.card("Layout hochladen", form + note, icon="bi-upload") + js


async def _tab_load(cog, request, ui, csrf, guild, metas, perms_ok) -> str:
    q = request.query
    lid = q.get("layout") or ""
    mode = q.get("mode") if q.get("mode") in P.MODES else "merge"
    preview = q.get("preview") == "1"
    meta = next((m for m in metas if m["id"] == lid), None)
    if not metas:
        return ui.card(body=ui.empty("bi-box-arrow-in-down", "Noch keine Layouts",
                                     "Zuerst ein Layout speichern oder hochladen."))
    available = meta.get("parts") if meta else L.PARTS
    parts = [p for p in L.PARTS if q.get(p)] if preview else list(available)
    options = [(m["id"], f"{m['name']} · {m.get('source_name') or '?'} · {_fmt_date(m.get('created'))}") for m in metas]
    choose = ui.form(BASE, ui.grid(
        ui.field("Layout (Quelle)", ui.select("layout", options, lid or None, none_label="— Layout wählen —")),
        ui.field("Modus", ui.select("mode", [("merge", "Ergänzen – nichts wird gelöscht"),
                                             ("exact", "Exakt angleichen – Überzähliges wird gelöscht")], mode),
                 help="<b>Ergänzen</b> legt Fehlendes an und passt Gleichnamiges an. <b>Exakt angleichen</b> löscht "
                      "zusätzlich Rollen/Kanäle, die nicht im Layout stehen."),
        ui.field("Teile anwenden", _part_switches(ui, parts), wide=True),
    ) + ui.actions(ui.button("Vorschau anzeigen", icon="bi-eye")), csrf=csrf, method="get",
        hidden={"guild": guild.id, "tab": "laden", "preview": "1"})
    out = ui.card(f"Layout auf „{guild.name}“ laden", choose, icon="bi-box-arrow-in-down",
                  desc="Ziel ist der oben rechts gewählte Server. Vor dem Anwenden kommt immer die Vorschau.")
    if not perms_ok:
        out += ui.callout("Dem Bot fehlen auf diesem Server <b>Rollen verwalten</b>, <b>Kanäle verwalten</b> oder "
                          "<b>Server verwalten</b> – Anwenden ist gesperrt.", tone="bad")
    if not preview:
        return out
    if meta is None:
        return out + ui.callout("Bitte ein Layout wählen.", tone="warn")
    if not parts:
        return out + ui.callout("Bitte mindestens einen Teil wählen.", tone="warn")
    try:
        _layout, plan = await cog.preview(guild, lid, mode, parts)
    except (L.LayoutError, OSError, ValueError) as exc:
        return out + ui.callout(f"Layout kann nicht gelesen werden: {_esc(exc)}", tone="bad")
    return out + _preview(ui, csrf, guild, meta, plan, cog.running(guild.id))


def _preview(ui, csrf, guild, meta, plan, busy: bool) -> str:
    c = plan["counts"]
    out = ui.stats([
        ("Wird angelegt", c["create"], "bi-plus-circle", None, "ok" if c["create"] else None),
        ("Wird geändert", c["update"], "bi-pencil", None, "info" if c["update"] else None),
        ("Wird gelöscht", c["delete"], "bi-trash", None, "bad" if c["delete"] else None),
        ("Übersprungen", c["skip"], "bi-skip-forward", None, "warn" if c["skip"] else None),
    ])
    for b in plan["blockers"]:
        out += ui.callout(_esc(b), tone="bad")
    if plan["warnings"]:
        out += ui.callout("<b>Warnungen</b><ul class='mb-0'>" + "".join(f"<li>{_esc(w)}</li>" for w in plan["warnings"])
                          + "</ul>", tone="warn")
    for sec, title, icon in SEC_TITLES:
        items = [it for it in plan["items"] if it["sec"] == sec]
        if not items:
            continue
        rows = []
        for it in items:
            label, tone = OP_BADGE[it["op"]]
            info = "; ".join(_esc(d) for d in it["details"])
            if it["reason"]:
                info = (info + "<br>" if info else "") + f"<span class='text-muted'>{_esc(it['reason'])}</span>"
            rows.append(ui.row(ui.badge(label, tone), f"<b>{_esc(it['label'])}</b>", info or "—"))
        counts = {op: sum(1 for it in items if it["op"] == op) for op in OP_BADGE}
        desc = " · ".join(f"{n} {OP_BADGE[op][0]}" for op, n in counts.items() if n)
        out += ui.card(title, ui.table(["Aktion", "Objekt", "Details"], rows, search=len(rows) > 12,
                                       id=f"sl-prev-{sec}"), icon=icon, desc=_esc(desc))
    if not plan["actionable"]:
        return out + ui.card(body=ui.empty("bi-check2-circle", "Nichts zu tun",
                                           "Der Server entspricht in den gewählten Teilen bereits dem Layout."))
    blocked = bool(plan["blockers"]) or busy
    fields = ""
    if plan["mode"] == "exact":
        fields = ui.grid(ui.field(
            "Server-Namen zur Bestätigung eintippen",
            ui.text_input("confirm_name", "", placeholder=guild.name, attrs={"required": True, "autocomplete": "off"}),
            help=f"Exakt angleichen löscht {c['delete']} Einträge. Tippe <b>{_esc(guild.name)}</b> ein.", wide=True))
    btn_attrs = {"disabled": True} if blocked else None
    text = (f"„{meta['name']}“ jetzt auf „{guild.name}“ laden ({P.MODE_LABELS[plan['mode']]})? "
            "Vorher wird automatisch eine Sicherung angelegt.")
    confirm = ui.form(BASE, fields + ui.callout(
        "Vor dem Laden wird der aktuelle Stand automatisch als Layout „Automatisch vor dem Laden – …“ gesichert. "
        "Gelöschte Kanäle kommen beim Zurückladen nur als <b>leere</b> Kanäle zurück – Nachrichten sind weg.", tone="info")
        + ui.actions(ui.button("Jetzt laden", icon="bi-play-fill", kind="danger" if plan["mode"] == "exact" else "accent",
                               attrs=btn_attrs)),
        csrf=csrf, confirm=None if blocked else text,
        hidden={"form": "apply", "guild": guild.id, "layout": meta["id"], "mode": plan["mode"],
                "parts": ",".join(plan["parts"]), "hash": plan["hash"]})
    if busy:
        confirm = ui.callout("Auf diesem Server läuft bereits ein Ladevorgang.", tone="warn") + confirm
    return out + ui.card("Anwenden", confirm, icon="bi-play-circle",
                         tone="bad" if plan["mode"] == "exact" else None,
                         desc=f"Modus <b>{_esc(P.MODE_LABELS[plan['mode']])}</b> · Teile: {_esc(_parts_label(plan['parts']))}")


def _tab_history(ui, csrf, guild, job, reports) -> str:
    out = ""
    if job and job.running:
        meter = (f"<div class='meter'><div class='mlabel'><span class='k' id='sl-step'>{_esc(job.step)}</span>"
                 f"<span class='v' id='sl-count'>{job.done} / {job.total}</span></div>"
                 f"<div class='bar'><span id='sl-bar' style='width:{job.percent}%'></span></div></div>")
        cancel = ui.form(BASE, ui.actions(ui.button("Abbrechen", icon="bi-stop-circle", kind="danger")), csrf=csrf,
                         hidden={"form": "cancel", "guild": guild.id},
                         confirm="Laden abbrechen? Bereits ausgeführte Schritte bleiben bestehen.")
        js = ("<script>(function(){var g=" + str(int(guild.id)) + ";function tick(){fetch('" + BASE + "?guild='+g+"
              "'&status=json',{credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(r)"
              "{return r.json();}).then(function(s){var b=document.getElementById('sl-bar');if(b)b.style.width=s.percent+'%';"
              "var t=document.getElementById('sl-step');if(t)t.textContent=s.step;var c=document.getElementById('sl-count');"
              "if(c)c.textContent=s.done+' / '+s.total;if(!s.running){location.href='" + BASE + "?guild='+g+'&tab=verlauf';}"
              "else setTimeout(tick,2000);}).catch(function(){setTimeout(tick,5000);});}setTimeout(tick,2000);})();</script>"
              "<noscript><meta http-equiv='refresh' content='5'></noscript>")
        out += ui.card(f"Läuft: {job.layout_name}", meter + ui.divider() + cancel, icon="bi-activity",
                       desc=f"{_esc(P.MODE_LABELS.get(job.mode, job.mode))} · gestartet von {_esc(job.user_name)}"
                            + (f" · Sicherung: {_esc(job.backup_name)}" if job.backup_name else "")) + js
    if not reports:
        return out + ui.card(body=ui.empty("bi-clock-history", "Noch keine Ladevorgänge auf diesem Server"))
    from datetime import datetime, timezone
    for r in reports:
        label, tone = STATUS_BADGE.get(r.get("status"), ("?", "muted"))
        cnt = r.get("counts") or {}
        when = datetime.fromtimestamp(int(r.get("finished") or 0), timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        summary = (f"{cnt.get('created', 0)} angelegt · {cnt.get('updated', 0)} geändert · {cnt.get('deleted', 0)} gelöscht · "
                   f"{cnt.get('skipped', 0)} übersprungen · {cnt.get('errors', 0)} Fehler")
        kv = ("<dl class='wc-kv'>"
              f"<dt>Ergebnis</dt><dd>{ui.badge(label, tone)} {_esc(summary)}</dd>"
              f"<dt>Modus / Teile</dt><dd>{_esc(P.MODE_LABELS.get(r.get('mode'), r.get('mode')))} · "
              f"{_esc(_parts_label(r.get('parts') or []))}</dd>"
              f"<dt>Von</dt><dd>{_esc(r.get('user_name') or '—')}</dd>"
              f"<dt>Sicherung vorher</dt><dd>{_esc(r.get('backup_name') or '—')}</dd>"
              + (f"<dt>Fehler</dt><dd>{_esc(r['error'])}</dd>" if r.get("error") else "")
              + "</dl>")
        lines = "".join(
            f"<li>{ui.badge(*LVL_BADGE.get(x.get('lvl'), ('?', 'muted')))}<span>{_esc(x.get('msg'))}</span></li>"
            for x in r.get("log") or [])
        log_html = (f"<details class='mt-3'><summary>Protokoll ({len(r.get('log') or [])} Zeilen)</summary>"
                    f"<ul class='wc-list'>{lines}</ul></details>") if lines else ""
        out += ui.card(f"{r.get('layout_name')} – {when}", kv + log_html, icon="bi-journal-text")
    return out
