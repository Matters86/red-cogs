# 📣 Changelog

Server-Updates direkt im eigenen Bot: Team-Mitglieder füllen ein **Modal** aus (`/changelog`), der Bot postet daraus ein **einheitliches Update-Embed** im festgelegten Kanal – optional mit einem Rollen-Ping davor. Ziel-Kanal, Poster-Rollen, Ping-Rolle, Farbe, Sprache und die wählbaren Kategorien werden **pro Server** gesetzt (per Befehl oder komplett über das **WebCore-Dashboard**). **Deutsch ist Standard**, die Sprache ist pro Server umschaltbar.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs changelog
[p]load changelog
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet. Falls nötig einmalig `[p]slash enable changelog` und `[p]slash sync`.

**Funktionen**
- Posten per Modal – Felder Titel/Neu/Geändert/Fixes/Hinweis, kein manuelles Embed-Basteln
- Einheitliches Embed mit Bullet-Listen, Kategorie-Emoji und Fußzeile (Datum + Name)
- Kategorie pro Changelog wählbar (z. B. 🚗/🌾/⚙️), Liste pro Server konfigurierbar
- Fester Ziel-Kanal pro Server + serverseitige Rechteprüfung (Poster-Rollen/Admin)
- Optionaler `@Updates`-Ping als separate Nachricht vor dem Embed
- Historie aller Posts inkl. Detailansicht und Löschfunktion im Dashboard

**Schnellstart**
```
[p]changelogset channel #server-news
[p]changelogset roleadd @Discord-Team
[p]changelogset pingrole @Updates
[p]changelogset ping on
```

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `/changelog [kategorie]` | Öffnet das Formular und postet das Update-Embed. | Poster-Rollen / Admin |
| `[p]changelogset channel <#kanal>` | Ziel-Kanal festlegen. | Admin / Manage Server |
| `[p]changelogset roleadd <rolle>` | Poster-Rolle hinzufügen. | Admin / Manage Server |
| `[p]changelogset roleremove <rolle>` | Poster-Rolle entfernen. | Admin / Manage Server |
| `[p]changelogset pingrole <rolle>` | Ping-Rolle festlegen. | Admin / Manage Server |
| `[p]changelogset ping <on\|off>` | Ping vor dem Embed an-/ausschalten. | Admin / Manage Server |
| `[p]changelogset color <#hex>` | Embed-Farbe setzen (z. B. `#3DDC97`). | Admin / Manage Server |
| `[p]changelogset language <de\|en>` | Sprache setzen. | Admin / Manage Server |
| `[p]changelogset catadd <emoji> <bezeichnung>` | Wählbare Kategorie hinzufügen. | Admin / Manage Server |
| `[p]changelogset catremove <nummer>` | Kategorie per Nummer entfernen. | Admin / Manage Server |
| `[p]changelogset cats` | Wählbare Kategorien anzeigen. | Admin / Manage Server |
| `[p]changelogset show` | Aktuelle Einstellungen anzeigen. | Admin / Manage Server |
| `[p]changelogset history [anzahl]` | Letzte Changelogs auflisten (Standard: 5). | Admin / Manage Server |

**Dashboard:** Seite **Changelog** unter `/cogs/changelog` – Einstellungen, Historie-Tabelle (mit „Zur Nachricht" und Löschen) und Detailansicht je Changelog.

**Hinweis zum Formular:** Das Modal hat genau fünf Felder (Discord-Limit). Mindestens eines von *Neu/Geändert/Fixes* muss ausgefüllt sein; mehrzeilige Eingaben werden automatisch zu Bullet-Listen.
