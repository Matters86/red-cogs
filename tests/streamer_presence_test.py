"""Discord-Streaming normalisieren, ausschließlich öffentliche Links ohne Memberdaten."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import bootstrap
import discord

from rc.streamer.presence import parse_activity, source_from_stream


CHANNEL = "UC" + "A" * 22
VIDEO = "video000001"


def main():
    assert bootstrap.ROOT.is_dir()
    checks = 0

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
        print("OK   " + message)

    def streaming(url, *, name="Twitch", **extra):
        return discord.Streaming(name=name, url=url, **extra)

    started = datetime(2026, 11, 16, 12, 15, tzinfo=timezone.utc)
    activity = streaming("https://www.twitch.tv/DNP_Team?tracking=discard", details="DNP – Rollenspiel",
                         created_at=started.timestamp() * 1000,
                         assets={"large_text": "PRIVATE_DISCORD_NICK", "large_image": "twitch:PRIVATE_ASSET_NAME"},
                         state="PRIVATE_GAME_STATE")
    result = parse_activity(activity)
    check(activity.platform == "Twitch" and activity.name == "DNP – Rollenspiel"
          and result["title"] == "DNP – Rollenspiel", "Echter Discord-Payload liefert Streamtitel aus name statt Plattform")
    check(result["source_key"] == "discord:twitch:dnp_team" and result["id"] == "live"
          and result["url"] == "https://www.twitch.tv/dnp_team" and result["name"] == "dnp_team",
          "Twitch-Kanal und kanonischer Link bleiben ohne Discord-Nutzerbezug stabil")
    check(result["started_at"] == "" and result["viewers"] is None and result["game"] == ""
          and result["thumbnail"] == "https://static-cdn.jtvnw.net/previews-ttv/live_user_dnp_team-1280x720.jpg",
          "Activity-Datum wird nicht als Streamstart verwendet; öffentliches Twitch-Vorschaubild bleibt erhalten")
    source = source_from_stream(result)
    check(source == {"key": "discord:twitch:dnp_team", "provider": "twitch", "identifier": "dnp_team",
                     "name": "dnp_team", "url": "https://www.twitch.tv/dnp_team",
                     "enabled": True, "origin": "discord"}, "Presence-Quelle enthält nur den öffentlichen Kanal")
    encoded = json.dumps({"stream": result, "source": source})
    check(all(private not in encoded for private in ("PRIVATE_DISCORD_NICK", "PRIVATE_ASSET_NAME", "PRIVATE_GAME_STATE")),
          "Discord-Nick, Assets und sonstiger privater Aktivitätszustand werden nicht persistiert")

    fallback = streaming("https://twitch.tv/other_channel", name="")
    fallback.details = "DNP Fallbacktitel"
    check(parse_activity(fallback)["title"] == "DNP Fallbacktitel"
          and parse_activity(fallback)["started_at"] == "", "Leerer name nutzt details; fehlender Presence-Zeitstempel bleibt leer")
    fallback.name = "DNP Haupttitel"
    check(parse_activity(fallback)["title"] == "DNP Haupttitel", "Ein vorhandener name hat Vorrang vor details")

    for activity in (None, discord.Game("DNP"), discord.CustomActivity("DNP live"),
                     discord.Activity(type=discord.ActivityType.streaming, name="DNP", url="https://twitch.tv/dnp_team"),
                     SimpleNamespace(type=discord.ActivityType.streaming, name="DNP", url="https://twitch.tv/dnp_team")):
        assert parse_activity(activity) is None
    check(True, "Nur echte discord.Streaming-Aktivitäten werden verarbeitet, keine Spiele oder Typ-Nachahmungen")

    for raw in ("https://www.youtube.com/watch?v=" + VIDEO + "&feature=share",
                "https://m.youtube.com/watch?v=" + VIDEO,
                "https://youtu.be/" + VIDEO + "?si=tracking",
                "https://www.youtu.be/" + VIDEO,
                "https://www.youtube.com/live/" + VIDEO + "?si=tracking"):
        result = parse_activity(streaming(raw, name="YouTube", details="DNP live"))
        assert result["url"] == "https://www.youtube.com/watch?v=" + VIDEO
        assert result["source_key"] == "discord:youtube:" + VIDEO
        assert result["provider"] == "youtube" and result["name"] == "YouTube-Livestream"
        assert result["id"] == "live" and result["thumbnail"] == ""
    check(True, "YouTube-Watch-, Kurz- und Live-Video-Links werden auf dieselbe öffentliche Videoquelle normalisiert")

    for raw, identifier in (("https://youtube.com/channel/" + CHANNEL + "/live", CHANNEL),
                            ("https://www.youtube.com/@DNPTeam/live?view=1", "@dnpteam"),
                            ("https://youtube.com/@GrüßeTeam/live", "@grüsseteam")):
        result = parse_activity(streaming(raw, name="YouTube", details="DNP Stream"))
        assert result["source_key"] == "discord:youtube:" + identifier
        assert result["url"].startswith("https://www.youtube.com/") and result["url"].endswith("/live")
        assert source_from_stream(result)["identifier"] == identifier
    check(True, "YouTube-Kanal-Live-Reiter funktionieren mit Kanal-ID und auch internationalen Handles")

    bad_urls = ("https://evil.example/dnp_team", "https://twitch.tv.evil.example/dnp_team",
                "https://twitch.tv@evil.example/dnp_team", "https://name@twitch.tv/dnp_team",
                "https://name:password@youtube.com/watch?v=" + VIDEO,
                "https://twitch.tv:443/dnp_team", "https://youtube.com:invalid/watch?v=" + VIDEO,
                "ftp://twitch.tv/dnp_team", "javascript:alert(1)", "//twitch.tv/dnp_team",
                "twitch.tv/dnp_team", "https://twitch.tv/", "https://twitch.tv/dnp_team/videos",
                "https://twitch.tv/directory", "https://youtube.com/shorts/" + VIDEO,
                "https://youtube.com/watch", "https://youtube.com/watch?v=short",
                "https://youtube.com/watch?v=" + VIDEO + "&v=video000002",
                "https://youtu.be/" + VIDEO + "/unexpected", "https://youtube.com/@DNPTeam/videos",
                "https://youtube.com/@DNPTeam/streams", "https://youtube.com/@DNPTeam/live/extra",
                "https://youtube.com/channel/invalid/live", "https://youtube.com/@bad<script>/live",
                "https://youtube.com\\@evil.example/@DNPTeam/live", "https://twit\nch.tv/dnp_team")
    for url in bad_urls:
        assert parse_activity(streaming(url)) is None, url
    check(True, "Fremdhosts, Userinfo, Ports, VOD-Reiter, ungültige IDs und manipulierte Pfade bleiben ausgeschlossen")

    invalid_time = streaming("https://twitch.tv/dnp_team", created_at=float("inf"))
    check(parse_activity(invalid_time)["started_at"] == "", "Unbrauchbare Presence-Zeitstempel brechen die Erkennung nicht ab")
    check(source_from_stream(None) is None
          and source_from_stream({"provider": "twitch", "source_key": "discord:twitch:forged",
                                  "url": "https://evil.example/forged"}) is None,
          "Auch die Quellenableitung akzeptiert ausschließlich passende öffentliche Streamlinks")
    print(f"\n{checks} Streamer-Presence-Prüfungen bestanden.")


if __name__ == "__main__":
    main()
