"""WebCore-Dashboard für den OnlyImageVideo-Cog.

* GET                 -> Übersicht: Statistik, Einstellungen, Funktionsweise
* POST form=settings  -> Einstellungen speichern (Post/Redirect/Get)

Nur Theme-Klassen (card-x, stat, table …) plus Bootstrap-Formularklassen; kein
eigenes Design. Nutzereingaben werden mit ``html.escape`` abgesichert.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from aiohttp import web

from .detect import MEDIA_HOSTS
from .strings import LANGUAGES, OVERRIDABLE_KEYS, STRINGS

NOTIFY_MIN = 2
NOTIFY_MAX = 60

_FORM_STYLE = """
<style>
  .oiv-form label{display:block;color:var(--muted);font-size:.8rem;
    text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .oiv-form input,.oiv-form select,.oiv-form textarea{width:100%;background:var(--panel-2);
    color:var(--text);border:1px solid var(--border);border-radius:9px;
    padding:9px 11px;font-family:inherit;font-size:.92rem}
  .oiv-form textarea{min-height:80px;resize:vertical;line-height:1.5}
  .oiv-form .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .oiv-check{display:flex;align-items:center;gap:8px;margin-top:12px}
  .oiv-check input{width:auto}
  .oiv-flash{background:rgba(61,220,151,.12);border:1px solid var(--accent);
    color:var(--text);border-radius:10px;padding:11px 14px;margin-bottom:18px}
  .oiv-title{font-family:"Archivo",sans-serif;font-weight:700;font-size:1.15rem;margin:0 0 14px}
  .oiv-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px}
  .oiv-bar{display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}
  .oiv-spacer{height:24px}
  .oiv-list{margin:0;padding-left:18px;color:var(--muted);line-height:1.7}
  .oiv-list code{color:var(--text)}
</style>
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _options(items, selected_ids) -> str:
    sel = {str(s) for s in (selected_ids or [])}
    out = []
    for ident, label in items:
        is_sel = " selected" if str(ident) in sel else ""
        out.append(f"<option value='{_esc(ident)}'{is_sel}>{_esc(label)}</option>")
    return "".join(out)


def _channel_items(guild):
    items = []
    for c in guild.text_channels:
        items.append((c.id, f"# {c.name}"))
    for c in getattr(guild, "forums", []):
        items.append((c.id, f"[Forum] {c.name}"))
    for c in guild.voice_channels:
        items.append((c.id, f"[Voice] {c.name}"))
    return items


async def dashboard_handler(cog, request):
    if request.method == "POST":
        return await _handle_post(cog, request)
    return await _render(cog, request)


def _selected_guild(cog, request):
    gid = request.query.get("guild")
    if gid and gid.isdigit():
        g = cog.bot.get_guild(int(gid))
        if g is not None:
            return g
    guilds = sorted(cog.bot.guilds, key=lambda g: g.name.lower())
    return guilds[0] if guilds else None


async def _render(cog, request):
    guild = _selected_guild(cog, request)
    if guild is None:
        return {"title": "Nur Medien", "content": "<div class='card-x'>Der Bot ist auf keinem Server.</div>"}

    conf = await cog.config.guild(guild).all()
    csrf = request.get("webcore_csrf", "")

    flash = ""
    if request.query.get("ok"):
        flash = f"<div class='oiv-flash'>{_esc(request.query.get('ok'))}</div>"

    guild_opts = _options([(g.id, g.name) for g in sorted(cog.bot.guilds, key=lambda g: g.name.lower())], [guild.id])
    bar = (
        "<div class='oiv-bar'>"
        "<form method='get' action='/cogs/onlyimagevideo' class='oiv-form' style='margin:0'>"
        f"<select name='guild' onchange='this.form.submit()'>{guild_opts}</select>"
        "</form>"
        f"<span class='mono' style='color:var(--muted)'>{_esc(guild.name)}</span>"
        "</div>"
    )

    n_channels = len(conf.get("channels") or [])
    n_roles = len(conf.get("exempt_roles") or [])
    deleted = int(conf.get("deleted_total", 0))
    stats = (
        "<div class='oiv-grid'>"
        f"<div class='stat'><div class='stat-label'>Überwachte Kanäle</div><div>{n_channels}</div></div>"
        f"<div class='stat'><div class='stat-label'>Ausnahme-Rollen</div><div>{n_roles}</div></div>"
        f"<div class='stat'><div class='stat-label'>Gelöschte Nachrichten</div><div>{deleted}</div></div>"
        "</div><div class='oiv-spacer'></div>"
    )

    settings = _render_settings(guild, conf, csrf)
    info = _render_info(conf)

    return {
        "title": "Nur Medien",
        "content": _FORM_STYLE + bar + flash + stats + settings
        + "<div class='oiv-spacer'></div>" + info,
    }


