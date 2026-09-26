"""levels: Kurve, XP/Cooldown/Multiplikator, Voice-XP-Regeln, Level-Up-Meldung, Belohnungen (Hierarchie,
Selbst-Hochstufung), Rangkarte, Rangliste, Befehle, Team-Dashboard, Mitgliederseite /me/level, Datenlöschung."""
import asyncio
import io
import logging
import random
import re
from urllib.parse import unquote_plus

import lv_harness as LV
from aiohttp.test_utils import TestClient, TestServer
import discord
from PIL import Image

L = LV.L
H = LV.H
NR = {"allow_redirects": False}
OWNER = {"X-Test-User": "1"}
LENA = {"X-Test-User": "11"}
TOM = {"X-Test-User": "12"}
KAI = {"X-Test-User": "13"}
BEN = {"X-Test-User": "21"}


def csrf(html):
    return re.search(r"name='csrf_token' value='([^']+)'", html).group(1)


def loc(r):
    return unquote_plus(r.headers.get("Location", ""))


class FakeThread(discord.Thread):
    @classmethod
    def make(cls, tid, parent):
        o = object.__new__(cls)
        o.id = tid; o.parent_id = parent.id; o.guild = parent.guild
        return o


class Ctx:
    def __init__(self, guild, author, channel):
        self.guild = guild; self.author = author; self.channel = channel; self.clean_prefix = "!"
        self.sent = []

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))
        return await self.channel.send(content, **{k: v for k, v in kw.items() if k in ("embed", "allowed_mentions", "file")})

    def typing(self):
        class T:
            async def __aenter__(s): pass
            async def __aexit__(s, *a): pass
        return T()


