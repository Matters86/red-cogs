"""Mehrsprachigkeit für den Guard-Cog.

Aufbau wie im Poll-/RaidHelper-Cog:
1. Sprachpakete (``STRINGS``) – ``de`` ist Standard und Fallback. Weitere
   Sprache = ein weiterer Block.
2. Pro-Server-Overrides (Config ``messages``) überschreiben einzelne sichtbare
   Texte; ausgewertet wird das im Cog/Dashboard, nicht hier.

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
        # Allgemein / Befehle
        "no_guild": "Dieser Befehl funktioniert nur auf einem Server.",
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "module_on": "Modul **{module}** aktiviert.",
        "module_off": "Modul **{module}** deaktiviert.",
        "module_unknown": "Unbekanntes Modul. Wähle `honeypot` oder `spam`.",
        "state_on": "an",
        "state_off": "aus",
        # Honeypot
        "hp_created": "Honeypot-Kanal {channel} angelegt und aktiviert.",
        "hp_create_failed": "Konnte keinen Kanal anlegen (fehlt mir „Kanäle verwalten\"?).",
        "hp_set": "Honeypot-Kanal auf {channel} gesetzt und aktiviert.",
        "hp_disabled": "Honeypot deaktiviert.",
        "hp_action_set": "Honeypot-Aktion auf **{action}** gesetzt.",
        "hp_action_unknown": "Unbekannte Aktion. Wähle `ban`, `softban`, `kick` oder `timeout`.",
        "hp_warning": "🚫 **Bitte hier nichts schreiben.** Dieser Kanal ist eine Falle gegen Spam-Bots – wer hier postet, wird automatisch entfernt.",
        # Whitelist / Log
        "wl_role_added": "Rolle {name} zur Ausnahmeliste hinzugefügt.",
        "wl_role_removed": "Rolle {name} aus der Ausnahmeliste entfernt.",
        "wl_user_added": "Nutzer {name} zur Ausnahmeliste hinzugefügt.",
        "wl_user_removed": "Nutzer {name} aus der Ausnahmeliste entfernt.",
        "wl_channel_added": "Kanal {name} wird vom Spamschutz ausgenommen.",
        "wl_channel_removed": "Kanal {name} wird wieder vom Spamschutz geprüft.",
        "log_set": "Log-Kanal auf {channel} gesetzt.",
        "log_cleared": "Log-Kanal entfernt.",
        # Lockdown
        "lockdown_started": "🔒 Notmodus aktiviert.",
        "lockdown_already": "Der Notmodus ist bereits aktiv.",
        "lockdown_ended": "🔓 Notmodus beendet.",
        "lockdown_not_active": "Der Notmodus ist nicht aktiv.",
        "lockdown_bad_state": "Bitte `on` oder `off` angeben.",
        # Hinweise
        "dashboard_hint": "Die Seite **Guard** findest du im WebCore-Dashboard unter `/cogs/guard`.",
        "dashboard_missing": "WebCore ist nicht geladen – das Dashboard ist nicht verfügbar.",
        "settings_header": "**Guard – Einstellungen ({guild})**",
        # Log-Embed
        "log_title_honeypot": "Honeypot ausgelöst",
        "log_title_spam": "Spamschutz ausgelöst",
        "log_title_raid": "Raid erkannt – Notmodus",
        "log_title_lockdown_end": "Notmodus beendet",
        "log_user": "Nutzer",
        "log_account_age": "Kontoalter",
        "log_action": "Aktion",
        "log_rule": "Regel",
        "log_channel": "Kanal",
        "log_points": "Punkte",
        "log_joins": "Beitritte",
        # Aktionsnamen
        "act_ban": "Bann",
        "act_softban": "Softban (Kick + Nachrichten gelöscht)",
        "act_kick": "Kick",
        "act_timeout": "Timeout",
        "act_delete": "Nachricht gelöscht",
        "act_warn": "Verwarnung (protokolliert)",
        "act_none": "keine",
        # Regelnamen
        "rule_honeypot": "Honeypot-Kanal",
        "rule_rate": "Nachrichten-Rate",
        "rule_repeat": "Wiederholungen",
        "rule_mentions": "Massen-Erwähnungen",
        "rule_invite": "Einladungslink",
        "rule_link": "Externer Link",
        "rule_wall": "Anhang-/Emoji-/Zeilen-Spam",
        "rule_newaccount": "Sehr neues Konto",
        "rule_lockdown_join": "Beitritt während Notmodus",
        # Audit-Log-Gründe (Discord)
        "reason_honeypot": "Guard: Honeypot-Kanal benutzt",
        "reason_spam": "Guard: Spam erkannt ({rules})",
        "reason_lockdown_join": "Guard: Beitritt während aktivem Notmodus",
    },
    "en": {
        "no_guild": "This command only works inside a server.",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "module_on": "Module **{module}** enabled.",
        "module_off": "Module **{module}** disabled.",
        "module_unknown": "Unknown module. Choose `honeypot` or `spam`.",
        "state_on": "on",
        "state_off": "off",
        "hp_created": "Honeypot channel {channel} created and enabled.",
        "hp_create_failed": "Could not create a channel (am I missing “Manage Channels”?).",
        "hp_set": "Honeypot channel set to {channel} and enabled.",
        "hp_disabled": "Honeypot disabled.",
        "hp_action_set": "Honeypot action set to **{action}**.",
        "hp_action_unknown": "Unknown action. Choose `ban`, `softban`, `kick` or `timeout`.",
        "hp_warning": "🚫 **Please do not post here.** This channel is a trap against spam bots – anyone posting here is removed automatically.",
        "wl_role_added": "Role {name} added to the exemption list.",
        "wl_role_removed": "Role {name} removed from the exemption list.",
        "wl_user_added": "User {name} added to the exemption list.",
        "wl_user_removed": "User {name} removed from the exemption list.",
        "wl_channel_added": "Channel {name} is now exempt from spam protection.",
        "wl_channel_removed": "Channel {name} is checked by spam protection again.",
        "log_set": "Log channel set to {channel}.",
        "log_cleared": "Log channel removed.",
        "lockdown_started": "🔒 Emergency mode enabled.",
        "lockdown_already": "Emergency mode is already active.",
        "lockdown_ended": "🔓 Emergency mode ended.",
        "lockdown_not_active": "Emergency mode is not active.",
        "lockdown_bad_state": "Please specify `on` or `off`.",
        "dashboard_hint": "You can find the **Guard** page in the WebCore dashboard at `/cogs/guard`.",
        "dashboard_missing": "WebCore is not loaded – the dashboard is unavailable.",
        "settings_header": "**Guard – settings ({guild})**",
        "log_title_honeypot": "Honeypot triggered",
        "log_title_spam": "Spam protection triggered",
        "log_title_raid": "Raid detected – emergency mode",
        "log_title_lockdown_end": "Emergency mode ended",
        "log_user": "User",
        "log_account_age": "Account age",
        "log_action": "Action",
        "log_rule": "Rule",
        "log_channel": "Channel",
        "log_points": "Points",
        "log_joins": "Joins",
        "act_ban": "Ban",
        "act_softban": "Softban (kick + messages deleted)",
        "act_kick": "Kick",
        "act_timeout": "Timeout",
        "act_delete": "Message deleted",
        "act_warn": "Warning (logged)",
        "act_none": "none",
        "rule_honeypot": "Honeypot channel",
        "rule_rate": "Message rate",
        "rule_repeat": "Repeated messages",
        "rule_mentions": "Mass mentions",
        "rule_invite": "Invite link",
        "rule_link": "External link",
        "rule_wall": "Attachment/emoji/newline spam",
        "rule_newaccount": "Very new account",
        "rule_lockdown_join": "Joined during emergency mode",
        "reason_honeypot": "Guard: posted in honeypot channel",
        "reason_spam": "Guard: spam detected ({rules})",
        "reason_lockdown_join": "Guard: joined during active emergency mode",
    },
}

# Keys, die ein Server frei überschreiben darf (Dashboard zeigt genau diese).
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "hp_warning",
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
