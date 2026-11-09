"""Persönliche, ausschließlich lesende Arbeitsübersicht mit seitenweisen Rechten."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from urllib.parse import urlencode

import aiohttp_jinja2

from . import access as acl

log = logging.getLogger("red.red-cogs.webcore.tasks")
MAX_VISIBLE = 200


@dataclass
class WorkItem:
    module: str
    kind: str
    title: str
    detail: str
    href: str
    due: datetime | None = None
    urgent: bool = False


def _stamp(value):
    try:
        stamp = datetime.fromtimestamp(float(value), timezone.utc) if isinstance(value, (int, float)) else datetime.fromisoformat(value)
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _link(slug, guild_id, **query):
    return "/cogs/" + slug + "?" + urlencode({"guild": guild_id, **query})


async def collect_items(webcore, request, guild, user, *, now=None):
    """Jede Quelle wird vor dem Lesen einzeln geprüft; kein Import optionaler Cogs."""
    now = now or datetime.now(timezone.utc)
    uid = int(user["id"])
    levels = await webcore._access_map(user, request)
    items, unavailable = [], []
    sources = {
        "tickets": acl.VIEW, "raidhelper": acl.VIEW, "scheduler": acl.VIEW, "teamcalendar": acl.VIEW,
        "organigram": acl.OPERATE, "sticky": acl.OPERATE, "poll": acl.OPERATE,
        "guard": acl.OPERATE, "autoroom": acl.EDIT,
    }
    for slug, minimum in sources.items():
        page = webcore.pages.get(slug)
        level = acl.EDIT if levels is None else (levels.get(guild.id) or {}).get(slug, acl.NONE)
        if page is None or level < minimum:
            continue
        cog = page.owner
        try:
            if await webcore.bot.cog_disabled_in_guild(cog, guild):
                continue
            conf = await cog.config.guild(guild).all()
            if slug == "tickets":
                member = guild.get_member(uid)
                for record in (conf.get("tickets") or {}).values():
                    if not isinstance(record, dict) or record.get("status") != "open" or record.get("claimed_by") != uid:
                        continue
                    if member is None or not cog._is_staff(member, conf, record):
                        continue
                    due_fn = getattr(cog, "support_due", None)
                    due = due_fn(record, conf, now=now) if due_fn is not None else None
                    waiting = "Wartet auf Nutzer" if record.get("waiting_for") == "user" else "Wartet auf Team"
                    detail = waiting + (" · " + str(record["reason_label"]) if record.get("reason_label") else "")
                    items.append(WorkItem(slug, "tickets", f"Ticket #{record.get('num', '?')}", detail,
                                          _link(slug, guild.id, view="mine"), due,
                                          record.get("priority") == "urgent"))
            elif slug == "teamcalendar":
                member = guild.get_member(uid)
                if not cog.can_view(member, conf):
                    continue
                for ident, task in (conf.get("work_tasks") or {}).items():
                    if not isinstance(task, dict) or task.get("status") == "done" or uid not in (task.get("assignee_ids") or []):
                        continue
                    project = (conf.get("projects") or {}).get(str(task.get("project_id") or "")) or {}
                    if project.get("status") in {"archived", "completed"}:
                        continue
                    detail = {"todo": "Offen", "in_progress": "In Arbeit", "blocked": "Blockiert"}.get(task.get("status"), "Offen")
                    if project.get("name"):
                        detail += " · " + str(project["name"])
                    items.append(WorkItem(slug, "tasks", str(task.get("title") or "Projektaufgabe"), detail,
                                          _link(slug, guild.id, task=ident), _stamp(task.get("due_ts")),
                                          task.get("priority") == "urgent"))
                for ident, record in (conf.get("events") or {}).items():
                    if not isinstance(record, dict) or record.get("status") != "scheduled":
                        continue
                    involved = uid in (record.get("owner_id"), record.get("created_by")) or (
                        record.get("participants") or {}).get(str(uid)) in {"yes", "maybe"}
                    due, end = _stamp(record.get("start_ts")), _stamp(record.get("end_ts"))
                    if not involved or due is None or end is None or end <= now or due > now + timedelta(days=7):
                        continue
                    items.append(WorkItem(slug, "events", str(record.get("title") or "Projekttermin"),
                                          "Projektkalender" + (" · " + str(record["project"]) if record.get("project") else ""),
                                          _link(slug, guild.id, event=ident), due))
                if conf.get("board_error") and level >= acl.OPERATE and cog.can_manage(member, conf):
                    items.append(WorkItem(slug, "problems", "Projektkalender: Übersicht prüfen",
                                          "Die Discord-Übersicht konnte nicht vollständig aktualisiert werden.", _link(slug, guild.id)))
                if conf.get("task_board_error") and level >= acl.OPERATE and cog.can_manage_projects(member, conf):
                    items.append(WorkItem(slug, "problems", "Projektmanagement: Aufgabenübersicht prüfen",
                                          "Die Discord-Aufgabenübersicht konnte nicht vollständig aktualisiert werden.", _link(slug, guild.id) + "#aufgabenboard"))
            elif slug == "raidhelper":
                for ident, record in (conf.get("events") or {}).items():
                    if not isinstance(record, dict) or record.get("completed"):
                        continue
                    signup = (record.get("signups") or {}).get(str(uid))
                    leader = record.get("leader_id") == uid
                    if not leader and (not signup or signup.get("status") == "absent"):
                        continue
                    start = _stamp(record.get("start_ts"))
                    if start is None or start > now + timedelta(days=7):
                        continue
                    # Alte, nie abgeschlossene Veranstaltungen machen die Liste nicht dauerhaft unbrauchbar.
                    if start < now - timedelta(days=1):
                        continue
                    items.append(WorkItem(slug, "events", str(record.get("title") or "Raid"),
                                          "Du leitest diesen Raid" if leader else "Du bist angemeldet",
                                          _link(slug, guild.id, event=ident), start))
                    if leader and not record.get("message_id"):
                        items.append(WorkItem(slug, "problems", str(record.get("title") or "Raid"),
                                              "Discord-Beitrag fehlt – Veröffentlichung prüfen.",
                                              _link(slug, guild.id, event=ident)))
            elif slug == "scheduler":
                for ident, record in (conf.get("entries") or {}).items():
                    if not isinstance(record, dict) or record.get("completed") or record.get("creator_id") != uid:
                        continue
                    href = _link(slug, guild.id, edit=ident)
                    title = str(record.get("name") or record.get("label") or f"Geplante Nachricht #{ident}")
                    if record.get("last_error"):
                        items.append(WorkItem(slug, "problems", title, "Ausführung fehlgeschlagen – Eintrag prüfen.", href))
                    elif not record.get("paused"):
                        due = _stamp(record.get("next_run_ts"))
                        if due is not None and due <= now + timedelta(days=7):
                            items.append(WorkItem(slug, "events", title, "Deine geplante Nachricht", href, due))
            elif slug == "organigram":
                for ident, chart in (conf.get("charts") or {}).items():
                    if not isinstance(chart, dict):
                        continue
                    failures = [post for post in chart.get("posts", []) if isinstance(post, dict) and post.get("last_error")]
                    if failures:
                        items.append(WorkItem(slug, "problems", str(chart.get("name") or "Organigramm"),
                                              f"{len(failures)} Veröffentlichung(en) benötigen einen neuen Versuch.",
                                              _link(slug, guild.id, chart=ident) + "#posten"))
            elif slug == "sticky":
                for ident, record in (conf.get("stickies") or {}).items():
                    if not isinstance(record, dict) or not record.get("enabled", True):
                        continue
                    if record.get("delivery_error") or not record.get("message_id"):
                        channel = guild.get_channel(int(ident)) if str(ident).isdigit() else None
                        items.append(WorkItem(slug, "problems", "Sticky " + ("#" + channel.name if channel else "(Kanal fehlt)"),
                                              "Nachricht fehlt oder konnte nicht vollständig aktualisiert werden.", _link(slug, guild.id)))
            elif slug == "poll":
                for ident, record in (conf.get("polls") or {}).items():
                    if isinstance(record, dict) and not record.get("message_id") and record.get("channel_id"):
                        items.append(WorkItem(slug, "problems", str(record.get("question") or f"Umfrage #{ident}"),
                                              "Discord-Beitrag fehlt – im Umfrage-Editor neu posten.", _link(slug, guild.id, poll=ident)))
            elif slug == "guard" and conf.get("lockdown_recovering"):
                items.append(WorkItem(slug, "problems", "Notmodus: Wiederherstellung ausstehend",
                                      "Mindestens eine Einschränkung konnte noch nicht zurückgesetzt werden.", _link(slug, guild.id)))
            elif slug == "autoroom":
                pending = sum(isinstance(record, dict) and bool(record.get("cleanup_error"))
                              for record in (conf.get("active_rooms") or {}).values())
                if pending:
                    items.append(WorkItem(slug, "problems", "Raumbereinigung ausstehend",
                                          f"{pending} Raumzuordnung(en) benötigen einen neuen Löschversuch.", _link(slug, guild.id)))
        except Exception:  # noqa: BLE001 – eine optionale Quelle darf die anderen Aufgaben nicht verstecken
            log.exception("Aufgabenquelle %s für Server %s nicht lesbar", slug, guild.id)
            unavailable.append(page.name)
    items.sort(key=lambda item: (
        0 if item.kind == "problems" or item.due is not None and item.due <= now else 1,
        not item.urgent, item.due or datetime.max.replace(tzinfo=timezone.utc), item.title.casefold(),
    ))
    return items, unavailable


async def handle_tasks(webcore, request):
    user = await webcore.current_user(request)
    if not await webcore._is_authorized(user, request):
        return await webcore._deny(request, user)
    guilds = await webcore.visible_guilds(request, min_level=acl.VIEW)
    if not guilds:
        return webcore._error_page(request, "Meine Aufgaben", "Keine freigegebenen Server.", status=403)
    raw = request.query.get("guild")
    if raw and (not raw.isdigit() or not any(guild.id == int(raw) for guild in guilds)):
        return webcore._error_page(request, "Meine Aufgaben", "Für diesen Server fehlt dir der Zugriff.", status=403)
    selected = await webcore._select_guild(request, guilds, "/tasks")
    guild = next(guild for guild in guilds if guild.id == selected)
    webcore._set_switcher(request, guilds, selected, "/tasks")
    now = datetime.now(timezone.utc)
    items, unavailable = await collect_items(webcore, request, guild, user, now=now)
    kind = request.query.get("kind", "all")
    kind = kind if kind in ("all", "tickets", "tasks", "events", "problems", "due") else "all"
    shown = [item for item in items if kind == "all" or item.kind == kind
             or kind == "due" and item.due is not None and item.due <= now]
    ui = webcore.ui
    filters = ui.form("/tasks", ui.field("Anzeigen", ui.select("kind", [
        ("all", "Alles"), ("tickets", "Meine Tickets"), ("tasks", "Meine Projektaufgaben"), ("events", "Termine in den nächsten 7 Tagen"),
        ("problems", "Fehler und Wiederherstellung prüfen"), ("due", "Frist oder Termin fällig"),
    ], kind, autosubmit=True)), method="get", csrf="", hidden={"guild": guild.id})
    rows = []
    for item in shown[:MAX_VISIBLE]:
        overdue = item.due is not None and item.due <= now
        badge = ui.badge("Prüfen", "bad") if item.kind == "problems" else (
            ui.badge("Fällig", "bad") if overdue else ui.badge("Offen", "info"))
        if item.urgent:
            badge += " " + ui.badge("Dringend", "warn")
        when = (f"<time datetime='{ui.esc(item.due.isoformat())}' data-wc-localtime>"
                f"{ui.esc(item.due.strftime('%d.%m.%Y %H:%M UTC'))}</time>" if item.due else "—")
        page = webcore.pages.get(item.module)
        rows.append(ui.row(
            ui.esc(page.name if page else item.module),
            f"<div class='wc-cell-title'>{ui.esc(item.title)}</div><div class='wc-cell-sub'>{ui.esc(item.detail)}</div>",
            badge, when, ">" + ui.button("Öffnen", icon="bi-arrow-right", href=item.href, small=True),
        ))
    counts = ui.stats([
        ("Meine Tickets", sum(item.kind == "tickets" for item in items), "bi-life-preserver", None, None),
        ("Projektaufgaben", sum(item.kind == "tasks" for item in items), "bi-kanban", None, None),
        ("Termine", sum(item.kind == "events" for item in items), "bi-calendar-event", "nächste 7 Tage", None),
        ("Zu prüfen", sum(item.kind == "problems" for item in items), "bi-exclamation-circle", None, None),
    ])
    warning = (ui.callout("Nicht alle Aufgabenquellen sind erreichbar: " + ui.esc(", ".join(unavailable))
                         + ". Lade die Übersicht erneut, bevor du von einer leeren Liste ausgehst.", tone="warn") if unavailable else "")
    if len(shown) > MAX_VISIBLE:
        warning += ui.callout(f"Die ersten {MAX_VISIBLE} von {len(shown)} Aufgaben werden angezeigt. Bitte einen Filter wählen.", tone="info")
    content = ui.hero("bi-check2-square", "", "Deine zugewiesenen Tickets und Aufgaben, Projekt- und Raid-Termine sowie geplanten Nachrichten. "
                      "Veröffentlichungs- und Wiederherstellungsprobleme erscheinen entsprechend deinen Modulrechten.",
                      actions=ui.button("Aktualisieren", href=str(request.rel_url), kind="ghost", icon="bi-arrow-clockwise"))
    content += counts + warning + filters + ui.card("Meine Aufgaben", ui.table(
        ["Modul", "Aufgabe", "Status", "Zeit / Frist", ">"], rows,
        empty_text="Hier ist gerade nichts zu erledigen. Erledigte Aufgaben verschwinden automatisch.",
        search=len(rows) > 6, id="my-tasks"), desc="Zeitangaben werden in deiner Browser-Zeitzone angezeigt.")
    response = aiohttp_jinja2.render_template("page.html", request, webcore._page_ctx(
        request, title="Meine Aufgaben", content=content, active_page="tasks"))
    response.headers["Cache-Control"] = "no-store"
    return response
