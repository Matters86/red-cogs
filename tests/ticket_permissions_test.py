"""Ticket-Teams bleiben in Discord getrennt; aktuelle Rollen zählen bei Ausführung."""
import asyncio
from types import SimpleNamespace

import discord
import tc_harness as T


class Response(T.Resp):
    async def send_message(self, content=None, *, view=None, **kwargs):
        self.view = view
        await super().send_message(content, view=view, **kwargs)


class PrivateThread(T.L._SendMixin, discord.Thread):
    guild = None
    category_id = None

    @classmethod
    def make(cls, guild, cid, name):
        obj = object.__new__(cls)
        T.L._init_common(obj, guild, cid, name, None, 0)
        obj.parent_id = 1002
        obj._type = discord.ChannelType.private_thread
        obj.archived = obj.locked = False
        obj.joined, obj.removed = set(), []
        obj.fail_uid = None
        obj.fail_remove_uid = None
        obj.deleted = False
        obj.sent_mentions = []
        guild.threads.append(obj)
        return obj

    async def add_user(self, member):
        if member.id == self.fail_uid:
            raise T.L.forbidden()
        self.joined.add(member.id)

    async def remove_user(self, member):
        if member.id == self.fail_remove_uid:
            raise T.L.forbidden()
        self.joined.discard(member.id)
        self.removed.append(member.id)

    async def fetch_member(self, uid):
        if uid not in self.joined:
            raise T.L.not_found()
        return SimpleNamespace(id=uid)

    def permissions_for(self, member):
        result = discord.Permissions.all()
        result.manage_threads = False
        return result

    async def send(self, *args, **kwargs):
        self.sent_mentions.append(kwargs.get("allowed_mentions"))
        return await super().send(*args, **kwargs)

    async def delete(self, **kwargs):
        self.deleted = True
        self.guild.threads.remove(self)


class TrackedText(T.L.FakeText):
    @property
    def overwrites(self):
        return dict(getattr(self, "acl", {}))

    async def edit(self, **kwargs):
        if "overwrites" in kwargs:
            self.acl = dict(kwargs["overwrites"])
        return await super().edit(**kwargs)


