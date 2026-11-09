# 🎟️ Tickets

Mehrsprachiges Support-Ticketsystem für Red – mit Panels (Buttons/Dropdown), optionalem Modal,
Tickets als Kanal **oder** Thread **oder** Forum-Beitrag, HTML-Transcripts, Statistik und
Verwaltung über das WebCore-Dashboard. **Deutsch ist Standard**, die Sprache ist pro Server
umschaltbar und alle Texte sind überschreibbar.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs tickets
[p]load tickets
```

**Funktionen**
- Panels mit Buttons oder Dropdown, Modal mit bis zu 5 Fragen
- Rollen: Support, Admin, View (nur lesen), Ping, Inhaber-Rolle
- Team-Zuordnung je Grund: eigenes Team, eigene Ping-Rollen, eigene Kategorie pro Ticket-Typ
- Ticketnamen per Auswahl, z. B. `bewerbung-max-12`, oder eigener Vorlage
- Übernehmen, Sperren, Schließen, Wiederöffnen, Löschen, Umbenennen, Mitglieder verwalten
- Limit für offene Tickets pro Nutzer, Schließen-Bestätigung
- HTML-Transcripts + Statistik im Dashboard
- **Meine Tickets** im Mitglieder-Bereich: eigene Tickets + Verläufe ansehen und Tickets auch über die Website öffnen
- Persistente Buttons (überstehen Neustarts)
- 24-Stunden-Timer pro Ticket: per Button starten, bei jeder neuen menschlichen Nachricht zurücksetzen,
  mit „Offen halten“ stoppen; sofortiges Schließen bleibt verfügbar

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]ticket close [grund]` | Schließt das aktuelle Ticket. | Ersteller (falls erlaubt) / Support |
| `[p]ticket autoclose` | Startet den 24-Stunden-Timer für das aktuelle Ticket. | Ersteller (falls Schließen erlaubt) / Support |
| `[p]ticket keepopen` | Stoppt den Timer; das Ticket bleibt offen. | Ersteller / Support |
| `[p]ticket open` | Öffnet ein archiviertes Ticket wieder. | Support |
| `[p]ticket claim` | Übernimmt das aktuelle Ticket. | Support |
| `[p]ticket assign <mitglied>` | Weist das Ticket einem Teammitglied zu oder übergibt es. | Support |
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

**Zuständigkeit:** Mit **Übernehmen** übernimmst du selbst; mit **Zuweisen** suchst du ein anderes
Teammitglied. Eine bestehende Zuweisung wird ersetzt. **Freigeben** entfernt sie. Der zuständige
Name steht direkt im Ticket und im Dashboard. Nur Teammitglieder mit Lese- und Schreibzugriff
können zugewiesen werden; Bots und Ticket-Ersteller sind ausgeschlossen. Im Dashboard lässt
sich die Zuständigkeit ab Stufe **Bedienen** über die Mitgliederauswahl ändern.

**24-Stunden-Timer:** Tickets haben zunächst keinen Timer. **24h-Timer starten** aktiviert ihn ab jetzt;
jede neue Nachricht vom Nutzer oder Team setzt die Frist auf weitere 24 Stunden. Bots, Webhooks und
Systemmeldungen zählen nicht. **Offen halten** stoppt ihn bis zum nächsten manuellen Start – auch über
Neustarts hinweg. **Schließen** schließt weiterhin sofort. Die Prüfung erfolgt ungefähr jede Minute;
Nachrichten während eines Bot-Ausfalls werden vor dem Schließen berücksichtigt. Transcripts, Logs und
Archiv-/Löscheinstellungen gelten wie beim manuellen Schließen. Wieder geöffnete Tickets haben keinen Timer.

**Dashboard:** Tab **Tickets** → Einstellungen, Panels (inkl. Editor und Team-Zuordnung je Grund), Transcripts und Statistik pro Server. In **Offene Tickets** stehen die aktuelle Auto-Close-Frist (UTC) und Aktionen zum Starten/Stoppen des Timers sowie zum sofortigen Schließen bereit (ab WebCore-Stufe **Bedienen**). Mitglieder finden unter **Mein Bereich → Meine Tickets** ihre eigenen Tickets und Verläufe und können dort (gleiche Fragen und Limits wie der Button) ein Ticket öffnen – abschaltbar im Reiter Einstellungen.

**Ticketnamen:** Unter **Einstellungen → Ticketnamen** stehen **Grund–Nutzer–Nummer** (`bewerbung-max-12`),
**Nutzer–Grund–Nummer**, **Ticket–Nummer**, das bisherige Verhalten und eine eigene Vorlage zur Wahl.
Platzhalter: `{reason}`, `{user}`, `{display}`, `{num}` und `{id}`; `{num}` ist Pflicht,
höchstens 90 Zeichen. Das Beispiel zeigt das gespeicherte Format. Bestehende Tickets behalten ihren Namen.

**Getrennte Teams:** Ein eigenes Team je Grund ersetzt für neue Tickets die globalen Support-Rollen.
Bereits offene Tickets behalten ihr bisheriges Team. Im Team-Dashboard sind Listen, Zählungen,
Verläufe und Aktionen auf die zugänglichen Tickets begrenzt; **Bedienen** oder **Bearbeiten** in
WebCore allein reicht nicht für fremde Tickets. Auch ein voller WebCore-Allowlist-Eintrag ersetzt
keine Ticketrechte. Globale Admin-Rollen, Discord-Administrator, Server-Owner und Bot-Owner behalten
Zugriff; **Server verwalten** allein macht niemanden zum Ticket-Admin. Explizite Nur-Lesen-Rollen
sehen zuordenbare Tickets ohne Aktionen. Unbekannte historische Transcripts bleiben Admins vorbehalten.
Die persönliche Ansicht **Meine Tickets** bleibt auf eigene oder ausdrücklich hinzugefügte Tickets begrenzt.

