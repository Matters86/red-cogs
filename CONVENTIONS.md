# CONVENTIONS — Red-Cogs

Verbindliche Standards für **alle** Cogs in diesem Repo. Jeder (auch ein frischer) Cog-Chat
richtet sich danach. Diese Datei gehört ins Projekt-Wissen **und** in die Projekt-Anweisungen
(als Verweis).

## Ziel & Stack
- Red-DiscordBot (min. 3.5), Python 3.11+
- Monorepo `red-cogs`, **ein Ordner pro Cog**
- Web-Dashboard: **WebCore** (läuft im Bot-Prozess), **Standard-Theme** aus `webcore/static/webcore.css` —
  **nicht** neu designen, nur dessen CSS-Klassen verwenden
- Doku & Forum-Posts auf **Deutsch**

## Repo-Layout
```
red-cogs/
├── info.json                 # Repo-Info
├── README.md                 # Übersicht + Tabelle aller Cogs
├── CONVENTIONS.md            # diese Datei
├── COG-BRIEF-TEMPLATE.md     # pro Cog-Chat ausfüllen
├── webcore/                  # Dashboard-Kern
├── tests/                    # automatische Tests (run_all.py) – kein Cog, ohne info.json
├── .github/workflows/        # CI (tests.yml)
└── <cog>/                    # je Cog: __init__.py, <cog>.py, info.json, README.md, FORUM.md
```

## Namens- & Code-Regeln
- Ordnername: kleingeschrieben, ein Wort (z. B. `welcomer`)
- Cog-Ordner **nie** wie ein Python-Standardmodul oder einen Red-Core-Cog benennen (z. B. `warnings`,
  `logging`, `json`, `admin`, `mod`) – das Paket überdeckt sonst das Modul bzw. kollidiert mit Reds
  eigenem Cog (deshalb heißt das Verwarnsystem `warns`). `tests/realred.py` prüft das.
- Cog-Klasse: CamelCase (`Welcomer`)
- `Config.get_conf(self, identifier=<eindeutige Zahl>, force_registration=True)` —
  jede Zahl nur **einmal** vergeben (Liste unten pflegen!)
- Befehle als `@commands.hybrid_*` (Text + Slash), wo sinnvoll
- Logging: `logging.getLogger("red.red-cogs.<cog>")`
- Keine Secrets/Tokens im Code oder in der Doku

## Vergebene identifier (NICHT doppelt verwenden)
| Cog | identifier |
|---|---|
| webcore | 8472013561 |
| example | 290117450912 |
| autoroom | 736014928503 |
| tickets | 846215097433 |
| raidhelper | 615238947104 |
| sticky | 592384710265 |
| organigram | 471203958624 |
| poll | 529184637025 |
| autorole | 905172634810 |
| commands | 318472905613 |
| guard | 384207516930 |
| changelog | 274069153822 |
| onlyimagevideo | 472619305847 |
| fivemadmin | 10539329 (`0xA0D141`, Altbestand ohne `force_registration` – nicht ändern, sonst Datenverlust) |
| twitchlive | 618305729164 |
| welcome | 730418295561 |
| warns | 551902837146 |
| _neue hier ergänzen_ | |

`tests/realred.py` prüft, dass jede Zahl im Code nur einmal vorkommt und hier eingetragen ist.

## info.json pro Cog — Vorlage
```json
{
    "name": "Welcomer",
    "short": "Kurzbeschreibung in einem Satz.",
    "description": "Etwas ausführlichere Beschreibung.",
    "tags": ["..."],
    "requirements": [],
    "min_bot_version": "3.5.0",
    "hidden": false,
    "disabled": false,
    "type": "COG",
    "end_user_data_statement": "Welche Endnutzerdaten gespeichert werden (oder keine)."
}
```

## WebCore-Integration (Pflicht — 1:1 aus `example` übernehmen)
```python
async def cog_load(self):
    webcore = self.bot.get_cog("WebCore")
    if webcore is not None:
        self._register_dashboard(webcore)

async def cog_unload(self):
    webcore = self.bot.get_cog("WebCore")
    if webcore is not None:
        webcore.unregister_owner(self)

@commands.Cog.listener()
async def on_webcore_ready(self, webcore):
    self._register_dashboard(webcore)

def _register_dashboard(self, webcore):
    webcore.register_page(owner=self, slug="<cog>", name="<Anzeigename>",
                          icon="bi-...", handler=self.dashboard_page)

async def dashboard_page(self, request):
    return {"title": "<Anzeigename>", "content": "<html>"}
```
- `handler` gibt **immer** `{"title": str, "content": <HTML-String>}` zurück.
- Markup mit dem **UI-Kit** bauen: `ui = request.app["webcore"].ui` → `ui.hero`, `ui.stats`, `ui.tab`,
  `ui.card`, `ui.form(..., savebar=True)`, `ui.field`, `ui.switch`, `ui.select`, `ui.table` …
  (Übersicht: `webcore/README.md` → „UI-Kit“; Vorbild: `example/example.py`, `tickets/dashboard.py`).
  Kein eigenes `<style>`, keine eigenen Erfolgsbalken (Meldungen per `?ok=`/`?err=` als Toast),
  Löschen immer mit `confirm=`. Icons: Bootstrap-Icons (`bi-...`).
- Nutzereingaben in HTML immer mit `html.escape(...)` absichern.

