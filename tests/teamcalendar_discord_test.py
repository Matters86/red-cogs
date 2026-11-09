"""Projektkalender in Discord: echte Views/Modals, gleiche Teamrechte und frische Freigaben."""
import asyncio
import copy

import tc_harness as T
import discord

from rc.teamcalendar.teamcalendar import TeamCalendar
from rc.teamcalendar import views as V
from rc.teamcalendar.models import format_local, parse_local


class Response:
    def __init__(self, interaction):
        self.interaction, self.done, self.modal = interaction, False, None

    def is_done(self):
        return self.done

    async def send_message(self, content=None, **kwargs):
        assert not self.done
        self.done = True
        self.interaction.capture("response", content, kwargs)

    async def defer(self, **kwargs):
        assert not self.done
        self.done = True
        self.interaction.deferred = kwargs

    async def send_modal(self, modal):
        assert not self.done
        self.done, self.modal = True, modal


class Followup:
    def __init__(self, interaction):
        self.interaction = interaction

    async def send(self, content=None, **kwargs):
        self.interaction.capture("followup", content, kwargs)


class Interaction:
    def __init__(self, guild, user, cid="", values=None, *, kind=discord.InteractionType.component):
        self.guild, self.user, self.type = guild, user, kind
        self.channel = guild.text_channels[0] if guild else None
        self.data = {"custom_id": cid}
        if values is not None:
            self.data["values"] = values
        self.response, self.followup = Response(self), Followup(self)
        self.messages, self.deferred = [], None

    def capture(self, kind, content, kwargs):
        assert kwargs.get("ephemeral") is True
        mentions = kwargs.get("allowed_mentions")
        assert mentions is not None and not mentions.everyone and not mentions.roles and not mentions.users
        T.L.validate_message(content, [kwargs["embed"]] if kwargs.get("embed") else [], kwargs.get("view"),
                             [kwargs["file"]] if kwargs.get("file") else [])
        self.messages.append({"kind": kind, "content": content, **kwargs})

    @property
    def last(self):
        return self.messages[-1] if self.messages else {}


def button(view, label):
    return next(child.custom_id for child in view.children if isinstance(child, discord.ui.Button) and child.label == label)


def fill(modal, **values):
    fields = {"title": modal.title_field, "start": modal.start_field, "end": modal.end_field,
              "location": modal.location_field, "description": modal.description_field}
    for key, field in fields.items():
        field._value = str(values.get(key, field.default or ""))


