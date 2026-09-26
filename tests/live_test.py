"""Posten-Pfade der Dashboards mit live_harness testen (echte isinstance-Prüfungen, Discord-Limits).

Aufruf: python tests/live_test.py   -> druckt je Pfad OK/FEHLER, am Ende Zusammenfassung;
Exit-Code 1, wenn mindestens ein Pfad fehlschlägt.
"""
import asyncio, re, sys, time, types
from urllib.parse import unquote_plus
import live_harness as L
import discord
from aiohttp.test_utils import TestServer, TestClient

OWNER = {"X-Test-User": "1"}
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("OK    " if cond else "FEHLER") + f" {name}" + (f"  – {detail}" if detail and not cond else ""))


BAD = re.compile(r"(nicht gefunden|fehlgeschlagen|ungültig|fehler|keine |abgelehnt|nicht erlaubt|bitte |darfst du nicht)", re.I)


def is_bad(loc):
    """Wird die Meldung als Fehler-Toast angezeigt? (err= oder WebCore-Schlüsselwort in ok=)"""
    if "err=" in loc:
        return True
    m = re.search(r"[?&]ok=([^&]*)", loc)
    return bool(m and BAD.search(m.group(1)))


def ops(since, op=None, ch=None):
    return [e for e in L.LOG[since:] if (op is None or e[0] == op) and (ch is None or e[1] == ch)]


class Resp:
    def __init__(self): self.sent = []; self._done = False; self.deferred = False
    def is_done(self): return self._done
    async def send_message(self, content=None, *, ephemeral=False, view=None, embed=None, **kw):
        self._done = True; self.sent.append(("send", content, ephemeral))
    async def edit_message(self, *, content=None, view=None, **kw):
        self._done = True; self.sent.append(("edit", content, True))
    async def defer(self, *, ephemeral=False, thinking=False):
        self._done = True; self.deferred = True


class Followup:
    def __init__(self, resp): self.resp = resp
    async def send(self, content=None, *, ephemeral=False, **kw):
        self.resp.sent.append(("followup", content, ephemeral))


def interaction(guild, user, custom_id=None, values=None):
    r = Resp()
    return types.SimpleNamespace(
        type=discord.InteractionType.component, guild=guild, user=user, response=r, followup=Followup(r),
        data={"custom_id": custom_id, **({"values": values} if values else {})}, channel=None, message=None)


