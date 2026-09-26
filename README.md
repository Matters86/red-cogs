# Red-Cogs

Eigene Cogs für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – jeweils mit
einer eigenen Seite im gemeinsamen **WebCore-Dashboard** und vollständiger Doku.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog list red-cogs
[p]cog install red-cogs webcore
[p]load webcore
```

Danach `webcore` einrichten (siehe [`webcore/README.md`](webcore/README.md)).

## Enthaltene Cogs

| Cog | Beschreibung |
|---|---|
| [`webcore`](webcore/) | Zentrales Web-Dashboard (aiohttp, Discord-OAuth2) mit Rollen-Rechten (Ansehen/Bearbeiten je Seite), globalem Server-Wechsler und Audit-Log. Andere Cogs klinken sich ein. |
| [`example`](example/) | Vorlage: Hybrid-Befehl + automatische Dashboard-Seite. |
| [`autoroom`](autoroom/) | Autovoiceroom: automatische temporäre Voicechannels, voll per Dashboard konfigurierbar. |
| [`autorole`](autorole/) | Automatische Rollenvergabe bei Beitritt + Self-Service-Rollen-Panels (Buttons/Dropdown). |
| [`changelog`](changelog/) | Server-Updates (Changelogs) per Modal als einheitliches Embed posten – mit Kategorien, optionalem Rollen-Ping und Dashboard-Historie. |
| [`commands`](commands/) | Listet alle geladenen Cogs und Befehle im Dashboard – mit Stufen und Mitglieds-Prüfung. |
| [`fivemadmin`](fivemadmin/) | FiveM-Adminpanel (QBox): Support-, Moderations- und Admin-Aktionen per Discord-Befehl und eigenem Live-Webpanel (Login per Discord), gemeinsame Action-Queue, Audit-Log und Not-Aus. Dazu die Dashboard-Seite „FiveM-Admin“ für die Verwaltung (Not-Aus, Sperren, Panel-Rechte, Einstellungen, Ein-Klick-Anmeldung im Live-Panel). |
| [`guard`](guard/) | Spamschutz, Honeypot und Raid-Notmodus – mehrsprachig und per Dashboard steuerbar. |
| [`onlyimagevideo`](onlyimagevideo/) | Macht Kanäle zu Nur-Medien-Kanälen: löscht Nachrichten ohne Bild/Video/GIF (auch Tenor-/Giphy-Links, Sticker), Threads erben die Regel, mit Dashboard. |
| [`organigram`](organigram/) | Postet Server-Organigramme als Bild (5 Muster), Embed oder Text – mit Live-Vorschau im Dashboard. |
| [`poll`](poll/) | Mehrsprachige Umfragen: Abstimmung per Button, Live-Ergebnis, Einzel-/Mehrfachauswahl, anonym/öffentlich, Auto-Ende, CSV-Export und Dashboard. |
| [`raidhelper`](raidhelper/) | Mehrsprachiger Raid-Planer: Anmeldung per Button, Roster, Erinnerungen, Wiederholung, CSV-Export und Dashboard. |
| [`sticky`](sticky/) | Hält eine Nachricht am unteren Ende eines Kanals fest – mit Webhook-Modus, Platzhaltern und Dashboard. |
| [`tickets`](tickets/) | Mehrsprachiges Ticketsystem mit Panels, Team-Zuordnung je Grund, Transcripts und Dashboard. |
| [`twitchlive`](twitchlive/) | Twitch-Live-Benachrichtigungen: genau eine Meldung pro Stream mit Vorschaubild, Rollen-Ping, eigener Nachricht, „war live“-Bearbeitung nach Stream-Ende, optionaler Live-Rolle und Dashboard. |
| [`warns`](warns/) | Verwarnsystem mit Punkten, Verfall, automatischen Maßnahmen (inkl. Hierarchie-Schutz), DM und Log sowie Dashboard. Hinweis: Reds eingebauten Cog `warnings` vorher entladen (`[p]unload warnings`). |
| [`welcome`](welcome/) | Willkommens- und Abschiedsnachrichten, Willkommensbild mit Avatar, Willkommens-DM und Dashboard mit Live-Vorschau. |

## Wie das Dashboard funktioniert

`webcore` startet einen Webserver im Bot-Prozess. Jeder andere Cog registriert beim Laden eigene
Seiten über `register_page(...)` und taucht dann automatisch in der Navigation auf. Lädt man
einen Cog wieder aus, verschwindet seine Seite ebenso automatisch. Das vollständige Muster steht
in `example/example.py`.

## Mitglieder-Bereich & Launcher-API

Neben den Team-Seiten bietet WebCore zwei Zugänge für alle anderen:

- **Mein Bereich (`/me`)** – normale Server-Mitglieder melden sich per Discord an und sehen nur ihre
  eigenen Daten: **Raids** (anmelden, Status ändern, abmelden), **Umfragen** (abstimmen),
  **Rollen** (Self-Service-Rollen wie an den Panels) und **Meine Tickets** (eigene Tickets und
  Transcripts, optional neues Ticket öffnen). Pro Server einschaltbar (`[p]webcore portal on` bzw.
  *Zugriff & Rollen*); jede Modul-Seite lässt sich zusätzlich im jeweiligen Dashboard ausblenden.
- **Öffentliche API (`/api/public/…`)** – ohne Login, mit CORS und Rate-Limit, z. B. die
  **Changelog-API** (`/api/public/changelog/<server-id>` als JSON bzw. `/rss`) für einen
  Spiele-Launcher oder die eigene Website.

Details, Einrichtung und die Regeln für Cog-Entwickler stehen in [`webcore/README.md`](webcore/README.md)
(„Mein Bereich“, „Mitglieder-Seiten“, „öffentliche API“), die Changelog-API in
[`changelog/README.md`](changelog/README.md).

## Tests & CI

Unter [`tests/`](tests/) liegen automatische Tests für alle Cogs (echter WebCore und echte Cogs,
Discord als Fake) – lokal mit `python tests/run_all.py`; eine GitHub Action führt sie zusammen mit
`compileall` und `pyflakes` bei jedem Push und Pull-Request aus. Details: [`tests/README.md`](tests/README.md).

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
ins Internet zeigen. Der Zugriff ist über `[p]webcore access` konfigurierbar: `owner` (nur
Bot-Owner/Co-Owner), `admin` (zusätzlich Server-Admins für ihre eigenen Server) oder `allowlist`
(Owner plus die per `[p]webcore allow` freigegebenen User).
