"""Mehrsprachigkeit für den Sticky-Cog.

Aufbau wie im Tickets-/RaidHelper-Cog:
1. Sprachpakete (``STRINGS``) – ``de`` ist Standard und Fallback. Weitere
   Sprache = ein weiterer Block.
2. ``t(lang, key, **kwargs)`` liefert den passenden String, fällt bei fehlender
   Sprache/fehlendem Key auf Deutsch bzw. den Key selbst zurück und formatiert
   optional mit ``str.format``.

Hinweis: Übersetzt werden **nur die Antworten des Bots** (Befehls-Feedback). Der
eigentliche Sticky-Inhalt wird vom Team frei festgelegt und nicht übersetzt. Die
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
        # Modus / Status (für Listen & Anzeige)
        "mode_text": "Text",
        "mode_embed": "Embed",
        "state_on": "aktiv",
        "state_off": "aus",
        "webhook_on": "Webhook",
        "webhook_off": "Bot",
        # Setzen / Entfernen
        "no_text": "Bitte gib einen Text für die Sticky an.",
        "set_ok": "📌 Sticky in {channel} gesetzt ({mode}).",
        "removed": "🗑️ Sticky in {channel} entfernt.",
        "not_set": "In {channel} ist keine Sticky eingerichtet.",
        "toggled_on": "✅ Sticky in {channel} aktiviert.",
        "toggled_off": "⏸️ Sticky in {channel} deaktiviert.",
        "refreshed": "🔄 Sticky in {channel} neu gepostet.",
        "is_disabled": "Die Sticky in {channel} ist deaktiviert. Aktiviere sie mit `{p}sticky toggle {channel}`.",
        # Anzeige (show)
        "show_header": "**Sticky in {channel}**",
        "show_mode": "Modus: {mode}",
        "show_state": "Status: {state}",
        "show_webhook": "Posten via: {via}",
        "show_text": "Inhalt:\n{text}",
        # Liste
        "list_header": "**Stickies auf diesem Server**",
        "list_row": "{channel} · {mode} · {state} · {via}",
        "list_empty": "Auf diesem Server sind keine Stickies eingerichtet.",
        # Einstellungen
        "cooldown_set": "⏱️ Cooldown auf {sec}s gesetzt (frühestens so oft wird neu gepostet).",
        "cooldown_bad": "Bitte eine ganze Zahl zwischen 0 und 3600 angeben.",
        "ignorebots_on": "Andere Bots werden jetzt **ignoriert** (lösen kein Neu-Posten aus).",
        "ignorebots_off": "Andere Bots lösen jetzt **ebenfalls** ein Neu-Posten aus.",
        "lang_set": "Sprache auf **{lang}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        # Fehler / Hinweise
        "no_perm": "Mir fehlen Rechte in {channel} (mindestens **Nachrichten senden** und **Nachrichten verwalten**; für den Webhook-Modus zusätzlich **Webhooks verwalten**).",
        "settings_header": "**Sticky-Einstellungen**",
        "settings_cooldown": "Cooldown: {sec}s",
        "settings_ignorebots": "Andere Bots ignorieren: {state}",
        "settings_lang": "Sprache: {lang}",
        "yes": "ja",
        "no": "nein",
    },
    "en": {
        "mode_text": "Text",
        "mode_embed": "Embed",
        "state_on": "active",
        "state_off": "off",
        "webhook_on": "Webhook",
        "webhook_off": "Bot",
        "no_text": "Please provide a text for the sticky.",
        "set_ok": "📌 Sticky set in {channel} ({mode}).",
        "removed": "🗑️ Sticky removed in {channel}.",
        "not_set": "There is no sticky configured in {channel}.",
        "toggled_on": "✅ Sticky enabled in {channel}.",
        "toggled_off": "⏸️ Sticky disabled in {channel}.",
        "refreshed": "🔄 Sticky reposted in {channel}.",
        "is_disabled": "The sticky in {channel} is disabled. Enable it with `{p}sticky toggle {channel}`.",
        "show_header": "**Sticky in {channel}**",
        "show_mode": "Mode: {mode}",
        "show_state": "Status: {state}",
        "show_webhook": "Posted via: {via}",
        "show_text": "Content:\n{text}",
        "list_header": "**Stickies on this server**",
        "list_row": "{channel} · {mode} · {state} · {via}",
        "list_empty": "There are no stickies configured on this server.",
        "cooldown_set": "⏱️ Cooldown set to {sec}s (the sticky reposts at most this often).",
        "cooldown_bad": "Please provide a whole number between 0 and 3600.",
        "ignorebots_on": "Other bots are now **ignored** (they no longer trigger a repost).",
        "ignorebots_off": "Other bots now **also** trigger a repost.",
        "lang_set": "Language set to **{lang}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "no_perm": "I am missing permissions in {channel} (at least **Send Messages** and **Manage Messages**; for webhook mode also **Manage Webhooks**).",
        "settings_header": "**Sticky settings**",
        "settings_cooldown": "Cooldown: {sec}s",
        "settings_ignorebots": "Ignore other bots: {state}",
        "settings_lang": "Language: {lang}",
        "yes": "yes",
        "no": "no",
    },
}

# Frei überschreibbare Schlüssel (für künftige Server-Overrides). Aktuell keine,
# da der Sticky-Inhalt ohnehin vollständig vom Team festgelegt wird.
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
