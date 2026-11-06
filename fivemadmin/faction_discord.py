"""Profile-scoped faction Discord reconciliation. No Discord calls in bridge requests.

Only authenticated, complete server snapshots are accepted. Valid isolated dev/live profiles default to enabled; a Discord administrator
may opt out and must allow any existing role/category before selection.
Creation intent is durable: an uncertain create is held, never retried by name.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager

import discord
from .faction_discord_transport import SingleAttemptCreates

BUILD = "faction-discord.3"
DEFAULT_LIVE_MANAGEMENT_ROLE_ID = "1497218321660248165"
MAX_FACTIONS, MAX_MEMBERS, MAX_PAIRS = 128, 4096, 16384
SNOWFLAKE = re.compile(r"[1-9][0-9]{16,19}\Z")
ELEVATED = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "kick_members", "ban_members", "moderate_members", "manage_webhooks",
    "manage_messages", "manage_threads", "manage_events", "manage_expressions",
    "manage_emojis", "mention_everyone", "mute_members", "deafen_members",
    "move_members", "view_audit_log", "manage_nicknames",
)


class Refused(ValueError):
    pass


def integer(value, low=0, high=9007199254740991):
    if type(value) is not int or not low <= value <= high:
        raise Refused("invalid_integer")
    return value


def snowflake(value):
    if not isinstance(value, str) or not SNOWFLAKE.fullmatch(value):
        raise Refused("invalid_discord_id")
    return value


def label(value, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Refused("invalid_label")
    if any(ord(char) < 32 for char in value):
        raise Refused("invalid_label")
    return value.strip()


def normalize_snapshot(value):
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value.get("schema") != 1 or value.get("complete") is not True:
        raise Refused("complete_snapshot_required")
    generation = integer(value.get("generation"), 1)
    factions, members = value.get("factions"), value.get("memberships")
    if not isinstance(factions, list) or len(factions) > MAX_FACTIONS:
        raise Refused("faction_limit")
    if not isinstance(members, list) or len(members) > MAX_MEMBERS:
        raise Refused("membership_limit")
    normalized, ids = [], set()
    for item in factions:
        if not isinstance(item, dict):
            raise Refused("invalid_faction")
        fid = integer(item.get("id"), 1)
        if fid in ids:
            raise Refused("duplicate_faction")
        ids.add(fid)
        cfg = item.get("config")
        if not isinstance(cfg, dict) or cfg.get("mode") not in ("off", "auto", "existing"):
            raise Refused("invalid_mode")
        if cfg.get("categoryMode") not in ("auto", "existing"):
            raise Refused("invalid_category_mode")
        if any(type(item.get(key, False)) is not bool for key in ("enabled", "deleted")):
            raise Refused("invalid_enabled")
        if any(type(cfg.get(key)) is not bool for key in ("textEnabled", "voiceEnabled")):
            raise Refused("invalid_channel_flags")
        role_id = cfg.get("roleId")
        category_id = cfg.get("categoryId")
        if role_id is not None:
            snowflake(role_id)
        if category_id is not None:
            snowflake(category_id)
        if cfg["mode"] == "existing" and not role_id:
            raise Refused("existing_role_required")
        if cfg["categoryMode"] == "existing" and not category_id:
            raise Refused("existing_category_required")
        normalized.append({
            "id": fid, "name": label(item.get("name"), 64),
            "label": label(item.get("label"), 80), "category": label(item.get("category"), 32),
            "enabled": item.get("enabled", False), "deleted": item.get("deleted", False),
            "config": {"revision": integer(cfg.get("revision"), 0), "mode": cfg["mode"],
                       "roleId": role_id, "textEnabled": cfg["textEnabled"],
                       "voiceEnabled": cfg["voiceEnabled"], "categoryMode": cfg["categoryMode"],
                       "categoryId": category_id,
                       "categoryName": label(cfg.get("categoryName", "DNP · Fraktionen"), 80)},
        })
    accounts, seen, pairs = [], set(), 0
    for member in members:
        if not isinstance(member, dict):
            raise Refused("invalid_membership")
        uid = snowflake(member.get("discordId"))
        fids = member.get("factionIds")
        if uid in seen or not isinstance(fids, list) or len(fids) > MAX_FACTIONS:
            raise Refused("duplicate_or_invalid_member")
        seen.add(uid)
        actual = [integer(fid, 1) for fid in fids]
        if len(set(actual)) != len(actual) or not set(actual) <= ids:
            raise Refused("unconfirmed_faction_membership")
        pairs += len(actual)
        if pairs > MAX_PAIRS:
            raise Refused("membership_pair_limit")
        accounts.append({"discordId": uid, "factionIds": sorted(actual)})
    return {"schema": 1, "generation": generation, "complete": True,
            "factions": sorted(normalized, key=lambda row: row["id"]),
            "memberships": sorted(accounts, key=lambda row: row["discordId"])}


class Store:
    """Own additive tables in the existing profile DB; no existing schema changes."""
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self):
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS faction_discord_snapshot
                  (singleton INTEGER PRIMARY KEY CHECK(singleton=1), generation INTEGER NOT NULL,
                   digest TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS faction_discord_resources
                  (faction_id INTEGER NOT NULL, kind TEXT NOT NULL, discord_id TEXT,
                   phase TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated REAL NOT NULL,
                   PRIMARY KEY(faction_id,kind));
                CREATE TABLE IF NOT EXISTS faction_discord_grants
                  (role_id TEXT NOT NULL,user_id TEXT NOT NULL,PRIMARY KEY(role_id,user_id));
                CREATE TABLE IF NOT EXISTS faction_discord_status
                  (faction_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS faction_discord_retry
                  (job TEXT PRIMARY KEY,attempts INTEGER NOT NULL,next_at REAL NOT NULL,
                   code TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS faction_discord_control
                  (singleton INTEGER PRIMARY KEY CHECK(singleton=1),paused INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS faction_discord_binding
                  (singleton INTEGER PRIMARY KEY CHECK(singleton=1),guild_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS faction_discord_deletions
                  (faction_id INTEGER PRIMARY KEY,role_id TEXT NOT NULL,phase TEXT NOT NULL,
                   generation INTEGER NOT NULL,note TEXT NOT NULL,updated REAL NOT NULL);
            """)
            # Process death after a creation request is deliberately not a new request.
            conn.execute("UPDATE faction_discord_resources SET phase='held',note='create_result_unknown' WHERE phase='creating'")
            conn.execute("UPDATE faction_discord_deletions SET phase='uncertain',note='delete_result_unknown' WHERE phase='deleting'")

    def snapshot(self):
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM faction_discord_snapshot WHERE singleton=1").fetchone()
        return json.loads(row[0]) if row else None

    def accept(self, value):
        payload = normalize_snapshot(value)
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT * FROM faction_discord_snapshot WHERE singleton=1").fetchone()
            if old:
                if payload["generation"] < old["generation"]:
                    raise Refused("stale_generation")
                if payload["generation"] == old["generation"]:
                    if old["digest"] != digest:
                        raise Refused("generation_conflict")
                    return payload["generation"]
                revisions = {row["id"]: row["config"]["revision"] for row in json.loads(old["payload"])["factions"]}
                if any(row["config"]["revision"] < revisions.get(row["id"], 0) for row in payload["factions"]):
                    raise Refused("configuration_revision_rollback")
            conn.execute("INSERT OR REPLACE INTO faction_discord_snapshot VALUES(1,?,?,?)",
                         (payload["generation"], digest, text))
        return payload["generation"]

    def resources(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM faction_discord_resources")]

    def resource(self, fid, kind):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM faction_discord_resources WHERE faction_id=? AND kind=?", (fid, kind)).fetchone()
        return dict(row) if row else None

    def put_resource(self, fid, kind, did, phase, note=""):
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO faction_discord_resources VALUES(?,?,?,?,?,?)",
                         (fid, kind, str(did) if did else None, phase, note, time.time()))

    def deletion(self, fid):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM faction_discord_deletions WHERE faction_id=?", (fid,)).fetchone()
        return dict(row) if row else None

    def put_deletion(self, fid, rid, phase, generation, note=""):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT role_id FROM faction_discord_deletions WHERE faction_id=?", (fid,)).fetchone()
            if previous and previous[0] != str(rid):
                raise Refused("deletion_role_identity_changed")
            conn.execute("INSERT OR REPLACE INTO faction_discord_deletions VALUES(?,?,?,?,?,?)",
                         (fid, str(rid), phase, generation, note, time.time()))

    def drop_deleted_role_grants(self, rid):
        with self.connection() as conn:
            conn.execute("DELETE FROM faction_discord_grants WHERE role_id=?", (str(rid),))

    def grants(self):
        with self.connection() as conn:
            return {(row[0], row[1]) for row in conn.execute("SELECT role_id,user_id FROM faction_discord_grants")}

    def grant(self, rid, uid, present):
        with self.connection() as conn:
            if present:
                conn.execute("INSERT OR IGNORE INTO faction_discord_grants VALUES(?,?)", (rid, uid))
            else:
                conn.execute("DELETE FROM faction_discord_grants WHERE role_id=? AND user_id=?", (rid, uid))

    def status(self, fid, revision, phase, message, **names):
        with self.connection() as conn:
            previous = conn.execute("SELECT payload FROM faction_discord_status WHERE faction_id=?", (fid,)).fetchone()
            last_sync = json.loads(previous[0]).get("lastSyncAt", 0) if previous else 0
            item = {"id": fid, "revision": revision, "phase": phase, "message": message,
                    "lastSyncAt": int(time.time()) if phase == "synced" else last_sync, **names}
            conn.execute("INSERT OR REPLACE INTO faction_discord_status VALUES(?,?)",
                         (fid, json.dumps(item, ensure_ascii=False)))

    def statuses(self):
        with self.connection() as conn:
            result = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM faction_discord_status ORDER BY faction_id LIMIT 128")]
        for row in result:
            if row.get("lastSyncAt") == 0:
                row.pop("lastSyncAt", None)
        return result

    def retry_ready(self, job):
        with self.connection() as conn:
            row = conn.execute("SELECT attempts,next_at FROM faction_discord_retry WHERE job=?", (job,)).fetchone()
        return row is None or (row[0] < 8 and row[1] <= time.time())

    def failed(self, job, code):
        with self.connection() as conn:
            row = conn.execute("SELECT attempts FROM faction_discord_retry WHERE job=?", (job,)).fetchone()
            attempts = (row[0] if row else 0) + 1
            conn.execute("INSERT OR REPLACE INTO faction_discord_retry VALUES(?,?,?,?)",
                         (job, attempts, time.time() + min(900, 5 * 2 ** min(attempts, 8)), code))

    def succeeded(self, job):
        with self.connection() as conn:
            conn.execute("DELETE FROM faction_discord_retry WHERE job=?", (job,))

    def defer(self, job, code, seconds=300):
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO faction_discord_retry VALUES(?,0,?,?)", (job, time.time() + seconds, code))

    def pause(self, value=None):
        with self.connection() as conn:
            if value is not None:
                conn.execute("INSERT OR REPLACE INTO faction_discord_control VALUES(1,?)", (int(value),))
            row = conn.execute("SELECT paused FROM faction_discord_control WHERE singleton=1").fetchone()
        return bool(row and row[0])

    def bind(self, guild_id):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT guild_id FROM faction_discord_binding WHERE singleton=1").fetchone()
            if row and row[0] != str(guild_id):
                raise Refused("persistent_guild_binding_mismatch")
            conn.execute("INSERT OR IGNORE INTO faction_discord_binding VALUES(1,?)", (str(guild_id),))

    def retry_reset(self):
        with self.connection() as conn:
            conn.execute("DELETE FROM faction_discord_retry")


