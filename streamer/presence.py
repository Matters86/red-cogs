"""Öffentliche Streamlinks aus Discord-Streaming-Aktivitäten, ohne Netzabfragen.

Die Aktivität bestätigt lediglich den von Discord gemeldeten Streamingstatus.
Es werden weder Memberobjekte noch Discord-Namen oder Nutzer-IDs übernommen.
``discord.Streaming.name`` ist der Streamtitel (``details`` ist sein Alias);
``platform`` bezeichnet dagegen typischerweise Twitch oder YouTube.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

import discord


_TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_LOGIN = re.compile(r"[a-z0-9_]{3,25}\Z")
_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
_VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_HANDLE = re.compile(r"@[\w.\-·]{3,30}\Z")
_TWITCH_RESERVED = {"directory", "downloads", "inventory", "jobs", "login", "search", "settings",
                    "signup", "subscriptions", "turbo", "videos", "wallet"}


def _stream_link(raw):
    """-> (Plattform, öffentlicher Kanal-/Video-Identifier, kanonischer Link)."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
        return None
    raw = raw.strip()
    if any(ord(char) < 32 or char == "\\" for char in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if (parsed.scheme not in {"http", "https"} or parsed.username is not None
                or parsed.password is not None or parsed.port is not None):
            return None
        host = parsed.hostname
    except ValueError:
        return None
    path = unquote(parsed.path).strip("/")
    parts = path.split("/")
    if host in _TWITCH_HOSTS:
        login = path.lower()
        if not _LOGIN.fullmatch(login) or login in _TWITCH_RESERVED:
            return None
        return "twitch", login, f"https://www.twitch.tv/{login}"
    if host in _SHORT_HOSTS:
        if not _VIDEO.fullmatch(path):
            return None
        return "youtube", path, f"https://www.youtube.com/watch?v={path}"
    if host not in _YOUTUBE_HOSTS:
        return None
    if path == "watch":
        videos = parse_qs(parsed.query).get("v") or []
        if len(videos) != 1 or not _VIDEO.fullmatch(videos[0]):
            return None
        identifier = videos[0]
        return "youtube", identifier, f"https://www.youtube.com/watch?v={identifier}"
    if len(parts) == 2 and parts[0] == "live" and _VIDEO.fullmatch(parts[1]):
        return "youtube", parts[1], f"https://www.youtube.com/watch?v={parts[1]}"
    if len(parts) == 3 and parts[0] == "channel" and _CHANNEL.fullmatch(parts[1]) and parts[2] == "live":
        return "youtube", parts[1], f"https://www.youtube.com/channel/{parts[1]}/live"
    if len(parts) == 2 and _HANDLE.fullmatch(parts[0]) and parts[1] == "live":
        # Handles sind nicht von Groß-/Kleinschreibung abhängig. Der Link behält
        # die Originalschreibweise, insbesondere bei internationalen Handles.
        return "youtube", parts[0].casefold(), "https://www.youtube.com/" + quote(parts[0], safe="@") + "/live"
    return None


def parse_activity(activity):
    """Eine echte Discord-Streaming-Aktivität zu einem öffentlichen Stream machen.

    ``id='live'`` bleibt während der Presence-Sitzung stabil; Quelle und öffentlicher
    Kanal-/Video-Identifier stecken vollständig im ``source_key``. Andere Aktivitäten
    und nicht erlaubte Streamlinks liefern ``None``.
    """
    if not isinstance(activity, discord.Streaming):
        return None
    link = _stream_link(activity.url)
    if link is None:
        return None
    provider, identifier, url = link
    title = activity.name if isinstance(activity.name, str) else ""
    if not title.strip():
        title = activity.details if isinstance(activity.details, str) else ""
    # Discords created_at bezeichnet den Beginn dieser Aktivität und kann sich
    # nach Presence-/Client-Neustarts ändern. Es ist kein Plattform-Streamstart.
    # Der Cog hält stattdessen die erste Erkennung dieser Live-Sitzung fest.
    return {"id": "live", "provider": provider, "source_key": f"discord:{provider}:{identifier}",
            "name": identifier if provider == "twitch" else "YouTube-Livestream", "title": title,
            "url": url, "thumbnail": f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{identifier}-1280x720.jpg"
            if provider == "twitch" else "", "game": "", "viewers": None, "started_at": ""}


def source_from_stream(stream):
    """Die öffentliche Presence-Quelle zum normalisierten Stream, ohne Nutzerbezug."""
    if not isinstance(stream, dict):
        return None
    provider = stream.get("provider")
    prefix = f"discord:{provider}:"
    key = stream.get("source_key")
    if (not isinstance(provider, str) or provider not in {"twitch", "youtube"}
            or not isinstance(key, str) or not key.startswith(prefix)):
        return None
    identifier = key[len(prefix):]
    link = _stream_link(stream.get("url"))
    if not identifier or link is None or link[0] != provider or link[1] != identifier:
        return None
    return {"key": key, "provider": provider, "identifier": identifier,
            "name": identifier if provider == "twitch" else "YouTube-Livestream", "url": link[2],
            "enabled": True, "origin": "discord"}
