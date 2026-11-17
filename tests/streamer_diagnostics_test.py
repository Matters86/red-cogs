"""Streamer: empfangene Präsenz diagnostizieren und veraltete Aktivitäten sicher neu laden."""
import asyncio
import contextlib
import copy
import json
import re
import types
from urllib.parse import unquote_plus

import discord
from aiohttp.test_utils import TestClient, TestServer

import streamer_harness as S


def stream(title="DNP – frischer Discord-Status"):
    return discord.Streaming(name=title, url="https://www.twitch.tv/matters86")


def with_activities(member, activities):
    fresh = copy.copy(member)
    fresh.activities = tuple(activities)
    return fresh


def has_private_fields(value):
    keys = {"member_id", "member_ids", "member_name", "discord_user_id", "discord_name",
            "activity_types", "diagnostics", "presences", "snapshots"}
    if isinstance(value, dict):
        return any(key in keys or has_private_fields(child) for key, child in value.items())
    if isinstance(value, list):
        return any(has_private_fields(child) for child in value)
    return False


class Ctx:
    def __init__(self, guild, author, *, slash=False):
        self.guild, self.author = guild, author
        self.interaction = types.SimpleNamespace() if slash else None
        self.clean_prefix = "!"
        self.sent, self.deferred = [], []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def reply(self, content=None, **kwargs):
        return await self.send(content, **kwargs)

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    @contextlib.asynccontextmanager
    async def typing(self):
        yield


