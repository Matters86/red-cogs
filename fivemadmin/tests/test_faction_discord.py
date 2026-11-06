"""Offline regression tests: no Red runtime, Discord client or production DB used."""
import asyncio
import contextlib
import contextvars
import importlib.util
import sys
import tempfile
import selectors
import types
import unittest
from copy import deepcopy
from pathlib import Path


# Windows' restricted test environment blocks loopback socketpair creation.
# This test-only loop needs no sockets: all Discord operations are in-memory,
# and artificial SQLite calls run inline rather than through a thread wake pipe.
class NoIOSelector(selectors.SelectSelector):
    def select(self, timeout=None):
        return []


class OfflineLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        super().__init__(selector=NoIOSelector())
    def _make_self_pipe(self):
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        pass


class OfflinePolicy(asyncio.DefaultEventLoopPolicy):
    # IsolatedAsyncioTestCase.loop_factory is available only from Python 3.13.
    # The primary workspace runtime is 3.12; keep that runtime socket-free too.
    def new_event_loop(self):
        return OfflineLoop()


asyncio.set_event_loop_policy(OfflinePolicy())


async def inline_thread(function, *args, **kwargs):
    return function(*args, **kwargs)


asyncio.to_thread = inline_thread


class Permissions:
    def __init__(self, **flags):
        self.flags = flags
        self.value = 0 if not any(flags.values()) else 1

    def __getattr__(self, name):
        return self.flags.get(name, False)

    @classmethod
    def none(cls):
        return cls()


class Overwrite:
    def __init__(self, **flags):
        self.flags = flags

    def __eq__(self, other):
        return isinstance(other, Overwrite) and self.flags == other.flags


class HTTPException(Exception):
    def __init__(self, status=500):
        self.status = status


class NotFound(HTTPException):
    pass


class Role:
    def __init__(self, did, name, position=1, **permissions):
        self.id, self.name, self.position = did, name, position
        self.permissions = Permissions(**permissions)
        self.managed = False
        self.default = False
        self.edits = []
        self.guild = None
        self.deletes = []
        self.delete_error = None
        self.delete_hook = None

    def is_default(self):
        return self.default

    def __ge__(self, other):
        return self.position >= other.position

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        self.name = kwargs.get("name", self.name)

    async def delete(self, **kwargs):
        self.deletes.append(kwargs)
        if self.delete_hook:
            await self.delete_hook()
        if self.delete_error == "before":
            raise TimeoutError("artificial deletion response unknown")
        if self.delete_error == "forbidden":
            raise HTTPException(403)
        if self.delete_error == "notfound":
            raise NotFound(404)
        if self.guild:
            self.guild.roles = [row for row in self.guild.roles if row.id != self.id]
            for member in self.guild.members.values():
                member.roles = [row for row in member.roles if row.id != self.id]
        if self.delete_error == "after":
            raise TimeoutError("artificial post-deletion timeout")
        if self.delete_error == "notfound_after":
            raise NotFound(404)


class Channel:
    def __init__(self, did, name, category=None, overwrites=None, **kwargs):
        self.id, self.name = did, name
        self.category_id = category.id if category else None
        self.overwrites = overwrites or {}
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        self.name = kwargs.get("name", self.name)
        self.overwrites = kwargs.get("overwrites", self.overwrites)
        if "category" in kwargs:
            self.category_id = kwargs["category"].id


class TextChannel(Channel):
    pass


class VoiceChannel(Channel):
    pass


class CategoryChannel(Channel):
    pass


class Member:
    def __init__(self, did):
        self.id, self.roles, self.calls = did, [], []
        self.after_add = None

    async def add_roles(self, role, **kwargs):
        self.calls.append(("add", role.id))
        if role not in self.roles:
            self.roles.append(role)
        if self.after_add:
            await self.after_add()

    async def remove_roles(self, role, **kwargs):
        self.calls.append(("remove", role.id))
        self.roles = [item for item in self.roles if item.id != role.id]


