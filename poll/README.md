# Poll

Mehrsprachiger Umfrage-Cog für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – Abstimmungen direkt im eigenen Bot, per Befehl **oder** komplett über das WebCore-Dashboard.

Der Bot postet ein **Embed mit Live-Ergebnis** (Balken und Prozente). Abgestimmt wird per **Button** – ein Button je Option, mit Stimmenzähler. Pro Umfrage frei wählbar: Einzel- oder Mehrfachauswahl, anonym oder öffentlich und eine optionale Laufzeit mit automatischem Ende.

## Funktionen

- **Abstimmen per Klick** – ein Button je Option, Stimme jederzeit änder- oder zurücknehmbar.
- **Live-Ergebnis** im Embed: Balken, Prozente und Teilnehmerzahl, aktualisiert sich bei jeder Stimme.
- **Einzel- oder Mehrfachauswahl** – pro Umfrage wählbar, mit Server-Standard.
- **Anonym oder öffentlich** – pro Umfrage wählbar; anonym zeigt nur Zähler, keine Namen.
- **Laufzeit & Auto-Ende** – optionale Dauer (`30m`, `2h`, `1d`, `1d12h`); endet automatisch und sagt das Ergebnis an.
- **Erstellrechte einstellbar** – alle Mitglieder oder nur Mods/Manager (per Server).
- **CSV-Export** der Ergebnisse (bei anonymen Umfragen nur Zähler).
- **Mehrsprachig** – Deutsch als Standard, pro Server umschaltbar (aktuell `de`, `en`).
- **Dashboard** – Umfragen anlegen, einstellen, schließen/löschen und Ergebnisse einsehen.
- **Persistente Buttons** – funktionieren auch nach einem Bot-Neustart.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs poll
[p]load poll
```

## Schnellstart

```
[p]pollset language de            # Sprache (optional, Standard de)
[p]pollset allowcreate manager    # wer erstellen darf (Standard: Mods/Manager)
[p]poll quick Beste Pizza? | Margherita | Salami | Hawaii
```

Oder mit allen Optionen:

```
[p]poll create frage: Beste Pizza? optionen: Margherita | Salami | Hawaii dauer: 2h mehrfach: true anonym: false
```

Als Slash-Befehl (`/poll create`) erscheinen `frage`, `optionen`, `dauer`, `mehrfach` und `anonym` als eigene Felder.

## Befehle

Erstellen/Verwalten (`poll`) – Erstellen ist auf die per `allowcreate` gesetzte Gruppe beschränkt; Schließen/Öffnen/Löschen/Export erfordert die eigene Umfrage, eine Manager-Rolle oder „Server verwalten".

| Befehl | Beschreibung |
|---|---|
| `[p]poll quick <frage> \| <opt1> \| <opt2> …` | Schnelle Umfrage mit Server-Standards |
| `[p]poll create frage: … optionen: A \| B [dauer: 2h] [mehrfach: true] [anonym: false]` | Umfrage mit allen Optionen anlegen |
| `[p]poll list` | Alle Umfragen des Servers auflisten |
| `[p]poll close <id>` | Umfrage schließen (zeigt Endergebnis) |
| `[p]poll reopen <id>` | Umfrage wieder öffnen (entfernt das Zeitlimit) |
| `[p]poll delete <id>` | Umfrage samt Nachricht löschen |
| `[p]poll results <id>` | Aktuellen Ergebnis-Stand posten |
| `[p]poll export <id>` | Ergebnisse als CSV exportieren |

Einstellungen (`pollset`) – erfordern „Server verwalten" oder Admin.

| Befehl | Beschreibung |
|---|---|
| `[p]pollset language <de\|en>` | Sprache setzen |
| `[p]pollset allowcreate <everyone\|manager>` | Wer Umfragen erstellen darf |
| `[p]pollset managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen (Umschalter) |
| `[p]pollset multiple <true\|false>` | Standard-Mehrfachauswahl an/aus |
| `[p]pollset anonymous <true\|false>` | Standard-Sichtbarkeit (an = anonym) |
| `[p]pollset maxoptions <2–25>` | Maximale Optionen pro Umfrage |
| `[p]pollset settings` | Aktuelle Einstellungen anzeigen |
| `[p]pollset dashboard` | Hinweis zur Dashboard-Seite |

