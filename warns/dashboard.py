"""WebCore-Dashboard für den Warns-Cog (Seite „Verwarnungen“, Slug ``warnings``).

* GET  -> Kennzahlen + Reiter Verlauf (Filter ``?filter=all``), Mitglied verwarnen,
  Automatische Maßnahmen, Einstellungen.
* POST ``form=warn|revoke|actions|settings`` -> Aktion, danach Redirect mit Toast.

Verwarnen im Dashboard: Moderator ist der angemeldete Dashboard-User; es gelten dieselben
Prüfungen wie beim Befehl (kein Bot/Owner/Server-Owner/man selbst, Rollen-Hierarchie gegenüber
dem Moderator) – das Recht dazu kommt aus WebCore: ``warn``/``revoke`` sind Tagesgeschäft
(ab Stufe „Bedienen“), ``actions``/``settings`` brauchen „Bearbeiten“ (zentral geprüft über
``register_page(operate_forms=…)``).
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime
from urllib.parse import quote_plus

from .strings import LANGUAGES, t

SLUG = "warnings"
_ACT_LABEL = {"timeout": "Timeout", "kick": "Kick", "ban": "Bann"}
_STATUS = {"active": ("aktiv", "warn"), "expired": ("abgelaufen", None), "revoked": ("aufgehoben", "info")}
_MENTION_RE = re.compile(r"^<@!?(\d{1,22})>$")
_TRAIL_ID_RE = re.compile(r"\((\d{1,22})\)\s*$")
MAX_ROWS = 500


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


def _redirect(guild_id, *, ok=None, err=None, extra="") -> dict:
    url = f"/cogs/{SLUG}?guild={guild_id}{extra}"
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


async def _dashboard_user(request):
    webcore = request.app["webcore"]
    getter = getattr(webcore, "current_user", None) or getattr(webcore, "_get_user")
    return await getter(request)


async def _get_member(guild, uid: int):
    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except Exception:  # noqa: BLE001 – kein Mitglied / keine Rechte
            member = None
    return member


async def find_member(guild, query: str):
    """Mitglied per ID, Erwähnung, „Name (ID)“ oder eindeutigem Namen. Rückgabe ``(member, fehler)``."""
    q = (query or "").strip()
    if not q:
        return None, "Bitte ein Mitglied angeben"
    m = _MENTION_RE.match(q)
    if m or q.isdigit():
        member = await _get_member(guild, int(m.group(1) if m else q))
        return (member, None) if member is not None else (None, "Mitglied nicht gefunden")
    m = _TRAIL_ID_RE.search(q)      # Vorschlag aus der Liste: „Name (ID)“
    if m:
        member = await _get_member(guild, int(m.group(1)))
        if member is not None:
            return member, None
    ql = q.lstrip("@").lower()
    hits = [mem for mem in guild.members
            if ql in {str(getattr(mem, a, "") or "").lower() for a in ("name", "display_name", "global_name")}]
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, "Name nicht eindeutig – bitte die ID verwenden"
    return None, "Mitglied nicht gefunden"


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


# --------------------------------------------------------------------------- #
#  Seite (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    from .warns import status_of

    webcore = request.app["webcore"]
    ui = webcore.ui
    guilds = await _visible(request)
    guild = _pick(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": "Verwarnungen", "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    readonly = bool(request.get("webcore_readonly"))
    show_all = request.query.get("filter") == "all"

    entries = await cog.all_entries(guild)
    now = time.time()
    active = [(uid, e) for uid, e in entries if status_of(e, now) == "active"]
    week = [e for _, e in entries if e.get("ts", 0) >= now - 7 * 86400]

    picker = ""
    if not request.get("wc_switcher"):
        picker = ui.card(body=ui.form(
            f"/cogs/{SLUG}",
            ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
            csrf="", method="get",
        ))

    auto = [a for a in ("timeout", "kick", "ban") if conf[f"{a}_at"]]
    head = ui.hero(
        "bi-exclamation-octagon", "",
        "Verwarnungen mit <b>Punkten</b>, optionalem <b>Verfall</b> und <b>automatischen Maßnahmen</b> "
        "(Timeout, Kick, Bann) ab einer Punktzahl. Befehle: <code>[p]warn</code>, <code>[p]warnings</code>, "
        "<code>[p]unwarn</code>, <code>[p]clearwarns</code>.",
    ) + ui.stats([
        ("Aktive Verwarnungen", len(active), "bi-exclamation-octagon", None, "warn" if active else None),
        ("Betroffene Mitglieder", len({uid for uid, _ in active}), "bi-people", None, None),
        ("Letzte 7 Tage", len(week), "bi-calendar-week", None, "info" if week else None),
        ("Automatische Maßnahmen", f"{len(auto)} aktiv" if auto else "Aus", "bi-lightning",
         " · ".join(f"{_ACT_LABEL[a]} ab {conf[a + '_at']}" for a in auto) or None, "ok" if auto else None),
    ])

    body = (
        ui.tab("verlauf", "Verlauf", "bi-clock-history",
               _history(ui, cog, guild, entries, csrf, readonly, show_all, now),
               count=len(active))
        + ui.tab("verwarnen", "Mitglied verwarnen", "bi-person-exclamation", _warn_form(ui, guild, conf, csrf, readonly))
        + ui.tab("massnahmen", "Automatische Maßnahmen", "bi-lightning", _actions_form(ui, cog, guild, conf, csrf))
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", _settings_form(ui, guild, conf, csrf))
    )
    return {"title": "Verwarnungen", "content": picker + head + body}


def _history(ui, cog, guild, entries, csrf, readonly, show_all, now) -> str:
    from .warns import status_of

    base = f"/cogs/{SLUG}?guild={guild.id}"
    filt = ui.actions(
        ui.button("Nur aktive", icon="bi-funnel", href=base, kind="ghost" if show_all else "accent", small=True),
        ui.button("Alle", icon="bi-list-ul", href=base + "&filter=all", kind="accent" if show_all else "ghost",
                  small=True),
    )
    rows = []
    shown = [(uid, e) for uid, e in entries if show_all or status_of(e, now) == "active"]
    for uid, e in shown[:MAX_ROWS]:
        st = status_of(e, now)
        label, tone = _STATUS[st]
        member = guild.get_member(uid)
        name = member.display_name if member is not None else (e.get("user_name") or str(uid))
        status = ui.badge(label, tone or "muted")
        if st == "revoked" and e.get("revoked_by_name"):
            status += f"<div class='wc-help'>von {_esc(e['revoked_by_name'])}</div>"
        elif e.get("expires"):
            status += f"<div class='wc-help'>{'bis' if st == 'active' else 'seit'} {_esc(_fmt_ts(e['expires']))}</div>"
        if e.get("action"):
            act = _ACT_LABEL.get(e["action"], e["action"])
            status += "<div class='wc-help'>" + _esc(act) + (" ausgeführt" if e.get("action_ok") else " nicht ausgeführt") + "</div>"
        action = ""
        if st == "active" and not readonly:
            action = ui.form(
                f"/cogs/{SLUG}", ui.button("Aufheben", icon="bi-arrow-counterclockwise", kind="danger", small=True),
                csrf=csrf, hidden={"form": "revoke", "guild": guild.id, "id": e["id"]},
                confirm=f"Verwarnung #{e['id']} von {name} aufheben?",
            )
        rows.append(ui.row(
            f"<span class='mono'>#{_esc(e['id'])}</span>",
            f"<b>{_esc(name)}</b><div class='wc-help mono'>{_esc(uid)}</div>",
            _esc(e.get("reason") or "—"),
            ">" + _esc(e.get("points", 1)),
            _esc(e.get("mod_name") or "—"),
            _esc(_fmt_ts(e.get("ts"))),
            status,
            ">" + action,
        ))
    more = ""
    if len(shown) > MAX_ROWS:
        more = ui.callout(f"Es werden die neuesten {MAX_ROWS} von {len(shown)} Einträgen gezeigt.", tone="info")
    table = ui.table(["#", "Mitglied", "Grund", ">Punkte", "Moderator", "Datum", "Status", ">Aktion"], rows,
                     empty_text="Keine aktiven Verwarnungen." if not show_all else "Noch keine Verwarnungen.",
                     search=True, search_placeholder="Mitglied, Grund, Moderator …", id="wl-warn-table")
    return ui.card("Verlauf", filt + table + more, icon="bi-clock-history",
                   desc="Aufheben zählt die Verwarnung nicht mehr mit (bleibt im Verlauf). "
                        "Endgültig löschen: <code>[p]clearwarns</code>.")


def _warn_form(ui, guild, conf, csrf, readonly) -> str:
    from .warns import MAX_POINTS, MAX_REASON

    members = sorted((m for m in guild.members if not getattr(m, "bot", False)),
                     key=lambda m: m.display_name.lower())[:500]
    datalist = "<datalist id='wl-members'>" + "".join(
        f"<option value='{_esc(m.display_name)} ({m.id})'></option>" for m in members) + "</datalist>"
    note = ""
    if readonly:
        note = ui.callout("Du hast auf dieser Seite nur <b>Ansehen</b> – verwarnen und aufheben erfordert "
                          "mindestens <b>Bedienen</b>.", tone="info")
    expiry = f"{conf['expiry_days']} Tage" if conf["expiry_days"] else "nie"
    body = ui.grid(
        ui.field("Mitglied", ui.text_input("member", "", placeholder="Name, @Erwähnung oder ID",
                                           attrs={"list": "wl-members", "required": True, "autocomplete": "off"}),
                 help="Tippen für Vorschläge. Bei gleichen Namen die ID verwenden.", wide=True),
        ui.field("Grund", ui.textarea("reason", "", rows=3, placeholder="z. B. Spam im Chat"),
                 help=f"Pflichtfeld, max. {MAX_REASON} Zeichen. Erscheint im Log und in der DM.", wide=True),
        ui.field("Punkte", ui.number("points", conf["default_points"], min=1, max=MAX_POINTS, unit="Pkt."),
                 help=f"Standard: {conf['default_points']}. Verfall: {expiry}."),
    ) + datalist + ui.actions(ui.button("Verwarnen", icon="bi-exclamation-octagon"))
    form = ui.form(f"/cogs/{SLUG}", body, csrf=csrf, hidden={"form": "warn", "guild": guild.id},
                   confirm="Mitglied jetzt verwarnen? DM, Log und ggf. automatische Maßnahmen werden ausgelöst.")
    return note + ui.card(
        "Mitglied verwarnen", form, icon="bi-person-exclamation",
        desc="Du bist der Moderator. Es gelten dieselben Regeln wie bei <code>[p]warn</code>: keine Bots, "
             "kein Bot-/Server-Owner, nicht du selbst und nur Mitglieder <b>unter</b> deiner höchsten Rolle.",
    )


def _actions_form(ui, cog, guild, conf, csrf) -> str:
    from .warns import MAX_POINTS, MAX_TIMEOUT_MIN

    me = guild.me
    warn = []
    if me is not None:
        perms = me.guild_permissions
        for key, perm, label in (("timeout", "moderate_members", "Mitglieder im Timeout"),
                                 ("kick", "kick_members", "Mitglieder kicken"),
                                 ("ban", "ban_members", "Mitglieder bannen")):
            if conf[f"{key}_at"] and not (getattr(perms, perm, False) or getattr(perms, "administrator", False)):
                warn.append(ui.callout(f"{_ACT_LABEL[key]} ist aktiv, aber mir fehlt das Recht <b>{label}</b>.",
                                       tone="bad"))
    body = ui.grid(
        ui.field("Timeout ab", ui.number("timeout_at", conf["timeout_at"], min=0, max=MAX_POINTS, unit="Punkten"),
                 help="0 = aus."),
        ui.field("Timeout-Dauer", ui.number("timeout_minutes", conf["timeout_minutes"], min=1, max=MAX_TIMEOUT_MIN,
                                            unit="Min."),
                 help="Max. 40320 Minuten (28 Tage)."),
        ui.field("Kick ab", ui.number("kick_at", conf["kick_at"], min=0, max=MAX_POINTS, unit="Punkten"),
                 help="0 = aus."),
        ui.field("Bann ab", ui.number("ban_at", conf["ban_at"], min=0, max=MAX_POINTS, unit="Punkten"),
                 help="0 = aus."),
    ) + ui.save_row()
    return "".join(warn) + ui.card(
        "Automatische Maßnahmen",
        ui.form(f"/cogs/{SLUG}", body, csrf=csrf, hidden={"form": "actions", "guild": guild.id}, savebar=True),
        icon="bi-lightning",
        desc="Wird eine Schwelle durch eine neue Verwarnung <b>erreicht</b>, führe ich die schwerste passende "
             "Maßnahme aus. Nie gegen Bot-Owner, Server-Owner oder Mitglieder mit gleich hoher/höherer Rolle als "
             "ich bzw. der Moderator; Administratoren bekommen keinen Timeout. Ergebnis steht im Log.",
    )


def _settings_form(ui, guild, conf, csrf) -> str:
    from .warns import MAX_DM_TEXT, MAX_EXPIRY_DAYS, MAX_POINTS

    roles = [(r.id, r.name, f"#{r.color.value:06x}" if getattr(r, "color", None) and r.color.value else None)
             for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()]
    lang = conf.get("language") or "de"
    body = ui.card("Allgemein", ui.grid(
        ui.field("Log-Kanal", ui.select("log_channel", [(c.id, f"#{c.name}") for c in guild.text_channels],
                                        conf["log_channel"], none_label="— kein Log —"),
                 help="Jede Verwarnung, Aufhebung und Löschung als Embed (braucht „Links einbetten“)."),
        ui.field("Mod-Rollen", ui.select("mod_roles", roles, conf["mod_roles"], multiple=True,
                                         placeholder="Rollen suchen …"),
                 help="Dürfen zusätzlich zu „Mitglieder kicken“ verwarnen, Verläufe sehen und aufheben.", wide=True),
        ui.field("Verfall", ui.number("expiry_days", conf["expiry_days"], min=0, max=MAX_EXPIRY_DAYS, unit="Tage"),
                 help="0 = nie. Gilt für neu erstellte Verwarnungen."),
        ui.field("Standard-Punkte", ui.number("default_points", conf["default_points"], min=1, max=MAX_POINTS,
                                              unit="Pkt."),
                 help="Wenn bei <code>[p]warn</code> keine Zahl angegeben ist."),
        ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf["language"]),
                 help="Sprache von Antworten, DM und Log."),
    ), icon="bi-sliders", desc="Log, Rechte und Verfall.")
    dm = ui.card("DM an Verwarnte", ui.grid(
        ui.field("Status", ui.switch("dm_enabled", "Verwarnten Mitgliedern eine DM schicken", conf["dm_enabled"],
                                     desc="Geschlossene DMs werden übersprungen (Hinweis beim Befehl)."), wide=True),
        ui.field("Text", ui.textarea("dm_text", conf["dm_text"], rows=5, placeholder=t(lang, "dm_default")),
                 help=f"Leer = Standardtext. Max. {MAX_DM_TEXT} Zeichen. Platzhalter: <code>{{user}}</code> "
                      "<code>{name}</code> <code>{server}</code> <code>{reason}</code> <code>{points}</code> "
                      "<code>{total}</code> <code>{id}</code> <code>{moderator}</code> <code>{expires}</code>",
                 wide=True),
    ), icon="bi-envelope", desc="Bei automatischen Maßnahmen wird die Maßnahme ergänzt.")
    return ui.form(f"/cogs/{SLUG}", body + dm + ui.save_row(), csrf=csrf,
                   hidden={"form": "settings", "guild": guild.id}, savebar=True)


# --------------------------------------------------------------------------- #
#  POST
# --------------------------------------------------------------------------- #
def _int(value, lo, hi):
    try:
        v = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


async def _handle_post(cog, request):
    from .warns import MAX_DM_TEXT, MAX_EXPIRY_DAYS, MAX_POINTS, MAX_REASON, MAX_TIMEOUT_MIN, Actor

    data = await request.post()
    guild = _pick(await _visible(request), data.get("guild"))
    if guild is None:
        return {"redirect": f"/cogs/{SLUG}?err=" + quote_plus("Server nicht gefunden oder keine Bearbeitungsrechte")}
    form = data.get("form")
    gconf = cog.config.guild(guild)
    lang = await gconf.language()

    if form in ("warn", "revoke"):
        user = await _dashboard_user(request)
        if not user:
            return _redirect(guild.id, err="Nicht angemeldet")
        uid = int(user["id"])
        moderator = await _get_member(guild, uid)
        if moderator is None:
            if uid in (cog.bot.owner_ids or set()):
                moderator = Actor(uid, user.get("name") or str(uid), owner=True)
            else:
                return _redirect(guild.id, err="Du bist kein Mitglied dieses Servers")

        if form == "revoke":
            wid = _int(data.get("id"), 1, 10**9)
            if wid is None:
                return _redirect(guild.id, err="Ungültige ID")
            err, target_id, _entry, total = await cog.revoke(guild, wid, moderator)
            if err:
                return _redirect(guild.id, err=t(lang, err, id=wid))
            return _redirect(guild.id, ok=f"Verwarnung #{wid} aufgehoben – aktive Punkte: {total}")

        target, err = await find_member(guild, data.get("member") or "")
        if target is None:
            return _redirect(guild.id, err=err)
        key = cog.check_target(guild, moderator, target)
        if key:
            return _redirect(guild.id, err=t(lang, key, user=target.display_name))
        reason = (data.get("reason") or "").replace("\r\n", "\n").strip()
        if not reason or len(reason) > MAX_REASON:
            return _redirect(guild.id, err=f"Bitte einen Grund angeben (max. {MAX_REASON} Zeichen)")
        points = _int(data.get("points") or await gconf.default_points(), 1, MAX_POINTS)
        if points is None:
            return _redirect(guild.id, err=f"Punkte müssen zwischen 1 und {MAX_POINTS} liegen")
        res = await cog.add_warning(guild, target, moderator, reason, points, source="dashboard")
        msg = f"Verwarnung #{res['id']} für {target.display_name} – aktive Punkte: {res['total']}"
        if res["action"]:
            if res["action_ok"]:
                msg += f" · Maßnahme: {res['action']}"
            else:
                return _redirect(guild.id, err=msg + f" · {res['action']} nicht ausgeführt: {res['action_why']}")
        if res["dm_ok"] is False:
            msg += " · DM nicht zugestellt"
        return _redirect(guild.id, ok=msg)

    if form == "actions":
        vals = {}
        for key in ("timeout_at", "kick_at", "ban_at"):
            v = _int(data.get(key) or 0, 0, MAX_POINTS)
            if v is None:
                return _redirect(guild.id, err=f"Schwellen: 0 (aus) bis {MAX_POINTS} Punkte")
            vals[key] = v
        minutes = _int(data.get("timeout_minutes"), 1, MAX_TIMEOUT_MIN)
        if minutes is None:
            return _redirect(guild.id, err=f"Timeout-Dauer: 1 bis {MAX_TIMEOUT_MIN} Minuten")
        vals["timeout_minutes"] = minutes
        for key, v in vals.items():
            await gconf.set_raw(key, value=v)
        return _redirect(guild.id, ok="Automatische Maßnahmen gespeichert")

    if form == "settings":
        raw = (data.get("log_channel") or "").strip()
        log_channel = None
        if raw:
            ch = next((c for c in guild.text_channels if raw.isdigit() and c.id == int(raw)), None)
            if ch is None:
                return _redirect(guild.id, err="Kanal nicht gefunden")
            log_channel = ch.id
        role_ids = []
        for r in data.getall("mod_roles", []):
            role = guild.get_role(int(r)) if str(r).isdigit() else None
            if role is None or role.is_default():
                return _redirect(guild.id, err="Rolle nicht gefunden")
            role_ids.append(role.id)
        expiry = _int(data.get("expiry_days") or 0, 0, MAX_EXPIRY_DAYS)
        if expiry is None:
            return _redirect(guild.id, err=f"Verfall: 0 (nie) bis {MAX_EXPIRY_DAYS} Tage")
        points = _int(data.get("default_points"), 1, MAX_POINTS)
        if points is None:
            return _redirect(guild.id, err=f"Standard-Punkte: 1 bis {MAX_POINTS}")
        dm_text = (data.get("dm_text") or "").replace("\r\n", "\n").strip()
        if len(dm_text) > MAX_DM_TEXT:
            return _redirect(guild.id, err=f"DM-Text zu lang (max. {MAX_DM_TEXT} Zeichen)")
        language = data.get("language") or "de"
        if language not in LANGUAGES:
            return _redirect(guild.id, err="Unbekannte Sprache")
        await gconf.log_channel.set(log_channel)
        await gconf.mod_roles.set(sorted(set(role_ids)))
        await gconf.expiry_days.set(expiry)
        await gconf.default_points.set(points)
        await gconf.dm_enabled.set(bool(data.get("dm_enabled")))
        await gconf.dm_text.set(dm_text)
        await gconf.language.set(language)
        return _redirect(guild.id, ok="Einstellungen gespeichert")

    return _redirect(guild.id, err="Unbekannte Aktion")