class Guild:
    def __init__(self, did=10000000000900000):
        self.id, self.serial, self.create_calls = did, 100000000001000000, []
        self.default_role = Role(did, "@everyone", position=0)
        self.default_role.default = True
        self.me = Member(10000000000900001)
        self.me.top_role = Role(10000000000900002, "Bot", position=100)
        self.me.guild_permissions = Permissions(manage_roles=True, manage_channels=True)
        self.roles, self.channels, self.members = [self.default_role], [], {}
        self.raise_create = None
        self.raise_channel = None
        self.fetch_hook = None
        self.fetches = 0
        self.role_fetches = 0
        self.role_fetch_hook = None
        self.hidden_role_ids = set()

    @property
    def categories(self):
        return [item for item in self.channels if isinstance(item, CategoryChannel)]

    def get_role(self, did):
        if did in self.hidden_role_ids:
            return None
        return next((role for role in self.roles if role.id == did), None)

    async def fetch_roles(self):
        self.role_fetches += 1
        if self.role_fetch_hook:
            await self.role_fetch_hook()
        return list(self.roles)

    def get_channel(self, did):
        return next((channel for channel in self.channels if channel.id == did), None)

    def get_member(self, did):
        return self.members.get(did)

    async def fetch_member(self, did):
        self.fetches += 1
        if self.fetch_hook:
            return await self.fetch_hook(did)
        raise NotFound(404)

    async def create_role(self, **kwargs):
        self.create_calls.append(("role", kwargs))
        self.serial += 1
        if self.raise_create == "forbidden":
            raise HTTPException(403)
        role = Role(self.serial, kwargs["name"])
        role.guild = self
        self.roles.append(role)
        if self.raise_create == "timeout":
            raise TimeoutError("artificial post-create timeout")
        return role

    async def create_channel(self, cls, **kwargs):
        self.create_calls.append((cls.__name__, kwargs))
        self.serial += 1
        if self.raise_channel == cls.__name__:
            raise HTTPException(403)
        channel = cls(self.serial, **kwargs)
        self.channels.append(channel)
        return channel

    async def create_category(self, **kwargs):
        return await self.create_channel(CategoryChannel, **kwargs)

    async def create_text_channel(self, **kwargs):
        return await self.create_channel(TextChannel, **kwargs)

    async def create_voice_channel(self, **kwargs):
        return await self.create_channel(VoiceChannel, **kwargs)


class FakeCreates:
    def available(self):
        return True

    async def role(self, guild, name):
        return await guild.create_role(name=name, permissions=Permissions.none(), mentionable=False, hoist=False)

    async def channel(self, guild, kind, name, overwrites, category=None):
        methods = {"category": guild.create_category, "text": guild.create_text_channel, "voice": guild.create_voice_channel}
        return await methods[kind](name=name, category=category, overwrites=overwrites)


fake_discord = types.ModuleType("discord")
for name, item in {"Permissions": Permissions, "PermissionOverwrite": Overwrite,
                   "Role": Role,
                   "HTTPException": HTTPException, "NotFound": NotFound,
                   "TextChannel": TextChannel, "VoiceChannel": VoiceChannel,
                   "CategoryChannel": CategoryChannel}.items():
    setattr(fake_discord, name, item)
