"""
Gemeinsame DB-Schicht für das Adminpanel.
Action-Queue + Login-Tokens + Sessions + Server-State.
"""

import hashlib
import json
import math
import secrets
import shutil
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

# Früherer Speicherort: direkt im Code-Ordner des Cogs. Dort geht die DB bei
# `[p]cog uninstall`/Neuinstallation verloren und landet beim Entwickeln im Repo-Ordner.
# set_data_dir() verlegt sie beim Laden in Reds Datenordner (cog_data_path).
_LEGACY_DIR = Path(__file__).parent
DB_PATH = _LEGACY_DIR / "adminpanel.sqlite3"
_PROFILE = ContextVar("adminpanel_server_profile", default=None)
_PROFILE_PATHS = {}
_PROFILE_SCOPING_REQUIRED = False

LOGIN_TOKEN_TTL = 300        # 5 Minuten gültig
SESSION_TTL = 12 * 3600      # 12 Stunden


def set_data_dir(data_dir) -> Path:
    """Setzt den DB-Speicherort auf ``data_dir`` (Reds Datenordner des Cogs).

    Einmalige Migration: existiert dort noch keine DB, aber am alten Ort, wird sie
    per SQLite-Backup-API konsistent kopiert (inkl. WAL-Inhalt); ``backups/`` wird
    mitkopiert. Die alte Datei bleibt als zusätzliche Sicherung unangetastet liegen.
    """
    global DB_PATH
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    new_path = data_dir / "adminpanel.sqlite3"
    legacy = _LEGACY_DIR / "adminpanel.sqlite3"
    if not new_path.exists() and legacy.exists() and legacy.resolve() != new_path.resolve():
        with closing(sqlite3.connect(legacy)) as src, closing(sqlite3.connect(new_path)) as dst:
            with dst:
                src.backup(dst)
        legacy_backups = _LEGACY_DIR / "backups"
        if legacy_backups.is_dir():
            shutil.copytree(legacy_backups, data_dir / "backups", dirs_exist_ok=True)
    DB_PATH = new_path
    return new_path


def configure_profiles(paths):
    """Nur vertrauenswürdige Konfiguration, niemals ein Request-Dateipfad."""
    global _PROFILE_PATHS, _PROFILE_SCOPING_REQUIRED
    _PROFILE_PATHS = {key: Path(value) for key, value in paths.items()}
    _PROFILE_SCOPING_REQUIRED = True


def current_profile():
    return _PROFILE.get()


def current_db_path(*, auth=False):
    if auth:
        return DB_PATH
    profile = current_profile()
    if profile in _PROFILE_PATHS:
        return _PROFILE_PATHS[profile]
    if _PROFILE_SCOPING_REQUIRED:
        raise RuntimeError("server_profile_scope_required")
    return DB_PATH  # Nur vor Konfiguration/Legacy-Migration, nie als Request-Default.


def profile_data_dir():
    return current_db_path().parent


@contextmanager
def profile_scope(profile_id):
    if profile_id not in _PROFILE_PATHS:
        raise ValueError("unknown_server_profile")
    token = _PROFILE.set(profile_id)
    try:
        yield profile_id
    finally:
        _PROFILE.reset(token)


