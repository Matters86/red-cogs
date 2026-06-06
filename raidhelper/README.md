# RaidHelper

Mehrsprachiger Raid-Planer für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – Anmeldungen wie bei [raid-helper.dev](https://raid-helper.dev), direkt im eigenen Bot und ohne externen Dienst.

Organisatoren legen ein Event an, der Bot postet ein **Embed mit Live-Roster** in einen Kanal. Mitglieder melden sich per **Klassen-Dropdown** an, wählen ihre **Spezialisierung** (wird gemerkt) und werden anhand der Spec automatisch der passenden **Rolle** (Tank / Heiler / Nahkampf / Fernkampf) zugeordnet.

## Funktionen

- **Anmeldung per Klick** – Klassen-Dropdown + Spec-Auswahl, dazu Bank, Spät, Vielleicht und Abwesend.
- **Live-Roster** im Embed, nach Rolle gruppiert, mit fortlaufender Nummerierung.
- **Spec-Gedächtnis** – die zuletzt gewählte Spezialisierung je Spiel und Klasse wird pro Nutzer gemerkt.
- **Limits** für das gesamte Event und pro Rolle.
- **Anmeldeschluss** – standardmäßig der Event-Start, Anmeldung danach automatisch zu.
- **Erinnerungen** 60 und 15 Minuten vor Start im Kanal, optional zusätzlich per DM an Angemeldete.
- **Wiederkehrende Events** – täglich, wöchentlich oder zweiwöchentlich; der nächste Termin wird automatisch erzeugt.
- **Teilnahme-Statistik** je Mitglied.
- **CSV-Export** der Anmeldungen.
- **Drei WoW-Vorlagen**: Retail (13 Klassen), Classic/Vanilla (9), WotLK/Cata (10) – mit **deutschen** Klassen- und Spec-Namen.
- **Klassen-Icons** – eigene Klassen-Icons botweit als Application-Emojis, bequem per Dashboard hochladbar; erscheinen im Dropdown und im Roster.
- **Mehrsprachig** – Deutsch als Standard, pro Server umschaltbar (aktuell `de`, `en`).
- **Dashboard** – Events und Einstellungen vollständig über das WebCore-Dashboard verwaltbar.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs <REPO-URL>
[p]cog install red-cogs raidhelper
[p]load raidhelper
```

`tzdata` wird als Abhängigkeit mitinstalliert (für korrekte Zeitzonen, v. a. unter Windows).

## Schnellstart

```
[p]raidset channel #raids        # Anmelde-Kanal festlegen
[p]raidset game wow_retail       # Standard-Spiel (optional)
[p]raidset language de           # Sprache (optional)
[p]raid create 13.06.2026 20:00 Mythic Undermine
```

Datum/Uhrzeit werden in der eingestellten Server-Zeitzone interpretiert (Standard `Europe/Berlin`) und im Embed als zeitzonenabhängige Discord-Zeitstempel angezeigt.

## Befehle

Verwaltung (`raid`) erfordert eine Manager-Rolle, „Server verwalten" oder Bot-Inhaber.

| Befehl | Beschreibung |
|---|---|
| `[p]raid create <datum> <zeit> <titel>` | Event im Standard-Kanal/-Spiel anlegen |
| `[p]raid quickcreate <spiel> <datum> <zeit> [#kanal] <titel>` | Event mit Spiel und Kanal direkt anlegen |
| `[p]raid list` | Alle Events des Servers auflisten |
| `[p]raid close <id>` | Anmeldung schließen |
| `[p]raid reopen <id>` | Anmeldung wieder öffnen |
| `[p]raid delete <id>` | Event samt Nachricht löschen |
| `[p]raid add <id> <mitglied> <klasse> <spec>` | Mitglied manuell eintragen |
| `[p]raid remove <id> <mitglied>` | Mitglied aus einem Event entfernen |
| `[p]raid export <id>` | Anmeldungen als CSV exportieren |

Einstellungen (`raidset`) erfordern „Server verwalten" oder Admin.

| Befehl | Beschreibung |
|---|---|
| `[p]raidset language <de\|en>` | Sprache setzen |
| `[p]raidset game <spiel-id>` | Standard-Spiel setzen |
| `[p]raidset channel <#kanal>` | Standard-Anmelde-Kanal setzen |
| `[p]raidset managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen (Umschalter) |
| `[p]raidset timezone <zone>` | Anzeige-Zeitzone setzen (z. B. `Europe/Berlin`) |
| `[p]raidset reminders <true\|false>` | Erinnerungen an-/ausschalten |
| `[p]raidset icons` | Zeigt, welche Klasse welches Icon hat |
| `[p]raidset classicon <klasse> <emoji>` | Icon einer Klasse manuell auf ein vorhandenes Emoji setzen |
| `[p]raidset clearicon <klasse>` | Icon einer Klasse entfernen |
| `[p]raidset uploadicons` | Angehängte Bilddateien als Klassen-Icons hochladen (Dateiname = Klassen-ID) |
| `[p]raidset settings` | Aktuelle Einstellungen anzeigen |
| `[p]raidset dashboard` | Hinweis zur Dashboard-Seite |

Spiel-IDs: `wow_retail`, `wow_classic`, `wow_wotlk`.

## Dashboard

Die Seite **Raidplaner** erscheint nach dem Laden automatisch im WebCore-Dashboard unter `/cogs/raidhelper`. Dort gibt es:

- Statistik-Kacheln (kommende Events, Anmeldungen gesamt, Standard-Spiel),
- ein Einstellungs-Formular (Sprache, Standard-Spiel, Anmelde-Kanal, Zeitzone, Erinnerungen, Text-Overrides),
- eine Event-Tabelle mit Aktionen (Schließen/Öffnen/Löschen),
- eine Roster-Ansicht pro Event,
- eine **Klassen-Icon-Verwaltung** mit Datei-Upload und Vorschau der aktuellen Icons.

## Klassen-Icons

Eigene Klassen-Icons werden als **Application-Emojis** an der Bot-Anwendung hinterlegt – botweit nutzbar, ohne Server-Emoji-Slots und ohne Einrichtung pro Server. Sie erscheinen im Klassen-Dropdown, in der Spec-Auswahl und in jeder Roster-Zeile.

Am einfachsten über das **Dashboard** (Abschnitt „Klassen-Icons"): die Bilddateien hochladen, wobei der Dateiname der Klassen-ID entspricht (`krieger.png`, `paladin.png`, `daemonenjaeger.png`, …). Pro Datei max. 256 KB; der Gesamt-Upload sollte unter ca. 1 MB bleiben (sonst in kleineren Gruppen hochladen). Alternativ per Befehl `[p]raidset uploadicons` mit angehängten Dateien oder manuell mit `[p]raidset classicon <klasse> <emoji>`.

Voraussetzung für den Upload ist discord.py ≥ 2.4 (in aktuellen Red-Versionen enthalten); das Cog erkennt dies und weist sonst im Dashboard darauf hin. Da die Klassen-IDs spielübergreifend gleich sind, gilt ein gesetztes Icon für alle WoW-Vorlagen.

Die offiziellen WoW-Klassen-Icons sind Eigentum von Blizzard und werden nicht mitgeliefert – die Grafiken stellst du selbst bereit, das Cog bindet sie über den obigen Mechanismus ein.

## Eigene Spiele ergänzen

Ein Spiel ist in `games.py` ein reiner Datenblock (Rollen, Klassen, Specs, Farben). Ein weiteres Spiel hinzuzufügen heißt: einen Eintrag in `GAMES` ergänzen – die gesamte Anmelde-, Roster- und Embed-Logik liest nur diese Tabellen, neuer Code ist nicht nötig. Die Rolle einer Anmeldung ergibt sich immer aus der gewählten Spec.

## Datenspeicherung

Pro Event werden Anmeldungen (Discord-ID, Anzeigename, Klasse/Spec, Rolle, Status, Zeitpunkt) gespeichert, pro Nutzer die zuletzt gewählte Spec je Spiel/Klasse sowie eine Teilnahme-Statistik. Daten werden beim Löschen eines Events, beim Entfernen des Cogs oder beim Verlassen des Servers entfernt.
