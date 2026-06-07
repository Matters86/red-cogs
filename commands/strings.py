"""Mehrsprachigkeit für den Commands-Cog.

Aufbau wie in den übrigen Cogs (Tickets/Sticky/RaidHelper):
1. Sprachpakete (``STRINGS``) – ``de`` ist Standard und Fallback.
2. ``t(lang, key, **kwargs)`` liefert den passenden String, fällt bei fehlender
   Sprache/fehlendem Key auf Deutsch bzw. den Key selbst zurück und formatiert
   optional mit ``str.format``.

Übersetzt werden nur die Bot-Antworten (Befehls-Feedback, ``[p]meinebefehle``).
Die Dashboard-Oberfläche ist – wie überall – durchgängig deutsch.
"""

from __future__ import annotations

# Reihenfolge = Anzeige-Reihenfolge.
LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # ----- [p]meinebefehle -----
        "title_my": "Deine Befehle",
        "title_member": "Befehle für {member}",
        "summary": "Du kannst **{usable}** von **{total}** sichtbaren Befehlen nutzen.",
        "summary_member": "**{member}** kann **{usable}** von **{total}** sichtbaren Befehlen nutzen.",
        "none_usable": "Hier gibt es derzeit keine Befehle, die du nutzen kannst.",
        "none_usable_member": "{member} kann hier derzeit keine Befehle nutzen.",
        "field_other": "Sonstige",
        "more_suffix": "… und {count} weitere",
        "footer_self": "Mit anderer Rolle oder mehr Rechten kann sich das ändern.",
        "guild_only": "Dieser Befehl funktioniert nur auf einem Server.",
        "no_permission_member": "Nur Moderatoren oder Admins dürfen die Befehle anderer prüfen.",
        "dm_sent": "📬 Ich habe dir die Liste per Direktnachricht geschickt.",
        "dm_failed": "Ich konnte dir keine Direktnachricht schicken – bitte erlaube DMs für diesen Server.",
        # ----- [p]befehlsliste (Owner) -----
        "hidden_cog": "🙈 Cog **{name}** wird im Dashboard und in der Liste ausgeblendet.",
        "hidden_cmd": "🙈 Befehl `{name}` wird im Dashboard und in der Liste ausgeblendet.",
        "shown_cog": "👁️ Cog **{name}** wird wieder angezeigt.",
        "shown_cmd": "👁️ Befehl `{name}` wird wieder angezeigt.",
        "already_hidden": "Das war bereits ausgeblendet.",
        "not_hidden": "Das war nicht ausgeblendet.",
        "unknown_kind": "Unbekannte Art – nutze `cog` oder `command`.",
        "lang_set": "🌐 Sprache der Nutzer-Ausgabe: **{lang}**.",
        "lang_unknown": "Unbekannte Sprache. Verfügbar: {langs}.",
        "status_title": "Commands – Status",
        "status_cogs": "Cogs",
        "status_commands": "Befehle gesamt",
        "status_hidden": "Ausgeblendet",
        "status_language": "Sprache (dieser Server)",
        "status_dashboard": "Dashboard",
        "status_dashboard_on": "verbunden (Tab 'Befehle')",
        "status_dashboard_off": "WebCore nicht geladen",
        "status_hidden_none": "—",
    },
    "en": {
        # ----- [p]meinebefehle -----
        "title_my": "Your commands",
        "title_member": "Commands for {member}",
        "summary": "You can use **{usable}** of **{total}** visible commands.",
        "summary_member": "**{member}** can use **{usable}** of **{total}** visible commands.",
        "none_usable": "There are currently no commands you can use here.",
        "none_usable_member": "{member} currently has no usable commands here.",
        "field_other": "Other",
        "more_suffix": "… and {count} more",
        "footer_self": "This can change with a different role or more permissions.",
        "guild_only": "This command only works inside a server.",
        "no_permission_member": "Only moderators or admins may check other members' commands.",
        "dm_sent": "📬 I sent you the list via direct message.",
        "dm_failed": "I couldn't DM you – please allow direct messages for this server.",
        # ----- [p]befehlsliste (Owner) -----
        "hidden_cog": "🙈 Cog **{name}** is now hidden from the dashboard and list.",
        "hidden_cmd": "🙈 Command `{name}` is now hidden from the dashboard and list.",
        "shown_cog": "👁️ Cog **{name}** is shown again.",
        "shown_cmd": "👁️ Command `{name}` is shown again.",
        "already_hidden": "That was already hidden.",
        "not_hidden": "That wasn't hidden.",
        "unknown_kind": "Unknown kind – use `cog` or `command`.",
        "lang_set": "🌐 User-output language: **{lang}**.",
        "lang_unknown": "Unknown language. Available: {langs}.",
        "status_title": "Commands – status",
        "status_cogs": "Cogs",
        "status_commands": "Total commands",
        "status_hidden": "Hidden",
        "status_language": "Language (this server)",
        "status_dashboard": "Dashboard",
        "status_dashboard_on": "connected (tab \"Befehle\")",
        "status_dashboard_off": "WebCore not loaded",
        "status_hidden_none": "—",
    },
}


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
