"""Schnellantworten, Priorität und Team-Antwortuhr: Vorschau, Rechte, Rennen, Offline-Zeit."""
import asyncio
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import tc_harness as T
import discord
from aiohttp.test_utils import TestClient, TestServer
from rc.tickets.support import human_reply, render_reply, reset_response, set_waiting, support_due
from rc.tickets.replies import ReplyPicker, ReplyPreview
from rc.tickets.views import CID_PRIORITY, CID_REPLY


UTC = timezone.utc
HOUR = timedelta(hours=1)


class Response(T.Resp):
    view = None
    async def send_message(self, content=None, *, view=None, **kwargs):
        self.view = view
        await super().send_message(content, view=view, **kwargs)


class Interaction(T.Inter):
    def __init__(self, guild, user, channel, cid=""):
        self.events = []
        super().__init__(self.events, guild, user, channel, cid)
        self.response = Response(self.events)
        self.edits = []
    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


class Ctx:
    def __init__(self, guild, channel, author):
        self.guild, self.channel, self.author = guild, channel, author
        self.sent = []
        self.deferred = False
    async def defer(self, **kwargs):
        self.deferred = True
    async def send(self, content=None, **kwargs):
        self.sent.append(content)


def clock_tests():
    start = datetime(2026, 11, 6, 10, tzinfo=UTC)
    conf = {"response_targets_enabled": True, "response_target_hours": 24, "response_urgent_hours": 4}
    record = {"status": "open", "waiting_for": "team", "priority": "normal"}
    assert support_due(record, conf) is None, "Altbestand ohne nachgewiesenen Zyklus bekommt keine erfundene Frist"
    reset_response(record, start)
    assert support_due(record, conf) == start + 24 * HOUR
    human_reply(record, False, start + HOUR)
    human_reply(record, False, start + 2 * HOUR)
    assert support_due(record, conf) == start + 24 * HOUR, "Spam verschiebt die Antwortfrist nicht"
    set_waiting(record, "user", start + 3 * HOUR)
    assert record["response_wait_seconds"] == 3 * 3600 and support_due(record, conf) is None
    set_waiting(record, "team", start + 10 * HOUR)
    assert support_due(record, conf) == start + 31 * HOUR
    set_waiting(record, "user", start + 12 * HOUR)
    set_waiting(record, "team", start + 20 * HOUR)
    assert record["response_wait_seconds"] == 5 * 3600
    assert support_due(record, conf) == start + 39 * HOUR
    record["priority"] = "urgent"
    assert support_due(record, conf) == start + 19 * HOUR, "Prioritätswechsel verwendet bereits gewartete Zeit"
    human_reply(record, True, start + 21 * HOUR)
    assert not record["response_cycle_open"] and support_due(record, conf) is None
    human_reply(record, False, start + 30 * HOUR)
    assert support_due(record, conf) == start + 34 * HOUR
    human_reply(record, False, start + 31 * HOUR)
    assert support_due(record, conf) == start + 34 * HOUR
    assert not human_reply(record, True, start + 29 * HOUR)
    assert record["waiting_for"] == "team"
    assert support_due(record, dict(conf, response_targets_enabled=False)) is None
    assert support_due(dict(record, status="closed"), conf) is None
    assert support_due(dict(record, support_history_unconfirmed=True), conf) is None
    assert support_due(record, dict(conf, response_urgent_hours=float("nan"))) is None
    before = deepcopy(record)
    assert support_due(record, conf, now=start) == start + 34 * HOUR and record == before
    text = render_reply("{user} / {ticket} / {staff} / {signature} / {unknown}", {"num": 7},
        SimpleNamespace(display_name="Support"), SimpleNamespace(display_name="@everyone"), "{user}")
    assert text == "@everyone / 7 / Support / {user} / {unknown}", "Nur bekannte Platzhalter, eine einzige Ersetzung"
    print("Antwortuhr: Teamzeit, Pause/Restzeit, Priorität, neue Zyklen, Spam, veraltete Events und sichere Platzhalter – OK")


