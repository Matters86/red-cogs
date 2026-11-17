"""Optionale Everyone-Pings: neue Live-Sitzungen, Wiederholungen und Einstellungsrechte."""
import asyncio
import copy
import re
import types
from contextlib import asynccontextmanager
from urllib.parse import unquote_plus

from aiohttp.test_utils import TestClient, TestServer
import discord
import streamer_harness as S
from rc.streamer.providers import ProviderError


TRACE = []
_send = S.L._SendMixin.send
_edit = S.L.FakeMessage.edit


async def traced_send(channel, content=None, **kwargs):
    entry = {"kind": "send", "channel": channel.id, "content": content,
             "mentions": kwargs.get("allowed_mentions"), "success": False}
    TRACE.append(entry)
    message = await _send(channel, content, **kwargs)
    entry.update(success=True, message_id=message.id)
    return message


async def traced_edit(message, **kwargs):
    TRACE.append({"kind": "edit", "channel": message.channel.id,
                  "content": kwargs.get("content"), "mentions": kwargs.get("allowed_mentions")})
    return await _edit(message, **kwargs)


def ping_count():
    return sum(entry["kind"] == "send" and entry.get("success")
               and entry["content"] == "@everyone" and entry["mentions"] is not None
               and entry["mentions"].everyone for entry in TRACE)


def assert_narrow_mentions():
    for entry in TRACE:
        mentions = entry["mentions"]
        assert mentions is not None, entry
        assert mentions.users is False and mentions.roles is False and mentions.replied_user is False, entry
        if entry["kind"] == "edit" or entry["content"] != "@everyone":
            assert mentions.everyone is False, entry


@asynccontextmanager
async def world():
    wc, bot, app, cog = await S.make_app()
    guild = bot.guilds[0]
    await cog.config.guild(guild).clear()
    channel = guild.get_channel(1003)
    await cog.configure(guild, channel_id=channel.id, title_filter="DNP")
    TRACE.clear()
    box = types.SimpleNamespace(wc=wc, bot=bot, app=app, cog=cog, guild=guild,
                                channel=channel, clock=cog.test_clock, fake=cog.api)

    async def poll():
        box.clock[0] += 601
        await box.cog.poll_once()

    async def messages():
        found = []
        for record in (await box.cog.config.guild(guild).state()).values():
            destination = guild.get_channel(int(record.get("channel_id") or 0))
            message = destination._messages.get(int(record.get("message_id") or 0)) if destination else None
            if message is not None:
                found.append(message)
        return found

    box.poll, box.messages = poll, messages
    try:
        yield box
    finally:
        await box.cog.cog_unload()
        await wc.cog_unload()


