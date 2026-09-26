"""„Mein Bereich → Gewinnspiele“ für normale Server-Mitglieder.

* GET  -> Reiter „Laufend“ (Gewinnspiele in Kanälen, die das Mitglied lesen kann, mit eigenem
          Teilnahme-Status und Button) und „Meine Gewinne“.
* POST form=join|leave -> exakt ``Giveaways.join``/``Giveaways.leave`` (dieselben Funktionen wie
          der Discord-Button, gleiche Regeln); die Discord-Nachricht wird wie beim Button (gedrosselt)
          aktualisiert.

Sichtbarkeit wie in Discord: gepostet und Kanal für das Mitglied lesbar (``view_channel``).
Fremde/unsichtbare Gewinnspiele verhalten sich wie nicht vorhandene. Namen anderer Teilnehmer
werden nie gezeigt (das Embed zeigt auch nur die Anzahl).
"""

from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from urllib.parse import quote

import discord

from .core import eligibility, is_running, tickets_for
from .strings import t

SLUG = "gewinnspiele"


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _plain(text: str) -> str:
    return (text or "").replace("**", "").replace("`", "")


def can_view(channel, member) -> bool:
    """Darf ``member`` den Kanal in Discord sehen? (private Threads: zusätzlich Mitgliedschaft)"""
    if channel is None or member is None:
        return False
    try:
        perms = channel.permissions_for(member)
    except Exception:  # noqa: BLE001
        return False
    if not perms.view_channel:
        return False
    if isinstance(channel, discord.Thread) and channel.is_private():
        if perms.manage_threads or channel.owner_id == member.id:
            return True
        return any(getattr(m, "id", None) == member.id for m in (channel.members or []))
    return True


def gw_visible(cog, guild, member, gw) -> bool:
    if not isinstance(gw, dict) or not gw.get("message_id"):
        return False
    return can_view(cog._channel(guild, gw.get("channel_id")), member)


def rel(ts: int, now: float) -> str:
    diff = int(ts - now)
    future = diff >= 0
    diff = abs(diff)
    if diff < 60:
        return "gleich" if future else "gerade eben"
    if diff < 3600:
        n, unit = diff // 60, "Min."
    elif diff < 86400:
        n, unit = diff // 3600, "Std."
    else:
        n = diff // 86400
        unit = "Tag" if n == 1 else "Tagen"
    return f"in {n} {unit}" if future else f"vor {n} {unit}"


def absolute(ts: int, tz) -> str:
    return datetime.fromtimestamp(int(ts), tz=tz or timezone.utc).strftime("%d.%m.%Y, %H:%M Uhr")


def _tz(name):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


async def member_page_handler(cog, request):
    guild = request["wc_member_guild"]
    member = request["wc_member"]
    conf = await cog.config.guild(guild).all()
    base = f"/me/{SLUG}?guild={guild.id}"
    if request.method == "POST":
        return await _handle_post(cog, request, guild, member, conf, base)
    return _render(cog, request, guild, member, conf)


async def _handle_post(cog, request, guild, member, conf, base):
    data = await request.post()
    lang = conf.get("language", "de")
    if not conf.get("member_page", True):
        return {"redirect": base + "&err=" + quote("Gewinnspiele sind im Mitglieder-Bereich ausgeschaltet")}
    action = data.get("form")
    if action not in ("join", "leave"):
        return {"redirect": base + "&err=" + quote("Unbekannte Aktion")}
    gw_id = str(data.get("gw") or "")
    gw = (conf.get("giveaways") or {}).get(gw_id)
    if not gw_id or not gw_visible(cog, guild, member, gw):
        return {"redirect": base + "&err=" + quote(_plain(t(lang, "err_unknown")))}
    if action == "join":
        key, kwargs, changed = await cog.join(guild, member, gw_id)
        if key == "already":
            key, kwargs, changed = "already_web", {"tickets": kwargs.get("tickets", 1)}, False
    else:
        key, kwargs, changed = await cog.leave(guild, member, gw_id)
    if key == "already_web":
        text = f"Du nimmst bereits teil (Lose: {kwargs['tickets']})."
    else:
        text = _plain(cog.text(guild, lang, key, kwargs, web=True))
    anchor = "#gw-" + quote(gw_id)
    return {"redirect": base + ("&ok=" if changed else "&err=") + quote(text) + anchor}


