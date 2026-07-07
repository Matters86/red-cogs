"""
Gemeinsame DB-Schicht für das Adminpanel.
Action-Queue + Login-Tokens + Sessions + Server-State.
"""

import json
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "adminpanel.sqlite3"

LOGIN_TOKEN_TTL = 300        # 5 Minuten gültig
SESSION_TTL = 12 * 3600      # 12 Stunden


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
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
    conn.close()


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------

def add_action(action_type: str, target: str, params: Optional[str], created_by: str) -> str:
    action_id = str(uuid.uuid4())
    conn = get_conn()
    conn.execute(
        "INSERT INTO actions (id, action_type, target, params, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (action_id, action_type, target, params, created_by, time.time()),
    )
    conn.commit()
    conn.close()
    return action_id


def get_pending_actions():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM actions WHERE status = 'pending' ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_action_result(action_id: str, status: str, result: str):
    conn = get_conn()
    conn.execute(
        "UPDATE actions SET status = ?, result = ?, completed_at = ? WHERE id = ?",
        (status, result, time.time(), action_id),
    )
    conn.commit()
    conn.close()


def get_action(action_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_actions(limit: int = 25):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_actions_for(citizenid: str, limit: int = 50):
    """Alle Aktionen, die diesen Spieler betreffen (als Ziel oder in den Params, z. B. Teleport-Ziel)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM actions WHERE target = ? OR (params IS NOT NULL AND params LIKE ?) "
        "ORDER BY created_at DESC LIMIT ?",
        (citizenid, f'%"{citizenid}"%', limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_events_for(citizenid: str, limit: int = 50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM game_events WHERE citizenid = ? ORDER BY at DESC, id DESC LIMIT ?",
        (citizenid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Notizen & Verwarnungen
# ------------------------------------------------------------------

def add_note(citizenid: str, kind: str, text: str, created_by: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO player_notes (citizenid, kind, text, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (citizenid, kind, text, created_by, time.time()),
    )
    conn.commit()
    note_id = cur.lastrowid
    conn.close()
    return note_id


def get_notes(citizenid: str, limit: int = 100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM player_notes WHERE citizenid = ? ORDER BY created_at DESC LIMIT ?",
        (citizenid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_note(note_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM player_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ------------------------------------------------------------------
# Bans
# ------------------------------------------------------------------

def add_ban(citizenid, license, discord, name, reason, banned_by, expires_at):
    """Legt einen Ban an (ersetzt einen evtl. bestehenden für dieselbe CitizenID)."""
    conn = get_conn()
    if citizenid:
        conn.execute("DELETE FROM bans WHERE citizenid = ?", (citizenid,))
    conn.execute(
        "INSERT INTO bans (citizenid, license, discord, name, reason, banned_by, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (citizenid, license, discord, name, reason, banned_by, time.time(), expires_at),
    )
    conn.commit()
    conn.close()


def get_active_bans():
    now = time.time()
    conn = get_conn()
    conn.execute("DELETE FROM bans WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
    conn.commit()
    rows = conn.execute("SELECT * FROM bans ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_ban(citizenid: str):
    now = time.time()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM bans WHERE citizenid = ? AND (expires_at IS NULL OR expires_at > ?)",
        (citizenid, now),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def remove_ban(citizenid: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM bans WHERE citizenid = ?", (citizenid,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ------------------------------------------------------------------
# Audit (Admin-Aktivität)
# ------------------------------------------------------------------

def update_action_target(action_id: str, target: str):
    """Ersetzt das Target einer Action (z. B. Name -> aufgelöste CitizenID)."""
    conn = get_conn()
    conn.execute("UPDATE actions SET target = ? WHERE id = ?", (target, action_id))
    conn.commit()
    conn.close()


def get_actions_audit(limit: int = 200):
    """Aktionen für die Audit-Ansicht – mehr Tiefe als das normale Protokoll."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Backup
# ------------------------------------------------------------------

def backup_db(keep: int = 14):
    """Kopiert die DB konsistent in einen backups/-Ordner, behält die letzten `keep`."""
    import shutil
    from datetime import datetime

    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"adminpanel_{stamp}.sqlite3"

    # sqlite backup-API für konsistente Kopie (auch bei laufenden Schreibvorgängen)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()

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
    conn = get_conn()
    conn.execute(
        "INSERT INTO login_tokens (token, user_id, guild_id, display_name, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (token, user_id, guild_id, display_name, time.time() + LOGIN_TOKEN_TTL),
    )
    conn.commit()
    conn.close()
    return token


def redeem_login_token(token: str):
    """Löst einen Login-Token ein und erzeugt eine Session. Gibt Session-Dict oder None zurück."""
    now = time.time()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM login_tokens WHERE token = ? AND used = 0 AND expires_at > ?",
        (token, now),
    ).fetchone()
    if not row:
        conn.close()
        return None

    conn.execute("UPDATE login_tokens SET used = 1 WHERE token = ?", (token,))

    session_token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token, user_id, guild_id, display_name, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_token, row["user_id"], row["guild_id"], row["display_name"], now + SESSION_TTL),
    )
    conn.commit()
    conn.close()
    return {
        "token": session_token,
        "user_id": row["user_id"],
        "guild_id": row["guild_id"],
        "display_name": row["display_name"],
    }


def get_session(token: str):
    now = time.time()
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    conn.execute("DELETE FROM login_tokens WHERE expires_at <= ?", (now,))
    conn.commit()
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ------------------------------------------------------------------
# Server-State (Heartbeat der FiveM-Bridge)
# ------------------------------------------------------------------

def save_server_state(payload: dict):
    conn = get_conn()
    conn.execute(
        "INSERT INTO server_state (id, payload, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
        (json.dumps(payload), time.time()),
    )
    conn.commit()
    conn.close()


def get_server_state():
    conn = get_conn()
    row = conn.execute("SELECT payload, updated_at FROM server_state WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return None
    state = json.loads(row["payload"])
    state["synced_at"] = row["updated_at"]
    return state


# ------------------------------------------------------------------
# Item-Katalog (von der Bridge beim Start geliefert)
# ------------------------------------------------------------------

def save_catalog(payload: dict):
    conn = get_conn()
    conn.execute(
        "INSERT INTO catalog (id, payload, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
        (json.dumps(payload), time.time()),
    )
    conn.commit()
    conn.close()


def get_catalog():
    conn = get_conn()
    row = conn.execute("SELECT payload FROM catalog WHERE id = 1").fetchone()
    conn.close()
    return json.loads(row["payload"]) if row else None


# ------------------------------------------------------------------
# Ereignis-Log (Anti-Missbrauch-Events der Bridge)
# ------------------------------------------------------------------

def add_events(event_list):
    now = time.time()
    conn = get_conn()
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
    conn.close()


def get_recent_events(limit: int = 60):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM game_events ORDER BY at DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
