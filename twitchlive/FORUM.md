# TwitchLive

Live-Benachrichtigungen für **Twitch**: Sobald ein beobachteter Kanal live geht, postet der Bot
eine Meldung mit Titel, Spiel, Zuschauern, Vorschaubild und Button „Zum Stream“ – genau einmal pro
Stream, optional mit Rollen-Ping und eigener Nachricht. Nach dem Stream wird die Meldung bearbeitet
(„war live · Dauer“) oder gelöscht. Optional Live-Rolle für verknüpfte Mitglieder. Komplett über das
Web-Dashboard bedienbar.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs twitchlive
[p]load twitchlive
```
Bot-Rechte im Zielkanal: **Nachrichten senden**, **Links einbetten**, **Nachrichtenverlauf lesen**
(Live-Rolle zusätzlich **Rollen verwalten**).

## Einrichtung (einmalig, Bot-Owner)
1. <https://dev.twitch.tv/console/apps> → **Register Your Application**
   (OAuth Redirect URL `http://localhost`, Kategorie „Chat Bot“ oder „Other“, Client-Typ „Confidential“).
2. Client-ID kopieren, **New Secret** erzeugen.
3. Per DM an den Bot: `[p]twitchset creds <client_id> <client_secret>` (Nachricht wird gelöscht).

## Schnellstart
```
[p]twitchset channel #streams
[p]twitch add matters86 #streams @Stream-Ping
[p]twitch test matters86
```

## Befehle – Streamer (Admin)
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]twitch add <login> [#kanal] [@rolle]` | Streamer beobachten / Kanal & Ping ändern. | Admin / „Server verwalten“ |
| `[p]twitch remove <login>` | Streamer entfernen. | Admin / „Server verwalten“ |
| `[p]twitch list` | Streamer mit Status auflisten. | Admin / „Server verwalten“ |
| `[p]twitch test <login>` | Testmeldung posten (ohne Ping). | Admin / „Server verwalten“ |
| `[p]twitch channel <login> [#kanal]` | Zielkanal (leer = Standardkanal). | Admin / „Server verwalten“ |
| `[p]twitch role <login> [@rolle]` | Ping-Rolle (leer = kein Ping). | Admin / „Server verwalten“ |
| `[p]twitch message <login> [text]` | Eigene Nachricht (leer = Standardtext). | Admin / „Server verwalten“ |
| `[p]twitch toggle <login>` | Pausieren/fortsetzen. | Admin / „Server verwalten“ |
| `[p]twitch link <@mitglied> <login>` | Mitglied ↔ Twitch verknüpfen (Live-Rolle). | Admin / „Server verwalten“ |
| `[p]twitch unlink <@mitglied>` | Verknüpfung entfernen. | Admin / „Server verwalten“ |

## Befehle – Einstellungen
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]twitchset channel [#kanal]` | Standard-Zielkanal. | Admin / „Server verwalten“ |
| `[p]twitchset message [text]` | Standardtext. | Admin / „Server verwalten“ |
| `[p]twitchset endaction <edit\|delete>` | Nach Stream-Ende bearbeiten oder löschen. | Admin / „Server verwalten“ |
| `[p]twitchset liverole [@rolle]` | Live-Rolle (leer = aus). | Admin / „Server verwalten“ |
| `[p]twitchset language <de\|en>` | Sprache. | Admin / „Server verwalten“ |
| `[p]twitchset show` | Einstellungen anzeigen. | Admin / „Server verwalten“ |
| `[p]twitchset creds <id> <secret>` | Twitch-Zugangsdaten (Nachricht wird gelöscht). | Bot-Owner |
| `[p]twitchset clearcreds` | Zugangsdaten löschen. | Bot-Owner |
| `[p]twitchset interval <60–600>` | Abfrage-Intervall (Standard 60 s). | Bot-Owner |

Gibt es auch als Slash-Befehle (`/twitch …`, `/twitchset …`) – außer `creds`/`clearcreds`.

**Platzhalter:** `{streamer}` `{title}` `{game}` `{url}` `{ping}`

## Dashboard
Seite **Twitch-Live**: Kennzahlen (Streamer, gerade live, API-Status), Streamer-Tabelle mit
live/offline, Bearbeiten, Testmeldung, Entfernen; Formular zum Hinzufügen; Vorschau der Meldung
(live und nach Stream-Ende); Einstellungen; Live-Rolle mit Verknüpfungen; Twitch-Zugang mit
Status („gesetzt/nicht gesetzt“) und Anleitung.

## Hinweise
- Meldung innerhalb ~1 Minute; Stream-Ende wird nach 5 Minuten ohne Stream erkannt.
- Genau eine Meldung pro Stream, auch nach einem Bot-Neustart.
- Ping nur für die gewählte Rolle – nie @everyone/@here.
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
