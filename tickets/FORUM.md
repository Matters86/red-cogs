# 🎟️ Tickets

Mehrsprachiges Support-Ticketsystem für Red – mit Panels (Buttons/Dropdown), optionalem Modal,
Tickets als Kanal **oder** Thread **oder** Forum-Beitrag, HTML-Transcripts, Statistik und
Verwaltung über das WebCore-Dashboard. **Deutsch ist Standard**, die Sprache ist pro Server
umschaltbar und alle Texte sind überschreibbar.

**Installation**
```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs tickets
[p]load tickets
```

**Funktionen**
- Panels mit Buttons oder Dropdown, Modal mit bis zu 5 Fragen
- Rollen: Support, Admin, View (nur lesen), Ping, Inhaber-Rolle
- Übernehmen, Sperren, Schließen, Wiederöffnen, Löschen, Umbenennen, Mitglieder verwalten
- Limit für offene Tickets pro Nutzer, Schließen-Bestätigung
- HTML-Transcripts + Statistik im Dashboard
- Persistente Buttons (überstehen Neustarts)

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]ticket close [grund]` | Schließt das aktuelle Ticket. | Ersteller (falls erlaubt) / Support |
| `[p]ticket open` | Öffnet ein archiviertes Ticket wieder. | Support |
| `[p]ticket claim` | Übernimmt das aktuelle Ticket. | Support |
| `[p]ticket unclaim` | Gibt das Ticket wieder frei. | Support |
| `[p]ticket add <mitglied>` | Fügt ein Mitglied hinzu. | Support |
| `[p]ticket remove <mitglied>` | Entfernt ein Mitglied. | Support |
| `[p]ticket rename <name>` | Benennt das Ticket um. | Support |
| `[p]ticket owner <mitglied>` | Ändert den Inhaber. | Support |
| `[p]ticket delete` | Löscht das Ticket endgültig (Transcript wird gesichert). | Admin |
| `[p]ticket list [open\|closed\|all]` | Listet Tickets. | Support |
| `[p]ticketset language <code>` | Sprache setzen (z. B. `de`, `en`). | Admin / Manage Server |
| `[p]ticketset type <category\|thread\|forum>` | Speicherort der Tickets. | Admin / Manage Server |
| `[p]ticketset support <rolle>` | Support-Rolle an/aus. | Admin / Manage Server |
| `[p]ticketset admin <rolle>` | Admin-Rolle an/aus. | Admin / Manage Server |
| `[p]ticketset view <rolle>` | View-Rolle (nur lesen) an/aus. | Admin / Manage Server |
| `[p]ticketset ping <rolle>` | Ping-Rolle an/aus. | Admin / Manage Server |
| `[p]ticketset ownerrole [rolle]` | Inhaber-Rolle setzen/entfernen. | Admin / Manage Server |
| `[p]ticketset category <offen> [geschlossen]` | Kategorien festlegen. | Admin / Manage Server |
| `[p]ticketset threadbase <kanal>` | Basis-Kanal für den Thread-Modus. | Admin / Manage Server |
| `[p]ticketset forum <kanal>` | Forum-Kanal für den Forum-Modus. | Admin / Manage Server |
| `[p]ticketset logchannel <kanal>` | Log-Kanal setzen. | Admin / Manage Server |
| `[p]ticketset maxopen <zahl>` | Max. offene Tickets pro Nutzer. | Admin / Manage Server |
| `[p]ticketset panel <kanal> [titel]` | Schnell ein einfaches Panel posten. | Admin / Manage Server |
| `[p]ticketset settings` | Aktuelle Einstellungen anzeigen. | Admin / Manage Server |
| `[p]ticketset dashboard` | Hinweis auf das Dashboard. | Admin / Manage Server |

**Dashboard:** Tab **Tickets** → Einstellungen, Panels, Transcripts und Statistik pro Server.
