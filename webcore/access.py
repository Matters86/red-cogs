"""Rechte-Logik des Dashboards (ohne discord-/aiohttp-Abhängigkeit, separat testbar).

Modell
------
Pro Server und Discord-Rolle kann der Bot-Owner für jede Dashboard-Seite eine
Stufe vergeben::

    role_perms = {
        "<guild_id>": {
            "<role_id>": {"tickets": "edit", "poll": "view", ...},
        },
    }

* ``view``     – Seite öffnen und alles ansehen, aber nichts speichern.
* ``operate``  – „Bedienen“: zusätzlich das Tagesgeschäft der Seite ausführen (z. B. Ticket schließen,
  verwarnen, entbannen) – nur Formulare, die der Cog per ``register_page(..., operate_forms=…)`` als
  Tagesgeschäft markiert hat. Keine Einstellungen.
* ``edit``     – ansehen und speichern (alle Formulare der Seite).
* fehlt        – kein Zugriff, die Seite erscheint nicht in der Navigation.

Gespeichert werden immer die Namen (``"view"``/``"operate"``/``"edit"``), nie Zahlen – deshalb bleiben
ältere Einträge (``view``/``edit``) nach Einführung von ``operate`` unverändert gültig.

Hat ein Mitglied mehrere Rollen, gilt die höchste Stufe je Seite.
Bot-Owner und Allowlist haben immer überall ``edit``; im Zugriffsmodus
``admin`` haben Discord-Administratoren eines Servers dort ebenfalls ``edit``.
"""

from __future__ import annotations

NONE = 0
VIEW = 1
OPERATE = 2
EDIT = 3

# Kanonische Namen (so wird gespeichert und in Sicherungen akzeptiert).
LEVEL_BY_NAME = {"none": NONE, "view": VIEW, "operate": OPERATE, "edit": EDIT}
NAME_BY_LEVEL = {NONE: "none", VIEW: "view", OPERATE: "operate", EDIT: "edit"}
LEVEL_LABEL = {NONE: "Kein Zugriff", VIEW: "Ansehen", OPERATE: "Bedienen", EDIT: "Bearbeiten"}
# Zusätzliche Schreibweisen für Befehle (deutsch) – werden nie gespeichert.
LEVEL_ALIASES = {
    "kein": NONE, "keine": NONE, "nichts": NONE, "aus": NONE, "-": NONE, "—": NONE,
    "ansehen": VIEW, "ansicht": VIEW, "lesen": VIEW,
    "bedienen": OPERATE,
    "bearbeiten": EDIT,
}

# Rollen-Vorlagen: Stufe je Seiten-slug, ``default`` für alle anderen (auch künftige) Seiten.
# Beim Anwenden werden nur aktuell registrierte Seiten gesetzt.
ROLE_TEMPLATES = {
    "view": {"label": "Nur ansehen", "default": "view", "levels": {},
             "desc": "Alle Seiten ansehen, nichts ändern."},
    "operate": {"label": "Bedienen", "default": "operate", "levels": {},
                "desc": "Überall Tagesgeschäft, keine Einstellungen."},
    "edit": {"label": "Bearbeiten", "default": "edit", "levels": {},
             "desc": "Alle Seiten ansehen und bearbeiten."},
    "support": {"label": "Support", "default": "none",
                "levels": {"tickets": "operate", "warnings": "view", "commands": "view", "serverstats": "view"},
                "desc": "Tickets bearbeiten, Verwarnungen/Befehle/Statistik ansehen."},
    "moderator": {"label": "Moderator", "default": "none",
                  "levels": {"tickets": "operate", "warnings": "operate", "guard": "operate", "poll": "operate",
                             "sticky": "operate", "fivemadmin": "operate", "commands": "view",
                             "serverstats": "view", "levels": "view"},
                  "desc": "Moderations-Tagesgeschäft (Tickets, Verwarnungen, Schutz, Umfragen, Sticky, FiveM)."},
    "eventleitung": {"label": "Eventleitung", "default": "none",
                     "levels": {"raidhelper": "operate", "giveaways": "operate", "scheduler": "operate",
                                "poll": "operate", "serverstats": "view"},
                     "desc": "Events, Gewinnspiele, geplante Nachrichten und Umfragen bedienen."},
    "admin": {"label": "Admin", "default": "edit", "levels": {},
              "desc": "Alle Seiten bearbeiten."},
}
TEMPLATE_ALIASES = {
    "nur ansehen": "view", "nur-ansehen": "view", "ansehen": "view", "bedienen": "operate",
    "bearbeiten": "edit", "mod": "moderator", "moderation": "moderator", "event": "eventleitung",
    "events": "eventleitung", "eventleiter": "eventleitung", "administrator": "admin",
}

AUDIT_MAX = 300
# Höchstens so viele Einträge aus dem Mitglieder-Bereich im Audit-Log, damit viele
# Mitglieder-Aktionen die Team-/Owner-Einträge nicht verdrängen.
MEMBER_AUDIT_MAX = 150


def parse_level(value) -> int:
    """'none'/'view'/'operate'/'edit' (auch deutsch: ansehen/bedienen/bearbeiten) oder
    eine Stufen-Zahl (0–3) -> Stufe; Unbekanntes = kein Zugriff."""
    if isinstance(value, int) and not isinstance(value, bool) and value in NAME_BY_LEVEL:
        return value
    key = str(value or "").strip().lower()
    if key in LEVEL_BY_NAME:
        return LEVEL_BY_NAME[key]
    return LEVEL_ALIASES.get(key, NONE)


