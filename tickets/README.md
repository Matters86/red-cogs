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
- **Ticketnamen nach Wahl** – etwa `bewerbung-max-12`, weitere Vorlagen oder eigene Platzhalter.
- **24-Stunden-Timer pro Ticket** – manuell starten, bei neuen Nachrichten zurücksetzen und mit
  „Offen halten“ dauerhaft stoppen; sofortiges Schließen ist jederzeit möglich.

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

## Zuständigkeit und Übergabe

**Übernehmen** weist das Ticket dir selbst zu. Über **Zuweisen** suchst du ein anderes
Teammitglied direkt in Discord; `[p]ticket assign @Mitglied` erledigt dasselbe per Text- oder
Slash-Befehl. Eine bestehende Zuständigkeit wird dabei ersetzt. **Freigeben** bzw.
`[p]ticket unclaim` entfernt sie wieder. Im Dashboard wählst du das Mitglied in der Spalte
**Zuständig** aus; „Nicht zugewiesen“ gibt das Ticket frei.

Zuweisen dürfen Support und Admins. Das Ziel muss zum Support gehören und im Ticket lesen
und schreiben dürfen; Bots und der Ticket-Ersteller sind ausgeschlossen. Bei privaten Threads
wird das zuständige Mitglied hinzugefügt. Die Zuständigkeit steht im Ticket-Fußtext und im
Dashboard; das Teammitglied erhält bei einer neuen Zuweisung einen Ping. Änderungen werden
protokolliert. Wiederholtes Zuweisen derselben Person erhöht die Übernahme-Statistik nicht.

## Schließen nach Inaktivität

Neue und bestehende Tickets bleiben zunächst ohne automatischen Schließtimer offen. Im Ticket
startet **24h-Timer starten** (oder `[p]ticket autoclose`) die Frist ab jetzt. Schreibt danach der
Ersteller, ein hinzugefügtes Mitglied oder das Team, beginnt die Frist erneut: Erst nach
**24 Stunden ohne neue menschliche Nachricht** wird geschlossen. Auch Nachrichten mit Anhängen
zählen; Bots, Webhooks und Discord-Systemmeldungen verlängern die Frist nicht.

**Offen halten** (oder `[p]ticket keepopen`) stoppt den Timer für dieses Ticket. Weitere Nachrichten
und Bot-Neustarts schalten ihn nicht wieder ein; dazu muss **24h-Timer starten** erneut gedrückt
werden. Der Ersteller darf den Timer auch stoppen, wenn er Tickets selbst nicht schließen darf.
**Schließen** bzw. `[p]ticket close` schließt weiterhin sofort, unabhängig vom Timer.

Die Frist wird gespeichert und ungefähr einmal pro Minute geprüft. Nach einem Neustart werden
auch während der Bot-Auszeit geschriebene Nachrichten berücksichtigt, bevor ein überfälliges Ticket
geschlossen wird. Dafür braucht der Bot Zugriff auf den Nachrichtenverlauf. Das automatische Schließen
verwendet dieselben Transcripts, Logs, Statistiken und Archiv-/Löscheinstellungen wie manuelles
Schließen. Ein wieder geöffnetes Ticket startet ohne Timer.

## Dashboard

Ist `webcore` geladen, erscheint der Tab **Tickets**. Dort lassen sich pro Server einstellen:

- **Einstellungen** – Sprache, Ticket-Typ, alle Rollen, Kategorien/Thread-Basis/Forum,
  Log-Kanal, Limit, Ticketnamen, Bestätigungen sowie eigene Texte (überschreiben die
  Sprachpakete; Platzhalter `{num}` und `{user}` in Titel und Begrüßungstext).
- **Panels** – bestehende Panels auflisten, bearbeiten, löschen und neue erstellen (inkl. Gründe
  und Modal-Fragen); das Panel wird direkt in den gewählten Kanal gepostet, Änderungen
  aktualisieren die bestehende Nachricht.
- **Team-Zuordnung je Grund** (im Panel-Editor) – jeder Grund kann eigene Team-Rollen,
  Ping-Rollen und eine eigene Kategorie bekommen. Das Team ersetzt für diese Tickets die globalen
  Support-Rollen; Admins behalten Zugriff. Leer = globale Einstellungen. **Gilt für neue Tickets:**
  Bereits offene Tickets behalten das beim Erstellen gespeicherte Team.
