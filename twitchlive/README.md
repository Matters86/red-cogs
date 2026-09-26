# TwitchLive

Meldet in Discord, sobald beobachtete **Twitch-Kanäle live gehen** – z. B. dein eigener Kanal und
die deiner Community. Pro Server beliebig viele Streamer (max. 100), jeweils mit eigenem Zielkanal,
optionaler Ping-Rolle und eigener Nachricht.

Highlights:

- **Embed** mit Titel, Spiel, Zuschauern, aktuellem **Vorschaubild** (1280×720, mit Cache-Buster),
  Profilbild und Link-Button **„Zum Stream“**; alle ~10 Minuten aktualisiert (Zuschauer, Spiel, Bild).
- **Genau eine Meldung pro Stream** – die Stream-ID wird gespeichert, auch über Bot-Neustarts.
  Kurze Aussetzer (< 5 min, z. B. OBS-Reconnect) erzeugen keine zweite Meldung.
- **Nach Stream-Ende** wird die Meldung bearbeitet („war live · Dauer“, Spiele, max. Zuschauer)
  oder gelöscht – einstellbar.
- **Rollen-Ping** nur für genau die gewählte Rolle (`allowed_mentions`), nie `@everyone`/`@here`,
  auch wenn der Stream-Titel so etwas enthält.
- **Eigene Nachricht** mit Platzhaltern `{streamer}`, `{title}`, `{game}`, `{url}`, `{ping}`.
- **Live-Rolle** (optional): verknüpfte Mitglieder bekommen eine Rolle, solange sie live sind.
- **Twitch-Helix-API** mit App-Access-Token (Client-Credentials): Token wird gecacht und bei `401`
  erneuert; Abfrage alle 60 s, **gebündelt** (bis 100 Kanäle pro Anfrage) und über alle Server
  dedupliziert; Backoff bei Fehlern und Rate-Limit (`429`).
- **Komplett über das WebCore-Dashboard** bedienbar, inkl. Vorschau der Meldung.
- Mehrsprachig (Deutsch/Englisch), Standard Deutsch.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs twitchlive
[p]load twitchlive
```

Bot-Rechte im Zielkanal: **Nachrichten senden**, **Links einbetten**, **Nachrichtenverlauf lesen**
(zum Bearbeiten nach Stream-Ende). Für die Live-Rolle zusätzlich **Rollen verwalten** (die Rolle
muss unter der Bot-Rolle liegen). Nicht erwähnbare Ping-Rollen pingen nur, wenn der Bot
„@everyone, @here und alle Rollen erwähnen“ darf.

## Einrichtung (einmalig): Twitch-Zugangsdaten

1. Auf <https://dev.twitch.tv/console/apps> mit einem Twitch-Konto anmelden
   (Zwei-Faktor-Authentifizierung muss aktiv sein).
2. **Register Your Application**: Name frei wählbar, **OAuth Redirect URL** `http://localhost`
   (wird nicht benutzt), **Kategorie** „Chat Bot“ oder „Other“, **Client-Typ** „Confidential“.
3. Application öffnen (**Manage**), **Client-ID** kopieren und mit **New Secret** ein
   **Client-Secret** erzeugen.
4. Als Bot-Owner (am besten per DM an den Bot):
   ```
   [p]twitchset creds <client_id> <client_secret>
   ```
   Die Nachricht wird sofort gelöscht; der Bot holt testweise einen Token und meldet das Ergebnis.
   Das Secret wird nirgends angezeigt (auch nicht im Dashboard).

## Schnellstart

