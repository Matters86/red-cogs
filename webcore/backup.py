"""Sichern & Wiederherstellen: Server-Einstellungen aller Cogs mit Dashboard-Seite als JSON.

Format::

    {"format": "red-cogs-backup", "version": 1, "created": "<ISO-8601 UTC>",
     "guild_id": 1000, "guild_name": "…",
     "cogs": {"<CogName>": {"identifier": "<config-identifier>", "guild": {…}, "global": {…}?}}}

* Exportiert wird generisch ``cog.config.guild(guild).all()`` jedes Cogs, der bei WebCore eine
  Dashboard- oder Mitglieder-Seite registriert hat (Owner-Objekt der Seiten).
* Schlüssel mit Secret-Namen (secret, token, password, api_key, key …) werden weder exportiert noch
  importiert – auch nicht verschachtelt.
* Import übernimmt nur Schlüssel, die im Default-Schema des Cogs existieren, und prüft die Typen grob
  gegen den Default (dict/list/bool/Zahl/Text; ``None`` im Default oder im Wert ist immer erlaubt).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

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


async def build_export(webcore, guild, *, include_global: bool = False) -> dict:
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
    return {
        "format": FORMAT,
        "version": VERSION,
        "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "guild_id": guild.id,
        "guild_name": guild.name,
        "cogs": cogs,
    }


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
    plan = {"cogs": [], "missing": [], "has_global": False}
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
