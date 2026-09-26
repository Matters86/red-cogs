"""Mehrsprachigkeit für den TwitchLive-Cog (Aufbau wie poll/strings.py).

``de`` ist Standard und Fallback. ``t(lang, key, **kwargs)`` liefert den Text,
fällt bei fehlender Sprache/fehlendem Key auf Deutsch bzw. den Key zurück und
formatiert optional mit ``str.format`` (nur mit vom Cog gelieferten Werten –
Nutzer-Vorlagen laufen NICHT über ``str.format``, siehe ``embed.render_template``).
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

# Standard-Nachrichtentext (Server-Standard, wenn nichts eingetragen ist).
DEFAULT_MESSAGE = {
    "de": "{ping} **{streamer}** ist jetzt live auf Twitch! 🎮 {game}",
    "en": "{ping} **{streamer}** is now live on Twitch! 🎮 {game}",
}

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # Embed / Nachricht
        "field_game": "Spiel",
        "field_viewers": "Zuschauer",
        "field_games": "Spiel(e)",
        "field_duration": "Dauer",
        "field_peak": "Max. Zuschauer",
        "no_game": "—",
        "no_title": "Live auf Twitch",
        "footer_live": "Twitch · live seit",
        "footer_ended": "Twitch · Stream beendet",
        "footer_test": "Twitch · Testmeldung",
        "button_watch": "Zum Stream",
        "button_channel": "Zum Kanal",
        "ended_content": "**{streamer}** war live.",
        "ended_desc": "**{streamer}** war live – {duration}",
        "test_prefix": "🧪 **Testmeldung** – so sieht die Live-Meldung aus (ohne echten Ping):",
        "test_offline_title": "Beispiel-Stream von {streamer}",
        # Befehle
        "added": "✅ **{login}** wird beobachtet. Zielkanal: {channel} · Ping: {ping}",
        "updated": "✅ **{login}** aktualisiert. Zielkanal: {channel} · Ping: {ping}",
        "removed": "🗑️ **{login}** wird nicht mehr beobachtet.",
        "not_watched": "**{login}** wird auf diesem Server nicht beobachtet.",
        "bad_login": "`{login}` ist kein gültiger Twitch-Login (3–25 Zeichen, nur Buchstaben, Ziffern und _).",
        "unknown_login": "Twitch kennt keinen Kanal **{login}**.",
        "too_many": "Maximal {max} Kanäle pro Server.",
        "no_channel": "Kein Zielkanal: gib einen Kanal an oder setze einen Standardkanal mit `{prefix}twitchset channel`.",
        "bad_channel": "In {channel} darf ich keine Nachrichten mit Embeds senden (Rechte prüfen).",
        "list_empty": "Auf diesem Server werden keine Twitch-Kanäle beobachtet.",
        "list_header": "**Beobachtete Twitch-Kanäle**",
        "list_row": "{state} **{login}** → {channel} · Ping: {ping}{custom}",
        "list_custom": " · eigener Text",
        "state_live": "🔴",
        "state_on": "🟢",
        "state_off": "⚪",
        "ping_none": "keiner",
        "channel_default": "Standardkanal",
        "toggled_on": "🟢 Meldungen für **{login}** eingeschaltet.",
        "toggled_off": "⚪ Meldungen für **{login}** ausgeschaltet.",
        "text_set": "✅ Eigener Text für **{login}** gespeichert.",
        "text_reset": "↩️ **{login}** nutzt wieder den Standardtext.",
        "test_sent": "🧪 Testmeldung für **{login}** in {channel} gesendet.",
        "test_failed": "Testmeldung konnte nicht gesendet werden (Rechte in {channel} prüfen).",
        "default_channel_set": "Standardkanal: {channel}.",
        "default_channel_cleared": "Standardkanal entfernt.",
        "message_set": "Standardtext gespeichert.",
        "message_reset": "Standardtext zurückgesetzt.",
        "message_too_long": "Der Text ist zu lang (max. {max} Zeichen).",
        "endaction_set": "Bei Stream-Ende: **{action}**.",
        "endaction_edit": "Nachricht bearbeiten („war live“)",
        "endaction_delete": "Nachricht löschen",
        "endaction_bad": "Erlaubt: `edit` oder `delete`.",
        "liverole_set": "Live-Rolle: {role}.",
        "liverole_cleared": "Live-Rolle entfernt.",
        "liverole_hierarchy": "Die Rolle {role} liegt nicht unter meiner höchsten Rolle oder mir fehlt „Rollen verwalten“.",
        "liverole_forbidden": "Diese Rolle darfst du nicht automatisch vergeben lassen (liegt über deiner höchsten Rolle oder hat Verwaltungsrechte).",
        "link_set": "🔗 {member} ↔ **{login}** verknüpft.",
        "link_removed": "🔗 Verknüpfung von {member} entfernt.",
        "link_missing": "{member} ist mit keinem Twitch-Kanal verknüpft.",
        "lang_set": "Sprache auf **{language}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "creds_set": "🔐 Twitch-Zugangsdaten gespeichert (Nachricht gelöscht). Token-Abruf: {result}",
        "creds_ok": "erfolgreich ✅",
        "creds_bad": "fehlgeschlagen – Client-ID/Secret prüfen ❌",
        "creds_error": "Twitch nicht erreichbar, wird beim nächsten Abruf erneut versucht.",
        "creds_not_deleted": "⚠️ Ich konnte deine Nachricht nicht löschen – bitte sofort selbst löschen und das Secret in der Twitch-Konsole erneuern!",
        "creds_cleared": "Twitch-Zugangsdaten entfernt.",
        "interval_set": "Abfrage-Intervall: **{sec} s**.",
        "interval_bad": "Bitte einen Wert zwischen {min} und {max} Sekunden angeben.",
        "settings_title": "**TwitchLive – Einstellungen**",
        "no_creds_hint": "⚠️ Es sind keine Twitch-Zugangsdaten gesetzt – der Bot fragt Twitch nicht ab. Bot-Owner: `{prefix}twitchset creds <client_id> <client_secret>`.",
        "channel_set": "📺 **{login}** meldet jetzt in {channel}.",
        "channel_reset": "📺 **{login}** nutzt wieder den Standardkanal ({channel}).",
        "role_set": "🔔 Ping-Rolle für **{login}**: {role}.",
        "role_cleared": "🔕 **{login}** pingt keine Rolle mehr.",
        "yes": "ja",
        "no": "nein",
    },
    "en": {
        "field_game": "Game",
        "field_viewers": "Viewers",
        "field_games": "Game(s)",
        "field_duration": "Duration",
        "field_peak": "Peak viewers",
        "no_game": "—",
        "no_title": "Live on Twitch",
        "footer_live": "Twitch · live since",
        "footer_ended": "Twitch · stream ended",
        "footer_test": "Twitch · test message",
        "button_watch": "Watch stream",
        "button_channel": "Open channel",
        "ended_content": "**{streamer}** was live.",
        "ended_desc": "**{streamer}** was live – {duration}",
        "test_prefix": "🧪 **Test message** – this is how the live alert looks (no real ping):",
        "test_offline_title": "Example stream by {streamer}",
        "added": "✅ Now watching **{login}**. Channel: {channel} · Ping: {ping}",
        "updated": "✅ **{login}** updated. Channel: {channel} · Ping: {ping}",
        "removed": "🗑️ No longer watching **{login}**.",
        "not_watched": "**{login}** is not watched on this server.",
        "bad_login": "`{login}` is not a valid Twitch login (3–25 characters, letters, digits and _ only).",
        "unknown_login": "Twitch has no channel **{login}**.",
        "too_many": "At most {max} channels per server.",
        "no_channel": "No target channel: pass a channel or set a default with `{prefix}twitchset channel`.",
        "bad_channel": "I can't send embeds in {channel} (check permissions).",
        "list_empty": "No Twitch channels are watched on this server.",
        "list_header": "**Watched Twitch channels**",
        "list_row": "{state} **{login}** → {channel} · Ping: {ping}{custom}",
        "list_custom": " · custom text",
        "state_live": "🔴",
        "state_on": "🟢",
        "state_off": "⚪",
        "ping_none": "none",
        "channel_default": "default channel",
        "toggled_on": "🟢 Alerts for **{login}** enabled.",
        "toggled_off": "⚪ Alerts for **{login}** disabled.",
        "text_set": "✅ Custom text for **{login}** saved.",
        "text_reset": "↩️ **{login}** uses the default text again.",
        "test_sent": "🧪 Test message for **{login}** sent to {channel}.",
        "test_failed": "Could not send the test message (check permissions in {channel}).",
        "default_channel_set": "Default channel: {channel}.",
        "default_channel_cleared": "Default channel removed.",
        "message_set": "Default text saved.",
        "message_reset": "Default text reset.",
        "message_too_long": "Text too long (max. {max} characters).",
        "endaction_set": "On stream end: **{action}**.",
        "endaction_edit": "edit message (“was live”)",
        "endaction_delete": "delete message",
        "endaction_bad": "Allowed: `edit` or `delete`.",
        "liverole_set": "Live role: {role}.",
        "liverole_cleared": "Live role removed.",
        "liverole_hierarchy": "The role {role} is not below my highest role or I lack “Manage Roles”.",
        "liverole_forbidden": "You may not have this role assigned automatically (above your highest role or has admin permissions).",
        "link_set": "🔗 Linked {member} ↔ **{login}**.",
        "link_removed": "🔗 Link for {member} removed.",
        "link_missing": "{member} is not linked to a Twitch channel.",
        "lang_set": "Language set to **{language}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "creds_set": "🔐 Twitch credentials saved (message deleted). Token request: {result}",
        "creds_ok": "successful ✅",
        "creds_bad": "failed – check client ID/secret ❌",
        "creds_error": "Twitch unreachable, will retry on the next poll.",
        "creds_not_deleted": "⚠️ I could not delete your message – delete it yourself right now and rotate the secret in the Twitch console!",
        "creds_cleared": "Twitch credentials removed.",
        "interval_set": "Poll interval: **{sec} s**.",
        "interval_bad": "Please pass a value between {min} and {max} seconds.",
        "settings_title": "**TwitchLive – settings**",
        "no_creds_hint": "⚠️ No Twitch credentials set – the bot does not poll Twitch. Bot owner: `{prefix}twitchset creds <client_id> <client_secret>`.",
        "channel_set": "📺 **{login}** now posts in {channel}.",
        "channel_reset": "📺 **{login}** uses the default channel again ({channel}).",
        "role_set": "🔔 Ping role for **{login}**: {role}.",
        "role_cleared": "🔕 **{login}** no longer pings a role.",
        "yes": "yes",
        "no": "no",
    },
}


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


def default_message(lang: str | None) -> str:
    return DEFAULT_MESSAGE.get(lang or DEFAULT_LANGUAGE, DEFAULT_MESSAGE[DEFAULT_LANGUAGE])
