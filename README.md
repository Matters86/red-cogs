# Red-Cogs

Eigene Cogs für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – jeweils mit
einer eigenen Seite im gemeinsamen **WebCore-Dashboard** und vollständiger Doku.

## Installation

```
[p]repo add red-cogs <github-url>
[p]cog list red-cogs
[p]cog install red-cogs webcore
[p]load webcore
```

Danach `webcore` einrichten (siehe [`webcore/README.md`](webcore/README.md)).

## Enthaltene Cogs

| Cog | Beschreibung |
|---|---|
| [`webcore`](webcore/) | Zentrales Web-Dashboard (aiohttp, Discord-OAuth2). Andere Cogs klinken sich ein. |
| [`example`](example/) | Vorlage: Hybrid-Befehl + automatische Dashboard-Seite. |
| [`autoroom`](autoroom/) | Autovoiceroom: automatische temporäre Voicechannels, voll per Dashboard konfigurierbar. |
| [`tickets`](tickets/) | Mehrsprachiges Ticketsystem mit Panels, Transcripts und Dashboard. |
| [`raidhelper`](raidhelper/) | Mehrsprachiger Raid-Planer: Anmeldung per Button, Roster, Erinnerungen, Wiederholung, CSV-Export und Dashboard. |
| [`sticky`](sticky/) | Hält eine Nachricht am unteren Ende eines Kanals fest (Text/Embed, Webhook, Platzhalter, Cooldown). Voll per Dashboard konfigurierbar. |
| [`organigram`](organigram/) | Postet Server-Organigramme als Bild, Embed oder Text (Rollen + manuelle Namen, fünf Muster, Auto-Update). Voll per Dashboard konfigurierbar. |
| [`poll`](poll/) | Mehrsprachige Umfragen mit Abstimmung per Button, Live-Ergebnis und Dashboard. |
| [`autorole`](autorole/) | Vergibt automatisch Rollen beim Beitritt – respektiert die Regelverifizierung, prüft Zuweisbarkeit, mit Anti-Raid, Bot- und sicheren Sticky-Rollen. Voll per Dashboard konfigurierbar. |

## Wie das Dashboard funktioniert

`webcore` startet einen Webserver im Bot-Prozess. Jeder andere Cog registriert beim Laden eigene
Seiten über `register_page(...)` und taucht dann automatisch in der Navigation auf. Lädt man
einen Cog wieder aus, verschwindet seine Seite ebenso automatisch. Das vollständige Muster steht
in `example/example.py`.

## Workflow pro neuem Cog (Definition of Done)

Jeder neue Cog gilt erst als fertig, wenn alle vier Punkte erledigt sind:

1. **Cog-Code** – Ordner `meincog/` mit `__init__.py`, `meincog.py` und `info.json`.
2. **Dashboard-Seite** – `register_page(...)` plus `cog_unload`-Aufräumen und
   `on_webcore_ready`-Listener (aus `example` kopieren). Wird mit jeder Funktion erweitert.
3. **Doku** – `README.md` (für GitHub) und `FORUM.md` (zum Posten ins Discord-Forum) auf Deutsch,
   mit Befehlstabelle (Befehl · Beschreibung · Rechte).
4. **GitHub** – committen und pushen; im Repo-README oben in der Tabelle ergänzen.

Schnellstart für einen neuen Cog: den Ordner `example/` kopieren, umbenennen, Inhalte ersetzen.

## Lizenz / Hosting-Hinweis

Der Dashboard-Webserver sollte hinter einem HTTPS-Reverse-Proxy laufen und nicht ungeschützt
ins Internet zeigen. Zugriff haben nur Bot-Owner.
