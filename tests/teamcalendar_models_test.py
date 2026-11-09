"""Projektkalender: Sommerzeit, Eingaben, lokales Kopieren und sichere Kalenderdateien."""
from datetime import datetime, timezone

import bootstrap  # echte Red-Instanz und rc-Paket registrieren
from rc.teamcalendar.models import (
    CalendarError, calendar_ics, duplicate_values, format_local, get_timezone,
    input_local, normalize_event, parse_local, parse_reminders,
)
from rc.webcore import ui
del bootstrap


def fails(callback):
    try:
        callback()
    except CalendarError:
        return
    raise AssertionError("Ungültige Kalendereingabe akzeptiert")


def main():
    utc = timezone.utc
    assert parse_local("09.11.2026 19:30") == int(datetime(2026, 11, 9, 18, 30, tzinfo=utc).timestamp())
    assert parse_local("2026-07-09T19:30") == int(datetime(2026, 7, 9, 17, 30, tzinfo=utc).timestamp())
    first = parse_local("2026-10-25T02:30+02:00")
    second = parse_local("2026-10-25T02:30+01:00")
    assert second - first == 3600
    for value in ("2026-03-29T02:30", "2026-10-25T02:30", "2026-02-30T19:00", "2026-11-09", "kein Datum"):
        fails(lambda value=value: parse_local(value))
    fails(lambda: get_timezone("Not/AZone"))
    assert format_local(first) == "25.10.2026 02:30"
    assert input_local(first) == "2026-10-25T02:30"
    assert parse_reminders("1440,60,15") == [1440, 60, 15]
    assert parse_reminders("60,60") == [60]
    assert parse_reminders("") == []
    for reminders in ("0", "-1", "1440,60,15,5", "1.5", "10081", "fünf"):
        fails(lambda reminders=reminders: parse_reminders(reminders))

    now = datetime(2026, 11, 1, tzinfo=utc).timestamp()
    data = {"title": "Projektbesprechung", "start": "2026-11-09T19:00", "end": "2026-11-09T20:00",
            "project": "GTA", "location": "Team-Voice", "description": "Nächste Schritte", "owner_id": "11"}
    event = normalize_event(data, {"timezone": "Europe/Berlin"}, now=now)
    assert event["end_ts"] - event["start_ts"] == 3600 and event["owner_id"] == 11
    previous = dict(event, id="1", revision=2)
    modal = {key: value for key, value in data.items() if key not in {"owner_id", "project"}}
    assert normalize_event(modal, {}, previous=previous, now=now)["project"] == "GTA"
    assert normalize_event(modal, {}, previous=previous, now=now)["owner_id"] == 11
    ambiguous_old = dict(previous, start_ts=first, end_ts=first + 3600)
    ambiguous_edit = dict(data, start=input_local(first), end=input_local(first + 3600))
    kept = normalize_event(ambiguous_edit, {}, previous=ambiguous_old, now=now)
    assert kept["start_ts"] == first and kept["end_ts"] == first + 3600, "Unveränderte Herbst-Uhrzeiten behalten ihren UTC-Bezug"
    fails(lambda: normalize_event(dict(data, title=""), {}, now=now))
    fails(lambda: normalize_event(dict(data, event_timezone="UTC"), {"timezone": "Europe/Berlin"}, now=now))
    fails(lambda: normalize_event(dict(data, end="2026-11-09T18:00"), {}, now=now))
    fails(lambda: normalize_event(dict(data, end="2026-11-20T20:00"), {}, now=now))
    fails(lambda: normalize_event(dict(data, start="2026-10-01T19:00", end="2026-10-01T20:00"), {}, now=now))
    before_dst = dict(previous, start_ts=parse_local("2026-03-22T19:00"), end_ts=parse_local("2026-03-22T20:00"))
    copied = duplicate_values(before_dst)
    assert copied["start"] == "2026-03-29T19:00" and copied["end"] == "2026-03-29T20:00"
    print("Termine: Sommerzeit eindeutig, Daten/Uhrzeiten validiert, Zuständigkeit erhalten, nächste Woche lokal kopiert – OK")

    exported = dict(previous, title="Ü" * 90, description="Zeile 1\r\nBEGIN:VEVENT\nA;B,C\\D", created_at=now,
                    participants={"11": "yes"}, status="cancelled")
    raw = calendar_ics([exported], 1000, "Team\r\nBEGIN:VEVENT")
    assert raw.startswith(b"BEGIN:VCALENDAR\r\n") and raw.endswith(b"END:VCALENDAR\r\n")
    assert all(len(line) <= 75 for line in raw.split(b"\r\n")), "ICS-Zeilen nach UTF-8-Oktetten falten"
    text = raw.decode("utf-8").replace("\r\n ", "")
    assert text.count("\r\nBEGIN:VEVENT\r\n") == 1, "Freitext darf keine weiteren Termine einschleusen"
    assert "SUMMARY:" + "Ü" * 90 in text
    assert "STATUS:CANCELLED" in text and "SEQUENCE:2" in text
    assert "UID:teamcalendar-1000-1@red-cogs.local" in text
    assert "A\\;B\\,C\\\\D" in text and "participants" not in text
    bad = dict(exported, id="../x")
    assert "BEGIN:VEVENT" not in calendar_ics([bad], 1000, "Team").decode()
    assert "BEGIN:VEVENT" not in calendar_ics([dict(exported, revision="oops")], 1000, "Team").decode()
    print("Kalenderexport: stabile IDs/Versionen, UTC, Absagen, Umlaute, Zeilenfaltung und Freitext sicher – OK")

    markup = ui.month_grid([[{"day": "<script>", "body": "<a href='/safe'>Termin</a>", "today": True}]], label="<Team>")
    assert "&lt;script&gt;" in markup and "aria-label='&lt;Team&gt;'" in markup and "<script>" not in markup
    assert "wc-month-entry" not in markup and "is-today" in markup
    print("Gemeinsame Monatsübersicht escaped Beschriftungen, HTML kommt ausschließlich vom Cog – OK")


if __name__ == "__main__":
    main()
