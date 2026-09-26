# RaidHelper

Mehrsprachiger Raid-Planer für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – Anmeldungen wie bei [raid-helper.dev](https://raid-helper.dev), direkt im eigenen Bot und ohne externen Dienst.

Organisatoren legen ein Event an, der Bot postet ein **Embed mit Live-Roster** in einen Kanal. Mitglieder melden sich per **Klassen-Dropdown** an, wählen ihre **Spezialisierung** (wird gemerkt) und werden anhand der Spec automatisch der passenden **Rolle** (Tank / Heiler / Nahkampf / Fernkampf) zugeordnet.

## Funktionen

- **Anmeldung per Klick** – Klassen-Dropdown + Spec-Auswahl, dazu Bank, Spät, Vielleicht und Abwesend.
- **Live-Roster** im Embed, nach Rolle gruppiert, mit fortlaufender Nummerierung.
- **Spec-Gedächtnis** – die zuletzt gewählte Spezialisierung je Spiel und Klasse wird pro Nutzer gemerkt.
- **Limits** für das gesamte Event und pro Rolle.
- **Anmeldeschluss** – standardmäßig der Event-Start, Anmeldung danach automatisch zu.
- **Erinnerungen** 60 und 15 Minuten vor Start im Kanal, optional zusätzlich per DM an Angemeldete.
- **Wiederkehrende Events** – täglich, wöchentlich oder zweiwöchentlich; der nächste Termin wird automatisch erzeugt.
- **Teilnahme-Statistik** je Mitglied.
- **CSV-Export** der Anmeldungen.
- **Drei WoW-Vorlagen**: Retail (13 Klassen), Classic/Vanilla (9), WotLK/Cata (10) – mit **deutschen** Klassen- und Spec-Namen.
- **Spec-Icons** – eigene Icons je Spezialisierung, botweit als Application-Emojis, bequem per Dashboard hochladbar; erscheinen im Spec-Auswahlmenü und im Roster.
- **Mehrsprachig** – Deutsch als Standard, pro Server umschaltbar (aktuell `de`, `en`).
- **Dashboard** – Events direkt im WebCore-Dashboard anlegen und bearbeiten, dazu Roster und alle Einstellungen.
- **Anmeldung über die Website** – Mitglieder sehen unter „Mein Bereich → Raids“ die kommenden Events und melden sich dort an (gleiche Regeln wie die Buttons).

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs <REPO-URL>
[p]cog install red-cogs raidhelper
[p]load raidhelper
```

`tzdata` wird als Abhängigkeit mitinstalliert (für korrekte Zeitzonen, v. a. unter Windows).

## Schnellstart

```
[p]raidset channel #raids        # Anmelde-Kanal festlegen
[p]raidset game wow_retail       # Standard-Spiel (optional)
[p]raidset language de           # Sprache (optional)
[p]raid create 13.06.2026 20:00 Mythic Undermine
```

Datum/Uhrzeit werden in der eingestellten Server-Zeitzone interpretiert (Standard `Europe/Berlin`) und im Embed als zeitzonenabhängige Discord-Zeitstempel angezeigt.

## Befehle

Verwaltung (`raid`) erfordert eine Manager-Rolle, „Server verwalten" oder Bot-Inhaber.

| Befehl | Beschreibung |
|---|---|
| `[p]raid create <datum> <zeit> <titel>` | Event im Standard-Kanal/-Spiel anlegen |
| `[p]raid quickcreate <spiel> <#kanal> <datum> <zeit> <titel>` | Event mit Spiel und Kanal direkt anlegen |
| `[p]raid list` | Alle Events des Servers auflisten |
| `[p]raid close <id>` | Anmeldung schließen |
| `[p]raid reopen <id>` | Anmeldung wieder öffnen |
| `[p]raid delete <id>` | Event samt Nachricht löschen |
| `[p]raid repost <id>` | Event-Nachricht neu posten (gelöscht/Posten fehlgeschlagen) – alte Nachricht wird ersetzt, Anmeldungen bleiben |
| `[p]raid add <id> <mitglied> <klasse> <spec>` | Mitglied manuell eintragen |
| `[p]raid remove <id> <mitglied>` | Mitglied aus einem Event entfernen |
| `[p]raid export <id>` | Anmeldungen als CSV exportieren |
| `[p]raid title <id> <titel>` | Titel ändern |
| `[p]raid time <id> <datum> <zeit>` | Termin verschieben (nur in die Zukunft; Erinnerungen werden neu gesendet, ein Standard-Anmeldeschluss wandert mit) |
| `[p]raid description <id> [text]` | Beschreibung setzen (ohne Text = entfernen) |
| `[p]raid deadline <id> <datum> <zeit>` | Anmeldeschluss setzen (muss vor dem Start liegen) |
| `[p]raid recurrence <id> <none\|daily\|weekly\|biweekly>` | Wiederholung setzen |
| `[p]raid maxsignups <id> <anzahl>` | Maximale Anmeldungen (`0` = unbegrenzt) |
| `[p]raid rolelimit <id> <rolle> <anzahl>` | Limit pro Rolle – `tank`, `healer`, `mdps`, `rdps` (`0` = kein Limit) |

Einstellungen (`raidset`) erfordern „Server verwalten" oder Admin.

| Befehl | Beschreibung |
|---|---|
| `[p]raidset language <de\|en>` | Sprache setzen |
| `[p]raidset game <spiel-id>` | Standard-Spiel setzen |
| `[p]raidset channel <#kanal>` | Standard-Anmelde-Kanal setzen |
| `[p]raidset managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen (Umschalter) |
| `[p]raidset timezone <zone>` | Anzeige-Zeitzone setzen (z. B. `Europe/Berlin`) |
| `[p]raidset reminders <true\|false>` | Erinnerungen an-/ausschalten |
| `[p]raidset cleanup <tage>` | Abgeschlossene Events nach N Tagen löschen (Standard 30, `0` = aus) – nur Daten, Discord-Nachrichten bleiben |
| `[p]raidset icons` | Zeigt, welche Klasse welches Icon hat |
| `[p]raidset specicon <klasse> <spec> <emoji>` | Icon einer Spezialisierung manuell auf ein vorhandenes Emoji setzen (nur Bot-Owner, gilt botweit) |
| `[p]raidset clearspecicon <klasse> <spec>` | Icon einer Spezialisierung entfernen (nur Bot-Owner) |
| `[p]raidset uploadicons` | Angehängte Bilddateien als Spec-Icons hochladen (Dateiname = klasse_spec, nur Bot-Owner) |
| `[p]raidset settings` | Aktuelle Einstellungen anzeigen |
| `[p]raidset dashboard` | Hinweis zur Dashboard-Seite |

Spiel-IDs: `wow_retail`, `wow_classic`, `wow_wotlk`.

## Dashboard

Die Seite **Raidplaner** erscheint nach dem Laden automatisch im WebCore-Dashboard unter `/cogs/raidhelper`. Dort gibt es:

- Statistik-Kacheln (kommende Events, Anmeldungen gesamt, Standard-Spiel),
- den Reiter **Neues Event** – Event anlegen und sofort posten (siehe unten),
- eine Event-Tabelle mit Aktionen (Roster, **Bearbeiten**, Schließen/Öffnen, Löschen, **Neu posten**),
- eine Roster-Ansicht pro Event,
- ein Einstellungs-Formular (Sprache, Standard-Spiel, Anmelde-Kanal, Zeitzone, Erinnerungen, Mitglieder-Bereich, Aufräumen, Text-Overrides) und der Reiter **Launcher & Website** (öffentliche API, siehe unten),
- eine **Spec-Icon-Verwaltung** mit Datei-Upload und Vorschau der aktuellen Icons.

Zusätzlich registriert der Cog die Mitglieder-Seite **Raids** (`/me/raids`) – siehe „Anmeldung über die Website“.

### Rechte im Dashboard

| Stufe | Darf |
|---|---|
| Ansehen | alles sehen (Events, Roster, Einstellungen), nichts ändern |
| **Bedienen** | Tagesgeschäft: Events **anlegen** und **bearbeiten**, **schließen/öffnen**, **löschen**, **neu posten** |
| Bearbeiten | zusätzlich Einstellungen (Sprache, Kanal, Zeitzone, Erinnerungen, Aufräumen), eigene Texte, Freigabe für Launcher & Website und den Schalter „Im Mitglieder-Bereich anzeigen“ |

Spec-Icons gelten botweit und bleiben dem Bot-Owner vorbehalten. Rechte gelten nur auf den Servern,
für die sie vergeben sind. Die Stufen vergibt der Bot-Owner unter *Verwaltung → Zugriff & Rollen* (je Server und Rolle); der Bot-Owner selbst darf immer alles.

### Neues Event

Alle Optionen von `[p]raid create`/`quickcreate` und den Einstellungsbefehlen in einem Formular:

| Feld | Bedeutung |
|---|---|
| Titel, Beschreibung | Titel max. 256 Zeichen, Beschreibung max. 1400 (Discord-Formatierung erlaubt) |
| Spiel / Vorlage | Klassen, Specs und Rollen (vorbelegt: Standard-Spiel) |
| Anmelde-Kanal | Vorbelegt: Standard-Anmelde-Kanal. Der Bot braucht dort „Kanal ansehen“, „Nachrichten senden“ und „Links einbetten“ |
| Datum, Uhrzeit | Kalender-/Uhrzeit-Auswahl; gilt in der **Server-Zeitzone** (wird mit aktuellem UTC-Versatz angezeigt). In Discord sieht jedes Mitglied die Zeit in seiner eigenen Zeitzone |
| Anmeldeschluss | Optional, muss vor dem Start liegen (leer = bis zum Start) |
| Wiederholung | Einmalig, täglich, wöchentlich, alle zwei Wochen |
| Maximale Anmeldungen, Rollen-Limits | Leer oder 0 = unbegrenzt |

Erinnerungen (60 und 15 Minuten vorher) gelten für alle Events des Servers und werden unter „Einstellungen“ geschaltet.

Das Dashboard nutzt **dieselbe Funktion wie `[p]raid create`**: gleiche Prüfungen, fortlaufende Event-ID, Nachricht mit Anmelde-Buttons. Raidleitung wird, wer das Event im Dashboard anlegt. Fehler (Datum in der Vergangenheit, Kanal ohne Bot-Rechte, ungültige Limits …) erscheinen als rote Meldung, die Eingaben bleiben im Formular erhalten. Nach dem Anlegen springt die Seite zum Reiter „Events“.

### Event bearbeiten

„Bearbeiten“ in der Event-Tabelle ändert Titel, Beschreibung, Termin, Anmeldeschluss, Wiederholung und Limits – wie die Befehle `[p]raid title/time/description/deadline/recurrence/maxsignups/rolelimit`. Die vorhandene Discord-Nachricht wird bearbeitet, Anmeldungen bleiben erhalten. Spiel und Kanal lassen sich nachträglich nicht ändern; bei abgeschlossenen Events ist der Termin gesperrt. Wird der Termin verschoben, werden die Erinnerungen neu gesendet.

### Neu posten

Fehlt die Event-Nachricht in Discord – weil jemand sie gelöscht hat, das Posten beim Anlegen fehlgeschlagen ist
(fehlende Rechte) oder der Kanal gelöscht wurde –, zeigt die Event-Tabelle ein Badge **„Nachricht fehlt“** und den
Knopf **„Neu posten“** (gleiche Rechte wie die anderen Event-Aktionen). Er nutzt dieselbe Prüfung und Post-Logik
wie das Anlegen: Kanal des Events (existiert er nicht mehr: der Standard-Anmelde-Kanal), Bot-Rechte „Kanal ansehen“,
„Nachrichten senden“, „Links einbetten“ – fehlen sie, erscheint eine rote Meldung. Die neue Nachricht enthält das
aktuelle Roster, ihre ID ersetzt die alte. Dasselbe per Befehl: `[p]raid repost <id>` (eine noch vorhandene alte
Nachricht wird dabei gelöscht, damit es keine Doppelten gibt). Gelöschte Nachrichten erkennt der Cog automatisch
(Discord-Ereignis „Nachricht gelöscht“ bzw. beim nächsten Aktualisieren).

### Alte Events aufräumen

Im Reiter **Einstellungen → Aufräumen** (oder per `[p]raidset cleanup <tage>`) legst du fest, nach wie vielen Tagen abgeschlossene Events gelöscht werden (Standard **30 Tage**, `0` = nie). Das läuft automatisch etwa stündlich und direkt nach dem Speichern:

- gelöscht werden nur Events, deren Termin länger als N Tage vorbei ist und die bereits abgeschlossen sind;
- bei Wiederholungen bleibt das jeweils letzte Event der Serie immer erhalten – Serien laufen weiter;
- nur die gespeicherten Daten werden entfernt, die Nachricht in Discord bleibt stehen. Ein Klick auf ihre Buttons antwortet dann (nur für den Klickenden sichtbar) mit „Dieses Event existiert nicht mehr.“;
- die Teilnahme-Statistik bleibt erhalten.

## Anmeldung über die Website

Mitglieder können sich auch im Browser anmelden – über **„Mein Bereich“** von WebCore, Seite **Raids**
(`/me/raids`). Voraussetzungen:

1. Der Bot-Owner schaltet den Mitglieder-Bereich für den Server ein: *Verwaltung → Zugriff & Rollen* →
   Karte „Mitglieder-Bereich“ (oder im Server `[p]webcore portal on`).
2. Im Raidplaner unter *Einstellungen → Mitglieder-Bereich* ist **„Im Mitglieder-Bereich anzeigen“** an
   (Standard). Ausgeschaltet sehen Mitglieder nur einen Hinweis, Aktionen werden abgelehnt.

Was Mitglieder dort sehen und tun können:

- **Kommende Events als Karten** – nur Events in Kanälen, die sie in Discord **sehen dürfen**
  (Kanalrecht „Kanal ansehen“); abgeschlossene Events und andere Server erscheinen nicht.
  Je Karte: Titel, Spiel, Termin in der Server-Zeitzone plus „in 3 Tagen“, gekürzte Beschreibung,
  Belegung (Roster gesamt als Balken, je Rolle mit Limit, Bank/Spät/Vielleicht/Abwesend), Status
  *offen / voll / geschlossen / Anmeldeschluss vorbei*, der **eigene Status** hervorgehoben und ein
  Link **„In Discord öffnen“**. Wer noch nicht angemeldet ist, meldet sich direkt auf der Karte an.
- **Detailansicht** (`?event=<id>`) mit komplettem Roster (eigener Eintrag markiert) und allen Aktionen:
  **anmelden** bzw. **Spec wechseln** (eine Auswahl „Klasse & Spezialisierung“, Specs nach Klasse
  gruppiert, zuletzt gewählte Spec markiert – funktioniert ohne JavaScript), **Status** Bank / Spät /
  Vielleicht / Abwesend und **abmelden** (mit Rückfrage).
- Es gelten **exakt dieselben Regeln wie bei den Buttons** – beide nutzen dieselbe Funktion: geschlossen
  und Anmeldeschluss sperren Anmeldung und Status (Abmelden bleibt möglich), Gesamt- und Rollen-Limits,
  Spec-Gedächtnis. Zusätzlich wird die Auswahl gegen die Spiel-Vorlage geprüft. Die Meldung erscheint
  als Hinweis oben rechts, mit demselben Text wie in Discord, und die **Event-Nachricht in Discord wird
  sofort aktualisiert**.
- Geändert werden nur die eigenen Daten; fremde Server oder Events in nicht sichtbaren Kanälen werden
  serverseitig abgelehnt. WebCore begrenzt Mitglieder-Aktionen auf 30 pro Minute.

## Öffentliche API für Launcher & Website

Kommende Raids lassen sich ohne Login als JSON abrufen – z. B. für einen Launcher oder die Community-Website:

```
GET /api/public/raids/<server-id>?limit=10
```

- **Standardmäßig aus.** Pro Server im Dashboard unter **Launcher & Website** einschalten („Kommende Raids öffentlich
  abrufbar machen“). Dort stehen die fertige Adresse und eine Beispiel-Antwort.
- Ist die API aus oder der Server unbekannt, kommt immer dieselbe Antwort `404 {"error": "not_found"}`.
- Die Adresse ist **öffentlich**: ausgegeben werden nur kommende (nicht abgeschlossene) Events in Kanälen, die
  **@everyone sehen darf**, und **keine Nutzernamen oder -IDs** (auch nicht die Raidleitung) – nur die Belegung als Zahlen.
- `limit` 1–50 (Standard 10), sortiert nach Start. CORS `*`, bis zu 60 s zwischengespeichert, 60 Anfragen/Minute pro IP
  (WebCore). Das Dashboard muss dafür öffentlich erreichbar sein (Reverse-Proxy mit HTTPS, siehe WebCore-README).

```json
{
  "server": "Matters Community",
  "events": [
    {
      "id": "rh-0001",
      "title": "Mythic Undermine",
      "game": "WoW – Retail",
      "start": "2026-10-01T18:00:00Z",
      "deadline": null,
      "signups": 14,
      "max": 20,
      "full": false,
      "roles": {
        "tank":   {"label": "Tanks",  "emoji": "🛡️", "signups": 2, "max": 2},
        "healer": {"label": "Heiler", "emoji": "✚",  "signups": 3, "max": 4},
        "mdps":   {"label": "Nahkampf", "emoji": "⚔️", "signups": 5, "max": null},
        "rdps":   {"label": "Fernkampf", "emoji": "🏹", "signups": 4, "max": null}
      },
      "other": {"bench": 1, "late": 0, "tentative": 2, "absence": 0},
      "closed": false,
      "url": "https://discord.com/channels/123/456/789"
    }
  ]
}
```

`signups` = Plätze im Roster, `closed` = Anmeldung geschlossen oder Anmeldeschluss vorbei, `url` = Link zur
Event-Nachricht (ohne Nachricht: zum Kanal). Rollen-Beschriftungen folgen der Server-Sprache.

```bash
curl https://dash.example.org/api/public/raids/123456789012345678?limit=5
```

```js
const res = await fetch("https://dash.example.org/api/public/raids/123456789012345678?limit=5");
if (res.ok) {
  const { events } = await res.json();
  for (const e of events) {
    console.log(`${e.title} – ${new Date(e.start).toLocaleString("de-DE")} – ${e.signups}/${e.max ?? "∞"}`);
  }
}
```

## Spec-Icons

Eigene Icons je Spezialisierung werden als **Application-Emojis** an der Bot-Anwendung hinterlegt – botweit nutzbar, ohne Server-Emoji-Slots und ohne Einrichtung pro Server. Sie erscheinen im Spec-Auswahlmenü und in jeder Roster-Zeile (im Klassen-Dropdown wird das Icon der Standard-Spec als Anker genutzt).

Am einfachsten über das **Dashboard** (Abschnitt „Spec-Icons"): die Bilddateien hochladen, wobei der Dateiname dem Schema `klasse_spec` folgt (`krieger_furor.png`, `priester_heilig.png`, `daemonenjaeger_rachsucht.png`, …). Pro Datei max. 256 KB; der Gesamt-Upload sollte unter ca. 1 MB bleiben (sonst in kleineren Gruppen hochladen). Alternativ per Befehl `[p]raidset uploadicons` mit angehängten Dateien oder manuell mit `[p]raidset specicon <klasse> <spec> <emoji>`.

Voraussetzung für den Upload ist discord.py ≥ 2.4 (in aktuellen Red-Versionen enthalten); das Cog erkennt dies und weist sonst im Dashboard darauf hin. Da Klassen- und Spec-IDs spielübergreifend gleich sind, gilt ein gesetztes Icon für alle WoW-Vorlagen, in denen es diese Spezialisierung gibt.

Die offiziellen WoW-Spec-Icons sind Eigentum von Blizzard und werden nicht mitgeliefert – die Grafiken stellst du selbst bereit, das Cog bindet sie über den obigen Mechanismus ein.

## Eigene Spiele ergänzen

Ein Spiel ist in `games.py` ein reiner Datenblock (Rollen, Klassen, Specs, Farben). Ein weiteres Spiel hinzuzufügen heißt: einen Eintrag in `GAMES` ergänzen – die gesamte Anmelde-, Roster- und Embed-Logik liest nur diese Tabellen, neuer Code ist nicht nötig. Die Rolle einer Anmeldung ergibt sich immer aus der gewählten Spec.

## Datenspeicherung

Pro Event werden Anmeldungen (Discord-ID, Anzeigename, Klasse/Spec, Rolle, Status, Zeitpunkt) gespeichert, pro Nutzer die zuletzt gewählte Spec je Spiel/Klasse sowie eine Teilnahme-Statistik. Daten werden beim Löschen eines Events (auch durch das automatische Aufräumen), beim Entfernen des Cogs oder beim Verlassen des Servers entfernt.

Die öffentliche API (falls eingeschaltet) gibt keine personenbezogenen Daten aus – nur Event-Daten und Belegungszahlen.