async def main():
    wc, bot, app, cog, _ = await T.make_app()
    guild = bot.guilds[0]
    gc = cog.config.guild(guild)
    owner, global_staff, scoped_staff, guest = (guild.get_member(uid) for uid in (13, 11, 12, 15))
    await gc.support_roles.set([1101])
    await gc.category_open.set(guild.categories[0].id)
    await gc.max_open.set(30)
    panel = {"id": "scope", "title": "Support", "reasons": [
        {"id": "private", "label": "Vertraulich", "support_roles": [1102]}]}
    await gc.panels.set([panel])

    async def new_ticket():
        result = await cog.open_ticket(guild, owner, panel, panel["reasons"][0], {})
        assert result.status == "ok", result
        return result.target

    async def record(channel):
        return (await gc.tickets())[str(channel.id)]

    channel = await new_ticket()
    conf, rec = await gc.all(), await record(channel)
    assert not cog._is_staff(global_staff, conf, rec)
    assert cog._is_staff(scoped_staff, conf, rec)
    assert not cog._is_staff(global_staff, conf, {"support_roles": []})
    assert cog._is_staff(global_staff, conf, {})  # Altbestand ohne Snapshot
    assert not cog._can_view_record(owner, conf, rec)
    assert not cog._can_view_record(guest, conf, rec)
    assert cog._can_view_record(scoped_staff, conf, rec)
    global_staff.guild_permissions.manage_guild = True
    assert not cog._is_admin(global_staff, conf)
    assert not cog._is_staff(global_staff, conf, rec)
    global_staff.guild_permissions.manage_guild = False
    assert cog._is_admin(guild.get_member(1), conf)
    assert not cog._is_admin(None, conf)
    assert not cog._is_admin(SimpleNamespace(id=1234), conf)
    conf["admin_roles"] = [1101]
    assert cog._is_staff(global_staff, conf, rec)
    conf["admin_roles"], conf["view_roles"] = [], [1101, 1102]
    assert cog._can_view_record(global_staff, conf, rec)
    assert not cog._can_view_record(global_staff, conf, None)
    assert cog._overwrites(guild, owner, conf, [1102])[guild.get_role(1102)].send_messages is True
    assert cog._closed_overwrites(guild, conf, [1102])[guild.get_role(1102)].send_messages is True

    assert await cog._assign_ticket(guild, channel, scoped_staff, global_staff)
    assert await cog._set_waiting(guild, channel, "user", global_staff)
    assert not await cog._set_ticket_autoclose(guild, channel, True, global_staff, await gc.all())
    assert not await cog._close_ticket(guild, channel, rec, global_staff, await gc.all())
    assert await cog._set_ticket_autoclose(guild, channel, True, scoped_staff, await gc.all())
    assert await cog._set_ticket_autoclose(guild, channel, False, owner, await gc.all())

    responses = []
    inter = T.Inter(responses, guild, scoped_staff, channel)
    inter.response = Response(responses)
    await cog._control_close(inter)
    confirmation = inter.response.view
    old_roles = scoped_staff.roles
    scoped_staff.roles = [guild.default_role]
    await confirmation.children[0].callback(T.Inter(responses, guild, scoped_staff, channel))
    assert (await record(channel))["status"] == "open"
    assert any(item[0] == "followup" for item in responses)
    scoped_staff.roles = old_roles

    # Auch nach Warten auf den gemeinsamen Kanallock werden aktuelle Rollen gelesen.
    lock = cog._lock("close", channel.id)
    await lock.acquire()
    pending = asyncio.create_task(cog._assign_ticket(guild, channel, None, scoped_staff))
    await asyncio.sleep(0)
    scoped_staff.roles = [guild.default_role]
    lock.release()
    assert await pending
    scoped_staff.roles = old_roles
    assert await cog._close_ticket(guild, channel, rec, scoped_staff, await gc.all())
    tr = (await gc.transcripts())[-1]
    assert tr["support_roles"] == [1102] and tr["reason_id"] == "private"
    assert cog._transcript_record(await gc.all(), tr) == tr
    assert cog._transcript_record(await gc.all(), {"num": rec["num"]})["support_roles"] == [1102]
    assert cog._transcript_record(await gc.all(), {"num": -1}) is None
    await gc.delete_on_close.set(True)
    assert not await cog._close_ticket(guild, channel, rec, scoped_staff, await gc.all())
    assert str(channel.id) in await gc.tickets(), "Wiederholtes Schließen darf Archiv nicht löschen"
    await gc.delete_on_close.set(False)
    assert not await cog._close_ticket(guild, channel, rec, scoped_staff, await gc.all(), force_delete=True)
    assert str(channel.id) in await gc.tickets()
    await cog._close_ticket(guild, channel, rec, guild.get_member(1), await gc.all(), force_delete=True)
    assert str(channel.id) not in await gc.tickets()

    # Zwischen Modal/Website und Lock geänderte oder gelöschte Gründe niemals ersetzen.
    await gc.panels.set([{**panel, "reasons": []}])
    result = await cog.open_ticket(guild, owner, panel, panel["reasons"][0], {})
    assert result.target is None
    await gc.panels.set([])
    result = await cog.open_ticket(guild, owner, panel, None, {})
    assert result.target is None
    await gc.panels.set([panel])

    # Besitzerwechsel entzieht alte Einzelrechte und erhält ausdrückliche Gäste.
    source = await new_ticket()
    tracked = TrackedText.make(guild, source.id, source.name, guild.categories[0], 0)
    tracked._messages = source._messages
    tracked.acl = {owner: discord.PermissionOverwrite(view_channel=True),
                   guest: discord.PermissionOverwrite(view_channel=True)}
    async with gc.tickets() as records:
        records[str(tracked.id)]["members"] = [guest.id]
    assert await cog._transfer_owner(guild, tracked, global_staff, guest)
    assert await cog._transfer_owner(guild, tracked, scoped_staff, guest) is None
    assert owner not in tracked.acl and guest in tracked.acl
    assert (await record(tracked))["owner_id"] == guest.id
    assert await cog._change_member(guild, tracked, scoped_staff, owner, add=True) is None
    rec = await record(tracked)
    async with gc.tickets() as records:
        records[str(tracked.id)]["status"] = "closed"
    assert await cog._reopen_ticket(guild, tracked, rec, await gc.all(), actor=scoped_staff)
    assert owner in tracked.acl and guest in tracked.acl

    # Private Threads: Ping-Rollen werden weder erwähnt noch eingeladen.
    await gc.ticket_type.set("thread")
    await gc.thread_base.set(1002)
    await gc.ping_roles.set([1101])
    created = []
    fail_uid = [None]

    async def create_thread(**kwargs):
        thread = PrivateThread.make(guild, 80000 + len(created), kwargs["name"])
        thread.fail_uid = fail_uid[0]
        created.append(thread)
        return thread

    guild.get_channel(1002).create_thread = create_thread
    thread = await new_ticket()
    assert owner.id in thread.joined and scoped_staff.id in thread.joined
    assert global_staff.id not in thread.joined
    assert all(mentions is not None and not mentions.roles and not mentions.users for mentions in thread.sent_mentions)
    thread.joined.discard(scoped_staff.id)
    assert await cog._reply_access(guild, thread, scoped_staff)
    assert await cog._assign_ticket(guild, thread, scoped_staff, scoped_staff) is None
    assert await cog._reply_access(guild, thread, scoped_staff) is None
    thread.joined.add(guest.id)
    thread.fail_remove_uid = owner.id
    assert await cog._transfer_owner(guild, thread, scoped_staff, guest)
    assert owner.id in thread.joined and guest.id in thread.joined
    assert (await record(thread))["owner_id"] == owner.id
    thread.fail_remove_uid = None
    fail_uid[0] = owner.id
    result = await cog.open_ticket(guild, owner, panel, panel["reasons"][0], {})
    assert result.target is None and created[-1].deleted
    fail_uid[0] = scoped_staff.id
    result = await cog.open_ticket(guild, owner, panel, panel["reasons"][0], {})
    assert result.status == "ok" and not result.target.deleted
    assert any("Teammitglieder" in (message.content or "") for message in result.target._messages.values())
    print("ticket_permissions_test: PASS – Teams, aktuelle Rechte, Snapshot, Transfer, private Threads")


asyncio.run(main())
