# Giveaways (Gewinnspiele)

Gewinnspiele für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – starten per Befehl **oder**
komplett über das WebCore-Dashboard. Mitglieder nehmen per **🎉-Button** teil, die Auslosung läuft automatisch
zum Ende – fair per kryptografisch sicherem Zufall und auch dann, wenn der Bot zu diesem Zeitpunkt offline war.

## Funktionen

- **Preis, Beschreibung, Kanal, Anzahl Gewinner (1–20)** und Laufzeit als **Dauer** (`2d`, `12h`, `1d12h`) oder
  **Datum + Uhrzeit** in der Server-Zeitzone (1 Minute bis 60 Tage).
- **Teilnahme-Regeln:** benötigte Rollen (mindestens eine davon), ausgeschlossene Rollen, Mindest-Mitgliedschaft
  in Tagen. Bots können nie teilnehmen. Die Regeln gelten beim Teilnehmen **und** noch einmal bei der Auslosung
  (wer den Server verlassen oder die Voraussetzung verloren hat, wird nicht gezogen).
- **Bonus-Lose:** bis zu 5 Rollen mit je +1 bis +10 Losen (werden addiert, höchstens 25 Lose pro Person).
- **Persistenter Button:** funktioniert nach Bot-Neustart und `[p]reload` weiter (`bot.add_view` mit fester
  `custom_id` `gw:join:<server>:<id>`). Erneuter Klick = Rückfrage „Wirklich austreten?“ (nur für dich sichtbar).
- **Teilnehmerzahl** im Embed und auf dem Button – **gedrosselt** aktualisiert (höchstens alle 10 Sekunden je
  Gewinnspiel, Klicks dazwischen werden mitgezählt), damit viele Klicks keine Rate-Limits auslösen.
- **Auslosung** mit `secrets.SystemRandom`, gewichtet nach Losen, ohne Zurücklegen (niemand gewinnt doppelt).
- **Gewinner-Ansage** als Antwort auf das Gewinnspiel – gepingt werden **nur die Gewinner** (kein `@everyone`,
  keine Rollen, auch wenn der Preis-Text so etwas enthält). Das Embed zeigt danach „Beendet“ und die Gewinner.
- **Vorzeitig beenden**, **abbrechen** (ohne Auslosung), **neu auslosen**: einzelnen Gewinner ersetzen oder alle.
  Wer einmal ersetzt wurde, kann bei diesem Gewinnspiel nicht erneut gezogen werden.
- **Nach Downtime:** Die Hintergrund-Schleife (alle 20 s) lost jedes Gewinnspiel aus, dessen Ende erreicht ist –
  auch wenn das Ende während einer Bot-Downtime lag. Fehler bei einem Gewinnspiel stoppen die anderen nicht.
- **Aufräumen:** beendete/abgebrochene Gewinnspiele werden nach der Aufbewahrungszeit (Standard 90 Tage) entfernt.
- **Mehrsprachig:** Embed, Button, Antworten und Ansage auf Deutsch (Standard) oder Englisch.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs giveaways
[p]load giveaways
```

Empfohlen: **Server Members Intent** aktivieren (für Mindest-Mitgliedschaft und die Prüfung bei der Auslosung;
ohne Intent fragt der Cog fehlende Mitglieder einzeln bei Discord ab).

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]giveaway start <dauer> <gewinner> <preis>` | Gewinnspiel in diesem Kanal starten, z. B. `[p]giveaway start 1d 2 Discord Nitro` | Manager |
| `[p]giveaway end <id>` | Vorzeitig beenden und sofort auslosen | Manager |
| `[p]giveaway reroll <id> [@nutzer]` | Neu auslosen – alle Gewinner oder nur `@nutzer` ersetzen | Manager |
| `[p]giveaway cancel <id>` | Abbrechen (ohne Auslosung) | Manager |
| `[p]giveaway list` | Alle Gewinnspiele des Servers | Manager |
| `[p]giveaway managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen (Umschalter) | Server verwalten |
| `[p]giveaway language <de\|en>` | Sprache setzen | Server verwalten |

**Manager** = Bot-Owner, „Server verwalten“/Administrator oder eine der Manager-Rollen. Alias: `[p]gewinnspiel`.
Alle Befehle gibt es auch als Slash-Befehl (`/giveaway …`). Rollen-Regeln, Bonus-Lose und Ende per Datum
stellt man im Dashboard ein.

## Dashboard

Seite **Gewinnspiele** (`/cogs/giveaways`, Icon Geschenk):

- **Laufend** / **Beendet** – Tabellen mit Suche; Aktionen *Details*, *Beenden*, *Abbrechen*, *Neu auslosen*,
  *Eintrag entfernen* (jeweils mit Bestätigung).
- **Details** (`?gw=<id>`) – alle Daten, Link zur Nachricht, Gewinner (einzeln neu auslosen) und die
  Teilnehmerliste mit aktuellen Losen und Status („gültig“, fehlende Voraussetzung, „nicht mehr auf dem Server“).
- **Neues Gewinnspiel** – Preis, Beschreibung, Kanal, Gewinner, Ende (Datum/Uhrzeit **oder** Dauer), Regeln und
  Bonus-Lose. Bei Eingabefehlern bleiben die Eingaben erhalten.
- **Einstellungen** – Sprache, Zeitzone, Embed-Farbe, Aufbewahrung, Manager-Rollen, Schalter
  **„Im Mitglieder-Bereich anzeigen“** (Standard an).

### Rechte im Dashboard

| Stufe | Darf |
|---|---|
| Ansehen | alles sehen (laufende/beendete Gewinnspiele, Teilnehmer, Einstellungen), nichts ändern |
| **Bedienen** | Tagesgeschäft: Gewinnspiel **starten**, **beenden & auslosen**, **neu auslosen** (alle oder einzeln), **abbrechen**, beendete Einträge **entfernen** |
| Bearbeiten | zusätzlich Einstellungen (Sprache, Zeitzone, Farbe, Aufbewahrung), **Manager-Rollen** und den Schalter „Im Mitglieder-Bereich anzeigen“ |

Die Stufen vergibt der Bot-Owner unter *Verwaltung → Zugriff & Rollen* (je Server und Rolle); der Bot-Owner selbst darf immer alles.

## Mein Bereich: „Gewinnspiele“ (für Mitglieder)

Ist der Mitglieder-Bereich eingeschaltet (`[p]webcore portal on`), finden Mitglieder unter
**Mein Bereich → Gewinnspiele** (`/me/gewinnspiele`):

- **Laufend:** alle laufenden Gewinnspiele aus Kanälen, die sie in Discord lesen können – mit eigenem Status
  („Du nimmst teil – 3 Lose“ bzw. welche Voraussetzung fehlt) und großem Button **Teilnehmen**/**Austreten**.
  Dahinter steckt **dieselbe Funktion wie beim Discord-Button** (gleiche Regeln); die Discord-Nachricht wird
  genauso aktualisiert.
- **Meine Gewinne:** eigene gewonnene Gewinnspiele.
- Namen anderer Teilnehmer werden nie gezeigt. Gewinnspiele in unsichtbaren Kanälen lassen sich auch per
  manipuliertem Formular nicht ansprechen.

## Datenspeicherung

Pro Gewinnspiel: Preis, Beschreibung, Kanal/Nachricht, Regeln, Discord-IDs und Anzeigenamen der Teilnehmenden
mit Beitrittszeit, Gewinner-IDs (inkl. ersetzter) und die ID der startenden Person. `red_delete_data_for_user`
entfernt Teilnahmen und Gewinner-Einträge und setzt die Veranstalter-ID auf 0.
