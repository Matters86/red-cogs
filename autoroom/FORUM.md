# AutoRoom (Autovoiceroom)

Automatische, temporäre Voicechannels: Wer einen Quell-Channel betritt, bekommt seinen
eigenen Raum – ist der Raum leer, verschwindet er wieder. Mit voller Selbstverwaltung,
mehreren Quellen pro Server und kompletter Konfiguration über das Web-Dashboard.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs autoroom
[p]load autoroom
```
Bot-Rechte: **Kanäle verwalten** und **Mitglieder verschieben**.

## Schnellstart
```
[p]autoroomset addsource "Voice erstellen"
```
Wer „Voice erstellen" betritt, bekommt ab sofort automatisch einen eigenen Voicechannel.

## Namensvorlagen
Platzhalter: `{user}` (Name), `{game}` (Spiel), `{num}` (nächste freie Nummer).
Standard: `🔊 {user}`

## Befehle – eigener Raum (in deinem AutoRoom)
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]autoroom settings` | Einstellungen deines Raums anzeigen. | im Raum |
| `[p]autoroom public` | Öffentlich (jeder sieht + joint). | Besitzer |
| `[p]autoroom locked` | Gesperrt (sichtbar, kein Beitritt). | Besitzer |
| `[p]autoroom private` | Privat (unsichtbar). | Besitzer |
| `[p]autoroom name <text>` | Umbenennen. | Besitzer |
| `[p]autoroom limit <zahl>` | Nutzerlimit (0 = unbegrenzt). | Besitzer |
| `[p]autoroom bitrate <kbps>` | Bitrate setzen. | Besitzer |
| `[p]autoroom allow <@user/@rolle>` | Zutritt erlauben. | Besitzer |
| `[p]autoroom deny <@user/@rolle>` | Zutritt verbieten (wirft raus). | Besitzer |
| `[p]autoroom claim` | Raum übernehmen, wenn Besitzer weg ist. | im Raum |
| `[p]autoroom transfer <@user>` | Raum übergeben. | Besitzer |

Gibt es auch als Slash-Befehle (`/autoroom …`).

## Befehle – Einrichtung (Admin)
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]autoroomset addsource <channel> [kategorie]` | Quelle anlegen. | Admin / „Server verwalten" |
| `[p]autoroomset removesource <channel>` | Quelle entfernen. | Admin / „Server verwalten" |
| `[p]autoroomset name <channel> <vorlage>` | Namensvorlage setzen. | Admin / „Server verwalten" |
| `[p]autoroomset limit <channel> <zahl>` | Standard-Nutzerlimit. | Admin / „Server verwalten" |
| `[p]autoroomset bitrate <channel> <kbps>` | Standard-Bitrate (0 = Standard). | Admin / „Server verwalten" |
| `[p]autoroomset visibility <channel> <public/locked/private>` | Standard-Sichtbarkeit. | Admin / „Server verwalten" |
| `[p]autoroomset textchannel <channel> <true/false>` | Textkanal pro Raum an/aus. | Admin / „Server verwalten" |
| `[p]autoroomset access <admin/mod> <true/false>` | Sehen Admin-/Mod-Rollen private Räume? | Admin / „Server verwalten" |
| `[p]autoroomset cleanup` | Verwaiste Räume aufräumen. | Admin / „Server verwalten" |
| `[p]autoroomset settings` | Alle Quellen anzeigen. | Admin / „Server verwalten" |

## Dashboard
Mit geladenem `webcore` erscheint der Tab **Autovoiceroom**: Live-Übersicht aller aktiven
Räume, Quellen pro Server anlegen/bearbeiten/entfernen und Zugriff der Admin-/Mod-Rollen
auf private Räume steuern – alles per Formular.

## Hinweise
- Admins (mit Administrator-Recht) sehen private Räume immer; `access` betrifft Rollen ohne dieses Recht.
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: `webcore` ist geladen und eingerichtet.