```
[p]twitchset channel #streams
[p]twitch add matters86 #streams @Stream-Ping
[p]twitch test matters86
```

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]twitch add <login> [#kanal] [@rolle]` | Streamer beobachten (Login oder `twitch.tv/…`-Link); ohne Kanal gilt der Standardkanal. Erneut aufrufen ändert Kanal/Rolle. | Admin / „Server verwalten“ |
| `[p]twitch remove <login>` | Streamer entfernen (eine laufende Meldung wird beendet). | Admin / „Server verwalten“ |
| `[p]twitch list` | Alle Streamer mit Status (🔴 live · 🟢 aktiv · ⚪ pausiert). | Admin / „Server verwalten“ |
| `[p]twitch test <login>` | Testmeldung in den Zielkanal posten (ohne echten Ping). | Admin / „Server verwalten“ |
| `[p]twitch channel <login> [#kanal]` | Zielkanal eines Streamers (ohne Kanal: Standardkanal). | Admin / „Server verwalten“ |
| `[p]twitch role <login> [@rolle]` | Ping-Rolle eines Streamers (ohne Rolle: kein Ping). | Admin / „Server verwalten“ |
| `[p]twitch message <login> [text]` | Eigene Nachricht (ohne Text: Standardtext). | Admin / „Server verwalten“ |
| `[p]twitch toggle <login>` | Meldungen pausieren/fortsetzen. | Admin / „Server verwalten“ |
| `[p]twitch link <@mitglied> <login>` | Mitglied mit Twitch-Kanal verknüpfen (Live-Rolle). | Admin / „Server verwalten“ |
| `[p]twitch unlink <@mitglied>` | Verknüpfung entfernen. | Admin / „Server verwalten“ |
| `[p]twitchset channel [#kanal]` | Standard-Zielkanal (ohne Angabe: entfernen). | Admin / „Server verwalten“ |
| `[p]twitchset message [text]` | Standardtext (ohne Text: eingebauter Text). | Admin / „Server verwalten“ |
| `[p]twitchset endaction <edit\|delete>` | Nach Stream-Ende bearbeiten („war live · Dauer“) oder löschen. | Admin / „Server verwalten“ |
| `[p]twitchset liverole [@rolle]` | Live-Rolle setzen (ohne Angabe: aus). | Admin / „Server verwalten“ |
| `[p]twitchset language <de\|en>` | Sprache der Meldungen und Antworten. | Admin / „Server verwalten“ |
| `[p]twitchset show` | Einstellungen anzeigen (ohne Secret). | Admin / „Server verwalten“ |
| `[p]twitchset creds <client_id> <client_secret>` | Twitch-Zugangsdaten setzen (Nachricht wird gelöscht, nur Textbefehl). | Bot-Owner |
| `[p]twitchset clearcreds` | Zugangsdaten löschen. | Bot-Owner |
| `[p]twitchset interval <60–600>` | Abfrage-Intervall in Sekunden (Standard 60). | Bot-Owner |

Alle Befehle außer `creds`/`clearcreds` gibt es auch als **Slash-Befehle** (`/twitch …`, `/twitchset …`).

## Platzhalter

| Platzhalter | Bedeutung |
|---|---|
| `{streamer}` | Anzeigename des Streamers |
| `{title}` | Stream-Titel |
| `{game}` | Spiel / Kategorie |
| `{url}` | Link zum Kanal (`https://www.twitch.tv/<login>`) |
| `{ping}` | Erwähnung der Ping-Rolle (fehlt der Platzhalter, wird der Ping vorangestellt) |

Standardtext: `{ping} **{streamer}** ist jetzt live auf Twitch! 🎮 {game}`. Vorlagen max. 1500
Zeichen; die fertige Nachricht wird auf Discords 2000 Zeichen gekürzt (Embed-Titel 256, Felder 1024).

## Dashboard

Mit geladenem `webcore` erscheint die Seite **Twitch-Live**:

- **Kennzahlen:** Streamer, gerade live, Twitch-API-Status (Verbunden / Zugangsdaten fehlen /
  ungültig / Rate-Limit / Störung), Meldungen heute.
- **Streamer:** Tabelle mit Status live (Zuschauer, Spiel, Dauer) / offline / pausiert, Bearbeiten,
  Testmeldung, Pausieren und Entfernen (mit Bestätigung).
- **Hinzufügen / Bearbeiten:** Login, Zielkanal, Ping-Rolle, eigene Nachricht, aktiv.
- **Vorschau:** so sieht die Meldung im Discord aus – live und nach Stream-Ende – plus
  „Testmeldung posten“.
- **Einstellungen:** Standardkanal, Standardtext, Verhalten bei Stream-Ende, Sprache.
- **Live-Rolle:** Rolle und Verknüpfungen Mitglied ↔ Twitch-Kanal.
- **Twitch-Zugang:** nur „gesetzt / nicht gesetzt“, API-Status, letzte/nächste Abfrage und die
  Einrichtungs-Anleitung. Bot-Owner können hier das Intervall ändern und eine Abfrage anstoßen.

Rechte: Die Seite folgt den WebCore-Rollen-Rechten (*Ansehen* = schreibgeschützt, *Bearbeiten* =
alle Einstellungen dieses Servers). Die Live-Rolle kann ein Team-Mitglied nur auf Rollen unter
seiner höchsten Rolle ohne Verwaltungsrechte setzen. Intervall und „Jetzt abfragen“ gelten botweit
und sind dem Bot-Owner vorbehalten. Zugangsdaten werden nur per Befehl gesetzt.

## Hinweise

- Neue Streams werden innerhalb etwa einer Minute gemeldet (Twitch-API selbst hat teils 1–2 min
  Verzögerung). Das Stream-Ende wird nach 5 Minuten ohne Stream erkannt.
- Löscht jemand die Live-Meldung von Hand, postet der Bot sie für diesen Stream nicht erneut.
- Es werden nur öffentliche Daten gelesen (App-Token, kein Login der Streamer nötig).
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Datenschutz: gespeichert werden die beobachteten Kanäle samt Einstellungen und – nur für die
  Live-Rolle – die Zuordnung Discord-Nutzer-ID ↔ Twitch-Login (wird bei einer Löschanfrage entfernt).
