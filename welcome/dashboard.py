"""WebCore-Dashboard für den Welcome-Cog.

* GET  ``/cogs/welcome?guild=<id>``                 -> Seite (Reiter Willkommen, Abschied, DM, Bild)
* GET  ``/cogs/welcome?guild=<id>&preview=card[…]`` -> PNG-Vorschau des Willkommensbildes. Mit
  „Bearbeiten“ dürfen ungespeicherte Werte als Query mitkommen (``bg``, ``accent``, ``tc``, ``url``,
  ``headline``) – so aktualisiert sich die Vorschau live; sonst (Ansehen/Bedienen) gelten die
  gespeicherten Werte (die Bild-URL lädt der Bot – deshalb nur mit „Bearbeiten“).
* POST ``form=welcome|leave|dm|card`` -> speichern; ``do=test`` postet danach eine Testnachricht mit
  dem angemeldeten Dashboard-User als Beispiel. Danach Redirect (Post/Redirect/Get) mit Toast.
* POST ``form=test`` + ``kind=welcome|leave|dm`` -> Testnachricht mit den **gespeicherten**
  Einstellungen, ohne zu speichern (Tagesgeschäft – schon mit der Stufe „Bedienen“).

Nur UI-Kit von WebCore, kein eigenes CSS. Rechte: Server über ``visible_guilds``; WebCore prüft
POSTs zentral: ``test`` ab „Bedienen“, alles andere (Speichern) braucht „Bearbeiten“.
"""

from __future__ import annotations

import html
import json
import re
import types
from urllib.parse import quote, quote_plus

import discord
from aiohttp import web

from .strings import LANGUAGES, t

SLUG = "welcome"

_KIND_LABEL = {"welcome": "Willkommen", "leave": "Abschied", "dm": "DM"}
_ERR_TEXT = {
    "err_no_channel": "Kein Kanal gesetzt",
    "err_channel_missing": "Der Kanal existiert nicht mehr",
    "err_no_send": "Mir fehlt das Recht „Nachrichten senden“ im Kanal",
    "err_no_embed": "Mir fehlt das Recht „Links einbetten“ im Kanal",
    "err_http": "Discord hat die Nachricht abgelehnt",
}
_PH_HELP = ("Platzhalter: <code>{user}</code> Erwähnung · <code>{name}</code> Name · <code>{server}</code> Server · "
            "<code>{count}</code> Mitgliederzahl · <code>{created}</code> Kontoalter")


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


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


async def _dashboard_member(request, guild):
    """Der angemeldete Dashboard-User als Mitglied von ``guild`` (oder ``None``)."""
    webcore = request.app["webcore"]
    getter = getattr(webcore, "current_user", None) or getattr(webcore, "_get_user")
    user = await getter(request)
    if not user:
        return None
    uid = int(user["id"])
    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except Exception:  # noqa: BLE001 – kein Mitglied / keine Rechte
            member = None
    return member


def _example(guild):
    """Ersatz-Beispiel, falls der Dashboard-User kein Mitglied ist: der Bot selbst."""
    if guild.me is not None:
        return guild.me
    return types.SimpleNamespace(id=0, display_name="Beispiel", name="beispiel", mention="@Beispiel",
                                 guild=guild, bot=False, created_at=None, display_avatar=None)


async def _can_edit(request, guild) -> bool:
    """Darf der User Einstellungen ändern (WebCore-Stufe „Bearbeiten“)?"""
    webcore = request.app["webcore"]
    can_edit = getattr(webcore, "can_edit", None)
    if can_edit is not None:
        return await can_edit(request, guild)
    return not request.get("webcore_readonly")  # ältere WebCore-Versionen: nur Ansehen/Bearbeiten


async def _operate_only(request, guild) -> bool:
    """Stufe „Bedienen“ (Tagesgeschäft, aber keine Einstellungen)?"""
    webcore = request.app["webcore"]
    can_operate = getattr(webcore, "can_operate", None)
    if can_operate is None:
        return False
    return await can_operate(request, guild) and not await _can_edit(request, guild)


