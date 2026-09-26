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
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
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
  Sprachpakete; Platzhalter `{num}` und `{user}` in Titel und Begrüßungstext).
- **Panels** – bestehende Panels auflisten, bearbeiten, löschen und neue erstellen (inkl. Gründe
  und Modal-Fragen); das Panel wird direkt in den gewählten Kanal gepostet, Änderungen
  aktualisieren die bestehende Nachricht.
- **Team-Zuordnung je Grund** (im Panel-Editor) – jeder Grund kann eigene Team-Rollen,
  Ping-Rollen und eine eigene Kategorie bekommen. Tickets dieses Typs sehen dann nur dieses Team
  plus die Admin-Rollen; das Team darf sie auch übernehmen, sperren und schließen. Leer = globale
  Einstellungen. Tickets mit Grund heißen automatisch `<grund>-<nummer>` (Umlaute werden zu
  ae/oe/ue/ss).
- **Offene Tickets** (Übersicht) – Nummer, Inhaber, Grund, Öffnungszeit und Übernahme; **Schließen** mit
  Bestätigung wirkt wie der Button im Ticket (Transcript, Log, Inhaber-Rolle entfernen, archivieren bzw.
  löschen). Existiert der Kanal nicht mehr, entfernt „Schließen“ nur den verwaisten Eintrag.
- **Transcripts** – gespeicherte Ticket-Verläufe als eigene Seite öffnen.
- **Statistik** – offene/geschlossene Tickets, Ø Laufzeit und Übernahmen je Support-Mitglied.

### Rechte im Dashboard

| WebCore-Stufe | Darf |
|---|---|
| Ansehen | alles ansehen, Transcripts öffnen |
| **Bedienen** | zusätzlich **einzelne Tickets schließen** (Tagesgeschäft) |
| Bearbeiten | zusätzlich Einstellungen, Rollen (Support/Admin/Inhaber …), Texte, Panels anlegen/bearbeiten/löschen und die Team-Zuordnung je Grund |

Panels und Team-Zuordnung gelten als Einrichtung des Ticketsystems (Rollen, Fragen, Eingangskanäle) und
brauchen deshalb *Bearbeiten*.

### Mitglieder-Bereich: „Meine Tickets“

Hat der Bot-Owner in WebCore **Mein Bereich** für den Server eingeschaltet, finden normale Mitglieder
dort die Seite **Meine Tickets** (`/me/tickets`):

- **Offen** – eigene offene Tickets mit Grund, Öffnungszeitpunkt, Status (wartet / in Bearbeitung /
  gesperrt) und Button „In Discord öffnen“.
- **Verlauf** – eigene geschlossene Tickets; „Verlauf ansehen“ öffnet das Transcript in derselben
  Darstellung wie im Team-Dashboard.
- **Neues Ticket** – die Panels, die das Mitglied in Discord sehen kann (gepostet, Kanal lesbar), mit
  ihren Gründen und Fragen als Formular. Das Ticket entsteht über **dieselbe Logik wie der Discord-Button**
  (gleiches Limit „max. offene Tickets pro Nutzer“, gleiche Sperre gegen Doppelklicks, gleiche Kanäle,
  Rollen, Pings und Log-Einträge); danach gibt es einen Link zum neuen Kanal.

Angezeigt werden nur Tickets, die das Mitglied **erstellt** hat oder zu denen es per `[p]ticket add`
**hinzugefügt** wurde (wird ab dieser Version gespeichert, `[p]ticket remove` entfernt es wieder).
Fremde Ticket- oder Transcript-Nummern in der Adresse ergeben „nicht gefunden“.

Im Team-Dashboard unter **Einstellungen → Mitglieder-Bereich** (beide Standard **an**):

| Schalter | Wirkung |
|---|---|
| Im Mitglieder-Bereich anzeigen | Aus: die Seite zeigt nur „auf diesem Server nicht verfügbar“, Transcripts sind gesperrt. |
| Tickets über die Website öffnen erlauben | Aus: kein Reiter „Neues Ticket“, Anfragen werden abgelehnt. |

Hinweis: Read-only **View-Rollen** wirken vor allem im **Kategorie-Modus**. In Threads/Foren wird
der Zugriff über Thread-Mitgliedschaft bzw. Kanalrechte gesteuert (Support-Rollen brauchen dort
ggf. die Berechtigung, private Threads zu sehen).

## Datenspeicherung & Datenlöschung

Gespeichert werden pro Ticket Metadaten (Nummer, Discord-IDs von Inhaber, hinzugefügten Mitgliedern und
Übernehmer, Grund, Formular-Antworten, Zeitstempel), eine Übernahme-Statistik je Team-Mitglied sowie
HTML-Transcripts (Nachrichten, Anzeigenamen, Zeitpunkte, Anhang-Dateinamen). Neue Transcripts markieren
jede Nachricht intern mit der Nutzer-ID des Autors, damit sie sich bei einer Löschanfrage exakt zuordnen lässt.

Bei einer Datenlöschung über Red (`[p]mydata forgetme`, Owner-Befehle oder Löschanfrage von Discord) passiert:

| Daten | Ergebnis |
|---|---|
| Transcripts, deren **Ersteller** der Nutzer ist | **vollständig gelöscht** (Datei + Eintrag im Dashboard) |
| Transcripts **anderer** Tickets | seine Nachrichten, sein Name („Geschlossen von“) und Erwähnungen werden durch „Gelöschter Nutzer“ ersetzt; der Rest bleibt |
| geschlossene Tickets | Inhaber-ID → 0 („Gelöschter Nutzer“), aus „hinzugefügt“ entfernt, Übernahme und Formular-Antworten gelöscht |
| Übernahme-Statistik | Eintrag des Nutzers gelöscht |
| **offene** Tickets | Betriebsdaten: bei `user` unverändert, bei `owner`/`user_strict` nur die IDs (Antworten gelöscht), bei gelöschtem Discord-Konto (`discord_deleted_user`) auch die IDs entfernt |

**Warum Löschen statt Anonymisieren beim Ersteller?** Ein Transcript ist der Verlauf *seines* Anliegens –
Formular-Antworten und Inhalte identifizieren ihn auch ohne Namen, und die Antworten des Teams darin
beziehen sich nur auf dieses Anliegen. Ein bloß geschwärzter Name wäre also keine echte Anonymisierung.
In fremden Tickets gehört der Verlauf dagegen zum Anliegen eines anderen Mitglieds und bleibt deshalb
erhalten – nur die Beiträge des Nutzers werden entfernt.

Hinweis: Transcripts aus Versionen vor dieser Änderung enthalten keine Nutzer-IDs an den Nachrichten; dort
werden nur Erwähnungen ersetzt (Anzeigenamen sind nicht eindeutig). Transcripts, deren Ersteller der Nutzer
ist, werden auch dort über die Metadaten gefunden und gelöscht. Nachrichten im Log-Kanal (Discord selbst)
sind nicht Teil der Cog-Daten.
