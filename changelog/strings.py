"""Mehrsprachigkeit für den Changelog-Cog.

Aufbau wie in Poll/Tickets/RaidHelper:
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
        # ---- Embed ----
        "embed_title": "🆕 SERVER UPDATE – {title}",
        "field_new": "Neu",
        "field_changed": "Geändert",
        "field_fixes": "Fixes",
        "field_note": "Hinweis",
        "footer": "gepostet von {author}",
        # ---- Modal ----
        "modal_title": "Changelog erstellen",
        "f_title_label": "Titel",
        "f_title_ph": "z. B. Fahrzeug-Update",
        "f_new_label": "Neu (ein Punkt pro Zeile)",
        "f_changed_label": "Geändert (ein Punkt pro Zeile)",
        "f_fixes_label": "Fixes (ein Punkt pro Zeile)",
        "f_note_label": "Hinweis (optional)",
        "f_note_ph": "z. B. Serverneustart erforderlich",
        "ph_lines": "ein Punkt pro Zeile",
        # ---- Rückmeldungen an die postende Person (ephemer) ----
        "posted_ok": "Changelog gepostet ✅",
        "err_need_section": "Bitte mindestens eines der Felder **Neu**, **Geändert** oder **Fixes** ausfüllen.",
        "err_no_channel": "Es ist kein Ziel-Kanal konfiguriert. Ein Admin kann ihn im Dashboard oder mit `{prefix}changelogset channel` setzen.",
        "err_no_perm": "Du darfst hier keine Changelogs posten.",
        "err_channel_gone": "Der konfigurierte Ziel-Kanal existiert nicht mehr.",
        "err_cant_send": "Ich darf im Ziel-Kanal nicht schreiben (fehlende Rechte).",
        "err_guild_only": "Dieser Befehl funktioniert nur auf einem Server.",
        # ---- Autocomplete ----
        "cat_none": "Standard 🆕",
    },
    "en": {
        # ---- Embed ----
        "embed_title": "🆕 SERVER UPDATE – {title}",
        "field_new": "New",
        "field_changed": "Changed",
        "field_fixes": "Fixes",
        "field_note": "Note",
        "footer": "posted by {author}",
        # ---- Modal ----
        "modal_title": "Create changelog",
        "f_title_label": "Title",
        "f_title_ph": "e.g. Vehicle update",
        "f_new_label": "New (one item per line)",
        "f_changed_label": "Changed (one item per line)",
        "f_fixes_label": "Fixes (one item per line)",
        "f_note_label": "Note (optional)",
        "f_note_ph": "e.g. server restart required",
        "ph_lines": "one item per line",
        # ---- Feedback to the posting user (ephemeral) ----
        "posted_ok": "Changelog posted ✅",
        "err_need_section": "Please fill in at least one of **New**, **Changed** or **Fixes**.",
        "err_no_channel": "No target channel is configured. An admin can set it in the dashboard or with `{prefix}changelogset channel`.",
        "err_no_perm": "You are not allowed to post changelogs here.",
        "err_channel_gone": "The configured target channel no longer exists.",
        "err_cant_send": "I am not allowed to post in the target channel (missing permissions).",
        "err_guild_only": "This command only works on a server.",
        # ---- Autocomplete ----
        "cat_none": "Default 🆕",
    },
}

# Sichtbare Texte, die pro Server im Dashboard überschrieben werden dürfen.
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "embed_title",
    "footer",
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