async def main():
    wc, bot, app, cog = await S.make_app()
    guild = bot.guilds[0]
    gc = cog.config.guild(guild)
    clock = cog.test_clock
    watched = S.L.H.Role(guild, 1118, "Streamer-Diagnose", 3)
    guild.roles.append(watched)
    lena, tom, kai = (guild.get_member(uid) for uid in (11, 12, 13))
    lena.roles.append(watched)
    tom.roles.append(watched)
    channel = guild.get_channel(1003)
    checks = 0
    query_calls = []
    answers = {}
    query_failure = [None]

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
        print("OK   " + message)

    async def query_members(*, user_ids, limit, presences, cache):
        query_calls.append({"ids": list(user_ids), "limit": limit,
                            "presences": presences, "cache": cache})
        if query_failure[0] is not None:
            raise query_failure[0]
        return [answers[uid] for uid in user_ids if uid in answers]

    guild.query_members = query_members

    def set_answers(lena_activities=(), tom_activities=()):
        answers.clear()
        answers.update({lena.id: with_activities(lena, lena_activities),
                        tom.id: with_activities(tom, tom_activities)})

    async def tracked_messages():
        result = {}
        for key, record in (await gc.state()).items():
            destination = guild.get_channel(int(record.get("channel_id") or 0))
            message = destination._messages.get(int(record.get("message_id") or 0)) if destination else None
            if message is not None:
                result[key] = message
        return result

    async def diag(member):
        return cog.member_diagnostics(guild, member, await gc.all())

    async def reload_cog():
        nonlocal cog, gc
        replacement_api = copy.deepcopy(cog.api)
        await cog.cog_unload()
        cog = await S.make_cog(bot, wc, fake=replacement_api)
        cog._now = lambda: clock[0]
        cog.test_clock = clock
        gc = cog.config.guild(guild)

    client = None
    pending = None
    try:
        # Diagnose unterscheidet Voraussetzungen, Discord-Aktivität und Titelfilter.
        check(await gc.presence_refresh_enabled() is False,
              "Gezieltes Nachladen ist vor der ersten ausdrücklichen Aktualisierung ausgeschaltet")
        item = await diag(lena)
        check(not item["has_role"] and bool(item["reason"]),
              "Diagnose zeigt eine noch nicht eingerichtete Rollenbeobachtung")
        for field in ("twitch_client_id", "twitch_client_secret", "youtube_api_key"):
            await getattr(cog.config, field).set("")
        await cog.configure(guild, channel_id=channel.id, title_filter="DNP", watched_role_id=watched.id)
        item = await diag(kai)
        check(not item["has_role"] and item["accepted"] == 0,
              "Diagnose erkennt Mitglieder außerhalb der beobachteten Rolle")
        item = await diag(lena)
        check(item["has_role"] and item["streaming"] == 0 and item["accepted"] == 0
              and bool(item["reason"]) and bool(item["hint"]),
              "Fehlende empfangene Aktivität erhält einen konkreten Diagnosehinweis")

        private_custom = "PRIVATE-CUSTOM-STATUS-MUST-NOT-LEAK"
        private_game = "PRIVATE-GAME-DETAILS-MUST-NOT-LEAK"
        lena.activities = (discord.CustomActivity(name=private_custom), discord.Game(name=private_game))
        item = await diag(lena)
        encoded = json.dumps(item, ensure_ascii=False)
        check(item["streaming"] == 0 and item["accepted"] == 0 and item["activity_types"]
              and private_custom not in encoded and private_game not in encoded,
              "Normale Aktivitäten werden als Typen erklärt, private Status- und Spieldetails bleiben verborgen")
        unsafe = "https://untrusted.invalid/live?api_key=PRIVATE-URL-SECRET"
        lena.activities = (discord.Streaming(name="DNP Test", url=unsafe),)
        item = await diag(lena)
        encoded = json.dumps(item, ensure_ascii=False)
        check(item["streaming"] == 1 and item["accepted"] == 0
              and unsafe not in encoded and "PRIVATE-URL-SECRET" not in encoded,
              "Nicht unterstützter Streaminglink wird ohne rohe URL oder Query-Secret diagnostiziert")
        lena.activities = (stream("Anderer Titel"),)
        item = await diag(lena)
        check(item["streaming"] == 1 and item["accepted"] == 1 and item["filter_matches"] == 0,
              "Diagnose trennt einen gültigen Stream von einem nicht passenden Titel")
        lena.activities = (stream(),)
        item = await diag(lena)
        check(item["accepted"] == 1 and item["filter_matches"] == 1 and "DNP" in item["title"]
              and item["url"] == "https://www.twitch.tv/matters86",
              "Unterstützter Stream mit passendem Titel wird vollständig erkannt")

        # Reale Regression: Der Discord-Cache kann leer bleiben, obwohl eine frische
        # Gateway-Abfrage dieselbe Person mit Streamingaktivität zurückliefert.
        lena.activities = tom.activities = ()
        set_answers((stream(),))
        entered, release = asyncio.Event(), asyncio.Event()

        async def first_delayed_query(**kwargs):
            answer = await query_members(**kwargs)
            entered.set()
            await release.wait()
            return answer

        guild.query_members = first_delayed_query
        pending = asyncio.create_task(cog.refresh_role_presences(guild))
        await asyncio.wait_for(entered.wait(), 2)
        before_removal = copy.copy(lena)
        before_removal.roles = list(lena.roles)
        lena.roles.remove(watched)
        await cog.on_member_update(before_removal, lena)
        await cog.on_presence_update(before_removal, lena)
        without_role = copy.copy(lena)
        without_role.roles = list(lena.roles)
        lena.roles.append(watched)
        await cog.on_member_update(without_role, lena)
        release.set()
        await asyncio.wait_for(pending, 2)
        pending = None
        await cog.poll_once()
        check(not await tracked_messages() and cog.presence_refresh.activities(lena) == (),
              "Rollenverlust und Wiederzuweisung während der ersten Abfrage verwerfen die überholte Live-Antwort")
        guild.query_members = query_members
        clock[0] += 31
        result = await cog.refresh_role_presences(guild)
        await cog.poll_once()
        first = await tracked_messages()
        check(result["ok"] and len(first) == 1 and lena.activities == () and tom.activities == ()
              and query_calls and all(c["presences"] and not c["cache"]
                                      and c["limit"] == 100 and len(c["ids"]) <= 100 for c in query_calls),
              "Gezieltes Neuladen erkennt den frischen Stream ohne den Discord-Cache zu manipulieren")
        check(await gc.presence_refresh_enabled() is True and not cog.api.calls and not has_private_fields(await gc.all())
              and not has_private_fields(await cog.config.all()),
              "Rollen-Aktualisierung braucht keine Plattformzugänge und speichert keine Mitgliedersnapshots")
        before_calls = len(query_calls)
        await cog.refresh_role_presences(guild)
        await cog.poll_once()
        check(len(query_calls) == before_calls and len(await tracked_messages()) == 1,
              "Wiederholtes Klicken innerhalb der Abkühlzeit erzeugt weder Gateway-Spam noch doppelte Meldungen")

        # Der Modus überlebt einen echten Cog-Unload, die Mitgliedersnapshots nicht.
        preserved_ids = {message.id for message in (await tracked_messages()).values()}
        await reload_cog()
        status = cog.role_watch_status(guild, await gc.all())
        await cog.cleanup_guild(guild)
        check(await gc.presence_refresh_enabled() is True and not cog.presence_refresh.enabled(guild)
              and not status["ready"] and status["warning"] and lena.activities == ()
              and {message.id for message in (await tracked_messages()).values()} == preserved_ids,
              "Nach Cog-Reload bleiben der aktivierte Modus und die alte Meldung bis zur frischen Gateway-Prüfung erhalten")
        before_calls = len(query_calls)
        await cog.poll_once()
        check(len(query_calls) == before_calls + 1 and cog.presence_refresh.enabled(guild)
              and {message.id for message in (await tracked_messages()).values()} == preserved_ids,
              "Erster Poll nach Reload fragt Discord erneut ab und übernimmt die vorhandene Live-Meldung ohne Doppelpost")
        set_answers()
        await reload_cog()
        before_calls = len(query_calls)
        await cog.poll_once()
        check(len(query_calls) == before_calls + 1 and not await tracked_messages(),
              "Frische Offline-Antwort beim ersten Poll nach Reload räumt die alte Meldung auf")

        clock[0] += 61
        set_answers()
        await cog.poll_once()
        check(not await tracked_messages(),
              "Die nächste frische Offline-Antwort entfernt die zuvor neu erkannte Ankündigung")
        clock[0] += 61
        set_answers((stream(),))
        await cog.poll_once()
        assert len(await tracked_messages()) == 1
        first_ids = {m.id for m in (await tracked_messages()).values()}
        query_failure[0] = asyncio.TimeoutError("PRIVATE-ERROR-DETAIL-MUST-NOT-LEAK")
        clock[0] += 61
        await cog.poll_once()
        status = cog.role_watch_status(guild, await gc.all())
        check(not status["ready"] and status["warning"]
              and "PRIVATE-ERROR-DETAIL" not in status["warning"]
              and {m.id for m in (await tracked_messages()).values()} == first_ids,
              "Fehlgeschlagene Präsenzabfrage ist unbekannt und löscht keine aktive Ankündigung")
        query_failure[0] = None
        clock[0] += 61
        answers.pop(tom.id)
        await cog.poll_once()
        status = cog.role_watch_status(guild, await gc.all())
        check(not status["ready"] and {m.id for m in (await tracked_messages()).values()} == first_ids,
              "Unvollständige Antwort für weiterhin vorhandene Rollenmitglieder ist kein Offline-Beweis")
        clock[0] += 61
        set_answers((stream(),))
        await cog.poll_once()
        assert cog.role_watch_status(guild, await gc.all())["ready"]
        # Beide echten Cachezustände sind leer; allein das Query-Overlay war live.
        before = with_activities(lena, ())
        after = with_activities(lena, ())
        cog._wake.clear()
        await cog.on_presence_update(before, after)
        await cog.poll_once()
        check(cog._wake.is_set() and not await tracked_messages(),
              "Ein neuer Presence-Event überschreibt auch bei identischem leerem Cache das zuvor geladene Live-Overlay")

        # Die Diagnoseantwort wird nicht in einem gewöhnlichen Kanal veröffentlicht.
        lena.activities = ()
        dms = []

        async def dm(content=None, **kwargs):
            dms.append((content, kwargs))
        lena.send = dm
        ctx = Ctx(guild, lena)
        await cog.streamer_diagnose.callback(cog, ctx)
        check(bool(dms) and all(lena.display_name not in str(content) for content, _ in ctx.sent),
              "Textbefehl sendet die Mitgliedsdiagnose per Direktnachricht")
        slash = Ctx(guild, lena, slash=True)
        await cog.streamer_diagnose.callback(cog, slash)
        check(slash.sent and all(kwargs.get("ephemeral") for _content, kwargs in slash.sent),
              "Slash-Diagnose ist ausschließlich für den aufrufenden Nutzer sichtbar")

        async def blocked_dm(*_args, **_kwargs):
            raise S.L.forbidden()
        lena.send = blocked_dm
        blocked = Ctx(guild, lena)
        await cog.streamer_diagnose.callback(cog, blocked)
        check(blocked.sent and all(lena.display_name not in str(content) for content, _ in blocked.sent),
              "Gesperrte Direktnachrichten führen nur zu einem Hinweis und keiner öffentlichen Diagnose")

        # WebCore prüft den neuen operativen POST genauso wie bestehende Aktionen.
        await wc.config.role_perms.set({"1000": {
            "1101": {"streamer": "edit"}, "1102": {"streamer": "operate"},
            "1104": {"streamer": "view"},
        }})
        client = TestClient(TestServer(app))
        await client.start_server()
        tokens = {}

        async def page(uid):
            response = await client.get("/cogs/streamer?guild=1000", headers={"X-Test-User": str(uid)})
            text = await response.text()
            match = re.search(r"name=['\"]csrf_token['\"] value=['\"]([^'\"]+)['\"]", text)
            if match:
                tokens[uid] = match.group(1)
            return response, text

        async def post(uid, *, guild_id="1000", token=None):
            if uid not in tokens:
                await page(uid)
            response = await client.post("/cogs/streamer", headers={"X-Test-User": str(uid)},
                data={"guild": guild_id, "form": "presence_refresh",
                      "csrf_token": token if token is not None else tokens.get(uid, next(iter(tokens.values()), ""))},
                allow_redirects=False)
            return response, unquote_plus(response.headers.get("Location", ""))

        response, operator_html = await page(12)
        _, viewer_html = await page(13)
        check(response.status == 200 and "Discord-Status neu laden" in operator_html
              and "presence_refresh" in operator_html and "Was sieht der Bot" in operator_html
              and "presence_refresh" not in viewer_html and "Was sieht der Bot" not in viewer_html,
              "Nur Bedienen/Bearbeiten sieht die detaillierte Mitgliedsdiagnose und den Aktualisieren-Button")
        clock[0] += 61
        set_answers((stream(),))
        response, location = await post(12)
        check(response.status == 302 and "ok=" in location and len(await tracked_messages()) == 1,
              "Bedienen lädt den Discord-Status über den geschützten WebCore-POST neu")
        previous_calls = len(query_calls)
        before = copy.deepcopy(await gc.all())
        response, location = await post(13)
        rejected = response.status == 403 or (response.status == 302 and (
            "err=" in location or "Keine Bearbeitungsrechte" in location or "Recht Bearbeiten" in location))
        check(rejected and len(query_calls) == previous_calls and await gc.all() == before,
              "Nur Ansicht darf weder Statusabfragen auslösen noch gespeicherte Daten verändern")
        response, _ = await post(12, token="ungueltig")
        assert response.status == 400 and len(query_calls) == previous_calls
        response, location = await post(12, guild_id="2000")
        check(response.status in {302, 403} and len(query_calls) == previous_calls,
              "Falsches CSRF und fremde Guilds können keine Präsenzabfrage auslösen")

        # Ein Rollenwechsel während einer wartenden Gateway-Antwort verwirft alte Daten.
        clock[0] += 61
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed_query(**kwargs):
            entered.set()
            await release.wait()
            return await query_members(**kwargs)

        guild.query_members = delayed_query
        pending = asyncio.create_task(cog.refresh_role_presences(guild))
        await asyncio.wait_for(entered.wait(), 2)
        await cog.configure(guild, watched_role_id=0)
        release.set()
        await asyncio.wait_for(pending, 2)
        pending = None
        await cog.poll_once()
        check(not await tracked_messages() and not cog.presence_refresh.enabled(guild),
              "Spät eintreffende Antwort nach Rollenwechsel belebt keine alte Beobachtung wieder")
        guild.query_members = query_members
        set_answers()
        for index in range(205):
            member = S.L.H.Member(guild, 50000 + index, f"Batchmitglied {index}", [watched])
            member.activities = ()
            guild.members.append(member)
            answers[member.id] = with_activities(member, ())
        await cog.configure(guild, watched_role_id=watched.id)
        previous_calls = len(query_calls)
        result = await cog.refresh_role_presences(guild)
        batches = query_calls[previous_calls:]
        check(result["ok"] and len(batches) == 3
              and all(len(batch["ids"]) <= 100 and batch["presences"] for batch in batches)
              and {uid for batch in batches for uid in batch["ids"]} == set(answers),
              "Große Rollen werden vollständig in Gateway-Anfragen mit höchstens 100 Mitgliedern aufgeteilt")

        # Ein bereits überholter Aufruf darf nach dem Scopewechsel nicht einmal
        # eine neue Gateway-Anfrage starten.
        await gc.presence_refresh_enabled.set(False)
        await reload_cog()
        ticket = cog.presence_refresh.checkpoint(guild)
        cog.presence_refresh.invalidate(guild)
        previous_calls = len(query_calls)
        result = await cog.presence_refresh.refresh(guild, watched, force=True, checkpoint=ticket)
        check(not result["ok"] and len(query_calls) == previous_calls
              and not cog.presence_refresh.enabled(guild),
              "Veralteter Checkpoint nach Rollenwechsel startet keine neue Präsenzabfrage")

        # Auch Await-Punkte vor dem eigentlichen Query müssen vom Unload erfasst
        # werden, sonst könnte ein verspäteter Aufruf den Modus wieder aktivieren.
        entered, release = asyncio.Event(), asyncio.Event()
        original_disabled = bot.cog_disabled_in_guild

        async def delayed_disabled(_cog, _guild):
            entered.set()
            await release.wait()
            return False

        bot.cog_disabled_in_guild = delayed_disabled
        try:
            previous_calls = len(query_calls)
            pending = asyncio.create_task(cog.refresh_role_presences(guild))
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(cog.cog_unload(), 2)
            check(pending.cancelled() and len(query_calls) == previous_calls
                  and await gc.presence_refresh_enabled() is False,
                  "Unload bricht bereits in der Vorprüfung wartende Aktualisierungen vor Query und Modusschreiben ab")
            pending = None
        finally:
            bot.cog_disabled_in_guild = original_disabled
            release.set()
        print(f"\n{checks} Streamer-Diagnose-Prüfungen bestanden.")
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        if client is not None:
            await client.close()
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
