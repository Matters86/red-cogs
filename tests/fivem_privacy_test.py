"""FiveM-Datenlöschung: profilgetrennt, exakte IDs, Fotos sicher, Queue unverändert."""
import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import fivem_harness as F
import bootstrap
from rc.fivemadmin import db


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def seed(path):
    root = path.parent / "support_media"
    root.mkdir(parents=True, exist_ok=True)
    for name in ("owncase.png", "mine.png", "keep.png"):
        (root / name).write_bytes(name.encode())
    (path.parent / "escape.png").write_bytes(b"must stay")
    with closing(connect(path)) as conn, conn:
        for cid, uid in ((901, "13"), (902, "15"), (903, "113"), (904, "113")):
            conn.execute("INSERT INTO support_cases(id,title,description,citizenid,created_by,created_name,assigned_to,assigned_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (cid, "Titel " + str(cid), "Persönlicher Inhalt", "13", uid, "Gleicher Name",
                 "13" if cid == 902 else None, "Person 13" if cid == 902 else None, 1, 1))
        for cid, uid, text, report in ((901, "15", "Fremde Antwort in eigenem Fall", None),
                (902, "13", "Eigener privater Kommentar", '{"private":"report"}'),
                (902, "15", "Fremder Inhalt mit 13", None), (903, "113", "Nicht verwechseln", None)):
            conn.execute("INSERT INTO support_case_events(case_id,type,text,actor_id,actor_name,report,at) VALUES(?,?,?,?,?,?,?)",
                         (cid, "comment", text, uid, "Gleicher Name", report, 1))
        for pid, cid, uid, name in (("p1", 901, "15", "owncase.png"), ("p2", 902, "13", "mine.png"),
                ("p3", 902, "15", "keep.png"), ("p4", 903, "13", "../escape.png")):
            conn.execute("INSERT INTO support_case_photos VALUES(?,?,?,?,?,?,?,?,?)",
                         (pid, cid, name, name, "image/png", 5, "hash", uid, 1))
        for request, uid, cid in (("ownreq", "13", 903), ("linkedown", "15", 901),
                                  ("linkedother", "15", 902), ("keepreq", "113", 904)):
            conn.execute("INSERT INTO support_case_requests VALUES(?,?,?,?,?)",
                         (request, uid, "fingerprint", json.dumps({"case": {"id": cid, "description": "cache"}}), 1))
        for uid in ("13", "113"):
            conn.execute("INSERT INTO login_tokens VALUES(?,?,?,?,?,?)", ("login-" + uid, uid, "1000", "Same Name", 9999999999, 0))
            conn.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", ("session-" + uid, uid, "1000", "Same Name", 9999999999))
        for aid, uid in (("eraseauthor", "13"), ("keepauthor", "113"), ("unverified", None)):
            conn.execute("INSERT INTO actions(id,action_type,target,params,created_by,created_at,author_user_id,status,profile_queue_hold,dispatch_hold_reason,result) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (aid, "heal", "13", '{"citizenid":"13"}', "Same Name", 1, uid, "pending", 1, "manual_hold", "result untouched"))


async def main():
    wc, bot, app, cog = await F.make_app()
    paths = {"legacy": db.DB_PATH, "dev": db.DB_PATH.parent / "profiles" / "dev" / "adminpanel.sqlite3"}
    db.configure_profiles(paths)
    for pid, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with db.profile_scope(pid):
            db.init_db()
        seed(path)
    await cog.config.guild_from_id(1000).user_map.set({"13": "support", "113": "moderator"})
    await cog.config.guild_from_id(1000).profile_selection.set({"13": "legacy", "113": "dev"})
    cog._player_search_gate = {("legacy", "1000", "13"): {}, ("dev", "1000", "113"): {}}
    original_unlink = Path.unlink
    fail_once = True

    def flaky_unlink(path, *args, **kwargs):
        if fail_once and path.name == "mine.png":
            raise PermissionError("simulierter Dateizugriffsfehler")
        return original_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", new=flaky_unlink), db.profile_scope("dev"):
        await cog.red_delete_data_for_user(requester="user", user_id=13)
        assert db.current_profile() == "dev", "Verschachtelter Profilkontext bleibt erhalten"
    fail_once = False
    for path in paths.values():
        root = path.parent / "support_media"
        assert not (root / "owncase.png").exists()
        assert (root / "mine.png").exists(), "Fehlgeschlagene Dateilöschung wird wiederholt"
        assert (root / "keep.png").exists() and (path.parent / "escape.png").exists()
        with closing(connect(path)) as conn:
            assert not conn.execute("SELECT 1 FROM support_cases WHERE id=901").fetchone()
            case = conn.execute("SELECT * FROM support_cases WHERE id=902").fetchone()
            assert case["created_by"] == "15" and case["assigned_to"] is None
            events = [dict(row) for row in conn.execute("SELECT * FROM support_case_events")]
            assert not any(row["case_id"] == 901 for row in events)
            scrubbed = next(row for row in events if row["actor_id"] == "0")
            assert scrubbed["report"] is None and scrubbed["text"] == "Gelöschter Nutzer"
            assert any(row["text"] == "Fremder Inhalt mit 13" and row["actor_id"] == "15" for row in events)
            assert {row[0] for row in conn.execute("SELECT id FROM support_case_photos")} == {"p3"}
            assert {row[0] for row in conn.execute("SELECT request_id FROM support_case_requests")} == {"keepreq"}
            assert {row[0] for row in conn.execute("SELECT user_id FROM login_tokens")} == {"113"}
            assert {row[0] for row in conn.execute("SELECT user_id FROM sessions")} == {"113"}
            actions = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM actions WHERE id IN ('eraseauthor','keepauthor','unverified')")}
            assert actions["eraseauthor"]["author_user_id"] == "0"
            assert actions["keepauthor"]["author_user_id"] == "113" and actions["unverified"]["created_by"] == "Same Name"
            assert all(row["status"] == "pending" and row["profile_queue_hold"] == 1
                       and row["dispatch_hold_reason"] == "manual_hold" and row["result"] == "result untouched"
                       and row["target"] == "13" for row in actions.values())
    assert await cog.config.guild_from_id(1000).user_map() == {"113": "moderator"}
    assert await cog.config.guild_from_id(1000).profile_selection() == {"113": "dev"}
    assert set(cog._player_search_gate) == {("dev", "1000", "113")}
    await cog.red_delete_data_for_user(requester="owner", user_id=13)
    await cog.red_delete_data_for_user(requester="discord_deleted_user", user_id=13)
    for path in paths.values():
        assert not (path.parent / "support_media" / "mine.png").exists()
        assert (path.parent / "support_media" / "keep.png").exists()
    # Eine kaputte Profil-DB darf die anderen Profile und Config-Bereinigung nicht blockieren.
    broken = bootstrap.tmpdir("broken_profile") / "adminpanel.sqlite3"
    broken.write_bytes(b"not a sqlite database")
    db.configure_profiles({"live": broken, **paths})
    await cog.red_delete_data_for_user(requester="user_strict", user_id=13)
    cog.runner = None
    await cog.cog_unload()
    await wc.cog_unload()
    print("FIVEM DATENLÖSCHUNG OK: beide Profile, exakte IDs, fremde Inhalte, sichere Fotos, Wiederholung, unveränderte Queue")


asyncio.run(main())
