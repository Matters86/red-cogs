"""Bedienung und Wiederherstellung: echte Config, simulierte Discord-Fehler und Rechtewechsel."""
import asyncio
import re

import tc_harness as T
from aiohttp.test_utils import TestClient, TestServer
from rc.autoroom.autoroom import AutoRoom
from rc.autoroom.controls import RoomLimitModal, RoomTransferView, room_controls
from rc.autorole.autorole import Autorole
from rc.guard.guard import Guard
from rc.sticky.sticky import Sticky
from rc.onlyimagevideo.onlyimagevideo import OnlyImageVideo
from rc.onlyimagevideo.dashboard import _render_overview
from rc.commands.inspector import build_command_info, evaluate_member
from rc.commands.dashboard import _verdict_cell
from rc.example.example import Example
from rc.warns.warns import Warns


class Ctx:
    def __init__(self, guild, author):
        self.guild, self.author = guild, author
        self.sent, self.clean_prefix = [], "!"

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


async def main():
    wc, bot, app, _, _ = await T.make_app()
    guild = bot.guilds[0]
    owner, member, next_member = (guild.get_member(uid) for uid in (1, 13, 15))
    guard, sticky, ar, role, oiv, example, warns = (cls(bot) for cls in
        (Guard, Sticky, AutoRoom, Autorole, OnlyImageVideo, Example, Warns))
    for cog in (guard, sticky, ar, role, oiv, example, warns):
        cog._register_dashboard(wc)
    channel = guild.get_channel(1001)

    # Uneinheitliche Rechte beim Beenden: nur ausstehende Änderungen behalten und erneut versuchen.
    gc = guard.config.guild(guild)
    await gc.lockdown_until.set(-1)
    await gc.lockdown_prev.set({"1001": 0, "1002": 3})
    await gc.lockdown_invites_paused.set(True)
    channel.slowmode_delay = 10
    channel.forbid.add("edit_channel")
    invite_fails = True
    invite_calls = []

    async def guild_edit(**kwargs):
        invite_calls.append(kwargs)
        if invite_fails:
            raise T.L.forbidden()
    guild.edit = guild_edit
    assert not await guard._end_lockdown(guild)
    assert await gc.lockdown_prev() == {"1001": 0}
    assert await gc.lockdown_invites_paused() and await gc.lockdown_recovering()
    assert channel.slowmode_delay == 10
    channel.forbid.clear()
    invite_fails = False
    assert await guard._end_lockdown(guild)
    assert channel.slowmode_delay == 0 and not await gc.lockdown_prev()
    assert not await gc.lockdown_until() and not await gc.lockdown_invites_paused()
    assert invite_calls
    print("Guard: teilweise Wiederherstellung bleibt gespeichert, zweiter Versuch beendet vollständig – OK")

    # Ersatz zuerst senden: Ausfall darf den bisher sichtbaren Text nicht entfernen.
    sc = sticky.config.guild(guild)
    await sc.stickies.set({"1001": {"enabled": True, "mode": "text", "text": "Wichtige Regeln"}})
    assert await sticky.post_now(channel)
    first = int((await sc.stickies())["1001"]["message_id"])
    channel.forbid.add("send")
    assert not await sticky.post_now(channel)
    assert first in channel._messages and (await sc.stickies())["1001"]["delivery_error"]
    channel.forbid.clear()
    assert await sticky.post_now(channel)
    assert first not in channel._messages and not (await sc.stickies())["1001"]["delivery_error"]
    # Ein fehlgeschlagener Wechsel zum Webhook darf die Herkunft der alten Bot-Nachricht nicht ändern.
    before_transition = dict((await sc.stickies())["1001"])
    old_bot = int(before_transition["message_id"])
    async with sc.stickies() as entries:
        entries["1001"]["webhook"] = True
    hook = await sticky._get_or_create_webhook(channel)
    original_hook_send = hook.send
    async def fail_hook_send(*args, **kwargs):
        raise T.L.forbidden()
    hook.send = fail_hook_send
    assert not await sticky.post_now(channel)
    failed = (await sc.stickies())["1001"]
    assert failed["message_id"] == before_transition["message_id"]
    assert failed["webhook_id"] == before_transition["webhook_id"]
    assert old_bot in channel._messages
    hook.send = original_hook_send
    assert await sticky.post_now(channel)
    webhook_message = int((await sc.stickies())["1001"]["message_id"])
    assert old_bot not in channel._messages and channel._messages[webhook_message].webhook_id == hook.id
    # Auch bei eingeschalteter Verarbeitung anderer Bots keinen eigenen Webhook nach unten kopieren.
    await sc.ignore_bots.set(False)
    await sticky.on_message(channel._messages[webhook_message])
    assert channel.id not in sticky._pending
    async with sc.stickies() as entries:
        entries["1001"]["webhook"] = False
    assert await sticky.post_now(channel)
    assert webhook_message not in channel._messages
    assert (await sc.stickies())["1001"]["webhook_id"] is None
    print("Sticky: fehlgeschlagener Ersatz erhält alte Nachricht, Wiederholung räumt sie auf – OK")

    # Raum-Löschung scheitert zunächst: Datensatz bleibt für Startup/automatische Wiederholung erhalten.
    voice = T.L.FakeVoice.make(guild, 987654, "Test-Raum", guild.categories[0])
    guild.voice_channels.append(voice)
    voice.members = []
    rc = ar.config.guild(guild)
    await rc.active_rooms.set({str(voice.id): {"owner_id": member.id, "source_id": 1050, "text_id": None}})
    original_delete = voice.delete

    async def fail_delete(**kwargs):
        raise T.L.forbidden()
    voice.delete = fail_delete
    await ar._maybe_cleanup_room(voice)
    assert (await rc.active_rooms())[str(voice.id)]["cleanup_error"]
    voice.delete = original_delete
    assert await ar._sweep_guild(guild) == 1
    assert str(voice.id) not in await rc.active_rooms()

    voice = T.L.FakeVoice.make(guild, 987655, "Besitzerraum", guild.categories[0])
    guild.voice_channels.append(voice)
    voice.members = [member, next_member]
    permission_calls = []

    async def set_permissions(target, **kwargs):
        permission_calls.append((target.id, kwargs))
    voice.set_permissions = set_permissions
    await rc.active_rooms.set({str(voice.id): {"owner_id": member.id, "source_id": 1050, "text_id": None}})
    assert len(room_controls(voice.id).children) == 6
    assert await ar.change_room(guild, voice.id, next_member, "private")
    assert await ar.change_room(guild, voice.id, member, "private") is None
    assert permission_calls[-1][1]["overwrite"].view_channel is False
    assert await ar.change_room(guild, voice.id, member, "limit", 7) is None and voice.user_limit == 7
    assert await ar.change_room(guild, voice.id, member, "limit", 100)
    assert await ar.change_room(guild, voice.id, member, "transfer", owner.id)
    assert await ar.change_room(guild, voice.id, member, "transfer", next_member.id) is None
    assert await ar.change_room(guild, voice.id, member, "public"), "Alter Besitzer verliert Steuerrechte sofort"
    assert await ar.change_room(guild, voice.id, member, "claim"), "Aktueller Besitzer ist noch im Raum"
    voice.members = [member]
    assert await ar.change_room(guild, voice.id, member, "claim") is None
    view = RoomTransferView(ar, voice.id, member.id)
    view.select._values = [next_member]
    denied = []
    await view.select.callback(T.Inter(denied, guild, next_member, channel))
    assert denied and (await rc.active_rooms())[str(voice.id)]["owner_id"] == member.id
    modal = RoomLimitModal(ar, voice.id)
    modal.limit._value = "5"
    # Rechteverlust zwischen Öffnen und Bestätigen muss auch das Modal stoppen.
    async with rc.active_rooms() as rooms:
        rooms[str(voice.id)]["owner_id"] = next_member.id
    old_limit = voice.user_limit
    await modal.on_submit(T.Inter([], guild, member, channel))
    assert voice.user_limit == old_limit
    voice.members = [member, next_member]
    async with rc.active_rooms() as rooms:
        rooms[str(voice.id)]["owner_id"] = owner.id
    result = await asyncio.gather(ar.change_room(guild, voice.id, member, "claim"),
                                  ar.change_room(guild, voice.id, next_member, "claim"))
    assert result.count(None) == 1
    print("AutoRoom: Löschwiederholung, persistente Steuerung, Besitzerwechsel/Claim und Dialog-Reauth – OK")

    # Vorschau und Vergabe benutzen exakt dieselbe Auswahl; Vorschau verändert nichts.
    ac = role.config.guild(guild)
    await ac.enabled.set(True)
    await ac.join_roles.set([1104, 999999])
    before_roles = {m.id: list(m.roles) for m in guild.members}
    plan = await role.preview_apply(guild)
    assert plan["assignments"] and plan["unavailable"]
    assert all(not m.bot and guild.get_role(1104) not in m.roles for m, _ in plan["assignments"])
    assert all(m.roles == before_roles[m.id] for m in guild.members)
    result = await role.apply_to_existing(guild)
    assert result == (sum(len(rs) for _, rs in plan["assignments"]), len(plan["assignments"]))
    assert not (await role.preview_apply(guild))["assignments"]
    ctx = Ctx(guild, owner)
    await role.autorole_applyall.callback(role, ctx)
    assert ctx.sent[-1][1].get("view") is not None
    original_role_log = len(T.ROLE_LOG)
    await ac.join_roles.set([1102, 1104])
    response = []
    await ctx.sent[-1][1]["view"].children[0].callback(T.Inter(response, guild, owner, channel))
    assert len(T.ROLE_LOG) == original_role_log and "geändert" in response[-1][1]
    member.guild_permissions.manage_guild = True
    former_admin = Ctx(guild, member)
    await role.autorole_applyall.callback(role, former_admin)
    member.guild_permissions.manage_guild = False
    response = []
    await former_admin.sent[-1][1]["view"].children[0].callback(T.Inter(response, guild, member, channel))
    assert len(T.ROLE_LOG) == original_role_log and "Verwaltungsrechte" in response[-1][1]
    print("Autorole: Vorschau zählt genaue Mitglieder/Rollen/Skips, keine Mutation vor Bestätigung – OK")

    # Fremdprüfung darf zusätzliche Befehlsbedingungen nicht als bekannt erfüllt ausgeben.
    info = build_command_info(example.example_setnote)
    info.custom_checks = 1
    info.req_priv = None
    info.perms = []
    verdict, note = evaluate_member(info, member, None)
    info.verdict, info.verdict_note = verdict, note
    assert verdict is None and "Bedingt nutzbar" in _verdict_cell(wc.ui, info)
    info.enabled = False
    assert evaluate_member(info, member, None)[0] is False
    original_permissions = channel.permissions_for
    def without_manage(target):
        value = original_permissions(target)
        value.manage_messages = False
        return value
    channel.permissions_for = without_manage
    html = _render_overview(wc.ui, guild, {"channels": [channel.id], "notify": True})
    assert "allgemein" in html and "Nachrichten verwalten" in html and "Berechtigungen" in html
    channel.permissions_for = original_permissions
    await example.config.guild(guild).note.set("vorher")
    ctx = Ctx(guild, owner)
    await example.example_setnote.callback(example, ctx, text="x" * 501)
    assert await example.config.guild(guild).note() == "vorher"
    assert "500" in ctx.sent[-1][0]
    await example.example_setnote.callback(example, ctx, text="x" * 500)
    assert len(await example.config.guild(guild).note()) == 500
    print("Commands/OIV/Example: ehrliche Rechte-Einschätzung, konkrete Kanalfehler, gleiche Textgrenze – OK")

    # Vorschau liest aktuelle Punkte; Ausführen rechnet nach einer weiteren Verwarnung erneut.
    wcg = warns.config.guild(guild)
    await wcg.dm_enabled.set(False)
    await wcg.timeout_at.set(3)
    await warns.add_warning(guild, member, owner, "vorher", 1)
    client = TestClient(TestServer(app))
    await client.start_server()
    headers = {"X-Test-User": "1"}
    try:
        response = await client.get("/cogs/warnings?guild=1000&preview=warn&member=13&points=1", headers=headers)
        preview = await response.json()
        assert "1 → 2" in preview["text"] and "keine automatische" in preview["text"]
        await warns.add_warning(guild, member, owner, "zwischenzeitlich", 1)
        actions = []
        async def execute(*args, **kwargs):
            actions.append(args[2])
            return None
        warns._execute = execute
        page = await client.get("/cogs/warnings?guild=1000", headers=headers)
        token = re.search(r"name='csrf_token' value='([^']+)'", await page.text()).group(1)
        response = await client.post("/cogs/warnings", headers=headers, allow_redirects=False,
            data={"csrf_token": token, "guild": "1000", "form": "warn", "member": "13", "reason": "neu", "points": "1"})
        assert response.status == 302 and await warns.active_points(guild, member.id) == 3
        assert actions == ["timeout"], actions
        response = await client.post("/cogs/example", headers=headers, allow_redirects=False,
            data={"csrf_token": token, "guild": "1000", "note": "x" * 501})
        assert "err=" in response.headers["Location"]
        assert len(await example.config.guild(guild).note()) == 500
    finally:
        await client.close()
    print("Warns: konkrete Vorschau ohne Mutation, Ausführung rechnet aktuellen Punktestand neu – OK")
    print("ALLE UX-/WIEDERHERSTELLUNGS-TESTS OK")


asyncio.run(main())
