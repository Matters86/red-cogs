"""Mehrsprachigkeit für den Autorole-Cog.

Aufbau wie im Tickets-/RaidHelper-/Sticky-Cog:
1. Sprachpakete (``STRINGS``) – ``de`` ist Standard und Fallback. Weitere
   Sprache = ein weiterer Block.
2. ``t(lang, key, **kwargs)`` liefert den passenden String, fällt bei fehlender
   Sprache/fehlendem Key auf Deutsch bzw. den Key selbst zurück und formatiert
   optional mit ``str.format``.

Hinweis: Übersetzt werden **nur die Antworten des Bots** (Befehls-Feedback). Die
Dashboard-Oberfläche ist – wie bei den übrigen Cogs – durchgängig deutsch.
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
        # Status / generische Bausteine
        "state_on": "aktiv",
        "state_off": "deaktiviert",
        "none": "—",
        "age_hours": "{hours} h",
        "age_off_short": "aus",
        # Gründe, warum eine Rolle nicht vergeben werden kann
        "reason_default": "@everyone",
        "reason_managed": "von Discord verwaltet (Booster-/Integrations-/Bot-Rolle)",
        "reason_too_high": "steht über meiner höchsten Rolle",
        # Berechtigung
        "no_manage_roles": "⚠️ Mir fehlt die Berechtigung **Rollen verwalten** – ohne sie kann ich keine Rollen vergeben.",
        # System an/aus
        "system_on": "✅ Autorole ist jetzt **aktiv**.",
        "system_off": "⏸️ Autorole ist jetzt **deaktiviert**.",
        # Mitglieder-Rollen
        "add_ok": "✅ **{role}** wird neuen **Mitgliedern** automatisch vergeben.",
        "add_already": "**{role}** ist bereits als Mitglieder-Rolle eingetragen.",
        "add_unassignable": "⚠️ **{role}** kann ich nicht vergeben ({reason}) und trage sie daher nicht ein.",
        "remove_ok": "🗑️ **{role}** wird neuen Mitgliedern nicht mehr vergeben.",
        "remove_not_set": "**{role}** war nicht als Mitglieder-Rolle eingetragen.",
        # Bot-Rollen
        "bot_add_ok": "✅ **{role}** wird neuen **Bots** automatisch vergeben.",
        "bot_add_already": "**{role}** ist bereits als Bot-Rolle eingetragen.",
        "bot_remove_ok": "🗑️ **{role}** wird neuen Bots nicht mehr vergeben.",
        "bot_remove_not_set": "**{role}** war nicht als Bot-Rolle eingetragen.",
        # Sticky
        "sticky_on": "📌 **{role}** ist jetzt **sticky** – Mitglieder erhalten sie beim erneuten Beitritt zurück.",
        "sticky_off": "**{role}** ist nicht mehr sticky.",
        "sticky_unassignable": "⚠️ **{role}** kann ich nicht vergeben ({reason}) und daher nicht als sticky nutzen.",
        # Verzögerung / Kontoalter / Screening
        "delay_set": "⏱️ Verzögerung auf **{sec}s** gesetzt (Wartezeit nach Beitritt vor der Vergabe).",
        "delay_bad": "Bitte eine ganze Zahl zwischen 0 und 3600 angeben.",
        "age_set": "🕓 Mindest-Kontoalter auf **{hours} h** gesetzt. Jüngere Konten erhalten keine Auto-Rollen.",
        "age_off": "🕓 Kontoalter-Prüfung **aus** – alle Konten erhalten Auto-Rollen.",
        "age_bad": "Bitte eine ganze Zahl ab 0 angeben (Stunden, 0 = aus).",
        "screening_set": "🛡️ Vergabe-Zeitpunkt: **{mode}**.",
        "screening_bad": "Unbekannter Wert `{value}`. Erlaubt: `auto`, `on`, `off`.",
        "screening_mode_auto": "automatisch (Verifizierung erkennen)",
        "screening_mode_on": "erst nach der Regel-Verifizierung",
        "screening_mode_off": "sofort beim Beitritt",
        # Sprache
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        # applyall
        "apply_running": "⏳ Wende die Mitglieder-Rollen auf bestehende Mitglieder an …",
        "apply_done": "✅ Fertig: **{added}** Rollen-Vergaben an **{members}** Mitglieder.",
        "apply_none": "Es sind keine vergebbaren Mitglieder-Rollen eingetragen – nichts anzuwenden.",
        "apply_disabled": "Autorole ist deaktiviert. Aktiviere es zuerst mit `{p}autorole toggle`.",
        # Einstellungen anzeigen
        "settings_header": "**Autorole-Einstellungen**",
        "settings_state": "Status: {state}",
        "settings_lang": "Sprache: {lang}",
        "settings_screening": "Vergabe: {mode}",
        "settings_delay": "Verzögerung: {sec}s",
        "settings_age": "Mindest-Kontoalter: {age}",
        "settings_join": "Mitglieder-Rollen: {roles}",
        "settings_bot": "Bot-Rollen: {roles}",
        "settings_sticky": "Sticky-Rollen: {roles}",
        "settings_gate_on": "ℹ️ Dieser Server nutzt Discords Regel-Verifizierung.",
        "settings_gate_off": "ℹ️ Dieser Server nutzt keine Regel-Verifizierung.",
    },
    "en": {
        "state_on": "enabled",
        "state_off": "disabled",
        "none": "—",
        "age_hours": "{hours} h",
        "age_off_short": "off",
        "reason_default": "@everyone",
        "reason_managed": "managed by Discord (booster/integration/bot role)",
        "reason_too_high": "is above my highest role",
        "no_manage_roles": "⚠️ I am missing the **Manage Roles** permission – I cannot assign any roles without it.",
        "system_on": "✅ Autorole is now **enabled**.",
        "system_off": "⏸️ Autorole is now **disabled**.",
        "add_ok": "✅ **{role}** will be assigned automatically to new **members**.",
        "add_already": "**{role}** is already a member role.",
        "add_unassignable": "⚠️ I cannot assign **{role}** ({reason}), so I won't add it.",
        "remove_ok": "🗑️ **{role}** will no longer be assigned to new members.",
        "remove_not_set": "**{role}** was not a member role.",
        "bot_add_ok": "✅ **{role}** will be assigned automatically to new **bots**.",
        "bot_add_already": "**{role}** is already a bot role.",
        "bot_remove_ok": "🗑️ **{role}** will no longer be assigned to new bots.",
        "bot_remove_not_set": "**{role}** was not a bot role.",
        "sticky_on": "📌 **{role}** is now **sticky** – members get it back when they rejoin.",
        "sticky_off": "**{role}** is no longer sticky.",
        "sticky_unassignable": "⚠️ I cannot assign **{role}** ({reason}), so it cannot be sticky.",
        "delay_set": "⏱️ Delay set to **{sec}s** (wait time after join before assigning).",
        "delay_bad": "Please provide a whole number between 0 and 3600.",
        "age_set": "🕓 Minimum account age set to **{hours} h**. Younger accounts will not get auto roles.",
        "age_off": "🕓 Account age check **off** – all accounts get auto roles.",
        "age_bad": "Please provide a whole number of 0 or more (hours, 0 = off).",
        "screening_set": "🛡️ Assignment timing: **{mode}**.",
        "screening_bad": "Unknown value `{value}`. Allowed: `auto`, `on`, `off`.",
        "screening_mode_auto": "automatic (detect screening)",
        "screening_mode_on": "only after rules screening",
        "screening_mode_off": "immediately on join",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "apply_running": "⏳ Applying member roles to existing members …",
        "apply_done": "✅ Done: **{added}** role grants to **{members}** members.",
        "apply_none": "There are no assignable member roles configured – nothing to apply.",
        "apply_disabled": "Autorole is disabled. Enable it first with `{p}autorole toggle`.",
        "settings_header": "**Autorole settings**",
        "settings_state": "Status: {state}",
        "settings_lang": "Language: {lang}",
        "settings_screening": "Assignment: {mode}",
        "settings_delay": "Delay: {sec}s",
        "settings_age": "Minimum account age: {age}",
        "settings_join": "Member roles: {roles}",
        "settings_bot": "Bot roles: {roles}",
        "settings_sticky": "Sticky roles: {roles}",
        "settings_gate_on": "ℹ️ This server uses Discord's rules screening.",
        "settings_gate_off": "ℹ️ This server does not use rules screening.",
    },
}

# Frei überschreibbare Schlüssel (für künftige Server-Overrides). Aktuell keine.
OVERRIDABLE_KEYS: tuple[str, ...] = ()


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
