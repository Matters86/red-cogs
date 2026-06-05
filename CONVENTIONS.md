# CONVENTIONS — Red-Cogs

Verbindliche Standards für **alle** Cogs in diesem Repo. Jeder (auch ein frischer) Cog-Chat
richtet sich danach. Diese Datei gehört ins Projekt-Wissen **und** in die Projekt-Anweisungen
(als Verweis).

## Ziel & Stack
- Red-DiscordBot (min. 3.5), Python 3.11+
- Monorepo `red-cogs`, **ein Ordner pro Cog**
- Web-Dashboard: **WebCore** (läuft im Bot-Prozess), **Standard-Theme** aus `webcore/base.html` —
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
└── <cog>/                    # je Cog: __init__.py, <cog>.py, info.json, README.md, FORUM.md
```

## Namens- & Code-Regeln
- Ordnername: kleingeschrieben, ein Wort (z. B. `welcomer`)
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
| tickets | 846215097433 |

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
- Nutzbare CSS-Klassen aus dem Standard-Theme: `card-x`, `table`, `stat`, `stat-label`,
  `mono`, `btn-accent`. Icons: Bootstrap-Icons (`bi-...`).
- Nutzereingaben in HTML immer mit `html.escape(...)` absichern.

## Definition of Done (ein Cog ist erst fertig, wenn ALLE 4 stehen)
1. **Code** — `<cog>/` mit `__init__.py`, `<cog>.py`, `info.json`
2. **Dashboard-Seite** — `register_page(...)` + `cog_unload`-Aufräumen + `on_webcore_ready`
3. **Doku** — `README.md` und `FORUM.md` (Deutsch, mit Befehlstabelle)
4. **GitHub** — committen/pushen + im Repo-`README.md` die Cog-Tabelle ergänzen

## Doku-Format
- **README.md**: Kurzbeschreibung · Installation · Befehlstabelle (Befehl · Beschreibung · Rechte) · Dashboard-Abschnitt
- **FORUM.md**: dieselbe Befehlstabelle, copy-paste-fertig fürs Discord-Forum

## GitHub-Befehle (Nutzerseite)
```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs <cog>
[p]load <cog>
```
