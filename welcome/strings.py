"""Mehrsprachigkeit für den Welcome-Cog (Aufbau wie guard/autorole).

``de`` ist Standard und Fallback. ``t(lang, key, **kwargs)`` liefert den Text, fällt bei
fehlender Sprache/fehlendem Key auf Deutsch bzw. den Key zurück und formatiert optional
mit ``str.format`` (nur für eigene, feste Texte – Nutzertexte laufen über
``welcome.fill_placeholders``, das ausschließlich die bekannten Platzhalter ersetzt).
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

# Platzhalter, die in allen Willkommens-/Abschieds-/DM-Texten funktionieren.
PLACEHOLDERS = ("user", "name", "server", "count", "created")

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # Standardtexte (gelten, solange kein eigener Text gesetzt ist)
        "default_welcome": "👋 Willkommen auf **{server}**, {user}! Du bist unser {count}. Mitglied.",
        "default_welcome_title": "Willkommen, {name}!",
        "default_leave": "👋 **{name}** hat den Server verlassen. Wir sind jetzt {count}.",
        "default_leave_title": "Auf Wiedersehen, {name}",
        "default_dm": "Hallo {name}, schön, dass du auf **{server}** bist! Viel Spaß bei uns. 🎉",
        "default_dm_title": "Willkommen auf {server}",
        "card_headline": "WILLKOMMEN",
        "card_member": "Mitglied #{count}",
        "card_fallback_name": "Neues Mitglied",
        "embed_footer": "Mitglied #{count}",
        # Kontoalter
        "age_years": "{n} Jahre", "age_year": "1 Jahr",
        "age_months": "{n} Monate", "age_month": "1 Monat",
        "age_days": "{n} Tage", "age_day": "1 Tag",
        "age_hours": "{n} Stunden", "age_hour": "1 Stunde",
        "age_new": "weniger als 1 Stunde",
        # Arten
        "kind_welcome": "Willkommen", "kind_leave": "Abschied", "kind_dm": "DM", "kind_card": "Willkommensbild",
        "on": "an", "off": "aus", "none": "—",
        # Befehle
        "channel_set": "✅ Kanal für **{kind}**: {channel}.",
        "channel_cleared": "Kanal für **{kind}** entfernt.",
        "enabled_set": "**{kind}** ist jetzt **{state}**.",
        "enabled_nochannel": "**{kind}** ist jetzt **{state}** – setze noch einen Kanal mit `{prefix}welcomeset channel {arg} #kanal`.",
        "text_set": "✅ Text für **{kind}** gespeichert.",
        "text_reset": "Text für **{kind}** zurückgesetzt (Standardtext).",
        "text_too_long": "Text zu lang (max. {max} Zeichen).",
        "mode_set": "Darstellung für **{kind}**: **{mode}**.",
        "title_set": "Embed-Titel für **{kind}** gespeichert.",
        "title_reset": "Embed-Titel für **{kind}** zurückgesetzt.",
        "color_set": "Embed-Farbe für **{kind}**: `{color}`.",
        "color_bad": "Ungültige Farbe. Beispiel: `#3ddc97`.",
        "image_set": "Embed-Bild für **{kind}** gespeichert.",
        "image_reset": "Embed-Bild für **{kind}** entfernt.",
        "url_bad": "Ungültige Adresse – erlaubt sind `https://…`-Links (max. {max} Zeichen).",
        "ping_set": "Neues Mitglied anpingen: **{state}**.",
        "bots_set": "Bots ignorieren: **{state}**.",
        "lang_set": "Sprache auf **{language}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "card_colors_set": "Bildfarben: Hintergrund `{c1}`, Akzent `{c2}`, Text `{c3}`.",
        "card_bg_set": "✅ Hintergrundbild gesetzt – wird beim nächsten Rendern geladen.",
        "card_bg_removed": "Hintergrundbild entfernt – es gilt wieder der Farbverlauf.",
        "card_headline_set": "Überschrift des Bildes gespeichert.",
        "card_headline_reset": "Überschrift des Bildes zurückgesetzt.",
        "card_render_failed": "❌ Das Bild konnte nicht erzeugt werden.",
        "card_bg_failed": "⚠️ Hintergrundbild nicht geladen ({reason}) – Farbverlauf verwendet.",
        "test_intro": "🧪 **Test – {kind}** (mit dir als Beispiel):",
        "test_dm_sent": "✅ Test-DM an dich gesendet.",
        "test_dm_failed": "❌ Die DM konnte nicht zugestellt werden (DMs geschlossen?).",
        "test_failed": "❌ Senden fehlgeschlagen: {reason}",
        "err_no_channel": "kein Kanal gesetzt",
        "err_channel_missing": "der Kanal existiert nicht mehr",
        "err_no_send": "mir fehlt das Recht „Nachrichten senden“ im Kanal",
        "err_no_embed": "mir fehlt das Recht „Links einbetten“ im Kanal",
        "err_http": "Discord hat die Nachricht abgelehnt",
        "settings_title": "Willkommen – Einstellungen",
        "settings_channel": "Kanal", "settings_mode": "Darstellung", "settings_text": "Text",
        "settings_custom": "eigener Text", "settings_default": "Standardtext",
        "settings_general": "Allgemein",
        "settings_ping": "Ping", "settings_bots": "Bots ignorieren", "settings_lang": "Sprache",
        "settings_card_bg": "Hintergrund", "settings_card_url": "Bild-URL",
    },
    "en": {
        "default_welcome": "👋 Welcome to **{server}**, {user}! You are member #{count}.",
        "default_welcome_title": "Welcome, {name}!",
        "default_leave": "👋 **{name}** has left the server. We are now {count}.",
        "default_leave_title": "Goodbye, {name}",
        "default_dm": "Hi {name}, great to have you on **{server}**! Have fun. 🎉",
        "default_dm_title": "Welcome to {server}",
        "card_headline": "WELCOME",
        "card_member": "Member #{count}",
        "card_fallback_name": "New member",
        "embed_footer": "Member #{count}",
        "age_years": "{n} years", "age_year": "1 year",
        "age_months": "{n} months", "age_month": "1 month",
        "age_days": "{n} days", "age_day": "1 day",
        "age_hours": "{n} hours", "age_hour": "1 hour",
        "age_new": "less than 1 hour",
        "kind_welcome": "Welcome", "kind_leave": "Goodbye", "kind_dm": "DM", "kind_card": "Welcome image",
        "on": "on", "off": "off", "none": "—",
        "channel_set": "✅ Channel for **{kind}**: {channel}.",
        "channel_cleared": "Channel for **{kind}** removed.",
        "enabled_set": "**{kind}** is now **{state}**.",
        "enabled_nochannel": "**{kind}** is now **{state}** – set a channel with `{prefix}welcomeset channel {arg} #channel`.",
        "text_set": "✅ Text for **{kind}** saved.",
        "text_reset": "Text for **{kind}** reset (default text).",
        "text_too_long": "Text too long (max. {max} characters).",
        "mode_set": "Display for **{kind}**: **{mode}**.",
        "title_set": "Embed title for **{kind}** saved.",
        "title_reset": "Embed title for **{kind}** reset.",
        "color_set": "Embed colour for **{kind}**: `{color}`.",
        "color_bad": "Invalid colour. Example: `#3ddc97`.",
        "image_set": "Embed image for **{kind}** saved.",
        "image_reset": "Embed image for **{kind}** removed.",
        "url_bad": "Invalid address – only `https://…` links are allowed (max. {max} characters).",
        "ping_set": "Ping the new member: **{state}**.",
        "bots_set": "Ignore bots: **{state}**.",
        "lang_set": "Language set to **{language}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "card_colors_set": "Image colours: background `{c1}`, accent `{c2}`, text `{c3}`.",
        "card_bg_set": "✅ Background image set – it will be loaded on the next render.",
        "card_bg_removed": "Background image removed – the gradient applies again.",
        "card_headline_set": "Image headline saved.",
        "card_headline_reset": "Image headline reset.",
        "card_render_failed": "❌ The image could not be rendered.",
        "card_bg_failed": "⚠️ Background image not loaded ({reason}) – gradient used.",
        "test_intro": "🧪 **Test – {kind}** (with you as the example):",
        "test_dm_sent": "✅ Test DM sent to you.",
        "test_dm_failed": "❌ The DM could not be delivered (DMs closed?).",
        "test_failed": "❌ Sending failed: {reason}",
        "err_no_channel": "no channel set",
        "err_channel_missing": "the channel no longer exists",
        "err_no_send": "I lack the “Send Messages” permission in the channel",
        "err_no_embed": "I lack the “Embed Links” permission in the channel",
        "err_http": "Discord rejected the message",
        "settings_title": "Welcome – settings",
        "settings_channel": "Channel", "settings_mode": "Display", "settings_text": "Text",
        "settings_custom": "custom text", "settings_default": "default text",
        "settings_general": "General",
        "settings_ping": "Ping", "settings_bots": "Ignore bots", "settings_lang": "Language",
        "settings_card_bg": "Background", "settings_card_url": "Image URL",
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
    pack = STRINGS.get(lang or DEFAULT_LANGUAGE) or STRINGS[DEFAULT_LANGUAGE]
    text = pack.get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
