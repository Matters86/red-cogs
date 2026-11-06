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
        "btn_autoclose": "24h-Timer starten",
        "btn_keep_open": "Offen halten",
        "autoclose_started": "⏱️ {user} hat den 24-Stunden-Timer gestartet. Dieses Ticket wird nach 24 Stunden ohne neue Nachricht automatisch geschlossen. Jede Nachricht eines Nutzers oder Team-Mitglieds setzt den Timer zurück. Mit **Offen halten** kannst du den Timer dauerhaft stoppen; **Schließen** schließt sofort.",
        "autoclose_cancelled": "⏹️ {user} hat den Timer gestoppt. Das Ticket bleibt offen, bis es manuell geschlossen oder der 24-Stunden-Timer erneut gestartet wird.",
        "autoclose_ack": "Der 24-Stunden-Timer ist aktiv. Neue Nachrichten setzen ihn zurück.",
        "keep_open_ack": "Der Timer ist aus. Das Ticket bleibt offen.",
        "auto_closed": "🔒 Automatisch geschlossen: 24 Stunden lang keine neue Nachricht von Nutzern oder Team-Mitgliedern.",
        "btn_claim": "Übernehmen",
        "btn_assign": "Zuweisen",
        "btn_wait_user": "Auf Nutzer warten",
        "btn_wait_team": "Auf Team warten",
        "waiting_user": "Wartet auf Nutzer",
        "waiting_team": "Wartet auf Team",
        "waiting_changed": "Wartestatus aktualisiert.",
        "waiting_footer": "Zuständig: {user} · {status}",
        "close_reminder": "⏱️ {user} Dieses Ticket wird bei weiterer Inaktivität <t:{deadline}:R> geschlossen (<t:{deadline}:f>). Mit **Offen halten** stoppst du den Timer; eine neue Nachricht setzt ihn auf weitere 24 Stunden.",
        "assign_placeholder": "Teammitglied suchen und auswählen …",
        "assign_prompt": "Wähle das zuständige Teammitglied. Es muss zum Support gehören und Zugriff auf dieses Ticket haben. Eine bestehende Zuständigkeit wird ersetzt.",
        "assignment_invalid": "Wähle ein Teammitglied mit Lese- und Schreibzugriff auf dieses Ticket. Bots und der Ticket-Ersteller können nicht zugewiesen werden.",
        "assignment_access_failed": "Das Teammitglied konnte dem Thread nicht hinzugefügt werden. Bitte die Bot-Berechtigungen prüfen.",
        "assignment_unchanged": "Diese Zuständigkeit ist bereits eingestellt.",
        "assignment_done": "Zuständigkeit aktualisiert.",
        "assigned_by": "👤 {actor} hat dieses Ticket {user} zugewiesen.",
        "assignee_footer": "Zuständig: {user}",
        "unassigned": "Noch nicht zugewiesen",
        "log_assigned": "Ticket #{num}: {actor} hat die Zuständigkeit geändert → {user}.",
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
        "claim_own_denied": "Du kannst dein eigenes Ticket nicht übernehmen.",
        "already_claimed": "Dieses Ticket wurde bereits von {user} übernommen.",
        "transcript_saved": "Transcript gespeichert.",
        "already_closed": "Dieses Ticket ist bereits geschlossen.",
        "not_closed": "Dieses Ticket ist nicht geschlossen.",
        "create_failed": "Ticket konnte nicht erstellt werden – bitte das Team informieren (Konfiguration: Kategorie/Forum/Basis-Kanal/Rechte).",
        # Log-Channel
        "log_opened": "Ticket #{num} geöffnet von {user} ({reason}).",
        "log_closed": "Ticket #{num} geschlossen von {user}. Laufzeit: {duration}.",
        "log_claimed": "Ticket #{num} übernommen von {user}.",
        # Modal
        "modal_title": "Ticket öffnen",
        # Datenlöschung (red_delete_data_for_user)
        "deleted_user": "Gelöschter Nutzer",
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
        "btn_autoclose": "Start 24h timer",
        "btn_keep_open": "Keep open",
        "autoclose_started": "⏱️ {user} started the 24-hour timer. This ticket will close automatically after 24 hours without a new message. Each message from a user or team member resets the timer. **Keep open** stops it until manually started again; **Close** closes immediately.",
        "autoclose_cancelled": "⏹️ {user} stopped the timer. This ticket stays open until closed manually or the 24-hour timer is started again.",
        "autoclose_ack": "The 24-hour timer is active. New messages reset it.",
        "keep_open_ack": "The timer is off. This ticket stays open.",
        "auto_closed": "🔒 Closed automatically: no new message from a user or team member for 24 hours.",
        "btn_claim": "Claim",
        "btn_assign": "Assign",
        "btn_wait_user": "Wait for user",
        "btn_wait_team": "Wait for team",
        "waiting_user": "Waiting for user",
        "waiting_team": "Waiting for team",
        "waiting_changed": "Waiting status updated.",
        "waiting_footer": "Assigned to: {user} · {status}",
        "close_reminder": "⏱️ {user} This ticket will close <t:{deadline}:R> if there is no activity (<t:{deadline}:f>). **Keep open** stops the timer; a new message resets it to another 24 hours.",
        "assign_placeholder": "Search and select a team member …",
        "assign_prompt": "Select the responsible team member. They must be support staff and have access to this ticket. This replaces any current assignment.",
        "assignment_invalid": "Choose a team member who can read and write in this ticket. Bots and the ticket creator cannot be assigned.",
        "assignment_access_failed": "The team member could not be added to the thread. Please check the bot's permissions.",
        "assignment_unchanged": "This assignment is already set.",
        "assignment_done": "Assignment updated.",
        "assigned_by": "👤 {actor} assigned this ticket to {user}.",
        "assignee_footer": "Assigned to: {user}",
        "unassigned": "Not assigned yet",
        "log_assigned": "Ticket #{num}: {actor} changed the assignment → {user}.",
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
        "claim_own_denied": "You can't claim your own ticket.",
        "already_claimed": "This ticket was already claimed by {user}.",
        "transcript_saved": "Transcript saved.",
        "already_closed": "This ticket is already closed.",
        "not_closed": "This ticket is not closed.",
        "create_failed": "The ticket could not be created – please inform the team (configuration: category/forum/base channel/permissions).",
        "log_opened": "Ticket #{num} opened by {user} ({reason}).",
        "log_closed": "Ticket #{num} closed by {user}. Duration: {duration}.",
        "log_claimed": "Ticket #{num} claimed by {user}.",
        "modal_title": "Open ticket",
        "deleted_user": "Deleted user",
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