- **Offene Tickets** (Übersicht) – Nummer, Inhaber, Grund, Öffnungszeit, Zuständigkeit und aktuelle
  Auto-Close-Frist (UTC). Die Mitgliederauswahl mit **Zuweisen** ändert die Zuständigkeit;
  **24h-Timer starten** und **Offen halten** steuern den Timer;
  **Schließen** mit
  Bestätigung wirkt wie der Button im Ticket (Transcript, Log, Inhaber-Rolle entfernen, archivieren bzw.
  löschen). Existiert der Kanal nicht mehr, entfernt „Schließen“ nur den verwaisten Eintrag.
- **Transcripts** – gespeicherte Ticket-Verläufe als eigene Seite öffnen.
- **Statistik** – sichtbare offene/geschlossene Tickets, Ø Laufzeit und Zuweisungen je Teammitglied.

### Ticketnamen

Unter **Einstellungen → Ticketnamen** wählst du das Format für neue Kanäle, private Threads und
Forum-Beiträge. **Grund–Nutzer–Nummer** ergibt beispielsweise `bewerbung-max-12`.

| Auswahl | Beispiel |
|---|---|
| Bisheriges Verhalten (Standard) | `bewerbung-12`; ohne Grund gilt die bisherige Vorlage |
| Grund–Nutzer–Nummer | `bewerbung-max-12` |
| Nutzer–Grund–Nummer | `max-bewerbung-12` |
| Ticket–Nummer | `ticket-12` |
| Eigene Vorlage | z. B. `{reason}-{display}-{num}` |

Die eigene Vorlage erlaubt `{reason}` (Grund), `{user}` (Nutzername), `{display}` (Anzeigename),
`{num}` (Ticketnummer) und `{id}` (Nutzer-ID). Sie darf höchstens 90 Zeichen enthalten und muss
`{num}` enthalten. Discord-taugliche Namen werden automatisch erzeugt, etwa mit ae/oe/ue/ss
für Umlaute. Eine gespeicherte Beispielansicht zeigt das Ergebnis. Änderungen benennen bestehende
Tickets nicht um; dafür gibt es weiterhin `[p]ticket rename`.

### Rechte im Dashboard

| WebCore-Stufe | Darf |
|---|---|
| Ansehen | zugängliche Tickets und Transcripts lesen |
| **Bedienen** | zusätzlich eigene Team-Tickets zuweisen/freigeben/schließen, Timer und Wartestatus steuern, Priorität ändern und Schnellantworten senden |
| Bearbeiten | zusätzlich Einstellungen, Rollen (Support/Admin/Inhaber …), Texte, Panels anlegen/bearbeiten/löschen und die Team-Zuordnung je Grund |

Panels und Team-Zuordnung gelten als Einrichtung des Ticketsystems (Rollen, Fragen, Eingangskanäle) und
brauchen deshalb *Bearbeiten*.

Die WebCore-Stufe allein gewährt keinen Zugriff auf Ticketinhalte oder Ticket-Aktionen. Dafür gilt
das im jeweiligen Ticket gespeicherte Team. Ein Bewerbungsteam sieht und bedient beispielsweise
seine Bewerbungen, während das globale Support-Team ohne weitere Berechtigung keinen Zugriff hat.
Das gilt auch für direkt aufgerufene Transcripts und manipulierte Formularanfragen. Ein voller
WebCore-Allowlist-Zugriff ersetzt die Ticketrechte ebenfalls nicht. Einrichtung mit **Bearbeiten**
ist unabhängig davon möglich. Im Team-Dashboard werden nur sichtbare Tickets und Verläufe gezählt.

Globale Ausnahmen sind die konfigurierten **Admin-Rollen**, Discord-**Administrator**, Server-Owner
und Bot-Owner. **Server verwalten** allein gewährt keine Ticketverwaltung. Explizite **Nur-Lesen-Rollen**
dürfen alle zuordenbaren Tickets und Verläufe lesen; ohne zuständige Teamrolle erscheinen keine
Bedienelemente. Sehr alte Transcripts ohne gespeichertes oder zuordenbares Team bleiben Admins
vorbehalten. Eigentümer und hinzugefügte Mitglieder nutzen unabhängig davon **Meine Tickets**.

Für strikt je Grund getrennten **Discord-Zugriff** verwende **Eigener Kanal**. Forum-Beiträge
übernehmen die Sichtbarkeit des gesamten Forums; Discords **Threads verwalten** kann auch private
Threads zugänglich machen. Die Bot-Aktionen prüfen bei allen drei Typen das zuständige Team.
In privaten Threads lädt der Bot bis zu 100 aktuelle Team-/Admin-Mitglieder ohne Rollen-Pings ein.
Fehlende Einladungen oder größere Teams werden gemeldet; eine spätere Zuweisung kann das zuständige
Mitglied hinzufügen. Nur-Lesen-Rollen im Dashboard ändern diese Discord-Grenzen nicht.

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