async def main():
    S.L._SendMixin.send, S.L.FakeMessage.edit = traced_send, traced_edit
    checks = 0

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
        print("OK   " + message)

    try:
        async with world() as w:
            gc = w.cog.config.guild(w.guild)
            check(await gc.mention_everyone() is False, "Everyone-Erwähnung ist standardmäßig ausgeschaltet")
            source = await w.cog.add_source(w.guild, "twitch", "matters86")
            w.fake.go_live(source["key"], "first", title="DNP @everyone @here <@11> <@&1101>")
            await w.poll()
            assert_narrow_mentions()
            check(len(await w.messages()) == 1 and ping_count() == 0,
                  "Streamtitel lösen bei ausgeschalteter Option keine Everyone-, Rollen- oder Nutzerpings aus")
            first = (await w.messages())[0]
            await w.cog.configure(w.guild, mention_everyone=True)
            await w.poll()
            check(ping_count() == 0 and (await w.messages())[0].id == first.id,
                  "Einschalten pingt eine bereits laufende Meldung nicht nachträglich")

            w.fake.live.clear()
            await w.poll()
            w.fake.go_live(source["key"], "second")
            await w.poll()
            announced = (await w.messages())[0]
            check(ping_count() == 1 and announced.content == "@everyone",
                  "Neue API-Live-Sitzung erwähnt Everyone genau einmal nach ausdrücklichem Einschalten")
            await asyncio.gather(w.cog.poll_once(), w.cog.poll_once(), w.cog.poll_once())
            assert_narrow_mentions()
            check(ping_count() == 1 and announced.content == "@everyone",
                  "Aktualisierungen behalten den sichtbaren Text und erlauben keine weiteren Erwähnungen")

            await announced.delete()
            await w.poll()
            repaired_id = (await w.messages())[0].id
            check(ping_count() == 1 and repaired_id != announced.id,
                  "Wiederherstellen einer manuell gelöschten Meldung pingt denselben Stream nicht erneut")
            await w.cog.cog_unload()
            w.cog = await S.make_cog(w.bot, fake=w.fake)
            w.cog._now = lambda: w.clock[0]
            gc = w.cog.config.guild(w.guild)
            await w.poll()
            check(ping_count() == 1 and (await w.messages())[0].id == repaired_id,
                  "Cog-Neustart behält die laufende Ankündigung und ihren bereits verbrauchten Ping")

            w.fake.live[source["key"]][0]["title"] = "Ohne passenden Text"
            await w.poll()
            assert not await w.messages()
            w.fake.live[source["key"]][0]["title"] = "DNP wieder passend"
            await w.poll()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Wieder passende Titel desselben Streams erzeugen keinen zusätzlichen Everyone-Ping")
            w.fake.errors["twitch"] = ProviderError("Vorübergehender Twitch-Ausfall")
            await w.poll()
            w.fake.errors.clear()
            await w.poll()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Ein Plattformausfall wird weder zu Offline noch zu einer erneuten Benachrichtigung")
            await w.cog.toggle_source(w.guild, source["key"])
            await w.poll()
            await w.cog.toggle_source(w.guild, source["key"])
            await w.poll()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Pausieren und Fortsetzen desselben laufenden Streams pingt nicht erneut")
            await w.cog.configure(w.guild, channel_id=1001)
            await w.poll()
            check(ping_count() == 1 and (await w.messages())[0].channel.id == 1001,
                  "Verschieben in einen anderen Zielkanal erzeugt keinen zusätzlichen Ping")
            w.fake.live.clear()
            await w.poll()
            w.fake.go_live(source["key"], "third")
            await w.poll()
            assert_narrow_mentions()
            check(ping_count() == 2, "Ein tatsächlich neuer Stream darf erneut Everyone benachrichtigen")
            await w.cog.configure(w.guild, mention_everyone=False)
            w.fake.live.clear()
            await w.poll()
            w.fake.go_live(source["key"], "fourth-without-ping")
            await w.poll()
            check(ping_count() == 2 and len(await w.messages()) == 1,
                  "Abschalten lässt neue Streammeldungen weiterhin erscheinen, ohne Everyone zu benachrichtigen")

        async with world() as w:
            gc = w.cog.config.guild(w.guild)
            original_permissions = w.channel.permissions_for
            allowed = [False]

            def permissions(member):
                result = original_permissions(member)
                result.mention_everyone = allowed[0]
                return result

            w.channel.permissions_for = permissions
            before = copy.deepcopy(await gc.all())
            try:
                await w.cog.configure(w.guild, title_filter="Teiländerung", mention_everyone=True)
            except ValueError:
                pass
            else:
                raise AssertionError("Everyone ohne Bot-Berechtigung darf nicht aktiviert werden")
            check(await gc.all() == before, "Fehlendes Everyone-Recht verhindert jede Teiländerung der Einstellungen")
            allowed[0] = True
            await w.cog.configure(w.guild, mention_everyone=True)
            allowed[0] = False
            source = await w.cog.add_source(w.guild, "twitch", "matters86")
            w.fake.go_live(source["key"], "permission-lost")
            await w.poll()
            check(ping_count() == 0 and len(await w.messages()) == 1 and bool(await gc.last_error()),
                  "Nachträglich fehlendes Everyone-Recht lässt die Streammeldung zu und meldet den ausgebliebenen Ping")
            await w.cog.configure(w.guild, mention_everyone=False)
            check(await gc.mention_everyone() is False,
                  "Die Everyone-Option lässt sich auch nach Verlust des Erwähnungsrechts abschalten")
            allowed[0] = True
            await w.cog.configure(w.guild, mention_everyone=True)
            await w.poll()
            check(ping_count() == 0, "Zurückgekehrte Berechtigung pingt den bereits angekündigten Stream nicht rückwirkend")

        async with world() as w:
            await w.cog.configure(w.guild, mention_everyone=True)
            source = await w.cog.add_source(w.guild, "twitch", "matters86")
            w.fake.go_live(source["key"], "rejected-post")
            send = w.channel.send

            async def forbidden_send(*args, **kwargs):
                raise S.L.forbidden()

            w.channel.send = forbidden_send
            await w.poll()
            assert not await w.messages()
            w.channel.send = send
            await w.poll()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Eindeutig abgelehnter erster Sendversuch verbraucht den erlaubten Ping nicht")

        async with world() as w:
            await w.cog.configure(w.guild, mention_everyone=True)
            source = await w.cog.add_source(w.guild, "twitch", "matters86")
            w.fake.go_live(source["key"], "uncertain-post")
            send = w.channel.send

            async def accepted_then_error(*args, **kwargs):
                await send(*args, **kwargs)
                raise discord.HTTPException(S.L._resp(500, "Server Error"), {"message": "Unklarer Ausgang"})

            w.channel.send = accepted_then_error
            await w.poll()
            w.channel.send = send
            assert ping_count() == 1
            await w.cog.cog_unload()
            w.cog = await S.make_cog(w.bot, fake=w.fake)
            w.cog._now = lambda: w.clock[0]
            await w.poll()
            assert_narrow_mentions()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Unklarer Sendestatus mit Neustart übernimmt die vorhandene Nachricht ohne zweiten Ping")

        async with world() as w:
            role = S.L.H.Role(w.guild, 1118, "Streamer", 3)
            w.guild.roles.append(role)
            member = w.guild.get_member(11)
            member.roles.append(role)
            await w.cog.configure(w.guild, watched_role_id=role.id, mention_everyone=True)
            member.activities = (discord.Streaming(name="DNP Rolle", url="https://twitch.tv/matters86"),)
            await w.poll()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Automatische Rollenstreams unterstützen den optionalen Everyone-Ping")
            member.activities = (discord.Streaming(name="Anderes Projekt", url="https://twitch.tv/matters86"),)
            await w.poll()
            member.activities = (discord.Streaming(name="DNP zurück", url="https://twitch.tv/matters86"),)
            await w.poll()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Auch bei Rollenstreams bleibt ein Titelwechsel ohne erneuten Ping")
            member.activities = ()
            w.clock[0] += 1
            await w.cog.poll_once()
            member.activities = (discord.Streaming(name="DNP Reconnect", url="https://twitch.tv/matters86"),)
            w.clock[0] += 60
            await w.cog.poll_once()
            check(ping_count() == 1 and len(await w.messages()) == 1,
                  "Ein kurzer Discord-Streamingaussetzer erzeugt keinen zweiten Everyone-Ping")
            member.activities = ()
            await w.poll()
            member.activities = (discord.Streaming(name="DNP neuer Rollenstream", url="https://twitch.tv/matters86"),)
            await w.poll()
            assert_narrow_mentions()
            check(ping_count() == 2, "Nach bestätigtem Offline darf eine neue Rollen-Live-Sitzung wieder pingen")

        async with world() as w:
            gc = w.cog.config.guild(w.guild)
            await w.wc.config.role_perms.set({"1000": {
                "1101": {"streamer": "edit"}, "1102": {"streamer": "operate"}, "1104": {"streamer": "view"},
            }})
            client = TestClient(TestServer(w.app))
            await client.start_server()
            tokens = {}

            async def page(uid):
                response = await client.get("/cogs/streamer?guild=1000", headers={"X-Test-User": str(uid)})
                html = await response.text()
                token = re.search(r"name='csrf_token' value='([^']+)'", html)
                if token:
                    tokens[uid] = token.group(1)
                return html

            async def post(uid, values, *, token=None):
                if uid not in tokens:
                    await page(uid)
                response = await client.post("/cogs/streamer", headers={"X-Test-User": str(uid)},
                    data={"form": "settings", "guild": "1000", "channel_id": "1003",
                          "title_filter": "DNP", "enabled": "on",
                          "csrf_token": (tokens.get(uid) or tokens[1]) if token is None else token, **values},
                    allow_redirects=False)
                return response, unquote_plus(response.headers.get("Location", ""))

            try:
                html = await page(1)
                check("name='mention_everyone'" in html and "name='mention_settings'" in html and not TRACE,
                      "Dashboard bietet den optionalen Schalter, ohne beim Anzeigen eine Meldung zu senden")
                response, location = await post(11, {"mention_settings": "1", "mention_everyone": "on"})
                check(response.status == 302 and "ok=" in location and await gc.mention_everyone(),
                      "Bearbeiter können die Everyone-Option einschalten")
                response, location = await post(11, {})
                check(response.status == 302 and "ok=" in location and await gc.mention_everyone(),
                      "Ältere Formulare ohne Erwähnungsfeld erhalten die bestehende Option")
                before = copy.deepcopy(await gc.all())
                for uid in (12, 13):
                    response, location = await post(uid, {"mention_settings": "1"})
                    assert response.status == 403 or (response.status == 302 and (
                        "err=" in location or "Bearbeitungsrechte" in location or "Bearbeiten" in location)), location
                    assert await gc.all() == before
                check(True, "Bedienen und Ansehen können keinen Everyone-Ping aktivieren oder abschalten")
                response, _ = await post(11, {"mention_settings": "1"}, token="falsch")
                check(response.status == 400 and await gc.all() == before,
                      "Ungültiges CSRF-Token verändert die Ping-Einstellung nicht")
                response, location = await post(11, {"mention_settings": "1"})
                check(response.status == 302 and "ok=" in location and await gc.mention_everyone() is False,
                      "Nicht angekreuzter Schalter mit Formularmarker schaltet Everyone ausdrücklich aus")
            finally:
                await client.close()

        print(f"\n{checks} Everyone-Prüfungen bestanden.")
    finally:
        S.L._SendMixin.send, S.L.FakeMessage.edit = _send, _edit


if __name__ == "__main__":
    asyncio.run(main())