def active(faction):
    return faction["enabled"] and not faction["deleted"] and faction["config"]["mode"] != "off"


def failure_code(exc):
    if getattr(exc, "request_not_sent", False):
        return str(exc)[:120]
    if getattr(exc, "definitive_rejection", False):
        return "discord_create_rejected_" + str(getattr(exc, "status", "unknown"))
    return type(exc).__name__


def profile_gate(profile_id, profiles):
    profile = profiles.items.get(profile_id)
    if profile_id not in ("dev", "live"):
        return "explicit_dev_or_live_profile_required"
    if profile is None or not profile.enabled or not profile.guild_id:
        return "profile_not_bound"
    # Dev must use a separate Discord server, even if the other bridge is quiet.
    if any(other.id != profile_id and other.id != "legacy" and other.guild_id == profile.guild_id
           for other in profiles.items.values() if other.guild_id):
        return "guild_shared_between_profiles"
    policy = profiles.raw.get(profile_id, {}).get("faction_discord", {})
    if not isinstance(policy, dict) or policy.get("enabled", True) is not True:
        return "discord_admin_activation_required"
    return None


def management_role_ids(profile_id, policy):
    """Trusted bot configuration only; a renamed role keeps its exact ID."""
    if not isinstance(policy, dict):
        raise Refused("management_policy_invalid")
    values = policy.get("management_role_ids", [DEFAULT_LIVE_MANAGEMENT_ROLE_ID] if profile_id == "live" else [])
    if not isinstance(values, list) or len(values) > 32:
        raise Refused("management_policy_invalid")
    checked = [snowflake(value) for value in values]
    if len(checked) != len(set(checked)):
        raise Refused("management_policy_invalid")
    return tuple(sorted(checked))


