"""Ticket-Zuständigkeit: gemeinsamer Pfad für Buttons, Slash-Befehle und Dashboard."""
import asyncio
import re

import tc_harness as T
import discord
from aiohttp.test_utils import TestClient, TestServer


class Ctx:
    def __init__(self, guild, channel, author):
        self.guild, self.channel, self.author = guild, channel, author
        self.deferred, self.sent = [], []

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class Response(T.Resp):
    view = None

    async def send_message(self, content=None, *, view=None, **kwargs):
        self.view = view
        await super().send_message(content, view=view, **kwargs)


class Interaction(T.Inter):
    def __init__(self, responses, guild, user, channel, cid=""):
        super().__init__(responses, guild, user, channel, cid)
        self.response = Response(responses)
        self.edits = []

    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


class AssignmentThread(T.L._SendMixin, discord.Thread):
    guild = None
    category_id = None

    @classmethod
    def from_text(cls, channel):
        result = object.__new__(cls)
        T.L._init_common(result, channel.guild, channel.id, channel.name, None, 0)
        result.parent_id = 1002
        result.archived = False
        result.locked = False
        result.fail_join = False
        result.joined = []
        result._messages = channel._messages
        for message in result._messages.values():
            message.channel = result
        return result

    async def add_user(self, member):
        if self.fail_join or self.archived:
            raise T.L.forbidden()
        self.joined.append(member.id)


