"""WebCore-Harness für „Mein Bereich“, öffentliche API und Audit-Kanal.

Baut auf wc_harness.py auf (unverändert importiert) und ergänzt:
* Nutzer 21 „Ben“ (nur auf Server 2000, keine Rechte), Nutzer 13 „Kai“ (nur Server 1000, VIP)
* Dummy-Mitglieder-Seiten + Dummy-Public-API, registriert von einem Fake-Owner-Objekt
* Fake-Kanäle mit send()-Aufzeichnung (SENT) für das Audit-Log nach Discord

Start: python tests/wcm_harness.py [port]   (ohne Port: freier Port)
"""
import html, types
import wc_harness as H

SENT = []           # (channel_id, kwargs) aller Chan.send-Aufrufe
COUNTERS = {}       # (guild_id, user_id) -> Klicks auf der Demo-Seite


async def _send(self, *args, **kwargs):
    SENT.append((self.id, kwargs))
    return types.SimpleNamespace(id=len(SENT))

H.Chan.send = _send

DEMO = types.SimpleNamespace(qualified_name="DemoCog")


async def profil_page(request):
    wc = request.app["webcore"]; ui = wc.ui
    guild = request["wc_member_guild"]; member = request["wc_member"]
    key = (guild.id, member.id)
    if request.method == "POST":
        form = await request.post()
        if form.get("form") == "click":
            COUNTERS[key] = COUNTERS.get(key, 0) + 1
            return {"redirect": f"/me/profil?guild={guild.id}&ok=Gezählt"}
        return {"redirect": f"/me/profil?guild={guild.id}&err=Unbekannte+Aktion"}
    roles = ", ".join(r.name for r in member.roles if not r.is_default()) or "—"
    body = (
        ui.hero("bi-person-vcard", "", f"Deine Daten auf <b>{html.escape(guild.name)}</b>.")
        + ui.card("Profil", ui.grid(
            ui.field("Anzeigename", f"<div class='mono'>{html.escape(member.display_name)}</div>"),
            ui.field("Rollen", f"<div>{html.escape(roles)}</div>"),
            ui.field("Klicks", f"<div class='mono' id='clicks'>{COUNTERS.get(key, 0)}</div>"),
        ), icon="bi-person")
        + ui.card("Aktion", ui.form(f"/me/profil?guild={guild.id}", ui.button("Klick zählen", icon="bi-hand-index"),
                                    csrf=request["webcore_csrf"], hidden={"form": "click", "guild": guild.id}))
    )
    return {"title": "Mein Profil", "content": body}


async def tickets_page(request):
    ui = request.app["webcore"].ui
    return {"title": "Meine Tickets", "content": ui.card(None, ui.empty("bi-ticket", "Keine offenen Tickets"))}


async def api_status(request):
    from aiohttp import web
    return web.json_response({"ok": True, "tail": request.match_info.get("tail", ""), "guilds": 2})


async def api_boom(request):
    raise RuntimeError("geheimer interner Fehler /pfad/zur/datei.py")


def register_demo(wc):
    wc.register_member_page(DEMO, "profil", "Mein Profil", profil_page, icon="bi-person-vcard",
                            description="Deine Rollen und ein Test-Zähler.")
    wc.register_member_page(DEMO, "tickets", "Meine Tickets", tickets_page, icon="bi-ticket-perforated",
                            description="Deine offenen und geschlossenen Tickets.")
    wc.register_public_api(DEMO, "status", api_status)
    wc.register_public_api(DEMO, "boom", api_boom)


async def make_app():
    wc, bot, app = await H.make_app()
    g1, g2 = bot.guilds
    g2.members.append(H.Member(g2, 21, "Ben", []))
    register_demo(wc)
    return wc, bot, app


async def make_demo():
    """Wie make_app, dazu Beispieldaten fürs Anschauen im Browser."""
    wc, bot, app = await make_app()
    # Mein Bereich auf Server 1000 an, Audit-Kanal gesetzt, etwas Audit-Historie.
    await wc.config.member_portal.set({"1000": True})
    await wc.config.audit_channels.set({"1000": 1004})
    await wc.config.role_perms.set({"1000": {"1101": {"tickets": "edit", "poll": "view"}}})
    owner = {"id": 1, "name": "Matters86"}
    await wc._audit(None, owner, page="access", guild_id=1000, action="portal", result="Mein Bereich eingeschaltet", ok=True)
    await wc._audit(None, {"id": 13, "name": "Kai"}, page="me:profil", guild_id=2000, action="guild",
                    result="Kein Mitglieder-Zugriff auf diesen Server", ok=False, area="member")
    return wc, bot, app


if __name__ == "__main__":
    H.main(make_demo)