def normalized_policy(profile_id, policy):
    ids = management_role_ids(profile_id, policy)
    result = deepcopy(policy)
    result["management_role_ids"] = list(ids)
    return result


def management_roles(guild, policy):
    result = []
    for did in policy["management_role_ids"]:
        role = guild.get_role(int(did))
        if (not isinstance(role, discord.Role) or role.is_default() or role.managed
                or role not in guild.roles):
            raise Refused("management_role_unavailable")
        result.append(role)
    return result


def safe_role(role, guild, policy, protected, owned=False):
    if role is None or role.is_default() or role.managed or role >= guild.me.top_role:
        return False
    # Management roles are never faction membership grants, even when a caller
    # holds an unnormalized raw policy or this ID was once owned by a faction.
    management = {DEFAULT_LIVE_MANAGEMENT_ROLE_ID, *policy.get("management_role_ids", [])}
    if str(role.id) in management or str(role.id) in protected or str(role.id) in policy.get("protected_role_ids", []):
        return False
    if any(getattr(role.permissions, name, False) for name in ELEVATED):
        return False
    return owned or str(role.id) in policy.get("allow_existing_role_ids", [])


def private_overwrites(guild, role=None, management=(), archived=False):
    result = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
            read_message_history=True, connect=True, speak=True, manage_channels=True),
    }
    for manager in management:
        result[manager] = discord.PermissionOverwrite(view_channel=True, send_messages=not archived,
            read_message_history=True, connect=not archived, speak=not archived)
    if role is not None:
        result[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
            read_message_history=True, connect=True, speak=True)
    return result


