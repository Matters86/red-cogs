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
        # --- Rollen-Panels (Buttons/Dropdown zum Selbstvergeben) ---
        # Interaktion (nur für die klickende Person sichtbar)
        "panel_gone": "Dieses Panel gibt es nicht mehr.",
        "panel_bot_no_perm": "⚠️ Mir fehlt die Berechtigung **Rollen verwalten** – ich kann dir keine Rolle geben.",
        "panel_role_unavailable": "⚠️ Diese Rolle kann ich dir gerade nicht geben.",
        "panel_failed": "⚠️ Das hat nicht geklappt (fehlen mir Rechte?).",
        "panel_got": "✅ **{role}** hinzugefügt.",
        "panel_removed": "🗑️ **{role}** entfernt.",
        "panel_have": "Du hast **{role}** bereits.",
        "panel_set": "✅ Du hast jetzt nur noch **{role}** aus dieser Gruppe.",
        "panel_updated": "✅ Rollen aktualisiert.",
        "panel_none": "Nichts geändert.",
        "panel_part_added": "➕ {roles}",
        "panel_part_removed": "➖ {roles}",
        # Befehle
        "panel_created": "✅ Panel **{name}** erstellt (ID `{id}`). Richte es im Dashboard ein oder füge Rollen hinzu mit `{p}autorole panel addrole {id} <Rolle>`.",
        "panel_not_found": "Kein Panel mit ID `{id}`.",
        "panel_list_empty": "Es gibt noch keine Panels. Erstelle eins mit `{p}autorole panel create <Name>`.",
        "panel_list_header": "**Rollen-Panels**",
        "panel_deleted": "🗑️ Panel **{name}** gelöscht.",
        "panel_role_added": "✅ **{role}** zum Panel **{name}** hinzugefügt.",
        "panel_role_exists": "**{role}** ist bereits im Panel **{name}**.",
        "panel_role_full": "Das Panel ist voll (max. {max} Rollen).",
        "panel_role_removed": "🗑️ **{role}** aus Panel **{name}** entfernt.",
        "panel_role_not_in": "**{role}** ist nicht im Panel **{name}**.",
        "panel_posted": "✅ Panel **{name}** in {channel} gepostet/aktualisiert.",
        "panel_post_no_channel": "Für **{name}** ist kein gültiger Kanal gesetzt. Nutze `{p}autorole panel post {id} #kanal` oder das Dashboard.",
        "panel_post_no_roles": "Das Panel **{name}** hat noch keine Rollen.",
        "panel_post_no_send": "Mir fehlen im Zielkanal die Rechte zum **Senden** (bzw. **Einbetten von Links**).",
        "panel_post_failed": "Das Posten von **{name}** ist fehlgeschlagen.",
        "panel_status_posted": "gepostet",
        "panel_status_unposted": "nicht gepostet",
        "panel_no_channel_short": "kein Kanal",
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
        # --- Role panels (buttons/dropdown for self-assign) ---
        "panel_gone": "This panel no longer exists.",
        "panel_bot_no_perm": "⚠️ I'm missing the **Manage Roles** permission – I can't give you a role.",
        "panel_role_unavailable": "⚠️ I can't give you this role right now.",
        "panel_failed": "⚠️ That didn't work (am I missing permissions?).",
        "panel_got": "✅ Added **{role}**.",
        "panel_removed": "🗑️ Removed **{role}**.",
        "panel_have": "You already have **{role}**.",
        "panel_set": "✅ You now only have **{role}** from this group.",
        "panel_updated": "✅ Roles updated.",
        "panel_none": "Nothing changed.",
        "panel_part_added": "➕ {roles}",
        "panel_part_removed": "➖ {roles}",
        "panel_created": "✅ Panel **{name}** created (ID `{id}`). Set it up in the dashboard or add roles with `{p}autorole panel addrole {id} <role>`.",
        "panel_not_found": "No panel with ID `{id}`.",
        "panel_list_empty": "There are no panels yet. Create one with `{p}autorole panel create <name>`.",
        "panel_list_header": "**Role panels**",
        "panel_deleted": "🗑️ Panel **{name}** deleted.",
        "panel_role_added": "✅ Added **{role}** to panel **{name}**.",
        "panel_role_exists": "**{role}** is already in panel **{name}**.",
        "panel_role_full": "The panel is full (max. {max} roles).",
        "panel_role_removed": "🗑️ Removed **{role}** from panel **{name}**.",
        "panel_role_not_in": "**{role}** is not in panel **{name}**.",
        "panel_posted": "✅ Panel **{name}** posted/updated in {channel}.",
        "panel_post_no_channel": "Panel **{name}** has no valid channel set. Use `{p}autorole panel post {id} #channel` or the dashboard.",
        "panel_post_no_roles": "Panel **{name}** has no roles yet.",
        "panel_post_no_send": "I'm missing **Send Messages** (or **Embed Links**) permission in the target channel.",
        "panel_post_failed": "Posting panel **{name}** failed.",
        "panel_status_posted": "posted",
        "panel_status_unposted": "not posted",
        "panel_no_channel_short": "no channel",
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
