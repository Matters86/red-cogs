"""Reine Gewinnspiel-Logik ohne Discord-I/O: Teilnahme-Regeln, Lose, faire Auslosung, Dauer.

Alles hier ist synchron und ohne Seiteneffekte – dadurch testbar und von Button, Befehl,
Dashboard und Mitgliederseite gemeinsam genutzt.
"""

from __future__ import annotations

import re
import secrets

MAX_WINNERS = 20            # Ansage mit 20 Erwähnungen bleibt weit unter 2000 Zeichen
MAX_PRIZE_LEN = 200         # Embed-Titel (256) inkl. Emoji
MAX_DESC_LEN = 1500
MAX_BONUS_PER_ROLE = 10
MAX_TICKETS = 25            # Obergrenze Lose je Mitglied (1 + Bonus)
MAX_BONUS_ROLES = 5
MAX_ROLE_LIST = 10          # je Liste (benötigt/ausgeschlossen)
MIN_DURATION = 60           # 1 Minute
MAX_DURATION_DAYS = 60
MAX_MEMBER_DAYS = 3650

# Kryptografisch sicherer Zufall (os.urandom) – nicht vorhersagbar, nicht seed-bar.
_RNG = secrets.SystemRandom()

_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str | None) -> int | None:
    """``'30m'``, ``'2h'``, ``'1d12h'`` -> Sekunden. Ungültig/zu kurz/zu lang -> ``None``."""
    if not text:
        return None
    raw = text.strip().lower().replace(" ", "")
    matches = _DURATION_RE.findall(raw)
    if not matches or "".join(f"{n}{u}" for n, u in matches) != raw:
        return None
    total = sum(int(num) * _DURATION_UNITS[unit] for num, unit in matches)
    if total < MIN_DURATION or total > MAX_DURATION_DAYS * 86400:
        return None
    return total


def role_ids(member) -> set[int]:
    return {getattr(r, "id", 0) for r in (getattr(member, "roles", None) or [])}


def _ids(values) -> set[int]:
    out = set()
    for v in values or []:
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            continue
    return out


def is_running(gw: dict, now: float) -> bool:
    return gw.get("status") == "running" and float(gw.get("end_ts") or 0) > now


def eligibility(member, gw: dict, now: float, *, check_running: bool = True) -> tuple[str, dict] | None:
    """Darf ``member`` teilnehmen? ``None`` = ja, sonst ``(text_key, kwargs)``.

    Regeln (in dieser Reihenfolge): läuft noch · kein Bot · keine ausgeschlossene Rolle ·
    mindestens EINE der benötigten Rollen (falls gesetzt) · Mindest-Mitgliedschaftsdauer
    (``joined_at`` unbekannt -> abgelehnt, weil nicht prüfbar).
    """
    if check_running and not is_running(gw, now):
        return "err_ended", {}
    if getattr(member, "bot", False):
        return "err_bot", {}
    mine = role_ids(member)
    if mine & _ids(gw.get("excluded_roles")):
        return "err_excluded", {}
    required = _ids(gw.get("required_roles"))
    if required and not (mine & required):
        return "err_required", {"roles": required}
    days = int(gw.get("min_member_days") or 0)
    if days > 0:
        joined = getattr(member, "joined_at", None)
        try:
            joined_ts = joined.timestamp() if joined is not None else None
        except Exception:  # noqa: BLE001
            joined_ts = None
        if joined_ts is None or now - joined_ts < days * 86400:
            return "err_too_new", {"days": days}
    return None


def tickets_for(member, gw: dict) -> int:
    """Lose eines Mitglieds: 1 + Summe der Bonus-Lose aller Bonus-Rollen, die es hat (max. 25)."""
    mine = role_ids(member)
    bonus = 0
    for rid, n in (gw.get("bonus_roles") or {}).items():
        try:
            if int(rid) in mine:
                bonus += max(0, min(MAX_BONUS_PER_ROLE, int(n)))
        except (TypeError, ValueError):
            continue
    return max(1, min(MAX_TICKETS, 1 + bonus))


def weighted_sample(pool, k: int, rng=None) -> list[int]:
    """Zieht bis zu ``k`` verschiedene IDs aus ``pool`` = [(id, lose)] – ohne Zurücklegen,
    Wahrscheinlichkeit je Zug proportional zu den Losen. Ganzzahlig (``randrange``), damit es
    keine Rundungsfehler gibt; ``rng`` ist standardmäßig ``secrets.SystemRandom``."""
    rng = rng or _RNG
    items = [(uid, int(w)) for uid, w in pool if int(w) > 0]
    out: list[int] = []
    while items and len(out) < k:
        total = sum(w for _, w in items)
        r = rng.randrange(total)
        acc = 0
        for i, (uid, w) in enumerate(items):
            acc += w
            if r < acc:
                out.append(uid)
                items.pop(i)
                break
    return out


def status_of(gw: dict) -> str:
    return gw.get("status") or "running"
