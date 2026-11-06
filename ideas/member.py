"""„Mein Bereich → Ideen“ (``/me/ideen``) für normale Server-Mitglieder.

* GET  -> Reiter „Einreichen“ (Formular), „Alle Ideen“ (nur wenn das Mitglied das Ideen-Forum in Discord
          sehen kann) und „Meine Ideen“ (eigene Ideen mit Status und letztem Team-Kommentar).
* POST form=submit -> exakt ``Ideas.submit`` – dieselbe Funktion wie das Discord-Formular (gleiche Limits,
          Cooldown, Sperre, Duplikat-Hinweis, Forum-Beitrag, Nummer unter Lock).

Keine Team-Interna: keine Einreicher-Namen fremder Ideen, kein Verlauf außer eigenen Status/Kommentaren.
"""

from __future__ import annotations

import html
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote

from .strings import OPEN_STATUSES, STATUS_EMOJI, status_label, t

SLUG = "ideen"
TONE = {"new": "info", "review": "warn", "planned": "info", "done": "ok", "rejected": "bad", "merged": "muted"}


def _pending(cog, request, values=None):
    store = cog.__dict__.setdefault("_submit_drafts", {})
    key = (request["wc_member_guild"].id, request["wc_member"].id, request.get("webcore_csrf", ""))
    now = time.monotonic()
    for old in list(store):
        if store[old]["expires"] < now:
            store.pop(old, None)
    if values is not None:
        store[key] = {"expires": now + 1800, "values": values, "token": secrets.token_urlsafe(24), "similar": []}
    return store, key, store.get(key)


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _plain(text: str) -> str:
    return (text or "").replace("**", "").replace("`", "")


def can_view(channel, member) -> bool:
    if channel is None or member is None:
        return False
    try:
        return bool(channel.permissions_for(member).view_channel)
    except Exception:  # noqa: BLE001
        return False


def _date(ts) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y") if ts else "—"


async def member_page_handler(cog, request):
    guild = request["wc_member_guild"]
    member = request["wc_member"]
    ui = request.app["webcore"].ui
    data = await cog.config.guild(guild).all()
    lang = data.get("language", "de")
    base = f"/me/{SLUG}?guild={guild.id}"
    forum = cog.forum_of(guild, data)
    visible = can_view(forum, member)
    if request.method == "POST":
        form = await request.post()
        if not data.get("member_page", True):
            return {"redirect": base + "&err=" + quote("Ideen sind im Mitglieder-Bereich ausgeschaltet")}
        if form.get("form") not in ("submit", "confirm_similar"):
            return {"redirect": base + "&err=" + quote("Unbekannte Aktion")}
        if forum is None:
            return {"redirect": base + "&err=" + quote(_plain(t(lang, "err_no_forum")))}
        if not visible:
            return {"redirect": base + "&err=" + quote(_plain(t(lang, "err_no_view")))}
        confirm = form.get("form") == "confirm_similar"
        if confirm:
            store, key, pending = _pending(cog, request)
            if not pending or not secrets.compare_digest(str(form.get("token") or ""), pending["token"]):
                return {"redirect": base + "&err=" + quote(t(lang, "similar_expired"))}
            values = pending["values"]
            store.pop(key, None)  # Bestätigung genau einmal verbrauchen, bevor submit auf Discord wartet.
        else:
            values = {k: str(form.get(k) or "") for k in ("title", "description", "category")}
            store, key, pending = _pending(cog, request, values)
        res = await cog.submit(guild, member, **values, source="web", confirm_similar=confirm)
        if confirm and not res.get("ok"):
            store.setdefault(key, pending)
        if res.get("key") == "similar_before_submit":
            pending["similar"] = res["similar"]
            return {"redirect": base + "&similar=1#einreichen"}
        text = _plain(cog.result_text(guild, lang, res, web=True))
        if res.get("ok"):
            if store.get(key) is pending:
                store.pop(key, None)
            return {"redirect": base + "&ok=" + quote(text) + "#meine"}
        return {"redirect": base + "&err=" + quote(text)}

    if not data.get("member_page", True):
        return {"title": "Ideen", "content": ui.card(body=ui.empty(
            "bi-lightbulb", "Ideen sind im Mitglieder-Bereich ausgeschaltet."))}
    ideas = [i for i in (data.get("ideas") or {}).values() if isinstance(i, dict) and not i.get("deleted")]
    mine = sorted((i for i in ideas if i.get("author_id") == member.id), key=lambda i: -i.get("nr", 0))
    head = ui.hero("bi-lightbulb", "",
                   f"Ideen für <b>{_esc(guild.name)}</b> einreichen und verfolgen. Jede Idee bekommt einen eigenen "
                   "Beitrag im Ideen-Forum; das Team setzt den Status.")
    body = ui.tab("einreichen", "Einreichen", "bi-send",
                  await _render_submit(cog, ui, request, guild, member, data, forum, visible))
    if visible:
        body += ui.tab("alle", "Alle Ideen", "bi-lightbulb", _render_all(cog, ui, guild, member, ideas, lang),
                       count=len(ideas))
    body += ui.tab("meine", "Meine Ideen", "bi-person", _render_mine(cog, ui, guild, mine, lang, visible),
                   count=len(mine))
    return {"title": "Ideen", "content": head + body}


