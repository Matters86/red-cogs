"""Mehrsprachigkeit für den Poll-Cog.

Aufbau wie im Tickets-/RaidHelper-Cog:
1. Sprachpakete (``STRINGS``) – ``de`` ist Standard und Fallback. Weitere
   Sprache = ein weiterer Block.
2. Pro-Server-Overrides (Config ``messages``) überschreiben einzelne sichtbare
   Texte; wird im Cog/Dashboard ausgewertet, nicht hier.

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
        # Embed
        "embed_by": "Umfrage von {author}",
        "embed_multiple": "Mehrfachauswahl",
        "embed_single": "Eine Stimme",
        "embed_anonymous": "Anonym",
        "embed_ends": "⏳ Endet {rel}",
        "embed_ended": "🏁 Beendet",
        "embed_closed": "🔒 Geschlossen",
        "embed_no_votes": "Noch keine Stimmen – sei die/der Erste!",
        "embed_total": "{count} Stimmen · {voters} Teilnehmer",
        "embed_winner_tag": "🏆",
        # Interaktion (ephemer)
        "vote_added": "✅ Stimme für **{option}** gezählt.",
        "vote_removed": "↩️ Deine Stimme für **{option}** wurde zurückgezogen.",
        "vote_changed": "🔄 Stimme geändert zu **{option}**.",
        "vote_closed": "Diese Umfrage ist geschlossen.",
        "vote_ended": "Diese Umfrage ist beendet.",
        "unknown_poll": "Diese Umfrage existiert nicht mehr.",
        "unknown_option": "Option nicht erkannt – bitte erneut versuchen.",
        # Befehle – Erstellen
        "created": "✅ Umfrage erstellt: {link}",
        "create_few_options": "Bitte mindestens zwei Optionen angeben (getrennt mit `|`).",
        "create_too_many": "Zu viele Optionen (max. {max}).",
        "create_bad_duration": "Dauer nicht erkannt. Beispiele: `30m`, `2h`, `1d`, `1d12h`.",
        "create_bad_channel": "In diesem Kanal kann keine Umfrage gepostet werden.",
        # Befehle – Verwaltung
        "no_permission_create": "Umfragen erstellen ist auf Mods/Manager beschränkt.",
        "no_permission_manage": "Dazu fehlt dir die Berechtigung (eigene Umfrage, Manager-Rolle oder Server verwalten).",
        "no_permission_admin": "Dazu fehlt dir die Berechtigung (Server verwalten oder Admin).",
        "deleted": "🗑️ Umfrage `{id}` gelöscht.",
        "closed": "🔒 Umfrage `{id}` geschlossen.",
        "reopened": "🔓 Umfrage `{id}` wieder geöffnet (ohne Zeitlimit).",
        "not_found": "Umfrage `{id}` nicht gefunden.",
        "no_polls": "Auf diesem Server sind keine Umfragen gespeichert.",
        "list_header": "**Umfragen auf diesem Server**",
        "list_row": "`{id}` · {question} · {votes} Stimmen · {status}",
        "status_open": "offen",
        "status_closed": "geschlossen",
        "status_ended": "beendet",
        # Ergebnis-Ansage / Ende
        "ended_announcement": "🏁 Die Umfrage **{question}** ist beendet!\n{result}",
        "result_winner": "🏆 **{option}** mit {votes} Stimmen ({pct}%).",
        "result_tie": "Unentschieden zwischen: {options} (je {votes} Stimmen).",
        "result_none": "Es wurden keine Stimmen abgegeben.",
        # Einstellungen
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "set_multiple": "Standard-Mehrfachauswahl: **{state}**.",
        "set_anonymous": "Standard-Sichtbarkeit: **{state}**.",
        "state_multiple_on": "an (mehrere Stimmen)",
        "state_multiple_off": "aus (eine Stimme)",
        "state_anon_on": "anonym",
        "state_anon_off": "öffentlich",
        "allowcreate_set": "Umfragen erstellen dürfen jetzt: **{who}**.",
        "allowcreate_unknown": "Unbekannt. Erlaubt: `everyone`, `manager`.",
        "who_everyone": "alle Mitglieder",
        "who_manager": "Mods/Manager",
        "mgr_added": "Manager-Rolle hinzugefügt: {role}.",
        "mgr_removed": "Manager-Rolle entfernt: {role}.",
        "maxoptions_set": "Maximale Optionen pro Umfrage: **{n}**.",
        "maxoptions_bad": "Bitte eine Zahl zwischen 2 und 25 angeben.",
        "dashboard_hint": "Die Umfragen-Seite findest du im WebCore-Dashboard unter `/cogs/poll`.",
        "dashboard_missing": "WebCore ist nicht geladen – Dashboard nicht verfügbar.",
    },
    "en": {
        "embed_by": "Poll by {author}",
        "embed_multiple": "Multiple choice",
        "embed_single": "Single vote",
        "embed_anonymous": "Anonymous",
        "embed_ends": "⏳ Ends {rel}",
        "embed_ended": "🏁 Ended",
        "embed_closed": "🔒 Closed",
        "embed_no_votes": "No votes yet – be the first!",
        "embed_total": "{count} votes · {voters} participants",
        "embed_winner_tag": "🏆",
        "vote_added": "✅ Vote for **{option}** counted.",
        "vote_removed": "↩️ Your vote for **{option}** was removed.",
        "vote_changed": "🔄 Vote changed to **{option}**.",
        "vote_closed": "This poll is closed.",
        "vote_ended": "This poll has ended.",
        "unknown_poll": "This poll no longer exists.",
        "unknown_option": "Option not recognized – please try again.",
        "created": "✅ Poll created: {link}",
        "create_few_options": "Please provide at least two options (separated by `|`).",
        "create_too_many": "Too many options (max. {max}).",
        "create_bad_duration": "Duration not recognized. Examples: `30m`, `2h`, `1d`, `1d12h`.",
        "create_bad_channel": "A poll cannot be posted in this channel.",
        "no_permission_create": "Creating polls is restricted to mods/managers.",
        "no_permission_manage": "You lack permission for that (own poll, manager role or Manage Server).",
        "no_permission_admin": "You lack permission for that (Manage Server or Admin).",
        "deleted": "🗑️ Poll `{id}` deleted.",
        "closed": "🔒 Poll `{id}` closed.",
        "reopened": "🔓 Poll `{id}` reopened (without time limit).",
        "not_found": "Poll `{id}` not found.",
        "no_polls": "No polls stored for this server.",
        "list_header": "**Polls on this server**",
        "list_row": "`{id}` · {question} · {votes} votes · {status}",
        "status_open": "open",
        "status_closed": "closed",
        "status_ended": "ended",
        "ended_announcement": "🏁 The poll **{question}** has ended!\n{result}",
        "result_winner": "🏆 **{option}** with {votes} votes ({pct}%).",
        "result_tie": "Tie between: {options} ({votes} votes each).",
        "result_none": "No votes were cast.",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "set_multiple": "Default multiple choice: **{state}**.",
        "set_anonymous": "Default visibility: **{state}**.",
        "state_multiple_on": "on (multiple votes)",
        "state_multiple_off": "off (single vote)",
        "state_anon_on": "anonymous",
        "state_anon_off": "public",
        "allowcreate_set": "Polls may now be created by: **{who}**.",
        "allowcreate_unknown": "Unknown. Allowed: `everyone`, `manager`.",
        "who_everyone": "all members",
        "who_manager": "mods/managers",
        "mgr_added": "Manager role added: {role}.",
        "mgr_removed": "Manager role removed: {role}.",
        "maxoptions_set": "Maximum options per poll: **{n}**.",
        "maxoptions_bad": "Please provide a number between 2 and 25.",
        "dashboard_hint": "You can find the polls page in the WebCore dashboard at `/cogs/poll`.",
        "dashboard_missing": "WebCore is not loaded – dashboard unavailable.",
    },
}

# Keys, die ein Server frei überschreiben darf (Dashboard zeigt genau diese).
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "embed_no_votes",
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
