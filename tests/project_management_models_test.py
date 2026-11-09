"""Aufgabenmodelle: stabile Checklisten, Fristen, Meilensteine und sicherer Export."""
import csv
import io
from datetime import datetime, timezone

import bootstrap
from rc.teamcalendar.models import CalendarError, parse_local
from rc.teamcalendar.project_models import (
    label_project, normalize_project, normalize_task, parse_task_reminders, project_progress, tasks_csv,
)
from rc.webcore import ui
del bootstrap


def rejects(call):
    try:
        call()
    except CalendarError:
        return
    raise AssertionError("Ungültige Projekt-/Aufgabendaten akzeptiert")


def main():
    conf = {"timezone": "Europe/Berlin"}
    project = normalize_project({"name": "GTA", "description": "Release vorbereiten", "deadline": "2026-11-30", "owner_id": "11"}, conf)
    assert project["deadline_ts"] == parse_local("2026-11-30T23:59") and project["owner_id"] == 11
    previous = dict(project, id="1", status="active", revision=1)
    assert normalize_project({"name": "GTA 2"}, conf, previous)["deadline_ts"] == project["deadline_ts"]
    assert normalize_project({"deadline": "", "owner_id": ""}, conf, previous)["deadline_ts"] is None
    rejects(lambda: normalize_project({"name": "", "deadline": ""}, conf))
    rejects(lambda: normalize_project({"name": "GTA", "task_timezone": "UTC"}, conf))

    task = normalize_task({"title": "Release testen", "project_id": "1", "assignee_ids": ["12", "11", "11"],
                           "due": "2026-11-12", "priority": "high", "milestone": "on", "event_id": "2",
                           "checklist": "[x] Umgebung bereit\n[ ] Funktion geprüft\nDokumentiert"}, conf)
    assert task["assignee_ids"] == [11, 12] and task["due_ts"] == parse_local("2026-11-12T23:59")
    assert task["checklist"][0]["done"] and not task["checklist"][1]["done"]
    ids = {item["text"]: item["id"] for item in task["checklist"]}
    reordered = normalize_task({"checklist": "Dokumentiert\nUmgebung bereit\nNeue Prüfung"}, conf, task)
    assert reordered["checklist"][0]["id"] == ids["Dokumentiert"]
    assert reordered["checklist"][1]["id"] == ids["Umgebung bereit"] and reordered["checklist"][1]["done"]
    assert reordered["checklist"][2]["id"] not in ids.values() and not reordered["checklist"][2]["done"]
    assert reordered["assignee_ids"] == [11, 12] and reordered["due_ts"] == task["due_ts"], "Teiländerungen müssen andere Felder erhalten"
    assert normalize_task({"assignee_ids": [], "milestone": False, "due": ""}, conf, task)["assignee_ids"] == []
    for raw in ({"title": "x", "assignee_ids": [""]}, {"title": "x", "assignee_ids": ["0"]},
                {"title": "x", "assignee_ids": list(range(1, 12))}, {"title": "x", "priority": "invalid"},
                {"title": "x", "project_id": "../1"}, {"title": "x", "event_id": "-1"},
                {"title": "x", "milestone": True}, {"title": "x", "task_timezone": "UTC"},
                {"title": "x", "checklist": "\n".join(str(i) for i in range(26))},
                {"title": "x", "checklist": "x" * 201}, {"title": "x", "due": "2026-03-29T02:30"}):
        rejects(lambda raw=raw: normalize_task(raw, conf))
    assert parse_task_reminders("1440,60,0") == [1440, 60, 0]
    assert parse_task_reminders("") == []
    for value in ("-1", "10081", "1.5", "1,2,3,4"):
        rejects(lambda value=value: parse_task_reminders(value))
    print("Projekt-/Aufgabenprüfung: Verantwortliche, Fristen, Teiländerungen, stabile Checklisten und Meilensteine – OK")

    due = parse_local("2026-11-12T12:00")
    records = {"projects": {"1": {"name": "GTA aktuell"}}, "work_tasks": {
        "1": dict(task, id="1", status="done"),
        "2": dict(task, id="2", status="blocked", due_ts=due),
        "3": {"id": "3", "title": "Anderes Projekt", "project_id": "2", "status": "todo"},
    }}
    assert label_project(records, {"project_id": "1", "project": "Alter Name"}) == "GTA aktuell"
    assert label_project(records, {"project": "Altes freies Kalenderprojekt"}) == "Altes freies Kalenderprojekt"
    progress = project_progress(records, "1", now=due + 1)
    assert progress["total"] == 2 and progress["done"] == 1 and progress["percent"] == 50
    assert progress["blocked"] == 1 and progress["overdue"] == 1 and progress["milestone_count"] == 2
    assert project_progress(records, "99")["percent"] == 0
    exported_task = dict(task, id="1", title="=SUM(1,2)", description="  @danger\r\nText;mit;Trenner", status="todo")
    blob = tasks_csv([exported_task], {"1": {"name": "+Projekt"}}, {11: "Lena", 12: "Tom"})
    assert blob.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(blob.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2 and rows[1][1].startswith("'+") and rows[1][2].startswith("'=") and rows[1][-1].startswith("'")
    assert rows[1][5] == "Lena, Tom" and "reminders_sent" not in blob.decode("utf-8-sig")
    markup = ui.kanban([{"title": "<script>", "count": 1, "body": "<b>Aufgabe</b>"}], label="<Team>")
    assert "&lt;script&gt;" in markup and "<script>" not in markup and "aria-label='&lt;Team&gt;'" in markup
    assert datetime.fromtimestamp(due, timezone.utc).year == 2026
    print("Fortschritt, alte Kalenderprojekte, CSV-Formelschutz und gemeinsame Board-Beschriftung – OK")


if __name__ == "__main__":
    main()