async def main():
    wc, bot, app, cog, _ = await T.make_app()
    from rc.tickets.views import AssignmentView, CID_ASSIGN, CID_UNCLAIM, build_controls_view
    guild = bot.guilds[0]
    conf = cog.config.guild(guild)
    owner, staff, second, outsider = (guild.get_member(i) for i in (13, 11, 14, 15))
    await conf.support_roles.set([1101])
    await conf.category_open.set(guild.categories[0].id)
    await conf.max_open.set(30)
    panel = {"id": "assignment", "title": "Support", "reasons": [], "modal_questions": []}

    async def new_ticket():
        result = await cog.open_ticket(guild, owner, panel, None, {})
        assert result.status == "ok"
        return result.target

    async def record(channel):
        return (await conf.tickets())[str(channel.id)]

    async def claims():
        return (await conf.stats())["claims"]

    channel = await new_ticket()
    assert CID_ASSIGN in {button.custom_id for button in build_controls_view("de").children}
    assert await cog._assign_ticket(guild, channel, staff, staff) is None
    assert (await record(channel))["claimed_by"] == staff.id
    assert (await claims())[str(staff.id)] == 1
    opening = await channel.fetch_message((await record(channel))["message_id"])
    assert staff.display_name in opening.embeds[0].footer.text
    before = await claims()
    assert await cog._assign_ticket(guild, channel, staff, staff)
    assert await claims() == before, "Doppelklick darf keine weitere Übernahme zählen"
    assert await cog._assign_ticket(guild, channel, second, staff) is None
    assert (await record(channel))["claimed_by"] == second.id
    assert (await claims())[str(second.id)] == 1
    assert await cog._assign_ticket(guild, channel, None, second) is None
    assert (await record(channel))["claimed_by"] is None
    assert await claims() == {str(staff.id): 1, str(second.id): 1}
    assert second.display_name not in opening.embeds[0].footer.text

    # Sowohl Handelnder als auch Ziel brauchen die aktuellen Rechte dieses Tickets.
    for invalid in (owner, outsider, guild.me, bot.guilds[1].get_member(11)):
        assert await cog._assign_ticket(guild, channel, invalid, staff)
    assert await cog._assign_ticket(guild, channel, staff, outsider)
    assert (await record(channel))["claimed_by"] is None
    original_permissions = channel.permissions_for
    for denied in ("view_channel", "read_message_history", "send_messages"):
        def permissions(member, denied=denied):
            result = original_permissions(member)
            if member.id == second.id:
                setattr(result, denied, False)
            return result
        channel.permissions_for = permissions
        assert await cog._assign_ticket(guild, channel, second, staff), denied
    channel.permissions_for = original_permissions
    assert (await record(channel))["claimed_by"] is None
    owner.roles.append(guild.get_role(1101))
    assert await cog._assign_ticket(guild, channel, owner, staff), "Ticket-Inhaber ist auch als Teammitglied kein Ziel"
    owner.roles.remove(guild.get_role(1101))

    # Ein grundspezifisches Team muss ebenfalls zuweisen und übernehmen können.
    team_member = guild.get_member(12)
    async with conf.tickets() as tickets:
        tickets[str(channel.id)]["support_roles"] = [1102]
    assert await cog._assign_ticket(guild, channel, team_member, team_member) is None
    assert await cog._assign_ticket(guild, channel, None, staff) is None
    assert await cog._assign_ticket(guild, guild.get_channel(1001), staff, staff)
    print("Zuweisen/Übergabe/Freigabe: Rechte, Kanalzugriff, Inhaber/Bots, Statistik und sichtbarer Status – OK")

    # Gleichzeitiges Selbst-Übernehmen: genau einer gewinnt; keine stille Übernahme des anderen.
    concurrent = await new_ticket()
    before_total = sum((await claims()).values())
    results = await asyncio.gather(
        cog._assign_ticket(guild, concurrent, staff, staff, replace=False),
        cog._assign_ticket(guild, concurrent, second, second, replace=False),
    )
    assert results.count(None) == 1 and sum((await claims()).values()) == before_total + 1
    assert (await record(concurrent))["claimed_by"] in (staff.id, second.id)
    closing = await new_ticket()
    async with conf.tickets() as tickets:
        tickets[str(closing.id)]["status"] = "closing"
    assert await cog._assign_ticket(guild, closing, staff, staff)
    async with conf.tickets() as tickets:
        tickets[str(closing.id)]["status"] = "open"
    async with cog._lock("close", closing.id):
        close_task = asyncio.create_task(cog._close_ticket(
            guild, closing, await record(closing), staff, await conf.all()))
        await asyncio.sleep(0)
        assign_task = asyncio.create_task(cog._assign_ticket(guild, closing, staff, staff))
        await asyncio.sleep(0)
    assert await close_task
    assert await assign_task
    assert (await record(closing))["claimed_by"] is None
    print("Nebenläufigkeit: genau eine Übernahme, keine Zuweisung während/nach Schließen – OK")

    # Ein langsamer alter Refresh darf weder die Zuständigkeit noch die Übernehmen-Buttons zurückdrehen.
    slow = await new_ticket()
    stale = await record(slow)
    slow_opening = await slow.fetch_message(stale["message_id"])
    fetch_entered, fetch_release, assignment_saved = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_fetch, original_send, original_edit = slow.fetch_message, slow.send, slow_opening.edit
    edits = []
    first_fetch = True

    async def delayed_fetch(message_id):
        nonlocal first_fetch
        if first_fetch:
            first_fetch = False
            fetch_entered.set()
            await fetch_release.wait()
        return await original_fetch(message_id)

    async def observed_send(*args, **kwargs):
        result = await original_send(*args, **kwargs)
        assignment_saved.set()
        return result

    async def observed_edit(**kwargs):
        edits.append((kwargs["embed"].footer.text,
                      {item.custom_id for item in kwargs["view"].children}))
        return await original_edit(**kwargs)

    slow.fetch_message, slow.send, slow_opening.edit = delayed_fetch, observed_send, observed_edit
    old_refresh = asyncio.create_task(cog._refresh_controls(guild, slow, stale, "de"))
    await asyncio.wait_for(fetch_entered.wait(), timeout=5)
    assign = asyncio.create_task(cog._assign_ticket(guild, slow, second, staff))
    await asyncio.wait_for(assignment_saved.wait(), timeout=5)
    assert (await record(slow))["claimed_by"] == second.id
    fetch_release.set()
    refresh_result, assign_result = await asyncio.wait_for(asyncio.gather(old_refresh, assign), timeout=5)
    assert refresh_result is None and assign_result is None
    assert len(edits) == 2
    assert all(second.display_name in footer and CID_UNCLAIM in buttons for footer, buttons in edits), edits
    assert second.display_name in slow_opening.embeds[0].footer.text
    slow.fetch_message, slow.send, slow_opening.edit = original_fetch, original_send, original_edit
    print("Steuerleisten: langsamer alter Refresh liest neue Zuständigkeit, feste Schreibreihenfolge ohne Deadlock – OK")

    # Native Discord-Mitgliedersuche: nur die öffnende Person; Rechte nach Auswahl erneut prüfen.
    responses = []
    button = Interaction(responses, guild, outsider, channel, CID_ASSIGN)
    await cog.on_interaction(button)
    assert button.response.view is None and responses
    button = Interaction([], guild, staff, channel, CID_ASSIGN)
    await cog.on_interaction(button)
    view = button.response.view
    assert isinstance(view, AssignmentView) and isinstance(view.select, discord.ui.UserSelect)
    view.select._values = [second]
    intruder = Interaction([], guild, second, channel)
    await view.select.callback(intruder)
    assert not intruder.edits and (await record(channel))["claimed_by"] is None
    saved_roles = staff.roles
    staff.roles = [guild.default_role]
    revoked = Interaction([], guild, staff, channel)
    await view.select.callback(revoked)
    assert not revoked.edits and (await record(channel))["claimed_by"] is None
    staff.roles = saved_roles
    selected = Interaction([], guild, staff, channel)
    await view.select.callback(selected)
    assert selected.edits and selected.edits[-1]["view"] is None
    assert (await record(channel))["claimed_by"] == second.id
    missing = Interaction([], guild, staff, channel)
    assert not await cog._assign_from_interaction(missing, 9999999)
    print("Discord-Buttons: native Suche, Schutz gegen fremde Auswahl, erneute Rechteprüfung – OK")

    # Private Threads erst zugänglich machen; fehlgeschlagener Beitritt darf keine Zuständigkeit speichern.
    text = await new_ticket()
    thread = AssignmentThread.from_text(text)
    guild.text_channels.remove(text)
    guild.threads.append(thread)
    original_lookup = guild.get_channel_or_thread
    guild.get_channel_or_thread = lambda cid: (
        next((item for item in guild.threads if item.id == cid), None) or original_lookup(cid)
    )
    thread.fail_join = True
    before = await claims()
    assert await cog._assign_ticket(guild, thread, second, staff)
    assert (await record(thread))["claimed_by"] is None and await claims() == before
    thread.fail_join = False
    thread.archived = True
    thread.locked = True
    async with conf.tickets() as tickets:
        tickets[str(thread.id)]["locked"] = True
    assert await cog._assign_ticket(guild, thread, second, staff) is None
    assert thread.joined == [second.id] and (await record(thread))["claimed_by"] == second.id
    assert not thread.archived and thread.locked, "Archivierung lösen, bestehende Sperre erhalten"
    print("Threads: vor Beitritt entarchiviert, Sperre erhalten, Fehler ohne gespeicherte Zuweisung/Statistik – OK")

    # Slash-/Textbefehle bestätigen auch den Erfolgsfall und benutzen denselben Kern.
    command_channel = await new_ticket()
    for command, args, expected in (
        (cog.ticket_assign, (second,), second.id),
        (cog.ticket_unclaim, (), None),
        (cog.ticket_claim, (), staff.id),
    ):
        ctx = Ctx(guild, command_channel, staff)
        await command.callback(cog, ctx, *args)
        assert ctx.deferred and ctx.sent and ctx.sent[-1][1].get("ephemeral")
        assert (await record(command_channel))["claimed_by"] == expected
    denied = Ctx(guild, command_channel, outsider)
    await cog.ticket_assign.callback(cog, denied, second)
    assert denied.sent and (await record(command_channel))["claimed_by"] == staff.id
    print("Befehle: assign/claim/unclaim mit Antwort, Übergabe und Rechteprüfung – OK")

    # Zuweisen ist Tagesgeschäft im Dashboard; die Zielprüfung bleibt bei zentraler Autorisierung bestehen.
    await wc.config.role_perms.set({"1000": {
        "1101": {"tickets": "operate"}, "1102": {"tickets": "view"},
    }})
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async def post(uid, member_id):
            headers = {"X-Test-User": str(uid)}
            page = await client.get("/cogs/tickets?guild=1000", headers=headers)
            html = await page.text()
            token = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
            response = await client.post("/cogs/tickets", headers=headers, allow_redirects=False,
                                         data={"csrf_token": token, "guild": "1000", "form": "ticket_assign",
                                               "channel_id": str(command_channel.id), "member_id": member_id})
            return response

        response = await post(12, str(second.id))
        assert response.status in (302, 303, 403)
        assert (await record(command_channel))["claimed_by"] == staff.id
        response = await post(11, str(second.id))
        assert response.status in (302, 303) and "ok=" in response.headers["Location"]
        assert (await record(command_channel))["claimed_by"] == second.id
        for invalid in ("not-an-id", "9999999", str(owner.id), str(guild.me.id), str(outsider.id)):
            response = await post(11, invalid)
            assert "err=" in response.headers.get("Location", ""), invalid
            assert (await record(command_channel))["claimed_by"] == second.id
        response = await post(11, "")
        assert "ok=" in response.headers["Location"]
        assert (await record(command_channel))["claimed_by"] is None
        # WebCore-Bedienen kann unabhängig von einer Discord-Supportrolle vergeben werden.
        await wc.config.role_perms.set({"1000": {"1102": {"tickets": "operate"}}})
        response = await post(12, str(second.id))
        assert "ok=" in response.headers["Location"]
        assert (await record(command_channel))["claimed_by"] == second.id
    finally:
        await client.close()
    print("Dashboard: Bedienen/Ansehen, unabhängige Webrechte, Freigabe und ungültige Ziele – OK")
    print("ALLE TICKET-ZUWEISUNGS-TESTS OK")


asyncio.run(main())