def is_level_name(value) -> bool:
    """Ist ``value`` ein gültiger Stufen-Name (kanonisch oder deutscher Alias)?"""
    key = str(value or "").strip().lower()
    return key in LEVEL_BY_NAME or key in LEVEL_ALIASES


def resolve_template(name) -> str | None:
    """Schlüssel einer Rollen-Vorlage aus Schlüssel, Anzeigename oder Alias (``None`` = unbekannt)."""
    key = " ".join(str(name or "").strip().lower().split())
    if key in ROLE_TEMPLATES:
        return key
    if key in TEMPLATE_ALIASES:
        return TEMPLATE_ALIASES[key]
    for tkey, tpl in ROLE_TEMPLATES.items():
        if tpl["label"].lower() == key:
            return tkey
    return None


def template_levels(template: str, slugs) -> dict:
    """{slug: Stufen-Name} der Vorlage für die gegebenen (registrierten) Seiten, ohne ``none``."""
    tpl = ROLE_TEMPLATES[template]
    out = {}
    for slug in slugs:
        lvl = parse_level(tpl["levels"].get(slug, tpl["default"]))
        if lvl > NONE:
            out[slug] = NAME_BY_LEVEL[lvl]
    return out


def apply_template(entry: dict | None, template: str, slugs) -> dict:
    """Neuer Rechte-Eintrag einer Rolle: registrierte Seiten laut Vorlage, Einträge für aktuell nicht
    registrierte Seiten (Cog entladen) bleiben erhalten."""
    slugs = list(slugs)
    out = {s: v for s, v in (entry or {}).items() if s not in slugs}
    out.update(template_levels(template, slugs))
    return out


def form_values(data, key: str) -> list:
    """Alle Werte eines POST-Feldes (MultiDict oder dict)."""
    if hasattr(data, "getall"):
        return [str(v) for v in data.getall(key, [])]
    v = data.get(key) if hasattr(data, "get") else None
    return [] if v is None else [str(v)]


def is_operate_post(operate_forms, data) -> bool:
    """Ist der POST laut ``operate_forms`` Tagesgeschäft?

    ``operate_forms``: Menge von Werten des Feldes ``form`` (falls vorhanden, sonst ``action``) oder
    ein Callable ``(data) -> bool``. Bei mehreren Werten des Feldes müssen ALLE in der Menge sein.
    Fehler im Callable = kein Tagesgeschäft.
    """
    if not operate_forms:
        return False
    if callable(operate_forms):
        try:
            return operate_forms(data) is True
        except Exception:  # noqa: BLE001 – im Zweifel „Bearbeiten“ verlangen
            return False
    values = form_values(data, "form")
    if not any(values):
        values = form_values(data, "action")
    return bool(values) and all(v in operate_forms for v in values)


def guild_role_perms(role_perms: dict | None, guild_id: int) -> dict:
    """Rollen-Rechte eines Servers: {role_id(str): {slug: 'view'|'edit'}}."""
    return (role_perms or {}).get(str(guild_id)) or {}


def level_from_roles(role_ids, guild_perms: dict, slug: str) -> int:
    """Höchste Stufe, die eine der Rollen für ``slug`` hat."""
    best = NONE
    for rid in role_ids:
        entry = guild_perms.get(str(rid))
        if entry:
            best = max(best, parse_level(entry.get(slug)))
            if best == EDIT:
                break
    return best


def levels_from_roles(role_ids, guild_perms: dict, slugs) -> dict:
    """{slug: Stufe} für alle ``slugs`` (nur Einträge > NONE)."""
    out = {}
    for slug in slugs:
        lvl = level_from_roles(role_ids, guild_perms, slug)
        if lvl > NONE:
            out[slug] = lvl
    return out


def set_role_level(role_perms: dict, guild_id: int, role_id: int, slug: str, level: int) -> dict:
    """Setzt/entfernt eine Stufe (in-place) und räumt leere Einträge auf."""
    g = role_perms.setdefault(str(guild_id), {})
    r = g.setdefault(str(role_id), {})
    if level > NONE:
        r[slug] = NAME_BY_LEVEL[level]
    else:
        r.pop(slug, None)
    if not r:
        g.pop(str(role_id), None)
    if not g:
        role_perms.pop(str(guild_id), None)
    return role_perms


def configured_guild_ids(role_perms: dict | None) -> set[int]:
    return {int(gid) for gid, roles in (role_perms or {}).items() if roles and str(gid).isdigit()}


def append_audit(entries: list, entry: dict, cap: int = AUDIT_MAX, member_cap: int | None = None) -> list:
    """Neuester Eintrag zuerst, gekappt auf ``cap`` (in-place).

    ``member_cap``: zusätzlich höchstens so viele Einträge mit ``area == "member"``
    behalten (die ältesten fliegen zuerst raus).
    """
    entries.insert(0, entry)
    if member_cap is not None and entry.get("area") == "member":
        seen = 0
        for i in range(len(entries)):
            if entries[i].get("area") == "member":
                seen += 1
                if seen > member_cap:
                    entries[i] = None
        entries[:] = [e for e in entries if e is not None]
    del entries[cap:]
    return entries


def avatar_url(user_id: int, avatar_hash: str | None, size: int = 64) -> str:
    """Discord-CDN-URL des Avatars (Standard-Avatar, wenn keiner gesetzt ist)."""
    if avatar_hash:
        ext = "gif" if str(avatar_hash).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{int(user_id)}/{avatar_hash}.{ext}?size={size}"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(user_id) >> 22) % 6}.png"
