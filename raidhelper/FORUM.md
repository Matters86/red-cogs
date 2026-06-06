# 🛡️ RaidHelper

Mehrsprachiger Raid-Planer für Red – Anmeldungen wie bei **raid-helper.dev**, direkt im eigenen Bot. Der Bot postet ein Embed mit **Live-Roster**, Mitglieder melden sich per **Klassen-Dropdown** an, wählen ihre **Spec** (wird gemerkt) und landen automatisch in der passenden Rolle (Tank/Heiler/Nahkampf/Fernkampf). **Deutsch ist Standard**, die Sprache ist pro Server umschaltbar.

**Installation**
```
[p]repo add red-cogs <github-url>
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
- Verwaltung komplett über das WebCore-Dashboard
- Persistente Buttons (überstehen Neustarts)

**Spiel-IDs:** `wow_retail`, `wow_classic`, `wow_wotlk`

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]raid create <datum> <zeit> <titel>` | Event im Standard-Kanal/-Spiel anlegen. | Manager / Manage Server |
| `[p]raid quickcreate <spiel> <datum> <zeit> [#kanal] <titel>` | Event mit Spiel und Kanal direkt anlegen. | Manager / Manage Server |
| `[p]raid list` | Alle Events des Servers auflisten. | Manager / Manage Server |
| `[p]raid close <id>` | Anmeldung schließen. | Manager / Manage Server |
| `[p]raid reopen <id>` | Anmeldung wieder öffnen. | Manager / Manage Server |
| `[p]raid delete <id>` | Event samt Nachricht löschen. | Manager / Manage Server |
| `[p]raid add <id> <mitglied> <klasse> <spec>` | Mitglied manuell eintragen. | Manager / Manage Server |
| `[p]raid remove <id> <mitglied>` | Mitglied aus einem Event entfernen. | Manager / Manage Server |
| `[p]raid export <id>` | Anmeldungen als CSV exportieren. | Manager / Manage Server |
| `[p]raidset language <de\|en>` | Sprache setzen. | Admin / Manage Server |
| `[p]raidset game <spiel-id>` | Standard-Spiel setzen. | Admin / Manage Server |
| `[p]raidset channel <#kanal>` | Standard-Anmelde-Kanal setzen. | Admin / Manage Server |
| `[p]raidset managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen. | Admin / Manage Server |
| `[p]raidset timezone <zone>` | Anzeige-Zeitzone setzen (z. B. `Europe/Berlin`). | Admin / Manage Server |
| `[p]raidset reminders <true\|false>` | Erinnerungen an-/ausschalten. | Admin / Manage Server |
| `[p]raidset icons` | Zeigt, welche Klasse welches Icon hat. | Admin / Manage Server |
| `[p]raidset specicon <klasse> <spec> <emoji>` | Icon einer Spezialisierung manuell setzen. | Admin / Manage Server |
| `[p]raidset clearspecicon <klasse> <spec>` | Icon einer Spezialisierung entfernen. | Admin / Manage Server |
| `[p]raidset uploadicons` | Angehängte Bilder als Spec-Icons hochladen (Dateiname = klasse_spec). | Admin / Manage Server |
| `[p]raidset settings` | Aktuelle Einstellungen anzeigen. | Admin / Manage Server |
| `[p]raidset dashboard` | Hinweis zur Dashboard-Seite. | Admin / Manage Server |

**Beispiel**
```
[p]raidset channel #raids
[p]raid create 13.06.2026 20:00 Mythic Undermine
```

Verwaltung ist außerdem komplett über das **WebCore-Dashboard** möglich (Seite „Raidplaner" unter `/cogs/raidhelper`): Einstellungen, Event-Tabelle mit Aktionen und Roster-Ansicht.
