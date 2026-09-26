"""Mehrsprachigkeit für den Levels-Cog (Aufbau wie welcome/guard).

``de`` ist Standard und Fallback. ``t(lang, key, **kwargs)`` formatiert nur eigene, feste Texte
mit ``str.format``; Nutzertexte (Level-Up-Meldung) laufen über ``levels.fill_placeholders``,
das ausschließlich die bekannten Platzhalter ersetzt.
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

PLACEHOLDERS = ("user", "name", "level", "server")

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        "levelup_default": "🎉 {user} hat **Level {level}** erreicht!",
        "card_level": "LEVEL",
        "card_rank": "RANG",
        "card_xp": "{into} / {needed} XP",
        "card_total": "{total} XP gesamt",
        "rank_title": "Rang von {name}",
        "rank_line": "**Rang #{rank}** · Level **{level}** · {xp} XP\nNoch **{left} XP** bis Level {next}.",
        "rank_unranked": "noch ohne Rang",
        "rank_bot": "Bots sammeln keine XP.",
        "lb_title": "🏆 Rangliste – {server}",
        "lb_line": "**#{rank}** {name} — Level {level} · {xp} XP",
        "lb_empty": "Noch hat niemand XP gesammelt.",
        "lb_footer": "Seite {page}/{pages} · Dein Rang: {rank}",
        "lb_page_bad": "Diese Seite gibt es nicht (1–{pages}).",
        "disabled": "Das Levelsystem ist auf diesem Server ausgeschaltet.",
        "xp_done": "✅ {name}: jetzt **{xp} XP** (Level {level}).",
        "xp_amount_bad": "Bitte eine Menge zwischen 1 und {max} angeben.",
        "xp_bot": "Bots sammeln keine XP.",
        "toggle_set": "Levelsystem ist jetzt **{state}**.",
        "range_set": "XP pro Nachricht: **{min}–{max}**.",
        "range_bad": "Ungültiger Bereich (1–{max}, min ≤ max).",
        "cooldown_set": "Cooldown: **{sec} s** pro Mitglied.",
        "cooldown_bad": "Cooldown muss zwischen 0 und {max} Sekunden liegen.",
        "voice_set": "Voice-XP: **{state}** ({xp} XP pro Minute).",
        "voice_bad": "Voice-XP muss zwischen 1 und {max} liegen.",
        "exclude_channel_on": "🔕 In {channel} gibt es keine XP mehr.",
        "exclude_channel_off": "🔔 In {channel} gibt es wieder XP.",
        "exclude_role_on": "🔕 Mitglieder mit {role} bekommen keine XP mehr.",
        "exclude_role_off": "🔔 Mitglieder mit {role} bekommen wieder XP.",
        "mult_set": "Multiplikator für {role}: **×{factor}**.",
        "mult_removed": "Multiplikator für {role} entfernt.",
        "mult_bad": "Faktor muss zwischen {min} und {max} liegen (1 = entfernen).",
        "reward_set": "🎁 Level **{level}** → {role}.",
        "reward_removed": "Belohnung für Level **{level}** entfernt.",
        "reward_none": "Für Level {level} ist keine Belohnung eingetragen.",
        "reward_level_bad": "Level muss zwischen 1 und {max} liegen.",
        "reward_role_bad": "Diese Rolle kann nicht vergeben werden (@everyone oder von einer Integration verwaltet).",
        "reward_bot_hierarchy": "Die Rolle {role} liegt nicht unter meiner höchsten Rolle oder mir fehlt „Rollen verwalten“.",
        "reward_user_hierarchy": "Du darfst {role} nicht als Belohnung eintragen (Rolle liegt nicht unter deiner höchsten Rolle oder hat Moderationsrechte).",
        "stack_set": "Belohnungen: **{mode}**.",
        "stack_on": "stapeln (alle erreichten Rollen behalten)",
        "stack_off": "nur die höchste erreichte Rolle",
        "announce_set": "Level-Up-Meldung: **{mode}**.",
        "announce_needs_channel": "Für „channel“ bitte einen Kanal angeben.",
        "message_set": "✅ Text der Level-Up-Meldung gespeichert.",
        "message_reset": "Text der Level-Up-Meldung zurückgesetzt (Standardtext).",
        "message_bad": "Text zu lang (max. {max} Zeichen).",
        "lang_set": "Sprache auf **{language}** gesetzt.",
        "lang_unknown": "Unbekannte Sprache `{code}`. Verfügbar: {langs}.",
        "sync_done": "Belohnungen abgeglichen: {added} vergeben, {removed} entfernt.",
        "mode_off": "aus", "mode_same": "im selben Kanal", "mode_channel": "fester Kanal", "mode_dm": "per DM",
        "on": "an", "off": "aus", "none": "—",
        "settings_title": "Level – Einstellungen",
        "settings_general": "Allgemein",
        "settings_xp": "XP pro Nachricht",
        "settings_cooldown": "Cooldown",
        "settings_voice": "Voice-XP",
        "settings_announce": "Level-Up-Meldung",
        "settings_rewards": "Belohnungen",
        "settings_excluded": "Ausgeschlossen",
        "settings_mult": "Multiplikatoren",
    },
    "en": {
        "levelup_default": "🎉 {user} reached **level {level}**!",
        "card_level": "LEVEL",
        "card_rank": "RANK",
        "card_xp": "{into} / {needed} XP",
        "card_total": "{total} XP total",
        "rank_title": "Rank of {name}",
        "rank_line": "**Rank #{rank}** · level **{level}** · {xp} XP\n**{left} XP** to level {next}.",
        "rank_unranked": "not ranked yet",
        "rank_bot": "Bots don't earn XP.",
        "lb_title": "🏆 Leaderboard – {server}",
        "lb_line": "**#{rank}** {name} — level {level} · {xp} XP",
        "lb_empty": "Nobody has earned XP yet.",
        "lb_footer": "Page {page}/{pages} · Your rank: {rank}",
        "lb_page_bad": "That page doesn't exist (1–{pages}).",
        "disabled": "The level system is turned off on this server.",
        "xp_done": "✅ {name}: now **{xp} XP** (level {level}).",
        "xp_amount_bad": "Please give an amount between 1 and {max}.",
        "xp_bot": "Bots don't earn XP.",
        "toggle_set": "Level system is now **{state}**.",
        "range_set": "XP per message: **{min}–{max}**.",
        "range_bad": "Invalid range (1–{max}, min ≤ max).",
        "cooldown_set": "Cooldown: **{sec} s** per member.",
        "cooldown_bad": "Cooldown must be between 0 and {max} seconds.",
        "voice_set": "Voice XP: **{state}** ({xp} XP per minute).",
        "voice_bad": "Voice XP must be between 1 and {max}.",
        "exclude_channel_on": "🔕 {channel} no longer gives XP.",
        "exclude_channel_off": "🔔 {channel} gives XP again.",
        "exclude_role_on": "🔕 Members with {role} no longer earn XP.",
        "exclude_role_off": "🔔 Members with {role} earn XP again.",
        "mult_set": "Multiplier for {role}: **×{factor}**.",
        "mult_removed": "Multiplier for {role} removed.",
        "mult_bad": "Factor must be between {min} and {max} (1 = remove).",
        "reward_set": "🎁 Level **{level}** → {role}.",
        "reward_removed": "Reward for level **{level}** removed.",
        "reward_none": "There is no reward for level {level}.",
        "reward_level_bad": "Level must be between 1 and {max}.",
        "reward_role_bad": "This role can't be granted (@everyone or managed by an integration).",
        "reward_bot_hierarchy": "The role {role} is not below my highest role or I lack “Manage Roles”.",
        "reward_user_hierarchy": "You may not use {role} as a reward (not below your highest role or it has moderation permissions).",
        "stack_set": "Rewards: **{mode}**.",
        "stack_on": "stack (keep all reached roles)",
        "stack_off": "only the highest reached role",
        "announce_set": "Level-up message: **{mode}**.",
        "announce_needs_channel": "For “channel” please give a channel.",
        "message_set": "✅ Level-up message saved.",
        "message_reset": "Level-up message reset (default text).",
        "message_bad": "Text too long (max. {max} characters).",
        "lang_set": "Language set to **{language}**.",
        "lang_unknown": "Unknown language `{code}`. Available: {langs}.",
        "sync_done": "Rewards synced: {added} granted, {removed} removed.",
        "mode_off": "off", "mode_same": "same channel", "mode_channel": "fixed channel", "mode_dm": "via DM",
        "on": "on", "off": "off", "none": "—",
        "settings_title": "Levels – settings",
        "settings_general": "General",
        "settings_xp": "XP per message",
        "settings_cooldown": "Cooldown",
        "settings_voice": "Voice XP",
        "settings_announce": "Level-up message",
        "settings_rewards": "Rewards",
        "settings_excluded": "Excluded",
        "settings_mult": "Multipliers",
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
