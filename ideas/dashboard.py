"""WebCore-Dashboard des Ideas-Cogs („Ideen“, ``/cogs/ideas``).

* GET                     -> Kennzahlen je Status · Reiter Ideen · Umfrage · Einstellungen · Sperren
* GET ?idea=<nr>          -> Detailansicht (Verlauf, Status/Kommentar, Zusammenführen, Bearbeiten, Löschen)
* GET ?export=csv         -> CSV-Export aller Ideen
* POST form=status|comment|merge|edit|delete           -> einzelne Idee (Tagesgeschäft)
* POST form=bulk_status|poll_select                    -> Auswahl aus der Tabelle (Tagesgeschäft)
* POST form=poll                                       -> Umfrage aus Ideen über den Poll-Cog (Tagesgeschäft)
* POST form=settings|panel|create_forum|tags|block|unblock -> braucht „Bearbeiten“

Alles mit dem UI-Kit von WebCore, Werte mit ``html.escape``. Server nur über ``visible_guilds``.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import discord
from aiohttp import web

from .strings import LANGUAGES, OPEN_STATUSES, STATUS_EMOJI, STATUSES, status_label

SLUG = "ideas"
BASE = f"/cogs/{SLUG}"
OPERATE_FORMS = ("status", "comment", "merge", "edit", "delete", "bulk_status", "poll_select", "poll")
STATUS_TONE = {"new": "info", "review": "warn", "planned": "info", "done": "ok", "rejected": "bad", "merged": "muted"}
SOURCE_LABEL = {"form": "Formular (Discord)", "web": "Website", "manual": "Manueller Beitrag"}


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _ts(ts) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def _go(guild, key="ok", text="", **extra) -> dict:
    params = {"guild": guild.id, **{k: v for k, v in extra.items() if v not in (None, "")}}
    if text:
        params[key] = text
    return {"redirect": f"{BASE}?{urlencode(params)}"}


def _badge(ui, status):
    return ui.badge(f"{STATUS_EMOJI.get(status, '')} {status_label('de', status)}", STATUS_TONE.get(status, "muted"))


async def _visible_guilds(request):
    webcore = request.app["webcore"]
    return sorted(await webcore.visible_guilds(request), key=lambda g: g.name.lower())


def _pick(guilds, gid):
    if gid and str(gid).isdigit():
        for g in guilds:
            if g.id == int(gid):
                return g
    return None


class _Who:
    """Dashboard-Nutzer als ``by`` für den Verlauf (id + Name)."""

    def __init__(self, user, member=None):
        self.id = int((user or {}).get("id") or 0)
        self.display_name = getattr(member, "display_name", None) or (user or {}).get("name") or ""


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    ui = request.app["webcore"].ui
    guilds = await _visible_guilds(request)
    guild = _pick(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": "Ideen", "content": ui.card(body=ui.empty("bi-hdd-network", "Der Bot ist auf keinem Server."))}
    if request.query.get("export") == "csv":
        body = await cog.export_csv(guild)
        return web.Response(body=body, content_type="text/csv", charset="utf-8",
                            headers={"Content-Disposition": f"attachment; filename=\"ideen-{guild.id}.csv\"",
                                     "Cache-Control": "no-store"})
    data = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    webcore = request.app["webcore"]
    can_edit = await webcore.can_edit(request, guild) if hasattr(webcore, "can_edit") else not request.get("webcore_readonly")
    nr = request.query.get("idea")
    if nr and nr.isdigit() and str(int(nr)) in (data.get("ideas") or {}):
        return {"title": "Ideen · Details", "content": _render_detail(cog, ui, guild, data, int(nr), csrf)}
    return {"title": "Ideen", "content": await _render_main(cog, request, ui, guild, data, csrf, can_edit)}


# --------------------------------------------------------------------------- #
#  Hauptseite
# --------------------------------------------------------------------------- #
async def _render_main(cog, request, ui, guild, data, csrf, can_edit):
    ideas = [i for i in (data.get("ideas") or {}).values() if isinstance(i, dict)]
    live = [i for i in ideas if not i.get("deleted")]
    counts = {s: sum(1 for i in live if i.get("status") == s) for s in STATUSES}
    forum = cog.forum_of(guild, data)
    head = ui.hero(
        "bi-lightbulb", "",
        "Mitglieder reichen Ideen per Formular ein – jede Idee wird ein eigener Beitrag im Ideen-Forum. "
        "Hier setzt ihr den Status, führt Duplikate zusammen und startet Umfragen aus mehreren Ideen.",
        actions=ui.button("CSV-Export", icon="bi-download", kind="ghost", small=True,
                          href=f"{BASE}?guild={guild.id}&export=csv"),
    ) + ui.stats([("Duplikate" if s == "merged" else status_label("de", s), counts[s], _icon(s),
                   "zusammengeführt" if s == "merged" else None, _stat_tone(s, counts[s])) for s in STATUSES])
    if forum is None:
        head += ui.callout("Noch kein Ideen-Forum eingestellt – unter <b>Einstellungen</b> ein Forum wählen oder "
                           "mit „Forum anlegen“ ein fertig eingerichtetes erstellen.", tone="warn")
    body = (
        ui.tab("ideen", "Ideen", "bi-lightbulb", _render_list(cog, request, ui, guild, data, live, csrf),
               count=len(live))
        + ui.tab("umfrage", "Umfrage", "bi-bar-chart", await _render_poll(cog, request, ui, guild, data, live, csrf))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", _render_settings(cog, ui, guild, data, csrf, can_edit))
        + ui.tab("sperren", "Sperren", "bi-slash-circle", _render_blocked(ui, guild, data, csrf),
                 count=len(data.get("blocked") or []))
    )
    return head + body


def _icon(status):
    return {"new": "bi-stars", "review": "bi-search", "planned": "bi-calendar-check", "done": "bi-check2-circle",
            "rejected": "bi-x-circle", "merged": "bi-link-45deg"}.get(status, "bi-lightbulb")


def _stat_tone(status, n):
    if not n:
        return None
    return {"new": "info", "review": "warn", "done": "ok", "rejected": "bad"}.get(status)


def _render_list(cog, request, ui, guild, data, live, csrf):
    q = request.query
    f_status = q.get("status", "")
    f_cat = q.get("cat", "")
    sort = q.get("sort", "new")
    rows_src = [i for i in (data.get("ideas") or {}).values() if isinstance(i, dict)]
    if f_status == "deleted":
        items = [i for i in rows_src if i.get("deleted")]
    else:
        items = list(live)
        if f_status == "open":
            items = [i for i in items if i.get("status") in OPEN_STATUSES]
        elif f_status in STATUSES:
            items = [i for i in items if i.get("status") == f_status]
    if f_cat == "__none__":
        items = [i for i in items if not i.get("category")]
    elif f_cat:
        items = [i for i in items if i.get("category") == f_cat]
    if sort == "old":
        items.sort(key=lambda i: (i.get("created_ts", 0), i.get("nr", 0)))
    elif sort == "nr":
        items.sort(key=lambda i: i.get("nr", 0))
    else:
        items.sort(key=lambda i: (i.get("created_ts", 0), i.get("nr", 0)), reverse=True)

    status_items = [("", "Alle (ohne gelöschte)"), ("open", "Offen (Neu/In Prüfung/Geplant)")] + \
        [(s, status_label("de", s)) for s in STATUSES] + [("deleted", "In Discord gelöscht")]
    cat_items = [("", "Alle Kategorien"), ("__none__", "Ohne Kategorie")] + \
        [(c, c) for c in data.get("categories") or []]
    filters = ui.form(
        BASE,
        ui.grid(
            ui.field("Status", ui.select("status", status_items, f_status, autosubmit=True)),
            ui.field("Kategorie", ui.select("cat", cat_items, f_cat, autosubmit=True)),
            ui.field("Sortierung", ui.select("sort", [("new", "Neueste zuerst"), ("old", "Älteste zuerst"),
                                                     ("nr", "Nach Nummer")], sort, autosubmit=True)),
            cols=3,
        ),
        csrf="", method="get", hidden={"guild": guild.id},
    )
    if not items:
        empty = ui.empty("bi-lightbulb", "Keine Ideen für diese Auswahl.",
                         "Mitglieder reichen Ideen über den Button im Forum-Panel oder unter „Mein Bereich → Ideen“ ein.")
        return ui.card("Ideen", filters + empty, icon="bi-lightbulb")
    rows = []
    for i in items:
        nr = i["nr"]
        link = cog.idea_link(guild, i)
        detail = ui.button("Details", icon="bi-box-arrow-in-right", kind="ghost", small=True,
                           href=f"{BASE}?guild={guild.id}&idea={nr}")
        forum_btn = ui.button("", icon="bi-discord", kind="ghost", small=True, href=link,
                              attrs={"title": "Beitrag in Discord öffnen", "target": "_blank", "rel": "noopener"}) \
            if link and not i.get("deleted") else ""
        author = "anonym · " if i.get("anonymous") else ""
        author += _esc(i.get("author_name") or (f"ID {i['author_id']}" if i.get("author_id") else "—"))
        extra = []
        if i.get("category"):
            extra.append(_esc(i["category"]))
        if i.get("polls"):
            extra.append(f"🗳️ {len(i['polls'])}")
        if i.get("merged_into"):
            extra.append(f"→ #{int(i['merged_into'])}")
        status_cell = ui.badge("gelöscht", "bad") if i.get("deleted") else _badge(ui, i.get("status", "new"))
        check = (f"<input class='form-check-input' type='checkbox' name='ids' value='{nr}' "
                 f"aria-label='Idee #{nr} auswählen'>") if not i.get("deleted") else ""
        rows.append(ui.row(
            check,
            f"<div class='wc-cell-title'><span class='mono'>#{nr}</span> {_esc(i.get('title', '')[:90])}</div>"
            f"<div class='wc-cell-sub'>{author}{' · ' + ' · '.join(extra) if extra else ''}</div>",
            status_cell,
            f"<span class='wc-muted'>{_ts(i.get('created_ts'))}</span>",
            f"><div class='wc-row-actions'>{detail}{forum_btn}</div>",
            attrs={"id": f"idea-{nr}"},
        ))
    set_items = [(s, status_label("de", s)) for s in STATUSES if s != "merged"]
    poll_ok = cog.poll_cog() is not None
    bar = (
        ui.grid(ui.field("Neuer Status für die Auswahl", ui.select("status", set_items, "review"),
                         help="Häkchen in der Tabelle setzen, dann Status setzen oder daraus eine Umfrage starten."))
        + ui.actions(
            ui.button("Status setzen", icon="bi-flag", kind="ghost", name="form", value="bulk_status",
                      confirm="Status für alle ausgewählten Ideen setzen?"),
            ui.button("Umfrage starten", icon="bi-bar-chart", name="form", value="poll_select") if poll_ok else "")
        + ("" if poll_ok else ui.callout("Der Umfragen-Cog (<code>poll</code>) ist nicht geladen – „Umfrage aus Ideen“ "
                                         "ist erst nach <code>[p]load poll</code> möglich.", tone="warn"))
    )
    table = ui.table(["", "Idee", "Status", "Eingereicht", ">"], rows, search=True,
                     search_placeholder="Nach Titel, Nummer, Kategorie oder Einreicher suchen …", id="id-ideas")
    form = ui.form(BASE, table + bar, csrf=csrf, hidden={"guild": guild.id})
    return ui.card("Ideen", filters + form, icon="bi-lightbulb",
                   desc="Ideen per Häkchen auswählen, dann unten Status setzen oder eine Umfrage daraus starten.")


async def _render_poll(cog, request, ui, guild, data, live, csrf):
    pc = cog.poll_cog()
    if pc is None:
        return ui.card("Umfrage aus Ideen", ui.callout(
            "Der Umfragen-Cog (<code>poll</code>) ist nicht geladen. Nach <code>[p]load poll</code> kannst du hier "
            "mehrere Ideen auswählen und daraus eine Umfrage posten.", tone="warn"), icon="bi-bar-chart")
    max_opts = await cog.poll_limits(guild)
    selected = {s for s in (request.query.get("sel") or "").split(",") if s.isdigit()}
    open_ideas = sorted((i for i in live if i.get("status") in OPEN_STATUSES), key=lambda i: -i.get("nr", 0))
    if len(open_ideas) < 2:
        return ui.card("Umfrage aus Ideen", ui.empty("bi-bar-chart", "Es gibt weniger als 2 offene Ideen.",
                                                     "Offen = Neu, In Prüfung oder Geplant."), icon="bi-bar-chart")
    rows = []
    for i in open_ideas:
        nr = i["nr"]
        chk = " checked" if str(nr) in selected else ""
        rows.append(ui.row(
            f"<input class='form-check-input' type='checkbox' name='ids' value='{nr}'{chk} aria-label='Idee #{nr}'>",
            f"<div class='wc-cell-title'><span class='mono'>#{nr}</span> {_esc(i.get('title', '')[:90])}</div>"
            + (f"<div class='wc-cell-sub'>{_esc(i['category'])}</div>" if i.get("category") else ""),
            _badge(ui, i.get("status", "new")),
        ))
    try:
        pconf = await pc.config.guild(guild).all()
    except Exception:  # noqa: BLE001
        pconf = {}
    channels = [(c.id, f"#{c.name}") for c in guild.text_channels]
    form = ui.form(
        BASE,
        ui.table(["", "Idee", "Status"], rows, search=True, search_placeholder="Ideen filtern …", id="id-poll")
        + ui.grid(
            ui.field("Frage", ui.text_input("question", "Welche Idee sollen wir als Nächstes umsetzen?",
                                            attrs={"maxlength": 256, "required": True}), wide=True),
            ui.field("Kanal", ui.select("channel", channels), help="Hier postet der Umfragen-Cog die Umfrage."),
            ui.field("Laufzeit (optional)", ui.text_input("duration", "", placeholder="z. B. 2h, 1d, 3d"),
                     help="Leer = läuft, bis sie im Umfragen-Dashboard geschlossen wird."),
        )
        + ui.switches(
            ui.switch("multiple", "Mehrfachauswahl erlauben", pconf.get("default_multiple"),
                      desc="Mitglieder dürfen für mehrere Ideen stimmen."),
            ui.switch("anonymous", "Anonym abstimmen", pconf.get("default_anonymous"),
                      desc="Nur Zähler sichtbar, keine Namen."),
            ui.switch("set_review", "Neue Ideen auf „In Prüfung“ setzen", data.get("poll_review", True),
                      desc="Ideen mit Status „Neu“ wechseln auf „In Prüfung“."),
        )
        + ui.actions(ui.button("Umfrage posten", icon="bi-send")),
        csrf=csrf, hidden={"form": "poll", "guild": guild.id},
    )
    return ui.card("Umfrage aus Ideen", form, icon="bi-bar-chart",
                   desc=f"2 bis {max_opts} offene Ideen wählen (Grenze aus den Umfragen-Einstellungen). Jede Idee wird "
                        "eine Option „#Nr Titel“; im Beitrag jeder Idee erscheint ein Link zur Abstimmung.")


def _render_settings(cog, ui, guild, data, csrf, can_edit):
    forum = cog.forum_of(guild, data)
    forums = [(f.id, f"#{f.name}") for f in getattr(guild, "forums", []) or []]
    role_items = [(r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
                  for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                  if not r.is_default() and not getattr(r, "managed", False)]
    status = _forum_status(cog, ui, guild, data, forum)
    general = ui.card("Ideen-Forum", ui.grid(
        ui.field("Forum", ui.select("forum_id", forums, data.get("forum_id"), none_label="— kein Forum —"),
                 help="Forum-Kanal, in dem jede Idee ein eigener Beitrag wird. Fehlende Status-Tags legt der Bot an."),
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), data.get("language", "de")),
                 help="Sprache der Discord-Texte und neuer Tags."),
    ) + status, icon="bi-signpost-split", desc="Wo die Ideen landen.")
    cats = ui.card("Kategorien", ui.grid(
        ui.field("Kategorien (eine pro Zeile)", ui.textarea("categories", "\n".join(data.get("categories") or []),
                                                            rows=5, placeholder="Events\nDiscord\nSpiele"),
                 help="Höchstens 10, je höchstens 20 Zeichen. Leer = keine Kategorie-Auswahl.", wide=True),
    ) + ui.switches(ui.switch("category_tags", "Kategorien als Forum-Tags", data.get("category_tags", True),
                              desc="Zusätzlich zum Status-Tag bekommt der Beitrag den Kategorie-Tag.")),
        icon="bi-tags", desc="Mitglieder wählen beim Einreichen eine Kategorie.")
    protect = ui.card("Einreichen & Schutz", ui.grid(
        ui.field("Wartezeit", ui.number("cooldown_minutes", int(data.get("cooldown_minutes") or 0), min=0, max=1440,
                                        unit="Min."), help="Zwischen zwei Ideen eines Mitglieds. 0 = aus."),
        ui.field("Max. offene Ideen", ui.number("max_open", int(data.get("max_open") or 0), min=0, max=100,
                                                unit="je Mitglied"), help="Neu, In Prüfung, Geplant. 0 = unbegrenzt."),
    ) + ui.switches(
        ui.switch("anonymous", "Anonym einreichen", data.get("anonymous"),
                  desc="Im Beitrag steht „anonym“ statt des Namens. Das Team sieht den Einreicher hier weiterhin."),
        ui.switch("follow_submitter", "Einreicher dem Beitrag hinzufügen", data.get("follow_submitter", True),
                  desc="So bekommt er Antworten mit (nicht bei anonymen Ideen)."),
        ui.switch("manual_posts", "Manuelle Beiträge als Ideen übernehmen", data.get("manual_posts", True),
                  desc="Erstellt jemand (mit entsprechenden Rechten) direkt einen Beitrag, bekommt er Nummer und Tag „Neu“."),
    ), icon="bi-shield-check", desc="Schutz vor Spam und Doppel-Ideen.")
    team = ui.card("Team-Workflow", ui.grid(
        ui.field("Team-Rollen", ui.select("team_roles", role_items, data.get("team_roles") or [], multiple=True,
                                          placeholder="Rollen suchen …"),
                 help="Dürfen die <code>[p]ideas</code>-Befehle nutzen. „Server verwalten“ darf das immer.", wide=True),
    ) + ui.switches(
        ui.switch("dm_status", "DM an den Einreicher bei Statuswechsel", data.get("dm_status", True)),
        ui.switch("archive_closed", "Bei Umgesetzt/Abgelehnt schließen & archivieren", data.get("archive_closed", True),
                  desc="Beitrag wird geschlossen; zurück auf einen offenen Status öffnet ihn wieder."),
        ui.switch("poll_review", "Umfrage: neue Ideen auf „In Prüfung“", data.get("poll_review", True),
                  desc="Vorbelegung im Reiter Umfrage und Standard für <code>[p]ideas poll</code>."),
    ), icon="bi-people", desc="Wer Ideen bearbeitet und was dabei automatisch passiert.")
    portal = ui.card("Mitglieder-Bereich", ui.switch(
        "member_page", "Im Mitglieder-Bereich anzeigen", data.get("member_page", True),
        desc="Mitglieder reichen unter „Mein Bereich → Ideen“ ein (gleiche Regeln wie das Formular in Discord) und "
             "sehen den Status ihrer Ideen.",
    ), icon="bi-person-badge")
    settings = ui.form(BASE, general + cats + protect + team + portal + ui.save_row("Einstellungen speichern"),
                       csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True)
    setup = ui.card("Panel & Forum", ui.columns(
        ui.form(BASE, "<p class='wc-muted'>Postet bzw. erneuert den angepinnten Beitrag „💡 Idee einreichen“ mit "
                      "Button im Forum.</p>" + ui.actions(ui.button("Panel posten/erneuern", icon="bi-pin-angle")),
                csrf=csrf, hidden={"form": "panel", "guild": guild.id}),
        ui.form(BASE, "<p class='wc-muted'>Prüft die Status-/Kategorie-Tags im Forum und legt fehlende an "
                      "(Limit 20 Tags).</p>" + ui.actions(ui.button("Tags prüfen/anlegen", icon="bi-tags", kind="ghost")),
                csrf=csrf, hidden={"form": "tags", "guild": guild.id}),
        ui.form(BASE, ui.field("Neues Forum", ui.text_input("name", "ideen", attrs={"maxlength": 100}),
                               help="Legt ein Forum mit Status-Tags an: Mitglieder dürfen antworten, aber keine eigenen "
                                    "Beiträge erstellen; der Bot postet das Panel und wird als Ideen-Forum eingestellt.")
                + ui.actions(ui.button("Forum anlegen", icon="bi-plus-square", kind="ghost")),
                csrf=csrf, hidden={"form": "create_forum", "guild": guild.id},
                confirm="Neues Forum anlegen und als Ideen-Forum einstellen?"),
        cols=3,
    ), icon="bi-tools", desc="Einrichtung in Discord.")
    note = "" if can_edit else ui.callout("Einstellungen, Panel, Forum und Sperren brauchen das Recht <b>Bearbeiten</b>.")
    return note + settings + setup


def _forum_status(cog, ui, guild, data, forum):
    if forum is None:
        return ui.callout("Kein Forum eingestellt.", tone="warn")
    me = getattr(guild, "me", None)
    perms = forum.permissions_for(me) if me is not None else None
    missing = []
    for attr, label in (("view_channel", "Kanal ansehen"), ("send_messages", "Beiträge erstellen"),
                        ("send_messages_in_threads", "In Threads schreiben"), ("manage_threads", "Threads verwalten"),
                        ("manage_channels", "Kanäle verwalten (Tags)"), ("embed_links", "Links einbetten")):
        if perms is None or not getattr(perms, attr, False):
            missing.append(label)
    ids = {tg.id for tg in forum.available_tags}
    tag_ids = data.get("tag_ids") or {}
    no_tag = [status_label("de", s) for s in STATUSES if not tag_ids.get(s) or int(tag_ids[s]) not in ids]
    parts = [f"Forum <b>#{_esc(forum.name)}</b> · {len(forum.available_tags)}/20 Tags"]
    panel = data.get("panel_thread_id")
    parts.append("Panel gepostet" if panel else "Panel noch nicht gepostet")
    text = " · ".join(parts)
    if missing:
        return ui.callout(text + "<br>Dem Bot fehlen im Forum: " + _esc(", ".join(missing)), tone="warn")
    if no_tag:
        return ui.callout(text + "<br>Fehlende Status-Tags: " + _esc(", ".join(no_tag))
                          + " – „Tags prüfen/anlegen“ klicken.", tone="warn")
    return ui.callout(text + " · alle Status-Tags vorhanden.", tone="ok")


def _render_blocked(ui, guild, data, csrf):
    rows = []
    for uid in data.get("blocked") or []:
        m = guild.get_member(int(uid))
        name = getattr(m, "display_name", None) or f"ID {uid}"
        rows.append(ui.row(
            f"<div class='wc-cell-title'>{_esc(name)}</div><div class='wc-cell-sub mono'>{_esc(uid)}</div>",
            ">" + ui.form(BASE, ui.button("Entsperren", icon="bi-unlock", kind="ghost", small=True),
                          csrf=csrf, hidden={"form": "unblock", "guild": guild.id, "user": uid}),
        ))
    table = ui.table(["Mitglied", ">"], rows, empty_text="Niemand ist gesperrt.")
    add = ui.form(BASE, ui.grid(ui.field("Mitglied sperren", ui.text_input(
        "user", "", placeholder="Name oder Discord-ID", attrs={"required": True}),
        help="Gesperrte Mitglieder können keine Ideen mehr einreichen (Formular, Website, manuelle Beiträge).")
    ) + ui.actions(ui.button("Sperren", icon="bi-slash-circle", kind="danger")),
        csrf=csrf, hidden={"form": "block", "guild": guild.id})
    return ui.card("Gesperrte Mitglieder", table + add, icon="bi-slash-circle")


# --------------------------------------------------------------------------- #
#  Detailansicht
# --------------------------------------------------------------------------- #
def _render_detail(cog, ui, guild, data, nr, csrf):
    ideas = data.get("ideas") or {}
    i = ideas[str(nr)]
    link = cog.idea_link(guild, i)
    back = ui.button("Zurück zu den Ideen", icon="bi-arrow-left", kind="ghost", small=True,
                     href=f"{BASE}?guild={guild.id}#ideen")
    to_forum = ui.button("Beitrag in Discord", icon="bi-discord", kind="ghost", small=True, href=link,
                         attrs={"target": "_blank", "rel": "noopener"}) if link and not i.get("deleted") else ""
    status = i.get("status", "new")
    meta = [f"<span class='mono'>#{nr}</span>", _badge(ui, status)]
    if i.get("deleted"):
        meta.append(ui.badge("in Discord gelöscht", "bad"))
    head = ui.hero("bi-lightbulb", i.get("title", ""), " · ".join(meta) + f"<br><br>{back} {to_forum}")
    author = ("anonym (für Mitglieder) · " if i.get("anonymous") else "") + \
        (f"{_esc(i.get('author_name') or '—')} <span class='mono wc-muted'>{_esc(i.get('author_id') or '')}</span>"
         if i.get("author_id") else "— (gelöscht)")
    polls = "".join(
        f"<div><a href='https://discord.com/channels/{guild.id}/{int(p['channel_id'])}/{int(p['message_id'])}' "
        f"target='_blank' rel='noopener'>🗳️ Umfrage {_esc(p.get('id') or '')}</a> "
        f"<span class='wc-muted'>{_ts(p.get('ts'))}</span></div>"
        for p in i.get("polls") or [] if isinstance(p, dict) and p.get("message_id") and p.get("channel_id"))
    merged = ""
    if i.get("merged_into"):
        merged = f"<a href='{BASE}?guild={guild.id}&idea={int(i['merged_into'])}'>#{int(i['merged_into'])}</a>"
    merged_from = ", ".join(f"<a href='{BASE}?guild={guild.id}&idea={int(n)}'>#{int(n)}</a>"
                            for n in i.get("merged_from") or [])
    kv = [("Kategorie", _esc(i.get("category") or "—")), ("Einreicher", author),
          ("Quelle", _esc(SOURCE_LABEL.get(i.get("source"), i.get("source") or "—"))),
          ("Eingereicht", _ts(i.get("created_ts"))), ("Aktualisiert", _ts(i.get("updated_ts")))]
    if merged:
        kv.append(("Zusammengeführt mit", merged))
    if merged_from:
        kv.append(("Hierher zusammengeführt", merged_from))
    info = ui.card("Idee", f"<p style='white-space:pre-wrap'>{_esc(i.get('description') or 'Keine Beschreibung.')}</p>"
                   + "<div class='kv'>" + "".join(f"<div class='row-kv'><span class='k'>{k}</span><span>{v}</span></div>"
                                                  for k, v in kv) + "</div>"
                   + (f"<div style='margin-top:12px'>{polls}</div>" if polls else ""), icon="bi-card-text")
    hist_rows = []
    for h in reversed(i.get("history") or []):
        if not isinstance(h, dict):
            continue
        what = []
        if h.get("status") == "new" and not h.get("old"):
            what.append("eingereicht")
        elif h.get("status"):
            what.append((f"{status_label('de', h['old'])} → " if h.get("old") and h["old"] != h["status"] else "")
                        + status_label("de", h["status"]))
        if h.get("merged_into"):
            what.append(f"zusammengeführt mit #{int(h['merged_into'])}")
        if h.get("merged_from"):
            what.append(f"#{int(h['merged_from'])} hierher zusammengeführt")
        if h.get("edited"):
            what.append("bearbeitet: " + ", ".join({"title": "Titel", "description": "Beschreibung",
                                                   "category": "Kategorie"}.get(x, x) for x in h["edited"]))
        if h.get("comment"):
            what.append("Kommentar")
        hist_rows.append(ui.row(
            f"<span class='wc-muted'>{_ts(h.get('ts'))}</span>",
            _esc(" · ".join(what) or "—")
            + (f"<div class='wc-cell-sub' style='white-space:pre-wrap'>{_esc(h['comment'])}</div>" if h.get("comment") else ""),
            _esc(h.get("by_name") or ("—" if not h.get("by") else f"ID {h['by']}")),
        ))
    history = ui.card("Verlauf", ui.table(["Zeit", "Änderung", "Von"], hist_rows, empty_text="Kein Verlauf."),
                      icon="bi-clock-history")
    hidden = {"guild": guild.id, "nr": nr}
    if i.get("deleted"):
        actions = ui.card("Aktionen", ui.callout("Der Forum-Beitrag wurde in Discord gelöscht. Du kannst den Eintrag "
                                                 "hier endgültig entfernen.", tone="warn")
                          + ui.form(BASE, ui.actions(ui.button("Eintrag löschen", icon="bi-trash", kind="danger")),
                                    csrf=csrf, hidden={**hidden, "form": "delete"},
                                    confirm=f"Idee #{nr} endgültig löschen?"), icon="bi-lightning")
        return head + ui.columns(info, actions) + history
    status_form = ui.form(BASE, ui.grid(
        ui.field("Neuer Status", ui.select("status", [(s, status_label("de", s)) for s in STATUSES if s != "merged"],
                                           status if status != "merged" else "review")),
        ui.field("Kommentar / Begründung (optional)", ui.textarea("comment", "", rows=3,
                                                                  placeholder="Wird als Antwort im Beitrag gepostet."),
                 wide=True),
    ) + ui.actions(ui.button("Status setzen", icon="bi-flag")), csrf=csrf, hidden={**hidden, "form": "status"})
    comment_form = ui.form(BASE, ui.field("Kommentar", ui.textarea("comment", "", rows=3,
                                                                   placeholder="Antwort des Teams im Beitrag"))
                           + ui.actions(ui.button("Kommentar posten", icon="bi-chat-left-text", kind="ghost")),
                           csrf=csrf, hidden={**hidden, "form": "comment"})
    targets = [(x["nr"], f"#{x['nr']} · {x.get('title', '')[:60]}")
               for x in sorted(ideas.values(), key=lambda x: -x.get("nr", 0))
               if isinstance(x, dict) and x.get("nr") != nr and not x.get("deleted") and x.get("status") != "merged"]
    merge_form = ui.form(BASE, ui.field("Duplikat von", ui.select("target", targets), help="Diese Idee wird „Zusammengeführt“, "
                                        "bekommt einen Hinweis mit Link zum Ziel und wird archiviert.")
                         + ui.actions(ui.button("Zusammenführen", icon="bi-link-45deg", kind="ghost")),
                         csrf=csrf, hidden={**hidden, "form": "merge"},
                         confirm=f"Idee #{nr} mit der gewählten Idee zusammenführen?") \
        if targets and status != "merged" else ui.callout("Keine passende Ziel-Idee." if status != "merged"
                                                          else "Diese Idee ist bereits zusammengeführt.")
    cats = [("", "Ohne Kategorie")] + [(c, c) for c in data.get("categories") or []]
    if i.get("category") and i["category"] not in (data.get("categories") or []):
        cats.append((i["category"], i["category"] + " (nicht mehr eingestellt)"))
    edit_form = ui.form(BASE, ui.grid(
        ui.field("Titel", ui.text_input("title", i.get("title", ""), attrs={"maxlength": 100, "required": True}), wide=True),
        ui.field("Beschreibung", ui.textarea("description", i.get("description", ""), rows=5), wide=True),
        ui.field("Kategorie", ui.select("category", cats, i.get("category") or "")),
    ) + ui.actions(ui.button("Speichern", icon="bi-check2")), csrf=csrf, hidden={**hidden, "form": "edit"})
    delete_form = ui.form(BASE, ui.actions(ui.button("Idee löschen", icon="bi-trash", kind="danger")),
                          csrf=csrf, hidden={**hidden, "form": "delete"},
                          confirm=f"Idee #{nr} und ihren Forum-Beitrag endgültig löschen?")
    left = ui.card("Status", status_form, icon="bi-flag",
                   desc="Setzt Tag und Embed, postet Kommentar im Beitrag, DM an den Einreicher (falls eingeschaltet).") \
        + ui.card("Kommentar", comment_form, icon="bi-chat-left-text", desc="Ohne Statuswechsel.")
    right = ui.card("Zusammenführen", merge_form, icon="bi-link-45deg") \
        + ui.card("Bearbeiten", edit_form, icon="bi-pencil") \
        + ui.card("Löschen", delete_form, icon="bi-trash", desc="Löscht auch den Forum-Beitrag.")
    return head + ui.columns(info + left, right) + history


# --------------------------------------------------------------------------- #
#  POST
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    data = await request.post()
    form = data.get("form")
    guilds = await _visible_guilds(request)
    guild = _pick(guilds, data.get("guild"))
    if guild is None:
        return {"redirect": f"{BASE}?err=" + quote("Server nicht gefunden")}
    webcore = request.app["webcore"]
    user = await webcore.current_user(request) if hasattr(webcore, "current_user") else None
    by = _Who(user, guild.get_member(int((user or {}).get("id") or 0)) if user else None)
    lang = await cog._lang(guild)
    gconf = cog.config.guild(guild)
    nr = int(data["nr"]) if str(data.get("nr") or "").isdigit() else None

    def text(key, kw):
        from .strings import t
        return t(lang, key, **kw).replace("**", "").replace("`", "")

    def back(key, kw, ok_keys):
        return _go(guild, "ok" if key in ok_keys else "err", text(key, kw), idea=nr)

    if form == "status" and nr:
        key, kw = await cog.set_status(guild, nr, data.get("status"), by=by, comment=data.get("comment"))
        return back(key, kw, {"status_set"})
    if form == "comment" and nr:
        key, kw = await cog.add_comment(guild, nr, data.get("comment"), by=by)
        return back(key, kw, {"comment_ok"})
    if form == "merge" and nr:
        target = data.get("target")
        if not str(target or "").isdigit():
            return _go(guild, "err", "Bitte eine Ziel-Idee wählen", idea=nr)
        key, kw = await cog.merge(guild, nr, int(target), by=by)
        return back(key, kw, {"merged_ok"})
    if form == "edit" and nr:
        key, kw = await cog.edit_idea(guild, nr, title=data.get("title", ""), description=data.get("description", ""),
                                      category=data.get("category", ""), by=by)
        return back(key, kw, {"edited_ok"})
    if form == "delete" and nr:
        key, kw = await cog.delete_idea(guild, nr)
        return _go(guild, "ok" if key == "deleted_ok" else "err", text(key, kw))
    if form in ("bulk_status", "poll_select"):
        ids = [int(x) for x in data.getall("ids", []) if str(x).isdigit()]
        if not ids:
            return _go(guild, "err", "Bitte zuerst Ideen auswählen")
        if form == "poll_select":
            return {"redirect": f"{BASE}?guild={guild.id}&sel={','.join(map(str, ids))}#umfrage"}
        status = data.get("status")
        if status not in STATUSES or status == "merged":
            return _go(guild, "err", "Ungültiger Status")
        done = 0
        for n in ids[:100]:
            key, _ = await cog.set_status(guild, n, status, by=by)
            done += key == "status_set"
        return _go(guild, "ok", f"Status „{status_label('de', status)}“ für {done} von {len(ids)} Ideen gesetzt")
    if form == "poll":
        ids = [x for x in data.getall("ids", []) if str(x).isdigit()]
        cid = data.get("channel")
        channel = guild.get_channel(int(cid)) if str(cid or "").isdigit() else None
        ok, msg, _ = await cog.start_poll(
            guild, ids, question=data.get("question"), channel=channel, duration=(data.get("duration") or "").strip(),
            multiple="multiple" in data, anonymous="anonymous" in data, set_review="set_review" in data, by=by)
        msg = msg.replace("**", "").replace("`", "")
        if ok:
            return _go(guild, "ok", msg.split(": https://")[0])
        return {"redirect": f"{BASE}?{urlencode({'guild': guild.id, 'sel': ','.join(ids), 'err': msg})}#umfrage"}

    # ------------------------------------------------ ab hier: Bearbeiten
    if form == "settings":
        from .ideas import MAX_CATEGORIES, MAX_CATEGORY_LEN, clean_categories
        cats = clean_categories((data.get("categories") or "").splitlines())
        if cats is None:
            return _go(guild, "err", f"Höchstens {MAX_CATEGORIES} Kategorien mit je höchstens {MAX_CATEGORY_LEN} Zeichen")
        fid = data.get("forum_id")
        forum = guild.get_channel(int(fid)) if str(fid or "").isdigit() else None
        if fid and not isinstance(forum, discord.ForumChannel):
            return _go(guild, "err", "Bitte einen Forum-Kanal wählen")
        lang_new = (data.get("language") or "de").lower()
        if lang_new in LANGUAGES:
            await gconf.language.set(lang_new)
        await gconf.categories.set(cats)
        for key in ("category_tags", "anonymous", "follow_submitter", "manual_posts", "dm_status", "archive_closed",
                    "poll_review", "member_page"):
            await getattr(gconf, key).set(key in data)
        for key, lo, hi in (("cooldown_minutes", 0, 1440), ("max_open", 0, 100)):
            try:
                await getattr(gconf, key).set(max(lo, min(hi, int(data.get(key) or 0))))
            except (TypeError, ValueError):
                pass
        roles = [int(r) for r in data.getall("team_roles", []) if str(r).isdigit() and guild.get_role(int(r))]
        await gconf.team_roles.set(roles)
        warnings = await cog.set_forum(guild, forum)
        if warnings:
            return _go(guild, "err", "Gespeichert – " + " ".join(warnings))
        return _go(guild, "ok", "Gespeichert")
    if form == "tags":
        if await cog.get_forum(guild) is None:
            return _go(guild, "err", "Kein Ideen-Forum eingestellt")
        warnings = await cog.ensure_tags(guild)
        return _go(guild, "err" if warnings else "ok", " ".join(warnings) or "Alle Tags sind vorhanden")
    if form == "panel":
        ok, msg, warnings = await cog.post_panel(guild)
        msg = msg.replace("**", "").split(": https://")[0]
        return _go(guild, "ok" if ok and not warnings else "err", " ".join([msg] + warnings))
    if form == "create_forum":
        ok, msg, warnings = await cog.create_forum(guild, data.get("name") or "ideen")
        msg = msg.replace("**", "")
        if ok:
            forum = await cog.get_forum(guild)
            msg = f"Forum #{forum.name} angelegt – mit Status-Tags und Panel" if forum else msg
        return _go(guild, "ok" if ok and not warnings else "err", " ".join([msg] + warnings))
    if form in ("block", "unblock"):
        raw = (data.get("user") or "").strip()
        member = None
        if raw.isdigit():
            member = guild.get_member(int(raw))
            uid = int(raw)
        else:
            low = raw.lstrip("@").casefold()
            member = next((m for m in guild.members if low and low in (m.display_name.casefold(), m.name.casefold())), None)
            uid = member.id if member else None
        if not uid:
            return _go(guild, "err", "Mitglied nicht gefunden")
        if form == "block":
            if member is not None and await cog.is_team(member):
                return _go(guild, "err", "Team-Mitglieder und der Bot-Owner können nicht gesperrt werden")
            await cog.set_blocked(guild, uid, True)
            name = getattr(member, "display_name", None) or f"ID {uid}"
            return _go(guild, "ok", f"{name} ist gesperrt")
        await cog.set_blocked(guild, uid, False)
        return _go(guild, "ok", "Sperre aufgehoben")
    return _go(guild, "err", "Unbekannte Aktion")
