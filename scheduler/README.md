# Scheduler (Geplante Nachrichten)

Geplante Nachrichten für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot): Der Bot postet Text
und/oder Embeds automatisch nach Zeitplan – per Befehl angelegt **oder** komplett über das WebCore-Dashboard.

## Funktionen

- **Inhalt:** Text (max. 1900 Zeichen) und/oder Embed (Titel, Text, Farbe, Bild-URL).
- **Rollen-Ping (optional):** wird vor den Text gesetzt; `allowed_mentions` erlaubt **nur diese Rolle** –
  `@everyone`, `@here` und Nutzer-Erwähnungen im Text pingen nie.
- **Zeitpläne:**
  - einmalig (Datum + Uhrzeit)
  - täglich (Uhrzeit)
  - wöchentlich an ausgewählten Wochentagen
  - monatlich am Tag X – gibt es den Tag nicht (z. B. 31. im April), am **letzten Tag des Monats**
  - alle N Minuten/Stunden (mindestens 10 Minuten)
- **Zeitzone je Server** (IANA, z. B. `Europe/Berlin`, Standard) mit korrekter **Sommerzeit**:
  „täglich 09:00“ bleibt 09:00 Ortszeit. Fällt eine Uhrzeit in die Lücke der Sommerzeit-Umstellung (02:30),
  kommt sie um 03:30; bei der doppelten Stunde im Herbst wird nur einmal gesendet. Intervalle laufen in echter
  Zeit (alle 2 Std. = immer 120 Minuten).
- **Start- und Enddatum** (inklusive), **pausieren/fortsetzen**, **„Vorherige Nachricht löschen“** (nach dem
  Senden wird die zuletzt von diesem Eintrag gesendete Nachricht entfernt).
- **Robuste Schleife** (alle 30 s): Fehler je Eintrag/Server werden abgefangen und protokolliert.

### Regeln nach Downtime und bei Fehlern

- **Verpasste Termine werden nicht nachgeholt** – außer der letzte fällige Termin liegt **weniger als 10 Minuten**
  zurück (z. B. kurzer Neustart): dann wird er **einmal** gesendet. Nach längerer Downtime kommt also keine Flut
  alter Nachrichten; im Dashboard steht „Übersprungen“ mit Zeitpunkt.
- Schlägt das Senden fehl (Kanal gelöscht, Rechte fehlen …), zählt der Eintrag einen Fehler und macht mit dem
  nächsten regulären Termin weiter (kein sofortiges Wiederholen). Nach **5 Fehlern in Folge** wird er
  **automatisch pausiert**; das Dashboard zeigt oben einen roten Hinweis mit dem letzten Fehler. Ein
  erfolgreicher Versand setzt den Zähler zurück, „Fortsetzen“ ebenfalls.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs scheduler
[p]load scheduler
```

## Befehle

Alle Befehle erfordern **„Server verwalten“** (oder Administrator; Bot-Owner immer). Alias: `[p]zeitplan`.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]schedule add <#kanal> "<zeitplan>" <text>` | Nachricht planen, z. B. `[p]schedule add #news "täglich 09:00" Guten Morgen!` | Server verwalten |
| `[p]schedule list` | Alle Einträge mit nächster Ausführung | Server verwalten |
| `[p]schedule remove <id>` | Eintrag löschen | Server verwalten |
| `[p]schedule pause <id>` | Eintrag pausieren | Server verwalten |
| `[p]schedule resume <id>` | Fortsetzen (auch nach Auto-Pause; setzt den Fehlerzähler zurück) | Server verwalten |
| `[p]schedule test <id>` | Nachricht einmal sofort **hier** posten (ohne Ping, Zeitplan unverändert) | Server verwalten |
| `[p]schedule timezone [zone]` | Zeitzone anzeigen/setzen (IANA), Termine werden neu berechnet | Server verwalten |
| `[p]schedule language <de\|en>` | Sprache der Bot-Antworten | Server verwalten |

**Zeitplan-Schreibweisen** (deutsch oder englisch):
`einmalig 2026-10-01 18:00` (auch `01.10.2026`) · `täglich 09:00` · `wöchentlich mo,mi,fr 18:00` ·
`monatlich 31 12:00` · `alle 30m` / `alle 2h` / `alle 1h30m` · `once …`, `daily …`, `weekly mon,wed …`,
`monthly …`, `every …`.

Embed, Rollen-Ping, Start-/Enddatum und „Vorherige löschen“ stellt man im Dashboard ein.

## Dashboard

Seite **Geplante Nachrichten** (`/cogs/scheduler`, Icon Uhr) – vollständig **ohne JavaScript** bedienbar:

- **Nachrichten** – Tabelle mit Suche: Name/Text, Kanal, Zeitplan, **nächste Ausführung (relativ + absolut)**,
  Status (aktiv, pausiert, automatisch pausiert, abgeschlossen) und Aktionen *Bearbeiten*, *Testen*,
  *Pausieren/Fortsetzen*, *Löschen* (mit Bestätigung).
- **Neue Nachricht** – alle Felder auf einer Seite; **Vorschau** zeigt die Nachricht und die nächsten 5 Termine,
  ohne zu speichern. Bei Fehlern bleiben die Eingaben erhalten.
- **Bearbeiten** (`?edit=<id>`) – Status (letzte Ausführung, Fehler, Übersprungen), Vorschau, **„Jetzt testen“**
  (postet einmal in den Kanal, **ohne** Rollen-Ping, ändert nichts am Zeitplan).
- **Einstellungen** – Zeitzone und Sprache.

## Datenspeicherung

Pro Eintrag: Inhalt, Kanal, Zeitplan, Status und die Discord-ID der Person, die ihn angelegt/zuletzt bearbeitet
hat. `red_delete_data_for_user` setzt diese IDs auf 0.
