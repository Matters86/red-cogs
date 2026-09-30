"""Server-Layout: Export eines Servers in ein JSON-Layout und strenge Prüfung hochgeladener Layouts.

Reine Logik (nur discord-Enums/Permissions) – Discord-Objekte werden per Duck-Typing gelesen, damit die Tests
mit einfachen Fakes auskommen.

Format (``version`` 1)::

    {"format": "red-serverlayout", "version": 1, "name": "…", "created": "2026-09-30T12:00:00+00:00",
     "creator_id": 1, "source": {"guild_id": 1000, "guild_name": "…", "premium_tier": 2, "community": true},
     "parts": ["roles", "channels", "settings"],
     "everyone": {"permissions": 1071698660929},
     "roles": [{"name", "color", "permissions", "hoist", "mentionable", "managed"}],        # unten -> oben
     "categories": [{"name", "overwrites": [...]}],                                        # Reihenfolge
     "channels": [{"name", "type", "category": <Index in categories>|null, "topic", …, "overwrites": [...]}],
     "settings": {"name", "description", "verification_level", …, "afk_channel": <Kanal-Ref>, "icon": {…}}}

Überschreibungen: ``{"type": "everyone"|"role", "name", "n", "allow", "deny"}`` (Rolle per Name, ``n`` = Nummer
bei gleichnamigen Rollen, von unten gezählt) bzw. ``{"type": "member", "id", "allow", "deny"}`` (nur Info).
Kanal-Referenz: ``{"name", "group", "category", "n"}`` (Gruppe text/voice/stage/forum, Kategorie per Name).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from datetime import datetime, timezone

import discord

FORMAT = "red-serverlayout"
VERSION = 1
PARTS = ("roles", "channels", "settings")
PART_LABELS = {"roles": "Rollen", "channels": "Kanäle", "settings": "Einstellungen"}
PART_LABELS_EN = {"roles": "roles", "channels": "channels", "settings": "settings"}

MAX_FILE_BYTES = 8 * 1024 * 1024          # Upload/Datei
MAX_IMAGE_BYTES = 3 * 1024 * 1024         # je Bild (Icon/Banner) roh
MAX_ROLES = 250                           # Discord-Limit
MAX_CHANNELS = 500                        # Discord-Limit (inkl. Kategorien)
MAX_NAME = 100
MAX_LAYOUT_NAME = 64
MAX_TAGS = 20

ALL_PERMS = discord.Permissions.all().value
PERM_MASK = (1 << 53) - 1                 # JSON-sichere Obergrenze, unbekannte künftige Bits bleiben erhalten

KINDS = ("text", "news", "voice", "stage", "forum")
BUCKET = {"text": 0, "news": 0, "forum": 0, "voice": 2, "stage": 2, "category": 4}
AFK_TIMEOUTS = (60, 300, 900, 1800, 3600)
AUTO_ARCHIVE = (60, 1440, 4320, 10080)


def group_of(kind: str) -> str:
    """Zuordnungs-Gruppe: Text und Ankündigung sind austauschbar (Typ wird ggf. umgestellt)."""
    return "text" if kind in ("text", "news") else kind


def kind_of(channel) -> str | None:
    t = getattr(channel, "type", None)
    CT = discord.ChannelType
    if t == CT.text:
        return "text"
    if t == CT.news:
        return "news"
    if t == CT.voice:
        return "voice"
    if t == CT.stage_voice:
        return "stage"
    if t in (CT.forum, getattr(CT, "media", None)):
        return "forum"
    if t == CT.category:
        return "category"
    return None


def dup_keys(names) -> list[tuple[str, int]]:
    """``["a", "b", "a"]`` -> ``[("a", 0), ("b", 0), ("a", 1)]`` – Nummerierung gleichnamiger Einträge."""
    seen: dict = defaultdict(int)
    out = []
    for n in names:
        out.append((n, seen[n]))
        seen[n] += 1
    return out


def role_key(name: str, n: int) -> str:
    return f"{int(n)}:{name}"


def sorted_roles(guild) -> list:
    """Rollen ohne @everyone, von unten nach oben."""
    return sorted((r for r in guild.roles if not r.is_default()), key=lambda r: (r.position, r.id))


def sorted_categories(guild) -> list:
    return sorted(guild.categories, key=lambda c: (c.position, c.id))


def sorted_channels(guild) -> list:
    """Kanäle (ohne Kategorien/Threads) in Discord-Reihenfolge: Kategorie, Text vor Sprache, Position."""
    cats = {c.id: i for i, c in enumerate(sorted_categories(guild))}
    out = []
    for ch in guild.channels:
        kind = kind_of(ch)
        if kind is None or kind == "category":
            continue
        cat = getattr(ch, "category", None)
        out.append(((cats.get(cat.id, -1) if cat else -1), BUCKET[kind], ch.position, ch.id, ch))
    out.sort(key=lambda t: t[:4])
    return [t[-1] for t in out]


def channel_key(kind: str, name: str, category_name) -> tuple:
    return (group_of(kind), name, category_name)


def target_channel_keys(guild) -> list[tuple[tuple, object]]:
    """[((Gruppe, Name, Kategorie-Name, n), Kanal)] für alle Kanäle des Servers."""
    chans = sorted_channels(guild)
    base = [channel_key(kind_of(c), c.name, c.category.name if getattr(c, "category", None) else None) for c in chans]
    keys = dup_keys(base)
    return [((*k, n), c) for (k, n), c in zip(keys, chans)]


def layout_channel_keys(layout, community: bool = True) -> list[tuple]:
    """Schlüssel der Layout-Kanäle. Ohne Community wird Stage als Sprachkanal angelegt – und so auch zugeordnet."""
    cats = layout.get("categories") or []
    base = []
    for ch in layout.get("channels") or []:
        ci = ch.get("category")
        kind = "voice" if (ch["type"] == "stage" and not community) else ch["type"]
        base.append(channel_key(kind, ch["name"], cats[ci]["name"] if ci is not None else None))
    return [(*k, n) for k, n in dup_keys(base)]


def ref_tuple(ref: dict) -> tuple:
    return (ref["group"], ref["name"], ref.get("category"), int(ref.get("n", 0)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
#  Bilder
# --------------------------------------------------------------------------- #
def image_mime(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_sha(entry: dict | None) -> str:
    import hashlib
    raw = image_bytes(entry)
    return hashlib.sha256(raw).hexdigest()[:32] if raw else ""


def image_bytes(entry: dict | None) -> bytes | None:
    if not entry:
        return None
    try:
        return base64.b64decode(entry["data"], validate=True)
    except (KeyError, ValueError, binascii.Error, TypeError):
        return None


async def _read_asset(asset, notes: list, label: str):
    if asset is None:
        return None
    raw = None
    try:
        raw = await asset.read()
        for size in (1024, 512, 256):
            if len(raw) <= MAX_IMAGE_BYTES:
                break
            raw = await asset.with_size(size).read()
    except Exception as exc:  # noqa: BLE001 – Netzwerk/Discord: Bild weglassen, Rest speichern
        notes.append(f"{label} konnte nicht gelesen werden ({type(exc).__name__}) – nicht gespeichert.")
        return None
    if len(raw) > MAX_IMAGE_BYTES or image_mime(raw) is None:
        notes.append(f"{label} ist zu groß oder kein Bild – nicht gespeichert.")
        return None
    return {"mime": image_mime(raw), "data": base64.b64encode(raw).decode("ascii"),
            "key": str(getattr(asset, "key", "") or ""), "animated": bool(asset.is_animated())}


# --------------------------------------------------------------------------- #
#  Export
# --------------------------------------------------------------------------- #
def _overwrites(target_obj, guild, role_refs: dict) -> list[dict]:
    out = []
    for target, ow in (getattr(target_obj, "overwrites", None) or {}).items():
        allow, deny = ow.pair()
        a, d = int(allow.value), int(deny.value)
        if target.id == guild.id:
            out.append({"type": "everyone", "allow": a, "deny": d})
        elif target.id in role_refs:
            name, n = role_refs[target.id]
            out.append({"type": "role", "name": name, "n": n, "allow": a, "deny": d})
        else:
            out.append({"type": "member", "id": int(target.id), "allow": a, "deny": d})
    out.sort(key=lambda o: ({"everyone": 0, "role": 1, "member": 2}[o["type"]], o.get("name", ""), o.get("n", 0),
                            o.get("id", 0)))
    return out


def _emoji_str(emoji) -> str | None:
    """Nur Unicode-Emojis sind übertragbar (Server-Emojis gibt es auf dem Ziel nicht)."""
    if emoji is None:
        return None
    try:
        if isinstance(emoji, str):
            return emoji or None
        if getattr(emoji, "id", None):
            return None
        name = getattr(emoji, "name", None)
        return name or None
    except Exception:  # noqa: BLE001
        return None


def _enum_val(v, default=0) -> int:
    try:
        return int(getattr(v, "value", v))
    except (TypeError, ValueError):
        return default


def channel_ref(guild, channel) -> dict | None:
    if channel is None:
        return None
    for key, ch in target_channel_keys(guild):
        if ch.id == channel.id:
            return {"group": key[0], "name": key[1], "category": key[2], "n": key[3]}
    return None


async def export_guild(guild, parts, *, name: str, creator_id: int, read_images: bool = True) -> tuple[dict, list]:
    """Liest die gewählten Teile des Servers. Rückgabe ``(layout, hinweise)``."""
    parts = [p for p in PARTS if p in set(parts)]
    notes: list[str] = []
    features = set(getattr(guild, "features", None) or [])
    roles = sorted_roles(guild)
    role_refs = {r.id: k for r, k in zip(roles, dup_keys(r.name for r in roles))}
    data = {
        "format": FORMAT, "version": VERSION, "name": name, "created": _now_iso(), "creator_id": int(creator_id),
        "source": {"guild_id": int(guild.id), "guild_name": str(guild.name),
                   "premium_tier": int(getattr(guild, "premium_tier", 0) or 0), "community": "COMMUNITY" in features},
        "parts": parts,
    }
    if "roles" in parts:
        data["everyone"] = {"permissions": int(guild.default_role.permissions.value)}
        data["roles"] = [{
            "name": r.name, "color": int(getattr(r.colour if hasattr(r, "colour") else r.color, "value", 0)),
            "permissions": int(r.permissions.value), "hoist": bool(r.hoist), "mentionable": bool(r.mentionable),
            "managed": bool(r.managed),
        } for r in roles]
    if "channels" in parts:
        cats = sorted_categories(guild)
        cat_idx = {c.id: i for i, c in enumerate(cats)}
        data["categories"] = [{"name": c.name, "overwrites": _overwrites(c, guild, role_refs)} for c in cats]
        chans = []
        for ch in sorted_channels(guild):
            kind = kind_of(ch)
            cat = getattr(ch, "category", None)
            e = {"name": ch.name, "type": kind, "category": cat_idx.get(cat.id) if cat else None,
                 "nsfw": bool(ch.is_nsfw()) if hasattr(ch, "is_nsfw") else bool(getattr(ch, "nsfw", False)),
                 "synced": bool(getattr(ch, "permissions_synced", False)),
                 "overwrites": _overwrites(ch, guild, role_refs)}
            if kind in ("text", "news", "forum"):
                e["topic"] = getattr(ch, "topic", None) or ""
                e["slowmode"] = int(getattr(ch, "slowmode_delay", 0) or 0)
                e["default_auto_archive"] = int(getattr(ch, "default_auto_archive_duration", 1440) or 1440)
                e["default_thread_slowmode"] = int(getattr(ch, "default_thread_slowmode_delay", 0) or 0)
            if kind in ("voice", "stage"):
                e["bitrate"] = int(getattr(ch, "bitrate", 64000) or 64000)
                e["user_limit"] = int(getattr(ch, "user_limit", 0) or 0)
                region = getattr(ch, "rtc_region", None)
                e["rtc_region"] = str(region) if region else None
                e["video_quality"] = _enum_val(getattr(ch, "video_quality_mode", 1), 1)
            if kind == "forum":
                e["media"] = getattr(ch, "type", None) == getattr(discord.ChannelType, "media", object())
                e["tags"] = [{"name": t.name, "emoji": _emoji_str(t.emoji), "moderated": bool(t.moderated)}
                             for t in (getattr(ch, "available_tags", None) or [])][:MAX_TAGS]
                e["default_layout"] = _enum_val(getattr(ch, "default_layout", 0))
                e["default_sort_order"] = (None if getattr(ch, "default_sort_order", None) is None
                                           else _enum_val(ch.default_sort_order))
                e["default_reaction"] = _emoji_str(getattr(ch, "default_reaction_emoji", None))
            chans.append(e)
        data["channels"] = chans
    if "settings" in parts:
        s = {
            "name": str(guild.name), "description": getattr(guild, "description", None) or "",
            "verification_level": _enum_val(getattr(guild, "verification_level", 0)),
            "explicit_content_filter": _enum_val(getattr(guild, "explicit_content_filter", 0)),
            "default_notifications": _enum_val(getattr(guild, "default_notifications", 0)),
            "afk_timeout": int(getattr(guild, "afk_timeout", 300) or 300),
            "afk_channel": channel_ref(guild, getattr(guild, "afk_channel", None)),
            "system_channel": channel_ref(guild, getattr(guild, "system_channel", None)),
            "system_channel_flags": _enum_val(getattr(guild, "system_channel_flags", 0)),
            "rules_channel": channel_ref(guild, getattr(guild, "rules_channel", None)),
            "public_updates_channel": channel_ref(guild, getattr(guild, "public_updates_channel", None)),
            "icon": None, "banner": None,
        }
        if read_images:
            s["icon"] = await _read_asset(getattr(guild, "icon", None), notes, "Server-Icon")
            s["banner"] = await _read_asset(getattr(guild, "banner", None), notes, "Banner")
        data["settings"] = s
    # Gesamtgröße begrenzen: zuerst Banner, dann Icon weglassen
    for key, label in (("banner", "Banner"), ("icon", "Server-Icon")):
        if len(dump(data)) <= MAX_FILE_BYTES:
            break
        if data.get("settings", {}).get(key):
            data["settings"][key] = None
            notes.append(f"{label} weggelassen (Layout-Datei wäre größer als 8 MB).")
    member_ows = sum(1 for c in data.get("categories", []) + data.get("channels", [])
                     for o in c["overwrites"] if o["type"] == "member")
    if member_ows:
        notes.append(f"{member_ows} Überschreibung(en) für einzelne Mitglieder nur zur Info gespeichert "
                     "(werden beim Laden übersprungen).")
    return data, notes


def dump(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def counts(data: dict) -> dict:
    return {"roles": len(data.get("roles") or []), "categories": len(data.get("categories") or []),
            "channels": len(data.get("channels") or [])}


# --------------------------------------------------------------------------- #
#  Validierung (Upload / Datei) – streng, unbekannte Felder werden ignoriert
# --------------------------------------------------------------------------- #
class LayoutError(ValueError):
    pass


def _str(v, where, *, max_len=MAX_NAME, min_len=1, allow_empty=False) -> str:
    if not isinstance(v, str):
        raise LayoutError(f"{where}: Text erwartet")
    if any(ord(ch) < 32 and ch not in "\n\t\r" for ch in v):
        raise LayoutError(f"{where}: Steuerzeichen nicht erlaubt")
    if (not allow_empty and len(v.strip()) < min_len) or len(v) > max_len:
        raise LayoutError(f"{where}: Länge ungültig (max. {max_len})")
    return v


def _int(v, where, lo, hi) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise LayoutError(f"{where}: Zahl zwischen {lo} und {hi} erwartet")
    return v


def _bool(v, where) -> bool:
    if not isinstance(v, bool):
        raise LayoutError(f"{where}: true/false erwartet")
    return v


def _opt(d: dict, key, default):
    v = d.get(key, default)
    return default if v is None else v


def _ows(lst, where) -> list[dict]:
    if lst is None:
        return []
    if not isinstance(lst, list) or len(lst) > 500:
        raise LayoutError(f"{where}: Liste erwartet")
    out = []
    for i, o in enumerate(lst):
        w = f"{where}[{i}]"
        if not isinstance(o, dict):
            raise LayoutError(f"{w}: Objekt erwartet")
        t = o.get("type")
        allow = _int(o.get("allow", 0), f"{w}.allow", 0, PERM_MASK)
        deny = _int(o.get("deny", 0), f"{w}.deny", 0, PERM_MASK)
        if t == "everyone":
            out.append({"type": "everyone", "allow": allow, "deny": deny})
        elif t == "role":
            out.append({"type": "role", "name": _str(o.get("name"), f"{w}.name"),
                        "n": _int(o.get("n", 0), f"{w}.n", 0, MAX_ROLES), "allow": allow, "deny": deny})
        elif t == "member":
            out.append({"type": "member", "id": _int(o.get("id"), f"{w}.id", 0, 2 ** 64 - 1),
                        "allow": allow, "deny": deny})
        else:
            raise LayoutError(f"{w}.type: everyone/role/member erwartet")
    return out


def _ref(v, where) -> dict | None:
    if v is None:
        return None
    if not isinstance(v, dict):
        raise LayoutError(f"{where}: Kanal-Referenz erwartet")
    group = v.get("group")
    if group not in ("text", "voice", "stage", "forum"):
        raise LayoutError(f"{where}.group ungültig")
    cat = v.get("category")
    return {"group": group, "name": _str(v.get("name"), f"{where}.name"),
            "category": None if cat is None else _str(cat, f"{where}.category"),
            "n": _int(v.get("n", 0), f"{where}.n", 0, MAX_CHANNELS)}


def _image(v, where) -> dict | None:
    if v is None:
        return None
    if not isinstance(v, dict) or not isinstance(v.get("data"), str):
        raise LayoutError(f"{where}: Bild-Objekt erwartet")
    if len(v["data"]) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise LayoutError(f"{where}: Bild zu groß (max. 3 MB)")
    raw = image_bytes(v)
    if raw is None:
        raise LayoutError(f"{where}: kein gültiges base64")
    mime = image_mime(raw)
    if mime is None:
        raise LayoutError(f"{where}: kein PNG/JPEG/GIF/WEBP")
    key = v.get("key") if isinstance(v.get("key"), str) else ""
    return {"mime": mime, "data": v["data"], "key": key[:100],
            "animated": bool(v.get("animated")) if isinstance(v.get("animated"), bool) else mime == "image/gif"}


def validate(obj, *, size: int | None = None) -> dict:
    """Prüft ein geladenes JSON-Objekt und liefert eine bereinigte Kopie (nur bekannte Felder).
    Wirft ``LayoutError`` mit einer deutschen Meldung inkl. Fundstelle."""
    if size is not None and size > MAX_FILE_BYTES:
        raise LayoutError("Datei zu groß (höchstens 8 MB).")
    if not isinstance(obj, dict):
        raise LayoutError("Kein Layout (JSON-Objekt erwartet).")
    if obj.get("format") != FORMAT:
        raise LayoutError("Falsches Format – keine Server-Layout-Datei (format ≠ red-serverlayout).")
    if obj.get("version") != VERSION:
        raise LayoutError(f"Nicht unterstützte Version {obj.get('version')!r} (erwartet {VERSION}).")
    parts = obj.get("parts")
    if not isinstance(parts, list) or not parts or any(p not in PARTS for p in parts):
        raise LayoutError("parts: Liste aus roles/channels/settings erwartet")
    parts = [p for p in PARTS if p in parts]
    src = obj.get("source") if isinstance(obj.get("source"), dict) else {}
    out = {
        "format": FORMAT, "version": VERSION,
        "name": _str(obj.get("name") or "Layout", "name", max_len=200),
        "created": obj.get("created") if isinstance(obj.get("created"), str) and len(obj["created"]) <= 40 else "",
        "creator_id": obj.get("creator_id") if isinstance(obj.get("creator_id"), int)
        and not isinstance(obj.get("creator_id"), bool) and obj["creator_id"] >= 0 else 0,
        "source": {
            "guild_id": src.get("guild_id") if isinstance(src.get("guild_id"), int) and not isinstance(src.get("guild_id"), bool) else 0,
            "guild_name": src.get("guild_name")[:100] if isinstance(src.get("guild_name"), str) else "",
            "premium_tier": src.get("premium_tier") if isinstance(src.get("premium_tier"), int) else 0,
            "community": src.get("community") is True,
        },
        "parts": parts,
    }
    if "roles" in parts:
        ev = obj.get("everyone")
        if not isinstance(ev, dict):
            raise LayoutError("everyone: Objekt erwartet")
        out["everyone"] = {"permissions": _int(ev.get("permissions", 0), "everyone.permissions", 0, PERM_MASK)}
        roles = obj.get("roles")
        if not isinstance(roles, list) or len(roles) > MAX_ROLES:
            raise LayoutError(f"roles: Liste mit höchstens {MAX_ROLES} Einträgen erwartet")
        rl = []
        for i, r in enumerate(roles):
            w = f"roles[{i}]"
            if not isinstance(r, dict):
                raise LayoutError(f"{w}: Objekt erwartet")
            rl.append({
                "name": _str(r.get("name"), f"{w}.name"),
                "color": _int(_opt(r, "color", 0), f"{w}.color", 0, 0xFFFFFF),
                "permissions": _int(_opt(r, "permissions", 0), f"{w}.permissions", 0, PERM_MASK),
                "hoist": _bool(_opt(r, "hoist", False), f"{w}.hoist"),
                "mentionable": _bool(_opt(r, "mentionable", False), f"{w}.mentionable"),
                "managed": _bool(_opt(r, "managed", False), f"{w}.managed"),
            })
        out["roles"] = rl
    if "channels" in parts:
        cats = obj.get("categories")
        chans = obj.get("channels")
        if not isinstance(cats, list) or not isinstance(chans, list):
            raise LayoutError("categories/channels: Listen erwartet")
        if len(cats) + len(chans) > MAX_CHANNELS:
            raise LayoutError(f"Zu viele Kanäle (höchstens {MAX_CHANNELS} inkl. Kategorien).")
        cl = []
        for i, c in enumerate(cats):
            w = f"categories[{i}]"
            if not isinstance(c, dict):
                raise LayoutError(f"{w}: Objekt erwartet")
            cl.append({"name": _str(c.get("name"), f"{w}.name"), "overwrites": _ows(c.get("overwrites"), f"{w}.overwrites")})
        out["categories"] = cl
        chl = []
        for i, c in enumerate(chans):
            w = f"channels[{i}]"
            if not isinstance(c, dict):
                raise LayoutError(f"{w}: Objekt erwartet")
            kind = c.get("type")
            if kind not in KINDS:
                raise LayoutError(f"{w}.type: {'/'.join(KINDS)} erwartet")
            cat = c.get("category")
            if cat is not None:
                _int(cat, f"{w}.category", 0, len(cl) - 1 if cl else -1)
            e = {"name": _str(c.get("name"), f"{w}.name"), "type": kind, "category": cat,
                 "nsfw": _bool(_opt(c, "nsfw", False), f"{w}.nsfw"),
                 "synced": _bool(_opt(c, "synced", False), f"{w}.synced"),
                 "overwrites": _ows(c.get("overwrites"), f"{w}.overwrites")}
            if kind in ("text", "news", "forum"):
                e["topic"] = _str(_opt(c, "topic", ""), f"{w}.topic", max_len=4096 if kind == "forum" else 1024,
                                  allow_empty=True)
                e["slowmode"] = _int(_opt(c, "slowmode", 0), f"{w}.slowmode", 0, 21600)
                aa = _opt(c, "default_auto_archive", 1440)
                e["default_auto_archive"] = aa if aa in AUTO_ARCHIVE else 1440
                e["default_thread_slowmode"] = _int(_opt(c, "default_thread_slowmode", 0),
                                                    f"{w}.default_thread_slowmode", 0, 21600)
            if kind in ("voice", "stage"):
                e["bitrate"] = _int(_opt(c, "bitrate", 64000), f"{w}.bitrate", 8000, 384000)
                e["user_limit"] = _int(_opt(c, "user_limit", 0), f"{w}.user_limit", 0, 10000 if kind == "stage" else 99)
                region = c.get("rtc_region")
                e["rtc_region"] = _str(region, f"{w}.rtc_region", max_len=40) if region is not None else None
                e["video_quality"] = _int(_opt(c, "video_quality", 1), f"{w}.video_quality", 1, 2)
            if kind == "forum":
                e["media"] = c.get("media") is True
                tags = _opt(c, "tags", [])
                if not isinstance(tags, list) or len(tags) > MAX_TAGS:
                    raise LayoutError(f"{w}.tags: höchstens {MAX_TAGS} Tags")
                tl = []
                for j, t in enumerate(tags):
                    if not isinstance(t, dict):
                        raise LayoutError(f"{w}.tags[{j}]: Objekt erwartet")
                    em = t.get("emoji")
                    tl.append({"name": _str(t.get("name"), f"{w}.tags[{j}].name", max_len=20),
                               "emoji": _str(em, f"{w}.tags[{j}].emoji", max_len=32) if em is not None else None,
                               "moderated": _bool(_opt(t, "moderated", False), f"{w}.tags[{j}].moderated")})
                e["tags"] = tl
                e["default_layout"] = _int(_opt(c, "default_layout", 0), f"{w}.default_layout", 0, 2)
                so = c.get("default_sort_order")
                e["default_sort_order"] = None if so is None else _int(so, f"{w}.default_sort_order", 0, 1)
                dr = c.get("default_reaction")
                e["default_reaction"] = _str(dr, f"{w}.default_reaction", max_len=32) if dr is not None else None
            chl.append(e)
        out["channels"] = chl
    if "settings" in parts:
        s = obj.get("settings")
        if not isinstance(s, dict):
            raise LayoutError("settings: Objekt erwartet")
        at = _opt(s, "afk_timeout", 300)
        if at not in AFK_TIMEOUTS:
            raise LayoutError(f"settings.afk_timeout: einer von {AFK_TIMEOUTS}")
        out["settings"] = {
            "name": _str(s.get("name"), "settings.name", min_len=2),
            "description": _str(_opt(s, "description", ""), "settings.description", max_len=120, allow_empty=True),
            "verification_level": _int(_opt(s, "verification_level", 0), "settings.verification_level", 0, 4),
            "explicit_content_filter": _int(_opt(s, "explicit_content_filter", 0), "settings.explicit_content_filter", 0, 2),
            "default_notifications": _int(_opt(s, "default_notifications", 0), "settings.default_notifications", 0, 1),
            "afk_timeout": at,
            "afk_channel": _ref(s.get("afk_channel"), "settings.afk_channel"),
            "system_channel": _ref(s.get("system_channel"), "settings.system_channel"),
            "system_channel_flags": _int(_opt(s, "system_channel_flags", 0), "settings.system_channel_flags", 0, 2 ** 16 - 1),
            "rules_channel": _ref(s.get("rules_channel"), "settings.rules_channel"),
            "public_updates_channel": _ref(s.get("public_updates_channel"), "settings.public_updates_channel"),
            "icon": _image(s.get("icon"), "settings.icon"),
            "banner": _image(s.get("banner"), "settings.banner"),
        }
    return out


def parse_bytes(raw: bytes) -> dict:
    """Upload/Datei -> bereinigtes Layout (``LayoutError`` bei Problemen)."""
    if len(raw) > MAX_FILE_BYTES:
        raise LayoutError("Datei zu groß (höchstens 8 MB).")
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise LayoutError(f"Keine gültige JSON-Datei ({type(exc).__name__}).") from None
    return validate(obj, size=len(raw))


# --------------------------------------------------------------------------- #
#  Rechte-Namen (für Vorschau/Warnungen)
# --------------------------------------------------------------------------- #
PERM_LABELS = {
    "administrator": "Administrator", "manage_guild": "Server verwalten", "manage_roles": "Rollen verwalten",
    "manage_channels": "Kanäle verwalten", "kick_members": "Mitglieder kicken", "ban_members": "Mitglieder bannen",
    "moderate_members": "Timeout", "manage_messages": "Nachrichten verwalten", "manage_webhooks": "Webhooks verwalten",
    "manage_nicknames": "Nicknames verwalten", "manage_expressions": "Emojis/Sticker verwalten",
    "manage_threads": "Threads verwalten", "manage_events": "Events verwalten", "view_audit_log": "Audit-Log ansehen",
    "mention_everyone": "@everyone erwähnen", "view_channel": "Kanal ansehen", "send_messages": "Nachrichten senden",
    "read_message_history": "Verlauf lesen", "embed_links": "Links einbetten", "attach_files": "Dateien anhängen",
    "add_reactions": "Reaktionen", "connect": "Verbinden", "speak": "Sprechen", "stream": "Video",
    "mute_members": "Stummschalten", "deafen_members": "Ein-/Ausgabe sperren", "move_members": "Mitglieder verschieben",
    "priority_speaker": "Very Important Speaker", "create_instant_invite": "Einladung erstellen",
    "change_nickname": "Nickname ändern", "use_application_commands": "Befehle verwenden",
    "create_public_threads": "Öffentliche Threads", "create_private_threads": "Private Threads",
    "send_messages_in_threads": "In Threads schreiben", "external_emojis": "Externe Emojis",
    "external_stickers": "Externe Sticker", "send_tts_messages": "TTS senden", "use_voice_activation": "Sprachaktivierung",
    "request_to_speak": "Redeanfrage", "view_guild_insights": "Server-Einblicke", "send_voice_messages": "Sprachnachrichten",
    "send_polls": "Umfragen erstellen", "use_soundboard": "Soundboard", "use_external_sounds": "Externe Sounds",
    "use_embedded_activities": "Aktivitäten", "create_expressions": "Emojis erstellen", "create_events": "Events erstellen",
    "set_voice_channel_status": "Sprachkanal-Status", "use_external_apps": "Externe Apps", "pin_messages": "Nachrichten anpinnen",
    "bypass_slowmode": "Slowmode umgehen", "view_creator_monetization_analytics": "Monetarisierungs-Einblicke",
}


def perm_names(value: int, limit: int = 8) -> str:
    names = []
    seen = set()
    for flag, bit_value in discord.Permissions.VALID_FLAGS.items():
        if value & bit_value and bit_value not in seen:
            seen.add(bit_value)
            names.append(PERM_LABELS.get(flag, flag))
    rest = value & ~ALL_PERMS
    if rest:
        names.append(f"unbekannte Bits {rest:#x}")
    if len(names) > limit:
        return ", ".join(names[:limit]) + f" (+{len(names) - limit})"
    return ", ".join(names)
