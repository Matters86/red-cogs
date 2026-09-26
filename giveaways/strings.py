"""Mehrsprachigkeit für den Giveaways-Cog (Aufbau wie poll/strings.py).

``de`` ist Standard und Fallback. ``t(lang, key, **kwargs)`` liefert den Text, fällt bei
fehlender Sprache/fehlendem Key auf Deutsch bzw. den Key zurück und formatiert mit ``str.format``.
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # Embed
        "embed_ends": "Endet {rel} ({abs})",
        "embed_ended": "Beendet {rel}",
        "embed_cancelled": "🚫 Abgebrochen – es wird nicht ausgelost.",
        "embed_winners_count": "Gewinner: **{n}**",
        "embed_host": "Veranstaltet von {host}",
        "embed_entries": "Teilnehmer",
        "embed_requirements": "Teilnahme-Voraussetzungen",
        "req_required": "Eine dieser Rollen: {roles}",
        "req_excluded": "Ausgeschlossen: {roles}",
        "req_days": "Mindestens {days} Tage auf dem Server",
        "embed_bonus": "Bonus-Lose",
        "bonus_line": "{role}: +{n}",
        "embed_winners": "Gewinner",
        "embed_no_winners": "Keine gültigen Teilnahmen – niemand hat gewonnen.",
        "embed_footer": "Gewinnspiel #{id} · Klicke auf 🎉, um teilzunehmen",
        "embed_footer_done": "Gewinnspiel #{id}",
        "button_join": "Teilnehmen",
        "button_ended": "Beendet",
        "button_cancelled": "Abgebrochen",
        "button_leave": "Ja, austreten",
        # Interaktion (ephemer)
        "joined": "🎉 Du nimmst jetzt teil! Lose: **{tickets}**. Viel Glück!",
        "already": "Du nimmst bereits teil (Lose: **{tickets}**). Möchtest du wirklich austreten?",
        "left": "↩️ Du nimmst nicht mehr an diesem Gewinnspiel teil.",
        "not_entered": "Du nimmst an diesem Gewinnspiel nicht teil.",
        "leave_timeout": "Keine Änderung – du nimmst weiter teil.",
        "err_unknown": "Dieses Gewinnspiel existiert nicht mehr.",
        "err_ended": "Dieses Gewinnspiel ist bereits beendet.",
        "err_bot": "Bots können nicht teilnehmen.",
        "err_excluded": "Mit deinen Rollen kannst du an diesem Gewinnspiel nicht teilnehmen.",
        "err_required": "Für die Teilnahme brauchst du eine dieser Rollen: {roles}.",
        "err_too_new": "Du musst mindestens {days} Tage auf dem Server sein, um teilzunehmen.",
        # Ansage
        "announce_winners": "🎉 Glückwunsch {mentions}! {verb} **{prize}** gewonnen!",
        "verb_one": "Du hast",
        "verb_many": "Ihr habt",
        "announce_none": "Das Gewinnspiel **{prize}** ist beendet – leider gab es keine gültigen Teilnahmen.",
        "announce_reroll": "🔁 Neu ausgelost für **{prize}**: Glückwunsch {mentions}!",
        # Befehle
        "no_permission": "Dazu fehlt dir die Berechtigung (Server verwalten oder Gewinnspiel-Manager-Rolle).",
        "no_permission_admin": "Dazu fehlt dir die Berechtigung (Server verwalten).",
        "started": "✅ Gewinnspiel **#{id}** gestartet: {link}",
        "bad_duration": "Dauer nicht erkannt oder außerhalb von 1 Minute bis {max_days} Tagen. Beispiele: `30m`, `2h`, `1d12h`.",
        "bad_winners": "Anzahl Gewinner muss zwischen 1 und {max} liegen.",
        "bad_prize": "Bitte einen Preis angeben (max. {max} Zeichen).",
        "bad_channel": "In diesem Kanal kann ich kein Gewinnspiel posten (Textkanal und Rechte prüfen).",
        "post_failed": "Das Gewinnspiel konnte nicht gepostet werden (Rechte im Kanal prüfen).",
        "not_found": "Gewinnspiel `{id}` nicht gefunden.",
        "not_running": "Gewinnspiel `{id}` läuft nicht (mehr).",
        "not_ended": "Gewinnspiel `{id}` ist noch nicht beendet – neu auslosen geht erst danach.",
        "not_winner": "{user} ist kein Gewinner von `{id}`.",
        "no_candidates": "Es gibt keine weiteren gültigen Teilnahmen, die neu ausgelost werden könnten.",
        "ended_ok": "🏁 Gewinnspiel `{id}` beendet und ausgelost.",
        "cancelled_ok": "🚫 Gewinnspiel `{id}` abgebrochen.",
        "rerolled_ok": "🔁 Neu ausgelost: {mentions}",
        "list_empty": "Auf diesem Server gibt es keine Gewinnspiele.",
        "list_header": "**Gewinnspiele auf diesem Server**",
        "list_row": "`#{id}` · {prize} · {status} · {entries} Teilnehmer · {when}",
        "status_running": "läuft",
        "status_ended": "beendet",
        "status_cancelled": "abgebrochen",
        "mgr_added": "Manager-Rolle hinzugefügt: {role}.",
        "mgr_removed": "Manager-Rolle entfernt: {role}.",
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
    },
    "en": {
        "embed_ends": "Ends {rel} ({abs})",
        "embed_ended": "Ended {rel}",
        "embed_cancelled": "🚫 Cancelled – there will be no draw.",
        "embed_winners_count": "Winners: **{n}**",
        "embed_host": "Hosted by {host}",
        "embed_entries": "Entries",
        "embed_requirements": "Requirements",
        "req_required": "One of these roles: {roles}",
        "req_excluded": "Excluded: {roles}",
        "req_days": "At least {days} days on the server",
        "embed_bonus": "Bonus entries",
        "bonus_line": "{role}: +{n}",
        "embed_winners": "Winners",
        "embed_no_winners": "No valid entries – nobody won.",
        "embed_footer": "Giveaway #{id} · Click 🎉 to enter",
        "embed_footer_done": "Giveaway #{id}",
        "button_join": "Enter",
        "button_ended": "Ended",
        "button_cancelled": "Cancelled",
        "button_leave": "Yes, leave",
        "joined": "🎉 You're in! Entries: **{tickets}**. Good luck!",
        "already": "You are already entered (entries: **{tickets}**). Do you really want to leave?",
        "left": "↩️ You left this giveaway.",
        "not_entered": "You are not entered in this giveaway.",
        "leave_timeout": "No change – you are still entered.",
        "err_unknown": "This giveaway no longer exists.",
        "err_ended": "This giveaway has already ended.",
        "err_bot": "Bots cannot enter.",
        "err_excluded": "Your roles do not allow you to enter this giveaway.",
        "err_required": "To enter you need one of these roles: {roles}.",
        "err_too_new": "You must be on the server for at least {days} days to enter.",
        "announce_winners": "🎉 Congratulations {mentions}! {verb} won **{prize}**!",
        "verb_one": "You",
        "verb_many": "You",
        "announce_none": "The giveaway **{prize}** has ended – unfortunately there were no valid entries.",
        "announce_reroll": "🔁 Rerolled for **{prize}**: congratulations {mentions}!",
        "no_permission": "You lack permission for that (Manage Server or giveaway manager role).",
        "no_permission_admin": "You lack permission for that (Manage Server).",
        "started": "✅ Giveaway **#{id}** started: {link}",
        "bad_duration": "Duration not recognized or outside 1 minute to {max_days} days. Examples: `30m`, `2h`, `1d12h`.",
        "bad_winners": "Number of winners must be between 1 and {max}.",
        "bad_prize": "Please provide a prize (max. {max} characters).",
        "bad_channel": "I cannot post a giveaway in this channel (check text channel and permissions).",
        "post_failed": "The giveaway could not be posted (check channel permissions).",
        "not_found": "Giveaway `{id}` not found.",
        "not_running": "Giveaway `{id}` is not running (anymore).",
        "not_ended": "Giveaway `{id}` has not ended yet – rerolling is only possible afterwards.",
        "not_winner": "{user} is not a winner of `{id}`.",
        "no_candidates": "There are no further valid entries to reroll.",
        "ended_ok": "🏁 Giveaway `{id}` ended and drawn.",
        "cancelled_ok": "🚫 Giveaway `{id}` cancelled.",
        "rerolled_ok": "🔁 Rerolled: {mentions}",
        "list_empty": "There are no giveaways on this server.",
        "list_header": "**Giveaways on this server**",
        "list_row": "`#{id}` · {prize} · {status} · {entries} entries · {when}",
        "status_running": "running",
        "status_ended": "ended",
        "status_cancelled": "cancelled",
        "mgr_added": "Manager role added: {role}.",
        "mgr_removed": "Manager role removed: {role}.",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
    """Text für ``key`` in ``lang`` (Fallback: Deutsch, dann der Key selbst)."""
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
