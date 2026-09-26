"""WebCore-Dashboard „Level“ für den Levels-Cog (Team-Seite).

* GET  ``/cogs/levels?guild=<id>`` -> Reiter Rangliste (mit Suche), Belohnungen, Einstellungen, XP anpassen
* POST ``form=settings|reward_add|reward_del|stack|sync|mult_add|mult_del|xp`` -> speichern, danach
  Redirect (Post/Redirect/Get) mit Toast.

Nur UI-Kit von WebCore, kein eigenes CSS. Rechte: Server über ``visible_guilds`` (GET = Ansehen,
POST = Bearbeiten). Belohnungsrollen werden vor dem Speichern mit ``webcore.can_grant_role``
(Schutz vor Selbst-Hochstufung) und gegen die Bot-Hierarchie geprüft.
"""

from __future__ import annotations

import html
from urllib.parse import quote_plus

from .strings import LANGUAGES, t

SLUG = "levels"
TITLE = "Level"

_MODE_LABELS = [("off", "Aus – keine Meldung"), ("same", "Im selben Kanal wie die Nachricht"),
                ("channel", "In einem festen Kanal"), ("dm", "Per DM an das Mitglied")]
_PH_HELP = ("Platzhalter: <code>{user}</code> Erwähnung (pingt nur das Mitglied) · <code>{name}</code> Name · "
            "<code>{level}</code> neues Level · <code>{server}</code> Server")


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _num(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _redirect(guild_id, *, ok: str | None = None, err: str | None = None) -> dict:
    url = f"/cogs/{SLUG}?guild={guild_id}"
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


def _role_items(guild):
    roles = [r for r in guild.roles if not r.is_default() and not getattr(r, "managed", False)]
    roles.sort(key=lambda r: -r.position)
    out = []
    for r in roles:
        color = getattr(getattr(r, "color", None), "value", 0) or 0
        out.append((r.id, f"@{r.name}", f"#{color:06x}") if color else (r.id, f"@{r.name}"))
    return out


def _channel_items(guild, voice: bool = True):
    items = [(c.id, f"#{c.name}") for c in guild.text_channels]
    if voice:
        items += [(c.id, f"🔊 {c.name}") for c in guild.voice_channels]
    return items


def resolve_member(guild, raw: str):
    """Mitglied aus ID, Erwähnung oder eindeutigem (Anzeige-)Namen. Rückgabe ``(member, fehler)``."""
    raw = (raw or "").strip()
    if not raw:
        return None, "Bitte ein Mitglied angeben"
    digits = raw.strip("<@!>")
    if digits.isdigit():
        m = guild.get_member(int(digits))
        return (m, None) if m else (None, "Mitglied nicht gefunden")
    low = raw.lstrip("@").lower()
    hits = [m for m in guild.members
            if (getattr(m, "display_name", "") or "").lower() == low or (getattr(m, "name", "") or "").lower() == low]
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, "Name ist nicht eindeutig – bitte die Nutzer-ID angeben"
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
def _checks(cog, guild, conf) -> list[tuple[str, str]]:
    out = []
    if not conf["enabled"]:
        out.append(("warn", "Das Levelsystem ist <b>ausgeschaltet</b> – es werden keine XP vergeben."))
    if conf["announce_mode"] == "channel":
        ch = guild.get_channel(int(conf["announce_channel"])) if conf["announce_channel"] else None
        if ch is None:
            out.append(("bad", "Level-Up-Meldung „fester Kanal“ ist gewählt, aber der Kanal fehlt."))
        elif guild.me is not None and hasattr(ch, "permissions_for") and not ch.permissions_for(guild.me).send_messages:
            out.append(("bad", f"In <b>#{_esc(ch.name)}</b> darf ich keine Nachrichten senden."))
    bad = []
    for lvl, rid in (conf.get("rewards") or {}).items():
        role = guild.get_role(int(rid)) if str(rid).isdigit() else None
        if role is None:
            bad.append(f"Level {int(lvl)}: Rolle gelöscht")
        elif not cog.bot_can_manage(guild, role):
            bad.append(f"Level {int(lvl)}: @{_esc(role.name)} liegt über der Bot-Rolle")
    if bad:
        out.append(("bad", "Diese Belohnungen kann ich nicht vergeben: " + "; ".join(bad) + "."))
    return out


async def _render(cog, request):
    from .levels import MAX_ANNOUNCE, MAX_COOLDOWN, MAX_GIVE, MAX_LEVEL, MAX_MULT, MAX_VOICE_XP, MAX_XP_PER_MESSAGE, \
        MIN_MULT, progress

    webcore = request.app["webcore"]
    ui = webcore.ui
    guilds = await _visible(request)
    guild = _pick(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": TITLE, "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    rows = await cog.ranking(guild)

    picker = ""
    if not request.get("wc_switcher"):
        picker = ui.card(body=ui.form(
            f"/cogs/{SLUG}",
            ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
            csrf="", method="get",
        ))

    head = ui.hero(
        "bi-trophy", "",
        "Mitglieder sammeln <b>XP</b> für Nachrichten (und optional Voice), steigen im <b>Level</b> auf und "
        "erhalten <b>Rollen-Belohnungen</b>.",
    ) + ui.stats([
        ("Status", "Aktiv" if conf["enabled"] else "Aus", "bi-power", None, "ok" if conf["enabled"] else "warn"),
        ("Mitglieder mit XP", _num(len(rows)), "bi-people", None, None),
        ("Höchstes Level", rows[0][1]["level"] if rows else 0, "bi-bar-chart-steps", None, None),
        ("XP gesamt", _num(sum(r["xp"] for _, r in rows)), "bi-stars", None, None),
        ("Belohnungen", len(conf["rewards"]), "bi-gift", None, None),
    ])
    checks = "".join(ui.callout(text, tone=tone) for tone, text in _checks(cog, guild, conf))

    # --- Rangliste ---
    trs = []
    for i, (uid, rec) in enumerate(rows[:500], 1):
        m = guild.get_member(uid)
        level, into, needed = progress(rec["xp"])
        pct = int(100 * into / needed) if needed else 0
        name = _esc(m.display_name) if m else f"<span class='wc-muted'>{uid}</span>"
        trs.append(ui.row(
            f"<b>#{i}</b>", name, ">" + str(level), ">" + _num(rec["xp"]),
            f"<div class='rankbar' title='{_num(into)} / {_num(needed)} XP bis Level {level + 1}'>"
            f"<span style='width:{pct}%'></span></div>",
        ))
    more = (f"<div class='wc-help'>Angezeigt: Top 500 von {_num(len(rows))}.</div>" if len(rows) > 500 else "")
    board = ui.card("Rangliste", ui.table(["#", "Mitglied", ">Level", ">XP", "Fortschritt"], trs, search=True,
                                          search_placeholder="Mitglied suchen …", id="lv-board",
                                          empty_text="Noch hat niemand XP gesammelt.") + more,
                    icon="bi-list-ol", desc="Nur Mitglieder, die noch auf dem Server sind.")

    # --- Belohnungen ---
    rtrs = []
    for lvl, rid in sorted(((int(k), v) for k, v in conf["rewards"].items()), key=lambda x: x[0]):
        role = guild.get_role(int(rid)) if str(rid).isdigit() else None
        if role is None:
            status = ui.badge("Rolle gelöscht", "bad")
        elif not cog.bot_can_manage(guild, role):
            status = ui.badge("über Bot-Rolle", "bad")
        else:
            status = ui.badge("OK", "ok")
        delete = ui.form(f"/cogs/{SLUG}", ui.button("Entfernen", icon="bi-trash", kind="danger", small=True),
                         csrf=csrf, hidden={"form": "reward_del", "guild": guild.id, "level": lvl},
                         confirm=f"Belohnung für Level {lvl} entfernen?")
        rtrs.append(ui.row(f"<b>{lvl}</b>", _esc("@" + role.name) if role else _esc(rid), status, ">" + delete))
    rewards_list = ui.card("Belohnungen", ui.table(["Level", "Rolle", "Status", ">Aktion"], rtrs,
                                                    empty_text="Noch keine Belohnungen eingerichtet."),
                           icon="bi-gift", desc="Diese Rollen bekommen Mitglieder beim Erreichen des Levels.")
    add_form = ui.form(
        f"/cogs/{SLUG}",
        ui.grid(
            ui.field("Level", ui.number("level", "", min=1, max=MAX_LEVEL, placeholder="z. B. 10")),
            ui.field("Rolle", ui.select("role", _role_items(guild), None, none_label="— Rolle wählen —")),
        ) + ui.save_row("Belohnung speichern"),
        csrf=csrf, hidden={"form": "reward_add", "guild": guild.id},
    )
    add_card = ui.card("Belohnung hinzufügen", add_form, icon="bi-plus-circle",
                       desc="Gibt es für das Level schon eine Belohnung, wird sie ersetzt. Die Rolle muss unter der "
                            "Bot-Rolle liegen; Team-Mitglieder können nur Rollen unter ihrer eigenen höchsten Rolle "
                            "ohne Moderationsrechte eintragen.")
    stack_form = ui.form(
        f"/cogs/{SLUG}",
        ui.switch("stack_rewards", "Belohnungen stapeln", conf["stack_rewards"],
                  desc="An: alle erreichten Rollen behalten. Aus: nur die Rolle des höchsten erreichten Levels "
                       "(niedrigere werden entfernt).") + ui.save_row(),
        csrf=csrf, hidden={"form": "stack", "guild": guild.id}, savebar=True,
    )
    sync_form = ui.form(
        f"/cogs/{SLUG}",
        ui.actions(ui.button("Jetzt für alle abgleichen", icon="bi-arrow-repeat", kind="ghost"),
                   "<span class='wc-help'>Vergibt/entfernt Belohnungsrollen passend zum aktuellen Level aller "
                   "Mitglieder – z. B. nach dem Anlegen einer neuen Belohnung.</span>"),
        csrf=csrf, hidden={"form": "sync", "guild": guild.id},
        confirm="Belohnungsrollen jetzt für alle Mitglieder abgleichen?",
    )
    mode_card = ui.card("Modus", stack_form + ui.divider() + sync_form, icon="bi-layers")

    # --- Einstellungen ---
    lang = conf["language"]
    settings = ui.form(
        f"/cogs/{SLUG}",
        ui.card("Allgemein", ui.grid(
            ui.field("Status", ui.switches(
                ui.switch("enabled", "Levelsystem aktiv", conf["enabled"], desc="Aus = keine XP, keine Meldungen."),
                ui.switch("member_page", "Im Mitglieder-Bereich anzeigen", conf["member_page"],
                          desc="Mitglieder sehen unter „Mein Bereich → Mein Level“ ihren Rang, Fortschritt, "
                               "die Rangkarte und die Top 10 (nur Anzeigenamen)."),
            ), wide=True),
            ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), lang),
                     help="Sprache der Meldungen, Befehle und der Rangkarte."),
            ui.field("Kartenfarbe", ui.color_input("card_color", conf["card_color"]),
                     help="Akzentfarbe der Rangkarte."),
        ) + ui.callout(
            "Den Mitglieder-Bereich selbst schaltet der Bot-Owner pro Server unter <b>Verwaltung → Zugriff &amp; "
            "Rollen</b> ein (oder mit <code>[p]webcore portal on</code>). Der Schalter hier blendet nur die Seite "
            "„Mein Level“ aus."), icon="bi-sliders")
        + ui.card("XP", ui.grid(
            ui.field("XP pro Nachricht (min.)", ui.number("xp_min", conf["xp_min"], min=1, max=MAX_XP_PER_MESSAGE)),
            ui.field("XP pro Nachricht (max.)", ui.number("xp_max", conf["xp_max"], min=1, max=MAX_XP_PER_MESSAGE),
                     help="Zufällig zwischen min. und max. (Standard 15–25)."),
            ui.field("Cooldown", ui.number("cooldown", conf["cooldown"], min=0, max=MAX_COOLDOWN, unit="Sek."),
                     help="Pro Mitglied zählt höchstens eine Nachricht in dieser Zeit (Standard 60)."),
            ui.field("Voice-XP pro Minute", ui.number("voice_xp", conf["voice_xp"], min=1, max=MAX_VOICE_XP, unit="XP")),
            ui.field("Voice", ui.switch("voice_enabled", "XP für Zeit in Sprachkanälen", conf["voice_enabled"],
                                        desc="Nur wer nicht allein, nicht stumm/taub und nicht im AFK-Kanal ist."),
                     wide=True),
        ), icon="bi-stars", desc="Levelkurve: von Level L nach L+1 braucht man 5·L² + 50·L + 100 XP.")
        + ui.card("Ausschlüsse", ui.grid(
            ui.field("Kanäle ohne XP", ui.select("excluded_channels", _channel_items(guild),
                                                 conf["excluded_channels"], multiple=True, placeholder="Kanäle suchen …"),
                     help="Nachrichten (auch in Threads dieser Kanäle) und Voice-Zeit dort geben keine XP.", wide=True),
            ui.field("Rollen ohne XP", ui.select("excluded_roles", _role_items(guild), conf["excluded_roles"],
                                                 multiple=True, placeholder="Rollen suchen …"),
                     help="Mitglieder mit einer dieser Rollen bekommen keine XP.", wide=True),
        ), icon="bi-slash-circle")
        + ui.card("Level-Up-Meldung", ui.grid(
            ui.field("Meldung", ui.select("announce_mode", _MODE_LABELS, conf["announce_mode"])),
            ui.field("Fester Kanal", ui.select("announce_channel", _channel_items(guild, voice=False),
                                               conf["announce_channel"], none_label="— kein Kanal —"),
                     help="Nur für „In einem festen Kanal“."),
            ui.field("Text", ui.textarea("announce_text", conf["announce_text"], rows=3,
                                         placeholder=t(lang, "levelup_default")),
                     help=f"Leer = Standardtext. Max. {MAX_ANNOUNCE} Zeichen. " + _PH_HELP, wide=True),
        ) + ui.save_row("Einstellungen speichern"), icon="bi-megaphone", desc="Gepingt wird nie @everyone/@here oder eine Rolle. Bei Voice-Level-Ups gibt "
                                     "es im Modus „selber Kanal“ keine Meldung."),
        csrf=csrf, hidden={"form": "settings", "guild": guild.id}, savebar=True,
    )
    mtrs = []
    for rid, factor in sorted(conf["multipliers"].items(), key=lambda kv: -float(kv[1])):
        role = guild.get_role(int(rid)) if str(rid).isdigit() else None
        delete = ui.form(f"/cogs/{SLUG}", ui.button("Entfernen", icon="bi-trash", kind="danger", small=True),
                         csrf=csrf, hidden={"form": "mult_del", "guild": guild.id, "role": rid},
                         confirm="Multiplikator entfernen?")
        mtrs.append(ui.row(_esc("@" + role.name) if role else _esc(rid), f"×{_esc(factor)}", ">" + delete))
    mult_card = ui.card("XP-Multiplikatoren", ui.table(["Rolle", "Faktor", ">Aktion"], mtrs,
                                                        empty_text="Keine Multiplikatoren.")
                        + ui.form(f"/cogs/{SLUG}", ui.grid(
                            ui.field("Rolle", ui.select("role", _role_items(guild), None, none_label="— Rolle wählen —")),
                            ui.field("Faktor", ui.number("factor", "1.5", min=MIN_MULT, max=MAX_MULT, step="0.1",
                                                         unit="×")),
                        ) + ui.save_row("Multiplikator speichern"), csrf=csrf,
                            hidden={"form": "mult_add", "guild": guild.id}),
                        icon="bi-lightning-charge",
                        desc=f"Mitglieder mit dieser Rolle bekommen mehr (oder weniger) XP ({MIN_MULT}–{MAX_MULT}). "
                             "Hat jemand mehrere, gilt der höchste Faktor.")

    # --- XP anpassen ---
    xp_form = ui.form(
        f"/cogs/{SLUG}",
        ui.grid(
            ui.field("Mitglied", ui.text_input("member", "", placeholder="Nutzer-ID oder Anzeigename",
                                               attrs={"maxlength": 100, "autocomplete": "off"}),
                     help="ID (Rechtsklick → ID kopieren), Erwähnung oder eindeutiger Name."),
            ui.field("Aktion", ui.select("action", [("give", "XP geben"), ("take", "XP abziehen"),
                                                    ("set", "XP auf Wert setzen"), ("reset", "Zurücksetzen (0 XP)")],
                                         "give")),
            ui.field("Menge", ui.number("amount", 100, min=0, max=MAX_GIVE, unit="XP"),
                     help="Bei „Zurücksetzen“ ohne Bedeutung."),
        ) + ui.save_row("XP ändern"),
        csrf=csrf, hidden={"form": "xp", "guild": guild.id},
        confirm="XP dieses Mitglieds wirklich ändern? Belohnungsrollen werden angepasst, eine Level-Up-Meldung gibt es nicht.",
    )
    xp_card = ui.card("XP anpassen", xp_form, icon="bi-pencil-square",
                      desc="Korrekturen durch das Team – ohne Level-Up-Meldung.")

    body = (
        ui.tab("rangliste", "Rangliste", "bi-list-ol", board, count=len(rows) or None)
        + ui.tab("belohnungen", "Belohnungen", "bi-gift", rewards_list + add_card + mode_card,
                 count=len(conf["rewards"]) or None)
        + ui.tab("einstellungen", "Einstellungen", "bi-sliders", settings + mult_card)
        + ui.tab("xp", "XP anpassen", "bi-pencil-square", xp_card)
    )
    return {"title": TITLE, "content": picker + head + checks + body}


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
def _int(raw, lo, hi):
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


