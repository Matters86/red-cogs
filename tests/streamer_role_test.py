"""Discord-Rollen automatisch beobachten: Präsenz, Filter, Rechte, Deduplikation und Ausfälle."""
import asyncio
import copy
import json

import discord
import streamer_harness as S
from rc.streamer.providers import ProviderError


async def main():
    wc, bot, _app, cog = await S.make_app()
    guild = bot.guilds[0]
    gc = cog.config.guild(guild)
    channel = guild.get_channel(1003)
    fake, clock = cog.api, cog.test_clock
    watched = S.L.H.Role(guild, 1118, "Beobachtete Streamer", 3)
    replacement = S.L.H.Role(guild, 1119, "Andere Streamer", 3)
    guild.roles.extend((watched, replacement))
    lena, tom, kai, mia = (guild.get_member(uid) for uid in (11, 12, 13, 14))
    lena.roles.append(watched)
    tom.roles.append(watched)
    kai.roles.append(replacement)
    checks = 0

    def activity(title, url):
        return discord.Streaming(name=title, url=url)

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
            message = destination._messages.get(int(record.get("message_id") or 0)) if destination else None
            if message is not None:
                found[key] = message
        return found

    async def expect_invalid_role(role_id):
        before = copy.deepcopy(await gc.all())
        try:
            await cog.configure(guild, channel_id=channel.id, title_filter="Neu", watched_role_id=role_id)
        except ValueError:
            pass
        else:
            raise AssertionError("Ungültige Rolle akzeptiert: " + str(role_id))
        assert await gc.all() == before

    try:
        for role_id in (1000, 2101, 999999):
            await expect_invalid_role(role_id)
        check(True, "Everyone, fremde und unbekannte Rollen werden ohne Teiländerung abgelehnt")
        for field in ("twitch_client_id", "twitch_client_secret", "youtube_api_key"):
            await getattr(cog.config, field).set("")
        await cog.configure(guild, channel_id=channel.id, title_filter="DNP", watched_role_id=watched.id)
        lena.activities = (activity("Anderer Server", "https://twitch.tv/matters86"),)
        tom.activities = (activity("dNp YouTube", "https://www.youtube.com/watch?v=ABCdef12345"),)
        await poll()
        status = cog.role_watch_status(guild, await gc.all())
        check(status["role_id"] == watched.id and status["role_name"] == watched.name
              and status["members"] == 2 and status["ready"] and not status["warning"],
              "Rollenübersicht meldet eingerichtete Rolle und verfügbaren Mitgliedercache")
        check(len(await messages()) == 1 and not fake.calls,
              "Discord-Streamingstatus wird ohne Plattform-API-Zugang erkannt und nach Titel gefiltert")

        lena.activities = (activity("DNP Twitch", "https://twitch.tv/matters86"),)
        await poll()
        check(len(await messages()) == 2, "Passender Twitch-Status ergänzt die automatische YouTube-Anzeige")
        mia.roles.append(watched)
        mia.activities = lena.activities
        kai.activities = (activity("DNP außerhalb der Rolle", "https://twitch.tv/outsider"),)
        guild.me.roles.append(watched)
        guild.me.activities = (activity("DNP Bot", "https://twitch.tv/botstream"),)
        guild.members.append(guild.me)
        await poll()
        check(len(await messages()) == 2,
              "Gleicher Stream bei mehreren Rollenmitgliedern erscheint einmal; Bots und Außenstehende bleiben außen vor")

        before_ids = {key: message.id for key, message in (await messages()).items()}
        lena.activities = (activity("DNP Neuer Titel", "https://twitch.tv/matters86"),)
        mia.activities = lena.activities
        await poll()
        check({key: message.id for key, message in (await messages()).items()} == before_ids,
              "Titelwechsel eines Rollenstreams bearbeitet vorhandene Meldungen ohne Duplikate")
        state_text = json.dumps(await gc.state(), ensure_ascii=False)
        forbidden_fields = {"user_id", "discord_user_id", "member_id", "member_ids", "owner_id", "discord_name", "nickname"}

        def has_private_fields(value):
            if isinstance(value, dict):
                return any(key in forbidden_fields or has_private_fields(child) for key, child in value.items())
            if isinstance(value, list):
                return any(has_private_fields(child) for child in value)
            return False

        check(not has_private_fields(await gc.state()) and all(name not in state_text for name in ("Lena", "Tom", "Mia")),
              "Automatik speichert öffentliche Streamdaten und Rollenbezug, keine Discord-Nutzerprofile")

        restarted = await S.make_cog(bot, fake=fake)
        restarted._now = lambda: clock[0]
        cog = restarted
        gc = cog.config.guild(guild)
        await poll()
        check({key: message.id for key, message in (await messages()).items()} == before_ids,
              "Neustart setzt automatisch erkannte Streams ohne neue Meldungen fort")

        # Unbekannte Präsenz ist keine bestätigte Offline-Aussage.
        saved_lena, saved_tom, saved_mia = lena.activities, tom.activities, mia.activities
        lena.activities = tom.activities = mia.activities = ()
        conditions = (
            ("Präsenz-Intent", lambda: setattr(bot.intents, "presences", False),
             lambda: setattr(bot.intents, "presences", True)),
            ("Mitglieder-Intent", lambda: setattr(bot.intents, "members", False),
             lambda: setattr(bot.intents, "members", True)),
            ("vollständiger Cache", lambda: setattr(guild, "chunked", False),
             lambda: setattr(guild, "chunked", True)),
            ("Discord-Verbindung", lambda: setattr(bot, "is_ready", lambda: False),
             lambda: setattr(bot, "is_ready", lambda: True)),
        )
        for label, disable, restore in conditions:
            disable()
            try:
                await poll()
                status = cog.role_watch_status(guild, await gc.all())
                check(not status["ready"] and bool(status["warning"])
                      and {key: message.id for key, message in (await messages()).items()} == before_ids,
                      f"Fehlender Zustand „{label}“ zeigt Warnung und bewahrt bestehende Meldungen")
            finally:
                restore()
        lena.activities, tom.activities, mia.activities = saved_lena, saved_tom, saved_mia

        # Das globale Resume-Ereignis bestätigt nicht die Verbindung einer einzelnen Shard.
        guild.shard_id = 0
        await cog.on_shard_disconnect(0)
        lena.activities = tom.activities = mia.activities = ()
        await poll()
        check({key: message.id for key, message in (await messages()).items()} == before_ids,
              "Getrennte Shard bewahrt Rollenmeldungen trotz leerer Präsenzdaten")
        await cog.on_resumed()
        await poll()
        check({key: message.id for key, message in (await messages()).items()} == before_ids
              and not cog.role_watch_status(guild, await gc.all())["ready"],
              "Globales Resume allein macht eine weiterhin getrennte Shard nicht autoritativ")
        await cog.on_shard_resumed(0)
        await poll()
        check(not await messages() and cog.role_watch_status(guild, await gc.all())["ready"],
              "Erst Resume der betroffenen Shard bestätigt Offline-Daten und räumt Rollenmeldungen auf")
        lena.activities, tom.activities, mia.activities = saved_lena, saved_tom, saved_mia
        await poll()

        before = copy.copy(lena)
        before.activities = ()
        cog._wake.clear()
        await cog.on_presence_update(before, lena)
        check(cog._wake.is_set(), "Präsenzänderung weckt die Überwachung sofort")
        before = copy.copy(mia)
        before.roles = [role for role in mia.roles if role.id != watched.id]
        cog._wake.clear()
        await cog.on_member_update(before, mia)
        check(cog._wake.is_set(), "Rollenänderung weckt die Überwachung sofort")

        tom.roles.remove(watched)
        mia.roles.remove(watched)
        await poll()
        check(len(await messages()) == 1,
              "Verlust der beobachteten Rolle entfernt die Meldung des nicht mehr beobachteten Streams")
        guild.members.remove(lena)
        cog._wake.clear()
        await cog.on_member_remove(lena)
        assert cog._wake.is_set()
        await poll()
        check(not await messages(), "Verlassen des Servers entfernt den letzten beobachteten Stream")
        guild.members.append(lena)
        await poll()
        assert len(await messages()) == 1
        lena.activities = ()
        await poll()
        check(not await messages(), "Beendeter Discord-Streamingstatus löscht die aktive Meldung")

        lena.activities = saved_lena
        await poll()
        kai.activities = (activity("DNP Andere Rolle", "https://www.youtube.com/watch?v=ZYXwvu98765"),)
        await cog.configure(guild, watched_role_id=replacement.id)
        await poll()
        check(len(await messages()) == 1 and all("youtube.com" in message.embed.url for message in (await messages()).values()),
              "Rollenwechsel entfernt alte Rollenstreams und beobachtet ausschließlich die neue Rolle")
        guild.roles.remove(replacement)
        cog._wake.clear()
        await cog.on_guild_role_delete(replacement)
        assert cog._wake.is_set()
        await poll()
        check(not await messages(), "Löschen der beobachteten Discord-Rolle räumt die Meldung auf")

        # Manuelle Kanäle und Rollenautomatik teilen eine einzige Anzeige je Stream-URL.
        await cog.configure(guild, watched_role_id=watched.id)
        await cog.add_source(guild, "twitch", "matters86")
        await cog.config.twitch_client_id.set(S.TWITCH_ID)
        await cog.config.twitch_client_secret.set(S.TWITCH_SECRET)
        fake.go_live("twitch:matters86", "manual-live", title="DNP Twitch")
        await poll()
        check(len(await messages()) == 1,
              "Eine identische manuelle Quelle und ein Rollenstatus erzeugen gemeinsam höchstens eine Meldung")
        fake.errors["twitch"] = ProviderError("Twitch vorübergehend nicht erreichbar")
        try:
            await poll()
            check(len(await messages()) == 1,
                  "Manueller API-Ausfall erzeugt bei gleichzeitigem Rollenstatus keine Doppelmeldung")
        finally:
            fake.errors.clear()
        await cog.configure(guild, watched_role_id=0)
        await poll()
        check(len(await messages()) == 1 and "twitch:matters86" in await gc.sources(),
              "Ausschalten der Rollenautomatik behält unabhängig eingerichtete manuelle Streams")
        fake.live.clear()
        await poll()
        check(not await messages(), "Manuelle Quelle bleibt nach Abschalten der Automatik regulär offline aufräumbar")

        # Ein YouTube-Kanal-/Handle-Livelink und die Video-URL der API gehören zur selben Quelle.
        youtube_key = "youtube:" + S.YOUTUBE_ID
        fake.sources[youtube_key]["handles"] = ["@dnpteam"]
        await cog.config.youtube_api_key.set(S.YOUTUBE_KEY)
        for index, presence_url in enumerate((f"https://www.youtube.com/channel/{S.YOUTUBE_ID}/live",
                                              "https://www.youtube.com/@dnpteam/live"), 1):
            lena.activities = (activity("DNP YouTube-Livelink", presence_url),)
            await cog.configure(guild, watched_role_id=watched.id)
            await poll()
            role_message = next(iter((await messages()).values()))
            assert len(await messages()) == 1 and role_message.embed.url == presence_url
            await cog.add_source(guild, "youtube", "@projektteam")
            video = fake.go_live(youtube_key, f"api-video-{index}", title="DNP YouTube API")
            channel.forbid.add("delete")
            try:
                await poll()
                check(len(await messages()) == 1 and next(iter((await messages()).values())).id == role_message.id,
                      f"YouTube-Livelink {index}: Löschfehler beim Wechsel zur API-Videoquelle erzeugt keinen zweiten Post")
            finally:
                channel.forbid.discard("delete")
            await poll()
            current = await messages()
            check(len(current) == 1 and next(iter(current.values())).embed.url == video["url"]
                  and role_message.id not in channel._messages,
                  f"YouTube-Livelink {index}: Kanal-/Handle-Alias und API-Video werden zu einer Anzeige zusammengeführt")
            await cog.remove_source(guild, youtube_key)
            fake.live.pop(youtube_key, None)
            await cog.configure(guild, watched_role_id=0)
            await poll()
            assert not await messages()
        print(f"\n{checks} Streamer-Rollen-Prüfungen bestanden.")
    finally:
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
