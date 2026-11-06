"""Execute actual added Cog method AST with fake framework/HTTP dependencies."""
import ast
import asyncio
import copy
import types
import unittest
from pathlib import Path

import test_faction_discord as harness


MODULE = Path(__file__).resolve().parents[1] / "adminpanel.py"
TREE = ast.parse(MODULE.read_text(encoding="utf-8"))
CLASS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "AdminPanel")


def actual_method(name, extra=None):
    node = copy.deepcopy(next(node for node in CLASS.body if getattr(node, "name", "") == name))
    node.decorator_list = []
    tree = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    env = {"asyncio": asyncio, "web": types.SimpleNamespace(Request=object, json_response=lambda value: value),
           "db": None, "READ_ACTIONS": {"read"}, "commands": types.SimpleNamespace(Context=object),
           "discord": harness.fake_discord,
           "faction_discord_id": harness.fd.snowflake,
           "faction_discord_management_ids": harness.fd.management_role_ids,
           "faction_discord_safe_role": harness.fd.safe_role,
           "FactionDiscordRefused": harness.fd.Refused}
    env.update(extra or {})
    exec(compile(tree, str(MODULE), "exec"), env)
    return env[name]


class BridgeWiring(unittest.IsolatedAsyncioTestCase):
    loop_factory = harness.OfflineLoop

    async def asyncSetUp(self):
        self.calls = []
        data = {"state": {"players": 2}, "events": [{"type": "join"}]}
        async def read(request):
            return data
        async def actions(profile):
            return [{"action_type": "read"}, {"action_type": "write"}]
        async def locked():
            return False
        async def alerts(events):
            self.calls.append(("alerts", events))
        async def sync(pid, payload):
            self.calls.append(("faction", pid, payload))
            return {"schema": 1, "profile": pid, "ready": True, "acceptedGeneration": 11}
        self.data = data
        self.obj = types.SimpleNamespace(_read_json=read, _actions_for_bridge=actions,
            profile_locked=locked, _dispatch_alerts=alerts,
            faction_discord=types.SimpleNamespace(sync=sync),
            faction_discord_log=lambda *args: self.calls.append(("log", args)))
        self.db = types.SimpleNamespace(save_server_state=lambda state: self.calls.append(("state", state)),
            add_events=lambda events: self.calls.append(("events", events)),
            get_active_bans=lambda: [{"license": "artificial", "reason": "test"}])
        self.method = actual_method("http_bridge_sync", {"db": self.db})

    async def test_existing_state_events_actions_bans_unchanged(self):
        result = await self.method(self.obj, {"profile": {"id": "legacy"}})
        self.assertEqual(set(result), {"actions", "bans"})
        self.assertEqual(len(result["actions"]), 2)
        self.assertEqual(result["bans"][0]["license"], "artificial")
        self.assertEqual([item[0] for item in self.calls], ["state", "events", "alerts"])

    async def test_explicit_profile_returns_cached_response_without_new_payload(self):
        result = await self.method(self.obj, {"profile": {"id": "live"}})
        self.assertEqual(result["faction_discord"]["acceptedGeneration"], 11)
        self.assertEqual(self.calls[-1], ("faction", "live", None))

    async def test_nested_snapshot_passed_without_guild_from_client(self):
        self.data["faction_discord"] = harness.snapshot(11)
        self.data["guild_id"] = "ATTACKER"
        result = await self.method(self.obj, {"profile": {"id": "dev", "guild_id": "10000000000900000"}})
        self.assertEqual(result["faction_discord"]["profile"], "dev")
        self.assertEqual(self.calls[-1], ("faction", "dev", self.data["faction_discord"]))

    async def test_coordinator_error_does_not_break_old_bridge(self):
        async def failed(*args):
            raise RuntimeError("artificial")
        self.obj.faction_discord.sync = failed
        result = await self.method(self.obj, {"profile": {"id": "live"}})
        self.assertEqual(len(result["actions"]), 2)
        self.assertEqual(result["faction_discord"]["code"], "coordinator_unavailable")

    async def test_lockdown_filter_still_applies(self):
        async def locked():
            return True
        self.obj.profile_locked = locked
        result = await self.method(self.obj, {"profile": {"id": "live"}})
        self.assertEqual(result["actions"], [{"action_type": "read"}])


class CommandAuthorization(unittest.IsolatedAsyncioTestCase):
    loop_factory = harness.OfflineLoop

    async def asyncSetUp(self):
        self.messages = []
        self.guild = harness.Guild()
        async def send(value):
            self.messages.append(value)
        self.ctx = types.SimpleNamespace(guild=self.guild, author=types.SimpleNamespace(guild_permissions=harness.Permissions(administrator=False)), send=send)
        self.obj = types.SimpleNamespace(profiles=types.SimpleNamespace(select=lambda pid, gid: types.SimpleNamespace(id=pid)))
        self.method = actual_method("ap_factiondiscord")

    async def test_nonadministrator_cannot_even_enter_configuration(self):
        await self.method(self.obj, self.ctx, "live", "enable")
        self.assertIn("Nur Discord-Administratoren", self.messages[-1])

    async def test_legacy_denied_even_for_administrator(self):
        self.ctx.author.guild_permissions = harness.Permissions(administrator=True)
        await self.method(self.obj, self.ctx, "legacy", "enable")
        self.assertIn("Legacy bleibt gesperrt", self.messages[-1])


