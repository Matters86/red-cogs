"""Mitglieder-Seite „Mein Level“ (``/me/level``) im WebCore-Mitglieder-Bereich.

* GET ``/me/level?guild=<id>``          -> eigener Rang, Fortschrittsbalken, Rangkarte, nächste Belohnung, Top 10
* GET ``/me/level?guild=<id>&card=1``   -> eigene Rangkarte als PNG

Nur eigene Daten (``request["wc_member"]``); die Top 10 zeigen ausschließlich Anzeigenamen, Level und XP.
Abschaltbar über den Schalter „Im Mitglieder-Bereich anzeigen“ im Team-Dashboard.
"""

from __future__ import annotations

import html
import logging
from urllib.parse import quote_plus

from aiohttp import web

log = logging.getLogger("red.red-cogs.levels")

SLUG = "level"
TITLE = "Mein Level"


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _num(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def next_reward(guild, conf: dict, level: int):
    """``(level, rolle)`` der nächsten Belohnung über ``level`` oder ``None``."""
    upcoming = []
    for lvl, rid in (conf.get("rewards") or {}).items():
        role = guild.get_role(int(rid)) if str(rid).isdigit() else None
        if role is not None and str(lvl).isdigit() and int(lvl) > level:
            upcoming.append((int(lvl), role))
    return min(upcoming, key=lambda x: x[0]) if upcoming else None


async def member_handler(cog, request):
    from .levels import progress, total_xp_for_level

    webcore = request.app["webcore"]
    ui = webcore.ui
    guild = request["wc_member_guild"]
    member = request["wc_member"]
    conf = await cog.config.guild(guild).all()

    if request.method == "POST":   # diese Seite hat keine Aktionen
        return {"redirect": f"/me/{SLUG}?guild={guild.id}&err=" + quote_plus("Unbekannte Aktion")}
    if not conf.get("member_page", True):
        if request.query.get("card"):
            raise web.HTTPNotFound(text="ausgeschaltet")
        return {"title": TITLE, "content": ui.card(body=ui.empty(
            "bi-eye-slash", "Level sind auf diesem Server im Mitglieder-Bereich ausgeschaltet.",
            "Nutze <code>/rank</code> direkt in Discord."))}
    if not conf.get("enabled", True):
        if request.query.get("card"):
            raise web.HTTPNotFound(text="ausgeschaltet")
        return {"title": TITLE, "content": ui.card(body=ui.empty(
            "bi-pause-circle", "Das Levelsystem ist auf diesem Server ausgeschaltet."))}

    if request.query.get("card"):
        png = await cog.render_card(member, conf)
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    rec = await cog.member_record(guild, member.id)
    level, into, needed = progress(rec["xp"])
    rank, total = await cog.rank_of(guild, member.id)
    pct = int(100 * into / needed) if needed else 0

    head = ui.hero("bi-trophy", "", f"Dein Fortschritt auf <b>{_esc(guild.name)}</b>. XP gibt es fürs Schreiben"
                   + (" und für Zeit in Sprachkanälen" if conf.get("voice_enabled") else "") + ".")
    kpis = ui.stats([
        ("Rang", f"#{rank}" if rank else "–", "bi-trophy", f"von {_num(total)}" if rank else "noch ohne XP", "ok" if rank else None),
        ("Level", level, "bi-bar-chart-steps", None, None),
        ("XP gesamt", _num(rec["xp"]), "bi-stars", None, None),
    ])
    meter = (
        "<div class='meter'><div class='mlabel'>"
        f"<span class='k'>Level {level} → {level + 1}</span><span class='v'>{_num(into)} / {_num(needed)} XP</span></div>"
        f"<div class='bar' role='progressbar' aria-valuemin='0' aria-valuemax='{needed}' aria-valuenow='{into}'>"
        f"<span style='width:{pct}%'></span></div></div>"
        f"<div class='wc-help' style='margin-top:8px'>Noch <b>{_num(needed - into)} XP</b> bis Level {level + 1}.</div>"
    )
    nxt = next_reward(guild, conf, level)
    if nxt:
        lvl, role = nxt
        missing = max(0, total_xp_for_level(lvl) - rec["xp"])
        reward = (f"<div class='kv'><div class='row-kv'><span class='k'>Nächste Belohnung</span>"
                  f"<span class='v'>@{_esc(role.name)}</span></div>"
                  f"<div class='row-kv'><span class='k'>ab Level</span><span class='v'>{lvl}</span></div>"
                  f"<div class='row-kv'><span class='k'>fehlen noch</span><span class='v'>{_num(missing)} XP</span></div></div>")
    elif conf.get("rewards"):
        reward = ui.empty("bi-patch-check", "Du hast alle Belohnungen erreicht.")
    else:
        reward = ui.empty("bi-gift", "Auf diesem Server gibt es keine Level-Belohnungen.")
    card_img = (f"<img src='/me/{SLUG}?guild={guild.id}&amp;card=1' class='img-fluid rounded' width='934' height='282' "
                f"alt='Rangkarte von {_esc(member.display_name)}' loading='lazy' style='width:100%;max-width:720px;height:auto'>")

    rows = await cog.ranking(guild)
    trs = []
    for i, (uid, r) in enumerate(rows[:10], 1):
        m = guild.get_member(uid)
        name = _esc(m.display_name if m else "Unbekannt")
        if uid == member.id:
            name = f"<b>{name}</b> " + ui.badge("Du", "ok")
        trs.append(ui.row(f"<b>#{i}</b>", name, ">" + str(r["level"]), ">" + _num(r["xp"])))
    top = ui.table(["#", "Mitglied", ">Level", ">XP"], trs, empty_text="Noch hat niemand XP gesammelt.", id="lv-top")
    if rank and rank > 10:
        top += f"<div class='wc-help' style='margin-top:8px'>Du bist auf Platz <b>#{rank}</b>.</div>"

    content = (
        head + kpis
        + ui.columns(
            ui.card("Fortschritt", meter, icon="bi-graph-up-arrow"),
            ui.card("Belohnung", reward, icon="bi-gift"),
        )
        + ui.card("Deine Rangkarte", card_img, icon="bi-image", desc="Dieselbe Karte zeigt <code>/rank</code> in Discord.")
        + ui.card("Top 10", top, icon="bi-list-ol", desc="Die aktivsten Mitglieder dieses Servers.")
    )
    return {"title": TITLE, "content": content}
