"""Server-Layout: Vorschau/Plan – vergleicht ein Layout mit dem Ziel-Server.

``build_plan`` liefert alles, was die Vorschau zeigt, und zugleich die Arbeitsliste für ``executor``:

* ``items``: ``{"sec", "op", "label", "details", "reason", "do"}`` – ``sec`` roles/categories/channels/settings/order,
  ``op`` create/update/delete/skip, ``do`` die Nutzdaten für die Ausführung (JSON-fähig).
* ``warnings`` (gelb), ``blockers`` (rot – Anwenden gesperrt), ``counts`` und ``hash`` (Plan-Fingerabdruck:
  ändert sich der Server zwischen Vorschau und Bestätigung, passt er nicht mehr).

Zuordnung per Name: Rollen per Name (gleichnamige in Reihenfolge von unten), Kategorien per Name,
Kanäle per Name + Typ-Gruppe (Text/Ankündigung zusammen) + Kategorie-Name.
"""

from __future__ import annotations

import hashlib
import json

from . import layout as L

MODES = ("merge", "exact")
MODE_LABELS = {"merge": "Ergänzen", "exact": "Exakt angleichen"}
MODE_LABELS_EN = {"merge": "merge", "exact": "exact sync"}

KIND_LABELS = {"text": "Text", "news": "Ankündigung", "voice": "Sprache", "stage": "Stage", "forum": "Forum",
               "category": "Kategorie"}
VERIFY = ["keine", "niedrig", "mittel", "hoch", "sehr hoch"]
FILTER = ["aus", "Mitglieder ohne Rollen", "alle Mitglieder"]
NOTIFY = ["alle Nachrichten", "nur Erwähnungen"]


def _hex(c: int) -> str:
    return f"#{int(c):06x}"


def _onoff(v) -> str:
    return "an" if v else "aus"


def bot_caps(guild) -> dict:
    me = guild.me
    perms = me.guild_permissions
    admin = bool(perms.administrator)
    top = me.top_role.position if getattr(me, "top_role", None) is not None else 0
    return {
        "admin": admin, "grant": L.PERM_MASK if admin else int(perms.value), "top": top,
        "role_ids": {r.id for r in getattr(me, "roles", [])},
        "manage_roles": bool(perms.manage_roles), "manage_channels": bool(perms.manage_channels),
        "manage_guild": bool(perms.manage_guild),
    }


def merge_perms(desired: int, current: int, grant: int) -> tuple[int, int]:
    """Gewünschte Rechte, soweit der Bot sie vergeben kann; nicht steuerbare Bits bleiben wie sie sind.
    Rückgabe ``(neu, nicht_setzbar)`` – ``nicht_setzbar`` = Bits, die anders bleiben als gewünscht."""
    new = (desired & grant) | (current & ~grant)
    return new, (desired ^ new)


def channel_manageable(channel, me) -> bool:
    try:
        p = channel.permissions_for(me)
        return bool(p.manage_channels and p.view_channel)
    except Exception:  # noqa: BLE001
        return True


def _perm_diff(old: int, new: int) -> str:
    plus, minus = new & ~old, old & ~new
    out = []
    if plus:
        out.append("+ " + L.perm_names(plus))
    if minus:
        out.append("− " + L.perm_names(minus))
    return "; ".join(out)


# --------------------------------------------------------------------------- #
#  Rollen-Reihenfolge (auch vom Executor benutzt)
# --------------------------------------------------------------------------- #
def role_sequence(current: list, wanted: list, top: int, new_ids=()) -> tuple[list, list]:
    """``current``: [(id, position)] aller Rollen ohne @everyone; ``wanted``: Rollen-IDs in Layout-Reihenfolge
    (unten -> oben); ``new_ids``: gerade angelegte Rollen. Nur Rollen unterhalb der höchsten Bot-Rolle werden
    umsortiert. Rollen, die nicht im Layout stehen, bleiben direkt über der (vorher schon vorhandenen)
    Layout-Rolle, über der sie bisher lagen – ohne solche ganz unten. Rückgabe ``(alt, neu)`` – beide unten -> oben."""
    movable = [rid for rid, pos in sorted(current, key=lambda t: (t[1], str(t[0]))) if pos < top]
    mset = set(movable)
    wset = set(wanted)
    new_ids = set(new_ids)
    anchor: dict = {}
    last = None
    for rid in movable:
        if rid in wset:
            if rid not in new_ids:
                last = rid
        else:
            anchor[rid] = last
    ordered = [rid for rid in wanted if rid in mset]
    new = [rid for rid in movable if rid not in wset and anchor[rid] is None]
    for rid in ordered:
        new.append(rid)
        new.extend(u for u in movable if u not in wset and anchor[u] == rid)
    return movable, new


