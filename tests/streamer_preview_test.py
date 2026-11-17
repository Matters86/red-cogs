"""Streamer: feste Erkennungszeit trotz wechselnder Discord-Presence und Vorschaubilder."""
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlsplit

import discord
import streamer_harness as S

from rc.streamer.presence import parse_activity


async def main():
    wc, bot, _app, cog = await S.make_app()
    guild = bot.guilds[0]
    member = guild.get_member(11)
    role = S.L.H.Role(guild, 1118, "Streamer", 3)
    guild.roles.append(role)
    member.roles.append(role)
    clock = cog.test_clock
    checks = 0

    def check(condition, text):
        nonlocal checks
        assert condition, text
        checks += 1
        print("OK   " + text)

    def activity(title, created):
        return discord.Streaming(name="Twitch", details=title,
                                 url="https://www.twitch.tv/matters86", created_at=created * 1000)

    def messages():
        return [message for channel in guild.text_channels for message in channel._messages.values()
                if message.embeds and str(message.embed.footer.text or "").startswith("Streamer · ")]

    try:
        first_seen = clock[0]
        member.activities = (activity("DNP Erster Titel", first_seen - 3600),)
        check(parse_activity(member.activities[0])["started_at"] == "",
              "Discords wechselnder Activity-Beginn wird nicht als Plattform-Startzeit übernommen")
        await cog.configure(guild, channel_id=guild.id + 3, title_filter="DNP", watched_role_id=role.id)
        await cog.poll_once()
        assert len(messages()) == 1
        message = messages()[0]
        original_id, original_time, original_image = message.id, message.embed.timestamp, message.embed.image.url
        check(original_time is not None and abs(original_time.timestamp() - first_seen) < 2,
              "Rollenstream erhält einmalig die erste Erkennungszeit des Bots")
        first_image_parts = urlsplit(original_image)
        check(first_image_parts.scheme == "https" and first_image_parts.hostname == "static-cdn.jtvnw.net"
              and first_image_parts.path.endswith("/live_user_matters86-1280x720.jpg"),
              "Vorschaubild bleibt am öffentlichen Twitch-CDN-Kanal gebunden")

        clock[0] += 601
        member.activities = (activity("DNP Zweiter Titel", clock[0]),)
        await cog.poll_once()
        current = messages()[0]
        check(len(messages()) == 1 and current.id == original_id and current.embed.timestamp == original_time,
              "Titel- und Presencewechsel aktualisieren dieselbe Meldung ohne Zurücksetzen der Uhrzeit")
        check(current.embed.image.url != original_image and urlsplit(current.embed.image.url).path == first_image_parts.path,
              "Twitch-Vorschau erhält nach einigen Minuten eine neue Cache-Adresse, ohne den Stream zu wechseln")

        fake = cog.api
        await cog.cog_unload()
        cog = await S.make_cog(bot, wc, fake=fake)
        cog._now = lambda: clock[0]
        await cog.poll_once()
        check(len(messages()) == 1 and messages()[0].id == original_id
              and messages()[0].embed.timestamp == original_time,
              "Cog-Neuladen behält die gespeicherte Erkennungszeit und vorhandene Ankündigung")

        member.activities = ()
        await cog.poll_once()
        assert not messages()
        clock[0] += 120
        member.activities = (activity("DNP Nach kurzem Aussetzer", clock[0]),)
        await cog.poll_once()
        check(len(messages()) == 1 and messages()[0].id != original_id
              and messages()[0].embed.timestamp == original_time,
              "Kurzer Presence-Aussetzer entfernt die Meldung, setzt bei Rückkehr aber die Erkennungszeit nicht zurück")
        short_gap_id = messages()[0].id

        member.activities = ()
        await cog.poll_once()
        assert not messages()
        clock[0] += 301
        await cog.poll_once()
        assert not messages()
        member.activities = (activity("DNP Neuer Stream", first_seen),)
        await cog.poll_once()
        check(len(messages()) == 1 and messages()[0].id != short_gap_id
              and abs(messages()[0].embed.timestamp.timestamp() - clock[0]) < 2,
              "Eine neue Presence-Sitzung nach über fünf Minuten Offline erhält eine neue Erkennungszeit")

        await cog.configure(guild, watched_role_id=0)
        await cog.add_source(guild, "twitch", "lenaplays")
        api_start = "2026-11-17T12:00:00Z"
        fake.go_live("twitch:lenaplays", "api-session", started_at=api_start)
        await cog.poll_once()
        check(len(messages()) == 1 and messages()[0].embed.timestamp == datetime(2026, 11, 17, 12, tzinfo=timezone.utc),
              "API-Streams behalten ihren echten Plattform-Startzeitpunkt")
        check(messages()[0].embed.image.url == "https://example.org/stream-preview.jpg",
              "Fremde Vorschaubild-URLs werden nicht mit Twitch-Cacheparametern verändert")
        print(f"\n{checks} Streamer-Vorschauprüfungen bestanden.")
    finally:
        await cog.cog_unload()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
