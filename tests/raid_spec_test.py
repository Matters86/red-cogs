"""Raid-Specs: gemerkte Auswahl bestätigen, Wechsel und frische Anmeldeprüfungen.

Die Interaktions-Doubles entsprechen live_test, erfassen zusätzlich die echte View
und prüfen, dass eine Antwort vor dem Aktualisieren der Raid-Nachricht erfolgt.
"""
import asyncio
import copy
import sys
import time
import types

import rc_harness as R
import discord

from rc.raidhelper import games
from rc.raidhelper import views as V
from rc.raidhelper.strings import t


class Resp:
    def __init__(self, trace):
        self.sent, self.captured, self.trace = [], [], trace
        self._done = False

    def is_done(self):
        return self._done

    async def send_message(self, content=None, *, ephemeral=False, **kwargs):
        assert not self._done, "Interaktion darf nur einmal beantwortet werden"
        R.L.validate_message(content, [], kwargs.get("view"), [])
        self._done = True
        self.sent.append(("send", content, ephemeral))
        self.captured.append(kwargs)
        self.trace.append("response")

    async def edit_message(self, *, content=None, **kwargs):
        assert not self._done, "Interaktion darf nur einmal beantwortet werden"
        R.L.validate_message(content, [], kwargs.get("view"), [])
        self._done = True
        self.sent.append(("edit", content, True))
        self.captured.append(kwargs)
        self.trace.append("response")


class Followup:
    def __init__(self, resp):
        self.resp = resp

    async def send(self, content=None, *, ephemeral=False, **kwargs):
        self.resp.sent.append(("followup", content, ephemeral))
        self.resp.captured.append(kwargs)


def interaction(guild, user, custom_id, values=None):
    trace = []
    resp = Resp(trace)
    return types.SimpleNamespace(
        type=discord.InteractionType.component, guild=guild, user=user,
        response=resp, followup=Followup(resp), trace=trace,
        data={"custom_id": custom_id, **({"values": values} if values is not None else {})},
        channel=None, message=None,
    )


