"""Mehrsprachigkeit für den Ideas-Cog (Aufbau wie poll/strings.py).

``de`` ist Standard und Fallback. ``t(lang, key, **kwargs)`` liefert den Text, fällt bei fehlender
Sprache/fehlendem Key auf Deutsch bzw. den Key zurück und formatiert mit ``str.format``.
Die Status-Namen sind zugleich die Namen der Forum-Tags (max. 20 Zeichen).
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

DEFAULT_LANGUAGE = "de"

# Reihenfolge = Anzeige-Reihenfolge überall (Kennzahlen, Auswahllisten, Tags)
STATUSES = ("new", "review", "planned", "done", "rejected", "merged")
OPEN_STATUSES = ("new", "review", "planned")
CLOSED_STATUSES = ("done", "rejected")

STATUS_EMOJI = {"new": "🆕", "review": "🔍", "planned": "📅", "done": "✅", "rejected": "❌", "merged": "🔗"}
STATUS_COLOR = {"new": 0x6CB6FF, "review": 0xF5B94A, "planned": 0xB28DFF, "done": 0x3DDC97,
                "rejected": 0xF2545B, "merged": 0x8B97A7}

STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # Status (= Forum-Tags)
        "status_new": "Neu",
        "status_review": "In Prüfung",
        "status_planned": "Geplant",
        "status_done": "Umgesetzt",
        "status_rejected": "Abgelehnt",
        "status_merged": "Zusammengeführt",
        # Panel
        "panel_thread": "💡 Idee einreichen",
        "panel_title": "💡 Idee einreichen",
        "panel_text": (
            "Du hast eine Idee für den Server? Klicke auf **Idee einreichen** und fülle das Formular aus.\n\n"
            "• Jede Idee bekommt einen eigenen Beitrag in diesem Forum mit Nummer und Status.\n"
            "• Das Team prüft die Ideen und setzt den Status (Neu, In Prüfung, Geplant, Umgesetzt, Abgelehnt).\n"
            "• Unter jeder Idee kannst du antworten und mitdiskutieren.\n"
            "• Eigene Beiträge bitte nur über das Formular – so geht keine Idee verloren."
        ),
        "panel_limits": "Pro Person höchstens {max_open} offene Ideen · Wartezeit zwischen zwei Ideen: {cooldown} Min.",
        "panel_button": "Idee einreichen",
        # Kategorie-Auswahl + Formular
        "cat_prompt": "Zu welcher Kategorie passt deine Idee?",
        "cat_placeholder": "Kategorie wählen …",
        "cat_none": "Ohne Kategorie",
        "modal_title": "Idee einreichen",
        "modal_field_title": "Titel",
        "modal_title_ph": "Kurz und knackig, z. B. „Wöchentlicher Spieleabend“",
        "modal_field_desc": "Beschreibung",
        "modal_desc_ph": "Was genau schlägst du vor und warum? (optional)",
        # Embed
        "embed_category": "Kategorie",
        "embed_author": "Eingereicht von",
        "embed_status": "Status",
        "embed_anonymous": "anonym",
        "embed_merged_into": "Zusammengeführt mit",
        "embed_polls": "Abstimmung",
        "embed_no_desc": "*Keine Beschreibung.*",
        "embed_footer": "Idee #{nr}",
        # Einreichen – Antworten
        "submitted": "✅ Deine Idee **#{nr}** wurde eingereicht: {link}",
        "dup_hint": "Hinweis: Es gibt schon eine ähnliche Idee – {links}",
        "thread_dup_note": "🔎 Ähnliche Ideen: {links}",
        "err_no_forum": "Der Ideen-Kanal ist noch nicht eingerichtet. Bitte wende dich an das Team.",
        "err_blocked": "Du kannst auf diesem Server keine Ideen einreichen (gesperrt).",
        "err_cooldown": "Bitte warte noch {minutes} Min., bevor du die nächste Idee einreichst.",
        "err_limit": "Du hast schon {max} offene Ideen. Warte, bis das Team eine davon bearbeitet hat.",
        "err_title_empty": "Bitte gib einen Titel an.",
        "err_title_long": "Der Titel darf höchstens {max} Zeichen lang sein.",
        "err_desc_long": "Die Beschreibung darf höchstens {max} Zeichen lang sein.",
        "err_category": "Unbekannte Kategorie. Möglich: {cats}",
        "err_post_failed": "Die Idee konnte nicht im Forum gepostet werden (Rechte des Bots prüfen).",
        "err_bot": "Bots können keine Ideen einreichen.",
        "err_no_view": "Du kannst den Ideen-Kanal nicht sehen.",
        # Team-Workflow im Beitrag / DM
        "status_note": "🔄 Status: **{old}** → **{new}**",
        "comment_note": "💬 **Team:** {text}",
        "merged_note": "🔗 Diese Idee wurde mit **#{nr} · {title}** zusammengeführt: {link}",
        "merged_target_note": "🔗 Idee **#{nr} · {title}** wurde hier zusammengeführt.",
        "poll_note": "🗳️ Diese Idee steht zur Abstimmung: {link}",
        "manual_registered": "💡 Als Idee **#{nr}** übernommen. Status: **{status}**.",
        "dm_status": "💡 Deine Idee **#{nr} · {title}** auf **{guild}** hat jetzt den Status **{status}**.",
        "dm_comment": "Kommentar vom Team: {text}",
        # Befehle
        "no_permission": "Dazu fehlt dir die Berechtigung (Server verwalten oder Ideen-Team-Rolle).",
        "not_found": "Idee `#{nr}` nicht gefunden.",
        "bad_status": "Unbekannter Status. Möglich: {valid}",
        "status_set": "✅ Idee **#{nr}** hat jetzt den Status **{status}**.",
        "status_same": "Idee **#{nr}** hat bereits den Status **{status}**.",
        "comment_ok": "💬 Kommentar zu Idee **#{nr}** gepostet.",
        "comment_empty": "Bitte einen Kommentar eingeben.",
        "merge_same": "Eine Idee kann nicht mit sich selbst zusammengeführt werden.",
        "merge_bad_target": "Idee `#{nr}` kann kein Ziel sein (gelöscht oder selbst zusammengeführt).",
        "merge_already": "Idee `#{nr}` ist bereits zusammengeführt.",
        "merged_ok": "🔗 Idee **#{dup}** wurde mit **#{target}** zusammengeführt.",
        "bad_field": "Feld muss `titel`, `beschreibung` oder `kategorie` sein.",
        "edited_ok": "✏️ Idee **#{nr}** wurde aktualisiert.",
        "delete_confirm": "Idee **#{nr}** und ihr Forum-Beitrag werden gelöscht. Zum Bestätigen: `{cmd}`",
        "deleted_ok": "🗑️ Idee **#{nr}** wurde gelöscht.",
        "blocked_ok": "⛔ {user} kann keine Ideen mehr einreichen.",
        "unblocked_ok": "✅ {user} kann wieder Ideen einreichen.",
        "block_team": "Team-Mitglieder und der Bot-Owner können nicht gesperrt werden.",
        "list_empty": "Keine passenden Ideen.",
        "list_header": "**Ideen auf diesem Server**",
        "list_row": "`#{nr}` {emoji} {title} · {status}{cat}",
        "export_empty": "Es gibt noch keine Ideen zum Exportieren.",
        "export_ok": "📄 Export aller Ideen:",
        # Umfrage
        "poll_missing": "Der Umfragen-Cog (`poll`) ist nicht geladen – `[p]load poll`.",
        "poll_old": "Der Umfragen-Cog ist zu alt (keine Funktion `create_poll`).",
        "poll_few": "Bitte mindestens 2 Ideen auswählen.",
        "poll_many": "Zu viele Ideen – der Umfragen-Cog erlaubt höchstens {max} Optionen.",
        "poll_not_open": "Nur offene Ideen können zur Abstimmung gestellt werden: {nrs}",
        "poll_unknown": "Unbekannte Ideen: {nrs}",
        "poll_bad_channel": "Bitte einen Textkanal für die Umfrage wählen.",
        "poll_bad_duration": "Dauer nicht erkannt (z. B. 2h, 30m, 1d).",
        "poll_bad_question": "Die Frage darf nicht leer und höchstens {max} Zeichen lang sein.",
        "poll_post_failed": "Die Umfrage wurde angelegt, konnte aber nicht gepostet werden (Rechte im Kanal prüfen).",
        "poll_default_question": "Welche Idee sollen wir als Nächstes umsetzen?",
        "poll_ok": "🗳️ Umfrage mit {n} Ideen gestartet: {link}",
        # Einstellungen
        "set_forum": "✅ Ideen-Forum: {forum}",
        "set_forum_bad": "Das ist kein Forum-Kanal.",
        "set_tag_warn": "⚠️ {warn}",
        "tag_warn_perm": "Dem Bot fehlt im Forum das Recht „Kanäle verwalten“ – fehlende Tags konnten nicht angelegt werden: {tags}",
        "tag_warn_limit": "Forum-Tag-Limit (20) erreicht – nicht angelegt: {tags}",
        "tag_warn_fail": "Tags konnten nicht angelegt werden: {tags}",
        "panel_ok": "✅ Panel „Idee einreichen“ ist im Forum: {link}",
        "panel_fail": "Das Panel konnte nicht gepostet werden (Rechte im Forum prüfen).",
        "forum_created": "✅ Forum {forum} angelegt – mit Status-Tags und Panel.",
        "forum_create_fail": "Das Forum konnte nicht angelegt werden (Recht „Kanäle verwalten“ prüfen).",
        "forum_topic": "Ideen der Community. Neue Ideen bitte über den angepinnten Beitrag „💡 Idee einreichen“.",
        "set_ok": "✅ Gespeichert.",
        "teamrole_added": "Team-Rolle hinzugefügt: {role}.",
        "teamrole_removed": "Team-Rolle entfernt: {role}.",
        "categories_set": "✅ Kategorien: {cats}",
        "categories_bad": "Höchstens {max} Kategorien mit je höchstens {len} Zeichen.",
        "lang_set": "Sprache: {lang}.",
        "lang_bad": "Unbekannte Sprache. Möglich: {langs}",
    },
    "en": {
        "status_new": "New",
        "status_review": "Under review",
        "status_planned": "Planned",
        "status_done": "Done",
        "status_rejected": "Rejected",
        "status_merged": "Merged",
        "panel_thread": "💡 Submit an idea",
        "panel_title": "💡 Submit an idea",
        "panel_text": (
            "Got an idea for the server? Click **Submit idea** and fill in the form.\n\n"
            "• Every idea gets its own post in this forum with a number and a status.\n"
            "• The team reviews ideas and sets the status (New, Under review, Planned, Done, Rejected).\n"
            "• You can reply to every idea and join the discussion.\n"
            "• Please only post through the form – that way no idea gets lost."
        ),
        "panel_limits": "At most {max_open} open ideas per person · wait {cooldown} min. between two ideas",
        "panel_button": "Submit idea",
        "cat_prompt": "Which category fits your idea?",
        "cat_placeholder": "Choose a category …",
        "cat_none": "No category",
        "modal_title": "Submit an idea",
        "modal_field_title": "Title",
        "modal_title_ph": "Short and clear, e.g. “Weekly game night”",
        "modal_field_desc": "Description",
        "modal_desc_ph": "What exactly do you suggest and why? (optional)",
        "embed_category": "Category",
        "embed_author": "Submitted by",
        "embed_status": "Status",
        "embed_anonymous": "anonymous",
        "embed_merged_into": "Merged into",
        "embed_polls": "Vote",
        "embed_no_desc": "*No description.*",
        "embed_footer": "Idea #{nr}",
        "submitted": "✅ Your idea **#{nr}** has been submitted: {link}",
        "dup_hint": "Note: there is already a similar idea – {links}",
        "thread_dup_note": "🔎 Similar ideas: {links}",
        "err_no_forum": "The ideas channel has not been set up yet. Please contact the team.",
        "err_blocked": "You cannot submit ideas on this server (blocked).",
        "err_cooldown": "Please wait another {minutes} min. before submitting your next idea.",
        "err_limit": "You already have {max} open ideas. Wait until the team has handled one of them.",
        "err_title_empty": "Please enter a title.",
        "err_title_long": "The title may be at most {max} characters long.",
        "err_desc_long": "The description may be at most {max} characters long.",
        "err_category": "Unknown category. Possible: {cats}",
        "err_post_failed": "The idea could not be posted in the forum (check the bot's permissions).",
        "err_bot": "Bots cannot submit ideas.",
        "err_no_view": "You cannot see the ideas channel.",
        "status_note": "🔄 Status: **{old}** → **{new}**",
        "comment_note": "💬 **Team:** {text}",
        "merged_note": "🔗 This idea was merged into **#{nr} · {title}**: {link}",
        "merged_target_note": "🔗 Idea **#{nr} · {title}** was merged into this one.",
        "poll_note": "🗳️ This idea is up for a vote: {link}",
        "manual_registered": "💡 Registered as idea **#{nr}**. Status: **{status}**.",
        "dm_status": "💡 Your idea **#{nr} · {title}** on **{guild}** now has the status **{status}**.",
        "dm_comment": "Comment from the team: {text}",
        "no_permission": "You lack the permission for this (Manage Server or ideas team role).",
        "not_found": "Idea `#{nr}` not found.",
        "bad_status": "Unknown status. Possible: {valid}",
        "status_set": "✅ Idea **#{nr}** now has the status **{status}**.",
        "status_same": "Idea **#{nr}** already has the status **{status}**.",
        "comment_ok": "💬 Comment on idea **#{nr}** posted.",
        "comment_empty": "Please enter a comment.",
        "merge_same": "An idea cannot be merged into itself.",
        "merge_bad_target": "Idea `#{nr}` cannot be a target (deleted or merged itself).",
        "merge_already": "Idea `#{nr}` has already been merged.",
        "merged_ok": "🔗 Idea **#{dup}** was merged into **#{target}**.",
        "bad_field": "Field must be `title`, `description` or `category`.",
        "edited_ok": "✏️ Idea **#{nr}** has been updated.",
        "delete_confirm": "Idea **#{nr}** and its forum post will be deleted. To confirm: `{cmd}`",
        "deleted_ok": "🗑️ Idea **#{nr}** has been deleted.",
        "blocked_ok": "⛔ {user} can no longer submit ideas.",
        "unblocked_ok": "✅ {user} can submit ideas again.",
        "block_team": "Team members and the bot owner cannot be blocked.",
        "list_empty": "No matching ideas.",
        "list_header": "**Ideas on this server**",
        "list_row": "`#{nr}` {emoji} {title} · {status}{cat}",
        "export_empty": "There are no ideas to export yet.",
        "export_ok": "📄 Export of all ideas:",
        "poll_missing": "The poll cog (`poll`) is not loaded – `[p]load poll`.",
        "poll_old": "The poll cog is too old (no `create_poll` function).",
        "poll_few": "Please select at least 2 ideas.",
        "poll_many": "Too many ideas – the poll cog allows at most {max} options.",
        "poll_not_open": "Only open ideas can be put to a vote: {nrs}",
        "poll_unknown": "Unknown ideas: {nrs}",
        "poll_bad_channel": "Please choose a text channel for the poll.",
        "poll_bad_duration": "Duration not recognised (e.g. 2h, 30m, 1d).",
        "poll_bad_question": "The question must not be empty and at most {max} characters long.",
        "poll_post_failed": "The poll was created but could not be posted (check channel permissions).",
        "poll_default_question": "Which idea should we implement next?",
        "poll_ok": "🗳️ Poll with {n} ideas started: {link}",
        "set_forum": "✅ Ideas forum: {forum}",
        "set_forum_bad": "That is not a forum channel.",
        "set_tag_warn": "⚠️ {warn}",
        "tag_warn_perm": "The bot lacks “Manage Channels” in the forum – missing tags could not be created: {tags}",
        "tag_warn_limit": "Forum tag limit (20) reached – not created: {tags}",
        "tag_warn_fail": "Tags could not be created: {tags}",
        "panel_ok": "✅ The “Submit idea” panel is in the forum: {link}",
        "panel_fail": "The panel could not be posted (check forum permissions).",
        "forum_created": "✅ Forum {forum} created – with status tags and panel.",
        "forum_create_fail": "The forum could not be created (check “Manage Channels”).",
        "forum_topic": "Community ideas. Please submit new ideas via the pinned post “💡 Submit an idea”.",
        "set_ok": "✅ Saved.",
        "teamrole_added": "Team role added: {role}.",
        "teamrole_removed": "Team role removed: {role}.",
        "categories_set": "✅ Categories: {cats}",
        "categories_bad": "At most {max} categories with at most {len} characters each.",
        "lang_set": "Language: {lang}.",
        "lang_bad": "Unknown language. Possible: {langs}",
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
    table = STRINGS.get(lang or DEFAULT_LANGUAGE) or STRINGS[DEFAULT_LANGUAGE]
    text = table.get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANGUAGE].get(key, key)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError, ValueError):
        return text


def status_label(lang: str | None, status: str) -> str:
    return t(lang, f"status_{status}")


def status_aliases() -> dict[str, str]:
    """Eingabe (Key oder Name in jeder Sprache, ohne Leer-/Sonderzeichen) -> Status-Key."""
    out: dict[str, str] = {}

    def norm(s):
        return "".join(c for c in s.casefold().replace("ü", "ue") if c.isalnum())

    for key in STATUSES:
        out[norm(key)] = key
        for lang in STRINGS:
            out[norm(status_label(lang, key))] = key
    extra = {"pruefung": "review", "offen": "new", "umgesetzt": "done", "abgelehnt": "rejected",
             "duplikat": "merged", "merge": "merged", "geplant": "planned"}
    for k, v in extra.items():
        out[norm(k)] = v
    return out


def normalize_status(text: str | None) -> str | None:
    if not text:
        return None
    key = "".join(c for c in str(text).casefold().replace("ü", "ue") if c.isalnum())
    return status_aliases().get(key)