sys.modules["discord"] = fake_discord
package = types.ModuleType("fd_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[package.__name__] = package
scope = contextvars.ContextVar("artificial_profile")
fake_db = types.ModuleType("fd_test_package.db")


@contextlib.contextmanager
def profile_scope(pid):
    token = scope.set(pid)
    try:
        yield
    finally:
        scope.reset(token)


fake_db.profile_scope = profile_scope
sys.modules[fake_db.__name__] = fake_db
package.db = fake_db
spec = importlib.util.spec_from_file_location("fd_test_package.faction_discord",
    Path(__file__).resolve().parents[1] / "faction_discord.py")
fd = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fd
spec.loader.exec_module(fd)


def faction(fid=6, mode="auto", role=None, enabled=True, revision=1):
    return {"id": fid, "name": "police" + str(fid), "label": "LSPD " + str(fid),
            "category": "state", "enabled": enabled, "deleted": False,
            "config": {"revision": revision, "mode": mode, "roleId": role,
                       "textEnabled": True, "voiceEnabled": True,
                       "categoryMode": "auto", "categoryId": None,
                       "categoryName": "DNP · Fraktionen"}}


def snapshot(generation=1, factions=None, members=None):
    return {"schema": 1, "generation": generation, "complete": True,
            "factions": [faction()] if factions is None else factions,
            "memberships": [{"discordId": "10000000000800001", "factionIds": [6]}] if members is None else members}


class FakeConfig:
    def __init__(self):
        self.mapping = {}

    def guild(self, guild):
        return self

    async def role_map(self):
        return self.mapping


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    loop_factory = OfflineLoop
    async def asyncSetUp(self):
        self.test_root = Path(__file__).resolve().parent / ".artificial"
        self.test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.test_root)
        fake_db.current_db_path = lambda: Path(self.temp.name) / (scope.get() + ".sqlite3")
        self.guild = Guild()
        self.member = Member(10000000000800001)
        self.guild.members[self.member.id] = self.member
        self.policy = {"enabled": True, "allow_existing_role_ids": [], "allow_category_ids": [], "protected_role_ids": []}
        profiles = types.SimpleNamespace(
            items={"live": types.SimpleNamespace(id="live", guild_id=str(self.guild.id), enabled=True)},
            raw={"live": {"faction_discord": self.policy}})
        self.cog = types.SimpleNamespace(profiles=profiles, bot=types.SimpleNamespace(get_guild=lambda did: self.guild if did == self.guild.id else None),
                                         config=FakeConfig(), faction_discord_log=lambda *args: None,
                                         faction_discord_transport=FakeCreates())
        self.engine = fd.Coordinator(self.cog)
        self.store = await self.engine.store("live")

    async def asyncTearDown(self):
        self.assertEqual(Path(self.temp.name).resolve().parent, self.test_root)
        self.temp.cleanup()

    async def submit(self, value):
        return await self.engine.sync("live", value)

    async def test_auto_create_once_private_and_grant(self):
        self.assertTrue((await self.submit(snapshot()))["ready"])
        await self.engine.tick("live")
        await self.engine.tick("live")
        self.assertEqual(len(self.guild.create_calls), 4)
        self.assertEqual(len(self.member.calls), 1)
        role = self.member.roles[0]
        self.assertEqual(role.permissions.value, 0)
        self.assertFalse(self.guild.categories[0].overwrites[self.guild.default_role].flags["view_channel"])
        for channel in self.guild.channels:
            self.assertFalse(channel.overwrites[self.guild.default_role].flags["view_channel"])
            self.assertEqual(set(channel.overwrites), {self.guild.default_role, self.guild.me} if isinstance(channel, CategoryChannel)
                             else {self.guild.default_role, self.guild.me, role})
        result = await self.engine.sync("live")
        self.assertEqual(result["acceptedGeneration"], 1)
        self.assertEqual(result["statuses"][0]["phase"], "synced")
        self.assertGreater(result["statuses"][0]["lastSyncAt"], 0)

    async def test_complete_required_no_destructive_empty(self):
        await self.submit(snapshot())
        await self.engine.tick("live")
        calls = list(self.member.calls)
        result = await self.submit({"schema": 1, "complete": False, "code": "identity_unavailable"})
        self.assertFalse(result["ready"])
        self.assertTrue(result["needSnapshot"])
        await self.engine.tick("live")
        self.assertEqual(self.member.calls, calls)
        self.assertEqual(self.store.snapshot()["generation"], 1)
        await self.submit(snapshot(2, members=[]))
        await self.engine.tick("live")
        self.assertEqual(self.member.calls[-1][0], "remove")

    async def test_shared_role_union_and_no_mass_strip(self):
        role = Role(10000000000700001, "Taxi", position=3)
        self.guild.roles.append(role)
        self.policy["allow_existing_role_ids"] = [str(role.id)]
        other = Member(10000000000800002)
        other.roles.append(role)  # Unrelated manual assignment is not swept.
        self.guild.members[other.id] = other
        factions = [faction(6, "existing", str(role.id)), faction(7, "existing", str(role.id))]
        await self.submit(snapshot(factions=factions, members=[{"discordId": "10000000000800001", "factionIds": [6, 7]}]))
        await self.engine.tick("live")
        await self.submit(snapshot(2, factions=factions, members=[{"discordId": "10000000000800001", "factionIds": [7]}]))
        await self.engine.tick("live")
        self.assertEqual(self.member.calls, [("add", role.id)])
        await self.submit(snapshot(3, factions=factions, members=[]))
        await self.engine.tick("live")
        self.assertEqual(self.member.calls[-1], ("remove", role.id))
        self.assertIn(role, other.roles)

    async def test_selected_existing_role_adopted_for_current_member_and_removed_on_leave(self):
        role = Role(10000000000700001, "Existing manually assigned")
        self.guild.roles.append(role)
        self.member.roles.append(role)
        self.policy["allow_existing_role_ids"] = [str(role.id)]
        rows = [faction(6, "existing", str(role.id))]
        await self.submit(snapshot(factions=rows))
        await self.engine.tick("live")
        self.assertEqual(self.store.grants(), {(str(role.id), str(self.member.id))})
        await self.submit(snapshot(2, factions=rows, members=[]))
        await self.engine.tick("live")
        self.assertNotIn(role, self.member.roles)
        self.assertEqual(self.member.calls, [("remove", role.id)])

    async def test_disable_during_creation_intent_prevents_external_call(self):
        original = self.store.put_resource
        def changed(fid, kind, did, phase, note=""):
            original(fid, kind, did, phase, note)
            if phase == "creating":
                self.policy["enabled"] = False
        self.store.put_resource = changed
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(self.guild.create_calls, [])
        self.assertEqual(self.store.resource(6, "role")["phase"], "retryable")

    async def test_unknown_creation_held_through_restart(self):
        self.guild.raise_create = "timeout"
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(self.store.resource(6, "role")["phase"], "held")
        self.store.retry_reset()
        self.engine = fd.Coordinator(self.cog)
        await self.engine.tick("live")
        self.assertEqual(len(self.guild.create_calls), 1)
        self.assertEqual(len(self.guild.roles), 2)

    async def test_definitive_rejection_can_retry(self):
        self.guild.raise_create = "forbidden"
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(self.store.resource(6, "role")["phase"], "retryable")
        self.guild.raise_create = None
        self.store.retry_reset()
        await self.engine.tick("live")
        self.assertEqual(self.store.resource(6, "role")["phase"], "ready")
        self.assertEqual(len(self.member.roles), 1)

    async def test_definitive_channel_rejection_retries(self):
        self.guild.raise_channel = "TextChannel"
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(self.store.resource(6, "text")["phase"], "retryable")
        self.guild.raise_channel = None
        self.store.retry_reset()
        await self.engine.tick("live")
        self.assertEqual(self.store.resource(6, "text")["phase"], "ready")
        self.assertEqual(len(self.guild.channels), 3)

    async def test_retryable_create_attempts_share_network_budget(self):
        rows = [faction(i) for i in range(1, 129)]
        await self.submit(snapshot(factions=rows, members=[]))
        for row in rows:
            self.store.put_resource(row["id"], "role", None, "retryable")
        self.guild.raise_create = "forbidden"
        await self.engine.tick("live")
        self.assertEqual(len(self.guild.create_calls), 12)

    async def test_broken_other_faction_cannot_keep_police_role(self):
        await self.submit(snapshot())
        await self.engine.tick("live")
        bad = faction(9, "existing", "10000000000777777")
        await self.submit(snapshot(2, factions=[faction(), bad], members=[]))
        await self.engine.tick("live")
        self.assertEqual(self.member.calls[-1][0], "remove")
        self.assertEqual(self.member.roles, [])

    async def test_error_does_not_replace_last_success_time(self):
        await self.submit(snapshot())
        await self.engine.tick("live")
        last_sync = self.store.statuses()[0]["lastSyncAt"]
        self.store.status(6, 1, "error", "artificial")
        self.assertEqual(self.store.statuses()[0]["lastSyncAt"], last_sync)

    async def test_process_death_creation_marker_never_retried(self):
        self.store.put_resource(6, "role", None, "creating")
        self.engine = fd.Coordinator(self.cog)
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(self.store.resource(6, "role")["phase"], "held")
        self.assertEqual(self.guild.create_calls, [])

    async def test_cold_restart_requires_fresh_full_roster(self):
        await self.submit(snapshot())
        self.engine = fd.Coordinator(self.cog)
        await self.engine.tick("live")
        self.assertEqual(self.guild.create_calls, [])
        self.assertTrue((await self.engine.sync("live"))["needSnapshot"])
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(len(self.member.roles), 1)

    async def test_stale_healthy_roster_expires(self):
        await self.submit(snapshot())
        self.engine.fresh["live"] -= 121
        await self.engine.tick("live")
        self.assertEqual(self.guild.create_calls, [])
        self.assertFalse((await self.engine.sync("live"))["ready"])
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(len(self.member.roles), 1)

    async def test_disabled_and_deleted_archive_without_delete(self):
        await self.submit(snapshot())
        await self.engine.tick("live")
        await self.submit(snapshot(2, factions=[], members=[]))
        await self.engine.tick("live")
        self.assertEqual(len(self.guild.channels), 3)
        self.assertEqual(len(self.member.roles), 0)
        for channel in self.guild.channels:
            if not isinstance(channel, CategoryChannel):
                self.assertTrue(channel.name.startswith("archiv-"))
                self.assertEqual(set(channel.overwrites), {self.guild.default_role, self.guild.me})

    async def owned(self):
        await self.submit(snapshot())
        await self.engine.tick("live")
        return self.guild.get_role(int(self.store.resource(6, "role")["discord_id"]))

    async def dissolve(self, generation=2):
        row = faction()
        row["enabled"], row["deleted"] = False, True
        await self.submit(snapshot(generation, factions=[row], members=[]))
        return row

    async def test_profile_missing_policy_defaults_on_through_actual_sync_and_tick(self):
        self.cog.profiles.raw["live"].pop("faction_discord")
        self.assertIsNone(fd.profile_gate("live", self.cog.profiles))
        self.assertTrue((await self.submit(snapshot()))["ready"])
        await self.engine.tick("live")
        self.assertEqual(len(self.member.roles), 1)

    async def test_profile_empty_policy_defaults_on_explicit_false_preserved(self):
        self.cog.profiles.raw["live"]["faction_discord"] = {}
        self.assertTrue((await self.submit(snapshot()))["ready"])
        self.cog.profiles.raw["live"]["faction_discord"] = {"enabled": False}
        self.assertFalse((await self.submit(snapshot()))["ready"])
        await self.engine.tick("live")
        self.assertEqual(self.guild.create_calls, [])

    async def test_profile_malformed_policy_and_enabled_fail_closed(self):
        for policy in (None, True, "enabled", [], {"enabled": None}, {"enabled": "true"}, {"enabled": 1}):
            self.cog.profiles.raw["live"]["faction_discord"] = policy
            self.assertIsNotNone(fd.profile_gate("live", self.cog.profiles))
            await self.engine.tick("live")
        self.assertEqual(self.guild.create_calls, [])

    async def test_explicit_dissolution_deletes_only_owned_role_and_archives_channels(self):
        role = await self.owned()
        await self.dissolve()
        await self.engine.tick("live")
        self.assertEqual(len(role.deletes), 1)
        self.assertNotIn(role, self.guild.roles)
        self.assertEqual(self.store.deletion(6)["phase"], "complete")
        self.assertEqual(self.store.grants(), set())
        self.assertEqual(len(self.guild.channels), 3)
        for channel in self.guild.channels:
            if not isinstance(channel, CategoryChannel):
                self.assertTrue(channel.name.startswith("archiv-"))
                self.assertEqual(set(channel.overwrites), {self.guild.default_role, self.guild.me})
        await self.engine.tick("live")
        self.assertEqual(len(role.deletes), 1)

    async def test_off_or_disabled_never_deletes_owned_role(self):
        role = await self.owned()
        for generation, value in [(2, faction(enabled=False)), (3, faction(mode="off"))]:
            await self.submit(snapshot(generation, factions=[value], members=[]))
            await self.engine.tick("live")
        self.assertEqual(role.deletes, [])
        self.assertIsNone(self.store.deletion(6))

    async def test_missing_snapshot_faction_never_deletes_role(self):
        role = await self.owned()
        await self.submit(snapshot(2, factions=[], members=[]))
        await self.engine.tick("live")
        self.assertEqual(role.deletes, [])
        self.assertEqual(self.guild.role_fetches, 0)
        self.assertIsNone(self.store.deletion(6))

    async def test_existing_mapped_role_never_deleted_on_dissolution(self):
        role = Role(10000000000700001, "Existing")
        self.guild.roles.append(role)
        self.policy["allow_existing_role_ids"] = [str(role.id)]
        row = faction(mode="existing", role=str(role.id))
        await self.submit(snapshot(factions=[row]));await self.engine.tick("live")
        row["enabled"], row["deleted"] = False, True
        await self.submit(snapshot(2, factions=[row], members=[]));await self.engine.tick("live")
        self.assertEqual(role.deletes, [])
        self.assertIn(role, self.guild.roles)
        self.assertIsNone(self.store.deletion(6))

    async def test_other_disabled_or_off_faction_reference_protects_owned_role(self):
        role = await self.owned();deleted = await self.dissolve()
        for generation, other in [(3, faction(7, mode="existing", role=str(role.id), enabled=False)),
                                   (4, faction(7, mode="off", role=str(role.id)))]:
            await self.submit(snapshot(generation, factions=[deleted, other], members=[]))
            self.store.retry_reset();await self.engine.tick("live")
            self.assertEqual(role.deletes, [])
            self.assertIsNone(self.store.deletion(6))

    async def test_other_live_owned_registry_reference_protects_role(self):
        role = await self.owned();deleted = await self.dissolve()
        self.store.put_resource(7, "role", str(role.id), "ready")
        await self.submit(snapshot(3, factions=[deleted, faction(7, enabled=False)], members=[]))
        await self.engine.tick("live")
        self.assertEqual(role.deletes, [])

    async def test_other_missing_owner_registry_reference_is_not_silently_discarded(self):
        role=await self.owned();await self.dissolve()
        self.store.put_resource(7,"role",str(role.id),"ready")
        await self.engine.tick("live")
        self.assertEqual(role.deletes,[])
        self.assertIsNone(self.store.deletion(6))

    async def test_changed_or_protected_owned_role_not_deleted(self):
        role = await self.owned();await self.dissolve()
        for change in ("permission", "protected", "elevated", "managed", "hierarchy"):
            role.permissions=Permissions(send_messages=change=="permission", administrator=change=="elevated")
            role.managed=change=="managed";role.position=200 if change=="hierarchy" else 1
            self.policy["protected_role_ids"] = [str(role.id)] if change=="protected" else []
            self.store.retry_reset();await self.engine.tick("live")
            self.assertEqual(role.deletes, [])
        self.assertEqual(self.guild.role_fetches, 5)

    async def test_role_cache_miss_requires_fresh_rest_and_can_delete_exact_id(self):
        role=await self.owned();await self.dissolve()
        self.guild.hidden_role_ids.add(role.id)
        await self.engine.tick("live")
        self.assertEqual(self.guild.role_fetches,1)
        self.assertEqual(len(role.deletes),1)

    async def test_fresh_rest_absence_completes_without_delete_or_recreation(self):
        role=await self.owned();await self.dissolve()
        self.guild.roles.remove(role)
        await self.engine.tick("live")
        self.assertEqual(role.deletes,[])
        self.assertEqual(self.store.deletion(6)["note"],"rest_absence_confirmed")
        self.assertEqual(self.store.grants(),set())
        self.assertEqual(len(self.guild.create_calls),4)

    async def test_new_reference_during_rest_fetch_prevents_delete(self):
        role=await self.owned();deleted=await self.dissolve()
        async def change():
            self.guild.role_fetch_hook=None
            await self.submit(snapshot(3,factions=[deleted,faction(7,mode="off",role=str(role.id))],members=[]))
        self.guild.role_fetch_hook=change
        await self.engine.tick("live")
        self.assertEqual(role.deletes,[])
        self.assertIsNone(self.store.deletion(6))

    async def test_resurrection_during_rest_fetch_prevents_delete(self):
        role=await self.owned();await self.dissolve()
        async def change():
            self.guild.role_fetch_hook=None
            await self.submit(snapshot(3))
        self.guild.role_fetch_hook=change
        await self.engine.tick("live")
        self.assertEqual(role.deletes,[])

    async def test_new_reference_during_registry_read_prevents_delete(self):
        role=await self.owned();deleted=await self.dissolve();original=self.store.resources;calls=0
        def change():
            nonlocal calls
            calls+=1
            if calls==3:  # Last context check, after the durable DELETE intent.
                self.store.accept(snapshot(3,factions=[deleted,faction(7,mode="off",role=str(role.id))],members=[]))
            return original()
        self.store.resources=change
        with self.assertRaises(fd.Refused):
            await self.engine.dissolve_role("live",self.store,deleted,[12])
        self.assertEqual(role.deletes,[])
        self.assertEqual(calls,3)

    async def test_new_reference_during_delete_intent_prevents_delete(self):
        role=await self.owned();deleted=await self.dissolve();original=self.store.put_deletion
        def change(fid,rid,phase,generation,note=""):
            original(fid,rid,phase,generation,note)
            if phase=="deleting":
                self.store.accept(snapshot(3,factions=[deleted,faction(7,mode="off",role=str(role.id))],members=[]))
        self.store.put_deletion=change
        await self.engine.tick("live")
        self.assertEqual(role.deletes,[])
        self.assertEqual(self.store.deletion(6)["phase"],"pending")

    async def test_unknown_delete_after_server_success_reconciles_on_exact_rest_id(self):
        role=await self.owned();await self.dissolve();role.delete_error="after"
        await self.engine.tick("live")
        self.assertEqual(self.store.deletion(6)["phase"],"uncertain")
        self.store.retry_reset();await self.engine.tick("live")
        self.assertEqual(self.store.deletion(6)["phase"],"complete")
        self.assertEqual(len(role.deletes),1)
        self.assertEqual(self.store.grants(),set())

    async def test_exact_delete_404_confirms_concurrent_removal(self):
        role=await self.owned();await self.dissolve();role.delete_error="notfound_after"
        await self.engine.tick("live")
        self.assertEqual(self.store.deletion(6)["phase"],"complete")
        self.assertEqual(self.store.grants(),set())
        self.assertEqual(self.guild.role_fetches,2)
        await self.engine.tick("live")
        self.assertEqual(len(role.deletes),1)

    async def test_delete_404_with_role_still_present_never_claims_completion(self):
        role=await self.owned();deleted=await self.dissolve();role.delete_error="notfound"
        tracked=self.store.grants()
        with self.assertRaises(fd.Refused):
            await self.engine.dissolve_role("live",self.store,deleted,[12])
        self.assertEqual(self.store.deletion(6)["phase"],"uncertain")
        self.assertEqual(self.store.grants(),tracked)

    async def test_delete_404_with_guild_unavailable_never_claims_completion(self):
        role=await self.owned();deleted=await self.dissolve();role.delete_error="notfound"
        async def unavailable():raise NotFound(404)
        async def change():self.guild.role_fetch_hook=unavailable
        role.delete_hook=change;tracked=self.store.grants()
        with self.assertRaises(NotFound):
            await self.engine.dissolve_role("live",self.store,deleted,[12])
        self.assertEqual(self.store.deletion(6)["phase"],"uncertain")
        self.assertEqual(self.store.grants(),tracked)

    async def test_delete_404_confirmation_uses_budget_then_resumes_without_second_delete(self):
        role=await self.owned();deleted=await self.dissolve();role.delete_error="notfound_after"
        with self.assertRaises(fd.Refused):
            await self.engine.dissolve_role("live",self.store,deleted,[2])
        self.assertEqual(self.store.deletion(6)["phase"],"uncertain")
        await self.engine.dissolve_role("live",self.store,deleted,[12])
        self.assertEqual(self.store.deletion(6)["phase"],"complete")
        self.assertEqual(len(role.deletes),1)

    async def test_unknown_delete_before_send_can_retry_same_id_only(self):
        role=await self.owned();await self.dissolve();role.delete_error="before"
        await self.engine.tick("live");self.assertEqual(self.store.deletion(6)["phase"],"uncertain")
        role.delete_error=None;self.store.retry_reset();await self.engine.tick("live")
        self.assertEqual(self.store.deletion(6)["phase"],"complete")
        self.assertEqual(len(role.deletes),2)
        self.assertEqual(len(self.guild.create_calls),4)

    async def test_restart_preserves_delete_intent_and_requires_fresh_roster(self):
        role=await self.owned();deleted=await self.dissolve()
        self.store.put_deletion(6,str(role.id),"deleting",2)
        self.engine=fd.Coordinator(self.cog)
        await self.engine.tick("live");self.assertEqual(role.deletes,[])
        await self.submit(snapshot(2,factions=[deleted],members=[]));await self.engine.tick("live")
        self.assertEqual(self.store.deletion(6)["phase"],"complete")
        self.assertEqual(len(role.deletes),1)

    async def test_deleted_role_never_recreated_from_restored_auto_config(self):
        role=await self.owned();await self.dissolve();await self.engine.tick("live")
        await self.submit(snapshot(3));self.store.retry_reset();await self.engine.tick("live")
        self.assertEqual(len(self.guild.create_calls),4)
        self.assertEqual(len(role.deletes),1)
        self.assertIn("role_dissolution_recorded_no_recreation", self.store.statuses()[0]["message"])

    async def test_unknown_created_role_without_exact_id_not_deleted_by_name(self):
        self.store.put_resource(6,"role",None,"held","create_result_unknown")
        await self.dissolve(1);await self.engine.tick("live")
        self.assertEqual(self.guild.role_fetches,0)
        self.assertEqual(self.guild.create_calls,[])
        self.assertIsNone(self.store.deletion(6))

    async def test_incomplete_rest_roles_without_everyone_never_confirms_absence(self):
        role=await self.owned();await self.dissolve()
        async def incomplete():
            return []
        self.guild.fetch_roles=incomplete
        await self.engine.tick("live")
        self.assertEqual(role.deletes,[])
        self.assertIsNone(self.store.deletion(6))

    async def test_no_adoption_by_name(self):
        unrelated = Role(10000000000700001, "LSPD 6")
        self.guild.roles.append(unrelated)
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertNotEqual(self.member.roles[0].id, unrelated.id)
        self.assertEqual(unrelated.edits, [])

    async def test_existing_roles_require_allowlist_and_deny_privileged(self):
        role = Role(10000000000700001, "Normal")
        self.guild.roles.append(role)
        await self.submit(snapshot(factions=[faction(6, "existing", str(role.id))]))
        await self.engine.tick("live")
        self.assertEqual(self.member.roles, [])
        self.policy["allow_existing_role_ids"] = [str(role.id)]
        self.store.retry_reset()
        self.cog.config.mapping = {str(role.id): "editor"}
        await self.engine.tick("live")
        self.assertEqual(self.member.roles, [])
        self.cog.config.mapping = {}
        self.policy["protected_role_ids"] = [str(role.id)]
        self.store.retry_reset()
        await self.engine.tick("live")
        self.assertEqual(self.member.roles, [])
        self.policy["protected_role_ids"] = []
        role.permissions = Permissions(administrator=True)
        self.store.retry_reset()
        await self.engine.tick("live")
        self.assertEqual(self.member.roles, [])

    async def test_legacy_off_and_shared_guild_refused(self):
        self.cog.profiles.items["legacy"] = types.SimpleNamespace(id="legacy", guild_id=str(self.guild.id), enabled=True)
        self.assertEqual(fd.profile_gate("legacy", self.cog.profiles), "explicit_dev_or_live_profile_required")
        self.policy["enabled"] = False
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual(self.guild.create_calls, [])
        self.policy["enabled"] = True
        self.cog.profiles.items["dev"] = types.SimpleNamespace(id="dev", guild_id=str(self.guild.id), enabled=True)
        self.assertEqual(fd.profile_gate("live", self.cog.profiles), "guild_shared_between_profiles")
        await self.engine.tick("live")
        self.assertEqual(self.guild.create_calls, [])

    async def test_persistent_guild_binding_cannot_move(self):
        await self.submit(snapshot())
        self.store.bind(self.guild.id)
        with self.assertRaises(fd.Refused):
            self.store.bind(self.guild.id + 1)

    async def test_membership_change_during_fetch_cannot_grant_stale(self):
        self.guild.members.clear()
        await self.submit(snapshot())
        async def fetch(did):
            await self.submit(snapshot(2, members=[]))
            return self.member
        self.guild.fetch_hook = fetch
        await self.engine.tick("live")
        self.assertEqual(self.member.calls, [])

    async def test_membership_change_during_add_is_corrected(self):
        await self.submit(snapshot())
        async def update():
            await self.submit(snapshot(2, members=[]))
        self.member.after_add = update
        await self.engine.tick("live")
        self.member.after_add = None
        await self.engine.tick("live")
        self.assertEqual([call[0] for call in self.member.calls], ["add", "remove"])

    async def test_network_and_roster_work_bounded(self):
        accounts = [{"discordId": str(10000000000800000 + i), "factionIds": [6]} for i in range(100)]
        self.guild.members.clear()
        await self.submit(snapshot(members=accounts))
        await self.engine.tick("live")
        self.assertLessEqual(self.guild.fetches + len(self.guild.create_calls), 12)

    async def test_existing_category_children_do_not_inherit_public_access(self):
        category = CategoryChannel(10000000000700001, "Public", overwrites={self.guild.default_role: Overwrite(view_channel=True)})
        self.guild.channels.append(category)
        item = faction()
        item["config"].update(categoryMode="existing", categoryId=str(category.id))
        self.policy["allow_category_ids"] = [str(category.id)]
        await self.submit(snapshot(factions=[item]))
        await self.engine.tick("live")
        self.assertEqual(category.edits, [])
        for channel in self.guild.channels:
            if channel is not category:
                self.assertFalse(channel.overwrites[self.guild.default_role].flags["view_channel"])

    async def test_role_catalog_only_explicit_allowed_and_current(self):
        role, hidden = Role(10000000000700001, "Allowed"), Role(10000000000700002, "Server Editor")
        self.guild.roles.extend([role, hidden])
        self.policy["allow_existing_role_ids"] = [str(role.id)]
        await self.submit(snapshot())
        await self.engine.tick("live")
        self.assertEqual((await self.engine.sync("live"))["catalog"]["roles"], [{"id": str(role.id), "name": role.name}])
        self.cog.config.mapping[str(role.id)] = "support"
        self.assertEqual((await self.engine.sync("live"))["catalog"]["roles"], [])

    async def test_generation_idempotence_and_conflicts(self):
        value = snapshot()
        self.store.accept(value)
        self.assertEqual(self.store.accept(deepcopy(value)), 1)
        conflict = deepcopy(value)
        conflict["memberships"] = []
        with self.assertRaisesRegex(fd.Refused, "generation_conflict"):
            self.store.accept(conflict)
        value["generation"] = 2
        self.store.accept(value)
        with self.assertRaisesRegex(fd.Refused, "stale_generation"):
            self.store.accept(snapshot())
        rollback = snapshot(3)
        rollback["factions"][0]["config"]["revision"] = 0
        with self.assertRaisesRegex(fd.Refused, "configuration_revision_rollback"):
            self.store.accept(rollback)

    async def test_snapshot_bounds_and_duplicate_identity(self):
        value = snapshot()
        value["memberships"] *= 2
        with self.assertRaises(fd.Refused):
            fd.normalize_snapshot(value)
        value = snapshot(factions=[faction(i) for i in range(1, 130)], members=[])
        with self.assertRaises(fd.Refused):
            fd.normalize_snapshot(value)
        value = snapshot()
        value["memberships"][0]["factionIds"] = [6, 6]
        with self.assertRaises(fd.Refused):
            fd.normalize_snapshot(value)
        value = snapshot()
        value["generation"] = True
        with self.assertRaises(fd.Refused):
            fd.normalize_snapshot(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