def _render(cog, request, guild, member, conf):
    ui = request.app["webcore"].ui
    csrf = request.get("webcore_csrf", "")
    if not conf.get("member_page", True):
        return {"title": "Gewinnspiele", "content": ui.card(body=ui.empty(
            "bi-eye-slash", "Gewinnspiele sind auf diesem Server im Mitglieder-Bereich ausgeschaltet.",
            "Nimm direkt in Discord über den 🎉-Button unter dem Gewinnspiel teil."))}
    now = time.time()
    tz = _tz(conf.get("timezone"))
    lang = conf.get("language", "de")
    all_gws = [g for g in (conf.get("giveaways") or {}).values() if isinstance(g, dict)]
    running = sorted((g for g in all_gws if is_running(g, now) and gw_visible(cog, guild, member, g)),
                     key=lambda g: int(g.get("end_ts") or 0))
    wins = sorted((g for g in all_gws if g.get("status") == "ended"
                   and member.id in [int(w) for w in g.get("winner_ids") or []]),
                  key=lambda g: -int(g.get("ended_ts") or 0))

    head = ui.hero("bi-gift", "", "Nimm hier genauso teil wie mit dem 🎉-Button in Discord – es gelten dieselben "
                                  "Regeln. Du siehst nur Gewinnspiele aus Kanälen, die du lesen kannst.")
    if running:
        cards = "".join(_card(cog, ui, guild, member, g, csrf, now, tz, lang) for g in running)
    else:
        cards = ui.card(body=ui.empty("bi-gift", "Gerade läuft kein Gewinnspiel.",
                                      "Neue Gewinnspiele erscheinen hier automatisch."))
    if wins:
        rows = []
        for g in wins:
            ch = cog._channel(guild, g.get("channel_id"))
            rows.append(
                f"<div><b>🏆 {_esc(g.get('prize'))}</b><div class='wc-muted'>"
                + (f"#{_esc(ch.name)} · " if ch is not None else "")
                + f"gewonnen {_esc(rel(int(g.get('ended_ts') or 0), now))} "
                  f"({_esc(absolute(int(g.get('ended_ts') or 0), tz))})</div></div>")
        won = ui.card("Meine Gewinne", "<div class='wc-divider'></div>".join(rows), icon="bi-trophy",
                      desc="Melde dich beim Team, falls du deinen Gewinn noch nicht erhalten hast.")
    else:
        won = ui.card(body=ui.empty("bi-trophy", "Du hast noch kein Gewinnspiel gewonnen.",
                                    "Viel Glück beim nächsten Mal!"))
    body = (ui.tab("laufend", "Laufend", "bi-broadcast", cards, count=len(running))
            + ui.tab("gewinne", "Meine Gewinne", "bi-trophy", won, count=len(wins)))
    return {"title": "Gewinnspiele", "content": head + body}


def _card(cog, ui, guild, member, gw, csrf, now, tz, lang) -> str:
    gw_id = str(gw.get("id"))
    entered = str(member.id) in (gw.get("entrants") or {})
    ch = cog._channel(guild, gw.get("channel_id"))
    meta = []
    if ch is not None:
        meta.append(f"<span><i class='bi bi-hash'></i>{_esc(ch.name)}</span>")
    end_ts = int(gw.get("end_ts") or 0)
    meta.append(f"<span title='{_esc(absolute(end_ts, tz))}'><i class='bi bi-hourglass-split'></i> endet "
                f"{_esc(rel(end_ts, now))}</span>")
    meta.append(ui.badge(f"{int(gw.get('winner_count') or 1)} Gewinner", "info"))
    meta.append(ui.badge(f"{len(gw.get('entrants') or {})} Teilnehmer", "muted"))
    body = f"<div class='wc-muted'>{' &nbsp;'.join(meta)}</div>"
    if gw.get("description"):
        body += f"<div class='wc-divider'></div><div style='white-space:pre-line'>{_esc(gw['description'])}</div>"
    reqs = []
    if gw.get("required_roles"):
        names = [getattr(guild.get_role(int(r)), "name", None) for r in gw["required_roles"]]
        reqs.append("Eine dieser Rollen: " + ", ".join(_esc(n) for n in names if n))
    if gw.get("excluded_roles"):
        names = [getattr(guild.get_role(int(r)), "name", None) for r in gw["excluded_roles"]]
        reqs.append("Ausgeschlossen: " + ", ".join(_esc(n) for n in names if n))
    if int(gw.get("min_member_days") or 0):
        reqs.append(f"Mindestens {int(gw['min_member_days'])} Tage auf dem Server")
    bonus = []
    for rid, n in (gw.get("bonus_roles") or {}).items():
        r = guild.get_role(int(rid))
        if r is not None:
            bonus.append(f"{_esc(r.name)} +{int(n)}")
    if reqs or bonus:
        body += "<div class='wc-divider'></div>"
        if reqs:
            body += "<div class='wc-help'><b>Voraussetzungen:</b> " + " · ".join(reqs) + "</div>"
        if bonus:
            body += "<div class='wc-help'><b>Bonus-Lose:</b> " + " · ".join(bonus) + "</div>"

    tickets = tickets_for(member, gw)
    hidden = {"guild": guild.id, "gw": gw_id}
    action = f"/me/{SLUG}?guild={guild.id}"
    if entered:
        status = ui.callout(f"Du nimmst teil – <b>{tickets}</b> {'Los' if tickets == 1 else 'Lose'}. Viel Glück!",
                            tone="ok")
        btn = ui.form(action, ui.actions(ui.button("Austreten", icon="bi-box-arrow-left", kind="danger")),
                      csrf=csrf, hidden={**hidden, "form": "leave"},
                      confirm="Möchtest du wirklich nicht mehr an diesem Gewinnspiel teilnehmen?")
    else:
        err = eligibility(member, gw, now)
        if err is not None:
            status = ui.callout(_esc(_plain(cog.text(guild, lang, err[0], err[1], web=True))), tone="warn")
            btn = ""
        else:
            status = ui.callout(f"Du würdest mit <b>{tickets}</b> {'Los' if tickets == 1 else 'Losen'} teilnehmen.")
            btn = ui.form(action, ui.actions(ui.button("Teilnehmen", icon="bi-gift")),
                          csrf=csrf, hidden={**hidden, "form": "join"})
    body += f"<div style='margin-top:12px'>{status}</div>{btn}"
    return f"<div id='gw-{_esc(gw_id)}'>" + ui.card(gw.get("prize") or "Gewinnspiel", body, icon="bi-gift") + "</div>"