def role_order(current: list, wanted: list, top: int, new_ids=()) -> dict:
    """{id: neue Position} (1 = direkt über @everyone) nur für Rollen, deren Position sich ändert."""
    old, new = role_sequence(current, wanted, top, new_ids)
    if old == new:
        return {}                 # Reihenfolge stimmt (Lücken in den Positionen sind egal)
    cur_pos = dict(current)
    return {rid: i + 1 for i, rid in enumerate(new) if cur_pos.get(rid) != i + 1}


def channel_order(groups: dict, wanted: list) -> dict:
    """``groups``: {(parent, bucket): [(id, position)]}; ``wanted``: Kanal-IDs in Layout-Reihenfolge.
    Innerhalb jeder Gruppe werden die Layout-Kanäle in Layout-Reihenfolge auf ihre Plätze gesetzt.
    Rückgabe: {id: neue Position} nur für geänderte Kanäle."""
    rank = {cid: i for i, cid in enumerate(wanted)}
    out = {}
    for items in groups.values():
        cur = [cid for cid, pos in sorted(items, key=lambda t: (t[1], t[0]))]
        cur_pos = dict(items)
        slots = [i for i, cid in enumerate(cur) if cid in rank]
        ordered = sorted((cid for cid in cur if cid in rank), key=lambda c: rank[c])
        new = list(cur)
        for slot, cid in zip(slots, ordered):
            new[slot] = cid
        if new == cur:
            continue              # Reihenfolge stimmt (Lücken nach Löschungen sind egal)
        for i, cid in enumerate(new):
            if cur_pos.get(cid) != i:
                out[cid] = i
    return out


def channel_groups(guild) -> dict:
    groups: dict = {}
    for ch in guild.channels:
        kind = L.kind_of(ch)
        if kind is None:
            continue
        parent = None if kind == "category" else (ch.category.id if getattr(ch, "category", None) else None)
        groups.setdefault((parent, L.BUCKET[kind]), []).append((ch.id, ch.position))
    return groups


# --------------------------------------------------------------------------- #
#  Überschreibungen
# --------------------------------------------------------------------------- #
def current_overwrites(obj, guild, role_ids: set) -> dict:
    out = {}
    for target, ow in (getattr(obj, "overwrites", None) or {}).items():
        allow, deny = ow.pair()
        kind = "role" if (target.id in role_ids or target.id == guild.id) else "member"
        out[(kind, int(target.id))] = (int(allow.value), int(deny.value))
    return out


def plan_overwrites(entry_ows: list, current: dict, ctx: dict, mode: str, where: str) -> tuple[dict, list, int]:
    """Ziel-Überschreibungen für einen Kanal/eine Kategorie.

    Rückgabe ``(final, hinweise, mitglieder_übersprungen)``; ``final`` = {(art, id): (allow, deny)} mit art
    role/member/new (new = Rolle, die erst angelegt wird; id = Layout-Index)."""
    grant = ctx["caps"]["grant"]
    desired: dict = {}
    notes: list[str] = []
    members = 0
    for o in entry_ows:
        if o["type"] == "member":
            members += 1
            continue
        if o["type"] == "everyone":
            key = ("role", ctx["guild"].id)
        else:
            ref = ctx["rolemap"].get(L.role_key(o["name"], o["n"]))
            if ref is None:
                notes.append(f"Rolle „{o['name']}“ fehlt auf dem Ziel-Server")
                continue
            key = tuple(ref)
        cur = current.get(key, (0, 0))
        a, miss_a = merge_perms(o["allow"], cur[0], grant)
        d, miss_d = merge_perms(o["deny"], cur[1], grant)
        if miss_a | miss_d:
            ctx["ungrantable"].setdefault(where, 0)
            ctx["ungrantable"][where] |= (miss_a | miss_d)
        desired[key] = (a, d)
    if mode == "merge":
        final = dict(current)
        final.update(desired)
    else:
        final = dict(desired)
        for key, val in current.items():
            if key in final:
                continue
            if key[0] == "member":
                final[key] = val          # Mitglieder-Überschreibungen des Ziels bleiben
            elif key[1] in ctx["managed_ids"]:
                final[key] = val          # verwaltete Rollen (Bots/Integrationen) nie anfassen
    return final, notes, members