async def main():
    wc, bot, _app, rh = await R.make_app(seed=False)
    guild = bot.guilds[0]
    user, other = guild.get_member(11), guild.get_member(12)
    now = int(time.time())
    conf = rh.config.guild(guild)
    checks = 0

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
        print("OK   " + message)

    async def create(**changes):
        values = dict(game="wow_retail", title="Spec-Regression", description=None,
                      leader_id=1, channel_id=guild.id + 1, start_ts=now + 86400,
                      max_signups=20, role_limits={})
        values.update(changes)
        return await rh.create_event(guild, **values)

    def buttons(view):
        return [child for child in view.children if isinstance(child, discord.ui.Button)]

    def select(view):
        return next(child for child in view.children if isinstance(child, discord.ui.Select))

    def confirmation(view):
        result = [button for button in buttons(view) if button.custom_id.startswith("rh:confirm:")]
        assert len(result) == 1, "Genau ein Bestätigungsbutton für eine bekannte Spec"
        return result[0]

    async def pick(event, class_id="krieger"):
        inter = interaction(guild, user, f"rh:cls:{event['id']}", [class_id])
        await rh.on_interaction(inter)
        assert len(inter.response.sent) == 1 and inter.response.sent[0][2] is True
        view = inter.response.captured[0].get("view")
        assert isinstance(view, discord.ui.View)
        R.L.validate_view(view)
        return view

    async def act(custom_id, values=None):
        inter = interaction(guild, user, custom_id, values)
        original = rh.refresh_event_message

        async def tracked_refresh(target, snapshot):
            assert inter.response.is_done(), "Discord-Antwort muss vor Raid-Refresh erfolgen"
            inter.trace.append("refresh")
            return await original(target, snapshot)

        rh.refresh_event_message = tracked_refresh
        try:
            await rh.on_interaction(inter)
        finally:
            rh.refresh_event_message = original
        assert len(inter.response.sent) == 1 and inter.response.sent[0][0] == "edit"
        assert inter.response.captured[0].get("view", "missing") is None, "Auswahl-Controls entfernen"
        assert inter.trace[0] == "response"
        return inter

    async def denied(custom_id, key, values=None, **kwargs):
        before = copy.deepcopy(await conf.events())
        memory = copy.deepcopy(await rh.config.user_from_id(user.id).remember())
        inter = await act(custom_id, values)
        assert inter.response.sent[0][1] == t("de", key, **kwargs), inter.response.sent
        assert inter.trace == ["response"], "Abgelehnte Anmeldung aktualisiert kein Roster"
        assert await conf.events() == before, "Abgelehnte Anmeldung verändert keine Event-Daten"
        assert await rh.config.user_from_id(user.id).remember() == memory, "Keine ungültige Spec merken"

    try:
        # Echte Discord-Views: Bestätigung ausschließlich für vorhandene Vorauswahl.
        for default in (None, "entfernte_spec"):
            view = V.build_spec_view("rh-ui", "krieger", "wow_retail", "de", default_spec=default)
            R.L.validate_view(view)
            check(not buttons(view) and not any(option.default for option in select(view).options),
                  f"Keine Bestätigung ohne gültige bekannte Spec ({default!r})")
        for game_id in ("wow_retail", "wow_classic", "wow_wotlk"):
            view = V.build_spec_view("rh-ui", "krieger", game_id, "de", default_spec="furor")
            button = confirmation(view)
            check(button.custom_id == "rh:confirm:rh-ui:krieger:furor"
                  and button.label == "Furor bestätigen"
                  and button.style == discord.ButtonStyle.success
                  and [option.value for option in select(view).options if option.default] == ["furor"],
                  f"Gültige bekannte Spec bleibt auswählbar und direkt bestätigbar ({game_id})")
            R.L.validate_view(view)

        # Der ursprüngliche Fehler: kein Select-Change notwendig, Button genügt.
        await rh._remember_spec(user.id, "wow_retail", "krieger", "furor")
        event = await create()
        view = await pick(event)
        check(not (await conf.events())[event["id"]]["signups"], "Vorauswahl meldet noch niemanden an")
        inter = await act(confirmation(view).custom_id)
        signup = (await conf.events())[event["id"]]["signups"][str(user.id)]
        check(signup["class"] == "krieger" and signup["spec"] == "furor" and signup["role"] == "mdps"
              and signup["status"] == "signed" and "Angemeldet" in inter.response.sent[0][1]
              and inter.trace == ["response", "refresh"],
              "Gemerkte Spec ohne Dropdownänderung bestätigt, Controls entfernt, Antwort vor Refresh")

        # Wechsel bleibt ein einziger Dropdown-Klick, Datum und Anmeldung bleiben erhalten.
        original_at = signup["at"]
        view = await pick(event)
        inter = await act(select(view).custom_id, ["waffen"])
        signup = (await conf.events())[event["id"]]["signups"][str(user.id)]
        check(signup["spec"] == "waffen" and signup["at"] == original_at
              and "Spec geändert" in inter.response.sent[0][1], "Dropdownwechsel bleibt möglich und erhält Anmeldezeit")

        # Wiederbestätigung darf bei gefülltem Roster nicht gegen eigene Limits laufen.
        async with conf.events() as events:
            events[event["id"]]["max_signups"] = 1
            events[event["id"]]["role_limits"] = {"mdps": 1}
        view = await pick(event)
        await act(confirmation(view).custom_id)
        current = (await conf.events())[event["id"]]["signups"]
        check(len(current) == 1 and current[str(user.id)]["at"] == original_at
              and current[str(user.id)]["spec"] == "waffen",
              "Eigene Wiederbestätigung bei voller Rolle/vollem Roster ohne Duplikat oder Zeitverlust")

        # Payload bestätigt den angezeigten Stand, keine inzwischen anderweitig gemerkte Spec.
        snap_event = await create()
        await rh._remember_spec(user.id, "wow_retail", "krieger", "furor")
        snap_view = await pick(snap_event)
        await rh._remember_spec(user.id, "wow_retail", "krieger", "waffen")
        await act(confirmation(snap_view).custom_id)
        check((await conf.events())[snap_event["id"]]["signups"][str(user.id)]["spec"] == "furor"
              and (await rh.config.user_from_id(user.id).remember())["wow_retail:krieger"] == "furor",
              "Button bestätigt die sichtbare Spec trotz später geänderter Erinnerung")

        await rh._remember_spec(user.id, "wow_classic", "krieger", "waffen")
        classic = await create(game="wow_classic")
        check(confirmation(await pick(classic)).custom_id.endswith(":krieger:waffen")
              and confirmation(await pick(snap_event)).custom_id.endswith(":krieger:furor"),
              "Spec-Erinnerungen bleiben pro Spiel getrennt")
        await rh._remember_spec(user.id, "wow_wotlk", "krieger", "entfernte_spec")
        wotlk = await create(game="wow_wotlk")
        check(not buttons(await pick(wotlk)), "Veraltete Erinnerung erzeugt keinen Bestätigungsbutton")

        # Zustände werden beim Klick frisch geprüft, nicht nur beim Öffnen der Auswahl.
        for name, key in (("closed", "signup_closed"), ("deadline", "deadline_passed"), ("deleted", "unknown_event")):
            blocked = await create()
            cid = confirmation(await pick(blocked)).custom_id
            async with conf.events() as events:
                if name == "closed":
                    events[blocked["id"]]["closed"] = True
                elif name == "deadline":
                    events[blocked["id"]]["deadline_ts"] = now - 10
                else:
                    del events[blocked["id"]]
            await denied(cid, key)
            check(True, f"Offener Bestätigungsdialog nach {name} sicher abgelehnt")

        full = await create(max_signups=1)
        cid = confirmation(await pick(full)).custom_id
        result = await rh.set_signup(guild, full["id"], other, class_id="krieger", spec_id="furor", validate=True)
        assert result[0]
        await denied(cid, "event_full", max=1)
        check(True, "Zwischenzeitlich volles Event beim Bestätigen ohne Mutation abgelehnt")

        rolefull = await create(role_limits={"mdps": 1})
        cid = confirmation(await pick(rolefull)).custom_id
        result = await rh.set_signup(guild, rolefull["id"], other, class_id="krieger", spec_id="furor", validate=True)
        assert result[0]
        await denied(cid, "role_full", label=games.role_meta("wow_retail", "mdps")["label"], max=1)
        check(True, "Zwischenzeitlich volle Rolle beim Bestätigen ohne Mutation abgelehnt")

        # Discord-Payloads sind keine Vertrauensquelle: beide Wege prüfen aktuelle Paarung.
        invalid = await create()
        for class_id, spec_id in (("krieger", "keine_spec"), ("keine_klasse", "furor"), ("krieger", "frost")):
            await denied(f"rh:confirm:{invalid['id']}:{class_id}:{spec_id}", "unknown_pick")
            await denied(f"rh:spec:{invalid['id']}:{class_id}", "unknown_pick", [spec_id])
        check(True, "Manipulierte Klasse/Spec für Button und Dropdown ohne Datenänderung abgelehnt")

        changed_game = await create()
        await rh._remember_spec(user.id, "wow_retail", "daemonenjaeger", "verwuestung")
        cid = confirmation(await pick(changed_game, "daemonenjaeger")).custom_id
        async with conf.events() as events:
            events[changed_game["id"]]["game"] = "wow_classic"
        await denied(cid, "unknown_pick")
        check(True, "Nach Spielwechsel ungültig gewordene bekannte Spec wird erneut geprüft")
    finally:
        await wc.cog_unload()
    print(f"\n{checks} Raid-Spec-Prüfungen bestanden.")
    return True


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