async def main():
    clock_tests()
    wc, bot, app, cog, _ = await T.make_app()
    guild = bot.guilds[0]
    owner, staff, other = (guild.get_member(uid) for uid in (13, 11, 12))
    gc = cog.config.guild(guild)
    await gc.support_roles.set([1101])
    await gc.category_open.set(guild.categories[0].id)
    await gc.max_open.set(30)
    panel = {"id": "support", "title": "Support", "reasons": [], "modal_questions": []}

    async def new_ticket():
        await gc.panels.set([panel])
        result = await cog.open_ticket(guild, owner, panel, None, {})
        assert result.status == "ok"
        return result.target

    async def record(channel):
        return (await gc.tickets())[str(channel.id)]

    channel = await new_ticket()
    assert not await gc.response_targets_enabled()
    assert cog.support_due(await record(channel), await gc.all()) is None
    start = datetime.now(UTC) - 8 * HOUR
    async with gc.tickets() as records:
        reset_response(records[str(channel.id)], start)
    await gc.response_targets_enabled.set(True)
    before = await record(channel)
    assert await cog._set_priority(guild, channel, "urgent", staff) is None
    assert (await record(channel))["response_wait_seconds"] == before["response_wait_seconds"]
    assert (await record(channel))["response_wait_started_at"] == before["response_wait_started_at"]
    assert await cog._set_priority(guild, channel, "normal", other)
    assert (await record(channel))["priority"] == "urgent"
    ctx = Ctx(guild, channel, staff)
    await cog.ticket_priority.callback(cog, ctx, "normal")
    assert ctx.deferred and ctx.sent and (await record(channel))["priority"] == "normal"
    priority = Interaction(guild, staff, channel, CID_PRIORITY)
    await cog.on_interaction(priority)
    assert priority.response.view is not None
    print("Priorität: Button/Befehl, Rollenrechte und keine Rücksetzung der Antwortuhr – OK")

    # Auswählen und Bearbeiten senden noch keine Nachricht in das Ticket.
    initial = len(channel._messages)
    picker_inter = Interaction(guild, staff, channel, CID_REPLY)
    await cog.on_interaction(picker_inter)
    picker = picker_inter.response.view
    assert isinstance(picker, ReplyPicker)
    picker.select._values = ["details"]
    selection = Interaction(guild, staff, channel)
    await picker.select.callback(selection)
    modal = selection.response.modal
    assert modal is not None and len(channel._messages) == initial
    modal.body._value = "Geprüfte Antwort @everyone <@&1101> {unknown}"
    preview_inter = Interaction(guild, staff, channel)
    await modal.on_submit(preview_inter)
    preview = preview_inter.response.view
    assert isinstance(preview, ReplyPreview) and len(channel._messages) == initial
    intruder = Interaction(guild, other, channel)
    await preview.send(intruder)
    assert len(channel._messages) == initial
    old_roles = staff.roles
    staff.roles = [guild.default_role]
    await preview.send(Interaction(guild, staff, channel))
    assert len(channel._messages) == initial and not preview.sending
    staff.roles = old_roles
    original_send = channel.send
    mentions = []
    async def capture_send(*args, **kwargs):
        mentions.append(kwargs.get("allowed_mentions"))
        return await original_send(*args, **kwargs)
    channel.send = capture_send
    await asyncio.gather(preview.send(Interaction(guild, staff, channel)),
                         preview.send(Interaction(guild, staff, channel)))
    sent = [message for message in channel._messages.values() if message.content == modal.body.value]
    assert len(sent) == 1 and len(channel._messages) == initial + 1
    assert mentions[-1].everyone is False and mentions[-1].roles is False and mentions[-1].users is False
    assert (await record(channel))["waiting_for"] == "user" and not (await record(channel))["response_cycle_open"]
    channel.send = original_send
    assert await cog._send_support_reply(guild, channel, staff, "x" * 2001)
    assert await cog._prepare_reply(guild, channel, other, "details") == ("Dafür brauchst du die Support-Rechte dieses Tickets.", None)
    await gc.quick_reply_signature.set("s" * 200)
    async with gc.quick_replies() as templates:
        templates.append({"id": "overflow", "label": "Zu lang", "text": "x" * 1950 + "{signature}"})
    assert (await cog._prepare_reply(guild, channel, staff, "overflow"))[0]
    print("Schnellantworten: native Auswahl/Bearbeitung/Vorschau ohne Senden, Reauth, ausdrücklicher einmaliger Versand ohne Pings – OK")

    # Schließen gewinnt, wenn die vorbereitete Antwort erst danach an den gemeinsamen Lock kommt.
    closing = await new_ticket()
    async with cog._lock("close", closing.id):
        close_task = asyncio.create_task(cog._close_ticket(guild, closing, await record(closing), staff, await gc.all()))
        await asyncio.sleep(0)
        send_task = asyncio.create_task(cog._send_support_reply(guild, closing, staff, "Darf nicht mehr gesendet werden"))
        await asyncio.sleep(0)
    assert await close_task and await send_task
    assert not any(message.content == "Darf nicht mehr gesendet werden" for message in closing._messages.values())
    assert support_due(await record(closing), await gc.all()) is None
    await cog._reopen_ticket(guild, closing, await record(closing), await gc.all())
    reopened = await record(closing)
    assert reopened["response_cycle_open"] and reopened["response_wait_seconds"] == 0
    assert support_due(reopened, await gc.all()) > datetime.now(UTC)

    # Offline-Antwort beendet den alten Zyklus, nächste Nutzerantwort startet den neuen.
    offline = await new_ticket()
    now = datetime.now(UTC)
    baseline = now - 8 * HOUR
    async with gc.tickets() as records:
        current = records[str(offline.id)]
        reset_response(current, baseline)
        current["created_at"] = current["support_synced_at"] = baseline.isoformat()
    events = [SimpleNamespace(author=author, created_at=when, webhook_id=None, type=discord.MessageType.default)
              for author, when in ((staff, now - 6 * HOUR), (owner, now - 3 * HOUR), (owner, now - HOUR))]
    original_history = offline.history
    async def offline_history(**kwargs):
        for message in events:
            yield message
    offline.history = offline_history
    await cog._mark_support_history_pending()
    assert support_due(await record(offline), await gc.all()) is None
    await cog._sync_support_history(guild, offline, await gc.all())
    assert support_due(await record(offline), await gc.all()) == now + 21 * HOUR
    offline.history = original_history
    offline.forbid.add("history")
    await cog._sync_support_history(guild, offline, await gc.all())
    assert (await record(offline))["support_history_unconfirmed"]
    assert support_due(await record(offline), await gc.all()) is None
    offline.forbid.clear()
    offline.history = offline_history
    await cog._retry_support_history()
    assert not (await record(offline))["support_history_unconfirmed"]
    print("Rennen/Neustart: Schließen vor Versand, neue Frist beim Wiederöffnen, Offline-Antworten und fehlende Leserechte – OK")

    # Dashboard: Vorlagen nur mit Bearbeiten; Vorschau und Senden nur mit Bedienen UND Ticket-Teamrechten.
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "operate"}, "1102": {"tickets": "view"}}})
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async def page(uid, suffix=""):
            response = await client.get("/cogs/tickets?guild=1000" + suffix, headers={"X-Test-User": str(uid)})
            html = await response.text()
            return html, re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
        async def post(uid, fields):
            _, token = await page(uid)
            return await client.post("/cogs/tickets", headers={"X-Test-User": str(uid)}, allow_redirects=False,
                data={"csrf_token": token, "guild": "1000", **fields})
        templates = await gc.quick_replies()
        response = await post(11, {"form": "quick_reply_save", "label": "Verboten", "text": "x"})
        assert await gc.quick_replies() == templates
        response = await post(1, {"form": "quick_reply_save", "label": "Neue Vorlage", "text": "Hallo {user}, Ticket {ticket}: {unknown}"})
        assert "ok=" in response.headers["Location"]
        new = next(item for item in await gc.quick_replies() if item["label"] == "Neue Vorlage")
        fresh = await new_ticket()
        initial = len(fresh._messages)
        response = await post(12, {"form": "ticket_reply_preview", "channel_id": str(fresh.id), "reply_id": new["id"]})
        assert len(fresh._messages) == initial
        response = await post(11, {"form": "ticket_reply_preview", "channel_id": str(fresh.id), "reply_id": new["id"]})
        assert "reply=" in response.headers["Location"] and len(fresh._messages) == initial
        html, _ = await page(11, "&reply=" + str(fresh.id))
        token = re.search(r"name='token' value='([^']+)'", html).group(1)
        assert "noch nicht gesendet" in html and "{unknown}" in html
        fields = {"form": "ticket_reply_send", "channel_id": str(fresh.id), "token": token, "text": "Bewusst veröffentlichte Antwort"}
        fresh.forbid.add("send")
        failed = await post(11, fields)
        assert "err=" in failed.headers["Location"] and len(fresh._messages) == initial
        fresh.forbid.clear()
        retry_html, _ = await page(11, "&reply=" + str(fresh.id))
        assert fields["text"] in retry_html, "Bearbeitung bleibt bei fehlgeschlagenem Versand erhalten"
        responses = await asyncio.gather(post(11, fields), post(11, fields))
        assert sum("ok=" in result.headers.get("Location", "") for result in responses) == 1
        assert sum(message.content == fields["text"] for message in fresh._messages.values()) == 1
        response = await post(11, {"form": "ticket_reply_send", "channel_id": str(fresh.id), "token": "forged", "text": "No"})
        assert "err=" in response.headers["Location"]
        response = await post(1, {"form": "quick_reply_delete", "reply_id": new["id"]})
        assert not any(item["id"] == new["id"] for item in await gc.quick_replies())
    finally:
        await client.close()
    print("Dashboard: administrative Vorlagen, getrennte Vorschau, editierbarer Text, einmalige Bestätigung und Rechte – OK")
    print("ALLE TICKET-SUPPORT-TESTS OK")


asyncio.run(main())
