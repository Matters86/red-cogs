"""WebCore-Dashboard „Statistik“ für den ServerStats-Cog.

* GET  ``/cogs/serverstats?guild=<id>&range=7|30|90``        -> Seite (Übersicht, Kanäle, Einstellungen)
* GET  ``…&export=days``                                     -> CSV je Tag
* GET  ``…&export=channels``                                 -> CSV je Kanal (Summe im Zeitraum)
* POST ``form=settings`` (Aufbewahrung, Zeitzone, ignorierte Kanäle, Sprache) · ``form=reset`` (alle Tage löschen)

Alle Tage (Diagramm-Achsen, Tabellen, CSV-Spalte ``datum``) sind Kalendertage in der Zeitzone des Servers.

Nur UI-Kit von WebCore, Diagramme als Inline-SVG (``charts.py``). Rechte: Server über
``visible_guilds`` (GET = Ansehen, POST = Bearbeiten).
"""

from __future__ import annotations

import csv
import io
import logging
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus, urlencode

import discord
from aiohttp import web

from . import charts
from .strings import LANGUAGES

log = logging.getLogger("red.red-cogs.serverstats")

SLUG = "serverstats"
TITLE = "Statistik"


def _redirect(guild_id, *, ok: str | None = None, err: str | None = None, rng: int | None = None) -> dict:
    url = f"/cogs/{SLUG}?guild={guild_id}"
    if rng:
        url += f"&range={rng}"
    if ok:
        url += "&ok=" + quote_plus(ok)
    if err:
        url += "&err=" + quote_plus(err)
    return {"redirect": url}


async def _visible(request):
    webcore = request.app["webcore"]
    return sorted(await webcore.visible_guilds(request), key=lambda g: g.name.lower())


def _pick(guilds, raw):
    if raw and str(raw).isdigit():
        return next((g for g in guilds if g.id == int(raw)), None)
    return None


def _range(request) -> int:
    from .serverstats import RANGES
    raw = request.query.get("range", "")
    return int(raw) if raw.isdigit() and int(raw) in RANGES else 30


def _date_window(request, today):
    start_raw, end_raw = request.query.get("start"), request.query.get("end")
    if not start_raw and not end_raw:
        return today - timedelta(days=_range(request) - 1), today
    try:
        start, end = date.fromisoformat(start_raw or ""), date.fromisoformat(end_raw or "")
    except ValueError:
        raise ValueError("Bitte Start- und Enddatum vollständig angeben (JJJJ-MM-TT).") from None
    if start > end or end > today or (end - start).days >= 730:
        raise ValueError("Wähle einen Zeitraum von 1 bis 730 Tagen bis einschließlich heute.")
    if start < date.min + timedelta(days=(end - start).days + 1):
        raise ValueError("Für diesen Zeitraum lässt sich kein vorheriger Vergleichszeitraum bilden.")
    return start, end


def _short(day: str) -> str:
    return f"{day[8:10]}.{day[5:7]}."


def _long(day: str) -> str:
    return f"{day[8:10]}.{day[5:7]}.{day[0:4]}"


def _channel_items(guild):
    items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    items += [(c.id, f"🔊 {c.name}") for c in guild.voice_channels]
    return items


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    if request.query.get("export") in ("days", "channels", "csv"):
        return await _export(cog, request)
    return await _render(cog, request)


# --------------------------------------------------------------------------- #
#  Kacheln aus anderen Cogs (nur lesend, robust wenn nicht geladen)
# --------------------------------------------------------------------------- #
async def other_tiles(bot, guild, tz=timezone.utc) -> list[tuple]:
    tiles = []
    tickets = bot.get_cog("Tickets")
    if tickets is not None and getattr(tickets, "config", None) is not None:
        try:
            data = await tickets.config.guild(guild).tickets()
            n = sum(1 for r in (data or {}).values() if isinstance(r, dict) and r.get("status") == "open")
            tiles.append(("Offene Tickets", n, "bi-life-preserver", "aus dem Ticket-System", "warn" if n else None))
        except Exception:  # noqa: BLE001 – fremder Cog, andere Version …
            log.debug("ServerStats: Tickets nicht lesbar", exc_info=True)
    raids = bot.get_cog("RaidHelper")
    if raids is not None and getattr(raids, "config", None) is not None:
        try:
            events = await raids.config.guild(guild).events()
            now = time.time()
            upcoming = sorted((e.get("start_ts") or 0) for e in (events or {}).values()
                              if isinstance(e, dict) and not e.get("completed") and (e.get("start_ts") or 0) > now)
            hint = None
            if upcoming:
                nxt = datetime.fromtimestamp(upcoming[0], tz)
                hint = "nächster: " + nxt.strftime("%d.%m. %H:%M ") + (nxt.tzname() or "")
            tiles.append(("Kommende Raids", len(upcoming), "bi-calendar-event", hint, "info" if upcoming else None))
        except Exception:  # noqa: BLE001
            log.debug("ServerStats: Raids nicht lesbar", exc_info=True)
    return tiles