def _channel_items(guild):
    return [(c.id, f"#{c.name}") for c in guild.text_channels]


# --------------------------------------------------------------------------- #
#  Einstieg
# --------------------------------------------------------------------------- #
async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    if request.query.get("preview") == "card":
        return await _preview(cog, request)
    return await _render(cog, request)


# --------------------------------------------------------------------------- #
#  Bildvorschau (GET, PNG)
# --------------------------------------------------------------------------- #
async def _preview(cog, request):
    from .welcome import MAX_HEADLINE, valid_color, valid_url

    guild = _pick(await _visible(request), request.query.get("guild"))
    if guild is None:
        raise web.HTTPNotFound(text="Server nicht gefunden")
    conf = await cog.config.guild(guild).all()
    q = request.query
    if await _can_edit(request, guild):
        # Ungespeicherte Formularwerte nur mit Bearbeiten-Recht (die URL wird vom Bot geladen).
        if valid_color(q.get("bg")):
            conf["card_bg_color"] = valid_color(q.get("bg"))
        if valid_color(q.get("accent")):
            conf["card_accent"] = valid_color(q.get("accent"))
        if valid_color(q.get("tc")):
            conf["card_text_color"] = valid_color(q.get("tc"))
        if "url" in q:
            conf["card_bg_url"] = valid_url(q.get("url")) or ""
        if "headline" in q:
            conf["card_headline"] = (q.get("headline") or "")[:MAX_HEADLINE]
    member = await _dashboard_member(request, guild) or _example(guild)
    png, bg_err = await cog.render_card(member, conf)
    headers = {"Cache-Control": "no-store"}
    if bg_err:
        headers["X-Bg-Error"] = quote(bg_err)
    return web.Response(body=png, content_type="image/png", headers=headers)


# --------------------------------------------------------------------------- #
#  Seite (GET)
# --------------------------------------------------------------------------- #
async def _render(cog, request):
    webcore = request.app["webcore"]
    ui = webcore.ui
    guilds = await _visible(request)
    guild = _pick(guilds, request.query.get("guild")) or (guilds[0] if guilds else None)
    if guild is None:
        return {"title": "Willkommen", "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")
    readonly = bool(request.get("webcore_readonly"))
    can_edit = await _can_edit(request, guild)
    operate_only = await _operate_only(request, guild)
    example = await _dashboard_member(request, guild) or _example(guild)

    def test(kind):
        return _test_form(ui, guild, kind, csrf) if operate_only else ""

    picker = ""
    if not request.get("wc_switcher"):
        picker = ui.card(body=ui.form(
            f"/cogs/{SLUG}",
            ui.field("Server", ui.select("guild", [(g.id, g.name) for g in guilds], guild.id, autosubmit=True)),
            csrf="", method="get",
        ))

    def state(on):
        return ("Aktiv", "ok") if on else ("Aus", None)

    w, lv, dm, cd = (state(conf["welcome_enabled"]), state(conf["leave_enabled"]),
                     state(conf["dm_enabled"]), state(conf["card_enabled"]))
    head = ui.hero(
        "bi-door-open", "",
        "Begrüßt neue Mitglieder mit einer Nachricht, einem <b>Willkommensbild</b> und optional einer <b>DM</b> "
        "und verabschiedet Mitglieder, die den Server verlassen.",
    ) + ui.stats([
        ("Willkommen", w[0], "bi-door-open", None, w[1]),
        ("Abschied", lv[0], "bi-door-closed", None, lv[1]),
        ("DM", dm[0], "bi-envelope", None, dm[1]),
        ("Bild", cd[0], "bi-image", None, cd[1]),
        ("Mitglieder", getattr(guild, "member_count", None) or len(guild.members), "bi-people", None, None),
    ])

    checks = _checks(cog, guild, conf)

    def check_html(tab):
        return "".join(ui.callout(text, tone=tone) for tone, text, where in checks if where == tab)

    body = (
        ui.tab("willkommen", "Willkommen", "bi-door-open",
               check_html("welcome") + test("welcome")
               + _kind_form(ui, cog, guild, conf, "welcome", csrf, example, readonly))
        + ui.tab("abschied", "Abschied", "bi-door-closed",
                 check_html("leave") + test("leave") + _kind_form(ui, cog, guild, conf, "leave", csrf, example, readonly))
        + ui.tab("dm", "DM", "bi-envelope", test("dm") + _kind_form(ui, cog, guild, conf, "dm", csrf, example, readonly))
        + ui.tab("bild", "Bild", "bi-image",
                 check_html("card") + test("card") + _card_form(ui, guild, conf, csrf, not can_edit))
    )
    return {"title": "Willkommen", "content": picker + head + body}