async def main():
    wc, bot, app, cog = await LV.make_app()
    g = bot.guilds[0]
    allg, sup, ann, logs = g.text_channels
    lobby, gaming, afk = g.voice_channels
    owner, lena, tom, kai, mia = (g.get_member(i) for i in (1, 11, 12, 13, 14))
    R = {r.id: r for r in g.roles}
    gconf = cog.config.guild(g)
    now = [1_800_000_000.0]
    cog._clock = lambda: now[0]
    cog._random = lambda lo, hi: 20

    sends = []
    orig_send = L.FakeText.send

    async def spy(self, content=None, **kw):
        sends.append((self.id, content, kw))
        return await orig_send(self, content, **kw)
    L.FakeText.send = spy

    def tick(sec=61):
        now[0] += sec

    # ------------------------------------------------------------ 1) Levelkurve
    from rc.levels.levels import level_from_xp, progress, total_xp_for_level, xp_to_next
    assert [xp_to_next(i) for i in range(4)] == [100, 155, 220, 295]
    assert [total_xp_for_level(i) for i in range(6)] == [0, 100, 255, 475, 770, 1150]
    assert level_from_xp(99) == 0 and level_from_xp(100) == 1 and level_from_xp(254) == 1 and level_from_xp(255) == 2
    assert progress(300) == (2, 45, 220) and level_from_xp(-5) == 0
    print("Levelkurve 5·L²+50·L+100 OK")

    # ------------------------------------------------------------ 2) XP, Cooldown, Regeln, Puffer
    loads = []
    orig_all = cog.config.all_members

    async def counting_all(guild=None):
        loads.append(getattr(guild, "id", None))
        return await orig_all(guild)
    cog.config.all_members = counting_all
    await gconf.announce_mode.set("off")
    assert await cog.handle_message(LV.msg(g, lena, allg)) == 20
    assert await cog.handle_message(LV.msg(g, lena, allg)) == 0, "Cooldown"
    tick(59)
    assert await cog.handle_message(LV.msg(g, lena, sup)) == 0
    tick(2)
    assert await cog.handle_message(LV.msg(g, lena, sup)) == 20
    assert (await cog.member_record(g, lena.id))["xp"] == 40
    assert await cog.handle_message(LV.msg(g, g.me, allg)) == 0, "Bot"
    assert await cog.handle_message(LV.msg(g, mia, allg, webhook=True)) == 0, "Webhook"
    assert await cog.handle_message(LV.msg(None, mia, allg)) == 0, "DM"
    assert loads == [g.id], f"all_members genau einmal laden: {loads}"
    cog.config.all_members = orig_all
    # Standardbereich 15–25 (echter Zufall)
    cog._random = random.randint
    got = await cog.handle_message(LV.msg(g, tom, allg))
    assert 15 <= got <= 25, got
    cog._random = lambda lo, hi: 20
    # Multiplikator (höchster Faktor gilt)
    await gconf.multipliers.set({"1104": 1.5, "1101": 3})
    assert await cog.handle_message(LV.msg(g, kai, allg)) == 30, "VIP ×1,5"
    assert await cog.handle_message(LV.msg(g, mia, allg)) == 60, "Support ×3"
    mia.roles.append(R[1104])
    tick()
    assert await cog.handle_message(LV.msg(g, mia, allg)) == 60, "höchster Faktor, nicht Produkt"
    mia.roles.remove(R[1104])
    await gconf.multipliers.set({})
    # Ausschlüsse: Kanal (auch Threads darin), Rolle, System aus
    await gconf.excluded_channels.set([ann.id]); await gconf.excluded_roles.set([1102])
    tick()
    assert await cog.handle_message(LV.msg(g, lena, ann)) == 0
    assert await cog.handle_message(LV.msg(g, lena, FakeThread.make(777, ann))) == 0
    assert await cog.handle_message(LV.msg(g, tom, allg)) == 0, "ausgeschlossene Rolle"
    assert await cog.handle_message(LV.msg(g, lena, FakeThread.make(778, allg))) == 20
    await gconf.excluded_channels.set([]); await gconf.excluded_roles.set([])
    await gconf.enabled.set(False)
    tick()
    assert await cog.handle_message(LV.msg(g, lena, allg)) == 0
    await gconf.enabled.set(True)
    # Puffer: vor dem Flush nichts in der Config, danach genau die Werte
    assert await cog.config.member(lena).xp() == 0
    n = await cog.flush()
    assert n >= 4 and await cog.config.member(lena).xp() == 60 and await cog.config.member(lena).level() == 0
    assert await cog.config.member(lena).last_msg_ts() > 0
    assert await cog.flush() == 0
    print("XP pro Nachricht, Cooldown, Bots/Webhooks/DMs, Multiplikator, Ausschlüsse, Puffer (1x laden, Flush) OK")

    # ------------------------------------------------------------ 3) Voice-XP
    await gconf.voice_enabled.set(True); await gconf.voice_xp.set(7)
    xp = {m.id: (await cog.member_record(g, m.id))["xp"] for m in (kai, mia, lena, tom)}

    async def gained():
        cur = {m.id: (await cog.member_record(g, m.id))["xp"] for m in (kai, mia, lena, tom)}
        diff = {k: cur[k] - xp[k] for k in cur if cur[k] != xp[k]}
        xp.update(cur)
        return diff
    LV.set_voice(kai, lobby)
    assert await cog.voice_tick() == 0 and await gained() == {}, "allein"
    lobby.members.append(g.me)
    assert await cog.voice_tick() == 0, "nur mit Bot = allein"
    lobby.members.remove(g.me)
    LV.set_voice(mia, lobby)
    assert await cog.voice_tick() == 2 and await gained() == {13: 7, 14: 7}
    LV.set_voice(mia, lobby, self_mute=True)
    await cog.voice_tick()
    assert await gained() == {13: 7}, "stumm -> keine XP (Kai ist trotzdem nicht allein)"
    LV.set_voice(mia, lobby, deaf=True)
    await cog.voice_tick()
    assert await gained() == {13: 7}
    LV.set_voice(kai, afk); LV.set_voice(mia, afk)
    assert await cog.voice_tick() == 0, "AFK-Kanal"
    LV.set_voice(kai, gaming); LV.set_voice(mia, gaming); LV.set_voice(lena, gaming)
    await gconf.excluded_roles.set([1103])      # Raidleitung -> Mia
    await gconf.multipliers.set({"1104": 2})
    await cog.voice_tick()
    assert await gained() == {13: 14, 11: 7}, "Rolle ausgeschlossen + Multiplikator"
    await gconf.excluded_roles.set([]); await gconf.multipliers.set({})
    await gconf.excluded_channels.set([gaming.id])
    assert await cog.voice_tick() == 0
    await gconf.excluded_channels.set([])
    await gconf.voice_enabled.set(False)
    assert await cog.voice_tick() == 0
    for m in (kai, mia, lena):
        LV.set_voice(m, None)
    print("Voice-XP (allein, Bots, stumm/taub, AFK, ausgeschlossen, Multiplikator, aus) OK")

    # ------------------------------------------------------------ 4) Level-Up-Meldung
    await cog.set_xp(kai, 0, announce=False)
    await gconf.announce_mode.set("same")
    sends.clear()
    tick()
    cog._random = lambda lo, hi: 100
    await cog.handle_message(LV.msg(g, kai, sup))
    assert (await cog.member_record(g, kai.id))["level"] == 1
    cid, content, kw = sends[-1]
    assert cid == sup.id and content == "🎉 <@13> hat **Level 1** erreicht!", content
    am = kw["allowed_mentions"]
    assert am.everyone is False and am.roles is False and [u.id for u in am.users] == [13]
    await gconf.announce_text.set("{user} {name} ist jetzt {level} auf {server} {x} {0} @everyone")
    kai.display_name = "K*a*i"
    await gconf.announce_mode.set("channel"); await gconf.announce_channel.set(logs.id)
    tick(); cog._random = lambda lo, hi: 155
    await cog.handle_message(LV.msg(g, kai, sup))
    cid, content, kw = sends[-1]
    assert cid == logs.id and content == "<@13> K\\*a\\*i ist jetzt 2 auf Matters Community {x} {0} @everyone", content
    assert kw["allowed_mentions"].everyone is False
    kai.display_name = "Kai"
    await gconf.announce_mode.set("dm"); await gconf.announce_text.set("")
    tick(); cog._random = lambda lo, hi: 220
    await cog.handle_message(LV.msg(g, kai, sup))
    assert LV.DMS[-1] == (13, "🎉 <@13> hat **Level 3** erreicht!"), LV.DMS[-1]
    kai.dm_closed = True
    assert await cog.announce(kai, 4) is False
    kai.dm_closed = False
    await gconf.announce_mode.set("off")
    n = len(sends)
    tick(); cog._random = lambda lo, hi: 295
    await cog.handle_message(LV.msg(g, kai, sup))
    assert len(sends) == n and (await cog.member_record(g, kai.id))["level"] == 4
    # fester Kanal ohne Senderecht -> kein Absturz; Voice-Level-Up im Modus „same“ -> keine Meldung
    await gconf.announce_mode.set("channel"); logs.forbid = {"send"}
    assert await cog.announce(kai, 5) is False
    logs.forbid = set()
    await gconf.announce_mode.set("same")
    assert await cog.announce(kai, 5, None) is False
    # Englisch
    await gconf.language.set("en"); await gconf.announce_mode.set("same")
    assert await cog.announce(kai, 9, allg) is True and sends[-1][1] == "🎉 <@13> reached **level 9**!"
    await gconf.language.set("de")
    cog._random = lambda lo, hi: 20
    print("Level-Up-Meldung (selber/fester Kanal, DM, aus, Platzhalter, kein Massen-Ping, fehlende Rechte, EN) OK")

    # ------------------------------------------------------------ 5) Belohnungen
    await gconf.announce_mode.set("off")
    await gconf.rewards.set({"5": 1301, "10": 1302, "3": 1305})
    LV.ROLE_LOG.clear()
    await cog.set_xp(mia, total_xp_for_level(5))
    held = {r.id for r in mia.roles}
    assert 1301 in held and 1305 not in held, "über Bot-Rolle wird nicht vergeben"
    await cog.set_xp(mia, total_xp_for_level(10))
    held = {r.id for r in mia.roles}
    assert {1301, 1302} <= held, "stapeln"
    await gconf.stack_rewards.set(False)
    await cog.set_xp(mia, total_xp_for_level(11))     # nächster Level-Wechsel gleicht ab
    held = {r.id for r in mia.roles}
    assert 1302 in held and 1301 not in held, "nur höchste"
    await cog.set_xp(mia, total_xp_for_level(4), announce=False)
    held = {r.id for r in mia.roles}
    assert 1301 not in held and 1302 not in held, "XP abgezogen -> Belohnungen weg"
    await gconf.stack_rewards.set(True)
    mia.fail_roles = True
    logging.getLogger("red.red-cogs.levels").disabled = True
    await cog.set_xp(mia, total_xp_for_level(6))       # Forbidden -> kein Absturz
    logging.getLogger("red.red-cogs.levels").disabled = False
    mia.fail_roles = False
    added, removed = await cog.sync_all(g)
    assert 1301 in {r.id for r in mia.roles} and added >= 1
    # Befehl: Rechte-/Hierarchieprüfung
    ctx_l = Ctx(g, lena, logs)
    await cog.ls_reward.callback(cog, ctx_l, 7, R[1303])
    assert "nicht als Belohnung eintragen" in ctx_l.sent[-1][0], "über Lenas höchster Rolle"
    await cog.ls_reward.callback(cog, ctx_l, 7, R[1304])
    assert "nicht als Belohnung eintragen" in ctx_l.sent[-1][0], "Moderationsrechte"
    await cog.ls_reward.callback(cog, ctx_l, 7, R[1305])
    assert "meiner höchsten Rolle" in ctx_l.sent[-1][0]
    await cog.ls_reward.callback(cog, ctx_l, 7, g.default_role)
    assert "kann nicht vergeben" in ctx_l.sent[-1][0]
    await cog.ls_reward.callback(cog, ctx_l, 7, R[1306])
    assert (await gconf.rewards())["7"] == 1306
    ctx_o = Ctx(g, owner, logs)
    await cog.ls_reward.callback(cog, ctx_o, 20, R[1303])
    assert (await gconf.rewards())["20"] == 1303, "Owner darf höhere Rollen"
    await cog.ls_reward.callback(cog, ctx_o, 20, None)
    assert "20" not in await gconf.rewards() and "entfernt" in ctx_o.sent[-1][0]
    await cog.ls_reward.callback(cog, ctx_o, 0, R[1306])
    assert "zwischen 1 und" in ctx_o.sent[-1][0]
    print("Belohnungen (stapeln/nur höchste, Abzug, Bot-Hierarchie, Forbidden, Abgleich, Befehl mit Rechteprüfung) OK")

    # ------------------------------------------------------------ 6) Rangkarte
    from rc.levels import card as cardmod
    assert cardmod.fonts_available()
    png = await cog.render_card(kai)
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG" and im.size == (934, 282), im.size
    raw = cardmod.render_rank_card(name="🔥" * 3 + "x" * 200, level=999, rank=12345, xp_into=5, xp_needed=0,
                                   total_xp=10 ** 9, server="S" * 300, avatar=b"kaputt")
    assert Image.open(io.BytesIO(raw)).size == (934, 282)

    class SlowAsset:
        key = "slow"; url = "https://x"
        async def read(self): await asyncio.sleep(30)
    import rc.levels.levels as lvmod
    lvmod.AVATAR_TIMEOUT = 0.2
    old_av = tom.display_avatar
    tom.display_avatar = SlowAsset()
    assert await cog.avatar_bytes(tom) is None
    png = await cog.render_card(tom)
    assert png[:4] == b"\x89PNG"
    tom.display_avatar = old_av
    ctx = Ctx(g, kai, allg)
    await cog.rank.callback(cog, ctx, None)
    f = ctx.sent[-1][1]["file"]
    assert f.filename == "rang.png"
    orig_perm = L._SendMixin.permissions_for

    def no_attach(self, obj):
        p = orig_perm(self, obj); p.attach_files = False; return p
    L.FakeText.permissions_for = no_attach
    await cog.rank.callback(cog, ctx, mia)
    emb = ctx.sent[-1][1]["embed"]
    assert "Mia" in emb.title and "Rang #" in emb.description
    L.validate_embed(emb)
    L.FakeText.permissions_for = orig_perm
    await cog.rank.callback(cog, ctx, g.me)
    assert "Bots" in ctx.sent[-1][0]
    print("Rangkarte (934×282, Avatar-Timeout, kaputte Daten, Emojis/Überlänge, Befehl + Embed-Ersatz) OK")

    # ------------------------------------------------------------ 7) Rangliste
    rows = await cog.ranking(g)
    xs = [r["xp"] for _, r in rows]
    assert xs == sorted(xs, reverse=True) and rows[0][0] == mia.id
    assert await cog.ranking(g) is rows, "Cache ohne Änderung"
    gone = H.Member(g, 4444, "Weg", [])
    g.members.append(gone)
    await cog.set_xp(gone, 10 ** 6, announce=False)
    assert (await cog.ranking(g))[0][0] == 4444
    g.members.remove(gone)
    await cog.set_xp(gone, 10 ** 6, announce=False)   # Version erhöhen
    assert all(uid != 4444 for uid, _ in await cog.ranking(g)), "Ausgetretene nicht in der Rangliste"
    rank, total = await cog.rank_of(g, kai.id)
    assert rank and total == len(await cog.ranking(g))
    await cog.leaderboard.callback(cog, ctx, 1)
    emb = ctx.sent[-1][1]["embed"]
    assert emb.description.startswith("**#1** Mia — Level") and "Dein Rang: #" in emb.footer.text
    L.validate_embed(emb)
    await cog.leaderboard.callback(cog, ctx, 9)
    assert "gibt es nicht" in ctx.sent[-1][0]
    assert "top" in cog.leaderboard.aliases
    print("Rangliste (Sortierung, Cache, Ausgetretene, Befehl leaderboard/top) OK")

    # ------------------------------------------------------------ 8) Befehle levelset
    ls = Ctx(g, owner, logs)
    await cog.ls_xp.callback(cog, ls, "give", tom, 500)
    assert (await cog.member_record(g, tom.id))["xp"] >= 500 and "XP" in ls.sent[-1][0]
    await cog.ls_xp.callback(cog, ls, "set", tom, 300)
    assert (await cog.member_record(g, tom.id)) ["xp"] == 300 and (await cog.member_record(g, tom.id))["level"] == 2
    await cog.ls_xp.callback(cog, ls, "take", tom, 1000)
    assert (await cog.member_record(g, tom.id))["xp"] == 0
    await cog.ls_xp.callback(cog, ls, "give", tom, None)
    assert "Menge" in ls.sent[-1][0]
    await cog.ls_xp.callback(cog, ls, "give", tom, 0)
    assert "Menge" in ls.sent[-1][0]
    await cog.ls_xp.callback(cog, ls, "reset", mia, None)
    assert (await cog.member_record(g, mia.id))["xp"] == 0 and 1301 not in {r.id for r in mia.roles}
    await cog.ls_xp.callback(cog, ls, "give", g.me, 5)
    assert "Bots" in ls.sent[-1][0]
    await cog.ls_toggle.callback(cog, ls, None); assert await gconf.enabled() is False
    await cog.ls_toggle.callback(cog, ls, True); assert await gconf.enabled() is True
    await cog.ls_xprange.callback(cog, ls, 30, 10); assert "Ungültiger" in ls.sent[-1][0]
    await cog.ls_xprange.callback(cog, ls, 10, 30); assert (await gconf.xp_min(), await gconf.xp_max()) == (10, 30)
    await cog.ls_cooldown.callback(cog, ls, -1); assert "zwischen" in ls.sent[-1][0]
    await cog.ls_cooldown.callback(cog, ls, 30); assert await gconf.cooldown() == 30
    await cog.ls_voice.callback(cog, ls, True, 500); assert "zwischen" in ls.sent[-1][0]
    await cog.ls_voice.callback(cog, ls, True, 9); assert await gconf.voice_enabled() and await gconf.voice_xp() == 9
    await cog.ls_excludechannel.callback(cog, ls, ann); assert ann.id in await gconf.excluded_channels()
    await cog.ls_excludechannel.callback(cog, ls, ann); assert ann.id not in await gconf.excluded_channels()
    await cog.ls_excluderole.callback(cog, ls, R[1104]); assert 1104 in await gconf.excluded_roles()
    await cog.ls_excluderole.callback(cog, ls, R[1104]); assert 1104 not in await gconf.excluded_roles()
    await cog.ls_multiplier.callback(cog, ls, R[1104], 9.0); assert "zwischen" in ls.sent[-1][0]
    await cog.ls_multiplier.callback(cog, ls, R[1104], 2.5); assert (await gconf.multipliers())["1104"] == 2.5
    await cog.ls_multiplier.callback(cog, ls, R[1104], 1.0); assert "1104" not in await gconf.multipliers()
    await cog.ls_stack.callback(cog, ls, False); assert await gconf.stack_rewards() is False
    await cog.ls_stack.callback(cog, ls, True)
    await cog.ls_announce.callback(cog, ls, "channel", None); assert "Kanal angeben" in ls.sent[-1][0]
    await cog.ls_announce.callback(cog, ls, "channel", ann)
    assert await gconf.announce_mode() == "channel" and await gconf.announce_channel() == ann.id
    await cog.ls_message.callback(cog, ls, text="x" * 1001); assert "zu lang" in ls.sent[-1][0]
    await cog.ls_message.callback(cog, ls, text="GG {user}!"); assert await gconf.announce_text() == "GG {user}!"
    await cog.ls_language.callback(cog, ls, "fr"); assert "Unbekannte Sprache" in ls.sent[-1][0]
    await cog.ls_settings.callback(cog, ls)
    L.validate_embed(ls.sent[-1][1]["embed"])
    await cog.ls_syncrewards.callback(cog, ls)
    assert "abgeglichen" in ls.sent[-1][0]
    for c in ls.sent + ctx_l.sent:
        am = c[1].get("allowed_mentions")
        assert am is None or (am.everyone is False and am.roles is False and am.users is False), am
    await gconf.announce_mode.set("off"); await gconf.cooldown.set(60); await gconf.voice_enabled.set(False)
    await gconf.xp_min.set(15); await gconf.xp_max.set(25); await gconf.announce_text.set("")
    print("Befehle levelset (xp give/take/set/reset, toggle, xprange, cooldown, voice, exclude*, multiplier, "
          "stack, announce, message, language, settings, syncrewards) OK")

    # ------------------------------------------------------------ 9) Team-Dashboard
    await LV.seed(cog, bot)
    client = TestClient(TestServer(app)); await client.start_server()
    r = await client.get("/cogs/levels?guild=1000", headers=OWNER); t = await r.text()
    assert r.status == 200, r.status
    for s in ("data-title='Rangliste'", "data-title='Belohnungen'", "data-title='Einstellungen'",
              "data-title='XP anpassen'", "Mitglieder mit XP", "rankbar", "Im Mitglieder-Bereich anzeigen",
              "5·L² + 50·L + 100", "data-wc-filter='#lv-board'"):
        assert s in t, s
    assert "Noah &lt;b&gt;fett&lt;/b&gt;" in t and "<b>fett</b>" not in t
    assert "data-confirm='XP dieses Mitglieds wirklich ändern?" in t
    tok = csrf(t)
    base = {"csrf_token": tok, "form": "settings", "guild": "1000", "xp_min": "10", "xp_max": "20", "cooldown": "45",
            "voice_xp": "4", "language": "de", "card_color": "#ff8800", "announce_mode": "channel",
            "announce_channel": str(ann.id), "announce_text": "Hi {user}", "enabled": "on", "member_page": "on",
            "voice_enabled": "on", "excluded_channels": [str(logs.id), str(gaming.id)], "excluded_roles": ["1104"]}
    r = await client.post("/cogs/levels", headers=OWNER, data=base, **NR)
    assert "ok=" in r.headers["Location"], loc(r)
    c = await gconf.all()
    assert (c["xp_min"], c["xp_max"], c["cooldown"], c["voice_xp"], c["card_color"]) == (10, 20, 45, 4, "#ff8800")
    assert c["excluded_channels"] == [logs.id, gaming.id] and c["excluded_roles"] == [1104] and c["voice_enabled"]
    assert c["announce_mode"] == "channel" and c["announce_channel"] == ann.id and c["announce_text"] == "Hi {user}"
    for bad, msg in (({"xp_min": "30"}, "min. ≤ max."), ({"cooldown": "99999"}, "Cooldown"), ({"voice_xp": "0"}, "Voice"),
                     ({"language": "xx"}, "Sprache"), ({"card_color": "rot"}, "Kartenfarbe"),
                     ({"excluded_channels": "123"}, "Kanal"), ({"excluded_roles": "999"}, "Rolle"),
                     ({"announce_mode": "laut"}, "Modus"), ({"announce_channel": ""}, "fester Kanal"),
                     ({"announce_text": "x" * 1001}, "zu lang")):
        r = await client.post("/cogs/levels", headers=OWNER, data={**base, **bad}, **NR)
        assert "err=" in r.headers["Location"] and msg in loc(r), (bad, loc(r))
    assert (await gconf.xp_min()) == 10
    d = {k: v for k, v in base.items() if k not in ("enabled", "voice_enabled", "member_page")}
    r = await client.post("/cogs/levels", headers=OWNER, data=d, **NR)
    assert not await gconf.enabled() and not await gconf.voice_enabled() and not await gconf.member_page()
    r = await client.post("/cogs/levels", headers=OWNER, data=base, **NR)
    # Belohnungen: Selbst-Hochstufung / Bot-Hierarchie / Rechte
    r = await client.get("/cogs/levels?guild=1000", headers=LENA); lt = await r.text(); ltok = csrf(lt)
    rw = {"form": "reward_add", "guild": "1000", "level": "15"}
    for rid, msg in (("1303", "Selbst-Hochstufung"), ("1304", "Selbst-Hochstufung")):
        r = await client.post("/cogs/levels", headers=LENA, data={**rw, "csrf_token": ltok, "role": rid}, **NR)
        assert msg in loc(r) and "15" not in await gconf.rewards(), loc(r)
    r = await client.post("/cogs/levels", headers=LENA, data={**rw, "csrf_token": ltok, "role": "1306"}, **NR)
    assert "ok=" in r.headers["Location"] and (await gconf.rewards())["15"] == 1306
    r = await client.post("/cogs/levels", headers=OWNER, data={**rw, "csrf_token": tok, "role": "1305"}, **NR)
    assert "Bot-Rolle" in loc(r), loc(r)
    r = await client.post("/cogs/levels", headers=OWNER, data={**rw, "csrf_token": tok, "role": "1303"}, **NR)
    assert (await gconf.rewards())["15"] == 1303, "Owner darf"
    for bad in ({"level": "0", "role": "1306"}, {"level": "x", "role": "1306"}, {"level": "3", "role": "1000"},
                {"level": "3", "role": "42"}):
        r = await client.post("/cogs/levels", headers=OWNER, data={**rw, "csrf_token": tok, **bad}, **NR)
        assert "err=" in r.headers["Location"], bad
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "reward_del", "guild": "1000",
                                                              "level": "15"}, **NR)
    assert "ok=" in r.headers["Location"] and "15" not in await gconf.rewards()
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "reward_del", "guild": "1000",
                                                              "level": "15"}, **NR)
    assert "nicht gefunden" in loc(r)
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "stack", "guild": "1000"}, **NR)
    assert await gconf.stack_rewards() is False
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "stack", "guild": "1000",
                                                              "stack_rewards": "on"}, **NR)
    assert await gconf.stack_rewards() is True
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "sync", "guild": "1000"}, **NR)
    assert "Abgeglichen" in loc(r)
    # Multiplikatoren
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "mult_add", "guild": "1000",
                                                              "role": "1101", "factor": "2,5"}, **NR)
    assert (await gconf.multipliers())["1101"] == 2.5, loc(r)
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "mult_add", "guild": "1000",
                                                              "role": "1101", "factor": "50"}, **NR)
    assert "Faktor" in loc(r)
    r = await client.post("/cogs/levels", headers=OWNER, data={"csrf_token": tok, "form": "mult_del", "guild": "1000",
                                                              "role": "1101"}, **NR)
    assert "1101" not in await gconf.multipliers()
    # XP anpassen
    xpd = {"csrf_token": tok, "form": "xp", "guild": "1000"}
    await cog.set_xp(tom, 0, announce=False)
    r = await client.post("/cogs/levels", headers=OWNER, data={**xpd, "member": "tom", "action": "give", "amount": "500"}, **NR)
    assert "Tom: 500 XP (Level 3)" in loc(r), loc(r)
    r = await client.post("/cogs/levels", headers=OWNER, data={**xpd, "member": "<@12>", "action": "take", "amount": "100"}, **NR)
    assert (await cog.member_record(g, tom.id))["xp"] == 400
    r = await client.post("/cogs/levels", headers=OWNER, data={**xpd, "member": "12", "action": "set", "amount": "0"}, **NR)
    assert (await cog.member_record(g, tom.id))["xp"] == 0
    r = await client.post("/cogs/levels", headers=OWNER, data={**xpd, "member": "12", "action": "reset"}, **NR)
    assert "ok=" in r.headers["Location"]
    for bad, msg in (({"member": "Niemand", "action": "give", "amount": "5"}, "nicht gefunden"),
                     ({"member": "", "action": "give", "amount": "5"}, "angeben"),
                     ({"member": "12", "action": "give", "amount": "0"}, "Menge"),
                     ({"member": "12", "action": "hack", "amount": "5"}, "Unbekannte")):
        r = await client.post("/cogs/levels", headers=OWNER, data={**xpd, **bad}, **NR)
        assert msg in loc(r), (bad, loc(r))
    g.members.append(g.me)
    r = await client.post("/cogs/levels", headers=OWNER, data={**xpd, "member": "999", "action": "give", "amount": "5"}, **NR)
    assert "Bots" in loc(r), loc(r)
    g.members.remove(g.me)
    dup = H.Member(g, 4555, "Tom", [])
    g.members.append(dup)
    r = await client.post("/cogs/levels", headers=OWNER, data={**xpd, "member": "Tom", "action": "give", "amount": "5"}, **NR)
    assert "nicht eindeutig" in loc(r)
    g.members.remove(dup)
    # Tom (Ansehen): Seite ja, Speichern nein; Lena nicht auf Server 2000; Kai kein Zugriff
    r = await client.get("/cogs/levels?guild=1000", headers=TOM); tt = await r.text()
    assert r.status == 200 and "Rangliste" in tt
    r = await client.post("/cogs/levels", headers=TOM, data={**xpd, "csrf_token": csrf(tt), "member": "12",
                                                            "action": "give", "amount": "999"}, **NR)
    assert r.status in (302, 403) and (await cog.member_record(g, tom.id))["xp"] == 0
    r = await client.post("/cogs/levels", headers=LENA, data={**xpd, "csrf_token": ltok, "guild": "2000", "member": "11",
                                                             "action": "give", "amount": "5"}, **NR)
    assert r.status in (302, 403) and (await cog.member_record(bot.guilds[1], 11))["xp"] == 0
    r = await client.get("/cogs/levels?guild=1000", headers=KAI, **NR)
    assert r.status in (302, 403)
    print("Team-Dashboard (Reiter, Einstellungen + Validierung, Belohnungen mit can_grant_role/Bot-Hierarchie, "
          "Multiplikatoren, XP anpassen, Rechte) OK")

    # ------------------------------------------------------------ 10) Mitgliederseite /me/level
    await gconf.rewards.set({"5": 1301, "10": 1302, "30": 1303})
    await cog.set_xp(kai, total_xp_for_level(7) + 10, announce=False)
    r = await client.get("/me?guild=1000", headers=KAI); t = await r.text()
    assert "/me/level" in t and "Mein Level" in t
    r = await client.get("/me/level?guild=1000", headers=KAI); t = await r.text()
    assert r.status == 200
    rank, total = await cog.rank_of(g, kai.id)
    for s in (f"#{rank}", f"von {total}", "Level 7 → 8", "class='bar'", "/me/level?guild=1000&amp;card=1",
              "@Level 10", "Top 10", "Noah &lt;b&gt;fett&lt;/b&gt;"):
        assert s in t, s
    assert "XP anpassen" not in t and "Belohnung speichern" not in t
    top_names = re.findall(r"<td>(?:<b>)?([^<]+)", t.split("Top 10")[1])
    assert len([n for n in top_names if not n.startswith("#")]) <= 10
    r = await client.get("/me/level?guild=1000&card=1", headers=KAI)
    assert r.status == 200 and r.headers["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(await r.read())).size == (934, 282)
    r = await client.get("/me/profil?guild=1000", headers=KAI); ktok = csrf(await r.text())   # Demo-Seite mit Formular
    r = await client.post("/me/level", headers=KAI, data={"csrf_token": ktok, "guild": "1000"}, **NR)
    assert "Unbekannte" in loc(r)
    r = await client.get("/me/level?guild=2000", headers=BEN, **NR)
    assert r.status in (302, 403) or "kein" in (await r.text()).lower()
    # Schalter aus -> Kachel weg, Seite + Bild gesperrt
    await gconf.member_page.set(False)
    r = await client.get("/me?guild=1000", headers=KAI); t = await r.text()
    assert "/me/level" not in t
    r = await client.get("/me/level?guild=1000", headers=KAI); t = await r.text()
    assert "ausgeschaltet" in t and "Top 10" not in t
    r = await client.get("/me/level?guild=1000&card=1", headers=KAI)
    assert r.status == 404
    await gconf.member_page.set(True)
    await gconf.enabled.set(False)
    r = await client.get("/me/level?guild=1000", headers=KAI)
    assert "ausgeschaltet" in await r.text()
    await gconf.enabled.set(True)
    print("Mitgliederseite /me/level (Rang, Fortschritt, Rangkarte, nächste Belohnung, Top 10, Schalter) OK")
    await client.close()

    # ------------------------------------------------------------ 11) Datenlöschung + Entladen
    await cog.flush()
    assert await cog.config.member(kai).xp() > 0
    await cog.red_delete_data_for_user(requester="user", user_id=kai.id)
    assert await cog.config.member(kai).xp() == 0 and kai.id not in cog._data[g.id]
    assert all(uid != kai.id for uid, _ in await cog.ranking(g))
    raw = await cog.config.all_members(g)
    assert kai.id not in raw
    await cog.set_xp(lena, 5000, announce=False)
    assert "levels" in wc.pages and "level" in wc.member_pages
    await cog.cog_unload()
    assert "levels" not in wc.pages and "level" not in wc.member_pages
    assert await cog.config.member(lena).xp() == 5000, "cog_unload schreibt den Puffer"
    print("red_delete_data_for_user, cog_unload (Puffer + Seiten) OK")
    print("ALLE LEVELS-TESTS OK")


asyncio.run(main())
