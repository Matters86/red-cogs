"""Terminprüfung, lokale Zeiten und Kalenderexport ohne Discord-/Config-Seiteneffekte."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
MAX_EVENTS = 250
MAX_REMINDERS = 3
DEFAULT_REMINDERS = [1440, 60]
STATUSES = {"scheduled", "cancelled", "completed"}


class CalendarError(ValueError):
    """Validierungs-/Rechtefehler, dessen deutscher Text im UI angezeigt werden darf."""


def get_timezone(name):
    try:
        return ZoneInfo(str(name or "Europe/Berlin"))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise CalendarError("Bitte eine gültige Zeitzone wählen, z. B. Europe/Berlin.") from None


def parse_local(value, tz_name="Europe/Berlin"):
    """Lokale Eingabe in UTC umrechnen; Zeitumstellung nie stillschweigend raten."""
    tz = get_timezone(tz_name)
    raw = str(value or "").strip()
    if not raw or len(raw) > 64:
        raise CalendarError("Bitte Datum und Uhrzeit angeben, z. B. 09.11.2026 19:30.")
    if not re.search(r"(?:T|\s)\d{2}:\d{2}", raw):
        raise CalendarError("Bitte neben dem Datum auch die Uhrzeit angeben.")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(raw, "%d.%m.%Y %H:%M")
        except ValueError:
            raise CalendarError("Bitte Datum und Uhrzeit als TT.MM.JJJJ HH:MM oder JJJJ-MM-TTTHH:MM eingeben.") from None
    if not 2000 <= dt.year <= 2100:
        raise CalendarError("Bitte ein Datum zwischen 2000 und 2100 wählen.")
    if dt.tzinfo is not None:
        return int(dt.astimezone(UTC).timestamp())
    candidates = set()
    for fold in (0, 1):
        local = dt.replace(tzinfo=tz, fold=fold)
        back = local.astimezone(UTC).astimezone(tz)
        if back.replace(tzinfo=None) == dt:
            candidates.add(int(local.timestamp()))
    if not candidates:
        raise CalendarError("Diese Uhrzeit existiert wegen der Zeitumstellung nicht. Bitte eine andere Uhrzeit wählen.")
    if len(candidates) > 1:
        raise CalendarError("Diese Uhrzeit kommt wegen der Zeitumstellung zweimal vor. Bitte eine eindeutige Uhrzeit oder einen UTC-Offset angeben.")
    return candidates.pop()


def format_local(stamp, tz_name="Europe/Berlin"):
    try:
        return datetime.fromtimestamp(float(stamp), get_timezone(tz_name)).strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError, OverflowError, OSError):
        return "—"


def input_local(stamp, tz_name="Europe/Berlin"):
    try:
        return datetime.fromtimestamp(float(stamp), get_timezone(tz_name)).strftime("%Y-%m-%dT%H:%M")
    except (ValueError, TypeError, OverflowError, OSError):
        return ""


def parse_reminders(value):
    if isinstance(value, str):
        value = [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    if value is None:
        return []
    if not isinstance(value, (tuple, list, set)) or len(value) > MAX_REMINDERS:
        raise CalendarError("Bitte höchstens drei Erinnerungszeiten in Minuten wählen.")
    result = set()
    for item in value:
        try:
            minutes = int(str(item))
        except (ValueError, TypeError):
            raise CalendarError("Erinnerungen brauchen ganze Minuten, z. B. 1440,60.") from None
        if not 1 <= minutes <= 10080:
            raise CalendarError("Erinnerungen müssen zwischen 1 Minute und 7 Tagen vor dem Termin liegen.")
        result.add(minutes)
    return sorted(result, reverse=True)


def _text(data, key, maximum, *, required=False):
    value = str(data.get(key) or "").strip()
    if (required and not value) or len(value) > maximum or "\x00" in value:
        raise CalendarError(f"{ {'title': 'Titel', 'description': 'Notizen', 'project': 'Projekt', 'location': 'Ort'}[key] }: "
                            f"Bitte {'1 bis ' if required else 'höchstens '}{maximum} Zeichen eingeben.")
    return value


def normalize_event(data, conf, previous=None, now=None):
    now = datetime.now(UTC).timestamp() if now is None else float(now)
    tz = conf.get("timezone") or "Europe/Berlin"
    if "event_timezone" in data and str(data["event_timezone"]) != tz:
        raise CalendarError("Die Kalender-Zeitzone wurde inzwischen geändert. Bitte Datum und Uhrzeit neu prüfen und das Formular neu laden.")
    previous = previous or {}
    values = {**previous, **data}
    def parse_field(key):
        raw = str(data.get(key) or "").strip()
        old = previous.get(key + "_ts")
        # Ein unverändert angezeigter Termin behält bei einer doppelten Herbst-
        # Uhrzeit seine bereits eindeutig gespeicherte UTC-Zeit.
        if old is not None and raw in {input_local(old, tz), format_local(old, tz)}:
            return int(old)
        return parse_local(raw, tz)
    start = parse_field("start")
    end = parse_field("end")
    if end <= start or end - start > 7 * 86400:
        raise CalendarError("Das Ende muss nach dem Beginn liegen; ein Termin darf höchstens 7 Tage dauern.")
    if start < now - 60 and start != previous.get("start_ts"):
        raise CalendarError("Ein neuer Beginn muss in der Zukunft liegen.")
    try:
        owner_id = int(str(data.get("owner_id") or previous.get("owner_id") or 0))
    except (ValueError, TypeError):
        raise CalendarError("Bitte ein gültiges verantwortliches Teammitglied auswählen.") from None
    if owner_id < 0:
        raise CalendarError("Bitte ein gültiges verantwortliches Teammitglied auswählen.")
    reminder_data = data.get("reminder_minutes", previous.get("reminder_minutes", conf.get("reminder_minutes", DEFAULT_REMINDERS)))
    project_id = str(values.get("project_id") or "").strip()
    if project_id and (len(project_id) > 24 or not project_id.isdecimal() or int(project_id) <= 0):
        raise CalendarError("Bitte ein gültiges Projekt auswählen.")
    return {
        "title": _text(values, "title", 100, required=True),
        "description": _text(values, "description", 2000),
        "project": _text(values, "project", 80),
        "project_id": str(int(project_id)) if project_id else "",
        "location": _text(values, "location", 200),
        "owner_id": owner_id, "start_ts": start, "end_ts": end,
        "reminder_minutes": parse_reminders(reminder_data),
    }


def duplicate_values(event, tz_name="Europe/Berlin", days=7):
    """Expliziter neuer Termin: lokale Uhrzeit beim Kopieren über Sommerzeit erhalten."""
    tz = get_timezone(tz_name)
    result = {key: str(event.get(key) or "") for key in ("title", "description", "project", "location", "owner_id")}
    for key in ("start", "end"):
        stamp = event.get(key + "_ts")
        local = datetime.fromtimestamp(float(stamp), tz) + timedelta(days=days)
        result[key] = local.strftime("%Y-%m-%dT%H:%M")
    result["reminder_minutes"] = list(event.get("reminder_minutes") or [])
    return result


def _ics_escape(value):
    return str(value or "").replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _fold_ics(line):
    """RFC5545: höchstens 75 UTF-8-Oktette, niemals mitten im Umlaut falten."""
    chunks, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 75:
            chunks.append(current)
            current, size = " ", 1
        current += char
        size += width
    chunks.append(current)
    return chunks


def _ics_stamp(value):
    stamp = float(value)
    if not math.isfinite(stamp):
        raise ValueError("Invalid timestamp")
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y%m%dT%H%M%SZ")


def calendar_ics(events, guild_id, guild_name):
    """Authentifizierter Download; enthält keine Teilnehmer-IDs oder erfundenen E-Mail-Adressen."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Red-Cogs//Projektkalender//DE", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:" + _ics_escape(guild_name)]
    values = events.values() if isinstance(events, dict) else events
    for event in sorted(values, key=lambda item: (item.get("start_ts", 0), str(item.get("id", "")))):
        try:
            start, end = _ics_stamp(event["start_ts"]), _ics_stamp(event["end_ts"])
            updated = _ics_stamp(event.get("updated_at") or event.get("created_at") or event["start_ts"])
            ident = str(event["id"])
            revision = max(0, int(event.get("revision") or 0))
            if not ident.isdigit():
                continue
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            continue
        description = str(event.get("description") or "")
        if event.get("project"):
            description = "Projekt: " + str(event["project"]) + ("\n\n" + description if description else "")
        lines.extend([
            "BEGIN:VEVENT", f"UID:teamcalendar-{int(guild_id)}-{ident}@red-cogs.local", "DTSTAMP:" + updated,
            "DTSTART:" + start, "DTEND:" + end, "SUMMARY:" + _ics_escape(event.get("title")),
            "DESCRIPTION:" + _ics_escape(description), "LOCATION:" + _ics_escape(event.get("location")),
            "STATUS:" + ("CANCELLED" if event.get("status") == "cancelled" else "CONFIRMED"),
            "SEQUENCE:" + str(revision), "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(part for line in lines for part in _fold_ics(line)) + "\r\n").encode("utf-8")
