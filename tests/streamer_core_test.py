"""Aktive Streammeldungen: Filter, Offline-Cleanup, Fehler, Neustart und Parallelität."""
import asyncio
import copy

import discord
import streamer_harness as S
from rc.streamer.providers import ProviderError
from rc.webcore.backup import strip_secrets


async def main():
    wc, bot, _app, cog = await S.make_app()
    guild, second_guild = bot.guilds
    gc = cog.config.guild(guild)
    channel = guild.get_channel(guild.id + 3)
    fake, clock = cog.api, cog.test_clock
    checks = 0
    mentions = []
    original_send = channel.send

    async def recorded_send(*args, **kwargs):
        mentions.append(kwargs.get("allowed_mentions"))
        return await original_send(*args, **kwargs)

    channel.send = recorded_send

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
        print("OK   " + message)

    async def poll():
        clock[0] += 601
        await cog.poll_once()

    async def messages():
        found = {}
        for key, record in (await gc.state()).items():
            destination = guild.get_channel(int(record.get("channel_id") or 0))
            if destination is not None and record.get("message_id"):
                message = destination._messages.get(int(record["message_id"]))
                if message is not None:
                    found[key] = message
        return found

    async def expect_invalid(**values):
        before = copy.deepcopy(await gc.all())
        try:
            await cog.configure(guild, **values)
        except (ValueError, ProviderError):
            pass
        else:
            raise AssertionError("Ungültige Einstellung akzeptiert: " + str(values))
        assert await gc.all() == before

    try:
        await expect_invalid(channel_id=second_guild.id + 1)
        await expect_invalid(channel_id=guild.id + 50)
        await expect_invalid(title_filter="x" * 101)
        check(True, "Fremde/ungeeignete Kanäle und überlange Filter ohne Teiländerung abgelehnt")

        await cog.configure(guild, channel_id=channel.id, title_filter="DNP")
        twitch = await cog.add_source(guild, "twitch", "matters86")
        youtube = await cog.add_source(guild, "youtube", "@projektteam")
        await cog.add_source(guild, "twitch", "https://twitch.tv/matters86")
        check(len(await gc.sources()) == 2 and twitch["key"] != youtube["key"],
              "Quellen pro Plattform gespeichert, dieselbe Quelle wird nicht doppelt angelegt")
        foreign = S.L.FakeMessage(channel, guild.get_member(11), "Diese normale Nachricht bleibt stehen")
        channel._messages[foreign.id] = foreign

        fake.go_live(twitch["key"], title="Anderes Projekt")
        fake.go_live(youtube["key"], "video-1", title="dNp Teamabend")
        await poll()
        current = await messages()
        check(len(current) == 1 and next(iter(current.values())).embed is not None,
              "Titelfilter gilt plattformübergreifend ohne Beachtung der Groß-/Kleinschreibung")
        first_ids = {key: message.id for key, message in current.items()}
        await asyncio.gather(cog.poll_once(), cog.poll_once(), cog.poll_once())
        check({key: message.id for key, message in (await messages()).items()} == first_ids,
              "Gleichzeitige Prüfungen erzeugen keine doppelten Meldungen")

        fake.live[twitch["key"]][0]["title"] = "DNP @everyone <script>alert(1)</script>"
        await poll()
        check(len(await messages()) == 2 and all(m is not None and not m.everyone and not m.users
                                                and not m.roles and not m.replied_user for m in mentions),
              "Titelwechsel fügt passenden laufenden Stream hinzu; Ankündigungen lösen keine Pings aus")
        fake.live[youtube["key"]][0]["title"] = "Ein anderer Server"
        await poll()
        check(len(await messages()) == 1 and foreign.id in channel._messages,
              "Nicht mehr passender Titel entfernt nur die verwaltete Streammeldung")
        fake.live[youtube["key"]][0]["title"] = "DNP wieder da"
        await poll()
        check(len(await messages()) == 2,
              "Derselbe Stream wird nach erneuter Filterübereinstimmung wieder angezeigt")

        # Gespeicherte Nachrichten-IDs genügen nach Cog-Neuerstellung für Fortsetzung.
        before_ids = {key: message.id for key, message in (await messages()).items()}
        restarted = await S.make_cog(bot, fake=fake)
        restarted._now = lambda: clock[0]
        cog = restarted
        gc = cog.config.guild(guild)
        await poll()
        check({key: message.id for key, message in (await messages()).items()} == before_ids,
              "Neustart setzt vorhandene Ankündigungen fort statt erneut zu posten")

        # Ein Plattformfehler ist keine Offline-Aussage und blockiert die andere nicht.
        fake.errors["twitch"] = ProviderError("Twitch ist vorübergehend nicht erreichbar")
        fake.live.pop(youtube["key"], None)
        await poll()
        current = await messages()
        check(len(current) == 1 and any(twitch["key"] in key for key in current),
              "API-Ausfall erhält Twitch-Meldung, während YouTube offline korrekt aufgeräumt wird")
        fake.errors.clear()

        manual = next(iter(current.values()))
        await manual.delete()
        await poll()
        await poll()
        check(len(await messages()) == 1 and next(iter((await messages()).values())).id != manual.id,
              "Manuell gelöschte aktive Ankündigung wird wiederhergestellt")

        channel.forbid.add("delete")
        fake.live.pop(twitch["key"], None)
        await poll()
        check(bool(await gc.state()) and len(await messages()) == 1,
              "Fehlgeschlagene Löschung verliert die gespeicherte Nachricht nicht")
        channel.forbid.discard("delete")
        await poll()
        check(not await gc.state() and foreign.id in channel._messages,
              "Offline-Löschung wird wiederholt und fremde Nachrichten bleiben erhalten")

        channel.forbid.add("send")
        fake.go_live(twitch["key"], "stream-2")
        await poll()
        check(not await messages(), "Fehlende Senderechte erzeugen keine Phantom-Ankündigung")
        channel.forbid.discard("send")
        await poll()
        check(len(await messages()) == 1, "Nach Wiederherstellung der Rechte wird der aktive Stream gepostet")

        # Kanalwechsel löscht zuerst die alte Meldung; kein stilles Vergessen bei 403.
        replacement = guild.get_channel(guild.id + 1)
        channel.forbid.add("delete")
        await cog.configure(guild, channel_id=replacement.id)
        await poll()
        check(len(await messages()) == 1 and not replacement._messages,
              "Kanalwechsel wartet bei Löschfehler auf Bereinigung der alten Meldung")
        channel.forbid.discard("delete")
        await poll()
        check(len(await messages()) == 1 and all(m.channel.id == replacement.id for m in (await messages()).values()),
              "Kanalwechsel verschiebt aktive Anzeige nach erfolgreicher Bereinigung")

        await cog.toggle_source(guild, twitch["key"])
        await poll()
        check(not await messages(), "Pausieren entfernt die laufende Ankündigung")
        await cog.toggle_source(guild, twitch["key"])
        await poll()
        check(len(await messages()) == 1, "Fortsetzen zeigt den weiter laufenden Stream erneut an")
        await cog.configure(guild, title_filter="")
        fake.live[twitch["key"]][0]["title"] = "Ohne D-N-P Filtertext"
        await poll()
        check(len(await messages()) == 1, "Leerer Titelfilter erlaubt jeden aktiven Stream")
        await cog.remove_source(guild, twitch["key"])
        await poll()
        check(twitch["key"] not in await gc.sources() and not await messages(),
              "Entfernen einer Quelle bereinigt ihre Ankündigung")

        fake.go_live(youtube["key"], "video-2")
        await poll()
        assert len(await messages()) == 1
        await cog.configure(guild, enabled=False)
        await poll()
        check(not await messages() and youtube["key"] in await gc.sources(),
              "Serverweit deaktivieren löscht Meldungen und behält die eingerichteten Quellen")

        # Discord kann einen Post annehmen und trotzdem einen HTTP-Fehler zurückliefern.
        fake.live.clear()
        await cog.configure(guild, enabled=True, channel_id=channel.id, title_filter="DNP")
        await cog.add_source(guild, "twitch", "matters86")
        fake.go_live(twitch["key"], "accepted-with-500")
        real_send = channel.send
        ambiguous_messages = []

        async def accepted_then_error(*args, **kwargs):
            message = await real_send(*args, **kwargs)
            ambiguous_messages.append(message)
            raise discord.HTTPException(S.L._resp(500, "Server Error"), {"message": "Unklarer Sendeausgang"})

        channel.send = accepted_then_error
        try:
            await poll()
        finally:
            channel.send = real_send
        pending = list((await gc.state()).values())
        assert len(pending) == 1 and pending[0].get("pending") and not pending[0].get("message_id")
        channel.forbid.add("history")
        try:
            await poll()
        finally:
            channel.forbid.discard("history")
        pending = list((await gc.state()).values())
        check(len(pending) == 1 and pending[0].get("pending") and not pending[0].get("message_id")
              and len(ambiguous_messages) == 1,
              "Vorübergehend fehlendes Leserecht erhält nach unklarem Sendeausgang die offene Absicht")
        await poll()
        current = await messages()
        check(len(ambiguous_messages) == 1 and len(current) == 1
              and next(iter(current.values())).id == ambiguous_messages[0].id
              and not next(iter((await gc.state()).values())).get("pending"),
              "Nach akzeptiertem Post mit HTTP500 wird die vorhandene Meldung übernommen statt doppelt gepostet")

        fake.live.clear()
        await poll()
        fake.go_live(twitch["key"], "accepted-before-cancel")
        cancelled_messages = []

        async def accepted_then_cancel(*args, **kwargs):
            message = await real_send(*args, **kwargs)
            cancelled_messages.append(message)
            raise asyncio.CancelledError()

        channel.send = accepted_then_cancel
        try:
            try:
                await poll()
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("Abbruch muss die laufende Abfrage verlassen")
        finally:
            channel.send = real_send
        pending = list((await gc.state()).values())
        assert len(pending) == 1 and pending[0].get("pending") and not pending[0].get("message_id")
        restarted = await S.make_cog(bot, fake=fake)
        restarted._now = lambda: clock[0]
        cog = restarted
        gc = cog.config.guild(guild)
        await poll()
        current = await messages()
        check(len(cancelled_messages) == 1 and len(current) == 1
              and next(iter(current.values())).id == cancelled_messages[0].id,
              "Neustart nach Abbruch übernimmt einen bereits gesendeten Post aus dem Nachrichtenverlauf")

        original_streams = fake.streams
        before_ids = {key: message.id for key, message in current.items()}

        async def incomplete(provider, sources, *, known=None):
            if provider == "twitch":
                return {}
            return await original_streams(provider, sources, known=known)

        fake.streams = incomplete
        try:
            await poll()
        finally:
            fake.streams = original_streams
        check(cog.status["twitch"]["state"] == "error"
              and {key: message.id for key, message in (await messages()).items()} == before_ids,
              "Unvollständiger Plattform-Snapshot ist ein Fehler und löscht keine laufende Meldung")

        # Die allgemeine Sicherung entfernt als Secrets klassifizierte Schlüsselwörter.
        await gc.state.set(strip_secrets(await gc.state()))
        await gc.sources.set(strip_secrets(await gc.sources()))
        await poll()
        check({key: message.id for key, message in (await messages()).items()} == before_ids,
              "Wiederhergestellte Sicherung setzt Meldungen trotz entfernter Hilfsfelder ohne Duplikat fort")

        # Auch eine manuell gestartete Abfrage muss vor dem Schließen des Clients enden.
        entered, release = asyncio.Event(), asyncio.Event()
        original_streams = fake.streams
        before_posts = sum(entry[0] == "send" for entry in S.L.LOG)

        async def held_streams(provider, sources, *, known=None):
            entered.set()
            await release.wait()
            return await original_streams(provider, sources, known=known)

        fake.streams = held_streams
        manual_poll = asyncio.create_task(cog.poll_once())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            await asyncio.wait_for(cog.cog_unload(), timeout=2)
            check(manual_poll.cancelled() and fake.closed
                  and sum(entry[0] == "send" for entry in S.L.LOG) == before_posts,
                  "Entladen bricht auch manuelle Abfragen während wartender API ab und schließt den Client ohne weitere Posts")
        finally:
            release.set()
            if not manual_poll.done():
                manual_poll.cancel()
            await asyncio.gather(manual_poll, return_exceptions=True)
            fake.streams = original_streams
        print(f"\n{checks} Streamer-Core-Prüfungen bestanden.")
    finally:
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