def _render_settings(guild, conf, csrf) -> str:
    lang_opts = _options(list(LANGUAGES.items()), [conf.get("language", "de")])
    channel_opts = _options(_channel_items(guild), conf.get("channels") or [])
    role_opts = _options([(r.id, r.name) for r in guild.roles if not r.is_default()],
                         conf.get("exempt_roles") or [])

    overrides = conf.get("messages") or {}
    override_fields = ""
    for key in OVERRIDABLE_KEYS:
        current = overrides.get(key, "")
        default = STRINGS["de"].get(key, "")
        override_fields += (
            f"<label>{_esc(key)} <span style='text-transform:none;color:var(--muted)'>"
            "(Platzhalter {user} wird ersetzt)</span></label>"
            f"<textarea name='ovr_{key}' placeholder='{_esc(default)}'>{_esc(current)}</textarea>"
        )

    def chk(field):
        return "checked" if conf.get(field) else ""

    return (
        "<div class='card-x'><div class='oiv-title'>Einstellungen</div>"
        "<form class='oiv-form' method='post' action='/cogs/onlyimagevideo'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        "<input type='hidden' name='form' value='settings'>"
        f"<input type='hidden' name='guild' value='{guild.id}'>"
        f"<label>Sprache</label><select name='language'>{lang_opts}</select>"
        "<label>Nur-Medien-Kanäle (Mehrfachauswahl – Threads erben die Regel)</label>"
        f"<select name='channels' multiple size='6'>{channel_opts}</select>"
        "<label>Ausnahme-Rollen (Mehrfachauswahl)</label>"
        f"<select name='exempt_roles' multiple size='4'>{role_opts}</select>"
        f"<div class='oiv-check'><input type='checkbox' name='allow_links' {chk('allow_links')}><span>Links zu Mediendateien zählen als Medium</span></div>"
        f"<div class='oiv-check'><input type='checkbox' name='allow_hosts' {chk('allow_hosts')}><span>GIF-/Medien-Dienste (Tenor, Giphy …) zählen als Medium</span></div>"
        f"<div class='oiv-check'><input type='checkbox' name='allow_stickers' {chk('allow_stickers')}><span>Sticker zählen als Bild</span></div>"
        f"<div class='oiv-check'><input type='checkbox' name='ignore_bots' {chk('ignore_bots')}><span>Bots/Webhooks ausnehmen</span></div>"
        f"<div class='oiv-check'><input type='checkbox' name='notify' {chk('notify')}><span>Hinweis beim Löschen senden</span></div>"
        f"<label>Hinweis verschwindet nach (Sekunden, {NOTIFY_MIN}–{NOTIFY_MAX})</label>"
        f"<input type='number' name='notify_delete_after' min='{NOTIFY_MIN}' max='{NOTIFY_MAX}' value='{int(conf.get('notify_delete_after', 6))}'>"
        "<div class='oiv-spacer'></div>"
        "<div class='oiv-title' style='font-size:1rem'>Hinweistext überschreiben</div>"
        f"{override_fields}"
        "<div class='oiv-spacer'></div>"
        "<button class='btn-accent' type='submit'>Speichern</button>"
        "</form></div>"
    )


def _render_info(conf) -> str:
    items = ["hochgeladene Bilder und Videos (inkl. <code>.gif</code>)"]
    if conf.get("allow_stickers"):
        items.append("Sticker")
    if conf.get("allow_links"):
        items.append("direkte Links zu Mediendateien (z. B. <code>.png</code>, <code>.mp4</code>)")
    if conf.get("allow_hosts"):
        hosts = ", ".join(f"<code>{_esc(h)}</code>" for h in MEDIA_HOSTS[:5])
        items.append(f"Links von GIF-/Medien-Diensten ({hosts} …)")
    li = "".join(f"<li>{i}</li>" for i in items)
    return (
        "<div class='card-x'><div class='oiv-title'>Funktionsweise</div>"
        "<p style='color:var(--muted);margin-top:0'>In den ausgewählten Kanälen (und deren Threads) "
        "werden Nachrichten ohne Medium gelöscht. Als gültiges Medium zählt aktuell:</p>"
        f"<ul class='oiv-list'>{li}</ul>"
        "<p style='color:var(--muted)'>Bots/Webhooks und Mitglieder mit einer Ausnahme-Rolle sind "
        "ausgenommen. Damit das Löschen funktioniert, braucht der Bot in den Kanälen das Recht "
        "<code>Nachrichten verwalten</code>.</p></div>"
    )


async def _handle_post(cog, request):
    data = await request.post()
    if data.get("form") != "settings":
        raise web.HTTPFound("/cogs/onlyimagevideo")
    gid = data.get("guild")
    guild = cog.bot.get_guild(int(gid)) if gid and gid.isdigit() else None
    if guild is None:
        raise web.HTTPFound("/cogs/onlyimagevideo?ok=Server+nicht+gefunden")

    gconf = cog.config.guild(guild)

    lang = (data.get("language") or "de").lower()
    if lang in LANGUAGES:
        await gconf.language.set(lang)

    channels = [int(c) for c in data.getall("channels", []) if str(c).isdigit()]
    await gconf.channels.set(channels)
    roles = [int(r) for r in data.getall("exempt_roles", []) if str(r).isdigit()]
    await gconf.exempt_roles.set(roles)

    await gconf.allow_links.set("allow_links" in data)
    await gconf.allow_hosts.set("allow_hosts" in data)
    await gconf.allow_stickers.set("allow_stickers" in data)
    await gconf.ignore_bots.set("ignore_bots" in data)
    await gconf.notify.set("notify" in data)

    try:
        secs = int(data.get("notify_delete_after") or 6)
        await gconf.notify_delete_after.set(max(NOTIFY_MIN, min(NOTIFY_MAX, secs)))
    except (TypeError, ValueError):
        pass

    overrides = {}
    for key in OVERRIDABLE_KEYS:
        val = (data.get(f"ovr_{key}") or "").strip()
        if val:
            overrides[key] = val
    await gconf.messages.set(overrides)

    raise web.HTTPFound(f"/cogs/onlyimagevideo?guild={guild.id}&ok=" + quote("Gespeichert"))
