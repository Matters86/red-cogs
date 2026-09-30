# Ideas (Ideen-Sammler)

Ideen-Sammler für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot): ein **eigenes Ideen-Forum**,
Einreichen per **Formular**, **Status-Workflow** fürs Team, **Umfragen aus Ideen** und eine Seite im
**Mitglieder-Bereich** der Website. Bewusst **ohne** 👍/👎-Abstimmung – abgestimmt wird gezielt über Umfragen.

## Funktionen

- **Forum-Kanal:** Jede Idee wird ein eigener Beitrag `#12 · Titel`, vom Bot erstellt. Die Startnachricht ist ein
  Embed mit Beschreibung, Kategorie, Status und Einreicher (Erwähnung **ohne Ping** bzw. „anonym“).
- **Status als Forum-Tags:** `Neu`, `In Prüfung`, `Geplant`, `Umgesetzt`, `Abgelehnt`, `Zusammengeführt`
  (+ optional ein Tag je Kategorie). Fehlende Tags legt der Bot an – in **einem** Schritt, mit Prüfung der Rechte
  („Kanäle verwalten“) und des Limits von **20 Tags** je Forum. Vorhandene Tags werden per Name wiedererkannt
  (Deutsch und Englisch). Status-Tags sind „moderiert“ (nur Team/Bot kann sie setzen).
- **Einreichen-Panel:** angepinnter, gesperrter Beitrag „💡 Idee einreichen“ mit **persistentem Button**
  (funktioniert nach Neustart/Reload weiter, `custom_id` `ideas:submit`).
- **Formular (zweistufig):** Button → (nur wenn Kategorien eingestellt sind) **ephemere Kategorie-Auswahl** →
  **Modal** mit Titel (max. 100) und Beschreibung (max. 1000). *Warum zweistufig?* Ein Modal kann in den
  discord.py-Versionen, die Red 3.5 mitbringt, keine Auswahlliste enthalten; ein Textfeld für die Kategorie führt zu
  Tippfehlern. Die Auswahlliste liefert immer eine gültige Kategorie.
- **Schutz:** Wartezeit je Mitglied (Standard 10 Min.), max. offene Ideen je Mitglied (Standard 5; offen = Neu, In
  Prüfung, Geplant), **Sperrliste**, **Duplikat-Hinweis** bei sehr ähnlichem Titel (nur Hinweis mit Link, die Idee
  wird trotzdem eingereicht; im neuen Beitrag steht „Ähnliche Ideen: …“ fürs Team). Nummern werden unter einem
  Server-Lock vergeben – keine doppelten Nummern, keine Lücken (der Zähler steigt erst nach erfolgreichem Posten);
  Limits und Wartezeit werden unter dem Lock erneut geprüft. Der Bot-Owner ist von Wartezeit/Limit/Sperre ausgenommen.
- **Manuelle Beiträge** (falls Mitglieder im Forum selbst posten dürfen): Schalter „manuelle Beiträge als Ideen
  übernehmen“ (Standard an) → Beitrag bekommt Nummer, Tag „Neu“ und ein Info-Embed als Bot-Antwort (die
  Startnachricht gehört dem Mitglied). Ein vom Mitglied gewählter Kategorie-Tag wird als Kategorie übernommen.
  Beiträge gesperrter Mitglieder werden nicht übernommen.
