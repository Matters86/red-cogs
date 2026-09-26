"""Zeitplan-Logik für geplante Nachrichten – rein, ohne Discord, voll testbar.

Ein Zeitplan (``schedule``) ist ein Dict::

    {"type": "once",     "date": "2026-10-01", "time": "18:00"}
    {"type": "daily",    "time": "09:00"}
    {"type": "weekly",   "time": "18:00", "weekdays": [0, 2, 4]}      # 0 = Montag … 6 = Sonntag
    {"type": "monthly",  "time": "12:00", "day": 31}                   # kürzere Monate: letzter Tag
    {"type": "interval", "minutes": 90}                                # mindestens 10 Minuten

Dazu je Eintrag optional ``start_date``/``end_date`` (``YYYY-MM-DD``, lokales Datum, inklusive).

**Zeitzone und Sommerzeit:** Uhrzeiten gelten in der IANA-Zeitzone des Servers (``zoneinfo``).
Termine werden als lokale Uhrzeit berechnet und erst dann in UTC umgerechnet – „täglich 09:00“
bleibt also auch nach der Zeitumstellung 09:00 Ortszeit. Sonderfälle:

* Uhrzeit fällt in die **Lücke** der Umstellung auf Sommerzeit (z. B. 02:30 in Europe/Berlin am
  letzten Märzsonntag): die Nachricht kommt eine Stunde später nach der alten Zählung, also um 03:30 Sommerzeit.
* Uhrzeit gibt es bei der Umstellung auf Winterzeit **doppelt** (02:00–02:59): es wird nur beim
  ersten Mal (noch Sommerzeit) gesendet.
* Intervalle („alle N Minuten/Stunden“) laufen in echter Zeit weiter (alle 2 Std. = immer 7200 s),
  unabhängig von der Umstellung. Anker ist das Startdatum (00:00 bzw. die gesetzte Uhrzeit) oder
  der Zeitpunkt des Anlegens.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TYPES = ("once", "daily", "weekly", "monthly", "interval")
MIN_INTERVAL_MINUTES = 10
MAX_INTERVAL_MINUTES = 31 * 24 * 60
MISSED_GRACE = 600          # s: verpasste Termine nur nachholen, wenn der letzte < 10 Minuten zurückliegt
MAX_FAILS = 5               # Fehler in Folge bis zur automatischen Pause

WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_WEEKDAY_ALIASES = {
    "mo": 0, "mon": 0, "montag": 0, "monday": 0,
    "di": 1, "tue": 1, "dienstag": 1, "tuesday": 1,
    "mi": 2, "wed": 2, "mittwoch": 2, "wednesday": 2,
    "do": 3, "thu": 3, "donnerstag": 3, "thursday": 3,
    "fr": 4, "fri": 4, "freitag": 4, "friday": 4,
    "sa": 5, "sat": 5, "samstag": 5, "saturday": 5,
    "so": 6, "sun": 6, "sonntag": 6, "sunday": 6,
}


def get_tz(name: str | None):
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def parse_hhmm(text) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if 0 <= h <= 23 and 0 <= mi <= 59 else None


def parse_date(text) -> date | None:
    """``YYYY-MM-DD`` oder ``TT.MM.JJJJ``."""
    s = str(text or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    try:
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def local_ts(d: date, hh: int, mm: int, tz) -> int:
    """Lokales Datum + Uhrzeit -> UTC-Zeitstempel (Lücke/Doppelung siehe Modul-Doku, ``fold=0``)."""
    return int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).timestamp())


def local_date(ts: float, tz) -> date:
    return datetime.fromtimestamp(ts, tz=tz).date()


def validate(schedule: dict, *, start_date=None, end_date=None) -> str | None:
    """Fehler-Key (strings.py) oder ``None``."""
    if not isinstance(schedule, dict) or schedule.get("type") not in TYPES:
        return "err_type"
    kind = schedule["type"]
    if kind != "interval" and parse_hhmm(schedule.get("time")) is None:
        return "err_time"
    if kind == "once" and parse_date(schedule.get("date")) is None:
        return "err_date"
    if kind == "weekly":
        days = schedule.get("weekdays") or []
        if not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            return "err_weekdays"
    if kind == "monthly":
        try:
            day = int(schedule.get("day"))
        except (TypeError, ValueError):
            return "err_day"
        if not 1 <= day <= 31:
            return "err_day"
    if kind == "interval":
        try:
            minutes = int(schedule.get("minutes"))
        except (TypeError, ValueError):
            return "err_interval"
        if not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            return "err_interval"
    sd = parse_date(start_date) if start_date else None
    ed = parse_date(end_date) if end_date else None
    if (start_date and sd is None) or (end_date and ed is None):
        return "err_date"
    if sd and ed and ed < sd:
        return "err_range"
    return None


def next_run(schedule: dict, tz_name: str, after: float, *, start_date=None, end_date=None,
             anchor_ts: float | None = None) -> int | None:
    """Erster Termin **strikt nach** ``after`` (UTC-Sekunden) – oder ``None``, wenn keiner mehr kommt."""
    tz = get_tz(tz_name)
    kind = (schedule or {}).get("type")
    sd = parse_date(start_date) if start_date else None
    ed = parse_date(end_date) if end_date else None

    def in_range(d: date) -> bool:
        return (sd is None or d >= sd) and (ed is None or d <= ed)

    if kind == "interval":
        try:
            step = int(schedule.get("minutes")) * 60
        except (TypeError, ValueError):
            return None
        if step < MIN_INTERVAL_MINUTES * 60:
            return None
        hm = parse_hhmm(schedule.get("time")) or (0, 0)
        if sd is not None:
            anchor = local_ts(sd, hm[0], hm[1], tz)
        else:
            anchor = int(anchor_ts if anchor_ts is not None else after)
        if after < anchor:
            nxt = anchor
        else:
            nxt = anchor + (int((after - anchor) // step) + 1) * step
        if ed is not None and local_date(nxt, tz) > ed:
            return None
        return int(nxt)

    hm = parse_hhmm(schedule.get("time"))
    if hm is None:
        return None
    hh, mm = hm

    if kind == "once":
        d = parse_date(schedule.get("date"))
        if d is None or not in_range(d):
            return None
        ts = local_ts(d, hh, mm, tz)
        return ts if ts > after else None

    first = local_date(after, tz)
    if sd is not None and sd > first:
        first = sd

    if kind in ("daily", "weekly"):
        days = set(schedule.get("weekdays") or []) if kind == "weekly" else set(range(7))
        if not days:
            return None
        for i in range(0, 400):
            d = first + timedelta(days=i)
            if ed is not None and d > ed:
                return None
            if d.weekday() not in days:
                continue
            ts = local_ts(d, hh, mm, tz)
            if ts > after:
                return ts
        return None

    if kind == "monthly":
        try:
            want = int(schedule.get("day"))
        except (TypeError, ValueError):
            return None
        y, m = first.year, first.month
        for _ in range(0, 26):
            last = calendar.monthrange(y, m)[1]
            d = date(y, m, min(want, last))          # Monatsende sauber: 31. -> 30./28./29.
            if ed is not None and d > ed:
                return None
            if in_range(d):
                ts = local_ts(d, hh, mm, tz)
                if ts > after:
                    return ts
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return None
    return None


def catch_up(schedule: dict, tz_name: str, first_due: int, now: float, **kw) -> int | None:
    """Downtime-Regel: Welcher fällige Termin (``first_due`` ≤ ``now``) wird noch gesendet?

    Nur einer, und nur wenn er weniger als ``MISSED_GRACE`` (10 Minuten) zurückliegt – ältere
    verpasste Termine werden übersprungen. Rückgabe: Zeitstempel des zu sendenden Termins oder ``None``.
    """
    after = max(int(first_due) - 1, now - MISSED_GRACE)
    due = next_run(schedule, tz_name, after, **kw)
    return due if due is not None and due <= now else None


def parse_minutes(text) -> int | None:
    """``90``, ``90m``, ``2h``, ``1h30m`` -> Minuten."""
    s = str(text or "").strip().lower().replace(" ", "")
    if s.isdigit():
        return int(s)
    parts = re.findall(r"(\d+)([mhd])", s)
    if not parts or "".join(a + b for a, b in parts) != s:
        return None
    return sum(int(n) * {"m": 1, "h": 60, "d": 1440}[u] for n, u in parts)


def parse_spec(text: str) -> tuple[dict | None, str | None]:
    """Zeitplan aus Befehls-Text (deutsch oder englisch):

    ``einmalig 2026-10-01 18:00`` · ``täglich 09:00`` · ``wöchentlich mo,mi,fr 18:00`` ·
    ``monatlich 31 12:00`` · ``alle 2h`` / ``alle 90m`` (auch ``once``/``daily``/``weekly``/
    ``monthly``/``every``)
    """
    words = (text or "").strip().split()
    if not words:
        return None, "err_spec"
    kind = words[0].lower()
    rest = words[1:]
    if kind in ("einmalig", "once") and len(rest) == 2:
        sched = {"type": "once", "date": str(parse_date(rest[0]) or ""), "time": rest[1]}
    elif kind in ("täglich", "taeglich", "daily") and len(rest) == 1:
        sched = {"type": "daily", "time": rest[0]}
    elif kind in ("wöchentlich", "woechentlich", "weekly") and len(rest) == 2:
        days = []
        for part in re.split(r"[,;/]+", rest[0].lower()):
            if part not in _WEEKDAY_ALIASES:
                return None, "err_weekdays"
            if _WEEKDAY_ALIASES[part] not in days:
                days.append(_WEEKDAY_ALIASES[part])
        sched = {"type": "weekly", "weekdays": sorted(days), "time": rest[1]}
    elif kind in ("monatlich", "monthly") and len(rest) == 2:
        if not rest[0].rstrip(".").isdigit():
            return None, "err_day"
        sched = {"type": "monthly", "day": int(rest[0].rstrip(".")), "time": rest[1]}
    elif kind in ("alle", "every") and len(rest) == 1:
        minutes = parse_minutes(rest[0])
        if minutes is None:
            return None, "err_interval"
        sched = {"type": "interval", "minutes": minutes}
    else:
        return None, "err_spec"
    err = validate(sched)
    return (None, err) if err else (sched, None)


def fmt_minutes(minutes: int, lang: str = "de") -> str:
    h, m = divmod(int(minutes), 60)
    if lang == "en":
        return " ".join(p for p in (f"{h} h" if h else "", f"{m} min" if m else "") if p)
    return " ".join(p for p in (f"{h} Std." if h else "", f"{m} Min." if m else "") if p)


def describe(schedule: dict, lang: str = "de") -> str:
    """Kurzbeschreibung, z. B. „wöchentlich Mo, Mi um 18:00“."""
    kind = (schedule or {}).get("type")
    en = lang == "en"
    tm = schedule.get("time") or ""
    if kind == "once":
        d = parse_date(schedule.get("date"))
        ds = d.strftime("%Y-%m-%d" if en else "%d.%m.%Y") if d else "?"
        return f"once on {ds} at {tm}" if en else f"einmalig am {ds} um {tm}"
    if kind == "daily":
        return f"daily at {tm}" if en else f"täglich um {tm}"
    if kind == "weekly":
        names = WEEKDAYS_EN if en else WEEKDAYS_DE
        days = ", ".join(names[d] for d in sorted(schedule.get("weekdays") or []) if 0 <= d <= 6)
        return f"weekly on {days} at {tm}" if en else f"wöchentlich {days} um {tm}"
    if kind == "monthly":
        day = int(schedule.get("day") or 1)
        extra = ("" if day <= 28 else (" (last day in shorter months)" if en else " (in kürzeren Monaten am letzten Tag)"))
        return (f"monthly on day {day} at {tm}" if en else f"monatlich am {day}. um {tm}") + extra
    if kind == "interval":
        return f"every {fmt_minutes(schedule.get('minutes') or 0, lang)}" if en else \
            f"alle {fmt_minutes(schedule.get('minutes') or 0, lang)}"
    return "?"


def utc_now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()
