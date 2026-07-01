# Changelog

Server-Updates (Changelogs) für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – Team-Mitglieder füllen ein **Modal** aus, der Bot postet daraus ein **einheitliches Embed** im festgelegten Kanal. Mehrsprachig, mit eigener Seite im WebCore-Dashboard.

Der Befehl **`/changelog`** öffnet ein Popup-Formular mit den Feldern **Titel, Neu, Geändert, Fixes, Hinweis**. Beim Absenden baut der Bot ein sauberes Update-Embed (Bullet-Listen, Kategorie-Emoji, Fußzeile mit Datum und Name) und postet es – optional mit einem Rollen-Ping davor.

## Funktionen

- **Posten per Modal** – `/changelog` öffnet ein Formular; kein manuelles Embed-Basteln.
- **Einheitliches Embed** – Titel, Abschnitte *Neu/Geändert/Fixes* als Bullet-Listen, optionaler **Hinweis** (fett, mit ⚠️), Fußzeile mit Datum + Name.
- **Kategorie pro Changelog wählbar** – die postende Person wählt beim Befehl ein Emoji für den „Neu\"-Bereich (z. B. 🚗/🌾/⚙️); die Auswahl-Liste ist pro Server konfigurierbar.
- **Ziel-Kanal fest pro Server** – nicht vom User wählbar, damit Changelogs immer am richtigen Ort landen.
- **Rechte pro Server** – nur festgelegte Rollen (plus Admins) dürfen posten; serverseitig geprüft.
- **Optionaler Ping** – eine `@Updates`-Rolle wird als separate Nachricht vor dem Embed gepingt (an-/abschaltbar).
- **Mehrsprachig** – Deutsch als Standard, pro Server umschaltbar (aktuell `de`, `en`).
- **Historie & Dashboard** – jeder Post wird gespeichert; im Dashboard einsehbar, mit Detailansicht und Löschfunktion.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs changelog
[p]load changelog
```

`/changelog` ist ein Slash-Befehl. Falls die Slash-Befehle des Bots noch nicht synchronisiert sind, einmalig:

```
[p]slash enable changelog
[p]slash sync
```

## Schnellstart

```
[p]changelogset channel #server-news     # Ziel-Kanal festlegen
[p]changelogset roleadd @Discord-Team     # wer posten darf
[p]changelogset pingrole @Updates         # optionale Ping-Rolle
[p]changelogset ping on                    # Ping aktivieren
```

Danach im Server `/changelog` aufrufen, optional eine `kategorie` wählen, Formular ausfüllen, absenden – fertig. Alternativ lässt sich alles auch im **Dashboard** unter `/cogs/changelog` einstellen.

## Befehle

Posten (`/changelog`) – nur als Slash-Befehl, da ein Modal eine Interaction voraussetzt.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `/changelog [kategorie]` | Öffnet das Changelog-Formular; postet das Embed in den Ziel-Kanal. | Poster-Rollen / Admin |

Einstellungen (`changelogset`) – erfordern „Server verwalten" oder Admin.

| Befehl | Beschreibung |
|---|---|
| `[p]changelogset channel <#kanal>` | Ziel-Kanal für Changelogs festlegen |
| `[p]changelogset roleadd <rolle>` | Rolle hinzufügen, die posten darf |
| `[p]changelogset roleremove <rolle>` | Poster-Rolle entfernen |
| `[p]changelogset pingrole <rolle>` | Rolle festlegen, die vor dem Embed gepingt wird |
| `[p]changelogset ping <on\|off>` | Ping vor dem Embed an-/ausschalten |
| `[p]changelogset color <#hex>` | Embed-Farbe setzen (z. B. `#3DDC97`) |
| `[p]changelogset language <de\|en>` | Sprache setzen |
| `[p]changelogset catadd <emoji> <bezeichnung>` | Wählbare Kategorie hinzufügen |
| `[p]changelogset catremove <nummer>` | Kategorie per Nummer entfernen |
| `[p]changelogset cats` | Wählbare Kategorien anzeigen |
| `[p]changelogset show` | Aktuelle Einstellungen anzeigen |
| `[p]changelogset history [anzahl]` | Letzte Changelogs auflisten (Standard: 5) |

## Das Formular

Das Modal hat genau fünf Felder (Discord-Limit): **Titel** (Pflicht), **Neu**, **Geändert**, **Fixes** (je optional, mehrzeilig – ein Punkt pro Zeile) und **Hinweis** (optional). Mindestens eines der Felder *Neu/Geändert/Fixes* muss ausgefüllt sein, sonst postet der Bot nicht und meldet das nur der postenden Person (ephemer). Mehrzeilige Eingaben werden im Embed automatisch zu Bullet-Listen.

## Dashboard

Die Seite **Changelog** erscheint nach dem Laden automatisch im WebCore-Dashboard unter `/cogs/changelog`. Dort gibt es:

- ein Einstellungs-Formular (Ziel-Kanal, Sprache, Poster-Rollen, Ping-Rolle + Schalter, Embed-Farbe, wählbare Kategorien, Text-Overrides),
- eine **Historie-Tabelle** aller geposteten Changelogs (Datum, Kategorie, Titel, Kanal, Autor) mit Link „Zur Nachricht" und Löschfunktion,
- eine **Detailansicht** je Changelog mit allen Abschnitten.

Die Server-Auswahl im Dashboard ist auf die Server beschränkt, die der eingeloggte User sehen darf.

## Datenspeicherung

Pro Server werden die geposteten Changelogs gespeichert: Titel und Inhalte (Neu/Geändert/Fixes/Hinweis), die gewählte Kategorie, Kanal- und Nachrichten-ID sowie Anzeigename und Discord-ID der postenden Person (für die Historie). Einträge lassen sich im Dashboard löschen; beim Löschen wird auf Wunsch auch die Discord-Nachricht entfernt. Daten werden beim Entfernen des Cogs oder beim Verlassen des Servers gelöscht.
