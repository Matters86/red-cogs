# Tickets

Mehrsprachiges Support-Ticketsystem für Red. Nutzer öffnen Tickets über ein **Panel**
(Buttons oder Dropdown), optional mit einem **Modal** (bis zu 5 Fragen). Tickets entstehen
wahlweise als **eigener Kanal**, **privater Thread** oder **Forum-Beitrag**.

- Getrennte Rollen: Support (mitlesen & übernehmen), Admin (volle Rechte), View (nur lesen),
  Ping (Benachrichtigung), Inhaber-Rolle (automatisch an den Ersteller).
- Übernehmen, sperren, schließen, wieder öffnen, löschen, umbenennen, Mitglieder verwalten,
  Inhaber wechseln, Limit für offene Tickets pro Nutzer.
- **Mehrsprachig** – Deutsch ist Standard, pro Server umschaltbar; alle sichtbaren Texte lassen
  sich zusätzlich frei überschreiben.
- **HTML-Transcripts** beim Schließen, im Dashboard lesbar, plus **Statistik**.
- **Persistente Buttons** – Panels und Steuerleisten funktionieren auch nach einem Bot-Neustart.

Die Buttons (Panels, Schließen/Übernehmen/Sperren) decken den Alltag ab; die Befehle unten sind
für Sonderfälle. Konfiguriert wird am bequemsten über das **Dashboard**.

## Installation

```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs tickets
[p]load tickets
```

Voraussetzung für die Verwaltung im Browser ist ein geladenes **WebCore** (siehe
[`webcore/README.md`](../webcore/README.md)).

## Befehle

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

## Dashboard

Ist `webcore` geladen, erscheint der Tab **Tickets**. Dort lassen sich pro Server einstellen:

- **Einstellungen** – Sprache, Ticket-Typ, alle Rollen, Kategorien/Thread-Basis/Forum,
  Log-Kanal, Limit, Kanalname-Vorlage, Bestätigungen sowie eigene Texte (überschreiben die
  Sprachpakete).
- **Panels** – bestehende Panels auflisten/löschen und neue erstellen (inkl. Gründe und
  Modal-Fragen); das Panel wird direkt in den gewählten Kanal gepostet.
- **Transcripts** – gespeicherte Ticket-Verläufe als eigene Seite öffnen.
- **Statistik** – offene/geschlossene Tickets, Ø Laufzeit und Übernahmen je Support-Mitglied.

Hinweis: Read-only **View-Rollen** wirken vor allem im **Kategorie-Modus**. In Threads/Foren wird
der Zugriff über Thread-Mitgliedschaft bzw. Kanalrechte gesteuert (Support-Rollen brauchen dort
ggf. die Berechtigung, private Threads zu sehen).
