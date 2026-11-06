"""Reine Ticket-Antwortuhr und sichere Textbausteine (keine Discord-/Config-Aufrufe)."""
import math
import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
MAX_REPLY = 2000
DEFAULT_REPLIES = [
    {"id": "details", "label": "Weitere Informationen", "text": "Hallo {user}, bitte beschreibe dein Anliegen genauer und ergänze, falls möglich, einen Screenshot.\n{signature}"},
    {"id": "checking", "label": "Wir prüfen das", "text": "Hallo {user}, wir prüfen dein Anliegen in Ticket #{ticket} und melden uns mit dem nächsten Schritt.\n{signature}"},
    {"id": "resolved", "label": "Rückfrage zur Lösung", "text": "Hallo {user}, hat unser Vorschlag dein Anliegen gelöst oder brauchst du noch Unterstützung?\n{signature}"},
]
_PLACEHOLDER = re.compile(r"\{(user|ticket|staff|signature)\}")


def utc(value):
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def reset_response(record, now=None):
    now = utc(now) or datetime.now(UTC)
    record.update(response_wait_seconds=0.0, response_wait_started_at=now.isoformat(),
                  response_cycle_open=True, support_history_unconfirmed=False, response_event_at=now.isoformat())


def set_waiting(record, waiting, now=None, *, answered=False):
    """Manuelle Wechsel pausieren dieselbe Uhr; eine echte Teamantwort löst den Zyklus."""
    now = utc(now) or datetime.now(UTC)
    started = utc(record.get("response_wait_started_at"))
    elapsed = float(record.get("response_wait_seconds") or 0)
    if started is not None:
        elapsed += max(0.0, (now - started).total_seconds())
    record["response_wait_seconds"] = elapsed
    record["response_wait_started_at"] = None
    if answered:
        record["response_cycle_open"] = False
        record["response_wait_seconds"] = 0.0
    elif waiting == "team":
        if not record.get("response_cycle_open", False):
            record["response_wait_seconds"] = 0.0
            record["response_cycle_open"] = True
        record["response_wait_started_at"] = now.isoformat()
    record["waiting_for"] = waiting
    record["response_event_at"] = now.isoformat()


def human_reply(record, staff, at):
    at = utc(at)
    previous = utc(record.get("last_human_at"))
    transition = utc(record.get("response_event_at"))
    if at is None or (previous is not None and at < previous) or (transition is not None and at < transition):
        return False
    if staff:
        set_waiting(record, "user", at, answered=True)
    elif record.get("waiting_for") != "team" or not record.get("response_cycle_open", False):
        set_waiting(record, "team", at)
    # Weitere Nutzernachrichten im laufenden Team-Zyklus setzen die Uhr nicht zurück.
    record["waiting_for"] = "user" if staff else "team"
    record["last_human_at"] = at.isoformat()
    return True


def support_due(record, conf, now=None):
    """Fälligkeit als UTC-datetime; unbekannt/pausiert/ausgeschaltet ergibt None."""
    if (not conf.get("response_targets_enabled", False) or record.get("status") != "open"
            or record.get("waiting_for", "team") != "team" or not record.get("response_cycle_open", False)
            or record.get("support_history_unconfirmed", False)):
        return None
    started = utc(record.get("response_wait_started_at"))
    if started is None:
        return None
    try:
        hours = float(conf.get("response_urgent_hours", 4) if record.get("priority") == "urgent"
                      else conf.get("response_target_hours", 24))
        elapsed = float(record.get("response_wait_seconds") or 0)
        if not math.isfinite(hours) or not math.isfinite(elapsed) or not 0 < hours <= 720 or elapsed < 0:
            return None
        return started + timedelta(seconds=hours * 3600 - elapsed)
    except (TypeError, ValueError, OverflowError):
        return None


def render_reply(text, record, actor, owner, signature=""):
    values = {"user": str(getattr(owner, "display_name", None) or "du"),
              "ticket": str(record.get("num") or ""),
              "staff": str(getattr(actor, "display_name", None) or "Support"), "signature": str(signature)}
    result = _PLACEHOLDER.sub(lambda match: values[match.group(1)], str(text or "")).strip()
    if not result or len(result) > MAX_REPLY or "\x00" in result:
        raise ValueError("Die Antwort muss 1 bis 2000 Zeichen lang sein (einschließlich Signatur und Platzhaltern).")
    return result
