"""Mehrsprachigkeit für den ServerLayout-Cog (Aufbau wie scheduler/strings.py). ``de`` = Standard/Fallback."""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        "not_found": "Layout `{name}` nicht gefunden. Liste: `{prefix}layout list`.",
        "name_missing": "Bitte einen Namen angeben, z. B. `{prefix}layout save Grundgerüst rollen,kanäle`.",
        "name_invalid": "Ungültiger Name (1–64 Zeichen, keine Steuerzeichen).",
        "name_taken": "Es gibt schon ein Layout mit dem Namen **{name}**.",
        "saving": "💾 Speichere Layout …",
        "saved": "✅ Layout **{name}** gespeichert ({parts}): {roles} Rollen, {categories} Kategorien, {channels} Kanäle · {size}.",
        "notes": "Hinweise:\n{notes}",
        "list_empty": "Noch keine Layouts gespeichert.",
        "list_header": "**Gespeicherte Layouts**",
        "list_row": "• **{name}** · {source} · {date} · {parts} · {size}{auto}",
        "auto": " · automatisch",
        "info_title": "Layout „{name}“",
        "info_body": "Quelle: **{source}** (`{source_id}`)\nErstellt: {date} von {creator}\nTeile: {parts}\n"
                     "Inhalt: {roles} Rollen, {categories} Kategorien, {channels} Kanäle\nGröße: {size}",
        "deleted": "🗑️ Layout **{name}** gelöscht.",
        "renamed": "✏️ Layout umbenannt: **{old}** → **{new}**.",
        "import_no_file": "Bitte die Layout-Datei (.json) an die Nachricht anhängen.",
        "import_too_big": "Datei zu groß (höchstens {max}).",
        "import_invalid": "Layout-Datei ungültig: {error}",
        "imported": "📥 Layout **{name}** importiert ({parts}): {roles} Rollen, {categories} Kategorien, {channels} Kanäle.",
        "export_too_big": "Die Datei ({size}) ist größer als das Upload-Limit dieses Servers – bitte im Dashboard herunterladen.",
        "export_ok": "📤 Layout **{name}**:",
        "no_access": "Dieses Layout stammt von einem anderen Server – nur der Bot-Owner darf es sehen.",
        "preview_title": "Vorschau: „{name}“ → {guild}",
        "preview_desc": "Modus: **{mode}** · Teile: {parts}\n"
                        "➕ {create} anlegen · ✏️ {update} ändern · 🗑️ {delete} löschen · ⏭️ {skip} übersprungen",
        "preview_items": "Änderungen",
        "preview_more": "… und {n} weitere (vollständig im Dashboard)",
        "preview_warnings": "⚠️ Warnungen",
        "preview_blockers": "⛔ Anwenden gesperrt",
        "preview_nothing": "Nichts zu tun – der Server entspricht bereits dem Layout.",
        "confirm_merge": "Layout jetzt laden (**Ergänzen** – es wird nichts gelöscht)? Vorher wird automatisch eine Sicherung angelegt.",
        "confirm_exact": "⚠️ **Exakt angleichen** löscht Rollen und Kanäle, die nicht im Layout stehen – Nachrichten darin sind "
                         "unwiderruflich weg. Zum Bestätigen auf „Laden“ klicken und den Server-Namen eintippen.",
        "btn_load": "Laden",
        "btn_cancel": "Abbrechen",
        "modal_title": "Exakt angleichen bestätigen",
        "modal_label": "Server-Namen zur Bestätigung eintippen",
        "name_mismatch": "Der eingegebene Name passt nicht zum Server-Namen – nichts geändert.",
        "not_yours": "Nur wer den Befehl ausgeführt hat, kann das bestätigen.",
        "aborted": "Abgebrochen – nichts geändert.",
        "timeout": "Zeit abgelaufen – nichts geändert.",
        "busy": "Auf diesem Server läuft bereits ein Ladevorgang. Status: `{prefix}layout status`.",
        "changed": "Der Server oder das Layout hat sich seit der Vorschau geändert – bitte erneut prüfen.",
        "blocked": "Anwenden gesperrt: {reasons}",
        "backup_failed": "Automatische Sicherung fehlgeschlagen – es wurde nichts geändert: {error}",
        "started": "⏳ Layout **{name}** wird geladen ({mode}) … Fortschritt: `{prefix}layout status`, abbrechen: `{prefix}layout cancel`.",
        "status_none": "Auf diesem Server läuft kein Ladevorgang und es gibt noch keinen Bericht.",
        "status_running": "⏳ **{name}** ({mode}) läuft: {done}/{total} Schritte ({percent} %) – {step}",
        "status_last": "Letzter Vorgang: **{name}** ({mode}) – {status}, {date}.\n{summary}",
        "cancel_ok": "⏹️ Abbruch angefordert – der laufende Schritt wird noch beendet.",
        "cancel_none": "Auf diesem Server läuft gerade kein Ladevorgang.",
        "summary": "➕ {created} angelegt · ✏️ {updated} geändert · 🗑️ {deleted} gelöscht · ⏭️ {skipped} übersprungen · ❌ {errors} Fehler",
        "report_done": "✅ Layout **{name}** geladen.\n{summary}\nSicherung vorher: **{backup}**",
        "report_cancelled": "⏹️ Laden von **{name}** abgebrochen.\n{summary}\nSicherung vorher: **{backup}**",
        "report_failed": "❌ Laden von **{name}** fehlgeschlagen: {error}",
        "report_errors": "Fehler (Auszug):\n{lines}",
        "st_done": "fertig", "st_cancelled": "abgebrochen", "st_failed": "fehlgeschlagen", "st_running": "läuft",
        "mode_merge": "Ergänzen", "mode_exact": "Exakt angleichen",
        "part_roles": "Rollen", "part_channels": "Kanäle", "part_settings": "Einstellungen",
        "lang_set": "Sprache auf **{name}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
    },
    "en": {
        "not_found": "Layout `{name}` not found. List: `{prefix}layout list`.",
        "name_missing": "Please give a name, e.g. `{prefix}layout save Base roles,channels`.",
        "name_invalid": "Invalid name (1–64 characters, no control characters).",
        "name_taken": "A layout named **{name}** already exists.",
        "saving": "💾 Saving layout …",
        "saved": "✅ Layout **{name}** saved ({parts}): {roles} roles, {categories} categories, {channels} channels · {size}.",
        "notes": "Notes:\n{notes}",
        "list_empty": "No layouts saved yet.",
        "list_header": "**Saved layouts**",
        "list_row": "• **{name}** · {source} · {date} · {parts} · {size}{auto}",
        "auto": " · automatic",
        "info_title": "Layout “{name}”",
        "info_body": "Source: **{source}** (`{source_id}`)\nCreated: {date} by {creator}\nParts: {parts}\n"
                     "Content: {roles} roles, {categories} categories, {channels} channels\nSize: {size}",
        "deleted": "🗑️ Layout **{name}** deleted.",
        "renamed": "✏️ Layout renamed: **{old}** → **{new}**.",
        "import_no_file": "Please attach the layout file (.json) to your message.",
        "import_too_big": "File too large (max. {max}).",
        "import_invalid": "Invalid layout file: {error}",
        "imported": "📥 Layout **{name}** imported ({parts}): {roles} roles, {categories} categories, {channels} channels.",
        "export_too_big": "The file ({size}) exceeds this server's upload limit – please download it from the dashboard.",
        "export_ok": "📤 Layout **{name}**:",
        "no_access": "This layout comes from another server – only the bot owner may see it.",
        "preview_title": "Preview: “{name}” → {guild}",
        "preview_desc": "Mode: **{mode}** · Parts: {parts}\n"
                        "➕ {create} create · ✏️ {update} change · 🗑️ {delete} delete · ⏭️ {skip} skipped",
        "preview_items": "Changes",
        "preview_more": "… and {n} more (see dashboard for all)",
        "preview_warnings": "⚠️ Warnings",
        "preview_blockers": "⛔ Applying blocked",
        "preview_nothing": "Nothing to do – the server already matches the layout.",
        "confirm_merge": "Load the layout now (**merge** – nothing is deleted)? A backup is created automatically first.",
        "confirm_exact": "⚠️ **Exact sync** deletes roles and channels that are not in the layout – their messages are gone "
                         "for good. Click “Load” and type the server name to confirm.",
        "btn_load": "Load",
        "btn_cancel": "Cancel",
        "modal_title": "Confirm exact sync",
        "modal_label": "Type the server name to confirm",
        "name_mismatch": "The name does not match the server name – nothing changed.",
        "not_yours": "Only the person who ran the command can confirm this.",
        "aborted": "Cancelled – nothing changed.",
        "timeout": "Timed out – nothing changed.",
        "busy": "A layout is already being loaded on this server. Status: `{prefix}layout status`.",
        "changed": "The server or layout changed since the preview – please check again.",
        "blocked": "Applying blocked: {reasons}",
        "backup_failed": "Automatic backup failed – nothing was changed: {error}",
        "started": "⏳ Loading layout **{name}** ({mode}) … Progress: `{prefix}layout status`, cancel: `{prefix}layout cancel`.",
        "status_none": "No layout is being loaded on this server and there is no report yet.",
        "status_running": "⏳ **{name}** ({mode}) running: {done}/{total} steps ({percent} %) – {step}",
        "status_last": "Last run: **{name}** ({mode}) – {status}, {date}.\n{summary}",
        "cancel_ok": "⏹️ Cancel requested – the current step will still finish.",
        "cancel_none": "No layout is being loaded on this server.",
        "summary": "➕ {created} created · ✏️ {updated} changed · 🗑️ {deleted} deleted · ⏭️ {skipped} skipped · ❌ {errors} errors",
        "report_done": "✅ Layout **{name}** loaded.\n{summary}\nBackup before: **{backup}**",
        "report_cancelled": "⏹️ Loading **{name}** was cancelled.\n{summary}\nBackup before: **{backup}**",
        "report_failed": "❌ Loading **{name}** failed: {error}",
        "report_errors": "Errors (excerpt):\n{lines}",
        "st_done": "done", "st_cancelled": "cancelled", "st_failed": "failed", "st_running": "running",
        "mode_merge": "merge", "mode_exact": "exact sync",
        "part_roles": "roles", "part_channels": "channels", "part_settings": "settings",
        "lang_set": "Language set to **{name}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
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