class Coordinator:
    """One bounded worker; tests inject a fake Cog/Discord client and temporary DB."""
    def __init__(self, cog):
        self.cog = cog
        self.stores = {}
        self.catalogs = {}
        self.turn = 0
        self.fresh = {}  # Never restored from disk: every bot start needs a healthy full roster.
        self.checked = {}
        self.sync_locks = {}
        self.store_locks = {}
        self.transport = getattr(cog, "faction_discord_transport", None) or SingleAttemptCreates(cog.bot)

    def roster_fresh(self, pid):
        return pid in self.fresh and time.monotonic() - self.fresh[pid] <= 120

    async def store(self, pid):
        from . import db
        with db.profile_scope(pid):
            path = db.current_db_path()
        async with self.store_locks.setdefault(pid, asyncio.Lock()):
            if pid not in self.stores:
                value = Store(path)
                await asyncio.to_thread(value.init)
                self.stores[pid] = value
            elif self.stores[pid].path != path:
                raise Refused("profile_database_changed")
        return self.stores[pid]

    async def policy(self, pid):
        reason = profile_gate(pid, self.cog.profiles)
        if reason:
            raise Refused(reason)
        profile = self.cog.profiles.items[pid]
        guild = self.cog.bot.get_guild(int(profile.guild_id))
        if guild is None or guild.me is None:
            raise Refused("discord_guild_unavailable")
        if not guild.me.guild_permissions.manage_roles or not guild.me.guild_permissions.manage_channels:
            raise Refused("bot_permissions_missing")
        raw_policy = deepcopy(self.cog.profiles.raw.get(pid, {}).get("faction_discord", {}))
        policy = normalized_policy(pid, raw_policy)
        management_roles(guild, policy)  # Missing configured IDs pause; never infer by name.
        store = await self.store(pid)
        await asyncio.to_thread(store.bind, guild.id)
        mapping = await self.cog.config.guild(guild).role_map()
        if profile_gate(pid, self.cog.profiles) is not None or self.cog.profiles.raw.get(pid, {}).get("faction_discord", {}) != raw_policy:
            raise Refused("trusted_policy_changed")
        if self.cog.profiles.items[pid].guild_id != str(guild.id):
            raise Refused("trusted_guild_changed")
        protected = set(mapping) if isinstance(mapping, dict) else set()
        management_roles(guild, policy)
        return guild, policy, protected

    def channel_overwrites(self, pid, guild, role=None, archived=False):
        # No await between this fresh policy read and constructing the request.
        if profile_gate(pid, self.cog.profiles) is not None or self.cog.profiles.items[pid].guild_id != str(guild.id):
            raise Refused("trusted_policy_changed")
        policy = normalized_policy(pid, self.cog.profiles.raw.get(pid, {}).get("faction_discord", {}))
        managers = management_roles(guild, policy)
        if role is not None and str(role.id) in policy["management_role_ids"]:
            raise Refused("management_role_not_faction_role")
        return private_overwrites(guild, role, managers, archived)

    async def sync(self, pid, payload=None):
        async with self.sync_locks.setdefault(pid, asyncio.Lock()):
            return await self._sync(pid, payload)

    async def _sync(self, pid, payload=None):
        store = await self.store(pid)
        error = None
        if payload is not None:
            try:
                await asyncio.to_thread(store.accept, payload)
                await asyncio.to_thread(store.pause, False)
                self.fresh[pid] = time.monotonic()
            except Refused as exc:
                error = str(exc)
                await asyncio.to_thread(store.pause, True)
        snapshot = await asyncio.to_thread(store.snapshot)
        gate = profile_gate(pid, self.cog.profiles)
        statuses = await asyncio.to_thread(store.statuses)
        revisions = {row["id"]: row["config"]["revision"] for row in snapshot["factions"]} if snapshot else {}
        statuses = [row for row in statuses if revisions.get(row["id"]) == row["revision"]]
        cached = self.catalogs.get(pid, {})
        if gate is None:
            try:
                guild, policy, protected = await self.policy(pid)
                allowed_roles = {str(role.id) for role in guild.roles if safe_role(role, guild, policy, protected)}
                allowed_categories = set(policy.get("allow_category_ids", []))
                cached = {"data": {
                    "roles": [row for row in cached.get("data", {}).get("roles", []) if row["id"] in allowed_roles],
                    "categories": [row for row in cached.get("data", {}).get("categories", []) if row["id"] in allowed_categories],
                }}
            except Refused as exc:
                gate = str(exc)
        paused = await asyncio.to_thread(store.pause)
        fresh = self.roster_fresh(pid)
        result = {"schema": 1, "profile": pid, "ready": gate is None and not paused and fresh,
                  "needSnapshot": snapshot is None or paused or not fresh,
                  "catalog": cached.get("data", {"roles": [], "categories": []}) if gate is None else {"roles": [], "categories": []},
                  "statuses": statuses, "code": error or gate or ("accepted" if fresh else "fresh_snapshot_required")}
        if snapshot:
            result["acceptedGeneration"] = snapshot["generation"]
        return result

    async def loop(self):
        await self.cog.bot.wait_until_ready()
        await self.cog._settings_ready.wait()
        while not self.cog._closing:
            for pid in ("live", "dev"):
                if pid not in self.cog.profiles.items:
                    continue
                try:
                    await self.tick(pid)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # No raw Discord response, member identity or key in logs.
                    self.cog.faction_discord_log(pid, type(exc).__name__)
            await asyncio.sleep(5)

    async def refresh_catalog(self, pid, guild, policy, protected):
        cached = self.catalogs.get(pid, {})
        if time.time() - cached.get("at", 0) < 60:
            return
        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles
                 if safe_role(role, guild, policy, protected)]
        categories = [{"id": str(channel.id), "name": channel.name} for channel in guild.categories
                      if str(channel.id) in policy.get("allow_category_ids", [])]
        self.catalogs[pid] = {"at": time.time(), "data": {"roles": roles[:128], "categories": categories[:100]}}

    async def current(self, pid, store, faction=None):
        context = await self.policy(pid)
        if not self.roster_fresh(pid):
            raise Refused("fresh_snapshot_required")
        if not self.transport.available():
            raise Refused("discord_rate_wait")
        if await asyncio.to_thread(store.pause):
            raise Refused("complete_snapshot_required")
        latest = await asyncio.to_thread(store.snapshot)
        if latest is None:
            raise Refused("snapshot_missing")
        if faction:
            row = next((item for item in latest["factions"] if item["id"] == faction["id"]), None)
            if row != faction:
                raise Refused("desired_state_changed")
        guild, policy, _ = context
        # A mutable configuration can change during the final SQLite awaits.
        if (profile_gate(pid, self.cog.profiles) is not None
                or self.cog.profiles.items[pid].guild_id != str(guild.id)
                or normalized_policy(pid, self.cog.profiles.raw.get(pid, {}).get("faction_discord", {})) != policy):
            raise Refused("trusted_policy_changed")
        management_roles(guild, policy)
        return context, latest

    async def create(self, pid, store, faction, kind, operation, budget, check_faction=None):
        fid = faction["id"] if faction else 0
        expected = check_faction or faction
        row = await asyncio.to_thread(store.resource, fid, kind)
        if kind == "role" and await asyncio.to_thread(store.deletion, fid):
            raise Refused("role_dissolution_recorded_no_recreation")
        if row:
            if row["phase"] not in ("ready", "retryable"):
                raise Refused(row["note"] or "create_result_unknown")
            if row["phase"] == "ready":
                return row["discord_id"]
        if budget[0] <= 0:
            raise Refused("pending_budget")
        budget[0] -= 1
        await self.current(pid, store, expected)
        await asyncio.to_thread(store.put_resource, fid, kind, None, "creating")
        try:
            await self.current(pid, store, expected)
        except Refused:
            # The external call has not begun; this intent is safe to retry later.
            await asyncio.to_thread(store.put_resource, fid, kind, None, "retryable", "precall_cancelled")
            raise
        result = None
        try:
            result = await operation()
            await asyncio.to_thread(store.put_resource, fid, kind, result.id, "ready")
            return str(result.id)
        except BaseException as exc:
            # Includes process cancellation. A create may already have reached Discord.
            rejected = (isinstance(exc, discord.HTTPException) or getattr(exc, "definitive_rejection", False)) and getattr(exc, "status", 0) in (400, 401, 403, 404, 405, 413, 422, 429)
            rejected = rejected or getattr(exc, "request_not_sent", False)
            await asyncio.shield(asyncio.to_thread(store.put_resource, fid, kind, getattr(result, "id", None),
                "retryable" if rejected else "held",
                "discord_request_rejected" if rejected else "create_result_unknown"))
            raise

    async def role(self, pid, store, faction, budget):
        (guild, policy, protected), _ = await self.current(pid, store, faction)
        cfg = faction["config"]
        owned = cfg["mode"] == "auto"
        if owned:
            did = await self.create(pid, store, faction, "role", lambda: self.transport.role(guild, faction["label"]), budget)
        else:
            did = cfg["roleId"]
        (guild, policy, protected), _ = await self.current(pid, store, faction)
        role = guild.get_role(int(did))
        if not safe_role(role, guild, policy, protected, owned=owned):
            raise Refused("role_missing_protected_or_not_allowed")
        if owned and role.name != faction["label"]:
            if budget[0] <= 0:
                raise Refused("pending_budget")
            budget[0] -= 1
            (guild, policy, protected), _ = await self.current(pid, store, faction)
            role = guild.get_role(int(did))
            if not safe_role(role, guild, policy, protected, owned=owned):
                raise Refused("role_missing_protected_or_not_allowed")
            await role.edit(name=faction["label"], reason="DNP Fraktion umbenannt")
        return role

    async def channels(self, pid, store, faction, role, budget):
        (guild, policy, _), _ = await self.current(pid, store, faction)
        cfg = faction["config"]
        category = None
        if cfg["textEnabled"] or cfg["voiceEnabled"]:
            if cfg["categoryMode"] == "existing":
                if cfg["categoryId"] not in policy.get("allow_category_ids", []):
                    raise Refused("category_not_allowed")
                category = guild.get_channel(int(cfg["categoryId"]))
                if not isinstance(category, discord.CategoryChannel):
                    raise Refused("category_missing")
            else:
                did = await self.create(pid, store, None, "category", lambda: self.transport.channel(
                    guild, "category", "DNP · Fraktionen", self.channel_overwrites(pid, guild)), budget, check_faction=faction)
                category = guild.get_channel(int(did))
                if not isinstance(category, discord.CategoryChannel):
                    raise Refused("owned_category_missing")
                desired = self.channel_overwrites(pid, guild)
                if category.overwrites != desired:
                    if budget[0] <= 0:
                        raise Refused("pending_budget")
                    budget[0] -= 1
                    await self.current(pid, store, faction)
                    await category.edit(overwrites=self.channel_overwrites(pid, guild),
                        reason="DNP Fraktionskategorie: Verwaltung aktualisiert")
        names = {}
        for kind, enabled in (("text", cfg["textEnabled"]), ("voice", cfg["voiceEnabled"])):
            row = await asyncio.to_thread(store.resource, faction["id"], kind)
            if not row and not enabled:
                continue
            name = (re.sub(r"[^\wäöüß-]+", "-", faction["label"].lower()).strip("-") or "fraktion")[:80]
            if kind == "voice":
                name = faction["label"][:80]
            if not row or row["phase"] != "ready":
                await self.create(pid, store, faction, kind, lambda: self.transport.channel(
                    guild, kind, name, self.channel_overwrites(pid, guild, role), category), budget)
                row = await asyncio.to_thread(store.resource, faction["id"], kind)
            channel = guild.get_channel(int(row["discord_id"])) if row["discord_id"] else None
            expected_type = discord.TextChannel if kind == "text" else discord.VoiceChannel
            if not isinstance(channel, expected_type):
                raise Refused(row["note"] or "owned_channel_missing")
            overwrites = self.channel_overwrites(pid, guild, role if enabled else None, archived=not enabled)
            desired_name = name if enabled else ("archiv-" + name)[:95]
            # Explicit full replacement defeats unsafe inherited/category overwrites.
            changes = channel.overwrites != overwrites or channel.name != desired_name
            if enabled and channel.category_id != category.id:
                changes = True
            if changes:
                if budget[0] <= 0:
                    raise Refused("pending_budget")
                budget[0] -= 1
                await self.current(pid, store, faction)
                kwargs = {"name": desired_name, "overwrites": self.channel_overwrites(pid, guild, role if enabled else None, archived=not enabled),
                          "reason": "DNP Fraktionszugang aktualisiert"}
                if enabled:
                    kwargs.update(category=category, sync_permissions=False)
                await channel.edit(**kwargs)
            names[kind + "Name"] = desired_name
        return names

    async def archive(self, pid, store, faction, budget):
        (guild, _, _), _ = await self.current(pid, store)
        own_category = await asyncio.to_thread(store.resource, 0, "category")
        if own_category and own_category["phase"] == "ready" and own_category["discord_id"]:
            category = guild.get_channel(int(own_category["discord_id"]))
            if isinstance(category, discord.CategoryChannel) and category.overwrites != self.channel_overwrites(pid, guild):
                if budget[0] <= 0:
                    raise Refused("pending_budget")
                budget[0] -= 1
                await self.current(pid, store)
                await category.edit(overwrites=self.channel_overwrites(pid, guild),
                    reason="DNP Fraktionskategorie: Verwaltung aktualisiert")
        for kind in ("text", "voice"):
            row = await asyncio.to_thread(store.resource, faction["id"], kind)
            if not row or not row["discord_id"]:
                continue
            channel = guild.get_channel(int(row["discord_id"]))
            if channel is None:
                continue  # Never recreate a deleted/disabled channel.
            overwrites = self.channel_overwrites(pid, guild, archived=True)
            name = channel.name if channel.name.startswith("archiv-") else ("archiv-" + channel.name)[:95]
            if channel.overwrites != overwrites or channel.name != name:
                if budget[0] <= 0:
                    raise Refused("pending_budget")
                budget[0] -= 1
                _, latest = await self.current(pid, store)
                current = next((row for row in latest["factions"] if row["id"] == faction["id"]), None)
                if current and active(current):
                    raise Refused("desired_state_changed")
                await channel.edit(name=name, overwrites=self.channel_overwrites(pid, guild, archived=True),
                    reason="DNP Fraktion deaktiviert; Historie bleibt")

    @staticmethod
    def deletion_referenced(latest, registry, fid, rid):
        # Off/disabled factions still own their configured associations.
        live = {row["id"] for row in latest["factions"] if not row["deleted"]}
        dissolved = {row["id"] for row in latest["factions"] if row["deleted"] is True}
        for row in latest["factions"]:
            if row["id"] != fid and row["id"] in live and row["config"].get("roleId") == rid:
                return True
        # A missing other owner is unconfirmed, not proof its reference ended.
        return any(row["faction_id"] != fid and row["faction_id"] not in dissolved
                   and row["kind"] == "role" and row["discord_id"] == rid for row in registry)

    async def deletion_context(self, pid, store, faction, rid):
        if faction.get("deleted") is not True:
            raise Refused("explicit_dissolution_required")
        registry = await asyncio.to_thread(store.resources)
        context, latest = await self.current(pid, store, faction)
        if self.deletion_referenced(latest, registry, faction["id"], rid):
            raise Refused("role_referenced_by_other_faction")
        return context, latest

    @staticmethod
    def confirmed_role_list(guild, fetched):
        if not isinstance(fetched, list) or len(fetched) > 1000 or any(not isinstance(r, discord.Role) for r in fetched):
            raise Refused("role_rest_observation_unconfirmed")
        if len({r.id for r in fetched}) != len(fetched):
            raise Refused("role_rest_observation_unconfirmed")
        if not any(r.id == guild.id and r.is_default() for r in fetched):
            raise Refused("role_rest_observation_unconfirmed")
        return fetched

    async def dissolve_role(self, pid, store, faction, budget):
        # Absence, mode=off and enabled=false alone are never dissolution proof.
        if faction.get("deleted") is not True:
            return False
        fid = faction["id"]
        row = await asyncio.to_thread(store.resource, fid, "role")
        if row is None:
            return False  # A selected existing role was never owned by this integration.
        rid = row["discord_id"]
        if not rid or row["phase"] not in ("ready", "held"):
            raise Refused("owned_role_creation_unconfirmed")
        snowflake(rid)
        (guild, policy, protected), latest = await self.deletion_context(pid, store, faction, rid)
        intent = await asyncio.to_thread(store.deletion, fid)
        if intent and intent["role_id"] != rid:
            raise Refused("deletion_role_identity_changed")
        if intent and intent["phase"] == "complete":
            await asyncio.to_thread(store.drop_deleted_role_grants, rid)
            return True
        if budget[0] <= 0:
            raise Refused("pending_budget")
        budget[0] -= 1
        # Cache absence is not proof. Fetch the exact guild's current role list.
        fetched = self.confirmed_role_list(guild, await guild.fetch_roles())
        (guild, policy, protected), latest = await self.deletion_context(pid, store, faction, rid)
        role = next((r for r in fetched if str(r.id) == rid), None)
        if role is None:
            await asyncio.to_thread(store.put_deletion, fid, rid, "complete", latest["generation"], "rest_absence_confirmed")
            await asyncio.to_thread(store.drop_deleted_role_grants, rid)
            return True
        if not safe_role(role, guild, policy, protected, owned=True) or role.permissions.value != 0:
            raise Refused("owned_role_changed_or_protected")
        if budget[0] <= 0:
            raise Refused("pending_budget")
        await asyncio.to_thread(store.put_deletion, fid, rid, "deleting", latest["generation"])
        try:
            (guild, policy, protected), latest = await self.deletion_context(pid, store, faction, rid)
            cached = guild.get_role(int(rid))
            if not safe_role(role, guild, policy, protected, owned=True) or role.permissions.value != 0:
                raise Refused("owned_role_changed_or_protected")
            if cached is not None and (not safe_role(cached, guild, policy, protected, owned=True) or cached.permissions.value != 0):
                raise Refused("owned_role_changed_or_protected")
        except Refused:
            # No DELETE has begun, so this intent can safely be reconsidered.
            await asyncio.to_thread(store.put_deletion, fid, rid, "pending", latest["generation"], "precall_cancelled")
            raise
        budget[0] -= 1
        try:
            await role.delete(reason="DNP Fraktion vollständig aufgelöst; eigene Rolle")
        except discord.NotFound:
            # 404 can also mean the guild became unavailable. Confirm the role's
            # absence in a fresh complete list before declaring this deletion done.
            await asyncio.to_thread(store.put_deletion, fid, rid, "uncertain", latest["generation"], "delete_404_requires_rest_confirmation")
            try:
                (guild, _, _), latest = await self.deletion_context(pid, store, faction, rid)
                if budget[0] <= 0:
                    raise Refused("pending_budget")
                budget[0] -= 1
                observed = self.confirmed_role_list(guild, await guild.fetch_roles())
                _, latest = await self.deletion_context(pid, store, faction, rid)
                if any(str(item.id) == rid for item in observed):
                    raise Refused("delete_404_role_still_observed")
            except BaseException:
                await asyncio.shield(asyncio.to_thread(store.put_deletion, fid, rid, "uncertain", latest["generation"], "delete_404_unconfirmed"))
                raise
        except BaseException:
            await asyncio.shield(asyncio.to_thread(store.put_deletion, fid, rid, "uncertain", latest["generation"], "delete_result_unknown"))
            raise
        await asyncio.to_thread(store.put_deletion, fid, rid, "complete", latest["generation"], "delete_confirmed")
        await asyncio.to_thread(store.drop_deleted_role_grants, rid)
        return True

    async def tick(self, pid):
        if not self.roster_fresh(pid):
            return
        try:
            guild, policy, protected = await self.policy(pid)
        except Refused:
            self.catalogs.pop(pid, None)
            return
        store = await self.store(pid)
        if await asyncio.to_thread(store.pause):
            return
        snapshot = await asyncio.to_thread(store.snapshot)
        await self.refresh_catalog(pid, guild, policy, protected)
        if not snapshot:
            return
        budget = [12]
        roles = {}
        factions = snapshot["factions"]
        explicit_deleted = {row["id"] for row in factions if row["deleted"] is True}
        known = {row["id"] for row in factions}
        missing = {row["faction_id"] for row in await asyncio.to_thread(store.resources)} - known - {0}
        for fid in sorted(missing):
            factions = factions + [{"id": fid, "config": {"revision": 0}, "enabled": False, "deleted": True}]
        # Round-robin prevents a large broken first faction starving later entries.
        if factions:
            offset = self.turn % len(factions)
            factions = factions[offset:] + factions[:offset]
        self.turn += 1
        for faction in factions:
            if budget[0] <= 0:
                break
            fid, rev = faction["id"], faction["config"]["revision"]
            job = "faction:%s:%s" % (fid, rev)
            if not await asyncio.to_thread(store.retry_ready, job):
                continue
            try:
                if active(faction):
                    role = await self.role(pid, store, faction, budget)
                    roles[fid] = role
                    names = await self.channels(pid, store, faction, role, budget)
                    await asyncio.to_thread(store.status, fid, rev, "ready", "Bereit", roleName=role.name, **names)
                else:
                    await self.archive(pid, store, faction, budget)
                    if fid in explicit_deleted:
                        removed = await self.dissolve_role(pid, store, faction, budget)
                        await asyncio.to_thread(store.status, fid, rev, "deleted" if removed else "off",
                            "Fraktion aufgelöst; eigene Rolle gelöscht, Kanalhistorie archiviert" if removed else
                            "Fraktion aufgelöst; vorhandene zugeordnete Rolle bleibt erhalten, Kanäle archiviert")
                    else:
                        await asyncio.to_thread(store.status, fid, rev, "off", "Deaktiviert; Rolle und Kanalhistorie bleiben erhalten")
                await asyncio.to_thread(store.succeeded, job)
            except Refused as exc:
                code = str(exc)
                await asyncio.to_thread(store.status, fid, rev, "pending" if code == "pending_budget" else "held", code)
                if code not in ("pending_budget", "desired_state_changed"):
                    await asyncio.to_thread(store.failed, job, code)
            except Exception as exc:
                code = failure_code(exc)
                await asyncio.to_thread(store.status, fid, rev, "error", code)
                await asyncio.to_thread(store.failed, job, code)
        registry = await asyncio.to_thread(store.resources)
        bindings = {}
        for faction in snapshot["factions"]:
            if not active(faction):
                continue
            cfg = faction["config"]
            if cfg["mode"] == "existing":
                bindings[faction["id"]] = cfg["roleId"]
            else:
                item = next((row for row in registry if row["faction_id"] == faction["id"] and row["kind"] == "role"), None)
                if item and item["discord_id"]:
                    bindings[faction["id"]] = item["discord_id"]
        targets, grantable = set(), set()
        for member in snapshot["memberships"]:
            for fid in member["factionIds"]:
                if fid in bindings:
                    targets.add((bindings[fid], member["discordId"]))
                if fid in roles:
                    grantable.add((str(roles[fid].id), member["discordId"]))
        # A role appearing twice is one union: leaving one faction cannot revoke it.
        tracked = await asyncio.to_thread(store.grants)
        changes = sorted(grantable | tracked)
        if self.checked.get(pid, {}).get("generation") != snapshot["generation"]:
            self.checked[pid] = {"generation": snapshot["generation"], "pairs": set()}
        checked = self.checked[pid]["pairs"]
        if changes:
            offset = (self.turn * 8) % len(changes)
            changes = changes[offset:] + changes[:offset]
        for rid, uid in changes[:32]:
            if budget[0] <= 0:
                break
            checked.discard((rid, uid))
            job = "member:%s:%s:%s" % (snapshot["generation"], rid, uid)
            if not await asyncio.to_thread(store.retry_ready, job):
                continue
            try:
                (guild, policy, protected), latest = await self.current(pid, store)
                if latest["generation"] != snapshot["generation"]:
                    return  # Never finish a previous roster after newer acceptance.
                owned = any(row["kind"] == "role" and row["discord_id"] == rid for row in registry)
                role = guild.get_role(int(rid))
                if not safe_role(role, guild, policy, protected, owned):
                    raise Refused("tracked_role_now_protected")
                member = guild.get_member(int(uid))
                if member is None:
                    budget[0] -= 1
                    try:
                        member = await guild.fetch_member(int(uid))
                    except discord.NotFound:
                        # Leaving Discord is not proof of leaving the in-game faction.
                        await asyncio.to_thread(store.defer, job, "discord_member_unavailable")
                        continue
                (guild, policy, protected), latest = await self.current(pid, store)
                if latest["generation"] != snapshot["generation"]:
                    return
                if not safe_role(role, guild, policy, protected, owned):
                    raise Refused("tracked_role_now_protected")
                wanted = (rid, uid) in targets
                has_role = any(str(row.id) == rid for row in member.roles)
                if wanted and not has_role:
                    if budget[0] <= 0:
                        break
                    budget[0] -= 1
                    await asyncio.to_thread(store.grant, rid, uid, True)
                    (guild, policy, protected), latest = await self.current(pid, store)
                    if latest["generation"] != snapshot["generation"]:
                        return
                    role = guild.get_role(int(rid))
                    if not safe_role(role, guild, policy, protected, owned):
                        raise Refused("tracked_role_now_protected")
                    await member.add_roles(role, atomic=True, reason="DNP bestätigte Fraktionsmitgliedschaft")
                elif not wanted and has_role:
                    if budget[0] <= 0:
                        break
                    budget[0] -= 1
                    await member.remove_roles(role, atomic=True, reason="DNP Fraktionsmitgliedschaft beendet")
                # An explicitly selected+allowlisted existing role is authoritative
                # for CURRENT canonical members, even if manually assigned before.
                # Unrelated manual recipients never enter targets or this registry.
                await asyncio.to_thread(store.grant, rid, uid, wanted)
                checked.add((rid, uid))
                await asyncio.to_thread(store.succeeded, job)
            except Refused as exc:
                await asyncio.to_thread(store.failed, job, str(exc))
            except Exception as exc:
                await asyncio.to_thread(store.failed, job, failure_code(exc))
        try:
            _, latest = await self.current(pid, store)
        except Refused:
            return
        if latest["generation"] != snapshot["generation"]:
            return
        remaining = (await asyncio.to_thread(store.grants)) - targets
        current_statuses = {row["id"]: row for row in await asyncio.to_thread(store.statuses)}
        for faction in snapshot["factions"]:
            fid, revision = faction["id"], faction["config"]["revision"]
            status = current_statuses.get(fid, {})
            if fid not in bindings or status.get("revision") != revision or status.get("phase") not in ("ready", "synced"):
                continue
            rid = bindings[fid]
            wanted = {pair for pair in targets if pair[0] == rid}
            complete = wanted <= checked and not any(pair[0] == rid for pair in remaining)
            names = {key: status[key] for key in ("roleName", "textName", "voiceName") if key in status}
            await asyncio.to_thread(store.status, fid, revision, "synced" if complete else "pending",
                "Abgeglichen" if complete else "Mitgliedschaften werden abgeglichen", **names)