def _ow_label(key, ctx) -> str:
    kind, rid = key
    if kind == "new":
        return f"{ctx['layout']['roles'][rid]['name']} (neu)"
    if kind == "member":
        m = ctx["guild"].get_member(rid) if hasattr(ctx["guild"], "get_member") else None
        return f"Mitglied {getattr(m, 'display_name', rid)}"
    if rid == ctx["guild"].id:
        return "@everyone"
    r = ctx["guild"].get_role(rid)
    return r.name if r is not None else str(rid)


def ow_diff(current: dict, final: dict, ctx) -> str:
    added = [k for k in final if k not in current]
    removed = [k for k in current if k not in final]
    changed = [k for k in final if k in current and final[k] != current[k]]
    parts = []
    if added:
        parts.append("+ " + ", ".join(_ow_label(k, ctx) for k in added[:6]) + (" …" if len(added) > 6 else ""))
    if changed:
        parts.append("~ " + ", ".join(_ow_label(k, ctx) for k in changed[:6]) + (" …" if len(changed) > 6 else ""))
    if removed:
        parts.append("− " + ", ".join(_ow_label(k, ctx) for k in removed[:6]) + (" …" if len(removed) > 6 else ""))
    return "Überschreibungen: " + "; ".join(parts) if parts else ""


def _ow_json(final: dict) -> list:
    return sorted([[k[0], k[1], v[0], v[1]] for k, v in final.items()])


