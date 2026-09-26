"""Fehlerprotokoll für das Dashboard: ``logging.Handler`` am Logger ``red`` mit Ringpuffer im RAM.

* Fängt WARNING und höher aller Red-/Cog-Logger (``red.<cog>``, ``red.red-cogs.<cog>`` …).
* Speichert höchstens ``MAX_RECORDS`` Einträge (älteste fallen raus) – nichts landet auf der Platte.
* Secrets werden schon beim Erfassen maskiert (bekannte Werte + typische Muster wie ``token=…``,
  ``Authorization: …``, ``Bearer …``) und bei der Anzeige erneut.
* Beim Neuladen von WebCore wird der alte Handler entfernt und sein Puffer übernommen – es gibt nie
  zwei Handler gleichzeitig (Erkennung über das Attribut ``_webcore_errorlog``, nicht über die Klasse,
  weil die Klasse nach einem Reload ein neues Objekt ist).
"""

from __future__ import annotations

import collections
import logging
import re
import time

MAX_RECORDS = 500
MAX_MESSAGE = 4000
MAX_TRACEBACK = 20000
LOGGER_NAME = "red"
MASK = "••••••"
_MARKER = "_webcore_errorlog"

# Schlüssel=Wert / "schlüssel": "wert" mit geheimem Namen (token, client_secret, password, api_key …)
_KV_RE = re.compile(
    r"""(?ix)
    (\b[\w-]*(?:secret|token|passw(?:or)?d|passwort|api[_-]?key|apikey)[\w-]*["']?\s*[:=]\s*["']?)
    (?!\s)([^\s"'&,;}\]]+)
    """
)
# Authorization-Header (mit oder ohne Schema)
_AUTH_RE = re.compile(r"""(?i)(\bauthorization["']?\s*[:=]\s*["']?)(?:(bearer|bot|basic)\s+)?([^\s"',;}\]]+)""")
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{4,}")
# Discord-Bot-Token (drei Base64-Teile)
_DISCORD_TOKEN_RE = re.compile(r"\b[MNO][A-Za-z\d_-]{23,30}\.[A-Za-z\d_-]{5,7}\.[A-Za-z\d_-]{25,}\b")


def _auth_sub(m) -> str:
    scheme = m.group(2)
    return f"{m.group(1)}{scheme + ' ' if scheme else ''}{MASK}"


def mask_secrets(text, known=()) -> str:
    """Bekannte Secrets und typische Secret-Muster in ``text`` durch ``••••••`` ersetzen."""
    if not text:
        return "" if text is None else str(text)
    text = str(text)
    for secret in sorted({str(s) for s in known if s and len(str(s)) >= 6}, key=len, reverse=True):
        text = text.replace(secret, MASK)
    text = _AUTH_RE.sub(_auth_sub, text)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)} {MASK}", text)
    text = _KV_RE.sub(lambda m: m.group(1) + MASK, text)
    text = _DISCORD_TOKEN_RE.sub(MASK, text)
    return text


def source_of(logger_name: str) -> str:
    """Kurzname der Quelle: ``red.red-cogs.tickets`` → ``tickets``, ``red.core`` → ``core``."""
    name = str(logger_name or "")
    for prefix in ("red.red-cogs.", "red."):
        if name.startswith(prefix):
            rest = name[len(prefix):]
            return rest.split(".", 1)[0] or name
    return name or "?"


class RingBufferHandler(logging.Handler):
    """Hält die letzten ``maxlen`` WARNING+-Einträge als kleine Dicts im Speicher."""

    def __init__(self, maxlen: int = MAX_RECORDS, secrets_provider=None):
        super().__init__(level=logging.WARNING)
        setattr(self, _MARKER, True)
        self.records: collections.deque = collections.deque(maxlen=maxlen)
        self.secrets_provider = secrets_provider  # () -> Iterable[str]
        self._counter = 0
        self._fmt = logging.Formatter()

    def _known(self):
        try:
            return tuple(self.secrets_provider() or ()) if self.secrets_provider else ()
        except Exception:  # noqa: BLE001
            return ()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            try:
                msg = record.getMessage()
            except Exception:  # noqa: BLE001 – kaputte %-Formatierung darf nichts verlieren
                msg = f"{record.msg!r} {record.args!r}"
            tb = ""
            if record.exc_info:
                tb = self._fmt.formatException(record.exc_info)
            elif record.exc_text:
                tb = record.exc_text
            if record.stack_info:
                tb = (tb + "\n" if tb else "") + self._fmt.formatStack(record.stack_info)
            known = self._known()
            self._counter += 1
            self.records.append({
                "id": self._counter,
                "ts": record.created,
                "level": record.levelname,
                "levelno": record.levelno,
                "logger": record.name,
                "source": source_of(record.name),
                "message": mask_secrets(msg[:MAX_MESSAGE], known),
                "traceback": mask_secrets(tb[-MAX_TRACEBACK:], known) if tb else "",
            })
        except Exception:  # noqa: BLE001 – ein Log-Handler darf nie selbst werfen
            self.handleError(record)

    def snapshot(self) -> list:
        """Einträge, neueste zuerst."""
        return list(reversed(self.records))

    def clear(self) -> None:
        self.records.clear()


def _ours(handler) -> bool:
    return bool(getattr(handler, _MARKER, False))


def install(secrets_provider=None, logger_name: str = LOGGER_NAME) -> RingBufferHandler:
    """Handler am Logger ``red`` anbringen. Vorhandene WebCore-Handler (z. B. vom letzten Laden)
    werden entfernt; ihr Puffer wird übernommen."""
    logger = logging.getLogger(logger_name)
    handler = RingBufferHandler(secrets_provider=secrets_provider)
    for old in [h for h in logger.handlers if _ours(h)]:
        try:
            handler.records.extend(getattr(old, "records", ()))
            handler._counter = max(handler._counter, getattr(old, "_counter", 0))
        except Exception:  # noqa: BLE001
            pass
        logger.removeHandler(old)
    logger.addHandler(handler)
    return handler


def remove(handler, logger_name: str = LOGGER_NAME) -> None:
    """Handler wieder entfernen (``cog_unload``)."""
    if handler is None:
        return
    logger = logging.getLogger(logger_name)
    if handler in logger.handlers:
        logger.removeHandler(handler)
    try:
        handler.close()
    except Exception:  # noqa: BLE001
        pass


def installed_count(logger_name: str = LOGGER_NAME) -> int:
    return sum(1 for h in logging.getLogger(logger_name).handlers if _ours(h))


def fmt_time(ts) -> str:
    try:
        return time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError, OSError):
        return "—"
