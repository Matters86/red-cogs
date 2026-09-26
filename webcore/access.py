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

* ``view``  – Seite öffnen und alles ansehen, aber nichts speichern.
* ``edit``  – ansehen und speichern (alle Formulare der Seite).
* fehlt     – kein Zugriff, die Seite erscheint nicht in der Navigation.

Hat ein Mitglied mehrere Rollen, gilt die höchste Stufe je Seite.
Bot-Owner und Allowlist haben immer überall ``edit``; im Zugriffsmodus
``admin`` haben Discord-Administratoren eines Servers dort ebenfalls ``edit``.
"""

from __future__ import annotations

NONE = 0
VIEW = 1
EDIT = 2

LEVEL_BY_NAME = {"none": NONE, "view": VIEW, "edit": EDIT}
NAME_BY_LEVEL = {NONE: "none", VIEW: "view", EDIT: "edit"}
LEVEL_LABEL = {NONE: "Kein Zugriff", VIEW: "Ansehen", EDIT: "Bearbeiten"}

AUDIT_MAX = 300
# Höchstens so viele Einträge aus dem Mitglieder-Bereich im Audit-Log, damit viele
# Mitglieder-Aktionen die Team-/Owner-Einträge nicht verdrängen.
MEMBER_AUDIT_MAX = 150


def parse_level(value) -> int:
    """'view'/'edit'/'none' (oder 0/1/2) -> Stufe; Unbekanntes = kein Zugriff."""
    if isinstance(value, int) and value in NAME_BY_LEVEL:
        return value
    return LEVEL_BY_NAME.get(str(value or "").strip().lower(), NONE)


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
