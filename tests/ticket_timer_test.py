"""Ticket-Timer: Aktivität, Abbruch, Neustart, Rechte und gemeinsamer Schließpfad."""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import tc_harness as T
import discord
from aiohttp.test_utils import TestClient, TestServer


UTC = timezone.utc
DAY = timedelta(hours=24)


class Ctx:
    def __init__(self, guild, channel, author):
        self.guild, self.channel, self.author = guild, channel, author
        self.sent = []
        self.deferred = []

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


class TimerThread(T.L._SendMixin, discord.Thread):
    """Thread-Nachbau mit demselben Discord-Send/History-Backend wie normale Testkanäle."""
    guild = None
    category_id = None

    @classmethod
    def from_text(cls, channel):
        result = object.__new__(cls)
        T.L._init_common(result, channel.guild, channel.id, channel.name, None, 0)
        result.parent_id = channel.guild.get_channel(1002).id
        result.archived = False
        result.locked = False
        result._messages = channel._messages
        for msg in result._messages.values():
            msg.channel = result
        return result


def message(guild, channel, author, created_at, *, webhook_id=None, kind=None):
    return SimpleNamespace(
        guild=guild, channel=channel, author=author, created_at=created_at,
        webhook_id=webhook_id,
        type=discord.MessageType.default if kind is None else kind,
    )


def history_since(channel, messages=(), *, fail=False):
    """Nur die Discord-Abfrage nach Offline-Aktivität ersetzen; Transcripts bleiben echt."""
    original = channel.history

    async def history(*, limit=100, oldest_first=False, after=None, **kwargs):
        if after is None:
            async for item in original(limit=limit, oldest_first=oldest_first, **kwargs):
                yield item
            return
        if fail:
            raise T.L.forbidden()
        for item in sorted(messages, key=lambda m: m.created_at, reverse=True):
            if item.created_at > after:
                yield item

    channel.history = history


