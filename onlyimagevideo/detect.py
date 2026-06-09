"""Reine Erkennungslogik für den OnlyImageVideo-Cog.

Bewusst ohne discord-Abhängigkeit, damit die Link-/Endungs-/Host-Erkennung
losgelöst getestet werden kann. Der Cog kombiniert diese Funktionen mit den
Discord-spezifischen Prüfungen (Anhänge, Sticker, Embeds).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Datei-Endungen, die als Bild oder Video gelten (Uploads wie Links).
MEDIA_EXTENSIONS: tuple[str, ...] = (
    # Bilder
    ".png", ".jpg", ".jpeg", ".gif", ".gifv", ".webp", ".bmp", ".tiff",
    ".tif", ".apng", ".avif", ".heic", ".heif", ".jfif",
    # Videos
    ".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".ogv",
)

# Hosts, die typischerweise Bild-/GIF-/Video-Inhalte liefern – auch ohne
# Datei-Endung in der URL (z. B. der Discord-GIF-Picker fügt Tenor-Links ein).
MEDIA_HOSTS: tuple[str, ...] = (
    "tenor.com", "giphy.com", "imgur.com", "gfycat.com", "redgifs.com",
    "media.discordapp.net", "cdn.discordapp.com",
)

_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
# Satzzeichen, die am URL-Ende abgeschnitten werden (z. B. "...png).").
_TRAILING = ")]}>.,!?;:'\""


def extract_urls(content: str | None) -> list[str]:
    """Alle http(s)-URLs aus einem Text, ohne anhängende Satzzeichen."""
    if not content:
        return []
    out = []
    for raw in _URL_RE.findall(content):
        out.append(raw.rstrip(_TRAILING))
    return out


def _host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _path(url: str) -> str:
    try:
        return (urlparse(url).path or "").lower()
    except ValueError:
        return ""


def url_is_media_file(url: str) -> bool:
    """True, wenn der Pfad der URL auf eine Medien-Endung endet."""
    return _path(url).endswith(MEDIA_EXTENSIONS)


def url_is_media_host(url: str) -> bool:
    """True, wenn der Host ein bekannter Bild-/GIF-/Video-Dienst ist."""
    host = _host(url)
    if not host:
        return False
    return any(host == h or host.endswith("." + h) for h in MEDIA_HOSTS)


def filename_is_media(name: str | None) -> bool:
    """Fallback für Anhänge ohne content_type: Prüfung über den Dateinamen."""
    if not name:
        return False
    return name.lower().endswith(MEDIA_EXTENSIONS)


def text_has_media_link(content: str | None, *, allow_links: bool, allow_hosts: bool) -> bool:
    """True, wenn der Text einen als Medium zählenden Link enthält."""
    if not (allow_links or allow_hosts):
        return False
    for url in extract_urls(content):
        if allow_links and url_is_media_file(url):
            return True
        if allow_hosts and url_is_media_host(url):
            return True
    return False
