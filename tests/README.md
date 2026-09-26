# Tests

Automatische Prüfungen für alle Cogs – ohne Discord-Verbindung, ohne Browser, ohne festen Port.
Die Suiten starten den **echten WebCore** (aiohttp) und die **echten Cogs** mit echter Red-`Config`
(JSON-Treiber in einem Temp-Ordner) und ersetzen nur Discord selbst durch Fakes.
Sie laufen bei jedem Push und Pull-Request automatisch auf GitHub (`.github/workflows/tests.yml`).

## Lokal ausführen

Voraussetzung: **Python 3.11** (Red 3.5 unterstützt kein 3.12).

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt      # = Red-DiscordBot + pyflakes + Cog-Anforderungen

python tests/run_all.py                    # alle Suiten (oder: python -m tests)
python tests/run_all.py wc pr              # nur Suiten, deren Name so beginnt
python tests/run_all.py -v                 # Ausgabe jeder Suite zeigen
python tests/wc_test.py                    # eine Suite direkt

python -m compileall -q .                  # wie in der CI
python -m pyflakes .
```

`tests/requirements.txt` enthält neben `Red-DiscordBot` und `pyflakes` die `requirements` aus den
`info.json` der Cogs (Pillow, tzdata, aiohttp-jinja2, aiohttp-session, cryptography).
`run_all.py` meldet, wenn dort eine Anforderung fehlt.

`run_all.py` startet jede Suite in einem eigenen Prozess, zeigt Laufzeit und Ergebnis und endet
mit Exit-Code ≠ 0, sobald eine Suite scheitert. Bei Fehlern wird die Ausgabe der Suite gezeigt.
Vorher prüft es außerdem: jede Test-Datei ist eingetragen, jeder Cog wird von mindestens einer
Test-Datei importiert, alle Cog-Anforderungen stehen in `requirements.txt`.

Die echte Red-Konfiguration des Rechners wird **nicht** angefasst: `bootstrap.py` legt eine eigene
Red-Instanz im System-Temp an und löscht sie am Ende wieder.

## Suiten

| Suite | prüft |
|---|---|
| `realred.py` | Echtes Red: alle Cogs importierbar (`setup()`), `info.json` gültig, `identifier` eindeutig + in CONVENTIONS.md, keine Namenskollision mit Python-Standardmodulen/Red-Core-Cogs, Config-Locks/Nebenläufigkeit |
| `wc_test.py` | WebCore: Login, Server-Wechsler, Rollen-Rechte-Matrix, Nur-Ansicht, Schutz vor Selbst-Hochstufung, Audit-Log, Zugriffsmodus `admin` |
| `wcm_test.py` | WebCore: Mitglieder-Bereich `/me` (Portal-Schalter, fremde Server, CSRF, Rate-Limit), öffentliche API (CORS, Cache, 429, Fehler ohne Details), Audit-Kanal, Befehle |
| `vis_test.py` | WebCore: `visible()`-Callback blendet Mitglieder-Seiten je Server aus |
| `live_test.py` | Posten/Bearbeiten/Löschen aus den Dashboards mit Discord-Limits und fehlenden Rechten (tickets, poll, raidhelper, sticky, changelog, autorole, organigram, guard, autoroom) |
| `rc_functest.py` | raidhelper: Events im Dashboard anlegen/bearbeiten, Validierung, Entwurf nach Fehler, Rechte, `raid`-Befehle |
| `rm_functest.py` | raidhelper: Mitgliederseite `/me/raids` (Sichtbarkeit nach Kanal, Anmelden/Abmelden, Ablehnungen, Discord-Update) |
| `pr_test.py` | poll + autorole: Mitgliederseiten `/me/umfragen` und `/me/rollen` (gleiche Logik wie Buttons, Hierarchie, Fehler) |
| `tc_functest.py` | tickets + changelog: „Meine Tickets“ (eigene und hinzugefügte Tickets/Transcripts, keine fremden) und öffentliche Changelog-API |
| `tw_functest.py` | twitchlive: gemockte Twitch-API (Token, 401/429/5xx, Backoff), genau eine Meldung pro Stream, Live-Rolle, Befehle, Dashboard |
| `wl_test_welcome.py` | welcome: Beitritt/Verlassen, Willkommensbild mit Avatar, DM, Befehle, Dashboard mit Vorschau |
| `wl_test_warns.py` | warns: Punkte, Verfall, automatische Maßnahmen mit Hierarchie-Schutz, DM/Log, Befehle, Dashboard |
| `fivem_functest.py` | fivemadmin: WebCore-Seite, Panel-Rechte/Presets, SSO, keine Secrets im HTML |
| `fx_test.py` | tickets: `red_delete_data_for_user` (alle requester, Transcripts schwärzen/löschen) · raidhelper: „Neu posten“ · öffentliche APIs `/api/public/raids` und `/api/public/twitch` (aus = 404, keine Nutzerdaten, versteckte Kanäle, CORS, nur Cache) |
| `ws_test.py` | WebCore: Bot-Status, Fehlerprotokoll (Handler am Logger `red`, Secrets maskiert, kein doppelter Handler), Sichern & Wiederherstellen (Export ohne Secrets, Import mit Vorschau/Bestätigung/Rückgängig, Limits), Audit-Log als Tabelle – nur Owner, CSRF |
| `st_test.py` | serverstats: Zählung (Bots/Webhooks/AFK ausgenommen), Puffer/Flush, Voice-Zeit, Aufbewahrung, keine Personendaten, SVG-Diagramme, CSV-Export, Befehle, Dashboard-Rechte |
| `lv_test.py` | levels: XP/Cooldown/Levelkurve, Voice-XP-Regeln, Level-Up-Meldung, Belohnungen mit Hierarchie/Selbst-Hochstufung, Rangkarte, Rangliste, Befehle, Team-Dashboard, `/me/level`, Datenlöschung |
| `gv_test.py` | giveaways: Teilnahme-Regeln, persistente Views nach Neustart, faire gewichtete Auslosung, Nachholen nach Downtime, Reroll/Ende/Abbruch, Ping nur Gewinner, Rechte, Dashboard, `/me/gewinnspiele`, Datenlöschung |
| `sc_test.py` | scheduler: nächster Termin für alle Typen inkl. Sommerzeitwechsel Europe/Berlin und Monatsende, Downtime-Regel (< 10 min), Auto-Pause nach 5 Fehlern, allowed_mentions nur Ping-Rolle, Dashboard-Formulare/Vorschau, Befehle, Rechte |

## Bausteine (Harnesses)

| Datei | Inhalt |
|---|---|
| `bootstrap.py` | Repo-Wurzel, Paket `rc` (= Repo), temporäre Red-Instanz, `tmpdir()` für Testdaten |
| `wc_harness.py` | Fake-Discord (Server 1000/2000, Rollen, Mitglieder), `FakeBot`, `make_webcore(bot)` (WebCore ohne Port, Login per Header), `make_app()` mit den Standard-Cog-Dashboards |
| `live_harness.py` | Kanäle als echte Unterklassen von `discord.TextChannel`/… (bestehen `isinstance`), `send`/`edit`/`delete`/Webhooks werden in `LOG` aufgezeichnet und wie von Discord geprüft (Längen, Komponenten, Emojis); Rechte per `chan.forbid = {"send", …}` entziehen |
| `wcm_harness.py` | Mitglieder-Bereich: Nutzer Ben/Kai, Demo-Mitgliederseiten, Demo-Public-API, aufgezeichnete Log-Kanal-Posts |
| `rc_harness.py`, `rm_harness.py` | nur RaidHelper (+ gesperrter/versteckter Kanal, Demo-Events) |
| `pr_harness.py` | poll + autorole mit Kanal-Sichtbarkeit je Mitglied und aufgezeichneten Rollen |
| `tc_harness.py`, `tc_seed.py` | tickets + changelog, Fake-Interactions, Beispieldaten |
| `tw_harness.py` | twitchlive mit `FakeTwitch` (Helix-Nachbau, kein Netz) |
| `wl_harness.py` | welcome + warns, DMs aufgezeichnet |
| `fivem_harness.py` | fivemadmin ohne eigenen Webserver, SQLite im Temp-Ordner |
| `ws_harness.py` | WebCore mit Demo-Cog `WsDemo` (Secret-Keys), `bot.cogs`, installiertem Fehlerprotokoll |
| `st_harness.py`, `lv_harness.py` | serverstats bzw. levels (Voice-Kanäle Gaming/AFK, Belohnungsrollen, aufgezeichnete Rollen/DMs, Mein Bereich) |
| `gv_harness.py` | giveaways: `bot.add_view`-Aufzeichnung, Sendungen mit allowed_mentions, Kanal-Sichtbarkeit, `joined_at`, Fake-Interaktionen |
| `sc_harness.py` | scheduler: Sendungen mit allowed_mentions, `chan.fail_next` für Sendefehler, Beispieldaten |

Login wird in allen Harnesses per Header `X-Test-User: <id>` (oder `?_as=<id>`) simuliert:
1 = Bot-Owner, 11 Lena (Support), 12 Tom (Moderator), 13 Kai (VIP, nur Mitglied), 14 Mia (Support + Raidleitung).

**Zum Anschauen im Browser** lässt sich jede Harness als Server starten, z. B.
`python tests/tc_harness.py` (freier Port, wird ausgegeben) oder `python tests/tc_harness.py 8797`.
Der Login kommt aus dem Header `X-Test-User` – im Browser z. B. per Header-Erweiterung oder mit
Playwright (`browser.new_context(extra_http_headers={"X-Test-User": "1"})`); `?_as=1` gilt nur für
die einzelne Anfrage. Screenshot-/Playwright-Skripte liegen bewusst nicht im Repo (brauchen einen
Browser) – bei Bedarf lokal mit Playwright gegen so einen Server laufen lassen.

## Test für einen neuen Cog ergänzen

1. **Harness** (falls nötig) `tests/<cog>_harness.py` – meist reicht `live_harness`:
   ```python
   import live_harness as L          # echte Kanal-Unterklassen, L.LOG
   H = L.H

   async def make_app():
       wc, bot, app = await L.make_app()             # WebCore + Standard-Dashboards
       from rc.meincog.meincog import MeinCog
       cog = MeinCog(bot); bot._cogs["MeinCog"] = cog; cog._register_dashboard(wc)
       return wc, bot, app, cog

   if __name__ == "__main__":
       H.main(make_app)                              # python tests/<cog>_harness.py [port]
   ```
2. **Suite** `tests/<cog>_test.py` – mit `assert` prüfen (oder am Ende `sys.exit(1)` bei Fehlern),
   damit der Exit-Code stimmt:
   ```python
   """meincog: Dashboard speichert, Rechte, Posten."""
   import asyncio, re
   import meincog_harness as MH
   from aiohttp.test_utils import TestClient, TestServer

   async def main():
       wc, bot, app, cog = await MH.make_app()
       client = TestClient(TestServer(app)); await client.start_server()   # freier Port
       owner = {"X-Test-User": "1"}
       r = await client.get("/cogs/meincog?guild=1000", headers=owner); t = await r.text()
       assert r.status == 200 and "Meincog" in t
       tok = re.search(r"name='csrf_token' value='([^']+)'", t).group(1)
       r = await client.post("/cogs/meincog", headers=owner, allow_redirects=False,
                             data={"csrf_token": tok, "guild": "1000", "note": "x"})
       assert "ok=" in r.headers["Location"]
       assert await cog.config.guild(bot.get_guild(1000)).note() == "x"
       await client.close()
       print("ALLE MEINCOG-TESTS OK")

   asyncio.run(main())
   ```
3. In `run_all.py` in `SUITES` eintragen (Name + eine Zeile, was geprüft wird) und hier in der Tabelle.
4. Neue `requirements` aus der `info.json` in `tests/requirements.txt` ergänzen.
5. `python tests/run_all.py` muss grün sein – die GitHub Action prüft dasselbe.

Regeln: Cog-Code für Tests nie ändern – Fakes nur zur Laufzeit einsetzen/patchen. Keine festen
Pfade oder Ports; Testdaten nur über `bootstrap.tmpdir()` bzw. die temporäre Red-Instanz.