Für strikt getrennten **Discord-Zugriff** eignet sich **Eigener Kanal**. Forum-Beiträge übernehmen
die Forum-Sichtbarkeit; **Threads verwalten** kann private Threads zugänglich machen. Die Bot-Aktionen
prüfen dennoch bei jedem Typ das Ticket-Team. Private Threads laden bis zu 100 aktuelle Team-/Admin-Mitglieder
ohne Rollen-Pings ein; nicht mögliche Einladungen werden gemeldet. Änderungen an der Team-Zuordnung
migrieren keine vorhandenen Kanalrechte.

## Wartestatus, eigene Tickets und Erinnerungen

Tickets zeigen **Wartet auf Nutzer** oder **Wartet auf Team**. Eine neue menschliche Nachricht setzt den Status passend: Team-Antwort → Nutzer, Nutzer-Antwort → Team. Das Team kann ihn auch per Button, Dashboard oder `[p]ticket waiting <user|team>` setzen.

Die Übersicht filtert **Meine Tickets**, **Nicht zugewiesen** und beide Wartestatus. „Meine Tickets“ meint die dir zugewiesenen Tickets. Bei aktivem 24h-Timer erinnert der Bot ungefähr eine Stunde vor Ablauf einmal pro Frist an die Schließung. Der Hinweis bietet **Offen halten** und **Schließen**; eine neue Nachricht startet die 24 Stunden erneut. Vor Erinnern und Schließen werden auch Offline-Antworten geprüft.

## Schnellantworten und Priorität

Das Team öffnet **Schnellantwort**, wählt einen Textbaustein und bearbeitet ihn im Dialog. Danach erscheint eine Vorschau. Erst **Antwort jetzt senden** veröffentlicht den Text im Ticket. Auswahl, Bearbeiten und Vorschau senden nichts. Im Dashboard funktioniert derselbe Ablauf über **Entwurf öffnen** und die editierbare Vorschau; die Bestätigung gilt einmalig und läuft nach zehn Minuten ab. Fehlgeschlagene Sendungen erhalten die bearbeitete Vorschau.

Unter **Schnellantworten → Erweitert** verwalten Administratoren mit WebCore-Recht **Bearbeiten** bis zu 25 Vorlagen und eine optionale Signatur (höchstens 200 Zeichen). Drei deutsche Beispiele sind vorbelegt. Platzhalter: `{user}` = Anzeigename des Inhabers, `{ticket}` = Ticketnummer, `{staff}` = Teammitglied, `{signature}` = gespeicherte Signatur. Nur diese Platzhalter werden einmal ersetzt; unbekannte bleiben wörtlich. Der vollständige Antworttext muss nach Ersetzung 1–2000 Zeichen enthalten. Vorlagenwahl veröffentlicht niemals automatisch und alle Erwähnungen sind beim Versand ohne Ping.

Vorschau/Versand und Priorität brauchen im Dashboard **Bedienen** sowie die aktuellen Supportrechte des jeweiligen Tickets; Lesen und Schreiben im Kanal müssen weiterhin erlaubt sein. Der Bot prüft diese Rechte und den offenen Ticketstatus vor dem Senden erneut. Ein zwischenzeitlich geschlossenes Ticket erhält keine vorbereitete Antwort.

**Normal** oder **Dringend** setzt das Team per Button, Dashboard oder `[p]ticket priority <normal|urgent>`. Prioritätswechsel verändern keine bereits gewartete Zeit.

## Antwortzeiten (optional, Standard aus)

Unter **Einstellungen → Erweitert: Priorität und Antwortzeiten** einschalten; Vorgaben sind 24 Stunden für Normal und 4 Stunden für Dringend (je 1–720 Stunden, Dringend höchstens so lang wie Normal). Dann zeigen Ticket-Steuerleiste und Übersicht **Antwort bis …** bzw. **Antwort fällig**.

- Die Uhr zählt ausschließlich, während das Ticket auf das **Team** wartet. Weitere Nutzernachrichten verlängern eine laufende Frist nicht.
- Manuelles Wechseln auf **Wartet auf Nutzer** pausiert den vorhandenen Zyklus. Beim Zurückschalten läuft nur die verbleibende Zeit weiter; wiederholtes Umschalten setzt die Frist nicht zurück.
- Eine tatsächliche Teamantwort – auch eine bestätigte Schnellantwort – erledigt den bisherigen Antwortzyklus. Das nächste Nutzeranliegen startet einen neuen. Priorität verwendet jeweils dieselbe bereits angesammelte Teamwartezeit.
- Zeiten und angesammelte Wartezeit bleiben bei Bot-Neustarts erhalten. Bei aktivierten Antwortzeiten gleicht der Bot seitdem verpasste menschliche Antworten aus dem Ticket-Verlauf ab. Fehlen Leserechte, wird keine ungesicherte Fälligkeit behauptet; die Übersicht meldet **Verlauf noch nicht bestätigt** und versucht es erneut.
- Altbestand ohne bestätigten Antwortzyklus erhält keine aus dem Ticketalter geratene Frist. Ein bestätigtes Nutzeranliegen oder manuelles Setzen auf Team startet die Uhr. Wiederöffnen beginnt einen neuen Zyklus; geschlossen ist keine Antwort fällig.

Antwortzeiten schließen kein Ticket und senden keine zusätzlichen Erinnerungs-Pings. Der vorhandene 24-Stunden-Inaktivitätstimer samt Erinnerung bleibt davon unabhängig.
