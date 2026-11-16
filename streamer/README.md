# Streamer

Eine Übersicht, in der nur **aktive Twitch- und YouTube-Streams** stehen: Der Bot kündigt
beobachtete Kanäle in einem Discord-Kanal mit Titel, Vorschaubild und Stream-Link an und
löscht seine Meldungen nach dem Stream wieder.

Optional muss der Titel einen bestimmten Text enthalten, etwa **DNP**. Dabei wird die
Groß-/Kleinschreibung ignoriert. `DNP`, `dnp` und `#DNP` passen zum Filter `DNP`.
Ein leeres Filterfeld zeigt alle Live-Streams der eingetragenen Kanäle. Der Filter ist ein
einfacher Teiltext, kein regulärer Ausdruck und keine Liste mehrerer Begriffe.

## Funktionen

- Twitch und YouTube gemeinsam in einem Zielkanal pro Server.
- Quellen als Twitch-Name/-Kanal-URL oder YouTube-@Handle/Kanal-ID/Kanal-URL hinzufügen.
- Ankündigungen werden aktualisiert und bei Stream-Ende entfernt; es gibt keine „war live“-Historie im Kanal.
- Der Titelfilter wird auch während eines Streams geprüft: Passt der Titel nicht mehr, verschwindet
  die Meldung. Passt er später wieder, kann der laufende Stream erneut angezeigt werden.
- Einzelne Quellen pausieren oder das Modul für einen Server ausschalten; die zugehörigen Meldungen werden bereinigt.
- Gespeicherte Nachrichten-IDs überstehen Neustarts. Der Bot löscht ausschließlich seine eigenen verwalteten Stream-Meldungen.
- API-Fehler gelten nicht als Offline-Nachweis. Verbindungs- und Löschprobleme werden im Dashboard angezeigt und erneut geprüft.
- Einfache WebCore-Seite **Streamer** mit Quellenliste, Ankündigungen, Zielkanal, Filter und geschützten Zugangsdaten.
- Keine automatischen Rollen-Pings, `@everyone`- oder `@here`-Pings durch Streamtitel.

## Installation

```text
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs streamer
[p]load streamer
```

`[p]` steht für euren Bot-Präfix. Für die Browserbedienung muss zusätzlich `webcore` geladen
und eingerichtet sein. Der Menüpunkt **Streamer** erscheint, sobald der Cog geladen ist.
`tzdata` wird als Abhängigkeit installiert, damit die tägliche YouTube-Quotagrenze auch unter
Windows in der richtigen Zeitzone berechnet wird.

Streamer ist unabhängig von `twitchlive`. Vorhandene TwitchLive-Einstellungen werden nicht
automatisch übernommen. Falls beide Cogs denselben Twitch-Kanal ankündigen, die entsprechende
Quelle in einem der beiden Cogs pausieren oder entfernen, damit keine doppelten Meldungen entstehen.

## Schnellstart im Dashboard

1. Als Bot-Owner **WebCore → Streamer → Zugang** öffnen und Twitch und/oder YouTube einrichten.
2. Unter **Einstellungen** den Discord-Zielkanal wählen. Optional bei **Titel muss enthalten**
   beispielsweise `DNP` eintragen. Speichern.
3. In der **Übersicht** Plattform und Streamer-Kanal auswählen und hinzufügen.
4. **Jetzt prüfen** verwenden. Bei einem passenden Live-Stream erscheint die Ankündigung automatisch.
5. Unter **WebCore → Zugriff & Rollen → Streamer** den zuständigen Teamrollen Rechte geben.

Der Bot braucht im Zielkanal **Kanal ansehen**, **Nachrichten senden**, **Links einbetten** und
**Nachrichtenverlauf lesen**. Für das Löschen seiner eigenen Ankündigungen benötigt er nicht
das Recht „Nachrichten verwalten“. Andere Nachrichten im Kanal bleiben erhalten.

## Twitch-Zugang