async def main():
    wc, bot, app = await L.make_app()
    client = TestClient(TestServer(app)); await client.start_server()
    g = bot.guilds[0]
    allg, support, ank, logs = g.text_channels
    logs_ch = logs
    lena = g.get_member(11)

    async def page(path):
        r = await client.get(path, headers=OWNER)
        return r.status, await r.text()

    async def csrf():
        _, t = await page("/cogs/example?guild=1000")
        return re.search(r"name=['\"]csrf_token['\"] value=['\"]([^'\"]+)", t).group(1)
    tok = await csrf()

    async def post(slug, **data):
        data = {"csrf_token": tok, **data}
        r = await client.post(f"/cogs/{slug}", headers=OWNER, data=data, allow_redirects=False)
        loc = unquote_plus(r.headers.get("Location", ""))
        return r.status, loc

    # ------------------------------------------------------------ tickets
    n = len(L.LOG)
    st, loc = await post("tickets", form="panel_create", guild="1000", channel_id=str(support.id),
                         title="Support", description="Hilfe gesucht?", mode="button",
                         reasons="Bug | 🐛 | Fehler melden\nFrage | ❓")
    panels = await bot._cogs["Tickets"].config.guild(g).panels()
    check("tickets: Panel (Buttons) erstellen & posten", ops(n, "send", support.id) and panels[-1]["message_id"], loc)
    n = len(L.LOG)
    st, loc = await post("tickets", form="panel_create", guild="1000", channel_id=str(support.id),
                         title="Support 2", mode="dropdown", reasons="Bug | abc | kaputtes Emoji\nFrage")
    panels = await bot._cogs["Tickets"].config.guild(g).panels()
    check("tickets: Dropdown-Panel mit ungültigem Emoji -> zweiter Versuch ohne Emoji", panels[-1]["message_id"], loc)
    pid = panels[0]["id"]
    n = len(L.LOG)
    st, loc = await post("tickets", form="panel_save", guild="1000", panel_id=pid, channel_id=str(support.id),
                         title="Support neu", mode="button", reasons="Bug | 🐛\nFrage | ❓\nSonstiges")
    check("tickets: Panel bearbeiten -> Nachricht editiert", ops(n, "edit", support.id) and not ops(n, "send"), loc)
    n = len(L.LOG)
    st, loc = await post("tickets", form="panel_save", guild="1000", panel_id=pid, channel_id=str(ank.id),
                         title="Support neu", mode="button", reasons="Bug")
    check("tickets: Panel Kanalwechsel -> alt gelöscht, neu gepostet", ops(n, "delete", support.id) and ops(n, "send", ank.id), loc)
    support.forbid = {"send"}
    st, loc = await post("tickets", form="panel_create", guild="1000", channel_id=str(support.id), title="X", mode="button", reasons="A")
    check("tickets: Posten ohne Rechte -> Fehler-Toast", is_bad(loc), loc)
    support.forbid = set()

    # ------------------------------------------------------------ poll
    n = len(L.LOG)
    st, loc = await post("poll", form="create", guild="1000", question="Pizza oder Pasta?", options="Pizza\nPasta\nBeides",
                         channel=str(allg.id), duration="2h")
    polls = await bot._cogs["Poll"].config.guild(g).polls()
    p = next(iter(polls.values()))
    check("poll: Umfrage anlegen & posten", ops(n, "send", allg.id) and p["message_id"], loc)
    n = len(L.LOG)
    st, loc = await post("poll", form="action", guild="1000", poll_id=p["id"], action="close")
    check("poll: schließen -> Nachricht editiert", ops(n, "edit", allg.id), loc)
    long_opts = "\n".join(f"Option {i} " + "x" * 90 for i in range(10))
    n = len(L.LOG)
    st, loc = await post("poll", form="create", guild="1000", question="Q" * 400, options=long_opts, channel=str(allg.id))
    check("poll: lange Frage/10 lange Optionen -> Discord-Limits eingehalten", ops(n, "send", allg.id), loc)
    n = len(L.LOG)
    st, loc = await post("poll", form="action", guild="1000", poll_id=p["id"], action="delete")
    check("poll: löschen -> Nachricht gelöscht", ops(n, "delete", allg.id), loc)
    st, loc = await post("poll", form="create", guild="1000", question="Nur eine", options="A", channel=str(allg.id))
    check("poll: Validierung meldet Fehler als Fehler-Toast", is_bad(loc), loc)
    st, loc = await post("poll", form="create", guild="1000", question="Q", options="A\nB", channel=str(allg.id), duration="bald")
    check("poll: unbekannte Dauer -> Fehler-Toast", is_bad(loc), loc)

    # ------------------------------------------------------------ raidhelper
    rh = bot._cogs["RaidHelper"]
    now = int(time.time())
    n = len(L.LOG)
    ev = await rh.create_event(g, game="wow_retail", title="Raid " + "R" * 300, description="D" * 5000, leader_id=1,
                               channel_id=allg.id, start_ts=now + 86400)
    check("raidhelper: Event posten (lange Texte gekappt)", ev["message_id"] and ops(n, "send", allg.id))
    n = len(L.LOG)
    st, loc = await post("raidhelper", form="action", guild="1000", event_id=ev["id"], action="close")
    check("raidhelper: Dashboard schließen -> editiert", ops(n, "edit", allg.id), loc)
    # Anmelden per Button
    user = lena
    inter = interaction(g, user, f"rh:cls:{ev['id']}", ["krieger"])
    st, loc = await post("raidhelper", form="action", guild="1000", event_id=ev["id"], action="reopen")
    await rh.on_interaction(inter)
    check("raidhelper: Klassen-Auswahl beantwortet", inter.response.sent, str(inter.response.sent))
    # Aufräumen: altes abgeschlossenes Event, Serie mit/ohne Nachfolger
    old = now - 40 * 86400
    single = await rh.create_event(g, game="wow_retail", title="Alt", description="", leader_id=1, channel_id=allg.id, start_ts=old)
    s1 = await rh.create_event(g, game="wow_retail", title="Serie", description="", leader_id=1, channel_id=allg.id,
                               start_ts=old, recurrence="weekly")
    tail = await rh.create_event(g, game="wow_retail", title="Serie-Ende", description="", leader_id=1, channel_id=allg.id,
                                 start_ts=old + 3600, recurrence="weekly")
    recent = await rh.create_event(g, game="wow_retail", title="Neu", description="", leader_id=1, channel_id=allg.id, start_ts=now - 5 * 86400)
    async with rh.config.guild(g).events() as evs:
        for e in (single, s1, tail, recent):
            evs[e["id"]]["completed"] = True; evs[e["id"]]["closed"] = True
    # Folgetermin von s1 per _spawn_next (setzt series)
    await rh._spawn_next(g, {**s1})
    n_msgs = len(allg._messages)
    st, loc = await post("raidhelper", form="settings", guild="1000", language="de", default_game="wow_retail",
                         timezone="Europe/Berlin", reminders="on", cleanup_days="30")
    evs = await rh.config.guild(g).events()
    check("raidhelper: Aufräumen löscht altes Einzel-Event", single["id"] not in evs, loc)
    check("raidhelper: Aufräumen löscht Serien-Event mit Folgetermin", s1["id"] not in evs)
    check("raidhelper: letztes Glied einer Serie bleibt", tail["id"] in evs)
    check("raidhelper: junges Event bleibt", recent["id"] in evs and ev["id"] in evs)
    check("raidhelper: keine Discord-Nachrichten gelöscht", len(allg._messages) == n_msgs)
    check("raidhelper: Einstellung gespeichert + Meldung", await rh.config.guild(g).cleanup_days() == 30 and "alte Events gelöscht" in loc, loc)
    _, html = await page("/cogs/raidhelper?guild=1000")
    check("raidhelper: Feld cleanup_days im Dashboard", "name='cleanup_days'" in html and "Tage" in html)
    st, loc = await post("raidhelper", form="settings", guild="1000", language="de", cleanup_days="-3")
    check("raidhelper: ungültige Tage -> err", "err=" in loc and await rh.config.guild(g).cleanup_days() == 30, loc)
    # Buttons an gelöschtem Event
    for cid, vals in ((f"rh:cls:{single['id']}", ["krieger"]), (f"rh:spec:{single['id']}:krieger:furor", ["furor"]),
                      (f"rh:st:{single['id']}:late", None), (f"rh:leave:{single['id']}", None)):
        inter = interaction(g, user, cid, vals)
        await rh.on_interaction(inter)
        s = inter.response.sent
        check(f"raidhelper: Button an gelöschtem Event ({cid.split(':')[1]}) -> ephemeral Hinweis",
              s and "existiert nicht mehr" in (s[0][1] or "") and s[0][2], str(s))
    # Tick mit kaputtem Server darf Schleife nicht beenden
    rh._last_cleanup.clear()
    orig_cleanup = rh.cleanup_old_events
    called = []
    async def flaky(guild, **kw):
        called.append(guild.id)
        if guild.id == 1000:
            raise RuntimeError("kaputte Daten")
        return await orig_cleanup(guild, **kw)
    rh.cleanup_old_events = flaky
    async with rh.config.guild(bot.guilds[1]).events() as evs2:
        evs2["x"] = {"id": "x", "title": "alt", "game": "wow_retail", "start_ts": old, "completed": True, "signups": {}}
    try:
        await rh._reminder_tick.coro(rh)
        ok_tick = 1000 in called and 2000 in called and "x" not in await rh.config.guild(bot.guilds[1]).events()
        check("raidhelper: Tick – Fehler auf Server A stoppt Aufräumen auf Server B nicht", ok_tick, str(called))
    except Exception as e:  # noqa: BLE001
        check("raidhelper: Tick – Fehler auf Server A stoppt Aufräumen auf Server B nicht", False, repr(e))
    called.clear()
    await rh._reminder_tick.coro(rh)
    check("raidhelper: Aufräumen höchstens stündlich", not called, str(called))
    rh.cleanup_old_events = orig_cleanup
    # Befehl
    sent = []
    ctx = types.SimpleNamespace(guild=g, send=lambda m, **k: _append(sent, m))
    await rh.raidset_cleanup.callback(rh, ctx, 0)
    await rh.raidset_cleanup.callback(rh, ctx, 14)
    await rh.raidset_cleanup.callback(rh, ctx, 99999)
    check("raidhelper: [p]raidset cleanup 0/14/99999", "aus" in sent[0] and "14 Tagen" in sent[1] and "0 bis 3650" in sent[2], str(sent))
    await rh.config.guild(g).cleanup_days.set(30)

    # ------------------------------------------------------------ sticky
    n = len(L.LOG)
    st, loc = await post("sticky", form="save", guild="1000", channel=str(logs.id), mode="text", text="Bitte Regeln lesen @everyone")
    check("sticky: anlegen (Text) -> gepostet", ops(n, "send", logs.id), loc)
    n = len(L.LOG)
    st, loc = await post("sticky", form="save", guild="1000", channel=str(logs.id), mode="embed", text="Neu",
                         embed_title="Hinweis", embed_color="#ff0000", embed_footer="Team")
    check("sticky: ändern -> alte gelöscht, neu gepostet", ops(n, "delete", logs.id) and ops(n, "send", logs.id), loc)
    n = len(L.LOG)
    st, loc = await post("sticky", form="save", guild="1000", channel=str(logs.id), mode="text", text="Per Webhook",
                         webhook="on", webhook_name="Info")
    check("sticky: Webhook-Modus -> Webhook angelegt + gesendet", ops(n, "webhook_create", logs.id) and ops(n, "webhook_send", logs.id), loc)
    n = len(L.LOG)
    st, loc = await post("sticky", form="toggle", guild="1000", channel=str(logs.id))
    check("sticky: deaktivieren -> Webhook-Nachricht gelöscht", ops(n, "webhook_delete", logs.id), loc)
    st, loc = await post("sticky", form="save", guild="1000", channel=str(logs.id), mode="text", text="x" * 2100)
    check("sticky: zu langer Text abgewiesen (Fehler-Toast)", is_bad(loc), loc)

    # ------------------------------------------------------------ changelog
    cl = bot._cogs["Changelog"]
    await cl.config.guild(g).channel_id.set(ank.id)
    await cl.config.guild(g).ping_role_id.set(1101); await cl.config.guild(g).ping_enabled.set(True)
    inter = interaction(g, lena)
    n = len(L.LOG)
    await cl.handle_modal_submit(inter, title="Version 1.2", neu="A\nB", geaendert="C", fixes="", hinweis="Achtung",
                                 category_emoji="✨", category_label="Feature", lang="de")
    check("changelog: Eintrag posten (Ping + Embed)", len(ops(n, "send", ank.id)) == 2 and inter.response.sent, str(inter.response.sent))
    await cl.config.guild(g).messages.set({"embed_title": "📋 Changelog – {title} – bitte aufmerksam lesen und im Team weitergeben"})
    inter = interaction(g, lena)
    n = len(L.LOG)
    await cl.handle_modal_submit(inter, title="T" * 230, neu="A", geaendert="", fixes="", hinweis="",
                                 category_emoji="✨", category_label="Feature", lang="de")
    check("changelog: langer Titel + Titel-Vorlage -> trotzdem gepostet", ops(n, "send", ank.id)[-1:] and "err" not in str(inter.response.sent) and any(
        e[2].get("embeds") for e in ops(n, "send", ank.id)), str(inter.response.sent))
    await cl.config.guild(g).messages.set({})
    entries = await cl.config.guild(g).entries()
    eid = next(iter(entries))
    n = len(L.LOG)
    st, loc = await post("changelog", form="action", action="delete", guild="1000", entry_id=eid)
    check("changelog: Dashboard löschen -> Nachricht gelöscht", ops(n, "delete", ank.id), loc)

    # ------------------------------------------------------------ autorole
    ar = bot._cogs["Autorole"]
    st, loc = await post("autorole", form="panel_create", guild="1000", name="Farben")
    pid = next(iter(await ar.config.guild(g).panels()))
    st, loc = await post("autorole", form="panel_save", guild="1000", panel=pid, channel_id=str(allg.id), style="buttons",
                         mode="toggle", use_embed="on", title="Rollen", color="#3ddc97", text="Wähle")
    st, loc = await post("autorole", form="panel_role_add", guild="1000", panel=pid, role_id="1104", label="VIP", emoji="⭐", style="primary")
    st, loc = await post("autorole", form="panel_role_add", guild="1000", panel=pid, role_id="1101", label="Support", emoji="abc", style="success")
    n = len(L.LOG)
    st, loc = await post("autorole", form="panel_post", guild="1000", panel=pid)
    check("autorole: Panel posten (ein Emoji ungültig) -> ohne Emojis gepostet + Hinweis", ops(n, "send", allg.id) and "Emoji" in loc, loc)
    n = len(L.LOG)
    st, loc = await post("autorole", form="panel_post", guild="1000", panel=pid)
    check("autorole: erneut posten -> editiert statt doppelt", ops(n, "edit", allg.id) and not ops(n, "send"), loc)
    allg.forbid = {"send"}
    p2 = (await post("autorole", form="panel_create", guild="1000", name="Ohne Rechte"))[1]
    pid2 = re.search(r"panel=([0-9a-f]+)", p2).group(1)
    await post("autorole", form="panel_save", guild="1000", panel=pid2, channel_id=str(allg.id), style="buttons", mode="toggle", title="x", text="y")
    await post("autorole", form="panel_role_add", guild="1000", panel=pid2, role_id="1104", label="VIP")
    st, loc = await post("autorole", form="panel_post", guild="1000", panel=pid2)
    check("autorole: ohne Senderechte -> Fehler-Toast", is_bad(loc), loc)
    allg.forbid = set()
    n = len(L.LOG)
    st, loc = await post("autorole", form="panel_save", guild="1000", panel=pid, channel_id=str(allg.id), style="select",
                         mode="toggle", unique="on", use_embed="on", title="Rollen", text="Wähle")
    check("autorole: Stil -> Dropdown aktualisiert Nachricht", ops(n, "edit", allg.id), loc)
    n = len(L.LOG)
    st, loc = await post("autorole", form="panel_save", guild="1000", panel=pid, channel_id=str(ank.id), style="select",
                         mode="toggle", unique="on", use_embed="on", title="Rollen", text="Wähle")
    check("autorole: Kanalwechsel -> alte Nachricht gelöscht, neu gepostet (kein Doppel-Panel)",
          ops(n, "delete", allg.id) and ops(n, "send", ank.id), loc)
    n = len(L.LOG)
    st, loc = await post("autorole", form="panel_delete", guild="1000", panel=pid)
    check("autorole: Panel löschen -> Nachricht gelöscht", ops(n, "delete", ank.id), loc)

    # ------------------------------------------------------------ organigram
    og = bot._cogs["Organigram"]
    st, loc = await post("organigram", form="chart_new", guild="1000", name="Team", title="Unser Team", pattern="baum",
                         mode="bild", accent="#3ddc97", show_avatars="on", show_vacant="on", auto_update="on")
    cid = re.search(r"chart=([0-9a-f]+)", loc).group(1)
    await post("organigram", form="node_save", guild="1000", chart=cid, label="Leitung", role_id="1102", emoji="👑")
    await post("organigram", form="node_save", guild="1000", chart=cid, label="Support", role_id="1101")
    r = await client.get(f"/cogs/organigram?guild=1000&preview={cid}", headers=OWNER)
    body = await r.read()
    check("organigram: Vorschau-PNG", r.status == 200 and body[:8] == b"\x89PNG\r\n\x1a\n", f"{r.status} {body[:80]!r}")
    for mode in ("bild", "embed", "text"):
        n = len(L.LOG)
        st, loc = await post("organigram", form="post", guild="1000", chart=cid, channel=str(ank.id), mode=mode)
        check(f"organigram: posten ({mode})", ("Gepostet" in loc) and (ops(n, "send", ank.id) or ops(n, "edit", ank.id)), loc)
    posts = (await og.config.guild(g).charts())[cid]["posts"]
    check("organigram: ein Post je Kanal (weiter editiert)", len(posts) == 1, str(posts))

    # ------------------------------------------------------------ guard
    gd = bot._cogs["Guard"]
    gconf = gd.config.guild(g)
    await gconf.hp_channel.set(logs.id); await gconf.hp_enabled.set(True)
    legacy = await logs.send("🚫 alter Warntext")   # Altbestand: ID nicht gespeichert
    logs.topic = gd.config and (await gd._text(g, "hp_warning"))
    base = dict(form="settings", guild="1000", language="de", hp_enabled="on", hp_channel=str(logs.id), hp_action="softban")
    n = len(L.LOG)
    st, loc = await post("guard", **base, ovr_hp_warning="Neuer Warntext A")
    check("guard: Altbestand -> letzte eigene Nachricht editiert", ops(n, "edit", logs.id) and legacy.content == "Neuer Warntext A"
          and await gconf.hp_message_id() == legacy.id and "aktualisiert" in loc, loc)
    check("guard: Kanalthema mit altem Text nachgezogen", logs.topic == "Neuer Warntext A", str(logs.topic))
    n = len(L.LOG)
    st, loc = await post("guard", **base, ovr_hp_warning="Neuer Warntext A")
    check("guard: unveränderter Text -> nichts angefasst", not ops(n, "edit") and not ops(n, "send"), loc)
    n = len(L.LOG)
    st, loc = await post("guard", **base, ovr_hp_warning="Text B")
    check("guard: gespeicherte ID -> fetch+edit", ops(n, "fetch", logs.id) and legacy.content == "Text B", loc)
    await legacy.delete()
    for m in list(logs._messages.values()):
        if m.author is L.BOT_USER:
            await m.delete()
    n = len(L.LOG)
    st, loc = await post("guard", **base, ovr_hp_warning="Text C")
    check("guard: Nachricht weg -> neu gepostet + ID gemerkt", ops(n, "send", logs.id) and "neu gepostet" in loc
          and logs._messages.get(await gconf.hp_message_id()).content == "Text C", loc)
    logs.forbid = {"send", "history", "edit"}
    st, loc = await post("guard", **base, ovr_hp_warning="Text D")
    check("guard: fehlende Rechte -> err, trotzdem gespeichert", "err=" in loc and "Rechte" in loc
          and (await gconf.messages()).get("hp_warning") == "Text D", loc)
    logs.forbid = set()
    await gconf.hp_channel.set(123456)  # Kanal weg (Formular sendet ihn nicht mehr -> direkt setzen)
    st, loc = await post("guard", **{**base, "hp_channel": ""}, ovr_hp_warning="Text E")
    check("guard: ohne Kanal -> kein Fehler, nur gespeichert", "ok=" in loc, loc)
    await gconf.hp_channel.set(logs.id)
    del logs  # (Kanal-Objekt bleibt in guild)
    chan = g.get_channel(g.id + 4)
    g.text_channels.remove(chan)
    st, loc = await post("guard", **base, ovr_hp_warning="Text F")
    check("guard: Kanal gelöscht -> Hinweis", "ok=" in loc or "err=" in loc, loc)
    g.text_channels.append(chan)
    await gconf.hp_channel.set(chan.id)
    sent = []
    ctx = types.SimpleNamespace(guild=g, send=lambda m, **k: _append(sent, m))
    await gd.hp_warning.callback(gd, ctx, text="Per Befehl")
    check("guard: [p]guardset honeypot warning <text>", "aktualisiert" in sent[-1] or "gepostet" in sent[-1], str(sent))
    await gd.hp_warning.callback(gd, ctx, text="reset")
    check("guard: warning reset -> Standardtext", "hp_warning" not in (await gconf.messages())
          and any("Bitte hier nichts schreiben" in m.content for m in chan._messages.values()), str(sent))
    # hp create speichert ID
    sent = []
    ctx = types.SimpleNamespace(guild=g, send=lambda m, **k: _append(sent, m))
    await gd.hp_create.callback(gd, ctx, name="falle")
    newch = g.text_channels[-1]
    check("guard: honeypot create merkt Nachrichten-ID", await gconf.hp_message_id() in newch._messages, str(sent))

    # ------------------------------------------------------------ autoroom
    ao = bot._cogs["AutoRoom"]
    lobby = g.voice_channels[0]
    r = await client.post("/cogs/autoroom", headers=OWNER, allow_redirects=False,
                          data={"csrf_token": tok, "action": "add", "guild_id": "1000", "channel_id": str(lobby.id),
                                "template": "🔊 {user}", "limit": "5", "bitrate": "500", "visibility": "public"})
    src = (await ao.config.guild(g).sources()).get(str(lobby.id), {})
    check("autoroom: Neue Quelle mit Bitrate (auf Server-Max begrenzt)", src.get("bitrate_kbps") == 96, str(src))
    await ao.config.guild(g).sources.set({})
    r = await client.post("/cogs/autoroom", headers=OWNER, allow_redirects=False,
                          data={"csrf_token": tok, "action": "add", "guild_id": "1000", "channel_id": str(lobby.id),
                                "template": "", "limit": "0", "bitrate": "", "visibility": "public"})
    src = (await ao.config.guild(g).sources()).get(str(lobby.id), {})
    check("autoroom: Neue Quelle ohne Bitrate -> Server-Standard", "bitrate_kbps" in src and src["bitrate_kbps"] is None, str(src))
    await ao.config.guild(g).sources.set({})
    _, html = await page("/cogs/autoroom?guild=1000")
    check("autoroom: Feld Bitrate im Formular Neue Quelle", html.count("name='bitrate'") == 1 or "name='bitrate'" in html.split("Neue Quelle")[-1])

    # ------------------------------------------------------------ Grenzfälle (Discord-Limits)
    pc = bot._cogs["Poll"]
    await pc.config.guild(g).max_options.set(25)
    n = len(L.LOG)
    st, loc = await post("poll", form="create", guild="1000", question="F" * 300,
                         options="\n".join(f"{i:02d} " + "o" * 120 for i in range(25)), channel=str(allg.id), anonymous="on")
    check("grenz: poll 25 Optionen à 100 Zeichen", ops(n, "send", allg.id), loc)
    polls = await pc.config.guild(g).polls()
    big = [p for p in polls.values() if len(p["options"]) == 25]
    if big:
        bp = big[0]
        async with pc.config.guild(g).polls() as ps:
            for uid in range(300):
                ps[bp["id"]]["votes"][str(10_000 + uid)] = {"name": "Nutzer" + "n" * 30, "choices": [uid % 25]}
        n = len(L.LOG)
        await post("poll", form="action", guild="1000", poll_id=bp["id"], action="close")
        check("grenz: poll 25 Optionen + 300 Stimmen -> Nachricht editierbar", ops(n, "edit", allg.id), str(ops(n)))
    reasons = "\n".join(f"Grund {i} " + "g" * 90 + " | 🎫 | " + "d" * 150 for i in range(30))
    for mode in ("button", "dropdown"):
        n = len(L.LOG)
        st, loc = await post("tickets", form="panel_create", guild="1000", channel_id=str(support.id), title="T" * 300,
                             description="D" * 5000, mode=mode, reasons=reasons, questions="\n".join(f"Frage {i} " + "q" * 60 for i in range(8)))
        check(f"grenz: tickets 30 lange Gründe ({mode})", ops(n, "send", support.id), loc)
    # organigram: großes Organigramm
    st, loc = await post("organigram", form="chart_new", guild="1000", name="Groß", title="G" * 300, pattern="liste",
                         mode="embed", accent="#ff0000", show_vacant="on")
    cid2 = re.search(r"chart=([0-9a-f]+)", loc).group(1)
    async with og.config.guild(g).charts() as charts:
        nodes = charts[cid2]["nodes"]
        for i in range(60):
            nodes[f"n{i}"] = {"label": f"Position {i} " + "p" * 200, "parent": f"n{i // 3}" if i else None, "role_id": None,
                              "manual_names": [f"Person {j} " + "x" * 60 for j in range(12)], "emoji": "⭐", "color": "", "order": i}
    for mode in ("embed", "text"):
        n = len(L.LOG)
        st, loc = await post("organigram", form="post", guild="1000", chart=cid2, channel=str(logs_ch.id), mode=mode)
        check(f"grenz: organigram 60 Positionen ({mode})", "Gepostet" in loc, loc)
    t0 = time.time()
    st, loc = await post("organigram", form="post", guild="1000", chart=cid2, channel=str(logs_ch.id), mode="bild")
    check("grenz: organigram zu groß fürs Bild -> klare Meldung statt Speicherexplosion",
          "zu groß" in loc and is_bad(loc) and time.time() - t0 < 30, loc)
    r = await client.get(f"/cogs/organigram?guild=1000&preview={cid2}", headers=OWNER)
    body = await r.read()
    check("grenz: organigram Vorschau zu groß -> Hinweisbild", r.status == 200 and body[:4] == b"\x89PNG", str(r.status))
    # raidhelper: volles Roster
    ev2 = await rh.create_event(g, game="wow_retail", title="Voll", description="B" * 3000, leader_id=1, channel_id=allg.id, start_ts=now + 7200)
    async with rh.config.guild(g).events() as evs:
        su = evs[ev2["id"]]["signups"]
        for i in range(40):
            su[str(20_000 + i)] = {"name": "N" * 32 + str(i), "class": "krieger", "spec": "furor", "role": "mdps",
                                   "status": ["signed", "late", "tentative", "absent", "bench"][i % 5], "at": now}
    n = len(L.LOG)
    await rh.refresh_event_message(g, (await rh.config.guild(g).events())[ev2["id"]])
    check("grenz: raidhelper 40 Anmeldungen + lange Beschreibung -> editierbar", ops(n, "edit", allg.id))
    # sticky: Embed mit Bild-URL + Farbe kaputt
    st, loc = await post("sticky", form="save", guild="1000", channel=str(allg.id), mode="embed", text="x",
                         embed_title="T" * 300, embed_color="grün", embed_image="https://example.com/a.png")
    stk = (await bot._cogs["Sticky"].config.guild(g).stickies()).get(str(allg.id))
    check("grenz: sticky Embed mit ungültiger Farbe/langem Titel", is_bad(loc) or (stk and stk.get("message_id")), loc)

    await client.close()
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} OK")
    if bad:
        print("FEHLGESCHLAGEN:")
        for b in bad:
            print("  -", b[0], "|", b[2][:300])
    return not bad


async def _append(lst, m):
    lst.append(m)

sys.exit(0 if asyncio.run(main()) else 1)