# --------------------------------------------------------------------------- #
#  Seite (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    webcore = request.app["webcore"]
    ui = webcore.ui
    guilds = await _visible(request)
    guild = _pick(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": TITLE, "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    tz = await cog.guild_tz(guild)
    today = datetime.fromtimestamp(cog._clock(), tz).date()
    period_error = ""
    try:
        start, end = _date_window(request, today)
    except ValueError as exc:
        start, end = today - timedelta(days=29), today
        period_error = ui.callout(ui.esc(str(exc)) + " Angezeigt werden vorerst die letzten 30 Tage.", tone="bad")
    rng = (end - start).days + 1
    data = await cog.get_period(guild, start, end)
    s = cog.summarize(data)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=rng - 1)
    previous = cog.summarize(await cog.get_period(guild, previous_start, previous_end))
    period_label = f"{_long(start.isoformat())} bis {_long(end.isoformat())}"
    period_caption = period_label if request.query.get("start") or request.query.get("end") else f"letzte {rng} Tage"
    labels = [_short(d) for d, _ in data]

    picker = ""
    if not request.get("wc_switcher"):
        picker = ui.card(body=ui.form(
            f"/cogs/{SLUG}",
            ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
            csrf="", method="get", hidden={"range": rng},
        ))

    base = f"/cogs/{SLUG}?guild={guild.id}"
    period_query = urlencode({"start": start.isoformat(), "end": end.isoformat()})
    range_btns = "".join(
        ui.button(f"{n} Tage", kind="accent" if n == rng else "ghost", small=True, href=f"{base}&range={n}",
                  attrs={"aria-current": "true" if n == rng else None})
        for n in (7, 30, 90)
    )
    export_btns = (
        ui.button("CSV je Tag", icon="bi-download", kind="ghost", small=True, href=f"{base}&{period_query}&export=days")
        + ui.button("CSV je Kanal", icon="bi-download", kind="ghost", small=True,
                    href=f"{base}&{period_query}&export=channels")
    )
    head = ui.hero(
        "bi-graph-up", "",
        f"Aktivität auf <b>{ui.esc(guild.name)}</b> – nur Zählungen, keine Inhalte und keine Personendaten. "
        f"Tage nach Zeitzone <b>{ui.esc(tz.key)}</b> (Mitternacht zu Mitternacht).",
        actions=range_btns,
    )
    net = s["net"]
    period_form = ui.form(f"/cogs/{SLUG}", ui.grid(
        ui.field("Von", ui.text_input("start", request.query.get("start") or start.isoformat(), type="date")),
        ui.field("Bis", ui.text_input("end", request.query.get("end") or end.isoformat(), type="date",
                                     attrs={"max": today.isoformat()})),
    ) + ui.button("Zeitraum anzeigen", icon="bi-calendar-range"), method="get", csrf="", hidden={"guild": guild.id})
    period_card = ui.card("Zeitraum", period_error + period_form, desc=period_label)
    kpis = ui.stats([
        ("Mitglieder", charts.fmt_num(s["members"]), "bi-people", "aktuell" if end == today else f"Stand {_long(end.isoformat())}", None),
        ("Netto-Wachstum", f"{net:+d}", "bi-person-plus", f"{s['joins']} rein · {s['leaves']} raus",
         "ok" if net > 0 else ("bad" if net < 0 else None)),
        ("Nachrichten", charts.fmt_num(s["messages"]), "bi-chat-dots", f"Ø {charts.fmt_num(round(s['messages'] / rng, 1))} pro Tag", None),
        ("Voice-Stunden", charts.fmt_num(round(s["voice_hours"], 1)), "bi-mic", "ohne AFK-Kanal", None),
    ])
    tiles = await other_tiles(cog.bot, guild, tz)
    extra = ui.stats(tiles) if tiles else ""

    # --- Diagramme ---
    members = [r["members"] for _, r in data]
    member_svg = charts.line_chart(labels, members, label=f"Mitglieder, {period_caption}",
                                   tips=[f"{_long(d)}: {charts.fmt_num(r['members'])} Mitglieder"
                                         if r["members"] is not None else "" for d, r in data])
    joins = [r["joins"] for _, r in data]
    leaves = [r["leaves"] for _, r in data]
    jl_svg = charts.diverging_chart(labels, joins, leaves, label=f"Beitritte und Abgänge, {period_caption}",
                                    tips=[f"{_long(d)}: {r['joins']} Beitritte, {r['leaves']} Abgänge "
                                          f"(netto {r['joins'] - r['leaves']:+d})" for d, r in data])
    msgs = [sum(r["messages"].values()) for _, r in data]
    msg_svg = charts.bar_chart(labels, msgs, label=f"Nachrichten pro Tag, {period_caption}",
                               tips=[f"{_long(d)}: {charts.fmt_num(v)} Nachrichten" for (d, _), v in zip(data, msgs)])
    voice = [round(sum(r["voice_sec"].values()) / 3600, 1) for _, r in data]
    voice_svg = charts.bar_chart(labels, voice, label=f"Voice-Stunden pro Tag, {period_caption}",
                                 tips=[f"{_long(d)}: {charts.fmt_num(v)} Voice-Stunden" for (d, _), v in zip(data, voice)],
                                 color=charts.C_AMBER)
    top_msg = sorted(s["by_channel_messages"].items(), key=lambda kv: -kv[1])[:10]
    top_voice = sorted(s["by_channel_voice"].items(), key=lambda kv: -kv[1])[:10]
    top_msg_svg = charts.hbar_chart([("#" + cog.channel_name(guild, c), v) for c, v in top_msg],
                                    label="Top-10-Textkanäle nach Nachrichten", unit="Nachrichten")
    top_voice_svg = charts.hbar_chart(
        [(cog.channel_name(guild, c), round(v / 3600, 1)) for c, v in top_voice],
        label="Top-10-Sprachkanäle nach Voice-Stunden", unit="Std.", color=charts.C_AMBER)

    legend = (f"<span style='color:{charts.C_ACCENT}'>■</span> Beitritte · "
              f"<span style='color:{charts.C_DANGER}'>■</span> Abgänge")
    overview = (
        period_card
        + ui.card("Vergleich mit vorherigem Zeitraum", ui.table(
            ["Kennzahl", "Gewählt", "Vorher", "Änderung"], [ui.row(label, str(current), str(old), f"{current - old:+g}")
            for label, current, old in (("Nachrichten", s["messages"], previous["messages"]),
                                       ("Voice-Stunden", round(s["voice_hours"], 1), round(previous["voice_hours"], 1)),
                                       ("Beitritte", s["joins"], previous["joins"]),
                                       ("Abgänge", s["leaves"], previous["leaves"]))]),
                  desc=f"Vorher: {_long(previous_start.isoformat())} bis {_long(previous_end.isoformat())}. "
                       "Verglichen werden vorhandene Zählungen; außerhalb der Aufbewahrungszeit fehlen Daten.")
        +
        ui.columns(
            ui.card("Mitglieder", member_svg, icon="bi-people", desc="Mitgliederzahl am Tagesende."),
            ui.card("Beitritte & Abgänge", jl_svg, icon="bi-arrow-left-right", desc=legend),
        )
        + ui.columns(
            ui.card("Nachrichten pro Tag", msg_svg, icon="bi-chat-dots", desc="Ohne Bots und Webhooks."),
            ui.card("Voice-Stunden pro Tag", voice_svg, icon="bi-mic", desc="Zeit in Sprachkanälen, ohne AFK-Kanal."),
        )
        + ui.columns(
            ui.card("Top-10-Textkanäle", top_msg_svg, icon="bi-hash", desc=f"Nachrichten, {period_caption}."),
            ui.card("Top-10-Sprachkanäle", top_voice_svg, icon="bi-volume-up", desc=f"Voice-Stunden, {period_caption}."),
        )
        + ui.card("Export", ui.actions(export_btns, f"<span class='wc-help'>Zeitraum: {period_caption}.</span>"),
                  icon="bi-filetype-csv", desc="Rohdaten als CSV (UTF-8, Komma-getrennt) – z. B. für Excel.")
    )

    # --- Kanäle (Tabelle) ---
    rows = []
    cids = set(s["by_channel_messages"]) | set(s["by_channel_voice"])
    for cid in sorted(cids, key=lambda c: (-s["by_channel_messages"].get(c, 0), -s["by_channel_voice"].get(c, 0))):
        ch = guild.get_channel(int(cid)) if cid.isdigit() else None
        name = (("🔊 " if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)) else "#") + ch.name) if ch else f"gelöscht ({cid})"
        rows.append(ui.row(
            ui.esc(name),
            ">" + charts.fmt_num(s["by_channel_messages"].get(cid, 0)),
            ">" + charts.fmt_num(round(s["by_channel_voice"].get(cid, 0) / 3600, 1)),
        ))
    channels = ui.card(f"Alle Kanäle ({rng} Tage)", ui.table(["Kanal", ">Nachrichten", ">Voice-Std."], rows, search=True,
                                                                 empty_text="Noch keine Aktivität gezählt.",
                                                                 id="ss-channels"),
                       icon="bi-list-ol", desc="Summen im gewählten Zeitraum. Ignorierte Kanäle werden nicht gezählt.")

    # --- Einstellungen ---
    from .serverstats import COMMON_TIMEZONES, MAX_RETENTION, MIN_RETENTION
    tz_name = conf.get("timezone") or tz.key
    local_now = datetime.fromtimestamp(cog._clock(), tz).strftime("%d.%m.%Y, %H:%M")
    tz_list = "<datalist id='ss-timezones'>" + "".join(
        f"<option value='{ui.esc(z)}'></option>" for z in COMMON_TIMEZONES) + "</datalist>"
    ignored = [int(c) for c in conf.get("ignored_channels") or []]
    settings = ui.form(
        f"/cogs/{SLUG}",
        ui.card("Erfassung", ui.grid(
            ui.field("Aufbewahrung", ui.number("retention_days", conf["retention_days"], min=MIN_RETENTION,
                                               max=MAX_RETENTION, unit="Tage"),
                     help=f"Ältere Tage werden stündlich automatisch gelöscht ({MIN_RETENTION}–{MAX_RETENTION}, Standard 90)."),
            ui.field("Zeitzone", ui.text_input("timezone", tz_name, placeholder="Europe/Berlin",
                                               attrs={"list": "ss-timezones", "autocomplete": "off",
                                                      "spellcheck": "false"}) + tz_list,
                     help="IANA-Name, z. B. <code>Europe/Berlin</code>, <code>Europe/Vienna</code>, <code>UTC</code> "
                          f"(Vorschläge beim Tippen). Jetzt dort: {ui.esc(local_now)}. Tage laufen von Mitternacht "
                          "zu Mitternacht dieser Zeitzone (Sommerzeit inklusive); ein Wechsel gilt ab dann."),
            ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf["language"]),
                     help="Sprache von <code>[p]stats</code>."),
            ui.field("Ignorierte Kanäle", ui.select("ignored", _channel_items(guild), ignored, multiple=True,
                                                    placeholder="Kanäle suchen …"),
                     help="Nachrichten und Voice-Zeit in diesen Kanälen werden nicht gezählt (z. B. Bot-Spam).",
                     wide=True),
        ) + ui.save_row(), icon="bi-sliders", desc="Was gezählt wird und wie lange es aufbewahrt wird."),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id, "range": rng}, savebar=True,
    )
    privacy = ui.card("Datenschutz", ui.callout(
        "Gespeichert werden nur <b>Tages-Summen je Kanal</b> (Beitritte, Abgänge, Mitgliederzahl, Anzahl Nachrichten, "
        "Voice-Sekunden). Keine Nachrichteninhalte, keine Nutzer-IDs. Wer gerade in Voice sitzt, steht nur im "
        "Arbeitsspeicher, bis die Sitzung endet.", tone="info"), icon="bi-shield-lock")
    reset = ui.card("Statistik zurücksetzen", ui.form(
        f"/cogs/{SLUG}",
        ui.actions(ui.button("Alle Statistikdaten löschen", icon="bi-trash", kind="danger"),
                   "<span class='wc-help'>Löscht alle gespeicherten Tage dieses Servers. Einstellungen bleiben.</span>"),
        csrf=csrf, hidden={"form": "reset", "guild": guild.id, "range": rng},
        confirm=f"Wirklich alle Statistikdaten von {guild.name} löschen? Das lässt sich nicht rückgängig machen.",
    ), icon="bi-exclamation-octagon", tone="bad")

    body = (
        ui.tab("uebersicht", "Übersicht", "bi-graph-up", overview)
        + ui.tab("kanaele", "Kanäle", "bi-hash", channels, count=len(rows) or None)
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", settings + privacy + reset)
    )
    return {"title": TITLE, "content": picker + head + kpis + extra + body}