# --------------------------------------------------------------------------- #
#  Plan
# --------------------------------------------------------------------------- #
def build_plan(layout: dict, guild, *, mode: str = "merge", parts=None, protect_channel_id: int | None = None,
               image_state: dict | None = None) -> dict:
    """``image_state``: {"icon"/"banner": {"sha", "key"}} – zuletzt per Layout gesetzte Bilder dieses Servers
    (damit ein erneutes Laden dasselbe Bild nicht wieder hochlädt)."""
    mode = mode if mode in MODES else "merge"
    parts = [p for p in L.PARTS if p in set(parts or L.PARTS)]
    caps = bot_caps(guild)
    features = set(getattr(guild, "features", None) or [])
    community = "COMMUNITY" in features
    items: list = []
    warnings: list = []
    blockers: list = []
    missing = [lbl for ok, lbl in ((caps["manage_roles"], "Rollen verwalten"), (caps["manage_channels"], "Kanäle verwalten"),
                                   (caps["manage_guild"], "Server verwalten")) if not ok]
    if missing:
        blockers.append("Dem Bot fehlen auf diesem Server die Rechte: " + ", ".join(missing) + ".")
    for p in parts:
        if p not in layout.get("parts", []):
            warnings.append(f"Das Layout enthält keine {L.PART_LABELS[p]} – dieser Teil wird übersprungen.")
    parts = [p for p in parts if p in layout.get("parts", [])]

    def add(sec, op, label, details=None, reason=None, do=None):
        items.append({"sec": sec, "op": op, "label": label, "details": [d for d in (details or []) if d],
                      "reason": reason, "do": do or {}})

    # --- Rollen-Zuordnung (immer – Überschreibungen brauchen sie) ---------------------------------------
    troles = L.sorted_roles(guild)
    tmap = dict(zip(L.dup_keys(r.name for r in troles), troles))
    lroles = layout.get("roles") or []
    rolemap: dict = {}
    managed_ids = {r.id for r in troles if r.managed}
    matched_role_ids = set()
    ctx = {"guild": guild, "caps": caps, "rolemap": rolemap, "layout": layout, "ungrantable": {},
           "managed_ids": managed_ids}
    role_creates = role_deletes = 0
    order_wanted: list = []
    above: list = []
    if lroles:
        for i, (lr, key) in enumerate(zip(lroles, L.dup_keys(r["name"] for r in lroles))):
            t = tmap.get(key)
            rk = L.role_key(*key)
            if t is not None:
                rolemap[rk] = ("role", t.id)
                matched_role_ids.add(t.id)
                order_wanted.append(("role", t.id))
            if "roles" not in parts:
                continue
            if lr["managed"]:
                if t is None:
                    add("roles", "skip", lr["name"], reason="verwaltete Rolle (Bot/Integration/Booster) – wird nie angelegt")
                continue
            if t is None:
                rolemap[rk] = ("new", i)
                order_wanted.append(("new", i))
                perms, miss = merge_perms(lr["permissions"], 0, caps["grant"])
                if miss:
                    ctx["ungrantable"][f"Rolle „{lr['name']}“"] = miss
                role_creates += 1
                add("roles", "create", lr["name"],
                    [f"Farbe {_hex(lr['color'])}", f"Rechte: {L.perm_names(perms) or 'keine'}",
                     "hervorgehoben" if lr["hoist"] else "", "erwähnbar" if lr["mentionable"] else ""],
                    do={"a": "role_create", "idx": i, "key": rk, "name": lr["name"], "color": lr["color"],
                        "permissions": perms, "hoist": lr["hoist"], "mentionable": lr["mentionable"]})
                continue
            fields, det = {}, []
            cur_color = int(getattr(getattr(t, "colour", None) or t.color, "value", 0))
            if cur_color != lr["color"]:
                fields["color"] = lr["color"]
                det.append(f"Farbe {_hex(cur_color)} → {_hex(lr['color'])}")
            cur_perms = int(t.permissions.value)
            new_perms, miss = merge_perms(lr["permissions"], cur_perms, caps["grant"])
            if new_perms != cur_perms:
                fields["permissions"] = new_perms
                det.append("Rechte: " + _perm_diff(cur_perms, new_perms))
            if bool(t.hoist) != lr["hoist"]:
                fields["hoist"] = lr["hoist"]
                det.append(f"Hervorheben {_onoff(t.hoist)} → {_onoff(lr['hoist'])}")
            if bool(t.mentionable) != lr["mentionable"]:
                fields["mentionable"] = lr["mentionable"]
                det.append(f"Erwähnbar {_onoff(t.mentionable)} → {_onoff(lr['mentionable'])}")
            if not fields and not miss:
                continue
            if t.managed:
                add("roles", "skip", t.name, det, reason="verwaltete Rolle (Bot/Integration/Booster) – wird nicht geändert")
            elif t.position >= caps["top"]:
                above.append(t.name)
                add("roles", "skip", t.name, det, reason="liegt über oder auf Höhe der höchsten Bot-Rolle")
            elif fields:
                if miss:
                    ctx["ungrantable"][f"Rolle „{t.name}“"] = miss
                add("roles", "update", t.name, det, do={"a": "role_update", "id": t.id, "fields": fields})
            elif miss:
                ctx["ungrantable"][f"Rolle „{t.name}“"] = miss
    if "roles" in parts:
        ev = layout.get("everyone") or {}
        cur = int(guild.default_role.permissions.value)
        new, miss = merge_perms(int(ev.get("permissions", cur)), cur, caps["grant"])
        if miss:
            ctx["ungrantable"]["@everyone"] = miss
        if new != cur:
            add("roles", "update", "@everyone", ["Rechte: " + _perm_diff(cur, new)],
                do={"a": "everyone", "permissions": new})
        if mode == "exact":
            for t in troles:
                if t.id in matched_role_ids:
                    continue
                if t.managed:
                    add("roles", "skip", t.name, reason="verwaltete Rolle (Bot/Integration/Booster) – wird nie gelöscht")
                elif t.id in caps["role_ids"]:
                    add("roles", "skip", t.name, reason="Rolle des Bots – wird nie gelöscht")
                elif t.position >= caps["top"]:
                    add("roles", "skip", t.name, reason="liegt über oder auf Höhe der höchsten Bot-Rolle – nicht löschbar")
                else:
                    role_deletes += 1
                    add("roles", "delete", t.name, [f"{len(getattr(t, 'members', []) or [])} Mitglieder verlieren die Rolle"],
                        do={"a": "role_delete", "id": t.id})
        # Reihenfolge (Vorschau: neue Rollen landen zunächst ganz unten)
        sim = [(("new", i), 0) for i in range(len(lroles)) if ("new", i) in order_wanted]
        sim += [(("role", t.id), t.position) for t in troles]
        old, new = role_sequence(sim, order_wanted, caps["top"], {k for k, _ in sim if k[0] == "new"})
        old_e = [x for x in old if x[0] == "role"]
        new_e = [x for x in new if x[0] == "role"]
        moved = sum(1 for a, b in zip(old_e, new_e) if a != b)
        if moved or role_creates:
            add("order", "update", "Rollen-Reihenfolge",
                [f"{moved} bestehende Rolle(n) werden neu einsortiert" if moved else "",
                 "neue Rollen werden an ihren Platz gesetzt" if role_creates else "",
                 "nur unterhalb der höchsten Bot-Rolle"], do={"a": "role_order"})
        if above:
            warnings.append(f"{len(above)} Rolle(n) liegen über oder auf Höhe der Bot-Rolle und werden nicht geändert: "
                            f"{', '.join(above[:8])}{' …' if len(above) > 8 else ''}.")

    # --- Kategorien & Kanäle --------------------------------------------------------------------------
    chan_creates = chan_deletes = 0
    member_skips = 0
    missing_role_refs: set = set()
    catmap: dict = {}
    chanmap: dict = {}
    if "channels" in parts:
        role_ids = {r.id for r in guild.roles}
        lcats = layout.get("categories") or []
        tcats = L.sorted_categories(guild)
        tcmap = dict(zip(L.dup_keys(c.name for c in tcats), tcats))
        matched_cats = set()
        for i, (lc, key) in enumerate(zip(lcats, L.dup_keys(c["name"] for c in lcats))):
            t = tcmap.get(key)
            cur = current_overwrites(t, guild, role_ids) if t is not None else {}
            final, notes, mem = plan_overwrites(lc["overwrites"], cur, ctx, mode, f"Kategorie „{lc['name']}“")
            member_skips += mem
            missing_role_refs.update(notes)
            if t is None:
                catmap[i] = None
                chan_creates += 1
                add("categories", "create", lc["name"], [f"{len(final)} Überschreibung(en)" if final else ""],
                    do={"a": "cat_create", "idx": i, "name": lc["name"], "ow": _ow_json(final)})
                continue
            catmap[i] = t.id
            matched_cats.add(t.id)
            if final != cur:
                if not channel_manageable(t, guild.me):
                    add("categories", "skip", t.name, reason="Bot hat in dieser Kategorie keine Rechte")
                else:
                    add("categories", "update", t.name, [ow_diff(cur, final, ctx)],
                        do={"a": "cat_update", "id": t.id, "idx": i, "fields": {}, "ow": _ow_json(final)})
        # Kanäle
        lchans = layout.get("channels") or []
        lkeys = L.layout_channel_keys(layout, community)
        tkeys = dict(L.target_channel_keys(guild))
        matched_chans = set()
        bitrate_limit = int(getattr(guild, "bitrate_limit", 96000) or 96000)
        for i, (lc, key) in enumerate(zip(lchans, lkeys)):
            t = tkeys.get(key)
            kind = lc["type"]
            label = f"#{lc['name']}" if kind in ("text", "news", "forum") else lc["name"]
            want_kind = kind
            if kind == "news" and not community:
                want_kind = "text"
            if kind == "stage" and not community:
                want_kind = "voice"
            cur = current_overwrites(t, guild, role_ids) if t is not None else {}
            final, notes, mem = plan_overwrites(lc["overwrites"], cur, ctx, mode, f"Kanal „{lc['name']}“")
            member_skips += mem
            missing_role_refs.update(notes)
            if t is None:
                chan_creates += 1
                det = [f"Typ {KIND_LABELS[kind]}" + (f" (als {KIND_LABELS[want_kind]}, Community fehlt)" if want_kind != kind else ""),
                       f"in „{lcats[lc['category']]['name']}“" if lc["category"] is not None else "ohne Kategorie"]
                if lc.get("bitrate", 0) > bitrate_limit:
                    det.append(f"Bitrate auf {bitrate_limit // 1000} kbps begrenzt (Boost-Stufe)")
                add("channels", "create", label, det,
                    do={"a": "chan_create", "idx": i, "kind": want_kind, "cat": lc["category"], "ow": _ow_json(final)})
                continue
            matched_chans.add(t.id)
            chanmap[i] = t.id
            tkind = L.kind_of(t)
            fields, det = {}, []
            if tkind != want_kind and {tkind, want_kind} <= {"text", "news"}:
                fields["type"] = want_kind
                det.append(f"Typ {KIND_LABELS[tkind]} → {KIND_LABELS[want_kind]}")
            if kind in ("text", "news", "forum"):
                if (getattr(t, "topic", None) or "") != lc["topic"]:
                    fields["topic"] = lc["topic"]
                    det.append("Thema geändert" if lc["topic"] else "Thema entfernt")
                if int(getattr(t, "slowmode_delay", 0) or 0) != lc["slowmode"]:
                    fields["slowmode_delay"] = lc["slowmode"]
                    det.append(f"Slowmode {int(getattr(t, 'slowmode_delay', 0) or 0)} → {lc['slowmode']} s")
                if tkind in ("text", "news", "forum"):
                    if int(getattr(t, "default_auto_archive_duration", 1440) or 1440) != lc["default_auto_archive"]:
                        fields["default_auto_archive_duration"] = lc["default_auto_archive"]
                        det.append(f"Threads archivieren nach {lc['default_auto_archive']} min")
                    if int(getattr(t, "default_thread_slowmode_delay", 0) or 0) != lc["default_thread_slowmode"]:
                        fields["default_thread_slowmode_delay"] = lc["default_thread_slowmode"]
                        det.append(f"Thread-Slowmode → {lc['default_thread_slowmode']} s")
            cur_nsfw = bool(t.is_nsfw()) if hasattr(t, "is_nsfw") else bool(getattr(t, "nsfw", False))
            if cur_nsfw != lc["nsfw"]:
                fields["nsfw"] = lc["nsfw"]
                det.append(f"NSFW {_onoff(cur_nsfw)} → {_onoff(lc['nsfw'])}")
            if kind in ("voice", "stage"):
                br = min(lc["bitrate"], bitrate_limit)
                if int(getattr(t, "bitrate", 0) or 0) != br:
                    fields["bitrate"] = br
                    det.append(f"Bitrate {int(getattr(t, 'bitrate', 0) or 0) // 1000} → {br // 1000} kbps"
                               + (" (Boost-Limit)" if br < lc["bitrate"] else ""))
                ul = lc["user_limit"] if tkind == "stage" else min(lc["user_limit"], 99)
                if int(getattr(t, "user_limit", 0) or 0) != ul:
                    fields["user_limit"] = ul
                    det.append(f"Nutzerlimit {int(getattr(t, 'user_limit', 0) or 0)} → {ul}")
                region = getattr(t, "rtc_region", None)
                if (str(region) if region else None) != lc["rtc_region"]:
                    fields["rtc_region"] = lc["rtc_region"]
                    det.append(f"Region → {lc['rtc_region'] or 'automatisch'}")
                if L._enum_val(getattr(t, "video_quality_mode", 1), 1) != lc["video_quality"]:
                    fields["video_quality_mode"] = lc["video_quality"]
                    det.append("Videoqualität " + ("720p" if lc["video_quality"] == 2 else "automatisch"))
            if kind == "forum" and tkind == "forum":
                cur_tags = {tg.name: tg for tg in (getattr(t, "available_tags", None) or [])}
                want_tags = {tg["name"]: tg for tg in lc["tags"]}
                tag_names = list(want_tags) + ([n for n in cur_tags if n not in want_tags] if mode == "merge" else [])
                tag_names = tag_names[:L.MAX_TAGS]
                changed_tags = [n for n in want_tags if n not in cur_tags or L._emoji_str(cur_tags[n].emoji) != want_tags[n]["emoji"]
                                or bool(cur_tags[n].moderated) != want_tags[n]["moderated"]]
                removed_tags = [n for n in cur_tags if n not in tag_names]
                if changed_tags or removed_tags:
                    fields["tags"] = [dict(want_tags.get(n) or {"name": n, "emoji": L._emoji_str(cur_tags[n].emoji),
                                                                  "moderated": bool(cur_tags[n].moderated)},
                                           id=int(getattr(cur_tags.get(n), "id", 0) or 0)) for n in tag_names]
                    det.append("Forum-Tags: " + "; ".join(x for x in (
                        ("+/~ " + ", ".join(changed_tags)) if changed_tags else "",
                        ("− " + ", ".join(removed_tags)) if removed_tags else "") if x))
                if L._enum_val(getattr(t, "default_layout", 0)) != lc["default_layout"]:
                    fields["default_layout"] = lc["default_layout"]
                    det.append("Standard-Ansicht geändert")
                cur_so = getattr(t, "default_sort_order", None)
                if lc["default_sort_order"] is not None and (cur_so is None or L._enum_val(cur_so) != lc["default_sort_order"]):
                    fields["default_sort_order"] = lc["default_sort_order"]
                    det.append("Standard-Sortierung geändert")
                if L._emoji_str(getattr(t, "default_reaction_emoji", None)) != lc["default_reaction"] and \
                        (lc["default_reaction"] or getattr(t, "default_reaction_emoji", None)):
                    fields["default_reaction_emoji"] = lc["default_reaction"]
                    det.append(f"Standard-Reaktion → {lc['default_reaction'] or 'keine'}")
            ow_changed = final != cur
            if ow_changed:
                det.append(ow_diff(cur, final, ctx))
            if not fields and not ow_changed:
                continue
            if not channel_manageable(t, guild.me):
                add("channels", "skip", label, det, reason="Bot hat in diesem Kanal keine Rechte")
                continue
            add("channels", "update", label, det,
                do={"a": "chan_update", "id": t.id, "idx": i, "fields": fields, "ow": _ow_json(final) if ow_changed else None})
        # Löschen (nur exakt)
        if mode == "exact":
            protected = set()
            if community:
                for attr in ("rules_channel", "public_updates_channel", "safety_alerts_channel"):
                    ch = getattr(guild, attr, None)
                    if ch is not None:
                        protected.add(ch.id)
            for key, t in L.target_channel_keys(guild):
                if t.id in matched_chans:
                    continue
                lbl = f"#{t.name}" if L.kind_of(t) in ("text", "news", "forum") else t.name
                if t.id in protected:
                    add("channels", "skip", lbl, reason="Regel-/Update-Kanal eines Community-Servers – Discord erlaubt kein Löschen")
                elif protect_channel_id and t.id == protect_channel_id:
                    add("channels", "skip", lbl, reason="Kanal, in dem der Befehl ausgeführt wurde")
                elif not channel_manageable(t, guild.me):
                    add("channels", "skip", lbl, reason="Bot hat in diesem Kanal keine Rechte")
                else:
                    chan_deletes += 1
                    add("channels", "delete", lbl, ["Nachrichten darin sind danach unwiderruflich weg"],
                        do={"a": "chan_delete", "id": t.id})
            for t in tcats:
                if t.id in matched_cats:
                    continue
                if not channel_manageable(t, guild.me):
                    add("categories", "skip", t.name, reason="Bot hat in dieser Kategorie keine Rechte")
                else:
                    chan_deletes += 1
                    add("categories", "delete", t.name, do={"a": "cat_delete", "id": t.id})
        # Reihenfolge (Vorschau: nur bestehende Kanäle; neue werden bei der Ausführung mit einsortiert)
        wanted = [catmap[i] for i in range(len(lcats)) if catmap.get(i)]
        wanted += [tkeys[k].id for k in lkeys if k in tkeys]
        moved = channel_order(channel_groups(guild), wanted)
        if moved or chan_creates:
            add("order", "update", "Kanal-Reihenfolge",
                [f"{len(moved)} bestehende Kanäle/Kategorien werden verschoben" if moved else "",
                 "neue Kanäle werden einsortiert" if chan_creates else ""], do={"a": "chan_order"})
        if member_skips:
            add("channels", "skip", f"{member_skips} Mitglieder-Überschreibung(en)",
                reason="Überschreibungen für einzelne Mitglieder werden nicht übertragen (Mitglieder unterscheiden sich)")
        if missing_role_refs:
            warnings.append("Überschreibungen für fehlende Rollen werden übersprungen: "
                            + ", ".join(sorted(missing_role_refs)[:8]) + (" …" if len(missing_role_refs) > 8 else "")
                            + (" – Tipp: Teil „Rollen“ mitladen." if "roles" not in parts else "."))
        kinds = {c["type"] for c in lchans}
        if not community and kinds & {"news", "stage"}:
            warnings.append("Community-Funktionen fehlen auf dem Ziel-Server: Ankündigungs-Kanäle werden als Textkanäle, "
                            "Stage-Kanäle als Sprachkanäle angelegt.")

    # --- Server-Einstellungen -----------------------------------------------------------------------------
    if "settings" in parts:
        s = layout["settings"]
        fields: dict = {}
        det: list = []
        tkeys = dict(L.target_channel_keys(guild))
        layout_keys = set(L.layout_channel_keys(layout, community)) if "channels" in parts else set()

        def ref_ok(ref, label):
            if ref is None:
                return True
            k = L.ref_tuple(ref)
            if k in tkeys or k in layout_keys:
                return True
            add("settings", "skip", label, reason=f"Kanal „{ref['name']}“ gibt es auf dem Ziel-Server nicht")
            return False

        if s["name"] != guild.name:
            fields["name"] = s["name"]
            det.append(f"Name „{guild.name}“ → „{s['name']}“")
        for key, label, names in (("verification_level", "Verifizierungsstufe", VERIFY),
                                  ("explicit_content_filter", "Filter für explizite Inhalte", FILTER),
                                  ("default_notifications", "Standard-Benachrichtigungen", NOTIFY)):
            cur = L._enum_val(getattr(guild, key, 0))
            if cur != s[key]:
                fields[key] = s[key]
                det.append(f"{label}: {names[cur] if cur < len(names) else cur} → {names[s[key]]}")
        if int(getattr(guild, "afk_timeout", 300) or 300) != s["afk_timeout"]:
            fields["afk_timeout"] = s["afk_timeout"]
            det.append(f"AFK-Timeout → {s['afk_timeout'] // 60} min")
        if L._enum_val(getattr(guild, "system_channel_flags", 0)) != s["system_channel_flags"]:
            fields["system_channel_flags"] = s["system_channel_flags"]
            det.append("Systemnachrichten-Optionen geändert")
        for key, label in (("afk_channel", "AFK-Kanal"), ("system_channel", "Systemkanal")):
            cur = L.channel_ref(guild, getattr(guild, key, None))
            want = s[key]
            if (L.ref_tuple(cur) if cur else None) != (L.ref_tuple(want) if want else None) and ref_ok(want, label):
                fields[key] = want
                det.append(f"{label} → {want['name'] if want else 'keiner'}")
        for key, label in (("rules_channel", "Regel-Kanal"), ("public_updates_channel", "Update-Kanal")):
            cur = L.channel_ref(guild, getattr(guild, key, None))
            want = s[key]
            if (L.ref_tuple(cur) if cur else None) == (L.ref_tuple(want) if want else None):
                continue
            if not community:
                if want:
                    add("settings", "skip", label, reason="nur auf Community-Servern möglich")
                continue
            if want is None:
                add("settings", "skip", label, reason="Discord verlangt auf Community-Servern einen Kanal – bleibt")
            elif ref_ok(want, label):
                fields[key] = want
                det.append(f"{label} → {want['name']}")
        if s["description"] != (getattr(guild, "description", None) or ""):
            if community:
                fields["description"] = s["description"]
                det.append("Beschreibung geändert")
            elif s["description"]:
                add("settings", "skip", "Beschreibung", reason="nur auf Community-Servern möglich")
        if fields:
            add("settings", "update", "Server-Einstellungen", det, do={"a": "settings", "fields": fields})
        for key, label, feat, anim_feat in (("icon", "Server-Icon", None, "ANIMATED_ICON"),
                                            ("banner", "Banner", "BANNER", "ANIMATED_BANNER")):
            img = s.get(key)
            if not img:
                continue
            cur_asset = getattr(guild, key, None)
            cur_key = str(getattr(cur_asset, "key", "") or "") if cur_asset is not None else ""
            if cur_key and img.get("key") and cur_key == img["key"]:
                continue        # dasselbe Bild (z. B. derselbe Server)
            st = (image_state or {}).get(key) or {}
            if cur_key and st.get("key") == cur_key and st.get("sha") == L.image_sha(img):
                continue        # wurde bereits aus genau diesem Bild gesetzt
            if feat and feat not in features:
                add("settings", "skip", label, reason="Boost-Stufe des Ziel-Servers erlaubt kein Banner")
                warnings.append("Banner wird übersprungen: die Boost-Stufe des Ziel-Servers erlaubt kein Banner.")
            elif img.get("animated") and anim_feat not in features:
                add("settings", "skip", label, reason="animiertes Bild braucht eine höhere Boost-Stufe")
            else:
                size = len(L.image_bytes(img) or b"")
                add("settings", "update", label, [f"neues Bild ({size // 1024} KB)" if size >= 1024 else "neues Bild (< 1 KB)"],
                    do={"a": "image", "key": key})

    # --- Warnungen -----------------------------------------------------------------------------------
    if ctx["ungrantable"]:
        total = 0
        for v in ctx["ungrantable"].values():
            total |= v
        names = list(ctx["ungrantable"])
        warnings.append("Rechte, die der Bot selbst nicht hat, werden ausgelassen (" + L.perm_names(total) + ") bei: "
                        + ", ".join(names[:6]) + (f" (+{len(names) - 6})" if len(names) > 6 else "") + ".")
    roles_after = len(guild.roles) + role_creates - role_deletes
    if roles_after > L.MAX_ROLES:
        warnings.append(f"Rollen-Limit: danach wären es {roles_after} Rollen (Discord erlaubt {L.MAX_ROLES}) – "
                        "überzählige Rollen können nicht angelegt werden.")
    chans_after = len(guild.channels) + chan_creates - chan_deletes
    if chans_after > L.MAX_CHANNELS:
        warnings.append(f"Kanal-Limit: danach wären es {chans_after} Kanäle (Discord erlaubt {L.MAX_CHANNELS}) – "
                        "überzählige Kanäle können nicht angelegt werden.")
    if mode == "exact" and chan_deletes:
        warnings.append(f"Exakt angleichen löscht {chan_deletes} Kanäle/Kategorien – Nachrichten darin sind unwiderruflich "
                        "weg (die automatische Sicherung stellt nur leere Kanäle wieder her).")

    counts = {op: sum(1 for it in items if it["op"] == op and it["sec"] != "order") for op in ("create", "update", "delete", "skip")}
    counts["order"] = sum(1 for it in items if it["sec"] == "order")
    fingerprint = json.dumps([[it["sec"], it["op"], it["label"], it["details"], it["do"]] for it in items] + [mode, parts],
                             ensure_ascii=False, sort_keys=True, default=str)
    return {
        "mode": mode, "parts": parts, "items": items, "warnings": warnings, "blockers": blockers, "counts": counts,
        "rolemap": rolemap, "catmap": catmap, "chanmap": chanmap, "hash": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16],
        "actionable": counts["create"] + counts["update"] + counts["delete"] + counts["order"],
    }