async def main():
    wc, bot, _, _, _ = await T.make_app()
    guild = bot.guilds[0]
    cog = TeamCalendar(bot)
    bot._cogs["TeamCalendar"] = cog
    gc = cog.config.guild(guild)
    await gc.team_roles.set([1101, 1102])
    now = 2_000_000_000
    cog._now = lambda: now
    start, end = now + 86400, now + 90000
    start_text, end_text = format_local(start, "Europe/Berlin"), format_local(end, "Europe/Berlin")
    user_a, user_b = guild.get_member(11), guild.get_member(12)

    async def act(uid, cid, values=None, target=guild):
        user = target.get_member(uid) if target is not None else user_a
        interaction = Interaction(target, user, cid, values)
        await V.handle_interaction(cog, interaction)
        return interaction

    async def details(eid, uid=11):
        interaction = await act(uid, f"teamcalendar:select:{uid}", [str(eid)])
        assert interaction.last.get("embed"), interaction.last
        return interaction

    async def create(uid, title):
        interaction = await act(uid, "teamcalendar:new")
        modal = interaction.response.modal
        assert modal and len(modal.children) == 5
        assert max(len(field.label) for field in modal.children) <= 45
        fill(modal, title=title, start=start_text, end=end_text, location="Team-Voice", description="Gemeinsam planen.")
        submit = Interaction(guild, guild.get_member(uid), kind=discord.InteractionType.modal_submit)
        await modal.on_submit(submit)
        assert submit.last.get("embed") and "gespeichert" in submit.last["content"], submit.last
        before_repeat = copy.deepcopy(await gc.events())
        repeated = Interaction(guild, guild.get_member(uid), kind=discord.InteractionType.modal_submit)
        await modal.on_submit(repeated)
        assert "bereits abgesendet" in repeated.last["content"] and await gc.events() == before_repeat
        return max((await gc.events()).values(), key=lambda event: int(event["id"])), submit

    try:
        board = V.build_board_view()
        assert board.timeout is None and board.is_persistent() and len(board.children) == 5
        assert {child.custom_id for child in board.children} == {"teamcalendar:new", "teamcalendar:list", "teamcalendar:export", "teamcalendar:pm:newtask", "teamcalendar:pm:tasks"}
        for cid in ("other:new", "teamcalendar:unknown", "teamcalendar:new:extra", "teamcalendar:delete:11"):
            interaction = await act(11, cid)
            assert not interaction.messages and interaction.response.modal is None
        interaction = Interaction(None, user_a, "teamcalendar:new")
        await V.handle_interaction(cog, interaction)
        assert "Discord-Server" in interaction.last["content"]
        for cid in ("teamcalendar:new", "teamcalendar:list", "teamcalendar:export"):
            denied = await act(13, cid)
            assert "Kalender-Team" in denied.last["content"]
        empty = await act(11, "teamcalendar:list")
        assert "Noch keine Termine" in empty.last["content"]

        event, _ = await create(11, "Projektbesprechung @everyone")
        event_b, _ = await create(12, "Planung des anderen Teammitglieds")
        assert event["created_by"] == 11 and event_b["created_by"] == 12
        shown = await details(event["id"], 12)
        edit = await act(12, button(shown.last["view"], "Bearbeiten"))
        modal = edit.response.modal
        original_start, original_end = event["start_ts"], event["end_ts"]
        # Explicit offsets keep the event unchanged if the server timezone is
        # changed while the modal is open (and during ambiguous autumn times).
        assert parse_local(modal.start_field.default, "UTC") == original_start
        await gc.timezone.set("UTC")
        fill(modal, title="Von Teammitglied B bearbeitet")
        submit = Interaction(guild, user_b, kind=discord.InteractionType.modal_submit)
        await modal.on_submit(submit)
        saved = (await gc.events())[event["id"]]
        assert saved["updated_by"] == 12 and saved["title"] == "Von Teammitglied B bearbeitet"
        assert saved["start_ts"] == original_start and saved["end_ts"] == original_end
        await gc.timezone.set("Europe/Berlin")
        print("Dauerhaftes Board, nur Teamzugriff, beide Teamrollen dürfen erstellen/bearbeiten, Zeitzonenwechsel im offenen Modal – OK")

        detail = await details(event["id"])
        rsvp_view = detail.last["view"]
        for label, expected in (("Zusagen", "yes"), ("Vielleicht", "maybe"), ("Absagen", "no")):
            answer = await act(11, button(rsvp_view, label))
            assert answer.last.get("embed")
            assert (await gc.events())[event["id"]]["participants"] == {"11": expected}
        await act(11, button(rsvp_view, "Antwort zurücknehmen"))
        assert not (await gc.events())[event["id"]]["participants"]
        forged = await act(12, button(rsvp_view, "Zusagen"))
        assert "andere" in forged.last["content"] and not (await gc.events())[event["id"]]["participants"]
        outsider_answer = await act(13, f"teamcalendar:rsvp:13:{event['id']}:yes")
        assert "Kalender-Team" in outsider_answer.last["content"]
        print("Zusagen, Vielleicht, Absagen und Rücknahme betreffen ausschließlich die eigene Person – OK")

        # No mutation happens before the explicit destructive confirmation.
        detail = await details(event["id"])
        cancel = await act(11, button(detail.last["view"], "Termin absagen"))
        assert (await gc.events())[event["id"]]["status"] == "scheduled"
        confirm_id = button(cancel.last["view"], "Absage bestätigen")
        other = await act(12, confirm_id)
        assert "andere" in other.last["content"]
        expired_id = confirm_id.rsplit(":", 1)[0] + f":{now - 1}"
        expired = await act(11, expired_id)
        assert "abgelaufen" in expired.last["content"]
        cancelled = await act(11, confirm_id)
        assert cancelled.last.get("embed") and (await gc.events())[event["id"]]["status"] == "cancelled"
        repeated = await act(11, confirm_id)
        assert "geändert" in repeated.last["content"]
        detail = await details(event["id"], 12)
        assert not any(child.custom_id.endswith(":yes") for child in detail.last["view"].children)
        await act(12, button(detail.last["view"], "Wieder öffnen"))
        detail = await details(event["id"], 12)
        await act(12, button(detail.last["view"], "Als erledigt markieren"))
        assert (await gc.events())[event["id"]]["status"] == "completed"
        detail = await details(event["id"], 12)
        delete = await act(12, button(detail.last["view"], "Löschen"))
        assert event["id"] in await gc.events()
        await act(12, button(delete.last["view"], "Endgültig löschen"))
        assert event["id"] not in await gc.events()
        assert event_b["id"] in await gc.events()
        print("Absagen/Löschen erst nach ausdrücklicher, nutzer- und versionsgebundener Bestätigung; Wiederöffnen und Erledigen – OK")

        # Revoke a role after a modal/confirmation was opened, then submit.
        initial = copy.deepcopy(await gc.events())
        pending = await act(11, "teamcalendar:new")
        fill(pending.response.modal, title="Darfnicht", start=start_text, end=end_text)
        old_roles = list(user_a.roles)
        user_a.roles = [guild.default_role]
        denied = Interaction(guild, user_a, kind=discord.InteractionType.modal_submit)
        await pending.response.modal.on_submit(denied)
        assert "Kalender-Team" in denied.last["content"] and await gc.events() == initial
        user_a.roles = old_roles
        pending = await act(11, "teamcalendar:new")
        fill(pending.response.modal, title="Falsche Person", start=start_text, end=end_text)
        wrong_person = Interaction(guild, user_b, kind=discord.InteractionType.modal_submit)
        await pending.response.modal.on_submit(wrong_person)
        assert "anderen Person" in wrong_person.last["content"] and await gc.events() == initial
        foreign = Interaction(bot.guilds[1], bot.guilds[1].get_member(11), kind=discord.InteractionType.modal_submit)
        await pending.response.modal.on_submit(foreign)
        assert "anderen Server" in foreign.last["content"] and await gc.events() == initial
        # The cog-disabled gate also applies to modals opened before disabling.
        original_disabled = bot.cog_disabled_in_guild
        async def disabled(*args):
            return True
        bot.cog_disabled_in_guild = disabled
        try:
            for cid in ("teamcalendar:new", "teamcalendar:list", "teamcalendar:export"):
                denied = await act(11, cid)
                assert "deaktiviert" in denied.last["content"]
            denied = Interaction(guild, user_a, kind=discord.InteractionType.modal_submit)
            await pending.response.modal.on_submit(denied)
            assert "deaktiviert" in denied.last["content"] and await gc.events() == initial
        finally:
            bot.cog_disabled_in_guild = original_disabled

        shown = await details(event_b["id"])
        pending_edit = await act(11, button(shown.last["view"], "Bearbeiten"))
        fill(pending_edit.response.modal, title="Veraltet")
        current = (await gc.events())[event_b["id"]]
        await cog.update_event(guild, user_b, event_b["id"], {"title": "Neuere Bearbeitung", "start": start_text, "end": end_text}, revision=current["revision"])
        stale = Interaction(guild, user_a, kind=discord.InteractionType.modal_submit)
        await pending_edit.response.modal.on_submit(stale)
        assert "geändert" in stale.last["content"]
        assert (await gc.events())[event_b["id"]]["title"] == "Neuere Bearbeitung"
        print("Nachträglicher Rechteentzug, fremde Formularperson/-Guild, deaktivierter Cog und veraltetes Bearbeitungsformular – OK")

        # More than 25 entries remain reachable, and all Discord component limits
        # are checked by capture() on the actual rendered objects.
        current = (await gc.events())[event_b["id"]]
        many = {str(i): {**copy.deepcopy(current), "id": str(i), "title": "Projekt " + "ü" * 100,
                         "project": "x" * 80, "start_ts": start + i * 60, "end_ts": end + i * 60}
                for i in range(100, 161)}
        await gc.events.set(many)
        first = await act(11, "teamcalendar:list")
        first_view = first.last["view"]
        select = next(child for child in first_view.children if isinstance(child, discord.ui.Select))
        assert len(select.options) == 25 and "Seite 1/3" in first.last["content"]
        second = await act(11, button(first_view, "Weiter"))
        last = await act(11, button(second.last["view"], "Weiter"))
        options = next(child for child in last.last["view"].children if isinstance(child, discord.ui.Select)).options
        assert len(options) == 11 and "Seite 3/3" in last.last["content"]
        assert next(child for child in last.last["view"].children if getattr(child, "label", "") == "Weiter").disabled
        assert max(len(o.label) for o in select.options) <= 100 and max(len(o.description) for o in select.options) <= 100
        all_seen = {o.value for o in select.options} | {o.value for o in next(c for c in second.last["view"].children if isinstance(c, discord.ui.Select)).options} | {o.value for o in options}
        assert all_seen == set(many)
        assert "Ungültige Kalenderseite" in (await act(11, "teamcalendar:list:11:nope")).last["content"]
        assert "existiert nicht" in (await act(11, "teamcalendar:select:11", ["missing"])).last["content"]

        # Worst-size notes and participant names still fit a real embed.
        rich = {**current, "title": "T" * 100, "description": "D" * 2000, "location": "O" * 200,
                "project": "P" * 80, "participants": {str(5000 + i): status for i in range(90) for status in [list(V.RSVP)[i % 3]]}}
        for i in range(90):
            guild.members.append(T.H.Member(guild, 5000 + i, "*_" * 16, []))
        embed = V.event_embed(guild, rich, await gc.all())
        T.L.validate_message(None, [embed], None, [])
        assert all(len(field.value) <= 1024 for field in embed.fields)
        assert all("weitere" in field.value for field in embed.fields if field.name.startswith(("Zusagen", "Vielleicht", "Absagen")))
        assert len(embed) <= 6000
        assert "Bei dir: <t:" in embed.fields[0].value

        exported = await act(11, "teamcalendar:export")
        file = exported.last["file"]
        blob = file.fp.read()
        assert file.filename == "projektkalender-1000.ics" and blob.startswith(b"BEGIN:VCALENDAR")
        assert blob.count(b"BEGIN:VEVENT") == len(many)
        assert not T.ROLE_LOG and not T.L.LOG, "Private Bedienung darf weder Rollen vergeben noch Nachrichten öffentlich posten"
        print("61 Termine erreichbar, sichere Discord-Limits für große Inhalte/Teilnehmerlisten, ephemerer Kalenderexport ohne öffentliche Nachrichten – OK")
        print("teamcalendar_discord_test: PASS")
    finally:
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