def _checks(cog, guild, conf) -> list[tuple[str, str, str]]:
    """[(ton, text, reiter)] – reiter: welcome | leave | card."""
    out = []
    me = guild.me
    for kind in ("welcome", "leave"):
        if not conf[f"{kind}_enabled"]:
            continue
        label = _KIND_LABEL[kind]
        cid = conf[f"{kind}_channel"]
        ch = cog._resolve_channel(guild, cid) if cid else None
        if not cid:
            out.append(("warn", f"<b>{label}</b> ist aktiv, aber es ist noch <b>kein Kanal</b> gesetzt.", kind))
        elif ch is None:
            out.append(("bad", f"Der Kanal für <b>{label}</b> existiert nicht mehr – bitte einen neuen wählen.", kind))
        elif me is not None:
            perms = ch.permissions_for(me)
            missing = []
            if not perms.send_messages:
                missing.append("Nachrichten senden")
            if conf[f"{kind}_mode"] == "embed" and not perms.embed_links:
                missing.append("Links einbetten")
            if kind == "welcome" and conf["card_enabled"] and not perms.attach_files:
                missing.append("Dateien anhängen")
            if missing:
                out.append(("bad", f"In <b>#{_esc(ch.name)}</b> fehlen mir Rechte: " + ", ".join(missing) + ".", kind))
    if conf["card_enabled"] and not conf["welcome_enabled"]:
        out.append(("info", "Das Willkommensbild ist an, die Willkommensnachricht aber aus – das Bild wird nur "
                            "zusammen mit ihr gepostet.", "card"))
    return out


def _example_text(cog, conf, kind, member) -> str:
    try:
        msg = cog.build_message(conf, kind, member, ping=False)
    except Exception:  # noqa: BLE001 – Vorschau ist nur Beiwerk
        return ""
    mention = getattr(member, "mention", None)
    shown = f"@{getattr(member, 'display_name', '')}"

    def fmt(value):
        value = str(value or "")
        if mention:
            value = value.replace(mention, shown)
        value = _esc(value)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value).replace("\n", "<br>")

    emb = msg.get("embed")
    if emb is not None:
        return f"<b>{fmt(emb.title)}</b><br>{fmt(emb.description)}"
    return fmt(msg.get("content"))


