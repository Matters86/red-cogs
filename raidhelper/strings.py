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
        "create_empty_title": "Bitte einen Titel angeben.",
        "create_title_long": "Der Titel ist zu lang (max. {max} Zeichen).",
        "create_desc_long": "Die Beschreibung ist zu lang (max. {max} Zeichen).",
        "create_bad_max": "Maximale Teilnehmer: bitte eine Zahl von 0 bis {max} angeben (0 = unbegrenzt).",
        "create_bad_rolelimit": "Limit für {label}: bitte eine Zahl von 0 bis {max} angeben (0 = kein Limit).",
        "deadline_after_start": "Der Anmeldeschluss muss vor dem Start liegen.",
        "create_no_perms": "Der Bot darf in {channel} nicht posten – er braucht dort „Kanal ansehen“, „Nachrichten senden“ und „Links einbetten“.",
        "edit_completed": "Event `{id}` ist bereits abgeschlossen – der Termin lässt sich nicht mehr ändern.",
        "edited": "✅ Event `{id}` aktualisiert.",
        "time_set": "✅ Termin für `{id}` auf {time} verschoben – Erinnerungen werden neu gesendet.",
        "deleted": "🗑️ Event `{id}` gelöscht.",
        "closed": "🔒 Anmeldung für `{id}` geschlossen.",
        "reopened": "🔓 Anmeldung für `{id}` wieder geöffnet.",
        "not_found": "Event `{id}` nicht gefunden.",
        "reposted": "📨 Event `{id}` neu gepostet: {link}",
        "repost_failed": "Die Event-Nachricht konnte in {channel} nicht gepostet werden – bitte die Bot-Rechte prüfen.",
        "no_events": "Für diesen Server sind keine Events gespeichert.",
        "no_permission": "Dazu fehlt dir die Berechtigung (Manager-Rolle oder Server verwalten).",
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "game_set": "Standard-Spiel auf **{game}** gesetzt.",
        "channel_set": "Anmelde-Kanal auf {channel} gesetzt.",
        "tz_set": "Anzeige-Zeitzone auf `{tz}` gesetzt.",
        "tz_unknown": "Unbekannte Zeitzone `{tz}`.",
        "cleanup_set": "Abgeschlossene Events werden nach **{days} Tagen** gelöscht (nur Daten, keine Nachrichten). Jetzt entfernt: {removed}.",
        "cleanup_off": "Automatisches Löschen alter Events ist **aus**.",
        "cleanup_bad": "Bitte eine Zahl von 0 bis 3650 angeben (0 = aus).",
        "mgr_added": "Manager-Rolle hinzugefügt: {role}.",
        "mgr_removed": "Manager-Rolle entfernt: {role}.",
        "added_manual": "➕ {user} als **{spec} {cls}** eingetragen.",
        "removed_manual": "➖ {user} aus dem Event entfernt.",
        # Event nachträglich konfigurieren (Manager)
        "description_set": "✅ Beschreibung für `{id}` aktualisiert.",
        "description_cleared": "🗑️ Beschreibung für `{id}` entfernt.",
        "deadline_set": "✅ Anmeldeschluss für `{id}` auf {time} gesetzt.",
        "recurrence_set": "✅ Wiederholung für `{id}` auf **{value}** gesetzt.",
        "recurrence_cleared": "✅ Wiederholung für `{id}` deaktiviert.",
        "recurrence_bad": "Ungültiger Wert `{value}`. Erlaubt: {allowed}.",
        "maxsignups_set": "✅ Maximale Anmeldungen für `{id}` auf {max} gesetzt.",
        "maxsignups_cleared": "✅ Anmeldungen für `{id}` sind jetzt unbegrenzt.",
        "rolelimit_set": "✅ Limit für **{label}** in `{id}` auf {max} gesetzt.",
        "rolelimit_cleared": "🗑️ Limit für **{label}** in `{id}` entfernt.",
        "rolelimit_bad_role": "Unbekannte Rolle `{role}`. Erlaubt: {roles}.",
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
        "dash_edit_event": "Event bearbeiten",
        "dash_created": "Event {id} erstellt und gepostet.",
        "dash_created_unposted": "Event {id} gespeichert, aber das Posten ist fehlgeschlagen – Rechte des Bots im Kanal prüfen.",
        "dash_updated": "Event {id} aktualisiert.",
        "dash_updated_nochange": "{id}: nichts geändert.",
        "dash_no_channel": "Bitte einen Textkanal wählen (oder unter „Einstellungen“ einen Anmelde-Kanal festlegen).",
        "dash_saved": "Gespeichert.",
        # Spec-Icons
        "icons_list_header": "**Spec-Icons** (gelten botweit für alle WoW-Vorlagen)",
        "icon_set": "✅ Icon für **{cls} / {spec}** gesetzt: {emoji}",
        "icon_removed": "🗑️ Icon für **{cls} / {spec}** entfernt.",
        "icon_unknown_pair": "Unbekannte Spezialisierung `{cls}:{spec}`.",
        "icons_unsupported": "Dieser Bot unterstützt keine Application-Emojis (discord.py < 2.4). Bitte Red aktualisieren oder Icons manuell per `specicon` mit vorhandenen Emojis setzen.",
        "icons_no_files": "Bitte hänge die Icon-Dateien an die Nachricht an (Dateiname = klasse_spec, z. B. `krieger_furor.png`).",
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
        "create_empty_title": "Please enter a title.",
        "create_title_long": "The title is too long (max. {max} characters).",
        "create_desc_long": "The description is too long (max. {max} characters).",
        "create_bad_max": "Max participants: please give a number from 0 to {max} (0 = unlimited).",
        "create_bad_rolelimit": "Limit for {label}: please give a number from 0 to {max} (0 = no limit).",
        "deadline_after_start": "The sign-up deadline must be before the start.",
        "create_no_perms": "The bot can't post in {channel} – it needs “View Channel”, “Send Messages” and “Embed Links” there.",
        "edit_completed": "Event `{id}` has already finished – its date can no longer be changed.",
        "edited": "✅ Event `{id}` updated.",
        "time_set": "✅ `{id}` moved to {time} – reminders will be sent again.",
        "deleted": "🗑️ Event `{id}` deleted.",
        "closed": "🔒 Sign-up for `{id}` closed.",
        "reopened": "🔓 Sign-up for `{id}` reopened.",
        "not_found": "Event `{id}` not found.",
        "reposted": "📨 Event `{id}` reposted: {link}",
        "repost_failed": "The event message could not be posted in {channel} – please check the bot's permissions.",
        "no_events": "No events stored for this server.",
        "no_permission": "You lack permission for that (manager role or Manage Server).",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "game_set": "Default game set to **{game}**.",
        "channel_set": "Sign-up channel set to {channel}.",
        "tz_set": "Display timezone set to `{tz}`.",
        "tz_unknown": "Unknown timezone `{tz}`.",
        "cleanup_set": "Completed events are deleted after **{days} days** (data only, no messages). Removed now: {removed}.",
        "cleanup_off": "Automatic deletion of old events is **off**.",
        "cleanup_bad": "Please give a number from 0 to 3650 (0 = off).",
        "mgr_added": "Manager role added: {role}.",
        "mgr_removed": "Manager role removed: {role}.",
        "added_manual": "➕ {user} added as **{spec} {cls}**.",
        "removed_manual": "➖ {user} removed from the event.",
        # Event configuration (manager)
        "description_set": "✅ Description for `{id}` updated.",
        "description_cleared": "🗑️ Description for `{id}` removed.",
        "deadline_set": "✅ Sign-up deadline for `{id}` set to {time}.",
        "recurrence_set": "✅ Recurrence for `{id}` set to **{value}**.",
        "recurrence_cleared": "✅ Recurrence for `{id}` disabled.",
        "recurrence_bad": "Invalid value `{value}`. Allowed: {allowed}.",
        "maxsignups_set": "✅ Max sign-ups for `{id}` set to {max}.",
        "maxsignups_cleared": "✅ Sign-ups for `{id}` are now unlimited.",
        "rolelimit_set": "✅ Limit for **{label}** in `{id}` set to {max}.",
        "rolelimit_cleared": "🗑️ Limit for **{label}** in `{id}` removed.",
        "rolelimit_bad_role": "Unknown role `{role}`. Allowed: {roles}.",
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
        "dash_edit_event": "Edit event",
        "dash_created": "Event {id} created and posted.",
        "dash_created_unposted": "Event {id} saved, but posting failed – check the bot's permissions in the channel.",
        "dash_updated": "Event {id} updated.",
        "dash_updated_nochange": "{id}: nothing changed.",
        "dash_no_channel": "Please pick a text channel (or set a sign-up channel under “Settings”).",
        "dash_saved": "Saved.",
        "icons_list_header": "**Spec icons** (apply bot-wide to all WoW templates)",
        "icon_set": "✅ Icon for **{cls} / {spec}** set: {emoji}",
        "icon_removed": "🗑️ Icon for **{cls} / {spec}** removed.",
        "icon_unknown_pair": "Unknown specialization `{cls}:{spec}`.",
        "icons_unsupported": "This bot does not support application emojis (discord.py < 2.4). Please update Red, or set icons manually via `specicon` using existing emojis.",
        "icons_no_files": "Please attach the icon files to the message (filename = class_spec, e.g. `krieger_furor.png`).",
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
