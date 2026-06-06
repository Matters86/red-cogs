# 📊 Poll

Mehrsprachiger Umfrage-Cog für Red – Abstimmungen direkt im eigenen Bot, per Befehl **oder** komplett über das **WebCore-Dashboard**. Der Bot postet ein Embed mit **Live-Ergebnis** (Balken & Prozente); abgestimmt wird per **Button** (ein Button je Option, mit Zähler). Pro Umfrage wählbar: Einzel-/Mehrfachauswahl, anonym/öffentlich und optionale Laufzeit mit Auto-Ende. **Deutsch ist Standard**, die Sprache ist pro Server umschaltbar.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs poll
[p]load poll
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet.

**Funktionen**
- Abstimmen per Button, Stimme jederzeit änder-/zurücknehmbar
- Live-Ergebnis im Embed (Balken, Prozente, Teilnehmerzahl)
- Einzel- oder Mehrfachauswahl, anonym oder öffentlich – pro Umfrage wählbar
- Optionale Laufzeit mit automatischem Ende und Ergebnis-Ansage
- Erstellrechte pro Server (alle Mitglieder oder Mods/Manager)
- CSV-Export der Ergebnisse
- Umfragen anlegen & verwalten komplett über das Dashboard
- Persistente Buttons (überstehen Neustarts)

**Dauer-Format:** Zahl + Einheit (`s`/`m`/`h`/`d`/`w`), kombinierbar, z. B. `90m`, `2h`, `1d12h`.

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]poll quick <frage> \| <opt1> \| <opt2> …` | Schnelle Umfrage mit Server-Standards. | je nach `allowcreate` |
| `[p]poll create frage: … optionen: A \| B [dauer: 2h] [mehrfach: true] [anonym: false]` | Umfrage mit allen Optionen anlegen. | je nach `allowcreate` |
| `[p]poll list` | Alle Umfragen des Servers auflisten. | alle |
| `[p]poll close <id>` | Umfrage schließen (zeigt Endergebnis). | eigene / Manager |
| `[p]poll reopen <id>` | Umfrage wieder öffnen (entfernt Zeitlimit). | eigene / Manager |
| `[p]poll delete <id>` | Umfrage samt Nachricht löschen. | eigene / Manager |
| `[p]poll results <id>` | Aktuellen Ergebnis-Stand posten. | alle |
| `[p]poll export <id>` | Ergebnisse als CSV exportieren. | eigene / Manager |
| `[p]pollset language <de\|en>` | Sprache setzen. | Admin / Manage Server |
| `[p]pollset allowcreate <everyone\|manager>` | Wer Umfragen erstellen darf. | Admin / Manage Server |
| `[p]pollset managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen. | Admin / Manage Server |
| `[p]pollset multiple <true\|false>` | Standard-Mehrfachauswahl an/aus. | Admin / Manage Server |
| `[p]pollset anonymous <true\|false>` | Standard-Sichtbarkeit (an = anonym). | Admin / Manage Server |
| `[p]pollset maxoptions <2–25>` | Maximale Optionen pro Umfrage. | Admin / Manage Server |
| `[p]pollset settings` | Aktuelle Einstellungen anzeigen. | Admin / Manage Server |
| `[p]pollset dashboard` | Hinweis zur Dashboard-Seite. | Admin / Manage Server |

**Beispiel**
```
[p]poll quick Beste Pizza? | Margherita | Salami | Hawaii
[p]poll create frage: Bester Patch-Tag? optionen: Montag | Mittwoch | Freitag dauer: 1d mehrfach: false
```

Verwaltung ist außerdem komplett über das **WebCore-Dashboard** möglich (Seite „Umfragen" unter `/cogs/poll`): Einstellungen, Umfragen anlegen, Tabelle mit Aktionen und Ergebnis-Ansicht.
