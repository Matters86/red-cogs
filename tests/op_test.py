"""WebCore: Rechte-Stufe „Bedienen“ (operate_forms, zentrale POST-Prüfung, visible_guilds, Helfer, Oberfläche,
JS-Sperre) und Rollen-Vorlagen (Zugriff & Rollen, Befehle, Sicherung)."""
import asyncio
import json
import re
import types
from urllib.parse import unquote_plus

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

import wc_harness as H
from rc.webcore import access as acl
from rc.webcore import backup as bk

nr = {"allow_redirects": False}
OWNER = {"X-Test-User": "1"}
LENA = {"X-Test-User": "11"}   # Support (1101) – auf 2000 RP-Support (2101)
TOM = {"X-Test-User": "12"}    # Moderator (1102)
MIA = {"X-Test-User": "14"}    # Support (1101) + Raidleitung (1103)
KAI = {"X-Test-User": "13"}    # VIP (1104)
TOAST_EDIT = "Dafür brauchst du das Recht Bearbeiten"


def csrf(text):
    return re.search(r"name='csrf_token' value='([^']+)'", text).group(1)


class OpDemo:
    """Demo-Cog mit drei Seiten: Tagesgeschäft als Menge, als Callable und ganz ohne."""
    qualified_name = "OpDemo"

    def __init__(self):
        self.calls = []   # (slug, form-Werte, visible_guilds, wc_operate, Datei-Inhalt)
        self.levels = {}  # slug -> (page_level, can_operate, can_edit) beim letzten GET

    def register(self, wc):
        wc.register_page(self, "opdemo", "Op-Demo", self.page("opdemo"), icon="bi-stars",
                         operate_forms={"act", "repost"})
        wc.register_page(self, "opcall", "Op-Callable", self.page("opcall"), icon="bi-stars",
                         operate_forms=self.classify)
        wc.register_page(self, "opnone", "Op-Ohne", self.page("opnone"), icon="bi-stars")

    @staticmethod
    def classify(data):
        if data.get("x") == "boom":
            raise RuntimeError("kaputt")
        return data.get("form") == "custom" and data.get("x") == "1"

    def page(self, slug):
        async def handler(request):
            wc = request.app["webcore"]
            ui = wc.ui
            if request.method == "POST":
                data = await request.post()          # zweites Lesen: WebCore hat vorab gelesen
                upload = data.get("file")
                content = upload.file.read().decode() if hasattr(upload, "file") else None
                vis = [g.id for g in await wc.visible_guilds(request)]
                self.calls.append((slug, data.getall("form", []) or data.getall("action", []), vis,
                                   request.get("wc_operate"), content))
                gid = str(data.get("guild") or "")
                if not gid.isdigit() or int(gid) not in vis:
                    return {"redirect": f"/cogs/{slug}?guild={gid}&err=Server+nicht+erlaubt"}
                return {"redirect": f"/cogs/{slug}?guild={gid}&ok=Erledigt"}
            gid = request.query.get("guild")
            guild = wc.bot.get_guild(int(gid))
            self.levels[slug] = (await wc.page_level(request, guild), await wc.can_operate(request, guild),
                                 await wc.can_edit(request, guild))
            csrf_ = request.get("webcore_csrf", "")
            h = {"guild": gid}
            content = (
                ui.form(f"/cogs/{slug}", "<button class='btn-accent' id='b-act'>Aktion</button>", csrf=csrf_,
                        hidden={**h, "form": "act"}, id="f-act")
                + ui.form(f"/cogs/{slug}", "<input name='note' id='i-note'><button id='b-set'>Speichern</button>",
                          csrf=csrf_, hidden={**h, "form": "settings"}, id="f-set", savebar=True)
                + ui.form(f"/cogs/{slug}",
                          "<input name='reason' id='i-reason'>"
                          "<button name='action' value='repost' id='b-repost'>Neu posten</button>"
                          "<button name='action' value='delete' id='b-del'>Löschen</button>",
                          csrf=csrf_, hidden=h, id="f-btn")
                + ui.form(f"/cogs/{slug}", "<button id='b-custom'>Custom</button>", csrf=csrf_,
                          hidden={**h, "form": "custom", "x": "1"}, id="f-custom", operate=True)
            )
            return {"title": slug, "content": content}
        return handler