def _kind_form(ui, cog, guild, conf, kind, csrf, example, readonly) -> str:
    from .welcome import MAX_TEXT, MAX_TITLE, MAX_URL

    lang = conf.get("language") or "de"
    label = _KIND_LABEL[kind]
    enabled_label = {"welcome": "Willkommensnachricht beim Beitritt posten",
                     "leave": "Abschiedsnachricht beim Verlassen posten",
                     "dm": "Neuen Mitgliedern eine DM schicken"}[kind]
    enabled_desc = {"welcome": "Postet in den gewählten Kanal, sobald jemand dem Server beitritt.",
                    "leave": "Postet in den gewählten Kanal, sobald jemand den Server verlässt (auch bei Kick/Bann).",
                    "dm": "Geschlossene DMs werden still übersprungen."}[kind]
    fields = [ui.field("Status", ui.switch("enabled", enabled_label, conf[f"{kind}_enabled"], desc=enabled_desc),
                       wide=True)]
    if kind != "dm":
        fields.append(ui.field("Kanal", ui.select("channel", _channel_items(guild), conf[f"{kind}_channel"],
                                                  none_label="— kein Kanal —")))
    fields.append(ui.field("Darstellung", ui.select("mode", [("text", "Normaler Text"), ("embed", "Embed")],
                                                    conf[f"{kind}_mode"]),
                           help="Embed: mit Titel, Farbe und Bild."))
    fields.append(ui.field(
        "Text", ui.textarea("text", conf[f"{kind}_text"], rows=4, placeholder=t(lang, f"default_{kind}")),
        help=f"Leer = Standardtext (siehe Platzhalter im Feld). Max. {MAX_TEXT} Zeichen. " + _PH_HELP, wide=True,
    ))
    msg_card = ui.card(f"{label}-Nachricht", ui.grid(*fields), icon={"welcome": "bi-door-open",
                                                                      "leave": "bi-door-closed",
                                                                      "dm": "bi-envelope"}[kind],
                       desc={"welcome": "Was neue Mitglieder im Server sehen.",
                             "leave": "Was im Server erscheint, wenn jemand geht.",
                             "dm": "Private Nachricht an neue Mitglieder."}[kind])
    embed_card = ui.card("Embed", ui.grid(
        ui.field("Titel", ui.text_input("title", conf[f"{kind}_title"], placeholder=t(lang, f"default_{kind}_title"),
                                        attrs={"maxlength": MAX_TITLE}),
                 help="Leer = Standardtitel. Platzhalter erlaubt."),
        ui.field("Farbe", ui.color_input("color", conf[f"{kind}_color"])),
        ui.field("Bild-URL", ui.text_input("image", conf[f"{kind}_image"], placeholder="https://…",
                                           type="url", attrs={"maxlength": MAX_URL}),
                 help="Großes Bild im Embed (nur <code>https://</code>)."
                      + (" Ist das Willkommensbild aktiv, ersetzt es dieses Bild." if kind == "welcome" else ""),
                 wide=True),
    ), icon="bi-card-heading", desc="Gilt nur bei der Darstellung „Embed“.")
    extra = ""
    if kind == "welcome":
        extra = ui.card("Allgemein", ui.grid(
            ui.field("Optionen", ui.switches(
                ui.switch("ping_user", "Neues Mitglied anpingen", conf["ping_user"],
                          desc="Nur das neue Mitglied wird gepingt – nie @everyone, @here oder Rollen."),
                ui.switch("ignore_bots", "Bots ignorieren", conf["ignore_bots"],
                          desc="Keine Begrüßung/DM/Abschied für Bots."),
            ), wide=True),
            ui.field("Sprache", ui.select("language", list(LANGUAGES.items()), conf["language"]),
                     help="Sprache der Standardtexte und des Bildes."),
        ), icon="bi-sliders", desc="Gilt für Willkommen, Abschied und DM.")
    sample = _example_text(cog, conf, kind, example)
    preview = ui.card("Beispiel", f"<div class='wc-help'>{sample}</div>" if sample else "",
                      icon="bi-eye", desc="So sieht die <b>gespeicherte</b> Nachricht mit dir als Beispiel aus.")
    test_label = "Test-DM an mich senden" if kind == "dm" else "Testnachricht posten"
    test_help = ("Speichert und schickt dir die DM." if kind == "dm"
                 else "Speichert und postet die Nachricht mit dir als Beispiel in den eingestellten Kanal.")
    buttons = ui.actions(
        ui.button("Speichern", icon="bi-check2"),
        ui.button(test_label, icon="bi-send", kind="ghost", name="do", value="test"),
        f"<span class='wc-help'>{_esc(test_help)}</span>",
    )
    return ui.form(f"/cogs/{SLUG}", msg_card + embed_card + extra + preview + buttons, csrf=csrf,
                   hidden={"form": kind, "guild": guild.id}, savebar=True)


