"""Mehrsprachigkeit für den RaidHelper-Cog.

Aufbau wie im Tickets-Cog:
1. Sprachpakete (``STRINGS``) – ``de`` ist Standard und Fallback. Weitere
   Sprache = ein weiterer Block.
2. Pro-Server-Overrides (Config ``messages``) überschreiben einzelne sichtbare
   Texte; wird im Cog/Dashboard ausgewertet, nicht hier.

Hinweis: **Rollen**-Bezeichnungen sind hier übersetzbar (``role_*``), während
Klassen-/Spec-Namen aus ``games.py`` stammen (eine Quelle, deutsch).

``t(lang, key, **kwargs)`` liefert den passenden String, fällt bei fehlender
Sprache/fehlendem Key auf Deutsch bzw. den Key selbst zurück und formatiert
optional mit ``str.format``.
"""

from __future__ import annotations

# Reihenfolge = Anzeige-Reihenfolge im Dashboard-Dropdown.
LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # Rollen (Roster-Überschriften)
        "role_tank": "Tanks",
        "role_healer": "Heiler",
        "role_mdps": "Nahkampf",
        "role_rdps": "Fernkampf",
        # Status (außerhalb des Roster-Zählers)
        "status_bench": "Bank",
        "status_late": "Spät",
        "status_tentative": "Vielleicht",
        "status_absence": "Abwesend",
        # Embed
        "embed_leader": "Raidleitung: {leader}",
        "embed_when": "🗓️ {time} ({rel})",
        "embed_deadline": "⏳ Anmeldeschluss: {time}",
        "embed_signups": "👥 {count} Anmeldungen · {roster} im Roster",
        "embed_no_signups": "Noch keine Anmeldungen – sei die/der Erste!",
        "embed_closed": "🔒 Anmeldung geschlossen",
        "embed_recurring": "🔁 Wiederholung: {rule}",
        "roster_more": "… +{n} weitere",
        # Buttons
        "btn_pick_class": "Klasse wählen",
        "btn_bench": "Bank",
        "btn_late": "Spät",
        "btn_tentative": "Vielleicht",
        "btn_absence": "Abwesend",
        "btn_leave": "Abmelden",
        "select_class_placeholder": "Klasse wählen …",
        "select_spec_placeholder": "Spec wählen …",
        # Interaktions-Antworten (ephemer)
        "pick_spec": "Wähle deine Spezialisierung für **{cls}**:",
        "signed": "✅ Angemeldet als **{spec} {cls}** ({role}).",
        "spec_changed": "🔄 Spec geändert auf **{spec} {cls}**.",
        "moved_status": "✅ Du stehst jetzt auf: **{status}**.",
        "left": "↩️ Du wurdest vom Event abgemeldet.",
        "not_signed": "Du bist für dieses Event nicht angemeldet.",
        "signup_closed": "Die Anmeldung für dieses Event ist geschlossen.",
        "deadline_passed": "Der Anmeldeschluss ist bereits vorbei.",
        "event_full": "Das Event ist voll ({max} Plätze).",
        "role_full": "Diese Rolle ist voll ({label}: {max}).",
        "class_full": "Das Limit für diese Klasse ist erreicht ({max}).",
        "unknown_event": "Dieses Event existiert nicht mehr.",
        "unknown_pick": "Auswahl nicht erkannt – bitte erneut versuchen.",
        # Befehle – Erfolg/Hinweise
        "created": "✅ Event erstellt: {link}",
        "create_no_channel": "Kein Anmelde-Kanal gesetzt. Nutze `{p}raidset channel #kanal`.",
        "create_bad_date": "Datum/Uhrzeit nicht erkannt. Format: `TT.MM.JJJJ HH:MM` (z. B. 13.06.2026 20:00).",
        "create_bad_game": "Unbekanntes Spiel `{game}`. Verfügbar: {games}.",
        "create_past": "Der Zeitpunkt liegt in der Vergangenheit.",
        "deleted": "🗑️ Event `{id}` gelöscht.",
        "closed": "🔒 Anmeldung für `{id}` geschlossen.",
        "reopened": "🔓 Anmeldung für `{id}` wieder geöffnet.",
        "not_found": "Event `{id}` nicht gefunden.",
        "no_events": "Für diesen Server sind keine Events gespeichert.",
        "no_permission": "Dazu fehlt dir die Berechtigung (Manager-Rolle oder Server verwalten).",
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "game_set": "Standard-Spiel auf **{game}** gesetzt.",
        "channel_set": "Anmelde-Kanal auf {channel} gesetzt.",
        "tz_set": "Anzeige-Zeitzone auf `{tz}` gesetzt.",
        "tz_unknown": "Unbekannte Zeitzone `{tz}`.",
        "mgr_added": "Manager-Rolle hinzugefügt: {role}.",
        "mgr_removed": "Manager-Rolle entfernt: {role}.",
        "added_manual": "➕ {user} als **{spec} {cls}** eingetragen.",
        "removed_manual": "➖ {user} aus dem Event entfernt.",
        "list_header": "**Events auf diesem Server**",
        "list_row": "`{id}` · {game} · {time} · {signups} Anmeldungen · {status}",
        "status_open": "offen",
        "status_closed": "geschlossen",
        # Erinnerungen
        "reminder": "⏰ **{title}** startet {rel}! Aktuell **{signups}** Anmeldungen.",
        "reminder_dm": "Erinnerung: **{title}** startet {rel}. Du bist als {spec} {cls} angemeldet.",
        # Statistik
        "stats_title": "Teilnahme-Statistik",
        "stats_attended": "Teilnahmen",
        "stats_signups": "Anmeldungen",
        # Dashboard
        "dash_settings": "Einstellungen",
        "dash_events": "Kommende Events",
        "dash_new_event": "Neues Event",
        "dash_saved": "Gespeichert.",
        # Klassen-Icons
        "icons_list_header": "**Klassen-Icons** (gelten botweit für alle WoW-Vorlagen)",
        "icon_set": "✅ Icon für **{cls}** gesetzt: {emoji}",
        "icon_removed": "🗑️ Icon für **{cls}** entfernt.",
        "icon_unknown_class": "Unbekannte Klasse `{cls}`. Verfügbar: {classes}.",
        "icons_unsupported": "Dieser Bot unterstützt keine Application-Emojis (discord.py < 2.4). Bitte Red aktualisieren oder Icons manuell per `classicon` mit vorhandenen Emojis setzen.",
        "icons_no_files": "Bitte hänge die Icon-Dateien an die Nachricht an (Dateiname = Klassen-ID, z. B. `krieger.png`).",
        "icons_upload_result": "Fertig: {ok} Icon(s) gesetzt, {skipped} übersprungen.",
    },
    "en": {
        "role_tank": "Tanks",
        "role_healer": "Healers",
        "role_mdps": "Melee",
        "role_rdps": "Ranged",
        "status_bench": "Bench",
        "status_late": "Late",
        "status_tentative": "Tentative",
        "status_absence": "Absence",
        "embed_leader": "Organizer: {leader}",
        "embed_when": "🗓️ {time} ({rel})",
        "embed_deadline": "⏳ Sign-up closes: {time}",
        "embed_signups": "👥 {count} sign-ups · {roster} in roster",
        "embed_no_signups": "No sign-ups yet – be the first!",
        "embed_closed": "🔒 Sign-up closed",
        "embed_recurring": "🔁 Repeats: {rule}",
        "roster_more": "… +{n} more",
        "btn_pick_class": "Pick class",
        "btn_bench": "Bench",
        "btn_late": "Late",
        "btn_tentative": "Tentative",
        "btn_absence": "Absence",
        "btn_leave": "Leave",
        "select_class_placeholder": "Pick a class …",
        "select_spec_placeholder": "Pick a spec …",
        "pick_spec": "Choose your specialization for **{cls}**:",
        "signed": "✅ Signed up as **{spec} {cls}** ({role}).",
        "spec_changed": "🔄 Spec changed to **{spec} {cls}**.",
        "moved_status": "✅ You are now: **{status}**.",
        "left": "↩️ You have been removed from the event.",
        "not_signed": "You are not signed up for this event.",
        "signup_closed": "Sign-up for this event is closed.",
        "deadline_passed": "The sign-up deadline has already passed.",
        "event_full": "The event is full ({max} slots).",
        "role_full": "This role is full ({label}: {max}).",
        "class_full": "The limit for this class has been reached ({max}).",
        "unknown_event": "This event no longer exists.",
        "unknown_pick": "Selection not recognized – please try again.",
        "created": "✅ Event created: {link}",
        "create_no_channel": "No sign-up channel set. Use `{p}raidset channel #channel`.",
        "create_bad_date": "Date/time not recognized. Format: `DD.MM.YYYY HH:MM`.",
        "create_bad_game": "Unknown game `{game}`. Available: {games}.",
        "create_past": "That point in time is in the past.",
        "deleted": "🗑️ Event `{id}` deleted.",
        "closed": "🔒 Sign-up for `{id}` closed.",
        "reopened": "🔓 Sign-up for `{id}` reopened.",
        "not_found": "Event `{id}` not found.",
        "no_events": "No events stored for this server.",
        "no_permission": "You lack permission for that (manager role or Manage Server).",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "game_set": "Default game set to **{game}**.",
        "channel_set": "Sign-up channel set to {channel}.",
        "tz_set": "Display timezone set to `{tz}`.",
        "tz_unknown": "Unknown timezone `{tz}`.",
        "mgr_added": "Manager role added: {role}.",
        "mgr_removed": "Manager role removed: {role}.",
        "added_manual": "➕ {user} added as **{spec} {cls}**.",
        "removed_manual": "➖ {user} removed from the event.",
        "list_header": "**Events on this server**",
        "list_row": "`{id}` · {game} · {time} · {signups} sign-ups · {status}",
        "status_open": "open",
        "status_closed": "closed",
        "reminder": "⏰ **{title}** starts {rel}! Currently **{signups}** sign-ups.",
        "reminder_dm": "Reminder: **{title}** starts {rel}. You are signed up as {spec} {cls}.",
        "stats_title": "Attendance statistics",
        "stats_attended": "Attended",
        "stats_signups": "Sign-ups",
        "dash_settings": "Settings",
        "dash_events": "Upcoming events",
        "dash_new_event": "New event",
        "dash_saved": "Saved.",
        "icons_list_header": "**Class icons** (apply bot-wide to all WoW templates)",
        "icon_set": "✅ Icon for **{cls}** set: {emoji}",
        "icon_removed": "🗑️ Icon for **{cls}** removed.",
        "icon_unknown_class": "Unknown class `{cls}`. Available: {classes}.",
        "icons_unsupported": "This bot does not support application emojis (discord.py < 2.4). Please update Red, or set icons manually via `classicon` using existing emojis.",
        "icons_no_files": "Please attach the icon files to the message (filename = class id, e.g. `krieger.png`).",
        "icons_upload_result": "Done: {ok} icon(s) set, {skipped} skipped.",
    },
}

# Keys, die ein Server frei überschreiben darf (Dashboard zeigt genau diese).
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "embed_no_signups",
    "reminder",
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


def role_name(lang: str | None, role_id: str) -> str:
    """Übersetzte Rollen-Überschrift (z. B. 'mdps' -> 'Nahkampf')."""
    return t(lang, f"role_{role_id}")
