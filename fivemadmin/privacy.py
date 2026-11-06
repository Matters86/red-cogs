"""Red-Datenlöschung anhand gespeicherter Discord-IDs; keine Namens-/Spieler-Zuordnung."""
import asyncio
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from . import db

log = logging.getLogger("red.red-cogs.fivemadmin")
LABEL = "Gelöschter Nutzer"


def _references_case(value, affected):
    if isinstance(value, dict):
        case = value.get("case")
        if isinstance(case, dict) and str(case.get("id")) in affected:
            return True
        if any(str(value.get(key)) in affected for key in ("caseId", "case_id")):
            return True
        return any(_references_case(child, affected) for child in value.values())
    if isinstance(value, list):
        return any(_references_case(child, affected) for child in value)
    return False


def _photo_path(root, filename):
    if not isinstance(filename, str) or not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        return None
    path = root / filename
    try:
        return path if path.resolve().parent == root.resolve() else None
    except OSError:
        return None


def clean_database(path, uid):
    """Eine vertrauenswürdig konfigurierte Datenbank, atomare Zeilenänderungen, danach sichere Datei-Bereinigung."""
    path = Path(path)
    if not path.is_file():
        return
    photo_root = path.parent / "support_media"
    with closing(sqlite3.connect(path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            affected = set()
            if "support_cases" in tables:
                affected.update(str(r[0]) for r in conn.execute(
                    "SELECT id FROM support_cases WHERE created_by=? OR assigned_to=?", (uid, uid)))
            for table, field in (("support_case_events", "actor_id"), ("support_case_photos", "created_by")):
                if table in tables:
                    affected.update(str(r[0]) for r in conn.execute(f"SELECT case_id FROM {table} WHERE {field}=?", (uid,)))
            own_case = "case_id IN (SELECT id FROM support_cases WHERE created_by=?)" if "support_cases" in tables else "0"
            own_values = (uid,) if "support_cases" in tables else ()
            conn.execute("CREATE TABLE IF NOT EXISTS privacy_file_cleanup (filename TEXT PRIMARY KEY)")
            if "support_case_photos" in tables:
                where = f"created_by=? OR {own_case}"
                values = (uid, *own_values)
                for row in conn.execute(f"SELECT filename FROM support_case_photos WHERE {where}", values):
                    if _photo_path(photo_root, row[0]) is not None:
                        conn.execute("INSERT OR IGNORE INTO privacy_file_cleanup VALUES(?)", (row[0],))
                conn.execute(f"DELETE FROM support_case_photos WHERE {where}", values)
            if "support_case_events" in tables:
                conn.execute(f"DELETE FROM support_case_events WHERE {own_case}", own_values)
                conn.execute("UPDATE support_case_events SET actor_id='0',actor_name=?,text=?,report=NULL WHERE actor_id=?",
                             (LABEL, LABEL, uid))
            if "support_cases" in tables:
                conn.execute("DELETE FROM support_cases WHERE created_by=?", (uid,))
                conn.execute("UPDATE support_cases SET assigned_to=NULL,assigned_name=NULL,version=version+1 WHERE assigned_to=?", (uid,))
            if "support_case_requests" in tables:
                for row in conn.execute("SELECT request_id,actor_id,response FROM support_case_requests").fetchall():
                    try:
                        linked = _references_case(json.loads(row["response"]), affected)
                    except (ValueError, TypeError):
                        linked = False
                    if row["actor_id"] == uid or linked:
                        conn.execute("DELETE FROM support_case_requests WHERE request_id=?", (row["request_id"],))
            for table in ("login_tokens", "sessions"):
                if table in tables:
                    conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
            if "actions" in tables:
                columns = {r[1] for r in conn.execute("PRAGMA table_info(actions)")}
                if "author_user_id" in columns:
                    conn.execute("UPDATE actions SET author_user_id='0',created_by=? WHERE author_user_id=?", (LABEL, uid))
        # Namen bleiben bei Fehlern ohne Nutzerbezug in einer kleinen Wiederholungsliste.
        for row in conn.execute("SELECT filename FROM privacy_file_cleanup").fetchall():
            target = _photo_path(photo_root, row[0])
            if target is None:
                continue
            try:
                target.unlink(missing_ok=True)
            except OSError:
                log.warning("FiveM-Datenlöschung: Supportfoto konnte noch nicht entfernt werden")
                continue
            with conn:
                conn.execute("DELETE FROM privacy_file_cleanup WHERE filename=?", (row[0],))


async def delete_user(cog, user_id):
    uid = str(int(user_id))
    # Nur vom Cog konfigurierte Pfade verwenden, nie Dateipfade aus Requests oder DB-Zeilen.
    seen = set()
    targets = [(None, db.DB_PATH), *list(db._PROFILE_PATHS.items())]
    for profile_id, path in targets:
        resolved = Path(path).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            if profile_id is None:
                await asyncio.to_thread(clean_database, path, uid)
            else:
                with db.profile_scope(profile_id):
                    await asyncio.to_thread(clean_database, db.current_db_path(), uid)
        except (OSError, sqlite3.Error, ValueError):
            log.exception("FiveM-Datenlöschung in Profil %s fehlgeschlagen", profile_id or "Anmeldung")
    for gid in await cog.config.all_guilds():
        guild_conf = cog.config.guild_from_id(int(gid))
        for field in ("user_map", "profile_selection"):
            async with getattr(guild_conf, field)() as mapping:
                mapping.pop(uid, None)
    gate = getattr(cog, "_player_search_gate", {})
    for key in list(gate):
        if isinstance(key, tuple) and len(key) == 3 and str(key[2]) == uid:
            gate.pop(key, None)
