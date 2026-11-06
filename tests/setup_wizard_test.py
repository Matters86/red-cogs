"""Gemeinsamer Assistent: echte Formulare, Rechte, Vorschau, Rücknahme und Testversand."""
import asyncio
from html.parser import HTMLParser

import tc_harness as T
import wl_harness as W
import discord
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from multidict import MultiDict

from rc.webcore import setup_wizard as S
from rc.welcome.welcome import Welcome
from rc.autorole.autorole import Autorole
from rc.poll.poll import Poll
from rc.raidhelper.raidhelper import RaidHelper
from rc.organigram.organigram import Organigram
from rc.sticky.sticky import Sticky
from rc.giveaways.giveaways import Giveaways
from rc.scheduler.scheduler import Scheduler


class Forms(HTMLParser):
    """Die wirklich gerenderten Browser-Werte weiterreichen, auch Mehrfachauswahl."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.forms, self.current, self.select, self.textarea = [], None, None, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = MultiDict()
            self.forms.append(self.current)
        elif self.current is not None:
            if tag == "input" and attrs.get("name"):
                if attrs.get("type") not in {"checkbox", "radio"} or "checked" in attrs:
                    self.current.add(attrs["name"], attrs.get("value", "on"))
            elif tag == "select":
                self.select = [attrs["name"], "multiple" in attrs, [], []]
            elif tag == "option" and self.select is not None:
                value = attrs.get("value", "")
                self.select[2].append(value)
                if "selected" in attrs:
                    self.select[3].append(value)
            elif tag == "textarea":
                self.textarea = [attrs["name"], ""]

    def handle_data(self, text):
        if self.textarea is not None:
            self.textarea[1] += text

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None
        elif tag == "select" and self.select is not None:
            name, multiple, options, selected = self.select
            for value in selected or ([] if multiple else options[:1]):
                self.current.add(name, value)
            self.select = None
        elif tag == "textarea" and self.textarea is not None:
            self.current.add(*self.textarea)
            self.textarea = None

    def action(self, action):
        return next(f for f in self.forms if f.get("action") == action)


def updated(form, **values):
    result = MultiDict(form)
    for key, value in values.items():
        result.popall(key, None)
        if value is not None:
            for item in value if isinstance(value, list) else [value]:
                result.add(key, str(item))
    return result


async def main():
    wc, bot, app, tickets, _ = await T.make_app()
    W.patch_members(bot)
    guild = bot.guilds[0]
    for server in bot.guilds:
        for role in server.roles:
            role.permissions = discord.Permissions.none()
        for category in server.categories:
            category.permissions_for = lambda _: discord.Permissions.all()
    cogs = {"tickets": tickets}
    for cls in (Welcome, Autorole, Poll, RaidHelper, Organigram, Sticky, Giveaways, Scheduler):
        cog = cls(bot)
        bot._cogs[cls.__name__] = cog
        cog._register_dashboard(wc)
        cogs[next(a.slug for a in S.ADAPTERS if a.cog == cls.__name__)] = cog
    # Equal/higher support/display references are allowed. Automatic grants have
    # a distinct stricter hierarchy check.
    role_perms = {"1000": {"1101": dict.fromkeys(cogs, "edit"), "1102": dict.fromkeys(cogs, "view"),
                           "1104": dict.fromkeys(cogs, "operate"), "1103": {"poll": "edit", "welcome": "view"}}}
    await wc.config.role_perms.set(role_perms)
    guild.members.append(T.H.Member(guild, 16, "Nur Umfragen", [guild.get_role(1103)]))
    oldtickets = {"73": {"status": "open", "owner": 15, "channel_id": 1002}}
    await tickets.config.guild(guild).tickets.set(oldtickets)
    await tickets.config.guild(guild).counter.set(73)
    await cogs["organigram"].config.guild(guild).charts.set({"existing": {"name": "Vorhanden", "nodes": {}, "posts": []}})
    client = TestClient(TestServer(app))
    await client.start_server()

    async def get(uid=1, query=None):
        response = await client.get("/setup", params={"guild": "1000", **(query or {})}, headers={"X-Test-User": str(uid)})
        return response, await response.text()

    async def page(uid=1, step="modules"):
        response, html = await get(uid, {"step": step})
        assert response.status == 200, html[:500]
        return html

    async def post(form, uid=1):
        response = await client.post("/setup", data=form, headers={"X-Test-User": str(uid)}, allow_redirects=False)
        return response, await response.text()

    async def choose(slugs, uid=1):
        form = Forms(await page(uid)).action("choose")
        response, body = await post(updated(form, modules=slugs), uid)
        assert response.status == 302 and "configure" in response.headers.get("Location", ""), body
        return Forms(await page(uid, "configure")).action("review")

    async def review(form, uid=1):
        response, body = await post(form, uid)
        assert response.status == 302 and "review" in response.headers.get("Location", ""), body[:1000]
        html = await page(uid, "review")
        return updated(Forms(html).action("apply"), confirm="on"), html

    async def configs():
        return {slug: await cog.config.guild(guild).all() for slug, cog in cogs.items()}

    try:
        response = await client.get("/setup")
        assert response.status == 403
        html = await page()
        assert "Gemeinsame Einrichtung" in html and "modules' value='tickets'" in html
        assert "modules' value='scheduler'" in html and "modules' value='changelog'" not in html
        assert "Weitere geladene Module" in html and "/cogs/changelog?guild=1000" in html
        for uid in (12, 13, 21, 99):
            response, _ = await get(uid)
            assert response.status == 403, uid
        # A page-specific editor cannot configure another module, even though
        # the same guild is accessible via its one allowed module.
        html = await page(16)
        choose_form = Forms(html).action("choose")
        assert "modules' value='poll'" in html and "modules' value='welcome'" not in html
        response, _ = await post(updated(choose_form, modules="welcome"), 16)
        assert response.status == 403
        response, _ = await post(updated(choose_form, guild="2000", modules="poll"), 16)
        assert response.status == 403
        for uid in (12, 13):
            response, _ = await post(updated(choose_form, modules="poll"), uid)
            assert response.status == 403
        response, _ = await post(updated(choose_form, csrf_token="forged", modules="poll"), 16)
        assert response.status == 400
        response, _ = await post(updated(choose_form, modules="unsupported"), 16)
        assert response.status == 400
        print("Server, Modul-Auswahl, anonyme/Ansehen/Bedienen/Bearbeiten-Rechte und CSRF – OK")

        initial = await configs()
        log_before, roles_before = len(T.L.LOG), len(T.ROLE_LOG)
        form = await choose(list(cogs))
        values = {"tickets.support_roles": [1101], "tickets.category_open": 1090, "tickets.owner_role": 1104,
                  "welcome.welcome_enabled": "on", "welcome.welcome_channel": 1001,
                  "welcome.welcome_text": "Hallo {name} <script>gefährlich</script>",
                  "autorole.join_roles": [1104], "raidhelper.signup_channel": 1003,
                  "organigram.name": "Neues Team", "organigram.roles": [1101, 1102],
                  "sticky.channel": 1002, "sticky.text": "Bitte zuerst die Regeln lesen.", "scheduler.timezone": "UTC"}
        apply_form, html = await review(updated(form, **values))
        assert "Nach Übernahme" in html and "Geprüfte Bot-Rechte" in html and "Kanäle verwalten" in html
        assert "Hallo {name} &lt;script&gt;gefährlich&lt;/script&gt;" in html and "<script>gefährlich" not in html
        assert "Begrüßung bei zukünftigen Beitritten aktiv" in html and "Aktiv" in html
        assert "Neue Vorlage: <b>Deaktiviert</b>" in html and "Unverändert" in html
        assert await configs() == initial
        assert (len(T.L.LOG), len(T.ROLE_LOG)) == (log_before, roles_before)
        # Session- and user-bound: a second browser has another CSRF token;
        # copying the complete first form still cannot take over that draft.
        another = TestClient(TestServer(app))
        await another.start_server()
        try:
            response = await another.get("/setup?guild=1000", headers={"X-Test-User": "1"})
            other_token = Forms(await response.text()).action("choose")["csrf_token"]
            response = await another.post("/setup", data=updated(apply_form, csrf_token=other_token), headers={"X-Test-User": "1"})
            assert response.status == 400
        finally:
            await another.close()
        response, _ = await post(apply_form, 11)
        assert response.status == 400
        for bad in (updated(apply_form, review="forged"), updated(apply_form, review=None), updated(apply_form, confirm=None)):
            response, _ = await post(bad)
            assert response.status == 400
        assert await configs() == initial
        response, _ = await post(apply_form)
        assert response.status == 302 and "done" in response.headers["Location"]
        after = await configs()
        assert after["tickets"]["support_roles"] == [1101] and after["tickets"]["owner_role"] == 1104
        assert after["tickets"]["tickets"] == oldtickets and after["tickets"]["counter"] == 73
        assert after["welcome"]["welcome_text"] == values["welcome.welcome_text"]
        charts = after["organigram"]["charts"]
        assert "existing" in charts and len(charts) == 2
        new_chart = next(v for k, v in charts.items() if k != "existing")
        assert new_chart["draft"] and not new_chart["posts"] and len(new_chart["nodes"]) == 2
        sticky = after["sticky"]["stickies"]["1002"]
        assert sticky["enabled"] is False and sticky["message_id"] is None
        assert not after["scheduler"]["entries"] and not after["giveaways"]["giveaways"]
        assert (len(T.L.LOG), len(T.ROLE_LOG)) == (log_before, roles_before)
        # Retries and simultaneous duplicate submits never create another chart.
        results = await asyncio.gather(post(apply_form), post(apply_form))
        assert all(r.status == 302 for r, _ in results)
        assert await configs() == after
        print("Echte Mehrmodul-Vorschau ohne Versand, exakte Übernahme, Erhalt bestehender Daten und idempotente Wiederholung – OK")

        html = await page(step="done")
        assert "5 · Vorschau und Tests" in html and "Testnachricht senden" in html
        test_form = Forms(html).action("test_welcome")
        response, _ = await post(updated(test_form, text="UNERWÜNSCHTER TEXT", channel="1004"))
        assert response.status == 302 and "ok=" in response.headers["Location"]
        sent = [entry for entry in T.L.LOG[log_before:] if entry[0] == "send"]
        assert len(sent) == 1 and "UNERWÜNSCHTER TEXT" not in str(sent)
        assert sent[0][1] == 1001 and "Hallo Matters86" in str(sent)
        assert await configs() == after
        response, _ = await post(test_form)
        assert response.status == 400 and len([e for e in T.L.LOG[log_before:] if e[0] == "send"]) == 1
        html = await page(step="done")
        test_form = Forms(html).action("test_welcome")
        await cogs["welcome"].config.guild(guild).welcome_channel.set(1004)
        response, _ = await post(test_form)
        assert response.status == 400
        await cogs["welcome"].config.guild(guild).welcome_channel.set(1001)
        print("Getrennter ausdrücklicher Begrüßungstest: gespeicherte Werte, keine Erwähnungen, Schutz vor Wiederholung und veraltetem Ziel – OK")

        # References may equal/exceed the editor's role; grants may not.
        form = await choose(["tickets", "organigram"], 11)
        apply_form, _ = await review(updated(form, **{"tickets.support_roles": 1102, "tickets.owner_role": "", "organigram.name": "Team von Lena", "organigram.roles": 1102}), 11)
        response, _ = await post(apply_form, 11)
        assert response.status == 302
        form = await choose(["autorole"], 11)
        response, body = await post(updated(form, **{"autorole.join_roles": 1102}), 11)
        assert response.status == 200 and "Du darfst diese automatische Rolle nicht vergeben" in body
        assert "autorole.join_roles" in body
        for bad in (2101, 1000, 1999, "x"):
            response, body = await post(updated(form, **{"autorole.join_roles": bad}), 11)
            assert response.status == 200
            assert Forms(body).action("review")
        form = await choose(["welcome"])
        for channel in (2001, 1050, "x"):
            response, body = await post(updated(form, **{"welcome.welcome_channel": channel, "welcome.welcome_text": "Text bleibt <b>erhalten</b>"}))
            assert response.status == 200 and "Text bleibt &lt;b&gt;erhalten&lt;/b&gt;" in body
        response, body = await post(updated(form, **{"welcome.welcome_text": "x" * 2001}))
        assert response.status == 200 and "Höchstens 2000 Zeichen" in body
        form = await choose(["poll", "welcome"])
        response, body = await post(updated(form, **{"poll.max_options": 1, "welcome.welcome_text": "ZWEITES MODUL ERHALTEN"}))
        assert response.status == 200 and "2 bis 25" in body and "ZWEITES MODUL ERHALTEN" in body
        print("Rollenzuweisung versus Verweis, fremde IDs, falsche Kanaltypen, Limits und mehrmodulige Fehler-Erhaltung – OK")

        # Current rights, bot permissions, and touched config are checked again
        # after the review; unrelated config edits are preserved and permitted.
        form = await choose(["welcome"], 11)
        apply_form, _ = await review(updated(form, **{"welcome.welcome_text": "Lenas Änderung"}), 11)
        await wc.config.role_perms.set({"1000": {"1101": {"poll": "edit", "welcome": "view"}}})
        response, _ = await post(apply_form, 11)
        assert response.status == 403 and (await cogs["welcome"].config.guild(guild).welcome_text()) != "Lenas Änderung"
        await wc.config.role_perms.set(role_perms)
        form = await choose(["welcome"])
        apply_form, _ = await review(updated(form, **{"welcome.welcome_text": "Neue Änderung"}))
        channel = guild.get_channel(1001)
        original_perms = channel.permissions_for
        denied = discord.Permissions.all(); denied.send_messages = False
        channel.permissions_for = lambda _: denied
        response, body = await post(apply_form)
        assert response.status == 200 and "Nachrichten senden" in body
        channel.permissions_for = original_perms
        assert (await cogs["welcome"].config.guild(guild).welcome_text()) != "Neue Änderung"
        form = Forms(body).action("review")
        apply_form, _ = await review(form)
        await cogs["welcome"].config.guild(guild).welcome_text.set("Zwischenzeitlich geändert")
        response, body = await post(apply_form)
        assert response.status == 200 and "seit der Vorschau geändert" in body
        assert await cogs["welcome"].config.guild(guild).welcome_text() == "Zwischenzeitlich geändert"
        form = Forms(body).action("review")
        apply_form, _ = await review(form)
        await cogs["welcome"].config.guild(guild).leave_text.set("Unabhängige Änderung")
        response, _ = await post(apply_form)
        assert response.status == 302 and await cogs["welcome"].config.guild(guild).leave_text() == "Unabhängige Änderung"
        print("Rechteentzug, geänderte Bot-Rechte, veraltete Vorschau und Erhalt unabhängiger Änderungen – OK")

        form = await choose(["poll", "welcome"])
        apply_form, _ = await review(updated(form, **{"poll.allow_create": "everyone", "welcome.welcome_text": "Darf nicht übrig bleiben"}))
        before_failure = await configs()
        original_write = S._write_value
        calls = []

        async def fail_after_write(cog, target, key, value):
            calls.append((cog.qualified_name, key))
            await original_write(cog, target, key, value)
            if key == "welcome_text" and value == "Darf nicht übrig bleiben":
                raise RuntimeError("Simulierter Fehler nach erfolgreicher Speicherung")

        S._write_value = fail_after_write
        try:
            response, body = await post(apply_form)
        finally:
            S._write_value = original_write
        assert response.status == 200 and "zurückgesetzt" in body
        assert await configs() == before_failure and len(calls) >= 4
        # The draft can be reviewed and applied after rollback.
        apply_form, _ = await review(Forms(body).action("review"))
        response, _ = await post(apply_form)
        assert response.status == 302
        print("Fehler im zweiten Modul nach erfolgreichem Schreiben: alle eigenen Änderungen zurückgenommen, Entwurf erneut nutzbar – OK")

        form = await choose(["welcome"], 11)
        apply_form, _ = await review(updated(form, **{"welcome.welcome_enabled": None, "welcome.welcome_text": "RECHTE ENTZOGEN"}), 11)
        before_revoke = await configs()

        async def revoke_after_first(cog, target, key, value):
            await original_write(cog, target, key, value)
            if key == "welcome_enabled" and value is False:
                await wc.config.role_perms.set({"1000": {"1101": {"poll": "edit", "welcome": "view"}}})

        S._write_value = revoke_after_first
        try:
            response, body = await post(apply_form, 11)
            assert response.status == 403 or (response.status == 200 and "zurückgesetzt" in body)
            assert await configs() == before_revoke
        finally:
            S._write_value = original_write
            await wc.config.role_perms.set(role_perms)

        form = await choose(["welcome"])
        apply_form, _ = await review(updated(form, **{"welcome.welcome_text": "NEU GELADEN"}))
        before_reload = await configs()
        original_validate = S._validate_fields
        old_welcome = cogs["welcome"]
        replaced = False

        async def replace_during_validation(*args, **kwargs):
            nonlocal replaced
            checks = await original_validate(*args, **kwargs)
            if not replaced:
                replaced = True
                replacement = Welcome(bot)
                bot._cogs["Welcome"] = replacement
                replacement._register_dashboard(wc)
            return checks

        S._validate_fields = replace_during_validation
        try:
            response, body = await post(apply_form)
            assert response.status == 200 and "neu geladen" in body
            assert await configs() == before_reload
        finally:
            S._validate_fields = original_validate
            bot._cogs["Welcome"] = old_welcome
            old_welcome._register_dashboard(wc)
        print("Rechteentzug zwischen zwei Schlüsseln und Cog-Austausch während Prüfung: keine Teiländerung – OK")

        form = await choose(["poll", "welcome"])
        await review(updated(form, **{"poll.allow_create": "manager", "welcome.welcome_text": "ABBRUCH"}))
        before_cancel = await configs()
        draft = next(d for k, d in wc._setup_drafts.items() if k[0] == 1 and k[2] == 1000)
        second_write, rollback_started, release_rollback = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def pause_second(cog, target, key, value):
            if key == "welcome_text" and value == "ABBRUCH":
                second_write.set()
                await asyncio.Event().wait()
            if key == "allow_create" and value == "everyone":
                rollback_started.set()
                await release_rollback.wait()
            await original_write(cog, target, key, value)

        S._write_value = pause_second
        request = make_mocked_request("POST", "/setup", headers={"X-Test-User": "1"}, app=app)
        pending = asyncio.create_task(S._apply(wc, request, guild, draft))
        try:
            await asyncio.wait_for(second_write.wait(), 5)
            assert await cogs["poll"].config.guild(guild).allow_create() == "manager"
            pending.cancel()
            await asyncio.wait_for(rollback_started.wait(), 5)
            pending.cancel()  # A second cancellation must not interrupt rollback.
            release_rollback.set()
            try:
                await pending
                raise AssertionError("Abbruch wurde verschluckt")
            except asyncio.CancelledError:
                pass
            assert await configs() == before_cancel and not draft["applied"]
        finally:
            S._write_value = original_write
            release_rollback.set()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        print("Abbruch während der zweiten Speicherung, erneuter Abbruch während Rücknahme: vollständig zurückgesetzt – OK")

        form = await choose(["welcome"])
        draft = next(d for k, d in wc._setup_drafts.items() if k[0] == 1 and k[2] == 1000)
        draft["expires"] = 0
        response, _ = await post(form)
        assert response.status == 400
        await choose(["poll"], 11)
        await choose(["welcome"])
        S.discard_user(wc, 11)
        assert not any(k[0] == 11 for k in wc._setup_drafts)
        assert any(k[0] == 1 for k in wc._setup_drafts)
        print("Ablauf und Datenschutz-Löschung sind sitzungs-/nutzerbezogen – OK")
        print("setup_wizard_test: PASS")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