# --------------------------------------------------------------------------- #
#  CSV-Export
# --------------------------------------------------------------------------- #
def _cell(value) -> str:
    """Schutz vor Formel-Injection in Tabellenprogrammen."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


async def _export(cog, request):
    guild = _pick(await _visible(request), request.query.get("guild"))
    if guild is None:
        raise web.HTTPNotFound(text="Server nicht gefunden")
    tz = await cog.guild_tz(guild)
    try:
        start, end = _date_window(request, datetime.fromtimestamp(cog._clock(), tz).date())
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    data = await cog.get_period(guild, start, end)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    kind = request.query.get("export")
    if kind == "channels":
        s = cog.summarize(data)
        w.writerow(["kanal_id", "kanal", "nachrichten", "voice_minuten"])
        for cid in sorted(set(s["by_channel_messages"]) | set(s["by_channel_voice"])):
            w.writerow([cid, _cell(cog.channel_name(guild, cid)), s["by_channel_messages"].get(cid, 0),
                        round(s["by_channel_voice"].get(cid, 0) / 60, 1)])
        name = f"statistik-kanaele-{guild.id}-{start}-{end}.csv"
    else:
        w.writerow(["datum", "beitritte", "abgaenge", "netto", "mitglieder", "nachrichten", "voice_minuten"])
        for d, r in data:
            w.writerow([d, r["joins"], r["leaves"], r["joins"] - r["leaves"],
                        "" if r["members"] is None else r["members"],
                        sum(r["messages"].values()), round(sum(r["voice_sec"].values()) / 60, 1)])
        name = f"statistik-{guild.id}-{start}-{end}.csv"
    body = ("﻿" + buf.getvalue()).encode("utf-8")
    return web.Response(body=body, content_type="text/csv", charset="utf-8",
                        headers={"Content-Disposition": f"attachment; filename=\"{name}\"",
                                 "Cache-Control": "no-store"})


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    from .serverstats import MAX_RETENTION, MIN_RETENTION, RANGES, valid_tz

    data = await request.post()
    guild = _pick(await _visible(request), data.get("guild"))
    if guild is None:
        return {"redirect": f"/cogs/{SLUG}?err=" + quote_plus("Server nicht gefunden oder keine Bearbeitungsrechte")}
    raw_rng = data.get("range") or ""
    rng = int(raw_rng) if raw_rng.isdigit() and int(raw_rng) in RANGES else None
    form = data.get("form")
    gconf = cog.config.guild(guild)
    if form == "settings":
        try:
            keep = int(data.get("retention_days") or "")
        except ValueError:
            return _redirect(guild.id, err="Aufbewahrung muss eine Zahl sein", rng=rng)
        if not MIN_RETENTION <= keep <= MAX_RETENTION:
            return _redirect(guild.id, err=f"Aufbewahrung: {MIN_RETENTION}–{MAX_RETENTION} Tage", rng=rng)
        lang = data.get("language") or "de"
        if lang not in LANGUAGES:
            return _redirect(guild.id, err="Unbekannte Sprache", rng=rng)
        tz_raw = data.get("timezone")
        tz_name = (tz_raw if tz_raw is not None else await gconf.timezone()).strip()
        if not valid_tz(tz_name):
            return _redirect(guild.id, err=f"Unbekannte Zeitzone: {tz_name[:60]}", rng=rng)
        valid = {c.id for c in guild.text_channels} | {c.id for c in guild.voice_channels}
        ignored = []
        for raw in data.getall("ignored", []):
            if not str(raw).isdigit() or int(raw) not in valid:
                return _redirect(guild.id, err="Kanal nicht gefunden", rng=rng)
            if int(raw) not in ignored:
                ignored.append(int(raw))
        await gconf.retention_days.set(keep)
        await gconf.language.set(lang)
        await gconf.timezone.set(tz_name)
        await gconf.ignored_channels.set(ignored)
        cog.invalidate(guild.id)
        for k in [k for k, sess in cog._voice.items() if k[0] == guild.id and sess[0] in ignored]:
            cog._voice.pop(k, None)
        return _redirect(guild.id, ok="Einstellungen gespeichert", rng=rng)
    if form == "reset":
        async with cog._lock:
            await gconf.days.set({})
            cog._pending.pop(guild.id, None)
            cog._members_written.pop(guild.id, None)
        return _redirect(guild.id, ok="Statistik zurückgesetzt", rng=rng)
    return _redirect(guild.id, err="Unbekannte Aktion", rng=rng)
