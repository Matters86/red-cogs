"""Ticketnamen: konfigurierbares Format gilt auch mit Grund und erhält die Nummer."""
import asyncio
import re
from types import SimpleNamespace

import tc_harness as T
from aiohttp.test_utils import TestClient, TestServer
from rc.tickets.naming import NAME_PRESETS, name_format, parse_name_settings, ticket_base_name


async def main():
    wc, bot, app, tickets, _ = await T.make_app()
    guild = bot.guilds[0]
    gc = tickets.config.guild(guild)
    user = guild.get_member(13)
    reason = {"id": "bug", "label": "Störung"}
    legacy = await gc.all()
    assert ticket_base_name(legacy, reason, 42, user) == "Störung-42"
    assert ticket_base_name(legacy, None, 42, user) == "ticket-42"
    assert tickets._channel_name(ticket_base_name(legacy, {"label": "ü" * 80}, 42, user)).endswith("-42")
    conf = dict(legacy, name_template_mode="template", name_template=NAME_PRESETS["reason_user_num"])
    assert ticket_base_name(conf, reason, 42, user) == "Störung-kai-42"
    assert ticket_base_name(conf, None, 42, user) == "ticket-kai-42"
    assert name_format(conf) == "reason_user_num"
    long_user = SimpleNamespace(id=123, name="ü" * 100, display_name="ä" * 100)
    long_name = ticket_base_name(conf, {"label": "Ö" * 100}, 987654, long_user)
    slug = tickets._channel_name(long_name)
    assert 70 <= len(slug) <= 90 and slug.endswith("-987654"), slug
    for template in ("{reason}.{display}.{num}", "x" * 65 + "{id}-{num}"):
        configured = dict(conf, name_template=template)
        assert "42" in ticket_base_name(configured, reason, 42, user)
    for template in ("{reason}-{user}", "{unknown}-{num}", "x\n{num}", "{num:03}", "x" * 100):
        try:
            parse_name_settings({"name_format": "custom", "name_template": template}, conf)
        except ValueError:
            pass
        else:
            raise AssertionError("Ungültige Namensvorlage akzeptiert: " + template)
    assert parse_name_settings({}, legacy) == ("legacy", "ticket-{num}")
    print("Namensformate: Grund/Nutzer/Nummer, lange Umlaute, sichere Platzhalter und unveränderte Altvorgabe – OK")

    await gc.category_open.set(guild.categories[0].id)
    await gc.support_roles.set([1101])
    await gc.max_open.set(25)
    await gc.name_template_mode.set("template")
    await gc.name_template.set(NAME_PRESETS["reason_user_num"])
    panel = {"id": "panel", "reasons": [reason]}
    await gc.panels.set([panel])
    opened = await tickets.open_ticket(guild, user, panel, reason, {})
    assert opened.status == "ok", opened
    assert opened.target.name == "stoerung-kai-1", opened.target.name
    rec = (await gc.tickets())[str(opened.target.id)]
    assert rec["reason_label"] == "Störung" and rec["owner_id"] == user.id and rec["num"] == 1

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/cogs/tickets?guild=1000", headers={"X-Test-User": "1"})
        html = await response.text()
        assert response.status == 200 and 'name_format' in html
        token = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
        before = await gc.all()
        response = await client.post("/cogs/tickets", headers={"X-Test-User": "1"}, data={
            "csrf_token": token, "guild": "1000", "form": "settings", "name_format": "custom",
            "name_template": "{unbekannt}-{num}", "max_open": "2"}, allow_redirects=False)
        assert response.status == 302 and "err=" in response.headers["Location"]
        assert await gc.all() == before, "Ungültige Namensvorlage darf keine anderen Einstellungen mitspeichern"
        response = await client.post("/cogs/tickets", headers={"X-Test-User": "1"}, data={
            "csrf_token": token, "guild": "1000", "form": "settings", "name_format": "user_reason_num",
            "language": "de", "ticket_type": "category", "max_open": "25", "category_open": str(guild.categories[0].id)},
            allow_redirects=False)
        assert response.status == 302 and "err=" not in response.headers["Location"]
        configured = await gc.all()
        assert configured["name_template"] == NAME_PRESETS["user_reason_num"] and configured["name_template_mode"] == "template"
        assert opened.target.name == "stoerung-kai-1", "Bestehende Tickets dürfen nicht ungefragt umbenannt werden"
        print("Erstellung und Dashboard: gewähltes Format tatsächlich genutzt, ungültige Vorlage ohne Teiländerung – OK")
    finally:
        await client.close()
        await wc.cog_unload()


if __name__ == "__main__":
    asyncio.run(main())