def get_conn(*, auth=False):
    conn = sqlite3.connect(current_db_path(auth=auth))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(*, auth=False):
    with closing(get_conn(auth=auth)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS actions (
                id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                target TEXT NOT NULL,
                params TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                created_by TEXT,
                created_at REAL NOT NULL,
                completed_at REAL
            );

            CREATE TABLE IF NOT EXISTS login_tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                expires_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS server_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS catalog (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS game_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                severity TEXT NOT NULL,
                type TEXT NOT NULL,
                citizenid TEXT,
                name TEXT,
                message TEXT NOT NULL,
                at REAL NOT NULL,
                received_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS player_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                citizenid TEXT NOT NULL,
                kind TEXT NOT NULL,          -- 'note' | 'warn'
                text TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                citizenid TEXT,
                license TEXT,
                discord TEXT,
                name TEXT,
                reason TEXT NOT NULL,
                banned_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL          -- NULL = permanent
            );
        """)
        conn.commit()
        # Additive Migration. Keine Pending-Aktion wird beim Upgrade neu angelegt,
        # freigegeben oder als bereits ausgeführt behandelt.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(actions)")}
        for name, definition in (
            ("target_name", "TEXT"),
            ("callback_fingerprint", "TEXT"),
            ("result_review_required", "INTEGER NOT NULL DEFAULT 0"),
            ("result_review_reason", "TEXT"),
            ("audit_delivery", "TEXT"),
            ("audit_claimed_at", "REAL"),
            ("audit_completed_at", "REAL"),
            ("profile_queue_hold", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                conn.execute(f"ALTER TABLE actions ADD COLUMN {name} {definition}")
                if name == "profile_queue_hold":
                    conn.execute("UPDATE actions SET profile_queue_hold = 1 WHERE status = 'pending'")
        from . import support_store
        support_store.install(conn)
        conn.commit()


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------

def add_action(action_type: str, target: str, params: Optional[str], created_by: str) -> str:
    action_id = str(uuid.uuid4())
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO actions (id, action_type, target, params, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (action_id, action_type, target, params, created_by, time.time()),
        )
        conn.commit()
    return action_id


def get_pending_actions():
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM actions WHERE status = 'pending' AND profile_queue_hold = 0 ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def _flag_result_review(conn, action_id: str, reason: str):
    row = conn.execute("SELECT result_review_reason FROM actions WHERE id = ?", (action_id,)).fetchone()
    reasons = (row[0] or "").split(";") if row else []
    if reason not in reasons:
        reasons.append(reason)
    conn.execute(
        "UPDATE actions SET result_review_required = 1, result_review_reason = ? WHERE id = ?",
        (";".join(filter(None, reasons))[:512], action_id),
    )


def _insert_completed_ban(conn, action, result: str, completed_at: float):
    """Nur innerhalb der ersten Ergebnis-Transaktion; kein Wiederaufbau bei Retry."""
    try:
        params = json.loads(action.get("params") or "{}")
        info = json.loads(result)
        if not isinstance(params, dict) or not isinstance(info, dict):
            raise ValueError("invalid ban payload")
        hours = params.get("hours")
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 0:
            raise ValueError("invalid ban duration")
        expires_at = completed_at + hours * 3600 if hours else None
        if expires_at is not None and not math.isfinite(expires_at):
            raise ValueError("invalid ban expiry")
        license_id, discord_id = info.get("license"), info.get("discord")
        for value in (license_id, discord_id, info.get("name")):
            if value is not None and (not isinstance(value, str) or len(value) > 256):
                raise ValueError("invalid ban identity")
        if not license_id and not discord_id:
            raise ValueError("unconfirmed ban identity")
        reason = params.get("reason") or "Kein Grund angegeben"
        if not isinstance(reason, str):
            raise ValueError("invalid ban reason")
    except (ValueError, TypeError, OverflowError):
        # Das Spiel kann die Aktion bereits ausgeführt haben. Nicht stillschweigend
        # eine permanente Sperre erfinden oder das Ergebnis erneut ausführen lassen.
        _flag_result_review(conn, action["id"], "ban_persistence_unconfirmed")
        return
    conn.execute("DELETE FROM bans WHERE citizenid = ?", (action["target"],))
    conn.execute(
        "INSERT INTO bans (citizenid, license, discord, name, reason, banned_by, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (action["target"], license_id, discord_id, info.get("name"), reason,
         action.get("created_by") or "unbekannt", completed_at, expires_at),
    )


def mark_action_result(action_id: str, status: str, result: str, *,
                       resolved_target=None, resolved_name=None, audit_required=False):
    """Terminales Bridge-Ergebnis genau einmal annehmen, inkl. Ban-Persistenz.

    Ein bereits gespeichertes Ergebnis bleibt unverändert. Gleiche Callbacks sind
    wiederholbar; widersprüchliche Callbacks werden nur als prüfpflichtig markiert.
    Die Rückgabe enthält ``outcome`` und die gespeicherte Aktion, keine Queue-Freigabe.
    """
    if not isinstance(action_id, str) or not action_id or len(action_id) > 128:
        raise ValueError("invalid_id")
    if status not in ("done", "failed") or not isinstance(status, str):
        raise ValueError("invalid_status")
    if not isinstance(result, str) or len(result) > 1024 * 1024:
        raise ValueError("invalid_result")
    for value in (resolved_target, resolved_name):
        if value is not None and (not isinstance(value, str) or not value or len(value) > 256):
            raise ValueError("invalid_resolved_identity")
    if resolved_name is not None and resolved_target is None:
        raise ValueError("resolved_target_required")
    fingerprint = hashlib.sha256(json.dumps(
        [status, result, resolved_target, resolved_name], ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    with closing(get_conn()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            conn.rollback()
            return {"outcome": "not_found", "action": None}
        action = dict(row)
        if action["status"] == "pending":
            completed_at = time.time()
            target = resolved_target if resolved_target is not None else action["target"]
            name = resolved_name if resolved_name is not None else action.get("target_name")
            conn.execute(
                "UPDATE actions SET status = ?, result = ?, completed_at = ?, target = ?, target_name = ?, "
                "callback_fingerprint = ?, audit_delivery = ? WHERE id = ? AND status = 'pending'",
                (status, result, completed_at, target, name, fingerprint,
                 "pending" if audit_required else None, action_id),
            )
            action["target"] = target
            if action["action_type"] == "ban" and status == "done":
                _insert_completed_ban(conn, action, result, completed_at)
            outcome = "accepted"
        else:
            same = action.get("callback_fingerprint") == fingerprint
            if not action.get("callback_fingerprint"):
                # Altbestand hat keinen Callback-Beleg. Weder Ban noch Audit beim
                # Upgrade nachholen; ein gleiches Ergebnis lediglich quittieren.
                same = (action["status"] == status and action.get("result") == result
                        and (resolved_target is None or resolved_target == action["target"])
                        and (resolved_name is None or resolved_name == action.get("target_name")))
                _flag_result_review(conn, action_id, "legacy_terminal_unverified")
            if not same:
                _flag_result_review(conn, action_id, "terminal_callback_conflict")
            outcome = "replayed" if same else "conflict"
        saved = dict(conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone())
        conn.commit()
        return {"outcome": outcome, "action": saved}


def claim_result_audit(action_id: str) -> bool:
    """Vor externem Versand reservieren: parallele Callbacks senden nie doppelt."""
    with closing(get_conn()) as conn:
        cur = conn.execute(
            "UPDATE actions SET audit_delivery = 'claimed', audit_claimed_at = ? "
            "WHERE id = ? AND status IN ('done', 'failed') AND audit_delivery = 'pending'",
            (time.time(), action_id),
        )
        conn.commit()
        return cur.rowcount == 1


def finish_result_audit(action_id: str, delivery: str):
    if delivery not in ("sent", "not_configured", "uncertain"):
        raise ValueError("invalid_audit_delivery")
    with closing(get_conn()) as conn:
        cur = conn.execute(
            "UPDATE actions SET audit_delivery = ?, audit_completed_at = ? "
            "WHERE id = ? AND audit_delivery = 'claimed'",
            (delivery, time.time(), action_id),
        )
        if cur.rowcount and delivery == "uncertain":
            _flag_result_review(conn, action_id, "audit_delivery_uncertain")
        conn.commit()


def cancel_pending_actions(reason: str) -> int:
    """Verwirft alle noch offenen Aufträge (Not-Aus). Rückgabe: Anzahl."""
    with closing(get_conn()) as conn:
        cur = conn.execute(
            "UPDATE actions SET status = 'failed', result = ?, completed_at = ? WHERE status = 'pending'",
            (reason, time.time()),
        )
        conn.commit()
        return cur.rowcount


def newest_backup_age() -> Optional[float]:
    """Alter des jüngsten Backups in Sekunden (None = noch keins)."""
    backup_dir = current_db_path().parent / "backups"
    files = sorted(backup_dir.glob("adminpanel_*.sqlite3")) if backup_dir.is_dir() else []
    if not files:
        return None
    return max(0.0, time.time() - files[-1].stat().st_mtime)


def get_action(action_id: str):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    return dict(row) if row else None


def get_recent_actions(limit: int = 25):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_actions_for(citizenid: str, limit: int = 50):
    """Alle Aktionen, die diesen Spieler betreffen (als Ziel oder in den Params, z. B. Teleport-Ziel)."""
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM actions WHERE target = ? OR (params IS NOT NULL AND params LIKE ?) "
            "ORDER BY created_at DESC LIMIT ?",
            (citizenid, f'%"{citizenid}"%', limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_events_for(citizenid: str, limit: int = 50):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM game_events WHERE citizenid = ? ORDER BY at DESC, id DESC LIMIT ?",
            (citizenid, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Notizen & Verwarnungen
# ------------------------------------------------------------------

def add_note(citizenid: str, kind: str, text: str, created_by: str) -> int:
    with closing(get_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO player_notes (citizenid, kind, text, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (citizenid, kind, text, created_by, time.time()),
        )
        conn.commit()
        note_id = cur.lastrowid
    return note_id


def get_notes(citizenid: str, limit: int = 100):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM player_notes WHERE citizenid = ? ORDER BY created_at DESC LIMIT ?",
            (citizenid, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_note(note_id: int) -> bool:
    with closing(get_conn()) as conn:
        cur = conn.execute("DELETE FROM player_notes WHERE id = ?", (note_id,))
        conn.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------------
# Bans
# ------------------------------------------------------------------

def add_ban(citizenid, license, discord, name, reason, banned_by, expires_at):
    """Legt einen Ban an (ersetzt einen evtl. bestehenden für dieselbe CitizenID)."""
    with closing(get_conn()) as conn:
        if citizenid:
            conn.execute("DELETE FROM bans WHERE citizenid = ?", (citizenid,))
        conn.execute(
            "INSERT INTO bans (citizenid, license, discord, name, reason, banned_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (citizenid, license, discord, name, reason, banned_by, time.time(), expires_at),
        )
        conn.commit()


def get_active_bans():
    now = time.time()
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM bans WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        conn.commit()
        rows = conn.execute("SELECT * FROM bans ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_ban(citizenid: str):
    now = time.time()
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM bans WHERE citizenid = ? AND (expires_at IS NULL OR expires_at > ?)",
            (citizenid, now),
        ).fetchone()
    return dict(row) if row else None


def remove_ban(citizenid: str) -> bool:
    with closing(get_conn()) as conn:
        cur = conn.execute("DELETE FROM bans WHERE citizenid = ?", (citizenid,))
        conn.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------------
# Audit (Admin-Aktivität)
# ------------------------------------------------------------------

def update_action_target(action_id: str, target: str, target_name: str = None):
    """Ersetzt das Target einer Action (Name -> aufgelöste CitizenID) und speichert den Anzeigenamen."""
    with closing(get_conn()) as conn:
        if target_name:
            conn.execute("UPDATE actions SET target = ?, target_name = ? WHERE id = ?",
                         (target, target_name, action_id))
        else:
            conn.execute("UPDATE actions SET target = ? WHERE id = ?", (target, action_id))
        conn.commit()


def get_actions_audit(limit: int = 200):
    """Aktionen für die Audit-Ansicht – mehr Tiefe als das normale Protokoll."""
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Backup
# ------------------------------------------------------------------

def backup_db(keep: int = 14):
    """Kopiert die DB konsistent in einen backups/-Ordner, behält die letzten `keep`."""
    from datetime import datetime

    selected_path = current_db_path()
    backup_dir = selected_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"adminpanel_{stamp}.sqlite3"

    # sqlite backup-API für konsistente Kopie (auch bei laufenden Schreibvorgängen)
    with closing(sqlite3.connect(selected_path)) as src, closing(sqlite3.connect(dest)) as dst:
        with dst:
            src.backup(dst)

    backups = sorted(backup_dir.glob("adminpanel_*.sqlite3"))
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
    return str(dest), len(backups[-keep:]) if len(backups) > keep else len(backups)


# ------------------------------------------------------------------
# Login-Tokens (Einmal-Links aus Discord)
# ------------------------------------------------------------------

def create_login_token(user_id: str, guild_id: str, display_name: str) -> str:
    token = secrets.token_urlsafe(32)
    with closing(get_conn(auth=True)) as conn:
        conn.execute(
            "INSERT INTO login_tokens (token, user_id, guild_id, display_name, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, user_id, guild_id, display_name, time.time() + LOGIN_TOKEN_TTL),
        )
        conn.commit()
    return token


def redeem_login_token(token: str):
    """Löst einen Login-Token ein und erzeugt eine Session. Gibt Session-Dict oder None zurück."""
    now = time.time()
    with closing(get_conn(auth=True)) as conn:
        row = conn.execute(
            "SELECT * FROM login_tokens WHERE token = ? AND used = 0 AND expires_at > ?",
            (token, now),
        ).fetchone()
        if not row:
            return None

        conn.execute("UPDATE login_tokens SET used = 1 WHERE token = ?", (token,))

        session_token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (token, user_id, guild_id, display_name, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_token, row["user_id"], row["guild_id"], row["display_name"], now + SESSION_TTL),
        )
        conn.commit()
        return {
            "token": session_token,
            "user_id": row["user_id"],
            "guild_id": row["guild_id"],
            "display_name": row["display_name"],
        }


def get_session(token: str):
    now = time.time()
    with closing(get_conn(auth=True)) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute("DELETE FROM login_tokens WHERE expires_at <= ?", (now,))
        conn.commit()
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------------
# Server-State (Heartbeat der FiveM-Bridge)
# ------------------------------------------------------------------

def save_server_state(payload: dict):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO server_state (id, payload, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (json.dumps(payload), time.time()),
        )
        conn.commit()


def get_server_state():
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT payload, updated_at FROM server_state WHERE id = 1").fetchone()
    if not row:
        return None
    state = json.loads(row["payload"])
    state["synced_at"] = row["updated_at"]
    return state


# ------------------------------------------------------------------
# Item-Katalog (von der Bridge beim Start geliefert)
# ------------------------------------------------------------------

def save_catalog(payload: dict):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO catalog (id, payload, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (json.dumps(payload), time.time()),
        )
        conn.commit()


def get_catalog():
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT payload FROM catalog WHERE id = 1").fetchone()
    return json.loads(row["payload"]) if row else None


# ------------------------------------------------------------------
# Ereignis-Log (Anti-Missbrauch-Events der Bridge)
# ------------------------------------------------------------------

def add_events(event_list):
    now = time.time()
    with closing(get_conn()) as conn:
        conn.executemany(
            "INSERT INTO game_events (severity, type, citizenid, name, message, at, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    str(e.get("severity", "info")),
                    str(e.get("type", "unknown")),
                    e.get("citizenid"),
                    e.get("name"),
                    str(e.get("message", "")),
                    float(e.get("at") or now),
                    now,
                )
                for e in event_list
                if isinstance(e, dict)
            ],
        )
        # Log begrenzen, damit die DB nicht unendlich wächst
        conn.execute(
            "DELETE FROM game_events WHERE id NOT IN "
            "(SELECT id FROM game_events ORDER BY at DESC LIMIT 5000)"
        )
        conn.commit()


def get_recent_events(limit: int = 60):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM game_events ORDER BY at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
