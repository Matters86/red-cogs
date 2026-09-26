"""Sichern & Wiederherstellen: Server-Einstellungen aller Cogs mit Dashboard-Seite als JSON.

Format::

    {"format": "red-cogs-backup", "version": 1, "created": "<ISO-8601 UTC>",
     "guild_id": 1000, "guild_name": "…",
     "cogs": {"<CogName>": {"identifier": "<config-identifier>", "guild": {…}, "global": {…}?}},
     "webcore": {"role_perms": {"<role_id>": {"<slug>": "view"|"operate"|"edit"}}, "member_portal": bool,
                 "audit_channel": <channel_id>|null}?}

* Exportiert wird generisch ``cog.config.guild(guild).all()`` jedes Cogs, der bei WebCore eine
  Dashboard- oder Mitglieder-Seite registriert hat (Owner-Objekt der Seiten).
* Schlüssel mit Secret-Namen (secret, token, password, api_key, key …) werden weder exportiert noch
  importiert – auch nicht verschachtelt.
* Import übernimmt nur Schlüssel, die im Default-Schema des Cogs existieren, und prüft die Typen grob
  gegen den Default (dict/list/bool/Zahl/Text; ``None`` im Default oder im Wert ist immer erlaubt).
* Abschnitt ``webcore`` (optional, nur vom Bot-Owner exportiert/importiert): WebCores eigene Einstellungen
  **nur des gewählten Servers** aus der globalen WebCore-Config – Rollen-Rechte-Matrix (``role_perms``),
  Mitglieder-Bereich an/aus (``member_portal``) und Audit-Kanal (``audit_channels``). Keine anderen
  Server, keine Secrets, keine Allowlist-/Owner-Daten. Beim Import nur mit eigenem Häkchen; Rollen und
  Kanäle, die es auf dem Ziel-Server nicht gibt, ungültige Stufen und unbekannte Seiten werden
  übersprungen und gemeldet.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone

from . import access as acl

FORMAT = "red-cogs-backup"
VERSION = 1
MAX_BYTES = 2 * 1024 * 1024

_SECRET_KEY_RE = re.compile(r"(?i)(secret|token|passw(?:or)?d|passwort|api_?key|apikey|(?:^|[_\-.])key(?:$|[_\-.]))")


def is_secret_key(key) -> bool:
    return bool(_SECRET_KEY_RE.search(str(key)))


def strip_secrets(value):
    """Kopie ohne Schlüssel mit Secret-Namen (rekursiv in dicts und Listen)."""
    if isinstance(value, dict):
        return {k: strip_secrets(v) for k, v in value.items() if not is_secret_key(k)}
    if isinstance(value, list):
        return [strip_secrets(v) for v in value]
    return value


def backup_cogs(webcore) -> dict:
    """{CogName: cog} aller Cogs mit registrierter Seite und Red-``Config``."""
    out = {}
    owners = [p.owner for p in list(webcore.pages.values()) + list(webcore.member_pages.values())]
    for owner in owners:
        if owner is webcore:
            continue
        config = getattr(owner, "config", None)
        if config is None or not hasattr(config, "guild") or not hasattr(config, "defaults"):
            continue
        name = getattr(owner, "qualified_name", None) or type(owner).__name__
        out.setdefault(str(name), owner)
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def _defaults(config, scope: str) -> dict:
    try:
        return dict((config.defaults or {}).get(scope) or {})
    except Exception:  # noqa: BLE001
        return {}


def guild_defaults(config) -> dict:
    return _defaults(config, "GUILD")


def global_defaults(config) -> dict:
    return _defaults(config, "GLOBAL")


def identifier_of(config) -> str:
    return str(getattr(config, "unique_identifier", "") or "")


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


async def webcore_section(webcore, guild) -> dict:
    """WebCores eigene Einstellungen nur für ``guild`` (Rollen-Rechte, Mitglieder-Bereich, Audit-Kanal)."""
    gid = str(guild.id)
    data = await webcore.config.all()
    perms = (data.get("role_perms") or {}).get(gid) or {}
    cid = (data.get("audit_channels") or {}).get(gid)
    return {
        "role_perms": {str(rid): {str(slug): str(lvl) for slug, lvl in entry.items()}
                       for rid, entry in perms.items() if isinstance(entry, dict) and entry},
        "member_portal": bool((data.get("member_portal") or {}).get(gid)),
        "audit_channel": int(cid) if str(cid or "").isdigit() else None,
    }


async def build_export(webcore, guild, *, include_global: bool = False, include_webcore: bool = False) -> dict:
    cogs = {}
    for name, cog in backup_cogs(webcore).items():
        cfg = cog.config
        entry = {"identifier": identifier_of(cfg)}
        if guild_defaults(cfg):
            entry["guild"] = strip_secrets(_jsonable(await cfg.guild(guild).all()))
        if include_global and global_defaults(cfg):
            entry["global"] = strip_secrets(_jsonable(await cfg.all()))
        if "guild" in entry or "global" in entry:
            cogs[name] = entry
    out = {
        "format": FORMAT,
        "version": VERSION,
        "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "guild_id": guild.id,
        "guild_name": guild.name,
        "cogs": cogs,
    }
    if include_webcore:
        out["webcore"] = await webcore_section(webcore, guild)
    return out


def parse_backup(raw: bytes) -> dict:
    """Datei prüfen und laden. Wirft ``ValueError`` mit deutscher Meldung."""
    if len(raw) > MAX_BYTES:
        raise ValueError("Datei zu groß (höchstens 2 MB).")
    if not raw.strip():
        raise ValueError("Die Datei ist leer.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Keine gültige JSON-Datei.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("Das ist keine Sicherung aus „Sichern & Wiederherstellen“ (format fehlt).")
    if data.get("version") != VERSION:
        raise ValueError(f"Nicht unterstützte Version der Sicherung ({data.get('version')!r}).")
    if not isinstance(data.get("cogs"), dict):
        raise ValueError("Die Sicherung enthält keine Cog-Einstellungen.")
    return data


def merge_secrets(current, incoming):
    """Verschachtelte Secret-Schlüssel des Ist-Zustands behalten (die Sicherung enthält sie nie)."""
    if isinstance(current, dict) and isinstance(incoming, dict):
        out = {k: merge_secrets(current.get(k), v) if isinstance(v, dict) else v for k, v in incoming.items()}
        for k, v in current.items():
            if is_secret_key(k) and k not in out:
                out[k] = v
        return out
    return incoming


def _type_ok(default, value) -> bool:
    if default is None or value is None:
        return True
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list)
    if isinstance(default, dict):
        return isinstance(value, dict)
    return True


def _type_name(value) -> str:
    if value is None:
        return "leer"
    if isinstance(value, bool):
        return "Ja/Nein"
    if isinstance(value, (int, float)):
        return "Zahl"
    if isinstance(value, str):
        return "Text"
    if isinstance(value, list):
        return "Liste"
    if isinstance(value, dict):
        return "Objekt"
    return type(value).__name__


def _check_scope(defaults: dict, current: dict, incoming) -> dict:
    """Vergleicht einen Bereich (guild/global). Ergebnis: changed/same/unknown/type_errors/secret/values."""
    res = {"changed": [], "same": [], "unknown": [], "type_errors": [], "secret": [], "values": {}}
    if not isinstance(incoming, dict):
        res["type_errors"].append(("(Bereich)", "Objekt", _type_name(incoming)))
        return res
    for key, value in incoming.items():
        key = str(key)
        if key not in defaults:
            res["unknown"].append(key)
            continue
        if is_secret_key(key):
            res["secret"].append(key)
            continue
        if not _type_ok(defaults[key], value):
            res["type_errors"].append((key, _type_name(defaults[key]), _type_name(value)))
            continue
        clean = merge_secrets(current.get(key), strip_secrets(value))
        res["values"][key] = clean
        if current.get(key) == clean:
            res["same"].append(key)
        else:
            res["changed"].append(key)
    return res


async def plan_import(webcore, guild, data: dict) -> dict:
    """Vorschau: was würde der Import auf ``guild`` ändern? (schreibt nichts)"""
    loaded = backup_cogs(webcore)
    plan = {"cogs": [], "missing": [], "has_global": False, "webcore": None}
    if "webcore" in data:
        plan["webcore"] = await plan_webcore(webcore, guild, data.get("webcore"),
                                             same_guild=str(data.get("guild_id")) == str(guild.id))
    for name, entry in sorted((data.get("cogs") or {}).items(), key=lambda kv: str(kv[0]).lower()):
        name = str(name)
        cog = loaded.get(name)
        if cog is None:
            plan["missing"].append(name)
            continue
        if not isinstance(entry, dict):
            plan["cogs"].append({"name": name, "status": "invalid", "guild": None, "global": None})
            continue
        cfg = cog.config
        ident = str(entry.get("identifier") or "")
        if ident and ident != identifier_of(cfg):
            plan["cogs"].append({"name": name, "status": "identifier", "guild": None, "global": None})
            continue
        item = {"name": name, "status": "ok", "guild": None, "global": None}
        if "guild" in entry:
            item["guild"] = _check_scope(guild_defaults(cfg), await cfg.guild(guild).all(), entry.get("guild"))
        if "global" in entry:
            item["global"] = _check_scope(global_defaults(cfg), await cfg.all(), entry.get("global"))
            plan["has_global"] = True
        plan["cogs"].append(item)
    return plan


def plan_totals(plan: dict, *, include_global: bool) -> dict:
    t = {"changed": 0, "unknown": 0, "type_errors": 0, "secret": 0, "cogs": 0}
    for item in plan["cogs"]:
        scopes = [item.get("guild")] + ([item.get("global")] if include_global else [])
        touched = False
        for sc in scopes:
            if not sc:
                continue
            t["changed"] += len(sc["changed"])
            t["unknown"] += len(sc["unknown"])
            t["type_errors"] += len(sc["type_errors"])
            t["secret"] += len(sc["secret"])
            touched = touched or bool(sc["changed"])
        t["cogs"] += int(touched)
    return t


async def apply_import(webcore, guild, plan: dict, *, include_global: bool) -> dict:
    """Übernimmt die geänderten Schlüssel. Gibt den Ist-Zustand davor zurück (für „Rückgängig“):
    ``{CogName: {"guild": {key: alt}, "global": {key: alt}}}``."""
    loaded = backup_cogs(webcore)
    snapshot = {}
    for item in plan["cogs"]:
        cog = loaded.get(item["name"])
        if cog is None or item.get("status") != "ok":
            continue
        cfg = cog.config
        snap = {}
        g = item.get("guild")
        if g and g["changed"]:
            group = cfg.guild(guild)
            current = await group.all()
            snap["guild"] = {k: current.get(k) for k in g["changed"]}
            for key in g["changed"]:
                await group.set_raw(key, value=g["values"][key])
        gl = item.get("global")
        if include_global and gl and gl["changed"]:
            current = await cfg.all()
            snap["global"] = {k: current.get(k) for k in gl["changed"]}
            for key in gl["changed"]:
                await cfg.set_raw(key, value=gl["values"][key])
        if snap:
            snapshot[item["name"]] = snap
    return snapshot


async def restore_snapshot(webcore, guild, snapshot: dict) -> tuple[int, list]:
    """Stellt einen mit ``apply_import`` gesicherten Zustand wieder her. -> (Schlüssel, fehlende Cogs)."""
    loaded = backup_cogs(webcore)
    count, missing = 0, []
    for name, snap in snapshot.items():
        cog = loaded.get(name)
        if cog is None:
            missing.append(name)
            continue
        cfg = cog.config
        for key, value in (snap.get("guild") or {}).items():
            await cfg.guild(guild).set_raw(key, value=value)
            count += 1
        for key, value in (snap.get("global") or {}).items():
            await cfg.set_raw(key, value=value)
            count += 1
    return count, missing


# --------------------------------------------------------------------------- #
#  Abschnitt „webcore“: Rollen-Rechte, Mitglieder-Bereich, Audit-Kanal (nur Owner)
# --------------------------------------------------------------------------- #
def _channel_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def known_slugs(webcore, role_perms_all: dict) -> set:
    """Registrierte Dashboard-Seiten plus Seiten, für die schon Rechte gespeichert sind
    (Cogs, die gerade nicht geladen sind – deren Rechte bleiben erhalten wie auf „Zugriff & Rollen“)."""
    known = {str(s) for s in webcore.pages}
    for gperms in (role_perms_all or {}).values():
        for entry in (gperms or {}).values() if isinstance(gperms, dict) else ():
            if isinstance(entry, dict):
                known.update(str(s) for s in entry)
    return known


async def plan_webcore(webcore, guild, section, *, same_guild: bool) -> dict:
    """Vorschau für den Abschnitt ``webcore`` (schreibt nichts).

    Rollen-Rechte: Rollen aus der Sicherung bekommen genau die dort gespeicherten Stufen. Auf demselben
    Server wird die Matrix vollständig auf den Stand der Sicherung gesetzt (Rollen, die dort fehlen,
    verlieren ihre Rechte); auf einem anderen Server bleiben Rollen, die nicht in der Sicherung stehen,
    unverändert. Rollen, die es auf dem Ziel-Server nicht gibt, ungültige Stufen (nur ``none``/``view``/
    ``operate``/``edit``) und unbekannte Seiten werden übersprungen und gemeldet; bei einer ungültigen Stufe bleibt
    der bisherige Wert dieser Seite erhalten.
    """
    gid = str(guild.id)
    data = await webcore.config.all()
    rp_all = data.get("role_perms") or {}
    current = {str(k): dict(v) for k, v in (rp_all.get(gid) or {}).items() if isinstance(v, dict)}
    res = {
        "errors": [], "skipped_roles": [], "invalid_levels": [], "unknown_slugs": [],
        "roles": [], "role_perms": None, "role_perms_changed": False,
        "portal": None, "audit_channel": None, "skipped_channel": None, "changes": 0, "same_guild": same_guild,
    }
    if not isinstance(section, dict):
        res["errors"].append(f"Abschnitt „webcore“: Objekt erwartet, {_type_name(section)}")
        return res

    if "role_perms" in section:
        rp = section.get("role_perms")
        if not isinstance(rp, dict):
            res["errors"].append(f"role_perms: Objekt erwartet, {_type_name(rp)}")
        else:
            known = known_slugs(webcore, rp_all)
            incoming = {}
            for rid, entry in rp.items():
                rid = str(rid)
                role = guild.get_role(int(rid)) if rid.isdigit() else None
                if role is None or role.is_default():
                    res["skipped_roles"].append(rid)
                    continue
                if not isinstance(entry, dict):
                    res["invalid_levels"].append((role.name, "(Rolle)", _type_name(entry)))
                    continue
                clean = {}
                for slug, lvl in entry.items():
                    slug = str(slug)
                    if slug not in known:
                        if slug not in res["unknown_slugs"]:
                            res["unknown_slugs"].append(slug)
                        continue
                    name = lvl.strip().lower() if isinstance(lvl, str) else None
                    if name not in acl.LEVEL_BY_NAME:
                        res["invalid_levels"].append((role.name, slug, str(lvl)[:20]))
                        old = (current.get(rid) or {}).get(slug)
                        if old is not None:
                            clean[slug] = old
                        continue
                    level = acl.LEVEL_BY_NAME[name]
                    if level > acl.NONE:
                        clean[slug] = acl.NAME_BY_LEVEL[level]
                incoming[rid] = clean
            new = {} if same_guild else copy.deepcopy(current)
            for rid, entry in incoming.items():
                if entry:
                    new[rid] = entry
                else:
                    new.pop(rid, None)
            roles = {rid: (guild.get_role(int(rid)) if rid.isdigit() else None) for rid in set(current) | set(new)}
            for rid in sorted(roles, key=lambda r: (roles[r] is None, roles[r].name.lower() if roles[r] else r)):
                old_e, new_e = current.get(rid) or {}, new.get(rid) or {}
                if old_e == new_e:
                    continue
                role = roles[rid]
                gain = sorted(s for s in new_e if s not in old_e)
                lose = sorted(s for s in old_e if s not in new_e)
                change = sorted(s for s in new_e if s in old_e and old_e[s] != new_e[s])
                res["roles"].append({
                    "id": rid, "name": role.name if role else f"gelöschte Rolle ({rid})",
                    "gain": [(s, new_e[s]) for s in gain], "lose": [(s, old_e[s]) for s in lose],
                    "change": [(s, old_e[s], new_e[s]) for s in change],
                })
            res["role_perms"] = new
            res["role_perms_changed"] = new != current

    if "member_portal" in section:
        val = section.get("member_portal")
        old = bool((data.get("member_portal") or {}).get(gid))
        if not isinstance(val, bool):
            res["errors"].append(f"member_portal: Ja/Nein erwartet, {_type_name(val)}")
        else:
            res["portal"] = {"old": old, "new": val, "changed": old != val}

    if "audit_channel" in section:
        val = section.get("audit_channel")
        old = _channel_id((data.get("audit_channels") or {}).get(gid))

        def _name(cid):
            ch = guild.get_channel(cid) if cid else None
            return ch.name if ch is not None else None

        new, valid = None, False
        if val is None:
            valid = True
        elif _channel_id(val) is None:
            res["errors"].append(f"audit_channel: Kanal-ID erwartet, {_type_name(val)}")
        else:
            ch = next((c for c in guild.text_channels if c.id == _channel_id(val)), None)
            if ch is None:
                res["skipped_channel"] = _channel_id(val)
            else:
                new, valid = ch.id, True
        if valid:
            res["audit_channel"] = {"old": old, "new": new, "changed": old != new,
                                    "old_name": _name(old), "new_name": _name(new)}

    res["changes"] = (len(res["roles"]) + int(bool(res["portal"] and res["portal"]["changed"]))
                      + int(bool(res["audit_channel"] and res["audit_channel"]["changed"])))
    return res


def webcore_problems(wplan: dict | None) -> int:
    """Anzahl übersprungener/ungültiger Einträge im Abschnitt ``webcore``."""
    if not wplan:
        return 0
    return (len(wplan["errors"]) + len(wplan["skipped_roles"]) + len(wplan["invalid_levels"])
            + len(wplan["unknown_slugs"]) + int(wplan["skipped_channel"] is not None))


async def apply_webcore(webcore, guild, wplan: dict) -> dict:
    """Übernimmt den Abschnitt ``webcore``. Gibt den Ist-Zustand davor zurück (nur geänderte Teile):
    ``{"role_perms": {…}, "member_portal": bool, "audit_channel": id|None}``."""
    gid = str(guild.id)
    snap = {}
    if wplan.get("role_perms_changed"):
        async with webcore.config.role_perms() as rp:
            snap["role_perms"] = copy.deepcopy(rp.get(gid) or {})
            if wplan["role_perms"]:
                rp[gid] = copy.deepcopy(wplan["role_perms"])
            else:
                rp.pop(gid, None)
    portal = wplan.get("portal")
    if portal and portal["changed"]:
        async with webcore.config.member_portal() as mp:
            snap["member_portal"] = bool(mp.get(gid))
            if portal["new"]:
                mp[gid] = True
            else:
                mp.pop(gid, None)
    chan = wplan.get("audit_channel")
    if chan and chan["changed"]:
        async with webcore.config.audit_channels() as ac:
            snap["audit_channel"] = _channel_id(ac.get(gid))
            if chan["new"]:
                ac[gid] = int(chan["new"])
            else:
                ac.pop(gid, None)
    if snap:
        snap["changes"] = wplan.get("changes", 0)
    return snap


async def restore_webcore(webcore, guild, snap: dict) -> int:
    """Stellt einen mit ``apply_webcore`` gesicherten Stand wieder her. -> Anzahl Teile."""
    gid = str(guild.id)
    count = 0
    if "role_perms" in snap:
        async with webcore.config.role_perms() as rp:
            if snap["role_perms"]:
                rp[gid] = copy.deepcopy(snap["role_perms"])
            else:
                rp.pop(gid, None)
        count += 1
    if "member_portal" in snap:
        async with webcore.config.member_portal() as mp:
            if snap["member_portal"]:
                mp[gid] = True
            else:
                mp.pop(gid, None)
        count += 1
    if "audit_channel" in snap:
        async with webcore.config.audit_channels() as ac:
            if snap["audit_channel"]:
                ac[gid] = int(snap["audit_channel"])
            else:
                ac.pop(gid, None)
        count += 1
    return count
