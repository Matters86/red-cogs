"""Echte Workflows: Roster, Umfrage-Reparatur, Changelog, Ideen und Layout-Wiederherstellung."""
import asyncio
import re
import time
from types import SimpleNamespace, MethodType

import tc_harness as T
import discord
from aiohttp.test_utils import TestClient, TestServer

from rc.poll.poll import Poll
from rc.raidhelper.raidhelper import RaidHelper
from rc.ideas.ideas import Ideas
from rc.ideas.views import SimilarIdeasView
from rc.serverlayout.serverlayout import ServerLayout, LoadError

L = T.L


class IdeaThread(L._SendMixin, discord.Thread):
    applied_tags = None
    @classmethod
    def make(cls, guild, cid, name, parent_id):
        obj = object.__new__(cls)
        obj.id, obj.guild, obj.name, obj.parent_id = cid, guild, name, parent_id
        obj._state, obj._messages, obj.forbid = None, {}, set()
        obj.archived, obj.locked = False, False
        obj.applied_tags = []
        return obj

    async def add_user(self, member):
        return None

    async def edit(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)
        return self


class IdeasForum(discord.ForumChannel):
    available_tags = None

    @classmethod
    def make(cls, guild):
        obj = object.__new__(cls)
        obj.id, obj.guild, obj.name, obj.available_tags = 1800, guild, "ideen", [SimpleNamespace(id=1, name="Neu")]
        obj.posts = []
        return obj

    def permissions_for(self, member):
        return discord.Permissions.all()

    def get_tag(self, tag_id):
        return next((tag for tag in self.available_tags if tag.id == tag_id), None)

    async def edit(self, *, available_tags, **kw):
        for index, tag in enumerate(available_tags, 1):
            if not tag.id:
                tag.id = index
        self.available_tags = available_tags
        return self

    async def create_thread(self, *, name, embed, **kw):
        thread = IdeaThread.make(self.guild, 900000 + len(self.posts), name, self.id)
        message = await thread.send(embed=embed)
        self.guild.threads.append(thread)
        self.posts.append(thread)
        return SimpleNamespace(thread=thread, message=message)


def setup_layout_world(guild):
    """Discord-Mutationen faken; Planner, Executor, Dateiformat und automatische Backups bleiben echt."""
    for role in guild.roles:
        role.permissions = discord.Permissions.none()
        role.hoist, role.mentionable = False, False
    guild.me.guild_permissions = discord.Permissions.all()
    for key in ("verification_level", "explicit_content_filter", "default_notifications", "system_channel_flags"):
        setattr(guild, key, 0)
    guild.afk_timeout = 300

    def patch_role(role):
        async def edit(self, **kw):
            for key, value in kw.items():
                if key == "reason":
                    continue
                setattr(self, "color" if key == "colour" else key, value)
            return self

        async def delete(self, **kw):
            guild.roles.remove(self)
        role.edit, role.delete = MethodType(edit, role), MethodType(delete, role)
        return role

    for role in guild.roles:
        patch_role(role)

    async def create_role(*, name, permissions, colour, hoist, mentionable, **kw):
        rid = max(r.id for r in guild.roles) + 1
        role = T.H.Role(guild, rid, name, 1, colour.value)
        role.permissions, role.hoist, role.mentionable = permissions, hoist, mentionable
        guild.roles.append(patch_role(role))
        return role

    async def role_positions(positions, **kw):
        for role, pos in positions.items():
            guild.get_role(role.id).position = pos

    async def fetch_roles():
        return guild.roles

    async def guild_edit(**kw):
        for key, value in kw.items():
            if key != "reason":
                setattr(guild, key, value)
        return guild

    guild.create_role, guild.edit_role_positions = create_role, role_positions
    guild.fetch_roles, guild.edit = fetch_roles, guild_edit
    return create_role


