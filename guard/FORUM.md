# 🛡️ Guard

Schutz-Cog für Red – **Spamschutz**, **Honeypot** und **Raid-Notmodus** in einem, mehrsprachig und komplett über das **WebCore-Dashboard** steuerbar. **Ohne externe pip-Abhängigkeiten.** Aktionen erfolgen **ohne DM** an Ausgelöste, landen in einem Log-Kanal (optional zusätzlich in Reds `modlog`) und als Verlauf im Dashboard. **Deutsch ist Standard**, pro Server umschaltbar.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs guard
[p]load guard
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet.

**Funktionen**
- **Honeypot** – Köder-Kanal; wer dort postet, wird automatisch entfernt (Bann/Softban/Kick/Timeout wählbar). Kanal neu anlegen oder bestehenden markieren.
- **Spamschutz mit Punktesystem** – Heuristiken vergeben Punkte, Schwellen lösen eine Eskalationsleiter aus: **verwarnen → Timeout → Kick → Bann**. Punkte verfallen nach einstellbarer Zeit.
- **Heuristiken** – Rate, Wiederholungen (auch kanalübergreifend), Massen-Erwähnungen, Einladungslinks, optional alle Links, Anhang-/Emoji-/Zeilen-Walls, sehr neue Konten (als Verstärker).
- **Raid-Notmodus** – zu viele Beitritte oder ein Befehl → Slowmode, Einladungen pausieren (falls unterstützt), neue Beitritte automatisch behandeln. Übersteht Neustarts, endet automatisch.
- **Ausnahmen** – Owner, Admins, Bot selbst und Reds Immunität (`[p]immune`) immer ausgenommen; dazu eigene Whitelist (Rollen/Kanäle/Nutzer).
- **Mehrsprachig** (`de`/`en`) und **voll per Dashboard** konfigurierbar (inkl. Verlauf und Notmodus-Schalter).

**Punktesystem (Standard)**

| Stufe | Schwelle | Aktion |
|---|---|---|
| Verwarnen | 3 | nur protokolliert |
| Timeout | 6 | Timeout |
| Kick | 9 | Kick |
| Bann | 12 | Bann + Nachrichten löschen |

Punkte je Treffer: Einladung 5, Erwähnungen 4, Rate/Wiederholung 3, Link/Wall/neues Konto 2. Neue Konten zählen nur zusätzlich, wenn ohnehin etwas auffällig war.

> **Honeypot-Tipp:** Kanal oben in der Liste platzieren, Bot-Rolle über die Mitglieder, Schreibrecht für `@everyone` lassen. Standard-Aktion ist **softban** (umstellbar).

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]guardset module <honeypot\|spam> <on\|off>` | Modul ein-/ausschalten. | Admin / Manage Server |
| `[p]guardset honeypot create [name]` | Honeypot-Kanal anlegen und aktivieren. | Admin / Manage Server |
| `[p]guardset honeypot set <kanal>` | Bestehenden Kanal als Honeypot markieren. | Admin / Manage Server |
| `[p]guardset honeypot disable` | Honeypot deaktivieren. | Admin / Manage Server |
| `[p]guardset honeypot action <ban\|softban\|kick\|timeout>` | Aktion bei Auslösung. | Admin / Manage Server |
| `[p]guardset logchannel [kanal]` | Log-Kanal setzen (ohne Angabe: entfernen). | Admin / Manage Server |
| `[p]guardset whitelistrole <rolle>` | Rolle ausnehmen (Umschalter). | Admin / Manage Server |
| `[p]guardset whitelistuser <nutzer>` | Nutzer ausnehmen (Umschalter). | Admin / Manage Server |
| `[p]guardset whitelistchannel <kanal>` | Kanal vom Spamschutz ausnehmen (Umschalter). | Admin / Manage Server |
| `[p]guardset language <de\|en>` | Sprache setzen. | Admin / Manage Server |
| `[p]guardset settings` | Einstellungen + Dashboard-Link. | Admin / Manage Server |
| `[p]lockdown on` | Notmodus sofort aktivieren. | Admin / Manage Server |
| `[p]lockdown off` | Notmodus beenden. | Admin / Manage Server |

**Dashboard:** Seite **Guard** (`/cogs/guard`) – Statistik, Notmodus-Schalter, alle Einstellungen und der Aktions-Verlauf.

Hinweis: `modlog`-Spiegelung ist standardmäßig an, greift aber nur bei eingerichtetem `modlog`. Es werden keine Nachrichteninhalte dauerhaft gespeichert, nur Aktions-Metadaten.
