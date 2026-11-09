"""Validierung und lesende Auswertungen für Projekte/Aufgaben; keine Config-Aufrufe."""
from __future__ import annotations

import copy
import csv
import io
import re
import secrets
import time

from .models import CalendarError, format_local, input_local, parse_local

PMError = CalendarError
MAX_PROJECTS = 100
MAX_TASKS = 500
MAX_COMMENTS = 50
MAX_CHECKLIST = 25
TASK_STATUSES = {"todo": "Offen", "in_progress": "In Arbeit", "blocked": "Blockiert", "done": "Erledigt"}
PRIORITIES = {"low": "Niedrig", "normal": "Normal", "high": "Hoch", "urgent": "Dringend"}
PROJECT_STATUSES = {"active": "Aktiv", "paused": "Pausiert", "completed": "Abgeschlossen", "archived": "Archiviert"}


def _text(data, key, limit, label, required=False):
    value = str(data.get(key) or "").strip()
    if (required and not value) or len(value) > limit or "\x00" in value:
        raise CalendarError(f"{label}: Bitte {'1 bis ' if required else 'höchstens '}{limit} Zeichen eingeben.")
    return value


def _id(value, label):
    value = str(value or "").strip()
    if not value:
        return ""
    if len(value) > 24 or not value.isdecimal() or int(value) <= 0:
        raise CalendarError(f"Bitte {label} gültig auswählen.")
    return str(int(value))


def _member_ids(value):
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if value is None:
        value = []
    if not isinstance(value, (list, tuple, set)) or len(value) > 10:
        raise CalendarError("Bitte höchstens zehn zuständige Teammitglieder auswählen.")
    result = set()
    for item in value:
        ident = _id(item, "ein Teammitglied")
        if not ident:
            raise CalendarError("Bitte ein gültiges Teammitglied auswählen.")
        result.add(int(ident))
    return sorted(result)


def _flag(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "on", "yes"}:
        return True
    if text in {"", "0", "false", "off", "no"}:
        return False
    raise CalendarError("Ungültige Meilenstein-Auswahl.")


def _timezone(data, conf):
    zone = str(conf.get("timezone") or "Europe/Berlin")
    if "task_timezone" in data and str(data["task_timezone"]) != zone:
        raise CalendarError("Die Zeitzone wurde inzwischen geändert. Bitte das Formular neu laden und die Frist prüfen.")
    return zone


def _deadline(data, key, stored_key, previous, zone):
    if key not in data:
        return previous.get(stored_key)
    raw = str(data.get(key) or "").strip()
    if not raw:
        return None
    old = previous.get(stored_key)
    if old is not None and raw in {input_local(old, zone), format_local(old, zone)}:
        return int(old)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) or re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", raw):
        raw += "T23:59" if "-" in raw else " 23:59"
    return parse_local(raw, zone)


def normalize_project(data, conf, previous=None, now=None):
    previous = previous or {}
    merged = {**previous, **data}
    zone = _timezone(data, conf)
    raw_owner = merged.get("owner_id")
    owner_id = int(_id(raw_owner, "ein verantwortliches Mitglied")) if raw_owner else 0
    return {"name": _text(merged, "name", 80, "Projektname", True),
            "description": _text(merged, "description", 2000, "Projektbeschreibung"),
            "owner_id": owner_id,
            "deadline_ts": _deadline(data, "deadline", "deadline_ts", previous, zone)}


def normalize_checklist(value, previous=()):
    if isinstance(value, str):
        items = [line.strip() for line in value.splitlines() if line.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(item.get("text") or "").strip() if isinstance(item, dict) else str(item).strip() for item in value]
        items = [item for item in items if item]
    else:
        raise CalendarError("Bitte Checklistenpunkte zeilenweise eingeben.")
    parsed = []
    for line in items:
        marker = re.match(r"^(?:-\s*)?\[([ xX])\]\s*(.+)$", line)
        parsed.append((marker.group(2).strip(), marker.group(1).lower() == "x") if marker else (line, None))
    if len(parsed) > MAX_CHECKLIST or any(not text or len(text) > 200 or "\x00" in text for text, _ in parsed):
        raise CalendarError("Eine Checkliste darf höchstens 25 Punkte mit je 200 Zeichen enthalten.")
    known = {}
    used = {str(item.get("id")) for item in previous if isinstance(item, dict)}
    for item in previous:
        if isinstance(item, dict):
            known.setdefault(str(item.get("text") or ""), []).append(item)
    result = []
    for text, explicit_done in parsed:
        candidates = known.get(text) or []
        if candidates:
            old = candidates.pop(0)
            result.append({"id": str(old["id"]), "text": text, "done": bool(old.get("done")) if explicit_done is None else explicit_done})
        else:
            ident = secrets.token_hex(4)
            while ident in used:
                ident = secrets.token_hex(4)
            used.add(ident)
            result.append({"id": ident, "text": text, "done": bool(explicit_done)})
    return result


