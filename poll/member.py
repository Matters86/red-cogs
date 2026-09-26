"""„Mein Bereich → Umfragen“: Abstimmen im Web für normale Server-Mitglieder.

* GET  -> laufende Umfragen aus Kanälen, die das Mitglied lesen kann (Karten mit Ergebnis-Balken
          und einem Button je Option) + beendete Umfragen der letzten 14 Tage mit Ergebnis.
* POST form=vote -> Stimme abgeben/ändern/zurückziehen – exakt über ``Poll.cast_vote`` (dieselbe
          Funktion wie der Discord-Button), danach wird die Umfrage-Nachricht aktualisiert.

Sichtbarkeit wie in Discord: Die Umfrage muss gepostet sein und ihr Kanal für das Mitglied
lesbar (``view_channel``). Ergebnisse zeigt die Umfrage in Discord immer live (Balken im Embed,
Zähler auf den Buttons) – deshalb auch hier; Namen zeigt das Embed nie, also auch hier nicht.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote

import discord

from .embed import vote_counts
from .strings import t

FINISHED_DAYS = 14          # beendete Umfragen so lange anzeigen
BUTTON_LABEL_MAX = 34       # Button-Beschriftung kürzen (Handy), voller Text steht darüber


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _now() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def _plain(text: str) -> str:
    """Discord-Markdown aus Bot-Antworten entfernen (Toast zeigt reinen Text)."""
    return (text or "").replace("**", "").replace("`", "")


def can_view(channel, member) -> bool:
    """Darf ``member`` den Kanal in Discord sehen? (bei privaten Threads zusätzlich Mitgliedschaft)"""
    if channel is None or member is None:
        return False
    try:
        perms = channel.permissions_for(member)
    except Exception:  # noqa: BLE001 – unbekannter Kanaltyp o. Ä. -> lieber verbergen
        return False
    if not perms.view_channel:
        return False
    if isinstance(channel, discord.Thread) and channel.is_private():
        if perms.manage_threads or channel.owner_id == member.id:
            return True
        return any(getattr(m, "id", None) == member.id for m in (channel.members or []))
    return True


def poll_visible(guild, member, poll) -> bool:
    """Gepostet + Kanal für das Mitglied lesbar (nur solche Umfragen kann man in Discord anklicken)."""
    if not isinstance(poll, dict) or not poll.get("message_id") or not poll.get("channel_id"):
        return False
    try:
        channel = guild.get_channel(int(poll["channel_id"]))
    except (TypeError, ValueError):
        return False
    if channel is None and hasattr(guild, "get_thread"):
        channel = guild.get_thread(int(poll["channel_id"]))
    return can_view(channel, member)


def finished_ts(poll: dict) -> int:
    """Zeitpunkt des Endes (ältere Umfragen ohne ``closed_ts``: Laufzeit-Ende bzw. Erstellung)."""
    return int(poll.get("closed_ts") or poll.get("end_ts") or poll.get("created_ts") or 0)


def _is_finished(poll: dict) -> bool:
    return bool(poll.get("closed") or poll.get("ended"))


def _rel(ts: int, now: int) -> str:
    """Kurze relative Zeitangabe („in 2 Std.“, „vor 3 Tagen“)."""
    diff = int(ts) - now
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


def _utc(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y, %H:%M UTC")


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def member_page_handler(cog, request):
    guild = request["wc_member_guild"]
    member = request["wc_member"]
    conf = await cog.config.guild(guild).all()
    base = f"/me/umfragen?guild={guild.id}"
    if request.method == "POST":
        return await _handle_post(cog, request, guild, member, conf, base)
    return _render(request, guild, member, conf)


async def _handle_post(cog, request, guild, member, conf, base):
    data = await request.post()
    lang = conf.get("language", "de")
    if not conf.get("member_page", True):
        return {"redirect": base + "&err=" + quote("Umfragen sind im Mitglieder-Bereich ausgeschaltet")}
    if data.get("form") != "vote":
        return {"redirect": base + "&err=" + quote("Unbekannte Aktion")}
    pid = str(data.get("poll") or "")
    poll = (conf.get("polls") or {}).get(pid)
    # Fremde/unsichtbare Umfragen verhalten sich wie nicht vorhandene (keine Rückschlüsse möglich).
    if not pid or poll is None or not poll_visible(guild, member, poll):
        return {"redirect": base + "&err=" + quote(_plain(t(lang, "unknown_poll")))}
    raw = str(data.get("option") or "")
    if not raw.isdigit():
        return {"redirect": base + "&err=" + quote(_plain(t(lang, "unknown_option")))}

    key, kwargs, snapshot = await cog.cast_vote(guild, member, pid, int(raw))
    text = _plain(t(lang, key, **kwargs))
    anchor = "#pl-" + quote(pid)
    if snapshot is None:
        return {"redirect": base + "&err=" + quote(text) + anchor}
    # Wie beim Button: Umfrage-Nachricht (Balken + Zähler) in Discord aktualisieren.
    await cog.refresh_poll_message(guild, snapshot)
    return {"redirect": base + "&ok=" + quote(text) + anchor}


# --------------------------------------------------------------------------- #
#  Rendern (GET)
# --------------------------------------------------------------------------- #
def _render(request, guild, member, conf):
    ui = request.app["webcore"].ui
    csrf = request.get("webcore_csrf", "")
    if not conf.get("member_page", True):
        return {"title": "Umfragen", "content": ui.card(body=ui.empty(
            "bi-eye-slash", "Umfragen sind auf diesem Server im Mitglieder-Bereich ausgeschaltet.",
            "Stimme direkt in Discord über die Buttons unter der Umfrage ab."))}

    now = _now()
    cutoff = now - FINISHED_DAYS * 86400
    polls = [p for p in (conf.get("polls") or {}).values() if poll_visible(guild, member, p)]
    active = sorted((p for p in polls if not _is_finished(p)),
                    key=lambda p: p.get("created_ts", 0), reverse=True)
    done = sorted((p for p in polls if _is_finished(p) and finished_ts(p) >= cutoff),
                  key=finished_ts, reverse=True)

    head = ui.hero(
        "bi-bar-chart", "",
        "Stimme hier genauso ab wie mit den Buttons in Discord – die Umfrage-Nachricht wird sofort "
        "aktualisiert. Du siehst nur Umfragen aus Kanälen, die du lesen kannst.",
    )
    if active:
        running = "".join(_poll_card(ui, guild, member, p, csrf, now) for p in active)
    else:
        running = ui.card(body=ui.empty("bi-bar-chart", "Gerade läuft keine Umfrage.",
                                        "Neue Umfragen erscheinen hier automatisch."))
    if done:
        finished = "".join(_poll_card(ui, guild, member, p, csrf, now) for p in done)
    else:
        finished = ui.card(body=ui.empty("bi-flag", f"In den letzten {FINISHED_DAYS} Tagen ist keine Umfrage beendet worden."))
    body = (
        ui.tab("laufend", "Laufend", "bi-broadcast", running, count=len(active))
        + ui.tab("beendet", "Beendet", "bi-flag", ui.callout(
            f"Umfragen, die in den letzten {FINISHED_DAYS} Tagen geendet haben, mit Endergebnis.") + finished,
            count=len(done))
    )
    return {"title": "Umfragen", "content": head + body}


def _poll_card(ui, guild, member, poll, csrf, now) -> str:
    pid = str(poll.get("id", ""))
    options = poll.get("options") or []
    counts, total, voters = vote_counts(poll)
    finished = _is_finished(poll)
    multiple = bool(poll.get("multiple"))
    mine = set((poll.get("votes") or {}).get(str(member.id), {}).get("choices") or [])
    winning = max(counts) if counts else 0
    channel = guild.get_channel(int(poll["channel_id"])) if poll.get("channel_id") else None

    # Kopfzeile: Kanal · Modus · Sichtbarkeit · Status/Laufzeit
    meta = []
    if channel is not None:
        meta.append(f"<span><i class='bi bi-hash'></i>{_esc(channel.name)}</span>")
    meta.append(ui.badge("Mehrfachwahl" if multiple else "Einfachwahl", "info"))
    if poll.get("anonymous"):
        meta.append(ui.badge("anonym", "muted"))
    if poll.get("ended"):
        meta.append(ui.badge("beendet", "muted"))
    elif poll.get("closed"):
        meta.append(ui.badge("geschlossen", "warn"))
    else:
        meta.append(ui.badge("offen", "ok"))
    if finished:
        ts = finished_ts(poll)
        if ts:
            meta.append(f"<span class='wc-muted' title='{_esc(_utc(ts))}'>endete {_esc(_rel(ts, now))}</span>")
    elif poll.get("end_ts"):
        meta.append(f"<span class='wc-muted' title='{_esc(_utc(poll['end_ts']))}'>"
                    f"<i class='bi bi-hourglass-split'></i> endet {_esc(_rel(poll['end_ts'], now))}</span>")

    # Ergebnis-Balken (wie im Embed: Anteil an allen Stimmen, 🏆 erst nach dem Ende)
    blocks = []
    for idx, opt in enumerate(options):
        c = counts[idx] if idx < len(counts) else 0
        pct = int(round((c / total) * 100)) if total else 0
        trophy = " 🏆" if finished and c == winning and c > 0 else ""
        own = (" " + ui.badge("deine Stimme", "ok")) if idx in mine else ""
        blocks.append(
            "<div class='meter'>"
            f"<div class='mlabel'><span>{idx + 1}. {_esc(opt)}{trophy}{own}</span>"
            f"<span class='v'>{c} · {pct}%</span></div>"
            f"<div class='bar'><span style='width:{pct}%'></span></div></div>"
        )
    summary = f"<div class='wc-muted' style='margin-top:12px'>{total} Stimmen · {voters} Teilnehmer</div>"
    body = (f"<div class='wc-muted'>{' &nbsp;'.join(meta)}</div><div class='wc-divider'></div>"
            f"<div class='kv'>{''.join(blocks)}</div>" + summary)

    if not finished and options:
        buttons = []
        for idx, opt in enumerate(options):
            chosen = idx in mine
            label = f"{idx + 1}. {opt}"
            short = label if len(label) <= BUTTON_LABEL_MAX else label[: BUTTON_LABEL_MAX - 1] + "…"
            if multiple:
                icon = "bi-check2-square" if chosen else "bi-square"
                title = "Auswahl entfernen" if chosen else "Auswahl hinzufügen"
            else:
                icon = "bi-check2-circle" if chosen else "bi-circle"
                title = "Stimme zurückziehen" if chosen else ("Stimme ändern" if mine else "Abstimmen")
            buttons.append(ui.button(short, icon=icon, kind="accent" if chosen else "ghost",
                                     name="option", value=str(idx),
                                     attrs={"title": f"{title}: {opt}", "aria-pressed": "true" if chosen else "false"}))
        hint = ("Tippe Optionen an, um sie hinzuzufügen oder wieder zu entfernen."
                if multiple else
                "Tippe eine Option an, um abzustimmen oder deine Stimme zu ändern. "
                "Tippst du deine gewählte Option erneut an, wird die Stimme zurückgezogen.")
        body += ui.form(
            f"/me/umfragen?guild={guild.id}",
            ui.actions(*buttons) + f"<div class='wc-help' style='margin-top:8px'>{_esc(hint)}</div>",
            csrf=csrf, hidden={"form": "vote", "guild": guild.id, "poll": pid},
        )
    elif mine:
        chosen = ", ".join(options[i] for i in sorted(mine) if 0 <= i < len(options))
        body += f"<div class='wc-help' style='margin-top:8px'>Deine Stimme: {_esc(chosen)}</div>"

    return (f"<div id='pl-{_esc(pid)}'>"
            + ui.card(poll.get("question") or "Umfrage", body, icon="bi-bar-chart")
            + "</div>")