async def main():
    wc, bot, app, _tickets, changelog = await T.make_app()
    guild = bot.guilds[0]
    owner, staff, member = (guild.get_member(i) for i in (1, 11, 13))
    poll, raid, ideas, layouts = Poll(bot), RaidHelper(bot), Ideas(bot), ServerLayout(bot)
    for cog in (poll, raid, ideas, layouts):
        bot._cogs[cog.qualified_name] = cog
        cog._register_dashboard(wc)
    await wc.config.member_portal.set({"1000": True})
    await wc.config.role_perms.set({"1000": {"1101": {"poll": "operate", "raidhelper": "operate", "changelog": "operate"},
                                                   "1102": {"poll": "view", "raidhelper": "view", "changelog": "view"}}})
    client = TestClient(TestServer(app))
    await client.start_server()

    async def page(slug, uid=1, query=""):
        response = await client.get(f"/cogs/{slug}?guild=1000{query}", headers={"X-Test-User": str(uid)})
        html = await response.text()
        assert response.status == 200, html[:500]
        return html, re.search(r"name='csrf_token' value='([^']+)'", html).group(1)

    async def post(slug, token, values, uid=1):
        response = await client.post(f"/cogs/{slug}", headers={"X-Test-User": str(uid)}, allow_redirects=False,
                                     data={"csrf_token": token, "guild": "1000", **values})
        assert response.status in (302, 303, 403), (response.status, await response.text())
        return response.headers.get("Location", "")

    try:
        # Poll: Tippfehler verliert keine Frage/Optionen; fehlende Nachricht wird genau einmal ersetzt.
        _, token = await page("poll", 11)
        values = {"form": "create", "question": "Neue Spielrunde?", "options": "Ja\nNein", "channel": "1001", "duration": "kaputt"}
        assert "err=" in await post("poll", token, values, 11)
        html, _ = await page("poll", 11)
        assert "Neue Spielrunde?" in html and "kaputt" in html and "Ja\nNein" in html
        channel = guild.get_channel(1001)
        channel.forbid.add("send")
        values["duration"] = "2h"
        assert "err=" in await post("poll", token, values, 11)
        saved = next(iter((await poll.config.guild(guild).polls()).values()))
        assert saved["message_id"] is None
        channel.forbid.clear()
        await asyncio.gather(poll.repost_poll(guild, saved["id"]), poll.repost_poll(guild, saved["id"]))
        saved = await poll._get_poll(guild, saved["id"])
        mid = saved["message_id"]
        assert mid and sum(m.id == mid for m in channel._messages.values()) == 1
        await channel._messages[mid].delete()
        await poll.on_raw_message_delete(SimpleNamespace(guild_id=guild.id, message_id=mid))
        await poll.repost_poll(guild, saved["id"])
        assert (await poll._get_poll(guild, saved["id"]))["message_id"] != mid
        key, _, snapshot = await poll.cast_vote(guild, member, saved["id"], 0)
        assert key == "vote_added"
        await poll.refresh_poll_message(guild, saved)  # absichtlich alter Snapshot
        current = await poll._get_poll(guild, saved["id"])
        msg = channel._messages[current["message_id"]]
        assert re.search(r"·\s+1$", msg.view.children[0].label) and "100%" in msg.embeds[0].description
        assert current["votes"]["13"]["choices"] == [0]
        html, view_token = await page("poll", 12)
        await post("poll", view_token, {"form": "action", "action": "repost", "poll_id": saved["id"]}, 12)
        print("Poll: Entwürfe, parallele Reparatur, gelöschte Nachricht, frischer Ergebnisstand, Rechte – OK")

        # RaidHelper: dieselbe Teilnehmerfunktion für Befehle und Web, inklusive Rechte und Bank.
        event = await raid.create_event(guild, game="wow_retail", title="UX Raid", description="",
                                        leader_id=1, channel_id=1001, start_ts=int(time.time()) + 3600)
        _, token = await page("raidhelper", 11, "&event=" + event["id"])
        values = {"form": "action", "action": "roster", "event_id": event["id"], "member_id": "13",
                  "roster_action": "signed", "pick": "krieger|schutz"}
        assert "ok=" in await post("raidhelper", token, values, 11)
        assert (await raid._get_event(guild, event["id"]))["signups"]["13"]["status"] == "signed"
        values["roster_action"] = "bench"
        assert "ok=" in await post("raidhelper", token, values, 11)
        assert (await raid._get_event(guild, event["id"]))["signups"]["13"]["status"] == "bench"
        values["roster_action"] = "remove"
        assert "ok=" in await post("raidhelper", token, values, 11)
        assert "13" not in (await raid._get_event(guild, event["id"]))["signups"]
        try:
            await raid.manage_signup(guild, event["id"], 13, action="bench", actor=member)
            raise AssertionError("Mitglied darf kein Team-Roster ändern")
        except ValueError:
            pass
        print("RaidHelper: Eintragen, Bank, Entfernen und serverseitige Rechte – OK")

        # Changelog: Vorschau postet nichts, Veröffentlichung nutzt dieselbe Logik und echte Person.
        await changelog.config.guild(guild).channel_id.set(1003)
        _, token = await page("changelog", 11)
        values = {"form": "compose", "action": "preview", "title": "Neu <script>", "neu": "Web-Editor", "fixes": ""}
        before = len(guild.get_channel(1003)._messages)
        location = await post("changelog", token, values, 11)
        assert "preview=1" in location and len(guild.get_channel(1003)._messages) == before
        html, _ = await page("changelog", 11, "&preview=1")
        assert "Vorschau – noch nicht veröffentlicht" in html and "&lt;script&gt;" in html
        values["action"] = "publish"
        assert "ok=" in await post("changelog", token, values, 11)
        entries = await changelog.config.guild(guild).entries()
        assert len(entries) == 1 and next(iter(entries.values()))["author_id"] == staff.id
        assert len(guild.get_channel(1003)._messages) == before + 1
        values["title"] = ""
        assert "err=" in await post("changelog", token, values, 11)
        assert len(await changelog.config.guild(guild).entries()) == 1
        print("Changelog: sicherer Entwurf, Vorschau ohne Versand, Veröffentlichen, Validierung – OK")

        # Ideas: erst vorhandene Vorschläge prüfen, kein Thread/Zähler/Cooldown vor Bestätigung.
        forum = IdeasForum.make(guild)
        guild.get_channel = (lambda old: lambda cid: forum if cid == forum.id else old(cid))(guild.get_channel)
        old_lookup = guild.get_channel_or_thread
        guild.get_channel_or_thread = lambda cid: next((t for t in guild.threads if t.id == cid), None) or old_lookup(cid)
        await ideas.config.guild(guild).forum_id.set(forum.id)
        await ideas.config.guild(guild).tag_ids.set({"new": 1})
        await ideas.config.guild(guild).cooldown_minutes.set(0)
        first = await ideas.submit(guild, member, title="Wöchentlicher Spieleabend", description="Zusammen spielen")
        assert first["ok"]
        before_cooldown = await ideas.config.member(member).last_submit()
        duplicate = await ideas.submit(guild, member, title="Wöchentlicher Spieleabend", description="Anderer Termin")
        assert duplicate["key"] == "similar_before_submit" and len(forum.posts) == 1
        assert await ideas.config.guild(guild).counter() == 1
        assert await ideas.config.member(member).last_submit() == before_cooldown
        confirmed = await ideas.submit(guild, member, title="Wöchentlicher Spieleabend", confirm_similar=True)
        assert confirmed["ok"] and len(forum.posts) == 2
        r = await client.get("/me/ideen?guild=1000", headers={"X-Test-User": "13"})
        html = await r.text()
        assert r.status == 200, html[:500]
        token = re.search(r"name='csrf_token' value='([^']+)'", html).group(1)
        r = await client.post("/me/ideen?guild=1000", headers={"X-Test-User": "13"}, allow_redirects=False,
                              data={"csrf_token": token, "form": "submit", "title": "Wöchentlicher Spieleabend"})
        assert "similar=1" in r.headers["Location"] and len(forum.posts) == 2
        r = await client.get("/me/ideen?guild=1000&similar=1", headers={"X-Test-User": "13"})
        html = await r.text()
        choice = re.search(r"name='token' value='([^']+)'", html).group(1)
        assert "Trotzdem neue Idee einreichen" in html
        r = await client.post("/me/ideen?guild=1000", headers={"X-Test-User": "13"}, allow_redirects=False,
                              data={"csrf_token": token, "form": "confirm_similar", "token": choice})
        assert "ok=" in r.headers["Location"] and len(forum.posts) == 3
        r = await client.post("/me/ideen?guild=1000", headers={"X-Test-User": "13"}, allow_redirects=False,
                              data={"csrf_token": token, "form": "confirm_similar", "token": choice})
        assert "err=" in r.headers["Location"] and len(forum.posts) == 3
        view = SimilarIdeasView(ideas, member.id, "de", "Wöchentlicher Spieleabend", "", None)
        replies = []
        await view._continue(T.Inter(replies, guild, staff, guild.get_channel(1001)))
        assert len(forum.posts) == 3
        await view._continue(T.Inter(replies, guild, member, guild.get_channel(1001)))
        await view._continue(T.Inter(replies, guild, member, guild.get_channel(1001)))
        assert len(forum.posts) == 4
        assert (await ideas.set_status(guild, 1, "planned", by=staff, notify=False))[0] == "status_set"
        merge_result = await ideas.merge(guild, 2, 1, by=staff)
        assert merge_result[0] == "merged_ok", merge_result
        stored_ideas = await ideas.config.guild(guild).ideas()
        assert stored_ideas["1"]["status"] == "planned" and stored_ideas["2"]["merged_into"] == 1
        print("Ideas: Prüfung vor Erstellung, bestehende Links, bewusste Fortsetzung, Einmal-Token, Discord-Rechte – OK")

        # ServerLayout: echte destructive Anwendung + automatisch gesicherten Ausgangsstand zurückholen.
        create_role = setup_layout_world(guild)
        base, _ = await layouts.save_layout(guild, "Vorher", ["roles", "channels", "settings"], creator_id=owner.id)
        added_role = await create_role(name="Temporäre Rolle", permissions=discord.Permissions.none(), colour=discord.Colour(0), hoist=False, mentionable=False)
        added_channel = await guild.create_text_channel("temporaerer-kanal")
        await added_channel.send("Diese Nachricht gehört zum Test")
        _, plan = await layouts.preview(guild, base["id"], "exact", ["roles", "channels", "settings"])
        assert plan["counts"]["delete"] >= 2
        try:
            await layouts.start_load(guild, base["id"], mode="exact", parts=plan["parts"], user=owner, expected_hash="stale")
            raise AssertionError("Veraltete Vorschau muss blockieren")
        except LoadError as exc:
            assert exc.key == "changed"
        real_save = layouts.save_layout

        async def failed_backup(*args, **kwargs):
            raise OSError("Sicherungsdatenträger nicht verfügbar")

        layouts.save_layout = failed_backup
        failed = await layouts.start_load(guild, base["id"], mode="exact", parts=plan["parts"], user=owner, expected_hash=plan["hash"])
        await failed.task
        assert failed.status == "failed" and guild.get_role(added_role.id) is not None and guild.get_channel(added_channel.id) is not None
        layouts.save_layout = real_save
        job = await layouts.start_load(guild, base["id"], mode="exact", parts=plan["parts"], user=owner, expected_hash=plan["hash"])
        await job.task
        assert job.status == "done" and job.counts["errors"] == 0, job.to_report()
        assert guild.get_role(added_role.id) is None and guild.get_channel(added_channel.id) is None
        assert job.backup_id
        html, token = await page("serverlayout")
        assert "Sicherung prüfen / wiederherstellen" in html and job.backup_id in html
        location = await post("serverlayout", token, {"form": "apply", "layout": job.backup_id, "mode": "exact",
                              "parts": "roles,channels,settings", "confirm_name": guild.name})
        assert "err=" in location and not layouts.running(guild.id)
        _, restore = await layouts.preview(guild, job.backup_id, "exact", ["roles", "channels", "settings"])
        recovery = await layouts.start_load(guild, job.backup_id, mode="exact", parts=restore["parts"], user=owner, expected_hash=restore["hash"])
        await recovery.task
        assert recovery.status == "done" and recovery.counts["errors"] == 0, recovery.to_report()
        assert any(role.name == "Temporäre Rolle" for role in guild.roles)
        restored = next(ch for ch in guild.text_channels if ch.name == "temporaerer-kanal")
        assert not restored._messages and restored.id != added_channel.id
        assert recovery.backup_id != job.backup_id
        print("ServerLayout: Vorschau-Hash, echte Löschung, automatische Sicherung, geprüfte Wiederherstellung leerer Kanäle – OK")
    finally:
        await client.close()
        await layouts.cog_unload()
    print("ALLE WORKFLOW-UX-TESTS OK")


asyncio.run(main())
