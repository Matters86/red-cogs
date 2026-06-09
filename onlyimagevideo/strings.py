"""Mehrsprachigkeit für den OnlyImageVideo-Cog.

Gleicher Aufbau wie in den übrigen Cogs (poll/raidhelper/tickets):
``de`` ist Standard und Fallback, ``t(lang, key, **kwargs)`` formatiert optional.
``OVERRIDABLE_KEYS`` listet die Texte, die ein Server im Dashboard frei
überschreiben darf (hier der Hinweis beim Löschen).
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # Hinweis beim Löschen (selbstlöschend)
        "notice": "{user} In diesem Kanal sind nur Beiträge mit Bild, Video oder GIF erlaubt – reine Textnachrichten werden entfernt.",
        # Kanäle
        "channel_added": "✅ {channel} ist jetzt ein Nur-Medien-Kanal.",
        "channel_removed": "{channel} ist kein Nur-Medien-Kanal mehr.",
        "channel_already": "{channel} ist bereits ein Nur-Medien-Kanal.",
        "channel_not_listed": "{channel} ist kein Nur-Medien-Kanal.",
        "channel_bad": "Dieser Kanaltyp wird nicht unterstützt (erlaubt: Text-, Voice- und Forum-Kanäle).",
        "list_header": "**Nur-Medien-Kanäle**",
        "list_empty": "Es sind keine Nur-Medien-Kanäle festgelegt.",
        "list_row": "• {channel}",
        "list_note": "Threads in diesen Kanälen erben die Regel.",
        # Ausnahme-Rollen
        "role_added": "Ausnahme-Rolle hinzugefügt: {role}.",
        "role_removed": "Ausnahme-Rolle entfernt: {role}.",
        # Schalter
        "set_links": "Links zu Mediendateien zählen als Medium: **{state}**.",
        "set_hosts": "GIF-/Medien-Dienste (z. B. Tenor, Giphy) zählen als Medium: **{state}**.",
        "set_stickers": "Sticker zählen als Bild: **{state}**.",
        "set_ignorebots": "Bots/Webhooks ausnehmen: **{state}**.",
        "set_notify": "Hinweis beim Löschen senden: **{state}**.",
        "state_on": "an",
        "state_off": "aus",
        # Sprache / Dashboard
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "dashboard_hint": "Die Verwaltung findest du im WebCore-Dashboard unter `/cogs/onlyimagevideo`.",
        "dashboard_missing": "WebCore ist nicht geladen – Dashboard nicht verfügbar.",
    },
    "en": {
        "notice": "{user} Only posts containing an image, video or GIF are allowed in this channel – text-only messages are removed.",
        "channel_added": "✅ {channel} is now a media-only channel.",
        "channel_removed": "{channel} is no longer a media-only channel.",
        "channel_already": "{channel} is already a media-only channel.",
        "channel_not_listed": "{channel} is not a media-only channel.",
        "channel_bad": "This channel type is not supported (allowed: text, voice and forum channels).",
        "list_header": "**Media-only channels**",
        "list_empty": "No media-only channels configured.",
        "list_row": "• {channel}",
        "list_note": "Threads in these channels inherit the rule.",
        "role_added": "Exempt role added: {role}.",
        "role_removed": "Exempt role removed: {role}.",
        "set_links": "Links to media files count as media: **{state}**.",
        "set_hosts": "GIF/media services (e.g. Tenor, Giphy) count as media: **{state}**.",
        "set_stickers": "Stickers count as an image: **{state}**.",
        "set_ignorebots": "Exempt bots/webhooks: **{state}**.",
        "set_notify": "Send a notice when deleting: **{state}**.",
        "state_on": "on",
        "state_off": "off",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "dashboard_hint": "Management is available in the WebCore dashboard at `/cogs/onlyimagevideo`.",
        "dashboard_missing": "WebCore is not loaded – dashboard unavailable.",
    },
}

OVERRIDABLE_KEYS: tuple[str, ...] = (
    "notice",
)


def t(lang: str | None, key: str, **kwargs) -> str:
    """Liefert den Text für ``key`` in ``lang`` (Fallback: Deutsch, dann Key)."""
    pack = STRINGS.get(lang or DEFAULT_LANGUAGE) or STRINGS[DEFAULT_LANGUAGE]
    template = pack.get(key)
    if template is None:
        template = STRINGS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
    return template