In der [Twitch Developer Console](https://dev.twitch.tv/console/apps) eine Anwendung registrieren.
Als OAuth-Redirect-URL kann für diese Server-Anbindung `http://localhost` verwendet werden.
Client-ID und Client-Secret im Reiter **Zugang** speichern. Der Bot nutzt den
[Client-Credentials-Ablauf](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#client-credentials-grant-flow)
für öffentliche Streamdaten; die einzelnen Streamer müssen sich nicht beim Bot anmelden.

Twitch-Streams werden normalerweise etwa jede Minute geprüft. API-Ausfälle oder Rate-Limits
können das Intervall verlängern.

## YouTube-Zugang und Prüfintervall

In einem [Google-Cloud-Projekt die YouTube Data API v3 aktivieren](https://console.cloud.google.com/apis/library/youtube.googleapis.com),
einen API-Key erstellen und auf diese API einschränken. Den Key im Reiter **Zugang** speichern.
Ein eigenes Projekt bzw. ein ausschließlich für diesen Bot verwendeter Key macht die
verfügbare Suchquote nachvollziehbar.

YouTube unterscheidet die Suche nach neuen Streams von der Prüfung bereits bekannter Streams:

- **Bekannte Streams:** ungefähr minütlich werden aktueller Titel und Live-Status geprüft.
- **Neue Streams:** Die Live-Suche erfolgt frühestens alle **30 Minuten** pro Kanal. Bei vielen
  beobachteten YouTube-Kanälen wird der Abstand automatisch größer, damit sich die Kanäle die
  verfügbare Tagesquote teilen. Eine neue Ankündigung kann deshalb verzögert erscheinen.
- Der Bot reserviert höchstens **80 Live-Suchen pro Tag** und speichert den Verbrauch über
  Neustarts hinweg. **Jetzt prüfen** umgeht diese Grenze nicht.
- Geplante Streams, gewöhnliche Videos und beendete Übertragungen werden nicht als live angekündigt.

Die derzeitige [YouTube-Quota-Dokumentation](https://developers.google.com/youtube/data/determine_quota_cost)
führt für `search.list` einen eigenen Tagesbereich mit standardmäßig 100 Aufrufen. Die
Tagesgrenze wird nach Pacific Time zurückgesetzt. Nutzen andere Anwendungen dasselbe Projekt,
steht dem Bot möglicherweise weniger Quote zur Verfügung. Ein ausgeschöpftes Kontingent wird
als API-Problem angezeigt und löst keine falsche Offline-Bereinigung aus.

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]streamer setup #kanal` | Zielkanal für Stream-Ankündigungen setzen. | Serververwaltung |
| `[p]streamer add twitch <name-oder-url>` | Twitch-Kanal hinzufügen. | Serververwaltung |
| `[p]streamer add youtube <@handle-kanal-id-oder-url>` | YouTube-Kanal hinzufügen. | Serververwaltung |
| `[p]streamer list` | Quellen mit ihren Schlüsseln auflisten. | Serververwaltung |
| `[p]streamer remove <quellenschlüssel>` | Quelle entfernen und ihre Meldungen bereinigen. | Serververwaltung |
| `[p]streamer filter [text]` | Titelfilter setzen; ohne Text ausschalten. | Serververwaltung |
| `[p]streamer check` | Aktuellen Status prüfen; YouTube-Suchgrenzen bleiben wirksam. | Serververwaltung |
| `[p]streamerset twitch <client-id> <client-secret>` | Twitch-Zugang botweit speichern. | Bot-Owner, ausschließlich per Direktnachricht |
| `[p]streamerset youtube <api-key>` | YouTube-Zugang botweit speichern. | Bot-Owner, ausschließlich per Direktnachricht |

Serververwaltung bedeutet Bot-Owner, Red-Admin oder das Discord-Recht **Server verwalten**.
Die normalen Streamer-Befehle sind auch als Slash-Befehle verfügbar. Zugangsdaten vorzugsweise
im Dashboard eintragen; die `streamerset`-Befehle sind Textbefehle für Direktnachrichten an den Bot.

Beispiel:

```text
[p]streamer setup #aktive-streams
[p]streamer filter DNP
[p]streamer add twitch deinkanal
[p]streamer add youtube @euerkanal
[p]streamer check
```

## Dashboard-Rechte

| Stufe | Erlaubte Bedienung |
|---|---|
| Ansehen | Quellen, Ankündigungen und Verbindungsstatus lesen. |
| Bedienen | Zusätzlich aktuell prüfen sowie einzelne Quellen pausieren/fortsetzen. |
| Bearbeiten | Zusätzlich Quellen hinzufügen/entfernen, Zielkanal und Filter ändern. |
| Bot-Owner | Zusätzlich botweite Twitch- und YouTube-Zugangsdaten speichern. |

Gespeicherte Zugangsdaten werden nicht im HTML ausgegeben. Die Passwortfelder sind immer leer
und werden nicht als Formularentwürfe gespeichert. Zum Ersetzen des Twitch-Zugangs Client-ID
und Client-Secret zusammen eintragen.

## Daten

Gespeichert werden pro Server die ausgewählten öffentlichen Twitch-/YouTube-Kanäle, Einstellungen,
öffentliche Live-Metadaten und die IDs der vom Bot verwalteten Discord-Nachrichten. Botweit werden
API-Zugangsdaten sowie der YouTube-Suchverbrauch gespeichert. Der Cog erstellt keine
Discord-Nutzerprofile und verknüpft keine Discord-Mitglieder mit Streaming-Konten.