- **Beitrag in Discord gelöscht** → Idee wird als „gelöscht“ markiert (Dashboard-Filter). Archiviert → nichts passiert.
- **Team-Workflow:** Status setzen mit optionaler Begründung (als Bot-Antwort im Beitrag), Tags + Embed werden
  aktualisiert, optional **DM an den Einreicher**; bei *Umgesetzt*/*Abgelehnt* optional **schließen + archivieren**
  (zurück auf einen offenen Status öffnet den Beitrag wieder). **Kommentar** ohne Statuswechsel.
  **Zusammenführen** (Duplikat → Ziel: Status „Zusammengeführt“, Hinweis mit Link, Duplikat wird archiviert, im Ziel
  ein Hinweis). **Bearbeiten** (Titel/Beschreibung/Kategorie – Beitragsname, Tags, Embed folgen), **Löschen**
  (mit Bestätigung, löscht auch den Forum-Beitrag), Mitglieder **sperren/entsperren**.
- **Umfrage aus Ideen:** 2 bis max. Optionen des Poll-Cogs auswählen → Umfrage über den vorhandenen Cog `poll`
  (`Poll.create_poll`, dieselbe Funktion wie dessen Dashboard und Befehl). Optionen „#12 Titel“ (auf das Poll-Limit
  von 100 Zeichen gekürzt), Laufzeit/Einfach-Mehrfach/anonym wie beim Poll-Cog. Die Ideen werden mit der Umfrage
  verknüpft (Embed-Feld „Abstimmung“, Dashboard), im Beitrag jeder Idee steht „🗳️ Diese Idee steht zur
  Abstimmung: <Link>“, optional wechseln *neue* Ideen auf „In Prüfung“. Nur offene Ideen sind wählbar.
  Ist der Poll-Cog nicht geladen, zeigt das Dashboard einen Hinweis statt des Knopfs.
- **Mehrsprachig:** Discord-Texte und neue Tags auf Deutsch (Standard) oder Englisch.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet. Für „Umfrage aus Ideen“ zusätzlich
[`poll`](../poll/).

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs ideas
[p]load ideas
```

## Einrichtung

**Variante A – Forum anlegen lassen (empfohlen):** Dashboard → *Ideen* → *Einstellungen* → „Forum anlegen“ oder
`[p]ideaset createforum ideen`. Der Bot legt ein Forum an mit:

| Wer | Rechte im Forum |
|---|---|
| @everyone | darf in Beiträgen **antworten**, aber **keine eigenen Beiträge** erstellen (Einreichen nur über das Formular) |
| Bot | ansehen, Beiträge erstellen, antworten, Threads verwalten, Links einbetten, Verlauf lesen |
| Team-Rollen | Threads verwalten, antworten |

Dazu die sechs Status-Tags (+ Kategorie-Tags), das Forum wird als Ideen-Forum eingestellt und das Panel gepostet.
Der Bot braucht dafür auf dem Server „Kanäle verwalten“.

**Variante B – vorhandenes Forum:** `[p]ideaset forum #forum` (oder im Dashboard wählen) → fehlende Tags werden
angelegt → `[p]ideaset panel`. Damit Mitglieder nur über das Formular einreichen, im Forum für @everyone
„Beiträge erstellen“ (*Send Messages*) verbieten und „In Threads schreiben“ erlauben.
Der Bot braucht im Forum: *Kanal ansehen, Nachrichten senden, In Threads senden, Threads verwalten, Kanäle verwalten
(für Tags), Links einbetten, Nachrichtenverlauf lesen*. Das Dashboard zeigt fehlende Rechte/Tags an.

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]ideas status <nr> <status> [kommentar]` | Status setzen (`neu`, `prüfung`, `geplant`, `umgesetzt`, `abgelehnt`) mit optionaler Begründung | Team |
| `[p]ideas comment <nr> <text>` | Kommentar des Teams im Beitrag posten | Team |
| `[p]ideas merge <duplikat> <ziel>` | Duplikat mit Ziel zusammenführen | Team |
| `[p]ideas edit <nr> <titel\|beschreibung\|kategorie> <wert>` | Idee bearbeiten | Team |
| `[p]ideas delete <nr> [ja]` | Idee + Forum-Beitrag löschen (ohne `ja` nur Rückfrage) | Team |
| `[p]ideas block <@mitglied>` / `unblock <@mitglied>` | Mitglied für das Einreichen sperren / entsperren | Team |
| `[p]ideas list [status\|offen]` | Ideen auflisten | Team |
| `[p]ideas export` | Alle Ideen als CSV | Team |
| `[p]ideas poll <nr> <nr> … [\| frage]` | Umfrage aus Ideen in diesem Kanal (Poll-Cog) | Team |
| `[p]ideaset forum <#forum>` | Ideen-Forum festlegen, fehlende Tags anlegen | Server verwalten |
| `[p]ideaset createforum [name]` | Forum mit Tags, Rechten und Panel anlegen | Server verwalten |
| `[p]ideaset panel` | Panel „💡 Idee einreichen“ posten/erneuern | Server verwalten |
| `[p]ideaset categories <a \| b \| c>` | Kategorien (max. 10, je max. 20 Zeichen; leer = keine) | Server verwalten |
| `[p]ideaset teamrole <rolle>` | Team-Rolle hinzufügen/entfernen | Server verwalten |
| `[p]ideaset anonymous\|dm\|archive\|manual <true\|false>` | anonym · DM bei Status · schließen bei Umgesetzt/Abgelehnt · manuelle Beiträge | Server verwalten |
| `[p]ideaset cooldown <minuten>` / `maxopen <anzahl>` | Wartezeit / max. offene Ideen je Mitglied (0 = aus) | Server verwalten |
| `[p]ideaset language <de\|en>` | Sprache | Server verwalten |
| `[p]ideaset settings` | Einstellungen anzeigen | Server verwalten |

**Team** = Bot-Owner, „Server verwalten“/Administrator oder eine der Team-Rollen. Alias: `[p]ideen`.
Alle Befehle gibt es auch als Slash-Befehl. Einreichen geht über den Button im Forum oder die Website.

## Dashboard

Seite **Ideen** (`/cogs/ideas`, Icon Glühbirne):

- **Kennzahlen** je Status.
- **Ideen:** Tabelle mit Suche, Filter Status (inkl. „offen“ und „in Discord gelöscht“) und Kategorie, Sortierung
  Neueste/Älteste/Nummer. Häkchen + Aktionsleiste: **Status setzen** für die Auswahl, **Umfrage starten**.
- **Details** (`?idea=<nr>`): Beschreibung, Einreicher, Quelle, Verknüpfungen (Umfragen, Zusammenführungen),
  **Verlauf**, Status mit Begründung, Kommentar, Zusammenführen, Bearbeiten, Löschen, Link zum Forum-Beitrag.
- **Umfrage:** offene Ideen auswählen (vorbelegt aus der Auswahl), Frage (Vorschlag „Welche Idee sollen wir als
  Nächstes umsetzen?“), Kanal, Laufzeit, Einfach/Mehrfach, anonym, „neue Ideen auf In Prüfung“.
- **Einstellungen:** Forum (mit Status von Rechten/Tags), Sprache, Kategorien (+ als Tags), Wartezeit, max. offene
  Ideen, anonym, Einreicher hinzufügen, manuelle Beiträge, Team-Rollen, DM, Archivieren, Mitglieder-Bereich;
  **Panel posten/erneuern**, **Tags prüfen/anlegen**, **Forum anlegen**.
- **Sperren:** gesperrte Mitglieder, sperren per Name/ID, entsperren.
- **CSV-Export** (Knopf oben rechts; `;`-getrennt, UTF-8 mit BOM, Formel-Injection entschärft).

„Anonym“ gilt für die Öffentlichkeit: Im Beitrag steht „anonym“ und der Einreicher wird dem Beitrag nicht
hinzugefügt. Das Team sieht den Einreicher im Dashboard weiterhin (nötig für Sperren/Rückfragen).

### Rechte im Dashboard

| Stufe | Darf |
|---|---|
| Ansehen | alles sehen, nichts ändern |
| **Bedienen** | Tagesgeschäft an einzelnen Ideen: **Status setzen** (auch für eine Auswahl), **kommentieren**, **zusammenführen**, **bearbeiten**, **löschen**, **Umfrage aus Ideen starten** |
| Bearbeiten | zusätzlich Einstellungen, **Team-Rollen**, **Panel** posten, **Tags** anlegen, **Forum anlegen**, Mitglieder **sperren/entsperren** |

Die Stufen vergibt der Bot-Owner unter *Verwaltung → Zugriff & Rollen*; der Bot-Owner darf immer alles.
Sperren zählt zu „Bearbeiten“, weil es Mitgliedern dauerhaft eine Funktion entzieht.

## Mein Bereich: „Ideen“ (für Mitglieder)

Ist der Mitglieder-Bereich eingeschaltet (`[p]webcore portal on`) und der Schalter „Im Mitglieder-Bereich anzeigen“
an, finden Mitglieder unter **Mein Bereich → Ideen** (`/me/ideen`):

- **Einreichen:** Formular mit Titel, Beschreibung und Kategorie – **dieselbe Funktion** wie das Discord-Formular
  (Wartezeit, Limit, Sperre, Duplikat-Hinweis, Forum-Beitrag). Hinweise wie „Bitte warte noch …“ erscheinen schon vorab.
- **Alle Ideen:** Nummer, Titel, Kategorie, Status, Link zum Forum-Beitrag – nur für Mitglieder, die das
  Ideen-Forum in Discord sehen können (sonst ist auch Einreichen gesperrt). Keine Namen anderer Einreicher.
- **Meine Ideen:** eigene Ideen mit Status und letztem Kommentar des Teams.

## Datenspeicherung

Pro Idee: Titel, Beschreibung, Kategorie, Discord-ID und Anzeigename der einreichenden Person, Status-Verlauf mit
IDs/Namen der Team-Mitglieder, Verknüpfungen zu Forum-Beitrag und Umfragen. Pro Mitglied der Zeitpunkt der letzten
Einreichung, pro Server die Sperrliste.

`red_delete_data_for_user` **anonymisiert** statt zu löschen: Einreicher-ID/-Name und die IDs/Namen der Person im
Verlauf und bei Umfrage-Verknüpfungen werden entfernt, der Sperrlisten-Eintrag und der Wartezeit-Zeitstempel
gelöscht. Titel und Beschreibung bleiben, weil die Idee ein Beitrag im Community-Forum ist (die Discord-Nachrichten
gehören nicht dem Cog) und Nummern, Zusammenführungen und Umfragen für alle nachvollziehbar bleiben sollen.
