"""Organigramm: Mehrfachanzeige / höchste Position in allen Ausgaben und Einstellungen."""
import asyncio
import re
from copy import deepcopy
from types import SimpleNamespace

import live_harness as L
import discord
from aiohttp.test_utils import TestClient, TestServer

from rc.organigram.organigram import Organigram, resolve_node_people
from rc.organigram.render import build_text_tree


def node(role, *, parent=None, order=0, label="", manual=()):
    return {"role_id": role, "parent": parent, "order": order, "label": label,
            "manual_names": list(manual)}


def member_ids(people, nid):
    return [member.id for _, member in people[nid] if member is not None]


class OrgThread(L._SendMixin, discord.Thread):
    guild = None
    category_id = None

    @classmethod
    def make(cls, guild, cid):
        thread = object.__new__(cls)
        L._init_common(thread, guild, cid, "organigramm-thread", None, 0)
        thread.parent_id = guild.text_channels[0].id
        thread.archived = True
        thread.locked = False
        return thread


async def main():
    guilds = L.H.build_world()
    bot = L.H.FakeBot(guilds)
    guild = guilds[0]
    cog = Organigram(bot)
    chart = {"name": "Team", "title": "Unser Team", "show_avatars": False,
             "show_vacant": False, "auto_update": True,
             # Absichtlich Kind vor Eltern und hohe Discord-Rolle unter niedriger Rolle.
             "nodes": {"support": node(1101, parent="lead", label="Support"),
                       "lead": node(1103, label="Leitung")}, "posts": []}

    legacy = resolve_node_people(guild, chart)
    assert 14 in member_ids(legacy, "lead") and 14 in member_ids(legacy, "support")
    chart["member_display"] = "highest"
    people = resolve_node_people(guild, chart)
    assert member_ids(people, "lead") == [14]
    assert member_ids(people, "support") == [11], "Organigrammhöhe schlägt Discord-Rollenhöhe"
    assert resolve_node_people(guild, dict(chart, member_display="multiple")) == legacy
    assert resolve_node_people(guild, dict(chart, member_display="unknown")) == legacy

    # Oberste Ebene gewinnt auch gegenüber einem Kind des ersten sichtbaren Zweigs.
    levels = deepcopy(chart)
    levels["nodes"]["other"] = node(1101, order=100, label="Andere Leitung")
    people = resolve_node_people(guild, levels)
    assert member_ids(people, "support") == []
    assert member_ids(people, "other") == [11]

    # Gleiche Ebene: konfigurierte Reihenfolge, danach Beschriftung.
    same_level = dict(chart, nodes={"a": node(1101, order=10, label="A"),
                                   "b": node(1101, order=0, label="Z")})
    assert member_ids(resolve_node_people(guild, same_level), "a") == []
    assert member_ids(resolve_node_people(guild, same_level), "b") == [11, 14]
    same_level["nodes"]["a"]["order"] = 0
    assert member_ids(resolve_node_people(guild, same_level), "a") == [11, 14]
    assert member_ids(resolve_node_people(guild, same_level), "b") == []
    branches = dict(chart, nodes={"root_a": node(None, order=0),
                                 "child_a": node(1101, parent="root_a", order=100),
                                 "root_b": node(None, order=100),
                                 "child_b": node(1101, parent="root_b", order=0)})
    assert member_ids(resolve_node_people(guild, branches), "child_a") == [11, 14]
    assert member_ids(resolve_node_people(guild, branches), "child_b") == []
    empty = dict(chart, nodes={"missing": node(999999)})
    assert resolve_node_people(guild, empty) == {"missing": []}

    # Identität = Discord-ID, keine Namensvergleiche; manuelle Namen bleiben erhalten.
    role = guild.get_role(1101)
    first = L.H.Member(guild, 501, "Gleicher Name", [role])
    second = L.H.Member(guild, 502, "Gleicher Name", [role])
    robot = L.H.Member(guild, 503, "Bot", [role, guild.get_role(1103)])
    robot.bot = True
    guild.members.extend([first, second, robot])
    chart["nodes"]["support"]["manual_names"] = ["Mia", "Externe Person"]
    people = resolve_node_people(guild, chart)
    assert {11, 501, 502} == set(member_ids(people, "support"))
    assert set(member_ids(people, "lead")) == {14, 503}, "Bots folgen derselben bestehenden Anzeigeregel"
    assert [name for name, member in people["support"] if member is None] == ["Mia", "Externe Person"]
    chart["nodes"]["support"]["manual_names"] = []
    print("Zuordnung: rückwärtskompatibel, Hierarchie, Gleichstand, IDs, Freitext und Bots – OK")

    model = await cog._resolve(guild, chart)
    assert build_text_tree(model).count("Mia") == 1
    embed = cog._build_embed(guild, chart, model)
    assert sum(field.value.count("Mia") for field in embed.fields) == 1
    png = await cog._render_png(guild, chart)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    await cog.config.guild(guild).charts.set({"team": chart})
    channel = guild.text_channels[0]
    for mode in ("text", "embed", "image"):
        ok, error = await cog._post_and_save(guild, "team", channel, mode)
        assert ok, error
        stored = (await cog.config.guild(guild).charts())["team"]
        posted = await channel.fetch_message(stored["posts"][0]["message_id"])
        if mode == "text":
            assert posted.content.count("Mia") == 1
        elif mode == "embed":
            assert sum(field.value.count("Mia") for field in posted.embed.fields) == 1
    assert len(stored["posts"]) == 1
    assert len(channel._messages) == 1

    # Fehlende Leserechte dürfen trotz erlaubtem Senden keine Doppelposts erzeugen.
    old_id = stored["posts"][0]["message_id"]
    channel.forbid.add("history")
    ok, error = await cog._post_and_save(guild, "team", channel, "text")
    assert not ok and "Rechte" in error
    await cog._refresh_chart(guild.id, "team")
    assert len(channel._messages) == 1
    assert (await cog.config.guild(guild).charts())["team"]["posts"][0]["message_id"] == old_id
    channel.forbid.clear()

    original_fetch = channel.fetch_message

    async def temporary_message_error(mid):
        raise discord.HTTPException(SimpleNamespace(status=503, reason="Unavailable"), "temporär")

    channel.fetch_message = temporary_message_error
    try:
        ok, error = await cog._post_and_save(guild, "team", channel, "text")
        assert not ok and error
        assert len(channel._messages) == 1
        assert (await cog.config.guild(guild).charts())["team"]["posts"][0]["message_id"] == old_id
    finally:
        channel.fetch_message = original_fetch

    # Eine tatsächlich gelöschte Nachricht wird durch genau eine neue ersetzt.
    channel._messages.pop(old_id)
    await cog._refresh_chart(guild.id, "team")
    new_id = (await cog.config.guild(guild).charts())["team"]["posts"][0]["message_id"]
    assert new_id != old_id and len(channel._messages) == 1

    # Archivierte/nicht gecachte Threads sind nicht gelöscht: erst per Discord auflösen.
    thread = OrgThread.make(guild, 8001)
    thread_chart = deepcopy(chart)
    thread_chart["name"] = "Thread"
    thread_chart["posts"] = []
    async with cog.config.guild(guild).charts() as charts:
        charts["thread"] = thread_chart
    ok, error = await cog._post_and_save(guild, "thread", thread, "text")
    assert ok, error
    thread_post = (await cog.config.guild(guild).charts())["thread"]["posts"][0]
    fetch_state = {"error": None, "calls": []}

    async def fetch_channel(cid):
        fetch_state["calls"].append(cid)
        assert cid == thread.id
        if fetch_state["error"] is not None:
            raise fetch_state["error"]
        return thread

    guild.fetch_channel = fetch_channel
    try:
        assert guild.get_channel_or_thread(thread.id) is None
        await cog._refresh_chart(guild.id, "thread")
        assert fetch_state["calls"] == [thread.id]
        refreshed = (await cog.config.guild(guild).charts())["thread"]["posts"][0]
        assert refreshed["message_id"] == thread_post["message_id"] and not refreshed["last_error"]
        assert len(thread._messages) == 1
        for failure in (L.forbidden(), discord.HTTPException(
                SimpleNamespace(status=503, reason="Unavailable"), "temporär")):
            fetch_state["error"] = failure
            await cog._refresh_chart(guild.id, "thread")
            failed = (await cog.config.guild(guild).charts())["thread"]["posts"][0]
            assert failed["message_id"] == thread_post["message_id"] and failed["last_error"]
            assert failed["last_success_at"] == refreshed["last_success_at"]
            assert len(thread._messages) == 1
        fetch_state["error"] = L.not_found()
        await cog._refresh_chart(guild.id, "thread")
        assert (await cog.config.guild(guild).charts())["thread"]["posts"] == []
    finally:
        del guild.fetch_channel
    print("Post-Sicherheit: Lesefehler ohne Duplikate, echte Löschung ersetzt, Threads aufgelöst/erhalten – OK")

    # Rollenwechsel verschiebt die Person beim nächsten Auflösen in die verbleibende Position.
    mia = guild.get_member(14)
    mia.roles.remove(guild.get_role(1103))
    changed = resolve_node_people(guild, chart)
    assert 14 not in member_ids(changed, "lead") and 14 in member_ids(changed, "support")
    print("Vorschau/Bild/Embed/Text/Posten teilen Zuordnung, Rollenwechsel passt Anzeige an – OK")

    scheduled = []
    cog._schedule = lambda gid, cid: scheduled.append((gid, cid))
    replies = []

    async def send(content):
        replies.append(content)

    ctx = SimpleNamespace(guild=guild, send=send)
    await cog.og_members.callback(cog, ctx, "Team", "multiple")
    assert (await cog.config.guild(guild).charts())["team"]["member_display"] == "multiple"
    assert scheduled == [(guild.id, "team")]
    await cog.og_members.callback(cog, ctx, "Team", "highest")
    assert (await cog.config.guild(guild).charts())["team"]["member_display"] == "highest"
    assert "höchsten" in replies[-1]
    await cog.og_members.callback(cog, ctx, "Unbekannt", "highest")
    assert "Kein Organigramm" in replies[-1]

    # Echtes Dashboard: Einstellung sichtbar, Speichern nur mit Bearbeiten.
    wc = await L.H.make_webcore(bot)
    cog._register_dashboard(wc)
    await wc.config.role_perms.set({"1000": {"1101": {"organigram": "operate"},
                                             "1102": {"organigram": "view"}}})
    client = TestClient(TestServer(wc.app))
    await client.start_server()
    try:
        for uid, allowed in ((11, False), (12, False), (1, True)):
            headers = {"X-Test-User": str(uid)}
            response = await client.get("/cogs/organigram?guild=1000&chart=team", headers=headers)
            html = await response.text()
            assert response.status == 200
            assert 'name="member_display"' in html or "name='member_display'" in html
            csrf = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
            response = await client.post("/cogs/organigram", headers=headers, allow_redirects=False,
                                         data={"csrf_token": csrf, "guild": "1000", "chart": "team",
                                               "form": "chart_settings", "name": "Team",
                                               "member_display": "multiple"})
            assert response.status == 302, (uid, response.status, await response.text())
            assert ("Einstellungen+gespeichert" in response.headers["Location"]) == allowed, (
                uid, response.headers["Location"])
            if not allowed:
                assert (await wc.config.audit())[0]["ok"] is False
            expected = "multiple" if allowed else "highest"
            assert (await cog.config.guild(guild).charts())["team"]["member_display"] == expected

        # Neues Organigramm und alte Formularversion: einmalige Anzeige bleibt erhalten.
        headers = {"X-Test-User": "1"}
        response = await client.post("/cogs/organigram", headers=headers, allow_redirects=False,
                                     data={"csrf_token": csrf, "guild": "1000", "form": "chart_new",
                                           "name": "Neu", "member_display": "highest"})
        assert response.status == 302
        created_id = re.search(r"chart=([0-9a-f]+)", response.headers["Location"]).group(1)
        assert (await cog.config.guild(guild).charts())[created_id]["member_display"] == "highest"
        response = await client.post("/cogs/organigram", headers=headers, allow_redirects=False,
                                     data={"csrf_token": csrf, "guild": "1000", "form": "chart_settings",
                                           "chart": created_id, "name": "Neu"})
        assert response.status == 302
        assert (await cog.config.guild(guild).charts())[created_id]["member_display"] == "highest"
    finally:
        await client.close()
        await cog.cog_unload()
        await wc.cog_unload()
    print("Befehl und Dashboard speichern, planen Aktualisierung und prüfen Bearbeiten-Recht – OK")


if __name__ == "__main__":
    asyncio.run(main())