async def post(client, headers, slug, **fields):
    r = await client.post(f"/cogs/{slug}", headers=headers, data=fields, **nr)
    return r.status, unquote_plus(r.headers.get("Location", ""))


async def main():
    wc, bot, app = await H.make_app()
    g1, g2 = bot.guilds
    demo = OpDemo()
    demo.register(wc)
    client = TestClient(TestServer(app))
    await client.start_server()

    # ------------------------------------------------------------ access.py
    assert (acl.NONE, acl.VIEW, acl.OPERATE, acl.EDIT) == (0, 1, 2, 3) == (wc.NONE, wc.VIEW, wc.OPERATE, wc.EDIT)
    for raw, lvl in (("view", 1), ("operate", 2), ("edit", 3), ("none", 0), ("Ansehen", 1), ("bedienen", 2),
                     ("BEARBEITEN", 3), ("keine", 0), ("quatsch", 0), (None, 0), (3, 3), (True, 0), ("2", 0)):
        assert acl.parse_level(raw) == lvl, (raw, acl.parse_level(raw))
    assert acl.is_level_name("bedienen") and acl.is_level_name("operate") and not acl.is_level_name("2")
    assert acl.NAME_BY_LEVEL[acl.OPERATE] == "operate" and acl.LEVEL_LABEL[acl.OPERATE] == "Bedienen"
    assert "bedienen" not in acl.LEVEL_BY_NAME, "Aliase werden nie gespeichert/importiert"
    assert acl.is_operate_post({"act"}, {"form": "act"}) and not acl.is_operate_post({"act"}, {"form": "settings"})
    assert acl.is_operate_post({"act"}, {"action": "act"}) and not acl.is_operate_post((), {"form": "act"})
    assert acl.is_operate_post({"act"}, {"form": "", "action": "act"})
    assert acl.resolve_template("Nur ansehen") == "view" and acl.resolve_template("MOD") == "moderator"
    assert acl.resolve_template("eventleitung") == "eventleitung" and acl.resolve_template("x") is None
    # Bestehende gespeicherte Werte (Namen) behalten ihre Bedeutung
    legacy = {"1000": {"1101": {"a": "view", "b": "edit"}}}
    assert acl.levels_from_roles([1101], acl.guild_role_perms(legacy, 1000), ["a", "b", "c"]) == {"a": 1, "b": 3}
    print("access.py: Stufen 0–3, Namen/Aliase, Klassifizierung, Vorlagen-Namen, alte Werte – OK")

    # ------------------------------------------------------------ Rechte setzen (Owner)
    await wc.config.role_perms.set({
        "1000": {"1101": {"opdemo": "operate", "opcall": "operate", "opnone": "operate", "tickets": "edit"},
                 "1102": {"opdemo": "view", "opcall": "view"},
                 "1103": {"opdemo": "edit", "opnone": "edit"}},
        "2000": {"2101": {"opdemo": "view"}},
    })

    # ------------------------------------------------------------ Oberfläche
    t = await (await client.get("/cogs/opdemo?guild=1000", headers=LENA)).text()
    assert 'data-operate="1"' in t and 'data-operate-forms="act,repost"' in t and 'data-readonly="0"' in t, t[:1500]
    assert "op-banner" in t and "Du kannst Aktionen ausführen, aber keine Einstellungen ändern." in t
    assert "Nur Ansicht." not in t and "wc-operate" in t
    assert "data-wc-operate='1'" in t, "ui.form(operate=True) setzt data-wc-operate"
    assert demo.levels["opdemo"] == (acl.OPERATE, True, False), demo.levels
    nav = re.search(r'href="/cogs/opdemo">(.*?)</a>', t, re.S).group(1)
    assert 'nav-badge op' in nav and "Bedienen" in nav, nav
    nav = re.search(r'href="/cogs/opnone">(.*?)</a>', t, re.S).group(1)
    assert "Ansicht" in nav and "Bedienen" not in nav, "Bedienen ohne Tagesgeschäft = Ansicht"
    nav = re.search(r'href="/cogs/tickets">(.*?)</a>', t, re.S).group(1)
    assert "nav-badge" not in nav
    # Callable: Liste leer, Cog markiert Formulare selbst
    t = await (await client.get("/cogs/opcall?guild=1000", headers=LENA)).text()
    assert 'data-operate="1"' in t and 'data-operate-forms=""' in t and "op-banner" in t
    # Seite ohne operate_forms: wie Nur-Ansicht
    t = await (await client.get("/cogs/opnone?guild=1000", headers=LENA)).text()
    assert 'data-readonly="1"' in t and "data-operate" not in t and "Nur Ansicht." in t and "op-banner" not in t
    assert demo.levels["opnone"] == (acl.OPERATE, True, False)
    # Tom: Ansehen
    t = await (await client.get("/cogs/opdemo?guild=1000", headers=TOM)).text()
    assert 'data-readonly="1"' in t and "data-operate" not in t and "Nur Ansicht." in t
    assert demo.levels["opdemo"] == (acl.VIEW, False, False)
    # Mia: Bearbeiten (höchste Stufe aus Support=operate + Raidleitung=edit)
    t = await (await client.get("/cogs/opdemo?guild=1000", headers=MIA)).text()
    assert 'data-readonly="0"' in t and "data-operate" not in t and "ro-banner" not in t
    assert demo.levels["opdemo"] == (acl.EDIT, True, True)
    t = await (await client.get("/cogs/opdemo?guild=1000", headers=OWNER)).text()
    assert "ro-banner" not in t and demo.levels["opdemo"] == (acl.EDIT, True, True)
    # GET: visible_guilds unverändert (Ansehen) – Lena sieht auf opdemo beide Server
    r = await client.get("/cogs/opdemo?guild=2000", headers=LENA)
    t = await r.text()
    assert r.status == 200 and 'data-readonly="1"' in t and demo.levels["opdemo"] == (acl.VIEW, False, False)
    print("Oberfläche: data-operate/-forms, Bedienen-Banner, Nav-Badge, ohne operate_forms = Ansicht, Helfer – OK")

    # ------------------------------------------------------------ POST-Prüfung
    tok = csrf(await (await client.get("/cogs/opdemo?guild=1000", headers=LENA)).text())
    a0 = len(await wc.config.audit())
    demo.calls.clear()
    st, loc = await post(client, LENA, "opdemo", csrf_token=tok, guild="1000", form="act")
    assert st == 302 and "ok=Erledigt" in loc, loc
    assert demo.calls[-1] == ("opdemo", ["act"], [1000], True, None), demo.calls[-1]
    st, loc = await post(client, LENA, "opdemo", csrf_token=tok, guild="1000", action="repost", reason="x")
    assert "ok=Erledigt" in loc and demo.calls[-1][3] is True
    n = len(demo.calls)
    st, loc = await post(client, LENA, "opdemo", csrf_token=tok, guild="1000", form="settings", note="x")
    assert st == 302 and f"err={TOAST_EDIT}" in loc and "guild=1000" in loc, loc
    assert len(demo.calls) == n, "Handler darf nicht laufen"
    au = (await wc.config.audit())[0]
    assert au["ok"] is False and au["page"] == "opdemo" and au["action"] == "settings" and "Bedienen" in au["result"], au
    st, loc = await post(client, LENA, "opdemo", csrf_token=tok, guild="1000", action="delete")
    assert TOAST_EDIT in loc and len(demo.calls) == n
    # mehrere form-Werte: alle müssen Tagesgeschäft sein
    r = await client.post("/cogs/opdemo", headers=LENA, **nr,
                          data=[("csrf_token", tok), ("guild", "1000"), ("form", "act"), ("form", "settings")])
    assert TOAST_EDIT in unquote_plus(r.headers["Location"]) and len(demo.calls) == n
    # fremder Server (dort nur Ansehen)
    st, loc = await post(client, LENA, "opdemo", csrf_token=tok, guild="2000", form="act")
    assert "Keine Bearbeitungsrechte" in loc and len(demo.calls) == n, loc
    assert "Ansehen" in (await wc.config.audit())[0]["result"]
    # Multipart/Upload: Handler liest die vorab gelesenen Daten inkl. Datei
    fd = FormData()
    for k, v in (("csrf_token", tok), ("guild", "1000"), ("form", "act")):
        fd.add_field(k, v)
    fd.add_field("file", b"hallo-datei", filename="a.txt", content_type="text/plain")
    r = await client.post("/cogs/opdemo", headers=LENA, data=fd, **nr)
    assert "ok=Erledigt" in unquote_plus(r.headers["Location"]) and demo.calls[-1][4] == "hallo-datei", demo.calls[-1]
    # CSRF weiterhin vor allem anderen
    st, _ = await post(client, LENA, "opdemo", csrf_token="falsch", guild="1000", form="act")
    assert st == 400
    print("Bedienen: Tagesgeschäft erlaubt (form/action, Upload), Einstellungen/Löschen/Mischwerte/fremder Server "
          "abgelehnt (Toast + Audit mit Stufe) – OK")

    # Tom (Ansehen): nichts
    tok_t = csrf(await (await client.get("/cogs/opdemo?guild=1000", headers=TOM)).text())
    n = len(demo.calls)
    for f in ("act", "settings"):
        st, loc = await post(client, TOM, "opdemo", csrf_token=tok_t, guild="1000", form=f)
        assert "Keine Bearbeitungsrechte" in loc, loc
    assert len(demo.calls) == n and "Stufe Ansehen" in (await wc.config.audit())[0]["result"]
    # Mia (Bearbeiten): alles; visible_guilds bei POST = EDIT-Server bzw. OPERATE-Server
    tok_m = csrf(await (await client.get("/cogs/opdemo?guild=1000", headers=MIA)).text())
    st, loc = await post(client, MIA, "opdemo", csrf_token=tok_m, guild="1000", form="settings")
    assert "ok=Erledigt" in loc and demo.calls[-1][2:4] == ([1000], False), demo.calls[-1]
    st, loc = await post(client, MIA, "opdemo", csrf_token=tok_m, guild="1000", form="act")
    assert "ok=Erledigt" in loc and demo.calls[-1][2:4] == ([1000], True)
    # Owner: alles, alle Server
    tok_o = csrf(await (await client.get("/cogs/opdemo?guild=1000", headers=OWNER)).text())
    st, loc = await post(client, OWNER, "opdemo", csrf_token=tok_o, guild="2000", form="settings")
    assert "ok=Erledigt" in loc and demo.calls[-1][2] == [1000, 2000]
    # Owner-Level auf 2000 für Lena: Bearbeiten -> dort auch Einstellungen
    rp = await wc.config.role_perms(); rp["2000"]["2101"]["opdemo"] = "edit"; await wc.config.role_perms.set(rp)
    st, loc = await post(client, LENA, "opdemo", csrf_token=tok, guild="2000", form="settings")
    assert "ok=Erledigt" in loc and demo.calls[-1][2:4] == ([2000], False), demo.calls[-1]
    st, loc = await post(client, LENA, "opdemo", csrf_token=tok, guild="2000", form="act")
    assert demo.calls[-1][2:4] == ([1000, 2000], True), "OPERATE-POST: Server mit ≥ Bedienen"
    print("Ansehen: nichts · Bearbeiten/Owner: alles · visible_guilds bei POST je nach Klassifizierung – OK")
    assert len(await wc.config.audit()) > a0

    # Callable-Variante
    n = len(demo.calls)
    st, loc = await post(client, LENA, "opcall", csrf_token=tok, guild="1000", form="custom", x="1")
    assert "ok=Erledigt" in loc and demo.calls[-1][0] == "opcall" and demo.calls[-1][3] is True
    for x in ("2", "boom"):
        st, loc = await post(client, LENA, "opcall", csrf_token=tok, guild="1000", form="custom", x=x)
        assert TOAST_EDIT in loc, (x, loc)
    st, loc = await post(client, LENA, "opcall", csrf_token=tok, guild="1000", form="act")
    assert TOAST_EDIT in loc and len(demo.calls) == n + 1
    # Seite ohne operate_forms: Bedienen darf nichts
    st, loc = await post(client, LENA, "opnone", csrf_token=tok, guild="1000", form="act")
    assert TOAST_EDIT in loc and len(demo.calls) == n + 1
    # Tom hat auf opcall nur Ansehen
    st, loc = await post(client, TOM, "opcall", csrf_token=tok_t, guild="1000", form="custom", x="1")
    assert "Keine Bearbeitungsrechte" in loc
    print("Callable operate_forms (inkl. Fehler im Callable = kein Tagesgeschäft), Seite ohne operate_forms – OK")

    # ------------------------------------------------------------ bestehende Werte view/edit unverändert
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "edit", "poll": "view"}}})
    t = await (await client.get("/cogs/poll?guild=1000", headers=LENA)).text()
    assert 'data-readonly="1"' in t and "data-operate" not in t
    t = await (await client.get("/cogs/tickets?guild=1000", headers=LENA)).text()
    assert 'data-readonly="0"' in t and "data-operate" not in t and "ro-banner" not in t
    tok = csrf(t)
    st, loc = await post(client, LENA, "tickets", csrf_token=tok, guild="1000", form="settings", language="en",
                         ticket_type="category", max_open="2", name_template="ticket-{num}")
    assert "gespeichert" in loc.lower(), loc
    st, loc = await post(client, LENA, "poll", csrf_token=tok, guild="1000", form="settings", language="en")
    assert "Keine Bearbeitungsrechte" in loc
    print("Gespeicherte „view“/„edit“ funktionieren unverändert – OK")

    # ------------------------------------------------------------ Zugriff & Rollen
    await wc.config.role_perms.set({"1000": {"1101": {"opdemo": "operate", "levels": "view"}}})
    t = await (await client.get("/access?guild=1000", headers=OWNER)).text()
    tok = csrf(t)
    for needle in ("value='operate' selected", "lv-operate", "Bedienen", "wc-lv-legend", "name='template'",
                   "form='wc-tpl-1101'", "id='wc-tpl-1101'", "value='apply_template'", "Vorlage anwenden",
                   "value='eventleitung'", "Eventleitung", "Moderator", "Nur ansehen", "ohne Bedienen"):
        assert needle in t, needle
    assert "Startwert" not in t
    opnone_head = re.search(r"<th class='wc-col'><i class='bi bi-stars'></i><span>Op-Ohne</span>(.*?)</th>", t).group(1)
    assert "ohne Bedienen" in opnone_head
    opdemo_head = re.search(r"<th class='wc-col'><i class='bi bi-stars'></i><span>Op-Demo</span>(.*?)</th>", t).group(1)
    assert "ohne Bedienen" not in opdemo_head
    slugs = set(wc.pages)

    async def access(**fields):
        r = await client.post("/access", headers=OWNER, data={"csrf_token": tok, "guild": "1000", **fields}, **nr)
        return unquote_plus(r.headers["Location"])

    loc = await access(form="add_role", role_id="1104", template="support")
    assert "ok=Rolle VIP hinzugefügt (Vorlage Support)" in loc, loc
    rp = (await wc.config.role_perms())["1000"]
    exp_support = {s: v for s, v in {"tickets": "operate", "commands": "view"}.items() if s in slugs}
    assert rp["1104"] == exp_support, rp["1104"]   # warnings/serverstats nicht registriert -> nicht gesetzt
    loc = await access(form="add_role", role_id="1104", template="admin")
    assert "err=" in loc and "bereits" in loc
    loc = await access(form="apply_template", role_id="1101", template="moderator")
    assert "ok=Vorlage Moderator auf Support angewendet" in loc, loc
    rp = (await wc.config.role_perms())["1000"]
    mod = acl.ROLE_TEMPLATES["moderator"]["levels"]
    assert rp["1101"] == {**{s: v for s, v in mod.items() if s in slugs}, "levels": "view"}, rp["1101"]
    loc = await access(form="apply_template", role_id="1101", template="admin")
    rp = (await wc.config.role_perms())["1000"]
    assert all(rp["1101"][s] == "edit" for s in slugs) and rp["1101"]["levels"] == "view"
    loc = await access(form="apply_template", role_id="1101", template="operate")
    assert all(v == "operate" for s, v in (await wc.config.role_perms())["1000"]["1101"].items() if s in slugs)
    loc = await access(form="apply_template", role_id="1101", template="gibtsnicht")
    assert "err=Vorlage nicht gefunden" in loc
    loc = await access(form="add_role", role_id="1102", template="eventleitung")
    rp = (await wc.config.role_perms())["1000"]
    assert rp["1102"] == {s: v for s, v in acl.ROLE_TEMPLATES["eventleitung"]["levels"].items() if s in slugs}
    # älteres Formular („Startwert“ 2 = Bearbeiten) funktioniert weiter
    loc = await access(form="add_role", role_id="1103", default="2")
    assert all(v == "edit" for v in (await wc.config.role_perms())["1000"]["1103"].values())
    # Matrix mit operate; Zahlenwerte (alte offene Seite) werden abgelehnt
    before = await wc.config.role_perms()
    data = [("csrf_token", tok), ("form", "matrix"), ("guild", "1000"), ("roles", "1101")]
    data += [(f"p:1101:{s}", "2") for s in slugs]
    r = await client.post("/access", headers=OWNER, data=data, **nr)
    assert "err=" in r.headers["Location"] and await wc.config.role_perms() == before
    data = [("csrf_token", tok), ("form", "matrix"), ("guild", "1000"), ("roles", "1101")]
    data += [(f"p:1101:{s}", {"opdemo": "operate", "tickets": "edit", "poll": "view"}.get(s, "none")) for s in slugs]
    r = await client.post("/access", headers=OWNER, data=data, **nr)
    assert (await wc.config.role_perms())["1000"]["1101"] == {"opdemo": "operate", "tickets": "edit", "poll": "view",
                                                              "levels": "view"}
    # Vorlage, die für die geladenen Seiten nichts ergibt
    saved = dict(wc.pages)
    for s in list(wc.pages):
        if s not in ("example",):
            del wc.pages[s]
    g1.roles.append(H.Role(g1, 1105, "Gast", 1))
    loc = await access(form="add_role", role_id="1105", template="support")
    assert "err=" in loc and "keine Rechte" in loc and "1105" not in (await wc.config.role_perms())["1000"], loc
    wc.pages.clear(); wc.pages.update(saved)
    au = [a for a in (await wc.config.audit()) if a["page"] == "access"]
    assert any(a["action"] == "apply_template" and a["ok"] for a in au)
    print("Zugriff & Rollen: 4 Stufen, Legende, Vorlagen beim Hinzufügen und pro Rolle, unbekannte slugs bleiben, "
          "alte Formulare, Zahlenwerte abgelehnt – OK")

    # ------------------------------------------------------------ Befehle
    sent = []

    async def ctx_send(content=None, **kw):
        sent.append(content)
    ctx = types.SimpleNamespace(guild=g1, author=types.SimpleNamespace(id=1, display_name="Matters86",
                                                                        display_avatar=None),
                                send=ctx_send, clean_prefix="!")
    vip = g1.get_role(1104)
    await wc.config.role_perms.set({})
    await wc.webcore_roleperm.callback(wc, ctx, vip, "opdemo", "bedienen")
    assert (await wc.config.role_perms()) == {"1000": {"1104": {"opdemo": "operate"}}} and "Bedienen" in sent[-1]
    await wc.webcore_roleperm.callback(wc, ctx, vip, "opnone", "operate")
    assert "wirkt dort wie" in sent[-1]
    await wc.webcore_roleperm.callback(wc, ctx, vip, "tickets", "bearbeiten")
    await wc.webcore_roleperm.callback(wc, ctx, vip, "poll", "view")
    rp = (await wc.config.role_perms())["1000"]["1104"]
    assert rp == {"opdemo": "operate", "opnone": "operate", "tickets": "edit", "poll": "view"}, rp
    await wc.webcore_roleperm.callback(wc, ctx, vip, "poll", "superuser")
    assert "operate" in sent[-1] and "poll" in (await wc.config.role_perms())["1000"]["1104"]
    await wc.webcore_roleperm.callback(wc, ctx, vip, "poll", "none")
    assert "poll" not in (await wc.config.role_perms())["1000"]["1104"]
    await wc.webcore_roleperm.callback(wc, ctx, vip, "alle", "ansehen")
    assert set((await wc.config.role_perms())["1000"]["1104"].values()) == {"view"}
    await wc.webcore_roles.callback(wc, ctx)
    assert "opdemo=ansehen" in sent[-1], sent[-1]
    await wc.webcore_roleperm.callback(wc, ctx, vip, "opdemo", "bedienen")
    await wc.webcore_roles.callback(wc, ctx)
    assert "opdemo=bedienen" in sent[-1] and "tickets=ansehen" in sent[-1], sent[-1]
    await wc.webcore_roletemplate.callback(wc, ctx, vip, vorlage="Eventleitung")
    rp = (await wc.config.role_perms())["1000"]["1104"]
    assert rp == {s: v for s, v in acl.ROLE_TEMPLATES["eventleitung"]["levels"].items() if s in slugs}, rp
    assert "Eventleitung" in sent[-1]
    await wc.webcore_roletemplate.callback(wc, ctx, vip, vorlage="nur ansehen")
    assert set((await wc.config.role_perms())["1000"]["1104"].values()) == {"view"}
    await wc.webcore_roletemplate.callback(wc, ctx, vip, vorlage="superheld")
    assert "Unbekannte Vorlage" in sent[-1]
    await wc.webcore_roletemplate.callback(wc, ctx, g1.default_role, vorlage="admin")
    assert "@everyone" in sent[-1]
    assert any(a["action"] == "roletemplate (Befehl)" for a in await wc.config.audit())
    print("Befehle: roleperm (operate + deutsche Aliase, alle, ungültig), roles zeigt Stufe, roletemplate – OK")

    # ------------------------------------------------------------ Sicherung
    await wc.config.role_perms.set({"1000": {"1101": {"opdemo": "operate", "tickets": "edit"}}})
    t = await (await client.get("/backup?guild=1000", headers=OWNER)).text()
    tok = csrf(t)
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "export", "guild": "1000"}, **nr)
    exp = json.loads(await r.text())
    assert exp["webcore"]["role_perms"] == {"1101": {"opdemo": "operate", "tickets": "edit"}}, exp["webcore"]
    wp = await bk.plan_webcore(wc, g1, {"role_perms": {"1101": {"opdemo": "operate", "poll": "bedienen",
                                                                "tickets": "OPERATE"}}}, same_guild=True)
    assert wp["invalid_levels"] == [("Support", "poll", "bedienen")], wp["invalid_levels"]
    assert wp["role_perms"] == {"1101": {"opdemo": "operate", "tickets": "operate"}}, wp["role_perms"]
    # HTTP-Import mit operate
    await wc.config.role_perms.set({})
    fd = FormData()
    for k, v in (("csrf_token", tok), ("form", "preview"), ("guild", "1000")):
        fd.add_field(k, v)
    fd.add_field("backup", json.dumps(exp).encode(), filename="b.json", content_type="application/json")
    r = await client.post("/backup?guild=1000", headers=OWNER, data=fd, **nr)
    loc = r.headers["Location"]; pid = re.search(r"preview=([^&]+)", loc).group(1)
    t = await (await client.get(loc, headers=OWNER)).text()
    assert "Op-Demo: Bedienen" in t, "Vorschau nennt die Stufe"
    r = await client.post("/backup", headers=OWNER, data={"csrf_token": tok, "form": "confirm", "guild": "1000",
                                                          "preview": pid, "include_webcore": "on"}, **nr)
    assert "ok=" in r.headers["Location"]
    assert await wc.config.role_perms() == {"1000": {"1101": {"opdemo": "operate", "tickets": "edit"}}}
    print("Sicherung: Export/Import mit „operate“, Aliase im Import ungültig – OK")

    # ------------------------------------------------------------ JS-Sperre im Browser (optional)
    await wc.config.role_perms.set({"1000": {"1101": {"opdemo": "operate", "opcall": "operate"},
                                             "1102": {"opdemo": "view"}, "1103": {"opdemo": "edit"}}})
    await js_check(client)
    await client.close()
    print("ALLE OPERATE-TESTS OK")