def _test_form(ui, guild, kind, csrf) -> str:
    """Test ohne Speichern (Tagesgeschäft, Stufe „Bedienen“) – nutzt die gespeicherten Einstellungen."""
    label = "Test-DM an mich senden" if kind == "dm" else "Testnachricht posten"
    desc = {"welcome": "Postet die gespeicherte Willkommensnachricht mit dir als Beispiel in den eingestellten Kanal.",
            "leave": "Postet die gespeicherte Abschiedsnachricht mit dir als Beispiel in den eingestellten Kanal.",
            "dm": "Schickt dir die gespeicherte DM.",
            "card": "Postet die gespeicherte Willkommensnachricht mit Bild und dir als Beispiel in den eingestellten "
                    "Kanal."}[kind]
    form = ui.form(f"/cogs/{SLUG}", ui.actions(ui.button(label, icon="bi-send", kind="ghost")), csrf=csrf,
                   hidden={"form": "test", "kind": "welcome" if kind == "card" else kind, "guild": guild.id},
                   operate=True)
    return ui.card("Testen", form, icon="bi-send",
                   desc=desc + " Einstellungen ändern kann nur, wer auf dieser Seite <b>Bearbeiten</b> hat.")


def _card_form(ui, guild, conf, csrf, readonly) -> str:
    from .welcome import MAX_HEADLINE, MAX_URL

    base = f"/cogs/{SLUG}?guild={guild.id}&preview=card"
    settings = ui.card("Willkommensbild", ui.grid(
        ui.field("Status", ui.switch("card_enabled", "Willkommensbild an die Willkommensnachricht hängen",
                                     conf["card_enabled"],
                                     desc="Banner mit rundem Avatar, Name und „Mitglied #N“."), wide=True),
        ui.field("Hintergrundfarbe", ui.color_input("card_bg_color", conf["card_bg_color"]),
                 help="Erste Farbe des Verlaufs (oben rechts)."),
        ui.field("Akzentfarbe", ui.color_input("card_accent", conf["card_accent"]), help="Zweite Farbe des Verlaufs (unten links)."),
        ui.field("Textfarbe", ui.color_input("card_text_color", conf["card_text_color"])),
        ui.field("Überschrift", ui.text_input("card_headline", conf["card_headline"], placeholder="WILLKOMMEN",
                                              attrs={"maxlength": MAX_HEADLINE}),
                 help=f"Leer = „WILLKOMMEN“ (max. {MAX_HEADLINE} Zeichen)."),
        ui.field("Hintergrundbild-URL", ui.text_input("card_bg_url", conf["card_bg_url"], placeholder="https://…",
                                                      type="url", attrs={"maxlength": MAX_URL}),
                 help="Optional statt Farbverlauf (PNG/JPEG/WebP/GIF, max. 8 MB, nur öffentliche "
                      "<code>https://</code>-Adressen). Wird abgedunkelt und auf 1000×400 zugeschnitten.",
                 wide=True),
    ), icon="bi-image", desc="Wird als Bild an die Willkommensnachricht gehängt (im Embed als großes Bild).")
    buttons = ui.actions(
        ui.button("Speichern", icon="bi-check2"),
        ui.button("Testnachricht posten", icon="bi-send", kind="ghost", name="do", value="test"),
        "<span class='wc-help'>Speichert und postet die Willkommensnachricht mit Bild in den eingestellten Kanal.</span>",
    )
    live = "" if readonly else " Änderungen erscheinen sofort – gespeichert wird erst mit „Speichern“."
    preview = ui.card(
        "Vorschau",
        f"<div class='text-center'><img id='wl-card-preview' class='img-fluid rounded' src='{_esc(base)}' "
        f"alt='Vorschau des Willkommensbildes' width='1000' height='400'></div>"
        "<div id='wl-card-warn' class='wc-help'></div>",
        icon="bi-eye", desc="Mit dir als Beispiel." + live,
    )
    form = ui.form(f"/cogs/{SLUG}", settings + preview + buttons, csrf=csrf,
                   hidden={"form": "card", "guild": guild.id}, savebar=True, id="wl-card-form")
    script = "" if readonly else (
        "<script>(function(){var f=document.getElementById('wl-card-form'),img=document.getElementById('wl-card-preview'),"
        "warn=document.getElementById('wl-card-warn');if(!f||!img||!window.fetch)return;"
        f"var base={json.dumps(base)},timer=null,last=null,seq=0;"
        "function val(n){var e=f.querySelector(\"[name='\"+n+\"']\");return e?e.value:'';}"
        "function url(){return base+'&bg='+encodeURIComponent(val('card_bg_color'))+'&accent='+encodeURIComponent(val('card_accent'))"
        "+'&tc='+encodeURIComponent(val('card_text_color'))+'&headline='+encodeURIComponent(val('card_headline'))"
        "+'&url='+encodeURIComponent(val('card_bg_url'));}"
        "function load(){var u=url();if(u===last)return;last=u;var my=++seq;"
        "fetch(u,{credentials:'same-origin'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);"
        "var w=r.headers.get('X-Bg-Error');return r.blob().then(function(b){return [b,w];});})"
        ".then(function(x){if(my!==seq)return;var old=img.src;img.src=URL.createObjectURL(x[0]);"
        "if(old.indexOf('blob:')===0)URL.revokeObjectURL(old);"
        "warn.textContent=x[1]?('Hintergrundbild nicht geladen: '+decodeURIComponent(x[1])+' – Farbverlauf verwendet.'):'';})"
        ".catch(function(e){if(my===seq)warn.textContent='Vorschau fehlgeschlagen ('+e.message+').';});}"
        "function later(){clearTimeout(timer);timer=setTimeout(load,450);}"
        "f.addEventListener('input',later);f.addEventListener('change',later);f.addEventListener('reset',function(){setTimeout(load,50);});"
        "load();})();</script>"
    )
    return form + script


