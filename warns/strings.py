"""Mehrsprachigkeit für den Warns-Cog (Aufbau wie guard/autorole).

``de`` ist Standard und Fallback. ``t(lang, key, **kwargs)`` liefert den Text, fällt bei
fehlender Sprache/fehlendem Key auf Deutsch bzw. den Key zurück und formatiert optional mit
``str.format`` (nur feste Texte – der frei einstellbare DM-Text läuft über ``fill_placeholders``).
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

# Platzhalter für den DM-Text.
DM_PLACEHOLDERS = ("user", "name", "server", "reason", "points", "total", "id", "moderator", "expires")

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # Prüfungen
        "err_not_mod": "Dafür brauchst du Moderationsrechte (Mitglieder kicken oder eine Mod-Rolle).",
        "err_self": "Du kannst dich nicht selbst verwarnen.",
        "err_bot": "Bots können nicht verwarnt werden.",
        "err_bot_owner": "Der Bot-Owner kann nicht verwarnt werden.",
        "err_guild_owner": "Der Server-Owner kann nicht verwarnt werden.",
        "err_hierarchy": "{user} hat eine gleich hohe oder höhere Rolle als du – keine Verwarnung möglich.",
        "err_points": "Punkte müssen zwischen 1 und {max} liegen.",
        "err_reason": "Bitte einen Grund angeben (max. {max} Zeichen).",
        "err_not_found": "Verwarnung #{id} wurde auf diesem Server nicht gefunden.",
        "err_already_revoked": "Verwarnung #{id} wurde bereits aufgehoben.",
        "err_own_warning": "Eigene Verwarnungen kannst du nicht aufheben.",
        "err_view_other": "Die Verwarnungen anderer Mitglieder dürfen nur Moderatoren sehen.",
        # Erfolg
        "warn_ok": "⚠️ Verwarnung **#{id}** für {user}: {reason} (+{points} Pkt.). Aktive Punkte: **{total}**.",
        "warn_dm_failed": "Die DM konnte nicht zugestellt werden.",
        "warn_action_done": "Automatische Maßnahme: **{action}**.",
        "warn_action_failed": "Automatische Maßnahme **{action}** nicht ausgeführt: {why}.",
        "unwarn_ok": "↩️ Verwarnung **#{id}** von {user} aufgehoben. Aktive Punkte: **{total}**.",
        "clear_ok": "🧹 {n} Verwarnung(en) von {user} gelöscht.",
        "clear_none": "{user} hat keine Verwarnungen.",
        # Maßnahmen
        "act_timeout": "Timeout ({duration})",
        "act_kick": "Kick",
        "act_ban": "Bann",
        "why_bot_owner": "Mitglied ist Bot-Owner",
        "why_guild_owner": "Mitglied ist Server-Owner",
        "why_bot_hierarchy": "die Rolle des Mitglieds ist gleich hoch oder höher als meine",
        "why_mod_hierarchy": "die Rolle des Mitglieds ist gleich hoch oder höher als die des Moderators",
        "why_bot_perms": "mir fehlt das Recht „{perm}“",
        "why_admin_timeout": "Administratoren können keinen Timeout bekommen",
        "why_http": "Discord hat die Aktion abgelehnt",
        "perm_moderate": "Mitglieder im Timeout",
        "perm_kick": "Mitglieder kicken",
        "perm_ban": "Mitglieder bannen",
        # Zeit
        "never": "nie",
        "minutes": "{n} Min.", "hours": "{n} Std.", "days": "{n} Tage",
        # Status
        "status_active": "aktiv", "status_expired": "abgelaufen", "status_revoked": "aufgehoben",
        # DM
        "dm_default": (
            "Du hast auf **{server}** eine Verwarnung (#{id}) erhalten.\n"
            "**Grund:** {reason}\n"
            "**Punkte:** {points} · aktive Punkte insgesamt: **{total}**\n"
            "**Läuft ab:** {expires}"
        ),
        "dm_action_line": "**Maßnahme:** {action}",
        # Log
        "log_warn": "Verwarnung #{id}",
        "log_revoke": "Verwarnung #{id} aufgehoben",
        "log_clear": "Verwarnungen gelöscht",
        "log_member": "Mitglied", "log_moderator": "Moderator", "log_reason": "Grund",
        "log_points": "Punkte", "log_total": "Aktive Punkte", "log_expires": "Läuft ab",
        "log_action": "Automatische Maßnahme", "log_source": "Quelle", "log_count": "Anzahl",
        "log_done": "ausgeführt", "log_failed": "nicht ausgeführt",
        "src_command": "Befehl", "src_dashboard": "Dashboard",
        # Verlauf
        "hist_title": "Verwarnungen von {user}",
        "hist_summary": "Aktive Punkte: **{total}** · aktive Verwarnungen: {active} · insgesamt: {count}",
        "hist_empty": "{user} hat keine Verwarnungen.",
        "hist_line": "**#{id}** · {points} Pkt. · {when} · von {mod}\n{reason}",
        "hist_more": "… und {n} ältere",
        # Einstellungen
        "set_log": "Log-Kanal: {channel}.",
        "set_log_cleared": "Log-Kanal entfernt.",
        "set_dm": "DM an Verwarnte: **{state}**.",
        "set_dmtext": "DM-Text gespeichert.",
        "set_dmtext_reset": "DM-Text zurückgesetzt (Standard).",
        "set_dmtext_long": "DM-Text zu lang (max. {max} Zeichen).",
        "set_modrole_added": "**{role}** zählt jetzt als Mod-Rolle.",
        "set_modrole_removed": "**{role}** ist keine Mod-Rolle mehr.",
        "set_expiry": "Verfall neuer Verwarnungen: **{days}**.",
        "set_expiry_bad": "Verfall: 0 (nie) bis {max} Tage.",
        "set_points": "Standard-Punkte je Verwarnung: **{points}**.",
        "set_action": "Ab **{points}** aktiven Punkten: {action}.",
        "set_action_off": "{action} ist jetzt **aus**.",
        "set_action_bad": "Punkte 0 (aus) bis {max}; Timeout-Dauer 1–40320 Minuten.",
        "set_lang": "Sprache auf **{language}** gesetzt.",
        "set_lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "on": "an", "off": "aus", "none": "—",
        "settings_title": "Verwarnungen – Einstellungen",
        "settings_log": "Log-Kanal", "settings_dm": "DM an Verwarnte", "settings_modroles": "Mod-Rollen",
        "settings_expiry": "Verfall", "settings_points": "Standard-Punkte", "settings_actions": "Automatische Maßnahmen",
        "settings_lang": "Sprache",
        "deleted_user": "Gelöschter Nutzer",
    },
    "en": {
        "err_not_mod": "You need moderation rights for this (Kick Members or a mod role).",
        "err_self": "You cannot warn yourself.",
        "err_bot": "Bots cannot be warned.",
        "err_bot_owner": "The bot owner cannot be warned.",
        "err_guild_owner": "The server owner cannot be warned.",
        "err_hierarchy": "{user} has an equal or higher role than you – cannot warn.",
        "err_points": "Points must be between 1 and {max}.",
        "err_reason": "Please give a reason (max. {max} characters).",
        "err_not_found": "Warning #{id} was not found on this server.",
        "err_already_revoked": "Warning #{id} has already been revoked.",
        "err_own_warning": "You cannot revoke your own warnings.",
        "err_view_other": "Only moderators may view other members' warnings.",
        "warn_ok": "⚠️ Warning **#{id}** for {user}: {reason} (+{points} pts). Active points: **{total}**.",
        "warn_dm_failed": "The DM could not be delivered.",
        "warn_action_done": "Automatic action: **{action}**.",
        "warn_action_failed": "Automatic action **{action}** not executed: {why}.",
        "unwarn_ok": "↩️ Warning **#{id}** of {user} revoked. Active points: **{total}**.",
        "clear_ok": "🧹 Deleted {n} warning(s) of {user}.",
        "clear_none": "{user} has no warnings.",
        "act_timeout": "Timeout ({duration})",
        "act_kick": "Kick",
        "act_ban": "Ban",
        "why_bot_owner": "member is the bot owner",
        "why_guild_owner": "member is the server owner",
        "why_bot_hierarchy": "the member's role is equal to or higher than mine",
        "why_mod_hierarchy": "the member's role is equal to or higher than the moderator's",
        "why_bot_perms": "I lack the “{perm}” permission",
        "why_admin_timeout": "administrators cannot be timed out",
        "why_http": "Discord rejected the action",
        "perm_moderate": "Timeout Members",
        "perm_kick": "Kick Members",
        "perm_ban": "Ban Members",
        "never": "never",
        "minutes": "{n} min", "hours": "{n} h", "days": "{n} days",
        "status_active": "active", "status_expired": "expired", "status_revoked": "revoked",
        "dm_default": (
            "You received a warning (#{id}) on **{server}**.\n"
            "**Reason:** {reason}\n"
            "**Points:** {points} · total active points: **{total}**\n"
            "**Expires:** {expires}"
        ),
        "dm_action_line": "**Action:** {action}",
        "log_warn": "Warning #{id}",
        "log_revoke": "Warning #{id} revoked",
        "log_clear": "Warnings deleted",
        "log_member": "Member", "log_moderator": "Moderator", "log_reason": "Reason",
        "log_points": "Points", "log_total": "Active points", "log_expires": "Expires",
        "log_action": "Automatic action", "log_source": "Source", "log_count": "Count",
        "log_done": "executed", "log_failed": "not executed",
        "src_command": "Command", "src_dashboard": "Dashboard",
        "hist_title": "Warnings of {user}",
        "hist_summary": "Active points: **{total}** · active warnings: {active} · total: {count}",
        "hist_empty": "{user} has no warnings.",
        "hist_line": "**#{id}** · {points} pts · {when} · by {mod}\n{reason}",
        "hist_more": "… and {n} older",
        "set_log": "Log channel: {channel}.",
        "set_log_cleared": "Log channel removed.",
        "set_dm": "DM to warned members: **{state}**.",
        "set_dmtext": "DM text saved.",
        "set_dmtext_reset": "DM text reset (default).",
        "set_dmtext_long": "DM text too long (max. {max} characters).",
        "set_modrole_added": "**{role}** now counts as a mod role.",
        "set_modrole_removed": "**{role}** is no longer a mod role.",
        "set_expiry": "Expiry of new warnings: **{days}**.",
        "set_expiry_bad": "Expiry: 0 (never) to {max} days.",
        "set_points": "Default points per warning: **{points}**.",
        "set_action": "From **{points}** active points: {action}.",
        "set_action_off": "{action} is now **off**.",
        "set_action_bad": "Points 0 (off) to {max}; timeout duration 1–40320 minutes.",
        "set_lang": "Language set to **{language}**.",
        "set_lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "on": "on", "off": "off", "none": "—",
        "settings_title": "Warnings – settings",
        "settings_log": "Log channel", "settings_dm": "DM to warned members", "settings_modroles": "Mod roles",
        "settings_expiry": "Expiry", "settings_points": "Default points", "settings_actions": "Automatic actions",
        "settings_lang": "Language",
        "deleted_user": "Deleted user",
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
