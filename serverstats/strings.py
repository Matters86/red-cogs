"""Mehrsprachigkeit für den ServerStats-Cog (Aufbau wie welcome/guard).

``de`` ist Standard und Fallback. ``t(lang, key, **kwargs)`` liefert den Text, fällt bei
fehlender Sprache/fehlendem Key auf Deutsch bzw. den Key zurück und formatiert optional
mit ``str.format`` (nur feste, eigene Texte).
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        "stats_title": "📊 Statistik – {server}",
        "stats_desc": "Letzte **{days}** Tage (Zeitzone {tz}).",
        "members": "Mitglieder",
        "growth": "Netto-Wachstum",
        "growth_value": "{net:+d} ({joins} rein · {leaves} raus)",
        "messages": "Nachrichten",
        "voice": "Voice-Stunden",
        "top_channels": "Aktivste Kanäle",
        "no_data": "Noch keine Daten – die Zählung läuft ab jetzt.",
        "footer": "Nur Zählungen, keine Inhalte · Aufbewahrung {retention} Tage",
        "retention_set": "✅ Statistiken werden jetzt **{days}** Tage aufbewahrt.",
        "retention_bad": "Bitte einen Wert zwischen {min} und {max} Tagen angeben.",
        "ignore_on": "🔕 {channel} wird nicht mehr gezählt.",
        "ignore_off": "🔔 {channel} wird wieder gezählt.",
        "lang_set": "Sprache auf **{language}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "settings_title": "Statistik – Einstellungen",
        "settings_retention": "Aufbewahrung",
        "settings_ignored": "Ignorierte Kanäle",
        "settings_lang": "Sprache",
        "settings_tz": "Zeitzone",
        "tz_current": "Zeitzone dieses Servers: **{tz}** (jetzt dort {now}). Tage werden nach dieser Zeitzone gezählt.",
        "tz_set": "🕓 Zeitzone auf **{tz}** gesetzt. Ab jetzt zählen die Tage nach dieser Zeitzone; bisherige Tage bleiben unverändert.",
        "tz_unknown": "Unbekannte Zeitzone `{tz}`. Beispiele: `Europe/Berlin`, `Europe/Vienna`, `UTC`.",
        "days_unit": "{n} Tage",
        "none": "—",
    },
    "en": {
        "stats_title": "📊 Statistics – {server}",
        "stats_desc": "Last **{days}** days (time zone {tz}).",
        "members": "Members",
        "growth": "Net growth",
        "growth_value": "{net:+d} ({joins} in · {leaves} out)",
        "messages": "Messages",
        "voice": "Voice hours",
        "top_channels": "Most active channels",
        "no_data": "No data yet – counting starts now.",
        "footer": "Counts only, no content · kept for {retention} days",
        "retention_set": "✅ Statistics are now kept for **{days}** days.",
        "retention_bad": "Please give a value between {min} and {max} days.",
        "ignore_on": "🔕 {channel} is no longer counted.",
        "ignore_off": "🔔 {channel} is counted again.",
        "lang_set": "Language set to **{language}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "settings_title": "Statistics – settings",
        "settings_retention": "Retention",
        "settings_ignored": "Ignored channels",
        "settings_lang": "Language",
        "settings_tz": "Time zone",
        "tz_current": "Time zone of this server: **{tz}** (now {now}). Days are counted in this time zone.",
        "tz_set": "🕓 Time zone set to **{tz}**. From now on days are counted in this time zone; existing days stay as they are.",
        "tz_unknown": "Unknown time zone `{tz}`. Examples: `Europe/Berlin`, `Europe/Vienna`, `UTC`.",
        "days_unit": "{n} days",
        "none": "—",
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
