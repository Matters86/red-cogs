"""Mehrsprachigkeit für den Tickets-Cog.

Zwei Ebenen:
1. Sprachpakete (``STRINGS``) – Standard-Texte je Sprache. ``de`` ist Standard
   und Fallback. Weitere Sprachen = einfach ein weiterer Block hier.
2. Pro-Server-Overrides (in der Config unter ``messages``) – überschreiben
   einzelne sichtbare Texte. Wird im Cog/Dashboard ausgewertet, nicht hier.

Helfer ``t(lang, key, **kwargs)`` liefert den passenden String, fällt bei
fehlender Sprache/fehlendem Key auf Deutsch bzw. den Key selbst zurück und
formatiert optional mit ``str.format``.
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
        # Panels
        "panel_default_title": "Support-Ticket",
        "panel_default_description": "Klicke unten, um ein Ticket zu öffnen. Unser Team meldet sich so schnell wie möglich.",
        "btn_open": "Ticket öffnen",
        "select_placeholder": "Grund auswählen …",
        # Erstellung
        "opened_title": "Ticket #{num}",
        "opened_body": "Hallo {user}, willkommen in deinem Ticket. Bitte beschreibe dein Anliegen – das Team wurde benachrichtigt.",
        "opened_reason": "Grund: **{reason}**",
        "created_ephemeral": "Dein Ticket wurde erstellt: {channel}",
        "max_open_reached": "Du hast bereits die maximale Anzahl offener Tickets ({max}).",
        "no_reason": "Kein Grund angegeben",
        # Steuer-Buttons
        "btn_close": "Schließen",
        "btn_claim": "Übernehmen",
        "btn_unclaim": "Freigeben",
        "btn_lock": "Sperren",
        "btn_unlock": "Entsperren",
        # Aktionen / Statusmeldungen
        "claimed_by": "🙋 Übernommen von {user}.",
        "unclaimed_by": "↩️ Von {user} freigegeben.",
        "closed_by": "🔒 Ticket geschlossen von {user}.",
        "reopened_by": "🔓 Ticket wieder geöffnet von {user}.",
        "locked_by": "🔇 Ticket gesperrt von {user}.",
        "unlocked_by": "🔊 Ticket entsperrt von {user}.",
        "member_added": "➕ {user} wurde hinzugefügt.",
        "member_removed": "➖ {user} wurde entfernt.",
        "renamed_to": "✏️ Ticket umbenannt in **{name}**.",
        "owner_changed": "👤 Neuer Ticket-Inhaber: {user}.",
        "confirm_close": "Dieses Ticket wirklich schließen?",
        "confirm_yes": "Ja, schließen",
        "confirm_no": "Abbrechen",
        "cancelled": "Abgebrochen.",
        # Fehler / Hinweise
        "not_a_ticket": "Dieser Kanal ist kein Ticket.",
        "no_permission": "Dazu hast du keine Berechtigung.",
        "already_claimed": "Dieses Ticket wurde bereits von {user} übernommen.",
        "transcript_saved": "Transcript gespeichert.",
        # Log-Channel
        "log_opened": "Ticket #{num} geöffnet von {user} ({reason}).",
        "log_closed": "Ticket #{num} geschlossen von {user}. Laufzeit: {duration}.",
        "log_claimed": "Ticket #{num} übernommen von {user}.",
        # Modal
        "modal_title": "Ticket öffnen",
    },
    "en": {
        "panel_default_title": "Support Ticket",
        "panel_default_description": "Click below to open a ticket. Our team will get back to you as soon as possible.",
        "btn_open": "Open ticket",
        "select_placeholder": "Choose a reason …",
        "opened_title": "Ticket #{num}",
        "opened_body": "Hi {user}, welcome to your ticket. Please describe your request – the team has been notified.",
        "opened_reason": "Reason: **{reason}**",
        "created_ephemeral": "Your ticket has been created: {channel}",
        "max_open_reached": "You already have the maximum number of open tickets ({max}).",
        "no_reason": "No reason provided",
        "btn_close": "Close",
        "btn_claim": "Claim",
        "btn_unclaim": "Unclaim",
        "btn_lock": "Lock",
        "btn_unlock": "Unlock",
        "claimed_by": "🙋 Claimed by {user}.",
        "unclaimed_by": "↩️ Released by {user}.",
        "closed_by": "🔒 Ticket closed by {user}.",
        "reopened_by": "🔓 Ticket reopened by {user}.",
        "locked_by": "🔇 Ticket locked by {user}.",
        "unlocked_by": "🔊 Ticket unlocked by {user}.",
        "member_added": "➕ {user} was added.",
        "member_removed": "➖ {user} was removed.",
        "renamed_to": "✏️ Ticket renamed to **{name}**.",
        "owner_changed": "👤 New ticket owner: {user}.",
        "confirm_close": "Really close this ticket?",
        "confirm_yes": "Yes, close",
        "confirm_no": "Cancel",
        "cancelled": "Cancelled.",
        "not_a_ticket": "This channel is not a ticket.",
        "no_permission": "You don't have permission to do that.",
        "already_claimed": "This ticket was already claimed by {user}.",
        "transcript_saved": "Transcript saved.",
        "log_opened": "Ticket #{num} opened by {user} ({reason}).",
        "log_closed": "Ticket #{num} closed by {user}. Duration: {duration}.",
        "log_claimed": "Ticket #{num} claimed by {user}.",
        "modal_title": "Open ticket",
    },
}

# Keys, die ein Server frei überschreiben darf (Dashboard zeigt genau diese an).
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "panel_default_title",
    "panel_default_description",
    "btn_open",
    "opened_title",
    "opened_body",
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