async def main():
    wc, bot, app, cog, _ = await T.make_app()
    from rc.tickets.tickets import Tickets
    from rc.tickets.views import CID_AUTOCLOSE, CID_KEEP_OPEN, build_controls_view

    guild = bot.guilds[0]
    gc = cog.config.guild(guild)
    owner, staff, other = (guild.get_member(i) for i in (13, 11, 15))
    await gc.support_roles.set([1101])
    await gc.category_open.set(guild.categories[0].id)
    await gc.max_open.set(30)
    panel = {"id": "timer", "title": "Support", "reasons": [], "modal_questions": []}

    async def new_ticket():
        result = await cog.open_ticket(guild, owner, panel, None, {})
        assert result.status == "ok", result
        return result.target

    async def record(channel):
        return (await gc.tickets())[str(channel.id)]

    async def overdue(channel):
        now = datetime.now(UTC)
        async with gc.tickets() as tickets:
            tickets[str(channel.id)].update(
                auto_close_started_at=(now - 2 * DAY).isoformat(),
                auto_close_at=(now - timedelta(seconds=1)).isoformat(),
            )
        return await record(channel)

    async def click(channel, user, cid):
        responses = []
        await cog.on_interaction(T.Inter(responses, guild, user, channel, cid))
        assert responses, "Jeder Button muss eine Antwort senden"
        return responses

    channel = await new_ticket()
    assert not (await record(channel)).get("auto_close_at")
    assert CID_AUTOCLOSE in {c.custom_id for c in build_controls_view("de").children}
    assert CID_KEEP_OPEN in {
        c.custom_id for c in build_controls_view("de", auto_close=True).children
    }

    before = datetime.now(UTC)
    assert await cog._set_ticket_autoclose(guild, channel, True, staff, await gc.all())
    rec = await record(channel)
    started = datetime.fromisoformat(rec["auto_close_started_at"])
    deadline = datetime.fromisoformat(rec["auto_close_at"])
    assert before <= started <= datetime.now(UTC)
    assert deadline - started == DAY

    activity = datetime.now(UTC) + timedelta(minutes=5)
    await cog.on_message(message(guild, channel, owner, activity))
    assert datetime.fromisoformat((await record(channel))["auto_close_at"]) == activity + DAY
    await cog.on_message(message(guild, channel, staff, activity + timedelta(minutes=1),
                                 kind=discord.MessageType.reply))
    latest = (await record(channel))["auto_close_at"]
    assert datetime.fromisoformat(latest) == activity + timedelta(minutes=1) + DAY
    await cog.on_message(message(guild, channel, owner, activity - timedelta(hours=1)))
    assert (await record(channel))["auto_close_at"] == latest, "Verspätete Events verkürzen nie den Timer"
    bot_author = SimpleNamespace(id=999, bot=True)
    for author, webhook, kind in (
        (bot_author, None, discord.MessageType.default),
        (owner, 123, discord.MessageType.default),
        (owner, None, discord.MessageType.pins_add),
    ):
        await cog.on_message(message(guild, channel, author, activity + DAY,
                                     webhook_id=webhook, kind=kind))
    assert (await record(channel))["auto_close_at"] == latest

    await click(channel, other, CID_KEEP_OPEN)
    assert (await record(channel))["auto_close_at"] == latest, "Fremde dürfen Timer nicht abbrechen"
    await gc.user_can_close.set(False)
    await click(channel, owner, CID_KEEP_OPEN)
    assert not (await record(channel)).get("auto_close_at"), "Ersteller darf sein Ticket offen halten"
    await click(channel, owner, CID_AUTOCLOSE)
    assert not (await record(channel)).get("auto_close_at"), "Start beachtet user_can_close"
    await click(channel, other, CID_AUTOCLOSE)
    assert not (await record(channel)).get("auto_close_at")
    await click(channel, staff, CID_AUTOCLOSE)
    assert (await record(channel)).get("auto_close_at")
    await click(channel, staff, CID_KEEP_OPEN)
    await gc.user_can_close.set(True)
    await click(channel, owner, CID_AUTOCLOSE)
    assert (await record(channel)).get("auto_close_at")
    await click(channel, owner, CID_KEEP_OPEN)
    await cog.on_message(message(guild, channel, owner, activity + 2 * DAY))
    assert not (await record(channel)).get("auto_close_at"), "Nachricht aktiviert abgebrochenen Timer nicht"
    restarted = Tickets(bot)
    assert not (await restarted._get_record(guild, channel.id)).get("auto_close_at")
    await restarted._check_autoclose()
    assert (await record(channel))["status"] == "open"
    print("Timer: 24h ab Start/letzter Nachricht, Bots/Webhooks/System ausgenommen, Rechte und Abbruch – OK")

    # Beide Befehle benutzen die gleichen Rechte und Timer wie die persistenten Buttons.
    for command in (cog.ticket_autoclose, cog.ticket_keepopen):
        outside = Ctx(guild, guild.get_channel(1001), staff)
        await command.callback(cog, outside)
        assert outside.sent, "Außerhalb eines Tickets muss der Befehl verständlich antworten"
    denied = Ctx(guild, channel, other)
    await cog.ticket_autoclose.callback(cog, denied)
    assert denied.sent and not (await record(channel)).get("auto_close_at")
    staff_ctx = Ctx(guild, channel, staff)
    await cog.ticket_autoclose.callback(cog, staff_ctx)
    assert (await record(channel)).get("auto_close_at")
    denied.sent.clear()
    await cog.ticket_keepopen.callback(cog, denied)
    assert denied.sent and (await record(channel)).get("auto_close_at")
    await gc.user_can_close.set(False)
    await cog.ticket_keepopen.callback(cog, Ctx(guild, channel, owner))
    assert not (await record(channel)).get("auto_close_at")
    owner_ctx = Ctx(guild, channel, owner)
    await cog.ticket_autoclose.callback(cog, owner_ctx)
    assert owner_ctx.sent and not (await record(channel)).get("auto_close_at")
    await gc.user_can_close.set(True)
    await cog.ticket_autoclose.callback(cog, owner_ctx)
    assert (await record(channel)).get("auto_close_at")
    await cog.ticket_keepopen.callback(cog, staff_ctx)
    assert not (await record(channel)).get("auto_close_at")
    print("Befehle: autoclose/keepopen, Ersteller-/Teamrechte, Ablehnung und Nicht-Ticket – OK")

    # Abgelaufene gespeicherte Timer werden nach einem Neustart aufgegriffen.
    expired = await new_ticket()
    history_since(expired)
    await overdue(expired)
    closed_before = (await gc.stats())["closed"]
    await restarted._check_autoclose()
    assert (await record(expired))["status"] == "closed"
    assert (await gc.stats())["closed"] == closed_before + 1
    expired_num = (await record(expired))["num"]
    assert any(tr["num"] == expired_num for tr in await gc.transcripts())
    await restarted._check_autoclose()
    assert (await gc.stats())["closed"] == closed_before + 1, "Kein zweites Transcript/Statistik bei Wiederholung"

    # Offline-Nachrichten verlängern; eine jüngere Bot-Nachricht darf Menschen nicht verdecken.
    offline = await new_ticket()
    now = datetime.now(UTC)
    human_time = now - timedelta(hours=2)
    history_since(offline, [message(guild, offline, owner, human_time),
                            message(guild, offline, bot_author, now - timedelta(minutes=1))])
    await overdue(offline)
    await restarted._check_autoclose()
    rec = await record(offline)
    assert rec["status"] == "open"
    assert datetime.fromisoformat(rec["auto_close_at"]) == human_time + DAY

    unreadable = await new_ticket()
    history_since(unreadable, fail=True)
    await overdue(unreadable)
    await restarted._check_autoclose()
    assert (await record(unreadable))["status"] == "open", "Ohne Verlauf keine sichere Inaktivitätsentscheidung"
    print("Neustart/Downtime: Fristen erhalten, Offline-Nachrichten berücksichtigt, Lesefehler sicher – OK")

    # Schon gelesene Timer-Snapshots sind ungültig, sobald Nachricht/Abbruch sie ändern.
    racing = await new_ticket()
    history_since(racing)
    stale = await overdue(racing)
    await cog.on_message(message(guild, racing, owner, datetime.now(UTC)))
    assert not await cog._close_ticket(guild, racing, stale, guild.me, await gc.all(), inactivity=True)
    assert (await record(racing))["status"] == "open"
    stale = await overdue(racing)
    assert await cog._set_ticket_autoclose(guild, racing, False, owner, await gc.all())
    assert not await cog._close_ticket(guild, racing, stale, guild.me, await gc.all(), inactivity=True)

    # Der wartende Schließversuch muss die Änderung erneut prüfen, nachdem er den Lock bekommt.
    stale = await overdue(racing)
    async with cog._lock("close", racing.id):
        cancel = asyncio.create_task(cog._set_ticket_autoclose(
            guild, racing, False, owner, await gc.all()))
        await asyncio.sleep(0)
        close = asyncio.create_task(cog._close_ticket(
            guild, racing, stale, guild.me, await gc.all(), inactivity=True))
        await asyncio.sleep(0)
    assert await cancel
    assert not await close
    assert (await record(racing))["status"] == "open"

    # Nachrichten während der Discord-Verlaufsabfrage müssen trotz gehaltenem Lock gewinnen.
    during_fetch = await new_ticket()
    await cog._set_ticket_autoclose(guild, during_fetch, True, staff, await gc.all())
    stale_fetch = await overdue(during_fetch)
    entered, release = asyncio.Event(), asyncio.Event()
    original_history = during_fetch.history

    async def delayed_history(*, after=None, **kwargs):
        if after is not None:
            entered.set()
            await release.wait()
            return
        async for item in original_history(**kwargs):
            yield item

    during_fetch.history = delayed_history
    close = asyncio.create_task(cog._close_ticket(
        guild, during_fetch, stale_fetch, guild.me, await gc.all(), inactivity=True))
    await asyncio.wait_for(entered.wait(), timeout=5)
    activity_task = asyncio.create_task(cog.on_message(
        message(guild, during_fetch, owner, datetime.now(UTC))))
    await asyncio.sleep(0)
    release.set()
    assert not await close
    await activity_task
    assert (await record(during_fetch))["status"] == "open"

    # Sofort schließen ignoriert zukünftige Timer und bleibt idempotent.
    await cog._set_ticket_autoclose(guild, racing, True, staff, await gc.all())
    rec = await record(racing)
    assert await cog._close_ticket(guild, racing, rec, staff, await gc.all())
    assert (await record(racing))["status"] == "closed"
    assert not (await record(racing)).get("auto_close_at")
    assert not await cog._close_ticket(guild, racing, rec, staff, await gc.all())
    assert not await cog._set_ticket_autoclose(guild, racing, True, staff, await gc.all())
    await cog._reopen_ticket(guild, racing, await record(racing), await gc.all())
    assert (await record(racing))["status"] == "open"
    assert not (await record(racing)).get("auto_close_at")
    print("Nebenläufigkeit: aktuelle Daten unter Lock, Sofort-Schließen und Wiederöffnen – OK")

    # Tagesgeschäft im Dashboard: Bedienen genügt, Ansehen ändert keine Timer.
    await wc.config.role_perms.set({"1000": {
        "1101": {"tickets": "operate"}, "1102": {"tickets": "view"},
    }})
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        for user_id, allowed in ((12, False), (11, True)):
            headers = {"X-Test-User": str(user_id)}
            response = await client.get("/cogs/tickets?guild=1000", headers=headers)
            html = await response.text()
            token = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
            for form, enabled in (("ticket_autoclose", True), ("ticket_keepopen", False)):
                before = (await record(racing)).get("auto_close_at")
                response = await client.post("/cogs/tickets", headers=headers, allow_redirects=False,
                                             data={"csrf_token": token, "guild": "1000",
                                                   "form": form, "channel_id": str(racing.id)})
                if allowed:
                    assert response.status in (302, 303), response.status
                    assert "ok=" in response.headers["Location"], response.headers["Location"]
                    assert bool((await record(racing)).get("auto_close_at")) == enabled
                else:
                    assert response.status in (302, 303, 403), response.status
                    assert (await record(racing)).get("auto_close_at") == before
    finally:
        await client.close()
    print("Dashboard: Timer starten/abbrechen mit Bedienen, Ansehen bleibt schreibgeschützt – OK")

    # Private Threads und Forum-Beiträge sind beides Discord-Threads und werden archiviert/gesperrt.
    original_lookup = guild.get_channel_or_thread
    guild.get_channel_or_thread = lambda cid: (
        next((thread for thread in guild.threads if thread.id == cid), None) or original_lookup(cid)
    )
    for mode in ("thread", "forum"):
        text = await new_ticket()
        thread = TimerThread.from_text(text)
        guild.text_channels.remove(text)
        guild.threads.append(thread)
        async with gc.tickets() as tickets:
            tickets[str(thread.id)]["type"] = mode
        history_since(thread)
        await overdue(thread)
        await cog._check_autoclose()
        assert (await record(thread))["status"] == "closed"
        assert thread.archived and thread.locked, mode
        assert any(tr["channel_name"] == thread.name for tr in await gc.transcripts())

    deleted = await new_ticket()
    history_since(deleted)
    deleted_num = (await record(deleted))["num"]
    await overdue(deleted)
    await gc.delete_on_close.set(True)
    await cog._check_autoclose()
    assert str(deleted.id) not in await gc.tickets()
    assert guild.get_channel(deleted.id) is None
    assert any(tr["num"] == deleted_num for tr in await gc.transcripts())
    await gc.delete_on_close.set(False)
    print("Schließpfad: Thread/Forum archiviert+gesperrt, Löschen mit erhaltenem Transcript – OK")

    # Wiederherstellung bestückt alte Steuerleisten und füllt den Aktivitätscache vor dem Timerlauf.
    lifecycle_channel = await new_ticket()
    await cog._set_ticket_autoclose(guild, lifecycle_channel, True, staff, await gc.all())
    lifecycle = Tickets(bot)
    assert lifecycle_channel.id not in lifecycle._active_timer_channels
    await lifecycle._restore_ticket_controls()
    assert lifecycle_channel.id in lifecycle._active_timer_channels
    opening = await lifecycle_channel.fetch_message((await record(lifecycle_channel))["message_id"])
    assert CID_KEEP_OPEN in {button.custom_id for button in opening.view.children}
    unarmed_opening = await channel.fetch_message((await record(channel))["message_id"])
    assert CID_AUTOCLOSE in {button.custom_id for button in unarmed_opening.view.children}
    await lifecycle.cog_load()
    task = lifecycle._autoclose_loop.get_task()
    assert task is not None and lifecycle._autoclose_loop.is_running()
    await asyncio.sleep(0)
    await lifecycle.cog_unload()
    await asyncio.gather(task, return_exceptions=True)
    assert not lifecycle._autoclose_loop.is_running()
    print("Lebenszyklus: alte Steuerleisten/aktive Timer wiederhergestellt, Schleife gestartet/beendet – OK")
    print("ALLE TICKET-TIMER-TESTS OK")


asyncio.run(main())