async def js_check(client):
    try:
        from playwright.async_api import async_playwright
    except Exception:  # noqa: BLE001
        print("JS-Sperre: Playwright nicht installiert – übersprungen")
        return
    base = str(client.make_url("/")).rstrip("/")

    async def route(r):
        if r.request.url.startswith(base):
            return await r.continue_()
        return await r.abort()
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 – kein Browser installiert
            print(f"JS-Sperre: Chromium nicht startbar ({type(exc).__name__}) – übersprungen")
            return
        errors = []

        async def state(user, path):
            ctx = await browser.new_context(extra_http_headers={"X-Test-User": user})
            page = await ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("**/*", route)
            await page.goto(base + path)
            res = await page.evaluate("""() => {
                const d = id => document.getElementById(id).disabled;
                const l = id => document.getElementById(id).getAttribute('data-wc-locked') === '1';
                return {act: d('b-act'), set: d('b-set'), note: d('i-note'), repost: d('b-repost'),
                        del: d('b-del'), reason: d('i-reason'), custom: d('b-custom'),
                        lAct: l('f-act'), lSet: l('f-set'), lBtn: l('f-btn'), lCustom: l('f-custom')};
            }""")
            await ctx.close()
            return res
        s = await state("11", "/cogs/opdemo?guild=1000")   # Bedienen, Liste act,repost
        assert s == {"act": False, "set": True, "note": True, "repost": False, "del": True, "reason": False,
                     "custom": False, "lAct": False, "lSet": True, "lBtn": False, "lCustom": False}, s
        s = await state("11", "/cogs/opcall?guild=1000")   # Bedienen, Callable: nur data-wc-operate
        assert s["custom"] is False and s["act"] and s["set"] and s["repost"] and s["lAct"], s
        s = await state("12", "/cogs/opdemo?guild=1000")   # Ansehen: alles gesperrt
        assert all(s[k] for k in ("act", "set", "repost", "del", "custom")), s
        s = await state("14", "/cogs/opdemo?guild=1000")   # Bearbeiten: nichts gesperrt
        assert not any(s[k] for k in ("act", "set", "repost", "del", "custom")), s
        await browser.close()
        assert not errors, errors
    print("JS-Sperre (Chromium): Bedienen sperrt nur Nicht-Tagesgeschäft (Formular/Button), Callable, Ansehen, "
          "Bearbeiten – keine JS-Fehler – OK")


asyncio.run(main())
