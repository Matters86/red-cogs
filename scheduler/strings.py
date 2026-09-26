"""Mehrsprachigkeit für den Scheduler-Cog (Aufbau wie poll/strings.py). ``de`` = Standard/Fallback."""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        "no_permission": "Dazu fehlt dir die Berechtigung (Server verwalten).",
        "added": "✅ Geplante Nachricht **#{id}** angelegt: {desc}. Nächste Ausführung: {next}.",
        "added_none": "✅ Geplante Nachricht **#{id}** angelegt – es gibt aber keinen künftigen Termin (Zeitplan prüfen).",
        "not_found": "Geplante Nachricht `{id}` nicht gefunden.",
        "removed": "🗑️ Geplante Nachricht `{id}` gelöscht.",
        "paused": "⏸️ Geplante Nachricht `{id}` pausiert.",
        "resumed": "▶️ Geplante Nachricht `{id}` läuft wieder. Nächste Ausführung: {next}.",
        "resumed_none": "▶️ Geplante Nachricht `{id}` fortgesetzt – es gibt aber keinen künftigen Termin mehr.",
        "tested": "🧪 Testnachricht für `{id}` gesendet (ohne Ping).",
        "test_failed": "Test fehlgeschlagen: {error}",
        "list_empty": "Auf diesem Server sind keine Nachrichten geplant.",
        "list_header": "**Geplante Nachrichten** (Zeitzone {tz})",
        "list_row": "`#{id}` · {name} · {channel} · {desc} · {state}",
        "state_next": "nächste {next}",
        "state_paused": "⏸️ pausiert",
        "state_auto_paused": "⚠️ automatisch pausiert ({fails} Fehler)",
        "state_done": "✔️ abgeschlossen",
        "tz_current": "Zeitzone dieses Servers: **{tz}** (jetzt dort {now}).",
        "tz_set": "Zeitzone auf **{tz}** gesetzt. Alle Termine wurden neu berechnet.",
        "tz_unknown": "Unbekannte Zeitzone `{tz}`. Beispiele: `Europe/Berlin`, `Europe/Vienna`, `UTC`.",
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        # Validierung
        "err_spec": "Zeitplan nicht erkannt. Beispiele: `täglich 09:00`, `wöchentlich mo,mi,fr 18:00`, "
                    "`monatlich 31 12:00`, `einmalig 2026-10-01 18:00`, `alle 2h`, `alle 90m`.",
        "err_type": "Unbekannter Zeitplan-Typ.",
        "err_time": "Uhrzeit ungültig (Format HH:MM, z. B. 09:00).",
        "err_date": "Datum ungültig (Format JJJJ-MM-TT oder TT.MM.JJJJ).",
        "err_weekdays": "Bitte mindestens einen Wochentag wählen (mo, di, mi, do, fr, sa, so).",
        "err_day": "Tag im Monat muss zwischen 1 und 31 liegen.",
        "err_interval": "Intervall muss zwischen 10 Minuten und 31 Tagen liegen (z. B. `alle 30m`, `alle 2h`).",
        "err_range": "Das Enddatum liegt vor dem Startdatum.",
        "err_channel": "Bitte einen Textkanal wählen, in den der Bot schreiben kann.",
        "err_empty": "Die Nachricht ist leer – bitte Text und/oder Embed (Titel, Text oder Bild) angeben.",
        "err_content_len": "Der Text ist zu lang (max. {max} Zeichen).",
        "err_embed_len": "Das Embed ist zu lang (Titel max. 256, Text max. 4000 Zeichen).",
        "err_image": "Die Bild-URL muss mit http:// oder https:// beginnen.",
        "err_color": "Ungültige Farbe (Format #RRGGBB).",
        "err_role": "Die Ping-Rolle gibt es auf diesem Server nicht.",
        "err_past": "Dieser Termin liegt in der Vergangenheit – es gäbe keine Ausführung.",
        "err_too_many": "Zu viele geplante Nachrichten auf diesem Server (max. {max}).",
        # Sendefehler (Dashboard/Log)
        "send_no_channel": "Kanal nicht gefunden (gelöscht?)",
        "send_forbidden": "Keine Rechte zum Senden im Kanal",
        "send_http": "Discord-Fehler {status}: {text}",
    },
    "en": {
        "no_permission": "You lack permission for that (Manage Server).",
        "added": "✅ Scheduled message **#{id}** created: {desc}. Next run: {next}.",
        "added_none": "✅ Scheduled message **#{id}** created – but there is no upcoming run (check the schedule).",
        "not_found": "Scheduled message `{id}` not found.",
        "removed": "🗑️ Scheduled message `{id}` deleted.",
        "paused": "⏸️ Scheduled message `{id}` paused.",
        "resumed": "▶️ Scheduled message `{id}` resumed. Next run: {next}.",
        "resumed_none": "▶️ Scheduled message `{id}` resumed – but there is no upcoming run anymore.",
        "tested": "🧪 Test message for `{id}` sent (without ping).",
        "test_failed": "Test failed: {error}",
        "list_empty": "No messages are scheduled on this server.",
        "list_header": "**Scheduled messages** (time zone {tz})",
        "list_row": "`#{id}` · {name} · {channel} · {desc} · {state}",
        "state_next": "next {next}",
        "state_paused": "⏸️ paused",
        "state_auto_paused": "⚠️ auto-paused ({fails} errors)",
        "state_done": "✔️ finished",
        "tz_current": "Time zone of this server: **{tz}** (now {now}).",
        "tz_set": "Time zone set to **{tz}**. All runs were recalculated.",
        "tz_unknown": "Unknown time zone `{tz}`. Examples: `Europe/Berlin`, `Europe/Vienna`, `UTC`.",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "err_spec": "Schedule not recognized. Examples: `daily 09:00`, `weekly mon,wed,fri 18:00`, "
                    "`monthly 31 12:00`, `once 2026-10-01 18:00`, `every 2h`, `every 90m`.",
        "err_type": "Unknown schedule type.",
        "err_time": "Invalid time (format HH:MM, e.g. 09:00).",
        "err_date": "Invalid date (format YYYY-MM-DD or DD.MM.YYYY).",
        "err_weekdays": "Please choose at least one weekday (mon, tue, wed, thu, fri, sat, sun).",
        "err_day": "Day of month must be between 1 and 31.",
        "err_interval": "Interval must be between 10 minutes and 31 days (e.g. `every 30m`, `every 2h`).",
        "err_range": "The end date is before the start date.",
        "err_channel": "Please choose a text channel the bot can write to.",
        "err_empty": "The message is empty – please provide text and/or an embed (title, text or image).",
        "err_content_len": "The text is too long (max. {max} characters).",
        "err_embed_len": "The embed is too long (title max. 256, text max. 4000 characters).",
        "err_image": "The image URL must start with http:// or https://.",
        "err_color": "Invalid color (format #RRGGBB).",
        "err_role": "The ping role does not exist on this server.",
        "err_past": "This date is in the past – there would be no run.",
        "err_too_many": "Too many scheduled messages on this server (max. {max}).",
        "send_no_channel": "Channel not found (deleted?)",
        "send_forbidden": "Missing permission to send in the channel",
        "send_http": "Discord error {status}: {text}",
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
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