# --------------------------------------------------------------------------- #
#  Speichern (POST)
# --------------------------------------------------------------------------- #
async def _handle_post(cog, request):
    from .welcome import KINDS, MAX_HEADLINE, MAX_TEXT, MAX_TITLE, MAX_URL, MODES, valid_color, valid_url

    data = await request.post()
    guild = _pick(await _visible(request), data.get("guild"))
    if guild is None:
        return {"redirect": f"/cogs/{SLUG}?err=" + quote_plus("Server nicht gefunden oder keine Bearbeitungsrechte")}
    form = data.get("form")
    gconf = cog.config.guild(guild)

    if form == "test":
        # Tagesgeschäft: nur testen, nichts speichern (gespeicherte Einstellungen).
        kind = data.get("kind")
        if kind not in KINDS:
            return _redirect(guild.id, err="Unbekannte Nachricht")
        return await _test(cog, request, guild, kind, "")

    if form in KINDS:
        kind = form
        updates: dict = {f"{kind}_enabled": bool(data.get("enabled"))}
        if kind != "dm":
            raw = (data.get("channel") or "").strip()
            if raw:
                ch = next((c for c in guild.text_channels if raw.isdigit() and c.id == int(raw)), None)
                if ch is None:
                    return _redirect(guild.id, err="Kanal nicht gefunden")
                updates[f"{kind}_channel"] = ch.id
            else:
                updates[f"{kind}_channel"] = None
        mode = data.get("mode") or "text"
        if mode not in MODES:
            return _redirect(guild.id, err="Ungültige Darstellung")
        updates[f"{kind}_mode"] = mode
        text = (data.get("text") or "").replace("\r\n", "\n").strip()
        if len(text) > MAX_TEXT:
            return _redirect(guild.id, err=f"Text zu lang (max. {MAX_TEXT} Zeichen)")
        updates[f"{kind}_text"] = text
        title = (data.get("title") or "").strip()
        if len(title) > MAX_TITLE:
            return _redirect(guild.id, err=f"Titel zu lang (max. {MAX_TITLE} Zeichen)")
        updates[f"{kind}_title"] = title
        color = valid_color(data.get("color") or "")
        if color is None:
            return _redirect(guild.id, err="Ungültige Farbe")
        updates[f"{kind}_color"] = color
        image = (data.get("image") or "").strip()
        if image and valid_url(image) is None:
            return _redirect(guild.id, err=f"Ungültige Bild-URL (nur https://, max. {MAX_URL} Zeichen)")
        updates[f"{kind}_image"] = image
        if kind == "welcome":
            updates["ping_user"] = bool(data.get("ping_user"))
            updates["ignore_bots"] = bool(data.get("ignore_bots"))
            lang = data.get("language") or "de"
            if lang not in LANGUAGES:
                return _redirect(guild.id, err="Unbekannte Sprache")
            updates["language"] = lang
        for key, value in updates.items():
            await gconf.set_raw(key, value=value)
        saved = f"{_KIND_LABEL[kind]} gespeichert"
        if data.get("do") == "test":
            return await _test(cog, request, guild, kind, saved)
        return _redirect(guild.id, ok=saved)

    if form == "card":
        updates = {"card_enabled": bool(data.get("card_enabled"))}
        for key in ("card_bg_color", "card_accent", "card_text_color"):
            color = valid_color(data.get(key) or "")
            if color is None:
                return _redirect(guild.id, err="Ungültige Farbe")
            updates[key] = color
        headline = (data.get("card_headline") or "").strip()
        if len(headline) > MAX_HEADLINE:
            return _redirect(guild.id, err=f"Überschrift zu lang (max. {MAX_HEADLINE} Zeichen)")
        updates["card_headline"] = headline
        url = (data.get("card_bg_url") or "").strip()
        if url and valid_url(url) is None:
            return _redirect(guild.id, err=f"Ungültige Bild-URL (nur https://, max. {MAX_URL} Zeichen)")
        updates["card_bg_url"] = url
        for key, value in updates.items():
            await gconf.set_raw(key, value=value)
        if data.get("do") == "test":
            return await _test(cog, request, guild, "welcome", "Willkommensbild gespeichert")
        return _redirect(guild.id, ok="Willkommensbild gespeichert")

    return _redirect(guild.id, err="Unbekannte Aktion")


async def _test(cog, request, guild, kind, saved: str):
    """Testnachricht/-DM; ``saved`` = Präfix der Meldung (leer beim Test ohne Speichern)."""
    def msg(text):
        return f"{saved} – {text}" if saved else text

    member = await _dashboard_member(request, guild)
    conf = await cog.config.guild(guild).all()
    if kind == "dm":
        if member is None:
            return _redirect(guild.id, err=msg("Test-DM nicht möglich: du bist kein Mitglied dieses Servers"))
        ok = await cog.send_dm(member, conf)
        if ok:
            return _redirect(guild.id, ok=msg("Test-DM gesendet"))
        return _redirect(guild.id, err=msg("Test-DM nicht zugestellt (DMs geschlossen?)"))
    try:
        ok, err = await cog.post(member or _example(guild), kind, conf, ping=False)
    except discord.DiscordException:
        ok, err = False, "err_http"
    if ok:
        ch = cog._resolve_channel(guild, conf[f"{kind}_channel"])
        where = f" in #{ch.name}" if ch is not None else ""
        return _redirect(guild.id, ok=msg(f"Testnachricht gepostet{where}"))
    return _redirect(guild.id, err=msg(f"Test fehlgeschlagen: {_ERR_TEXT.get(err, err)}"))
