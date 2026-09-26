# 🛡️ RaidHelper

Mehrsprachiger Raid-Planer für Red – Anmeldungen wie bei **raid-helper.dev**, direkt im eigenen Bot. Der Bot postet ein Embed mit **Live-Roster**, Mitglieder melden sich per **Klassen-Dropdown** an, wählen ihre **Spec** (wird gemerkt) und landen automatisch in der passenden Rolle (Tank/Heiler/Nahkampf/Fernkampf). **Deutsch ist Standard**, die Sprache ist pro Server umschaltbar.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs raidhelper
[p]load raidhelper
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet.

**Funktionen**
- Anmeldung per Klassen-Dropdown + Spec-Auswahl, dazu Bank/Spät/Vielleicht/Abwesend
- Live-Roster nach Rolle, fortlaufende Nummerierung, Spec-Gedächtnis pro Nutzer
- Limits gesamt und pro Rolle, automatischer Anmeldeschluss
- Erinnerungen 60 & 15 Min vorher (optional per DM), wiederkehrende Events
- Teilnahme-Statistik, CSV-Export
- Drei WoW-Vorlagen (Retail/Classic/WotLK) mit deutschen Klassen- und Spec-Namen
- Eigene Spec-Icons je Spezialisierung (Application-Emojis), bequem per Dashboard hochladbar
- Events direkt im WebCore-Dashboard anlegen und bearbeiten (Datum/Uhrzeit per Kalender, Kanal, Limits, Wiederholung) – die Discord-Nachricht wird automatisch gepostet bzw. aktualisiert
- Persistente Buttons (überstehen Neustarts)
- Anmeldung auch über die Website („Mein Bereich → Raids“)

**Spiel-IDs:** `wow_retail`, `wow_classic`, `wow_wotlk`

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]raid create <datum> <zeit> <titel>` | Event im Standard-Kanal/-Spiel anlegen. | Manager / Manage Server |
| `[p]raid quickcreate <spiel> <#kanal> <datum> <zeit> <titel>` | Event mit Spiel und Kanal direkt anlegen. | Manager / Manage Server |
| `[p]raid list` | Alle Events des Servers auflisten. | Manager / Manage Server |
| `[p]raid close <id>` | Anmeldung schließen. | Manager / Manage Server |
| `[p]raid reopen <id>` | Anmeldung wieder öffnen. | Manager / Manage Server |
| `[p]raid delete <id>` | Event samt Nachricht löschen. | Manager / Manage Server |
| `[p]raid add <id> <mitglied> <klasse> <spec>` | Mitglied manuell eintragen. | Manager / Manage Server |
| `[p]raid remove <id> <mitglied>` | Mitglied aus einem Event entfernen. | Manager / Manage Server |
| `[p]raid export <id>` | Anmeldungen als CSV exportieren. | Manager / Manage Server |
| `[p]raid title <id> <titel>` | Titel ändern. | Manager / Manage Server |
| `[p]raid time <id> <datum> <zeit>` | Termin verschieben. | Manager / Manage Server |
| `[p]raid description <id> [text]` | Beschreibung setzen/entfernen. | Manager / Manage Server |
| `[p]raid deadline <id> <datum> <zeit>` | Anmeldeschluss setzen. | Manager / Manage Server |
| `[p]raid recurrence <id> <none\|daily\|weekly\|biweekly>` | Wiederholung setzen. | Manager / Manage Server |
| `[p]raid maxsignups <id> <anzahl>` | Maximale Anmeldungen (0 = unbegrenzt). | Manager / Manage Server |
| `[p]raid rolelimit <id> <rolle> <anzahl>` | Limit pro Rolle (0 = kein Limit). | Manager / Manage Server |
| `[p]raidset language <de\|en>` | Sprache setzen. | Admin / Manage Server |
| `[p]raidset game <spiel-id>` | Standard-Spiel setzen. | Admin / Manage Server |
| `[p]raidset channel <#kanal>` | Standard-Anmelde-Kanal setzen. | Admin / Manage Server |
| `[p]raidset managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen. | Admin / Manage Server |
| `[p]raidset timezone <zone>` | Anzeige-Zeitzone setzen (z. B. `Europe/Berlin`). | Admin / Manage Server |
| `[p]raidset reminders <true\|false>` | Erinnerungen an-/ausschalten. | Admin / Manage Server |
| `[p]raidset cleanup <tage>` | Abgeschlossene Events nach N Tagen löschen (Standard 30, 0 = aus). | Admin / Manage Server |
| `[p]raidset icons` | Zeigt, welche Klasse welches Icon hat. | Admin / Manage Server |
| `[p]raidset specicon <klasse> <spec> <emoji>` | Icon einer Spezialisierung manuell setzen (botweit). | Bot-Owner |
| `[p]raidset clearspecicon <klasse> <spec>` | Icon einer Spezialisierung entfernen (botweit). | Bot-Owner |
| `[p]raidset uploadicons` | Angehängte Bilder als Spec-Icons hochladen (Dateiname = klasse_spec, botweit). | Bot-Owner |
| `[p]raidset settings` | Aktuelle Einstellungen anzeigen. | Admin / Manage Server |
| `[p]raidset dashboard` | Hinweis zur Dashboard-Seite. | Admin / Manage Server |

**Beispiel**
```
[p]raidset channel #raids
[p]raid create 13.06.2026 20:00 Mythic Undermine
```

Verwaltung ist außerdem komplett über das **WebCore-Dashboard** möglich (Seite „Raidplaner" unter `/cogs/raidhelper`): Reiter **Neues Event** (Event anlegen und posten – gleiche Prüfungen wie `[p]raid create`), Event-Tabelle mit **Bearbeiten**, Schließen/Öffnen, Löschen und Roster-Ansicht, dazu alle Einstellungen. Wer darf, legst du als Bot-Owner unter „Zugriff & Rollen“ fest.

**Anmeldung über die Website**
Mitglieder melden sich auch im Browser an: WebCore → **Mein Bereich → Raids** (`/me/raids`).
- Einschalten: Bot-Owner aktiviert den Mitglieder-Bereich unter „Zugriff & Rollen“ (oder `[p]webcore portal on`); im Raidplaner unter *Einstellungen → Mitglieder-Bereich* „Im Mitglieder-Bereich anzeigen“ (Standard: an).
- Zu sehen: kommende Events aus Kanälen, die das Mitglied in Discord lesen darf – Termin (Server-Zeitzone + „in 3 Tagen“), Belegung gesamt/je Rolle, Status offen/voll/geschlossen/Anmeldeschluss, eigener Status, Link „In Discord öffnen“, Detailansicht mit Roster.
- Aktionen: anmelden (Klasse & Spec), Spec wechseln, Bank/Spät/Vielleicht/Abwesend, abmelden.
- Gleiche Regeln und Meldungen wie die Buttons (Limits, Anmeldeschluss, geschlossen); die Discord-Nachricht wird sofort aktualisiert.