### Einstellungen schreiben (Formulare, POST + CSRF) — optional
Seiten dürfen auch schreiben. Jede Seite ist unter `/cogs/<slug>` per **GET und POST**
erreichbar; derselbe `handler` bekommt beide (Unterscheidung über `request.method`).
WebCore stellt pro Sitzung ein CSRF-Token unter `request["webcore_csrf"]` bereit, prüft es
bei jedem POST zentral (HTTP 400 bei Fehler) und der Handler leitet nach Erfolg per
`return {"redirect": "/cogs/<slug>?ok=1"}` um (Post/Redirect/Get).
```python
async def dashboard_page(self, request):
    csrf = request.get("webcore_csrf", "")
    if request.method == "POST":
        form = await request.post()                 # CSRF schon geprüft
        await self.config.guild_from_id(int(form["guild_id"])).note.set(form.get("note", ""))
        return {"redirect": "/cogs/<slug>?ok=1"}
    return {"title": "...", "content":
        f"<form method='post' action='/cogs/<slug>'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        f"<input name='note'><button class='btn-accent'>Speichern</button></form>"}
```
- Jedes Formular muss `csrf_token` als verstecktes Feld mitsenden.
- Werte serverseitig validieren (z. B. Channel-IDs gegen echte Guild-Objekte prüfen).

### Server-Auswahl & Rollen-Rechte (Pflicht)
- Server **nur** über `await webcore.visible_guilds(request)` auflösen – nie `self.bot.guilds`.
  Die Liste ist seitenbewusst: GET = Server mit *Ansehen*, POST = Server mit *Bearbeiten*.
  Jedes Formular sendet die Ziel-Guild als Feld `guild` (oder `guild_id`); der POST-Handler prüft
  sie gegen `visible_guilds`.
- Den aktuellen Server aus `request.query.get("guild")` lesen. WebCore setzt den Parameter
  automatisch und zeigt den **globalen Server-Wechsler** in der Kopfzeile – kein eigenes
  Server-Dropdown bauen (nur als Fallback, wenn `request.get("wc_switcher")` fehlt).
- Nach POST per `?ok=<Text>` / `?err=<Text>` umleiten → WebCore zeigt einen Toast.
- Rollen, die ein Cog **automatisch vergibt** (Beitritts-/Panel-/Inhaber-Rollen …), vor dem
  Speichern mit `await webcore.can_grant_role(request, guild, role)` prüfen.
- Botweite Einstellungen (gelten für alle Server) nur mit `await webcore.has_full_scope(request)`.
- **Bot-Owner hat immer alle Rechte.** Jede eigene Rechteprüfung (Staff-/Manager-/Admin-Checks,
  Button-Handler, Ausnahmen von Filtern) lässt den Owner zuerst durch: `await self.bot.is_owner(member)`
  bzw. synchron `member.id in self.bot.owner_ids`. Reds Dekoratoren (`commands.has_permissions`,
  `admin_or_permissions` …) machen das schon selbst.

### Mitglieder-Seiten („Mein Bereich“, `/me/<slug>`) — optional
Cogs dürfen normalen Mitgliedern eigene Seiten anbieten (`webcore.register_member_page(...)`,
Details und Beispiel: `webcore/README.md` → „Für Cog-Entwickler: Mitglieder-Seiten“). Pflicht dabei:
- **Nur eigene Daten**: immer über `request["wc_member"]` filtern, nie über IDs aus Formular/URL;
  Server nur aus `request["wc_member_guild"]` bzw. `portal_guilds`/`member_context` – nicht `visible_guilds`.
- **Gleiche Logik wie die Discord-Buttons**: dieselbe Cog-Funktion aufrufen (Limits, Cooldowns,
  Rechte, Rollen-Hierarchie), keine zweite Implementierung; Ergebnis per `?ok=`/`?err=`.
- **Abschaltbar**: `visible=lambda g: self.config.guild(g).member_page()` mitgeben und im
  Team-Dashboard einen Schalter „Im Mitglieder-Bereich anzeigen“ anbieten; ist er aus, sind Seite
  und Aktionen gesperrt.
- Keine Team-Interna ausgeben, alles mit `html.escape`, Formulare mit `csrf_token`.

## Tests (Pflicht)
- Jeder Cog braucht eine Test-Suite in `tests/` (Anleitung: `tests/README.md` → „Test für einen
  neuen Cog ergänzen“) und einen Eintrag in `tests/run_all.py` (`SUITES`). `run_all.py` meldet
  Cogs, die von keiner Test-Datei importiert werden.
- Neue `requirements` aus der `info.json` auch in `tests/requirements.txt` eintragen.
- Vor jedem Push: `python tests/run_all.py` muss grün sein. Die GitHub Action
  (`.github/workflows/tests.yml`: `compileall`, `pyflakes`, `run_all.py`) läuft bei jedem Push und
  Pull-Request – ohne grüne CI ist Punkt 4 der Definition of Done nicht erfüllt.
- Tests ändern nie Cog-Code, sondern setzen Fakes zur Laufzeit ein; keine festen Pfade oder Ports.

## Definition of Done (ein Cog ist erst fertig, wenn ALLE 4 stehen)
1. **Code** — `<cog>/` mit `__init__.py`, `<cog>.py`, `info.json`
2. **Dashboard-Seite** — `register_page(...)` + `cog_unload`-Aufräumen + `on_webcore_ready`
3. **Doku** — `README.md` und `FORUM.md` (Deutsch, mit Befehlstabelle)
4. **GitHub** — Test-Suite in `tests/` grün, committen/pushen + im Repo-`README.md` die Cog-Tabelle ergänzen

## Doku-Format
- **README.md**: Kurzbeschreibung · Installation · Befehlstabelle (Befehl · Beschreibung · Rechte) · Dashboard-Abschnitt
- **FORUM.md**: dieselbe Befehlstabelle, copy-paste-fertig fürs Discord-Forum

## GitHub-Befehle (Nutzerseite)
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs <cog>
[p]load <cog>
```