async def _render_submit(cog, ui, request, guild, member, data, forum, visible):
    lang = data.get("language", "de")
    if forum is None:
        return ui.card(body=ui.empty("bi-lightbulb", "Der Ideen-Kanal ist noch nicht eingerichtet."))
    if not visible:
        return ui.card(body=ui.empty("bi-eye-slash", "Du kannst den Ideen-Kanal nicht sehen.",
                                     "Einreichen ist nur für Mitglieder möglich, die das Ideen-Forum in Discord sehen."))
    pre = await cog.precheck(guild, member)
    note = ui.callout(_esc(_plain(t(lang, pre["key"], **pre["kw"]))), tone="warn") if pre else ""
    cats = data.get("categories") or []
    _store, _key, pending = _pending(cog, request)
    values = pending["values"] if pending else {}
    similar = ""
    if pending and pending.get("similar"):
        links = "".join(ui.button(f"#{idea['nr']} · {idea.get('title', '')[:70]}", kind="ghost",
                                   href=cog.idea_link(guild, idea)) for idea in pending["similar"]
                        if cog.idea_link(guild, idea))
        confirm = ui.form(f"/me/{SLUG}?guild={guild.id}", ui.actions(ui.button(t(lang, "similar_continue"), icon="bi-send")),
                          csrf=request["webcore_csrf"], hidden={"form": "confirm_similar", "token": pending["token"], "guild": guild.id})
        similar = ui.card("Ähnliche Ideen", ui.callout(_esc(t(lang, "similar_before_submit")), tone="info") + links + confirm,
                          icon="bi-search")
    fields = [
        ui.field("Titel", ui.text_input("title", values.get("title", ""), placeholder="Kurz und knackig, z. B. „Wöchentlicher Spieleabend“",
                                        attrs={"maxlength": 100, "required": True}), help="Höchstens 100 Zeichen.",
                 wide=True),
        ui.field("Beschreibung", ui.textarea("description", values.get("description", ""), rows=6,
                                             placeholder="Was genau schlägst du vor und warum? (optional)"),
                 help="Höchstens 1000 Zeichen.", wide=True),
    ]
    if cats:
        fields.append(ui.field("Kategorie", ui.select("category", [(c, c) for c in cats], values.get("category"),
                                                      none_label="Ohne Kategorie")))
    limits = []
    if data.get("max_open"):
        limits.append(f"höchstens {int(data['max_open'])} offene Ideen pro Person")
    if data.get("cooldown_minutes"):
        limits.append(f"{int(data['cooldown_minutes'])} Min. Wartezeit zwischen zwei Ideen")
    desc = ("Regeln: " + ", ".join(limits) + ".") if limits else None
    form = ui.form(f"/me/{SLUG}?guild={guild.id}", ui.grid(*fields)
                   + ui.actions(ui.button("Idee einreichen", icon="bi-send")),
                   csrf=request["webcore_csrf"], hidden={"form": "submit", "guild": guild.id})
    return similar + ui.card("Neue Idee", note + form, icon="bi-send", desc=desc)


def _link_btn(ui, link):
    return ui.button("Im Forum", icon="bi-discord", kind="ghost", small=True, href=link,
                     attrs={"target": "_blank", "rel": "noopener"}) if link else ""


def _render_all(cog, ui, guild, member, ideas, lang):
    if not ideas:
        return ui.card(body=ui.empty("bi-lightbulb", "Noch keine Ideen – reiche die erste ein!"))
    rows = []
    for i in sorted(ideas, key=lambda i: (i.get("status") not in OPEN_STATUSES, -i.get("nr", 0)))[:300]:
        st = i.get("status", "new")
        own = " · <b>deine Idee</b>" if i.get("author_id") == member.id else ""
        rows.append(ui.row(
            f"<div class='wc-cell-title'><span class='mono'>#{int(i['nr'])}</span> {_esc(i.get('title', ''))}</div>"
            f"<div class='wc-cell-sub'>{_esc(i.get('category') or 'ohne Kategorie')}{own}</div>",
            ui.badge(f"{STATUS_EMOJI.get(st, '')} {status_label(lang, st)}", TONE.get(st, "muted")),
            ">" + _link_btn(ui, cog.idea_link(guild, i)),
        ))
    return ui.card("Alle Ideen", ui.table(["Idee", "Status", ">"], rows, search=True,
                                          search_placeholder="Ideen durchsuchen …", id="me-ideas"),
                   icon="bi-lightbulb", desc="Offene Ideen zuerst, dann umgesetzte/abgelehnte.")


def _render_mine(cog, ui, guild, mine, lang, visible):
    if not mine:
        return ui.card(body=ui.empty("bi-person", "Du hast noch keine Ideen eingereicht."))
    rows = []
    for i in mine:
        st = i.get("status", "new")
        last = next((h for h in reversed(i.get("history") or [])
                     if isinstance(h, dict) and h.get("comment")), None)
        comment = f"<div class='wc-cell-sub'>💬 {_esc(last['comment'][:300])}</div>" if last else ""
        rows.append(ui.row(
            f"<div class='wc-cell-title'><span class='mono'>#{int(i['nr'])}</span> {_esc(i.get('title', ''))}</div>"
            f"<div class='wc-cell-sub'>{_esc(i.get('category') or 'ohne Kategorie')} · eingereicht am "
            f"{_date(i.get('created_ts'))}</div>{comment}",
            ui.badge(f"{STATUS_EMOJI.get(st, '')} {status_label(lang, st)}", TONE.get(st, "muted")),
            ">" + (_link_btn(ui, cog.idea_link(guild, i)) if visible else ""),
        ))
    return ui.card("Meine Ideen", ui.table(["Idee", "Status", ">"], rows), icon="bi-person",
                   desc="Status und letzter Kommentar des Teams zu deinen Ideen.")