Dauer-Format: Zahl + Einheit, kombinierbar – `s`, `m`, `h`, `d`, `w` (z. B. `90m`, `2h`, `1d12h`).

## Abstimmen

Jede Option ist ein Button mit Stimmenzähler. Bei **Einzelauswahl** ersetzt ein Klick die bisherige Stimme; ein erneuter Klick auf dieselbe Option zieht sie zurück. Bei **Mehrfachauswahl** schaltet jeder Klick die jeweilige Option an oder aus. Die Antwort erscheint nur für die abstimmende Person (ephemer), das Embed aktualisiert sich für alle.

## Dashboard

Die Seite **Umfragen** erscheint nach dem Laden automatisch im WebCore-Dashboard unter `/cogs/poll`. Dort gibt es:

- Statistik-Kacheln (aktive Umfragen, Stimmen gesamt, Standard-Sichtbarkeit),
- ein Einstellungs-Formular (Sprache, Erstellrechte, max. Optionen, Standard für Mehrfach/anonym, Manager-Rollen, Text-Overrides),
- ein Formular **„Neue Umfrage"** (Frage, Optionen, Kanal, Laufzeit, Mehrfach/anonym) – postet die Umfrage direkt in den gewählten Kanal,
- eine Umfragen-Tabelle mit Aktionen (Schließen/Öffnen/Löschen),
- eine Ergebnis-Ansicht pro Umfrage (Balken; bei nicht-anonymen Umfragen mit Namensliste je Option),
- unter *Einstellungen* den Schalter **„Im Mitglieder-Bereich anzeigen“** (Standard: an).

### Rechte im Dashboard

| Stufe | Darf |
|---|---|
| Ansehen | alles sehen (Umfragen, Ergebnisse, Einstellungen), nichts ändern |
| **Bedienen** | Tagesgeschäft: Umfrage **anlegen & posten**, **schließen/öffnen**, **löschen** |
| Bearbeiten | zusätzlich Einstellungen (Sprache, Erstellrechte, max. Optionen, Standardwerte), **Manager-Rollen**, eigene Texte und den Schalter „Im Mitglieder-Bereich anzeigen“ |

Die Stufen vergibt der Bot-Owner unter *Verwaltung → Zugriff & Rollen* (je Server und Rolle); der Bot-Owner selbst darf immer alles.

## Mein Bereich: „Umfragen“ (für Mitglieder)

Hat der Bot-Owner den Mitglieder-Bereich für den Server eingeschaltet (*Verwaltung → Zugriff & Rollen*
bzw. `[p]webcore portal on`), finden normale Mitglieder unter **Mein Bereich → Umfragen** (`/me/umfragen`):

- **Laufend:** alle offenen Umfragen aus Kanälen, die sie in Discord lesen können – als Karten mit
  Ergebnis-Balken (wie im Embed) und einem großen Button je Option. Abstimmen, Stimme ändern und
  zurückziehen funktioniert **genau wie mit den Discord-Buttons** (gleiche Funktion im Code:
  Einzelauswahl ersetzt bzw. zieht per erneutem Klick zurück, Mehrfachauswahl schaltet je Option;
  geschlossene/beendete Umfragen lehnen ab). Die Umfrage-Nachricht in Discord aktualisiert sich sofort.
- **Beendet:** Umfragen, die in den letzten 14 Tagen geschlossen wurden oder abgelaufen sind, mit Endergebnis (🏆).
- Namen von Abstimmenden werden nie gezeigt (wie im Embed), nur die eigene Stimme ist markiert.
  Ungepostete Umfragen und Umfragen in Kanälen ohne Leserecht bleiben unsichtbar und lassen sich auch
  per manipuliertem Formular nicht abstimmen.
- Der Schalter „Im Mitglieder-Bereich anzeigen“ in den Einstellungen blendet die Seite pro Server aus.

## Datenspeicherung

Pro Umfrage werden Frage, Optionen, Stimmen und der Zeitpunkt des Schließens (`closed_ts`, für „Beendet“ im Mitglieder-Bereich) gespeichert; je Stimme die Discord-ID, der Anzeigename und die gewählten Optionen. Bei anonymen Umfragen werden Namen nirgends angezeigt. Daten werden beim Löschen einer Umfrage, beim Entfernen des Cogs oder beim Verlassen des Servers entfernt.