def normalize_task(data, conf, previous=None, now=None):
    previous = previous or {}
    merged = {**previous, **data}
    zone = _timezone(data, conf)
    project_id = _id(merged.get("project_id"), "ein Projekt")
    event_id = _id(merged.get("event_id"), "einen Termin")
    due = _deadline(data, "due", "due_ts", previous, zone)
    priority = str(merged.get("priority") or "normal")
    if priority not in PRIORITIES:
        raise CalendarError("Bitte eine gültige Priorität auswählen.")
    milestone = _flag(merged.get("milestone"))
    if milestone and (not project_id or due is None):
        raise CalendarError("Ein Meilenstein braucht ein Projekt und eine Frist.")
    checklist = (normalize_checklist(data["checklist"], previous.get("checklist") or []) if "checklist" in data
                 else copy.deepcopy(previous.get("checklist") or []))
    return {"title": _text(merged, "title", 100, "Aufgabentitel", True),
            "description": _text(merged, "description", 2000, "Aufgabenbeschreibung"),
            "project_id": project_id, "event_id": event_id,
            "assignee_ids": _member_ids(merged.get("assignee_ids") or []),
            "due_ts": due, "priority": priority, "milestone": milestone, "checklist": checklist}


def parse_task_reminders(value):
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)) or len(value) > 3:
        raise CalendarError("Bitte höchstens drei Aufgaben-Erinnerungen wählen.")
    try:
        result = {int(str(item)) for item in value}
    except (TypeError, ValueError):
        raise CalendarError("Aufgaben-Erinnerungen brauchen ganze Minuten; 0 bedeutet bei Fälligkeit.") from None
    if any(item < 0 or item > 10080 for item in result):
        raise CalendarError("Aufgaben-Erinnerungen müssen zwischen 0 und 10080 Minuten liegen.")
    return sorted(result, reverse=True)


def label_project(conf, record):
    ident = str(record.get("project_id") or "")
    project = (conf.get("projects") or {}).get(ident)
    return str(project.get("name") or "Projekt") if isinstance(project, dict) else str(record.get("project") or ("Gelöschtes Projekt" if ident else ""))


def project_progress(conf, pid, now=None):
    now = time.time() if now is None else float(now)
    tasks = [record for record in (conf.get("work_tasks") or {}).values()
             if isinstance(record, dict) and str(record.get("project_id") or "") == str(pid)]
    done = sum(task.get("status") == "done" for task in tasks)
    milestones = sorted((task for task in tasks if task.get("milestone")),
                        key=lambda task: (task.get("due_ts") or float("inf"), str(task.get("id", ""))))
    return {"total": len(tasks), "done": done, "open": len(tasks) - done,
            "percent": round(done * 100 / len(tasks)) if tasks else 0,
            "blocked": sum(task.get("status") == "blocked" for task in tasks),
            "overdue": sum(task.get("status") != "done" and task.get("due_ts") is not None and task["due_ts"] < now for task in tasks),
            "milestones": milestones, "milestone_count": len(milestones)}


def tasks_csv(tasks, projects, member_names, tz_name="Europe/Berlin"):
    """Excel-tauglicher, formelsicherer Export ohne Kommentare oder interne Versanddaten."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(["Nummer", "Projekt", "Aufgabe", "Status", "Priorität", "Zuständig", "Frist", "Zeitzone", "Meilenstein", "Beschreibung"])
    values = tasks.values() if isinstance(tasks, dict) else tasks
    for task in sorted(values, key=lambda item: str(item.get("id", ""))):
        project = projects.get(str(task.get("project_id") or "")) or {}
        row = [task.get("id", ""), project.get("name", ""), task.get("title", ""),
               TASK_STATUSES.get(task.get("status"), "Unbekannt"), PRIORITIES.get(task.get("priority"), "Normal"),
               ", ".join(str(member_names.get(int(uid), "Ehemaliges Mitglied")) for uid in task.get("assignee_ids", [])),
               format_local(task["due_ts"], tz_name) if task.get("due_ts") is not None else "", tz_name,
               "Ja" if task.get("milestone") else "Nein", task.get("description", "")]
        safe = []
        for value in row:
            text = str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
                text = "'" + text
            safe.append(text)
        writer.writerow(safe)
    return stream.getvalue().encode("utf-8-sig")