async def _handle_post(cog, request):
    from .levels import ANNOUNCE_MODES, MAX_ANNOUNCE, MAX_COOLDOWN, MAX_GIVE, MAX_LEVEL, MAX_MULT, MAX_VOICE_XP, \
        MAX_XP_PER_MESSAGE, MAX_XP_TOTAL, MIN_MULT, valid_color

    webcore = request.app["webcore"]
    data = await request.post()
    guild = _pick(await _visible(request), data.get("guild"))
    if guild is None:
        return {"redirect": f"/cogs/{SLUG}?err=" + quote_plus("Server nicht gefunden oder keine Bearbeitungsrechte")}
    form = data.get("form")
    gconf = cog.config.guild(guild)

    if form == "settings":
        xp_min = _int(data.get("xp_min"), 1, MAX_XP_PER_MESSAGE)
        xp_max = _int(data.get("xp_max"), 1, MAX_XP_PER_MESSAGE)
        if xp_min is None or xp_max is None or xp_min > xp_max:
            return _redirect(guild.id, err=f"XP pro Nachricht: 1–{MAX_XP_PER_MESSAGE}, min. ≤ max.")
        cooldown = _int(data.get("cooldown"), 0, MAX_COOLDOWN)
        if cooldown is None:
            return _redirect(guild.id, err=f"Cooldown: 0–{MAX_COOLDOWN} Sekunden")
        voice_xp = _int(data.get("voice_xp"), 1, MAX_VOICE_XP)
        if voice_xp is None:
            return _redirect(guild.id, err=f"Voice-XP: 1–{MAX_VOICE_XP}")
        lang = data.get("language") or "de"
        if lang not in LANGUAGES:
            return _redirect(guild.id, err="Unbekannte Sprache")
        color = valid_color(data.get("card_color") or "#3ddc97")
        if color is None:
            return _redirect(guild.id, err="Ungültige Kartenfarbe")
        chan_ok = {c.id for c in guild.text_channels} | {c.id for c in guild.voice_channels}
        excluded_channels = []
        for raw in data.getall("excluded_channels", []):
            if not str(raw).isdigit() or int(raw) not in chan_ok:
                return _redirect(guild.id, err="Kanal nicht gefunden")
            excluded_channels.append(int(raw))
        excluded_roles = []
        for raw in data.getall("excluded_roles", []):
            role = guild.get_role(int(raw)) if str(raw).isdigit() else None
            if role is None or role.is_default():
                return _redirect(guild.id, err="Rolle nicht gefunden")
            excluded_roles.append(role.id)
        mode = data.get("announce_mode") or "same"
        if mode not in ANNOUNCE_MODES:
            return _redirect(guild.id, err="Ungültiger Meldungs-Modus")
        raw_ch = (data.get("announce_channel") or "").strip()
        announce_channel = None
        if raw_ch:
            ch = next((c for c in guild.text_channels if raw_ch.isdigit() and c.id == int(raw_ch)), None)
            if ch is None:
                return _redirect(guild.id, err="Kanal für die Meldung nicht gefunden")
            announce_channel = ch.id
        if mode == "channel" and announce_channel is None:
            return _redirect(guild.id, err="Für „fester Kanal“ bitte einen Kanal wählen")
        text = (data.get("announce_text") or "").replace("\r\n", "\n").strip()
        if len(text) > MAX_ANNOUNCE:
            return _redirect(guild.id, err=f"Text zu lang (max. {MAX_ANNOUNCE} Zeichen)")
        updates = {
            "enabled": "enabled" in data, "member_page": "member_page" in data, "language": lang,
            "card_color": color, "xp_min": xp_min, "xp_max": xp_max, "cooldown": cooldown,
            "voice_enabled": "voice_enabled" in data, "voice_xp": voice_xp,
            "excluded_channels": list(dict.fromkeys(excluded_channels)),
            "excluded_roles": list(dict.fromkeys(excluded_roles)),
            "announce_mode": mode, "announce_channel": announce_channel, "announce_text": text,
        }
        for key, value in updates.items():
            await gconf.set_raw(key, value=value)
        return _redirect(guild.id, ok="Einstellungen gespeichert")

    if form == "reward_add":
        level = _int(data.get("level"), 1, MAX_LEVEL)
        if level is None:
            return _redirect(guild.id, err=f"Level muss zwischen 1 und {MAX_LEVEL} liegen")
        raw = data.get("role") or ""
        role = guild.get_role(int(raw)) if str(raw).isdigit() else None
        if role is None:
            return _redirect(guild.id, err="Rolle nicht gefunden")
        if role.is_default() or getattr(role, "managed", False):
            return _redirect(guild.id, err="Diese Rolle kann nicht vergeben werden")
        if not await webcore.can_grant_role(request, guild, role):
            return _redirect(guild.id, err=f"@{role.name} darfst du nicht automatisch vergeben lassen "
                                           "(Schutz vor Selbst-Hochstufung)")
        if not cog.bot_can_manage(guild, role):
            return _redirect(guild.id, err=f"@{role.name} liegt nicht unter der Bot-Rolle oder dem Bot fehlt "
                                           "„Rollen verwalten“")
        async with gconf.rewards() as rewards:
            rewards[str(level)] = role.id
        return _redirect(guild.id, ok=f"Belohnung für Level {level} gespeichert")

    if form == "reward_del":
        level = _int(data.get("level"), 0, 10 ** 6)
        async with gconf.rewards() as rewards:
            had = rewards.pop(str(level), None) if level is not None else None
        if had is None:
            return _redirect(guild.id, err="Belohnung nicht gefunden")
        return _redirect(guild.id, ok=f"Belohnung für Level {level} entfernt")

    if form == "stack":
        await gconf.stack_rewards.set("stack_rewards" in data)
        return _redirect(guild.id, ok="Belohnungs-Modus gespeichert")

    if form == "sync":
        added, removed = await cog.sync_all(guild)
        return _redirect(guild.id, ok=f"Abgeglichen: {added} Rollen vergeben, {removed} entfernt")

    if form == "mult_add":
        raw = data.get("role") or ""
        role = guild.get_role(int(raw)) if str(raw).isdigit() else None
        if role is None or role.is_default():
            return _redirect(guild.id, err="Rolle nicht gefunden")
        try:
            factor = round(float(str(data.get("factor") or "").replace(",", ".")), 2)
        except ValueError:
            factor = None
        if factor is None or not MIN_MULT <= factor <= MAX_MULT:
            return _redirect(guild.id, err=f"Faktor muss zwischen {MIN_MULT} und {MAX_MULT} liegen")
        async with gconf.multipliers() as mults:
            if factor == 1:
                mults.pop(str(role.id), None)
            else:
                mults[str(role.id)] = factor
        return _redirect(guild.id, ok=f"Multiplikator für @{role.name} gespeichert")

    if form == "mult_del":
        async with gconf.multipliers() as mults:
            had = mults.pop(str(data.get("role") or ""), None)
        if had is None:
            return _redirect(guild.id, err="Multiplikator nicht gefunden")
        return _redirect(guild.id, ok="Multiplikator entfernt")

    if form == "xp":
        member, err = resolve_member(guild, data.get("member") or "")
        if member is None:
            return _redirect(guild.id, err=err)
        if getattr(member, "bot", False):
            return _redirect(guild.id, err="Bots sammeln keine XP")
        action = data.get("action")
        if action == "reset":
            await cog.reset_member(member)
        elif action in ("give", "take", "set"):
            limit = MAX_XP_TOTAL if action == "set" else MAX_GIVE
            amount = _int(data.get("amount"), 0 if action == "set" else 1, limit)
            if amount is None:
                return _redirect(guild.id, err=f"Menge: {0 if action == 'set' else 1}–{_num(limit)} XP")
            rec = await cog.member_record(guild, member.id)
            new = {"give": rec["xp"] + amount, "take": rec["xp"] - amount, "set": amount}[action]
            await cog.set_xp(member, new, announce=False)
        else:
            return _redirect(guild.id, err="Unbekannte Aktion")
        rec = await cog.member_record(guild, member.id)
        return _redirect(guild.id, ok=f"{member.display_name}: {_num(rec['xp'])} XP (Level {rec['level']})")

    return _redirect(guild.id, err="Unbekannte Aktion")