class SourcePreservation(unittest.TestCase):
    def test_build_constant(self):
        build = next(node for node in TREE.body if isinstance(node, ast.Assign) and
                     any(isinstance(item, ast.Name) and item.id == "PANEL_BUILD" for item in node.targets))
        self.assertEqual(build.value.value, "2026-11-06-support-v2.3.2")

    def test_unrelated_cog_functions_preserved(self):
        before = Path(__file__).resolve().parents[3] / "before" / "fivemadmin" / "adminpanel.py"
        if not before.exists():
            self.skipTest("Preimage belongs to workspace delivery verification, not installed Cog.")
        original = ast.parse(before.read_text(encoding="utf-8"))
        old_class = next(node for node in original.body if isinstance(node, ast.ClassDef) and node.name == "AdminPanel")
        old = {node.name: ast.dump(node, include_attributes=False) for node in old_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        new = {node.name: ast.dump(node, include_attributes=False) for node in CLASS.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        changed = {name for name in old if old[name] != new.get(name)}
        self.assertEqual(changed, {"ap_factiondiscord"})
        self.assertEqual(set(new) - set(old), set())


class ManagementCommands(unittest.IsolatedAsyncioTestCase):
    loop_factory = harness.OfflineLoop

    async def asyncSetUp(self):
        self.messages = []
        self.guild = harness.Guild()
        self.manager = harness.Role(int(harness.fd.DEFAULT_LIVE_MANAGEMENT_ROLE_ID), "Verwaltung", position=150)
        self.guild.roles.append(self.manager)
        self.records = {"live": {"faction_discord": {}}}
        self.saved = []
        async def get():
            return copy.deepcopy(self.records)
        async def put(value):
            self.records = copy.deepcopy(value)
            self.saved.append(value)
        async def mapping():
            return {}
        config = types.SimpleNamespace(server_profiles=types.SimpleNamespace(__call__=get, set=put))
        class Field:
            __call__ = staticmethod(get)
            set = staticmethod(put)
        config.server_profiles = Field()
        config.guild = lambda guild: types.SimpleNamespace(role_map=mapping)
        profiles = types.SimpleNamespace(select=lambda pid, gid: types.SimpleNamespace(id=pid), raw=copy.deepcopy(self.records))
        async def refresh():
            profiles.raw = copy.deepcopy(self.records)
        async def send(value):
            self.messages.append(value)
        self.ctx = types.SimpleNamespace(guild=self.guild, author=types.SimpleNamespace(guild_permissions=harness.Permissions(administrator=True)), send=send)
        self.obj = types.SimpleNamespace(profiles=profiles, config=config, _profile_config_lock=asyncio.Lock(),
            _refresh_profiles=refresh, faction_discord=types.SimpleNamespace(catalogs={}))
        self.method = actual_method("ap_factiondiscord")

    async def test_admin_remove_default_stores_explicit_empty_then_add_by_id(self):
        await self.method(self.obj, self.ctx, "live", "denymanagement", value=str(self.manager.id))
        self.assertEqual(self.records["live"]["faction_discord"]["management_role_ids"], [])
        self.manager.name = "Umbenannt"
        await self.method(self.obj, self.ctx, "live", "allowmanagement", value=str(self.manager.id))
        self.assertEqual(self.records["live"]["faction_discord"]["management_role_ids"], [str(self.manager.id)])

    async def test_nonadmin_management_configuration_denied(self):
        self.ctx.author.guild_permissions = harness.Permissions(administrator=False)
        await self.method(self.obj, self.ctx, "live", "allowmanagement", value=str(self.manager.id))
        self.assertEqual(self.saved, [])
        self.assertIn("Nur Discord-Administratoren", self.messages[-1])

    async def test_default_management_cannot_be_allowlisted_faction_role(self):
        await self.method(self.obj, self.ctx, "live", "allowrole", value=str(self.manager.id))
        self.assertEqual(self.saved, [])
        self.assertIn("geschützt", self.messages[-1])

    async def test_management_unknown_role_and_invalid_policy_not_written(self):
        await self.method(self.obj, self.ctx, "live", "allowmanagement", value="10000000000123456")
        self.assertEqual(self.saved, [])
        self.records["live"]["faction_discord"]["management_role_ids"] = "invalid"
        await self.method(self.obj, self.ctx, "live", "denymanagement", value=str(self.manager.id))
        self.assertEqual(self.saved, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
